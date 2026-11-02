"""用例依赖映射 —— 没有它就只能保守地跑全量。

支持 `<run>/coverage/test_dependencies.json`：
    {"schema": "test_dependencies_v1",
     "tests": {"alu_test": {"files": ["rtl/alu.sv"]},
               "apb_test": {"files": ["rtl/apb.sv", "rtl/dut.sv"]}}}
也接受 `{"tests": {"alu_test": ["rtl/alu.sv"]}}`。

**没有声明依赖的 test 一律视为受影响**（保守）—— 宁可多跑，不可漏跑。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

SCHEMA = "test_dependencies_v1"


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def load_dependency_map(run_root: str | Path) -> Dict[str, Set[str]]:
    doc = _read_json(Path(run_root) / "coverage" / "test_dependencies.json")
    tests = doc.get("tests")
    if not isinstance(tests, dict):
        return {}
    out: Dict[str, Set[str]] = {}
    for test, value in tests.items():
        files: Set[str] = set()
        if isinstance(value, dict):
            files = {str(f).replace("\\", "/") for f in (value.get("files") or [])}
        elif isinstance(value, (list, tuple)):
            files = {str(f).replace("\\", "/") for f in value}
        if files:
            out[str(test)] = files
    return out


def all_tests(run_root: str | Path) -> List[str]:
    """从 round_manifest 的 facts 收 test 名；没有就返回空列表。"""
    root = Path(run_root)
    doc = _read_json(root / "coverage" / "round_manifest.json")
    names: Set[str] = set()
    for rnd in doc.get("rounds") or []:
        for fact in rnd.get("facts") or []:
            name = str((fact or {}).get("test_name") or "")
            if name:
                names.add(name[5:] if name.startswith("test_") else name)
    return sorted(names)


def _matches(changed: str, declared: str) -> bool:
    """精确相对路径 / 通配 / 目录前缀 / 文件名 / 模块名都认。"""
    import fnmatch

    changed = changed.replace("\\", "/").lstrip("./")
    declared = declared.replace("\\", "/").lstrip("./")
    if changed == declared:
        return True
    if declared.endswith("/") and changed.startswith(declared):
        return True
    if any(ch in declared for ch in "*?[") and fnmatch.fnmatch(changed, declared):
        return True
    if Path(changed).name == Path(declared).name:
        return True
    stem = Path(declared).stem
    return bool(stem and Path(changed).stem == stem)


def derive_dependency_map(run_root: str | Path) -> Dict[str, Set[str]]:
    """从 `regression.yaml` 的 `file_pattern` 派生依赖（可选增强）。

    生成的 regression.yaml 目前通常没有 `file_pattern`；有就用，没有就返回空，
    让 `affected_tests` 走保守全量。**不猜**。
    """
    try:
        import yaml
    except Exception:                       # noqa: BLE001 可选依赖
        return {}
    root = Path(run_root)
    for rel in ("inputs/yaml/uvm/regression.yaml", "inputs/yaml/regression.yaml"):
        path = root / rel
        if not path.is_file():
            continue
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8", errors="replace"))
        except Exception:                   # noqa: BLE001
            continue
        out: Dict[str, Set[str]] = {}
        for test in (doc or {}).get("tests") or []:
            if not isinstance(test, dict) or not test.get("name"):
                continue
            patterns = {str(p).replace("\\", "/")
                        for p in (test.get("file_pattern") or [])}
            if patterns:
                out[str(test["name"])] = patterns
        if out:
            return out
    return {}


def affected_tests(changed_files: Iterable[str],
                   dep_map: Dict[str, Set[str]],
                   tests: Iterable[str]) -> Dict[str, Any]:
    changed = [str(c).replace("\\", "/") for c in changed_files]
    all_names = sorted({str(t) for t in tests})
    if not changed:
        return {"selected": all_names, "excluded": [], "undeclared": [],
                "confidence": "no_change",
                "reason": "没有 RTL 变更；保守起见仍跑全量"}
    if not dep_map:
        return {"selected": all_names, "excluded": [], "undeclared": all_names,
                "confidence": "conservative_all",
                "reason": "没有 coverage/test_dependencies.json，无法缩小范围"}

    # 变更文件不在任何声明里（新增文件 / 被清理的路径）→ 无法证明无关，跑全量。
    declared_all: Set[str] = set()
    for files in dep_map.values():
        declared_all.update(files)
    unknown = [c for c in changed
               if not any(_matches(c, d) for d in declared_all)]
    if unknown:
        return {"selected": all_names, "excluded": [], "undeclared": [],
                "confidence": "unknown_file",
                "reason": (f"{len(unknown)} 个变更文件不在任何依赖声明里，"
                           "无法证明无关，保守跑全量")}

    selected: List[str] = []
    excluded: List[str] = []
    undeclared: List[str] = []
    for test in all_names:
        declared = dep_map.get(test)
        if not declared:
            selected.append(test)
            undeclared.append(test)
            continue
        if any(_matches(c, d) for c in changed for d in declared):
            selected.append(test)
        else:
            excluded.append(test)
    return {
        "selected": selected,
        "excluded": excluded,
        "undeclared": undeclared,
        "confidence": "mapped",
        "reason": (f"{len(selected)}/{len(all_names)} 条用例受影响"
                   + (f"；{len(undeclared)} 条未声明依赖，按保守全跑" if undeclared else "")),
    }
