# isa_gen_tools —— NPU ISA 事务序列生成器

吃一份**场景 DSL**（YAML：意图 / 资源 / 事务池 / 形状与精度 / 编排），
吐一份 **IR**（ISA 事务层 JSON：带语义标注的指令流 + 地址分配 + 张量引用）。

对应 `08_验证策略.md` §3.5 那条流水线的生成侧前两段：

```
DSL(YAML) ──求解器──► IR(JSON) ──编码器──► 32bit(seq.hex, v1)
```

**编码器不在本包**（§3.1 把 L3 划成独立一层）。IR 是文档反复引用的单一契约层
—— TB 执行器消费 IR、比对模块靠 IR 的 `binds/writes` 索引、ISS 消费由同一
过程产出的二进制。先把这一层钉死，编码器和 tensor_gen 都能各自独立加进来。

---

## 命令

```bash
# 示例在 config/isa_gen/examples/
python -m src.tools.isa_gen_tools.cli validate config/isa_gen/examples/npu_gemm.yaml
python -m src.tools.isa_gen_tools.cli compile  config/isa_gen/examples/npu_gemm.yaml -o out/ --max-txns 16
python -m src.tools.isa_gen_tools.cli explain  --txn gemm_txn     # 注册表解读
python -m src.tools.isa_gen_tools.cli ops                        # 列出 op 注册表

# 不带 -o 就只打到 stdout，不落盘
python -m src.tools.isa_gen_tools.cli compile config/isa_gen/examples/minimal.yaml
```

`--seed` 是**覆盖**（不给则用 `meta.seed`，再没有才取时间戳）；
`--memmap` 指定 memmap；`--json` 出机器可读的完整产物。

退出码：有 error → `1`，DSL 或注册表读不了 → `2`，正常 → `0`。

### 示例

| 文件 | 演示什么 |
|---|---|
| `minimal.yaml` | **七段里只有 `meta` 是必填的** —— 多小才能跑。没有 `alloc` 时池子自动缩到"不需要动数据"的那几条事务 |
| `npu_gemm.yaml` | GEMM 为主的一轮活动：`gemm_out_org_pre_xn → gemm_drv_xn` 的强配对、CIMC 里的权重、5 个对象的地址分配 |
| `npu_noc.yaml` | 跨核搬运为主：`noc_pair_txn` 的 **dst/src 强配对且 `adjacency="strict"`**、两核反复搬同一块地方（地址复用） |

`tests/test_pipeline.py::TestExampleFiles` 会**逐份校验 + 逐份编译** —— 一份跑不
起来的示例比没有示例更糟：它教人写错的东西。

### 落盘布局 —— §3.6 的六件套

`compile -o <dir>` 按文档 §3.6 的布局落盘。**六件套分三层产**，但都由
`compile -o` 一次写完（三段都是确定性的，分开跑反而更容易忘）：

| 文件 | 谁写 | 层 |
|---|---|---|
| `case.json` | **isa_gen** | L1→L2 |
| `seq.ir.json` | **isa_gen** | L1→L2 |
| `preload.json` | **isa_gen** | L1→L2 |
| `expect.json` | **isa_gen** | L1→L2 |
| `seq.hex` + `reg-init.txt` | **`encode/`** | **L3 二进制编码**（§3.1） |
| `seq.lst` | **`encode/`** | 上一条的**人可读视图** —— NICE/VNICE 指令流逐条列出 |
| `tensors/*.hex` | **`tensors/`**（tensor_gen） | §3.12.9 |
| `manifest/*.json` + `registry.json` | **`tensors/`** | §3.12.9 |

`registry.json` 是 isa_gen 的 ref 解析 / CMI preload / scoreboard 共用的
**唯一枢纽**（§3.14.4）—— 所以由 tensor_gen 写、三方读。

**约定**：三个组件必须往**同一个 `tests/cases/<case_name>/`** 写，
各自只写自己那几份、**不覆盖别人的**。两条判据：

