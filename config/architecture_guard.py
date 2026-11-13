"""架构复杂度预算（Architecture Guard 2.0）。

四个门禁：

  · **Size**：> 2000 失败；> 1500 必须登记；已登记文件只能变小。
  · **Complexity**：圈复杂度 > 20 必须登记；已登记只能下降。
  · **Dependency**：禁止逆向依赖 / 未登记模块 / 动态 import 绕行。
  · **Debt**：预算不是豁免，是**只能变小的债务**。缩小后必须同步收紧。

规则文档：`docs/architecture/ARCHITECTURE_GUARD_PRINCIPLES.md`。

用法：
    python -m config.architecture_guard                 # 检查
    python -m config.architecture_guard --json          # 机器读
    python -m config.architecture_guard --reduce-debt   # 只降不升，写 history
    python -m config.architecture_guard --approve-debt \
        --key <file|file::Class.func> --reason ... --approver ...
"""
from __future__ import annotations

import argparse
import ast
import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

import yaml

ROOT = Path(__file__).resolve().parent.parent
BUDGET_FILE = Path(__file__).resolve().parent / "architecture_budget.yaml"
BASELINE_FILE = Path(__file__).resolve().parent / "complexity_baseline.json"
HISTORY_FILE = Path(__file__).resolve().parent / "architecture_debt_history.jsonl"

EXCLUDED_PARTS = {"__pycache__", "tests"}
DEBT_SLACK_RATIO = 0.05
DEBT_SLACK_MAX = 50
DEBT_SLACK_MIN = 10
COMPLEXITY_THRESHOLD = 20

#: 函数内部的延迟 import 只对这几条边界做硬检查（Engine/Generation 不得依赖 Agent）。
_LAZY_FORBIDDEN = {("engine", "agents"), ("generation", "agents")}


class GuardConfigError(RuntimeError):
    """预算文件损坏 / 参数不合法 —— CLI 以 exit 2 退出。"""


def _iter_py(root: Path = ROOT) -> Iterator[Path]:
    base = Path(root) / "src"
    if not base.is_dir():
        return
    for path in sorted(base.rglob("*.py")):
        if EXCLUDED_PARTS & set(path.relative_to(base).parts):
            continue
        yield path


def line_counts(root: Path = ROOT) -> Dict[str, int]:
    root = Path(root)
    out: Dict[str, int] = {}
    for path in _iter_py(root):
        try:
            with path.open(encoding="utf-8", errors="replace") as fh:
                out[path.relative_to(root).as_posix()] = sum(1 for _ in fh)
        except OSError:
            continue
    return out


def load_budget(path: Path = BUDGET_FILE) -> Dict[str, Any]:
    path = Path(path)
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise GuardConfigError(f"budget 文件不可读: {path}: {exc}") from exc
    if not isinstance(doc, dict):
        raise GuardConfigError(f"budget 文件格式错误: {path}")
    line = doc.get("line_budget") or {}
    return {
        "warn": int(line.get("warn", 1500)),
        "error": int(line.get("error", 2000)),
        "watched": doc.get("watched") or {},
    }


def _slack(registered: int) -> int:
    return max(DEBT_SLACK_MIN,
               min(DEBT_SLACK_MAX, math.ceil(registered * DEBT_SLACK_RATIO)))


def line_violations(root: Path = ROOT, budget: Dict[str, Any] = None,
                    budget_path: Path = BUDGET_FILE) -> List[Dict[str, Any]]:
    budget = budget or load_budget(budget_path)
    warn, error = budget["warn"], budget["error"]
    watched = budget["watched"]
    counts = line_counts(root)
    issues: List[Dict[str, Any]] = []
    for rel, lines in counts.items():
        entry = watched.get(rel)
        if lines > error:
            issues.append({"type": "lines_over_error", "path": rel,
                           "actual": lines, "limit": error})
        if entry:
            registered = int(entry.get("registered", error))
            if lines > registered:
                issues.append({"type": "watched_file_grew", "path": rel,
                               "actual": lines, "registered": registered})
            elif registered - lines > _slack(registered):
                issues.append({"type": "budget_not_tightened", "path": rel,
                               "actual": lines, "registered": registered,
                               "detail": "文件已缩小，必须 --reduce-debt 收紧"})
        elif lines > warn:
            issues.append({"type": "lines_unwatched", "path": rel,
                           "actual": lines, "warn": warn})
    for rel, entry in watched.items():
        if not Path(root, rel).is_file():
            issues.append({"type": "missing_watched_file", "path": rel})
        for key in ("reason", "plan", "registered"):
            if key not in entry:
                issues.append({"type": "watched_missing_field", "path": rel,
                               "field": key})
    return issues


