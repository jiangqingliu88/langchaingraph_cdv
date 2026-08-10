# 禁止 dvsim 约束下的重构可行性分析

> **约束：禁止使用 dvsim 工具。**
>
> **前提：** dvsim（lowRISC/OpenTitan 的仿真调度器）当前以 vendored git 仓库形式存在于 `src/tools/dvsim/`，另有配置目录 `src/tools/dvsim_cfg/` 和适配器 `src/tools/dvsim_adapter/`。
>
> **核心问题：砍掉 dvsim 之后，回归管理、仿真调度、覆盖率合并这些能力用什么替代？重构要改多少代码？风险多高？**
>
> 日期：2026-08-10

---

## 一、当前状态：dvsim 到底用在哪

### 1.1 代码级引用（唯一真正的依赖）

```
src/tools/dvsim_adapter/test_dvsim_api.py:11
    from dvsim.flow.factory import make_cfg
```

**全仓库只有这一行代码真正 import 了 dvsim。** 它是 Phase 1.4 的验证脚本——验证"SignOffAI 能否调用 dvsim Python API"。除此之外，**没有任何 Agent、core 模块、CLI 命令 import dvsim。**

### 1.2 实际使用的回归框架

`src/agents/regression_manager/main.py` 的回归执行**根本不走 dvsim**，而是用了一套独立的回归框架：

```python
from src.tools.regression_tools.regression_framwork.src.regression_framework.adapters.regression_runner import RegressionRunner
from src.tools.regression_tools.regression_framwork.src.regression_framework.reporters.json import JsonReporter
from src.tools.regression_tools.regression_framwork.src.regression_framework.reporters.html import HtmlReporter
```

实际的仿真工具调用链是：
```
RegressionRunner → 直接调 VCS/QuestaSim → 收集结果 → JsonReporter/HtmlReporter
```

**dvsim 从未真正进入过回归执行流程。** 它只是被"计划集成"但从未被"实际集成"。

### 1.3 dvsim 在仓库中的存在形式

| 路径 | 内容 | 大小 |
|------|------|------|
| `src/tools/dvsim/` | vendored git 仓库（完整的 dvsim 源码） | ~20,000 行 |
| `src/tools/dvsim_cfg/` | 仿真配置文件（.hjson/.tcl/.mk） | ~50 个文件 |
| `src/tools/dvsim_adapter/` | 1 个测试脚本 `test_dvsim_api.py` | 115 行 |

**注意：** dvsim 不是 git submodule（没有 `.gitmodules`）。它是被手动拷贝进仓库的 vendored 快照。这意味着删除它就是删除一个目录——不会触发 submodule 同步问题。

### 1.4 文档中的 dvsim 引用

以下文档提到了 dvsim，但它们是**规划文档，不是可执行代码**，删除 dvsim 后可以更新：
- `docs/dvsim_integration_analysis.md`（dvsim 集成分析）
- `docs/llm_vs_traditional_tools_analysis.md`（我刚写的，建议 regression_manager 应调用 dvsim API——这个建议已作废）
- `docs/prototype_vs_current_architecture.md`
- `PROJECT_ANALYSIS.md`

---

## 二、移除 dvsim 的影响面：实际 vs 预期

### 2.1 实际影响（代码层）

| 组件 | 是否受影响 | 影响程度 |
|------|-----------|---------|
| `src/agents/regression_manager/` | ❌ 不受影响 | 不使用 dvsim |
| `src/agents/` 其他 11 个 | ❌ 不受影响 | 无 dvsim 引用 |
| `src/core/` 全部模块 | ❌ 不受影响 | 无 dvsim 引用 |
| `src/cli/commands.py` | ❌ 不受影响 | 无 dvsim 引用 |
| `src/tools/dvsim_adapter/test_dvsim_api.py` | ✅ 唯一受影响 | 需删除或改写 |
| `src/tools/dvsim_cfg/` | ⚠️ 受影响 | 配置文件引用 dvsim 路径，需清理 |
| `src/tools/dvsim/` | ✅ 直接删除 | vendored 仓库 |

