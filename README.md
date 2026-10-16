# SignOffAI — IC 验证垂直领域智能体（纯 Python CLI）

**规格 → RTL → UVM → 回归 → 覆盖率 → 签核** 的 AI 验证闭环工具。个人级 CLI，**无 Web 前端**（`python -m src.cli.commands` 交付全部功能）。

> **架构**：**8 个阶段执行器（executor）** 编排在 **LangGraph 闭环图**（24 节点）上，
> 坐落在**五层引擎**（L1 基础设施 / L2 编排 / L3 决策 / L4 记忆 / L5 进化）之上。
>
> 关键文档：
> - `docs/design/architecture_optimization_plan.md` —— 现状诊断与优化路线（含本文档所有结论的出处）
> - `docs/design/verification_flow.md` —— 闭环拓扑
> - `docs/design/tool_layer_architecture.md` —— 工具层契约
> - `src/tools/casemodel_tools/readme.md` —— **功能覆盖率方法学**（case 模型 → covergroup → 种子 → 回归）

---

## 三条铁律（不可放松）

| 铁律 | 含义 | 代码落点 |
|------|------|---------|
| **EDA 是唯一真理** | LLM 生成的代码必须经 `vlog` 编译返回 0/1，不通过即丢弃/回退；**失败必须响亮**，禁止静默降级为假通过 | `executors/design/main.py:_verify_ip_rtl`、`executors/verify/main.py:_verify_compilation` |
| **覆盖率库版本固化** | 每轮 ucdb 算 SHA256 归档，复现时回滚比对 | `l1_infrastructure/infrastructure.py:archive_coverage` |
| **LLM 只读降采样文本** | 空洞分析只读 <1KB 语义汇总，绝不读几十 GB 的 ucdb | `executors/coverage` |

**"失败响亮"的几处具体落地**（都是实测踩出来的，不是设计口号）：

| 坑 | 症状 | 落点 |
|---|---|---|
| **仿真根本没起来被记成 pass** | `sim_vsim.log` 不存在时 `! grep …` 反而成立 —— 整轮回归全绿而覆盖率 0% | 判据先要 `[ -s sim_vsim.log ]` 再谈里面有没有错 |
| **vsim 崩了但没日志** | `vsim-3772` 加载 DPI 失败，日志里一条 `UVM_ERROR :` 都没有 | 判据补 `FATAL ERROR\|Errors: *[1-9]`（与 vsim 自己的结算行同源） |
| **组合模式不使能编译侧** | `cov+wave` 只设 `cov+wave_enabled`，build 判的是 `cov_enabled` → `vlog` 少 `+cover` | `apply_modes` 把组合词按 `+` 展开 |
| **产物写了但从没被编译** | `coverage/<module>_cg.sv` 全仓没有一处加进 filelist | 改走**已跑通**的 `env_cov` 通道 + 探针进 filelist |

---

## 快速开始

```powershell
# 依赖
.\venv\Scripts\activate
pip install -r requirements.txt

# 配置（可选；不配则走确定性/模板路径，LLM 环节如实失败）
# .env: LLM_PROVIDER=deepseek / LLM_API_KEY=... / LLM_MODEL=deepseek-chat

# 一键闭环
python -m src.cli.commands verify specs\apb_uart\apb_uart_spec.md --json
```

**行为约定（失败响亮 —— 这是全项目最一致的一条纪律）**：

| 情形 | 行为 |
|------|------|
| 无 EDA 工具（vlog/vsim 不在 PATH） | `BLOCKED_EDA_MISSING` + 安装指引，**不进入假通过路径** |
| debug 无仿真/编译日志 | `NO_EVIDENCE`（score 0）—— **"没有日志"绝不等于"没有错误"** |
| debug / ops 无 EDA | `EDA_MISSING`（score 0） |
| audit 四道门禁任一不过 | `NEEDS_FIX` 且阶段 FAIL |
| 无 spec 也没 RTL | `front` 直接拒绝往下走 —— 不静默填一个 `design_name: dut` |

---

## 8 个阶段执行器

代码在 `src/executors/`。它们**不是"会自己思考的 agent"** —— 8 个里**只有 `design` 与
`debug` 直接调 LLM**（前者写小 IP、后者兜底重写），其余 6 个是确定性管线；
LLM 只在具体位置被**点状**调用（符合"LLM 只做完形填空"的定位）。