_DECISIONS = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.IfExp,
              ast.ExceptHandler)


def _cyclomatic(func: ast.AST) -> int:
    score = 1

    def visit(node: ast.AST) -> None:
        nonlocal score
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef,
                                  ast.Lambda, ast.ClassDef)):
                continue
            if isinstance(child, _DECISIONS):
                score += 1
            elif isinstance(child, ast.BoolOp):
                score += len(child.values) - 1
            elif isinstance(child, ast.comprehension) and child.ifs:
                score += len(child.ifs)
            visit(child)

    visit(func)
    return score


def _walk_scope(node: ast.AST, scope: Tuple[str, ...], rel: str,
                out: Dict[str, int]) -> None:
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            qual = ".".join(scope + (child.name,))
            out[f"{rel}::{qual}"] = _cyclomatic(child)
            _walk_scope(child, scope + (child.name,), rel, out)
        elif isinstance(child, ast.ClassDef):
            _walk_scope(child, scope + (child.name,), rel, out)
        else:
            _walk_scope(child, scope, rel, out)


def complexity_map(root: Path = ROOT) -> Dict[str, int]:
    root = Path(root)
    out: Dict[str, int] = {}
    for path in _iter_py(root):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError):
            continue
        _walk_scope(tree, (), path.relative_to(root).as_posix(), out)
    return out


def load_baseline(path: Path = BASELINE_FILE) -> Dict[str, int]:
    path = Path(path)
    if not path.is_file():
        return {}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise GuardConfigError(f"baseline 文件损坏: {path}: {exc}") from exc
    if not isinstance(doc, dict):
        raise GuardConfigError(f"baseline 文件格式错误: {path}")
    return {str(k): int(v) for k, v in doc.items()}


def complexity_violations(root: Path = ROOT, threshold: int = COMPLEXITY_THRESHOLD,
                          baseline: Dict[str, int] = None,
                          baseline_path: Path = BASELINE_FILE
                          ) -> List[Dict[str, Any]]:
    baseline = baseline if baseline is not None else load_baseline(baseline_path)
    current = complexity_map(root)
    issues: List[Dict[str, Any]] = []
    for key, value in current.items():
        if value <= threshold:
            if key in baseline:
                issues.append({"type": "debt_cleared", "function": key,
                               "actual": value, "threshold": threshold,
                               "detail": "已低于阈值，必须 --reduce-debt 删除"})
            continue
        known = baseline.get(key)
        if known is None:
            issues.append({"type": "complexity_new", "function": key,
                           "actual": value, "limit": threshold,
                           "detail": "新增债务需 --approve-debt"})
        elif value > known:
            issues.append({"type": "complexity_grew", "function": key,
                           "actual": value, "baseline": known})
        elif value < known:
            issues.append({"type": "debt_repaid", "function": key,
                           "actual": value, "baseline": known,
                           "detail": "复杂度下降，必须 --reduce-debt 收紧"})
    for key in baseline:
        if key not in current:
            issues.append({"type": "baseline_stale", "function": key,
                           "detail": "函数已不存在，必须 --reduce-debt 删除"})
    return issues


_ZONES = (
    ("src/core/", "core"),
    ("src/layers/l1_infrastructure/", "l1"),
    ("src/layers/l2_orchestration/", "l2"),
    ("src/layers/l3_decision/", "l3"),
    ("src/knowledge/", "l4"),
    ("src/experience/", "l5"),
    ("src/tools/", "tools"),
    ("src/workspace/", "workspace"),
    ("src/runtime/", "runtime"),
    ("src/utils/", "core"),
    ("src/interfaces/cli/", "iface"),
    ("src/workbench/", "iface"),
    ("src/modes/", "iface"),
    ("src/generation/", "generation"),
    ("src/agent/specialists/", "agents"),
    ("src/engine/orchestration/", "orchestration"),
    ("src/engine/front/", "engine"),
    ("src/engine/verify/", "engine"),
    ("src/engine/ops/", "engine"),
    ("src/engine/coverage/", "engine"),
    ("src/engine/audit/", "engine"),
    ("src/engine/diagnostics/", "engine"),
    ("src/engine/", "iface"),
    ("src/agent/", "iface"),
    ("src/ir/", "ir"),
    ("src/interfaces/", "iface"),
)

