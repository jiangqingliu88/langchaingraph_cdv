"""纯函数节点 · 生命周期

图的入口与出口：`init` 建运行期对象，`finalize` 收签核产物。
"""
from __future__ import annotations

from typing import Any, Dict

from datetime import datetime
from pathlib import Path
import json
import time

import structlog

from src.layers.l2_orchestration.runtime import (
    hydrate_runtime, _rt, _git_head,
)
from src.layers.l2_orchestration.state import PipelineState

logger = structlog.get_logger()


def _ensure_architecture_v2(output_root: Path, rt, target: float) -> Dict[str, Any]:
    """收尾时确保血缘/质量门存在，并把 Spool 事件灌进 run 的事实日志。

    audit 通常已经写过这两份文件；这里再做一次是**幂等的**，覆盖两种异常路径：
    audit 提前失败、或老 run 目录在 --resume 后缺文件。任何失败只 warning ——
    证据增量不能拦住 finalize。
    """
    try:
        from src.core.provenance.graph import write_provenance
        from src.core.provenance.report import write_attribution_report
        from src.core.metrics.engineering import write as write_metrics
        from src.core.verification.quality import write as write_quality
        from src.core.runtime.events import flush_spool

        store = getattr(rt, "event_store", None)
        if store is not None:
            flush_spool(store)
        prov = write_provenance(output_root, event_store=store)
        attribution = write_attribution_report(output_root)
        quality = write_quality(
            output_root, target=(target if target and target > 0 else None),
            run_id=output_root.name, event_store=store)
        metrics = write_metrics(output_root, event_store=store)
        return {
            "schema": "architecture_v2_v1",
            "provenance": {
                "path": Path(prov["path"]).relative_to(output_root).as_posix(),
                "sha256": prov["jsonl_sha256"],
                "nodes": prov["summary"]["nodes"],
                "edges": prov["summary"]["edges"],
                "by_confidence": prov["summary"]["by_confidence"],
            },
            "attribution": {
                "path": Path(attribution["path"]).relative_to(output_root).as_posix(),
                "hit_bins": attribution["hit_bins"],
                "attribution_rate": attribution["attribution_rate"],
                "test_seed_rate": attribution["test_seed_rate"],
                "exact_rate": attribution["exact_rate"],
                "weak_rate": attribution["weak_rate"],
            },
            "engineering_metrics": {
                "path": Path(metrics["path"]).relative_to(output_root).as_posix(),
                "regression_seconds": metrics["regression"]["total_seconds"],
                "attribution_rate": metrics["attribution"]["attribution_rate"],
                "decision_rate": metrics["decision"]["effectiveness_rate"],
                "incremental": metrics["incremental"],
            },
            "verification_quality": {
                "path": Path(quality["path"]).relative_to(output_root).as_posix(),
                "overall": quality["overall"],
                "dimensions": {k: v["status"]
                               for k, v in quality["dimensions"].items()},
            },
        }
    except Exception as e:                             # noqa: BLE001
        logger.warning(f"Architecture 2.0 证据收尾失败（不影响 finalize）: {e}")
        return {}


async def n_init(state: PipelineState, config) -> Dict[str, Any]:
    """重建所有运行期对象 —— 直接跑时的入口（重入时走 `hydrate_runtime`）。"""
    rt = _rt(config)
    hydrate_runtime(rt, state)
    return {"phases": [{"name": "planning", "status": "planned",
                        "target": state.target,
                        "milestones": rt.planner.milestones}]}


def _attach_rtl_lineage(state: PipelineState, rtl_dir: Path,
                        run_id: str) -> Dict[str, Any]:
    """把「这一轮跑的是哪一版 RTL」记进血缘库，并在首次跑时锚下基准。

    版本号由 `ensure_run_rtl_version` 出（**front / debug / finalize 共用同一个
    入口**，各算一遍就会同一个 run 三个版本号而都不报错）。这里只多做一件事：
    **首次 run 锚基准**。

    返回写进 manifest 的 `rtl_version`（`{}` = 这一轮没有 RTL）。**任何失败都只
    记 warning 并返回 `{}`** —— 血缘是**可加的元数据**，不该因为写不进去就让整个
    run 的收尾失败（证据链、manifest 那些更要紧）。
    """
    try:
        from src.layers.l4_memory.lineage import ensure_run_rtl_version, LineageStore

        rtl_version = ensure_run_rtl_version(rtl_dir.parent, run_id=run_id)
        if not rtl_version:
            return {}
        store = LineageStore()
        try:
            is_new = store.ensure_baseline(rtl_version["module"], run_id,
                                           rtl_version["version_no"])
        finally:
            store.close()                                  # Windows 文件锁
        logger.info(f"血缘：{rtl_version['module']} {rtl_version['name']}"
                    f"（run={run_id}，{rtl_version['content_hash'][:12]}）"
                    + ("—— **首次会话，已锚为基准**" if is_new else ""))
        return rtl_version
    except Exception as e:                                 # noqa: BLE001
        logger.warning(f"血缘落盘失败（RTL 版本未记录）: {e}")
        return {}


