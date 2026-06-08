# IC Verification Multi-Agent System

基于 LangChain + DeepSeek 的 IC 验证多 Agent 协作系统。**11 个**专业 Agent 协同完成规格分析、设计架构生成、UVM 环境编码、测试用例生成、SVA 断言、编译仿真、覆盖率分析、错误诊断与自动修复全流程。

> 📖 数据流详见 [agent-dataflow.md](agent-dataflow.md)

## 快速开始

```powershell
cd D:\cdv_a
.\venv\Scripts\activate
pip install -r requirements.txt
```

### 配置（可选）

`.env`：
```ini
LLM_PROVIDER=deepseek
LLM_API_KEY=sk-your-key
LLM_MODEL=deepseek-chat
LLM_BASE_URL=https://api.deepseek.com/v1
```

### CLI 一键运行

```powershell
# Bypass 模式（全自动：分析→RTL→UVM→编译→仿真→覆盖率）
python -m src.cli.commands verify specs\alu_combined.md --bypass

# 输出：11/11 passed, Score: 67/100, 覆盖率: line=51.5% branch=32.2% toggle=60.7%
```

### Python API

```python
import asyncio
from pathlib import Path
from src.core.execution import PipelineExecutionService

async def main():
    spec = Path('specs/alu_combined.md').read_text(encoding='utf-8')
    service = PipelineExecutionService.get_instance()
    result = await service.run_pipeline(
        spec_text=spec,
        workflow='full_verification',
        bypass=True,
    )
    print(f"Passed: {result['passed']}/{result['total']}")
    print(f"Score: {result['overall_score']}")

asyncio.run(main())
```

### Python API

```python
import asyncio
from pathlib import Path
from src.core.execution import PipelineExecutionService

async def main():
    spec = Path('specs/alu_combined.md').read_text(encoding='utf-8')
    service = PipelineExecutionService.get_instance()
    result = await service.run_pipeline(
        spec_text=spec,
        workflow='full_verification',       # full_verification | quick_check
        output_root='output/alu_pipeline',
        bypass=True,                         # True=模板 | False=LLM hybrid
    )
    print(f'Passed: {result["passed"]}/{result["total"]}')
    print(f'Overall: {result["overall_score"]}/100')

asyncio.run(main())
```

### 启动 Web

```powershell
uvicorn src.web.api:app --host 0.0.0.0 --port 8000
# 浏览器打开 http://localhost:8000 → 账号 admin / admin123
```

## 运行模式

| 模式 | 命令 | Spec | 代码生成 | 耗时 | API |
|------|------|------|---------|------|-----|
| **Bypass** | `--bypass` | 模板规则 | 模板 | ~10s | 0 |
| **Hybrid (LLM)** | 默认 | LLM 分析 | 模板 bypass | ~90s | 1次 |

> Hybrid：spec_planner 用 LLM 分析规格，后续 agent 检测 ctx 有数据后自动切 bypass 模板模式。

### Bypass 模式输出

```
11/11 passed  Score: 71/100  迭代: 0  覆盖率: line=51.5% branch=32.2%
+--------+--------+--------+-------+------+------+
| Phase  | Output | Status | Score | Time | Note |
+--------+--------+--------+-------+------+------+
| spec   | spec   | PASS   | 95    | 0s   | 模板规则匹配 ALU |
| design | design | PASS   | 90    | 0s   | 12 functions, 8 regs |
| arch   | env    | PASS   | 95    | 7s   | ★ 真实编译+仿真 |
| model  | model  | PASS   | 75    | 0s   | C++ 参考模型 |
| test   | tests  | PASS   | 85    | 0s   | 5 场景, 7 约束策略 |
| regress| regr   | PASS   | 95    | 9s   | ★ 真实编译+仿真 |
| cover  | cov    | PASS   | 76    | 2s   | ★ 真实覆盖率 |
| debug  | debug  | PASS   | 80    | 0s   | 设计↔模型一致 ✅ |
+--------+--------+--------+-------+------+------+
```

## 11 个 Agent

| # | Agent | 产出 | 说明 |
|---|-------|------|------|
| ① | `spec_planner` | spec | 规格分析 → 结构化验证计划 |
| ② | `design_architect` | design_arch + **RTL** | 生成可综合 Verilog (`rtl/<module>.v`) |
| ③ | `verify_architect` | env + quality_report | UVM 环境 + 编译+循环验证 + 质量评分 |
| ④ | `model_agent` | model + **C++ cmodel** | C++ 参考模型 + DPI 桥接 + UVM predictor |
| ⑤ | `test_engineer` | tests | YAML 约束→策略→场景→SV 代码 |
| ⑥ | `assertion_engineer` | (text) | SVA 断言 + 形式验证属性 |
| ⑦ | `regression_manager` | regression | 编译 + 仿真（QuestaSim） |
| ⑧ | `coverage_manager` | coverage | 真实覆盖率收集（line/branch/toggle） |
| ⑨ | `debug_engineer` | debug | 日志分析 + 错误分类 + 设计↔模型交叉验证 |
| ⑩ | `quality_assurance` | (text) | 质量审查 |
| ⑪ | `report_generator` | (text) | 报告生成 |

