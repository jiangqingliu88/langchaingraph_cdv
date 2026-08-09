# SignOffAI Pipeline Agent 角色与能力

## 流水线概览

17 个阶段，11 个 AI Agent，5 条工作流。

```
spec → design → model → [ifspec] → [rtlsign] → [vplan] → [tpoint] → [rtm]
  → UVM → test → assert → regress → cover → debug → qa → report → [vclose]

[] = doc_only 阶段，仅生成文档不执行 Agent
```

### 工作流变体

| 工作流 | 阶段数 | 阶段列表 |
|--------|--------|---------|
| `full_verification` | 17 | 全部阶段 |
| `quick_check` | 5 | spec → design → model → ifspec → rtlsign |
| `regression_only` | 3 | regress → cover → report |
| `ppa_analysis` | 2 | vplan → report |

---

## Agent 详情

### 1. 规格与测试规划师 (SpecAndTestPlanner)

| 属性 | 值 |
|------|-----|
| **Role** | `spec_and_test_planner` |
| **Phase** | `spec`（第 1 阶段） |
| **LLM 模型** | `deepseek-chat` (task_type: `spec_analysis`) |
| **Consumes** | 无（从原始 spec 文本开始） |
| **Produces** | `spec` — 设计名称、功能特性、接口、寄存器、测试点、覆盖率目标、验证架构 |
| **最低分** | 60 |
| **最大重试** | 2 |

**能力：**
- 解析 Markdown 规格文档，提取 `module:`、`level:`、`requirements:` 等元数据
- 识别功能特性（features）、接口信号（interfaces）、寄存器（registers）
- 生成测试点分解（按类别：basic_function / configuration / error_handling / timing / stress）
- 输出覆盖率目标（code_coverage + functional_coverage）
- 定义验证架构（agent 类型、sequencer、scoreboard、clock/reset）

**评分规则：** `min(10×features + 5×interfaces + 3×tests + 5×registers, 90)`

---

### 2. 设计架构师 (DesignArchitect)

| 属性 | 值 |
|------|-----|
| **Role** | `design_architect` |
| **Phase** | `design`（第 2 阶段） |
| **LLM 模型** | `deepseek-coder` (task_type: `code_generation`) |
| **Consumes** | `spec.features`, `spec.interfaces`, `spec.registers` |
| **Produces** | `design_arch` — 模块层次、RTL 层次、寄存器映射、签核 checklist |
| **最低分** | 50 |
| **最大重试** | 2 |

**能力：**
- 生成 function hierarchy（顶层模块 → 子模块 → 功能单元）
- 生成 RTL hierarchy（文件列表、模块端口）
- 寄存器映射表（地址、位宽、读写属性、默认值）
- 签核 checklist（代码规范、接口一致性、功耗约束等）
- 输出 Markdown 微架构文档

**评分规则：** `min(30 + 5×registers + n_funcs/100, 90)`

---

### 3. 参考模型工程师 (ModelAgent)

| 属性 | 值 |
|------|-----|
| **Role** | `model_agent` |
| **Phase** | `model`（第 3 阶段） |
| **LLM 模型** | `deepseek-coder` (task_type: `code_generation`) |
| **Consumes** | `spec`, `design_arch` |
| **Produces** | `model` — C++ 参考模型、测试向量、运算分析 |
| **最低分** | 无（<50 触发重试） |
| **最大重试** | 2 |

**能力：**
- 分析设计架构（`analyze_design_arch`）
- 生成 C++ 参考模型（`generate_ref_model`）— 类结构、运算函数
- 生成测试向量（`generate_test_vectors`）— 输入/期望输出对
- 支持多种运算类型（算术、逻辑、移位）

**评分规则：** `min(50 + 文件数×10, 80)`；不足 → 25；无输出 → 10

---

### 4. 验证架构师 (VerificationArchitect)

| 属性 | 值 |
|------|-----|
| **Role** | `verification_architect` |
| **Phase** | `UVM`（第 9 阶段） |
| **LLM 模型** | `deepseek-coder` (task_type: `code_generation`) |
| **Consumes** | `spec` |
| **Produces** | `env` — UVM 环境结构、agent 列表、filelist、top_module |
| **质量检查** | 静态检查 + 编译检查 + 闭环仿真（3 项 PASS 才满分） |

