按你的交付目标，架构调整的原则是：**不推翻五层引擎和 LangGraph，只在 `verify` / `ops` / `coverage` / `debug` / `audit` 上把“交付契约显式化”。** 核心是把现在隐含的 scoreboard / checker / 接线关系变成一等交付件和单一真相源。

下面按优先级给调整方案。

---

## 一、总调整思路

当前架构的问题不是“没有闭环”，而是：

- **scoreboard / checker 不是显式交付件**，只在 `env/` 和 `assertions/` 里隐含；
- **agent ↔ scb/checker 的接线关系没有单一真相源**，散在模板里；
- **用例的约束仍在 sequence 侧**，批次 test 类只挂 config_db，没接约束；
- **波形与覆盖率同 run 归档的契约不显式**；
- **CLI 审批断链**，`approve/reject` 不驱动图恢复。

所以调整方向是：

```text
verify 内部拆成：
  agent → env → scb → checker → cov → tests → wave
每段都有显式交付件 + 单一接线 YAML + 签核门禁
```

---

## 二、把 `verify` 内部拆成显式子阶段

当前 `verify` 是一个执行器，产出 `env/ agents/ assertions/ coverage/`。建议在它内部拆成 7 个显式子阶段，每个都有交付件和门禁：

| 子阶段 | 交付件 | 门禁 |
|---|---|---|
| `agent_gen` | `agents/<if>_agent.sv` | monitor 有 analysis_port；driver/sequencer 齐 |
| `env_gen` | `env/<env>.sv` | agent 例化、config_db、vif 连接 |
| `scb_gen` | `env/<env>_scb.sv` | 接 monitor 事务，调 `model/` 参考模型 |
| `checker_gen` | `assertions/<env>_checker.sv` | SVA 协议/时序/复位/CDC 检查 |
| `cov_gen` | `coverage/` + `env_cov_bins.yaml` | 两条采样通道声明齐 |
| `tests_gen` | `{env}_batch_test.sv` + sequence + YAML | 批次同名 test 类存在 |
| `wave_cfg` | `sim_modes` 声明 `cov+wave` | 波形文件与 run 归档 |

**代码落点**：`src/executors/verify/main.py` 里加子阶段调度；模板放 `src/executors/verify/templates/`。  
**图节点**：`l2_orchestration/stages.py` 里给 `verify` 增加子节点元数据，或保持 24 节点不变，把子阶段作为 `verify` 内部状态机。

---

## 三、定义 agent ↔ scb/checker 的接线契约（单一真相源）

这是最关键的一步。现在接线散在 `env.sv.j2`、`env_cov.sv.j2`、`tb_top.sv.j2` 里，漂了不报错。

建议新增一份 YAML：

```yaml
# <run>/env/env_bindings.yaml
agents:
  - name: apb_master
    seq_item: APB_master_seq_item
    monitor_port: apb_master_mon
    scb_export: scb.apb_master_export
    checker_export: checker.apb_master_export
    cov_sample: stimulus

scoreboard:
  name: scb
  model_ref: model/apb_uart_ref
  compare: transaction_level   # 或 signal_level

checker:
  name: checker
  assertions:
    - assertions/apb_protocol_sva.sv
    - assertions/apb_reset_sva.sv

coverage:
  dut_if: apb_uart_if
  bind_module: apb_uart
  channels:
    - sample: stimulus
      covergroup: cg_apb_master
    - sample: dut
      covergroup: cg_dut
```

**四个读点必须都走这一份**：

- `env.sv.j2` 读它连 scb/checker；
- `env_cov.sv.j2` 读它连覆盖率；
- `tb_top.sv.j2` 读它连 `dut_if`；
- `build_filelist_for_tb` 读它收编译清单。

**纪律**：`dut_if` 接口类型名和 bind 实例名只有这一处出处。漂了就是句柄为空、覆盖率恒 0%，而编译加载都不报错。

**代码落点**：`l1_infrastructure/layout.py:find_env_bindings`，与 `find_case_model` 同构，单一判据。

---

## 四、把用例约束从 sequence 侧收回到模型

