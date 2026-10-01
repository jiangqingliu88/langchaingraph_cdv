"""领域层 —— 只有数据与不变式，不依赖任何 IO / 渲染 / 校验框架。

分层规则（整个包内唯一需要记住的规则）：
    domain      不 import 本包其它任何层
    repository  只 import domain
    generation  import domain
    analysis    import domain（+ repository 的产物）
    view        import domain + analysis 的结果，不 import repository
    agent       import domain + repository + analysis（作为门面的适配器）

对外只从这里取名字，`from ..domain import CaseModel` 就够了。
"""
from __future__ import annotations

from .cases import NO_NODE_CODE, CaseAttribute, ExternalCase
from .dimensions import CrossGroup, CrossPair, Dimension, build_cross_group, build_cross_pair, build_dimension
from .errors import CaseListError, CaseModelError
from .fields import (FIELD_TYPE_REGISTRY, EnumField, Field, FieldType,
                     LinkageField, RangeField, SetField, ValuePoint,
                     WeightedField, build_field, field_type)
from .model import CaseDefaults, CaseModel, Generation, ResolveReport
from .nodes import OrgNode, build_org_tree, collect_leaves, flatten
from .themes import Theme, build_theme, priority_gaps, sort_themes
from .vocab import (CHECK_ALIASES, CHECK_NAMES, CHECK_ORDER, CROSS_LEVEL_MARKS,
                    CROSS_LEVEL_NAMES, DEFAULT_ID_PREFIX, DEFAULT_PRIORITY,
                    DEFAULT_REPEAT, DEFAULT_SEED, ENV_KEYS, ENV_KEY_NAMES,
                    FIELD_TYPES, FIELD_TYPE_NAMES, METHOD_ALIASES, METHOD_NAMES,
                    METHOD_ORDER, PRIORITY_ALIASES, RELATION_ALIASES,
                    RELATION_NAMES, THEME_DIM_SCOPES, THEME_KINDS, WILDCARD,
                    as_list, canon, derive_code, is_wildcard, normalize_priority,
                    num, priority_label, priority_rank, split_cross_key,
                    token_of, value_of, weight_of)

__all__ = [
    # 聚合根与附属
    "CaseModel", "Generation", "CaseDefaults", "ResolveReport",
    # case 值对象
    "CaseAttribute", "ExternalCase", "NO_NODE_CODE",
    # 组织树
    "OrgNode", "build_org_tree", "flatten", "collect_leaves",
    # 专题
    "Theme", "build_theme", "sort_themes", "priority_gaps",
    # 维度与交叉
    "Dimension", "CrossPair", "CrossGroup",
    "build_dimension", "build_cross_pair", "build_cross_group",
    # 字段与类型策略
    "Field", "ValuePoint", "FieldType", "EnumField", "SetField",
    "WeightedField", "RangeField", "LinkageField",
    "FIELD_TYPE_REGISTRY", "field_type", "build_field",
    # 异常
    "CaseModelError", "CaseListError",
    # 词表与归一化
    "METHOD_ORDER", "METHOD_NAMES", "METHOD_ALIASES",
    "CHECK_ORDER", "CHECK_NAMES", "CHECK_ALIASES",
    "FIELD_TYPES", "FIELD_TYPE_NAMES",
    "RELATION_ALIASES", "RELATION_NAMES",
    "CROSS_LEVEL_NAMES", "CROSS_LEVEL_MARKS",
    "PRIORITY_ALIASES", "DEFAULT_PRIORITY", "THEME_KINDS", "THEME_DIM_SCOPES",
    "ENV_KEYS", "ENV_KEY_NAMES",
    "DEFAULT_ID_PREFIX", "DEFAULT_REPEAT", "DEFAULT_SEED", "WILDCARD",
    "as_list", "canon", "num", "token_of", "value_of", "weight_of",
    "derive_code", "split_cross_key", "is_wildcard",
    "normalize_priority", "priority_rank", "priority_label",
]