> 「点状」的含义：**流程、决策、工具选择都是确定性的**，LLM 只在"该写一段代码/该给一个
> 判断"的那个点上被叫一次。全部调用走唯一漏斗 `tools/lib/llm_call.py:call_llm`
> （token 预算 / 缓存 / 重试+回退 / 审计一处实现），完整清单见 `docs/design/llm_call_sites.md`。

| 执行器 | 职责 | 产出 |
|-------|------|------|
| `front` | 前置分析：读 spec / RTL，解出模块名与端口 | spec 摘要 + case 模型草稿 |
| `design` | spec 分析 → IP 拆解 → RTL 生成（LLM 写小 IP + `vlog` 门禁）→ 顶层集成 | `rtl/*.sv` + design_arch |
| `model` | 参考模型（模板 + 版本管理 + 回滚） | `model/` |
| `verify` | UVM 环境（Jinja2 模板）+ 用例 YAML + SVA 断言 + gap 定向激励<br>**+ 功能覆盖率三件套**（覆盖率计划 / DUT 探针 / 批次 test 类） | `env/ agents/ assertions/ coverage/` |
| `ops` | 编译 + 仿真 + 回归 | `regression.json` |
| `coverage` | 覆盖率收集（`vsim -coverage` → ucdb）+ gap 归因 | `coverage.json` + gaps |
| `debug` | 日志收集 → 分类 → 指纹去重 → 模板修复 → LLM 兜底重写 → EDA 重验 | debug report |
| `audit` | 签核门禁 + 签核报告 | `report.json` + 证据链 |

**8 个执行器服务 24 个图节点**：`verify` 与 `coverage` 各服务 **2 个阶段**
（`verify` 也管 `env_arch_check`，`coverage` 也管 `decide`），其余各 1 个。
所以"节点"和"执行器"是两个**正交**的概念，见 `l2_orchestration/stages.py`。

---

## 闭环流程（coverage-driven）

```
design → model → verify → [ops → coverage → decide]×N → audit
                              ↑          ↓
                              └── debug 修复 / 决策动作 ──┘
```

决策动作：`FIX_COMPILE` / `FIX_*_bug`（功能/复位/协议/CDC/死代码）/ `FIX_MODEL` /
`GENERATE_DIRECTED_TEST` / `RELAX_CONSTRAINT` / `EXPAND_SEEDS` / `CONVERGE`。

EDA 缺失时在首个 `ops` 轮终止（`BLOCKED_EDA_MISSING`），不空转。

**决策是确定性的**：硬失败动作（`FIX_COMPILE` / `FIX_MODEL`）**永远走规则**，RL 不参与；
RL 只管 4 个软动作，且经验统计只做"降级建议"不直接拍板（`decision_engine.py:523`）。

---

## 功能覆盖率方法学（case 模型 → covergroup → 种子 → 回归）

**这条链是本项目"可度量、可追溯、可签核"那条主张的落点。** 规则只此一份：
`src/tools/casemodel_tools/coverage.py`（模块头 = 方法学），细节见 `casemodel_tools/readme.md`。

### 一、模型里的东西变成 SystemVerilog

| case 模型 | 变成 | 为什么 |
|---|---|---|
| `Dimension` | 一组 coverpoint | 维度只归类，不承载取值 |
| `Field` | `coverpoint <字段名>` | 字段名就是接口信号名 |
| `ValuePoint` | 一个 `bins` | 取值点就是覆盖分母的刻度 |
| `Field.cover_bins` | bin 名 / **显式仓（含区间）** | 值域划分（`{[1:7]}`）表达不出来于取值点 |
| `Field.cover_illegal` | `illegal_bins` | 命中即报错 |
| `CrossPair` | `cross` / **`binsof` 过滤交叉 + 非法交叉** | 全交叉是乘积；非法组合不声明就会被当成正常状态统计 |
| `Field.cover_id` / `.requirement` | （不进 SV） | 追溯矩阵的两端 |

两条纪律：**生成的 SV 必须能编译**（中文取值投影成整型字面量、bin 名 ASCII 化去重）；
**算不出来就说出来**（空字段 / 解不出的交叉 / 超量取值点都进 `notes`，不静默少生成）。

### 二、两条采样通道 —— 先问"这个信号从哪看得见"