当前批次 test 类只把“打哪几个维度、用什么方法”挂 config_db，约束仍在 sequence 侧。调整：

```text
constraint.yaml（已有）→ 生成 sequence 约束 + 批次 test 类
```

具体：

- `constraints` 命令已能把 `themes[].method`（`D/G/SPCL/RND/RPLY`）生成策略 + 组合器；
- 需要把它接到 `tests_gen` 子阶段，让 `{env}_batch_test.sv` 的 `config_db` 里挂的是**生成的约束句柄**，不是空壳；
- 批次 test 类体里不铺激励，但要有 `uvm_config_db#(...)::set` 把约束对象传下去；
- sequence 侧读这个约束对象，而不是自己写死。

**代码落点**：`src/tools/casemodel_tools/coverage.py` 的 `constraints` 分支 + `verify/templates/batch_test.sv.j2`。

---

## 五、覆盖率采样通道显式化

两条通道已经在方法学里定义清楚：

| | `sample: stimulus` | `sample: dut` |
|---|---|---|
| 信号在哪 | agent 事务对象 | DUT 内部/端口 |
| 谁采 | `env_cov.sv.j2` 的 `cg_<agent>` | `env_cov.sv.j2` 的 `cg_dut` |
| 看得到什么 | 只有激励侧 | 内部状态、输出端口 |

调整点：

- 在 `env_bindings.yaml` 里显式声明每个 agent 的 `cov_sample: stimulus` 或 `dut`；
- `env_cov_bins.yaml` 的 `dut_if` 单一出处；
- DUT 探针走 `bind`，接口文件被 `build_filelist_for_tb` 收进编译清单，排在 RTL 之后；
- `coverage_plan.yaml` 四张表同批生成：§3 覆盖点、§5 批次、§6 种子、§8 需求追溯。

**代码落点**：`src/tools/casemodel_tools/coverage.py` 模块头就是方法学，保持只此一份规则。

---

## 六、波形与覆盖率同 run 归档

当前 `--sim-mode cov+wave` 已是默认。调整点：

- `sim_modes.py` 里把 `cov+wave` 展开成 `cov_enabled + wave_enabled`，确保 `vlog` 带 `+cover`、`vsim` 带波形；
- `ops` 执行器产出 `regression.json` 时，把波形文件路径写进去；
- `coverage` 执行器产出 `coverage.json` 时，把 ucdb SHA256 归档；
- `dump <run_id>` 证据包里同时含波形、ucdb、regression.json、coverage.json。

**代码落点**：`src/tools/regression_tools/sim_modes.py` + `l1_infrastructure/infrastructure.py:archive_coverage`。

---

## 七、补 CLI 审批断链

这是“可治理”支柱的缺口。当前：

- `interrupt()` + checkpointer 只有 GUI 路径启用；
- `vagent approve/reject` 只写 `approval.json`，不驱动图恢复。

调整：

- CLI `approve/reject` 写 `approval.json` 后，调 LangGraph 的 `update_state` + `invoke(None, config)` 恢复图；
- checkpointer 从 GUI 路径抽到公共 `runtime.py`，CLI 和 GUI 共用；
- 无人值守时 `--approval auto` 直接跳过人工节点。

**代码落点**：`src/cli/commands.py` + `l2_orchestration/runtime.py`。

---

## 八、参考模型层：先替后删

这是当前 17 个失败测试的全部来源。方向：

- 参考模型改为 **TLM1.0 + SQL 库**；
- 现有信号级 RTL 实现先保留，新实现并行跑；
- 替换完成前，17 个失败是已知基线，不是回归。

**代码落点**：`src/executors/model/` + `tests/test_ref_model_wiring.py`。

---

## 九、调整后的 verify 内部结构

```text
verify
├── agent_gen      → agents/<if>_agent.sv
├── env_gen        → env/<env>.sv
├── scb_gen        → env/<env>_scb.sv        ← 新增显式
├── checker_gen    → assertions/<env>_checker.sv ← 新增显式
├── cov_gen        → coverage/ + env_cov_bins.yaml
├── tests_gen      → {env}_batch_test.sv + sequence + YAML
└── wave_cfg       → sim_modes cov+wave
         ↑
   env_bindings.yaml（单一真相源）
```

