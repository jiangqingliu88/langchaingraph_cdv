# E203 + Open NPU（M1）

## 层级

NPU 是**子系统级 IP**，不是 CPU 内的 NICE core：

```text
tb_soc_top
 └─ u_e203_tb_top (E203 tb_top)
    └─ u_e203_soc_top
       └─ u_e203_subsys_top
          ├─ u_e203_subsys_main      # E203 CPU 子系统
          │    └─ ... → e203_cpu     # NICE 请求/响应/ICB 引到模块边界
          └─ u_npu_top               # NPU 子系统（与 subsys_main 同级）
               └─ u_nice_disp        # npu/nice_disp/e203_nice_npu_adapter.sv
                    └─ u_gemm        # npu/npu/int8_gemm.sv
```

NICE 的 ICB 主口回到 CPU 的 LSU（地址落在 DTCM），所以 CPU 侧看到的是普通
内存：descriptor / A / B / C 都在 DTCM。

## 接口上引（E203 树里改的 4 个文件）

| 文件 | 改动 |
|---|---|
| `e203_cpu.v` | 去掉 CPU 内的 NPU 实例；`nice_req_*` / `nice_rsp_*` / `nice_icb_*` 引成模块端口 |
| `e203_cpu_top.v` | 端口透传 |
| `e203_subsys_main.v` | 端口透传到子系统边界；导出 `core_rst_n_o` |
| `e203_subsys_top.v` | 例化 `npu_top u_npu_top`，与 `u_e203_subsys_main` 同级 |

适配器/GEMM 仍以编译文件表末尾同名覆盖的方式编入（不改树内旧副本）。

## 自定义指令

| 指令 | 编码 | 语义 |
|---|---|---|
| START | `custom3, func3=2, func7=1, rs1=desc` | 启动一次 8x8x8 INT8 GEMM |
| STATUS | `custom3, func3=4, func7=1` | 返回 `{irq, done}` |
| ACK | `custom3, func3=0, func7=1` | 清 `irq` |

`func3` 的 bit1/bit2 同时是 E203 的 `instr[13]=rs1en` / `instr[14]=rdwen`
（见 `e203_exu_decode.v`），所以 START 必须用 2、STATUS 必须用 4。

## 跑 C 用例

```bash
python examples/open_npu_soc/toolchain/setup_toolchain.py    # 首次
python -m src.cli.commands soc c-run examples/open_npu_soc \
    --case C-GEMM-8X8 -o output_c_C-GEMM-8X8
python -m src.cli.commands soc wave output_c_C-GEMM-8X8      # Visualizer
```

`regression/regression.yaml` 里也登记了 `build_e203_c` + `gemm_8x8_c`，
`soc run` 会连同参考用例一起跑。

## 边界（M1 当前）

- **CPU 轮询 STATUS**，尚未把 `irq` 接到 E203 PLIC。
- 矩阵固定 8x8x8 INT8。
- 适配器只做**功能模型**（组合乘加），不是时序收敛/可综合的 NPU。
- 需要 RISC-V 工具链 + Questa 才能实跑。
