# SignOffAI 架构现状与修复报告（2026-11-10）

> 分析对象：`C:\Users\liujiangqing\Desktop\cdv_advanced`
> 当前分支：`refactor/langgraph-migration`
> 历史修复提交：`98eb87b7`；本次 Supervisor 重构提交见分支 HEAD
> 基线 tag：`v2.1.0-pre-supervisor` / `v2.2.0-pre-agent-loop`
> 修复范围：除 `isa_ir_tools` / TB player 与 EDA 依赖外的已知问题

---

## 0. 结论

本次修复把“架构原则正确、但测试/legacy/文档/安全没收口”的状态收口到了可提交、可回归的基线：

- 主套件 **1182 passed / 0 failed / 4 skipped**；
- 工作台 **692 passed / 0 failed**；
- 架构守卫 `[architecture] OK`；
- 当前树 secret scan clean；
- boards / legacy 空壳 / 文档链接 / 版本号已处理；
- VPlan 的 gate 选 run、active 漂移、TP realization、矩阵 schema、uvm_arch 映射已增强。

仍未闭环、且按要求不修的两项：

1. `isa_ir_tools` / TB player 的集成与自动化测试（独立工具，按要求跳过）。
2. 需要 QuestaSim 的 VPlan 真实 E2E（按要求跳过 EDA 相关问题）。

因此当前状态应表述为：

> **架构与工程基线已收口；VPlan 规划层可 build、可审阅；真实 EDA 闭环仍需在装 Questa 的机器上跑一轮。**

---

## 1. 架构原理（修复后仍然是这套）

### 1.1 Supervisor 主图 + 四个专家子图

```text
CLI / Workbench
  → app/services
  → L2 Supervisor 主图（只路由：design / verify / debug / coverage / human_review / audit）
       ├─ design_expert 子图（front → design → model）
       ├─ verify_expert 子图（verify → env_arch_check）
       ├─ debug_expert 子图（round_bump → ops → debug_functional，失败才回环）
       ├─ coverage_expert 子图（coverage → decide → governor → approval → 动作）
       └─ human_review（Debug 连续 5 次返工 → interrupt() 等人）
  → 专家子图内部节点（旧 24 节点单图已删除）
  → 8 个 executor（front/design/model/verify/ops/coverage/debug/audit）
  → L1 / L3 / L4 / L5
  → core（RunContext / ArtifactStore / EventStore / Provenance / Quality）
```

- **唯一入口**是 `src.agents.supervisor.graph.build_closed_loop_graph()` →
  Supervisor 主图；旧 24 节点单图/回滚开关已删除。
- Supervisor 只读状态、只写 `next_agent / design_done / verify_done /
  debug_done / coverage_done / execution_done / supervisor_visits /
  supervisor_trace / audit_gate`，不调 LLM、不跑工具。
- 专家子图各自保留循环：design 执行器内部“生成→编译→重试”，execution 子图
  保留轮次/审批/覆盖率闭环；`audit_gate` 是纯代码硬审计。
- 只有 `design` / `debug` 直接调 LLM；所有 LLM 调用走 `call_llm`，流程与 pass/fail 保持确定性。

### 1.2 契约是构建物

| 契约 | 回答 | 权威落点 |
|---|---|---|
| dplan | RTL/参考模型怎么实现 | `<run>/inputs/dplan/` + `contract/dplan_map.json` |
| VPlan `C-*` | 该验证什么、验收依据 | `specs/<module>/data/contract_matrix/*.csv` |
| Case IR 四集合 | 用例用什么证明自己 | `<run>/coverage/case_ir.json` |
| Contract OS v3 | 每条义务现在什么状态 | `<run>/contract/{contract.yaml,obligations.json}` |
| IP release | IP 供应方/SoC 消费方绑定 | `spec/ip_releases/<ip>.json` |

### 1.3 规划层与执行层分离

```text
spec → front bootstrap → docs/specs + data + cases
     → 人工 review（哈希绑定）
     → vplan build（PLAN_ONLY：TP/Case/契约，无 EDA）
     → vplan execute（复用 verify 内核：UVM/回归/覆盖率/证据）
     → vplan link → vplan gate → signoff
```

