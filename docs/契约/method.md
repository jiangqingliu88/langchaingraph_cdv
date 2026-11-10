下面给一套**完整的项目文档包**。定位：这是 `NPU_V2.CMDSCHED 功能覆盖率验证项目` 的交付文档集，覆盖“项目怎么管、验证怎么做、契约怎么建、用例怎么挂、门禁怎么跑、签核怎么过、变更怎么管”。前面给的目录、CSV/YAML、SV 代码是**工程资产**；这里给的是**文档正文的组织与内容**，两者通过 `contract_id`/`case_id`/`cp_id` 互相引用。

文档分五层：**项目层 → 验证层 → 契约层 → 执行层 → 签核层**。

---

## 0. 文档清单与关系

| 编号 | 文档 | 层 | 读者 | 与工程资产关系 |
|---|---|---|---|---|
| P00 | 项目章程 | 项目 | 全员、管理层 | 定范围/目标/组织 |
| P01 | 项目计划 | 项目 | 全员 | 定里程碑/资源/风险 |
| P02 | 配置与变更管理计划 | 项目 | 全员 | 管 `data/`、`cases/`、`sv/`、`seeds/` 版本 |
| V00 | 验证计划（vplan） | 验证 | 验证/设计/架构 | 引用 `data/`、`cases/` |
| V01 | 验证策略 | 验证 | 验证/设计 | 定五手段分工、批次、种子 |
| V02 | 覆盖率计划 | 验证 | 验证 | 引用 `data/cg_list.yaml`、`cp_list.csv` |
| V03 | 用例设计说明 | 验证 | 验证 | 引用 `cases/*.yaml` |
| C00 | 契约方法学总纲 | 契约 | 全员 | 引用 `docs/methodology/M00` |
| C01 | 契约矩阵说明 | 契约 | 验证/设计 | 引用 `data/contract_matrix/*.csv` |
| C02 | 用例视图契约说明 | 契约 | 验证 | 引用 `cases/*.yaml` |
| C03 | SCB/SVA/Checker 分工说明 | 契约 | 验证/设计 | 引用 `sv/scb`、`sv/sva`、`sv/checker` |
| C04 | Agent 与资产契约说明 | 契约 | 验证环境 | 引用 `sv/agents`、`asset_registry.csv` |
| E00 | 回归与门禁说明 | 执行 | 验证/CI | 引用 `regression/regression.yaml` |
| E01 | 种子管理说明 | 执行 | 验证 | 引用 `seeds/baseline.txt` |
| E02 | 覆盖率收集与合并说明 | 执行 | 验证/CI | 引用 `evidence/`、`reports/` |
| S00 | 签核标准与流程 | 签核 | 验证负责人/评审 | 引用 `reports/gate_report.*` |
| S01 | 豁免管理说明 | 签核 | 验证负责人 | 引用 `data/exemption.csv` |
| S02 | 交付物清单 | 签核 | 全员 | 汇总所有交付 |
| X00 | 附录：ID 规范与锚点规范 | 附录 | 全员 | 定命名/注释规则 |
| X01 | 附录：工具与脚本使用说明 | 附录 | 全员 | 引用 `scripts/` |

最小交付集：**P00 + V00 + V02 + C00 + C01 + C02 + E00 + S00 + S02 + X00**。其余按项目节奏补。

---

## 1. P00 项目章程

**目的**：定项目边界、目标、组织、成功标准。

**章节**：
1. 项目背景：HM057 NPU_V2 CMD_SCH 功能覆盖率验证
2. 项目目标：建立约束→激励→覆盖率→收敛闭环，签核 100% 覆盖、0 illegal、无孤立
3. 范围：10 个 CG、Feat-1~40、批次 1~10、P1 七类
4. 不在范围：性能签核、硅后验证、形式化全量证明（列为 P1/后续）
5. 组织与角色：验证负责人、验证工程师、设计接口人、CI 负责人
6. 成功标准：`gate_full` 全绿、追溯无孤立、种子稳定、豁免审批
7. 关键依赖：CDD、接口文件、参考模型、仿真环境、CI
8. 风险：错误注入机制缺失、无多版本 DUT、形式化人力不足
9. 交付物：vplan、覆盖率报告、契约矩阵、用例视图、门禁报告、签核记录

