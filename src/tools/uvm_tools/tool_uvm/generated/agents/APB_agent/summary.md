<!-- 自动生成 (tool_uvm v0.1.0) — 请勿直接修改本文件 -->

# Agent: `APB`

| Property | Value |
|----------|-------|
| Interface | `APB` |
| Clock | `pclk` |
| Reset | `presetn` |
| Mode | master 🟢 `UVM_ACTIVE` · slave 🟢 `UVM_ACTIVE` |

## 📌 Interface Ports

| Dir | Name | Width | Description |
|-----|------|-------|-------------|
| output | `paddr` | `ADDR_WIDTH` | - |
| output | `pwrite` | 1 | - |
| output | `psel` | 1 | - |
| output | `penable` | 1 | - |
| output | `pwdata` | `DATA_WIDTH` | - |
| input | `prdata` | `DATA_WIDTH` | - |
| input | `pready` | 1 | - |
| input | `pslverr` | 1 | - |

## ⚙️ Parameters

| Parameter | Type | Default |
|-----------|------|---------|
| `ADDR_WIDTH` | `int` | `32` |
| `DATA_WIDTH` | `int` | `32` |

## 📦 Transactions (`APB_master_seq_item` / `APB_slave_seq_item`)

| Field | Type | Compare | Random |
|-------|------|---------|--------|
| `paddr` | `bit [ADDR_WIDTH-1:0]` | ✓ | ✓ |
| `pwrite` | `bit` | ✓ | ✓ |
| `pwdata` | `bit [DATA_WIDTH-1:0]` | ✓ | ✓ |
| `prdata` | `bit [DATA_WIDTH-1:0]` | ✓ | - |
| `pslverr` | `bit` | ✓ | - |

### Constraints (master)

- **`c_paddr_align`**: `{ paddr[1:0] == 2'b00; }`

### Constraints (slave)

- **`c_prdata_range`**: `{ prdata inside {[0:32'hFFFF_FFFF]}; }`

## 📁 Generated File Inventory

| # | File | Role |
|---|------|------|
| 1 | `1_interface/APB_if.sv` | Interface: internal logic + master/slave/monitor clocking + modport |
| 2 | `2_config/APB_master_config.sv` | Master config: drive delay / outstanding / timeout |
| 3 | `2_config/APB_slave_config.sv` | Slave config: response mode / memory / out-of-order / error window |
| 4 | `2_config/APB_system_config.sv` | System config: aggregates master_cfgs[] / slave_cfgs[] |
| 5 | `3_transaction_sequencer/APB_master_seq_item.sv` | Master transaction |
| 6 | `3_transaction_sequencer/APB_slave_seq_item.sv` | Slave transaction (request + response control) |
| 7 | `3_transaction_sequencer/APB_master_sequencer.sv` | Master sequencer |
| 8 | `3_transaction_sequencer/APB_slave_sequencer.sv` | Slave sequencer (+ req_fifo, event-driven) |
| 9 | `4_driver_monitor/APB_master_driver.sv` | Master driver |
| 10 | `4_driver_monitor/APB_slave_driver.sv` | Slave driver (responds) |
| 11 | `4_driver_monitor/APB_master_monitor.sv` | Master monitor |
| 12 | `4_driver_monitor/APB_slave_monitor.sv` | Slave monitor (→ req_fifo) |
| 13 | `5_agent/APB_master_agent.sv` | Master agent |
| 14 | `5_agent/APB_slave_agent.sv` | Slave agent |
| 15 | `7_sequence/APB_master_sequence.sv` | Master sequence |
| 16 | `7_sequence/APB_slave_sequence.sv` | Slave sequence (memory model) |
| 17 | `8_ral/APB_reg_adapter.sv` | RAL reg adapter |
| 18 | `APB_pkg.sv` | Package: includes all class files |
| 19 | `filelist.f` | Compile order: interface → package |

## 🚀 Quick Start

```bash
# Compile (from the agent directory)
vlog -sv -f filelist.f

# Env/bench level compile+sim is handled by the environment/bench tooling
```