_ALLOWED = {
    "core": set(),
    "l1": {"core", "tools"},
    "l3": {"l1", "l4", "core", "tools", "ir"},
    "l4": {"l1", "core", "tools"},
    "l5": {"l1", "l3", "l4", "core", "tools"},
    "l2": {"l1", "l3", "l4", "l5", "core", "agents", "tools", "ir", "runtime",
           "engine", "generation", "orchestration"},
    "stages": {"l1", "l2", "l3", "l4", "l5", "core", "agents", "tools", "ir",
               "runtime", "engine", "generation"},
    # 确定性 Engine：不 import Generation / Agent。
    "engine": {"core", "l1", "l2", "l3", "l4", "l5", "tools", "ir", "runtime",
               "workspace"},
    "orchestration": {"core", "l1", "l2", "l3", "l4", "l5", "tools", "ir",
                      "runtime", "workspace", "engine", "generation", "agents",
                      "iface"},
    "generation": {"core", "l1", "l2", "l3", "l4", "l5", "tools", "ir",
                   "runtime", "workspace", "engine"},
    "tools": {"core", "l1"},
    "agents": {"l1", "l2", "l3", "l4", "l5", "core", "tools", "ir", "runtime",
               "engine", "generation", "orchestration", "iface"},
    "runtime": {"core", "l1", "tools"},
    "workspace": {"core", "l1", "l2", "l3", "l4", "l5", "tools", "ir",
                  "runtime"},
    "ir": {"core", "l1", "l2", "l3", "l4", "l5", "workspace", "tools",
           "runtime"},
    "iface": {"core", "l1", "l2", "l3", "l4", "l5", "stages", "agents",
              "workspace", "ir", "tools", "runtime", "engine", "generation",
              "orchestration"},
}

#: 已知的过渡债务：engine → l2 的 ExecutorBase 尚未迁到 engine/executors。
#: 只允许具体文件，不允许整层放开。
_DEPENDENCY_DEBT = {
    "src/engine/front/main.py": {"l2"},
    "src/engine/ops/main.py": {"l2"},
    "src/engine/coverage/main.py": {"l2"},
    "src/engine/audit/main.py": {"l2"},
    "src/engine/audit/helpers.py": {"l2"},
}


def _zone_of(rel: str) -> str:
    for prefix, zone in _ZONES:
        if rel.startswith(prefix):
            return zone
    return ""


def _module_name(rel: str) -> str:
    return rel[:-3].replace("/", ".") if rel.endswith(".py") else rel


def _resolve_relative(rel: str, module: Optional[str], level: int) -> str:
    current = _module_name(rel)
    parts = current.split(".")
    if parts and not rel.endswith("__init__.py"):
        parts = parts[:-1]
    up = max(0, level - 1)
    base = parts[:len(parts) - up] if up else parts
    if module:
        base = base + module.split(".")
    return ".".join(base)


def _target_zone(module: str, root: Path) -> Tuple[str, Optional[str]]:
    if not module.startswith("src."):
        return "", None
    rel = module.replace(".", "/")
    zone = _zone_of(rel + "/")
    if zone:
        return zone, None
    top = rel.split("/")[0]
    if (Path(root) / "src" / top).is_dir():
        return "", "unregistered_zone"
    return "", None


def _imports(tree: ast.AST, rel: str) -> List[Tuple[int, str, bool]]:
    """[(行号, 绝对模块名, 是否函数内延迟 import)]。"""
    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.depth = 0
            self.items: List[Tuple[int, str, bool]] = []

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self.depth += 1
            self.generic_visit(node)
            self.depth -= 1

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_Import(self, node: ast.Import) -> None:
            for alias in node.names:
                self.items.append((node.lineno, alias.name, self.depth > 0))

        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
            if node.level:
                mod = _resolve_relative(rel, node.module, node.level)
            else:
                mod = node.module or ""
            if mod:
                self.items.append((node.lineno, mod, self.depth > 0))
            for alias in node.names:
                if mod:
                    self.items.append(
                        (node.lineno, f"{mod}.{alias.name}", self.depth > 0))

        def visit_Call(self, node: ast.Call) -> None:
            name = getattr(node.func, "attr", "")
            if name in ("import_module", "__import__") and node.args:
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    self.items.append((node.lineno, arg.value, self.depth > 0))
            self.generic_visit(node)

    visitor = Visitor()
    visitor.visit(tree)
    return visitor.items


