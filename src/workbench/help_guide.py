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
  <li><code>specs/&lt;module&gt;/casemodel.yaml</code>（人工 case 模型，优先于草稿）；</li>
  <li><code>specs/&lt;module&gt;/signoff_policy.yaml</code>（签核策略，可选）；</li>
  <li>EDA：QuestaSim（<code>vlog / vopt / vsim / vcover</code>）。</li>
</ul>
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
<tr><td>UVM 全流程</td><td><code>vagent verify --spec spec.md --rtl ./rtl --config casemodel.yaml</code></td>
    <td>工程服务 → UVM 自动化验证</td></tr>
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
├─ docs/manifest.json          运行清单（阶段、覆盖率、证据哈希）
├─ docs/run_events.jsonl       运行日志（追加写，坏行跳过）
├─ docs/evidence_chain.json    六层领域证据链
├─ rtl/ model/ agents/ env/ bench/ sim/ coverage/   各类产物
├─ regression_run/report.json  回归报告（含每条用例状态）
├─ signoff_evidence/manifest.json  证据包 v1（逐文件哈希 + package_hash）
├─ soc/soc_run.json            SoC run 摘要（含 consumed_ips 绑定）
├─ ip/ip_run.json              IP run 摘要（IP 级回归才有）
├─ c_run.json                  SoC C 用例 run（只有 C 路径有）
└─ ip_evidence/&lt;ip&gt;.json       IP 证据（引用来源 run）
</pre>
<p>IP 发布包写入工程里的 <code>spec/ip_releases/&lt;ip&gt;.json</code>，
带 <code>rtl_hash</code> / 准则结果 / <code>sha256</code>，进版本库。</p>

<h3>五、怎么看</h3>
<ol>
  <li><b>先选运行</b>：左窗格「运行历史」选中一次 run，其余视图（签核、证据、
      覆盖率、回归状态、波形）会一起切过去。</li>
  <li><b>回归是否真过</b>：看 <code>regression_run/report.json</code> 或
      「回归状态」页 —— 判据是日志里有 <code>mismatched=0</code>、没有
      <code>UVM_ERROR</code>，C 路径是 <code>TEST_PASS</code>；回归 exit code
      仍是唯一 PASS/FAIL 判据。</li>
  <li><b>证据是否完整</b>：「签核判定」/「证据」页 →「校验证据包」，
      逐文件哈希 + <code>package_hash</code>；缺失或对不上就是 ✗，不算 pass。</li>
  <li><b>覆盖率</b>：「覆盖率产出 / 回归覆盖率 / 功能覆盖」；
      UVM 三态签核看「签核判定」（PASS / PASS_WITH_CAVEAT / FAIL）。</li>
  <li><b>波形</b>：「打开波形」—— 回归 run 用用例目录里的 <code>qwave.db</code>，
      C 用例在 <code>&lt;run&gt;/e203/waves/</code>；DUT 需要 <code>+acc</code> 才进波形库。</li>
  <li><b>IP 状态</b>：IP 工作区顶部看 <code>source_kind</code> ——
      <code>ip_run</code> 表示用该 IP 自己的回归，<code>soc_run</code> 表示回退到
      SoC run；两种来源不会互相冒充。</li>
</ol>

<h3>六、边界（没做到的不装懂）</h3>
<ul>
  <li>没 EDA 时相关阶段会标 <code>BLOCKED_EDA_MISSING</code>，不算通过；</li>
  <li><code>None ≠ False</code>：判不了就显示"未知/未测量"，不拿空值冒充 pass；</li>
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
        self.resize(980, 780)
        layout = QVBoxLayout(self)
        self.view = QTextBrowser(self)
        self.view.setOpenExternalLinks(False)
        self.view.setHtml(GUIDE_HTML)
        layout.addWidget(self.view, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
