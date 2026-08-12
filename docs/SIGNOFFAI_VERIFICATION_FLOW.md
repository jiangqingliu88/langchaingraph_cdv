# SignOffAI — 芯片设计验证完整流程

> **项目定位**：个人级 CLI 工具，将 IC 验证从"手工作坊"演变为"可复现、可审计、可治理的工程平台"。
>
> **核心约束**：禁止 Web 前端开发，所有功能通过 `vagent` CLI 交付。

---

## 一、总体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        SignOffAI 平台                           │
│                                                                 │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐       │
│  │  spec    │→│  design  │→│   uvm    │→│  model   │       │
│  │ 规格分析 │  │ 架构设计 │  │ UVM环境  │  │ 参考模型 │       │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘       │
│        │             │              │              │            │
│        ▼             ▼              ▼              ▼            │
│  ┌──────────────────────────────────────────────────┐          │
│  │              并行开发阶段                          │          │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐       │          │
│  │  │   test   │  │  assert  │  │   rtl    │       │          │
│  │  │ 测试生成 │  │ 断言生成 │  │ RTL生成  │       │          │
│  │  └──────────┘  └──────────┘  └──────────┘       │          │
│  └──────────────────────────────────────────────────┘          │
│        │                                                       │
│        ▼                                                       │
│  ┌──────────┐  ┌──────────────────────────────────┐          │
│  │ regress  │→│         并行分析阶段               │          │
│  │ 回归执行 │  │  ┌──────────┐  ┌──────────┐      │          │
│  └──────────┘  │  │  cover   │  │  debug   │      │          │
│                │  │ 覆盖率   │  │ 调试分析 │      │          │
│                │  └──────────┘  └──────────┘      │          │
│                └──────────────────────────────────┘          │
│        │                                                       │
│        ▼                                                       │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐                    │
│  │    qa    │→│  report  │→│  vclose  │                    │
│  │ 质量审查 │  │ 签核报告 │  │ 验证收敛 │                    │
│  └──────────┘  └──────────┘  └──────────┘                    │
└─────────────────────────────────────────────────────────────────┘
```

---

## 二、完整验证流程（18 阶段）

验证流程分为 **前端设计（6 阶段）** 和 **功能验证（12 阶段）** 两大阶段。

### 2.1 前端设计阶段

| # | Phase | Agent | 产出 | 说明 |
|---|-------|-------|------|------|
| 1 | **spec** | `SpecAgent` | `spec.json` | 自然语言规格 → 结构化 JSON（features、interfaces、registers、test_points、coverage_goals） |
| 2 | **design** | `DesignAgent` | `design_arch.json` | 功能分解 → function hierarchy + register map + RTL hierarchy |
| 3 | **model** | `ModelAgent` | `model.h/.cpp` | 纯 C++ 参考模型（无 SystemC 依赖），g++ 可直接编译 |
| 4 | **rtl** | `RtlAgent` | RTL 代码 | 从 design_arch 生成可综合 RTL |
| 5 | **ifspec** | *(文档生成)* | 接口控制文档 | 自动生成接口规范文档 |
| 6 | **rtlsign** | *(文档生成)* | RTL 签核报告 | 自动生成 RTL 签核报告 |

### 2.2 功能验证阶段

| # | Phase | Agent | 产出 | 说明 |
|---|-------|-------|------|------|
| 7 | **vplan** | *(文档生成)* | 验证计划 | 自动生成验证计划文档 |
| 8 | **tpoint** | *(文档生成)* | 测试点分解 | 从 spec 提取测试点矩阵 |
| 9 | **rtm** | *(文档生成)* | 需求追踪矩阵 | feature ↔ test ↔ coverage 双向追溯 |
| 10 | **UVM** | `UvmAgent` | UVM 验证环境 | env、agent、driver、monitor、scoreboard |
| 11 | **test** | `TestAgent` | SV 测试代码 | 约束 YAML → 场景 → SV test/sequence |
| 12 | **assert** | `AssertsAgent` | SVA 断言 | 并发断言、形式属性、CDC 检查 |
| 13 | **regress** | `RegressAgent` | 回归报告 | 编译 → 仿真 → 收集 pass/fail + 覆盖率 |
| 14 | **cover** | `CoverAgent` | 覆盖率报告 | 代码覆盖 + 功能覆盖 gap 分析 |
| 15 | **debug** | `DebugAgent` | 根因分析 | 失败用例多跳因果推理 + 修复建议 |
| 16 | **qa** | `QaAgent` | 质量报告 | 代码审查 + 标准合规 + 质量评分 |
| 17 | **report** | `ReportAgent` | 签核证据包 | JSON/HTML 报告 + 签核结论 |
| 18 | **vclose** | *(文档生成)* | 验证收敛报告 | 覆盖率趋势 + 收敛判定 |

---

## 三、Agent 详解

### 3.1 SpecAgent — 规格与测试规划师

```
task_type: spec_analysis
consumes:  []
produces:  "spec"  →  spec.json
```

**职责**：将自然语言设计规格转为结构化 JSON。

**输出结构**：
```json
{
  "design_name": "apb_uart",
  "version": "1.0",
  "overview": "...",
  "features": ["APB 寄存器读写...", "UART 发送...", ...],
  "interfaces": [{"name": "APB", "type": "APB", "signals": {...}}, ...],
  "registers": [{"name": "baud_rate", "offset": "0x00", ...}, ...],
  "test_points": [{"id": "TP_001", "feature": "...", "priority": "P0", ...}, ...],
  "coverage_goals": {"functional_coverage": 100, "code_coverage": 95},
  "verification_architecture": {
    "agents": [...],
    "scoreboards": [...],
    "virtual_sequencer": {...},
    "clock_reset": {"clk": "pclk", "rst_n": "preset_n"}
  }
}
```

**硬约束**：
- `design_name` 禁止占位符（dut/DUT/top/chip/block）
- `interfaces` 必须列出每个端口信号的 direction/width
- `verification_architecture.agents` 的 ports 必须与 interfaces.signals 一致

---

### 3.2 DesignAgent — 设计架构师

```
task_type: code_generation
consumes:  spec (features, interfaces, registers)
produces:  "design_arch"
```

**职责**：将 spec 的 features 分解为 function hierarchy，生成 register map 语义（每个 bit field 的含义），构建 RTL 模块层次结构。

**输出**：
```json
{
  "module_name": "apb_uart",
  "function_hier": {
    "name": "apb_uart_top",
    "children": [
      {"name": "apb_interface", "ops": ["REG_RD", "REG_WR"]},
      {"name": "uart_tx", "ops": ["PARALLEL_TO_SERIAL"]},
      {"name": "uart_rx", "ops": ["SERIAL_TO_PARALLEL"]},
      {"name": "fifo_16x8", "ops": ["PUSH", "POP", "FULL", "EMPTY"]}
    ]
  },
  "registers": [...],
  "signoff_checklist": [...]
}
```

---

### 3.3 UvmAgent — 验证架构师（UVM 工程师）

```
task_type: code_generation
consumes:  spec
produces:  "env"  →  UVM 验证环境
```

**职责**：决策 UVM 组件结构、连接拓扑、比对策略，生成组件代码并通过质量检查。

**工具链**：
```
find_spec_yaml  →  jinja_render  →  quality_report
                                      ├── check_static   (文件存在性)
                                      ├── check_compile  (QuestaSim vlog)
                                      └── check_loopback (编译+仿真闭环)
