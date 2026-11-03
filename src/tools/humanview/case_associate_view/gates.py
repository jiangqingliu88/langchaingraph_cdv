"""Case Gate —— **blocker / warning / info** 三级门禁。

为什么从 `audit` 里独立出来：门禁规则要能被 **CI 单独调用**（`vagent coverage
case-gate`），也要能被 Workbench 顶部状态条消费；写在 audit 的 `_caveat(...)`
里只能得到"结论"，拿不到"规则"。audit 现在改为**消费**这里的结果。

规则表在 `gates.yaml`（`RULE_VER` 随文件走），本模块只负责：
  1. 从 `case_view` / `cell_matrix` / `evd` 三个生成物里**取事实**；
  2. 按规则表判级；
  3. 输出 `case_gates_v1`（blockers / warnings / infos + 覆盖计数）。

**首版止损**：所有 blocker 规则默认先在 `gates.yaml` 里降成 `warning`
（`stage: report`），跑一周统计后再逐条升级（`stage: block`）。误杀存量债务
比漏报更贵——它会让整条流水线被一条历史遗留挡住。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

SCHEMA = "case_gates_v1"
RULE_FILE = Path(__file__).with_name("gates.yaml")

BLOCKER, WARNING, INFO = "blocker", "warning", "info"
_LEVELS = (BLOCKER, WARNING, INFO)

#: 规则默认级别 —— `gates.yaml` 可覆盖（按 id）。
DEFAULT_RULES: Dict[str, Dict[str, str]] = {
    "duplicate_id": {"level": BLOCKER, "title": "ID 重复"},
    "case_without_tst": {"level": BLOCKER, "title": "用例落不到可执行实例"},
    "cell_without_checker": {"level": BLOCKER, "title": "CELL 没有任何 checker"},
    "cell_red": {"level": BLOCKER, "title": "CELL 红：该证明的没证明"},
    "cell_without_case": {"level": WARNING, "title": "CELL 没有对应用例"},
    "case_without_evd": {"level": WARNING, "title": "用例没有执行证据"},
    "evd_legacy": {"level": WARNING, "title": "旧 run 无 CASE 身份"},
    "case_synthesized": {"level": INFO, "title": "用例身份是结构合成的"},
    "cell_yellow": {"level": INFO, "title": "CELL 黄：证据不完整"},
    # ── 三集合完整性（arch.md §8）──
    "CASE_GROUPS_EMPTY": {"level": BLOCKER, "title": "用例没有任何功能组"},
    "CASE_SVA_UNDECLARED": {"level": BLOCKER, "title": "用例缺 sva 字段"},
    "CASE_SCB_UNDECLARED": {"level": BLOCKER, "title": "用例缺 scb 字段"},
    "CASE_ITEM_NO_CELL": {"level": BLOCKER, "title": "三集合项缺 cell"},
    "CASE_SVA_VACUOUS": {"level": BLOCKER, "title": "SVA 空转（cover_property 未命中）"},
    "CASE_SCB_NOT_EXECUTED": {"level": BLOCKER, "title": "SCB 未执行"},
    "CASE_STATUS_OVERCLAIM": {"level": BLOCKER, "title": "用例状态越报"},
    "CASE_IR_EVIDENCE_MISMATCH": {"level": BLOCKER, "title": "契约与证据不一致"},
}


def load_rules(path: str | Path = RULE_FILE) -> Dict[str, Dict[str, str]]:
    """读 `gates.yaml`；读不到就用默认表（不因为没有配置文件而失去门禁）。"""
    rules = {k: dict(v) for k, v in DEFAULT_RULES.items()}
    try:
        doc = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except (OSError, ValueError):
        return rules
    for item in (doc.get("rules") or []) if isinstance(doc, dict) else []:
        rid = str((item or {}).get("id") or "").strip()
        if not rid:
            continue
        entry = rules.setdefault(rid, {"level": WARNING, "title": rid})
        level = str(item.get("level") or "").strip()
        if level in _LEVELS:
            entry["level"] = level
        if item.get("title"):
            entry["title"] = str(item["title"])
        if item.get("stage"):
            entry["stage"] = str(item["stage"])
    return rules


def _emit(out: Dict[str, List[Dict[str, Any]]], rules: Dict[str, Dict[str, str]],
          rule: str, target: str, message: str, **extra: Any) -> None:
    spec = rules.get(rule) or {"level": WARNING, "title": rule}
    level = spec.get("level", WARNING)
    # `stage: report` = 只报告不阻断（存量债务上线期的安全阀）
    if level == BLOCKER and spec.get("stage") == "report":
        level = WARNING
    out.setdefault(level, []).append({
        "rule": rule, "title": spec.get("title", rule),
        "target": str(target), "message": message, **extra,
    })


def _cells(cells: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [c for c in (cells.get("cells") or []) if isinstance(c, dict)]


def _evd(evd: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [e for e in (evd.get("evd") or []) if isinstance(e, dict)]


def _case_rows(view: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [c for c in (view.get("cases") or []) if isinstance(c, dict)]


def _check_identity(out, rules, view, cells) -> None:
    """身份检查**只看带了契约身份的用例**。

    `case_view.cases` 是**按执行实例**（task@seed）一行的：同一条 CASE 会被
    多条测试实例覆盖，在这里按 case_id 判重会把正常情况报成 39 条重复。
    契约 ID 的唯一性由 `case_ir` 自己校验（`_check_contract_ids`）。
    """
    for case in _case_rows(view):
        cid = str(case.get("case_id") or "")
        if not cid:
            continue                      # 批次级 test：没有契约身份，不套契约规则
        if not str(case.get("tst_id") or ""):
            _emit(out, rules, "case_without_tst", cid, "用例没有 TST 身份（落不到执行实例）")


def _check_cells(out, rules, cells, view) -> None:
    case_cells = {c for case in _case_rows(view)
                  for c in (case.get("cell_ids") or [])}
    for cell in _cells(cells):
        cid = str(cell.get("cell_id") or "")
        color = str(cell.get("color") or "")
        tps = [t for t in (cell.get("tps") or []) if isinstance(t, dict)]
        if color == "red":
            _emit(out, rules, "cell_red", cid,
                  f"{cell.get('tp_count', 0)} 条 TP 里有未验证项", reasons=cell.get("reasons"))
        elif color == "yellow":
            _emit(out, rules, "cell_yellow", cid, "证据不完整", reasons=cell.get("reasons"))
        if not _has_any_checker(tps):
            _emit(out, rules, "cell_without_checker", cid,
                  "该 CELL 的 TP 没有任何 timing/data checker 声明的证据")
        if case_cells and cid not in case_cells:
            _emit(out, rules, "cell_without_case", cid, "没有用例声明占住这个格子")


def _has_any_checker(tps: List[Dict[str, Any]]) -> bool:
    for tp in tps:
        layers = tp.get("layers") or {}
        for key in ("timing", "data", "path"):
            status = str((layers or {}).get(key) or "")
            if status not in ("", "NOT_APPLICABLE"):
                return True
    return False


def _check_evd(out, rules, evd, view) -> None:
    tst_with_evd = {str(e.get("tst_id") or "") for e in _evd(evd)}
    for case in _case_rows(view):
        tst = str(case.get("tst_id") or "")
        if tst and tst_with_evd and tst not in tst_with_evd:
            _emit(out, rules, "case_without_evd", case.get("case_id") or tst,
                  "用例没有任何执行证据（EVD）")
    legacy = [e for e in _evd(evd) if e.get("legacy")]
    if legacy:
        _emit(out, rules, "evd_legacy", f"{len(legacy)} 条 EVD",
              "这些执行的 task_meta 不是 v2 写的（缺 case_ir_sha），"
              "不参与新版本聚合；批次级 test 合法地不挂 CASE，不算 legacy")


def _case_cov_records(od: Path) -> List[Dict[str, Any]]:
    out = []
    for path in sorted((od / "coverage" / "case_cov").rglob("*.json")):
        if path.name.endswith(".cache"):
            continue
        rec = _read_json(path)
        if rec.get("case_id") or rec.get("groups") or rec.get("sva"):
            out.append(rec)
    return out


def _check_contract_items(out, rules, case: Dict[str, Any]) -> None:
    """契约侧：三集合字段必须存在、每项必须带 cell。"""
    cid = str(case.get("id") or "")
    if not case.get("groups"):
        _emit(out, rules, "CASE_GROUPS_EMPTY", cid, "groups[] 为空 —— 这条用例证明不了任何功能组")
    for key, rule in (("sva", "CASE_SVA_UNDECLARED"),
                      ("scb", "CASE_SCB_UNDECLARED")):
        if key not in case:
            _emit(out, rules, rule, cid, f"契约缺 `{key}` 字段（空也要显式写 []）")
    for key in ("groups", "sva", "scb"):
        for item in case.get(key) or []:
            if isinstance(item, dict) and not item.get("cell"):
                _emit(out, rules, "CASE_ITEM_NO_CELL", cid,
                      f"{key} 项 {item.get('group') or item.get('id') or '?'} 没有 cell")


_NOT_PROVEN = ("PROVEN", "NOT_APPLICABLE")


def _check_checker_evidence(out, rules, cid: str, rec: Dict[str, Any]) -> None:
    """空转 SVA / 未执行 SCB。"""
    for item in rec.get("sva") or []:
        if (str(item.get("status")) not in ("NOT_APPLICABLE", "MISSING")
                and item.get("cover_property_hit") == 0):
            _emit(out, rules, "CASE_SVA_VACUOUS", cid,
                  f"{item.get('id')} cover_property_hit=0（断言覆盖从未命中）")
    for item in rec.get("scb") or []:
        if str(item.get("status")) not in ("NOT_APPLICABLE", "MISSING") \
                and int(item.get("exec") or 0) == 0:
            _emit(out, rules, "CASE_SCB_NOT_EXECUTED", cid,
                  f"{item.get('id')} exec=0（scoreboard 没跑过）")


def _unproven_items(rec: Dict[str, Any]) -> List[str]:
    bad = [g.get("group") for g in rec.get("groups") or []
           if str(g.get("result")) not in _NOT_PROVEN]
    bad += [s.get("id") for s in rec.get("sva") or []
            if str(s.get("status")) not in _NOT_PROVEN]
    bad += [s.get("id") for s in rec.get("scb") or []
            if str(s.get("status")) not in _NOT_PROVEN]
    return [str(b) for b in bad if b]


def _check_contract_evidence(out, rules, case: Dict[str, Any],
                             rec: Dict[str, Any]) -> None:
    """证据侧：空转 SVA / 未执行 SCB / 状态越报 / 集合不一致。"""
    cid = str(case.get("id") or "")
    _check_checker_evidence(out, rules, cid, rec)
    if str(rec.get("case_status")) == "VERIFIED":
        bad = _unproven_items(rec)
        if bad:
            _emit(out, rules, "CASE_STATUS_OVERCLAIM", cid,
                  f"case_status=VERIFIED 但仍有未 PROVEN 项：{bad[:5]}")
    want = {str(g.get("group")) for g in case.get("groups") or []}
    got = {str(g.get("group")) for g in rec.get("groups") or []}
    if want - got:
        _emit(out, rules, "CASE_IR_EVIDENCE_MISMATCH", cid,
              f"契约里的组在证据里缺失：{sorted(want - got)[:5]}")


def _check_contracts(out, rules, case_ir: Dict[str, Any],
                     records: List[Dict[str, Any]]) -> None:
    by_case: Dict[str, List[Dict[str, Any]]] = {}
    for rec in records:
        by_case.setdefault(str(rec.get("case_id") or ""), []).append(rec)
    seen: set = set()
    for case in case_ir.get("cases") or []:
        if not isinstance(case, dict):
            continue
        cid = str(case.get("id") or "")
        if cid:
            if cid in seen:
                _emit(out, rules, "duplicate_id", cid, "契约里同一 case_id 出现多次")
            seen.add(cid)
        if case.get("source") == "synthesized":
            _emit(out, rules, "case_synthesized", cid or "<case>",
                  "该用例由模型结构合成，尚未经人设计分类")
        _check_contract_items(out, rules, case)
        for rec in by_case.get(str(case.get("id") or "")) or []:
            _check_contract_evidence(out, rules, case, rec)


def validate_case_view(view: Dict[str, Any], cells: Dict[str, Any],
                       evd: Dict[str, Any],
                       rules: Optional[Dict[str, Dict[str, str]]] = None,
                       *, run: str = "", case_ir: Dict[str, Any] = None,
                       case_cov: List[Dict[str, Any]] = None) -> Dict[str, Any]:
    """生成物 → `case_gates_v1`（含三集合完整性）。"""
    rules = rules or load_rules()
    out: Dict[str, List[Dict[str, Any]]] = {BLOCKER: [], WARNING: [], INFO: []}
    _check_identity(out, rules, view, cells)
    _check_cells(out, rules, cells, view)
    _check_evd(out, rules, evd, view)
    if case_ir:
        _check_contracts(out, rules, case_ir, case_cov or [])
    counts = {level: len(items) for level, items in out.items()}
    return {
        "schema": SCHEMA,
        "run": run,
        "readonly": True,
        "counts": {**counts, "total": sum(counts.values())},
        "blockers": out[BLOCKER],
        "warnings": out[WARNING],
        "infos": out[INFO],
        "verdict": "BLOCKED" if counts[BLOCKER] else "PASS",
        "rules": {k: dict(v) for k, v in rules.items()},
    }


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def write_gates(od: str | Path, *, rules: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """从 run 目录读生成物 → 写 `coverage/gates.json`。"""
    root = Path(od)
    cov = root / "coverage"
    view = _read_json(cov / "case_view.json")
    cells = _read_json(cov / "cell_matrix.json")
    evd = _read_json(cov / "evd.json")
    case_ir = _read_json(cov / "case_ir.json")
    data = validate_case_view(view, cells, evd, rules, run=root.name,
                              case_ir=case_ir, case_cov=_case_cov_records(root))
    try:
        (cov / "gates.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8", newline="\n")
    except OSError:
        pass
    return data


__all__ = [
    "BLOCKER", "DEFAULT_RULES", "INFO", "RULE_FILE", "SCHEMA", "WARNING",
    "load_rules", "validate_case_view", "write_gates",
]