| | `sample: stimulus`（默认） | `sample: dut` |
|---|---|---|
| 信号在哪 | agent 的**事务对象** | DUT 里**按名字可见**：输入端口 / 输出端口 / **内部寄存器** |
| 谁采 | `env_cov.sv.j2` 的 `cg_<agent>`（monitor 每笔事务 → `sample()`） | `env_cov.sv.j2` 的 `cg_dut`（`coverpoint vif.<信号>`，时钟沿 + 复位屏蔽） |
| 看得到什么 | **只有激励侧** | 内部状态、输出端口 —— monitor 一个都采不到 |

**分不清这一点，就会给一堆采不到的信号生成一份永远不命中的覆盖率模型。**

DUT 那条先走 `bind`（挂**模块**上、端口表达式在目标模块作用域求值 → 内部名直接连得
过去），把信号引成一个**接口**；`env` 的覆盖率组件持 `virtual <接口>` 采样，覆盖率
因此与事务通道在**同一份报告**里（实测：`cg_dut` 41.5%，内部 `queue_level` 真采到）。
两个名字（接口类型名 / bind 实例名）只有**一处出处**，写进 `env_cov_bins.yaml` 的
`dut_if`，env_cov 与 tb_top 都读那一份 —— 漂了就是**句柄为空、覆盖率恒 0%，而编译
与加载都不报错**。接口文件被 `build_filelist_for_tb` 收进编译清单（排在 RTL 之后）。

### 三、功能覆盖率计划：一份 yaml，摆四张表

与 case 模型**同批生成**，落在 `<run>/coverage/coverage_plan.yaml`：

| | 内容 | 谁读 |
|---|---|---|
| §3 覆盖点 | 谁在采、采什么、bin / 非法仓 | 生成 covergroup 的人 |
| §5 批次 | 这批打哪个专题、跑哪个 **test** | 回归 |
| §6 种子管理 | 这批跑几条才算数（`base`/`count`/`explore`） | 回归 |
| §8 需求追溯 | `REQ ↔ CP/X ↔ 批次` | 签核的人 |

**为什么一起生成**：四张表同源，分散在三四个文件里对账很痛苦 —— 「声明了 12 个覆盖点、
回归里只跑 8 条」这种事，只有把两边摆在一张表上才看得出来。

### 四、种子管理 → 回归

种子声明在**专题（= 批次）**上 —— 它不是"怎么跑"的细节，是「**这一批要跑够几条才算数**」
的完备性声明。回归侧只把它铺开成 runtime 参数：

```yaml
- name: npu_type_test
  count: 18                      # 15 基线 + 3 探索
  variables: {SEED: 2001}        # count 展开成 base + i - 1
  run_cmd: 'vsim … +UVM_TESTNAME=npu_type_test +ntb_random_seed={{ SEED }} …'
  tags: ["p0", "batch", "TH-B02"]
```

批次还要有**同名的 UVM test 类**（`environment.batches` → `{env}_batch_test.sv`）：
没有它，`+UVM_TESTNAME=npu_type_test` 会撞 `UVM_FATAL (INVTST)`，而 **vsim 仍然 exit 0**
—— 跑不起来反而看不出来。类体里**不铺激励**（传参数不传行为），把"这一批打哪几个维度、
用什么方法、**用哪条约束策略**"挂上 config_db。

**约束策略名走全局通道**（`set(null, "*", "batch_policy", …)`，与 tb_top 挂 vif 同一个
写法）：sequence 的父链未必挂在 test 底下（`seq.start(sqr)` 建出来的可以不挂 parent），
用 `this` 作上下文会取不到 —— 而**取不到的表现是"约束静默没生效、回归照样全绿"**。
名字与 `constraint.yaml` 的 `policies[].name` **同一出处**（`theme_policy_map`），
两份各推一次就会漂。

### 五、命令

```powershell
python -m src.tools.casemodel_tools.cli covergroups    specs\npu_sched\casemodel.yaml -m npu_sched
python -m src.tools.casemodel_tools.cli coverage-plan  specs\npu_sched\casemodel.yaml -m npu_sched
# 主 CLI 同形：vagent case-model {covergroups,coverage-plan}
```

### 六、三层模型（case / 覆盖率 / 约束）靠名字关联

三份 yaml 各答一个问题，**关联靠名字不靠位置** —— 也不加第四个"关联表"文件，
那是第四份真相，改了名没人报。

| 文件 | 答什么 | 它的引用字段 |
|---|---|---|
| `cases.yaml` | **该测什么**（取值空间 / 专题 / 组合矩阵） | `cover_bins`、`cross_matrix`、`themes[].method`、`themes[].dimensions` |
| `coverage.yaml` | **怎么量**（coverpoint + bins + cross） | `bins[].name`、`crosses[].matrix_ref`、`dimension` |
| `constraint.yaml` | **怎么驱动**（policies + combinator） | `transactions[].name`、`policies[].applies_to`、`policies[].dimensions` |

