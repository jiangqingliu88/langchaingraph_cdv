"""轮次级事实表 —— 把“这一轮第 N 条用例实际跑了什么”钉进证据。

run 级 manifest 只回答“这次 run 产出了哪些文件”；player 落地后还需要回答
**per-test** 的问题：哪份 plan、哪个后端、实际播放了多少笔、判据是什么。

本模块从已有产物确定性重建：

    testpoints.json ─┐
    stimulus_plan.json ─┼─► coverage/round_manifest.json
    tp_matrix.json ─┘

不跑 EDA、不调 LLM；同一输入重复构建得到同一 sha256。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

SCHEMA = "round_manifest_v1"
QUERY_CONTRACT = "round_facts_v1"


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _sha(path: Path) -> str:
    try:
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return ""


def _entry_sha(entry: Dict[str, Any]) -> str:
    payload = json.dumps(entry, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _log_index(root: Path) -> Dict[str, Path]:
    """test 名 → sim_vsim.log（同名取第一条）。"""
    out: Dict[str, Path] = {}
    reg = root / "regression_run"
    if not reg.is_dir():
        return out
    for path in reg.rglob("sim_vsim.log"):
        out.setdefault(path.parent.name, path)
    return out


def _fact(tp: Dict[str, Any], round_no: int, backend: str,
          status_by_tp: Dict[str, str], plan_by_tp: Dict[str, Dict[str, Any]],
          logs: Dict[str, Path], log_sha: Dict[str, str],
          plan_sha: str) -> Optional[Dict[str, Any]]:
    tp_id = str(tp.get("tp_id") or "")
    if not tp_id:
        return None
    entry = plan_by_tp.get(tp_id)
    execution = tp.get("execution") or {}
    test = str((entry or {}).get("test") or execution.get("test") or "")
    if not test:
        return None
    if test in logs and test not in log_sha:
        log_sha[test] = _sha(logs[test])
    rule = tp.get("status_rule") or {}
    criteria = "；".join(x for x in (rule.get("pass", ""),
                                    rule.get("evidence", "")) if x)
    return {
        "round": int(round_no),
        "backend": backend if entry else "",
        "test_name": test,
        "tp_id": tp_id,
        "kind": str((tp.get("realization") or {}).get("kind") or ""),
        "status": status_by_tp.get(tp_id, ""),
        "plan_sha256": plan_sha if entry else "",
        "entry_sha256": _entry_sha(entry) if entry else "",
        "playback_log_sha256": log_sha.get(test, ""),
        "pass_criteria": criteria,
    }


def build_round_facts(output_dir: str | Path, round_no: int) -> List[Dict[str, Any]]:
    root = Path(output_dir)
    tps = _read_json(root / "coverage" / "testpoints.json").get("testpoints") or []
    plan = _read_json(root / "coverage" / "stimulus_plan.json")
    matrix = _read_json(root / "coverage" / "tp_matrix.json")
    status_by_tp = {
        str(r.get("tp_id") or ""): str(r.get("status") or "")
        for r in (matrix.get("rows") or []) if isinstance(r, dict)
    }
    plan_by_tp = {
        str(e.get("tp_id") or ""): e
        for e in (plan.get("testpoints") or []) if isinstance(e, dict)
    }
    logs = _log_index(root)
    log_sha: Dict[str, str] = {}
    backend = str(plan.get("backend") or "generated")
    plan_sha = str(plan.get("sha256") or "")
    facts = [_fact(tp, round_no, backend, status_by_tp, plan_by_tp,
                   logs, log_sha, plan_sha)
             for tp in tps if isinstance(tp, dict)]
    facts = [f for f in facts if f]
    facts.sort(key=lambda f: (f["test_name"], f["tp_id"]))
    return facts


def _digest(manifest: Dict[str, Any]) -> str:
    body = {k: v for k, v in manifest.items() if k != "sha256"}
    payload = json.dumps(body, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def record_round_facts(output_dir: str | Path, round_no: int) -> Dict[str, Any]:
    """写入/替换某一轮的事实；返回摘要。round_no <= 0 时什么都不做。"""
    if int(round_no or 0) <= 0:
        return {}
    root = Path(output_dir)
    path = root / "coverage" / "round_manifest.json"
    doc = _read_json(path)
    rounds = [r for r in (doc.get("rounds") or [])
              if int(r.get("round", 0) or 0) != int(round_no)]
    facts = build_round_facts(root, round_no)
    rounds.append({"round": int(round_no), "facts": facts})
    rounds.sort(key=lambda r: int(r.get("round", 0) or 0))
    manifest = {"schema": SCHEMA, "query_contract": QUERY_CONTRACT,
                "rounds": rounds}
    manifest["sha256"] = _digest(manifest)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8", newline="\n")
    return {"path": str(path), "round": int(round_no),
            "facts": len(facts), "sha256": manifest["sha256"]}


def load_round_manifest(output_dir: str | Path) -> Dict[str, Any]:
    return _read_json(Path(output_dir) / "coverage" / "round_manifest.json")


def validate_round_manifest(output_dir: str | Path) -> List[Dict[str, Any]]:
    """校验 facts 与当前 TP/plan 不漂移；返回 issues。"""
    root = Path(output_dir)
    doc = load_round_manifest(root)
    if not doc:
        return []
    tps = {str(t.get("tp_id") or ""): t for t in
           (_read_json(root / "coverage" / "testpoints.json").get("testpoints") or [])
           if isinstance(t, dict)}
    plan = _read_json(root / "coverage" / "stimulus_plan.json")
    plan_sha = str(plan.get("sha256") or "")
    plan_by_tp = {str(e.get("tp_id") or ""): e for e in
                  (plan.get("testpoints") or []) if isinstance(e, dict)}
    issues: List[Dict[str, Any]] = []
    for rnd in doc.get("rounds") or []:
        for fact in rnd.get("facts") or []:
            tp_id = str(fact.get("tp_id") or "")
            if tp_id not in tps:
                issues.append({"type": "tp_missing", "round": rnd.get("round"),
                               "tp_id": tp_id})
                continue
            if fact.get("plan_sha256") and fact["plan_sha256"] != plan_sha:
                issues.append({"type": "plan_drift", "round": rnd.get("round"),
                               "tp_id": tp_id,
                               "recorded": fact["plan_sha256"],
                               "current": plan_sha})
            entry = plan_by_tp.get(tp_id)
            if fact.get("entry_sha256") and entry is not None \
                    and fact["entry_sha256"] != _entry_sha(entry):
                issues.append({"type": "entry_drift", "round": rnd.get("round"),
                               "tp_id": tp_id})
    return issues