---

## 十、优先级排序

| 优先级 | 调整 | 理由 |
|---|---|---|
| **P0** | scoreboard / checker 显式化 + `env_bindings.yaml` 单一真相源 | 你的核心交付目标，现在最缺 |
| **P0** | 批次约束从 sequence 收回到 `constraint.yaml` | 用例交付的完备性 |
| **P1** | CLI 审批断链修复 | 可治理支柱 |
| **P1** | 波形 + ucdb 同 run 归档契约 | 你的波形交付 |
| **P2** | 参考模型 TLM1.0 + SQL | 17 个失败的根因 |
| **P2** | 工具白名单角色对齐 | 现在 8 个执行器只有 2 个凑上交集 |

---

## 一句话

**架构不用大改，只需要在 `verify` 内部把 agent / env / scb / checker / cov / tests / wave 七段显式化，用 `env_bindings.yaml` 做单一接线真相源，把批次约束从 sequence 收回到模型，补上 CLI 审批恢复和波形归档契约。** 这样你的 interface agent → env → scb/checker → 用例 → 覆盖率 → 波形 就能作为一条可签核的交付链收敛。


/////////////////////////
有，而且不少。前面说的是“把交付契约显式化”，下面这些是**在显式化之后还能再挖一层**的优化，按“直接影响覆盖率收敛”到“工程健康”排序。

---

## 一、收敛判据本身可以更聪明

现在只有 `--target 80 --max-rounds 5`，这是最粗的收敛控制。

| 优化 | 做什么 | 落点 |
|---|---|---|
| **边际收益早停** | 连续 N 轮覆盖率增长 < 阈值（如 1%）就 `CONVERGE` 或换策略，不空烧轮次 | `l3_decision/decision_engine.py` |
| **多目标收敛** | 不只看覆盖率，同时看 bug 数、未闭合 gap 数、时间预算 | `decide` 节点 |
| **收敛曲线** | `coverage trend` 已有命令，接进 `decide` 做趋势判据 | `coverage` 执行器 |
| **分阶段目标** | smoke 60% → 全量 80% → 长跑 90%，而不是一步到位 | `--target` 支持阶段列表 |

**为什么重要**：现在 `max-rounds 5` 是硬上限，跑满 5 轮可能覆盖率早就平了，后 3 轮全是浪费。

---

## 二、种子管理可以更深

现在种子声明在批次上，`count` 展开成 `base + i - 1`。缺的是：

| 优化 | 做什么 |
|---|---|
| **种子有效性评估** | 跑了 18 条，覆盖点只增了 2 个 → 这批种子质量低，标记出来 |
| **种子去重** | 不同 seed 产生相同事务序列 → 去重，别重复跑 |
| **失败种子保留** | 失败 seed 自动进 `regression` 重跑队列，不丢 |
| **种子淘汰** | 连续多轮无新增覆盖的 seed 降权或淘汰 |
| **探索比例自适应** | `explore` 占比按边际收益动态调，不是写死 3/18 |

**落点**：`casemodel_tools/coverage.py` 的种子管理段 + `regression_tools`。

---

## 三、LLM 生成质量可以前置校验

`async_fifo` 被 `max_tokens=8192` 截断丢弃，这是症状。根因是**生成完才编译，编译不过再丢**。

| 优化 | 做什么 |
|---|---|
| **动态 token 预算** | 按模块端口数/代码规模估 token，而不是固定 8192 |
| **分段生成** | 端口声明、内部逻辑、时序块分段生成，每段闭合校验 |
| **输出 schema 校验** | 生成 SV 前先校验结构（端口闭合、`endmodule` 存在、begin/end 配对） |
| **端口闭合门禁** | `vlog` 之前先做轻量语法检查，省一次编译 |
| **生成-校验-修复小循环** | 在 `design` 内部先自修复，不直接丢给 `debug` |