### Verification Architect 质量检查流水线

```
Step 1: 生成代码（Jinja2 模板，45 个 SV 文件）
Step 2: check_static   → 文件完整性检查
Step 3: check_compile  → QuestaSim vlog 编译
Step 4: check_loopback → Agent 闭环验证（每个 agent 独立编译+仿真）
Step 5: quality_report → quality_report.json（评分：static/compile/loopback）
```

### Debug Engineer 错误诊断

```
仿真日志 → 模式匹配分类:
  env:   virtual interface, config_db, Module.*not defined
  rtl:   X/Z detected, scoreboard.*mismatch
  model: predictor.*mismatch
  spec:  port.*mismatch, width.*mismatch
→ 路由到对应 agent 重生成 → 自动重跑 test→regress→cover→debug（2 轮闭环）
```

### Agent 评分与验证

每个 Agent 有 `min_score` 阈值，不达标自动重试 2 次：

| Agent | min_score | 公式 |
|-------|-----------|------|
| spec_planner | 60 | 10×features + 5×interfaces + 3×test_points + 5×registers |
| design_architect | 50 | 5×functions + 8×registers |
| verify_architect | 50 | 15×agents + files + quality_score×3 |
| regression_manager | 40 | compile_pass?50:0 + test_rate%×0.45 |
| coverage_manager | 20 | line%×0.8 + branch%×0.2 |
| 其余 agent | 50 | baseline |

## 工作流

```
Full (11 阶段):
spec → design → arch → model → test → assert → regress → cover → debug → qa → report
                ↑                         ↑        ↑                  ↑
                └── debug 路由修复 ────────┴────────┴──────────────────┘ (反馈闭环)

Quick (5 阶段):
spec → design → arch → model → test
```

### Agent 数据流 + 反馈闭环

```
spec → design → arch → model → test → regress → cover → debug → qa → report
                     ↑        ↑        ↑                  │
                     └────────┴────────┴── fix_agent ──────┘ (反馈闭环, max 2 轮)

debug_engineer 比对:
  ctx.design_arch.register_count ↔ ctx.model.analysis.register_count
  ctx.design_arch.function_count ↔ ctx.model.analysis.function_count
  不一致 → fix_agent=model_agent (模型落后) 或 fix_agent=design_architect (设计不足)
```

### 错误诊断与自动修复

```
仿真失败 → debug_engineer 解析日志 → 分类:
  env:     virtual interface, config_db → fix: verify_architect
  rtl:     X/Z detected, mismatch       → fix: design_architect  
  model:   predictor mismatch           → fix: model_agent
  spec:    port/width mismatch          → fix: spec_planner
  cross:   design(8 regs) ≠ model(5)    → fix: model_agent ← 新增

编译失败 → _try_autofix_loopback() 读生成文件 → 删错误行 → 写回 → 重编译
```

## 管道运行示例

```powershell
python -m src.cli.commands verify specs/alu_combined.md --bypass
```

```
═══ Pipeline: full_verification ═══
  [+] spec     OK → spec score=95 (0.0s)
  [+] design   OK → design_arch score=90 (0.0s)
  [+] arch     OK → env score=95 (7.7s)       ← 真实编译+仿真
  [+] model    OK → model score=75 (0.4s)
  [+] test     OK → tests score=30 (0.0s)
  [+] assert   OK score=50 (0.0s)
  [+] regress  OK → regression score=95 (9.1s) ← 真实编译+仿真
  [+] cover    OK → coverage score=76 (1.7s)   ← 真实覆盖率
  [+] debug    OK → debug score=80 (0.0s)
  [+] qa       OK score=50 (0.0s)
  [+] report   OK score=50 (0.0s)

+-----------+-------------+--------+-------+---------+-------+
| Phase     | Produces    | Status | Score | Retries | Time  |
+-----------+-------------+--------+-------+---------+-------+
| spec      | spec        | PASS   | 95    | 0       | 0.0s  |
| design    | design_arch | PASS   | 90    | 0       | 0.0s  |
| arch      | env         | PASS   | 95    | 0       | 7.7s  |
| model     | model       | PASS   | 75    | 0       | 0.4s  |
| test      | tests       | PASS   | 30    | 0       | 0.0s  |
| assert    |             | PASS   | 50    | 0       | 0.0s  |
| regress   | regression  | PASS   | 95    | 0       | 9.1s  |
| cover     | coverage    | PASS   | 76    | 0       | 1.7s  |
| debug     | debug       | PASS   | 80    | 0       | 0.0s  |
| qa        |             | PASS   | 50    | 0       | 0.0s  |
| report    |             | PASS   | 50    | 0       | 0.0s  |
+-----------+-------------+--------+-------+---------+-------+
Passed: 11/11  Score: 71/100
Coverage: line=51.5% branch=32.2% toggle=60.0%
```

## 项目结构