**关键段落示例**：
> 本项目以 CDD 功能契约为权威源，按 10 个覆盖率组组织验证；每个契约在 `data/contract_matrix/` 登记，每个用例在 `cases/` 声明挂载，门禁由 `scripts/` 自动执行；签核以 `reports/gate_report.json` 全绿且 `docs/signoff/` 审批为准。

---

## 2. P01 项目计划

**章节**：
1. 里程碑：骨架 → 数据 → 样板 case → 批次 1~10 → P1 → 签核
2. 排期：13 周（与前面落地顺序一致）
3. 资源：人力、仿真机时、VCS/URG、DuckDB、CI
4. 依赖关系：文档 → data → sv → regression → evidence → gate
5. 风险与缓解：数据漂移、锚点缺失、门禁误报、种子不稳
6. 评审点：vplan 评审、契约矩阵评审、样板 case 评审、签核评审

**里程碑表**：

| 周 | 里程碑 | 产出 | 门禁 |
|---|---|---|---|
| 1 | 骨架 | 目录 + README + 文档大纲 | 评审通过 |
| 2 | 数据 | `data/` 可 lint | `make lint` |
| 3 | 校验 | schemas + lint 脚本 | lint PASS |
| 4 | 样板 | `TC_CMDSCHED_RSP_001` 可编译 | 编译 PASS |
| 5 | 仿真 | 批次 8 跑通 | 覆盖率产出 |
| 6 | 门禁 | `make ci` 跑通 | gate_case_view |
| 7~10 | 扩批 | 批次 1~10 | 各 suite PASS |
| 11~12 | P1 | P1 七类 + REL case | p1 suite PASS |
| 13 | 签核 | gate_report 全绿 | 签核评审 |

---

## 3. P02 配置与变更管理计划

**章节**：
1. 版本控制：git 管 `docs/`、`data/`、`cases/`、`sv/`、`scripts/`、`regression/`、`seeds/`；`evidence/`、`reports/`、`db/` gitignore
2. 分支策略：main + feature + release
3. 变更影响分析：DUT 变更 → 契约矩阵 → cases → sv 锚点 → regression → 签核
4. 双源禁止：`regression.yaml` 由脚本生成，`xlsx` 只做视图
5. 版本记录：`docs/change_log.md` + `data/change_log.csv`
6. 评审流程：契约矩阵变更需 owner 评审；新增 case 需契约引用评审
7. 回滚：`seeds/history/`、`data/` 版本标签

**变更影响分析表模板**：

| 变更 | 影响契约 | 影响 case | 影响资产 | 影响 suite | 动作 |
|---|---|---|---|---|---|
| 新增 Feat | 新增 contract | 新增/改 case | 新增 sva/checker/scb | 新增/改 suite | 追溯矩阵更新 |
| 删除功能 | contract 改 illegal | case 移目标 bin | checker 加规则 | suite 改 | 豁免/记录 |
| 接口改名 | 改 if.csv | 改 case sva_bind | 改 adapter/bind | 改 suite | 契约测试 |
| 内部重构 | 契约不变 | 不变 | 改 monitor 适配 | 不变 | 锚点检查 |

---

## 4. V00 验证计划（vplan）

**章节**（与前面 `docs/vplan.md` 一致，这里给每章关键内容）：

1. 概述
   - 目的：定义 CMD_SCH 功能覆盖率模型、约束、种子、门禁、签核
   - 范围：10 个 CG、Feat-1~40、P1 七类
   - 术语：CMD/ISTB/MST/SPAD/CIMC/DRAM/sync/noc_fence/RAW/WAW/WAR/tile/page/CP/CG/Bin/Cross/种子基线/平台期
2. 设计功能概述
   - 调度器职责：握手、反压、依赖、发射、ISTB、start-done-rls、release
   - 接口信号表：cmd/rsp/start/done/rls/反压/中断/scalar/cfg
   - 二级模块：ISTB、decode、scoreboard、dispatch、cmd_int_perf
