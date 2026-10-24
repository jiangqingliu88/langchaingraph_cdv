"""规则基础设施 —— 每条完备性判断都是一个自包含的 Specification。

设计模式：**Specification**。一条规则 = 一个「模型是否满足某条件」的可复用判定单元，
自带身份（rule id / 严重度 / 分类）、自带人话说明（description）、
自己知道要读上下文的哪一部分。

这么做的好处是可插拔：新增一条校验 = 新增一个 Rule 子类（放在 rules/ 下）+
被 `load_rules()` 扫到，不用改门面、不用改报告、不用改 GUI —— 三处都从
同一个注册表读规则清单。规则之间互不依赖，可以单独测。

规则只读上下文，不抛异常、不改模型：`check()` 出任何问题都翻成 Issue 返回。
"""
from __future__ import annotations

import importlib
import pkgutil
from abc import ABC, abstractmethod
from dataclasses import dataclass, field as _field
from typing import Dict, List, Optional, Sequence, Type

from ..domain import CaseAttribute, CaseModel, Theme
from ..generation import GenerationResult
from .coverage import DimensionCoverage, FieldCoverage
from .issues import Issue


@dataclass
class RuleContext:
    """规则的只读运行时上下文 —— 门面算好之后一次性传给所有规则。"""
    model: CaseModel
    generation: GenerationResult
    matrix: "object" = None                          # analysis.matrix.CrossMatrix
    dimension_coverage: List[DimensionCoverage] = _field(default_factory=list)
    field_coverage: List[FieldCoverage] = _field(default_factory=list)
    #: 叶子节点 code → 打在它上面的 case
    node_hits: Dict[str, List[CaseAttribute]] = _field(default_factory=dict)
    #: 专题 id → 它生成的 case
    theme_hits: Dict[str, List[CaseAttribute]] = _field(default_factory=dict)

    def cases_for_theme(self, theme: Theme) -> List[CaseAttribute]:
        return self.theme_hits.get(theme.id, [])

    def cases_for_node(self, node_id: str) -> List[CaseAttribute]:
        """按组织树节点的 **id** 查（不是 case_id 里那个代号）。"""
        return self.node_hits.get(node_id, [])

    @property
    def themes(self) -> List[Theme]:
        return self.model.themes


class Rule(ABC):
    """一条完备性规则。

    子类只需声明身份 + 实现 check()。severity / category / description 都是
    规则自己的属性 —— 所以报告能按严重度排序、GUI 能按分类分页、
    readme 能自动列出规则清单，都不用规则作者额外登记。
    """

    id: str = ""
    severity: str = "warning"        # error | warning | info
    category: str = ""
    description: str = ""

    @abstractmethod
    def check(self, ctx: RuleContext) -> List[Issue]:
        ...

    # ── 造 Issue 的糖：severity/category 默认取规则自己的 ──

    def issue(self, target: str, message: str, *,
              severity: Optional[str] = None,
              rule: Optional[str] = None) -> Issue:
        return Issue(severity or self.severity, rule or self.id,
                     target, message, self.category)

    def issues(self, items: Sequence[tuple]) -> List[Issue]:
        """[(target, message)] → [Issue]，批量场景少写一层循环。"""
        return [self.issue(t, m) for t, m in items]

    def __repr__(self) -> str:                       # 便于调试注册表
        return f"<{type(self).__name__} {self.id} [{self.severity}]>"


_REGISTRY: Dict[str, Rule] = {}
_LOADED = False


def register(rule_cls: Type[Rule]) -> Type[Rule]:
    """类装饰器：登记一条规则。重名直接报错 —— 静默覆盖会让规则悄悄消失。"""
    instance = rule_cls()
    if not instance.id:
        raise ValueError(f"{rule_cls.__name__} 没有声明 id")
    if instance.id in _REGISTRY:
        raise ValueError(f"规则 id 重复: {instance.id}")
    _REGISTRY[instance.id] = instance
    return rule_cls


def load_rules() -> List[Rule]:
    """导入 rules/ 下的全部模块（触发 @register），返回按 id 排序的规则清单。"""
    global _LOADED
    if not _LOADED:
        from . import rules as rules_pkg
        for mod in pkgutil.iter_modules(rules_pkg.__path__):
            importlib.import_module(f"{rules_pkg.__name__}.{mod.name}")
        _LOADED = True
    return [r for _k, r in sorted(_REGISTRY.items())]


def rule_ids() -> List[str]:
    return [r.id for r in load_rules()]


def rule_docs() -> List[tuple]:
    """(id, severity, category, description) —— 供 readme / --help / GUI 展示。"""
    return [(r.id, r.severity, r.category, r.description) for r in load_rules()]
