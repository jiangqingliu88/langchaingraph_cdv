"""绑定表 —— 清单里能写哪些工具名。

这里**只登记核实过路径的条目**：名字、python 路径、返回值怎么解释。清单里
写了一个这里没有的名字，启动时就会拿到一句「没有这个绑定，已登记：…」，
而不是运行到一半才发现。

`pure=False` 的口径是**「有副作用或有成本」**，不只是"贵"：

  · 花钱：LLM 调用
  · 起子进程：编译、仿真/回归
  · **写盘**：人工编辑记账（`evidence.record_human_edit`）—— 它很快，但**不可逆**，
    绝不能因为「切了个标签页」就往证据链里写一条

`pure=False` 的绑定必须显式传 `force=True` 才肯跑，顺便也挡住了上面这些
"顺手跑一遍"。清单见 `src/workbench/tests/test_bridge.py`（多一条少一条都要
先改那里 —— 那条测试的用处就是逼人回答"它凭什么能自动跑"）。

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
        name="debug.bisect_failed_tests",
        target="src.workbench.bridge.adapters:bisect_failed_tests",
        kind="json",
        doc="失败用例集合内分批缩小 + 指纹归组（只出计划，不真跑仿真；不做代码版本溯源）",
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

    # ══ 集成设计环境：声明式 YAML ═════════════════════════════════
    # 读一份 YAML 按 JSON Schema 校验，纯读、无子进程，所以是 pure。
    ToolBinding(
        name="ide.manual_nodes",
        target="src.tools.ide_tools.api:run_manual_nodes",
        kind="json",
        doc="manual_nodes.yaml → 人工节点声明 schema 校验结果",
    ),
    ToolBinding(
        name="ide.ip_spec",
        target="src.tools.ide_tools.api:run_ip_spec",
        kind="json",
        doc="ip_spec.yaml → IP 规格声明 schema 校验结果",
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

    # ══ 覆盖率豁免（Exclude）══════════════════════════════════════
    # 提议由覆盖率阶段的"自动发现"在跑（`graph.py` 那句「已提议（待审批）」），
    # 但在此之前**只有 CLI** 能批（`vagent exclude approve`）—— 工作台里没有任何
    # 一页看得到待批的提议。于是这些东西的现状是：提议一直攒，没人批。
    #
    # 批准会改动**覆盖率分母**（把点从分母里拿掉 = 放行一个原本没覆盖的点），
    # 所以批准/拒绝两条都是 `pure=False`：**不可逆，且不能因为切标签页就发生**。
    ToolBinding(
        name="coverage.excludes",
        target="src.tools.coverage_tools.exclude_api:read_excludes",
        kind="json",
        doc="覆盖率豁免登记册 → 待批 / 已批（带审批人与哈希指纹）/ 统计",
    ),
    ToolBinding(
        name="coverage.approve_exclude",
        target="src.tools.coverage_tools.exclude_api:approve_exclude",
        kind="json", pure=False,
        doc="批准一条豁免 —— 签名 + 哈希指纹入链（改动覆盖率分母）",
    ),
    ToolBinding(
        name="coverage.reject_exclude",
        target="src.tools.coverage_tools.exclude_api:reject_exclude",
        kind="json", pure=False,
        doc="拒绝一条豁免 —— 该点仍需覆盖",
    ),

    # 测试点 / 验证资产跟踪表 —— 读一份 YAML，纯读、无子进程，所以是 pure。
    ToolBinding(
        name="flow.tracking",
        target="src.tools.tracking_tools.api:run_tracking",
        kind="json",
        doc="tracking.yaml → 测试点与验证资产跟踪表（JSON）",
    ),

    # 进度趋势 —— 同样是读一份 YAML 的纯读绑定，切标签页不弹确认。
    ToolBinding(
        name="flow.trend",
        target="src.tools.trend_tools.api:run_trend",
        kind="json",
        doc="trend.yaml → 各阶段进度趋势（build 数量 + P0-P3 通过率）",
    ),

    # 签核判定 —— 读一次运行目录里的 report.json + docs/evidence_chain.json。
    # 纯读、无子进程，所以是 pure；run_dir 由调用方从 pipeline.detail 取。
    ToolBinding(
        name="flow.signoff",
        target="src.tools.flow_tools.api:run_signoff",
        kind="json",
        doc="一次运行目录 → 签核门禁 + 六层证据链 + 总判定",
    ),

    # 任务总览 —— 一次运行作为一个「验证任务」：目标 / 进度 / 收敛预测 / 卡点。
    ToolBinding(
        name="flow.task",
        target="src.tools.flow_tools.api:run_task",
        kind="json",
        doc="一次运行目录 → 任务总览（目标 / 覆盖率 / 收敛预测 / 卡在哪）",
    ),

    # 一次运行的**中间产物**目录 + 每份的 schema 体检。纯读盘，所以是 pure。
    # 刻意不含 `docs/*.json` / `report.json` —— 那几份是**证据**（机器写下的结论
    # 与哈希链），改了等于篡改结论，不给编辑入口。
    ToolBinding(
        name="flow.artifacts",
        target="src.tools.flow_tools.api:run_artifacts",
        kind="json",
        doc="一次运行目录 → 中间产物清单（存在与否 / 哈希 / schema 体检）",
    ),

    # 闭环流程的**结构**（阶段组 + 成员节点 + 回边）—— 读领域自己的
    # `stages.py`，界面不另抄一份阶段清单（抄了就是第二份真相）。
    ToolBinding(
        name="flow.stages",
        target="src.workbench.bridge.adapters:stage_flow",
        kind="json",
        doc="闭环流程结构（阶段组 / 成员节点 / 每轮回边）",
    ),

    # 某个 agent 的产出总览 —— 七条 agent 线共用这一个绑定（role 作参数）。
    # 数据源同上：运行目录里的日志与产物。
    ToolBinding(
        name="agent.outputs",
        target="src.tools.flow_tools.api:run_agent_outputs",
        kind="json",
        doc="一次运行目录 + agent 角色 → 该 agent 的阶段与产物",
    ),
    ToolBinding(
        name="flow.decision",
        target="src.tools.flow_tools.api:run_decision_trace",
        kind="json",
        doc="一次运行目录 → 逐轮决策动作与驾驭裁决",
    ),
    ToolBinding(
        name="flow.regression_status",
        target="src.tools.flow_tools.api:run_regression_status",
        kind="json",
        doc="一次运行目录 → 回归用例状态（用例/状态/耗时/UVM 计数/日志/波形/覆盖率库）",
    ),
    # 覆盖率库是二进制，人看不了 —— 这个绑定把它摊成 HTML 报告（`vcover report
    # -html`）再打开，人才能真去校对。它**会写盘**（报告落在库旁边），所以不是
    # pure：得由人点一下显式触发（`force=True`），顺带也挡住"切个标签页就编报告"。
    ToolBinding(
        name="flow.coverage_report",
        target="src.tools.coverage_tools.cov_api:build_coverage_report",
        kind="json", pure=False,
        doc="覆盖率库 → HTML 报告（已是最新则复用）；返回报告路径供界面打开",
    ),
    # 一次运行的**总覆盖率**：数字 + 合并库 + 覆盖率阶段那份报告在哪。纯读盘
    # （只看文件在不在、多大、什么时候写的），所以是 pure。
    ToolBinding(
        name="flow.run_coverage",
        target="src.tools.flow_tools.api:run_coverage",
        kind="json",
        doc="一次运行目录 → 总覆盖率（总/功能 + 分项 + 合并库与报告的位置）",
    ),
    ToolBinding(
        name="flow.rule_drafts",
        target="src.tools.flow_tools.api:run_rule_drafts",
        kind="json",
        doc="一次运行 → 起草的规则草案（含粘贴骨架与是否已被接受）",
    ),
    ToolBinding(
        name="flow.todo",
        target="src.tools.flow_tools.api:collect_todos",
        kind="json",
        doc="一次运行 → 「现在该干什么」（待审批 / 待签豁免 / 需人工确认 / 卡住 / 挂死）",
    ),
    ToolBinding(
        name="flow.compare",
        target="src.tools.flow_tools.api:compare_runs",
        kind="json",
        doc="两次运行 → 逐项对比（覆盖率 delta / 变坏的用例 / 修复的用例 / 判定变化）",
    ),
    ToolBinding(
        name="flow.manifest",
        target="src.tools.flow_tools.api:run_manifest_info",
        kind="json",
        doc="一次运行目录 → 运行清单 + 文件变更链",
    ),

    # 人工编辑记账 —— 人在界面上改了文件，往**项目级**人工变更链写一条，
    # 并在给了 run_id 时往那次运行的日志追加一条 `human.edit`。
    # 写盘，所以不是 pure。
    ToolBinding(
        name="evidence.record_human_edit",
        target="src.layers.l2_orchestration.evidence.human_edit:record_human_edit",
        kind="json", pure=False,
        doc="人工编辑一个文件 → 项目级变更链 + （可选）运行日志锚点",
    ),
    ToolBinding(
        name="evidence.human_edits",
        target="src.layers.l2_orchestration.evidence.human_edit:read_human_edits",
        kind="json",
        doc="读回项目级人工变更链 + 完整性自校验（只读，pure）",
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