def _run_status(state: PipelineState) -> str:
    """终态字符串 —— 硬审计失败必须优先于覆盖率/EDA 状态。"""
    if state.audit_gate and state.audit_gate.get("ok") is False:
        return "AUDIT_BLOCKED"
    if state.eda_blocked:
        return "BLOCKED_EDA_MISSING"
    if state.awaiting_approval:
        return "WAITING_APPROVAL"
    if state.effective_coverage >= state.target:
        return "CONVERGED"
    return "COMPLETED"


async def n_finalize(state: PipelineState, config) -> Dict[str, Any]:
    """证据链落盘 + manifest + 释放资源。"""
    rt = _rt(config)
    output_root = Path(state.output_root)

    # ── 文件级变更链（谁改了什么、为什么）──
    docs = output_root / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    file_chain_path = ""
    chain_valid, total_changes = False, 0
    if rt.file_audit is not None:
        try:
            chain = rt.file_audit.to_dict()
            chain_valid = rt.file_audit.verify()
            chain["chain_valid"] = chain_valid
            total_changes = chain.get("total_changes", 0)
            file_chain_path = str(docs / "file_change_chain.json")
            Path(file_chain_path).write_text(
                json.dumps(chain, indent=2, ensure_ascii=False, default=str),
                encoding="utf-8")
            # 回读磁盘复核：内存 verify() 等于「自己验自己」，尾部被裁发现不了
            from src.layers.l2_orchestration.evidence.file_audit import FileAuditTrail
            persisted = FileAuditTrail.verify_persisted(file_chain_path)
            if not persisted["valid"]:
                logger.warning(f"文件变更链落盘后复核未通过: {persisted['issues']}")
                chain_valid = False
        except Exception as e:
            logger.warning(f"文件变更链落盘失败: {e}")

    # ── 五层领域证据（L1 需求 / L2 设计 / L3 验证 / L4 执行 / L4.5 功能覆盖 / L5 签核）──
    # 落在 docs/evidence_chain.json —— CLI 的 _print_evidence_chain 读的就是这个结构，
    # 此前没有任何东西产出它，那段打印因此永远显示 0/0 与 NO。
    evidence_path = ""
    try:
        from src.layers.l2_orchestration.evidence.five_layer import FiveLayerEvidence
        ev = FiveLayerEvidence(output_root).build(
            spec=state.spec, design_arch=state.design_arch, tests=state.tests,
            regression=state.regression, coverage=state.coverage,
            final_coverage=state.final_coverage, target=state.target,
            exclude_effect=state.exclude_effect, phases=state.phases,
            evidence_chain_valid=chain_valid)
        evidence_path = str(docs / "evidence_chain.json")
        Path(evidence_path).write_text(
            json.dumps(ev, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8")
    except Exception as e:
        logger.warning(f"五层证据落盘失败: {e}")

    manifest_path = ""
    rtl_version = {}

    # ── Architecture 2.0：血缘 + 五维质量门（幂等；失败只 warning）──
    architecture_v2 = _ensure_architecture_v2(output_root, rt, state.target)

    # ── Manifest：运行清单 ──
    try:
        docs = output_root / "docs"
        docs.mkdir(parents=True, exist_ok=True)
        from src.layers.l1_infrastructure.infrastructure import sha256_file
        rtl_hashes = {}
        rtl_dir = output_root / "rtl"
        if rtl_dir.exists():
            for sv in sorted(rtl_dir.glob("*.sv")):
                rtl_hashes[sv.name] = sha256_file(sv)[:16]

        # ── 血缘：这一轮跑的是 RTL 的哪一版 + 首次 run 当基准 ──
        #
        # `rtl_hashes` 是**给人看的短标识**（`[:16]`、只 `*.sv`），做身份会撞；
        # 血缘用 `compute_rtl_dir_hash` 的全 64 位聚合（收 `.v/.svh/.vh`）。
        # 空 RTL 目录 → 空串 → **整条跳过**（没 RTL 与 RTL 是空的，不该长得一样）。
        rtl_version = _attach_rtl_lineage(state, rtl_dir, str(output_root.name))

        manifest = {
            "architecture": "closed_loop_7agents",
            # 产出时刻 + 代码版本。**这两条本来写在每个生成文件的头注释里**，
            # 但那会让产物不可复现（同一输入两次跑，内容哈希对不上，见
            # gen_uvm.reproducible_now 的说明）。它们属于「这次 run 的元数据」，
            # 该记在 manifest 里 —— 每个产物文件没有独立的时间戳，整份签核包
            # 共用一个。
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "git_head": _git_head(output_root),
            "target": state.target,
            "final_coverage": state.final_coverage,
            "effective_coverage": state.effective_coverage,
            "converged": state.effective_coverage >= state.target,
            "iterations": state.iterations,
            "phases": state.phases,
            "planning": {"target": rt.planner.target,
                         "milestones": rt.planner.milestones,
                         "convergence_forecast":
                             rt.planner.predict_convergence(state.coverage_history)},
            "testcase_portfolio": rt.testcase_reg.get_portfolio(),
            "testcase_stats": rt.testcase_reg.get_stats(),
            "exclude": {"stats": rt.exclude_reg.stats(),
                        "effect": state.exclude_effect,
                        "approved_points": sorted(rt.exclude_reg.get_excluded_points())},
            "rtl_hashes": rtl_hashes,
            # 血缘：`{module, version_no, name, content_hash}` —— 空字典 = 这一轮
            # 没有 RTL（不是"版本是空的"）。下游（debug/bug 记录、用例句柄）读它。
            "rtl_version": rtl_version,
            "coverage_db_history": state.coverage_db_history,
            # 跨 run 成长：本次实际生效的蒸馏动作权重（可追溯「为什么这次这样决策」）
            "distilled_weights": rt.distilled_weights,
            "llm_audit": _collect_llm_audit(),
            "evidence": {"total_changes": total_changes,
                         "chain_valid": chain_valid,
                         "evidence_path": evidence_path,
                         "file_change_chain_path": file_chain_path,
                         "architecture_v2": architecture_v2},
        }
        manifest_path = str(docs / "manifest.json")
        Path(manifest_path).write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8")
    except Exception as e:
        logger.warning(f"Manifest 落盘失败: {e}")

    # 汇总 Exclude 状态后释放 sqlite 连接（Windows 文件锁）
    exclude_stats = rt.exclude_reg.stats()
    try:
        rt.exclude_reg.close()
    except Exception:
        pass

    _passed = sum(1 for p in state.phases if p.get("status") == "passed")
    _name = Path(state.output_root).name
    _run_id = f"run_{_name.split('_')[-1] if '_' in _name else 'closed_loop'}"

    result = {
        "architecture": "closed_loop_7agents",
        "run_id": _run_id,
        "output_root": state.output_root,
        "phases": state.phases,
        "passed": _passed,
        "total": len(state.phases),
        "overall_score": round(state.effective_coverage, 1) if state.effective_coverage else 0,
        "final_coverage": state.final_coverage,
        "effective_coverage": state.effective_coverage,
        "converged": state.effective_coverage >= state.target,
        "eda_blocked": state.eda_blocked,
        "target": state.target,
        "iterations": state.iterations,
        "exclude": {"stats": exclude_stats, "effect": state.exclude_effect},
        "status": _run_status(state),
        "audit_gate": state.audit_gate,
        "evidence": {"total_changes": total_changes, "chain_valid": chain_valid,
                     "evidence_path": evidence_path, "manifest_path": manifest_path,
                     "file_change_chain_path": file_chain_path,
                     "architecture_v2": architecture_v2},
        # 预算实况：token 预算刚接上真实用量，把数字暴露出来，
        # 否则「预算耗尽」拦截时没人知道到底用了多少、该把阈值调到哪。
        "budget": (rt.governor.budget.status() if rt.governor else {}),
    }
    if rt.governor:
        _b = rt.governor.budget
        logger.info(f"预算: tokens {_b.tokens_used}/{_b.token_budget} · "
                    f"eda {_b.eda_calls}/{_b.eda_budget} · "
                    f"time {_b.time_used_s:.0f}s/{_b.time_budget_s:.0f}s")
    return {"result": result}


# `_collect_llm_audit` 已随 execution.py 拆分搬到 `execution_helpers`；
# 这里延迟引用避免循环 import（execution → lifecycle → execution）。
def _collect_llm_audit() -> Any:
    from src.layers.l2_orchestration.execution_helpers import _collect_llm_audit as _f
    return _f()


# ═══════════════════════════════════════════════════════════════
# 构图
# ═══════════════════════════════════════════════════════════════

#: 节点注册表 —— (节点名, 节点函数)。
#: 抽成模块级常量的理由：`stages.py` 要给每个节点配一份显示元数据（中文名 /
#: 分组 / 归属 agent），而「有哪些节点」必须只有一份。`tests/test_stages.py`
#: 断言两张表一一对应 —— 加了节点却忘了加元数据，那条测试会红。