**结论：代码层的影响面极窄。** 砍掉 dvsim 只需要做 3 件事：
1. 删除 `src/tools/dvsim/`
2. 删除 `src/tools/dvsim_adapter/`
3. 清理 `src/tools/dvsim_cfg/` 中指向 dvsim 的路径引用

### 2.2 预期影响（能力层）

dvsim 原本**计划提供但从未实际启用**的能力：

| dvsim 能力 | 当前替代方案 | 替代是否充分 |
|-----------|-------------|-------------|
| 仿真任务调度（LSF/SGE/本地） | `RegressionRunner` 直接调仿真器 | ⚠️ 当前只支持本地，无集群调度 |
| 多仿真器支持（VCS/Questa/Verilator/Xcelium） | `RegressionRunner` + 手动配置 | ⚠️ 需验证多仿真器支持 |
| HJSON 配置驱动 | `RegressionRunner` + Python dict 配置 | ✅ Python dict 更灵活 |
| 覆盖率合并（URG/IMC） | `RegressionRunner` + `vcover merge` | ✅ 功能等价 |
| 测试计划追踪 | `src/core/design_mapper.py`（需求→测试点映射） | ✅ 更完整 |
| 结果 HTML 报告 | `HtmlReporter` | ✅ 功能等价 |
| CI 集成（JUnit XML） | `vagent ci verify --junit`（P3 task） | ✅ 计划中 |

**结论：dvsim 的 7 项核心能力中，6 项已有替代方案，1 项（集群调度）是能力缺口但非当前刚需。**

---

## 三、为什么用户要禁止 dvsim

常见的禁止 dvsim 的原因（推测+分析）：

| 原因 | 合理性分析 |
|------|-----------|
| **License 问题** | dvsim 是 Apache 2.0 许可（OpenTitan 项目），对商用友好。但如果担心 lowRISC/OpenTitan 的专利/版权牵连，移除是合理的 |
| **依赖复杂度** | dvsim 有自己完整的构建系统（Bazel/FuseSoC/uv/pyproject），引入后增加维护负担。这个理由成立 |
| **代码膨胀** | dvsim ~20,000 行，而 SignOffAI 实际只用其中极少部分。杀掉 99% 的 dead code 是合理的 |
| **架构自主性** | 不希望核心回归流程依赖外部项目。这个理由成立——SignOffAI 应该有自己可控的回归调度器 |
| **已被替代** | `RegressionRunner` 已经能干活，dvsim 从未真正用上。移除一个从未起作用的依赖是纯粹减负 |
| **学习成本** | dvsim 的 HJSON 配置语法和使用范式需要额外学习，增加新用户上手难度 |

---

## 四、重构方案

### 4.1 总体策略

```
Phase A: 直接删除（0 风险，立即可做）
    ├── 删除 src/tools/dvsim/ (vendored git 仓库)
    ├── 删除 src/tools/dvsim_adapter/ (唯一 import 者)
    └── 删除 src/tools/dvsim_cfg/ 中 dvsim 路径引用

Phase B: 评估和加固现有替代方案（低风险，1-2 天）
    ├── 审查 RegressionRunner 的完整性和正确性
    ├── 补全多仿真器支持（如果缺失）
    └── 确保覆盖率合并流程完整

Phase C: 清理文档和残余引用（低风险，半天）
    ├── 更新 docs/ 中提及 dvsim 的规划文档
    ├── 更新 PROJECT_ANALYSIS.md
    └── 确认 .gitignore 无遗漏
```

### 4.2 Phase A：直接删除（立即执行，零风险）

**步骤 1：删除 dvsim vendored 仓库**
```bash
# dvsim 不是 git submodule，直接删除
rm -rf src/tools/dvsim/
# 确认无 .gitmodules，如果有残留手动清理
```

**步骤 2：删除 dvsim 适配器**
```bash
rm -rf src/tools/dvsim_adapter/
```

**步骤 3：检查 dvsim_cfg 的保留价值**