**9 个工具：**
| 工具 | 功能 |
|------|------|
| `find_spec_yaml` | 从 spec 提取模块名，生成 agent/env/bench YAML |
| `jinja_render` | Jinja2 确定性渲染 → UVM SystemVerilog 骨架（51 个文件） |
| `quality_report` | 三项质量评分（静态 25 + 编译 25 + 闭环 25 = 75 分） |
| `check_static` | 验证所有预期 UVM 文件是否存在（每 agent 13 个 .sv） |
| `check_compile` | QuestaSim vlog 编译检查 |
| `check_loopback` | Agent 闭环自测（driver → monitor 闭环仿真） |
| `check_health` | 环境顶层模块编译检查 |
| `read_file` | 读取生成的 SV 文件 |
| `write_file` | 写入/修复 SV 文件 |

**输出：** 每个 agent 13 个 .sv + 4 个 loopback .sv + env 8 个 .sv + bench 1 个 .sv = 约 51 个 SystemVerilog 文件

---

### 5. 测试工程师 (TestEngineer)

| 属性 | 值 |
|------|-----|
| **Role** | `test_engineer` |
| **Phase** | `test`（第 10 阶段） |
| **LLM 模型** | `deepseek-coder` (task_type: `code_generation`) |
| **Consumes** | `spec`, `env` |
| **Produces** | `tests` — 测试用例列表、YAML 配置、覆盖率映射 |
| **最低分** | 无 |
| **最大重试** | 2 |

**6 个工具：**
| 工具 | 功能 |
|------|------|
| `parse_test_points` | 解析 spec 中的测试点 |
| `map_policies_to_tests` | 约束策略 → 测试场景映射 |
| `build_scenario_yaml` | 生成场景 YAML |
| `build_priority_rules` | 优先级规则（P0/P1/P2） |
| `generate_test_cases` | 生成 SV 测试用例代码 |
| `check_test_coverage` | 测试覆盖率检查 |

**评分规则：** `min(60 + 测试数×5, 95)`

---

### 6. 断言工程师 (AssertionEngineer)

| 属性 | 值 |
|------|-----|
| **Role** | `assertion_engineer` |
| **Phase** | `assert`（第 11 阶段） |
| **LLM 模型** | `deepseek-coder` (task_type: `assertion_generation`) |
| **Consumes** | 无（直接从 spec 文本工作） |
| **Produces** | 断言 .sv 文件（SVA / 立即断言 / 并发断言 / 形式属性） |
| **最低分** | 无 |
| **最大重试** | 2（`@retry` 装饰器） |

**能力：**
- 生成 SVA 断言（`generate_sva_assertions`）
- 生成立即断言（`generate_immediate_assertions`）
- 生成并发断言（`generate_concurrent_assertions`）
- 生成形式验证属性（`generate_formal_properties`）
- 协议断言生成（`generate_protocol_assertions`）

---

### 7. 回归管理器 (RegressionManager)

| 属性 | 值 |
|------|-----|
| **Role** | `regression_manager` |
| **Phase** | `regress`（第 12 阶段） |
| **LLM 模型** | `deepseek-chat` (task_type: `regression_management`) |
| **Consumes** | `env`, `tests` |
| **Produces** | `regression` — 编译状态、仿真结果（pass/fail）、覆盖率数据 |
| **最低分** | 无 |
| **最大重试** | 2 |

**3 个工具：**
| 工具 | 功能 |
|------|------|
| `compile_env` | 编译 UVM 环境（Questasim vlog） |
| `run_simulation` | 运行仿真（Questasim vsim），逐测试收集结果 |
| `generate_regression_report` | 生成 `report.json` + `report.html` |

**评分规则：** `min(int(80×passed/max(total,1)) + 10, 95)`；无数据 → 10

---

### 8. 覆盖率管理器 (CoverageManager)

| 属性 | 值 |
|------|-----|
| **Role** | `coverage_manager` |
| **Phase** | `cover`（第 13 阶段） |
| **LLM 模型** | `deepseek-chat` (task_type: `coverage_analysis`) |
| **Consumes** | `spec`, `regression` |
| **Produces** | `coverage` — 代码覆盖率 + 功能覆盖率 + gap 分析 |
| **目标** | 代码覆盖率 ≥95%，功能覆盖率 ≥100%，断言覆盖率 ≥100% |