- `expect.json` 先由本工具写**锚点**、后由 ISS **覆盖期望值** —— 这是唯一允许的
  原地更新（文件头的 `"$comment"` 已声明这件事）
- 其余文件「谁写谁负责」，跨组件不重写

> `seq.hex + reg-init` 的措辞出自 §3.0 的产物图；§3.6 的布局只列了 `seq.hex`。

#### 为什么本工具不写那两份

| 缺什么 | 归属 | 依据 |
|---|---|---|
| `seq.hex` | **编码器** | §3.1 把 L3（二进制编码）划成独立层，理由之一是**编码表变更只影响编码器模块**。若本工具直产二进制，改一次 funct7 就得重跑全部用例 —— 而现在 IR 一个字节都不用动 |
| `tensors/` | **tensor_gen** | §3.14.1 的契约是「**标量走指令字段、张量走内存**」，IR 里只放 `$t.xxx` 句柄；§3.14.4 又立了 registry 为**唯一枢纽**，工具之间**不允许再传数据文件** |

#### 不写空占位文件

一个空的 `seq.hex` 比没有它**更容易让人以为"生成过了"**。缺就是缺，
让下游一眼看出来 —— 和本工具其它地方的「fail loud」是同一条纪律
（`illegal_ratio > 0` 记成 note、EDA 缺失报 `EDA_MISSING`、无输入时不静默填 `dut`）。

---

## 四条结构性不变式

这是本工具与"随机造指令"的根本差别，也是它能不能用的分界线。

### 1. 随机化的最小单元是**事务**，不是指令

ISA 有强配对：`group_mask → cfg → [pre] → drv`；`tld` 前必须有 `tld_cfg`；
`gemm` 前必须有 `gemm_out_org_pre`。**以单条指令为随机单元会高概率产出非法
序列**（§3.9）—— 而非法序列漏进仿真，表现得像器件行为异常。

实现上不是"先生成再检查配对"（那等于把不变式放在代码之外），而是让**类型**
禁止它：IR 程序由 `Transaction` 组装，`Transaction.instructions` 是**有序
不可分的元组**，没有任何 API 能单独放一条 `gemm_drv_xn`。

`program.py` 里那条 `PairingError` 断言**按设计永远不会触发**；它只为
"从裸 dict 反序列化一份历史 IR"这条逃生口存在。有测试专门造一次裸 dict
让它响 —— 一条跑不到的断言和没有断言是一回事。

### 2. 标量走指令字段，张量走内存（§3.14.1）

两条通路**互不交叉**。`operands{rs1val,rs2val}` 只放字面量；张量一律走
`binds/writes` + `ref`。张量引用出现在指令字段里 = `DataPathError`。

### 3. 编译期失败是一等公民（§3.0.1 / §3.12.6）

文档列的失败类做成 `CompileError` 的**具名子类**（`domain/errors.py`），
`api` 返回 `{"error", "kind", "target", "fix"}` 而不是抛。`fix` 是"该改什么"
—— 没有它，报错只能靠猜。

对 NPU 尤其重要：地址分配无解、`pre/drv` 配对缺失这类问题**漏进仿真会表现
为器件行为异常**，排查成本远高于生成期报错。

### 4. 确定性：加一个张量不动既有比特（E5，§3.12.9）

每个可随机对象各自一条流：`派生 seed = hash(case_seed ⊕ name)`。
**禁止共享 RNG** —— 共享的话，新增一个对象会把它之后所有对象的取值整体挪位。

`compile/sequencer.py` 是**全包唯一允许出现随机的地方**，其余模块
`import random` 会被 `tests/test_layering.py` 的源码守卫抓出来。

---

## 两份注册表是**数据**不是代码

| 文件 | 内容 | 来源 |
|---|---|---|
| `schema/ops.registry.json` | 95 条指令 + 27 条非指令 op | `build_registry.py` 从《指令编码总表》xlsx 编出 |
| `schema/txn.registry.json` | 33 条事务（可用 32） | 文档 §3.11 的 L1 事务原子清单 |
| `schema/dsl.schema.json` | DSL 契约 | **由 `domain/dsl.py` 的 pydantic 模型生成** |

