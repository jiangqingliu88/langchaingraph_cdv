# Spec → RTL → Coverage → Signoff 端到端流程

## 总览

```
                         ┌─────────────────────────────────────────────┐
                         │              文档库 (specs/*.md)              │
                         │  uart_chip_spec / uart_tx_spec / ...         │
                         └──────────────┬──────────────────────────────┘
                                        │
                                        ▼
┌───────────────────────────────────────────────────────────────────────────┐
│                        需求管理 (Chip → ST → IT → BT)                       │
│                                                                           │
│  CHIP  芯片级: UART+AXI 完整验证                                           │
│  ├─ ST   系统级: UART↔AXI 交互 / 中断联动 / 功耗                           │
│  │  ├─ IT  集成级: TX+DMA / RX+DMA / 多通道仲裁                            │
│  │  │  ├─ BT  模块级: TX模块 / RX模块 / 波特率 / FIFO / 帧格式              │
│  │  │  │  ├─ UT  单元级: (隐式 — 由 design_arch 拆解)                      │
└──────────┬────────────────────────────────────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────────────────────────────┐
│                     ① Spec Analyzer (spec_planner)                    │
│  输入: spec_uart.txt                                                  │
│  输出: ctx.spec { test_points, features, architecture }               │
├──────────────────────────────────────────────────────────────────────┤
│                     ② UVM Architect (verification_architect)          │
│  输入: ctx.spec                                                        │
│  输出: ctx.env { env_name, filelist, agents, SV代码 }                 │
├──────────────────────────────────────────────────────────────────────┤
│                     ③ Sequence Engineer (sequence_engineer)           │
│  输入: ctx.spec                                                        │
│  输出: ctx.policies { sequences, constraints }                        │
├──────────────────────────────────────────────────────────────────────┤
│                     ④ TestCase Engineer (testcase_engineer)            │
│  输入: ctx.spec + ctx.env + ctx.policies                               │
│  输出: ctx.tests { scenarios, SV test files, run.sh }                 │
├──────────────────────────────────────────────────────────────────────┤
│                     ⑤ Design Architect (design_architect)  ★新增      │
│  输入: 模块级 Spec (BT)                                                │
│  输出: ctx.design_arch {                                               │
│      function_hier    ── 模块→子模块→leaf function (带端口声明)         │
│      registers        ── 寄存器 map (offset/bit fields/access/reset)  │
│      rtl_hier         ── RTL 例化层次 (module→submodule inst)         │
│      signoff_checklist── 签核检查清单                                  │
│  }                                                                     │
├──────────────────────────────────────────────────────────────────────┤
│                     ⑥ Assertion Engineer (assertion_engineer)         │
│  输入: 上游输出 (text chain)                                            │
│  输出: SVA 断言代码                                                     │
├──────────────────────────────────────────────────────────────────────┤
│                     ⑦ Regression Manager (regression_manager)        │
│  输入: ctx.env + ctx.tests                                              │
│  输出: ctx.regression { compile_status, pass/fail counts }             │
├──────────────────────────────────────────────────────────────────────┤
│                     ⑧ Coverage Manager (coverage_manager)             │
│  输入: ctx.spec + ctx.regression                                        │
│  输出: ctx.coverage { code_cov, functional_cov, gaps, suggestions }   │
├──────────────────────────────────────────────────────────────────────┤
│                     ⑨ Debug Engineer (debug_engineer)                 │
│  输入: 上游输出                                                         │
│  输出: 错误定位 + 修复建议                                               │
├──────────────────────────────────────────────────────────────────────┤
│                     ⑩ Quality Assurance (quality_assurance)           │
│  输入: 上游输出                                                         │
│  输出: 质量评分 + 审查报告                                               │
├──────────────────────────────────────────────────────────────────────┤
│                     ⑪ Report Generator (report_generator)             │
│  输入: 上游输出                                                         │
│  输出: 最终验证报告                                                     │
└──────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌──────────────────────────────────────────────────────────────────────┐
│                          签核报告 (Signoff)                            │
│                                                                      │
│  自动收集: 需求数 / 覆盖率 / 回归通过率 / 空洞数                       │
│  流程: draft → pending → approved / rejected                         │
└──────────────────────────────────────────────────────────────────────┘
```

## 11 个 Agent 数据契约

```
Agent                    consumes                produces         说明
─────────────────────────────────────────────────────────────────────────────
① spec_planner           []                      spec             规格→测试计划
② verification_architect ["spec"]                env              UVM 环境代码生成
③ sequence_engineer      ["spec"]                policies         序列/约束生成
④ testcase_engineer      ["spec","env","policies"] tests           测试用例自动生成
⑤ design_architect       ["spec"]                design_arch      ★ 模块架构(function+reg+RTL)
⑥ assertion_engineer     []                      (text)           SVA 断言
⑦ regression_manager     ["env","tests"]          regression       编译+仿真+结果
⑧ coverage_manager       ["spec","regression"]    coverage         覆盖率+空洞分析
⑨ debug_engineer         []                      (text)           错误定位
⑩ quality_assurance      []                      (text)           质量审查
⑪ report_generator       []                      (text)           最终报告
```

