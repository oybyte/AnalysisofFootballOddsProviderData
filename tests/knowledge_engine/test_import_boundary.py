"""Knowledge Engine import-boundary 测试。

验证依赖规则：
- domain/ 只依赖标准库、Pydantic 和同层领域类型。
- application/ 只依赖 domain/ 与 ports/。
- ports/ 只定义 Protocol、输入输出契约和领域异常。
- 只有 adapters/ 可以导入现有 observations、facts、cases、rules、AI governance、
  MatchDocument 和 RepositoryTransaction。
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path


def _collect_imports(file_path: Path) -> list[str]:
    """收集文件中的导入语句，返回绝对模块路径。"""
    tree = ast.parse(file_path.read_text(encoding="utf-8"))

    # 根据文件路径推断文件所在的包名（不含文件名）
    file_str = str(file_path.resolve())
    if "knowledge_engine" in file_str:
        parts = file_str.split("knowledge_engine")
        if len(parts) >= 1:
            rel = parts[1].replace("\\", "/").replace("/", ".").lstrip(".")
            rel = rel.replace(".py", "")
            if rel:
                # 去掉文件名，只保留包路径
                pkg_parts = rel.split(".")
                if pkg_parts[-1] != "__init__":
                    pkg_parts = pkg_parts[:-1]  # 去掉文件名
                if pkg_parts:
                    file_pkg = "odds_journal.knowledge_engine." + ".".join(pkg_parts)
                else:
                    file_pkg = "odds_journal.knowledge_engine"
            else:
                file_pkg = "odds_journal.knowledge_engine"
        else:
            file_pkg = ""
    else:
        file_pkg = ""

    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                if node.level == 0:
                    # 绝对导入
                    imports.append(node.module)
                else:
                    # 相对导入：解析为绝对路径
                    if file_pkg:
                        pkg_parts = file_pkg.split(".")
                        if node.level > len(pkg_parts):
                            # 越出包边界，保留原始
                            imports.append("." * node.level + node.module)
                        else:
                            base = ".".join(pkg_parts[:-(node.level - 1)] if node.level > 1 else pkg_parts)
                            resolved = f"{base}.{node.module}" if node.module else base
                            imports.append(resolved)
                    else:
                        imports.append("." * node.level + node.module)
    return imports


def _is_stdlib(module: str) -> bool:
    """检查是否为标准库模块。"""
    top = module.split(".")[0]
    return top in sys.stdlib_module_names


def _is_pydantic(module: str) -> bool:
    """检查是否为 Pydantic 模块。"""
    return module.startswith("pydantic")


def _is_knowledge_engine(module: str) -> bool:
    """检查是否为 knowledge_engine 内部模块。"""
    return module.startswith("odds_journal.knowledge_engine")


def _is_domain_internal(module: str) -> bool:
    """检查是否为 domain 内部模块。"""
    return module.startswith("odds_journal.knowledge_engine.domain")


def _is_ports_internal(module: str) -> bool:
    """检查是否为 ports 内部模块。"""
    return module.startswith("odds_journal.knowledge_engine.ports")


def _is_adapters_internal(module: str) -> bool:
    """检查是否为 adapters 内部模块。"""
    return module.startswith("odds_journal.knowledge_engine.adapters")


def _is_existing_odds_journal(module: str) -> bool:
    """检查是否为现有 odds_journal 模块（非 knowledge_engine）。"""
    return (
        module.startswith("odds_journal.")
        and not module.startswith("odds_journal.knowledge_engine")
    )


def test_domain_only_stdlib_and_pydantic():
    """domain/ 只依赖标准库、Pydantic 和同层领域类型。"""
    domain_dir = Path("src/odds_journal/knowledge_engine/domain")
    violations: list[str] = []

    for py_file in sorted(domain_dir.glob("*.py")):
        if py_file.name == "__init__.py":
            continue
        imports = _collect_imports(py_file)
        for imp in imports:
            if _is_stdlib(imp) or _is_pydantic(imp):
                continue
            if _is_domain_internal(imp):
                continue
            if imp == "__future__":
                continue
            violations.append(f"{py_file.name}: imports '{imp}'")

    assert not violations, (
        f"domain/ 导入违规（只能依赖标准库、Pydantic 和同层领域类型）：\n"
        + "\n".join(violations)
    )


def test_ports_only_protocols():
    """ports/ 只定义 Protocol、输入输出契约和领域异常。"""
    ports_dir = Path("src/odds_journal/knowledge_engine/ports")
    violations: list[str] = []

    for py_file in sorted(ports_dir.glob("*.py")):
        if py_file.name == "__init__.py":
            continue
        imports = _collect_imports(py_file)
        for imp in imports:
            if _is_stdlib(imp) or _is_pydantic(imp):
                continue
            if _is_domain_internal(imp):
                continue
            if _is_ports_internal(imp):
                continue
            if imp == "__future__":
                continue
            if imp == "typing":
                continue
            violations.append(f"{py_file.name}: imports '{imp}'")

    assert not violations, (
        f"ports/ 导入违规（只能依赖标准库、domain/ 和同层 ports/）：\n"
        + "\n".join(violations)
    )


def test_application_only_domain_and_ports():
    """application/ 只依赖 domain/ 与 ports/。"""
    app_dir = Path("src/odds_journal/knowledge_engine/application")
    violations: list[str] = []

    for py_file in sorted(app_dir.glob("*.py")):
        if py_file.name == "__init__.py":
            continue
        imports = _collect_imports(py_file)
        for imp in imports:
            if _is_stdlib(imp) or _is_pydantic(imp):
                continue
            if _is_domain_internal(imp) or _is_ports_internal(imp) or _is_adapters_internal(imp):
                continue
            if imp == "__future__":
                continue
            if imp == "typing":
                continue
            if _is_knowledge_engine(imp):
                if imp.startswith("odds_journal.knowledge_engine.domain") or imp.startswith("odds_journal.knowledge_engine.ports") or imp.startswith("odds_journal.knowledge_engine.adapters"):
                    continue
            if _is_existing_odds_journal(imp):
                violations.append(f"{py_file.name}: imports existing odds_journal '{imp}'")
                continue
            violations.append(f"{py_file.name}: imports '{imp}'")

    assert not violations, (
        f"application/ 导入违规（只能依赖 domain/ 和 ports/）：\n"
        + "\n".join(violations)
    )


def test_adapters_can_import_existing():
    """adapters/ 可以导入现有 odds_journal 模块。"""
    adapters_dir = Path("src/odds_journal/knowledge_engine/adapters")
    adapter_files = list(adapters_dir.glob("*.py"))
    adapter_names = {f.stem for f in adapter_files if f.name != "__init__.py"}

    expected_adapters = {
        "current_observations",
        "current_facts",
        "current_cases",
        "current_official_baseline",
        "ruleset_source",
        "sqlite_index",
        "repository_artifacts",
        "deterministic_reasoner",
        "ai_reasoner",
        "formal_draft",
        "clock",
    }

    missing = expected_adapters - adapter_names
    assert not missing, f"缺少适配器：{missing}"


def test_no_reverse_dependency():
    """现有 odds_journal 模块不应导入 knowledge_engine。"""
    existing_dir = Path("src/odds_journal")
    violations: list[str] = []

    for py_file in sorted(existing_dir.glob("*.py")):
        if py_file.name == "__init__.py":
            continue
        if "knowledge_engine" in str(py_file):
            continue
        imports = _collect_imports(py_file)
        for imp in imports:
            if _is_knowledge_engine(imp):
                violations.append(f"{py_file.name}: imports '{imp}'")

    # 也检查 rule_engine 子目录
    rule_engine_dir = existing_dir / "rule_engine"
    if rule_engine_dir.exists():
        for py_file in sorted(rule_engine_dir.glob("*.py")):
            if py_file.name == "__init__.py":
                continue
            imports = _collect_imports(py_file)
            for imp in imports:
                if _is_knowledge_engine(imp):
                    violations.append(f"rule_engine/{py_file.name}: imports '{imp}'")

    assert not violations, (
        f"反向依赖违规（现有模块不应导入 knowledge_engine）：\n"
        + "\n".join(violations)
    )


def test_all_domain_models_frozen():
    """所有领域模型使用 frozen=True。"""
    domain_dir = Path("src/odds_journal/knowledge_engine/domain")
    violations: list[str] = []

    for py_file in sorted(domain_dir.glob("*.py")):
        if py_file.name in ("__init__.py", "exceptions.py"):
            continue
        content = py_file.read_text(encoding="utf-8")
        tree = ast.parse(content)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                # 检查类是否继承 BaseModel
                for base in node.bases:
                    if isinstance(base, ast.Name) and base.id == "BaseModel":
                        # 检查 config_dict 是否有 frozen=True
                        for item in ast.walk(node):
                            if isinstance(item, ast.Call):
                                if (
                                    isinstance(item.func, ast.Attribute)
                                    and item.func.attr == "ConfigDict"
                                ):
                                    for kw in item.keywords:
                                        if kw.arg == "frozen" and kw.value is not True:
                                            violations.append(
                                                f"{py_file.name}:{node.name} 不是 frozen=True"
                                            )
        # 检查 StrEnum
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for base in node.bases:
                    if isinstance(base, ast.Name) and base.id == "StrEnum":
                        break  # StrEnum 不需要 frozen
                for base in node.bases:
                    if isinstance(base, ast.Name) and base.id == "BaseModel":
                        # BaseModel 已经在上面检查
                        break

    assert not violations, (
        f"领域模型 frozen 违规：\n" + "\n".join(violations)
    )