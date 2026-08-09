# DVSim 学习笔记 & SignOffAI 对接方案

> 日期：2026-08-09  
> 目标：理解 OpenTitan 的 DVSim 回归工具，设计 SignOffAI 的前端（spec→test）到后端（regression→signoff）衔接方案

---

## 1. DVSim 是什么

**DVSim** 是 lowRISC CIC（OpenTitan 项目）开发的 Python 回归管理系统。它是一个**工具无关的 EDA 流程调度器**，目前是 OpenTitan 芯片验证的核心基础设施。

```
一句话定位:
  DVSim 之于 IC 验证 = pytest 之于 Python 测试 + Make/Ninja 之于 C 构建
```

### 1.1 支持的工具链

| 流程类型 | 工具 | 配置文件中的 flow 键 |
|----------|------|:---:|
| 仿真 (Simulation) | VCS / Xcelium / Verilator | `sim` |
| 形式验证 (Formal) | JasperGold / VC-Formal | `formal` |
| Lint | AscentLint / Verilator | `lint` |
| CDC 检查 | SpyGlass / Meridian | `cdc` |
| RDC 检查 | Meridian | `rdc` |
| 综合 (Synthesis) | DC / Yosys | `syn` |

### 1.2 核心架构

```
                        dvsim CLI
                           │
                    ┌──────┴──────┐
                    │  FlowCfg    │  ← Hjson 配置驱动
                    │  (base)     │
                    └──────┬──────┘
           ┌───────────────┼───────────────┐
           │               │               │
      SimCfg           FormalCfg        LintCfg ...
      (sim flow)       (formal flow)    (lint flow)
           │
    ┌──────┴──────┐
    │  Scheduler  │  ← 异步调度器：解析依赖 → 并行编译 → 并行仿真
    └──────┬──────┘
           │
    ┌──────┴──────────────────┐
    │  Job Types:             │
    │  CompileSim → RunTest   │
    │  → CovMerge → CovReport │
    └─────────────────────────┘
           │
    ┌──────┴──────────┐
    │  Launcher        │  ← 本地 / LSF / Slurm 多种执行后端
    │  (local/lsf/slurm)│
    └─────────────────┘
           │
    ┌──────┴──────────┐
    │  Report          │  ← HTML Dashboard + JSON data + Testplan annotation
    │  (gen_reports)   │
    └─────────────────┘
```

---

## 2. DVSim 核心流程剖析

### 2.1 配置驱动：Hjson 文件

每个 IP 的验证配置通过一个主 Hjson 文件定义，例如 OpenTitan UART 的配置：

```hjson
// uart_sim_cfg.hjson (概念示意)
{
  flow: "sim"              // ← 告诉 dvsim 这是仿真流程
  name: "uart"
  tool: "vcs"              // 或 xcelium / verilator

  // 编译模式
  build_modes: [
    {
      name: "default"
      build_opts: ["+define+DUT_UART"]
    }
  ]

  // 运行模式
  run_modes: [
    {
      name: "default"
      run_opts: ["+UVM_TESTNAME=uart_smoke"]
    }
  ]

  // 测试列表
  tests: [
    {
      name: "uart_smoke"
      build_mode: "default"
      run_mode: "default"
      reseed: 5              // 跑 5 个不同 seed
    }
  ]

  // 回归集
  regressions: [
    {
      name: "sanity"
      tests: ["uart_smoke"]  // 只跑冒烟
    }
    {
      name: "nightly"
      // tests: null → 跑所有测试
      reseed: 20
    }
  ]
}
```

### 2.2 Testplan 体系：Hjson → Testpoint → Test → Result

```
testplan.hjson            (验证计划，人工编写)
     │
     ├── testpoints: [    ← 定义"要测什么"
     │     {name: "smoke", stage: V1, desc: "...", tests: ["uart_smoke"]}
     │     {name: "parity", stage: V2, desc: "...", tests: ["uart_tx_rx"]}
     │   ]
     │
     └── covergroups: [   ← 定义"要覆盖什么"
           {name: "tx_cg", desc: "..."}
         ]

sim_results.hjson         (仿真结果，工具生成)
     │
     └── {test: "uart_smoke", seed: 123, result: "P", runtime: 12.3, ...}

testplanner.py            (映射工具)
     │
     └── testplan + sim_results → 标注后的 Markdown 表格
         显示每个 testpoint 的通过率/覆盖率
```

