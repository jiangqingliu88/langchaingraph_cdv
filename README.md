# SignOffAI — IC 验证垂直领域智能体（纯 Python CLI）

**规格 → RTL → UVM → 回归 → 覆盖率 → 签核** 的 AI 验证闭环工具。个人级 CLI，**无 Web 前端**（`python -m src.cli.commands` 交付全部功能）。

> **架构**：**8 个阶段执行器（executor）** 编排在 **LangGraph 闭环图**（24 节点）上，
> 坐落在**五层引擎**（L1 基础设施 / L2 编排 / L3 决策 / L4 记忆 / L5 进化）之上。
>
> 关键文档：
> - `src/tools/casemodel_tools/framework/README.md` —— **方法学框架**（Stage 契约 / 注册表 / 流水线 / 测试点 IR）
> - `src/tools/casemodel_tools/readme.md` —— **功能覆盖率方法学**（case 模型 → covergroup → 种子 → 回归）
> - `src/tools/casemodel_tools/plan.py` —— 测试点 IR 的公开门面
> - `src/tools/casemodel_tools/framework/` —— `contracts / model / naming / realization / stages / pipeline / constraints`

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

## 测试点 IR —— 整条链的主键（方法学框架）

以前各段是**文件接力**：case 模型、覆盖率、约束、回归各自推导，靠"命名恰好一致"
对齐；一旦漂了，没有任何一处报错。现在中间立了一根轴：

```text
case 模型 ──framework 流水线──► TestPoint IR ──► 属性 test / 约束 / 覆盖 / 回归 / 签核
                                coverage/testpoints.yaml
                                coverage/methodology.json   （阶段 + 计数 + 输入 + IR sha256）
```

流水线只有四段（`src/tools/casemodel_tools/framework/`）：

| 阶段 | 回答什么 | 产出 |
|---|---|---|
| `decompose` | 一个取值点对应哪条测试点 | `tp_id` / 维度 / 取值 / 专题 / 优先级 |
| `trace` | 它观测哪个覆盖仓 | `coverpoint.bin` |
| `realize` | 取值**怎么进仿真** | `stimulus` / `sequence` / `observe`（可注册扩展） |
| `execute` | 跑哪个 test、哪一级、哪些种子 | test 类名 / `p0..p3` / 种子 / 判据 |

**realization 四分类**（最重要的一刀）：

| 类型 | 判据 | 下游 |
|---|---|---|
| `stimulus` | 取值能落到 `seq_item` 的 rand 字段 | 属性 test + 事务约束 |
| `sequence` | 取值是多条事务的组合/时序 | 场景序列（待实现） |
| `observe` | DUT 内部/输出/派生量，没有输入引脚 | 只采覆盖，报告按 `OBSERVE_ONLY` 统计 |
| **`backdoor`** | 观测型维度，但内部状态可**强制写入** | 属性 test 用 `uvm_hdl_force(path, value)` → 采覆盖 → release；签核单列 `BACKDOOR_HIT` |

`queue_level` 这种内部寄存器**没有输入引脚**，硬凑一个激励就是造假；标成 `observe`
是**诚实状态**，不是缺陷。而 `backdoor` 是"确定到达"的手段：模型里写

```yaml
realization:
  kind: backdoor
  path: npu_sched_bench_tb_top.u_npu_sched.queue_level
```

生成的属性 test 会把内部状态摆到目标值，覆盖探针采样后 release —— **但签核里
永远单列，不冒充激励覆盖**。

**扩展方式（核心阶段零改动）**：

```python
@REALIZATIONS.register("formal")
class FormalRealization: ...

pipeline.insert(MyStage(), after="trace")
CONSTRAINT_COMPILERS.register("cross-illegal", MyCompiler())
```

产物与消费方：

