"""TP Cov 证据视图 —— **一个功能契约的四层证据链，汇聚到一处**。

## 为什么要这张视图

覆盖率报告里的 bin 命中，只回答"这个场景发生过吗"。一个功能契约要被判定为
**验证完成**，需要四类证据（**按契约判定，不是按单个用例判定**）：

    功能覆盖   场景发生过吗？          coverpoint / cross bin 命中
    时序断言   时序行为对吗？          SVA / DUT_CHK（握手、start/done/rls、反压保持）
    数据比对   数据/资源结果对吗？     scoreboard（数据、tag、SPAD/寄存器、不丢不重）
    路径覆盖   整条生命周期走通了吗？  PATH 组（cmd_hs → … → rsp/rls）

一个用例可以只提供其中一部分，多个用例合起来构成完整证据链；**bin 命中
不能单独签核功能**。这张视图把四层按 `tp_id` 汇聚，并明确写出每一层
"证明了什么 / 不证明什么"。

## 数据来源（全部已落盘，不重跑生成器 / vcover / 仿真）

    coverage/testpoints.yaml            TP 身份
    coverage/tp_matrix.json             每 TP 的合并命中 + 逐用例签核字段
    coverage/case_tp.json               用例 ↔ TP（含 signed_off_by / wave / timing）
    coverage/case_cov/**/*.json         逐用例事实（SCB / DUT_CHK / timing / bin hits）
    coverage/coverage_plan.yaml         功能覆盖点 / 交叉 / PATH 组
    sim/coverage/coverage_result.json   实测 covergroup / cross 百分比
    waves/manifest.json                 波形 ↔ 用例
    coverage/methodology.json           TP IR 哈希

产物：`coverage/tp_cov_evidence.json`（schema `tp_cov_evidence_v1`）。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

SCHEMA = "tp_cov_evidence_v1"

#: 四层证据的固定顺序与含义 —— 视图、文档、评审话术共用这一份。
LAYERS = (
    ("functional", "功能覆盖", "这个场景发生过吗？",
     "激励和状态到达，coverpoint / cross 的 bin 命中",
     "只证明场景被激励到；不证明时序、数据、路径正确"),
    ("timing", "时序断言", "时序行为对吗？",
     "SVA / DUT_CHK 逐拍检查握手、start/done/rls、反压保持正确",
     "只证明时序契约；不证明数据结果或整条路径走通"),
    ("data", "数据比对", "数据/资源结果对吗？",
     "scoreboard 比对数据、tag、SPAD/寄存器统计，不丢不重",
     "只证明比对覆盖到的数据；不证明没声明要查的字段"),
    ("path", "路径覆盖", "整条生命周期走通了吗？",
     "PATH 组的端到端阶段序列命中，且该路径绑定的检查项全部通过",
     "没有 PATH 组 = 没证明；功能组 100% 不能替代"),
)

_STATUS_RANK = {"VERIFIED": 3, "PROVEN": 3, "PARTIAL": 2,
                "PENDING_BACKEND": 1, "NOT_APPLICABLE": 1,
                "MISSING": 0, "UNMAPPED": 0, "NOT_VERIFIED": 0}


# ────────────────────────────────────────────────────────────────
# 读盘
# ────────────────────────────────────────────────────────────────

def _read_json(path: Path) -> Dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _read_yaml(path: Path) -> Dict[str, Any]:
    try:
        import yaml as _yaml
        doc = _yaml.safe_load(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _read_testpoints(od: Path) -> List[Dict[str, Any]]:
    from src.tools.common.lib.collect_real_coverage import _read_testpoints as _rt
    return [tp for tp in _rt(od) if isinstance(tp, dict)]


def _case_records(od: Path) -> Dict[str, Dict[str, Any]]:
    """逐用例事实：`{task: case_cov_v1}`（缓存文件是 `.json.cache`，不会混进来）。"""
    root = od / "coverage" / "case_cov"
    out: Dict[str, Dict[str, Any]] = {}
    if not root.is_dir():
        return out
    for path in sorted(root.rglob("*.json")):
        rec = _read_json(path)
        task = str(rec.get("task") or "")
        if task and rec.get("schema") == "case_cov_v1":
            out[task] = rec
    return out


def _matrix_rows(matrix: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {str(r.get("tp_id")): r for r in (matrix.get("rows") or [])
            if isinstance(r, dict) and r.get("tp_id")}


def _owner_tasks(by_tp: Dict[str, Any], row: Dict[str, Any]) -> List[str]:
    """这个 TP 由哪些用例提供证据（`case_tp.cases` → owner_case 兜底）。"""
    tasks = [str(c.get("task")) for c in (by_tp.get("cases") or [])
             if isinstance(c, dict) and c.get("task")]
    if not tasks:
        owner = str(by_tp.get("owner_case") or row.get("owner_case") or "")
        tasks = [owner] if owner else []
    return list(dict.fromkeys(tasks))


def _case_facts(tp_id: str, tasks: List[str],
                records: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """每条用例的**与这个 TP 相关**的事实（bin / SCB / 断言 / timing）。"""
    out = []
    for task in tasks:
        rec = records.get(task) or {}
        if not rec:
            continue
        entry = next((e for e in (rec.get("tp") or [])
                      if isinstance(e, dict) and e.get("tp_id") == tp_id), {})
        out.append({
            "task": task, "test": rec.get("test"), "seed": rec.get("seed"),
            "stage": rec.get("stage"), "wave": rec.get("wave", ""),
            "entry": entry,
            # `case_cov` 里 `scb` 是三集合证据、`scb_summary` 才是 [SCB_DUT] 汇总
            "scb": rec.get("scb_summary") or
                   (rec.get("scb") if isinstance(rec.get("scb"), dict) else {}),
            "groups": rec.get("groups") or [],
            "sva": rec.get("sva") or [],
            "case_status": rec.get("case_status", ""),
            "assertions": rec.get("assertions") or {},
            "timing_ok": rec.get("timing_ok"),
            "uvm_errors": rec.get("uvm_errors", 0),
        })
    return out


# ────────────────────────────────────────────────────────────────
# 四层
# ────────────────────────────────────────────────────────────────

def _layer_functional(tp: Dict[str, Any], row: Dict[str, Any],
                      cases: List[Dict[str, Any]]) -> Dict[str, Any]:
    owned = list(row.get("bins") or [])
    if not owned and tp.get("bin"):
        owned = [str(tp["bin"])]
    hits = dict(row.get("bin_hits") or {})
    if not owned:
        status = "NOT_APPLICABLE"
    elif all((hits.get(b) or 0) > 0 for b in owned):
        status = "PROVEN"
    elif any((hits.get(b) or 0) > 0 for b in owned):
        status = "PARTIAL"
    elif owned and all(hits.get(b) is None for b in owned):
        status = "UNMAPPED"
    else:
        status = "MISSING"
    supporting = [c["task"] for c in cases
                  if c["entry"] and all((c["entry"].get("hits", {}).get(b) or 0) > 0
                                        for b in owned)]
    return {
        "status": status,
        "proves": "该场景被激励到（bin 命中）" if status == "PROVEN" else "未完整证明",
        "source": {"coverpoint": row.get("coverpoint") or tp.get("coverpoint"),
                   "owned_bins": owned, "bin_hits": hits,
                   "supporting_cases": supporting},
    }


def _layer_timing(tp: Dict[str, Any], cases: List[Dict[str, Any]]) -> Dict[str, Any]:
    rules = sum(int((c["assertions"] or {}).get("rules") or 0) for c in cases)
    fired = sum(int((c["assertions"] or {}).get("fired") or 0) for c in cases)
    declared = bool(tp.get("timing"))
    checked = [c for c in cases if c.get("timing_ok") is not None]
    violated = [c["task"] for c in checked if c["timing_ok"] is False]
    if not rules and not checked and not declared:
        status = "NOT_APPLICABLE"
    elif fired == 0 and not violated and (rules or checked):
        status = "PROVEN"
    elif fired or violated:
        status = "MISSING"
    else:
        status = "PARTIAL"
    return {
        "status": status,
        "proves": "握手/协议/保持时序正确" if status == "PROVEN" else "时序未被完整证明",
        "source": {"assertion_rules": rules, "fired": fired,
                   "timing_declared": declared,
                   "timing_checked_cases": [c["task"] for c in checked],
                   "timing_violations": violated,
                   "uvm_errors": sum(int(c.get("uvm_errors") or 0) for c in cases)},
    }


def _layer_data(tp: Dict[str, Any], cases: List[Dict[str, Any]]) -> Dict[str, Any]:
    scb_cases = [c for c in cases if (c["scb"] or {}).get("matched") is not None]
    matched = sum(int((c["scb"] or {}).get("matched") or 0) for c in scb_cases)
    mismatched = sum(int((c["scb"] or {}).get("mismatched") or 0) for c in scb_cases)
    if not scb_cases:
        status = "NOT_APPLICABLE"
    elif mismatched == 0 and matched > 0:
        status = "PROVEN"
    else:
        status = "MISSING"
    return {
        "status": status,
        "proves": "数据/资源比对通过（不丢不重）" if status == "PROVEN"
                  else "数据结果未被完整比对",
        "source": {"scb_cases": [c["task"] for c in scb_cases],
                   "matched": matched, "mismatched": mismatched},
    }


def _plan_paths(plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [p for p in (plan.get("paths") or []) if isinstance(p, dict)]


def _path_entry(tp: Dict[str, Any], plan: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    for group in _plan_paths(plan):
        for bin_ in group.get("bins") or []:
            if isinstance(bin_, dict) and bin_.get("name") == tp.get("bin"):
                return {"group": group, "bin": bin_}
    return None


def _layer_path(tp: Dict[str, Any], row: Dict[str, Any],
                plan: Dict[str, Any], by_tp: Dict[str, Any]) -> Dict[str, Any]:
    hit = _path_entry(tp, plan)
    kind = str((tp.get("realization") or {}).get("kind") or "")
    if hit is None:
        if kind == "sequence":
            return {"status": "NOT_APPLICABLE",
                    "proves": "有序列/定向实现，但**没有声明 PATH 组** —— "
                              "只提供部分路径证据，不构成路径覆盖",
                    "source": {"realization": kind,
                               "note": "补 `path_groups:` 才能把路径单独度量"}}
        return {"status": "NOT_APPLICABLE", "proves": "该契约不是路径型",
                "source": {}}
    group, bin_ = hit["group"], hit["bin"]
    signed = bool(by_tp.get("signed_off"))
    if str((tp.get("execution") or {}).get("stage")) == "behavior":
        status = "PENDING_BACKEND"
    elif signed:
        status = "PROVEN"
    elif (row.get("hits") or 0) > 0:
        status = "PARTIAL"
    else:
        status = "MISSING"
    return {
        "status": status,
        "proves": "端到端生命周期走通且绑定检查项通过" if status == "PROVEN"
                  else ("PATH 组已声明，执行后端待接" if status == "PENDING_BACKEND"
                        else "路径未证明"),
        "source": {"path_group": group.get("id"), "path_bin": bin_.get("name"),
                   "sequence": list(bin_.get("sequence") or []),
                   "checks": list(bin_.get("checks") or []),
                   "timing": dict(bin_.get("timing") or {}),
                   "signed_off_by": by_tp.get("signed_off_by", "")},
    }


def _contract_status(layers: Dict[str, Dict[str, Any]], tp: Dict[str, Any]) -> str:
    """四层证据 → 功能契约状态。

    **判据在 `verification_os.derive.tp_contract_status`（唯一实现）**，这里只
    传递 stage：bin 命中不能单独签核功能，要 VERIFIED 必须四层齐（见那里的
    docstring）。M2 起 `tp_evidence` 不再自己算这套规则。
    """
    from src.layers.l3_decision.contract.derive import tp_contract_status

    stage = str((tp.get("execution") or {}).get("stage") or "")
    return tp_contract_status(layers, stage)


def _tp_evidence(tp: Dict[str, Any], row: Dict[str, Any], by_tp: Dict[str, Any],
                 records: Dict[str, Dict[str, Any]],
                 plan: Dict[str, Any]) -> Dict[str, Any]:
    tasks = _owner_tasks(by_tp, row)
    cases = _case_facts(str(tp.get("tp_id") or ""), tasks, records)
    layers = {
        "functional": _layer_functional(tp, row, cases),
        "timing": _layer_timing(tp, cases),
        "data": _layer_data(tp, cases),
        "path": _layer_path(tp, row, plan, by_tp),
    }
    return {
        "tp_id": tp.get("tp_id"),
        "requirement": tp.get("requirement") or "",
        "dimension": tp.get("dimension"),
        "dimension_name": tp.get("dimension_name") or "",
        "value": tp.get("value"),
        "domain": ("path" if str(tp.get("dimension")) == "PATH"
                   else ("behavior" if str((tp.get("execution") or {}).get("stage"))
                         == "behavior" else "attribute")),
        "realization": tp.get("realization") or {},
        "execution": tp.get("execution") or {},
        "coverpoint": tp.get("coverpoint") or "",
        "bin": tp.get("bin") or "",
        "contract_status": _contract_status(layers, tp),
        "signed_off": bool(row.get("signed_off") or by_tp.get("signed_off")),
        "signed_off_by": row.get("signed_off_by") or by_tp.get("signed_off_by") or "",
        "wave": by_tp.get("wave") or "",
        "evidence_layers": layers,
        "cases": [{"task": c["task"], "seed": c["seed"], "test": c["test"],
                   "stage": c["stage"], "status": (c["entry"] or {}).get("status"),
                   "pct": (c["entry"] or {}).get("pct"),
                   "timing_ok": c.get("timing_ok")}
                  for c in cases],
    }


# ────────────────────────────────────────────────────────────────
# 分组 / 摘要 / 评审答案
# ────────────────────────────────────────────────────────────────

def _functional_groups(coverage: Dict[str, Any]) -> List[Dict[str, Any]]:
    detail = ((coverage.get("coverage") or {}).get("functional_detail")
              or coverage.get("functional_detail") or {})
    return [dict(g) for g in (detail.get("covergroups") or []) if isinstance(g, dict)]


def _cross_groups(plan: Dict[str, Any],
                  functional: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    measured = {}
    for group in functional:
        for cx in group.get("crosses") or []:
            if isinstance(cx, dict) and cx.get("name"):
                measured[cx["name"]] = cx.get("actual")
    out = []
    for cx in plan.get("crosses") or []:
        if not isinstance(cx, dict):
            continue
        out.append({
            "name": cx.get("name"), "dimensions": list(cx.get("dimensions") or []),
            "bins": len(cx.get("bins") or []), "actual": measured.get(cx.get("name")),
            "cover_id": cx.get("cover_id") or "", "requirement": cx.get("requirement") or "",
            "kind": "cross",
        })
    return out


def _path_groups(plan: Dict[str, Any], by_tp: Dict[str, Any],
                 rows: Dict[str, Dict[str, Any]],
                 tps: List[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    out = []
    for group in _plan_paths(plan):
        bins = []
        for bin_ in group.get("bins") or []:
            if not isinstance(bin_, dict):
                continue
            # TP 身份优先按 (coverpoint, bin) 从 testpoints 里对 —— PATH TP
            # 的 `by_tp` 可能还没有 cases（后端待接），不能只靠它反查。
            path_tp = next((t for t in (tps or [])
                            if t.get("coverpoint") == group.get("coverpoint")
                            and t.get("bin") == bin_.get("name")), {})
            tp_id = str(path_tp.get("tp_id") or "")
            if not tp_id:
                tp_id = next((tid for tid, v in by_tp.items()
                              if v.get("owned_bins")
                              and bin_.get("name") in v["owned_bins"]), "")
            row = rows.get(tp_id) or {}
            bins.append({
                "name": bin_.get("name"), "sequence": list(bin_.get("sequence") or []),
                "checks": list(bin_.get("checks") or []),
                "requirement": bin_.get("requirement") or "",
                "tp_id": tp_id, "status": row.get("status") or "PENDING_BACKEND",
                "signed_off": bool(row.get("signed_off")),
                "signed_off_by": row.get("signed_off_by") or "",
            })
        out.append({"id": group.get("id"), "name": group.get("name"),
                    "coverpoint": group.get("coverpoint"),
                    "sample": group.get("sample"),
                    "groups": list(group.get("groups") or []),
                    "bins": bins, "bin_count": len(bins), "kind": "path"})
    return out


def _layer_summary(tps: List[Dict[str, Any]]) -> Dict[str, Any]:
    out = {key: {"PROVEN": 0, "PARTIAL": 0, "MISSING": 0,
                 "UNMAPPED": 0, "NOT_APPLICABLE": 0, "PENDING_BACKEND": 0}
           for key, *_rest in LAYERS}
    for tp in tps:
        for key in out:
            status = str((tp.get("evidence_layers") or {}).get(key, {}).get("status"))
            out[key][status] = out[key].get(status, 0) + 1
    return out


def _review(plan: Dict[str, Any], tps: List[Dict[str, Any]],
            path_groups: List[Dict[str, Any]]) -> Dict[str, Any]:
    proof = []
    for group in path_groups:
        for bin_ in group.get("bins") or []:
            proof.append({
                "group": group.get("id"), "bin": bin_.get("name"),
                "tp_id": bin_.get("tp_id"), "sequence": bin_.get("sequence"),
                "checks": bin_.get("checks"), "status": bin_.get("status"),
                "signed_off": bin_.get("signed_off"),
                "signed_off_by": bin_.get("signed_off_by"),
            })
    return {
        "question": "每组都 100% 了，怎么证明一条完整指令路径是通的？",
        "answer": ("功能组的 100% 只证明每个功能契约的取值/场景都打到了；"
                   "路径通不通由 PATH 组 + 绑定的 SVA/SCB 单独证明。"
                   "四类证据按功能契约汇聚，不按单个用例：一个用例提供一部分，"
                   "多个用例合起来构成完整证据链。"),
        "four_layers": [{"key": k, "name": n, "question": q, "proves": p,
                         "does_not_prove": d}
                        for k, n, q, p, d in LAYERS],
        "path_proof": proof,
        "path_backend": ("pending" if any(b.get("status") == "PENDING_BACKEND"
                                          for b in proof) else "active"),
        "cross_architecture": {
            "source": "casemodel.cross_matrix / cross_groups / policy_pack.coverage_bins",
            "render": ("CoverageModel.crosses → covergroup `cross_<name>`（cg_<agent> "
                       "或 cg_mixed）→ ucdb 的 cross 覆盖"),
            "evidence": ("本视图 groups.cross_groups：名字 / 维度 / bin 数 / 实测 %；"
                         "每个 TP 的 crosses 归属"),
            "does_not_prove": ("交叉只证明组合发生过；组合在正确时序/数据下发生，"
                               "仍由 timing（SVA/DUT_CHK）与 data（SCB）两层证明"),
        },
    }


# ────────────────────────────────────────────────────────────────
# 门面
# ────────────────────────────────────────────────────────────────

def build_tp_evidence(od: str | Path) -> Dict[str, Any]:
    """读一次运行的全部落盘证据 → `tp_cov_evidence_v1`（不写盘）。"""
    od = Path(od)
    tps = _read_testpoints(od)
    matrix = _read_json(od / "coverage" / "tp_matrix.json")
    case_tp = _read_json(od / "coverage" / "case_tp.json")
    plan = _read_yaml(od / "coverage" / "coverage_plan.yaml")
    coverage = _read_json(od / "sim" / "coverage" / "coverage_result.json")
    methodology = _read_json(od / "coverage" / "methodology.json")
    rows = _matrix_rows(matrix)
    by_all = case_tp.get("by_tp") or {}
    records = _case_records(od)
    functional = _functional_groups(coverage)
    cross_groups = _cross_groups(plan, functional)
    path_groups = _path_groups(plan, by_all, rows, tps)

    evid = [_tp_evidence(tp, rows.get(str(tp.get("tp_id")), {}),
                         by_all.get(str(tp.get("tp_id")), {}), records, plan)
            for tp in tps]
    counts = {s: sum(1 for t in evid if t["contract_status"] == s)
              for s in ("VERIFIED", "PARTIAL", "NOT_VERIFIED", "PENDING_BACKEND")}
    return {
        "schema": SCHEMA,
        "run": od.name,
        "module": "",
        "testpoint_ir_sha256": ((methodology.get("artifacts") or {})
                                .get("testpoints_yaml") or {}).get("sha256", ""),
        "counts": counts,
        "evidence_layers": _layer_summary(evid),
        "groups": {
            "functional": functional,
            "path": path_groups,
            "cross": cross_groups,
        },
        "tps": evid,
        "review": _review(plan, evid, path_groups),
        "sources": {
            "testpoints": "coverage/testpoints.yaml",
            "tp_matrix": "coverage/tp_matrix.json",
            "case_tp": "coverage/case_tp.json",
            "case_cov": "coverage/case_cov/**/*.json",
            "coverage_plan": "coverage/coverage_plan.yaml",
            "coverage_result": "sim/coverage/coverage_result.json",
            "wave_manifest": "waves/manifest.json",
        },
    }


def write_tp_evidence(od: str | Path) -> Dict[str, Any]:
    """构建并落盘 `coverage/tp_cov_evidence.json`；返回 payload（落盘失败也返回）。"""
    od = Path(od)
    payload = build_tp_evidence(od)
    path = od / "coverage" / "tp_cov_evidence.json"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                        encoding="utf-8", newline="\n")
    except OSError:
        pass
    return payload


def load_tp_evidence(od: str | Path) -> Dict[str, Any]:
    """读已落盘的 `tp_cov_evidence.json`；没有就**现建一份内存版**（不写盘）。"""
    od = Path(od)
    doc = _read_json(od / "coverage" / "tp_cov_evidence.json")
    return doc if doc.get("schema") == SCHEMA else build_tp_evidence(od)