`src/tools/dvsim_cfg/` 里的文件分两类：

| 文件类别 | 是否依赖 dvsim | 处理方式 |
|---------|---------------|---------|
| `common/dvsim/*.hjson` | ✅ 直接依赖（文件名就是 dvsim） | **删除** |
| `common/sim.mk` 中的 `{proj_root}/hw/dv/tools/dvsim/...` 路径 | ✅ 引用 dvsim 路径 | **删除 dvsim 路径行** |
| `common/vcs/*.cfg`、`common/questa/sim.tcl` 等仿真器配置 | ❌ 不依赖 dvsim，是通用仿真配置 | **保留**，移到 `src/tools/lib/sim_configs/` |
| `adc_ctrl_example/` | ⚠️ 引用了 dvsim 的测试计划格式 | **保留**作为回归配置示例，去除 dvsim 引用 |

**步骤 4：检查 regression_manager 的独立运行能力**
```bash
# 确认 RegressionRunner 不依赖 dvsim（已验证无 import）
grep -r "dvsim" src/tools/regression_tools/  # 应无输出
grep -r "dvsim" src/agents/regression_manager/  # 应无输出
```

### 4.3 Phase B：加固替代方案

#### 4.3.1 审查 RegressionRunner 的完整性

`src/tools/regression_tools/regression_framwork/` 当前结构需要确认：

```
src/tools/regression_tools/regression_framwork/
├── src/regression_framework/
│   ├── adapters/
│   │   └── regression_runner.py    ← 核心调度器
│   ├── reporters/
│   │   ├── json.py                 ← JSON 报告
│   │   └── html.py                 ← HTML 报告
│   └── ...
```

**需要验证的点：**

| 检查项 | 方法 | 若缺失 |
|--------|------|--------|
| 支持哪些仿真器？ | 读 RegressionRunner 源码 | 补 VCS/Questa/Verilator adapter |
| 支持并行执行吗？ | 读调度逻辑 | 按需加 `concurrent.futures` |
| 支持超时 kill 吗？ | 读子进程管理 | 加 `subprocess timeout` |
| 支持 seed 管理吗？ | 读参数传递 | 加 `--seed` 参数 |
| 覆盖率合并工作吗？ | 实际跑一次 | 修复 UCDB merge 命令 |
| 失败重试机制？ | 读重试逻辑 | 加 `--retry-failed` |

**注意：** 这是**加固现有代码**，不是从零开发——RegressionRunner 已经在 regression_manager 里跑通了。

#### 4.3.2 补全多仿真器支持（如果需要）

dvsim 的一个关键特性是支持 7 种仿真器（VCS/Questa/Verilator/Xcelium/Riviera/DSim/Z01X）。如果 `RegressionRunner` 当前只支持一个仿真器，需要补上多仿真器抽象：

```python
# 替代 dvsim 多仿真器支持的轻量方案（~80 行）
from dataclasses import dataclass
from typing import List

@dataclass
class SimulatorConfig:
    name: str                       # "vcs" | "questa" | "verilator"
    compile_cmd: List[str]          # ["vcs", "-full64", ...]
    run_cmd: List[str]              # ["./simv", "+UVM_TESTNAME=...", ...]
    coverage_merge_cmd: List[str]   # ["vcover", "merge", ...]
    coverage_report_cmd: List[str]  # ["vcover", "report", ...]

# 预置配置
SIMULATORS = {
    "vcs": SimulatorConfig(
        name="vcs",
        compile_cmd=["vcs", "-full64", "-sverilog", "+v2k"],
        run_cmd=["./simv"],
        coverage_merge_cmd=["vcover", "merge"],
        coverage_report_cmd=["vcover", "report"],
    ),
    "questa": SimulatorConfig(
        name="questa",
        compile_cmd=["vlog", "+acc", "-sv"],
        run_cmd=["vsim", "-c", "-do", "run -all"],
        coverage_merge_cmd=["vcover", "merge"],
        coverage_report_cmd=["vcover", "report"],
    ),
    # ... 按需添加
}

class RegressionRunner:
    def __init__(self, simulator: str = "vcs"):
        self.sim_config = SIMULATORS[simulator]
```