**五条边**，连成一个闭合的三角形（前四条只连成 "V"）：

```
① case.field.cover_bins  ──bin 名──►  coverage.coverpoints[].bins[].name
② case.cross_matrix 键   ──矩阵键──►  coverage.crosses[].matrix_ref
③ 约束.policies[].applies_to ──端口──► 约束.transactions[].name
④ case.themes[].method   ──映射──►   约束.combinator / policies
⑤ 约束.policies[].dimensions ──维度 ID──► coverage.coverpoints[].dimension
```

**①② 是硬边**（`error` —— "声明的测试点没落成覆盖仓"/"组合关系没被覆盖"）；
**③④⑤ 是软边**（`warning`）。有 error 就不许渲染 SV：取值投影不出来时给个 0 让 bin 照
生成，收的是**错的数**，比生成不了更坏。

**边 ⑤ 补的是三角形缺的那一边。** "这条策略驱动的维度到底有没有人量它" —— ③ 查不了
（端口名↔信号名的对应没有建模，代码里如实记着这条），⑤ 改追 **dimension ID**：
`dimensions[].id` 是两边共用的命名空间（覆盖率侧 `coverpoint.dimension`、约束侧
`policy.dimensions`）。两处必须归一，都是实测踩出来的：专题的 `dimensions` 写的是
**原始引用**（`指令类型` 这种 name 也行）而覆盖率侧是 `D_type`，得归到 canonical key；
`dimensions: ["*"]` 的语义是**全部维度**，得展开 —— 否则所有维度都被报成"没人驱动"。

```powershell
python -m src.tools.casemodel_tools.cli associate   cases.yaml coverage.yaml [-c constraint.yaml]
python -m src.tools.casemodel_tools.cli constraints cases.yaml -p apb_master:APB_master_seq_item -o constraint.yaml
# 主 CLI 同形：vagent case-model {associate,constraints}
```

- **`associate`** 只**报**断点，五条边各自报自己的。
- **`constraints`** 把 `themes[].method`（`D/G/SPCL/RND/RPLY`）**生成**成策略 + 组合器，
  产物正好是 `gen_uvm` 认的约束模型形状 —— 边 ④ 从"事后报断"变成"从一开始就接上"。
  端口要显式给（case 说字段名、约束说 agent 名 + seq_item 类型，两边推不出来），
  **没给端口就不生成**（空 `transactions` 渲染出来是个空壳协调序列）。

**流水线里它是自动生成的**：verify 阶段在 `find_spec_yaml` 之后、`jinja_render` 之前落
`inputs/yaml/uvm/constraint.yaml`（早一步会被 `find_spec_yaml` 清空，晚一步这一轮渲染
不到 —— 两种都是"文件没生成、日志一片正常"），与 `env.yaml` 在同一次 `run()` 里被读到，
`default_env` 才回填得上。端口从 env.yaml 的 agents 推，**从 `type` 推不是从 `name`**
（`npu_sched_in_master_agent` → `npu_sched_in_master_seq_item`；照 name 拼出来的类
不存在，而那个错要到 vlog 才报）。产物渲染出 `env/cons/` 五个文件。

> ⚠️ **策略体目前是空的**：`env_cons_policies.sv.j2` 的 `case (policy_name)` 分支来自
> 内置名单（8 个**主题名**：`precision_consistency` / `mem_capacity` / …），与
> `build_constraint` 推出来的 `p_th_b02_random`（专题 + 方法）**一个都对不上** ——
> `case` 一个分支都没有。而空 `case` 不是"什么都不做"，是 `vlog-13302` **编译错误**
> （实测 11 策略 = 11 条 error），所以模板留了一个 `default:` 兜底。
> **要让约束真生效，得把那 8 个内置分支补成按 method 派生的五类**
> （`directed` / `combo` / `special` / `random` / `replay`）—— method 是 case 模型
> 建模得的，主题名不是。**这一步还没做。**

### 七、一份能跑的样板：`specs/npu_sched/`

`npu_sched.sv` 是《NPU 指令调度器功能覆盖率计划文档》§2.2 接口表的实现（12 个采样信号
+ 5 个内部信号），`casemodel.yaml` 是它的覆盖点模型（12 覆盖点 / 7 交叉 / 11 批次 / 195 次运行）。

