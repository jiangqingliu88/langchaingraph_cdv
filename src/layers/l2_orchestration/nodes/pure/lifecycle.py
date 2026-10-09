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


async def n_init(state: PipelineState, config) -> Dict[str, Any]:
    """重建所有运行期对象 —— 直接跑时的入口（重入时走 `hydrate_runtime`）。"""
    rt = _rt(config)
    hydrate_runtime(rt, state)
    return {"phases": [{"name": "planning", "status": "planned",
                        "target": state.target,
                        "milestones": rt.planner.milestones}]}


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
            "coverage_db_history": state.coverage_db_history,
            # 跨 run 成长：本次实际生效的蒸馏动作权重（可追溯「为什么这次这样决策」）
            "distilled_weights": rt.distilled_weights,
            "llm_audit": _collect_llm_audit(),
            "evidence": {"total_changes": total_changes,
                         "chain_valid": chain_valid,
                         "evidence_path": evidence_path,
                         "file_change_chain_path": file_chain_path},
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
        "status": ("BLOCKED_EDA_MISSING" if state.eda_blocked
                   else ("WAITING_APPROVAL" if state.awaiting_approval
                         else ("CONVERGED" if state.effective_coverage >= state.target
                               else "COMPLETED"))),
        "evidence": {"total_changes": total_changes, "chain_valid": chain_valid,
                     "evidence_path": evidence_path, "manifest_path": manifest_path,
                     "file_change_chain_path": file_chain_path},
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


# _collect_llm_audit 是 execution.py 的模块级函数；此处延迟引用避免循环 import
def _collect_llm_audit() -> Any:
    from src.layers.l2_orchestration.execution import _collect_llm_audit as _f
    return _f()


# ═══════════════════════════════════════════════════════════════
# 构图
# ═══════════════════════════════════════════════════════════════

#: 节点注册表 —— (节点名, 节点函数)。
#: 抽成模块级常量的理由：`stages.py` 要给每个节点配一份显示元数据（中文名 /
#: 分组 / 归属 agent），而「有哪些节点」必须只有一份。`tests/test_stages.py`
#: 断言两张表一一对应 —— 加了节点却忘了加元数据，那条测试会红。
