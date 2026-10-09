# 引用资料 —— 本工具的**权威来源**

放在这里而不是散在某个人的桌面上，理由有两条：

1. **工具得能自己跑**。`build_registry.py` 要从编码表编出
   `schema/ops.registry.json`；资料不在，这个包就没法重建自己。
2. **"这个数字是哪来的"要能回答**。注册表里每个 `funct7` 都出自这里的某一行
   —— 对着文件核得出来，而不是"当时有人说"。

| 文件 | 是什么 | 本工具用它做什么 |
|---|---|---|
| `HM056_V2_ISA_Pre_Drv.xlsx` | **《指令编码总表》**（Pre/Drv）。6 个 sheet：`ctrl` / `noc` / `glsu` / `tmu` / `mpu` / `vpu` | `schema/ops.registry.json` 的**唯一来源** —— 95 条指令的 funct7 / flags / opcode 全出自这里 |
| `HM056_V2_ISA_Cfg.xlsx` | **Cfg 字段总表**。`TLD_cfg` / `TST_cfg` / `TMU_cfg` / `MPU_cfg` / `VPU_cfg` / `Noc_cfg` / `数据精度编码规则` / `VPU_op_mode` | **尚未接入**。`npu_cfg_drv_xn` 的 payload 字段、以及 §3.11 说的"精度与操作的合法组合以 ISA_Prec 表为准"都要它 |
| `08_验证策略.md` | **顶层验证策略**（v4.3，1806 行） | `schema/txn.registry.json` 的来源（§3.11 的事务清单）、DSL 七段（§3.10）、IR 契约（§3.1/§3.2）、地址模型（§3.12）、约束分层（§3.9/§3.15） |
| `场景约束方法学.docx` | 场景约束方法学 | **尚未接入**。§3.9 的 L0/L1/L2 分层、§3.15 的缺口→偏置映射表应当以它为准 |
| `精度专题.docx` | 精度专题 | **尚未接入**。§3.11 的 `ISA_Prec` 表、E8（dtype×区域×指令类的合法组合） |

## 从编码表重建注册表

```bash
python -m src.tools.isa_gen_tools.build_registry \
    --pre-drv src/tools/isa_gen_tools/reference/HM056_V2_ISA_Pre_Drv.xlsx \
    --out     src/tools/isa_gen_tools/schema/ops.registry.json
```

跑完看一眼 diff —— **注册表进 git 就是让"表变了"看得见**。
重跑之后测试会告诉你哪几条对不上了（`tests/test_registry.py` 把数量与几条疑点都钉着）。

## 两份 docx 与 Cfg 表还没接的原因

它们**不是**用来生成指令的，是用来生成指令**内容**的：

- Cfg 表定义 `npu_cfg_drv_xn` 要往哪个 cfg 寄存器写什么 —— 属于"cfg_txn 的取值域"
- 两份 docx 定义精度组合的合法域 —— 属于"E8：dtype × 区域 × 指令类的合法性"

v0 的 DSL→IR 不碰这些（IR 里 `cfg` 只是一个**表名**，比如 `tld_cfg`），
所以它们现在是"有权威、但还没被消费"。接进来时应当补一张
`schema/cfg.registry.json`，与 `ops.registry.json` 同样的做法。

## 已知的疑点

`isa_gen explain` 会把"文档与编码表对不上"的地方原样端出来 —— 那些结论就是
对着这两份文件比对出来的。例如：

- `rd_csr_txn`：`08_验证策略.md` §3.2/§3.11 把它列为 Control 指令，
  而《指令编码总表》的 `ctrl` sheet 里没有它（只有 10 条，不含 csr 类）
- `gtld_drv_vn01`：声明在 GLSU，funct7 前缀却是 `001`（NoC），与 `noc_drv_vn01` 撞车

**这些不修。** 工具没有立场替编码表做判断 —— 改 funct7 是改指令语义，
那是编码表作者的事。`explain` 把它们摆出来，让人自己判断。
