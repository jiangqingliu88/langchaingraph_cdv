# 9 个 Agent 的目录、对话与产物

> 目录名 = GUI 模式 id。每个目录都有 `chat.py`；独立专家另有 `main.py` /
> `graph.py`。目录唯一，不保留别名副本（旧路径已删除）。

## 1. 目录

```text
src/agent_plane/specialists/
├── common.py                 # LLM JSON 校验/重试 + 原子落盘（独立专家共用）
├── chat_common.py            # 9 个 agent 共用的对话 turn
│
├── agentic_chat/             # 通用 Harness 对话（不是专家子图）
├── mental_model/             # 心智模型 IR（独立专家）
├── formal/                   # Formal IR（独立专家）
├── uvm/                      # UVM 专家（原 verify 子图实现）
├── rtl_designer/             # RTL/模型（闭环 design 子图）
├── unit_testing/             # 纯 SV 单测（独立专家）
├── functional_coverage/      # 覆盖率（闭环 coverage 子图）
├── debug/                    # 调试（闭环 debug 子图）
├── workflows/                # 端到端流程（对话入口，执行走 verify router）
```

## 2. 每个 agent 都有对话入口

```bash
vagent agents list                      # 9 个 agent + 目录 + 命令
vagent agents chat uvm "分析这份 testplan"
vagent uvm chat "分析这份 testplan"     # 每个 agent 的专属命令
```

`specialists/<agent>/chat.py` 只声明 `AGENT_ID`，统一走
`chat_common.chat()` → `workbench.modes.interaction.turn()`：
交互方式（chat / plan / verify）与 role_prompt 都来自
`workbench/modes/agent_modes.py`，CLI/GUI 共用同一份配置。

## 3. 三类 agent

| 类型 | 目录 | 驱动方式 |
|---|---|---|
| 闭环专家 | `rtl_designer` / `uvm` / `debug` / `functional_coverage` | `orchestration_plane/supervisor` 主图按阶段调度 |
| 独立专家 | `mental_model` / `formal` / `unit_testing` | `vagent <cmd>` 或 GUI 模式动作按钮 |
| 入口型 | `agentic_chat` / `workflows` | 通用 Harness / verify router（不新增执行链） |

## 4. 三个独立专家

共用 `specialists/common.py`：`generate_json_object()`（校验/重试）、
`write_json_artifact()`（JSON+YAML+manifest 原子写）、`SpecialistError`。

| 专家 | 输入 | 产物 | 如实边界 |
|---|---|---|---|
| `mental_model` | spec 文本 | `<run>/mental_ir/{mental_ir.json,yaml,manifest.json}` | 候选理解，必须人审 |
| `formal` | spec 文本 | `<run>/formal/{formal_plan.json,yaml,manifest.json}` | 只生成性质/假设/证明义务；`engine.ran=false` |
| `unit_testing` | RTL 文件 | `<run>/unit_test/{<dut>_tb.sv, report.json, rtl/}` | 只有 compile+run 都通过才是 PASS；无 EDA 是 GENERATED_ONLY |

```bash
vagent mental build <spec.md> -o <run>        # 或 vagent mental-model ...
vagent formal build <spec.md> -o <run>
vagent unit-test build <dut.sv> -o <run>      # 或 vagent unit-testing ...
```

## 5. GUI 模式 → 目录

| GUI 模式 | 目录 | 动作 |
|---|---|---|
| Agentic Chat | `agentic_chat` | 对话 |
| Mental Model | `mental_model` | 生成 Mental IR |
| Formal | `formal` | 生成 Formal 计划 |
| UVM | `uvm` | 对话/计划（UVM 子图） |
| RTL Designer | `rtl_designer` | 对话/计划 |
| Unit Testing | `unit_testing` | 生成/运行单测 |
| Functional Coverage | `functional_coverage` | 对话/计划 |
| Debug | `debug` | 对话/计划 |
| Workflows | `workflows` | 打开验证流程（supervisor） |

## 6. 边界

- 独立专家只生成/检查自己的产物，不驱动闭环；
- 要进 supervisor 必须另做路由与阶段接线，不能靠"多一个目录"冒充接入；
- Formal 未接形式引擎时 `engine.ran=false`；Unit Testing 无 EDA 时
  `GENERATED_ONLY`；两者都不是"通过"。
