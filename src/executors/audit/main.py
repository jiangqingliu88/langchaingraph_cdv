"""审计智能体 —— 质量审查 + 签核证据链"""
from typing import Dict, Any, List
import hashlib
import json
from datetime import datetime
from pathlib import Path

from src.layers.l2_orchestration.executors.base import BaseExecutor, ExecutorResult
from src.layers.l2_orchestration.executors.registry import register_executor
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
                "dimensions": {k: v["status"]
                               for k, v in quality["dimensions"].items()},
                "issues": quality["issues"],
            },
        }
    except Exception as e:                             # noqa: BLE001 证据增量别拦签核
        logger.warning(f"Architecture 2.0 证据构建失败（签核继续）: {e}")
        return {}


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
            "missed_tp_ids": [r.get("tp_id") for r in (tp.get("missed") or [])
                              if isinstance(r, dict)],
        },
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


@register_executor("audit")
class AuditExecutor(BaseExecutor):
    """审计智能体 = 质量审查 + 签核报告"""

    task_type = "quality_review"
    consumes = ["regression", "coverage"]
    produces = None

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(
            role="audit", display_name="审计智能体",
            description="质量审查+签核证据链", config=config or {})

    async def _setup(self):
        logger.info(f"{self.display_name} 初始化完成")

    async def _get_prompt_template(self):
        return None

    async def _get_tools(self):
        return []

    async def _execute(self, input_text: str):
        return {"output": ""}

    async def execute_task(self, task: Dict[str, Any]) -> ExecutorResult:
        from src.layers.l1_infrastructure.output_config import make_output_root
        output_dir = Path(make_output_root(task.get("output_dir") or None))
        task["output_dir"] = str(output_dir)

        ctx = task.get("ctx", {})
        regression = ctx.get("regression", {}) if hasattr(ctx, 'get') else {}
        coverage = ctx.get("coverage", {}) if hasattr(ctx, 'get') else {}
        if not isinstance(regression, dict):
            regression = {}
        if not isinstance(coverage, dict):
            coverage = {}

        # ── 质量审查（真实逻辑）──
        passed = regression.get("passed", 0)
        failed = regression.get("failed", 0)
        total = regression.get("total", 0)
        # **按口径取**（与闭环同一个来源）—— 门槛挂在哪个数上，必须与闭环盯的那个
        # 数一致；否则会出现"闭环在追功能覆盖率、审计在判代码覆盖率"这种错位。
        from src.layers.l2_orchestration.planning import pick_coverage_value
        _pick = pick_coverage_value(coverage)
        overall = _pick["value"]

        # ── 签核前置门禁（历史 bug：audit 永远 success=True，0% 覆盖率也"通过"）──
        # 任一门禁不满足 → NEEDS_FIX 且 success=False（失败响亮，禁止粉饰）
        gates = {}
        # G1: RTL 真实存在且通过 vlog 编译（无 RTL = 无签核对象）
        try:
            rtl_dir = output_dir / "rtl"
            rtl_files = sorted(rtl_dir.glob("*.sv")) if rtl_dir.exists() else []
            gates["rtl_present"] = len(rtl_files) > 0
            gates["rtl_files"] = [f.name for f in rtl_files][:20]
        except Exception:
            gates["rtl_present"] = False
            gates["rtl_files"] = []
        # G1b: RTL 顶层不是占位骨架（LLM 连线失败回退的确定性骨架无真实互连逻辑）
        try:
            _arch = ctx.get("design_arch", {}) if hasattr(ctx, "get") else {}
            gates["rtl_real"] = bool(gates["rtl_present"]) and not bool(
                (_arch if isinstance(_arch, dict) else {}).get("rtl_placeholder", False))
        except Exception:
            gates["rtl_real"] = bool(gates["rtl_present"])
        # G2: 回归真实执行且全过（total>0 且 failed==0）
        gates["regression_passed"] = failed == 0 and total > 0
        # G3: 覆盖率来自真实收集（>0 才算收集过；0 或缺失 = 没跑覆盖率）
        gates["coverage_collected"] = isinstance(overall, (int, float)) and overall > 0
        # G4: 参考模型是真实模型（禁止 a+b 模板占位模型通过签核）
        # ctx["model"] 已是 model_data（execution.py 的 ctx.update(data) 直接展开），
        # 历史读取层级错误（_model["model"]）导致占位模型被误判为真实。
        try:
            _model = ctx.get("model", {}) if hasattr(ctx, "get") else {}
            _model_data = _model if isinstance(_model, dict) else {}
            gates["model_real"] = not bool(_model_data.get("placeholder", False))
            gates["model_placeholder_reason"] = str(_model_data.get("placeholder_reason", ""))[:200]
        except Exception:
            gates["model_real"] = False
            gates["model_placeholder_reason"] = "无法读取模型状态"

        # 判定
        #
        # 门槛用**本次 run 的目标**（`ctx["target"]`，来自 `--target` / 配置），
        # 不是写死的 95。写死 95 的后果实测过：目标 80 的项目跑出 32.5%，
        # 判定当然还是 NEEDS_FIX —— 数字看着"有门槛"，其实门槛与实际目标无关，
        # 而闭环拿它当"动作失败"计数（见 runtime.py 的熔断那一段）。
        pass_rate_ok = gates["regression_passed"]
        try:
            _target = float(ctx.get("target") or 0) if hasattr(ctx, "get") else 0.0
        except (TypeError, ValueError):
            _target = 0.0
        # 目标没给（0/缺失）就不假装有门槛：如实说"判不了"，不让它静默通过
        coverage_ok = (isinstance(overall, (int, float)) and _target > 0
                       and overall >= _target)
        gates["target"] = _target
        gates["coverage_ok"] = bool(coverage_ok)
        # **参考模型是否作为硬门禁，由模块策略决定**（见下面的 `require_ref_model`）。
        # 这里先只算与策略无关的硬条件；`model_real` 仍是**事实字段**，
        # 但默认不再一票否决 —— 否则"没走参考模型链路"的 run（例如 --rtl
        # 验证专注模式）会永远无法签核，而策略明明允许没有模型。
        hard_ok = bool(pass_rate_ok and coverage_ok and gates.get("rtl_real", False))

        # ── 软缺口（caveats）：硬门禁过了，但"绿得不够实在" ──
        #
        # 这一层回答的是「数字好看**不等于**量到了该量的东西」。此前这类中间态
        # 只散在日志与人的记忆里：约束生成了而策略体是空壳、ucdb 落库而 bin
        # 一个没命中、关联硬边断了 —— audit 全当没看见，`READY` 照发。
        #
        # **三态而不是两态**：`PASS_WITH_CAVEAT` 与 `NEEDS_FIX` 的处置完全不同 ——
        # 前者可以签、但要写清保留了哪些缺口；后者根本不能签。
        sem = ctx.get("semantic_validations", {}) if hasattr(ctx, "get") else {}
        if not isinstance(sem, dict):
            sem = {}
        #
        # **只有显式的 `False` 才算缺口**。`None` 是"判不了"（没跑覆盖率 /
        # 没生成约束模型），而"判不了"到处都是 —— 把它也算进来的话几乎每个 run
        # 都会挂上 caveat，三态就贬值成"反正总有一条"，没人再去看那几行。
        # 同一条纪律见 `_artifact_manifest`：读不到就什么都不放。
        caveats: List[str] = []
        #: caveat 的**机器码**与人类可读消息一一对应。
        #: 策略文件按码接受/拒绝（`accepted_caveats`），签核结论按"未被接受的
        #: 码"计算 —— 这样"接受某条 caveat"是可审计的决定，不是改文案。
        caveat_records: List[Dict[str, str]] = []

        def _caveat(code: str, message: str) -> None:
            caveats.append(message)
            caveat_records.append({"code": code, "message": message})

        # 约束有没有真在约束 —— **优先读 verify 直接写下的那份**，`semantic_validations`
        # 里那份当补充。
        #
        # 为什么不能只靠 `semantic_validations`：它是**覆盖率阶段**拼进
        # `coverage_result.json` 的，而回归失败时闭环会**跳过 coverage**
        # （"功能回归 N 失败 → 跳过 coverage，进入 debug 修复"）。那种 run 里
        # `semantic_validations` 恒为 `{}`，于是"`env/cons/` 生成了但 11 条策略
        # 全是空壳"这件事在签核报告里**一个字都没有** —— 实测跑出来的就是这个。
        # 而 `constraint_status.json` 是 verify 写的，无论跑没跑覆盖率都在。
        _cpa = sem.get("constraint_policy_applied")
        if _cpa is None:
            _st = _read_constraint_status(output_dir)
            if _st.get("constraint_generated") is True:
                _cpa = _st.get("constraint_policy_applied")
        if _cpa is False:
            _st = _read_constraint_status(output_dir)
            _backed = _st.get("backed_policy_count")
            _total = _st.get("policy_count")
            if isinstance(_backed, int) and isinstance(_total, int) and _total > 0:
                _caveat("CONSTRAINT_PARTIAL",
                        f"约束只部分生效：{_backed}/{_total} 条策略由模型编译出真实赋值，"
                        f"其余 {_st.get('unbacked_policy_count', _total - _backed)} 条仍是"
                        f"空骨架（维度不可驱动，没有 `stimulus.field`）—— "
                        f"见 coverage/constraint_status.json")
            else:
                _caveat("CONSTRAINT_INACTIVE",
                        "约束未激活：策略体的 apply() 落在 `default:` 分支、不做任何事"
                        "（`env/cons/` 生成了但约束不约束东西）")
        if sem.get("ucdb_nonzero_bins") is False:
            _caveat("UCDB_NO_BINS",
                    "覆盖率库落了但**一个 bin 都没命中** —— 覆盖率的数字没有意义")
        if sem.get("cg_dut_hit_gt_zero") is False:
            _caveat("CG_DUT_ZERO",
                    "`cg_dut` 零命中 —— DUT 探针可能没挂上，内部状态/输出端口没采到")
        # 关联硬边断（`associate` 的 ① ②）—— 覆盖率与 case 模型对不上，
        # 那意味着"声明要测的"与"实际在量的"是两回事。
        #
        # **读文件而不是读 ctx**：那份报告由 verify 写在
        # `<run>/coverage/association_report.json`，而审计拿得到 run 目录 ——
        # 为一个旁路产物专门加一条穿过 24 个节点的 ctx 键，不划算。
        assoc = _read_association_report(output_dir)
        if assoc.get("hard_edge_broken"):
            _caveat("ASSOCIATION_HARD_EDGE",
                    f"三模型关联硬边断了 {assoc['hard_edge_broken']} 条"
                    f"（声明的测试点没落成覆盖仓）—— 见 coverage/association_report.json")
        # TP IR / StimulusPlan / constraint_backing 三份真相漂移
        _plan_consistency_caveat(output_dir, _caveat)

        # ── 测试点矩阵：**签核按测试点说话，不按百分比说话** ──
        #
        # 功能覆盖率 70% 只说明"有 30% 的仓没中"，但它不说"缺的是哪一条、
        # 属于谁、是不是根本不可激励"。矩阵把缺口归因到 `tp_id` 与需求编号。
        tp = _read_tp_matrix(output_dir)
        tp_summary: Dict[str, Any] = {}
        if tp:
            tp_summary = {
                "total": tp.get("total", 0),
                "drivable": tp.get("drivable", 0),
                "drivable_hit": tp.get("drivable_hit", 0),
                "drivable_pct": tp.get("drivable_pct", 0.0),
                # **后门到达单独一栏**：force 内部状态采到的覆盖，不算激励覆盖。
                "backdoor": tp.get("backdoor", 0),
                "backdoor_hit": tp.get("backdoor_hit", 0),
                "backdoor_pct": tp.get("backdoor_pct", 0.0),
                # **观测型不是缺口**：它们没有输入引脚，命中与否是"状态到没到"，
                # 单独一栏，不混进可激励覆盖率。
                "observe_only": tp.get("observe_only", 0),
                "observed": tp.get("observed", 0),
                # 行为域 TP：已进 IR、执行后端未接 —— 如实列出，不进任何覆盖率分母
                "behavior_pending": tp.get("behavior_pending", 0),
                "missed": len(tp.get("missed") or []),
                "unmapped": len(tp.get("unmapped") or []),
            }
            if tp_summary["unmapped"]:
                _caveat("TP_UNMAPPED",
                        f"{tp_summary['unmapped']} 条测试点的覆盖仓在报告里找不到"
                        f"（模型与生成的覆盖率模型漂了）—— 见 coverage/tp_matrix.json")
            if sem.get("testpoints_traced") is False and not tp_summary["unmapped"]:
                _caveat("TP_TRACE_INCOMPLETE",
                        "测试点与覆盖仓的对应关系不完整 —— 见 coverage/tp_matrix.json")
            if tp_summary["missed"]:
                _caveat("TP_MISSED",
                        f"{tp_summary['missed']} 条测试点的仓未命中"
                        f"（可激励 {tp_summary['drivable_hit']}/{tp_summary['drivable']}，"
                        f"{tp_summary['drivable_pct']}%；后门 "
                        f"{tp_summary.get('backdoor_hit', 0)}/{tp_summary.get('backdoor', 0)}；"
                        f"观测型 {tp_summary['observed']}/{tp_summary['observe_only']}）"
                        f"—— 逐条见 coverage/tp_matrix.json")
        _ingest_drift_caveat(output_dir, _caveat)

        # ── 参考模型 / 基线 / 模块策略：签核的"资格条件" ──
        #
        # 三条都是**可配置的**，不是写死的：不同模块对证据的要求不同
        # （一个实验性模块不该因为"没有 verified 参考模型"就永远不能签）。
        # 策略文件默认保守：不要求参考模型、要求基线、不接受任何 caveat。
        module = _module_name(output_dir, ctx)
        from src.layers.l2_orchestration.evidence.signoff_package import (
            collect_versions, load_policy, write_policy_snapshot)
        policy, _policy_src = load_policy(output_dir, module, Path.cwd(),
                                          strict=True)
        for _issue in policy.get("issues") or []:
            logger.warning(f"签核策略: {_issue}")
        write_policy_snapshot(output_dir, policy)
        model_info = _model_info(output_dir, ctx)
        lineage_info = _lineage_info(output_dir, module)
        versions = collect_versions()

        gates["reference_model_required"] = bool(policy.get("require_ref_model"))
        gates["reference_model_available"] = bool(model_info.get("available"))
        # `model_real` 只在策略**要求**参考模型时才是硬门禁；否则它是事实字段 +
        # `MODEL_UNAVAILABLE` caveat（"签核不含模型比对结论"，不是"不能签"）。
        gates["model_real_hard"] = bool(policy.get("require_ref_model"))
        if gates["model_real_hard"] and not gates.get("model_real", False):
            hard_ok = False
        gates["baseline_required"] = bool(policy.get("require_baseline"))
        gates["baseline_present"] = bool(
            (lineage_info.get("baseline") or {}).get("run_id"))

        if not model_info.get("available"):
            msg = (f"本轮没有 verified 参考模型（{model_info.get('reason') or '未知原因'}）"
                   f"—— 签核不含模型比对结论")
            if policy.get("require_ref_model"):
                hard_ok = False
                _caveat("MODEL_UNAVAILABLE",
                        f"策略要求参考模型，但{msg}")
            elif model_info.get("models_yaml") or model_info.get("placeholder"):
                # 只有**真的尝试过**建模却没得到 verified 模型时才挂 caveat。
                # 从没走过这条链路（没有 models.yaml、也没有 placeholder 标记）
                # 的 run 不该凭空多一条 —— 那会让三态贬值成"反正总有一条"。
                _caveat("MODEL_UNAVAILABLE", msg)
        if (policy.get("require_baseline") and gates["rtl_present"]
                and not gates["baseline_present"]):
            hard_ok = False
            _caveat("BASELINE_MISSING",
                    "策略要求血缘基线，但本轮没有可引用的 baseline —— "
                    "见 database/lineage.db 或 `vagent lineage baseline`")

        # 回归参数通道：`backend_args` 是显式逃生口，用了就要让签核的人看见。
        regression_config = _regression_config_summary(output_dir)
        if regression_config.get("backend_args"):
            _caveat("BACKEND_ARGS_USED",
                    f"{regression_config['backend_args']} 个 backend_args 手写进了"
                    f"后端命令 —— 这些参数不受结构化字段保护"
                    f"（见 {regression_config.get('path')}）")

        from src.layers.l2_orchestration.evidence.verdict import (
            accepted_codes_from_policy, decide_verdict, effective_caveats as _effective,
            signoff_status as _status)

        accepted_codes = accepted_codes_from_policy(policy)
        effective_caveats = _effective(caveat_records, accepted_codes)
        # **唯一判定实现**：audit 与离线 replay 共用，避免两边漂移。
        verdict = decide_verdict(hard_ok=hard_ok,
                                 raw_caveats=caveat_records,
                                 accepted_codes=accepted_codes)

        # ── 签核报告（证据链）──
        #
        # **两个覆盖率都写进去，并标出哪个是本次判定的口径**。只留一个数的话，
        # 读报告的人分不清"32.5%"是代码覆盖率还是功能覆盖率 —— 而这两个数在
        # 同一份 run 里可以差一倍（32.5% vs 64.81%），"差在哪"正是要回答的问题。
        #
        # Architecture 2.0：血缘与五维质量门先落盘，再组装签核（否则它们进不了
        # 下面的 evidence 包）。**只报告、不阻断**。
        architecture_v2 = _build_architecture_v2(output_dir, _target)
        signoff = {
            "verdict": verdict,
            "module": module,
            "pass_rate": f"{passed}/{total}",
            "coverage": overall,
            "coverage_metric": _pick["metric"],
            "coverage_detail": _coverage_detail(coverage, gates, _pick),
            "gates": gates,
            # **软缺口**：硬门禁全过、但"绿得不够实在"的地方。空列表 = 没有。
            # 与 `gates` 分开：门禁是"能不能签"，这是"签的时候要写清什么"。
            "caveats": caveats,
            #: 逐条 caveat 的机器码 —— 策略按码接受，结论按"未被接受的码"算。
            "caveat_records": caveat_records,
            "accepted_caveat_codes": sorted(accepted_codes),
            "effective_caveat_codes": [c["code"] for c in effective_caveats],
            "policy": {
                "schema": policy.get("schema", ""),
                "policy_hash": policy.get("policy_hash", ""),
                "source": policy.get("source", ""),
                "require_ref_model": bool(policy.get("require_ref_model")),
                "require_baseline": bool(policy.get("require_baseline")),
            },
            "reference_models": model_info,
            "lineage": lineage_info,
            "versions": versions,
            "regression_config": regression_config,
            "tool_receipts": _tool_receipt_summary(output_dir),
            "semantic_validations": sem,
            # 测试点维度的签核口径：**可激励 / 已命中 / 只能观测** 三栏分开。
            # 空字典 = 这一轮没有 TP IR（老 run / 没建模），不是"测试点全过"。
            "testpoints": tp_summary,
            "architecture_v2": architecture_v2,
            "summary": {
                "total_tests": total, "passed": passed, "failed": failed,
                "overall_coverage": overall,
                "coverage_metric": _pick["metric"],
                "functional_coverage": coverage.get("functional_pct"),
                "code_coverage": coverage.get("overall_pct"),
                "rtl_present": gates["rtl_present"],
                "coverage_collected": gates["coverage_collected"],
                "caveat_count": len(caveats),
                "caveat_effective_count": len(effective_caveats),
                "caveat_accepted_count": len(caveats) - len(effective_caveats),
                "testpoint_count": tp_summary.get("total", 0),
                "testpoint_missed": tp_summary.get("missed", 0),
            },
            # 三态 → 签核状态。**`NEEDS_FIX` 原来是 CONDITIONAL，这是错的** ——
            # "有条件通过"读起来像"可以签了、带着条件"，而 NEEDS_FIX 是
            # "根本不能签"。把两件事标成同一个词，报告读起来会误导。
            "signoff_status": _status(verdict),
        }

        # ── 可交换签核证据包（signoff_evidence_v1）──
        #
        # 与 report.json 并存：report 是人读的签核报告；evidence 是**带 schema、
        # 可被任何工具读取/校验/diff** 的证据包。`dump` 会把它一起打包。
        output_dir.mkdir(parents=True, exist_ok=True)
        evidence = None
        try:
            evidence = _build_signoff_evidence(
                output_dir, signoff, tp, sem, caveats,
                caveat_records=caveat_records, policy=policy,
                model_info=model_info, lineage=lineage_info,
                versions=versions, hard_ok=hard_ok)
            evidence["architecture_v2"] = architecture_v2
            ev_path = output_dir / "signoff_evidence.json"
            ev_path.write_text(json.dumps(evidence, indent=2, ensure_ascii=False),
                               encoding="utf-8")
            signoff["signoff_evidence"] = {
                "schema": evidence["schema"],
                "path": str(ev_path),
                "sha256": _sha256_file(ev_path),
            }
        except Exception as e:                         # noqa: BLE001 证据包别拦签核
            logger.warning(f"签核证据包写入失败: {e}")

        # ── caveat 明细（机器可读；策略接受/拒绝都按码）──
        try:
            (output_dir / "caveats.json").write_text(json.dumps({
                "schema": "signoff_caveats_v1",
                "module": module,
                "raw": caveat_records,
                "accepted_codes": sorted(accepted_codes),
                "effective_codes": [c["code"] for c in effective_caveats],
                "policy_source": policy.get("source", ""),
            }, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as e:
            logger.warning(f"caveats.json 写入失败: {e}")

        # ── 合同级证据包 v2：目录布局 + 版本绑定 + 离线回放脚本 ──
        package_info: Dict[str, Any] = {}
        if evidence:
            try:
                from src.layers.l2_orchestration.evidence.signoff_package import (
                    write_package)
                artifacts: Dict[str, Any] = {}
                for name, entry in ((_read_json_file(
                        output_dir / "sim" / "coverage" / "coverage_result.json")
                        .get("artifacts") or {}).items()):
                    if isinstance(entry, dict) and entry.get("path"):
                        artifacts[name] = {
                            # **相对路径**：证据包换机器后仍可定位
                            "path": _rel_to_run(entry.get("path"), output_dir),
                            "sha256": entry.get("sha256", ""),
                            "kind": entry.get("kind", name),
                        }
                merged = (evidence.get("coverage") or {}).get("merged_ucdb")
                if merged and Path(str(merged)).is_file():
                    artifacts["plan_ucdb"] = {
                        "path": _rel_to_run(merged, output_dir),
                        "sha256": _sha256_file(Path(str(merged))),
                        "kind": "coverage_db",
                    }
                cov_ev = dict(evidence.get("coverage") or {})
                # v2 是**可迁移**的那一份：路径一律相对 run 目录。
                for _key in ("merged_ucdb", "merge_manifest"):
                    if cov_ev.get(_key):
                        cov_ev[_key] = _rel_to_run(cov_ev[_key], output_dir)
                v2 = {
                    "run": output_dir.name,
                    "module": module,
                    "created_at": datetime.now().isoformat(timespec="seconds"),
                    "versions": versions,
                    "rtl_version_hash": evidence.get("rtl_version_hash", ""),
                    "testpoint_ir_sha256": evidence.get("testpoint_ir_sha256", ""),
                    "framework": evidence.get("framework") or {},
                    "reference_models": model_info,
                    "lineage": lineage_info,
                    "regression_config": evidence.get("regression_config") or {},
                    "policy": evidence.get("policy") or {},
                    "coverage": cov_ev,
                    "tp_matrix": evidence.get("tp_matrix") or {},
                    "seed_diversity": evidence.get("seed_diversity"),
                    "sim_reward": evidence.get("sim_reward"),
                    "knowledge_graph": evidence.get("knowledge_graph") or {},
                    "tool_receipts": evidence.get("tool_receipts") or {},
                    "architecture_v2": architecture_v2,
                    "verdict": {
                        "hard_ok": bool(hard_ok),
                        "raw_caveats": caveat_records,
                        "accepted_codes": sorted(accepted_codes),
                        "effective_codes": [c["code"] for c in effective_caveats],
                        "verdict": verdict,
                        "signoff_status": signoff["signoff_status"],
                    },
                    "artifacts": artifacts,
                    "seeds": (evidence.get("seed_diversity") or {}).get("seeds") or [],
                }
                pkg_manifest = write_package(output_dir, v2, project_root=Path.cwd())
                package_info = {
                    "schema": pkg_manifest.get("schema"),
                    "package_dir": pkg_manifest.get("package_dir", ""),
                    "package_hash": pkg_manifest.get("package_hash", ""),
                    "manifest_hash": pkg_manifest.get("manifest_hash", ""),
                }
                signoff.setdefault("signoff_evidence", {}).update(package_info)
            except Exception as e:                     # noqa: BLE001 包别拦签核
                logger.warning(f"签核证据包 v2 写入失败: {e}")

        # 写签核报告（在证据包之后：它要带上 package_hash）
        report_path = output_dir / "report.json"
        try:
            report_path.write_text(json.dumps(signoff, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            logger.warning(f"签核报告写入失败: {e}")

        score = 80 if verdict == "READY" else 40
        # 说真话：门禁不满足 → 如实失败（success=False），不再无条件"通过"
        return ExecutorResult(success=(verdict == "READY"), data={"report": signoff, "score": score})
