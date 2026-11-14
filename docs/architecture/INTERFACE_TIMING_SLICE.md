# AXI4-Stream 接口时序闭环：功能分块与实证边界

**状态**：结构化来源、绑定检查和 Specification 编译路径已实现并通过定向测试；本机缺少可用的 RTL 仿真器，**运行时结论为 INCOMPLETE，不是 RTL 验证通过**。

## 1. 本阶段做什么、不做什么

本阶段只有一个明确能力：

> 在单一 AXI4-Stream master 输出接口、单一 posedge 时钟域中，证明给定规则能够被编译并执行：**VALID 高而 READY 低时，VALID 与声明的 DATA 必须保持稳定，直到握手完成。**

不宣称：

- 任意自然语言都被正确理解；
- 所有接口、所有 AXI 规则、多时钟、CDC、乱序、TLAST 等都已覆盖；
- LLM 提取结果已经成为事实；
- 已在本机运行 RTL 仿真，或已有 Verification Signoff PASS。

输入使用 **structured_authoring**：人工提供的结构化语义和原文锚点，见 [structured.yaml](../../examples/interface_timing/axi_stream/intents/structured.yaml)。另提供 [LLM 候选提取适配器](../../src/agent_plane/specification/temporal_extractor.py)，其输出强制降为 `DERIVED`，不会因为模型自称正确就直接进入正式执行。

## 2. 功能分块，而不是增加 Plane

保留 Interfaces + 八个既有 `src/*_plane` 的九逻辑平面。每个功能块只承担一类责任：

| 功能块 | 位置 | 职责 |
|---|---|---|
| Temporal IR | [interface_timing/model.py](../../src/ir_plane/interface_timing/model.py) | 时钟、复位、信号绑定、规则、原文锚点与稳定 hash |
| 原规格契约桥接 | [interface_timing/bridge.py](../../src/ir_plane/interface_timing/bridge.py) | 转为既有 `specification_contract_v1`，让原 Specification 工作流继续处理 |
| Agent 候选提取 | [temporal_extractor.py](../../src/agent_plane/specification/temporal_extractor.py) | 注入可选 analyzer；强制保留候选与来源责任 |
| 协议知识 | [axi_stream.py](../../src/knowledge_plane/interface_protocols/axi_stream.py) | 当前握手必要角色和语义规则说明，不替当前设计确认 |
| 绑定校验 | [checker.py](../../src/engine_plane/interface_timing/checker.py) | 来源 hash/行号、端口方向/位宽、时钟/复位、规则与未知项检查 |
| Specification 主链 | [compiler.py](../../src/engine_plane/specification_compiler/compiler.py) | 校验 Temporal IR 与绑定报告的版本关联；旧入口不能丢弃接口证据 |
| Monitor 生成 | [monitor.py](../../src/generation_plane/interface_timing/monitor.py) | 从结构化字段生成 SystemVerilog，绝不把自然语言注入为断言 |
| 仿真执行 | [execution/interface_timing/simulator.py](../../src/runtime_plane/tools/execution/interface_timing/simulator.py) | 只在外部 `iverilog/vvp` 实际启动完成后，产出运行时证据 |
| 编排 | [interface_timing_workflow.py](../../src/orchestration_plane/interface_timing_workflow.py) | Source → IR → Binding → Specification → Monitor → Runtime → Evidence |
| 工作区投影 | [chipstack_workspace.py](../../src/runtime_plane/artifacts/chipstack_workspace.py) | 将原始产物归档到 Archive，并映射为项目级 mental_model/UVM/仿真/覆盖率/调试工作区和 SQLite 索引 |
| CLI | [cmd_interface_timing.py](../../src/workbench/cli/cmd_interface_timing.py) | `interface-timing run-slice`，显式区分三态与退出码 |

执行工具包已登记到 [BOARDS](../../src/runtime_plane/tools/boards.py) 的 `execution` 板块。它遵守现有目录和懒加载约束，不增加第八个工具板块，也不增加第十个架构平面。

## 3. 端到端责任链和停止条件

```text
权威原文（带 hash、locator、line_start/end）
    ↓
结构化候选 Temporal IR / 已确认结构化语义
    ↓
原文片段与行号、来源所属项目校验
    ↓
真实 RTL 端口、方向、位宽绑定
    ↓
时钟、复位、VALID / READY / DATA / UNKNOWN 校验
    ↓
Temporal IR + 匹配绑定报告 → 原 SpecificationContract
    ↓
确定性编译及 Readiness
    ↓
候选 SystemVerilog Monitor
    ↓
iverilog 编译 + vvp 运行
    ↓
seed、日志、VCD 波形、计数与规则身份
    ↓
Engine 三态裁决 + 证据清单
```

