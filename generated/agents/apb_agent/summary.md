<!-- 自动生成 (tool_uvm v0.1.0) — 请勿直接修改本文件 -->

# Agent: `apb`

| Property | Value |
|----------|-------|
| Interface | `apb` |
| Clock | `pclk` |
| Reset | `presetn` |
| Activation | 由 env 级 `agents[].is_active` 决定（缺省 `UVM_ACTIVE`）；loopback 套件固定 master-ACTIVE / slave-PASSIVE |

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

## 🏷️ Type Definitions

- `byte_t` = `bit [7:0]`

## 📦 Transactions (`apb_master_seq_item` / `apb_slave_seq_item`)

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

## 🔧 Configuration (`apb_config`)

| Variable | Default | Description |
|----------|---------|-------------|
| `priority_a` | `-` | - |

## 📬 Response Info

- **fifo_depth**: `4`
- **support_out_of_order**: `False`

## 📁 Generated File Inventory

| # | File | Role |
|---|------|------|
| 1 | `1_interface/apb_if.sv` | Interface: internal logic + master/slave/monitor clocking + modport |
| 2 | `2_config/apb_port_config.sv` | Port config: drive/response 统一（port_kind 区分端口类型） |
| 3 | `5_agent/apb_system_config.sv` | System config: aggregates master_cfgs[] / slave_cfgs[] |
| 4 | `3_transaction_sequencer/apb_base_seq_item.sv` | Base transaction: xact_type + base_transaction_vars（master/slave 共用） |
| 5 | `3_transaction_sequencer/apb_master_seq_item.sv` | Master transaction |
| 6 | `3_transaction_sequencer/apb_slave_seq_item.sv` | Slave transaction (request + response control) |
| 7 | `3_transaction_sequencer/apb_master_sequencer.sv` | Master sequencer |
| 8 | `3_transaction_sequencer/apb_slave_sequencer.sv` | Slave sequencer (+ req_fifo, event-driven) |
| 9 | `4_driver_monitor/apb_master_driver.sv` | Master driver |
| 10 | `4_driver_monitor/apb_slave_driver.sv` | Slave driver (responds) |
| 11 | `4_driver_monitor/apb_port_monitor.sv` | Port monitor: port_kind 分支（SLAVE 侧 → slave_mon_ap + req_fifo） |
| 12 | `5_agent/apb_master_agent.sv` | Master agent |
| 13 | `5_agent/apb_slave_agent.sv` | Slave agent |
| 14 | `5_agent/apb_system_vsqr.sv` | System virtual sequencer: 持有同协议全部 master/slave 子 sequencer 句柄 |
| 15 | `5_agent/apb_system_monitor.sv` | System monitor: 直接嗅探 system_if 全端口（{kind, index} 标签） |
| 16 | `7_sequence/apb_master_sequence.sv` | Master sequence |
| 17 | `7_sequence/apb_slave_sequence.sv` | Slave sequence (memory model) |
| 18 | `8_ral/apb_reg_adapter.sv` | RAL reg adapter |
| 19 | `apb_pkg.sv` | Package: includes all class files |
| 20 | `filelist.f` | Compile order: interface → package |

## 🚀 Quick Start

```bash
# Compile (from the agent directory)
vlog -sv -f filelist.f

# Env/bench level compile+sim is handled by the environment/bench tooling
```
