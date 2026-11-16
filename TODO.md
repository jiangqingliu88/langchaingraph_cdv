# TODO / 技术债

本文件是**代码仓库的待办入口**，不是环境变量速查表，也不保存任何凭据。

完整的架构分析、风险清单、VPlan 闭环验收项见
[`PROJECT_STATUS.md`](PROJECT_STATUS.md)；契约流程见
[`CONTRACT_FLOW.md`](CONTRACT_FLOW.md)。

## 当前优先级

- [x] **P0** 测试/守卫全绿：boards 注册表、architecture budget、VPlan bootstrap 计数、
      staged regression 时间戳测试、CLI evidence 文案测试。
- [x] **P0** 安全：当前树 secret scan clean；`scripts/check_secrets.py` 已接入 CI/pre-commit。
      历史凭据的轮换/清史仍需维护者执行。
- [x] **P1** VPlan review 粒度拆分：reviewed source 与 generated sidecar 分开，
      生成 sidecar 变化不再使审阅失效（review v2）。
- [x] **P1** VPlan gate：按 `linked_at` 选最新 run；增加 `active_drift` /
      `active_unsupported` 漂移报告。
- [x] **P1** TP realization：VPlan 表支持 `stimulus_field` / `realization_kind` /
      `realization_agent` / `realization_sequence`。
- [x] **P1** `uvm_arch` 映射：scoreboard 优先按 `check_artifact` / `object` 绑定，
      无声明时才回退；`scan-assets --check` 增加 `vc/` 与文件名→子目录布局校验。
- [x] **P1** 契约矩阵 schema：13 列 + status 枚举 + 原子写。
- [ ] **P2** `sv/` 单布局，legacy 退场；工作台/主套件性能优化。
- [ ] **P2** 真实 Questa 环境上的 VPlan E2E：
      `bootstrap → review → build → execute → link → gate → evidence verify`。

## 明确不在本仓库处理

- `isa_ir_tools` / TB player 的集成与测试（独立工具，见其目录 readme）。
- 需要 QuestaSim 的 EDA 端到端验证（在装有 EDA 的机器上执行）。
 ◼ 搭 standalone 专家公共骨架
  ◻ 新增 formal 专家 + Formal IR
  ◻ 新增 unit_test 专家（纯 SV TB + 编译/运行）
  ◻ 模式→专家 1:1 + GUI 动作按钮泛化 + AgentCard
  ◻ 文档与架构说明
对应表（已写入 src/workbench/modes/agent_modes.py）

  ┌──────────────┬────────────────────────────────────────┬────────────────────┬────────┐
  │   GUI 模式   │                 对应                   │       stages       │  交互  │
  │              │ agent（src/agent_plane/specialists/）  │                    │        │
  ├──────────────┼────────────────────────────────────────┼────────────────────┼────────┤
  │ Mental Model │ mental                                 │ -                  │ chat   │
  ├──────────────┼────────────────────────────────────────┼────────────────────┼────────┤
  │ UVM          │ verify                                 │ verify             │ plan   │
  ├──────────────┼────────────────────────────────────────┼────────────────────┼────────┤
  │ RTL Designer │ design                                 │ front/design/model │ plan   │
  ├──────────────┼────────────────────────────────────────┼────────────────────┼────────┤
  │ Functional   │ coverage                               │ coverage           │ plan   │
  │ Coverage     │                                        │                    │        │
  ├──────────────┼────────────────────────────────────────┼────────────────────┼────────┤
  │ Debug        │ debug                                  │ ops/debug          │ plan   │
  ├──────────────┼────────────────────────────────────────┼────────────────────┼────────┤
  │ Formal       │ verify（没有 formal 专家）             │ verify             │ plan   │
  ├──────────────┼────────────────────────────────────────┼────────────────────┼────────┤
  │ Unit Testing │ verify（没有 unit_test 专家）          │ verify             │ plan   │
  │  Agent       │                                        │                    │        │
  ├──────────────┼────────────────────────────────────────┼────────────────────┼────────┤
  │ Workflows    │ supervisor（编排主图，不是单一专家）   │ 全阶段             │ verify │
  ├──────────────┼────────────────────────────────────────┼────────────────────┼────────┤
  │ Agentic Chat │ harness（通用对话，不是专家）          │ -                  │ chat
