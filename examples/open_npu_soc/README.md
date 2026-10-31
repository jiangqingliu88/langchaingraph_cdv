# Open NPU SoC v0.1

一个**可执行**的 SoC 参考工程，用来把 SignOffAI 的 CLI / 回归 / 覆盖率 /
证据链链路跑在真实 RTL 上，而不是只跑单元级 demo。

## v0.1 的边界（先说实话）

| 部分 | v0.1 状态 |
|---|---|
| CPU | **E203 hbirdv2 已完整引入**：`e203_hbirdv2/`（Apache-2.0）；NICE 适配器见 `integration/e203/` |
| NICE | `e203_nice_npu_adapter.sv` 对齐 E203 NICE 端口；CPU 用 custom3 提交 GEMM、轮询 STATUS |
| DMA | `rtl/dma/dma_simple.sv`：A/B 搬入、C 搬回，逐字写 |
| SRAM | `rtl/sram/sram_banked.sv`：A/B 8x8 INT8，C 8x8 INT32 |
| NPU | `rtl/npu/int8_gemm.sv`：INT8 GEMM，32-bit 累加 |
| 软件 | `sw/` 提供 bare-metal 入口与 NICE 调用示例；v0.1 仿真**暂不执行**（E203 集成 seam） |
| 仿真 | 自检 TB `tb/tb_soc_top.sv`；比较 Python golden 向量 |

**两条验证路径并存**：

1. **参考 TB**（无需 EDA 以外的依赖）：`tb_soc_top` 预装 A/B、用
   `nice_cmd_sequencer` 驱动，先证明数据通路；
2. **E203 路径**（M1）：真实 E203 CPU 执行 bare-metal 固件，通过 NICE
   custom3 提交 GEMM，适配器用 NICE ICB 在 DTCM 里搬数。

## 数据流

```text
参考 TB:  Python golden → tb_soc_top 预装 A/B → nice_cmd_sequencer
          → DMA → SRAM → INT8 GEMM → SRAM C → TB 比较 → mismatched=0/PASS

E203:     CPU 执行 gemm_8x8.elf → NICE custom3 START(desc)
          → e203_nice_npu_adapter → NICE ICB 读 A/B → INT8 GEMM
          → ICB 写 C 回 DTCM → STATUS 轮询 → CPU 与 golden 比较
```

## 目录

```text
examples/open_npu_soc/
├─ rtl/
│  ├─ cpu/nice_cmd_sequencer.sv   # 参考 TB 的确定性命令时序
│  ├─ cpu/e203_nice_npu_adapter.sv # E203 NICE 端口 → NPU（M1）
│  ├─ dma/dma_simple.sv
│  ├─ interconnect/soc_map.svh    # 地址映射（单一来源）
│  ├─ npu/int8_gemm.sv
│  ├─ sram/sram_banked.sv
│  └─ soc_top.sv
├─ tb/tb_soc_top.sv               # 自检 TB
├─ sw/                            # E203 bare-metal 固件 + build_sw.py
├─ golden/gemm_golden.py          # Python golden + 向量生成
├─ spec/                          # SoC / 接口 / 验证计划
├─ regression/regression.yaml     # 现有回归框架配置
├─ e203_hbirdv2/                  # 完整 E203 hbirdv2（Apache-2.0）
├─ integration/e203/              # NICE→NPU 适配器 patch / 说明
├─ toolchain/                     # RISC-V 工具链 setup + prefix.mk
├─ filelist.f
└─ README.md
```

## 用法

### 1. 生成 golden 向量

```bash
python examples/open_npu_soc/golden/gemm_golden.py \
    --out examples/open_npu_soc/vectors
```

固定 seed → 每次生成同一组 `a.hex` / `b.hex` / `c.hex`。

### 2. 用现有 CLI 检查工程

```bash
python -m src.cli.commands soc check examples/open_npu_soc
```

### 3. 用现有回归执行器跑仿真