**加一条指令是 JSON 编辑 + schema 校验**，git diff 里看得见。编码器（v1）直接读
`ops.registry.json` 的 `funct7`，一行代码都不用改 —— 这就是"编码表唯一来源、
变更只影响编码器模块"那条设计意图的落点。

`schema/dsl.schema.json` **不要手改**：`tests/test_dsl.py` 会断言它与模型一致。
要改契约就改 `domain/dsl.py`，然后跑：

```bash
python -m src.tools.isa_gen_tools.schema.gen_dsl_schema
```

更新编码表：

```bash
python -m src.tools.isa_gen_tools.build_registry \
    --pre-drv "HM056_V2_ISA_Pre_Drv.xlsx" \
    --out src/tools/isa_gen_tools/schema/ops.registry.json
```

---

## 编码表里的疑点 —— **记录，不修**

`explain` 存在的理由就是这个。工具**没有立场替编码表做判断**，
但必须让使用者看得见 —— 悄悄按一种解释跑下去，是拿仿真时间赌一个猜测。

跑 `isa_gen ... explain` 会看到：

| 码 | 现象 |
|---|---|
| **XL-02** | `tld_drv_xn` 与 `gtld_drv_xn` 同为 `010_0001` **且 flags 也相同**，靠地址段（local/global）区分 |
| **XL-06** | `set_CIMCmode_drv_xn` 文档提过，硬件已移除、编码表里没有 |
| **XL-08** | `vv_v_drv_xn` 与 `vvv_v_drv_xn` 同为 `101_1000`，靠 `xd/xs1/xs2` 区分 |
| **XL-09** | TMV 的 `bc_drv_xn` 一族共用一个 funct7 段，与 NoC 是否重叠待确认 |
| **X-00** | `rd_csr_txn`：文档 §3.2/§3.11 列为 Control 指令，**编码表里没有** |

另外 `explain` 会列出：

- **6 组同码指令**，其中 `gtld_drv_vn01` 与 `noc_drv_vn01` 是**跨类碰撞**
  （前者声明在 GLSU，funct7 却是 NoC 前缀 `001`）
- **16 条指令的 funct7 类前缀与声明的类不符**（全是 VNICE 行）
- **6 条指令标了"暂时不做"**

这些都不修：改 funct7 是改指令语义，那是编码表作者的事。

**指令的身份是 `(funct7, xd, xs1, xs2)` 四元组，不是 funct7。**
只按 funct7 考虑，编码器会把 `noc_drv_dst_xn` 编成 `noc_drv_src_xn` ——
数据搬错方向，而且不报错。

---

## 目录

```
src/tools/isa_gen_tools/
├─ api.py            四个 run_*（纯）；失败返回 {"error","kind","target","fix"}
├─ cli.py            validate | compile | explain | ops
├─ export.py         落盘（**本包唯一有副作用的地方**），CLI 与界面共用
├─ build_registry.py 从编码表编出 ops.registry.json（维护脚本，不被运行时 import）
├─ schema/           三份数据：ops 注册表 / 事务注册表 / DSL 契约
├─ domain/ errors · opcode · instruction · address · memmap · dsl · transaction · program
├─ repository/       registries · txn_registry · memmap
├─ compile/          sequencer · resources · allocator · solver · templates
│                    · epochs · annotate · pipeline
├─ analysis/         issues · schema_check
├─ fixtures/         memmap.yaml（从文档重建的样例，**不是冻结版**）
├─ reference/        ★ 引用资料 —— 本工具的权威来源，见下
└─ tests/            10 个测试文件
```

示例 DSL 在 **`config/isa_gen/examples/`** —— 与 `casemodel` 一样放在 `config/`
而不是包内：这些 YAML 同时被命令行与验证工作台（`src/workbench`）使用，
而两边谁都不该依赖对方。

## 引用资料（`reference/`）

