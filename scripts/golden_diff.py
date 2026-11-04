"""Golden 产物对比 —— 重构的"行为没变"证明。

用法：

    python scripts/golden_diff.py tests/golden/architecture_baseline <run_dir>
    python scripts/golden_diff.py <baseline_dir> <current_dir> --json

比较的是**结构性产物**（case_ir / testpoints / contract_manifest / gates /
worklist），不是波形/耗时。对比前会剔除时间戳、run 名、绝对路径等易变字段。
退出码：0 = 一致，1 = 有差异，2 = 输入缺失。
"""
from __future__ import annotations

import argparse
import difflib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

try:
    import yaml
except ImportError:  # pragma: no cover - 仓库环境有 yaml
    yaml = None

#: 对比的产物（相对 run 目录）。缺失的文件记 `missing`，不静默跳过。
FILES = (
    "coverage/case_ir.json",
    "coverage/testpoints.yaml",
    "coverage/gates.json",
    "contract/contract_manifest.json",
    "status/worklist.json",
    "coverage/case_closure.json",
    "coverage/coverage_holes.json",
)

#: 易变字段：时间、run 名、绝对路径。结构字段（id/hash/status）不在此列。
VOLATILE_KEYS = {
    "generated_at", "timestamp", "created_at", "updated_at",
    "elapsed", "duration", "duration_seconds", "run", "run_id",
    "path", "wave", "wave_abs", "log", "log_abs", "dir",
    "ucdb", "ucdb_abs", "cov_db", "cov_source", "cached",
    "baseline_run", "current_run",
}


def _load(path: Path) -> Any:
    text = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() in (".yaml", ".yml"):
        if yaml is None:
            raise RuntimeError("需要 PyYAML 才能比较 YAML")
        return yaml.safe_load(text)
    return json.loads(text)


def _normalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _normalize(v) for k, v in sorted(value.items())
                if str(k) not in VOLATILE_KEYS}
    if isinstance(value, list):
        return [_normalize(v) for v in value]
    return value


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)


def _diff_text(base: Any, cur: Any, limit: int = 60) -> List[str]:
    a = _canonical(base).splitlines()
    b = _canonical(cur).splitlines()
    return list(difflib.unified_diff(a, b, fromfile="baseline", tofile="current",
                                     lineterm=""))[:limit]


def compare(baseline: Path, current: Path) -> Dict[str, Any]:
    diffs: List[Dict[str, Any]] = []
    checked = 0
    for rel in FILES:
        bpath, cpath = baseline / rel, current / rel
        if not bpath.is_file() and not cpath.is_file():
            continue
        if not bpath.is_file():
            diffs.append({"file": rel, "kind": "baseline_missing"})
            continue
        if not cpath.is_file():
            diffs.append({"file": rel, "kind": "current_missing"})
            continue
        checked += 1
        base = _normalize(_load(bpath))
        cur = _normalize(_load(cpath))
        if base != cur:
            diffs.append({"file": rel, "kind": "content",
                          "diff": _diff_text(base, cur)})
    return {"ok": not diffs, "checked": checked, "diffs": diffs,
            "baseline": str(baseline), "current": str(current)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("baseline", type=Path)
    ap.add_argument("current", type=Path)
    ap.add_argument("--json", "-j", action="store_true")
    args = ap.parse_args()
    if not args.baseline.is_dir() or not args.current.is_dir():
        print("基线或当前目录不存在", file=sys.stderr)
        return 2
    result = compare(args.baseline, args.current)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"checked={result['checked']} ok={result['ok']}")
        for item in result["diffs"]:
            print(f"  [{item['kind']}] {item['file']}")
            for line in item.get("diff") or []:
                print("    " + line)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