```

**质量自检循环**：
```
1. find_spec_yaml → 生成 agent/env/bench YAML
2. jinja_render   → Jinja2 渲染 → SV 骨架代码
3. quality_report → 三项检查（静态+编译+闭环）
4. 若失败 → read_file → write_file 修复 → 回到步骤3
5. 最多 3 轮修复，仍失败则降级交付
```

**验收标准**：静态检查（8 个 UVM 文件存在）是硬性指标。编译/闭环失败允许降级但管线继续。

**编译仿真路径**：`uvm_regress`

---

### 3.4 ModelAgent — 参考模型工程师

```
task_type: code_generation
consumes:  spec + design_arch
produces:  "model"  →  model.h / model.cpp
```

**职责**：从 design_arch 的 register map + function hierarchy 推导算法行为，生成纯 C++ 参考模型。

**设计原则**：
- **纯 C++，非 SystemC**：无库依赖，g++/clang 直接编译，无并发/时序语义
- **接口**：`predict(input_txn, state) → output_txn`
- **自验证**：生成 IO test vectors + 编译/运行命令

---

### 3.5 TestAgent — 测试工程师

```
task_type: code_generation
consumes:  spec + env
produces:  "tests"  →  SV 测试代码
```

**职责**：测试点 → 策略映射 → 约束 YAML → SV 测试代码，一站式生成。

**工具链**：
```
spec.json
  │
  ▼
