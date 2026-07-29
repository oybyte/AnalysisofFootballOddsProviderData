from __future__ import annotations

from pathlib import Path

import yaml


class AliasError(ValueError):
    pass


class AliasStore:
    def __init__(self, root: Path):
        self.root = root
        self.team_path = root / "data" / "team_aliases.yml"
        self.competition_path = root / "data" / "competition_aliases.yml"

    @staticmethod
    def _load(path: Path, key: str) -> dict:
        if not path.exists():
            return {key: {}}
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        data.setdefault(key, {})
        return data

    @staticmethod
    def _save(path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
            newline="\n",
        )

    @staticmethod
    def _assert_alias_unique(records: dict, aliases: list[str], record_id: str) -> None:
        wanted = {alias.casefold() for alias in aliases}
        for current_id, record in records.items():
            if current_id == record_id:
                continue
            existing = {str(x).casefold() for x in record.get("aliases", [])}
            existing.add(str(record.get("canonical_name", "")).casefold())
            overlap = wanted & existing
            if overlap:
                raise AliasError(f"别名已属于 {current_id}: {sorted(overlap)}")

    def add_team(self, team_id: str, name: str, aliases: list[str]) -> None:
        data = self._load(self.team_path, "teams")
        records = data["teams"]
        if team_id in records:
            raise AliasError(f"球队 ID 已存在：{team_id}")
        all_aliases = list(dict.fromkeys([name, *aliases]))
        self._assert_alias_unique(records, all_aliases, team_id)
        records[team_id] = {"canonical_name": name, "aliases": all_aliases}
        self._save(self.team_path, data)

    def add_competition(self, code: str, name: str, aliases: list[str]) -> None:
        data = self._load(self.competition_path, "competitions")
        records = data["competitions"]
        if code in records:
            raise AliasError(f"联赛代码已存在：{code}")
        all_aliases = list(dict.fromkeys([name, *aliases]))
        self._assert_alias_unique(records, all_aliases, code)
        records[code] = {"canonical_name": name, "aliases": all_aliases}
        self._save(self.competition_path, data)

    def has_team(self, team_id: str) -> bool:
        return team_id in self._load(self.team_path, "teams")["teams"]

    def has_competition(self, code: str) -> bool:
        return code in self._load(self.competition_path, "competitions")["competitions"]

    def validate_uniqueness(self) -> list[str]:
        errors: list[str] = []
        for path, key in ((self.team_path, "teams"), (self.competition_path, "competitions")):
            records = self._load(path, key)[key]
            owners: dict[str, str] = {}
            for record_id, record in records.items():
                names = [record.get("canonical_name", ""), *record.get("aliases", [])]
                for name in names:
                    folded = str(name).casefold()
                    if folded in owners and owners[folded] != record_id:
                        errors.append(f"{path.name}: {name} 同时属于 {owners[folded]} 和 {record_id}")
                    owners[folded] = record_id
        return errors

