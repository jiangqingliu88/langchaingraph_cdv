"""使用指南 —— 帮助菜单里的「一页纸」：业务怎么跑、输入是什么、输出去哪看。

内容写在这里而不是散在菜单里，是为了两件事：
  1. 测试能直接断言这份指南覆盖了哪些关键路径（输入/输出/判据）；
  2. 以后改流程只需改这一处，不必翻每个模块的 HINT。

**只描述现状**：这里写的都是代码已经做到的事；没做到的在"边界"一节如实标注。
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QTextBrowser, QVBoxLayout, QWidget,
)

GUIDE_TITLE = "使用指南 · SignOffAI 验证工作台"

#: 指南里必须出现的关键词 —— 测试用它防止"指南和产品走散"
REQUIRED_TOPICS = (
    "输入材料", "怎么跑", "输出在哪", "怎么看",
    "mismatched=0", "vagent soc run", "vagent ip release-build",
    "signoff_evidence", "运行历史",
    # Verification OS / Case 证据 / 工程指标
    "contract why", "case_view", "case-gate", "case-registry",
    "metrics trend", "constraints", "OS 账本", "QUALITY_GATE",
    "ir_shadow_diff",
)

GUIDE_HTML = """
<html><body>
<h2>SignOffAI 使用指南</h2>
<p><b>一句话</b>：CLI 是唯一正式入口，Workbench 是它的桌面外壳 —— 页面里的
数字全部来自 CLI/流水线落盘的 <code>run</code> 目录，工作台自己不产生签核结论。</p>

<h3>一、三条业务线</h3>
<table border="1" cellspacing="0" cellpadding="6">
<tr><th>业务线</th><th>给谁用</th><th>典型路径</th></tr>
<tr><td><b>IP 团队</b>（供应方）</td><td>IP 负责人 / Owner</td>
    <td>IP 目录 → IP 工作区（跑 IP 回归）→ 生成发布包 → 发布检查</td></tr>
<tr><td><b>SoC 团队</b>（消费方）</td><td>SoC 验证 / 集成</td>
    <td>SoC 总览 → 验证工作区（SoC 回归 / C 用例）→ SoC 签核</td></tr>
<tr><td><b>工程服务</b></td><td>所有人</td>
    <td>UVM 自动化验证 / 回归效率优化 / Coverage Closure（只编排，跳到专业模块）</td></tr>
</table>
<p>IP 和 SoC 的覆盖率<b>分账</b>：IP 看 IP 内部覆盖点，SoC 看集成场景；
两个数字不相加，也不互相顶替。IP 发布包（<code>ip_release_v1</code>）是两者
之间的契约，SoC 每次 run 都会记录消费了哪个版本、绑定是否还对得上。</p>

