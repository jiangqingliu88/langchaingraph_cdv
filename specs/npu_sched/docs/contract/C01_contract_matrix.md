# C01 契约矩阵

## 1. 定位

契约矩阵是验证计划的**本体**。case 视图（未来 `cases/*.yaml`）只允许引用 `contract_id`，不得复制契约字段；回归、覆盖率、签核全部反查矩阵。

当前工作区是 spec target plan：`data/contract_matrix/` 共 **42 条 spec 契约**，全部 `assume`。执行层尚未接入，当前没有运行证据。

## 2. 行字段（13 列固定）

| # | 列 | 说明 |
|---|---|---|
| 1 | `contract_id` | 全局唯一，正则 `^C-[A-Z]+(?:-[A-Z0-9]+)*-\d{3}$` |
| 2 | `class` | func/if/perf/cfg/res/exc/data/dbg/lp/env/gate/agent/concurrency/integration |
| 3 | `object` | 被验对象 |
| 4 | `description` | 一句话可判定描述 |
| 5 | `source_ref` | spec 引用，如 `SPEC-1.3-6` |
| 6 | `owner` | 契约 owner |
| 7 | `p_level` | P0/P1/P2 |
| 8 | `check_method` | sva/checker/scb/cover/formal/perf/manual |
| 9 | `check_artifact` | 检查产物 ID；当前 assume 用占位 `spec_<class>_artifact` |
| 10 | `gate` | 判定该契约的门禁脚本；当前未执行 |
| 11 | `status` | active/assume/exempt |
| 12 | `assumption` | assume 必填 |
| 13 | `remark` | 备注/推进来源 |

## 3. 当前 42 条 spec 契约

| 类别 | 数量 | 例子 |
|---|---:|---|
| 接口 if | 4 | C-IF-HS-001、C-IF-HS-002、C-IF-START-001、C-IF-DONE-001 |
| 功能 func | 13 | C-FUNC-UNIT-*、C-FUNC-DEP-*、C-FUNC-ISSUE-001、C-FUNC-RSP-* |
| 数据 data | 4 | C-DATA-TAG-001、C-DATA-RMW-001、C-DATA-SYNC-001、C-DATA-VS-001 |
| 性能/时序 perf | 4 | C-PERF-TMU-001、C-PERF-PRIO-001、C-PERF-PARAL-001、C-PERF-START-DONE-001 |
| 配置 cfg | 4 | C-CFG-CSR-001、C-CFG-CIMC-001、C-CFG-TILE-RLS-001、C-CFG-SPAD-EXCL-001 |
| 资源 res | 5 | C-RES-TILE-001、C-RES-PAGE-001、C-RES-DRAM-001、C-RES-SPAD-001、C-RES-RLS-001 |
| 异常 exc | 5 | C-EXC-ILLEGAL-001、C-EXC-ADDR-001、C-EXC-INT-001、C-EXC-CLEAR-001、C-EXC-BLOCK-001 |
| 可观测 dbg | 1 | C-DBG-REG-001 |
| 低功耗 lp | 2 | C-LP-IDLE-001、C-LP-RST-001 |

状态：`active=0`、`assume=42`、`exempt=0`。

## 4. 三权分立

| 检查手段 | 只允许做什么 | 资产 |
|---|---|---|
| SVA | 时序性质 | `sv/sva/*`（未来实现） |
| Checker | 静态规则/编码合法性 | `sv/checker/*` |
| SCB | 数据/状态/计数/顺序/资源比对 | `sv/scb/*` + 独立模型 |

## 5. 状态与推进

| 状态 | 含义 | 门禁要求 |
|---|---|---|
| assume | 已评审但未验证 | assumption 必填；不要求 case/资产 |
| active | 已验证 | case 引用 + 资产锚点 + 运行期激活 + 证据 |
| exempt | 豁免 | `data/exemption.csv` + 理由/审批/有效期 |

当前 42 条全部是 `assume`，所以：

- 没有可签核的 active 契约；
- 没有真实检查资产和证据；
- 先把 `TC_CMDSCHED_RSP_001` 等 planned case 落地，才能逐条转 active；
- 不允许只改 `status=active` 而不补 case/资产/证据。
