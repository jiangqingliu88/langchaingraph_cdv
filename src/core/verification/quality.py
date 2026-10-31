"""Verification Quality Gate（`verification_quality_v1`）。

五维分开，是因为「签核 PASS」至少可能以五种方式名不副实：
    functional  回归到底有没有真比过（scoreboard mismatch=0）
    coverage    覆盖率有没有真的采到、够不够目标
    model       参考模型是 verified 还是占位草稿
    structural  RTL / 轮次事实 / 文件哈希链有没有漂移
    evidence    产物血缘、事件、工具回执、必需输出在不在

本阶段**只报告、不阻断**：不新增 caveat code（否则会改到已冻结的
`EXPECTED_CAVEATS`），也不参与 `hard_ok`。`unknown` 绝不折算成 pass
——「判不了」与「判过了」必须分开。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

QUALITY_SCHEMA = "verification_quality_v1"

DIMENSIONS = ("functional", "coverage", "model", "structural", "evidence")

#: 总状态优先级：fail > unknown > warn > pass。unknown 不冒充 pass。
_RANK = {"pass": 0, "not_applicable": 0, "warn": 1, "unknown": 2, "fail": 3}


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _num(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _dim(status: str, *, score: float = 0.0, facts: Optional[Dict] = None,
         issues: Optional[List[str]] = None) -> Dict[str, Any]:
    return {"status": status, "score": round(max(0.0, min(1.0, score)), 2),
            "facts": facts or {}, "issues": list(issues or [])}


# ═══════════════════════════════════════════════════════════════
# 维度
# ═══════════════════════════════════════════════════════════════

def _regression_totals(root: Path) -> tuple:
    stages = _read_json(root / "regression_stages.json")
    report = _read_json(root / "regression_run" / "report.json")
    if stages:
        return (_num(stages.get("passed")), _num(stages.get("failed")),
                _num(stages.get("total")))
    return (_num(report.get("passed")), _num(report.get("failed")),
            _num(report.get("total")))


def _tp_counts(root: Path) -> tuple:
    matrix = _read_json(root / "coverage" / "tp_matrix.json")
    counts = matrix.get("counts") or {}
    return int(counts.get("HIT", 0) or 0), int(counts.get("UNMAPPED", 0) or 0)


def _functional(root: Path) -> Dict[str, Any]:
    passed, failed, total = _regression_totals(root)
    hit, unmapped = _tp_counts(root)
    plan = _read_json(root / "incremental" / "plan.json")
    selected = len(plan.get("selected_tests") or []) if plan else 0
    all_tests = int(plan.get("all_tests") or 0) if plan else 0
    facts = {"passed": passed, "failed": failed, "total": total,
             "tp_hit": hit, "tp_unmapped": unmapped,
             "incremental": bool(plan),
             "incremental_selected": selected,
             "incremental_all": all_tests}
    if total is None or failed is None:
        return _dim("unknown", facts=facts,
                    issues=["没有可用的回归结果（regression_stages.json / report.json）"])
    if total <= 0:
        return _dim("fail", score=0.0, facts=facts,
                    issues=["回归一条用例都没跑（total=0）"])
    if failed > 0:
        return _dim("fail", score=0.0, facts=facts,
                    issues=[f"回归失败 {int(failed)} 条"])
    if unmapped > 0:
        return _dim("warn", score=0.7, facts=facts,
                    issues=[f"{unmapped} 个 TP 在覆盖率报告里找不到（UNMAPPED）"])
    if hit <= 0:
        return _dim("warn", score=0.6, facts=facts,
                    issues=["回归全过但 TP 命中数为 0"])
    if plan.get("confidence") == "mapped" and selected < all_tests:
        return _dim("warn", score=0.8, facts=facts,
                    issues=[f"增量回归只跑 {selected}/{all_tests} 条用例，"
                            f"签核范围依赖基线计划（{plan.get('baseline_run', '')}）"])
    return _dim("pass", score=1.0, facts=facts)


def _coverage(root: Path, target: Optional[float]) -> Dict[str, Any]:
    result = _read_json(root / "sim" / "coverage" / "coverage_result.json")
    if not result:
        result = _read_json(root / "coverage" / "coverage_result.json")
    if not result:
        return _dim("unknown", issues=["没有 coverage_result.json"])
    functional = _num(result.get("functional_pct"))
    overall = _num(result.get("overall_pct"))
    plan_merge = (root / "coverage" / "plan_merge_manifest.json").is_file()
    seed_div = _read_json(root / "coverage" / "seed_diversity.json")
    facts = {"functional_pct": functional, "overall_pct": overall,
             "plan_merge_manifest": plan_merge,
             "seed_diversity": seed_div.get("verdict") if seed_div else None,
             "target": target}
    if functional is None and overall is None:
        return _dim("unknown", facts=facts, issues=["覆盖率结果缺 pct 字段"])
    pct = functional if functional is not None else overall
    if pct <= 0:
        return _dim("fail", score=0.0, facts=facts,
                    issues=["覆盖率采到了但为 0%"])
    if target and target > 0:
        if pct >= target:
            return _dim("pass", score=1.0, facts=facts)
        if pct >= target * 0.9:
            return _dim("warn", score=0.6, facts=facts,
                        issues=[f"覆盖率 {pct:.1f}% 低于目标 {target:.1f}%"])
        return _dim("fail", score=0.2, facts=facts,
                    issues=[f"覆盖率 {pct:.1f}% 显著低于目标 {target:.1f}%"])
    return _dim("warn", score=0.5, facts=facts,
                issues=["没有目标值，只能确认覆盖率非零"])


def _model(root: Path) -> Dict[str, Any]:
    candidates = (root / "inputs" / "yaml" / "uvm" / "models.yaml",
                  root / "inputs" / "yaml" / "models.yaml")
    path = next((p for p in candidates if p.is_file()), None)
    if path is None:
        return _dim("unknown", issues=["没有 models.yaml —— 判不了参考模型状态"])
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return _dim("unknown", issues=["models.yaml 读不到"])
    placeholder = bool(re.search(r"(?im)^\s*placeholder\s*:\s*true\b", text))
    verified = bool(re.search(r"(?im)^\s*status\s*:\s*[\"']?verified\b", text))
    facts = {"path": path.relative_to(root).as_posix(),
             "placeholder": placeholder, "verified": verified}
    if placeholder:
        return _dim("warn", score=0.3, facts=facts,
                    issues=["参考模型是占位草稿（placeholder: true）"])
    if verified:
        return _dim("pass", score=1.0, facts=facts)
    return _dim("warn", score=0.5, facts=facts,
                issues=["参考模型不是 verified 状态"])


def _structural(root: Path) -> Dict[str, Any]:
    round_manifest = _read_json(root / "coverage" / "round_manifest.json")
    chain = _read_json(root / "docs" / "file_change_chain.json")
    facts: Dict[str, Any] = {
        "round_manifest": bool(round_manifest),
        "rounds": len(round_manifest.get("rounds") or []),
        "file_chain": bool(chain),
        "chain_valid": chain.get("chain_valid"),
    }
    issues: List[str] = []
    if chain and chain.get("chain_valid") is False:
        issues.append("文件变更链自校验失败（hash 断/尾部被裁）")
    if round_manifest:
        rounds = round_manifest.get("rounds") or []
        if not rounds:
            issues.append("round_manifest 存在但没有 rounds")
        drift = [r for r in rounds if not isinstance(r, dict)]
        if drift:
            issues.append("round_manifest 含非法轮次记录")
    if issues:
        return _dim("fail", score=0.2, facts=facts, issues=issues)
    if not round_manifest and not chain:
        return _dim("unknown", facts=facts,
                    issues=["没有 round_manifest / 文件变更链"])
    if not round_manifest:
        return _dim("unknown", facts=facts,
                    issues=["没有 round_manifest（轮次事实不可核）"])
    if not chain:
        return _dim("warn", score=0.6, facts=facts,
                    issues=["没有文件变更链（人工编辑不可追溯）"])
    return _dim("pass", score=1.0, facts=facts)


def _evidence(root: Path) -> Dict[str, Any]:
    provenance = (root / "docs" / "provenance.jsonl").is_file()
    summary = _read_json(root / "docs" / "provenance_summary.json")
    events = (root / "docs" / "events.jsonl").is_file()
    receipts = (root / "docs" / "tool_receipts.jsonl").is_file()
    per_test = (root / "coverage" / "per_test_bins.json").is_file()
    artifacts = _read_json(root / "artifacts" / "artifacts.json")
    attribution = _read_json(root / "coverage" / "attribution.json")
    facts = {
        "provenance": provenance,
        "provenance_confidence": summary.get("by_confidence") or {},
        "events": events,
        "tool_receipts": receipts,
        "per_test_bins": per_test,
        "attribution_rate": attribution.get("attribution_rate"),
        "artifacts": len(artifacts.get("artifacts") or []),
    }
    issues: List[str] = []
    if not provenance and not events and not receipts:
        return _dim("unknown", facts=facts,
                    issues=["没有任何产物/事件/工具回执证据"])
    weak = int((summary.get("by_confidence") or {}).get("weak", 0) or 0)
    if provenance and weak:
        issues.append(f"{weak} 条血缘边是 weak（缺 per-test 覆盖率，不能精确归因）")
    if not receipts:
        issues.append("没有工具回执（docs/tool_receipts.jsonl）")
    if not per_test and provenance:
        issues.append("没有 per-test 覆盖率 sidecar")
    if issues:
        return _dim("warn", score=0.6, facts=facts, issues=issues)
    return _dim("pass", score=1.0, facts=facts)


# ═══════════════════════════════════════════════════════════════
# 汇总
# ═══════════════════════════════════════════════════════════════

def evaluate(run_root: str | Path, *, target: Optional[float] = None,
             run_id: str = "") -> Dict[str, Any]:
    root = Path(run_root)
    dims = {
        "functional": _functional(root),
        "coverage": _coverage(root, target),
        "model": _model(root),
        "structural": _structural(root),
        "evidence": _evidence(root),
    }
    overall = "pass"
    for dim in dims.values():
        status = dim["status"]
        if _RANK[status] > _RANK[overall]:
            overall = status
    if overall == "not_applicable":
        overall = "unknown"
    issues = [f"{name}: {msg}" for name, dim in dims.items()
              for msg in dim.get("issues") or []]
    return {
        "schema": QUALITY_SCHEMA,
        "run": run_id or root.name,
        "dimensions": dims,
        "overall": overall,
        "issues": issues,
    }


def write(run_root: str | Path, *, target: Optional[float] = None,
          run_id: str = "", event_store=None) -> Dict[str, Any]:
    """落盘 `<run>/docs/verification_quality.json`；返回报告本身。"""
    root = Path(run_root)
    report = evaluate(root, target=target, run_id=run_id)
    path = root / "docs" / "verification_quality.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8", newline="\n")
    report["path"] = str(path)
    if event_store is not None:
        event_store.append(
            "quality.gate", status=report["overall"],
            payload={"path": path.relative_to(root).as_posix(),
                     "overall": report["overall"],
                     "dimensions": {k: v["status"] for k, v in report["dimensions"].items()}},
            source="quality",
            dedup_key=f"quality:{root.name}:{report['overall']}")
    return report