parse_test_points()           # spec → 结构化 test 列表（按 feature 分组）
  │
  ▼
map_policies_to_tests()       # 关键词匹配 → 策略场景映射
  │                            #   寄存器/config → config_consistency
  │                            #   UART/串行/tx/rx → data_integrity
  │                            #   FIFO/缓冲/溢出   → capacity_boundary
  │                            #   中断/IRQ         → event_trigger
  │                            #   波特率/时钟      → timing_constraint
  │                            #   功耗/idle        → power_mode
  │                            #   复位/错误注入    → error_injection
  │
  ▼
build_scenario_yaml()         # 完整 constraint.yaml
  │                            #   ├── constraint (project, env, regress_dir)
  │                            #   ├── transactions (根据 interface 类型推断)
  │                            #   ├── policies (参数 schema + 默认值)
  │                            #   ├── combinator (5 种模式)
  │                            #   └── scenarios (P0/P1/P2 分级)
  │
  ▼
generate_test_cases()         # CLI 调用 → SV 代码
  │                            #   每个 scenario → test_xxx.sv + test_xxx_seq.sv + run.sh
  │
  ▼
check_test_coverage()         # spec test_points vs 生成 scenario 覆盖率检查
```

**编译仿真路径**：`test_regress`

**场景优先级分工**：

| 优先级 | 维护者 | 内容 |
|--------|--------|------|
| P0 | UVM 工程师定义骨架 | 冒烟测试、定向功能验证 |
| P1 | Test 工程师主力维护 | 随机回归、压力测试 |
| P2 | Test 工程师按需添加 | 功耗专项、CDC/并发专项 |

---

### 3.6 AssertsAgent — 断言工程师

```
task_type: assertion_generation
consumes:  (文本输入)
produces:  SVA 断言代码
```

**职责**：从设计意图推断时序属性，生成 SVA 断言和形式验证属性。

**断言模板**：
- **握手协议**：valid/ready、req/ack
- **数据完整性**：无 X/Z 检查
- **时序约束**：延迟范围、min/max
- **状态机**：合法转换、死锁检测

---

### 3.7 RegressAgent — 回归管理器

```
task_type: regression_management
consumes:  env + tests
produces:  "regression"  →  report.json / report.html
```

**双路径执行**：

```
regression.yaml 存在？
  ├── YES → 确定性路径
  │         python regression.py --config regression.yaml --action all --mode local
  │         → 解析 report_summary.txt
  │         → 收集覆盖率 (merged.ucdb)
  │         → 若 failed > 0 → LLM 失败聚类分析
  │
  └── NO  → LLM 路径
            compile_env → run_simulation → generate_regression_report
            → 若编译失败 → 停止
            → 收集所有 test 结果后生成报告
```

**回归 YAML 格式**（`regression.yaml`）：
```yaml
env_name: ALU_env
top_module: ALU_env_bench_tb_top
tests:
  - name: test_smoke_test
    uvm_test: test_smoke_test
    top: ALU_env_bench_tb_top
    coverage: true
  - name: test_random_regression
    uvm_test: test_random_regression
    top: ALU_env_bench_tb_top
    coverage: true