```powershell
python -m src.cli.commands verify --rtl specs\npu_sched -o output_npu
```

> ⚠️ **实测尚未验过**：本仓库最后一次改动时，本机 `vsim` 起不来（`vlog` 正常、license 未过期），
> 所以"批次 test 真跑起来、种子真影响随机数、探针真收到命中"这三件事**只在生成侧与编译侧验过**
> （生成的探针与真 DUT 一起 `vlog` 编译通过、回归里 `count`/`SEED`/plusarg 都对）。
> 等 `vsim` 恢复后用上面那条命令跑一轮即可确认。

---

## 主要命令

```powershell
# 闭环
python -m src.cli.commands verify <spec.md> [--target 80] [--max-rounds 5] [--json]
python -m src.cli.commands multi ...                 # 多模块并发
python -m src.cli.commands ci verify                 # CI 入口

# 执行器 / 运行
python -m src.cli.commands agent list
python -m src.cli.commands runs                      # 运行历史
python -m src.cli.commands show <run_id>
python -m src.cli.commands dump <run_id>             # 复现 / 导出证据包

# 人工介入（可治理）
python -m src.cli.commands approve <run_id> --reason "..."
python -m src.cli.commands reject  <run_id> --reason "..."

# 分组命令
python -m src.cli.commands signoff  {generate,export,verify,checklist,diff}
python -m src.cli.commands coverage {report,gaps,exclude,trend,merge}
python -m src.cli.commands env      {generate,validate,compile,template}
python -m src.cli.commands regression {stages,approve,run,report,trend,compare}
python -m src.cli.commands case-model {check,analyze,generate,tree,rules,uvm-tests,
                                       covergroups,coverage-plan,gui}
python -m src.cli.commands distill  {run,list,rollback}      # 经验蒸馏（L5）
python -m src.cli.commands govern   {status,override,reset}  # 治理
python -m src.cli.commands evidence {record,log,check}
python -m src.cli.commands lineage  {versions,baseline,bugs,compare}   # 血缘：RTL 版本 / 基准
```

### 血缘（`vagent lineage`）

把**跨 run 的四个实体**记下来（`.signoffai/lineage.db`）—— 没有它们，"这一轮比
上一轮差在哪"只能靠人肉记目录名：

| 实体 | 是什么 |
|---|---|
| **RTL 版本** | 由**目录内容哈希**自动派生（机器算、不依赖 git，`--rtl <dir>` 也能用）。同哈希幂等（跑一百轮还是 v1），改一字节就是新版 |
| **run 基准** | 每个模块的**第一次 run**，写下就不再改 —— "相对最初那版偏了多少"是单调的，"上一轮"会随跑的次数漂 |
| **bug ↔ 版本** | debug 记下的 bug 挂在"发现于哪版"，可查"这版还有哪些没修" |
| **用例 ↔ 模块/版本** | `testcase_registry` 的 `module` + `rtl_version_no` 两列（不再是 `name` 里的文本） |

```powershell
python -m src.cli.commands lineage versions            # 有哪些版本、哈希、首次 run
python -m src.cli.commands lineage baseline npu_sched  # 基准锚在哪一次
python -m src.cli.commands lineage bugs npu_sched -v 2 # 哪一版发现/修好了什么
python -m src.cli.commands lineage compare out_x       # 与**基准**比（自动找锚点）
```

`verify` 收尾时自动落版本与基准；拿不到就说拿不到（空 RTL 目录 → 整条跳过，
不写一个对应空目录的假 v1）。

**`verify` 的常用开关**（`--help` 里有全部）：

| 开关 | 作用 |
|---|---|
| `--rtl <dir>` | 拿现成 RTL 当 DUT，**自动跳过 design/model**（验开源 IP 用）；与 spec 互斥 |
| `--sim-mode {cov,wave,cov+wave,…}` | 仿真业务，**默认 `cov+wave`**（覆盖率是闭环主指标，波形是唯一现场） |
| `--no-manual-gate` | 关掉分级回归的人工节点（loopback 全过也不停车等人放行） |
| `--approval {interactive,auto,threshold}` | 审批模式；无人值守请显式 `auto` |

---

## 目录结构（实际）

