# X01 — 验证资产布局（方法学）

> **这里只定义目标布局与锚点规则，不手写 SV 资产。**
> 实际 `sv/` 由 SignOffAI 的 UVM 生成链路产出（run 目录），再由
> `vagent vplan package-assets` 按本布局整理并登记。

## 1. 目标布局

```text
<run>/sv/
├── README.md
├── interface/
│   └── bind/                            # SVA bind（生成器产出时）
├── agents/<agent>/                      # 自包含接口 agent（全部 .sv 平铺）
├── env/                                 # env + clock/reset + loopback env
├── seq/                                 # sequences / constraints
├── test/                                # UVM tests
├── tb/                                  # 顶层 testbench
│   ├── hdl_top.sv                       #   由 bench/*_tb_top.sv 映射
│   └── hvl_top.sv                       #   预留（内核当前只产单 tb_top）
├── vc/                                  # 编译清单
│   ├── hdl_files.f
│   └── hvl_files.f
├── checkers/                            # 静态规则/编码检查
├── scbs/                                # scoreboard / reference model
├── svas/                                # 时序断言
└── coverage/                            # CG/CP/cross（生成器产出时）
```

`cmdsched_pkg.sv` / `monitor/` 等不在生成器当前产物里的目录**不伪造**：
有文件才落，没有就空着。内核目前只产**单个** `bench/*_tb_top.sv`，映射为
`tb/hdl_top.sv`；`hvl_top.sv` 保留为空占位，等将来拆分 HVL top 再填。

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
