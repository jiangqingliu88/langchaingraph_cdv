"""架构复杂度预算 —— 防止“成功带来的复杂度增长”无声发生。

两个预算：

  · **文件行数**：> 2000 失败；> 1500 必须登记（且只能变小不能变大）。
  · **函数圈复杂度**：> 20 必须进 baseline；已登记的函数不得再增长。

基线不是“豁免”，是**债务清单**：拆小之后要把 registered / baseline 一起
下调，否则下一次增长会被当成“本来就这样”。

用法：
    python -m config.architecture_guard                 # 检查（有违规 exit 1）
    python -m config.architecture_guard --json          # 机器读
    python -m config.architecture_guard --update-baseline
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import yaml

ROOT = Path(__file__).resolve().parent.parent
BUDGET_FILE = Path(__file__).resolve().parent / "architecture_budget.yaml"
BASELINE_FILE = Path(__file__).resolve().parent / "complexity_baseline.json"

#: 只扫实现代码；测试文件不受行数预算约束（测试长一点不是架构问题）。
SCAN_ROOTS = (ROOT / "src",)
EXCLUDED_PARTS = {"__pycache__", "tests"}


# ═══════════════════════════════════════════════════════════════
# 行数预算
# ═══════════════════════════════════════════════════════════════

def _iter_py(root: Path = ROOT) -> Iterable[Path]:
    for base in SCAN_ROOTS:
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            if EXCLUDED_PARTS & set(path.parts):
                continue
            yield path


def line_counts(root: Path = ROOT) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for path in _iter_py(root):
        try:
            with path.open(encoding="utf-8", errors="replace") as fh:
                out[path.relative_to(root).as_posix()] = sum(1 for _ in fh)
        except OSError:
            continue
    return out


def load_budget(path: Path = BUDGET_FILE) -> Dict[str, Any]:
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    line = doc.get("line_budget") or {}
    return {
        "warn": int(line.get("warn", 1500)),
        "error": int(line.get("error", 2000)),
        "watched": doc.get("watched") or {},
    }


def line_violations(root: Path = ROOT, budget: Dict[str, Any] = None) -> List[Dict[str, Any]]:
    budget = budget or load_budget()
    warn, error = budget["warn"], budget["error"]
    watched = budget["watched"]
    issues: List[Dict[str, Any]] = []
    for rel, lines in line_counts(root).items():
        entry = watched.get(rel)
        if lines > error:
            issues.append({"type": "lines_over_error", "path": rel,
                           "actual": lines, "limit": error,
                           "detail": "超过硬上限"})
        if entry:
            # watched 文件的 registered 是**硬预算**：不是只在 >2000 时才检查。
            # 否则 guard 会对 626>600 这类漂移保持沉默，只有测试能发现。
            registered = int(entry.get("registered", error))
            if lines > registered:
                issues.append({"type": "watched_file_grew", "path": rel,
                               "actual": lines, "registered": registered,
                               "detail": "登记预算只能变小不能变大"})
        elif lines > warn:
            issues.append({"type": "lines_unwatched", "path": rel,
                           "actual": lines, "warn": warn,
                           "detail": "超过预警线，需登记 reason/plan"})
    for rel, entry in watched.items():
        if not Path(root / rel).is_file():
            issues.append({"type": "missing_watched_file", "path": rel})
        for key in ("reason", "plan", "registered"):
            if key not in entry:
                issues.append({"type": "watched_missing_field", "path": rel,
                               "field": key})
    return issues


# ═══════════════════════════════════════════════════════════════
# 圈复杂度
# ═══════════════════════════════════════════════════════════════

def cyclomatic(node: ast.AST) -> int:
    """近似 McCabe：1 + 分支点。够用，且不引入第三方分析器。"""
    score = 1
    for child in ast.walk(node):
        if isinstance(child, (ast.If, ast.For, ast.AsyncFor, ast.While,
                              ast.IfExp, ast.ExceptHandler)):
            score += 1
        elif isinstance(child, ast.BoolOp):
            score += len(child.values) - 1
        elif isinstance(child, ast.comprehension) and child.ifs:
            score += len(child.ifs)
    return score


def complexity_map(root: Path = ROOT) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for path in _iter_py(root):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError):
            continue
        rel = path.relative_to(root).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                out[f"{rel}::{node.name}"] = cyclomatic(node)
    return out


def load_baseline(path: Path = BASELINE_FILE) -> Dict[str, int]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(k): int(v) for k, v in doc.items()} if isinstance(doc, dict) else {}


def write_baseline(path: Path = BASELINE_FILE, threshold: int = 20) -> Dict[str, int]:
    data = {k: v for k, v in complexity_map().items() if v > threshold}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    return data


def complexity_violations(root: Path = ROOT, threshold: int = 20,
                          baseline: Dict[str, int] = None) -> List[Dict[str, Any]]:
    baseline = baseline if baseline is not None else load_baseline()
    current = complexity_map(root)
    issues: List[Dict[str, Any]] = []
    for key, value in current.items():
        if value <= threshold:
            continue
        known = baseline.get(key)
        if known is None:
            issues.append({"type": "complexity_new", "function": key,
                           "actual": value, "limit": threshold,
                           "detail": "新函数超过阈值且未登记基线"})
        elif value > known:
            issues.append({"type": "complexity_grew", "function": key,
                           "actual": value, "baseline": known})
    for key in baseline:
        if key not in current:
            issues.append({"type": "baseline_stale", "function": key,
                           "detail": "函数已不存在，请重生成基线"})
    return issues


# ═══════════════════════════════════════════════════════════════
# 依赖方向（Phase 1 先 warning，Phase 2 后转 error）
# ═══════════════════════════════════════════════════════════════

_ZONES = (
    ("src/core/", "core"),
    ("src/layers/l1_infrastructure/", "l1"),
    ("src/layers/l2_orchestration/", "l2"),
    ("src/layers/l3_decision/", "l3"),
    ("src/layers/l4_memory/", "l4"),
    ("src/layers/l5_evolution/", "l5"),
    ("src/executors/", "executors"),
    ("src/tools/", "tools"),
    ("src/agents/", "agents"),
    ("src/cli/", "iface"),
    ("src/workbench/", "iface"),
    ("src/app/", "iface"),
)

#: zone → 允许 import 的 zone（只能向下 / 同层）。
_ALLOWED = {
    "core": set(),
    # `tools` 目前是低层适配器集合（UVM/EDA/覆盖率解析），l1/l2/l3/l4/l5
    # 都可以调用它；**反向（tools → layers）才是债务**，Phase 3 要清零。
    "l1": {"core", "tools"},
    "l3": {"l1", "l4", "core", "tools"},
    "l4": {"l1", "core", "tools"},
    "l5": {"l1", "l3", "l4", "core", "tools"},
    "l2": {"l1", "l3", "l4", "l5", "core", "agents", "tools"},
    "executors": {"l1", "l2", "l3", "l4", "l5", "core", "agents", "tools"},
    # 适配器可以调用基础设施（L1）；但不得反向依赖 L2/L3/L4（业务层）。
    "tools": {"core", "l1"},
    "agents": {"l1", "l2", "l3", "l4", "l5", "core", "tools"},
    "iface": {"core", "l1", "l2", "l3", "l4", "l5", "executors", "agents", "tools"},
}

#: Phase 1 的 façade：它们**故意**转发旧实现，搬迁完成后删除。
_FACADE_PATHS = {
    "src/layers/l3_decision/contract/__init__.py",
    "src/layers/l3_decision/casemodel/__init__.py",
    "src/layers/l4_memory/ledger/__init__.py",
    "src/layers/l5_evolution/closure/__init__.py",
    # Phase 3 后保留的**边界 shim**：
    # Phase 4：边界 shim 逐步替换为端口/注册表注入；当前已全部删除。
}


def _zone_of(rel: str) -> str:
    for prefix, zone in _ZONES:
        if rel.startswith(prefix):
            return zone
    return ""


def import_violations(root: Path = ROOT) -> List[Dict[str, Any]]:
    """检查 `src.*` 绝对 import 是否逆流。相对 import 视为同包，不检查。"""
    issues: List[Dict[str, Any]] = []
    for path in _iter_py(root / "src"):
        rel = path.relative_to(root).as_posix()
        src_zone = _zone_of(rel)
        if not src_zone or rel in _FACADE_PATHS:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError):
            continue
        # **只看模块级 import**：函数内 `import` / `from ... import` 是
        # 有意的延迟加载（切断静态依赖的手段），不算方向违规。
        for node in tree.body:
            target = ""
            if isinstance(node, ast.ImportFrom) and node.level == 0:
                target = str(node.module or "")
            elif isinstance(node, ast.Import):
                target = next((a.name for a in node.names
                               if a.name.startswith("src.")), "")
            if not target.startswith("src."):
                continue
            dst_zone = _zone_of(target.replace(".", "/") + "/")
            if not dst_zone or dst_zone == src_zone:
                continue
            if dst_zone not in _ALLOWED.get(src_zone, set()):
                issues.append({"type": "import_direction", "file": rel,
                               "from": src_zone, "to": dst_zone,
                               "import": target})
    return issues


# ═══════════════════════════════════════════════════════════════
# 入口
# ═══════════════════════════════════════════════════════════════

def check(root: Path = ROOT) -> Dict[str, Any]:
    budget = load_budget()
    line_issues = line_violations(root, budget)
    comp_issues = complexity_violations(root, 20, load_baseline())
    import_issues = import_violations(root)
    return {
        # Phase 3 结束：依赖方向已经清零，**并入阻断门禁**（0 违规才绿）。
        "ok": not line_issues and not comp_issues and not import_issues,
        "line_budget": {"warn": budget["warn"], "error": budget["error"]},
        "line_issues": line_issues,
        "complexity_issues": comp_issues,
        "import_issues": import_issues,
        "import_direction_ok": not import_issues,
    }


def main(argv: List[str] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--update-baseline", action="store_true")
    args = parser.parse_args(argv)

    if args.update_baseline:
        data = write_baseline()
        print(f"baseline updated: {len(data)} functions > 20 (-> {BASELINE_FILE})")
        return 0

    result = check()
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for issue in result["line_issues"] + result["complexity_issues"]:
            print(f"[architecture] {issue['type']}: {issue}")
        print("[architecture] OK" if result["ok"]
              else "[architecture] FAILED —— 见上面条目")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
