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
    # ── 证据闭环（stage=report：先只报告，存量债务不大面积误杀）──
    "claim_confirmed_without_evidence": {
        "level": WARNING, "title": "Claim 已确认但没有证据"},
    "claim_from_agent_confirmed": {
        "level": WARNING, "title": "Agent 结论被当作已确认事实"},
    "unapproved_high_risk_action": {
        "level": WARNING, "title": "高风险动作没有审批记录"},
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
        # M3：规则可**关掉**（存量债务 / 新规则灰度），不用改代码
        if item.get("enabled") is False:
            entry["enabled"] = False
    return rules


def load_declarative(path: str | Path = RULE_FILE) -> List[Dict[str, Any]]:
    """`gates.yaml` 的 `declarative:` 段 —— **纯 YAML 规则**（M3）。

    一条规则 = 数据源 + 匹配条件 + 级别 + 文案：

        - id: CASE_REQUIREMENTS_EMPTY
          level: warning
          source: case_groups
          where: {requirements: empty}
          target: "{group}"
          message: "覆盖率组 {group} 没有 requirements"

    新增这类规则只改 YAML；复杂判据（集合比对等）仍留在 Python 里按 id 注册。
    """
    try:
        doc = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except (OSError, ValueError):
        return []
    out = []
    for item in (doc.get("declarative") or []) if isinstance(doc, dict) else []:
        if isinstance(item, dict) and str(item.get("id") or "").strip():
            out.append(dict(item))
    return out


def rules_table(rules: Dict[str, Dict[str, str]]) -> List[Dict[str, str]]:
    """规则表（CLI/CI 用）—— 每条规则的级别、阶段、是否启用。"""
    return [{"id": rid, "level": str(spec.get("level") or WARNING),
             "stage": str(spec.get("stage") or "block"),
             "enabled": spec.get("enabled", True) is not False,
             "title": str(spec.get("title") or rid)}
            for rid, spec in sorted(rules.items())]