<h3>二、输入材料</h3>
<h4>UVM 自动化验证（<code>vagent verify</code>）</h4>
<ul>
  <li><code>spec.md</code>（规格，用来生成 RTL）<b>或</b> <code>--rtl &lt;dir&gt;</code>（现成 RTL）；</li>
  <li><code>specs/&lt;module&gt;/</code>（VPlan 项目：<code>data/*.csv</code> + <code>cases/*.yaml</code>）——
      维度 / 覆盖仓 / 交叉 / <code>assertions</code> / <code>scoreboards</code> / 批次；</li>
  <li><code>specs/&lt;module&gt;/signoff_policy.yaml</code>（签核策略，可选）；</li>
  <li>EDA：QuestaSim（<code>vlog / vopt / vsim / vcover</code>）。</li>
</ul>
<p>每条逻辑用例的契约是<b>四集合</b>：
<code>groups[] + sva[] + scb[] + constraints[]</code>。约束 id（<code>p_*</code> 策略名）
按 coverage plan 的维度交集归属，没有交集就是空 —— <b>不编 id</b>。</p>
<h4>SoC 参考工程（<code>vagent soc</code>）</h4>
<ul>
  <li><code>spec/soc_spec.yaml</code>、<code>spec/interface_spec.yaml</code>、
      <code>spec/verification_plan.yaml</code>；</li>
  <li><code>regression/regression.yaml</code>、<code>filelist.f</code>、
      <code>rtl/</code>、<code>tb/</code>、<code>golden/</code>、<code>vectors/</code>；</li>
  <li>C 用例：<code>sw/cases.yaml</code> + RISC-V 工具链。</li>
</ul>
<h4>IP 团队</h4>
<ul>
  <li><code>spec/ip_manifest.yaml</code>（id / team / owner / version / status / rtl）；</li>
  <li><code>spec/ip_verification_plan.yaml</code>（tests / testpoints / 覆盖点 / 发布准则）。</li>
</ul>

<h3>三、怎么跑</h3>
<table border="1" cellspacing="0" cellpadding="6">
<tr><th>目标</th><th>CLI</th><th>工作台</th></tr>
<tr><td>UVM 全流程</td><td><code>vagent vplan execute specs/&lt;module&gt; --sim-mode cov</code></td>
    <td>工程服务 → UVM 自动化验证</td></tr>
<tr><td>契约 / 义务</td><td><code>vagent contract build|check|show -o &lt;run&gt;</code><br>
    <code>vagent contract why &lt;OBL-ID&gt; -o &lt;run&gt;</code><br>
    <code>vagent contract worklist|seeds|status -o &lt;run&gt;</code></td>
    <td>签核判定 →「OS 账本」页</td></tr>
<tr><td>Case 证据 / 门禁</td><td><code>vagent coverage case-evidence -o &lt;run&gt; -f html --out case_view</code><br>
    <code>vagent coverage case-gate -o &lt;run&gt; [--strict]</code><br>
    <code>vagent coverage case-registry -m &lt;module&gt;</code></td>
    <td>功能覆盖 →「Case 证据」/ 签核 →「Case 证据」</td></tr>
<tr><td>工程指标 / 趋势</td><td><code>vagent metrics show -o &lt;run&gt; [--baseline &lt;run&gt;]</code><br>
    <code>vagent metrics trend -o &lt;run&gt; --last 10</code></td>
    <td>（只读 CLI；数字进签核报告）</td></tr>
<tr><td>增量 / 对比</td><td><code>vagent incremental plan --baseline &lt;a&gt; --current &lt;b&gt;</code><br>
    <code>vagent diff runs --baseline &lt;a&gt; --current &lt;b&gt;</code></td>
    <td>运行对比</td></tr>
<tr><td>证据包校验 / 回放</td><td><code>vagent evidence verify &lt;run&gt;/signoff_evidence</code><br>
    <code>vagent evidence replay &lt;run&gt;/signoff_evidence</code></td>
    <td>签核判定 →「证据包 v2」→「校验证据包」</td></tr>
<tr><td>SoC 回归</td><td><code>vagent soc run examples/open_npu_soc</code></td>
    <td>SoC 总览 / 验证工作区 →「运行 SoC 回归」</td></tr>
<tr><td>SoC C 用例</td><td><code>vagent soc c-run examples/open_npu_soc --case C-GEMM-8X8</code></td>
    <td>SoC C 用例 →「运行选中用例」</td></tr>
<tr><td>IP 回归</td><td><code>vagent ip run examples/open_npu_soc --ip IP-NPU-GEMM</code></td>
    <td>IP 工作区 →「运行 IP 回归」</td></tr>
<tr><td>IP 发布包</td><td><code>vagent ip release-build &lt;project&gt; --ip IP-NPU-GEMM</code></td>
    <td>IP 工作区 →「生成发布包」（会先弹确认）</td></tr>
<tr><td>SoC 签核视角的 IP 绑定</td><td><code>vagent ip binding &lt;project&gt;</code></td>
    <td>SoC 签核 →「IP 发布包绑定」一行</td></tr>
</table>
<p>长任务（回归 / 编译 / 仿真）在后台线程跑，控制台底部有进度行；
刻意不提供「取消」—— 跑起来的仿真停不掉，给个点不动的按钮更糟。</p>

<h3>四、输出在哪</h3>
<p>每次运行 = 一个 run 目录（默认 <code>output_&lt;名字&gt;_&lt;时间戳&gt;</code>）：</p>
<pre>
&lt;run&gt;/
├─ docs/manifest.json              运行清单（阶段、覆盖率、证据哈希）
├─ docs/run_events.jsonl           运行日志（追加写，坏行跳过）
├─ docs/evidence_chain.json        六层领域证据链
├─ docs/verification_quality.json  五维质量门（functional/coverage/model/structural/evidence）
├─ docs/engineering_metrics.json   回归耗时 / 增量节省 / 归因 / 决策有效率
├─ docs/ir_shadow_diff.json        UVM IR 双写比对（IR 派生视图 vs 渲染 ctx）
├─ rtl/ model/ sim/ sv/            各类产物（UVM 资产只在 sv/）
├─ contract/                      契约构建物（contract.yaml / obligations / manifest）
├─ coverage/                      TP IR / Case IR（四集合）/ 矩阵 / 证据 / 视图 / 门禁
├─ evidence/ledger.jsonl          事实账本（只追加 + 哈希链）
├─ status/                        worklist / shadow / tp_shadow / seed_index
├─ regression_run/report.json     回归报告（含每条用例状态）
├─ signoff_evidence/manifest.json 证据包 v2（逐文件哈希 + package_hash + replay）
└─ soc/ ip/ c_run.json            SoC / IP / C 用例摘要; ip_evidence/&lt;ip&gt;.json
</pre>
<p><code>coverage/case_view.{json,md,html}</code> 是**能离线评审**的签核材料：
视图1 按逻辑 CASE 聚合（批次按测试名，执行次数单列）、视图2 功能契约、
视图3 路径矩阵、视图4 缺口（每个非绿 CELL 一条），再叠加
覆盖率组总览 / 四集合（Groups / SVA / SCB / Constraints）/ Case×CELL / EVD。</p>
<p>IP 发布包写入工程里的 <code>spec/ip_releases/&lt;ip&gt;.json</code>，
带 <code>rtl_hash</code> / 准则结果 / <code>sha256</code>，进版本库。
跨 run 的 CASE 索引在主库 <code>case_registry</code>（可重建，见
<code>case-registry</code> 命令）。</p>

<h3>五、怎么看</h3>
<ol>
  <li><b>先选运行</b>：左窗格「运行历史」选中一次 run，其余视图（签核、证据、
      覆盖率、回归状态、波形）会一起切过去。</li>
  <li><b>回归是否真过</b>：看 <code>regression_run/report.json</code> 或
      「回归状态」页 —— 判据锚定 <code>[SCB_DUT] ... mismatched=0</code> 或
      <code>Scoreboard: ... mismatched=0</code>，没有 <code>UVM_ERROR</code>；
      C 路径是 <code>TEST_PASS</code>。逐条 scoreboard 另有
      <code>[SCB &lt;id&gt;]</code> 行，<b>它不能单独满足判据</b>（防止"某条干净、
      聚合脏"被误判）。日志里还应有 <code>[DRV]</code>（发送）、
      <code>[MON]</code>（采样）、<code>[SCB] MATCH / MISMATCH / SUMMARY</code>
      —— 逐笔事务与比对结论都能直接看到。</li>
  <li><b>证据是否完整</b>：「签核判定」→「证据包 v2」→「校验证据包」，
      逐文件哈希 + <code>package_hash</code>；缺失或对不上就是 ✗，不算 pass。
      复用旧包文件前会校验<b>本体哈希</b>，不符强制重拷。</li>
  <li><b>签核怎么判</b>：「签核判定」五个标签页 —— 签核门禁 / 领域证据链 /
      Case 证据 / 证据包 v2 / OS 账本。三态：READY / PASS_WITH_CAVEAT /
      NEEDS_FIX；缺证据不下绿，NA ≠ pass。</li>
  <li><b>某条义务为什么红</b>：<code>vagent contract why &lt;OBL-ID&gt; -o &lt;run&gt;</code>
      给出谓词 → 事实 → 状态 → "该跑哪条 test×seed"；账本与两级对账看
      <code>vagent contract status</code>。「OS 账本」页同源。</li>
  <li><b>Case 证据</b>：「功能覆盖」→「Case 证据」四个子页 + 四集合明细。
      Constraints 段标 <code>backed</code>：<b>否（空骨架）</b>表示约束没真正
      编译进模型，不能算"受该约束驱动"；未登记表示没有注册表数据，不冒充否。</li>
  <li><b>覆盖率与质量门</b>：「覆盖率产出 / 回归覆盖率 / 功能覆盖」；
      质量门默认只报告，<code>SIGNOFFAI_QUALITY_GATE=block</code> 时
      <code>evidence</code>/<code>functional</code> 维 fail → 硬失败
      （<code>QUALITY_GATE_BLOCKED</code>），其余非 pass → 软 caveat。</li>
  <li><b>效率有没有提升</b>：<code>vagent metrics trend</code> 看连续 N 个 run
      的回归耗时 / 增量 / 归因 / 决策，以及 <code>conservative_rate</code>
      （有增量计划却保守跑全量的比例）—— 单看"预计节省"会偏乐观。</li>
  <li><b>波形</b>：「打开波形」—— 回归 run 用用例目录里的 <code>qwave.db</code>，
      C 用例在 <code>&lt;run&gt;/e203/waves/</code>；DUT 需要 <code>+acc</code> 才进波形库。</li>
  <li><b>IP 状态</b>：IP 工作区顶部看 <code>source_kind</code> ——
      <code>ip_run</code> 表示用该 IP 自己的回归，<code>soc_run</code> 表示回退到
      SoC run；两种来源不会互相冒充。</li>
</ol>

<h3>六、默认开关与回退</h3>
<table border="1" cellspacing="0" cellpadding="6">
<tr><th>能力</th><th>默认</th><th>回退</th></tr>
<tr><td>义务 worklist（只重跑未清偿义务对应的 test）</td>
    <td><b>开</b>（账本里已有历史证据时生效；全新 run 回落全量）</td>
    <td><code>SIGNOFFAI_WORKLIST=0</code> 或 <code>params.worklist=False</code></td></tr>
<tr><td>契约前置门禁（没有/损坏的契约拒绝开跑）</td><td><b>开</b></td>
    <td><code>SIGNOFFAI_CONTRACT_GATE=off</code> 或 <code>params.contract_gate=False</code></td></tr>
<tr><td>五维质量门</td><td><code>report</code>（只报告）</td>
    <td><code>SIGNOFFAI_QUALITY_GATE=warn|block</code></td></tr>
<tr><td>UVM IR 双写比对</td><td><b>开</b>（只写 <code>docs/ir_shadow_diff.json</code>）</td>
    <td><code>SIGNOFFAI_UVM_IR_SHADOW=off</code></td></tr>
<tr><td>命令白名单</td><td>EDA enforce；其他 monitor</td>
    <td><code>SIGNOFFAI_CMD_ALLOWLIST=enforce</code>；EDA 退回 monitor 用
        <code>SIGNOFFAI_CMD_ALLOWLIST_EDA=monitor</code></td></tr>
<tr><td>State 契约越权写</td><td>关键字段硬失败，其余告警</td>
    <td><code>SIGNOFFAI_STATE_CONTRACT=warn</code></td></tr>
</table>

<h3>七、边界（没做到的不装懂）</h3>
<ul>
  <li>没 EDA 时相关阶段会标 <code>BLOCKED_EDA_MISSING</code>，不算通过；</li>
  <li><code>None ≠ False</code>：判不了就显示"未知/未测量"，不拿空值冒充 pass；</li>
  <li>UVM IR 仍是影子模式（只做双写比对与结构校验），模板仍吃 dataclass ctx；
      <code>ir_shadow_diff</code> 差异清零是切 IR-first 的前置条件，不是签核条件；</li>
  <li><code>player</code> 激励后端只有计划、没有 runtime；增量<b>编译</b>尚未实现
      （只决定跑哪些用例）；回归按 seed 级重排未实现；</li>
  <li>IP 级覆盖率尚未测量（独立 IP TB 待 M2），发布包里如实写
      <code>measured: false</code>；</li>
  <li>SoC 证据包是工程级事实，不是 UVM 的 TP 矩阵 + caveat 三态签核。</li>
</ul>
</body></html>
"""


class UserGuideDialog(QDialog):
    """帮助 → 使用指南：一页纸讲清"输入 → 怎么跑 → 输出 → 怎么看"。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(GUIDE_TITLE)
        self.resize(1040, 820)
        layout = QVBoxLayout(self)
        self.view = QTextBrowser(self)
        self.view.setOpenExternalLinks(False)
        self.view.setHtml(GUIDE_HTML)
        layout.addWidget(self.view, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