**落点**：`tools/lib/llm_call.py` 的 token 预算 + `executors/design/main.py` 的 `_verify_ip_rtl`。

---

## 四、决策可解释性与回放

现在决策是确定性的，但**为什么选这个动作**没有结构化记录。

| 优化 | 做什么 |
|---|---|
| **决策依据记录** | 每个动作记录：哪个 gap、哪条规则、经验统计是什么 |
| **决策回放** | 给定 run_id + 轮次，复现当时为什么选 `GENERATE_DIRECTED_TEST` 而不是 `EXPAND_SEEDS` |
| **RL 冷启动策略** | 没有经验时怎么选，现在只说了“经验只做降级建议” |
| **动作预算** | 一轮只做一个动作还是并行，现在没显式策略 |
| **动作优先级** | `FIX_COMPILE` > `FIX_MODEL` > 软动作，已有，但软动作之间没有序 |

**落点**：`l3_decision/decision_engine.py:523` 附近 + `evidence` 层。

---

## 五、覆盖率方法学可以再深

| 优化 | 做什么 |
|---|---|
| **排除审计** | `coverage exclude` 要有理由、审批、追溯，不能随便排 |
| **illegal_bins 误报** | 某些模式下“非法”组合其实合法，需要模式感知 |
| **交叉爆炸控制** | 交叉数量上限、自动分组、高维交叉降维 |
| **断言覆盖率** | checker 的 SVA 也应该有覆盖率，不只是功能覆盖率 |
| **覆盖点冗余检测** | 两个 coverpoint 永远同增同减 → 冗余，合并 |
| **需求追溯闭环** | §8 需求追溯已有，但没提“需求未覆盖”怎么报警 |

**落点**：`casemodel_tools/coverage.py` + `assertions/` + `coverage` 执行器。

---

## 六、波形可以按需采，不是全采

默认 `cov+wave` 全采，长跑波形会爆。

| 优化 | 做什么 |
|---|---|
| **失败窗口裁剪** | 只采失败前后 N 个周期，不采全程 |
| **按 test 分段** | 每个 test 一个波形文件，不是整个 run 一个 |
| **波形与 ucdb 时间对齐** | 覆盖率 gap 能跳到波形对应时刻 |
| **波形大小预算** | 超预算自动降采样或分段 |
| **波形归档策略** | 全量波形只留最近 N 轮，历史轮次留裁剪版 |

**落点**：`regression_tools/sim_modes.py` + `ops` 执行器。

---

## 七、可观测性与成本

现在没有 run 级 tracing 和成本统计。

| 优化 | 做什么 |
|---|---|
| **节点级 tracing** | 每个节点的输入/输出/耗时/token 消耗 |
| **LLM 成本统计** | 按 run、按执行器、按调用点统计 token 和费用 |
| **EDA license 占用时长** | 哪个阶段占了多少 license 时间 |
| **失败分类学** | 编译失败/仿真失败/覆盖率失败/签核失败/EDA 缺失，标准化输出 |
| **告警/通知** | 长跑结束、失败、需要人工审批时通知 |

**落点**：`l2_orchestration/evidence/` + `tools/lib/llm_call.py`。

---

## 八、守卫测试可以再扩展

现有守卫测试是亮点，但还能加：

| 优化 | 做什么 |
|---|---|
| **变异测试** | 故意改坏代码，看守卫测试能不能抓到 |
| **基线冻结** | 17 个已知失败不能偷偷变 xfail，要有冻结机制 |
| **属性测试** | case 模型的属性（如 bins 并集 = 全空间） |
| **跨文件引用守卫** | 不只 case 模型，所有“单一真相源”都钉住 |
| **注入契约测试** | mock 是否符合真实接口 |

**落点**：`tests/` + `casemodel_tools/tests/`。

---

## 九、interface agent 专项优化

你重点是 interface agent，这块可以更产品化：