3. 验证契约策略
   - 契约全景与分层：需求/事务/接口/实现
   - 五手段分工：CG 度量、case 激励、SCB 结果、SVA 时序、Checker 规则
   - 契约矩阵 vs 用例视图：本体 vs associate view
   - 保障方式：规则/LLM/人三色
4. 覆盖率策略
   - CG 划分原则：功能契约、不按 RTL 模块
   - 10 个 CG 总览表（ID/名称/需求/覆盖点数/交叉数/目标）
   - 采样原则：monitor 采样、iff 有效周期、联合采样、illegal_bins
5. Case 分解与批次策略
   - case 与 CG 多对多
   - 10 个批次演进逻辑
   - 种子管理：基线 7 步、平台期、种子表
6. SCB/SVA/Checker 分工原则
   - SCB 结果、SVA 时序、Checker 规则
   - 边界与主/辅
7. 门禁与签核
   - 三层门禁：矩阵、视图、回归 CI
   - 签核条件
   - 豁免流程
8. 需求追溯说明
   - Feat-1~40 全映射结论；无孤立需求/契约/case
9. 版本记录
   - V.0.0.1 → V.1.0.0 → V.1.1.0
附录 A：`data/` 字段说明
附录 B：门禁脚本用法
附录 C：Agent 契约

**关键段落示例**：
> 覆盖率组按 CDD 功能维度划分，不按 RTL 子模块划分。每个 CG 聚焦一类功能契约，组内用覆盖点、交叉、非法/忽略 bin 描述；组间用跨组交叉和需求追溯矩阵闭环。每个 bin 必须能映射到约束、场景和测试批次。

---

## 5. V01 验证策略

**章节**：
1. 验证层次：模块级 CMD_SCH、IP 级、SoC 集成（集成层另立文档）
2. 五手段：CG/case/SCB/SVA/Checker
3. 激励策略：定向 + 随机 + 种子基线 + 随机混合
4. 检查策略：SCB 数据/状态/计数/顺序、SVA 时序、Checker 规则
5. 覆盖率策略：10 CG、100% bin、illegal 0、ignore 审批
6. 回归策略：smoke/batch/directed/p1/full
7. 缺口回灌：缺口→根因→约束/场景→case 契约更新
8. 复用策略：跨 DUT adapter/bind/参数化模型

---

## 6. V02 覆盖率计划

**章节**：
1. CG 总览（10 组，引用 `data/cg_list.yaml`）
2. 覆盖点与 bin（引用 `data/cp_list.csv`）
3. 组内交叉与跨组交叉（引用 `data/cross_list.csv`）
4. 非法 bin 与忽略 bin（illegal_bins、ignore_bins 审批）
5. 采样位置与事件（按 monitor 分）
6. 约束映射（引用 `data/constraint_map.csv`）
7. 批次映射（引用 `data/batch_seed.csv`）
8. 覆盖率目标与签核（100%/0 illegal/ignore 审批）

**10 个 CG 总览表**（md 里只放这张，明细引用 CSV）：

| CG ID | 名称 | 需求 | CP 数 | 交叉数 | 目标 |
|---|---|---|---|---|---|
| CG_CMDSCHED_ITYPE | 指令类型 | Feat-3,28 | 4 | 2 | 100% |
| CG_CMDSCHED_INSTB | ISTB 管理 | Feat-19 | 4 | 2 | 100% |
| CG_CMDSCHED_DEP | 数据依赖 | Feat-2,5,7,10,11~14 | 4 | 2 | 100% |
| CG_CMDSCHED_UNIT | 执行单元 | Feat-1,8,9,10,15~18,23 | 6 | 2 | 100% |
| CG_CMDSCHED_ISSUE | 发射决策 | Feat-19 | 4 | 2 | 100% |
| CG_CMDSCHED_MEM | 存储资源 | Feat-6,21,22 | 6 | 2 | 100% |
| CG_CMDSCHED_RSP | 返回值握手 | Feat-2,4,7,20,26,27 | 7 | 2 | 100% |
| CG_CMDSCHED_EXCP | 异常中断 | Feat-28,29,30 | 5 | 1 | 100% |
| CG_CMDSCHED_PERF | 性能 Debug | Feat-31~40 | 4 | 0 | 100% |
| CG_CMDSCHED_CSR | CSR 低功耗 | Feat-24,25 | 6 | 0 | 100% |

