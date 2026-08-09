---
document_id: VPLAN-DOC-006
title: "验证计划书"
project: "ALU IP"
version: 1.0
date: 2026-08-09
author: SignOffAI
status: Review
---

# 验证计划书

| 项目 | 内容 |
|------|------|
| **文档ID** | `VPLAN-DOC-006` |
| **版本** | 1.0 |
| **日期** | 2026-08-09 |
| **作者** | SignOffAI |
| **状态** | Review |
| **项目** | ALU IP — 32bit 算术逻辑单元 |

---

## 修订历史

| 版本 | 日期 | 作者 | 变更说明 |
|------|------|------|----------|
| 1.0 | 2026-08-09 | SignOffAI | 初始版本，由 SignOffAI 管道自动生成 |

---


## 1. 验证目标

本验证计划针对 **apb_uart** 模块，覆盖以下验证目标：

| 目标编号 | 验证目标 | 优先级 | 验收标准 |
|----------|----------|--------|----------|
| VGOAL-001 | 功能正确性 | P0 | 所有功能特性通过 directed + random 测试 |
| VGOAL-002 | 接口协议合规 | P0 | 所有接口协议检查通过，无 protocol violation |
| VGOAL-003 | 寄存器访问 | P0 | 所有寄存器读写回环测试通过 |
| VGOAL-004 | 代码覆盖率 | P1 | Line≥95%, Branch≥90% |
| VGOAL-005 | 功能覆盖率 | P1 | 所有 covergroup 覆盖点达到 100% |
| VGOAL-006 | 跨时钟域 | P1 | CDC 检查通过 |
| VGOAL-007 | 性能验证 | P2 | 时序满足 apb_uart 规格要求 |

## 2. 验证策略

### 2.1 验证层次

| 层次 | 范围 | 方法 | 工具 |
|------|------|------|------|
| **Agent 闭环** | 单个接口 Agent | Driver→Monitor 自发自收 | QuestaSim + UVM
| **模块级** | 单个模块 | 约束随机 + 定向测试 | QuestaSim + UVM
| **子系统级** | 多模块集成 | Scoreboard + Reference Model | QuestaSim + UVM

### 2.2 验证方法学

- **方法学**: UVM (Universal Verification Methodology)
- **激励生成**: 约束随机 (constrained-random) + 定向 (directed)
- **结果检查**: Scoreboard 自动比对 + Reference Model 预测
- **覆盖率驱动**: Covergroup + Coverpoint + Cross Coverage

## 3. 验证环境架构

```
                        ┌──────────────┐
                        │  Virtual     │
                        │  Sequencer   │
                        └──────┬───────┘
                               │
          ┌────────────────────┼────────────────────┐
          │                    │                    │
    ┌─────▼─────┐       ┌─────▼─────┐       ┌─────▼─────┐
    │ Agent In  │       │   DUT     │       │ Agent Out │
    │ ┌───────┐ │       │           │       │ ┌───────┐ │
    │ │Driver │─┼──────►│   ALU IP  ├───────►│ │Monitor│ │
    │ │Monitor│◄┼───────┤           │◄───────┤ │Driver │ │
    │ └───────┘ │       │           │       │ └───────┘ │
    └─────┬─────┘       └───────────┘       └─────┬─────┘
          │                                       │
    ┌─────▼───────────────────────────────────────▼─────┐
    │                  Scoreboard                       │
    │         (Expected vs Actual + Ref Model)          │
    └──────────────────────────────────────────────────┘
```

## 4. 验证资源与排期

| 阶段 | 任务 | 预计工时 | 依赖 |
|------|------|----------|------|
| Phase 1 | Agent 开发与闭环调试 | 3天 | Spec 冻结 |
| Phase 2 | 环境集成与编译 | 2天 | Agent 闭环 PASS |
| Phase 3 | 定向测试开发 | 3天 | 环境编译 PASS |
| Phase 4 | 随机测试与回归 | 5天 | 定向测试 PASS |
| Phase 5 | 覆盖率收敛 | 3天 | 回归环境就绪 |
| Phase 6 | 签核与报告 | 1天 | 覆盖率达标 |
| **总计** | | **17天** | |

## 5. 风险与缓解

| 风险编号 | 风险描述 | 影响 | 缓解措施 |
|----------|----------|------|----------|
| RSK-001 | Spec 变更导致环境返工 | 高 | 模块化 Agent 设计，接口参数化 |
| RSK-002 | 覆盖率收敛慢 | 中 | 自动覆盖率驱动的测试生成 |
| RSK-003 | 仿真时间过长 | 中 | 并行回归 + LSF 调度 |
| RSK-004 | 参考模型与 RTL 不一致 | 低 | Spec 双重审查 + 交叉验证 |



---

*文档ID: VPLAN-DOC-006 | 自动生成于 2026-08-09 08:16:36 | SignOffAI Pipeline Documentation System*