任何一步还没有得到证明，都不能越过阶段输出 PASS：

- LLM 候选只能为 DERIVED；
- 无原文、行号不对、文档 hash 不符 → 停止；
- 端口只是“名字相似”但找不到、方向错误、位宽未知 → 停止；
- 不确定时钟或复位极性、未知关系或冲突来源 → 停止；
- Temporal IR 与绑定报告不匹配 → 原 Specification 主链也报 INCOMPLETE；
- 只有端口表但没有合法 Temporal IR → 不能静默忽略；
- 没有实际仿真或没有可解析结果 → INCOMPLETE；
- 结果中的 `rule_id` 与当前 IR 不同 → INCOMPLETE。

## 4. 三个状态层级不能混用

| 层级 | 本例的实际结果 | 含义 |
|---|---|---|
| Source / Binding | `VALIDATED` | 结构化语义与原文锚点、RTL 端口和时钟/方向规则通过检查 |
| Specification Readiness | `VALIDATED` | 原 Specification 主链接受该 Temporal IR 与匹配的 binding report |
| Runtime | `INCOMPLETE` | 没有完成本机 RTL 仿真；没有真实 VCD 或运行期结论 |

**`execution_allowed=true` 在 `specification_readiness.json` 中只表示可以进入后续验证执行，不是“验证已经通过”。**

当前真实样例结果保存在 [manifest.json](../../review_bundle/interface_timing/axi_stream/run-1794628449637528800/manifest.json)：

- `overall_status = INCOMPLETE`；
- `specification_readiness.status = VALIDATED`；
- `binding_report.status = VALIDATED`；
- `rtl_simulation_completed = false`；
- 正样例与负样例的两项运行时均为 INCOMPLETE；
- 当前清单有 9 个产物及各自的文件 hash。

[SystemVerilog monitor 原文](../../review_bundle/interface_timing/axi_stream/run-1794628449637528800/monitors/monitor_r_valid_data_stable.sv) 已生成，但**未在本机编译执行**。它是来自已验证契约的候选工件，不是运行时通过报告。

## 5. 示例内容与真实 backend 行为

```text
examples/interface_timing/axi_stream/
├── source/spec.md
├── intents/structured.yaml
└── rtl/
    ├── pass_master.sv  # 遵守协议的 master 模型
    └── fail_master.sv  # 故意在背压期间改变 DATA 的对照模型
```

[原始 spec](../../examples/interface_timing/axi_stream/source/spec.md) 第 13 行给出当前握手义务及对应信号名。结构化语义引用该行的原文、行号和 SHA-256。

- `pass_master.sv`：符合所声明的握手稳定性；
- `fail_master.sv`：在 `VALID && !READY` 期间改变 DATA，作为故意违例的对照。

这两个模型分别用于预期的 PASS 与预期的 FAIL。**反例的 FAIL 不会被改写成系统的成功**；编排器比较 `actual_status` 与 `expected_status`，正样例没有背压观察、没有握手、未知值过多、或反例没有告警，都不能被当作完整通过。

Runtime 工具使用实际外部命令，记录编译日志、仿真日志、seed 与可选波形。当前 `seed = 4444`，payload 由 `0x101 XOR seed` 产生；这组场景是定向请求与背压，不冒充随机回归。如果外部工具不可用，后端只报告 unavailable，不会生成一份模拟的波形或虚假的仿真计数。

## 6. 测试与工程门禁

### 接口业务定向测试

[test_interface_timing_slice.py](../../tests/test_interface_timing_slice.py) 共 **27 项**，覆盖：

- 合法结构化语义与 RTL 绑定；
- 原文 hash 与行号一致性、过期来源；
- 来源路径越界、引文不覆盖本规则的信号；
- LLM 候选被强制降为 DERIVED，缺原文时拒绝；
- RTL 端口缺失、方向冲突、重复/不受支持的角色；
- SystemVerilog 生成、标识符注入防护、payload 复位清理；
- 显式端口连接、seed 计算和时钟周期；
- monitor 日志 rule_id 身份校验；
- 无效 binding / stale hash 在原 Specification 主链同样被拒绝；
- 旧端口表不能被静默丢弃；
- 正/反样例预期，以及反例没有报警时无法通过；
- 测试替身 `test_double` 与实际仿真完成状态严格分开。

### 组合与全量测试

