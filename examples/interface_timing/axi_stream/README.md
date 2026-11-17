# AXI4-Stream 有限接口时序示例

这是一个按功能分块的最小闭环，不是“任意接口/全文理解已完成”的演示。

## 目录

- [source/spec.md](source/spec.md)：权威时序说明，唯一被引用的握手规则来自第 13 行。
- [intents/structured.yaml](intents/structured.yaml)：人工提供的结构化 Temporal IR、来源行号和文件 SHA-256。
- [rtl/pass_master.sv](rtl/pass_master.sv)：遵守握手稳定性的 master 模型。
- [rtl/fail_master.sv](rtl/fail_master.sv)：背压时改变 DATA 的故意违例模型。

本 Demo 的正式输入不是 LLM 生成的结果，而是 `structured_authoring`。LLM 候选提取只作为可选适配器存在，未经进一步确认不能把其结果当成正式语义。

## 运行

在仓库根目录执行：

```powershell
python -m src.workbench.cli.commands interface-timing run-slice --seed 4444
```

命令会完成：原文/行号/hash 校验、RTL 端口绑定、原 Specification 工作流校验、monitor 生成，再尝试调用真实 `iverilog/vvp`。

默认以 `review_bundle/chipstack_artifacts` 作为工作区：原始结果保留在 `Archive/<run_id>/`，并按设计名建立 `mental_model_agent/`、`uvm_agent/`、`simulation_agent/` 及覆盖率/调试目录。系统根目录会有 `run_manifest.json` 与专用 `artifacts.sqlite`。

可用 `--legacy-layout` 回到原来的平铺输出；可用 `--top-design-name` 指定项目名。查询历史：

```powershell
python -m src.workbench.cli.commands interface-timing runs --workspace review_bundle/chipstack_demo --json
```

目录和真实状态示例见 [ChipStack 风格工作区文档](../../../docs/architecture/CHIPSTACK_ARTIFACT_WORKSPACE.md)。未运行的 formal/lint/PPA/compile-fix 仅显示状态，不生成结果。

本机没有可用的仿真器时，**输出 INCOMPLETE、退出码 2**。这与“规格已经通过校验”不是一回事。只有外部仿真器实际编译并运行后，运行时结果才可能为 PASS 或 FAIL。

如只希望查看契约和 [证据清单](../../../review_bundle/interface_timing/axi_stream/run-1794628449637528800/manifest.json)，可使用 `--allow-incomplete`。它只放开查看出口码，不修改实际三态。

## 目录职责

- Temporal IR 与规格桥接：`src/mental_ir_plane/interface_timing/`。
- 绑定检查：`src/engine_plane/interface_timing/`。
- Monitor 生成：`src/generation_plane/interface_timing/`。
- 真实仿真适配：`src/runtime_plane/tools/execution/interface_timing/`。
- 编排：`src/orchestration_plane/interface_timing_workflow.py`。
- CLI：`src/workbench/cli/cmd_interface_timing.py`。

详细实现状态与未覆盖范围见 [功能分块与实证边界](../../../docs/architecture/INTERFACE_TIMING_SLICE.md)。

特别说明：此示例只覆盖单时钟下的一次 VALID/READY/DATA 稳定性场景。TLAST、乱序、多时钟、CDC、其他协议及完整签核链不在本示例的证明范围内。
