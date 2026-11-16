# 独立专家（specialists）已退休 —— 迁移映射

> **`src/agent_plane/specialists/` 已删除。** 本页不再描述一个现存目录，
> 只保留迁移后的落点，便于旧 import / 文档 / 书签对照。
> 当前 Agent 分组与 SDK ReAct 入口见
> [Agent Domain 与 ReAct 布局](AGENT_DOMAIN_LAYOUT.md)。

## 1. 为什么不是“直接删”

原 `specialists/` 不是兼容壳：它同时承载了 supervisor 的四个专家子图、
独立专家的生成器、CLI/GUI 的执行入口和九个对话入口。直接删会打断
`supervisor` 闭环与 `vagent formal/mental/unit-test/repair`。本次先搬迁活代码，
再删除目录。

## 2. 迁移映射

| 原路径（`src/agent_plane/specialists/`） | 新路径 | 内容 |
|---|---|---|
| `common.py` | `src/agent_plane/common.py` | 独立专家共用 LLM 校验/重试/原子落盘 |
| `chat_common.py` | `src/workbench/modes/chats/common.py` | 九类对话的公共入口 |
| `<agent>/chat.py` | `src/workbench/modes/chats/<agent>.py` | `agentic_chat / mental_model / formal / uvm / rtl_designer / unit_testing / functional_coverage / debug / workflows` |
| `formal/main.py`、`formal/graph.py` | `verification/formal_agent/` | FormalPlan 生成器 + 独立子图 |
| `mental_model/main.py`、`mental_model/graph.py` | `design_understanding/mental_model_agent/` | Mental IR 生成器 + 独立子图 |
| `unit_testing/main.py`、`unit_testing/graph.py` | `design_verification/simulation_agent/` | 纯 SV testbench 生成/编译/运行 |
| `rtl_designer/tools.py` | `design_generation/rtl_upgrade_agent/design_tools.py`（公共入口仍是 `tools.py`） | 窄沙箱设计工具 |
| `rtl_designer/loop.py`、`graph.py` | `design_generation/rtl_upgrade_agent/` | Design 子图 + opt-in 工具循环 |
| `uvm/loop.py`、`graph.py` | `verification/uvm_coding_agent/` | Verify 子图 + opt-in 工具循环 |
| `functional_coverage/tools.py`、`loop.py`、`graph.py` | `verification/functional_coverage_agent/` | 只读覆盖率工具 + Coverage 子图 |
| `debug/main.py`、`graph.py`、`loop.py`、`repair_policy.py` | `verification/dv_debug_agent/` | DebugExecutor + Debug 子图 + 受控修复 |
| `debug/test_debug_waveform.py` | `tests/test_debug_waveform.py` | 随测试目录走 |

## 3. 调用方更新

- `orchestration_plane/supervisor/graph.py` 的四个专家子图改用新 Domain 路径；
- `execution_helpers.py` 的 `debug` 执行器映射改为
  `src.agent_plane.verification.dv_debug_agent:DebugExecutor`；
- CLI `cmd_formal / cmd_mental / cmd_unit_test / cmd_repair` 与
  `VerificationCLI` 改到新路径；
- GUI `modules/interaction` 与 `modes/agent_chat.py` 改用
  `workbench/modes/chats/`；
- `tests/` 中所有旧 import 同步更新。

## 4. 边界未变

- 生成器产物仍是**候选**：FormalPlan / Mental IR / testbench 存在不等于
  proof、理解或仿真通过。
- `NOT_RUN` / `INCOMPLETE` / `VALIDATED` / `PASS` 不混用。
- 原目录已删除；若发现遗漏引用，直接改到上表的新路径，不要恢复
  `specialists/` 兼容层。