- 接口闭环、Tool Boards 与 Architecture invariants：**47 passed**；
- 接口 + Resource IR + Guard + Planes 相关回归：**134 passed**；
- 全量 `tests/`：**1343 passed / 16 skipped，`PYTEST_EXIT=0`**；
- Architecture Guard：**OK**；
- 新改动模块的语法、import 和 E/F 类检查通过；未把全仓既有 lint 负债记为此次零负债。

这些测试是 Python/契约与生成工件验证。`test_double` 仅用于验证编排与控制逻辑，**不能作为真实 HDL 仿真证据**。

## 7. 直接运行

```powershell
python -m src.workbench.cli.commands interface-timing run-slice --seed 4444
```

当前环境预期返回 **2（INCOMPLETE）**，并打印新生成的 manifest 路径。

仅在明确接受不完整证据、需要查看契约/生成工件时，可额外使用：

```powershell
python -m src.workbench.cli.commands interface-timing run-slice --seed 4444 --allow-incomplete
```

`--allow-incomplete` 只放开命令的查看出口码，**不会把结果改成 PASS**。

若已配置 Icarus，可通过 `PATH`、`IVERILOG_HOME` 或显式的 `INTERFACE_TIMING_IVERILOG` / `INTERFACE_TIMING_VVP` 提供工具路径，再运行同一命令。默认不会使用 Python replay 代替 RTL 仿真。

## 8. 当前环境和真实边界

本机未找到已可用的 iverilog、Verilator、Questa 或 VCS。尝试从 [Icarus 官方 Windows 发行页](https://bleyer.org/icarus/) 获取发行包时被 Windows 的文件安全检查阻止；随后 `winget` 针对 user scope 也报告找不到适用安装程序。没有关闭安全软件或绕过验证，也没有因此生成假的仿真证据。

仍需明确保留的限制：

1. 只有当前握手稳定性规则的有限实现，而非完整协议模型。
2. 原文抽取是适配点；当前 Demo 的正式输入是结构化语义，不证明 LLM 从任意文档推导的结论正确。
3. Runtime 轻量端口读取只支持常见单行声明，并已排除注释中的端口；复杂 SystemVerilog 必须注入完整 parser，不能把正则扫描当成完整 RTL 理解。
4. 目前 monitor 是过程化采样检查，尚不是覆盖所有 AXI 助手、时序、死锁与响应语义的 SVA 库。
5. 计数日志已经检查格式和 rule_id，但还不是密码学签名证据，也尚未独立重放整条波形。用于正式签核前需要把这些运行时产物接入现有 Evidence Package / Replay / Audit 流程。
6. `interface_slice_evidence_v1` 是本地运行证据清单，不是完整 Evidence v2 三态签核包；跨 Run STALE 传播仍未实现。
7. 真实 EDA 后端尚未在本环境验证，因而不能宣称 CLI 的完整 RTL 仿真链已经完成。

## 9. 产物工作区：系统索引 + 项目 AI 工作区

在原始 monitor/波形/日志之外，已增加一个 Runtime 产物投影层。当前结果为：

- 系统级：`run_manifest.json`、专用 `artifacts.sqlite` 与按 run 隔离的 `Archive/<run_id>/`；
- 项目级：`mental_model_agent/`、`rtl_generation/`、`uvm_agent/`、`simulation_agent/`、`functional_coverage_agent/`、`coverage_closure_agent/`、`dv_debug/`；
- 未正式执行的 `formal_agent/`、`rtl_early_estimation_agent/`、`lint_autofix/`、`compile_n_fix/`：只写 NOT_RUN 状态，不伪造报告。

详见 [ChipStack 风格产物工作区](CHIPSTACK_ARTIFACT_WORKSPACE.md)。新布局是 Runtime 的持久化视图，不是第十个架构平面，也不是 Cadence 服务或数据库接管。原始 Archive 与项目 monitor 的字节和 hash 经定向测试核对一致；可用 `--legacy-layout` 保留原平铺输出。

## 10. 下一验收步骤

提供一个可用的 Icarus / RTL 仿真环境，重新运行本条命令并检查：

- 编译与运行确实启动；
- 正样例出现背压和真实握手，且 monitor 没有违例；
- 反样例在 DATA 变化时出现确定的 `TIMING_VIOLATION`；
- 同时保存 seed、监视器日志和真实 VCD；
- 最终 `runtime.json` 和 manifest 与实际文件一致，而不是由测试替身或静态结果生成。

**这一步完成前，只能承认已建立可验证的契约与执行适配，不得宣称 AI 已端到端理解并证明了这个接口。** 更不能外推为所有接口都已正确理解。