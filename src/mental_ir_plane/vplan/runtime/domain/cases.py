"""case 这一侧的值对象。

两个都放在 domain 而不是各自的使用方，是因为它们描述的是「一个 case 长什么样」
这件事本身 —— 而不是「怎么造出来」或「怎么比对」：

    CaseAttribute   文档十六节的 case 属性表最小字段集。generation 负责造它，
                    analysis 负责量它，view 负责展示它 —— 三方都只认这个形状。
    ExternalCase    外部真实存在的 case。repository 负责把 YAML/JSON/CSV 读成它，
                    analysis 负责拿它跟模型对账。

两者都有 `.fields`（字段名 → 取值 token），所以覆盖统计只需要一套代码
（analysis.coverage.hits_from_cases 就是按这个约定写的）。
"""
from __future__ import annotations

from dataclasses import dataclass, field as _field
from typing import Any, Dict, List, Optional, Tuple

from .vocab import CHECK_NAMES, METHOD_NAMES

#: 不作用树的专题，它的 case 不挂任何节点 —— 用这个代号占位，别留空
NO_NODE_CODE = "ALL"


@dataclass
class CaseAttribute:
    """一个 case 的属性表（文档十六节最小字段集 + 专题与树路径）。"""
    case_id: str
    object: str
    sub_object: str = ""
    sub_object_id: str = ""
    theme: str = ""
    priority: str = ""
    tree_path: str = ""
    dimensions: List[str] = _field(default_factory=list)
    fields: Dict[str, str] = _field(default_factory=dict)
    method: str = ""
    cross_group: str = ""
    checks: List[str] = _field(default_factory=list)
    cover_bins: List[str] = _field(default_factory=list)
    environment: Dict[str, Any] = _field(default_factory=dict)
    expected_result: str = ""
    seed: Optional[int] = None

    @property
    def method_name(self) -> str:
        return METHOD_NAMES.get(self.method, self.method)

    @property
    def node_key(self) -> str:
        """组织树节点的**标识**（id），不是代号（code）。

        代号只出现在 case_id 里，字号短、人读；id 才是机器索引。
        两者混用会让「按节点统计覆盖」全查不中 —— 早期实现踩过这个坑。
        """
        return self.sub_object_id or NO_NODE_CODE

    def field_pairs(self) -> List[Tuple[str, str]]:
        return list(self.fields.items())

    def check_labels(self) -> List[str]:
        return [f"{c} {CHECK_NAMES.get(c, '')}".strip() for c in self.checks]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "case_id": self.case_id,
            "object": self.object,
            "sub_object": self.sub_object,
            "sub_object_id": self.sub_object_id,
            "theme": self.theme,
            "priority": self.priority,
            "tree_path": self.tree_path,
            "dimensions": list(self.dimensions),
            "fields": dict(self.fields),
            "method": self.method,
            "cross_group": self.cross_group,
            "checks": list(self.checks),
            "cover_bins": list(self.cover_bins),
            "environment": dict(self.environment),
            "expected_result": self.expected_result,
            "seed": self.seed,
        }


@dataclass
class ExternalCase:
    """一条真实存在的 case（来自外部 case 列表，不是我们生成的）。

    字段集合与 CaseAttribute 对齐（只多一个 index），这样「生成 → 落盘 →
    回喂」是无损的：导出的属性表能被原样读回来，不需要转换脚本。
    """
    index: int
    case_id: str
    object: str = ""
    sub_object: str = ""
    sub_object_id: str = ""
    theme: str = ""
    priority: str = ""
    tree_path: str = ""
    method: str = ""
    cross_group: str = ""
    fields: Dict[str, str] = _field(default_factory=dict)
    checks: List[str] = _field(default_factory=list)
    cover_bins: List[str] = _field(default_factory=list)
    environment: Dict[str, Any] = _field(default_factory=dict)
    expected_result: str = ""

    @property
    def label(self) -> str:
        return self.case_id or f"#{self.index}"

    @property
    def node_key(self) -> str:
        """组织树节点的**标识**（id），不是代号（code）。

        代号只出现在 case_id 里，字号短、人读；id 才是机器索引。
        两者混用会让「按节点统计覆盖」全查不中 —— 早期实现踩过这个坑。
        """
        return self.sub_object_id or NO_NODE_CODE

    def fingerprint(self) -> Tuple[str, str, Tuple[Tuple[str, str], ...]]:
        """文档十二节：对象 + 子对象 + 字段取值相同即为重复（方法不参与）。"""
        return (self.object,
                self.sub_object_id or self.sub_object,
                tuple(sorted(self.fields.items())))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "case_id": self.case_id,
            "object": self.object,
            "sub_object": self.sub_object,
            "sub_object_id": self.sub_object_id,
            "theme": self.theme,
            "priority": self.priority,
            "tree_path": self.tree_path,
            "method": self.method,
            "cross_group": self.cross_group,
            "fields": dict(self.fields),
            "checks": list(self.checks),
            "cover_bins": list(self.cover_bins),
            "environment": dict(self.environment),
            "expected_result": self.expected_result,
        }

