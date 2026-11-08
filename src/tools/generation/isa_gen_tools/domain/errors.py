"""异常 —— **编译期失败是一等公民**。

为什么这个包把异常设计得这么重
    HM057 的 ISA 有强配对的**事务结构**（`group_mask → cfg → [pre] → drv`），
    与 RV 那种"指令基本独立"的世界不同。后果是：一次不合法的生成，
    **漏进仿真不会报错，会表现为器件行为异常** —— 地址分配算错就是数据搬到
    了另一块存储，`pre/drv` 配对缺一条就是流水线静默少算一次。

    所以文档（§3.0.1 / §3.12.6）列了 10 类必须**在生成期拦下**的失败。这里把它们
    做成具名子类，不是为了好看，是为了：
      · `api` 能返回 `{"error", "kind", "target", "fix"}` 而不是一句泛泛的报错；
      · 测试能**逐类**断言（每类一条正例一条反例），而不是断言"抛了个异常"；
      · 使用者看到 `kind` 就知道该改 DSL 的哪一段。

与 旧建模引擎的 `CaseModelError` 同一套做法：领域异常继承 `ValueError`，
`api` 层统一兜住转成 dict，不让异常穿到调用方。
"""
from __future__ import annotations

from typing import Any, Optional


class IsaGenError(ValueError):
    """本工具所有领域异常的基类。"""


class CompileError(IsaGenError):
    """生成期失败 —— 带 `kind` / `target` / `fix` 三件套。

    `kind`   机器可读的类型（子类名去掉 Error 后缀的蛇形），适配器与测试按它分发
    `target` 出错的对象（DSL 的哪一段 / 哪个 ref / 哪条 op）
    `fix`    给人看的一句话：**该改什么**。没有 fix 的报错等于把问题丢回给使用者
    """

    kind = "compile_error"

    def __init__(self, message: str, *, target: Any = "", fix: str = "",
                 detail: Optional[dict] = None) -> None:
        super().__init__(message)
        self.message = message
        self.target = str(target)
        self.fix = fix
        self.detail = dict(detail or {})

    def to_dict(self) -> dict:
        out = {"error": self.message, "kind": self.kind, "target": self.target}
        if self.fix:
            out["fix"] = self.fix
        if self.detail:
            out["detail"] = self.detail
        return out

    def __str__(self) -> str:              # 日志里一眼能看出是哪一类
        bits = [f"[{self.kind}]", self.message]
        if self.target:
            bits.append(f"@ {self.target}")
        if self.fix:
            bits.append(f"→ {self.fix}")
        return "  ".join(bits)


# ═══════════════════════════════════════════════════════════════
# 文档 §3.0.1 / §3.12.6 列的失败类
# ═══════════════════════════════════════════════════════════════

class SchemaError(CompileError):
    """DSL 不符合 `schema/dsl.schema.json`（键名拼错 / 类型不对 / 必填缺失）。

    文档没有单列这一类，但它是流水线的第 0 步 —— 一份连键都拼错的 DSL
    不该走到地址分配那一步才报错。
    """
    kind = "schema"


class RegistryError(CompileError):
    """op / 事务注册表本身有问题（缺字段、funct7 格式不对、身份重复）。

    这一类**不是使用者的错**，是工具自己的数据坏了 —— 所以它必须 fail-closed：
    注册表读不进来时宁可起不来，也不要拿着一半的表去生成。
    """
    kind = "registry"


class LintError(CompileError):
    """合法性检查没过。

    两种来源，文档把它们归为同一类失败语义（§3.12.6）：
      · declared 模式：显式地址不在 memmap 声明的合法区域内
      · 复用观测点纪律：同一地址被时间复用时，两段之间没有观测点
    """
    kind = "lint"


class UnresolvedRefError(CompileError):
    """`ref` 符号解析不了（§3.0 契约 2、§3.14.4）。

    `binds` 里每个 ref 必须能在 registry 里找到 name。找不到就是生成期失败 ——
    **不允许静默越界**：一条引用了不存在张量的指令，在仿真里会读到垃圾数据，
    而比对会把它当成实现错误。
    """
    kind = "unresolved_ref"


class AllocError(CompileError):
    """地址分配器找不到合法分配（§3.12.5）。

    文档明确"分配器默认不回退到非对齐地址"—— 所以无解就是无解，不是"凑合给一个"。
    """
    kind = "alloc"


class SolverError(CompileError):
    """约束求解无可行解（§3.0.1 第 ② 步）。"""
    kind = "solver"


class WhitelistError(CompileError):
    """pre/drv 组合落在白名单之外（§3.0.1、§3.11 通用规则第 2 条）。

    ISA 的配对不是"任意 pre 配任意 drv"—— 组合白名单本身是规格的一部分。
    """
    kind = "whitelist"


class PairingError(CompileError):
    """配对不闭合（§3.11）。

    **按设计这条永远不会从正常路径抛出来**：IR 由 `Transaction` 组装，
    没有任何 API 能单独放一条配对的 drv。它只为"从裸 dict 反序列化"这条
    逃生口存在 —— 有测试专门造一次裸 dict 让它响，证明兜底是真的。
    """
    kind = "pairing"


class DataPathError(CompileError):
    """两条数据通路串了（§3.14.1 契约）。

    标量走指令字段（`operands`），张量走内存（`binds/writes` + `ref`），
    互不交叉。张量数据出现在指令字段里 = 生成期失败。
    """
    kind = "data_path"


class DeterminismError(CompileError):
    """确定性被破坏（§3.12.9 E5）。

    "新增一个张量不得改变既有张量的比特值" —— 一旦有用例在共享 RNG，
    这条就断了，而且**断得很隐蔽**（只是比特值变了，不报错）。
    所以宁可在这里响。
    """
    kind = "determinism"


class OperandUnsupportedError(CompileError):
    """编码表里的操作数形态本版本还生成不了。

    实测 95 条指令里 **63 条**落在这里（`domain/operands.py` 的分类）：
      · `addr_part` —— 一个 44bit 地址拆成两半（tld / gspe 一族，§3.12.2 T4）
      · `scalar`    —— 地址 + 标量（bc / v1s1 等，DSL 还没有标量来源）
      · `mask` / `cfg` / `special` —— `core_mask`、`addr of cfg_reg` 等复合字段

    为什么要单独一个类、而不是笼统报"格式不认识"：
    这三种形态**各自要补的东西不一样**（T4 拆地址 / DSL 标量来源 / Cfg 表），
    报 `kind` 才能让人知道该去补哪一块。

    **绝不用"差不多的解释"糊过去** —— 漏读一段位域就是把错误的高位送进仿真，
    表现是数据搬到别处且不报错。
    """
    kind = "operand_unsupported"


#: 具名类清单 —— 测试按它逐类造反例；`api` 按它判断哪些异常转成 dict。
COMPILE_ERROR_KINDS = (
    SchemaError, RegistryError, LintError, UnresolvedRefError, AllocError,
    SolverError, WhitelistError, PairingError, DataPathError, DeterminismError,
    OperandUnsupportedError,
)
