# Software（E203 集成 seam）

v0.1 的 Questa 仿真用 `rtl/cpu/nice_cmd_sequencer.sv` 驱动 NICE 命令时序，
**不执行这里的 C 程序**。原因是先把「数据通路正确性」与「E203 启动/工具链」
两个变量隔开。

这里的文件是 M1 之后接真实 E203 的落点：

- `startup/startup.S`：设置栈、跳 `main`。
- `tests/gemm_8x8.c`：写 A/B → 写 NICE 命令 → 等 IRQ → 读 C → 与 golden 比较。

接 E203 时需要替换的只有：

1. `nice_cmd_sequencer` → E203 NICE 适配层；
2. `mmio_*` → NICE 自定义指令/CSR 访问；
3. 构建脚本 → RV32 工具链 + 固件镜像。