| 优化 | 做什么 |
|---|---|
| **协议模板库** | APB/AXI/CHI 标准 agent 模板，不是每次从零生成 |
| **agent 复用** | 跨模块复用同一 agent，参数化配置 |
| **monitor 采样点定义** | 在哪个时钟沿、什么条件下采样，显式声明 |
| **agent 配置化** | 同一 agent 不同参数（数据宽度、地址位宽、超时） |
| **agent 自检** | 生成后自检：analysis_port 存在、driver/sequencer 齐 |

**落点**：`executors/verify/templates/` + `agents/`。

---

## 十、scoreboard / checker 专项优化

| 优化 | 做什么 |
|---|---|
| **比对策略配置化** | transaction level vs signal level，可配 |
| **scoreboard 自检** | 接上 monitor 后自检 export 是否连上 |
| **checker 断言分级** | 协议/时序/复位/CDC 分级，可单独使能 |
| **checker 误报抑制** | 复位期间、初始化期间不报 |
| **scb/checker 覆盖率** | 比对次数、命中次数也进覆盖率 |

**落点**：`env/` + `assertions/`。

---

## 十一、多模块与资源

`multi` 多模块并发，缺资源隔离。

| 优化 | 做什么 |
|---|---|
| **EDA license 隔离** | 两个模块抢 license 怎么办 |
| **并发度控制** | 按 license 数、CPU 核数动态调 |
| **失败隔离** | 一个模块失败不影响其他模块 |
| **共享 agent 池** | 多模块共用 agent，减少重复生成 |

**落点**：`cli/commands.py` 的 `multi` + `l1_infrastructure`。

---

## 十二、配置与合规

| 优化 | 做什么 |
|---|---|
| **配置校验** | 配了 provider 没配 key → 启动就报，不是跑到 LLM 才报 |
| **数据脱敏** | spec/RTL 里有没有敏感信息进 LLM |
| **配置版本** | 配置变更记录，可复现 |
| **合规检查** | 签核 checklist 可配置，不同项目不同门禁 |

**落点**：`cli/` + `l1_infrastructure`。

---

## 优先级建议

| 优先级 | 优化 | 理由 |
|---|---|---|
| **P0** | 边际收益早停 + 多种子有效性 | 直接决定收敛效率，不空烧轮次 |
| **P0** | LLM token 预算动态化 + 端口闭合门禁 | 直接决定 RTL/agent/env 生成成功率 |
| **P1** | 决策可解释性 + 覆盖率排除审计 | 可治理、可追溯 |
| **P1** | 波形按需采 + 同 run 归档 | 你的波形交付，长跑不爆 |
| **P1** | 协议模板库 + agent 自检 | interface agent 交付质量 |
| **P2** | 断言覆盖率 + 交叉爆炸控制 | 覆盖率方法学深化 |
| **P2** | 节点 tracing + 成本统计 | 可观测性 |
| **P2** | 变异测试 + 基线冻结 | 工程健康 |
| **P3** | 多模块资源隔离 + 配置校验 | 规模化 |

---

## 一句话

**前面是把交付契约显式化，这些是让收敛更聪明、生成更可靠、交付更可治理。** 最该先做的是两件：**边际收益早停**（别空烧轮次）和**LLM token 预算动态化 + 端口闭合门禁**（别让 `async_fifo` 那种截断再发生）。这两件做完，覆盖率收敛的“效率”和“成功率”会同时上一个台阶。




对，**如果你定义的是“正面干过 EDA 厂商的通用验证引擎”，那干不过，而且基本没戏。**  
这不是你架构不行，是战场选错了。

---

## 为什么正面干不过

因为你在跟这几样东西竞争：

- **约束求解引擎**：VSO.ai / SimAI 在仿真器内部实时搜索约束空间，你的是模板化静态生成；
- **形式化引擎**：JasperGold / VC Formal 做可达性分析，你没有；
- **仿真器本身**：VCS / Xcelium / Questa 是 license 生意，你是上层脚本；
- **数据规模**：厂商有 4000+ 用例、USB/PCIe PHY 级回归，你 `async_fifo` 都被 token 截断；
- **客户信任**：流片签核没人敢把责任交给一个个人级 CLI。