```
cdv_a/
├── config/settings.py              # 全局配置
├── src/
│   ├── agents/                     # 11 个 Agent（每个独立目录）
│   │   ├── spec_planner/           #   规格分析
│   │   ├── design_architect/       #   设计架构
│   │   ├── verify_architect/       #   UVM 环境 + 质量自检
│   │   ├── model_agent/            #   参考模型
│   │   ├── test_engineer/          #   测试生成
│   │   ├── assertion_engineer/     #   SVA 断言
│   │   ├── coverage_manager/       #   覆盖率
│   │   ├── regression_manager/     #   回归管理
│   │   ├── debug_engineer/         #   错误诊断
│   │   ├── quality_assurance/      #   质量审查
│   │   └── report_generator/       #   报告生成
│   ├── core/                       # 核心框架
│   │   ├── base.py                 #   Agent 基类 + 验证 + 评分
│   │   ├── execution.py            #   管道引擎 + 反馈闭环 + hybrid 模式
│   │   └── llm_factory.py          #   LLM 工厂
│   ├── tools/                      # 工具集
│   │   ├── uvm/tool_uvm/           #   Jinja2 模板 + gen_uvm 生成器
│   │   ├── compilesim/             #   QuestaSim 编译+仿真+覆盖率
│   │   └── testcase/               #   测试用例生成器
│   ├── cli/commands.py             # CLI 命令行
│   └── web/api.py                  # Web API (FastAPI)
├── specs/                          # 模块规格库
│   ├── alu/  (6 md files)
│   └── uart/
├── generated/alu/                  # 生成的 UVM 代码
│   ├── agents/  env/  bench/  rtl/
│   ├── build/   sim/
│   ├── quality_report.json
│   └── filelist.f
├── tests/
├── .env                            # API key 配置
└── pyproject.toml
```

## 关键特性

| 特性 | 说明 |
|------|------|
| **设计↔模型比对** | debug_engineer 交叉验证 design 和 model 输出一致性 |
| **反馈闭环** | 不一致→路由到对应 agent 重生成→重测试（2轮迭代） |
| **自动修复** | 编译失败时自动读代码→删错误行→写回→重编 |
| Hybrid 模式 | LLM 分析 spec → 模板生成代码 |
| Agent 协作 | 11 agent consumes/produces 自动传递 ctx |
| 真实编译仿真 | QuestaSim vlog + vsim，真实覆盖率 |
| Agent 闭环 | 每个 agent 独立编译+仿真 loopback TB |
| 调试日志 | `logs/agent_debug/debug_*.jsonl` 记录每个 agent I/O |
| Web 平台 | FastAPI + JWT + RBAC，40+ API |

## 配置

### `.env`

```ini
LLM_PROVIDER=deepseek
LLM_API_KEY=sk-your-key
LLM_MODEL=deepseek-chat
LLM_BASE_URL=https://api.deepseek.com/v1
```

### 调试日志

每次运行生成 `logs/agent_debug/debug_YYYYMMDD_HHMMSS.jsonl`：

```jsonl
{"event":"pipeline_start","workflow":"full_verification","phases":["spec","design",...]}
{"agent":{"role":"spec_and_test_planner"},"input":"# ALU spec...","output":"{\"design_name\":\"ALU\",...}"}
{"agent":{"role":"debug_engineer"},"input":"...","output":"cross_check: design(8) vs model(8)"}
{"event":"pipeline_end","passed":11,"degraded":0,"total_time":"10.8s"}
```

### 常见问题

| 问题 | 解决 |
|------|------|
| `LLM API Key未设置` | `.env` 变量名大写 (`LLM_API_KEY`) |
| Agent SKIP | 用 `--bypass` 模式 |
| QuestaSim 路径 | 修改 `src/agents/regression_manager/main.py` 第17行 |
| test 得分低 | `_build_policies` 优先读 `ALU_constraint.yaml` |
| 模拟日志为空 | `debug_engineer` 自动读 `generated/alu/sim/*.log` |

## 配置

### .env 格式

```ini
LLM_PROVIDER=deepseek
LLM_API_KEY=sk-your-key
LLM_MODEL=deepseek-chat
LLM_BASE_URL=https://api.deepseek.com/v1
```

> 不配置 API key 也能用 `--bypass` 模式运行。

### 常见问题

| 问题 | 解决 |
|------|------|
| `LLM API Key未设置` | 检查 `.env` 文件变量名是否大写（`LLM_API_KEY`） |
| Agent 全部 SKIP | 使用 `--bypass` 模式 |
| QuestaSim 找不到 | 路径在 `src/agents/regression_manager/main.py` 第 17 行修改 |
| `{chat_history}` 错误 | 已修复：base.py 显式传入空列表 |

## 测试

```powershell
pytest tests/ src/agents/ src/tools/ -v --tb=short
```

## 环境要求

| 依赖 | 版本 |
|------|------|
| Python | 3.10 - 3.12 |
| langchain | 0.1.20 |
| FastAPI | >=0.110 |
| Jinja2 | >=3.1.0 |
| Rich | >=13.0 |
| PyYAML | >=6.0 |
| DeepSeek API Key | 可选（bypass 模式不需要） |
| QuestaSim | 可选（编译仿真 + 覆盖率） |
