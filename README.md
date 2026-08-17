# SignOffAI — IC 验证垂直领域智能体（纯 Python CLI）

**规格 → RTL → UVM → 回归 → 覆盖率 → 签核** 的 AI 验证闭环工具。个人级 CLI，**无 Web 前端**（`python -m src.cli.commands` 交付全部功能）。

> 架构说明：7 个领域 Agent（design/model/verify/ops/coverage/debug/audit）编排在五层引擎（L1 基础设施 → L2 编排 → L3 决策 → L4 记忆 → L5 进化）之上。详见 `docs/design/refactor_to_deepseek_harness.md` 与 `docs/design/harness_feature_design.md`。

## 三条铁律（不可放松）

| 铁律 | 含义 | 代码落点 |
|------|------|---------|
| **EDA 是唯一真理** | LLM 生成的代码必须经 `vlog` 编译返回 0/1，不通过即丢弃/回退；**失败必须响亮**，禁止静默降级为假通过 | `design` 的 `_verify_ip_rtl`、`verify` 的 `_verify_compilation` |
| **覆盖率库版本固化** | 每轮 ucdb 算 SHA256 归档，复现时回滚比对 | `InfrastructureManager.archive_coverage` |
| **LLM 只读降采样文本** | 空洞分析只读 <1KB 语义汇总，绝不读几十 GB 的 ucdb | `coverage` agent |

## 快速开始

```powershell
# 依赖（venv 已修复；若换机需重装）
.\venv\Scripts\activate
pip install -r requirements.txt          # 含 jsonschema

# 配置（可选；不配则走确定性/模板路径，LLM 环节如实失败）
# .env: LLM_PROVIDER=deepseek / LLM_API_KEY=... / LLM_MODEL=deepseek-chat

# 一键闭环
python -m src.cli.commands verify specs\apb_uart\apb_uart_spec.md --json
```

**行为约定（失败响亮）**：

- 无 EDA 工具（vlog/vsim 不在 PATH）→ `status: BLOCKED_EDA_MISSING`，给出安装指引，**不进入假通过路径**
- debug agent：无仿真/编译日志 → `NO_EVIDENCE`（score 0）；无 EDA → `EDA_MISSING`；**"没有日志"绝不等于"没有错误"**
- audit agent：四道门禁（RTL 存在 / 回归全过 / 覆盖率真实 / 参考模型非占位）任一不满足 → `NEEDS_FIX` 且阶段 FAIL
- model agent：模板参考模型标记 `placeholder: True`，audit 拒绝签核（真实参考模型见下文路线）

## 7 个领域 Agent

| Agent | 职责 | 产出 |
|-------|------|------|
| design | spec 分析 → IP 拆解 → RTL 生成（LLM 写小 IP + vlog 门禁）→ 顶层集成 | `rtl/*.sv` + design_arch |
| model | 多语言参考模型（模板占位 → 真实模型路线见 TODO） | `model/`（版本管理 + 回滚） |
| verify | UVM 环境（Jinja2 模板）+ 测试用例 YAML + SVA 断言 + gap 定向激励 | `env/ agents/ assertions/` |
| ops | 编译 + 仿真 + 回归（RegressionRunner / 回归框架） | regression.json |
| coverage | 覆盖率收集（vsim -coverage → ucdb）+ gap 归因（unreachable/constraint/unstimulated） | coverage.json + gaps |
| debug | 日志收集 → 分类 → 指纹去重 → 模板修复 → LLM 兜底重写 → EDA 重验 | debug report |
| audit | 签核判定（四道门禁）+ 签核报告 | report.json + 证据链 |

## 闭环流程（coverage-driven）

```
design → model → verify → [ops → coverage → decide]×N → audit
                              ↑          ↓
                              └── debug 修复 / 决策动作 ──┘
```

决策动作：`COMPILE_RETRY` / `REFACTOR_RTL` / `UPDATE_MODEL` / `GENERATE_DIRECTED_TEST` / `RELAX_CONSTRAINT` / `EXPAND_SEEDS` / `CONVERGE`。

EDA 缺失时在首个 `ops` 轮终止（`BLOCKED_EDA_MISSING`），不空转。

## 主要命令

```powershell
python -m src.cli.commands verify <spec.md> [--target 80] [--max-rounds 5] [--json]
python -m src.cli.commands agent list
python -m src.cli.commands dump <run_id>        # 复现/导出证据包
python -m src.cli.commands env generate ...     # UVM 环境
python -m src.cli.commands coverage report ...  # 覆盖率报告
python -m src.cli.commands signoff ...          # 签核
```

## 目录结构（实际）

```
src/
├── agents/            # 7 个领域 Agent（design/model/verify/ops/coverage/debug/audit）
├── layers/
│   ├── l1_infrastructure/   # EDA 后端/编译自愈/覆盖后端/黄金基线/基础设施
│   ├── l2_orchestration/    # Agent 注册/执行引擎/上下文/通信/证据链/治理/中间件
│   ├── l3_decision/         # 覆盖率驱动决策引擎 + 知识图
│   ├── l4_memory/           # IP 库/用例状态库/exclude 库/调试经验
│   └── l5_evolution/        # 经验蒸馏
├── tools/             # 领域工具（spec/uvm/coverage/debug/testcase/assertion/cmodel）
├── cli/               # vagent CLI（commands.py / output.py / repl.py）
└── regression_framework/    # 回归执行框架
specs/                 # 规格库（apb_uart 等）
tests/                 # pytest 套件（84 passed）
```

## 已知问题与路线

- [ ] **真实参考模型（golden 库）**：当前 model 产出为模板占位（audit 已拒绝签核）。路线：从 `spec.registers` 确定性生成 APB 寄存器参考模型（`find_spec_yaml._gen_apb_register_model` 已有雏形），协议逻辑（UART TX/RX）经 LLM + vlog 门禁 + 定向仿真验证后入库
- [ ] MCP 工具层断链已绕过（ops/coverage 直接调 L1），`tool_worker.py` 引用的 `regression_tool` 模块待重建或删除
- [ ] `env_arch_check` 无 EDA 时报 `[WinError 2]`（应为 EDA_MISSING 语义）

## 测试

```powershell
python -m pytest tests/ -q      # 84 passed, 1 skipped
```

## 环境要求

Python 3.10-3.12 · langchain 0.1.20 · QuestaSim（可选，编译仿真+覆盖率；缺失时失败响亮）· DeepSeek API key（可选）