这几条不是“架构调一调”能追上的，是**引擎级、生态级、资本级**差距。正面刚，就是拿步枪打航母。

---

## 但“干不过”是个伪命题，因为你本来就不该对标厂商

你真正的对手不是 Synopsys/Cadence。  
你真正的对手是：**Excel + Makefile + 人工记目录名 + 手动补激励 + 覆盖率靠人盯。**

EDA 厂商做的是通用引擎、大规模、license 绑定、大客户交付。  
他们**不愿意做、做不细、绑不定**的，才是你的战场：

| 你能赢的维度 | 为什么厂商不做 |
|---|---|
| **垂直协议/IP 的端到端编排** | 太窄，不值一个大产品线 |
| **公司内部流程自动化** | 每家流程不一样，厂商不定制 |
| **小团队/个人快速出验证环境** | 厂商卖的是 license，不是小工具 |
| **证据链与可复现** | 厂商有，但重、贵、绑工具 |
| **spec → UVM → 覆盖率 → 签核的胶水层** | 厂商各管一段，不帮你串 |
| **特定领域知识（NPU/ISA/自定义总线）** | 通用工具不懂你的领域 |

**你的定位应该是：EDA 工具之上的 AI 验证交付层。**  
不造引擎，接 VCS / Xcelium / Questa；不造形式化，调 JasperGold / VC Formal；不造仿真器，用 QuestaSim。  
你做的是：**把 spec 到签核这条链，自动化、可追溯、可复现地串起来。**

---

## 你能拿出手的指标，不是覆盖率绝对值

别跟 VSO.ai 比“同样跑测次数多拿 33% 覆盖率”。你比不过。

你能比的是：

- **端到端时间**：从 spec 到一个能跑的 UVM env，从几天缩到几小时；
- **人工步骤**：原来 20 步手工，现在 3 步；
- **可复现性**：每个 run 有证据包、ucdb SHA256、血缘；
- **特定协议覆盖**：APB/AXI/NPU ISA 这种你懂的领域，厂商模板不一定细；
- **小团队可用性**：不需要 license 服务器、不需要 CAD 支持。

**在这些指标上，你有可能赢。** 因为厂商的商业模式不覆盖这些。

---

## 如果还要继续，路线只有一条

**放弃“造引擎”，全力做“编排层 + 垂直场景”。**

1. **接后端，不自研**  
   QuestaSim / VCS / Xcelium 当编译仿真后端；JasperGold / VC Formal 当形式化后端。你只做调度和证据。

2. **聚焦一个真实小设计，跑出数据**  
   `npu_sched` 或一个 1K–2K 行 RTL 的开源 IP。拿到代码覆盖率、功能覆盖率、收敛轮次、人工步骤数。没有数据，一切白谈。

3. **把 formal 可达性分析做成外调**  
   在 `decide` 节点加 `FORMAL_REACHABILITY`，调外部 formal 工具，不可达 bin 直接 waive。别自研。

4. **把 agent / env / scb / checker / 用例 / 覆盖率 / 波形做成显式交付契约**  
   这是你相对厂商的差异化：厂商给你工具，不给你端到端交付链。

5. **别对标产品，对标任务**  
   你的目标不是“比 VSO.ai 强”，是“让一个验证工程师今天少加 4 小时班”。

---

## 一句话

**正面干，干不过。侧翼打，能打。**  
如果你要拿它去对标 Synopsys/Cadence，建议放弃；  
如果你要拿它去替代你流程里的 Excel + Makefile + 手工补激励，那它有价值，而且能干过。

现在最关键的不是继续调架构，是**找一个真实设计，跑通一次，拿到第一组数据**。没有这组数据，“干不过”和“能干过”都是空话。



对，**如果你定义的是“正面干过 EDA 厂商的通用验证引擎”，那干不过，而且基本没戏。**  
这不是你架构不行，是战场选错了。

---

## 为什么正面干不过

因为你在跟这几样东西竞争：

