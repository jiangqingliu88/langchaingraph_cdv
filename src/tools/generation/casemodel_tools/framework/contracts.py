"""方法学框架的**契约层** —— 阶段、上下文、注册表。

## 为什么要有这一层

在这之前，"测试点 → 实现方式 → 执行计划 → 约束"是几个函数里各写一遍的：

    plan.build_testpoints     自己判 stimulus/observe
    associate._policy_assignments  自己再从维度推一次赋值
    find_spec_yaml            又自己按方法拼回归任务

三处各自推导 = **三处会漂**。框架把它们收成一条可组合的流水线：

    decompose → trace → realize → execute
       │          │        │         └─ test 类名 / 分级 / 种子
       │          │        └─ realization 策略（可注册新 kind）
       │          └─ 覆盖仓对照
       └─ 取值点 → 测试点身份/需求/专题

每个阶段只依赖**上下文**里的具名产物（`ctx.artifacts`），不直接调下一个阶段。
新增一种实现方式（如 `backdoor`）只需要注册一个 `RealizationStrategy`，
核心阶段一行都不用改。

## 不变式

- 阶段顺序由 `MethodologyPipeline` 决定，阶段不互相 import；
- 每个阶段声明 `consumes` / `produces`，流水线在跑之前检查依赖；
- 产物进 `ctx.artifacts`，形状由数据模型（`model.py`）固定；
- 所有"判不了/没声明"都进 `ctx.notes`，**不静默**。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

#: 框架身份 —— manifest 与 IR 文件头共用（不放在 pipeline 里，避免
#: serialize ↔ pipeline 循环 import）。
FRAMEWORK_NAME = "signoff-methodology"
FRAMEWORK_VERSION = "1.0"


# ════════════════════════════════════════════════════════════
# 注册表
# ════════════════════════════════════════════════════════════

class Registry:
    """极简注册表：`register(key, item)` 或装饰器 `@reg.register(key)`。

    注册表是**框架的扩展点** —— 新增 realization / constraint 编译器时，
    只注册，不改核心阶段。
    """

    def __init__(self, what: str = "item") -> None:
        self.what = what
        self._items: Dict[str, Any] = {}

    def register(self, key: str, item: Any = None):
        def _decorator(obj: Any) -> Any:
            self._items[key] = obj
            return obj
        if item is not None:
            _decorator(item)
            return item
        return _decorator

    def unregister(self, key: str) -> None:
        """移除一个注册项（测试/插件卸载用）。不存在就忽略。"""
        self._items.pop(key, None)

    def get(self, key: str, default: Any = None) -> Any:
        return self._items.get(key, default)

    def require(self, key: str) -> Any:
        if key not in self._items:
            raise KeyError(f"未知的 {self.what}: {key!r}（已注册："
                           f"{'、'.join(sorted(self._items)) or '无'}）")
        return self._items[key]

    def keys(self) -> List[str]:
        return sorted(self._items)

    def __contains__(self, key: str) -> bool:
        return key in self._items


# ════════════════════════════════════════════════════════════
# 阶段契约
# ════════════════════════════════════════════════════════════

class Stage(ABC):
    """方法学流水线的一个阶段。

    `consumes` 是运行前从 `ctx.artifacts` 里**必须已经存在**的键；
    `produces` 是本阶段写回的键。流水线按声明做依赖检查 —— 漏了就在
    启动时报错，而不是跑到一半拿到 `None`。
    """
    name: str = ""
    consumes: Tuple[str, ...] = ()
    produces: str = ""

    @abstractmethod
    def run(self, ctx: "PipelineContext") -> None:
        """就地更新 `ctx`（产物写 artifacts、记账写 notes）。"""

    def describe(self) -> Dict[str, Any]:
        return {"name": self.name, "consumes": list(self.consumes),
                "produces": self.produces}


@dataclass
class PipelineContext:
    """流水线上下文 —— 阶段之间**只通过它**交换数据。

    `model` 必须是 `resolve()` 过的；`agents` 是
    `{agent 名: [master 事务字段名]}`，用于把 stimulus 字段解析到具体 agent。
    """
    model: Any
    env_name: str = ""
    module_name: str = ""
    agents: Optional[Dict[str, List[str]]] = None
    #: 覆盖模型（`coverage_model` 的产物），trace 阶段用。
    coverage: Any = None
    #: 阶段产物：`testpoints` / `constraints` / ...
    artifacts: Dict[str, Any] = field(default_factory=dict)
    #: 所有"判不了/没声明/对不上"的记账。**不静默**。
    notes: List[str] = field(default_factory=list)

    def require(self, key: str) -> Any:
        if key not in self.artifacts:
            raise KeyError(f"阶段依赖缺失: {key!r}（现有："
                           f"{'、'.join(sorted(self.artifacts)) or '无'}）")
        return self.artifacts[key]

    def put(self, key: str, value: Any) -> Any:
        self.artifacts[key] = value
        return value

    def take(self, key: str, default: Any = None) -> Any:
        return self.artifacts.get(key, default)


@dataclass
class StageRecord:
    """一个阶段跑完后的记录（进 manifest，供签核/复现）。"""
    name: str
    consumes: List[str]
    produces: str
    count: int = 0
    notes: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "consumes": list(self.consumes),
                "produces": self.produces, "count": self.count,
                "notes": self.notes}
