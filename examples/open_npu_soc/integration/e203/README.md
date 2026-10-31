# E203 + Open NPU（M1）

## 做了什么

- **E203 hbirdv2 原样引入**：`examples/open_npu_soc/e203_hbirdv2/`
  （Apache-2.0，含 NICE RTL、`riscv-tests`、`tb/tb_top.v`、iverilog/VCS 仿真配置）。
- **NICE 端口适配器**：
  `rtl/cpu/e203_nice_npu_adapter.sv`，端口与 E203
  `rtl/e203/subsys/e203_subsys_nice_core.v` **逐一对齐**：
  - `nice_req_*` / `nice_rsp_*`
  - `nice_icb_cmd_*` / `nice_icb_rsp_*`（ICB master，访问 E203 DTCM）
  - `nice_active` / `nice_mem_holdup`
- 适配器内部复用 `rtl/npu/int8_gemm.sv`，通过 ICB 读 descriptor/A/B、写 C。

## 自定义指令

| 指令 | 编码 | 语义 |
|---|---|---|
| START | `custom3, func3=0, func7=1, rs1=desc` | 启动一次 8x8x8 INT8 GEMM |
| STATUS | `custom3, func3=1, func7=1` | 返回 `{irq, done}` |
| ACK | `custom3, func3=2, func7=1` | 清 `irq` |

`desc = {a_addr, b_addr, c_addr, M, N, K}`（6 个 32-bit 字）。

## 应用 patch

```bash
python examples/open_npu_soc/integration/e203/apply_npu_patch.py
```

它会把适配器复制进 E203 树，并把 `e203_cpu.v` 的 NICE 实例指向适配器。
撤销：

```bash
python examples/open_npu_soc/integration/e203/apply_npu_patch.py --revert
```

## 编译固件

```bash
python examples/open_npu_soc/toolchain/setup_toolchain.py   # 首次
python examples/open_npu_soc/sw/build_sw.py
```

产物：`sw/gemm_8x8.elf`、`gemm_8x8.hex`、`gemm_8x8.dump`。
E203 TB 读取的是 `.verilog`，构建脚本会同时生成/复制 `gemm_8x8.verilog`。

## 跑 E203 仿真

E203 自带 `vsim` 支持 iverilog / VCS：

```bash
cd examples/open_npu_soc/e203_hbirdv2/vsim
make compile SIM=iverilog
make run_test SIM=iverilog TESTCASE=../../sw/gemm_8x8 DUMPWAVE=0
```

（本机若没有 `make`/`iverilog`，用 `build_sw.py` 编译固件后，在装有
Questasim/VCS/iverilog 的机器上执行；E203 自测也可以先跑 `rv32ui-p-add`。）

## 边界（M1 当前）

- **CPU 轮询 STATUS**，尚未把 `irq` 接到 E203 PLIC；适配器已经内部产生 `irq`，
  下一步在 `e203_subsys_main`/PLIC 侧接一条外部中断。
- 矩阵固定 8x8x8 INT8；边界/异常场景在 M2 扩展。
- 适配器只做**功能模型**（组合乘加），不是时序收敛/可综合的 NPU。
- 需要 EDA（Questa/VCS/iverilog）才能实际跑仿真；本机当前缺 EDA。