## Design Architect 内部流程 (⑤ 细节)

```
Module Spec (BT)
      │
      ▼
┌─────────────────┐
│ 提取模块名        │  uart / spi / i2c ...
└────────┬────────┘
         │
         ▼
┌─────────────────┐     ┌──────────────────────────────────────┐
│ function_hier   │────▶│ module UART_TOP (                     │
│ (功能层级)       │     │   input  logic         clk,          │
│                 │     │   input  logic         rst_n,        │
│ UART_TOP        │     │   output logic         tx,           │
│ ├─ UART_TX_PATH │     │   ...                                │
│ │  ├─ tx_fifo   │     │ );                                   │
│ │  ├─ tx_shift  │     │   // sub-module declarations          │
│ │  └─ tx_fsm    │     │   module UART_TX_PATH (...);          │
│ ├─ UART_RX_PATH │     │     module tx_fifo_16x8 (...);        │
│ ├─ UART_BAUD    │     │                                       │
│ ├─ UART_REG_FILE│     └──────────────────────────────────────┘
│ └─ UART_INTR    │
└────────┬────────┘
         │
         ▼
┌─────────────────┐     ┌──────────────────────────────────────┐
│ registers       │────▶│ UART_CTRL   0x00  8b  RW  8'h00      │
│ (寄存器 map)     │     │   [0]    TX_EN       RW  1'b0        │
│                 │     │   [1]    RX_EN       RW  1'b0        │
│ 7 个寄存器       │     │   [2]    PARITY_EN   RW  1'b0        │
│ 30+ bit fields  │     │ UART_STATUS 0x04  8b  RO  8'h01      │
│                 │     │ UART_BAUD   0x08 16b  RW 16'd326     │
│                 │     │ ...                                  │
└────────┬────────┘     └──────────────────────────────────────┘
         │
         ▼
┌─────────────────┐     ┌──────────────────────────────────────┐
│ rtl_hier        │────▶│ module uart_top (...);                │
│ (RTL 例化)       │     │   UART_TOP u_uart_top (              │
│                 │     │     .clk   (clk),                     │
│ 顶层模块框架     │     │     .tx    (tx),                      │
│ + 内部 wire      │     │     ...                              │
│ + 子模块例化     │     │   );                                  │
│ + 接口信号       │     │     UART_TX_PATH u_uart_tx_path (.); │
└────────┬────────┘     └──────────────────────────────────────┘
         │
         ▼
┌─────────────────┐
│ signoff_checklist│ 36+ 条:
│ (签核清单)       │   [function] verify tx_fifo_16x8
│                 │   [register] verify UART_CTRL reset == 8'h00
│                 │   [cdc]      PCLK → baud_clk synchronizer
│                 │   [reset]    assert rst_n ≥ 100ns
│                 │   [interface]APB protocol check
│                 │   [formal]   tx_fsm never deadlocks
└─────────────────┘
```

## 端到端数据流

```
spec_uart.txt
    │
    ▼
┌──────────────────────────────────────────────────────────────┐
│              共享上下文 ctx (SharedContext)                    │
│                                                              │
│  ctx.spec       ← ① spec_planner        {test_points, ...}  │
│  ctx.env        ← ② architect           {env_name, filelist} │
│  ctx.policies   ← ③ sequence_engineer    {sequences}         │
│  ctx.tests      ← ④ testcase_engineer    {scenarios, files}  │
│  ctx.design_arch← ⑤ design_architect    {func_hier, regs}  ★│
│  ctx.regression ← ⑦ regression_manager   {compile, pass/fail}│
│  ctx.coverage   ← ⑧ coverage_manager     {cov_data, gaps}    │
└──────────────────────────────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────────────────────┐
│              最终产物                                          │
│                                                              │
│  generated/uart/agents/    ── UVM 组件代码                    │
│  generated/uart/env/       ── UVM 环境                       │
│  output/testcases/         ── 测试用例 + run.sh              │
│  output/design_arch/       ── 设计架构代码          ★        │
│  build/uart/work/          ── QuestaSim 编译产物              │
│  signoff report            ── 签核报告 (需求+覆盖+回归)      │
└──────────────────────────────────────────────────────────────┘
```

## 前端页面 ↔ Agent 映射

```
📁 文档库      → specs/*.md
📋 需求管理    → spec_planner (层级需求追踪 Chip→ST→IT→BT)
🏗 设计架构 ★  → design_architect (function+registers+RTL hier)
⚡ 流水线      → 全 11 Agent pipeline
🧪 测试用例    → testcase_engineer
📈 覆盖率      → coverage_manager
🔄 回归管理    → regression_manager
✅ 签核报告    → signoff (自动收集 stats)
📚 知识库      → knowledge entries
```
