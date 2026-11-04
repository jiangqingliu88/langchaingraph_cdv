<!-- 自动生成 (tool_uvm v0.1.0) — 请勿直接修改本文件 -->

# Agent: `npu_sched_out`

| Property | Value |
|----------|-------|
| Interface | `npu_sched_out` |
| Clock | `clk` |
| Reset | `rst_n` |
| Activation | 由 env 级 `agents[].is_active` 决定（缺省 `UVM_ACTIVE`）；loopback 套件固定 master-ACTIVE / slave-PASSIVE |

## 📌 Interface Ports

| Dir | Name | Width | Description |
|-----|------|-------|-------------|
| input | `clk` | 1 | - |
| input | `rst_n` | 1 | - |
| input | `issue_valid` | 1 | - |
| input | `issue_unit` | [2:0] | - |
| input | `issue_decision` | [1:0] | - |

## ⚙️ Parameters

| Parameter | Type | Default |
|-----------|------|---------|
| `ISSUE_UNIT_WIDTH` | `int` | `3` |
| `ISSUE_DECISION_WIDTH` | `int` | `2` |

## 📦 Transactions (`npu_sched_out_master_seq_item` / `npu_sched_out_slave_seq_item`)

| Field | Type | Compare | Random |
|-------|------|---------|--------|
| `issue_valid` | `bit` | ✓ | ✓ |
| `issue_unit` | `bit [2:0]` | ✓ | ✓ |
| `issue_decision` | `bit [1:0]` | ✓ | ✓ |

### Constraints (master)

- **`data_c`**: `{issue_valid inside {[0:1]}; }`

## 📁 Generated File Inventory

| # | File | Role |
|---|------|------|
| 1 | `1_interface/npu_sched_out_if.sv` | Interface: internal logic + master/slave/monitor clocking + modport |
| 2 | `2_config/npu_sched_out_port_config.sv` | Port config: drive/response 统一（port_kind 区分端口类型） |
| 3 | `5_agent/npu_sched_out_system_config.sv` | System config: aggregates master_cfgs[] / slave_cfgs[] |
| 4 | `3_transaction_sequencer/npu_sched_out_base_seq_item.sv` | Base transaction: xact_type + base_transaction_vars（master/slave 共用） |
| 5 | `3_transaction_sequencer/npu_sched_out_master_seq_item.sv` | Master transaction |
| 6 | `3_transaction_sequencer/npu_sched_out_slave_seq_item.sv` | Slave transaction (request + response control) |
| 7 | `3_transaction_sequencer/npu_sched_out_master_sequencer.sv` | Master sequencer |
| 8 | `3_transaction_sequencer/npu_sched_out_slave_sequencer.sv` | Slave sequencer (+ req_fifo, event-driven) |
| 9 | `4_driver_monitor/npu_sched_out_master_driver.sv` | Master driver |
| 10 | `4_driver_monitor/npu_sched_out_slave_driver.sv` | Slave driver (responds) |
| 11 | `4_driver_monitor/npu_sched_out_port_monitor.sv` | Port monitor: port_kind 分支（SLAVE 侧 → slave_mon_ap + req_fifo） |
| 12 | `5_agent/npu_sched_out_master_agent.sv` | Master agent |
| 13 | `5_agent/npu_sched_out_slave_agent.sv` | Slave agent |
| 14 | `5_agent/npu_sched_out_system_vsqr.sv` | System virtual sequencer: 持有同协议全部 master/slave 子 sequencer 句柄 |
| 15 | `5_agent/npu_sched_out_system_monitor.sv` | System monitor: 直接嗅探 system_if 全端口（{kind, index} 标签） |
| 16 | `7_sequence/npu_sched_out_master_sequence.sv` | Master sequence |
| 17 | `7_sequence/npu_sched_out_slave_sequence.sv` | Slave sequence (memory model) |
| 18 | `8_ral/npu_sched_out_reg_adapter.sv` | RAL reg adapter |
| 19 | `npu_sched_out_pkg.sv` | Package: includes all class files |
| 20 | `filelist.f` | Compile order: interface → package |

## 🚀 Quick Start

```bash
# Compile (from the agent directory)
vlog -sv -f filelist.f

# Env/bench level compile+sim is handled by the environment/bench tooling
```
