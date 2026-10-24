"""场景 DSL —— 测试作者写的那个 YAML（文档 §3.10）。

七段（§3.10.1），每段职责单一：

    meta             名称、seed、ISA 版本、目标
    resources        参与随机的核 / SPAD tile / CIMC page / DRAM 区域
    txn_pool         启用哪些事务原子、各自权重
    shape_space      形状的合法域（**离散枚举**，保证每个取值都映射到合法 tile 边界）
    precision_mix    精度分布
    intent           L2 意图旋钮：hazard 密度 / tile 争抢 / mcast 比例 / fence 频率
    orchestration    epoch 数量、同步点策略
    harness          节奏参数（可选）
    alloc            本 case 必须驻留的对象（§3.12.7）

**为什么用 pydantic 而不是手写 dataclass + 手写 JSON Schema**
    手写两份就一定会漂移 —— 这个仓库已经栽过一次（casemodel 的 `schema.yaml`
    注释指着已删除的 `agent/registry.py`）。这里让 pydantic 模型当**唯一真相**，
    `schema/dsl.schema.json` 由 `model_json_schema()` 生成，
    并有测试断言两者相等。于是"契约文件"既存在（外部可读、可 diff）、
    又不可能和代码对不上。

**为什么 `extra="forbid"`**
    键名拼错必须报错。静默忽略拼错的键，等于配置"看似生效实则失效" ——
    那比报错难查得多。文档里 `txn_pool` 和 `intent` 都可能被拼成别的样子，
    报错能立刻指出是哪个键。

关于 `illegal_ratio`（§3.10.2 字段约定）
    文档明说"负例不属于 DSL 范围"，默认 0。这里保留字段但**默认 0**，
    并在编译时把非零值记成一条 note —— 不假装它不存在，也不让它悄悄生效。
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, field_validator

#: 所有段的公共配置：不许有多余的键（拼错即报错）
_STRICT = ConfigDict(extra="forbid")


class DslMeta(BaseModel):
    """第一段 —— 这份 case 是谁、用什么 seed、打哪个目标。"""

    model_config = _STRICT

    name: str
    seed: Optional[int] = None          # 缺省 = 取时间戳（文档说"缺省取值时间戳"）
    isa_rev: str = "V0.8"
    target: str = "npu_subsystem_top"

    @field_validator("name")
    @classmethod
    def _name_not_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("meta.name 不能为空 —— 它是 case 的标识，落盘目录要用它")
        return value.strip()


class DslDram(BaseModel):
    """`resources.dram` —— 本 case 限定的 DRAM 范围。

    两种写法都认：`share: auto` 与 `share: [auto]`。文档的例子里
    `common: auto` 是标量、`share: [...]` 是列表 —— 同一段里两种形态并存，
    所以这里显式地把标量收成单元素列表，而不是让它俩分叉。
    """

    model_config = _STRICT

    share: List[str] = Field(default_factory=list)
    common: str = "auto"

    @field_validator("share", mode="before")
    @classmethod
    def _scalar_share_becomes_a_list(cls, value: object) -> object:
        if isinstance(value, str):
            return [value]
        return value


class DslRegionPool(BaseModel):
    """§3.12.7 的可玩池定义 —— 从 memmap 的全局合法域里再切一块本 case 能用的。"""

    model_config = _STRICT

    regions: List[str] = Field(default_factory=list)
    domains: List[str] = Field(default_factory=list)
    tiles: Optional[int] = None
    size: Optional[str] = None


class DslResources(BaseModel):
    """第二段 —— 参与随机的资源。

    `cores` 限定 `6b_grp_mask` 的随机域（文档字段约定第 2 条）。
    """

    model_config = _STRICT

    cores: List[str] = Field(default_factory=list)
    spad_tiles: Optional[int] = None

    @field_validator("cores", mode="before")
    @classmethod
    def _cores_accept_ints(cls, value: object) -> object:
        """`[0, 1]` 与 `["0", "1"]` 等价 —— YAML 把裸数字解析成 int，
        而核号写成 `0` 是最自然的写法。

        不收的话报的是一句很难懂的 `resources.cores.0: Input should be a
        valid string` —— 使用者要盯着它想一会儿才明白"原来是要加引号"。
        这种错不值得让人想一会儿。

        `[0..3]` 那种区间写法是**字符串**，原样透传，由 `solver.parse_cores`
        解释（它两种都认）。
        """
        if isinstance(value, list):
            return [str(item) for item in value]
        return value
    cimc_pages: Optional[int] = None
    dram: DslDram = Field(default_factory=DslDram)
    region_pools: Dict[str, DslRegionPool] = Field(default_factory=dict)
    exclude: List[str] = Field(default_factory=list)
    #: 故意允许地址重叠的比例（RAW 注入，§3.12.7）
    overlap_ratio: float = 0.0


class DslTxnPool(BaseModel):
    """第三段 —— 事务池。**随机化的最小单元是事务**（§3.9），所以这里是事务名。"""

    model_config = _STRICT

    include: List[str] = Field(default_factory=list)
    weights: Dict[str, int] = Field(default_factory=dict)

    @field_validator("weights")
    @classmethod
    def _weights_are_positive(cls, value: Dict[str, int]) -> Dict[str, int]:
        bad = {k: v for k, v in value.items() if v < 0}
        if bad:
            raise ValueError(f"权重不能是负数：{bad}")
        return value


class DslIntent(BaseModel):
    """第五段 —— **L2 意图层**的旋钮（§3.9 的 L2 / §3.15）。

    这一层刻意只有这些"软"参数：缺口回灌只允许改这里，
    **不允许碰 L0（编码合法性、配对、对齐）**。所以它的字段都是比例/密度，
    没有任何一个能改变"什么是一条合法指令"。
    """

    model_config = _STRICT

    hazard_density: float = 0.0
    tile_contention: float = 0.0
    mcast_mix: Dict[str, float] = Field(default_factory=dict)
    fence_every_n_epochs: int = 0
    illegal_ratio: float = 0.0

    @field_validator("hazard_density", "tile_contention", "illegal_ratio")
    @classmethod
    def _is_a_ratio(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"{value} 不是比例（应在 [0,1]）")
        return value

    @field_validator("mcast_mix")
    @classmethod
    def _mix_sums_to_one(cls, value: Dict[str, float]) -> Dict[str, float]:
        if value and abs(sum(value.values()) - 1.0) > 1e-6:
            raise ValueError(
                f"mcast_mix 各项之和是 {sum(value.values()):.3f}，应当是 1.0")
        return value


class DslOrchestration(BaseModel):
    """第六段 —— L3 的时间窗编排。"""

    model_config = _STRICT

    epochs: int = 1
    epoch_boundary_sync: str = "random"

    @field_validator("epochs")
    @classmethod
    def _positive(cls, value: int) -> int:
        if value < 1:
            raise ValueError("epochs 至少是 1")
        return value


class DslInstAgent(BaseModel):
    model_config = _STRICT

    gap_mode: str = "random"
    gap_range: Tuple[int, int] = (0, 0)
    ready_throttle: float = 0.0


class DslHarness(BaseModel):
    """第七段 —— 节奏参数（可选；回归时以 nightly 的配置为准）。"""

    model_config = _STRICT

    inst_agent: DslInstAgent = Field(default_factory=DslInstAgent)


class DslAlloc(BaseModel):
    """§3.12.7 的 `alloc` 条目 —— 本 case 必须驻留的一个对象。

    `exp_range` 是**指数安全域**（E1）：超限要自动缩放并重生成，
    所以它在这里声明，由 tensor_gen 消费（本工具只把它带进 `preload.json`）。
    """

    model_config = _STRICT

    name: str
    pool: str = ""
    shape: List[int] = Field(default_factory=list)
    dtype: str = ""
    pattern: str = ""
    exp_range: Optional[List[float]] = None
    value_range: Optional[List[float]] = None
    region: str = ""
    #: 这个对象**扮演什么角色**（`wgt` / `in` / `out` / `scale` / `origin`…）。
    #:
    #: 文档 §3.14.4 第 2 条要求"MPU/VPU 计算类 IR **必须**携带 binds/writes"，
    #: 但没说生成器怎么知道哪个对象是权重 —— 那取决于 case，不取决于指令。
    #: 所以由 DSL 声明角色，事务注册表的 `roles` 引用它。
    #: 留空 = 这个对象不参与任何计算事务的 ref 解析。
    role: str = ""


class DslDocument(BaseModel):
    """一份完整的场景 DSL。"""

    model_config = _STRICT

    meta: DslMeta
    resources: DslResources = Field(default_factory=DslResources)
    txn_pool: DslTxnPool = Field(default_factory=DslTxnPool)
    shape_space: Dict[str, List[int]] = Field(default_factory=dict)
    precision_mix: Dict[str, float] = Field(default_factory=dict)
    intent: DslIntent = Field(default_factory=DslIntent)
    orchestration: DslOrchestration = Field(default_factory=DslOrchestration)
    harness: DslHarness = Field(default_factory=DslHarness)
    alloc: List[DslAlloc] = Field(default_factory=list)

    @field_validator("precision_mix")
    @classmethod
    def _precision_sums_to_one(cls, value: Dict[str, float]) -> Dict[str, float]:
        if value and abs(sum(value.values()) - 1.0) > 1e-6:
            raise ValueError(
                f"precision_mix 各项之和是 {sum(value.values()):.3f}，应当是 1.0")
        return value

    # ── 派生 ──

    def seed_or(self, fallback: int) -> int:
        """`meta.seed` 缺省时用调用方给的（通常是时间戳）。

        **实际用的 seed 要回填进 case.json**（文档字段约定第 1 条）——
        否则"这次跑的是哪个 seed"就没记录了，可复现链断在这里。
        """
        return int(self.meta.seed) if self.meta.seed is not None else int(fallback)

    def with_seed(self, seed: int) -> "DslDocument":
        """回填 seed 之后的副本 —— 落盘的 case.json 用这个。"""
        clone = self.model_copy(deep=True)
        clone.meta.seed = int(seed)
        return clone

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(mode="json")


# ═══════════════════════════════════════════════════════════════
# 派生 seed（E5）
# ═══════════════════════════════════════════════════════════════

def derive_seed(case_seed: int, name: str) -> int:
    """`hash(case_seed ⊕ name)` —— 文档 §3.12.9 E5 的可复现链。

    **不能只做 `case_seed + hash(name)`**：那样两个不同 case 的同一对象
    可能撞到同一个流。这里用 SHA-256 前 8 字节，截到一个正的 63 位整数
    （`random.Random` 接受任意 int，但保持正数让日志好读）。

    为什么是 hash 而不是"共享一个 RNG"
        共享 RNG 时，新增一个对象会把**它之后所有对象**的取值整体挪位 ——
        于是"加一个张量"就让既有 case 的比特值全变了，E5 直接失效。
        每个对象一条独立的流，加谁都不影响别人。
    """
    digest = hashlib.sha256(f"{int(case_seed)}\x00{name}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") & ((1 << 63) - 1)