| 产物 | 谁读 |
|---|---|
| `coverage/testpoints.yaml` / `.json` | 属性 test（注释带 `tp_id`）、回归编排（每条可激励 TP 一个任务） |
| `coverage/methodology.json` | 签核 / 复现（阶段、计数、输入、IR sha256；写入时**固定 LF**） |
| `coverage/tp_matrix.json` | 覆盖率阶段（TP × bin：HIT / MISS / OBSERVED / UNOBSERVED / UNMAPPED） |
| `coverage/constraint_status.json` | audit（约束是真实赋值还是空骨架） |

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
> （token 预算 / 缓存 / 重试+回退 / 审计一处实现）；每次调用落
> `<run>/docs/llm_audit.jsonl`（`site` / `node_id` / `round` / `prompt_hash`）。

| 执行器 | 职责 | 产出 |
|-------|------|------|
| `front` | 前置分析：读 spec / RTL，解出模块名与端口 | spec 摘要 + case 模型草稿 |
| `design` | spec 分析 → IP 拆解 → RTL 生成（LLM 写小 IP + `vlog` 门禁）→ 顶层集成 | `rtl/*.sv` + design_arch |
| `model` | 参考模型（模板 + 版本管理 + 回滚） | `model/` |
| `verify` | UVM 环境（Jinja2 模板）+ 用例 YAML + gap 定向激励<br>**+ 测试点 IR**（框架流水线）+ **功能覆盖率四件套**（覆盖率计划 / DUT 探针 / 批次 test 类 / **约束模型**）<br>注：SVA 生成已于 2026-10 撤掉 —— 规则由 env 检查组件逐拍求值、收口成 `mismatched=…` | `env/ agents/ coverage/ env/cons/` |
| `ops` | 编译 + 仿真 + 回归 | `regression_stages.json`（分级状态；回归结果本身是内存数据） |
| `coverage` | 覆盖率收集（`vsim -coverage` → ucdb）+ gap 归因 | `sim/coverage/coverage_result.json` + `coverage/coverage_points.json` + gaps |
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

### 二·五、激励绑定 —— 属性 test 不能是"死标签"

`fields[].name` 说的是**从哪儿观测**（多为 DUT 内部量 / 输出端口），不是**往哪儿驱动**。
两者的名字经常不相等，甚至根本没有对应物（`queue_level` 没有输入引脚）。所以模型允许
在每个维度上显式写：

```yaml
- id: D_type
  fields: [...]
  stimulus: {field: instr_type}     # 这个维度的取值由事务字段 instr_type 承载
```

链路：

```text
模型 stimulus.field
  → 属性 test 额外 set("<field>_int", <取值>)
  → master sequence 在 pre_body 读回
  → randomize() with { has_<field> -> <field> == attr_<field> }
```

没声明 `stimulus` 的维度保持**观测型**：生成物里明确写"本 test 不建立取值差异"，
而不是假装有区分度。生成期还会对照 agent 的 **master 事务字段**校验 —— 绑了一个不存在
的字段会**出声**，不会等到回归里才发现"set 了一个没人读的键"。

> 实测：同一 seed 下 `d_type_pMAC` 与 `d_type_pDMA` 的 DUT `instr_type` 分别是 `0` / `3`；
> 改之前 61 个属性 test 的激励一模一样。

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

# 测试点 IR（框架流水线；下游只认 tp_id）
python -m src.tools.casemodel_tools.cli testpoints specs\npu_sched\casemodel.yaml `
  --env-name npu_sched_env --module npu_sched `
  --agent-fields npu_sched_in=instr_type,instr_opcode,instr_dtype,barrier_type,op_priority

# 约束模型（有 --agent-fields 才会把 stimulus 维度编译成真实赋值）
python -m src.tools.casemodel_tools.cli constraints specs\npu_sched\casemodel.yaml `
  -p npu_sched_in:npu_sched_in_master_seq_item `
  --agent-fields npu_sched_in=instr_type,instr_opcode

# 主 CLI 同形：vagent case-model {covergroups,coverage-plan,testpoints,associate,constraints}
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

**约束层现在是真的在约束（部分）**，不再是整片空骨架：

- `build_constraint` 把声明了 `stimulus.field` 的维度编译成 `assignments`
  （`trans / field / values / mode`），模板渲染进 `apply()`；
- `env/cons/*` **真的进了 `env_pkg` 编译**（以前生成了却从没被 include），
  批次 test 读到 `batch_policy` 时启动**协调序列**，逐迭代应用策略；
