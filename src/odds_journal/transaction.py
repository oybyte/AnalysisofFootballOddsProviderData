from __future__ import annotations

import json
import os
import shutil
import uuid
from pathlib import Path
from typing import Any


TRANSACTION_SCHEMA_VERSION = 2


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _process_is_running(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _resolve_inside(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"事务日志路径越出项目根目录：{relative}") from exc
    return path


def _restore_from_journal(root: Path, transaction_directory: Path, journal: dict[str, Any]) -> None:
    backups = transaction_directory / "before"
    for item in journal.get("files", []):
        relative = str(item["path"])
        path = _resolve_inside(root, relative)
        backup = backups / Path(relative)
        if bool(item.get("existed")):
            if not backup.is_file():
                raise ValueError(f"事务备份缺失：{backup}")
            temporary = path.with_suffix(path.suffix + ".rollback")
            temporary.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(backup, temporary)
            temporary.replace(path)
        elif path.exists():
            if not path.is_file():
                raise ValueError(f"事务目标不是文件：{path}")
            path.unlink()

    for item in journal.get("directories", []):
        directory = _resolve_inside(root, str(item["path"]))
        existing = {
            _resolve_inside(root, str(relative)) for relative in item.get("existing_files", [])
        }
        if directory.exists():
            for path in sorted(
                (candidate.resolve() for candidate in directory.glob("**/*") if candidate.is_file()),
                reverse=True,
            ):
                if path not in existing:
                    path.unlink()
            for child in sorted(
                (candidate for candidate in directory.glob("**/*") if candidate.is_dir()),
                key=lambda candidate: len(candidate.parts),
                reverse=True,
            ):
                if not any(child.iterdir()):
                    child.rmdir()
            if not bool(item.get("existed")) and not any(directory.iterdir()):
                directory.rmdir()


def recover_pending_transactions(root: Path, *, force: bool = False) -> list[str]:
    """Recover interrupted writes before another CLI command accesses the repository."""
    root = root.resolve()
    base = root / ".odds-journal"
    lock = base / "write.lock"
    transactions = base / "transactions"
    if not lock.exists() and not transactions.exists():
        return []

    lock_payload: dict[str, Any] = {}
    if lock.exists():
        try:
            lock_payload = json.loads(lock.read_text(encoding="utf-8") or "{}")
        except (json.JSONDecodeError, OSError):
            lock_payload = {}
        if not force and _process_is_running(lock_payload.get("pid")):
            raise ValueError(
                f"另一个写入事务仍在运行：pid={lock_payload['pid']} operation={lock_payload.get('operation', '-') }"
            )

    recovered: list[str] = []
    if transactions.exists():
        for directory in sorted(path for path in transactions.iterdir() if path.is_dir()):
            journal_path = directory / "transaction.json"
            if not journal_path.exists():
                shutil.rmtree(directory)
                continue
            try:
                journal = json.loads(journal_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                raise ValueError(f"事务日志无法读取，需保留现场检查：{journal_path}") from exc
            if journal.get("schema_version") != TRANSACTION_SCHEMA_VERSION:
                raise ValueError(f"不支持的事务日志版本：{journal_path}")
            state = journal.get("state")
            if state == "prepared":
                _restore_from_journal(root, directory, journal)
                recovered.append(str(journal.get("operation", directory.name)))
            elif state != "committed":
                raise ValueError(f"未知事务状态 {state!r}：{journal_path}")
            shutil.rmtree(directory)

    if lock.exists():
        lock.unlink()
    return recovered


class RepositoryTransaction:
    """Recover a bounded multi-file mutation after exceptions or process interruption."""

    def __init__(self, root: Path, *, files: list[Path], directories: list[Path], operation: str):
        self.root = root.resolve()
        self.files = [path.resolve() for path in files]
        self.directories = [path.resolve() for path in directories]
        self.operation = operation
        self.base = self.root / ".odds-journal"
        self.lock = self.base / "write.lock"
        self.transaction_id = uuid.uuid4().hex
        self.directory = self.base / "transactions" / self.transaction_id
        self.backups = self.directory / "before"
        self.journal_path = self.directory / "transaction.json"
        self.journal: dict[str, Any] = {}
        self.committed = False

    def _relative(self, path: Path) -> Path:
        try:
            return path.relative_to(self.root)
        except ValueError as exc:
            raise ValueError(f"事务路径越出项目根目录：{path}") from exc

    def __enter__(self) -> "RepositoryTransaction":
        self.base.mkdir(parents=True, exist_ok=True)
        lock_payload = {
            "schema_version": 1,
            "transaction_id": self.transaction_id,
            "operation": self.operation,
            "pid": os.getpid(),
        }
        try:
            descriptor = os.open(self.lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise ValueError(f"另一个写入事务尚未完成：{self.lock}") from exc
        try:
            os.write(descriptor, (json.dumps(lock_payload, ensure_ascii=False) + "\n").encode("utf-8"))
        finally:
            os.close(descriptor)

        try:
            self._prepare()
        except Exception:
            if self.directory.exists():
                shutil.rmtree(self.directory)
            if self.lock.exists():
                self.lock.unlink()
            raise
        return self

    def _prepare(self) -> None:
        self.backups.mkdir(parents=True)
        file_records = []
        for path in self.files:
            relative = self._relative(path)
            existed = path.is_file()
            file_records.append({"path": relative.as_posix(), "existed": existed})
            if existed:
                target = self.backups / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)

        directory_records = []
        for directory in self.directories:
            relative = self._relative(directory)
            existed = directory.is_dir()
            existing_files = sorted(
                item.resolve().relative_to(self.root).as_posix()
                for item in directory.glob("**/*")
                if item.is_file()
            ) if existed else []
            directory_records.append({
                "path": relative.as_posix(),
                "existed": existed,
                "existing_files": existing_files,
            })

        self.journal = {
            "schema_version": TRANSACTION_SCHEMA_VERSION,
            "transaction_id": self.transaction_id,
            "operation": self.operation,
            "pid": os.getpid(),
            "state": "prepared",
            "files": file_records,
            "directories": directory_records,
        }
        _atomic_json(self.journal_path, self.journal)

    def commit(self) -> None:
        self.journal["state"] = "committed"
        _atomic_json(self.journal_path, self.journal)
        self.committed = True

    def _restore(self) -> None:
        _restore_from_journal(self.root, self.directory, self.journal)

    def __exit__(self, exc_type, exc, traceback) -> bool:
        try:
            if exc_type is not None or not self.committed:
                self._restore()
        finally:
            if self.directory.exists():
                shutil.rmtree(self.directory)
            if self.lock.exists():
                self.lock.unlink()
        return False
