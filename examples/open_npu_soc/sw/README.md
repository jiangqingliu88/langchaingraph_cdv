# Software（E203 bare-metal）

v0.1 的两条路径：

- **参考 TB**：`npu/nice_disp/nice_cmd_sequencer.sv` 驱动 NICE 命令时序，
  不执行这里的 C 程序；
- **E203 路径**：真实 CPU 执行这里的固件，NICE custom3 驱动子系统级的
  `u_npu_top`。

文件：

- `startup/startup.S`：设置栈、跳 `main`、把返回值写 `x3`，最后跳到
  `0x80000086`（E203 TB 的 tohost 标记）。
- `tests/gemm_8x8.c`：写 A/B/descriptor → START → 轮询 STATUS → ACK →
  与 C 版 golden 比较；返回 0 表示 PASS。
- `cases.yaml`：C 用例清单（IP 覆盖关系）。

构建：`python sw/build_sw.py`（需要 `toolchain/setup_toolchain.py` 装的
RISC-V 工具链），产物是 `gemm_8x8.elf/.hex/.verilog/.dump`。运行与波形：

```bash
python -m src.interfaces.cli.commands soc c-run examples/open_npu_soc \
    --case C-GEMM-8X8 -o output_c_C-GEMM-8X8
python -m src.interfaces.cli.commands soc wave output_c_C-GEMM-8X8
```

NICE 编码（func3 的 bit1/bit2 是 E203 的 rs1en/rdwen）：

| 指令 | func3 | 说明 |
|---|---|---|
| START | 2 | 读 rs1=descriptor 地址 |
| STATUS | 4 | 写回 `{irq, done}` 到 rd |
| ACK | 0 | 清 irq |
