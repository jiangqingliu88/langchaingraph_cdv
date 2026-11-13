# Open NPU SoC v0.1

一个**可执行**的 SoC 参考工程，用来把 SignOffAI 的 CLI / 回归 / 覆盖率 /
证据链链路跑在真实 RTL 上，而不是只跑单元级 demo。

## v0.1 的边界（先说实话）

| 部分 | v0.1 状态 |
|---|---|
| CPU | **E203 hbirdv2 已完整引入**：`e203_hbirdv2/`（Apache-2.0）；NICE 适配器见 `integration/e203/` |
| NICE | `e203_nice_npu_adapter.sv` 对齐 E203 NICE 端口；CPU 用 custom3 提交 GEMM、轮询 STATUS |
| DMA | `npu/dma/dma_simple.sv`：A/B 搬入、C 搬回，逐字写 |
| SRAM | `npu/sram/sram_banked.sv`：A/B 8x8 INT8，C 8x8 INT32 |
| NPU | `npu/npu_top.sv`（子系统顶层）+ `npu/npu/int8_gemm.sv`（INT8 GEMM） |
| 软件 | `sw/` 提供 bare-metal C 用例；`soc c-run` 已实跑通过（E203 执行 C、驱动 NICE/NPU） |
| 仿真 | 自检 TB `tb/tb_soc_top.sv`；比较 Python golden 向量 |

**两条验证路径并存**：

1. **参考 TB**（无需 EDA 以外的依赖）：`tb_soc_top` 预装 A/B、用
   `nice_cmd_sequencer` 驱动，先证明数据通路；
2. **E203 路径**（M1）：真实 E203 CPU 执行 bare-metal 固件，通过 NICE
   custom3 提交 GEMM，适配器用 NICE ICB 在 DTCM 里搬数。

> **NPU 挂在子系统层级**：`e203_subsys_top` 里 `u_npu_top` 与
> `u_e203_subsys_main` 同级；NICE 请求/响应/ICB 从 `e203_subsys_main`
> 边界引出。适配器与 `int8_gemm` 仍在文件表末尾覆盖树内同名模块；C 用例
> 的顶层复用 `tb/tb_soc_top.sv`（`+define+E203_C_RUN` 时例化 E203
> `tb_top`）。E203 树只改了 4 个文件做接口上引：`e203_cpu.v` /
> `e203_cpu_top.v` / `e203_subsys_main.v` / `e203_subsys_top.v`。

## 数据流

```text
参考 TB:  Python golden → tb_soc_top 预装 A/B → nice_cmd_sequencer
          → DMA → SRAM → INT8 GEMM → SRAM C → TB 比较 → mismatched=0/PASS

E203:     CPU 执行 gemm_8x8.elf → NICE custom3 START(desc)
          → e203_subsys_main 边界 → u_npu_top/u_nice_disp → NICE ICB 读 A/B
          → INT8 GEMM → ICB 写 C 回 DTCM → STATUS 轮询 → CPU 与 golden 比较
```

## 目录

```text
examples/open_npu_soc/
├─ npu/                           # NPU IP / 子系统
│  ├─ npu_top.sv                  # u_npu_top：与 u_e203_subsys_main 同级
│  ├─ soc_top.sv                  # 参考 TB 的 SoC 顶层（非 E203 路径）
│  ├─ nice_disp/nice_cmd_sequencer.sv   # 参考 TB 的确定性命令时序
│  ├─ nice_disp/e203_nice_npu_adapter.sv # E203 NICE → NPU（M1）
│  ├─ dma/dma_simple.sv
│  ├─ interconnect/soc_map.svh    # 地址映射（单一来源）
│  ├─ npu/int8_gemm.sv
│  └─ sram/sram_banked.sv
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
python -m src.interfaces.cli.commands soc check examples/open_npu_soc
```

### 3. 用现有回归执行器跑仿真

```bash
python -m src.interfaces.cli.commands soc run examples/open_npu_soc \
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
<run>/signoff_evidence/          # SoC 证据包（26 个文件，package_hash）
```

常用命令：

```bash
python -m src.interfaces.cli.commands soc report   <run>   # 摘要
python -m src.interfaces.cli.commands soc evidence <run>   # 逐文件哈希校验
python -m src.interfaces.cli.commands soc wave <run> --test gemm_8x8_c   # C 用例波形
python -m src.interfaces.cli.commands soc wave     <run>   # 默认最新一份 qwave.db
```

`regression.yaml` 里有两条用例：参考 TB `gemm_8x8` 和 E203 C 用例
`gemm_8x8_c`，所以一次 `soc run` 会出两份波形：

- 参考路径：`start → dma_load → gemm_start → gemm_done → dma_store → irq/done`；
- C 路径：custom3 `START/STATUS/ACK`、适配器 `nice_req_inst`、
  ICB 读写地址与 `a_buf/b_buf/c_buf`、`gemm_start/gemm_done`。

