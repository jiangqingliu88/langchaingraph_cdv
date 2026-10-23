"""executor 节点 · 执行与观测

中段：编译仿真回归 → 覆盖率收集 → 功能失败调试。
"""
from __future__ import annotations

from typing import Any, Dict

from pathlib import Path

import structlog

from src.layers.l2_orchestration.nodes.agent.fix import _triage_harness
from src.layers.l2_orchestration.runtime import (
    _token_delta, _rt, _as_float, _run_agent,
)
from src.layers.l2_orchestration.state import PipelineState

logger = structlog.get_logger()


async def n_ops(state: PipelineState, config) -> Dict[str, Any]:
    rt = _rt(config)
    # round_num 经 round_bump 后即为 1 基轮次（原 for-range 是 0 基），故直接用
    # `sim_modes` 与 `design_style` 同位：都是"这次运行怎么跑"的输入，不是全局开关。
    data, phase = await _run_agent(rt, state, "ops", f"ops_r{state.round_num}",
                                   {"design_style": state.design_style,
                                    "sim_modes": list(state.sim_modes or []),
                                    # 分级回归的人工节点开不开（工具栏那个开关）。
                                    # 不开 = `run_regression_staged(auto_approve=True)`。
                                    "manual_gate": bool(state.manual_gate)})
    regression = data.get("regression", {}) if isinstance(data, dict) else {}

    # ── EDA 缺失检测（优先级最高：环境问题不是代码问题，终止闭环）──
    if isinstance(regression, dict) and regression.get("eda_missing"):
        _err = str(regression.get("error", ""))[:200]
        logger.error(f"EDA 工具缺失，终止闭环（安装 QuestaSim 并加入 PATH 后重试）: {_err}")
        return {"regression": regression, "regression_failed_count": 0,
                "eda_blocked": True, "interrupted": True,
                "terminal_reason": "eda_missing",
                "phases": [phase, {"name": "eda_check", "status": "failed",
                                   "reason": f"EDA 工具缺失: {_err}"}]}

    # ── 人工节点检测：回归停在 loopback 等人放行 → 终止闭环 ──
    # **不是失败**，机器也不该空转：不拦的话每轮都停在同一个放行点、每轮都被判成
    # ops 失败，白烧 `max_rounds` 轮才收场（实测 5 轮跑完发现 5 次都是同一件事，
    # 而 P0 一次都没跑过）。放行是人的动作 —— 机器在这里该做的是**停下来交棒**。
    if isinstance(data, dict) and data.get("awaiting_approval"):
        aw = data.get("awaiting_approval") or {}
        logger.warning(f"分级回归停在人工节点 {aw.get('after')} → {aw.get('next')}，"
                       f"终止闭环等人放行（{aw.get('hint', '')}）")
        return {"regression": regression, "regression_failed_count": 0,
                "awaiting_approval": True, "interrupted": True,
                "terminal_reason": "awaiting_approval",
                "phases": [phase, {"name": "manual_gate",
                                   "status": "waiting_approval",
                                   "reason": (f"{aw.get('after')} 已全过，进 "
                                              f"{aw.get('next')} 前需人工放行："
                                              f"{aw.get('hint', '')}")}]}

    # ── 编译失败检测 ──
    compile_error = None
    if isinstance(regression, dict) and regression.get("compile") == "FAIL":
        try:
            from src.layers.l1_infrastructure.compile_healer import CompileErrorAnalyzer
            stderr = regression.get("stderr", regression.get("compile_errors", ""))
            cr = CompileErrorAnalyzer.analyze(str(stderr))
            compile_error = {"error_type": cr.error_type.value,
                             "message": cr.error_message,
                             "file": cr.error_file, "line": cr.error_line}
        except Exception as e:
            logger.warning(f"编译错误分析失败: {e}")

    failed = regression.get("failed", 0) if isinstance(regression, dict) else 0
    # **挂死/看门狗超时不算功能失败**：那是 bench/激励侧的事。算进去的后果是决策引擎
    # 按 REFACTOR_RTL 去改 RTL —— 实测真跑了一轮 `design_fix`，改的是没坏的代码。
    # `functional_failed` 由 L1 归类后给出（见 `_HANG_RE`）；没有这个键就退回旧口径。
    harness = regression.get("harness_failures") or [] if isinstance(regression, dict) else []
    if isinstance(regression, dict) and "functional_failed" in regression:
        decision_failed = int(regression.get("functional_failed", 0) or 0)
    else:
        decision_failed = failed
    if harness:
        phase["harness_failures"] = harness[:5]
        # ── C：挂死也要有**归因**，不能只留一串日志文本 ──
        # 取指纹（规范化后 MD5）+ 归类，走 debug_tools 的纯函数工具。
        # **只归类、不改 RTL** —— 这是"挂死不该引着改设计"与"挂死也得看得懂"
        # 之间的分界：debug 的判断力用上了，它那条改 RTL 的路没走。
        phase["harness_triage"] = _triage_harness(harness)
        # **定案 → 规则草案**：这类挂死反复出现、有指纹，却没有任何规则在拦它 ——
        # 正是最该长出一条规则的地方。只起草，不自动生效（见 rule_draft 的说明）。
        try:
            from src.layers.l4_memory.rule_draft import (drafts_from_triage,
                                                        write_drafts)

            _n = write_drafts(Path(state.output_root),
                              drafts_from_triage(phase["harness_triage"],
                                                 Path(state.output_root).name))
            if _n:
                phase["rule_drafts"] = _n
                logger.info(f"起草 {_n} 条规则草案 → docs/rule_drafts.md（等人拍板）")
        except Exception as _e:                        # noqa: BLE001 起草是旁路
            logger.debug(f"规则起草跳过: {_e}")
        # ── B：把"为什么没进 debug"写进 phase ──
        # 不然界面上只有一行日志，人会问"debug agent 怎么没触发"（真被问过）。
        if not decision_failed and not compile_error:
            phase["debug_skipped_reason"] = (
                f"{len(harness)} 个失败全是 bench 侧（挂死/看门狗超时）—— "
                f"debug 只修 DUT 功能错，不改 bench；已按指纹归类，见 harness_triage")
        phase["reason"] = (str(phase.get("reason", "")) +
                           f" | {len(harness)} 个 test 挂死/看门狗超时（bench 侧，"
                           f"不计入功能失败）")[:400]
        logger.warning(f"ops：{len(harness)} 个 test 挂死/看门狗超时，"
                       f"不计入功能失败、不触发 RTL 重构：{harness[:3]}")
    return {"regression": regression, "regression_failed_count": decision_failed,
            "compile_error": compile_error, "phases": [phase]}