**4 个工具：**
| 工具 | 功能 |
|------|------|
| `collect_coverage` | 收集覆盖率数据 |
| `analyze_coverage_gaps` | 覆盖率 gap 分析 |
| `generate_coverage_report` | 生成覆盖率报告 |
| `suggest_coverage_tests` | 建议补充测试 |

---

### 9. 调试工程师 (DebugEngineer)

| 属性 | 值 |
|------|-----|
| **Role** | `debug_engineer` |
| **Phase** | `debug`（第 14 阶段） |
| **LLM 模型** | `deepseek-chat` (task_type: `debug_analysis`) |
| **Consumes** | `regression`, `tests`, `env` |
| **Produces** | `debug` — 错误分类、根因分析、修复建议、路由修复目标 |
| **最低分** | 30 |
| **最大重试** | 2 |

**能力：**
- 错误分类（UVM_ERROR / 编译错误 / Scoreboard mismatch / 超时 / 断言失败）
- 根因定位（设计 bug vs 验证环境 bug vs 测试用例问题）
- 修复路由：指出应由哪个 Agent 修复（fix_agent_role）
- 触发流水线反馈闭环：重跑 fix_agent → test → regress → cover → debug

---

### 10. 质量保证 (QualityAssurance)

| 属性 | 值 |
|------|-----|
| **Role** | `quality_assurance` |
| **Phase** | `qa`（第 15 阶段） |
| **LLM 模型** | `deepseek-chat` (task_type: `quality_review`) |
| **Consumes** | `regression`, `coverage` |
| **Produces** | `quality` — 整体质量评估、verdict（READY / NEEDS_FIX / FAILED） |
| **最低分** | 无 |
| **最大重试** | 2 |

**能力：**
- 评估回归通过率
- 评估覆盖率达标情况
- 综合判断：READY（可以签核）/ NEEDS_FIX（需要修复）/ FAILED（不通过）
- 无外部工具，纯 LLM 分析

**评分规则：** `min(int(overall_score × 0.95), 95)`；无数据 → 10

---

### 11. 报告生成器 (ReportGenerator)

| 属性 | 值 |
|------|-----|
| **Role** | `report_generator` |
| **Phase** | `report`（第 16 阶段） |
| **LLM 模型** | `deepseek-chat` (task_type: `report_generation`) |
| **Consumes** | 无（从完整 ctx 上下文工作） |
| **Produces** | `report` — 最终验证报告 + 签核文档 |
| **最低分** | 无 |
| **最大重试** | 2 |

**2 个工具：**
| 工具 | 功能 |
|------|------|
| `generate_reports` | 生成签核报告（Markdown + HTML） |
| `query_trend_history` | 查询历史趋势数据 |

**评分规则：** 能解析 → 85；否则 → 10

---

## 上下文数据流

```
spec.md
  │
  ▼
[spec] ──→ ctx["spec"]          {design_name, features, interfaces, registers, test_points, coverage_goals}
  │
  ▼
[design] ──→ ctx["design_arch"] {function_hier, rtl_hier, registers, signoff_checklist}
  │
  ▼
[model] ──→ ctx["model"]        {ref_model, test_vectors, operations}
  │
  ▼
[UVM] ──→ ctx["env"]            {env_name, agents[], filelist, top_module, quality}
  │
  ▼
[test] ──→ ctx["tests"]         {test_names[], test_count, test_cases[]}
  │
  ├──────────────┐
  ▼              ▼
[assert]    [regress] ──→ ctx["regression"]  {compile, passed, failed, total, tests[]}
               │
               ▼
           [cover] ──→ ctx["coverage"]   {line_pct, branch_pct, toggle_pct, gaps[]}
               │
               ▼
           [debug] ──→ ctx["debug"]      {category, errors[], fix_agent, suggestion}
               │
               ▼              反馈闭环: 重跑 fix_agent → test → regress → cover → debug
               │
               ▼
             [qa] ──→ quality report      {verdict: READY|NEEDS_FIX|FAILED}
               │
               ▼
           [report] ──→ 签核报告
```

## Agent 依赖 DAG

```
spec_and_test_planner
    ├──→ design_architect
    │       └──→ model_agent
    ├──→ verification_architect
    │       └──→ test_engineer
    │               ├──→ assertion_engineer
    │               └──→ regression_manager
    │                       ├──→ coverage_manager
    │                       └──→ debug_engineer
    ├──→ coverage_manager
    └──→ quality_assurance
            └──→ report_generator
```
