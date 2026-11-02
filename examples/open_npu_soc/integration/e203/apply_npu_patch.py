"""NICE/NPU 接入说明（已不再需要打补丁）。

NPU 现在是**子系统级 IP**：`e203_subsys_top` 里 `u_npu_top` 与
`u_e203_subsys_main` 同级，NICE 请求/响应/ICB 已经从 `e203_subsys_main`
边界引出（见 `integration/e203/README.md` 的 4 个文件）。

编译时适配器/GEMM 仍以“文件表末尾同名覆盖”的方式编入：

  * 先编 `e203_hbirdv2/rtl/e203/**/*.v`；
  * 再编 `npu/npu_top.sv`、`npu/nice_disp/e203_nice_npu_adapter.sv`、
    `npu/npu/int8_gemm.sv`（Questa 后编覆盖前编）。

直接跑：

    python -m src.cli.commands soc c-run examples/open_npu_soc --case C-GEMM-8X8

本脚本只打印说明，不做任何写操作。
"""
from __future__ import annotations


def main(argv=None) -> int:
    print("NPU 已挂在 e203_subsys_top 层级（u_npu_top 与 u_e203_subsys_main 同级）。")
    print("适配器/GEMM 由编译文件表末尾同名覆盖接入，无需 patch E203 源树。")
    print("跑 C 用例：python -m src.cli.commands soc c-run "
          "examples/open_npu_soc --case C-GEMM-8X8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