---

## 7. V03 用例设计说明

**章节**：
1. case 是 associate view，不替代契约矩阵
2. case 分解维度：基础/指令类型/ISTB/依赖/hazard/并行/存储/返回值/异常性能CSR/随机混合
3. sequence/场景设计：raw_chain、parallel、barrier、xd1、ls_parallel、tmu、illegal、bp、perf、third_inst、tile_map、rsp_rmw、int_info
4. 约束三层：指令/序列/场景
5. 用例视图 YAML 字段说明（引用 `schemas/case_contract.schema.json`）
6. 挂载原则：按 `contract_refs` 挂载，不全挂
7. 运行证据：声明 vs 运行
8. 失败分类：CG 未命中/SCB 0 比对/SCB mismatch/SVA 0 触发/SVA fail/Checker 0 检查/Checker violation
9. 缺口回灌入口

---

## 8. C00 契约方法学总纲

**章节**（对应 `docs/methodology/M00`）：
1. 术语：契约、契约矩阵、associate view、CG/SCB/SVA/Checker、assume/guarantee/check/cover/measure/gate
2. 契约全景：功能/接口/时序性能/配置/资源/异常/数据/可观测/低功耗/环境/流程/复用/形式化/软硬件/并发/集成/可靠性/CDC/元契约/配置组合/版本/回归/文档
3. 五手段分工
4. 契约分层：需求/事务/接口/实现；锚点选择
5. 四维完备性：对象×形态×粒度×生命周期
6. 生命周期：发现→定义→实现→校验→维护→签核
7. 保障方式：规则/LLM/人三色
8. 门禁体系：矩阵/视图/回归 CI
9. 与 vplan 关系

**关键原则**：
> 契约锚定需求/功能契约和事务契约，不锚定实现细节；接口变化由 adapter/bind 吸收，内部变化由 monitor 适配层吸收；参考模型独立且参数化；契约版本化并做变更影响分析；LLM 输出必须人审+规则校验；签核和豁免不能 delegation。

---

## 9. C01 契约矩阵说明

**章节**：
1. 矩阵与视图关系：本体 vs associate view，多对多
2. 15 类矩阵 + P0/P1 扩展清单
3. 行字段：contract_id/category/content/form/authority/check_method/owner/stability/fail_mode/gate/feat_ids/guarantee_color/status
4. ID 规范：`C-类别-子类-序号`
5. 形态：assume/guarantee/check/cover/measure/gate
6. 保障方式三色：绿/黄/红
7. 维护：版本化、owner 评审、变更记录
8. 矩阵门禁：唯一 ID、字段齐全、Feat 映射、无孤立

**矩阵清单表**（引用 `data/contract_matrix/`）：