### 2.3 执行流程

```
dvsim run uart_sim_cfg.hjson --regression sanity

  Phase 1: 解析配置
    → load uart_sim_cfg.hjson + 所有 import 的文件
    → 展开 wildcards，解析 build_modes / run_modes / tests

  Phase 2: 构建 Job DAG
    → 每个 test 生成: CompileJob → RunJob(seed1) + RunJob(seed2) + ...
    → 每个 regression 生成: 过滤后的 job 集合
    → 依赖分析: RunJob 依赖 CompileJob 完成

  Phase 3: 调度执行 (Scheduler)
    → 异步并行调度，支持 LSF/Slurm 分发
    → 实时状态输出 (每 2s 刷新终端)
    → 支持 Ctrl+C 优雅终止

  Phase 4: 后处理
    → CovMerge: 合并所有 seed 的覆盖率
    → CovReport: 生成覆盖率报告
    → CovVPlan: 映射覆盖率到 testplan
    → gen_reports: 生成 HTML dashboard + JSON

  Phase 5: 发布
    → 结果发布到 regression dashboard
    → 趋势数据入库
```

---

## 3. OpenTitan 的完整验证目录结构

```
hw/ip/uart/                          ← 一个 IP 的完整验证目录
├── data/
│   ├── uart.hjson                   ← IP 寄存器规格 (Hjson)
│   ├── uart_testplan.hjson          ← 验证计划 (testpoint + covergroup)
│   └── uart_sec_cm_testplan.hjson   ← 安全对策验证计划
├── doc/
│   ├── theory_of_operation.md       ← 设计规格 (Markdown)
│   ├── interfaces.md                ← 接口文档
│   ├── registers.md                 ← 寄存器文档
│   ├── programmers_guide.md         ← 编程指南
│   └── checklist.md                 ← 签核检查清单
├── rtl/
│   ├── uart_core.sv                 ← RTL 设计
│   ├── uart_tx.sv
│   └── uart_rx.sv
├── dv/                              ← 验证环境
│   ├── env/
│   │   ├── uart_env.sv              ← UVM env
│   │   ├── uart_scoreboard.sv
│   │   └── seq_lib/                 ← sequence library (15+ sequences)
│   ├── cov/
│   │   └── uart_cov_excl.el         ← 覆盖率排除
│   ├── tb/
│   │   └── uart_tb.sv               ← testbench top
│   └── doc/
│       └── tb.svg                   ← 验证环境框图
└── lint/
    └── uart_lint_cfg.hjson           ← Lint 配置
```

### 关键观察