- 用 `backed_policy_count / unbacked_policy_count` 如实报告：NPU 模型是 **5/11**，
  其余 6 条专题的维度是观测型（没有输入引脚），按定义编不出字段约束。

> 剩下的是**业务缺口**，不是管道缺口：`sequence` 型维度（`D_seq` / `D_pipeline`）
> 还没有场景序列生成器；非法交叉（需要两侧都可驱动）尚未编译；协议参数（对齐/握手）
> 模型里没有。`constraint_policy_applied=false` 时 audit 会挂
> **`PASS_WITH_CAVEAT`**，并在报告里写清"5/11 条有真实赋值"。

> 约束层的另一条实测坑：`vsim`/`vlog` 从没编译过的那几个 `env_cons_*` 文件里有一串
> 语法错误（`priority` / `disable` / `end` 是 SV 关键字、语句后声明、`string.index()`
> 不存在、`uvm_virtual_sequence` 不存在、`while(1)` 永不退出、`start_item(item, sqr)`
> 实参类型错）。这些是在**第一次把它们接进编译**时一次性暴露并修掉的 ——
> "生成了"与"编译过"之间隔着这一整串。

### 七、一份能跑的样板：`specs/npu_sched/`

`npu_sched.sv` 是《NPU 指令调度器功能覆盖率计划文档》§2.2 接口表的实现（12 个采样信号
+ 5 个内部信号），`casemodel.yaml` 是它的覆盖点模型（12 覆盖点 / 7 交叉 / 11 批次 / 195 次运行）。

```powershell
python -m src.cli.commands verify --rtl specs\npu_sched -o output_npu
```

> **`vsim` 是好用的 —— "起不来"曾经是一次误判。** 当时把 `Error loading design` 读成
> "仿真器起不来"，真相是**设计侧**的 load 失败（`vsim-8451 Virtual interface resolution
> cannot find a matching instance` / `vopt-13130 Failed to find design unit`）。
> 本机 Questa 2024.1 的 `vlog` / `vopt` / `vsim` / `vcover` 全都能跑，不需要额外
> license 配置。别再用"验不了"当理由把仿真侧停在生成侧。

### 八、一轮完整的端到端实测（2026-10-22）

命令（无人值守：关掉分级回归的人工节点）：

```powershell
python -m src.cli.commands verify --rtl specs\npu_sched -o output_e2e_backdoor `
  --target 95 --max-rounds 1 --no-manual-gate --summary