**这是 dvsim 的 `common_sim_cfg.hjson` 的 Python 化翻译。** 不引入新依赖，代码量 ~100 行。

#### 4.3.3 确保覆盖率合并流程完整

当前 coverage_manager 使用的覆盖率工具链需要确认：

```bash
# 当前 RegressionRunner 使用的覆盖率命令（从 main.py 推断）
vcover merge -output merged.ucdb *.ucdb
vcover report -html merged.ucdb
```

这跟 dvsim 能做的事完全等价——因为 dvsim 底层也是调 `vcover`/`urg`。

### 4.4 Phase C：清理文档

| 文档 | 处理方式 |
|------|---------|
| `docs/dvsim_integration_analysis.md` | 归档到 `docs/archive/` 或删除 |
| `docs/llm_vs_traditional_tools_analysis.md` | 修改"regression_manager 应调用 dvsim"那一段 |
| `docs/prototype_vs_current_architecture.md` | 无需修改（未涉及 dvsim） |
| `docs/project_structure_opentitan_style.md` | 如引用 dvsim/OpenTitan，归档 |
| `PROJECT_ANALYSIS.md` | 删除"dvsim 集成"相关描述 |
| `CLAUDE.md` | 无需修改（未涉及 dvsim） |

---

## 五、风险评估

### 5.1 技术风险

| 风险 | 等级 | 缓解措施 |
|------|:---:|---------|
| RegressionRunner 有隐藏的 dvsim 依赖 | 🟢 极低 | 已 grep 验证，无 import |
| 多仿真器支持不全 | 🟡 低 | 当前只支持 VCS/Questa，够用。如需扩展，Phase B 补 |
| 覆盖率合并命令不兼容 | 🟢 极低 | `vcover merge` 是行业标准，与 dvsim 底层相同 |
| 删除后 CI 挂了 | 🟢 极低 | dvsim 从未在 CI 中使用 |
| 集群调度（LSF/SGE）缺失 | 🟡 低 | 个人级工具不需要集群调度。如未来需要，加 `--job-scheduler` 参数即可 |

### 5.2 项目风险

| 风险 | 等级 | 缓解措施 |
|------|:---:|---------|
| 删了之后又想要回来 | 🟢 极低 | git history 保留一切，`git revert` 一秒恢复 |
| 团队其他成员依赖 dvsim | 🟢 极低 | dvsim 不是 pip 依赖，不在 pyproject.toml 里，不在 .gitmodules 里 |
| 未来要集成 OpenTitan 项目 | 🟡 中 | OpenTitan 重度使用 dvsim。但如果将来需要，可以作为可选插件重新引入，而非核心依赖 |

### 5.3 总体风险评级：🟢 低风险

**原因：** dvsim 从未被实际集成到任何 Agent 或核心模块中。删除它等于删除一个 big dead code block。

---

## 六、重构后的目标架构

### 6.1 回归管理的新架构

```
vagent regression run
        │
        ▼
regression_manager (LLM 分析失败 + 建议)
        │
        ▼
RegressionRunner (纯 Python，无外部调度器依赖)
    ├── SimulatorConfig (多仿真器抽象，Python dataclass)
    ├── 并行/串行调度 (concurrent.futures)
    ├── 超时管理 (subprocess timeout)
    ├── 覆盖率合并 (vcover/urg 命令行包装)
    └── 结果报告 (JSON + HTML + JUnit XML)
```

### 6.2 删除 dvsim 后的目录结构变化

```
删除前                              删除后
───────                             ───────
src/tools/                          src/tools/
├── dvsim/              ❌ 删除     │
├── dvsim_cfg/          ⚠️ 精简    ├── sim_configs/    ← 从 dvsim_cfg 保留的仿真器配置
│   ├── common/vcs/                 │   ├── vcs/
│   ├── common/questa/              │   └── questa/
│   └── common/dvsim/   ❌ 删除     │
├── dvsim_adapter/      ❌ 删除     │
├── regression_tools/   ✅ 保留     ├── regression_tools/
├── cmodel_tools/       ✅ 保留     ├── cmodel_tools/
├── uvm_tools/          ✅ 保留     └── uvm_tools/
└── ...
```