```
src/
├── executors/          # 8 个阶段执行器（见上表）
│   ├── front/ design/ model/ verify/ ops/ coverage/ debug/ audit/
│   └── verify/casemodel/          # Case 建模（属性模型）
├── layers/
│   ├── l1_infrastructure/         # 零 AI 确定性层：EDA 后端 / 编译自愈 / 覆盖率 / Git / 文件
│   ├── l2_orchestration/          # 编排
│   │   ├── graph.py               #   建图（174 行 —— 只回答"节点怎么连起来"）
│   │   ├── runtime.py             #   Runtime / hydrate_runtime / _run_agent
│   │   ├── routers.py             #   条件边："下一步走哪"只在这里回答
│   │   ├── nodes/
│   │   │   ├── pure/              #   12 个纯函数节点（决策/治理/审批/轮次/收尾）
│   │   │   └── agent/             #   12 个调 executor 的节点
│   │   ├── stages.py              #   24 个节点的元数据（唯一来源）
│   │   ├── governance/            #   审批 / 治理 / 质量守护 / 策略包
│   │   ├── evidence/              #   证据链（五层证据 / manifest / 文件审计）
│   │   └── communication/         #   工具总线（ToolHub）
│   ├── l3_decision/               # 覆盖率驱动决策引擎 + 知识图 + RL
│   ├── l4_memory/                 # 持久化 / IP 库 / 用例状态库 / exclude 库 / 调试经验
│   └── l5_evolution/              # 经验蒸馏
├── tools/             # 领域工具（14 个域）+ lib/ 公共库
│   ├── casemodel_tools/           # case 建模 + **功能覆盖率方法学**（coverage.py）
│   ├── regression_tools/          # 回归框架（Questa）+ 仿真业务模式表（sim_modes.py）
│   └── isa_gen_tools/             # NPU ISA 事务序列生成器（见下节）
├── cli/               # vagent CLI（commands.py / output.py / repl.py）
└── workbench/         # PySide6 桌面工作台（可选，不是 Web —— 见 CLAUDE.md）
config/casemodel/examples/         # case 模型示例（+ `specs/<模块>/casemodel.yaml` 也是合法落点）
specs/                 # 规格库（apb_uart / apb_slave / **npu_sched**）
tests/                 # pytest 套件
```

**"用哪份 case 模型"只有一个判据**（`l1_infrastructure/layout.py:find_case_model`）——
优先级：`spec["case_model"]` → `specs/<模块>/casemodel.yaml` → `config/casemodel/<模块>.yaml`
→ `<run>/inputs/casemodel.yaml`（front 的草稿）。**人写的优先于草稿。**
这条判据原来散在四个读点（verify 分解测试点、覆盖率生成、DUT 探针、工作台那页各一份），
于是同一个 run 里两件事拿的是**两份不同的模型**而都不报错 —— 已收成一处，并有测试钉住"所有读点都走它"。

### 分层与依赖方向

五层**不是线性链**：L2（编排）是**装配者**，它必须调 L3（决策）、用 L4（记忆）、读 L5（蒸馏权重）
—— 那 50 多处 `L2 → L3/L4/L5` 是结构必需，不是债。

**被测试钉住的是这几条**（`tests/test_layer_direction.py`，用 AST 扫，不会被字符串骗到）：

| 规则 | 依据 |
|---|---|
| **L1 不得向上 import 任何层** | L1 是零 AI 确定性层，反了就没法脱离编排/记忆层单独跑（有子进程测试证明它能） |
| **L4（记忆）不得 import L2 / L3 / L5** | 它是被全员依赖的底座 |
| **L3（决策）不得 import L5（进化）** | 越级；经验查询是**注入**的（`ExperienceProvider`） |
| **L5（进化）不得 import L2 / L3** | 它读记忆、产权重，不驱动编排 |

被依赖的东西一律走**注入**（`GuardianAgent(run_tool=...)` / `InfrastructureManager(case_library=...)`
/ `CoverageDrivenDecisionEngine(experience=...)`）—— 而不是在函数体里延迟 import 把违规藏起来。

---

## NPU ISA 激励生成器（`src/tools/isa_gen_tools/`）

独立工具：吃**场景 DSL**（YAML），吐**ISA 事务层 IR** + 二进制编码 + 张量数据。

```powershell
python -m src.tools.isa_gen_tools.cli validate config/isa_gen/examples/npu_gemm.yaml
python -m src.tools.isa_gen_tools.cli compile  config/isa_gen/examples/npu_gemm.yaml -o out/
python -m src.tools.isa_gen_tools.cli explain  --txn gemm_txn     # 编码表疑点解读
python -m src.tools.isa_gen_tools.cli ops                          # 列 122 条 op
```