```bash
python -m src.cli.commands soc run examples/open_npu_soc \
    --output output_soc_v01
```

`SOC_ROOT` 会由 CLI 设置为工程目录；回归 YAML 的 build/test 命令都通过它定位
`filelist.f` / `vectors/`。需要 `vlog`/`vsim` 在 PATH（v0.1 用 Questa）。

`run` 会额外产出（复用 `src/core`，不另造引擎）：

```text
<run>/docs/run_context.json      # RunContext 身份
<run>/docs/events.jsonl          # EventStore 执行事实
<run>/artifacts/artifacts.json   # ArtifactStore（RTL/golden/日志/波形/报告）
<run>/soc/soc_run.json           # SoC run 摘要（状态/波形/回归）
<run>/signoff_evidence/          # SoC 证据包（24 个文件，package_hash）
```

常用命令：

```bash
python -m src.cli.commands soc report   <run>   # 摘要
python -m src.cli.commands soc evidence <run>   # 逐文件哈希校验
python -m src.cli.commands soc wave     <run>   # 用 Visualizer 打开 qwave.db
```

波形里可以直接看 `start → dma_load → gemm_start → gemm_done → dma_store →
irq/done` 这条 NICE 命令序列，以及 SRAM/GEMM 的数据变化。

也可以直接跑：

```bash
cd examples/open_npu_soc
vlog -sv -f filelist.f
vsim -c work.tb_soc_top -do "log -r /*; run -all; quit" -l sim_vsim.log \
     -qwavedb=+signal+class+wavefile=waves/gemm_8x8.db
grep mismatched=0 sim_vsim.log
```

### 3.1 E203 + NPU（M1）

```bash
# 1) 工具链（首次）
python examples/open_npu_soc/toolchain/setup_toolchain.py

# 2) 把 NICE 适配器接到 E203 CPU
python examples/open_npu_soc/integration/e203/apply_npu_patch.py

# 3) 编译 bare-metal 固件
python examples/open_npu_soc/sw/build_sw.py
```

产物：`sw/gemm_8x8.elf/.hex/.verilog/.dump`。E203 TB 读取
`<TESTCASE>.verilog`，所以在有 iverilog/VCS/Questa 的机器上：

```bash
cd examples/open_npu_soc/e203_hbirdv2/vsim
make compile SIM=iverilog
make run_test SIM=iverilog TESTCASE=../../sw/gemm_8x8 DUMPWAVE=0
```

本机缺 EDA，无法在这里实际执行仿真。NICE 适配器当前是**阻塞式**：
CPU 先 START，再轮询 STATUS；把 `irq` 接到 PLIC 是下一步。

### 4. 证据

`signoff`/`evidence` 走现有 CLI 流程；v0.1 先确保：

- `RunContext` / `ArtifactStore` 能看到 RTL、golden 向量、日志；
- 回归报告记录 `gemm_8x8` 的 pass/fail 与耗时；
- 日志里 `mismatched=0` / `PASS` 是唯一成功判据。

## 下一步（M1 → M4）

1. **M1**：E203 + NICE 已接入（适配器 + 固件编译）；还差在装有
   iverilog/VCS/Questa 的机器上实跑并修 NICE/ICB 时序问题。
2. **M2**：UVM 环境（CPU/NICE/DMA/SRAM/GEMM agent、scoreboard、覆盖点、回归）。
3. **M3**：接入 SignOffAI 的 spec 解析 / verification plan / UVM 生成 / 自动
   回归 / coverage / evidence。
4. **M4**：Workbench 增加 SoC 入口（总览 / 架构 / 验证 / 签核），复用现有
   `flow.*` 视图，不做第二套 GUI。

## 与 SignOffAI 核心的边界

本工程**不修改** SignOffAI 的 Agent/Executor/Core；CLI 里的 `soc` 组只是
工程适配层：校验输入、生成向量、用现有 `InfrastructureManager` 跑回归。