async def n_coverage(state: PipelineState, config) -> Dict[str, Any]:
    """coverage 阶段 —— 原循环里最大的一块（含 Exclude 调规 / 用例配比 / 归因校准）。"""
    rt = _rt(config)
    svc = rt.service
    data, phase = await _run_agent(rt, state, "coverage",
                                   f"coverage_r{state.round_num}",
                                   {"seed": state.seed, "round_num": state.round_num})

    coverage = data.get("coverage", {}) if isinstance(data, dict) else {}
    gaps = data.get("gaps", []) if isinstance(data, dict) else []
    final_coverage = state.final_coverage
    if isinstance(coverage, dict):
        # **按口径取**（默认功能覆盖率）—— 收敛信号盯哪个数由
        # `Settings.verification.coverage_metric` 决定，不是写死代码覆盖率。
        #
        # 写死代码覆盖率的后果实测过：闭环的动作（按覆盖点 gap 生成定向激励）
        # 主要动功能覆盖率，而收敛信号盯的是代码覆盖率 —— 于是"补了但数字不动"
        # 连续六轮，`convergence_forecast` 报 `rounds_to_target: Infinity`，
        # 而真正的功能覆盖率同期是 64.81%。**闭环在盯一个它的动作推不动的数。**
        from src.layers.l2_orchestration.planning import pick_coverage_value
        _pick = pick_coverage_value(coverage)
        final_coverage = round(_pick["value"], 1)
        if not _pick["present"]:
            # 缺就**说出来**，不悄悄换另一个口径（那会让目标在无声中换掉）
            logger.warning(f"口径 {_pick['metric']} 的覆盖率没采到"
                           f"（缺 {_pick['key']}）—— 本轮收敛信号按 0 计；"
                           f"两个口径的现值：{ {k: coverage.get(k) for k in ('overall_pct','functional_pct')} }")
        else:
            logger.info(f"覆盖率口径={_pick['metric']} → {final_coverage}%"
                        f"（另一个口径："
                        f"{'code' if _pick['metric'] == 'functional' else 'functional'}"
                        f"={coverage.get('overall_pct' if _pick['metric'] == 'functional' else 'functional_pct')}%）")

    # ── Exclude 四步闭环：自动发现 → 提议；已批准 → 有效覆盖率调规 ──
    coverage_map = data.get("coverage_map", {}) if isinstance(data, dict) else {}
    exclude_effect = {"excluded": 0, "effective_total": 0,
                      "effective_coverage": final_coverage}
    effective_coverage = final_coverage
    if isinstance(coverage_map, dict) and coverage_map.get("total"):
        calibration = data.get("calibration", {}) if isinstance(data, dict) else {}
        proposed = svc._discover_excludes(rt.exclude_reg, gaps, calibration)
        if proposed:
            logger.info(f"Exclude 自动发现 {proposed} 处结构性不可达覆盖点，已提议（待审批）")
        exclude_effect = rt.exclude_reg.effective_coverage_from_map(coverage_map)
        effective_coverage = exclude_effect.get("effective_coverage", final_coverage)
        if exclude_effect.get("excluded"):
            logger.info(f"Exclude 调规：{exclude_effect['excluded']} 点已放弃，"
                        f"有效覆盖率 {effective_coverage}%（原始 {exclude_effect['raw_coverage']}%）")

    # ── 用例比例动态优化：覆盖率反馈 → 调 purpose 权重 → 影响下一轮优先级 ──
    try:
        _by_purpose = {
            "functional": {"coverage": coverage.get("functional_pct", final_coverage),
                           "sim_time": 0},
            "protocol": {"coverage": coverage.get("branch_pct", 0), "sim_time": 0},
            "corner": {"coverage": coverage.get("toggle_pct", 0), "sim_time": 0},
        }
        rt.testcase_reg.optimize_portfolio({"by_purpose": _by_purpose},
                                           state.round_num)
    except Exception:
        pass

    # ── 归因校准：上一轮决策动作的成效（delta 覆盖率为反馈信号）──
    if rt.last_action is not None and rt.prev_coverage is not None:
        try:
            from src.layers.l4_memory.coverage_experience import get_coverage_experience_store
            # 按**名字**取（`last_action` 是具名字典，见 `converge.py` 的注释）——
            # 加字段不再需要同步改下标，也就不会有"漏改一处、静默取错位"。
            # `source` 一起落库：L5 蒸馏只拿 `rl_suggested` 那批学。
            get_coverage_experience_store().record_round(
                state.round_num, rt.last_action["action"], rt.last_action["reason"],
                rt.last_action["gap_reasons"], rt.prev_coverage, final_coverage,
                rt.last_action["unreachable_dims"],
                source=rt.last_action.get("source", "rule"))
            # ⚠️ 这里原来把「覆盖率没涨」记成**动作失败**，于是熔断计的是
            # "这一轮没长进" —— 而覆盖率**平台期是正常的**（边际收益递减、
            # 覆盖点本来就打不到、这一轮补的是行为不是数字）。实测后果：
            # 闭环每轮都判 `GENERATE_DIRECTED_TEST` 失败 → 连续 3 轮 → 熔断 →
            # 升级人工 → **闭环在 32.5% 处停住**，而 max_rounds 还有余量。
            #
            # 动作是否"执行成功"由执行层回答（`runtime.py` 里按 agent 的成功/异常
            # 计），覆盖率增量是**归因信号**：上面 `record_round(...)` 已经把它
            # 连同 delta 记进经验库了 —— 该用它去学"哪个动作有效"，不是用它去
            # 掐断闭环。收敛与否由 `converged` / `max_rounds` 判。
            rt.governor.after_action(rt.last_action["action"], success=True,
                                     tokens=_token_delta(rt))
        except Exception as e:
            logger.warning(f"归因校准记录失败: {e}")
    rt.prev_coverage = final_coverage

    # ── Planning：进度对比里程碑 ──
    progress = rt.planner.check_progress(state.round_num, final_coverage)
    if not progress["on_track"]:
        logger.info(f"进度落后里程碑: {progress['coverage']}% vs 里程碑 "
                    f"{progress['milestone']}%（差距 {progress['gap']}%）")

    # ── 铁律 2：覆盖率数据库版本固化记录 + 原始证据（log/VCD）哈希 ──
    from src.layers.l1_infrastructure.infrastructure import sha256_file
    _log_path = data.get("log_path", "") if isinstance(data, dict) else ""
    _vcd_path = data.get("vcd_path", "") if isinstance(data, dict) else ""
    db_entry = {
        "round": state.round_num,
        "coverage_db": data.get("coverage_db", {}) if isinstance(data, dict) else {},
        "coverage_summary": data.get("coverage_summary", "") if isinstance(data, dict) else "",
        "coverage": final_coverage,
        "log_path": _log_path, "log_sha256": sha256_file(_log_path)[:16],
        "vcd_path": _vcd_path, "vcd_sha256": sha256_file(_vcd_path)[:16],
    }

    return {
        "coverage": coverage if isinstance(coverage, dict) else {},
        "gaps": gaps if isinstance(gaps, list) else [],
        "coverage_map": coverage_map if isinstance(coverage_map, dict) else {},
        "calibration": data.get("calibration", {}) if isinstance(data, dict) else {},
        "coverage_db": data.get("coverage_db", {}) if isinstance(data, dict) else {},
        "coverage_summary": data.get("coverage_summary", "") if isinstance(data, dict) else "",
        "log_path": _log_path, "vcd_path": _vcd_path,
        "functional_coverage": coverage.get("functional_pct", final_coverage)
        if isinstance(coverage, dict) else final_coverage,
        "final_coverage": final_coverage,
        "effective_coverage": effective_coverage,
        "exclude_effect": exclude_effect,
        "coverage_db_history": [db_entry],
        "phases": [phase],
    }


async def n_debug_functional(state: PipelineState, config) -> Dict[str, Any]:
    """功能回归失败 → 跳过 coverage，进 debug 修复。"""
    rt = _rt(config)
    logger.info(f"功能回归 {state.regression_failed_count} 失败 → 跳过 coverage，进入 debug 修复")
    data, phase = await _run_agent(rt, state, "debug", f"debug_r{state.round_num}")
    updates: Dict[str, Any] = {"phases": [phase]}
    if isinstance(data.get("debug"), dict):
        updates["debug"] = data["debug"]
    return updates