| 文件 | 类别 | 示例 ID | P 级 |
|---|---|---|---|
| func.csv | 功能 | C-FUNC-DEP-001 | P0 |
| if.csv | 接口 | C-IF-HS-001 | P0 |
| perf.csv | 时序性能 | C-PERF-PRIO-001 | P0/P1 |
| cfg.csv | 配置 | C-CFG-CSR-001 | P0 |
| res.csv | 资源 | C-RES-TILE-001 | P0 |
| exc.csv | 异常 | C-EXC-INT-001 | P0 |
| data.csv | 数据一致性 | C-DATA-TAG-001 | P0 |
| dbg.csv | 可观测 | C-DBG-REG-001 | P1 |
| lp.csv | 低功耗 | C-LP-IDLE-001 | P1 |
| env.csv | 环境 | C-ENV-MON-001 | P0 |
| gate.csv | 流程 | C-GATE-COV-001 | P0 |
| agent.csv | Agent | C-AGENT-SELF-001 | P0 |
| concurrency.csv | 并发 | C-CONC-DEADLOCK-001 | P0 |
| integration.csv | 集成 | C-INT-ASSUME-001 | P0 |
| p1/*.csv | P1 七类 | C-REL-TIMEOUT-001 等 | P1 |

---

## 10. C02 用例视图契约说明

**章节**：
1. 定位：associate view，不替代矩阵
2. 字段：case_id/test_name/batch/contract_refs/cg/scb/sva/checker/sequences/constraints/pass_criteria/seed_baseline/pre_config/owner/status
3. 三种载体：登记表、YAML、UVM test 注册；推荐 YAML 一 case 一文件
4. 挂载原则：挂载≠激活，门禁校验激活次数>0
5. 运行时校验：声明 vs 实际对比
6. 失败分类与定位
7. 视图门禁：声明完整、运行一致、多激活补声明、少激活查挂载
8. 缺口回灌入口

**示例**：引用 `cases/TC_CMDSCHED_RSP_001.yaml` 和 `cases/TC_CMDSCHED_EXCP_001.yaml`，说明 `contract_refs` 如何引用 `C-FUNC-RSP-002`、`C-IF-HS-002`、`C-DATA-TAG-001`，`scb.mount` 如何挂 `rsp_scb/lmem_scb/rmw_scb/fifo_prio_scb`。

---

## 11. C03 SCB/SVA/Checker 分工说明

**章节**：
1. 三权分立：SCB 结果、SVA 时序、Checker 规则
2. SCB：数据/状态/计数/顺序/资源不泄漏；独立参考模型、参数化、按 tag 比对
3. SVA：握手/反压保持/start-done-rls/互斥/状态机/中断/TMU 仲裁/链表
4. Checker：编码/参数/跨模块约定/配置/地址空间/资源/NIU 规则
5. 边界：SCB 不做时序、SVA 不做数据比对、Checker 不做覆盖度量
6. 冗余策略：主/辅明确，失败以主定位
7. 契约归属表：功能契约→三手段
8. 失败定位：先看 CG 是否命中，再看三手段

**契约归属表**（md 里放这张，明细引用 `data/`）：

| 功能契约 | CG | Case | SCB | SVA | Checker |
|---|---|---|---|---|---|
| RAW/WAW/WAR | DEP | dep/hazard | hazard_scb | sva_dep_issue | chk_hazard_gran |
| ISTB 管理 | INSTB | instb | instb_scb | sva_istb_chain | chk_instb_dp |
| 发射决策 | ISSUE | basic/dep | issue_scb | sva_start_done_rls | chk_inst_id_match |
| MST/并行 | UNIT | parallel/hazard | unit_scb | sva_niu_rules/sva_tmu_arb | chk_niu_rules |
| 存储资源 | MEM | mem | res_model_scb | sva_res_release | chk_tile_map |
| 返回值/握手 | RSP | rsp | rsp_scb/lmem_scb/rmw_scb/fifo_prio_scb | sva_handshake_rsp/sva_fifo_prio | chk_tag_match |
| 异常/中断 | EXCP | excp | int_scb | sva_int | chk_illegal_encoding/chk_addr_space |
| 性能/debug | PERF | perf | perf_scb/debug_scb | sva_perf_window | chk_perf_range |
| CSR/低功耗 | CSR | csr | csr_scb | sva_idle_icg | chk_csr_default |

---

## 12. C04 Agent 与资产契约说明

**章节**：
1. agent 在契约链中的位置：驱动激励、观测事务、执行接口契约
2. 目录组织：`agents/<name>/` 自包含 agent/driver/sequencer/monitor/adapter；内部 monitor 独立 `sv/monitor/`
3. agent 契约：C-AGENT-MODE/DRV/SEQ/MON/ADP/SELF、C-ENV-MON
4. active/passive 契约差异
5. 资产登记表：`data/asset_registry.csv`，字段含 agent_owner/mode
6. 锚点规范：`// AGENT:`、`// DRIVER:`、`// SEQUENCER:`、`// MONITOR:`、`// ADAPTER:`
7. 扫描与门禁：自包含、模式一致、driver 契约存在、monitor CP 存在、复位不驱动
8. 资产登记表维护：脚本生成初稿，人补绑定

**agent 契约表**（md 里放这张）：

| contract_id | 契约 | form | 绑定资产 | 门禁 |
|---|---|---|---|---|
| C-AGENT-MODE-001 | active/passive 与 env 一致 | check | `agents/*/agent.sv` | gate_agent |
| C-AGENT-DRV-001 | driver 按接口契约驱动 | guarantee | `agents/*/driver.sv` | 协议 SVA |
| C-AGENT-SEQ-001 | sequencer 调度与 case 一致 | check | `agents/*/sequencer.sv` | 声明 vs 运行 |
| C-AGENT-MON-001 | monitor 事务完整、采样正确 | check | `agents/*/monitor.sv` | 事务契约测试 |
| C-AGENT-ADP-001 | adapter 映射正确 | check | `agents/*/adapter.sv` | 已知用例比对 |
| C-AGENT-SELF-001 | agent 自包含 | check | 目录扫描 | gate_agent |
| C-ENV-MON-001 | 内部 monitor 不驱动不干扰 | check | `monitor/*.sv` | 事务契约测试 |

---

## 13. E00 回归与门禁说明

**章节**：
1. 回归 YAML 定位：执行视图，不重复契约内容
2. suite 划分：smoke/batch01~10/directed/p1/full
3. 字段：test_name/case_id/cg/seeds_ref/gate/tags
4. 生成与校验：`gen_regression_yaml.py` 生成，`lint_regression.py` 校验
5. 门禁串联：lint→sim→evidence→merge→gate→full
6. CI 集成：`.gitlab-ci.yml` stages
7. 失败分类与重跑：flake 管理
8. 覆盖率合并：`urg merge`，按 `coverage_targets` 检查

**suite 表**（md 里放这张）：

| suite | 内容 | 触发 | 门禁 |
|---|---|---|---|
| smoke | 每 CG 一个代表 case | PR | gate_case_view |
| batch01~10 | 批次演进 | nightly | gate_case_view |
| directed | 定向补洞 | 缺口回灌 | gate_case_view |
| p1 | P1 七类 | nightly | gate_case_view |
| random_mix | 防过拟合 | nightly/release | gate_case_view |
| full | 全量 | release | gate_full |

---

## 14. E01 种子管理说明

**章节**：
1. 种子基线建立 7 步
2. 平台期判定
3. 种子表：`seeds/baseline.txt`，按 test 名分组
4. 种子分级：`urg -grade`
5. 探索种子与基线种子
6. 种子与 suite 绑定：`seeds_ref`
7. 种子稳定性：重跑一致、flake 标记
8. 历史归档：`seeds/history/`

---

## 15. E02 覆盖率收集与合并说明

**章节**：
1. 编译覆盖率：line/cond/fsm/tgl/functional
2. 仿真覆盖率：`-cm_dir` 按 seed 命名
3. 合并：`urg -dir *.vdb -cm merge`
4. 按 suite 合并：`merge_by_suite`
5. 目标检查：`coverage_targets` 10 个 CG 100%
6. 报告：`reports/coverage_summary.md`
7. 回填证据：`collect_evidence.py` → `evidence/json`
8. 声明 vs 运行：`gate_case_view.py`

---

## 16. S00 签核标准与流程

**章节**：
1. 签核条件：10 CG 100%、交叉 100%、illegal 0、ignore 审批、追溯无孤立、种子稳定、豁免记录
2. 三层门禁：矩阵/视图/回归 CI
3. 签核流程：gate_full 全绿 → 评审 → `docs/signoff/signoff_v1.1.0.md` 签字
4. 签核表：`docs/signoff/signoff_checklist.md`
5. 失败处理：失败分类→定位→修复→重跑→再签核
6. 版本签核：每个 release 版本签核记录

**签核检查表**：

| 检查项 | 标准 | 证据 | 结论 |
|---|---|---|---|
| 覆盖点 | 100% bin | `reports/coverage_summary.md` | |
| 交叉 | 100% 有意义组合 | 同上 | |
| 非法 bin | 0 命中 | `gate_report.json` | |
| 忽略 bin | 已审批 | `data/exemption.csv` | |
| 需求追溯 | 无孤立 | `reports/contract_trace_report.md` | |
| 用例视图 | 声明=运行 | `gate_report.json` | |
| 矩阵 | 无孤立契约 | `reports/orphan_report.md` | |
| Agent | 自包含/模式一致 | `gate_agent` 报告 | |
| 种子 | 基线稳定 | `seeds/baseline.txt` + 重跑 | |
| 豁免 | 有理由/审批/日期 | `data/exemption.csv` | |

---

## 17. S01 豁免管理说明

**章节**：
1. 豁免适用：架构不可达、暂不支持、工具限制
2. 豁免流程：发现→分析→申请→审批→记录→复查
3. 豁免记录表：`data/exemption.csv`，字段 bin/cp_id/reason/approver/date/status
4. 豁免不能用于：约束可覆盖但没抽到、DUT bug、覆盖点未实现
5. 定期复查：每个 release 复查豁免是否仍成立
6. 示例：`excl_cfg`（独占 SPAD 暂不支持）

---

## 18. S02 交付物清单

**章节**：
1. 文档交付：P00~S02、X00~X01
2. 数据交付：`data/` 全部
3. 用例交付：`cases/*.yaml`
4. 代码交付：`sv/`、`model/`
5. 脚本交付：`scripts/`
6. 回归交付：`regression/regression.yaml` + `batchNN.sh`
7. 种子交付：`seeds/baseline.txt`
8. 报告交付：`reports/gate_report.json/xlsx`、`coverage_summary.md`、`contract_trace_report.md`、`orphan_report.md`
9. 签核交付：`docs/signoff/`
10. 版本标签：git tag `v1.1.0`

**交付清单表**：

| 类别 | 路径 | 签核人 | 状态 |
|---|---|---|---|
| 文档 | docs/ | 验证负责人 | |
| 契约矩阵 | data/contract_matrix/ | owner | |
| 覆盖率计划 | data/cg_list.yaml, cp_list.csv | 验证负责人 | |
| 用例视图 | cases/ | 验证工程师 | |
| 验证代码 | sv/ | 验证工程师 | |
| 参考模型 | model/ | 验证工程师 | |
| 门禁脚本 | scripts/ | CI 负责人 | |
| 回归 | regression/ | 验证负责人 | |
| 种子 | seeds/ | 验证工程师 | |
| 报告 | reports/ | 验证负责人 | |
| 签核 | docs/signoff/ | 验证负责人 | |

---

## 19. X00 附录：ID 规范与锚点规范

**章节**：
1. ID 规范：`contract_id`、`cg_id`、`cp_id`、`cross_id`、`case_id`、`asset_id`、`seq_id`、`constraint_id`
2. 命名规范：coverpoint/cross/assert/checker/scb/seq/test/regression/seed
3. 注释锚点：`// CASE_ID:`、`// SEQ_ID:`、`// CONSTRAINT_ID:`、`// C-`、`// SCB:`、`// AGENT:`、`// DRIVER:`、`// SEQUENCER:`、`// MONITOR:`、`// ADAPTER:`
4. 回归脚本头：`# CASE: ...; BATCH: ...`
5. 种子文件格式：`test_name: seed1 seed2 ...`
6. 锚点检查：`lint_sv_anchor.py`

**ID 规范表**：

| ID | 正则 | 示例 |
|---|---|---|
| contract_id | `^C-[A-Z]+(-[A-Z0-9]+)+-[0-9]{3}$` | C-FUNC-RSP-002 |
| cg_id | `^CG_CMDSCHED_[A-Z]+$` | CG_CMDSCHED_RSP |
| cp_id | `^CP_CMDSCHED_[A-Z]+_[0-9]{3}$` | CP_CMDSCHED_RSP_003 |
| cross_id | `^X_CMDSCHED_[A-Z]+_[0-9]{3}$` | X_CMDSCHED_RSP_001 |
| case_id | `^TC_CMDSCHED_[A-Z_]+_[0-9]{3}$` | TC_CMDSCHED_RSP_001 |
| asset_id | `^A[0-9]{4}$` | A0101 |
| feat_id | `^Feat-[0-9]+(~[0-9]+)?$` | Feat-11~14 |

---

## 20. X01 附录：工具与脚本使用说明

**章节**：
1. 环境依赖：Python3、pandas、openpyxl、jsonschema、duckdb、VCS、URG
2. `make` 目标说明：lint/scan/sim/batch/evidence/db/gate/report/ci
3. 脚本清单与用法：每个脚本一行说明
4. CI 集成：`.gitlab-ci.yml` stages
5. xlsx 视图生成：`export_xlsx.py`
6. 常见问题：lint 失败、锚点缺失、门禁不一致

**脚本清单表**：

| 脚本 | 用途 | 输入 | 输出 |
|---|---|---|---|
| lint_data.py | CSV/YAML schema+孤立 | data/, cases/ | 控制台/退出码 |
| lint_md.py | md 引用 ID 一致 | docs/ | 控制台 |
| lint_sv_anchor.py | 源码锚点检查 | sv/ | 控制台 |
| lint_regression.py | 回归 YAML 一致性 | regression/ | 控制台 |
| scan_assets.py | 生成资产登记初稿 | sv/ | asset_registry.csv |
| load_db.py | 导入 DuckDB | data/, cases/ | vplan.duckdb |
| query_gates.sql | 孤立/引用查询 | db | 结果集 |
| collect_evidence.py | 回填证据 | evidence/ | evidence/json |
| gate_matrix.py | 矩阵门禁 | data/ | gate_report |
| gate_case_view.py | 视图门禁 | cases/, evidence/ | gate_report |
| gate_agent.py | agent 门禁 | sv/agents/ | gate_report |
| export_xlsx.py | 生成评审视图 | data/, reports/ | gate_report.xlsx |
| gen_coverage_summary.py | 覆盖率汇总 | evidence/urg | coverage_summary.md |
| gen_regression_yaml.py | 生成回归 YAML | cases/, data/, seeds/ | regression.yaml |

---

## 21. 文档与工程资产的挂接

| 文档 | 引用工程资产 | 挂接方式 |
|---|---|---|
| V00 vplan | `data/`、`cases/` | 章节引用 sheet/ID，不枚举明细 |
| V02 覆盖率计划 | `cg_list.yaml`、`cp_list.csv`、`cross_list.csv` | 总览表 + 引用 |
| C01 契约矩阵说明 | `data/contract_matrix/*.csv` | 清单表 + 引用 |
| C02 用例视图说明 | `cases/*.yaml` | 字段说明 + 示例 |
| C03 分工说明 | `sv/scb`、`sv/sva`、`sv/checker` | 归属表 + 锚点 |
| C04 Agent 说明 | `sv/agents/`、`asset_registry.csv` | 契约表 + 锚点 |
| E00 回归门禁 | `regression/regression.yaml` | suite 表 + 引用 |
| S00 签核 | `reports/gate_report.*` | 检查表 + 证据 |
| S01 豁免 | `data/exemption.csv` | 记录表 |
| S02 交付 | 全部 | 交付清单 |

---

## 22. 评审与签核流程

```
P00/P01 评审（项目启动）
  ↓
V00/V01/V02/V03 评审（验证计划）
  ↓
C00/C01/C02/C03/C04 评审（契约方法学）
  ↓
E00/E01/E02 评审（执行）
  ↓
样板 case 评审（TC_CMDSCHED_RSP_001）
  ↓
批次 1~10 评审（每个批次 gate_case_view PASS）
  ↓
P1 评审（p1 suite PASS）
  ↓
S00 签核（gate_full 全绿）
  ↓
S01 豁免审批
  ↓
S02 交付
```

每个评审点产出：评审记录、问题清单、关闭记录，存 `docs/review/`。

---

## 23. 一句话总结

**完整项目文档包按五层组织：项目层（P00 章程、P01 计划、P02 变更管理）、验证层（V00 vplan、V01 策略、V02 覆盖率计划、V03 用例设计）、契约层（C00 方法学、C01 契约矩阵、C02 用例视图、C03 三权分立、C04 Agent/资产）、执行层（E00 回归门禁、E01 种子、E02 覆盖率收集）、签核层（S00 签核、S01 豁免、S02 交付），外加 X00 ID/锚点规范、X01 工具说明；文档只放原则、结论、引用，明细全在 `data/`、`cases/`、`sv/`、`regression/`、`seeds/`，通过 ID 和锚点互相挂接；评审流程从项目启动到样板 case、批次 1~10、P1、签核、交付逐层推进。** 需要我把其中任意一份文档展开成完整正文（比如 V00 vplan 全文或 C01 契约矩阵说明全文），可以指定编号。