```

Run：`output_e2e_backdoor_20261022_jiang_20261022_232517`（默认 `cov+wave`，含 `backdoor` 测试点）

| 验到的 | 证据 |
|---|---|
| **五级回归全过** | `regression_stages.json`：loopback 2/2、p0 51/51、p1 85/85、p2 34/34、p3 87/87，**259/259 PASS** |
| **每级只生成自己的用例** | 分级 build 按 tag 裁剪：p0 50/50，p1 84/84（含 10 条 backdoor），p2 33/33，p3 86/86 |
| **测试点 IR 落盘** | `coverage/testpoints.yaml` 63 条；`methodology.json` 的 IR sha256 与文件**逐字节一致**；`tp_matrix.json`：**可激励 26/26（100%）**、**backdoor 10/10（100%）**、观测 25/27、UNMAPPED 0 |
| **backdoor 真到位** | 10 条 D_queue 属性 test 用 `uvm_hdl_force(...queue_level, value)` → 采覆盖 → release；签核单列 `BACKDOOR_HIT`，不冒充激励覆盖 |
| **属性 test 真被约束** | 生成类注释带 `tp_id`；`d_type_pMAC` / `d_type_pDMA` 在同一 seed 下驱动 `instr_type=0/3` |
| **约束部分生效** | `constraint_status.json`：5/11 条策略有真实赋值；协调序列 `Generated: 100, Processed: 100`，`p_th_b08_directed: apply=100` |
| **计划覆盖率（签核口径）** | **95.23%**（254 条回归用例库合并）；单条 coverage test 只有 68.57% —— 之前的签核数字**低估了计划** |
| **签核判定** | **`PASS_WITH_CAVEAT` / `CONDITIONAL`**：覆盖率硬门禁 `coverage_ok=true`；剩余 caveat 是约束 5/11 + 2 条观测型测试点未命中 |
| **可交换证据包** | `signoff_evidence.json`（`signoff_evidence_v1`）：RTL 哈希 / TP IR sha256 / 计划覆盖率 / TP 矩阵 / caveat + 建议动作 / 不可达嫌疑 / LLM 审计摘要 |

**剩余缺口（不再是硬门禁）**：

- 11 条约束策略里 6 条仍是骨架（对应观测型维度）；`sequence` 型维度（`D_seq`/`D_pipeline`）还没有场景生成器；
- 2 条观测型测试点仍 0 命中（`D_dep=WAR`、`D_decision=BLOCKED`）—— 证据包里标为 `SUSPECT`，需要补状态到达手段或模型声明不可达；
- 种子是否真的**改变激励分布**仍未逐 bin 验证（证据包里 `seed_diversity: null`，不冒充已验证）。

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

# 人工介入（可治理）—— run_id 走 --run（不是位置参数）
python -m src.cli.commands approve --run <run_id> --reason "..."   # 记审计 + 推图
python -m src.cli.commands reject  --run <run_id> --reason "..."   # 记审计 + 按驳回继续
python -m src.cli.commands resume  --run <run_id> --decision {approve,reject,skip}

# 分组命令
python -m src.cli.commands signoff  {generate,export,verify,checklist,diff}
python -m src.cli.commands coverage {report,gaps,exclude,trend,merge}
python -m src.cli.commands env      {generate,validate,compile,template}
python -m src.cli.commands regression {stages,approve,run,report,trend,compare,reference-finder}
python -m src.cli.commands case-model {check,analyze,generate,tree,rules,uvm-tests,
                                       testpoints,covergroups,coverage-plan,associate,
                                       constraints,gui}
python -m src.cli.commands distill  {run,list,rollback}      # 经验蒸馏（L5）
python -m src.cli.commands govern   {status,override,reset}  # 治理
python -m src.cli.commands evidence {record,log,check}
python -m src.cli.commands lineage  {versions,baseline,bugs,compare,bind-modules,prune}  # 血缘：RTL 版本 / 基准
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
| `--strict-semantic` | 把签核判的 `PASS_WITH_CAVEAT` 当失败（exit 5）—— CI 用 |
| `--checkpoint / --no-checkpoint` | **默认开**：落检查点（`docs/checkpoints.sqlite`），高危动作的审批从"进程内阻塞等答案"变成"停下来、关掉进程、过后来答"（`vagent resume`）。关掉就只能守着终端 |

**审批：挂起不是失败。** 图停在人工节点上时 `verify` 打印一张面板（含 run_id 与继续命令）
并以 **exit code 3** 退出 —— 不是 0 也不是失败。JSON 模式同理（`interrupted: true`）——
CI 不会把"等人答话"读成"跑完了"。

---

### 可视化（可选，PySide6 桌面工作台）

```powershell
python -m src.workbench          # 或 run_gui.bat
```

| 视图 | 行为 |
|---|---|
| **回归波形** | 点一行 → Questa Visualizer（`-designfile design.db -wavefile waves/x.db`）。`design.db` 按需由 `vopt` 生成、同一 build 共用 —— 有模块 hier、点信号能跳源码。只开了 `cov` 的 run 没有 qwavedb，回退 `vsim -view … -do "add wave -r /*"` 并说明原因 |
| **回归覆盖率** | 逐条用例：`questa.db`（coverstore）先 `vcover merge` 成 UCDB，再进 HTML 报告 / Visualizer —— 直接读 `questa.db` 会**静默丢掉功能覆盖率** |
| **测试点** | Case 建模模块第 12 页：`tp_id / 维度=取值 / realization / 覆盖仓 / 回归级`；选中运行后叠加 `tp_matrix.json` 的命中状态 |

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
│   ├── casemodel_tools/           # case 建模 + **方法学框架**（framework/）+ 功能覆盖率方法学
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

## 优势与劣势（诚实评估）

### 牛逼之处（真正稀缺的组合）

| 优势 | 为什么稀缺 | 证据 |
|---|---|---|
| **测试点 IR 是整条链的主键** | 多数 AI 验证工具停在"生成测试/报告"，没有一条从建模到签核的**可追溯主键** | `tp_id` 贯穿属性 test / 约束 / 回归级 / `tp_matrix` / audit；`methodology.json` 带阶段 + 计数 + IR sha256 |
| **失败响亮 + 三态签核** | 行业工具擅长报"50x 快"，很少把"没证据"当失败 | `NEEDS_FIX` / `PASS_WITH_CAVEAT` / `READY`；`None ≠ False`；X 记 `unverified`；`mismatched=0` 才算真 pass |
| **真实 EDA 闭环，不是 demo** | 通用 AI 编程工具进不了 VCS/Questa；多数"Agent 生成 RTL"项目停在生成 | 最新一轮 **259/259** 分级回归、254 条覆盖率库合并、TP 矩阵、`signoff_evidence_v1` 在同一 run 里落地；**计划覆盖率 95.23%，签核 PASS_WITH_CAVEAT** |
| **确定性编排 + 点状 LLM** | 长链路里 LLM 每步自由发挥 = 不可复现；这里只有 design/debug 调 LLM | `call_llm` 唯一漏斗；`docs/llm_audit.jsonl` 记 site/node/round/prompt_hash |
| **领域深度** | 不是"套个 LLM 壳"：UVM 模板、bind 探针、双采样通道、种子管理、分级回归、约束编译 | `tool_uvm` / `casemodel_tools` / `regression_framework` |
| **可扩展框架** | 新增 realization / 阶段 / 约束编译器**核心零改动**，且有测试钉住 | `REALIZATIONS` / `MethodologyPipeline.insert` / `CONSTRAINT_COMPILERS`；`test_framework.py` |
| **个人级治理** | 巨头服务企业客户，个人/小团队的"可审计签核"是空白 | 项目隔离、token 预算、人工审批、检查点、血缘、证据包 `dump` |

### 劣势（当前真实的天花板）

| 劣势 | 具体表现 | 影响 |
|---|---|---|
| **观测型覆盖的最后一公里** | 计划覆盖率已 95.23%，但 2 条观测型 TP（`D_dep=WAR` / `D_decision=BLOCKED`）仍 0 命中 | 签核 `PASS_WITH_CAVEAT`（可签、带条件），不是 `READY`；需要补状态到达或模型声明不可达 |
| **约束只部分生效** | 5/11 条策略有真实赋值；`sequence` 型维度（`D_seq`/`D_pipeline`）没有场景序列生成器；非法交叉未编译 | 随机批次仍可能"打不到该打的状态" |
| **参考模型层重构中** | `model_library/` 已删，SQL `ModelRegistry` 只有 draft；18 个测试是已知失败 | `scoreboard`/golden 参考模型链路不完整 |
| **模型依赖人工** | 高质量 case 模型要人写；front 的草稿弱；spec→model 的桥不健全 | 换一个模块，方法学收益取决于建模质量 |
| **LLM 作用面窄** | 只有 design/debug 调 LLM；不做 LLM 覆盖率归因（**有意**） | "AI 验证"叙事要收敛成"确定性验证 + 点状 AI" |
| **规模** | 本地串行回归；244 条 sims 约 14 分钟；单用户；依赖 Questa/license | 不适合大团队/大规模并行；个人级定位要守住 |
| **界面** | PySide6 桌面工作台，非 Web；部分页面仍是通用产出视图 | 不是核心卖点，但"可视化"体验会拖后腿 |
| **竞争** | 三大 EDA 已把 agentic verification 做进原生工具（Questa One / ChipStack / AgentEngineer） | 不能拼"AI 更聪明/覆盖率更快"，只能拼**可复现·可审计·可治理**的签核 |

### 一句话定位

> **不和巨头拼"AI 覆盖率收敛速度"；把「可复现 · 可审计 · 可治理的签核证据链」做成个人/小团队的默认答案。**
> 测试点 IR（`tp_id`）是这条链的主键，`methodology.json` / `tp_matrix.json` / 三态签核是它的证据面。

---

## 已知问题与路线

### 参考模型层（重构中，占当前已知失败的大头）

`tests/test_agents.py` / `test_golden_bench.py` / `test_ref_model_wiring.py` /
`test_sim_modes.py` 共 **18 个已知失败**。根因是**唯一一条**：`model_library/` 目录已从磁盘删除
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
- [x] **工具白名单的角色对上了**：`ToolHub.EXECUTOR_TOOL_MODULES` 是一张
      `executor → 模块` 的映射表（一处维护），替换了两处"对不上就回退到**全部**工具"
      的逻辑 —— 那个回退让白名单形同虚设（一个只该读 spec 的 `design` 手里握着
      `write_file` 与 `regression.run`）。表**建在实测用量上**（各 executor 里
      `call_tool(...)` 的名字落在哪个模块），并由 `tests/test_tool_roles.py` 从
      `executors/` 目录读角色反查"有没有漏登记"。
      **空元组 = 声明不用工具**（`_get_tools()` 返回 `[]`），与"没查到"分得开 ——
      混成一个的话前者会拿到全部工具。注：`ops` 那条是**同名巧合**撑着
      （模块角色里也有个 `ops`），迁移时按"名字一样所以不用映射"归零会把它的
      `regression.run` 拿走，有测试钉住。
- [x] **token 上限已提到 16384**（`config/settings.py`；原 8192/4096 会截断长端口表）。
      `async_fifo` 这条历史失败**需要复测**，不再用旧上限当理由。
- [x] **批次 test 类跑起来了**（原来这条写的是"要等 `vsim` 可用" —— 那是**误判**，
      仿真器一直是好的，`Error loading design` 是设计侧 load 失败）：
      分级回归五级全 PASS（最新一轮 **249/249**），`npu_basic_test` 真执行
      （`Errors: 0`、`mismatched=0`、覆盖率落库），用例目录按种子逐条展开，
      `sim.sh` 里 `+UVM_TESTNAME=<批次名> +ntb_random_seed=<base+i-1>`。
      证据见「一轮完整的端到端实测」那节。
- [ ] **种子有没有真改变激励分布**没验：种子进了命令行是事实，但"随机化真起作用"
      要拿各批次的 ucdb 逐 bin 比 —— 前者不等于后者。
- [x] **批次约束已从 sequence 收回到模型**：`theme_policy_map` 是策略名的**唯一出处**
      （`build_constraint` 的 `policies[].name` 与 `batches[].policy` 同名，实测 11/11
      逐字一致 —— 两份各推一次就会漂，而漂了的表现是"约束没生效但回归全绿"）；
      批次 test 类挂全局 `batch_policy`，协调序列按 `create_from_batch()` 建策略
      （plusargs 保留为回退）。**且已接进 verify**（见上一节）。
- [x] **约束层已接通并部分生效**：`env/cons/*` 真进编译；批次 test 触发协调序列；
      `stimulus` 维度编译成 `apply()` 里的真实赋值（NPU：5/11 条）。
- [ ] **约束仍有一半是骨架**：6/11 条对应观测型维度（没有 `stimulus.field`），
      `sequence` 型维度（`D_seq` / `D_pipeline`）还没有场景序列生成器；非法交叉
      （需要两侧都可驱动）尚未编译成排除约束。
- [x] **覆盖率硬门禁已过（计划口径）**：签核改用**回归全量用例库合并**的计划覆盖率，
      最新一轮 **95.23% ≥ 95%**（254 条用例库）；单条 coverage test 的 68.57% 不再
      作为签核数字。可激励 TP 26/26 命中、backdoor TP 10/10 到位。
- [ ] **观测型仍有两个缺口**：`D_dep=WAR`、`D_decision=BLOCKED` 在计划覆盖率里 0 命中，
      证据包标为 `SUSPECT`；需要补状态到达手段，或在模型里显式声明不可达/降级分母。
- [ ] **种子多样性未验**：证据包 `seed_diversity: null` —— 需要逐 bin 比对同一批次
      不同种子的命中集合，才能把"可复现"从"种子进了命令行"升级为"分布真的不同"。

---

## 让「半生效状态无处躲藏」

架构已经把最危险的静默路径堵死了（失败响亮 / 覆盖率库固化 / 审批驱动图）。
剩下的风险换了形态：**管道通了 ≠ 语义生效** —— 每一处都是"看着绿、其实空"。

| 半成品态 | 谁看得见 |
|---|---|
| `env/cons/` 生成了，但一部分策略仍落在 `default:` 分支、不做任何事 | `coverage/constraint_status.json` 的 `backed_policy_count / unbacked_policy_count`；`constraint_policy_applied=false` → audit 判 **`PASS_WITH_CAVEAT`** |
| ucdb 落了库，4360 个 bin 一个没命中 | `semantic_validations.ucdb_nonzero_bins=false` → 同上 |
| `cg_dut` 零命中（bind 探针没挂上） | `semantic_validations.cg_dut_hit_gt_zero=false` → 同上 |
| 三模型关联的**硬边**断了（声明要测的没落成覆盖仓） | `coverage/association_report.json` 的 `hard_edge_broken` → 同上 |
| 测试点与覆盖仓漂了（模型改了、覆盖率模型没跟上） | `coverage/tp_matrix.json` 的 `UNMAPPED`（**不冒充"没命中"**）；`testpoints_traced=false` |
| 可激励测试点的大量仓没命中 | `tp_matrix.drivable_pct` + `missed[]`（逐条带 `tp_id` / 需求 / 回归级） |
| 单条 coverage test 的漂亮数字 ≠ 回归计划的覆盖率 | `coverage_result.json` 同时记 `plan_coverage.functional_pct`（签核口径）与 `single_test_pct`；**签核门禁用前者** |
| 证据散在七八个文件里，无法对外交换 | `<run>/signoff_evidence.json`（`signoff_evidence_v1`）：RTL 哈希 / TP IR sha256 / 计划覆盖率 / TP 矩阵 / caveat + 建议动作 / 不可达嫌疑 / LLM 审计摘要 |

**签核从两态变三态**：`READY` / **`PASS_WITH_CAVEAT`**（硬门禁全过、但有软缺口 ——
能签，报告里写清保留了什么）/ `NEEDS_FIX`。`signoff_status` 相应是
`APPROVED` / `CONDITIONAL` / `REJECTED`（`NEEDS_FIX` 原来也标 `CONDITIONAL`，
读起来像"可以签、带条件"，与"根本不能签"是两回事）。

`vagent verify --strict-semantic` 把 `PASS_WITH_CAVEAT` 升格为失败（exit 5）——
**人看报告时那几行是提示，上了 CI 就得当失败**。

**一条纪律：只有显式的 `False` 才算缺口。** `None` 是"判不了"（这一轮没跑覆盖率 /
没生成约束），而"判不了"到处都是 —— 把它也算进来的话几乎每个 run 都挂 caveat，
三态就贬值成"反正总有一条"，没人再去看那几行。

### 另外两处"溯源"

- **启动期分层守卫**（`src/layers/_bootstrap.py`）：`python -m src.cli.commands …`
  冷启动就扫一遍 `src/layers` 的 import 方向，违规即 `exit 4`。规则与
  `tests/test_layer_direction.py` **同一份**（那个测试 import 它）。拆模块时本地
  立刻炸，不必等 CI 跑完全量。**函数体内的延迟 import 照样算违规**（AST 走整棵树）。
- **LLM 点状调用的出处**（`<run>/docs/llm_audit.jsonl`）：每次 `call_llm` 记一条，
  带 `site`（调用点，`inspect` 自动取，不手写）+ `node_id` / `round`（由
  `_run_agent` 经 contextvar 钉进来，那是唯一同时看得见 `state` 与 `task` 的地方）
  + `prompt_hash`。**内存只留最近 500 条，磁盘是权威** —— 出处是**事后**才问的
  问题，进程一退就没了的那种记录等于没有。

---

## 测试

```powershell
python -m pytest tests/ -q                            # 948 collected；除 18 个已知失败外全绿
python -m pytest src/workbench/tests -q               # 工作台：713 passed
python -m pytest src/tools/casemodel_tools/tests -q   # case 建模 + 框架 + 覆盖率方法学：509 passed
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
| `casemodel_tools/tests/test_framework.py` | 阶段依赖前置报错、注册表扩展（新增 realization/constraint **不改核心**）、manifest 哈希与实际落盘文件一致 |
| `tests/test_stage_filtered_generation.py` | 分级回归只生成**本级 tag** 的用例目录；非分级调用保持全量树 |
| `tests/test_coverage_coverstore.py` | `questa.db`（coverstore）必须走 `vcover merge "<store>:<test>"`，否则功能覆盖率静默丢失；`(null).data` 走无 test 名的形式 |
| `tests/test_audit_evidence.py` | `signoff_evidence_v1`：RTL/IR 哈希、计划覆盖率口径、`seed_diversity: null`、不可达只标 `SUSPECT` |
| `casemodel_tools/tests/test_plan.py::TestBackdoorRealization` | backdoor 维度带 `path`、不进 `observe`；缺 path 回退并记账 |

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


不是“多用户并发请求”，也不是说你不该做性能优化。这句话拆开是两层意思，我上一轮说得太压缩了。

## “不拼 AI 聪明度”

指的是：**不去比“谁的 LLM 更会写 RTL、更会归因覆盖率缺口、更会自主决策”。**

巨头的路线是让 agent 越来越自主——Cadence ChipStack 号称 Level-5 自主性，目标是“你给个自然语言需求，它自己把验证跑完”。它们的护城河是：模型 + 海量内部验证数据 + 与自家 EDA 的深度耦合。你如果也往“让 LLM 更聪明地自主决策”使劲，是在它们的优势战场上用你的短板打。

而你的项目恰恰是**反着设计的**——文档原话：“流程、决策、工具选择都是确定性的，LLM 只在‘该写一段代码/该给一个判断’的那个点上被叫一次”。8 个执行器里只有 `design` 和 `debug` 调 LLM，决策硬动作永远走规则，RL 只做降级建议不拍板。

**这不是能力不足的妥协，是刻意的产品选择。** 你的卖点是“可复现”——同一个 spec 跑两遍结果一样。LLM 每步自由发挥的长链路是不可复现的。所以“不拼聪明度”= 别把确定性编排改成“更多 LLM 自主”，那会毁掉你唯一稀缺的东西。

## “不拼吞吐量”

指的也不是“不做并发”。**个人级 CLI 根本不存在“多用户并发请求”这个问题**——一次就一个用户在本地跑，没有服务端、没有多租户。这跟商用 SaaS 的并发是两回事。

我说“不拼吞吐量”，针对的是巨头叙事里的**规模指标**：比如 Cadence 宣传的“40x 验证加速”“五周压到一天”，那是靠 Xcelium 大规模并行 + 云资源堆出来的。你要去比“谁能更快跑完一万条回归”，比的是机器和 license，不是你的代码。

但这**不等于**我反对你做性能优化。上一轮我明确提了两条：同 build 的 sims 合并成一次 `vsim` 会话、`vsim -batch` 按核数并行。244 条串行 14 分钟压到 3-5 分钟，这完全该做，而且不破坏个人级定位。**“个人级”不等于“串行低效”，这个我同意你。**

区别在于：优化是**为了你自己的闭环转得更快**（跑更多轮、更快看到覆盖率轨迹），不是为了**在“吞吐量”这个指标上跟巨头比高低**。前者是工具体验，后者是军备竞赛。

## 那到底拼什么

拼**“同一个 run 的证据，半年后别人能逐条验证”**。这个维度上，快 40 倍没用——你跑得再快，如果 `sim_vsim.log` 不存在被记成 pass、ucdb 落了 4360 个 bin 零命中还报绿，快就是负资产。

所以那句话的完整意思是：**把工程精力放在“证据链的完整性和诚实度”上，而不是放在“让 agent 更自主”和“跑得更快更多”上。** 后者你赢不了，也不需要赢；前者巨头不做，因为它们的客户有流程和签字兜底，而你的客户（个人、小团队）没有，只能靠工具本身诚实。