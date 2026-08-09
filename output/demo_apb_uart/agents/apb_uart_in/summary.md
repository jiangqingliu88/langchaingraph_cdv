# Agent: `apb_uart_in`

| Property | Value |
|----------|-------|
| Interface | `apb_uart_in` |
| Clock | `clk` |
| Reset | `rst` |
| Mode | 🟢 ACTIVE |

## 📌 Interface Ports

| Dir | Name | Width | Description |
|-----|------|-------|-------------|
| input | `clk` | 1 | - |
| input | `rst` | 1 | - |
| output | `data` | `DATA_WIDTH` | - |
| output | `valid` | 1 | - |
| input | `ready` | 1 | - |

## ⚙️ Parameters

| Parameter | Type | Default |
|-----------|------|---------|
| `DATA_WIDTH` | `int` | `32` |

## 📦 Transaction (`apb_uart_in_seq_item`)

| Field | Type | Compare | Random |
|-------|------|---------|--------|
| `data` | `bit [DATA_WIDTH-1:0]` | ✓ | ✓ |

### Constraints

- **`valid_c`**: `{{ data inside {{[0:255]}}; }}`

## 📁 Generated File Inventory

| # | File | Role |
|---|------|------|
| 1 | `apb_uart_in_interface.sv` | Physical interface: ports, clocking block, modport |
| 2 | `apb_uart_in_interface_structure.sv` | Interface structure / typedef definitions |
| 3 | `apb_uart_in_transaction.sv` | Transaction (sequence item): fields + constraints |
| 4 | `apb_uart_in_config.sv` | Configuration object |
| 5 | `apb_uart_in_sequencer.sv` | Sequencer: controls stimulus flow |
| 6 | `apb_uart_in_driver.sv` | Driver: drives signals on the bus |
| 7 | `apb_uart_in_monitor.sv` | Monitor: samples signals, collects coverage |
| 8 | `apb_uart_in_agent.sv` | Top-level agent: instantiates driver/monitor/sequencer |
| 9 | `apb_uart_in_pkg.sv` | Package: imports all components |
| 10 | `apb_uart_in_base_seq.sv` | Base sequence template |
| 11 | `apb_uart_in_coverage_collector.sv` | Functional coverage collector |
| 12 | `apb_uart_in_callback_base.sv` | Base callback class (extensible) |
| 13 | `apb_uart_in_callback_example.sv` | Example callback implementation |

## 🔁 Loopback Self-Test

Self-contained testbench (no DUT required): driver → monitor closed loop.

| File | Role |
|------|------|
| `loopback/apb_uart_in_loopback_env.sv` | Loopback environment: connects driver → scoreboard → monitor |
| `loopback/apb_uart_in_loopback_scb.sv` | Scoreboard: compares expected vs actual transactions |
| `loopback/apb_uart_in_loopback_test.sv` | Test case: starts sequence, checks results |
| `loopback/apb_uart_in_loopback_tb.sv` | Testbench top: instantiates interface + env, generates clock/reset |

## 🚀 Quick Start

```bash
# Compile (single agent loopback)
vlog -f inputs/filelists/filelist_apb_uart_in_lb.f

# Simulate
vsim -c apb_uart_in_loopback_tb +UVM_TESTNAME=apb_uart_in_loopback_test -do 'run -all; quit -f'
```