- `PLAN_ONLY` 明确不可签核；
- 未审阅/过期项目，`vplan execute` 与 `vplan gate --apply` 会拒绝；
- 契约 `assume → active` 只由证据 gate 推进，不靠手改 CSV。

### 1.4 证据驱动与失败响亮

- TP：`planned → HIT/OBSERVED/BACKDOOR_HIT` 只由 run 证据推进；
- case：`planned → executed` 只由逐用例证据推进；
- 义务：`PROVEN / PARTIAL / MISSING / PENDING_BACKEND / NOT_APPLICABLE / NOT_EXECUTED`；
- 缺 EDA → `EDA_MISSING` / `BLOCKED_EDA_MISSING`；缺日志 → `NO_EVIDENCE`；
- `None ≠ False`，`planned ≠ covered`，`assume ≠ active`。

### 1.5 `sv/` 资产布局与锚点

```text
<run>/sv/
├── interface/ agents/ env/ seq/ test/ tb/ vc/
├── checkers/ scbs/ svas/ covgs/ cons/
└── asset_registry.csv
```

每个文件带 `ARTIFACT / SOURCE / CONTRACT_REFS / CASE_ID / STATUS` 锚点；`package-assets` 整理、`scan-assets --check` 核对。

---

## 2. 本次修复清单

### 2.1 测试与守卫

| 问题 | 修复 |
|---|---|
| `verify/main.py` 626 行 > registered 600 | 接口投影拆到 `src/skills/verify/steps/interface_spec.py`，main 降到 522 行 |
| `architecture_guard` 只在 >2000 时检查 registered | watched 文件始终执行 `registered` 预算；guard 与测试同源 |
| `test_tools_boards` 2 项失败 | `boards.py` 按实际目录重建；`generation/__init__` 从 boards 派生 |
| `test_vplan_bootstrap` 2 项失败 | 契约计数改为“2 功能 + 1 接口组 = 3” |
| `test_staged_regression` 时间戳 flaky | 测试显式设置 expand 的 mtime |
| `test_cli_evidence` 依赖仓库内 tmp | monkeypatch `_git_changed_files` 返回 None |
| 旧 casemodel / isa_gen / verification_os 空壳 | 删除空目录、pycache、0 字节 `archture.md` |
| 主套件 | 从 7 failed 收敛到 **1182 passed / 4 skipped** |
| 工作台 | **692 passed**；CI deselect 已移除 |

### 2.2 安全

- 重写 `TODO.md`：删除全部环境变量/凭据内容，改成技术债入口。
- 新增 `scripts/check_secrets.py`：扫描 git tracked 文件中的高置信 token 前缀；接入 CI lint 与 pre-commit。
- `SECURITY.md` 改为“当前树扫描 + 历史泄露需轮换/清史”的准确表述。
- 当前工作区 secret scan clean。

> 历史提交里仍可能存在旧 token。轮换凭据 + `git filter-repo` 清历史需要外部操作与 force push，本次未自动改写历史。

### 2.3 文档与 legacy

- `README.md`：移除失效的 `docs/design` / `docs/notes` 链接与已删除的 `case-model` 命令；文档入口改为 ARCHITECTURE / CONTRACT_FLOW / PROJECT_STATUS。
- `ARCHITECTURE.md`：更新基线日期与测试数字；工具板块表/包表/文件地图改为实际目录；修正 regression_tools、case_view 等路径；标注历史 E2E 产物不可复核。
- `src/tools/README.md`：按实际板块与当前包重写。
- `known_limitations`：player 边界改为“SV 包已实现，但 stimulus_plan/verify 主链尚未接线”。
- 恢复 README 缺失的工作台截图 `docs/images/workbench-overview.png`。
- 删除 `docs/契约/vplan.md` 0 字节占位。

### 2.4 VPlan 增强