def _emit(out: Dict[str, List[Dict[str, Any]]], rules: Dict[str, Dict[str, str]],
          rule: str, target: str, message: str, **extra: Any) -> None:
    spec = rules.get(rule) or {"level": WARNING, "title": rule}
    if spec.get("enabled") is False:
        return                      # 规则被 YAML 关掉：不产出、不占位
    level = spec.get("level", WARNING)
    # `stage: report` = 只报告不阻断（存量债务上线期的安全阀）
    if level == BLOCKER and spec.get("stage") == "report":
        level = WARNING
    out.setdefault(level, []).append({
        "rule": rule, "rule_id": rule, "title": spec.get("title", rule),
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


_WAIVER_FIELDS = ("id", "owner", "approver", "reason", "expires")


def _check_waivers(out, rules, case: Dict[str, Any]) -> None:
    """豁免必须完整且未过期；没有审批人的"不适用"不算豁免。"""
    from datetime import date

    cid = str(case.get("id") or "<case>")
    for item in case.get("waivers") or []:
        if not isinstance(item, dict):
            continue
        missing = [k for k in _WAIVER_FIELDS
                   if not str(item.get(k) or "").strip()]
        if missing:
            _emit(out, rules, "waiver_incomplete", cid,
                  f"豁免 {item.get('id') or '?'} 缺少字段：{missing}")
        expires = str(item.get("expires") or "")
        try:
            if expires and date.fromisoformat(expires) < date.today():
                _emit(out, rules, "waiver_expired", cid,
                      f"豁免 {item.get('id')} 已于 {expires} 过期")
        except ValueError:
            _emit(out, rules, "waiver_invalid_date", cid,
                  f"豁免 {item.get('id')} 的 expires 不是 ISO 日期：{expires}")


def _check_closure(out, rules, closure: Dict[str, Any]) -> None:
    """`coverage/case_closure.json` 的引用闭合错误 → 门禁（blocker/warning）。"""
    for item in (closure or {}).get("errors") or []:
        if not isinstance(item, dict):
            continue
        rid = str(item.get("rule") or "closure_error")
        _emit(out, rules, rid, str(item.get("target") or "?"),
              str(item.get("message") or rid))
    for item in (closure or {}).get("warnings") or []:
        if not isinstance(item, dict):
            continue
        rid = str(item.get("rule") or "closure_warning")
        _emit(out, rules, rid, str(item.get("target") or "?"),
              str(item.get("message") or rid))


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
        # 业务表说"该测这个"，却没绑 dimensions/tests → 落不到任何执行实例。
        # 这是**业务意图与证据的脱节**；不能只当 warning（否则"没绑也能签"）。
        if not (case.get("dimensions") or case.get("tests")):
            _emit(out, rules, "case_without_binding", cid or "<case>",
                  "用例没有 dimensions/tests 绑定 —— 落不到任何可执行实例")
        _check_waivers(out, rules, case)
        _check_contract_items(out, rules, case)
        for rec in by_case.get(str(case.get("id") or "")) or []:
            _check_contract_evidence(out, rules, case, rec)


#: 规则数据源：`source:` 写哪个 key，就取哪张表。
_MISSING = object()


def _value_of(item: Dict[str, Any], key: str) -> Any:
    cur: Any = item
    for part in str(key).split("."):
        if not isinstance(cur, dict):
            return _MISSING
        cur = cur.get(part, _MISSING)
    return cur


def _test(value: Any, op: str, spec: Any) -> bool:
    blank = value is _MISSING or value in (None, "", [], {})
    if op == "missing":
        return value is _MISSING or value in (None, "")
    if op == "present":
        return not (value is _MISSING or value in (None, ""))
    if op == "empty":
        return blank
    if op == "nonempty":
        return not blank
    if op == "eq":
        return value is not _MISSING and value == spec
    if op == "ne":
        return value is _MISSING or value != spec
    if op in ("in", "any"):
        return value in (spec or [])
    return False


def _match(item: Dict[str, Any], where: Dict[str, Any]) -> bool:
    for key, spec in (where or {}).items():
        if isinstance(spec, dict) and "op" in spec:
            op, spec = str(spec.get("op") or "eq"), spec.get("value")
        else:
            op = "eq"
        if not _test(_value_of(item, key), op, spec):
            return False
    return True


def _render(template: Any, item: Dict[str, Any]) -> str:
    try:
        return str(template or "").format(
            **{k: ("" if v is _MISSING else v)
               for k, v in item.items() if isinstance(k, str)})
    except (KeyError, IndexError, ValueError):
        return str(template or "")


def _default_target(item: Dict[str, Any]) -> str:
    for key in ("id", "case", "cell_id", "tp_id", "group", "evd_id", "task"):
        if item.get(key):
            return str(item[key])
    return "?"


def _rule_sources(view, cells, evd, case_ir, case_cov) -> Dict[str, List[Dict[str, Any]]]:
    groups: List[Dict[str, Any]] = []
    for case in (case_ir or {}).get("cases") or []:
        if not isinstance(case, dict):
            continue
        for group in case.get("groups") or []:
            if isinstance(group, dict):
                groups.append({**group, "case": case.get("id")})
    return {"case_cases": [c for c in (case_ir or {}).get("cases") or []
                           if isinstance(c, dict)],
            "case_groups": groups, "case_cov": list(case_cov or []),
            "cells": _cells(cells), "evd": _evd(evd),
            "view_cases": _case_rows(view)}


def _declarative_findings(declarative: List[Dict[str, Any]],
                          sources: Dict[str, List[Dict[str, Any]]],
                          out: Dict[str, List[Dict[str, Any]]],
                          rules: Dict[str, Dict[str, str]]) -> None:
    """`gates.yaml` 的 `declarative:` —— 纯 YAML 规则（新增规则不必改代码）。"""
    for rule in declarative or []:
        rid = str(rule.get("id") or "")
        items = sources.get(str(rule.get("source") or "")) or []
        for item in items:
            if not _match(item, rule.get("where") or {}):
                continue
            target = (_render(rule.get("target") or "", item)
                      or _default_target(item))
            evidence = {k: item.get(k) for k in (rule.get("evidence") or [])}
            _emit(out, rules, rid, target,
                  _render(rule.get("message") or rid, item),
                  source=str(rule.get("source") or ""), evidence=evidence)


def validate_case_view(view: Dict[str, Any], cells: Dict[str, Any],
                       evd: Dict[str, Any],
                       rules: Optional[Dict[str, Dict[str, str]]] = None,
                       *, run: str = "", case_ir: Dict[str, Any] = None,
                       case_cov: List[Dict[str, Any]] = None,
                       case_closure: Dict[str, Any] = None,
                       declarative: List[Dict[str, Any]] = None) -> Dict[str, Any]:
    """生成物 → `case_gates_v1`（含三集合完整性 + 声明式规则）。"""
    rules = rules or load_rules()
    for rule in declarative or []:
        rid = str(rule.get("id") or "")
        if rid:
            entry = rules.setdefault(rid, {"level": WARNING, "title": rid})
            level = str(rule.get("level") or "").strip()
            if level in _LEVELS:
                entry["level"] = level
            entry.setdefault("title", str(rule.get("title") or rid))
            if rule.get("stage"):
                entry["stage"] = str(rule["stage"])
            if rule.get("enabled") is False:
                entry["enabled"] = False
    out: Dict[str, List[Dict[str, Any]]] = {BLOCKER: [], WARNING: [], INFO: []}
    _check_identity(out, rules, view, cells)
    _check_cells(out, rules, cells, view)
    _check_evd(out, rules, evd, view)
    if case_ir:
        _check_contracts(out, rules, case_ir, case_cov or [])
    if case_closure:
        _check_closure(out, rules, case_closure)
    _declarative_findings(
        declarative or [], _rule_sources(view, cells, evd, case_ir, case_cov),
        out, rules)
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


def _audit_rows(root: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    try:
        text = (root / "docs" / "action_audit.jsonl").read_text(
            encoding="utf-8", errors="replace")
    except OSError:
        return rows
    for line in text.splitlines():
        try:
            rec = json.loads(line) if line.strip() else {}
        except ValueError:
            continue
        if isinstance(rec, dict):
            rows.append(rec)
    return rows


def _check_evidence_claims(root: Path, rules: Dict[str, Dict[str, str]]
                           ) -> Dict[str, List[Dict[str, Any]]]:
    """Claim 证据覆盖 + 高风险动作审批（只报告，不改判定）。"""
    out: Dict[str, List[Dict[str, Any]]] = {BLOCKER: [], WARNING: [], INFO: []}
    claims = _read_json(root / "coverage" / "claims.json")
    index = _read_json(root / "docs" / "evidence_index.json")
    claim_index = index.get("claims") or {}
    for claim in claims.get("claims") or []:
        if not isinstance(claim, dict) or claim.get("status") != "CONFIRMED":
            continue
        cid = str(claim.get("claim_id") or "")
        if not ((claim_index.get(cid) or {}).get("evidence_ids") or []):
            _emit(out, rules, "claim_confirmed_without_evidence", cid,
                  "claim 标记为 CONFIRMED，但证据库里没有对应证据")
        if str(claim.get("producer_class") or "") == "agent":
            _emit(out, rules, "claim_from_agent_confirmed", cid,
                  "agent 产出的结论被标记为 CONFIRMED —— 需人工/引擎证据晋升")
    rows = _audit_rows(root)
    approved = {str(r.get("action")) for r in rows
                if r.get("decision") == "APPROVAL" and r.get("appr_id")}
    high = {str(r.get("action")) for r in rows if r.get("risk") == "HIGH"}
    for action in sorted(high - approved):
        _emit(out, rules, "unapproved_high_risk_action", action,
              "高风险动作出现在审计里，但没有审批记录")
    return out


def _merge_evidence_findings(root: Path, data: Dict[str, Any],
                             rules: Dict[str, Dict[str, str]]) -> None:
    extra = _check_evidence_claims(root, rules)
    for level, key in ((BLOCKER, "blockers"), (WARNING, "warnings"),
                       (INFO, "infos")):
        data[key] = list(data.get(key) or []) + extra[level]
    counts = {level: len(data[key]) for level, key in
              ((BLOCKER, "blockers"), (WARNING, "warnings"), (INFO, "infos"))}
    data["counts"] = {**counts, "total": sum(counts.values())}
    data["verdict"] = "BLOCKED" if counts[BLOCKER] else "PASS"


def write_gates(od: str | Path, *,
                rules: Optional[Dict[str, Any]] = None,
                rule_file: str | Path = RULE_FILE) -> Dict[str, Any]:
    """从 run 目录读生成物 → 写 `coverage/gates.json`（规则表 + 声明式规则）。"""
    root = Path(od)
    cov = root / "coverage"
    view = _read_json(cov / "case_view.json")
    cells = _read_json(cov / "cell_matrix.json")
    evd = _read_json(cov / "evd.json")
    case_ir = _read_json(cov / "case_ir.json")
    case_closure = _read_json(cov / "case_closure.json")
    rules = rules or load_rules(rule_file)
    data = validate_case_view(view, cells, evd, rules, run=root.name,
                              case_ir=case_ir, case_cov=_case_cov_records(root),
                              case_closure=case_closure,
                              declarative=load_declarative(rule_file))
    # 证据闭环：claim 覆盖 / 高风险动作审批（默认 warning，不改判定）
    _merge_evidence_findings(root, data, rules)
    try:
        from src.core.runtime.atomic import atomic_write_json

        atomic_write_json(cov / "gates.json", data)
    except OSError:
        pass
    return data


__all__ = [
    "BLOCKER", "DEFAULT_RULES", "INFO", "RULE_FILE", "SCHEMA", "WARNING",
    "load_rules", "validate_case_view", "write_gates",
]