def zone_violations(root: Path = ROOT) -> List[Dict[str, Any]]:
    src = Path(root) / "src"
    if not src.is_dir():
        return []
    issues: List[Dict[str, Any]] = []
    for child in sorted(src.iterdir()):
        if not child.is_dir() or child.name in EXCLUDED_PARTS or child.name == "src":
            continue
        rel = f"src/{child.name}/"
        if _zone_of(rel):
            continue
        # 纯容器目录（如 src/layers/）由子目录分区覆盖，不要求自身是 zone。
        if any(prefix.startswith(rel) for prefix, _ in _ZONES):
            continue
        issues.append({"type": "unregistered_zone", "path": rel,
                       "detail": "在 _ZONES 登记归属后再使用"})
    return issues


def import_violations(root: Path = ROOT) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    root = Path(root)
    for path in _iter_py(root):
        rel = path.relative_to(root).as_posix()
        src_zone = _zone_of(rel)
        if not src_zone:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError):
            continue
        for lineno, module, lazy in _imports(tree, rel):
            dst_zone, err = _target_zone(module, root)
            if err:
                issues.append({"type": err, "file": rel, "line": lineno,
                               "import": module})
                continue
            if not dst_zone or dst_zone == src_zone:
                continue
            allowed = _ALLOWED.get(src_zone, set()) | _DEPENDENCY_DEBT.get(rel, set())
            if dst_zone in allowed:
                continue
            if lazy and (src_zone, dst_zone) not in _LAZY_FORBIDDEN:
                continue
            issues.append({"type": "lazy_import_direction" if lazy
                           else "import_direction", "file": rel, "line": lineno,
                           "from": src_zone, "to": dst_zone,
                           "import": module})
    return issues


def _append_history(path: Path, rows: List[Dict[str, Any]]) -> None:
    if not rows:
        return
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _history(kind: str, key: str, old: Any, new: Any, reason: str,
             approver: str = "auto:reduce-debt") -> Dict[str, Any]:
    return {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "kind": kind, "key": key, "old": old, "new": new,
            "reason": reason, "approver": approver}


def _set_registered(text: str, rel: str, value: int) -> str:
    pattern = re.compile(
        rf"(^  {re.escape(rel)}:\n(?:    .*\n)*?    registered:\s*)\d+",
        re.MULTILINE)
    new_text, count = pattern.subn(rf"\g<1>{value}", text, count=1)
    if count != 1:
        raise GuardConfigError(f"无法在 budget 中定位 {rel}")
    return new_text


def _write_baseline(path: Path, data: Dict[str, int]) -> None:
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")


def reduce_debt(root: Path = ROOT, budget_path: Path = BUDGET_FILE,
                baseline_path: Path = BASELINE_FILE,
                history_path: Path = HISTORY_FILE) -> List[Dict[str, Any]]:
    """只允许降低预算 / 删除已解决债务；不新增、不提高。"""
    budget = load_budget(budget_path)
    counts = line_counts(root)
    comp = complexity_map(root)
    baseline = load_baseline(baseline_path)
    rows: List[Dict[str, Any]] = []
    budget_path = Path(budget_path)
    text = budget_path.read_text(encoding="utf-8")
    for rel, entry in budget["watched"].items():
        registered = int(entry.get("registered", 0))
        actual = counts.get(rel)
        if actual is None or actual >= registered:
            continue
        text = _set_registered(text, rel, actual)
        rows.append(_history("size", rel, registered, actual, "debt repayment"))
    new_base: Dict[str, int] = {}
    for key, old in baseline.items():
        actual = comp.get(key)
        if actual is None or actual <= COMPLEXITY_THRESHOLD:
            rows.append(_history("complexity", key, old, None, "debt cleared"))
        elif actual < old:
            new_base[key] = actual
            rows.append(_history("complexity", key, old, actual, "debt repayment"))
        else:
            new_base[key] = old
    if text != budget_path.read_text(encoding="utf-8"):
        budget_path.write_text(text, encoding="utf-8")
    _write_baseline(baseline_path, new_base)
    _append_history(history_path, rows)
    return rows