```

---

### 3.8 后续阶段

| Agent | 职责 | 核心逻辑 |
|-------|------|----------|
| **CoverAgent** | 覆盖率缺口解释 | 收集 Line/Branch/Toggle/FSM 覆盖率，分析语义缺口，建议补充测试 |
| **DebugAgent** | 多跳根因追踪 | 读错误摘要 → 假设 → 波形/仿真验证 → 排除/确认 → 收敛 |
| **QaAgent** | 语义级代码审查 | 5 维度评分：代码质量、架构、功能覆盖、标准合规、设计意图一致性 |
| **ReportAgent** | 签核证据包合成 | 聚合证据链 → 自然语言签核结论 + 风险评级 |
| **vclose** | 验证收敛判定 | 覆盖率趋势 + 收敛条件检查 |

---

## 四、两种管线模式

### 4.1 完整验证（full_verification）

```
spec → design → model → rtl → [ifspec] → [rtlsign]
  → [vplan] → [tpoint] → [rtm]
  → UVM → ┬─ test
          └─ assert     (并行)
  → regress
  → ┬─ cover
    └─ debug            (并行)
  → qa → report → [vclose]
```

**适用场景**：正式签核（tapeout），需要完整证据链。

### 4.2 快速检查（quick_check）

```
spec → design → model → [vplan] → [tpoint]
```

**适用场景**：早期设计迭代，快速验证 spec 一致性。

---

## 五、UVM 阶段 vs Test 阶段

两个工程师角色通过 **`regress_dir`** 字段区分编译仿真路径：

| 维度 | UVM 阶段 | Test 阶段 |
|------|----------|-----------|
| **Agent** | `UvmAgent` | `TestAgent` |
| **工作内容** | 调试 case、修复 env、model 保持稳定 | 补充次要场景 + 随机 case |
| **编译路径** | `uvm_regress/build/work` | `test_regress/build/work` |
| **产出** | UVM env + P0 case 骨架 | P1/P2 场景 SV 代码 |
| **约束 YAML 默认** | `regress_dir: uvm_regress` | `regress_dir: test_regress` |

**使用方式**：
```bash
# UVM 阶段
python -m src.tools.testcase_tools.main constraint.yaml --all --regress-dir uvm_regress

# Test 阶段（默认）
python -m src.tools.testcase_tools.main constraint.yaml --all --regress-dir test_regress
```

生成的 `run.sh` 自动指向正确路径：
```bash
#!/bin/bash
# Regress Dir: test_regress    # ← 自动切换
cd test_regress/build/work || exit 1
vsim -c -do "run -all" +UVM_TESTNAME=test_smoke_test ...
```

---

## 六、工具链全景

### 6.1 工具分类

| 类别 | 目录 | 工具数 | 使用者 |
|------|------|--------|--------|
| UVM 环境生成 | `uvm_tools/` | 10 | UvmAgent |
| 测试用例生成 | `testcase_tools/` | 6 | TestAgent |
| 断言生成 | `assertion_tools/` | 4 | AssertsAgent |
| 覆盖率 | `coverage_tools/` | 4 | CoverAgent |
| 调试 | `debug_tools/` | 4 | DebugAgent |
| 规格分析 | `spec_tools/` | 3 | SpecAgent |
| C 参考模型 | `cmodel_tools/` | 2 | ModelAgent |
| 回归框架 | `regression_tools/` | 1 | RegressAgent |
| 公共库 | `lib/` | 7 | 所有 UVM 工具 |
| 文档工具 | `doc_tools/` | 2 | 多 Agent |

### 6.2 公共库（`lib/`）

| 模块 | 功能 |
|------|------|
| `compile.py` | QuestaSim vlog 编译检查 |
| `loopback.py` | 编译 + vsim 闭环仿真 + 自动修复 |
| `static_check.py` | 验证 8 个 UVM 文件存在 |
| `filelist.py` | 构建 TB 文件列表 |
| `uvm_context.py` | 线程安全的共享上下文 |
| `llm_refine.py` | LLM 驱动的编译错误自动修复 |
| `collect_real_coverage.py` | 从 merged.ucdb 收集真实覆盖率 |

---

## 七、数据流与目录结构

### 7.1 黑板书通信

Agent 之间通过 ContextStore（黑板）传递数据，每个 Agent 声明 consumes/produces：

```
spec ────────→ design ────────→ uvm ────────→ regress ────────→ cover ────────→ report
  │               │               │               │               │
  │               │               ├──→ test      │               │
  │               │               │               │               │
  │               └──→ model      │               │               │
  │                               │               │               │
  └───────────────────────────────┴───────────────┴───────────────┘