- **约束求解引擎**：VSO.ai / SimAI 在仿真器内部实时搜索约束空间，你的是模板化静态生成；
- **形式化引擎**：JasperGold / VC Formal 做可达性分析，你没有；
- **仿真器本身**：VCS / Xcelium / Questa 是 license 生意，你是上层脚本；
- **数据规模**：厂商有 4000+ 用例、USB/PCIe PHY 级回归，你 `async_fifo` 都被 token 截断；
- **客户信任**：流片签核没人敢把责任交给一个个人级 CLI。

这几条不是“架构调一调”能追上的，是**引擎级、生态级、资本级**差距。正面刚，就是拿步枪打航母。

---

## 但“干不过”是个伪命题，因为你本来就不该对标厂商

你真正的对手不是 Synopsys/Cadence。  
你真正的对手是：**Excel + Makefile + 人工记目录名 + 手动补激励 + 覆盖率靠人盯。**

EDA 厂商做的是通用引擎、大规模、license 绑定、大客户交付。  
他们**不愿意做、做不细、绑不定**的，才是你的战场：

| 你能赢的维度 | 为什么厂商不做 |
|---|---|
| **垂直协议/IP 的端到端编排** | 太窄，不值一个大产品线 |
| **公司内部流程自动化** | 每家流程不一样，厂商不定制 |
| **小团队/个人快速出验证环境** | 厂商卖的是 license，不是小工具 |
| **证据链与可复现** | 厂商有，但重、贵、绑工具 |
| **spec → UVM → 覆盖率 → 签核的胶水层** | 厂商各管一段，不帮你串 |
| **特定领域知识（NPU/ISA/自定义总线）** | 通用工具不懂你的领域 |

**你的定位应该是：EDA 工具之上的 AI 验证交付层。**  
不造引擎，接 VCS / Xcelium / Questa；不造形式化，调 JasperGold / VC Formal；不造仿真器，用 QuestaSim。  
你做的是：**把 spec 到签核这条链，自动化、可追溯、可复现地串起来。**

---

## 你能拿出手的指标，不是覆盖率绝对值

别跟 VSO.ai 比“同样跑测次数多拿 33% 覆盖率”。你比不过。

你能比的是：

- **端到端时间**：从 spec 到一个能跑的 UVM env，从几天缩到几小时；
- **人工步骤**：原来 20 步手工，现在 3 步；
- **可复现性**：每个 run 有证据包、ucdb SHA256、血缘；
- **特定协议覆盖**：APB/AXI/NPU ISA 这种你懂的领域，厂商模板不一定细；
- **小团队可用性**：不需要 license 服务器、不需要 CAD 支持。

**在这些指标上，你有可能赢。** 因为厂商的商业模式不覆盖这些。

---

## 如果还要继续，路线只有一条

**放弃“造引擎”，全力做“编排层 + 垂直场景”。**

1. **接后端，不自研**  
   QuestaSim / VCS / Xcelium 当编译仿真后端；JasperGold / VC Formal 当形式化后端。你只做调度和证据。

2. **聚焦一个真实小设计，跑出数据**  
   `npu_sched` 或一个 1K–2K 行 RTL 的开源 IP。拿到代码覆盖率、功能覆盖率、收敛轮次、人工步骤数。没有数据，一切白谈。

3. **把 formal 可达性分析做成外调**  
   在 `decide` 节点加 `FORMAL_REACHABILITY`，调外部 formal 工具，不可达 bin 直接 waive。别自研。

4. **把 agent / env / scb / checker / 用例 / 覆盖率 / 波形做成显式交付契约**  
   这是你相对厂商的差异化：厂商给你工具，不给你端到端交付链。

5. **别对标产品，对标任务**  
   你的目标不是“比 VSO.ai 强”，是“让一个验证工程师今天少加 4 小时班”。

---

## 一句话

**正面干，干不过。侧翼打，能打。**  
如果你要拿它去对标 Synopsys/Cadence，建议放弃；  
如果你要拿它去替代你流程里的 Excel + Makefile + 手工补激励，那它有价值，而且能干过。

现在最关键的不是继续调架构，是**找一个真实设计，跑通一次，拿到第一组数据**。没有这组数据，“干不过”和“能干过”都是空话。