`compile -o <dir>` 一次产齐**六件套**（文档 §3.6）：

| 文件 | 谁产 | 说明 |
|---|---|---|
| `case.json` / `seq.ir.json` / `preload.json` / `expect.json` | 生成器（L1→L2） | |
| `seq.hex` + `reg-init.txt` + `seq.lst` | **L3 编码器** | `seq.lst` 是 NICE/VNICE 指令流的**人可读视图**（与 `seq.hex` 逐行对应） |
| `tensors/*.hex` + `manifest/*.json` + `registry.json` | **tensor_gen** | `registry.json` 是四方共用的唯一枢纽 |

**它把"哪些数字对不上"当一等公民**：编码表里的同码碰撞、前缀不符、文档与实现不一致，
由 `explain` 原样端出来，工具**不替编码表做判断**。

---

## 已知问题与路线

### 参考模型层（重构中，占当前 18 个失败测试的全部）

`tests/test_agents.py` / `test_golden_bench.py` / `test_ref_model_wiring.py` 共 **18 个失败**
（另有 `test_sim_modes.py` 一条）。根因是**唯一一条**：`model_library/` 目录已从磁盘删除
（那是"先替后删"的第一步），于是 `match_golden()` 恒 None → `build_ref_model_config()` 恒
None → `_ref_mirror_gate()` 恒 None → env.yaml 里不写 `scoreboards`。替代品
`ModelRegistry`（SQL）里只有 `apb_slave` 一个且状态是 `draft`，而 `_registry_model` 只认
`verified` —— 两条路都空。

方向是**参考模型改为 TLM1.0 + SQL 库**（原实现是信号级 RTL）。
**在替换完成前，这 18 个失败是已知状态，不是回归。**

> 顺带修掉的一个**真口子**：`generate_utils`（`gen_uvm.py`）的 ctx 里有 `ref_model`
> 却**没有 `body`** —— 于是模板里 `{% if body %}` 那个分支永远不进，SQL 库里存的
> TLM 1.0 语义一路白存、渲染出来还是 TODO 空壳。模板单测**直接喂 ctx**，所以它测不到
> 生成器（那组测试全绿）。已补，并加了走真生成器的回归测试。

### 其他

- [x] MCP 工具层断链：`tool_worker.py` 已无 `regression_tool` 引用（ops/coverage 直接调 L1）。
- [x] `env_arch_check` 无 EDA：返回 `EDA_MISSING`（不再 `[WinError 2]`）。
- [x] **点状 LLM 收敛到唯一漏斗**：`tools/lib/llm_call.py:call_llm`（token 预算 / 缓存 /
  重试+回退 / 审计一处实现）；可用性探测换成便宜探针（`llm_factory.is_available`），
  **不再为了"能不能用"真发一次请求**。
- [x] **CLI 的人工审批断链已修**：`verify` 改走 `run_closed_loop_streaming`（落检查点，
      `thread_id = run_id`），`interrupt()` 因此真会触发；新增 `vagent resume`，
      `approve`/`reject` 除记审计外**真的把图推下去**（恢复走 `Command(resume=…)`，
      不是 `update_state` —— 那个全仓库零调用且语义不对）。
      原先 `approval.json` 是**只写不读**的，现在它是审计记录、图由检查点恢复。
      没有检查点时 `approve` 仍然只记审计（**那不是错误** —— 审批记录是"人何时为何签了"
      的凭证，与"这次签核有没有推着图走"是两件事）。
- [ ] 工具白名单的角色对不上：工具绑 `assert/doc/spec/uvm`，执行器是 `front/design/verify/…`，
      **8 个里只有 2 个凑得上交集**，所以每次都回退到全部工具（现在会 warning，不再静默）。
- [ ] **`async_fifo` RTL 生成被 `max_tokens=8192` 截断丢弃**（三次都没产出完整端口闭合）。
- [ ] **批次 test 类的实测没验过**：生成侧 / 编译侧 / 回归声明都验了，但"跑起来是不是真影响
      随机数、探针是不是真收到命中"要等 `vsim` 可用（见「功能覆盖率方法学」末的说明）。
- [x] **批次约束已从 sequence 收回到模型**：`theme_policy_map` 是策略名的**唯一出处**
      （`build_constraint` 的 `policies[].name` 与 `batches[].policy` 同名，实测 11/11
      逐字一致 —— 两份各推一次就会漂，而漂了的表现是"约束没生效但回归全绿"）；
      批次 test 类挂全局 `batch_policy`，协调序列按 `create_from_batch()` 建策略
      （plusargs 保留为回退）。**且已接进 verify**（见上一节）。