| 增强 | 实现 |
|---|---|
| gate 选 run 不再依赖 append 顺序 | `link_run` 写 `linked_at`；`_latest()` 按时间取最新 |
| active 漂移可见 | `_evaluate_contract` 增加 `active_drift`；`vplan gate` 输出 `active_unsupported` 并以 exit 1 提示 |
| TP realization 可显式绑定 | 支持 `realization_kind` / `stimulus_field` / `realization_agent` / `realization_sequence`；只有文字时仍保持 observe |
| 契约矩阵 schema | `_load_matrix` 校验 13 列与 `assume/active/exempt` 状态 |
| CSV 原子写 | `apply_active` 改用 `atomic_write_text` |
| uvm_arch 精确映射 | scoreboard 先按 `check_artifact/object` 绑定；无声明才回退全部 func/data |
| 测试 | 新增 latest/drift、矩阵 schema、TP realization、uvm_arch 绑定回归测试 |

### 2.5 本轮追加（review 粒度 / 布局校验 / 备份 / lint）

| 增强 | 实现 |
|---|---|
| review 只绑权威输入 | `review.py` 改为 `vplan_review_v2`：`data/{dimensions,execution_meta,...}.csv` 等生成 sidecar 不进哈希，但 `data/contract_matrix/*`、`docs/specs`、`cases` 仍进；status 输出 `skipped_generated` |
| `sv/` 布局可校验 | 新增 `expected_layout_kind` / `layout_mismatches`；`vplan scan-assets --check` 额外核对 `vc/hdl_files.f`、`vc/hvl_files.f` 与文件名→子目录 |
| 矩阵写入可回滚 | `apply_active` 写入前把原 CSV 备份到 `data/contract_matrix/.backup/` |
| legacy 布局提示 | `SIGNOFFAI_UVM_LAYOUT=legacy` 打弃用 warning，仅用于旧 run 复现 |
| config 可 lint | `pyproject.toml` 增加 `[tool.ruff.lint.isort] known-first-party`，避免 `src` 被误判为第三方 |

### 2.6 Supervisor + 专家子图重构（默认入口）

| 改造 | 实现 |
|---|---|
| 主图/子图分离 | `src/agents/supervisor/graph.py`：主图 9 节点 `init → supervisor → design/verify/debug/coverage_expert → human_review → audit_gate → finalize` |
| 循环 | `debug_expert` 保留 `round_bump → ops → debug_functional → round_bump` 环形边；`coverage_expert` 保留 `coverage → decide → governor → approval → 动作`；动作非 CONVERGE 时交回主图重新派 debug |
| 状态拆分 | `PipelineState` 增加 `next_agent / design_done / verify_done / debug_done / coverage_done / execution_done / debug_attempts / human_reviewed / supervisor_visits / supervisor_trace / audit_gate`；`SupervisorView` 只读投影，专家不决定下一步 |
| 人工门 | Debug 连续 5 次返工 → 主图 `human_review` 用 `interrupt()` 挂起；无 checkpoint 时显式 `auto_no_checkpoint` 并 warning |
| 硬审计 | `audit_gate` 用 `verify_package` 重算文件/包哈希；失败写 `AUDIT_BLOCKED`、`terminal_reason=audit_gate_failed`，不进入 READY 签核 |
| 工具循环 | `src/agents/runtime/tool_loop.py`：LLM 输出 `tool`/`final` JSON，按 DebugTools 白名单执行，最多 6 步；`SIGNOFFAI_AGENT_LOOP=on` 时接入 `debug_expert`，失败回退确定性管线 |
| Design 工具循环 | `src/agents/design/loop.py`：`SIGNOFFAI_DESIGN_LOOP=on` 且 design 未产出 RTL 时，用 `read_file/write_file（仅 rtl/*.sv）/list_rtl/check_rtl` 补写；仍为空则 `r_after_design` 走 audit |
| Verify/Coverage 工具循环 | `verify_expert` 接 UVM 工具（find_spec_yaml/jinja_render/check_static/read_file/write_file）；`coverage_expert` 只读报告 + 写 `coverage/agent_notes.md`；`SIGNOFFAI_AGENT_LOOP=on` 总开关，单专家 env 可覆盖 |
| 硬审计 | `audit_gate` 调确定性 `n_audit` 后，独立核对 `report.json` 与 `signoff_evidence/manifest.json`，不信任子图汇报 |
| 目录 | 物理迁移到 `src/agents/{supervisor,design,verify,debug,coverage,runtime,gates}`；旧 `l2_orchestration/{graph,nodes,supervisor,routers}.py` 已删除 |
| 版本 | 2.6.0；新增 `v2.1.0-pre-supervisor` / `v2.2.0-pre-agent-loop` 基线 tag |

