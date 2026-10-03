"""绑定表 —— 清单里能写哪些工具名。

这里**只登记核实过路径的条目**：名字、python 路径、返回值怎么解释。清单里
写了一个这里没有的名字，启动时就会拿到一句「没有这个绑定，已登记：…」，
而不是运行到一半才发现。

`pure=False` 的三类（LLM 调用、编译、仿真/回归）都**不登记**或标记为非纯：
它们要么花钱，要么起子进程，绝不能因为「切了个标签页」就跑起来。

排布约定：名字用 `域.动作`（`debug.collect_sim_log`），域与清单里的模块
前缀一致，grep 起来能对上。
"""
from __future__ import annotations

from typing import List

from .binding import ToolBinding

BINDINGS: List[ToolBinding] = [

    # ══ 调试技术 ══════════════════════════════════════════════════
    # 这三个都来自 debug_tools/main.py。注意 `output_dir` 不存在时它们**不抛**，
    # 而是返回 {"error": "output_dir not found: ..."} —— 这正是界面想显示的话，
    # 所以不要在后面再包一层「文件不存在」的判断。

    ToolBinding(
        name="debug.collect_sim_log",
        target="src.tools.debug_tools.main:collect_sim_log",
        kind="json",
        doc="扫 output_dir 下的仿真日志，汇总 pass/fail 与错误摘要",
    ),
    ToolBinding(
        name="debug.collect_compile_log",
        target="src.tools.debug_tools.main:collect_compile_log",
        kind="json",
        doc="扫 output_dir 下的编译日志",
    ),
    ToolBinding(
        name="debug.fingerprint_error",
        target="src.tools.debug_tools.main:fingerprint_error",
        kind="json",
        doc="为一段错误文本算去重指纹 + 归类",
    ),

    # 波形与二分：原签名吃 `input_json`，经 adapters 包成关键字参数
    ToolBinding(
        name="debug.collect_waveform",
        target="src.workbench.bridge.adapters:collect_waveform",
        kind="json",
        doc="扫 output_dir 下 *.wlf，经 wlf2log 解析出信号时间线（需 QuestaSim）",
    ),
    ToolBinding(
        name="debug.bisect_test",
        target="src.workbench.bridge.adapters:bisect_test",
        kind="json",
        doc="二分定位失败用例的最小集合（只出计划，不真跑仿真）",
    ),

    # ══ 日志解析（纯文本进、dict 出，不需要任何 EDA 工具）══════════
    # 这三个来自 src/tools/lib/sim_log.py，是「手上有日志文本但没有 output/
    # 目录」时的入口 —— 界面里粘贴一段日志就能用。

    ToolBinding(
        name="sim.parse_log",
        target="src.tools.lib.sim_log:parse_sim_log",
        kind="auto",
        doc="把一段仿真日志文本解析成结构化结果",
    ),
    ToolBinding(
        name="sim.analyze_compile",
        target="src.tools.lib.sim_log:analyze_compile_log",
        kind="auto",
        doc="编译日志 → 错误/警告摘要",
    ),
    ToolBinding(
        name="sim.analyze_sim",
        target="src.tools.lib.sim_log:analyze_sim_log",
        kind="auto",
        doc="仿真日志 → 结果摘要",
    ),

    # ══ 验证管理系统：case 模型 ═══════════════════════════════════
    # casemodel_tools.api 是**唯一**已经是 dict 进 dict 出、且零 LLM 依赖的
    # 工具面；normalize 对它基本是空操作。

    ToolBinding(
        name="casemodel.validate",
        target="src.tools.casemodel_tools.api:run_validate",
        kind="json",
        doc="YAML → schema 校验结果",
    ),
    ToolBinding(
        name="casemodel.gaps",
        target="src.tools.casemodel_tools.api:run_gaps",
        kind="json",
        doc="YAML → 完备性分析（评分 / 覆盖 / 诊断）",
    ),
    ToolBinding(
        name="casemodel.generate",
        target="src.tools.casemodel_tools.api:run_generate",
        kind="json",
        doc="YAML → case 属性表",
    ),
    ToolBinding(
        name="casemodel.uvm_tests",
        target="src.tools.casemodel_tools.api:run_uvm_tests",
        kind="json",
        doc="YAML → UVM 的 environment.tests 片段（一条 = 一个 UVM_TEST）",
    ),

    # ══ 验证流程（闭环运行）═══════════════════════════════════════
    # 界面**不直接 import** graph.py / execution.py —— 只能经这张白名单到 L2。
    # 「GUI 能碰什么」因此永远是一份可审计的清单。
    #
    # 读的那三个是 pure：列表页、日志轮询会反复调，不该每次弹确认。
    # 启停那两个不是：启动一次运行会烧 LLM 与 EDA，必须显式触发
    # （`call(..., force=True)`），顺便也挡住了"切个标签页就顺手跑一遍"。

    ToolBinding(
        name="pipeline.start",
        target="src.layers.l2_orchestration.run_service:start_run",
        kind="json", pure=False,
        doc="启动一次闭环验证（立即返回 run_id）",
    ),
    ToolBinding(
        name="pipeline.cancel",
        target="src.layers.l2_orchestration.run_service:cancel_run",
        kind="json", pure=False,
        doc="协作式取消运行（停在节点边界）",
    ),
    ToolBinding(
        name="pipeline.runs",
        target="src.layers.l2_orchestration.run_service:list_runs",
        kind="json",
        doc="运行列表（含正在跑的与跑挂的）",
    ),
    ToolBinding(
        name="pipeline.journal",
        target="src.layers.l2_orchestration.run_service:read_run_journal",
        kind="json",
        doc="增量读运行日志（after_seq 只取新增）",
    ),
    ToolBinding(
        name="pipeline.status",
        target="src.layers.l2_orchestration.run_service:run_status",
        kind="json",
        doc="一次运行的概览（当前阶段 / 轮次 / 状态）",
    ),
    ToolBinding(
        name="pipeline.detail",
        target="src.layers.l2_orchestration.run_service:run_detail",
        kind="json",
        doc="一次运行的全部可见信息（产物 + 过程）",
    ),
    ToolBinding(
        name="pipeline.approval_handler",
        target="src.layers.l2_orchestration.run_service:set_approval_handler",
        kind="json", pure=False,
        doc="装上「有人要审批了」的接收方（界面装，None 卸载）",
    ),
    ToolBinding(
        name="pipeline.answer_approval",
        target="src.layers.l2_orchestration.run_service:answer_approval",
        kind="json", pure=False,
        doc="回答当前挂起的审批（approve/reject/skip/review）",
    ),
    ToolBinding(
        name="pipeline.pending_approval",
        target="src.layers.l2_orchestration.run_service:pending_approval",
        kind="json",
        doc="当前是否有人正等着审批",
    ),
    ToolBinding(
        name="pipeline.resume",
        target="src.layers.l2_orchestration.run_service:resume_run",
        kind="json", pure=False,
        doc="从检查点接着跑一次暂停的运行（approve/reject/skip）",
    ),
]


def bindings() -> List[ToolBinding]:
    """给 `ToolRegistry` 用的默认绑定列表。返回副本，调用方改不到表本身。"""
    return list(BINDINGS)


def by_name(name: str):
    for binding in BINDINGS:
        if binding.name == name:
            return binding
    return None


def default_registry():
    """建一个装好默认绑定的注册表 —— 界面的标准入口。"""
    from .binding import ToolRegistry

    registry = ToolRegistry()
    registry.register_all(BINDINGS)
    return registry
