"""决策成效评估（`decision_eval_v1`）。

为什么不能只看覆盖率涨没涨
    覆盖率上涨可能来自**别的**测试碰巧命中；下跌也可能只是本轮没跑某条用例。
    所以记录里同时保留：动作的期望（来自 VerificationPlan）、实际的覆盖率 delta、
    TP 命中数变化、回归失败数、编译状态与证据文件。判不出来就写 `UNCERTAIN`
    —— 不拿"看起来变好了"冒充 EFFECTIVE。

文件：`<run>/decision/evaluations.jsonl`，一行一条，按 (run_id, round, action)
幂等（节点重跑不会写出两条）。
"""
from __future__ import annotations
from src.runtime_plane.core.contracts import versions

import json
import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

DECISION_SCHEMA = versions.DECISION

EFFECTIVE = "EFFECTIVE"
INEFFECTIVE = "INEFFECTIVE"
REGRESSED = "REGRESSED"
UNCERTAIN = "UNCERTAIN"

#: 覆盖率变化的判定阈值（百分点）。小于它视为"没动"。
COVERAGE_EPSILON = 0.05

_LOCK = threading.RLock()


def record_path(run_root: str | Path) -> Path:
    return Path(run_root) / "decision" / "evaluations.jsonl"


def read_records(run_root: str | Path) -> List[Dict[str, Any]]:
    path = record_path(run_root)
    out: List[Dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    doc = json.loads(line)
                except ValueError:
                    continue
                if isinstance(doc, dict):
                    out.append(doc)
    except OSError:
        return out
    return out


def _num(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_regressed(failed, failed_prev, lost_hits, compile_ok, compile_ok_prev) -> bool:
    return bool(
        (compile_ok_prev is True and compile_ok is False)
        or (failed is not None and failed_prev is not None and failed > failed_prev)
        or lost_hits > 0
    )


def _is_improved(delta: Optional[float], new_hits: int) -> bool:
    return bool((delta is not None and delta > COVERAGE_EPSILON) or new_hits > 0)


def _is_unchanged(delta: Optional[float], new_hits: int, lost_hits: int) -> bool:
    return bool(delta is not None and abs(delta) <= COVERAGE_EPSILON
                and new_hits == 0 and lost_hits == 0)


def _classify(*, inputs: Dict[str, bool], regressed: bool, improved: bool,
              unchanged: bool, needs_human: bool, delta: Optional[float],
              new_hits: int, failed, failed_prev, lost_hits: int,
              compile_ok, compile_ok_prev) -> tuple:
    """(status, reason, confidence)。规则顺序就是优先级：回归 > 人工 > 无输入。"""
    if regressed:
        return (REGRESSED, _reason_regressed(failed, failed_prev, lost_hits,
                                            compile_ok, compile_ok_prev), "strong")
    if needs_human:
        return (UNCERTAIN, "动作需要人工升级，效果不由本套指标判定", "weak")
    if not (inputs["coverage"] or inputs["tp_matrix"]):
        return (UNCERTAIN, "覆盖率与 TP 矩阵都没有可用前后值，无法判定", "weak")
    if improved:
        return (EFFECTIVE, _reason_effective(delta, new_hits),
                "strong" if inputs["tp_matrix"] else "weak")
    if unchanged:
        return (INEFFECTIVE, "覆盖率与 TP 命中均无变化（确定性相等）",
                "strong" if inputs["coverage"] and inputs["tp_matrix"] else "weak")
    return (UNCERTAIN, "信号不足或方向不一致，不能归因", "weak")


def evaluate_round(*, run_id: str, round_num: int, action: Dict[str, Any],
                   expected: Dict[str, Any], actual: Dict[str, Any]) -> Dict[str, Any]:
    """把期望与实际合成为一条可审计记录。纯函数，不读写文件。"""
    prev_cov = _num(actual.get("prev_coverage"))
    cov = _num(actual.get("coverage"))
    delta = (cov - prev_cov) if (prev_cov is not None and cov is not None) else None

    new_hits = int(actual.get("new_hits") or 0)
    lost_hits = int(actual.get("lost_hits") or 0)
    failed = _num(actual.get("tests_failed"))
    failed_prev = _num(actual.get("tests_failed_prev"))
    compile_ok = actual.get("compile_ok")
    compile_ok_prev = actual.get("compile_ok_prev")
    tp_available = bool(actual.get("tp_matrix_available"))
    inputs = {
        "coverage": prev_cov is not None and cov is not None,
        "tp_matrix": tp_available,
        "regression": failed is not None,
        "compile": compile_ok is not None,
    }
    status, reason, confidence = _classify(
        inputs=inputs,
        regressed=_is_regressed(failed, failed_prev, lost_hits,
                                compile_ok, compile_ok_prev),
        improved=_is_improved(delta, new_hits),
        unchanged=_is_unchanged(delta, new_hits, lost_hits),
        needs_human=bool(expected.get("needs_human")),
        delta=delta, new_hits=new_hits, failed=failed, failed_prev=failed_prev,
        lost_hits=lost_hits, compile_ok=compile_ok, compile_ok_prev=compile_ok_prev)
    return {
        "schema": DECISION_SCHEMA,
        "run_id": run_id,
        "round": int(round_num or 0),
        "action": {
            "action_type": str(action.get("action_type") or action.get("action") or ""),
            "reason": str(action.get("reason") or ""),
            "source": str(action.get("source") or "rule"),
        },
        "expected": expected,
        "actual": {
            "prev_coverage": prev_cov, "coverage": cov,
            "delta": round(delta, 2) if delta is not None else None,
            "new_hits": new_hits, "lost_hits": lost_hits,
            "tests_failed": failed, "tests_failed_prev": failed_prev,
            "compile_ok": compile_ok, "compile_ok_prev": compile_ok_prev,
            "tp_matrix_available": tp_available,
            "evidence": list(actual.get("evidence") or []),
        },
        "status": status, "reason": reason, "confidence": confidence,
        "inputs_available": inputs,
    }


def _reason_effective(delta: Optional[float], new_hits: int) -> str:
    parts = []
    if delta is not None and delta > COVERAGE_EPSILON:
        parts.append(f"覆盖率 +{delta:.2f}")
    if new_hits:
        parts.append(f"新增命中 {new_hits} 个 TP")
    return "；".join(parts) + "；无回归"


def _reason_regressed(failed, failed_prev, lost_hits, compile_ok, compile_ok_prev) -> str:
    parts = []
    if compile_ok_prev is True and compile_ok is False:
        parts.append("编译由通过变为失败")
    if failed is not None and failed_prev is not None and failed > failed_prev:
        parts.append(f"回归失败 {failed_prev} → {failed}")
    if lost_hits:
        parts.append(f"丢失 {lost_hits} 个已命中 bin")
    return "；".join(parts) or "出现回归信号"


def append_record(run_root: str | Path, record: Dict[str, Any]) -> bool:
    """幂等追加。返回是否真的写入（重复 = False）。"""
    path = record_path(run_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    key = (str(record.get("run_id") or ""), int(record.get("round") or 0),
           str((record.get("action") or {}).get("action_type") or ""))
    with _LOCK:
        for old in read_records(path.parent.parent):
            old_key = (str(old.get("run_id") or ""), int(old.get("round") or 0),
                       str((old.get("action") or {}).get("action_type") or ""))
            if old_key == key:
                return False
        tmp = path.with_suffix(".jsonl.tmp")
        try:
            existing = path.read_text(encoding="utf-8") if path.exists() else ""
        except OSError:
            existing = ""
        body = existing + json.dumps(record, ensure_ascii=False) + "\n"
        try:
            tmp.write_text(body, encoding="utf-8", newline="\n")
            os.replace(tmp, path)
        except OSError:
            try:
                tmp.unlink()
            except OSError:
                pass
            return False
        return True


def summarize(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    counts = {EFFECTIVE: 0, INEFFECTIVE: 0, REGRESSED: 0, UNCERTAIN: 0}
    by_action: Dict[str, Dict[str, int]] = {}
    for rec in records:
        status = str(rec.get("status") or UNCERTAIN)
        counts[status] = counts.get(status, 0) + 1
        action = str((rec.get("action") or {}).get("action_type") or "")
        bucket = by_action.setdefault(action, {EFFECTIVE: 0, INEFFECTIVE: 0,
                                               REGRESSED: 0, UNCERTAIN: 0})
        bucket[status] = bucket.get(status, 0) + 1
    return {"total": len(records), "by_status": counts,
            "by_action": dict(sorted(by_action.items()))}