**净效果：删除 ~20,000 行代码，精简 3 个目录，agent/core/cli 代码零修改。**

---

## 七、可行性与收益

### 7.1 可行性：✅ 完全可行

- **代码层：** 1 个文件受影响（`test_dvsim_api.py`），0 个 Agent 受影响，0 个核心模块受影响
- **配置层：** `dvsim_cfg` 中 ~50% 文件可删除（dvsim 专有），~50% 可保留移动到新位置
- **时间估算：** Phase A（删除）30 分钟，Phase B（加固）1-2 天，Phase C（文档）半天。**总计 2-3 天。**

### 7.2 收益

| 收益 | 量化 |
|------|------|
| **代码量减少** | ~20,000 行（dvsim vendored 仓库） + ~50 配置文件 |
| **外部依赖减少** | 消除 1 个 vendored 第三方仓库 |
| **构建复杂度降低** | 不再需要理解 dvsim 的 Bazel/FuseSoC/uv 构建链 |
| **学习成本降低** | 新贡献者不需要学习 dvsim 的 HJSON 配置范式 |
| **架构自主性提升** | 回归调度完全自控，不跟随 OpenTitan 的版本演进 |
| **合规风险消除** | 不再包含来自 lowRISC/OpenTitan 的代码 |

### 7.3 代价

| 代价 | 程度 |
|------|------|
| 集群调度支持（LSF/SGE） | 需要时自建，~200 行。当前不需要 |
| 多仿真器支持 | 当前 RegressionRunner 已覆盖，如需扩展 ~100 行 |
| 失去 dvsim 社区的 bug 修复 | dvsim 的 bug 修复本来也没流到 SignOffAI（vendored 快照不会自动更新） |

---

## 八、执行检查清单

```
Phase A（30 分钟，零风险立即执行）
□ [ ] 删除 src/tools/dvsim/
□ [ ] 删除 src/tools/dvsim_adapter/
□ [ ] 确认 git status 中无 submodule 残留
□ [ ] git commit -m "Remove dvsim vendored dependency"

Phase B（1-2 天，验证替代方案）
□ [ ] 审查 RegressionRunner 源码完整性
□ [ ] 验证 regression_manager 独立运行（不含 dvsim）
□ [ ] 精简 dvsim_cfg → sim_configs（保留仿真器配置，删除 dvsim 引用）
□ [ ] （可选）补多仿真器 SimulatorConfig 抽象
□ [ ] 跑一次完整回归验证：regression → coverage → report

Phase C（半天，清理文档）
□ [ ] 更新 docs/ 中的 dvsim 引用
□ [ ] 将 dvsim_integration_analysis.md 移到 docs/archive/
□ [ ] 更新 PROJECT_ANALYSIS.md
□ [ ] git commit -m "Update docs after dvsim removal"
```

---

## 九、结论

**在"禁止 dvsim"约束下，SignOffAI 可以完全移除 dvsim，代价极低：**

1. **代码层面：0 个 Agent 受影响，0 个核心模块受影响。** 唯一受影响的是一个从未被调用的测试脚本。
2. **能力层面：无功能降级。** 回归执行（RegressionRunner）、覆盖率合并（vcover）、报告生成（HtmlReporter）都有成熟的替代方案，且已经在使用中。
3. **时间层面：2-3 天完成全部清理 + 验证 + 文档更新。**
4. **风险层面：极低。** dvsim 是一个 vendored dead code block，删除它不会破坏任何正在工作的功能。

**一句话：dvsim 在 SignOffAI 里从未真正"活过"——它一直是一个计划中但未实现的集成。砍掉一个从未活过的依赖，不是重构，是清理。**
