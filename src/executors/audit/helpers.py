"""audit 的只读摘要 / 门禁 / 证据包助手（Phase 2.2 拆分）。

从 `executors/audit/main.py` 抽出；行为不变，main 通过 import 使用。
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, List

import structlog

logger = structlog.get_logger()


def _read_constraint_status(output_dir: Path) -> Dict[str, Any]:
    """读 verify 写下的 `coverage/constraint_status.json`；读不到给空字典。

    **它比 `semantic_validations` 更可靠**：后者要等覆盖率阶段才拼出来，
    而回归失败时那个阶段会被跳过（见上面关于 caveat 的注释）。
    """
    try:
        doc = json.loads((output_dir / "coverage" / "constraint_status.json")
                         .read_text(encoding="utf-8", errors="replace"))
        return doc if isinstance(doc, dict) else {}
    except (OSError, ValueError):
        return {}


def _read_association_report(output_dir: Path) -> Dict[str, Any]:
    """读 verify 写下的 `coverage/association_report.json`；读不到给空字典。

    **读不到 = 这次没做关联校验**（老 run / verify 那一步失败了），
    于是 `hard_edge_broken` 取不到 → 不挂 caveat。那是"判不了"，不是"断了" ——
    与 `semantic_validations` 的 `None` 同一条纪律（见那里关于三态贬值的注释）。
    """
    try:
        doc = json.loads((output_dir / "coverage" / "association_report.json")
                         .read_text(encoding="utf-8", errors="replace"))
        return doc if isinstance(doc, dict) else {}
    except (OSError, ValueError):
        return {}


def _read_tp_matrix(output_dir: Path) -> Dict[str, Any]:
    """读覆盖率阶段写下的 `coverage/tp_matrix.json`；读不到给空字典。

    它是"每条测试点的覆盖仓有没有命中"的**逐条**结论。没有 = 这一轮没建
    TP IR 或没跑覆盖率 —— **判不了**，不挂 caveat（与上面两条同一纪律）。
    """
    try:
        doc = json.loads((output_dir / "coverage" / "tp_matrix.json")
                         .read_text(encoding="utf-8", errors="replace"))
        return doc if isinstance(doc, dict) else {}
    except (OSError, ValueError):
        return {}


def _read_case_tp(output_dir: Path) -> Dict[str, Any]:
    """读覆盖率阶段写下的 `coverage/case_tp.json`；读不到给空字典。

    它回答的是 **"哪条用例、哪颗 seed 证明了哪条测试点"**。没有 = 这一轮
    没做逐用例取证（老 run / 没有 TP IR）—— **判不了**，不挂
    `TP_NOT_SIGNED_OFF`（否则每个老 run 都会凭空多一条）。
    """
    try:
        doc = json.loads((output_dir / "coverage" / "case_tp.json")
                         .read_text(encoding="utf-8", errors="replace"))
        return doc if isinstance(doc, dict) else {}
    except (OSError, ValueError):
        return {}


def _case_coverage_summary(output_dir: Path, tp: Dict[str, Any]) -> Dict[str, Any]:
    """逐用例签核的**事实**（供 caveat 与证据包共用）。

    波形交叉核对用 `waves/manifest.json`（ops 收尾写的）：`tp_matrix` 说某条
    TP 由 `task@seed` 签核，manifest 必须能找到同一 task 的条目且有波形。
    找不到 → `wave_missing`；manifest 本身不存在 → `wave_index_available=False`
    （判不了，不逐条报缺口）。
    """
    from src.tools.common.lib.case_meta import read_wave_manifest

    rows = [r for r in (tp.get("rows") or []) if isinstance(r, dict)]
    attr = [r for r in rows if r.get("stage") != "behavior"]
    signed = [r for r in attr if r.get("signed_off")]
    unsigned = [r for r in attr if not r.get("signed_off")]
    required_kinds = ("stimulus", "sequence", "backdoor")
    unsigned_required = [r for r in unsigned if r.get("kind") in required_kinds]
    # 序列型时序超窗只降级为 WARN（设计稿 §6.2）—— 不算未签核，但要说出来。
    timing_warn = [r for r in attr
                   if r.get("timing_ok") is False and r.get("kind") == "sequence"]

    manifest = read_wave_manifest(output_dir)
    wave_missing = _wave_missing_for_signed(signed, manifest)

    return {
        "available": bool(attr and any("signed_off" in r for r in attr)),
        "case_tp": "coverage/case_tp.json",
        "wave_manifest": ("waves/manifest.json" if manifest else ""),
        "wave_index_available": bool(manifest),
        "signed_off": len(signed),
        "unsigned": len(unsigned),
        "unsigned_required": len(unsigned_required),
        "signed_off_pct": (round(100.0 * len(signed) / len(attr), 2)
                           if attr else 0.0),
        "unsigned_tp_ids": [r.get("tp_id") for r in unsigned][:200],
        "unsigned_required_tp_ids": [r.get("tp_id") for r in unsigned_required][:200],
        "timing_warn": len(timing_warn),
        "timing_warn_tp_ids": [r.get("tp_id") for r in timing_warn][:200],
        "wave_missing": wave_missing,
        "wave_missing_tp_ids": [x.get("tp_id") for x in wave_missing],
    }


def _wave_missing_for_signed(signed: list,
                             manifest: Dict[str, Any]) -> list:
    """已签核的 TP → 在 manifest 里找不到对应波形（或波形文件不在）的清单。

    条目在、波形却不在也算缺口（manifest 可能比波形活得久）。manifest 本身
    不存在 = 判不了 → 空列表，不逐条报缺口（三态纪律）。
    """
    if not manifest:
        return []
    indexed = {e.get("task"): e for e in (manifest.get("entries") or [])
               if isinstance(e, dict)}
    out = []
    for r in signed:
        by = str(r.get("signed_off_by") or "")
        task = by.split("@", 1)[0] if by else str(r.get("owner_case") or "")
        if task and not (indexed.get(task) or {}).get("wave_exists"):
            out.append({"tp_id": r.get("tp_id"), "signed_off_by": by})
    return out


def _apply_case_coverage_gate(output_dir: Path, tp: Dict[str, Any],
                              gates: Dict[str, Any], caveat) -> Dict[str, Any]:
    """逐用例签核门 → 写 `gates["tp_signed_off"]` + 两条 caveat。

    三态（与全文件同一纪律）：

        None  = 没有逐用例证据（老 run / 没 TP IR）→ 判不了，不挂 caveat
        True  = 有证据，且可激励/后门的 TP 全部 SIGNED_OFF
        False = 有证据，仍有未签核的 TP → `TP_NOT_SIGNED_OFF`
    """
    cc = _case_coverage_summary(output_dir, tp)
    if not cc["available"]:
        gates["tp_signed_off"] = None
        return cc
    gates["tp_signed_off"] = not bool(cc["unsigned_required"])
    if cc["unsigned_required"]:
        ids = "、".join(str(t) for t in cc["unsigned_required_tp_ids"][:8])
        more = (f" 等 {cc['unsigned_required']} 条"
                if cc["unsigned_required"] > 8 else "")
        caveat("TP_NOT_SIGNED_OFF",
               f"{cc['unsigned_required']} 条可激励/后门测试点没有"
               f"「同一条用例 + 同一次 seed」的完整证据（{ids}{more}）"
               f"—— 见 coverage/case_tp.json")
    if cc["wave_missing"]:
        caveat("TP_WAVE_MISSING",
               f"{len(cc['wave_missing'])} 条已签核测试点在"
               f" waves/manifest.json 里找不到对应波形"
               f"（签核材料不可反查）—— 见 waves/manifest.json")
    # 序列型时序超窗只降级为 WARN —— 不否决签核，但不能当没发生。
    if cc.get("timing_warn"):
        ids = "、".join(str(t) for t in cc["timing_warn_tp_ids"][:8])
        caveat("TP_TIMING_WARN",
               f"{cc['timing_warn']} 条序列型测试点的时序窗口超窗"
               f"（{ids}）—— 按设计稿只降级为 TIMING_WARN，不否决；"
               f"见 coverage/case_tp.json 的 timing_warn")
    return cc


def _apply_case_view_gates(output_dir: Path, gates: Dict[str, Any],
                           caveat) -> Dict[str, Any]:
    """Case View 门禁 → `gates["case_view"]` + `CASE_GATE_BLOCKED`。

    三态：没有 `gates.json` = 这一轮没生成（老 run），判不了就不挂 caveat；
    `verdict=PASS` = 无 blocker；`verdict=BLOCKED` = 有 blocker，逐条列前几条。
    """
    import json

    path = output_dir / "coverage" / "gates.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        gates["case_view"] = None
        return {"available": False}
    if not isinstance(data, dict) or not data.get("schema"):
        gates["case_view"] = None
        return {"available": False}
    # **签核读数以 cell_matrix 为主**（arch.md §9）：gates 是规则结论，
    # cell 是"哪个组×通路绿了"的主索引；两者都进 report。
    try:
        cell = json.loads((output_dir / "coverage" / "cell_matrix.json")
                          .read_text(encoding="utf-8", errors="replace"))
        gates["cell_matrix"] = (cell or {}).get("counts") or {}
    except (OSError, ValueError):
        gates["cell_matrix"] = None
    blockers = data.get("blockers") or []
    gates["case_view"] = not blockers
    if blockers:
        sample = "；".join(f"{b.get('rule')}@{b.get('target')}"
                          for b in blockers[:5])
        caveat("CASE_GATE_BLOCKED",
               f"Case 门禁有 {len(blockers)} 条 blocker（{sample}）"
               f"—— 逐条见 coverage/gates.json")
    return {"available": True, "verdict": data.get("verdict", ""),
            "counts": data.get("counts") or {}}


#: 三集合证据 → caveat 的判定表（arch.md §9）。顺序即输出顺序。
_CASE_CONTRACT_RULES = (
    ("CASE_GROUP_PARTIAL", "组证据不完整"),
    ("CASE_SVA_VACUOUS", "SVA 空转（cover_property 未命中）"),
    ("CASE_SCB_NOT_EXECUTED", "SCB 未执行"),
    ("CASE_PATH_PENDING_BACKEND", "PATH 后端未接"),
    ("CASE_IR_EVIDENCE_MISMATCH", "契约与证据不一致"),
)


def _case_cov_records(output_dir: Path) -> list:
    import json

    out = []
    for path in sorted((output_dir / "coverage" / "case_cov").rglob("*.json")):
        if path.name.endswith(".cache"):
            continue
        try:
            rec = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError):
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out


def _case_group_issues(groups: list) -> set:
    """组证据层面的问题码。"""
    codes = set()
    if any(str(g.get("result")) == "PARTIAL" for g in groups):
        codes.add("CASE_GROUP_PARTIAL")
    if any(str((g.get("path") or {}).get("status")) == "PENDING_BACKEND"
           for g in groups):
        codes.add("CASE_PATH_PENDING_BACKEND")
    return codes


def _case_checker_issues(rec: Dict[str, Any]) -> set:
    """SVA 空转 / SCB 未执行。"""
    codes = set()
    if any(s.get("cover_property_hit") == 0 for s in rec.get("sva") or []
           if isinstance(s, dict)):
        codes.add("CASE_SVA_VACUOUS")
    if any(int(s.get("exec") or 0) == 0 for s in rec.get("scb") or []
           if isinstance(s, dict)
           and str(s.get("status")) not in ("NOT_APPLICABLE", "MISSING")):
        codes.add("CASE_SCB_NOT_EXECUTED")
    return codes


def _case_contract_issues(output_dir: Path) -> Dict[str, list]:
    """三集合证据 → `{code: [case_id…]}`（只收**有命中**的项）。"""
    import json

    issues: Dict[str, list] = {code: [] for code, _ in _CASE_CONTRACT_RULES}
    try:
        ir = json.loads((output_dir / "coverage" / "case_ir.json")
                        .read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        ir = {}
    contract = {str(c.get("id")): c for c in (ir.get("cases") or [])
                if isinstance(c, dict)}
    for rec in _case_cov_records(output_dir):
        cid = str(rec.get("case_id") or rec.get("task") or "")
        groups = [g for g in rec.get("groups") or [] if isinstance(g, dict)]
        codes = _case_group_issues(groups) | _case_checker_issues(rec)
        want = {str(g.get("group")) for g in
                (contract.get(cid) or {}).get("groups") or []}
        if want - {str(g.get("group")) for g in groups}:
            codes.add("CASE_IR_EVIDENCE_MISMATCH")
        for code in codes:
            issues[code].append(cid)
    return issues


def _case_msg(ids: list, label: str) -> str:
    sample = "、".join(sorted(set(ids))[:5])
    return (f"{len(set(ids))} 条用例{label}（{sample}）"
            f"—— 逐条见 coverage/case_cov/")


def _apply_case_contract_caveats(output_dir: Path, gates: Dict[str, Any],
                                 caveat) -> Dict[str, Any]:
    """三集合证据问题 → 每条规则一条 caveat（列前几条用例）。

    **规则码写成字面量**：`EXPECTED_CAVEATS` 的白名单测试按 caveat 调用处的
    大写字面量扫描源码，走变量的话新码在测试里看不见（会被当成"未登记"）。
    """
    issues = _case_contract_issues(output_dir)
    gates["case_contract"] = {code: len(ids) for code, ids in issues.items()}
    if issues["CASE_GROUP_PARTIAL"]:
        caveat("CASE_GROUP_PARTIAL",
               _case_msg(issues["CASE_GROUP_PARTIAL"], "的组证据不完整"))
    if issues["CASE_SVA_VACUOUS"]:
        caveat("CASE_SVA_VACUOUS",
               _case_msg(issues["CASE_SVA_VACUOUS"], "的 SVA 空转（cover_property 未命中）"))
    if issues["CASE_SCB_NOT_EXECUTED"]:
        caveat("CASE_SCB_NOT_EXECUTED",
               _case_msg(issues["CASE_SCB_NOT_EXECUTED"], "的 SCB 未执行"))
    if issues["CASE_PATH_PENDING_BACKEND"]:
        caveat("CASE_PATH_PENDING_BACKEND",
               _case_msg(issues["CASE_PATH_PENDING_BACKEND"], "的 PATH 后端未接"))
    if issues["CASE_IR_EVIDENCE_MISMATCH"]:
        caveat("CASE_IR_EVIDENCE_MISMATCH",
               _case_msg(issues["CASE_IR_EVIDENCE_MISMATCH"], "的契约与证据不一致"))
    return gates["case_contract"]


def _rel_to_run(path_str: str, output_dir: Path) -> str:
    """绝对路径 → run 内相对路径；不在 run 内就原样返回（不假装可移植）。"""
    if not path_str:
        return ""
    p = Path(str(path_str))
    if not p.is_absolute():
        return p.as_posix()
    try:
        return p.resolve().relative_to(output_dir.resolve()).as_posix()
    except ValueError:
        return str(p)


def _sha256_file(path: Path) -> str:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return ""


def _read_json_file(path: Path) -> Dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        return doc if isinstance(doc, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_json(path: Path, doc: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8", newline="\n")


def _load_contract(output_dir: Path):
    """构建物优先，没有就适配 case_ir —— 与 `run_shadow` 同一口径。"""
    from src.layers.l3_decision.contract import (
        check_contract, contract_from_case_ir, load_contract,
    )

    case_ir = _read_json_file(Path(output_dir) / "coverage" / "case_ir.json")
    if not case_ir.get("cases"):
        return None
    contract = load_contract(output_dir) if check_contract(output_dir).get("ok") \
        else None
    return contract or contract_from_case_ir(case_ir)


def _build_obligations_v3(output_dir: Path):
    """P4：统一义务 → `docs/obligations_v3.json`；返回（摘要, 义务对象）。"""
    try:
        from src.layers.l3_decision.contract import read_ledger
        from src.layers.l3_decision.obligation import derive_obligations, summary

        contract = _load_contract(output_dir)
        if contract is None:
            return {"available": False}, []
        # 契约换版后旧事实失效 —— 与 `run_shadow` 的 stale 口径一致。
        facts = [f for f in read_ledger(output_dir)
                 if str(f.get("type") or "") != "contract_anchor"
                 and str(f.get("contract_hash") or "") in ("", contract.hash)]
        obligations = derive_obligations(contract, facts)
        stats = summary(obligations)
        counts = stats.get("counts") or {}
        doc = {
            "schema": "obligations_v3",
            "contract_id": contract.id,
            "contract_hash": contract.hash,
            "facts": len(facts),
            **stats,
            # **FAILED 与 UNKNOWN 必须分开**：前者"证据说不过"，
            # 后者"根本没有可信判据"。折成一个数会掩盖问题性质。
            "failed": int(counts.get("FAILED") or 0),
            "unknown": int(counts.get("UNKNOWN") or 0),
            "obligations": [o.to_dict() for o in obligations],
        }
        path = Path(output_dir) / "docs" / "obligations_v3.json"
        _write_json(path, doc)
        return {
            "available": True,
            "path": _rel_to_run(path, Path(output_dir)),
            "total": stats["total"], "done": stats["done"],
            "closure_rate": stats["closure_rate"], "counts": counts,
            "failed": doc["failed"], "unknown": doc["unknown"],
            "facts": len(facts),
        }, obligations
    except Exception as e:                             # noqa: BLE001 旁路
        logger.warning(f"统一义务推导失败（签核继续）: {e}")
        return {"available": False, "error": str(e)}, []


def _build_closure_plan(output_dir: Path,
                        obligations: List[Any]) -> Dict[str, Any]:
    """P5：义务 + 覆盖缺口 → `status/closure_plan.json`（确定性排序，不引入 RL）。"""
    if not obligations:
        return {"available": False}
    try:
        from src.layers.l5_evolution.closure import plan_next, should_continue

        holes = _read_json_file(Path(output_dir) / "coverage" /
                                "coverage_holes.json")
        plan = plan_next(obligations, holes)
        decision = should_continue(obligations)
        doc = {
            "schema": "closure_plan_v1",
            **decision,
            "action_count": len(plan),
            "actions": [c.to_dict() for c in plan],
            "source": {"obligations": len(obligations),
                       "holes": len(holes.get("holes") or [])},
        }
        path = Path(output_dir) / "status" / "closure_plan.json"
        _write_json(path, doc)
        return {"available": True,
                "path": _rel_to_run(path, Path(output_dir)),
                "continue": decision["continue"],
                "closure_rate": decision["closure_rate"],
                "actions": len(plan),
                "top_actions": [c.action for c in plan[:5]]}
    except Exception as e:                             # noqa: BLE001 旁路
        logger.warning(f"闭环计划生成失败（签核继续）: {e}")
        return {"available": False, "error": str(e)}


def _build_interpretation_context(output_dir: Path) -> Dict[str, Any]:
    """证据闭环 ④+反馈：证据索引 → 解释（HYPOTHESIS）→ 下一轮上下文。"""
    try:
        from src.layers.l4_memory.evidence_store import (
            build_evidence_index, build_interpretations, build_next_context,
        )

        # 解释先落盘，索引才能统计到本轮的 interpretations 数量。
        interp = build_interpretations(output_dir)
        index = build_evidence_index(output_dir)
        context = build_next_context(output_dir)
        sources = _read_json_file(Path(output_dir) / "docs" /
                                  "evidence_sources.json")
        return {"available": True,
                "evidence_sources": {
                    "path": "docs/evidence_sources.json",
                    "available": sources.get("available") or [],
                    "unavailable": sources.get("unavailable") or [],
                    "dummy": sources.get("dummy") or [],
                    "proof_core_coverage": sources.get("proof_core_coverage"),
                },
                "evidence_index": {
                    "path": "docs/evidence_index.json",
                    "ledger": (index.get("ledger") or {}).get("by_fact_class") or {},
                    "claims_with_evidence":
                        (index.get("claim_counts") or {}).get("with_evidence", 0),
                    "claims_without_evidence":
                        (index.get("claim_counts") or {}).get("without_evidence", 0),
                },
                "interpretations": interp,
                "next_context": context}
    except Exception as e:                             # noqa: BLE001 旁路
        logger.warning(f"证据闭环解释/上下文生成失败（签核继续）: {e}")
        return {"available": False, "error": str(e)}


def _build_architecture_v2(output_dir: Path, target: float) -> Dict[str, Any]:
    """产物血缘 + 五维质量门 —— 在签核包**之前**落盘，才能被一起收进包。

    只报告、不阻断：不新增 caveat code，不改 `hard_ok`。缺证据/判不了
    用 `unknown`，不折算成 pass。
    """
    try:
        from src.core.provenance.graph import write_provenance
        from src.core.provenance.report import write_attribution_report
        from src.core.metrics.engineering import write as write_metrics
        from src.core.verification.quality import write as write_quality

        prov = write_provenance(output_dir)
        attribution = write_attribution_report(output_dir)
        quality = write_quality(
            output_dir, target=(target if target and target > 0 else None),
            run_id=output_dir.name)
        metrics = write_metrics(output_dir)
        # P4/P5：统一义务 + 确定性闭环计划（只报告，不新增 caveat code）。
        obligations_v3, obligations = _build_obligations_v3(output_dir)
        closure_plan = _build_closure_plan(output_dir, obligations)
        evidence_loop = _build_interpretation_context(output_dir)
        return {
            "schema": "architecture_v2_v1",
            "provenance": {
                "path": _rel_to_run(prov["path"], output_dir),
                "sha256": prov["jsonl_sha256"],
                "summary_path": _rel_to_run(prov["summary_path"], output_dir),
                "summary": prov["summary"],
            },
            "attribution": {
                "path": _rel_to_run(attribution["path"], output_dir),
                "hit_bins": attribution["hit_bins"],
                "attribution_rate": attribution["attribution_rate"],
                "test_seed_rate": attribution["test_seed_rate"],
                "exact_rate": attribution["exact_rate"],
                "weak_rate": attribution["weak_rate"],
            },
            "engineering_metrics": {
                "path": _rel_to_run(metrics["path"], output_dir),
                "regression_seconds": metrics["regression"]["total_seconds"],
                "incremental": metrics["incremental"].get("estimated_savings_pct"),
                "attribution_rate": metrics["attribution"]["attribution_rate"],
                "decision_rate": metrics["decision"]["effectiveness_rate"],
            },
            "verification_quality": {
                "path": _rel_to_run(quality["path"], output_dir),
                "overall": quality["overall"],
                "enforcement": quality.get("enforcement", "report"),
                "dimensions": {k: v["status"]
                               for k, v in quality["dimensions"].items()},
                "issues": quality["issues"],
            },
            # UVM IR 双写比对：签核包里能直接读"IR 与渲染 ctx 还差多少"。
            # 不做门禁 —— 差异清零是后续切 IR-first 的前置条件，不是签核条件。
            "ir_shadow": _ir_shadow_summary(output_dir),
            # **状态权威对账**：视图色 vs derive 判定。差异非 0 = 两套判定分叉，
            # 是签核条件（见 `_apply_authority_gate`），不是仪表盘读数。
            "authority": _authority_summary(output_dir),
            # P4：统一义务（PROVEN/PARTIAL/OPEN/FAILED/BLOCKED/UNKNOWN）。
            "obligations_v3": obligations_v3,
            # P5：下一次该做什么（硬失败优先；AI 建议不能覆盖门禁）。
            "closure_plan": closure_plan,
            # 证据闭环：证据索引 + 解释（HYPOTHESIS）+ 下一轮上下文
            "evidence_loop": evidence_loop,
        }
    except Exception as e:                             # noqa: BLE001 证据增量别拦签核
        logger.warning(f"Architecture 2.0 证据构建失败（签核继续）: {e}")
        return {}


def _ir_shadow_summary(output_dir: Path) -> Dict[str, Any]:
    """`docs/ir_shadow_diff.json` → 签核报告里的摘要（缺文件 = 未生成，不编 0）。"""
    path = Path(output_dir) / "docs" / "ir_shadow_diff.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return {"available": False}
    counts = doc.get("counts") or {}
    return {
        "available": True,
        "path": _rel_to_run(path, Path(output_dir)),
        "scopes": int(counts.get("scopes") or 0),
        "inconsistent": int(counts.get("inconsistent") or 0),
        "differences": int(counts.get("differences") or 0),
    }


def _authority_summary(output_dir: Path) -> Dict[str, Any]:
    """`status/authority_diff.json` → 签核读路径（缺文件 = 未生成，不编 0）。"""
    path = Path(output_dir) / "status" / "authority_diff.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return {"available": False}
    case_view = doc.get("case_view") or {}
    tp_shadow = doc.get("tp_shadow") or {}
    case_mismatch = int(case_view.get("mismatched") or 0)
    tp_mismatch = int(tp_shadow.get("mismatched") or 0)
    return {
        "available": True,
        "path": _rel_to_run(path, Path(output_dir)),
        "checked": int(case_view.get("checked") or 0),
        "case_mismatched": case_mismatch,
        "tp_mismatched": tp_mismatch,
        "ok": case_mismatch == 0 and tp_mismatch == 0,
    }


def _obligation_closure_issues(output_dir: Path) -> Dict[str, Any]:
    """P4/P5 的签核读数：失败义务 / 闭环未收敛（默认只报告）。"""
    obligations = _read_json_file(Path(output_dir) / "docs" /
                                  "obligations_v3.json")
    failed = [str(o.get("obligation_id")) for o in
              (obligations.get("obligations") or [])
              if isinstance(o, dict) and o.get("status") == "FAILED"]
    closure = _read_json_file(Path(output_dir) / "status" /
                              "closure_plan.json")
    return {"failed_obligations": failed,
            "closure_continue": bool(closure.get("continue"))}


def _evidence_issues(output_dir: Path) -> Dict[str, Any]:
    """证据闭环硬问题：已确认无证据 / agent 结论当事实 / 高风险未审批。"""
    index = _read_json_file(Path(output_dir) / "docs" / "evidence_index.json")
    rows = index.get("claims") or {}
    confirmed_without = [cid for cid, row in rows.items()
                         if isinstance(row, dict)
                         and row.get("status") == "CONFIRMED"
                         and not row.get("evidence_count")]
    agent_confirmed = [cid for cid, row in rows.items()
                       if isinstance(row, dict)
                       and row.get("status") == "CONFIRMED"
                       and row.get("producer_class") == "agent"]
    approved, high = set(), set()
    try:
        text = (Path(output_dir) / "docs" / "action_audit.jsonl").read_text(
            encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    for line in text.splitlines():
        try:
            rec = json.loads(line) if line.strip() else {}
        except ValueError:
            continue
        if not isinstance(rec, dict):
            continue
        if rec.get("decision") == "APPROVAL" and rec.get("appr_id"):
            approved.add(str(rec.get("action")))
        if str(rec.get("risk") or "") == "HIGH":
            high.add(str(rec.get("action")))
    return {
        "confirmed_without_evidence": confirmed_without,
        "agent_confirmed": agent_confirmed,
        "unapproved_high_risk": sorted(high - approved),
        **_obligation_closure_issues(output_dir),
    }


def _apply_evidence_gate(output_dir: Path, architecture_v2: Dict[str, Any],
                         hard_ok: bool, caveat) -> bool:
    """证据闭环门禁：默认 **report**；`SIGNOFFAI_EVIDENCE_GATE=block` 才硬失败。"""
    issues = _evidence_issues(output_dir)
    (architecture_v2.setdefault("evidence_loop", {})).setdefault(
        "gate", {}).update(issues)
    blocking = (str(os.environ.get("SIGNOFFAI_EVIDENCE_GATE", "report")).lower()
                == "block")
    # `closure_continue` 只是读数：闭环未收敛是常态，不参与硬失败计数。
    total = sum(len(v) for v in issues.values() if isinstance(v, list))
    if not total:
        return hard_ok
    if not blocking:
        logger.warning(f"证据闭环问题 {total} 条（report 模式，不阻断）: {issues}")
        return hard_ok
    caveat("EVIDENCE_GATE",
           f"证据闭环硬失败：已确认无证据 {len(issues['confirmed_without_evidence'])} / "
           f"agent 结论当事实 {len(issues['agent_confirmed'])} / "
           f"高风险未审批 {len(issues['unapproved_high_risk'])} / "
           f"失败义务 {len(issues['failed_obligations'])} / "
           f"闭环未收敛 {issues['closure_continue']}")
    return False


def _apply_authority_gate(architecture_v2: Dict[str, Any], hard_ok: bool,
                          caveat) -> bool:
    """状态权威对账**进入签核**：非 0 差异 → 硬失败。

    它回答的是"视图展示与 derive 判定是否同一套结论"。分叉时，任何一方都
    不能再被当作签核依据 —— 所以不是 warning。
    """
    authority = (architecture_v2 or {}).get("authority") or {}
    if not authority.get("available"):
        caveat("AUTHORITY_DIFF_MISSING",
               "没有 status/authority_diff.json —— 视图与 derive 未对账")
        return hard_ok
    if authority.get("ok"):
        return hard_ok
    caveat("AUTHORITY_DIFF",
           f"状态权威对账不一致：case_view {authority.get('case_mismatched')} 条 / "
           f"tp_shadow {authority.get('tp_mismatched')} 条 —— 视图与 derive 分叉")
    return False


def _coverage_pct(run_dir: Path):
    path = Path(run_dir) / "sim" / "coverage" / "coverage_result.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return None
    cov = doc.get("coverage") if isinstance(doc.get("coverage"), dict) else doc
    try:
        return float(cov.get("functional_pct"))
    except (TypeError, ValueError):
        return None


def _coverage_delta(output_dir: Path) -> Dict[str, Any]:
    """覆盖率 delta 门禁：显式给基线时，功能覆盖率不得回退。

    基线用 `SIGNOFFAI_COVERAGE_BASELINE=<run 目录>` 指定；不设就不比较
    （兼容老 run / 无基线场景）。
    """
    baseline = os.environ.get("SIGNOFFAI_COVERAGE_BASELINE", "").strip()
    if not baseline:
        return {"available": False, "reason": "no_baseline"}
    base = _coverage_pct(Path(baseline))
    current = _coverage_pct(Path(output_dir))
    if base is None or current is None:
        return {"available": False, "reason": "coverage_missing"}
    return {"available": True, "baseline": base, "current": current,
            "delta": round(current - base, 2), "ok": current + 1e-9 >= base}


def _apply_coverage_delta(output_dir: Path, hard_ok: bool, caveat) -> bool:
    delta = _coverage_delta(Path(output_dir))
    if not delta.get("available"):
        return hard_ok
    if delta.get("ok"):
        return hard_ok
    caveat("COVERAGE_REGRESSION",
           f"功能覆盖率回退：{delta['baseline']}% → {delta['current']}%"
           f"（Δ {delta['delta']}）—— 基线 {os.environ.get('SIGNOFFAI_COVERAGE_BASELINE')}")
    return False


def _apply_quality_gate_block(architecture_v2: Dict[str, Any], hard_ok: bool,
                              caveat) -> bool:
    """`SIGNOFFAI_QUALITY_GATE=block` → 接进签核三态（按维度灰度）。

    · `evidence` / `functional` 维度 `fail` → **硬失败**（NEEDS_FIX）：
      前者是"数据不够判"，后者是"功能没验到"，两条都不该被软 caveat 放过。
    · 其余维度的非 pass（fail/warn/unknown）→ 软 caveat `QUALITY_GATE_WARN`。
    · `report`（默认）/ `warn` 不改变三态 —— 阈值稳定前只报告。
    """
    quality = (architecture_v2 or {}).get("verification_quality") or {}
    if str(quality.get("enforcement") or "") != "block":
        return hard_ok
    dims = quality.get("dimensions") or {}
    hard = sorted(k for k in ("evidence", "functional")
                  if dims.get(k) == "fail")
    if hard:
        caveat("QUALITY_GATE_BLOCKED",
               f"质量门 block：{', '.join(f'{k}={dims[k]}' for k in hard)} "
               f"—— 见 docs/verification_quality.json")
        return False
    soft = sorted(k for k, v in dims.items()
                  if v in ("fail", "warn", "unknown") and k not in hard)
    if soft:
        caveat("QUALITY_GATE_WARN",
               f"质量门 block 模式下仍有非 pass 维度："
               f"{', '.join(f'{k}={dims[k]}' for k in soft)}")
    return hard_ok


def _rtl_version_hash(output_dir: Path) -> str:
    """RTL 目录内容哈希 —— 与 lineage 同一口径（排序后拼「文件名 + 文件哈希」）。"""
    files = sorted((output_dir / "rtl").glob("*.sv"))
    if not files:
        return ""
    h = hashlib.sha256()
    for f in files:
        h.update(f.name.encode("utf-8"))
        h.update(_sha256_file(f).encode("ascii"))
    return h.hexdigest()


def _module_name(output_dir: Path, ctx: Any = None) -> str:
    """本 run 的模块身份：spec.json 优先，其次 ctx，最后目录名。"""
    spec = _read_json_file(output_dir / "spec.json")
    name = str(spec.get("design_name") or "").strip()
    if not name and hasattr(ctx, "get"):
        arch = ctx.get("design_arch") or {}
        if isinstance(arch, dict):
            name = str(arch.get("module_name") or "").strip()
    return name or "dut"


def _read_yaml_file(path: Path) -> Dict[str, Any]:
    try:
        import yaml

        doc = yaml.safe_load(path.read_text(encoding="utf-8", errors="replace"))
        return doc if isinstance(doc, dict) else {}
    except Exception:                               # noqa: BLE001
        return {}


def _model_info(output_dir: Path, ctx: Any = None) -> Dict[str, Any]:
    """这一轮到底有没有**可签核**的参考模型。

    判据是 `models.yaml` 的 `source.status == verified`（生成器只挑 verified）。
    没有 `models.yaml`、或选中的是 draft/generated —— 都算不可用，并给出原因。
    **不把"生成了模型文件"读成"有参考模型"**：那正是 18 个假失败的老坑。
    """
    doc = _read_yaml_file(output_dir / "inputs" / "yaml" / "uvm" / "models.yaml")
    source = doc.get("source") or {}
    utils = doc.get("util_components") or []
    status = str(source.get("status") or "")
    available = bool(utils) and status == "verified"
    if available:
        reason = ""
    elif not doc:
        reason = "没有 models.yaml（模型库未选中任何模型）"
    elif not utils:
        reason = "models.yaml 里没有 util_components"
    else:
        reason = f"选中的模型状态是 {status or 'unknown'}，不是 verified"
    registry = []
    try:
        from src.layers.l4_memory.model_registry import ModelRegistry

        reg = ModelRegistry()
        try:
            registry = [{
                "name": m.get("name"), "version": m.get("version"),
                "status": m.get("status"), "protocol": m.get("protocol"),
                "trans_in": m.get("trans_in"), "trans_out": m.get("trans_out"),
            } for m in reg.all()]
        finally:
            reg.close()
    except Exception as e:                          # noqa: BLE001
        registry = [{"error": str(e)[:160]}]
    placeholder = False
    if hasattr(ctx, "get"):
        m = ctx.get("model") or {}
        if isinstance(m, dict):
            placeholder = bool(m.get("placeholder"))
    return {
        "available": available,
        # 有没有**尝试过**建模：有 models.yaml 或 ctx 明确标了 placeholder。
        # 两者都没有 = 这一轮没走参考模型链路，不该凭空挂 caveat。
        "models_yaml": bool(doc),
        "status": status,
        "reason": reason,
        "source": source,
        "util_components": [u.get("name") for u in utils if isinstance(u, dict)],
        "placeholder": placeholder,
        "registry": registry,
    }


def _lineage_info(output_dir: Path, module: str) -> Dict[str, Any]:
    """RTL 版本 + 基线锚点（签核必须引用它；缺失时由策略决定是否阻断）。"""
    try:
        from src.layers.l4_memory.lineage import LineageStore, ensure_run_rtl_version

        info = ensure_run_rtl_version(output_dir, module=module,
                                      run_id=output_dir.name)
        if not info:
            return {"available": False, "reason": "没有 RTL 内容哈希"}
        store = LineageStore()
        try:
            is_new = store.ensure_baseline(info["module"], output_dir.name,
                                           info["version_no"])
            base = store.get_baseline(info["module"])
        finally:
            store.close()
        return {"available": True, **info, "baseline": base,
                "baseline_is_new": is_new}
    except Exception as e:                          # noqa: BLE001 血缘不该拦签核
        return {"available": False, "reason": f"血缘库不可用: {e}"[:200]}


def _regression_config_summary(output_dir: Path) -> Dict[str, Any]:
    """回归配置的**参数通道**统计 —— 签核要看见"有没有绕过结构化字段"。

    后端方言由生成物承载（`run_cmd`），这里只统计三类用户通道：
    `plusargs`（测试语义透传）、`backend_args`（逃生口）、`plusarg_matrix`
    （旧的每条用例展开）。`backend_args` 非空是 caveat 的数据源。
    """
    path = output_dir / "inputs" / "yaml" / "regression.yaml"
    doc = _read_yaml_file(path)
    if not doc:
        return {"available": False}
    tests = [t for t in (doc.get("tests") or []) if isinstance(t, dict)]
    plusargs = sum(len(t.get("plusargs") or []) for t in tests)
    backend_args = sum(len(t.get("backend_args") or []) for t in tests)
    matrix = sum(len(t.get("plusarg_matrix") or []) for t in tests)
    seeds = sum(1 for t in tests if isinstance(t.get("seeds"), dict))
    structured_test = sum(1 for t in tests if t.get("test"))
    return {
        "available": True,
        "simulator": str(doc.get("simulator") or ""),
        "tests": len(tests),
        "run_cmd_tests": sum(1 for t in tests if t.get("run_cmd")),
        "structured_test": structured_test,
        "seeds": seeds,
        "plusargs": plusargs,
        "backend_args": backend_args,
        "plusarg_matrix": matrix,
        "path": "inputs/yaml/regression.yaml",
    }


def _knowledge_graph_summary(output_dir: Path) -> Dict[str, Any]:
    """运行时知识图的身份摘要（路径 + sha256 + 规模）；没有就是空。"""
    path = output_dir / "coverage" / "knowledge_graph.json"
    if not path.is_file():
        return {}
    doc = _read_json_file(path)
    return {
        "path": "coverage/knowledge_graph.json",
        "sha256": _sha256_file(path),
        "schema": doc.get("schema", ""),
        "summary": doc.get("summary") or {},
        "gaps": len(doc.get("gaps") or []),
    }


def _code_plan_from(plan: Dict[str, Any]) -> Dict[str, Any]:
    return (plan.get("code_coverage_plan")
            or (plan.get("coverage") or {}).get("code_plan") or {})


def _code_coverage_evidence(plan: Dict[str, Any],
                            code_plan: Dict[str, Any]) -> Dict[str, Any]:
    metrics = {}
    for key in ("branch_pct", "condition_pct", "statement_pct", "toggle_pct"):
        if code_plan.get(key) is not None:
            metrics[key] = code_plan.get(key)
    return {
        "code_single_pct": (plan.get("coverage") or {}).get("overall_pct"),
        "code_plan_pct": code_plan.get("overall_pct"),
        "code_plan_metrics": metrics,
    }


def _coverage_detail(coverage: Dict[str, Any], gates: Dict[str, Any],
                     pick: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "metric": pick["metric"],
        "target": gates.get("target"),
        "functional_pct": coverage.get("functional_pct"),
        "code_overall_pct": coverage.get("overall_pct"),
        "code_plan_pct": (coverage.get("code_plan") or {}).get("overall_pct"),
        "code_metrics_present": coverage.get("metrics_present"),
        "code_metrics_absent": coverage.get("metrics_absent"),
    }


def _ingest_drift_caveat(output_dir: Path, caveat) -> None:
    """xlsx 导入后 casemodel 被手改 —— 证据链对不上，必须开口。"""
    ingest = _humanview_ingest(output_dir)
    issues = ingest.get("issues") if ingest.get("available") else None
    if issues:
        caveat("INGEST_DRIFT",
               f"xlsx 导入后 casemodel 被手改（{len(issues)} 处）"
               f"—— 重新导入或说明原因，见 inputs/source_map.json")


def _humanview_ingest(output_dir: Path) -> Dict[str, Any]:
    """xlsx 导入事实（source_map）：覆盖点出处 / 丢弃 / 导入后被手改。"""
    try:
        from src.tools.humanview.aivm_ir.evidence import ingest_facts

        return ingest_facts(output_dir)
    except Exception:                                  # noqa: BLE001 旁路
        return {"available": False}


def _plan_consistency_caveat(output_dir: Path, caveat) -> None:
    doc = _read_json_file(output_dir / "coverage" / "plan_consistency.json")
    issues = doc.get("issues") if isinstance(doc, dict) else None
    if issues:
        caveat("PLAN_INCONSISTENT",
               f"激励计划与 TP/约束不一致：{len(issues)} 处"
               f"（见 coverage/plan_consistency.json）")


def _tool_receipt_summary(output_dir: Path) -> Dict[str, Any]:
    """工具回执的 `verified_by` 覆盖度 —— 有多少结论是 EDA 说的。"""
    path = output_dir / "docs" / "tool_receipts.jsonl"
    counts: Dict[str, int] = {}
    total = 0
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            total += 1
            key = str(rec.get("verified_by") or "unknown")
            counts[key] = counts.get(key, 0) + 1
    except OSError:
        return {"available": False, "total": 0, "by_verified_by": {}}
    from src.layers.l2_orchestration.communication.tool_protocol import (
        aggregate_verified_by)

    expanded = [k for k, n in counts.items() for _ in range(n)]
    return {
        "available": total > 0,
        "total": total,
        "by_verified_by": counts,
        "aggregate": aggregate_verified_by(expanded),
        "eda_pct": round(100.0 * counts.get("eda", 0) / total, 2) if total else 0.0,
    }


def _build_signoff_evidence(output_dir: Path, signoff: Dict[str, Any],
                            tp: Dict[str, Any], sem: Dict[str, Any],
                            caveats: List[str], *,
                            caveat_records: List[Dict[str, str]] = None,
                            policy: Dict[str, Any] = None,
                            model_info: Dict[str, Any] = None,
                            lineage: Dict[str, Any] = None,
                            versions: Dict[str, Any] = None,
                            hard_ok: bool = None) -> Dict[str, Any]:
    """**可对外交换的签核证据包**（`signoff_evidence_v1`）。

    把散在各处的证据收成一份带 schema 的 JSON：任何工具都能读、能验、能 diff。
    这是"可复现 · 可审计 · 可治理"从内部自洽走向**可移植资产**的那一步。

    说清楚的边界：
      · `seed_diversity` 目前是 `None` —— 种子有没有真的改变激励分布**还没验**，
        `None` ≠ "已验证"，也 ≠ "没通过"；
      · `unreachable_justifications` 现在只列 `SUSPECT`（计划覆盖率里 0 命中），
        **不是**"已证明不可达"；模型声明不可达后才会升为 `JUSTIFIED`。
    """
    methodology = _read_json_file(output_dir / "coverage" / "methodology.json")
    plan = _read_json_file(output_dir / "sim" / "coverage" / "coverage_result.json")
    plan_cov = plan.get("plan_coverage") or {}
    code_plan = _code_plan_from(plan)
    rows = tp.get("rows") or []
    merged_stores = int(plan_cov.get("stores") or 0)

    # 观测型维度里 0 命中的仓 —— 证据是"跨 N 条合并用例库 0 命中"。
    # 这是**嫌疑**不是判决：没有模型声明的不可达理由，就不能把它从分母里拿掉。
    unreachable = []
    for row in rows:
        if not isinstance(row, dict) or row.get("status") != "UNOBSERVED":
            continue
        unreachable.append({
            "tp_id": row.get("tp_id"),
            "bin": f"{row.get('coverpoint')}.{row.get('bin')}",
            "kind": row.get("kind") or "observe",
            "status": "SUSPECT",
            "evidence": f"0 hits across {merged_stores} merged regression test stores"
                        if merged_stores else "no merged plan coverage",
            "note": "需要模型声明 `unreachable` 才能从覆盖率分母里剔除",
        })

    # caveat → 建议动作（**只给建议，不自动执行危险动作**）
    actions = []
    cpa = sem.get("constraint_policy_applied")
    if cpa is None:
        # 覆盖率阶段没跑 / 老 run：读 verify 直接写下的那份（与 audit 门禁同源）
        cpa = _read_constraint_status(output_dir).get("constraint_policy_applied")
    if cpa is False:
        actions.append({"action": "BACKFILL_CONSTRAINTS", "auto": False,
                        "reason": "部分策略仍是骨架：补 sequence realization / 协议参数"})
    if tp.get("missed"):
        actions.append({"action": "GENERATE_DIRECTED_TEST", "auto": False,
                        "reason": f"{len(tp.get('missed') or [])} 条测试点未命中："
                                  f"从 tp_matrix.missed[] 生成定向约束/用例"})
    if tp.get("unmapped"):
        actions.append({"action": "REGENERATE_COVERAGE_MODEL", "auto": True,
                        "reason": "测试点的覆盖仓在报告里找不到：模型与覆盖率模型漂了"})
    if sem.get("cg_dut_hit_gt_zero") is False:
        actions.append({"action": "CHECK_BIND_PROBE", "auto": False,
                        "reason": "cg_dut 零命中：检查 bind 探针 / config_db 句柄"})
    if sem.get("ucdb_nonzero_bins") is False:
        actions.append({"action": "RERUN_COVERAGE", "auto": True,
                        "reason": "ucdb 落了库但 bin 零命中"})

    # 种子多样性：覆盖率阶段写进 `semantic_validations`，同时落盘一份
    # `coverage/seed_diversity.json`。两处都读，优先语义块。
    seed_div = sem.get("seed_diversity")
    if seed_div is None:
        seed_div = _read_json_file(output_dir / "coverage" / "seed_diversity.json") or None
    merge_manifest = plan_cov.get("merge_manifest") or ""
    merge_manifest_path = Path(str(merge_manifest)) if merge_manifest else (
        output_dir / "coverage" / "plan_merge_manifest.json")
    merge_manifest_sha = (_sha256_file(merge_manifest_path)
                          if merge_manifest_path.is_file() else "")
    from src.layers.l2_orchestration.evidence.verdict import (
        accepted_codes_from_policy, effective_caveats as _effective)

    policy = policy or {}
    accepted = accepted_codes_from_policy(policy)
    effective = _effective(caveat_records, accepted)

    llm_log = output_dir / "docs" / "llm_audit.jsonl"
    return {
        "schema": "signoff_evidence_v1",
        # **v1 是兼容视图**；权威是 signoff_evidence/manifest.json（v2）。
        # 保留 v1 是因为老消费者/测试仍按这个 schema 读。
        "deprecated": True,
        "canonical": "signoff_evidence/manifest.json",
        "run": output_dir.name,
        "module": signoff.get("module", ""),
        "rtl_version_hash": _rtl_version_hash(output_dir),
        "testpoint_ir_sha256": ((methodology.get("artifacts") or {})
                                .get("testpoints_yaml") or {}).get("sha256", ""),
        "framework": {"name": methodology.get("framework", ""),
                      "version": methodology.get("version", "")},
        "versions": versions or {},
        "coverage": {
            "plan_pct": plan_cov.get("functional_pct"),
            "single_test_pct": plan_cov.get("single_test_pct"),
            # 代码覆盖率：单测口径 vs DUT 计划（回归合并）口径。
            # 签核门禁仍是 functional；这两个是**对照事实**，不冒充门禁。
            **_code_coverage_evidence(plan, code_plan),
            "gate_pct": signoff.get("coverage"),
            "gate_passed": (signoff.get("gates") or {}).get("coverage_ok"),
            "merged_stores": merged_stores,
            # 绝对值留给本机排查；相对值是**可迁移**的那一份。
            "merged_ucdb": plan_cov.get("ucdb", ""),
            "merged_ucdb_rel": _rel_to_run(plan_cov.get("ucdb", ""), output_dir),
            # 合并输入清单 —— "这个百分比由哪些库算出来"必须可核对
            "merge_manifest": str(merge_manifest_path) if merge_manifest_sha else "",
            "merge_manifest_sha256": merge_manifest_sha,
        },
        "humanview_ingest": _humanview_ingest(output_dir),
        "tp_matrix": {
            "counts": tp.get("counts") or {},
            "total": tp.get("total", 0),
            "drivable_pct": tp.get("drivable_pct", 0.0),
            "backdoor_pct": tp.get("backdoor_pct", 0.0),
            "behavior_pending": tp.get("behavior_pending", 0),
            "signed_off": tp.get("signed_off_total", 0),
            "unsigned": tp.get("unsigned_total", 0),
            "signed_off_pct": tp.get("signed_off_pct", 0.0),
            "missed_tp_ids": [r.get("tp_id") for r in (tp.get("missed") or [])
                              if isinstance(r, dict)],
        },
        # **逐用例签核**：用例 → 测试点 → 波形 的可反查证据。
        # 空 = 这一轮没有逐用例证据（老 run / 没 TP IR），不是"全部签核"。
        "case_coverage": _case_coverage_summary(output_dir, tp),
        # **做过就是对象，没做才 null** —— 不再无条件 null。
        "seed_diversity": seed_div,
        # 粗连续奖励：编译/回归/覆盖率三层合成。没有就是没有（老 run）。
        "sim_reward": (_read_json_file(output_dir / "coverage" / "sim_reward.json")
                       or None),
        # 运行时知识图：gap → bin/test/version/fix 的因果链（确定性，不含 LLM）。
        "knowledge_graph": _knowledge_graph_summary(output_dir),
        "seed_diversity_reason": (
            "" if seed_div and seed_div.get("analyzed")
            else (seed_div or {}).get("reason", "未分析") if seed_div
            else "未分析（没有 seed_diversity.json）"),
        # **兼容字段**：老测试/老证据消费者按这个名字判断"种子多样性还没验"。
        # 新代码请读 `seed_diversity` / `seed_diversity_reason`。
        "no_test_success": (
            ""
            if seed_div and seed_div.get("analyzed")
            else "seed_diversity 尚未实现/未分析："
                 + (str((seed_div or {}).get("reason") or "没有逐 bin 比对结果"))),
        "reference_models": model_info or {},
        "lineage": lineage or {},
        "regression_config": signoff.get("regression_config") or {},
        "policy": {
            "schema": policy.get("schema", ""),
            "policy_hash": policy.get("policy_hash", ""),
            "source": policy.get("source", ""),
            "require_ref_model": policy.get("require_ref_model"),
            "require_baseline": policy.get("require_baseline"),
            "accepted_codes": sorted(accepted),
        },
        "tool_receipts": _tool_receipt_summary(output_dir),
        "semantic_validations": sem,
        "caveats": list(caveats),
        "caveat_records": list(caveat_records or []),
        "accepted_caveat_codes": sorted(accepted),
        "effective_caveat_codes": [c.get("code") for c in effective],
        "caveat_actions": actions,
        "unreachable_justifications": unreachable,
        "llm_audit_digest": _sha256_file(llm_log),
        "verdict": signoff.get("verdict"),
        "signoff_status": signoff.get("signoff_status"),
        "hard_ok": hard_ok if hard_ok is not None else None,
    }


