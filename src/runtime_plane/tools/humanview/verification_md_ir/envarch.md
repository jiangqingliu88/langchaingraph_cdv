# {{ module }} UVM 验证环境框架说明

> **参考框架**：{{ reference_framework }}
> **整体结构图**：`{{ env_diagram }}`
> **Scoreboard 数据流图**：`{{ scoreboard_diagram }}`
> **代码搭建计划**：[uvm_buildplan.md](uvm_buildplan.md)

---

## 1. 总览

{{ env_overview }}

```text
╔══════════════════════════════════════════════════════════════════════╗
║  Test Layer  ({{ test_base }} / {{ test_count }} 类 test)             ║
║  ┌──────────────────────────────────────────────────────────────┐    ║
║  │  {{ tb_top }}                                                │    ║
║  │  ┌──────────────────────────────────────────────────────┐    │    ║
║  │  │  {{ env_name }}                                      │    │    ║
║  │  │  ┌─────────────┐   ┌─────────────┐   ┌───────────┐  │    │    ║
║  │  │  │ Active      │   │  DUT        │   │ Responder │  │    │    ║
║  │  │  │ Agents      │──►│  {{ dut }}  │──►│ Agents    │  │    │    ║
║  │  │  └──────┬──────┘   └──────┬──────┘   └─────┬─────┘  │    │    ║
║  │  │         │                 │                 │        │    │    ║
║  │  │         └────────────┬────┴─────────────────┘        │    │    ║
║  │  │                      ▼                               │    │    ║
║  │  │  ┌──────────────────────────────────────────────┐    │    │    ║
║  │  │  │ Scoreboard / Reference Model (Pred)          │    │    │    ║
║  │  │  │  expected ← pred / actual ← monitor          │    │    │    ║
║  │  │  └──────────────────────────────────────────────┘    │    │    ║
║  │  │  Virtual Sequencer / vseq_lib                        │    │    ║
║  │  └──────────────────────────────────────────────────────┘    │    ║
║  └──────────────────────────────────────────────────────────────┘    ║
╚══════════════════════════════════════════════════════════════════════╝
```

---

## 2. 各区域详细说明

### 2.1 Test 层

- 基类：`{{ test_base }}`
- 测试目录：`{{ test_dirs }}`
- 调度：`+UVM_TESTNAME` + `+plusarg`（`{{ plusargs }}`）

### 2.2 `{{ tb_top }}`（仿真顶层）

- 时钟 / 复位：`{{ clock }}` / `{{ reset }}`
- 例化：DUT、env、interface、SVA bind
- `config_db` 设置：vif、env cfg、reference model cfg

### 2.3 `{{ env_name }}`（环境容器）

| 成员 | 类型 | 作用 |
|---|---|---|
| {{ member.name }} | `{{ member.type }}` | {{ member.role }} |

### 2.4 Active Agents（激励驱动端）

| Agent | Interface | Seq Item | 驱动方向 | 说明 |
|---|---|---|---|---|
| {{ agent.name }} | `{{ agent.iface }}` | `{{ agent.seq_item }}` | {{ agent.direction }} | {{ agent.description }} |

### 2.5 Responder Agents（响应 / 配置端）

| Agent | Interface | Seq Item | 响应方向 | 说明 |
|---|---|---|---|---|
| {{ agent.name }} | `{{ agent.iface }}` | `{{ agent.seq_item }}` | {{ agent.direction }} | {{ agent.description }} |

### 2.6 中央：DUT

- 模块：`{{ dut }}`
- 关键端口组：{{ dut_port_groups }}
- 端口 → Agent 映射：见 `uvm_buildplan.md` 第 2 章

### 2.7 SVA

| SVA 文件 | 绑定对象 | 断言类 | 说明 |
|---|---|---|---|
| `{{ sva_file }}` | `{{ sva_bind_target }}` | {{ sva_class }} | {{ sva_description }} |

### 2.8 Scoreboard / Reference Model 层

| 组件 | 输入 | 输出 | 说明 |
|---|---|---|---|
| **Pred** | `{{ in_seq_item }}`（in monitor） | `{{ out_seq_item }}`（expected） | 参考模型；**不读 DUT 内部信号** |
| **Scoreboard** | expected（pred）+ actual（out monitor） | pass / fail | 事务级比对 |
| DUT Checker | DUT 信号（逐拍） | `matched/mismatched` | **逐拍规则检查，不是事务 scoreboard** |

**接线（必须）**

```text
{{ in_agent }}_agent_ap    → {{ module }}_pred.in_export
{{ module }}_pred.out_port → {{ module }}_scb.expected_export
{{ out_agent }}_agent_ap   → {{ module }}_scb.actual_export
```

> 没有真实 pred / reference model 时**不生成 env**，避免 expected 恒 0 的假 scoreboard。

---

## 3. 完整数据流路径

### 3.1 正常翻译 / 事务流

{{ normal_flow }}

### 3.2 无效化 / 控制流

{{ control_flow }}

### 3.3 错误注入流

{{ error_flow }}

### 3.4 复位 / 初始化流

{{ reset_flow }}

---

## 4. Package 与编译依赖

| Package / 文件 | 依赖 | 说明 |
|---|---|---|
| `{{ pkg.name }}` | {{ pkg.depends }} | {{ pkg.description }} |

编译顺序见 `uvm_buildplan.md` 第 12 章 `Files.f`。

---

## 5. 与参考框架的对位关系

| 参考框架组件 | 本环境对应 | 差异 |
|---|---|---|
| {{ ref.component }} | {{ local.component }} | {{ ref.diff }} |

---

## 6. 文件统计速查

| 类别 | 数量 |
|---|---:|
| Agent | {{ agent_count }} |
| Interface | {{ iface_count }} |
| Package | {{ pkg_count }} |
| Test | {{ test_count }} |
| SVA | {{ sva_count }} |
| Covergroup | {{ cg_count }} |