```

### 7.2 输出目录结构

```
output/<run_id>/
├── spec.json                    # SpecAgent 产出
├── design_arch.json             # DesignAgent 产出
├── model/
│   ├── model.h / model.cpp      # ModelAgent 产出
│   └── test_vectors/
├── rtl/                         # RTL 代码
├── env/                         # UVM 环境（UvmAgent 产出）
│   ├── ALU_env_pkg.sv
│   ├── ALU_env.sv
│   ├── ALU_agent/
│   ├── ALU_driver/
│   ├── ALU_monitor/
│   └── ALU_scoreboard/
├── inputs/yaml/
│   ├── constraint.yaml          # TestAgent 生成的约束 YAML
│   └── regression.yaml          # RegressAgent 的回归 YAML
├── testcases/                   # TestAgent 产出
│   ├── test_smoke_test/
│   │   ├── test_smoke_test.sv
│   │   ├── test_smoke_test_seq.sv
│   │   └── run.sh
│   ├── test_random_regression/
│   └── ...
├── build/work/                  # 编译工作目录
├── sim/agent/                   # 仿真日志
├── report.json                  # 回归报告
├── report.html                  # HTML 报告
└── quality_report.json          # UVM 质量评分
```

---

## 八、CLI 命令速查

```bash
# ── 管线执行 ──
vagent verify --pipeline full    # 执行完整验证管线
vagent verify --pipeline quick   # 执行快速检查管线
vagent verify --phase UVM        # 只执行 UVM 阶段

# ── 测试用例生成 ──
python -m src.tools.testcase_tools.main constraint.yaml --scenarios   # 列出场景
python -m src.tools.testcase_tools.main constraint.yaml --all         # 生成全部测试
python -m src.tools.testcase_tools.main constraint.yaml --test 0      # 预览第 0 个测试

# ── 复现与审计 ──
vagent dump <run_id>             # 复现任意一步 Agent 动作

# ── 签核 ──
vagent signoff <run_id>          # 生成签核证据包
```

---

## 九、签核证据链

SignOffAI 的最终产出不是"代码"，而是 **签核证据包**——一条从规格到签核的完整可审计链路：

```
spec.json
  ├── [hash: a1b2...] 输入: design_spec.md → 输出: spec.json
  │
design_arch.json
  ├── [hash: c3d4...] 输入: spec.json → 输出: function_hier + register_map
  │
UVM env (quality_report.json)
  ├── [hash: e5f6...] 静态检查 ✓  编译检查 ✓  闭环检查 ✓
  │
testcases/ (test_summary.json)
  ├── [hash: g7h8...] 6 scenarios → 覆盖率 100% vs spec test_points
  │
regression (report.json)
  ├── [hash: i9j0...] Pass: 48  Fail: 2  Coverage: 94.3%
  │
QA report
  ├── [hash: k1l2...] Verdict: READY  Score: 85/100
  │
REPORT (signoff.json)
  └── [hash: m3n4...] Status: CONDITIONAL_APPROVED
      风险: 低 (2 failures 均已知问题，有 workaround)
      签核人: AI 辅助建议，待人工确认
```

每个阶段输出 artifact manifest（包含 hash、输入、输出、执行日志），构成从规格到签核的完整证据链。

---

## 十、设计原则

| 原则 | 实现 |
|------|------|
| **LLM 不做结构决策** | LLM 只做"完形填空"——UVM 骨架由 Jinja2 模板渲染，策略由规则引擎推断 |
| **每个 Tool 独立可复现** | 每个 Tool 有独立脚本 + JSON Schema 契约 + 输入输出验证 |
| **确定性优先于 AI** | RegressAgent 优先走 regression.py CLI 确定性路径，仅失败时回退 LLM 分析 |
| **自检闭环** | UVM 阶段：静态→编译→闭环 三项检查全 PASS 才交付 |
| **降级交付** | 编译/闭环失败不阻断管线，标记质量评分后继续 |
| **证据驱动** | 每个阶段输出 artifact manifest，支持 `vagent dump` 完整复现 |