- [ ] **约束策略体还是空的**：链条全通了、`env/cons/*` 也真生成了，但策略的
      `apply()` 落到 `default:` 分支、什么都不做 —— 内置分支是主题名，对不上按 method
      派生的策略名。**要真生效得补那五类按 method 的分支**（见上一节的 ⚠️）。
      也就是说：**管道通了 ≠ 约束生效**，别把"env/cons 生成了"读成"约束起作用了"。

---

## 测试

```powershell
python -m pytest tests/ -q                            # 主套件：850 passed / 18 failed（见上）/ 2 skipped
python -m pytest src/workbench/tests -q               # 工作台：707 passed
python -m pytest src/tools/casemodel_tools/tests -q   # case 建模 + 覆盖率方法学：464 passed
python -m pytest src/tools/isa_gen_tools/tests -q     # ISA 工具：290 passed / 1 skipped
```

若干 **守卫型**测试值得单独提 —— 它们防的都是"**不会自动发现的退化**"：

| 测试 | 防什么 |
|---|---|
| `tests/test_layer_direction.py` | 分层依赖方向 + 「L1 能脱离上层单独 import」（AST 扫，不被字符串骗到） |
| `tests/test_tool_risk.py` | 每个 `@tool` 的风险分级完备；有副作用的工具不许被标成 SAFE |
| `tests/test_no_undefined_names.py` | 拆文件后**漏 import** —— 单元测试构造图不碰函数体，要等图真跑到那个节点才 `NameError` |
| `tests/test_env_cov_bins_wiring.py` | 落盘**时机**（`find_spec_yaml` 会清空那个目录）、四个读点是否走同一判据、批次 test 的 plusarg 对不对；**批次策略名与 `build_constraint` 逐字同名**；约束在同一个落盘窗口里 |
| `tests/test_checkpoint.py` | 检查点 + `Command(resume=…)` 重入；**CLI 的 `approve`/`resume` 真把图推下去**（拿 journal 里出现 `run.finished` 当判据，不是"文件写没写"） |
| `tests/test_manifest.py` | 覆盖率库 / 波形**带哈希进证据包**（不是文件表里的一行匿名记录）；相对 `output_root` 不许把路径拼两次 |
| `tests/test_ref_model_wiring.py` | predictor **不是空壳** —— 且**走真生成器**（直接喂 ctx 的测试测不到"生成器把键丢了"） |
| `casemodel_tools/tests/test_coverage.py` | 生成的 SV **真调 `vlog` 编译**（合成模型的断言挡不住 `bins b_ = {0};` 这类非法标识符） |

**"跑测试"在这里的定位**：主套件那 18 个失败是**已知基线**（参考模型层重构中），
其余全绿才算没退化。守卫型测试的价值不在通过率，而在**把本次踩过的坑固化成断言** ——
每一条失败信息里都写着"当时是怎么错的"。

---

## EDA 机器一键验收（有 QuestaSim 时）

```powershell
python scripts\eda_verify_all.py
# 1. 环境报告  2. 黄金模型入库验证（PASS 自动盖章+入索引）  3. 真实闭环 e2e
# exit: 0=全部 PASS  1=有 FAIL  2=EDA 缺失（如实报告，不假通过）
```

## 环境要求

Python 3.10–3.12 · **langchain-core 1.6.6 + langchain-openai 1.6.7 + langgraph 1.2.12**
（不再依赖 `langchain` 元包与 `langchain-community`）·
QuestaSim（可选，编译仿真+覆盖率；缺失时失败响亮）· DeepSeek API key（可选）·
PySide6（可选，仅工作台需要）

**关于 EDA 工具的可用性探测**：`vlog` 不需要 license、`vsim` 需要 —— 所以"工具在不在"
和"能不能跑"是两件事。代码里两处都是**先探测、再决定**，不靠"跑一下看看"：

| 探测 | 落点 | 缺失时 |
|---|---|---|
| `vlog` / `vsim` 在不在 PATH | `shutil.which` | `EDA_MISSING` / `BLOCKED_EDA_MISSING`，**不进入假通过路径** |
| LLM 能不能用 | `llm_factory.is_available`（**静态**探针，不发请求） | 确定性/模板路径，LLM 环节如实失败 |