**波形要在编译期加 `+acc`**：不加访问权限时 vopt 会删掉大部分信号，
qwave.db 只剩顶层几根线（实测 1.1 KB）。工程里的两个 build 都已加。

数组（`u_gemm.a/b/c`、适配器的 `a_buf/b_buf/c_buf`、`desc/c_words`）
默认不进波形；`-qwavedb` 里要带 `+memory=4096,4`（元素数/维数上限），
否则打开时会报 `Memory ... is not logged in the waveform file`。

**Hierarchy 里看源码**：Visualizer 的源码浏览要 `vopt -designfile
design.bin -linedebug`。该选项会额外拉起 viscom，实测峰值 3GB，在低内存
机器上会让 vopt `VirtualAlloc` 失败，所以默认**关闭**；`soc wave` 仍可直接
看波形/信号。需要源码浏览时单独在有足够内存的机器上生成 `design.bin`。

### 3.0 SoC C 用例（E203 驱动 IP）

```bash
python -m src.interfaces.cli.commands soc c-cases examples/open_npu_soc
python -m src.interfaces.cli.commands soc c-run   examples/open_npu_soc \
    --case C-GEMM-8X8 -o output_c_C-GEMM-8X8
# 跑完直接开 C 用例波形
python -m src.interfaces.cli.commands soc wave output_c_C-GEMM-8X8
```

C 用例也登记在 `regression/regression.yaml`（`build_e203_c` +
`gemm_8x8_c`），所以 `soc run` 会连同参考用例一起跑；跑完用
`soc wave <run> --test gemm_8x8_c` 打开 C 波形。

Workbench 里的位置：**SoC 团队 → SoC C 用例**（`soc.c_cases`）。页面列出
`sw/cases.yaml` 的用例，可「运行选中用例」并直接打开波形；`soc c-run`
产出的 `c_run.json` 也会出现在各 SoC 页的 run 选择器和「运行历史」里
（`kind=soc_c`）。

`c-run` 用 `sw/build_sw.py` 编 RISC-V bare-metal（需要
`toolchain/setup_toolchain.py` 先装工具链），再用 Questa 编 E203 SoC，
顶层是 `tb_soc_top`（`+define+E203_C_RUN` 时例化 E203 `tb_top`）；判据是
日志里的 `TEST_PASS` / `TEST_FAIL`。C 程序通过 NICE custom3 提交 GEMM，
DMA/SRAM/GEMM 都在 RTL 里被真实执行。

NICE custom3 的 func3 不是任意编码：E203 把 `instr[13]` 当 rs1en、
`instr[14]` 当 rdwen。因此 START 用 func3=2（读 rs1）、STATUS 用
func3=4（写 rd）、ACK 用 func3=0；改编码要同步改适配器
`npu/nice_disp/e203_nice_npu_adapter.sv`。

### 3.2 IP 团队视角

`spec/ip_manifest.yaml` 定义 IP 的团队/owner/版本/发布状态；
`spec/ip_verification_plan.yaml` 定义每个 IP 的 TP 与 tests。

```bash
python -m src.interfaces.cli.commands ip list    examples/open_npu_soc
python -m src.interfaces.cli.commands ip run     examples/open_npu_soc --ip IP-NPU-GEMM
python -m src.interfaces.cli.commands ip status  examples/open_npu_soc --ip IP-NPU-GEMM
python -m src.interfaces.cli.commands ip evidence examples/open_npu_soc --ip IP-NPU-GEMM
python -m src.interfaces.cli.commands ip release examples/open_npu_soc   # SoC 团队消费的矩阵
```

IP 证据写 `<run>/ip_evidence/<ip>.json`，引用来源 SoC run 的 TP 状态与证据包哈希；
独立 IP TB / 覆盖率拆分仍是 M2。

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

# 2) 编固件 + Questa 编 E203 SoC + 跑 C 用例（一条命令）
python -m src.interfaces.cli.commands soc c-run examples/open_npu_soc --case C-GEMM-8X8
```

产物：`sw/gemm_8x8.elf/.hex/.verilog/.dump`；run 目录下
`c_run.json`、`e203/build.log`、`e203/sim.log`。

- `e203_hbirdv2/` **只读**：适配器/GEMM 是编译文件表末尾的同名覆盖；
  C 用例顶层是 `tb/tb_soc_top.sv` 例化 E203 `tb_top`。
- NICE 适配器当前是**阻塞式**：CPU 先 START，再轮询 STATUS；把 `irq`
  接到 PLIC 是下一步。
- 已实测：`C-GEMM-8X8` 在 Questa 2024.1 上 `TEST_PASS`（C 程序先在
  DTCM 里初始化 A/B，再经 NICE custom3 → ICB 读 DTCM → INT8 GEMM →
  写回 C，最后与 C 版 golden 逐元素比较）。

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
