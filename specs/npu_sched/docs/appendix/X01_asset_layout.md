# X01 — 验证资产布局（方法学）

> **这里只定义目标布局与锚点规则，不手写 SV 资产。**
> 实际 `sv/` 由 SignOffAI 的 UVM 生成链路产出（run 目录），再由
> `vagent vplan package-assets` 按本布局整理并登记。

## 1. 目标布局

```text
<run>/sv/
├── README.md
├── cmdsched_pkg.sv                      # package 聚合
├── interface/
│   ├── cmdsched_if.sv
│   ├── cmdsched_if_v2.sv
│   └── bind/
│       ├── bind_sva_handshake.sv
│       ├── bind_sva_start_done.sv
│       ├── bind_sva_int.sv
│       └── bind_sva_lp.sv
├── agents/                              # 接口 agent，自包含
│   ├── cmdsched_cmd_agent/
│   │   ├── cmdsched_cmd_agent.sv
│   │   ├── cmdsched_cmd_driver.sv
│   │   ├── cmdsched_cmd_sequencer.sv
│   │   ├── cmdsched_cmd_monitor.sv
│   │   └── cmdsched_cmd_adapter.sv
│   ├── cmdsched_rsp_agent/
│   ├── cmdsched_mst_agent/
│   ├── cmdsched_mem_agent/
│   ├── cmdsched_int_agent/
│   └── cmdsched_csr_agent/
├── monitor/                             # 内部观测 monitor，env 所有
│   ├── cmdsched_monitor_base.sv
│   ├── cmdsched_decode_monitor.sv
│   ├── cmdsched_scoreboard_monitor.sv
│   ├── cmdsched_sp_inst_monitor.sv
│   └── cmdsched_int_perf_monitor.sv
├── coverage/
│   ├── cmdsched_coverage.sv
│   ├── cmdsched_cov_pkg.sv
│   └── cmdsched_cov_cfg.sv
├── sva/                                 # 时序断言
├── checker/                             # 静态规则/编码检查
├── scb/                                 # 独立参考模型比对
├── seq/                                 # 场景序列
├── test/                                # UVM test
└── env/
    ├── cmdsched_env.sv
    └── cmdsched_env_cfg.sv
```

## 2. 锚点规则

每个生成的文件由 `package-assets` 写上：

```systemverilog
// SOURCE: <run 内原始路径>
// ARTIFACT: <artifact_id>
// CONTRACT_ID / CONTRACT_REFS: <C-* ...>   # 能确定时写，不能确定留 (none)
// CASE_ID: <TC_* ...>                      # test 文件
// STATUS: candidate
```

`sv/asset_registry.csv` 列：

```text
artifact,kind,path,owner,status,contract_ids,case_ids,source
```

- 状态一律从 `candidate` 起步；
- `active` 只能由 gate 依据编译/运行证据推进；
- 没有锚点/没有证据的资产不能冒充 active。

## 3. 流程位置

```text
VPlan docs/specs + contract_matrix
  → (本目录) target plan / case 契约
  → SignOffAI UVM 生成链路（现有 kernel）
  → <run>/agents、env、coverage、...
  → vagent vplan package-assets <run>
  → <run>/sv/（本布局）+ sv/asset_registry.csv
  → 可选：vplan clean-layout <run> --apply 删除顶层 agents/bench/env/build
  → 编译/仿真/覆盖率（后续）+ gate
```

方法与锚点规范以本文件为准；`vplan package-assets` 在 SignOffAI 里实现。

## 4. 生成目录 → sv/ 映射（全部 `.sv` 都要有落点）

| 生成目录 | sv/ 落点 |
|---|---|
| `agents/*/1_interface/` | `sv/interface/` |
| `agents/*/2_config/`、`3_transaction_sequencer/`、`4_driver_monitor/`、`5_agent/`、`8_ral/` | `sv/agents/<agent>/` |
| `agents/*/7_sequence/`、`env/seqs/`、`env/cons/` | `sv/seq/` |
| `agents/*/loopback/`、`bench/`、`env/*.sv` | `sv/env/` |
| `env/coverage/` | `sv/coverage/` |
| `env/tests/` | `sv/test/` |
| `env/rtl_sc/` | `sv/scb/` |
| `coverage/*_cov_if.sv` | `sv/interface/` |
| `coverage/*bind*.sv` | `sv/interface/bind/` |

`vplan package-assets` 输出 `skipped=0` 才算“排完”；有未映射文件会逐条打印。