编码表与验证策略是**本工具的权威来源**，所以随包走，而不是散在某个人的桌面上
—— 「这个数字是哪来的」要能对着文件核出来。

| 文件 | 用途 |
|---|---|
| `HM056_V2_ISA_Pre_Drv.xlsx` | **《指令编码总表》** —— `schema/ops.registry.json` 的唯一来源 |
| `08_验证策略.md` | 顶层验证策略 —— `schema/txn.registry.json`、DSL 七段、IR 契约、地址模型、约束分层的来源 |
| `HM056_V2_ISA_Cfg.xlsx` | **尚未接入**（cfg 字段取值域） |
| `场景约束方法学.docx` | **尚未接入**（L0/L1/L2 分层的权威） |
| `精度专题.docx` | **尚未接入**（`ISA_Prec` 表 / E8 合法组合） |

详见 `reference/README.md`（含从编码表重建注册表的命令）。

---

## 磁盘上还没有的两份东西

| 缺什么 | 影响 | 现在怎么办 |
|---|---|---|
| **`verification/memmap.yaml`（冻结版 v1.0）** | 地址规则的权威来源 | 用包内 `fixtures/memmap.yaml`（**从文档 §3.12.5 重建的样例，不是冻结版**）。真文件放到 `verification/` 或 `config/` 会被优先自动使用，也可以 `--memmap` 指定 |
| **44 位地址里"区内偏移"的位宽** | 文档只把布局写到那儿就停了 | 按 `Page_num(4) + 区内偏移(13)` = 17 位 = 128KB 实现（正好是 SPAD 大小）。见下 |

**地址模型里两处文档不自洽**（都写在这里当路标）：

1. **13 位装不下 SPAD。** 按布局字面算，区内偏移只有 13 位 = 8KB，
   而同一份文档说 SPAD 是 128KB。先按 13 位实现过一次，把 8192 截回 0 ——
   于是 SPAD 里第二个 8KB 以上的对象和第一个算出同一个地址，**而且不报错**。
   现在按两级（`Page_num + 区内偏移`）拆。
2. **DRAM 根本装不下。** 2GB 的偏移要 31 位，而布局里可用的只有 17 位。
   所以 DRAM 走**普通十六进制字面量** —— 文档 §3.0.2 的 IR 样例本来也是
   这么写的（`"src_addr": "0x1_0004_0000"`）。

---

## 与别的工具的关系

**没有 import 关系。** 本仓库的规矩是工具之间只有**文件格式契约**
（谁往同一个用例目录写哪几份，见上文「落盘布局」）：

- 与 **编码器**（§3.1 的 L3）：`seq.ir.json`。本工具产 L2，编码器读它产
  `seq.hex`；两者分层是因为**编码表变更只影响编码器模块**
- 与 `tensor_gen`：`preload.json` 里的 `ref` 句柄（本工具只给句柄与 `exp_range`，
  张量数据由 tensor_gen 生成）
- 与 `tool_uvm`：无（IR 不产 UVM 代码）

---

## api 面

```python
from src.tools.isa_gen_tools.api import run_compile, run_validate

run_validate(dsl_text)                                  → {"valid", "issues", …}
run_compile(dsl_text, seed=…, max_txns=…)               → {"ir", "case", "preload", …}
run_explain(txn="")                                     → {"collisions", "risks", …}
run_ops()                                               → {"ops", "without_encoding", …}
```

失败一律返回 `{"error", "kind", "target", "fix"}`，**不抛**。
`TOOL_NAMES` 与 `RUNNERS` 必须一致（有测试钉住）。

**v0 没有 `run_encode`** —— 编码器落地时在同文件加一个，读注册表的 `funct7`，
注册表一行不用改。

---

## 测试

```bash
python -m pytest src/tools/isa_gen_tools/tests -q
```

（注意：本仓库 `pyproject.toml` 的 `testpaths` 只含根 `tests/`，
所以要显式给路径 —— 或者加 `-p no:cacheprovider` 之类的方式让 `src/` 下的测试
被发现。这是工具层架构文档里记的那条既有缺陷。）
