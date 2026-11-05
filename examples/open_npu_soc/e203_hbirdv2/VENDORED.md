# Vendored Hummingbird E203 (subset)

This directory contains a **functional subset** of the upstream
[Hummingbird E203](https://github.com/riscv-mcu/e203_hbirdv2) project, used by
the `open_npu_soc` reference flow. It is licensed under the Apache License 2.0
(see [LICENSE](LICENSE)).

The following bulky, non-functional assets are intentionally **not** committed
to keep the repository lean:

- `doc/` — generated documentation site and images
- `pics/` — board photographs
- `fpga/` — prebuilt FPGA configuration files (`.mcs`)
- `riscv-tools/**/*.dump` and `**/*.rpt` — generated disassembly and benchmark reports

RTL, testbenches, scripts, and toolchain sources required for simulation are
preserved. To work with the complete upstream tree, clone the upstream
repository and overlay the integration files from `examples/open_npu_soc/`.