> **OpenTitan 的 spec 文档（doc/*.md）与 testplan（data/*_testplan.hjson）是两套独立维护的体系。Spec 是人看的 Markdown，testplan 是机器解析的 Hjson。两者之间没有自动同步机制——spec 变更时需要人工同步更新 testplan。**

---

## 4. DVSim vs SignOffAI 当前回归系统的对比

| 维度 | DVSim (OpenTitan) | SignOffAI 现状 |
|------|:---:|:---:|
| **配置格式** | Hjson（结构化，可 include，wildcard 展开） | 硬编码 `FULL_PHASES` 列表 + agent_tools.py |
| **调度器** | 异步并行 Scheduler + LSF/Slurm | 串行 `for p_tuple in phases` |
| **工具支持** | VCS/Xcelium/Verilator/JasperGold/SpyGlass... | 无真实工具对接（Mock 数据） |
| **Testplan** | Hjson testplan → testpoint → test 映射 | 6 个 doc_only 阶段生成空模板 |
| **回归管理** | regression set + reseed + 依赖 DAG | `regression_manager` Agent（空壳） |
| **结果报告** | HTML dashboard + JSON + 趋势 DB | `report_generator` Agent（空壳） |
| **覆盖率** | UCM/URG + vplan 注释 | `coverage_manager` Agent（Mock 数据） |
| **生产验证** | ✅ OpenTitan 芯片已流片 | ❌ 从未执行过真实仿真 |

**结论：DVSim 是经过流片验证的生产级回归系统，SignOffAI 的回归系统目前只是骨架。**

---

## 5. 拼接方案：SignOffAI 前端 → DVSim 后端

### 5.1 完整链路设计

```
┌──────────────────── SignOffAI Front-End ────────────────────┐
│                                                              │
│  spec.md                                                      │
│    │                                                          │
│    ▼                                                          │
│  [Spec Agent]  ─→  spec.json (结构化规格)                      │
│    │                                                          │
│    ├──→ [VPlan Engine]  ─→  testplan.hjson (机器可解析)       │
│    │                                                          │
│    ├──→ [Design Agent]  ─→  design_arch.json                  │
│    │                                                          │
│    ├──→ [Model Agent]   ─→  ref_model.cpp                     │
│    │                                                          │
│    ├──→ [UVM Agent]     ─→  dv/env/ (UVM 环境代码)            │
│    │                                                          │
│    └──→ [Test Agent]    ─→  dv/env/seq_lib/ (sequence 代码)   │
│                                                              │
│    ──→ 生成 sim_cfg.hjson (DVSim 配置文件)                     │
│                                                              │
└──────────────────────┬───────────────────────────────────────┘
                       │
                       ▼
┌──────────────────── DVSim Back-End ──────────────────────────┐
│                                                              │
│  dvsim run sim_cfg.hjson --regression nightly                 │
│    │                                                          │
│    ├── Compile (VCS/Xcelium/Verilator)                        │
│    ├── Run (N seeds × M tests, 并行调度)                       │
│    ├── CovMerge + CovReport                                   │
│    └── gen_reports → dashboard.html + results.json            │
│                                                              │
└──────────────────────┬───────────────────────────────────────┘
                       │
                       ▼
┌──────────────────── SignOffAI Post-Process ──────────────────┐
│                                                              │
│  results.json + coverage.json                                 │
│    │                                                          │
│    ├──→ [Coverage Agent]  ─→  gap analysis                    │
│    ├──→ [Debug Agent]     ─→  failure analysis                │
│    ├──→ [QA Agent]        ─→  quality review                  │
│    └──→ [Report Agent]    ─→  signoff report + evidence.zip   │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

### 5.2 衔接点：SignOffAI 需要生成的文件

SignOffAI 的输出需要映射到 DVSim 的输入。具体来说：

```
SignOffAI 生成                          →  DVSim 消费
────────────────────────────────────────────────────────────
output/<project>/dvsim/sim_cfg.hjson    →  dvsim run ...sim_cfg.hjson
  ├─ 由 [UVM Agent] 的产出推导
  ├─ filelist: 从 env 代码提取
  ├─ tests: 从 [Test Agent] 的 test_names 推导
  └─ regressions: 从 vplan 优先级推导

output/<project>/dvsim/testplan.hjson   →  testplanner 注释
  ├─ testpoints: 从 [VPlan Engine] 生成
  └─ covergroups: 从 spec 接口/功能点推导

output/<project>/dv/env/               →  UVM 环境（已由 [UVM Agent] 生成）
  ├─ *_env.sv, *_agent.sv, *_scoreboard.sv ...
  └─ seq_lib/*.sv
```

### 5.3 加入 SignOffAI CLI

```bash
# 完整流程
vagent verify --spec specs/uart/spec.md --workflow full --backend dvsim

# 内部执行:
# 1. spec→vplan→UVM→test (SignOffAI front-end)
# 2. 生成 dvsim 配置文件
# 3. 调用 dvsim 执行回归
# 4. 解析 dvsim 结果
# 5. coverage→debug→qa→report→signoff (SignOffAI post-process)

# 只跑后端（已有 UVM 环境 + tests）
vagent regress --cfg sim_cfg.hjson --regression nightly
vagent regress --cfg sim_cfg.hjson --regression nightly --tool vcs
vagent regress --cfg sim_cfg.hjson --regression nightly --seeds 20
```

---

## 6. 分阶段实施计划

### Phase 1: DVSim 依赖安装 & API 调用链路验证（立即）

> dvsim 源码已在 `src/tools/dvsim/`，不需要"安装工具"，只需要装依赖。

#### 1.1 装依赖

```bash
cd src/tools/dvsim
pip install -e .    # 装上 hjson / click / jinja2 / tabulate / psutil / plotly ...
```

#### 1.2 dvsim 的真实 API 调用链路

dvsim 不是一个"lib 库"——它是 CLI 优先设计的。但它的核心逻辑完全可以通过 Python 直接调用，因为 `main()` 函数拆得很清楚：

```python
# dvsim 的 CLI main() 核心只有 4 步（cli/run.py:932-1050）:
def main(argv=None):
    args = parse_args(argv)                              # 1. 解析命令行参数 → argparse.Namespace
    cfg  = make_cfg(args.cfg, args, proj_root)           # 2. 读 Hjson 配置 → 构建 SimCfg 对象
    cfg.create_deploy_objects()                           # 3. 根据 tests/regressions 生成 Job DAG
    results = cfg.deploy_objects()                        # 4. Scheduler 异步调度执行所有 Job
    cfg.gen_results(results)                              # 5. 生成覆盖率报告/HTML dashboard/JSON
    sys.exit(1 if cfg.has_errors() else 0)
```

**关键发现：整条链路只需要一个 `args` 对象 + 一个 Hjson 文件。所有步骤都是 `SimCfg` 的方法调用。**

#### 1.3 SignOffAI 怎么调 dvsim

SignOffAI 不需要走 CLI 子进程，可以直接在 Python 里构造 `args` 然后调用：

```python
# src/tools/dvsim_adapter/runner.py (新建模块)

import argparse
from pathlib import Path
from dvsim.flow.factory import make_cfg

def run_regression(cfg_path: str, tests: list[str], tool: str = "vcs",
                   proj_root: str = ".", scratch_root: str = "output/scratch",
                   seeds: int = 5, max_parallel: int = 4) -> dict:
    """
    SignOffAI → dvsim: 直接调 Python API 跑回归。
    返回 {passed, failed, total, coverage, dashboard_url}
    """

    # Step 1: 构造 args（模拟命令行参数）
    args = argparse.Namespace(
        cfg=cfg_path,
        tool=tool,
        items=tests,              # ["uart_smoke", "uart_tx_rx"]
        proj_root=proj_root,
        scratch_root=scratch_root,
        branch="develop",
        build_opts=[], run_opts=[], build_modes=[], run_modes=[],
        reseed=seeds, reseed_multiplier=1.0,
        seeds=[], fixed_seed=None,
        gui=False, gui_debug=False, interactive=False,
        waves=None, max_waves=5, cov=True, cov_merge_previous=False,
        xprop_off=True, profile=None, dry_run=False,
        verbose=None, verbosity=None,
        build_unique=False, build_seed=None, build_only=False,
        run_only=False,
        max_parallel=max_parallel, max_odirs=5,
        local=True, remote=False, fake=False,
        purge=False, list=None,
        select_cfgs=None, job_prefix="",
        print_interval=2, instrumentation=None,
        cov_unr=False, cov_analyze=False,
        map_full_testplan=False,
        # 时间戳
        timestamp="signoffai", timestamp_long="signoffai",
    )

    # Step 2: 构建 FlowCfg（读 Hjson + 展开 wildcard + 创建 BuildMode/RunMode/Test/Regression）
    cfg = make_cfg(Path(cfg_path), args, proj_root)

    # Step 3: 生成 deploy 对象（CompileJob + RunJob × seeds）
    cfg.create_deploy_objects()

    # Step 4: 调度执行（异步并行编译 + 仿真）
    results = cfg.deploy_objects()

    # Step 5: 生成报告（覆盖率合并 + HTML dashboard + JSON）
    cfg.gen_results(results)

    # Step 6: 提取 SignOffAI 需要的数据
    return {
        "passed":  results.get("passed", 0),
        "failed":  results.get("failed", 0),
        "total":   results.get("total", 0),
        "coverage": {
            "line":   cfg.results_summary.get("line_coverage", 0),
            "branch": cfg.results_summary.get("branch_coverage", 0),
            "toggle": cfg.results_summary.get("toggle_coverage", 0),
        },
        "dashboard": str(Path(scratch_root) / "latest" / "reports" / "index.html"),
        "results_json": str(Path(scratch_root) / "latest" / "reports" / "index.json"),
    }
```

#### 1.4 集成到 SignOffAI Pipeline

```python
# 在 PipelineExecutionService 或 CLI 中调用:

# 旧代码:
# regress_agent.execute_task(...)  # → Mock 数据

# 新代码:
from src.tools.dvsim_adapter.runner import run_regression

result = run_regression(
    cfg_path="output/apb_uart/dvsim/sim_cfg.hjson",  # SignOffAI 在 UVM 阶段后生成
    tests=["uart_smoke", "uart_tx_rx", "uart_loopback"],
    tool="vcs",
    seeds=10,
)

# 结果写入 ContextStore → 触发后续 cover/debug/qa/signoff
ctx.put("regression", result)
```

#### 1.5 验证清单

```
□ pip install -e src/tools/dvsim 成功（所有依赖就位）
□ from dvsim.sim.flow import SimCfg  不报错
□ from dvsim.flow.factory import make_cfg  不报错
□ 为 apb_uart 手写 sim_cfg.hjson（对接已有的 UVM env 文件路径）
□ run_regression(...) 函数可以执行（即使仿真工具不可用，可以用 --dry-run 模式验证 Job DAG 正确）
```

### Phase 2: Hjson 自动生成（本周）

```
目标: SignOffAI 自动生成 dvsim 配置文件

步骤:
  1. 创建 src/tools/dvsim_adapter/ (新模块)
     ├── cfg_generator.py   ← spec.json → sim_cfg.hjson
     └── testplan_gen.py    ← vplan.json → testplan.hjson

  2. 从 spec.json 提取: module_name, filelist, top_module
  3. 从 vplan 提取: testpoints (name/stage/desc/tests)
  4. 从 UVM env 提取: agent 列表, config 参数
  5. 渲染 Jinja2 模板 → sim_cfg.hjson + testplan.hjson
```

### Phase 3: 结果解析 & 反馈闭环（下周）

```
目标: DVSim 结果回流到 SignOffAI 上下文

步骤:
  1. 解析 dvsim 输出的 sim_results.json
  2. 写入 ContextStore: regression / coverage / debug
  3. 触发 SignOffAI 的 Cover→Debug→QA→Report→Signoff 后处理链
  4. signoff 输出引用 dvsim 的 HTML dashboard
```

### Phase 4: OpenTitan IP 验证（下月）

```
目标: 在真实的 OpenTitan IP 上跑通完整流程

候选 IP:
  - uart: 中等复杂度，已有完整的 spec + UVM env + testplan
  - gpio: 简单，适合快速验证
  - spi_device: 接口清晰，覆盖率模型完整

步骤:
  1. 用 SignOffAI 读取 OpenTitan 的 doc/*.md 规格文档
  2. 生成 testplan.hjson (对比 OpenTitan 手写版，评估质量)
  3. 使用 OpenTitan 已有的 UVM env（不重新生成，验证兼容性）
  4. dvsim 跑回归
  5. SignOffAI 解析结果 + 生成签核报告
```

---

## 7. 关键技术决策

### 7.1 为什么不替换 DVSim 而是对接？

| 如果自己写回归系统 | 对接 DVSim |
|---|---|
| 需要实现：调度器/并行/资源管理/LSF/结果DB/覆盖率/仪表盘 | OpenTitan 已验证，bug 少 |
| 估计工作量：6-12 人月 | 估计工作量：2-3 周 |
| 不可控质量风险 | 流片验证过的代码 |
| 需要维护两套工具链适配（VCS+Xcelium+Verilator...） | DVSim 已适配 |

### 7.2 SignOffAI 的差异化价值在哪里？

```
DVSim 提供:                        SignOffAI 提供:
──────────────────────────────     ─────────────────────────────
"怎么跑"                           "跑什么"
仿真调度 + 结果收集 + 报告          LLM 理解 spec → 生成 testplan
                                   LLM 分析 log → 定位根因
"工具链集成"                        "智能决策"
VCS/Xcelium/Verilator/SpyGlass     LLM 决策：补充什么测试
                                   覆盖率缺口分析 + 自动建议
"机械执行"                          "认知工作"
解析配置 → 编译 → 跑 → 合并        读 spec → 理解 → 规划 → 签核
```

**SignOffAI 不替代 DVSim，而是给 DVSim 提供智能输入 + 智能后处理。**

---

## 8. 一句话总结

> **DVSim 是 OpenTitan 流片验证的生产级回归引擎，SignOffAI 是 LLM 驱动的验证前端。正确架构是：SignOffAI（spec→vplan→UVM→test→hjson）→ DVSim（compile→sim→cov→report）→ SignOffAI（analyze→debug→qa→signoff）。三阶段流水线，DVSim 做它最擅长的"机械执行"，SignOffAI 做它最擅长的"认知工作"。**