---

## 3. 当前验证结果

| 项 | 结果 |
|---|---|
| 主套件 | **1182 passed / 0 failed / 4 skipped** |
| 工作台 | **692 passed / 0 failed**（PySide6 回调析构 warning，无 failed） |
| 架构守卫 | `[architecture] OK` |
| 编译检查 | `compileall` 退出码 0 |
| secret scan | `scripts/check_secrets.py` → clean |
| VPlan status | `specs/npu_sched`：26 req / 43 features / 46 contracts / 46 TP / 20 cases |
| VPlan build | PLAN_ONLY 成功；`signable=false` |
| VPlan gate | 46 contracts 全 `assume`、46 blocked、0 eligible（无 linked run） |
| VPlan execute | 未审阅项目被 review gate 拒绝；dry-run 正常 |

### 3.1 VPlan 当前读数

```text
specs/npu_sched:
  requirements 26 / features 43 / topics 10
  contracts 46（assume 46）
  testpoints 46（planned 46）
  cases 20（planned 20）
  review: false（docs_specs/data/cases 未审阅）
  gate: 46 blocked / 0 eligible / 0 changed
```

这说明门禁是活的，也说明**当前还没有“已验证”的 VPlan run**。

---

## 4. 仍然存在的边界

| 边界 | 状态 | 说明 |
|---|---|---|
| VPlan 真实 E2E | 未闭环 | 需 Questa 环境按 `review → execute → link → gate` 跑一轮 |
| `isa_ir_tools` / TB player | 未修（按要求） | 工具可冒烟，但无仓库内测试、未接 VPlan execute/verify 主链 |
| 历史 secret | 部分修复 | 当前树已清除；历史 token 需轮换 + 历史清理 |
| review 粒度 | **已拆分（v2）** | 生成 sidecar（`data/dimensions.csv` 等）不再进审阅哈希；权威输入变化仍会使审阅过期 |
| `sv/` 与 legacy 双布局 | **已加校验与弃用提示** | `scan-assets --check` 核对 `vc/*.f` 与文件名→子目录布局；`SIGNOFFAI_UVM_LAYOUT=legacy` 打弃用 warning；旧 run 仍只读兼容 |
| 多后端 / IP 覆盖率 / SoC v2 | 未变 | 仍按 `known_limitations` 的 open 项推进 |
| LLM / EDA 路径 | 未实测 | 本机无 Questa/LLM key |
| ruff lint | 未本地验证 | 本机无法安装 ruff；CI lint 仍需在有 ruff 的环境确认 |

---

## 5. 下一步建议

### P0（发布前）

1. 轮换历史中可能泄露的 token，并与协作者协调 `git filter-repo` 清历史后 force push。
2. 在装 Questa 的机器上跑一次完整 VPlan E2E：
   `review → build → execute → link → gate → evidence verify`。
3. 把 E2E 的 commit hash / spec_hash / run_id / package_hash 写进发布说明。

### P1（1–2 周）

1. VPlan TP realization 从 `data/dimensions.csv` 自动回填（当前已支持表内显式声明）。
3. `uvm_arch` 用 `check_artifact` 做完整资产映射，并在 `scan-assets` 校验。
4. 给矩阵写入加备份/diff；给 review 加增量哈希缓存。

### P2（1 个月）

1. `sv/` 单布局，legacy 退场。
2. 主套件/工作台性能优化。
3. IP 级覆盖率（M2）、SoC 证据 v2、证据门/质量门从 report 转 block。
4. ISA IR / TB player 的独立测试与接线决策（按要求暂不修）。

---

## 6. 提交与推送

- Gitee：`https://gitee.com/liujiangqing/cdv_a.git`
- 分支：`refactor/langgraph-migration`
- 本次提交：Supervisor + 专家子图重构（见 `git log -1`）
- Tag：`v2.6.0`（最终推送后创建）

---

> 本报告与代码同批提交。所有数字来自 2026-11-10 本机实测；EDA/LLM 路径未实测。