def approve_debt(key: str, reason: str, approver: str, root: Path = ROOT,
                 budget_path: Path = BUDGET_FILE,
                 baseline_path: Path = BASELINE_FILE,
                 history_path: Path = HISTORY_FILE) -> Dict[str, Any]:
    if not key or not reason.strip() or not approver.strip():
        raise GuardConfigError("--key / --reason / --approver 均不能为空")
    if "::" in key:
        comp = complexity_map(root)
        actual = comp.get(key)
        if actual is None:
            raise GuardConfigError(f"找不到函数: {key}")
        if actual <= COMPLEXITY_THRESHOLD:
            raise GuardConfigError(f"{key} 复杂度 {actual} <= 阈值，无需登记")
        baseline = load_baseline(baseline_path)
        old = baseline.get(key)
        if old is not None and actual <= old:
            raise GuardConfigError("债务没有增加；请用 --reduce-debt")
        baseline[key] = actual
        _write_baseline(baseline_path, baseline)
        row = _history("complexity", key, old, actual, reason, approver)
    else:
        counts = line_counts(root)
        actual = counts.get(key)
        if actual is None:
            raise GuardConfigError(f"找不到文件: {key}")
        budget = load_budget(budget_path)
        entry = budget["watched"].get(key)
        if not entry:
            raise GuardConfigError("新增大文件请手工登记 watched（含 reason/plan）")
        old = int(entry.get("registered", 0))
        if actual <= old:
            raise GuardConfigError("文件没有增长；请用 --reduce-debt")
        text = Path(budget_path).read_text(encoding="utf-8")
        Path(budget_path).write_text(_set_registered(text, key, actual),
                                     encoding="utf-8")
        row = _history("size", key, old, actual, reason, approver)
    _append_history(history_path, [row])
    return row


def check(root: Path = ROOT, budget_path: Path = BUDGET_FILE,
          baseline_path: Path = BASELINE_FILE) -> Dict[str, Any]:
    root = Path(root)
    budget = load_budget(budget_path)
    line_issues = line_violations(root, budget)
    comp_issues = complexity_violations(root, COMPLEXITY_THRESHOLD,
                                        load_baseline(baseline_path))
    zone_issues = zone_violations(root)
    import_issues = import_violations(root)
    debt_types = {"budget_not_tightened", "debt_cleared", "debt_repaid",
                  "baseline_stale", "complexity_new", "complexity_grew"}
    debt_issues = [i for i in line_issues + comp_issues
                   if i["type"] in debt_types]
    ok = not (line_issues or comp_issues or zone_issues or import_issues)
    return {
        "ok": ok,
        "line_budget": {"warn": budget["warn"], "error": budget["error"]},
        "line_issues": line_issues,
        "complexity_issues": comp_issues,
        "zone_issues": zone_issues,
        "import_issues": import_issues,
        "debt_issues": debt_issues,
        "import_direction_ok": not (zone_issues or import_issues),
        "tool_version": "2.0",
    }


def main(argv: List[str] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--reduce-debt", action="store_true")
    parser.add_argument("--approve-debt", action="store_true")
    parser.add_argument("--key", default="")
    parser.add_argument("--reason", default="")
    parser.add_argument("--approver", default="")
    args = parser.parse_args(argv)
    root = Path(args.root)
    try:
        if args.reduce_debt:
            rows = reduce_debt(root)
            print(f"debt reduced: {len(rows)} entries")
        elif args.approve_debt:
            row = approve_debt(args.key, args.reason, args.approver, root)
            print(f"debt approved: {row['key']} {row['old']} -> {row['new']}")
        result = check(root)
    except GuardConfigError as exc:
        print(f"[architecture] config error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for issue in (result["line_issues"] + result["complexity_issues"]
                      + result["zone_issues"] + result["import_issues"]):
            print(f"[architecture] {issue['type']}: {issue}")
        print("[architecture] OK" if result["ok"]
              else "[architecture] FAILED —— 见上面条目")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
