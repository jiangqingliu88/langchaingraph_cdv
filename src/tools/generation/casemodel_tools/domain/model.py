"""CaseModel —— 聚合根。

一个 case 属性模型的完整实例。层级关系（文档一/二节）：

    L1 对象 Object              验证主体，用功能组织树描述
      └─ L2 功能组织树           domain.nodes.OrgNode（Composite）
           ↑ 专题作用于树节点     domain.themes.Theme（P0/P1/P2 分层）
      └─ L3 维度 / L4 字段       domain.dimensions / domain.fields
           └─ L5 方法 / L6 检查   词表在 domain.vocab，取值在 AnalysisResult

本模块只做两件事：持有这些部件，以及**解析引用**（把 YAML 里的字符串
绑到对象上，绑不上的原始文本记进 ResolveReport，交给 analysis 翻成 Issue）。
它不做校验、不做生成、不做渲染 —— 那些分别是 analysis / generation / view 的事。
"""
from __future__ import annotations

from dataclasses import dataclass, field as _field
from typing import Any, Dict, List, Optional, Tuple

from .dimensions import CrossGroup, CrossPair, Dimension
from .fields import Field
from .nodes import OrgNode, collect_leaves
from .themes import Theme, sort_themes
from .vocab import (DEFAULT_ID_PREFIX, DEFAULT_REPEAT, DEFAULT_SEED, ENV_KEY_NAMES,
                    is_wildcard)


# ════════════════════════════════════════════════════════════
# 附属配置
# ════════════════════════════════════════════════════════════

@dataclass
class Assertion:
    """模型里声明的一条 DUT 断言，以及它**保护了哪些测试点**。

    `tp_bindings` 是一对多：一条 SVA 往往同时守住好几个功能点（一个事务级
    稳定性质可以覆盖"基本等待""连续等待""写期间稳定"三条 TP）。绑定表示
    **关联**，不代表失败必然由所有关联 TP 引起 —— 归因仍要看 run 证据。
    """
    id: str
    name: str
    expr: str = ""
    message: str = ""
    signals: List[Any] = _field(default_factory=list)
    tp_bindings: List[Dict[str, str]] = _field(default_factory=list)
    failure_severity: str = "error"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "expr": self.expr,
            "message": self.message,
            "signals": list(self.signals),
            "tp_bindings": [dict(b) for b in self.tp_bindings],
            "failure_severity": self.failure_severity,
        }


@dataclass
class Generation:
    """case 组合生成参数（文档十七节）。"""
    themes: List[str] = _field(default_factory=list)        # 限定专题 id
    priorities: List[str] = _field(default_factory=list)    # 只跑这些优先级
    methods: List[str] = _field(default_factory=list)
    groups: List[str] = _field(default_factory=list)        # 无 themes 时的退路
    dimensions: List[str] = _field(default_factory=list)
    sub_objects: List[str] = _field(default_factory=list)
    seed: int = DEFAULT_SEED
    repeat: int = DEFAULT_REPEAT
    max_cases: Optional[int] = None
    declared: bool = False

    def allows_priority(self, priority: str) -> bool:
        return not self.priorities or priority in self.priorities


@dataclass
class CaseDefaults:
    """生成 case 的缺省属性。"""
    id_prefix: str = DEFAULT_ID_PREFIX
    expected_result: str = ""
    checks: List[str] = _field(default_factory=list)
    environment: Dict[str, Any] = _field(default_factory=dict)


@dataclass
class ResolveReport:
    """引用解析结果 —— 悬空引用的原始文本。

    这里只记录「绑不上」，不判断「该不该绑」—— 后者是 analysis 的职责。
    """
    relation_refs: List[Tuple[str, str]] = _field(default_factory=list)
    cross_refs: List[Tuple[str, str]] = _field(default_factory=list)
    group_refs: List[Tuple[str, str]] = _field(default_factory=list)
    group_sub_objects: List[Tuple[str, str]] = _field(default_factory=list)
    linkage_refs: List[Tuple[str, str]] = _field(default_factory=list)
    dim_sub_objects: List[Tuple[str, str]] = _field(default_factory=list)
    theme_nodes: List[Tuple[str, str]] = _field(default_factory=list)
    theme_dims: List[Tuple[str, str]] = _field(default_factory=list)
    gen_dims: List[str] = _field(default_factory=list)
    gen_groups: List[str] = _field(default_factory=list)
    gen_themes: List[str] = _field(default_factory=list)
    gen_sub_objects: List[str] = _field(default_factory=list)
    ambiguous_dims: List[Tuple[str, List[str]]] = _field(default_factory=list)

    @property
    def any(self) -> bool:
        return any(bool(getattr(self, f.name)) for f in self.__dataclass_fields__.values())


# ════════════════════════════════════════════════════════════
# 聚合根
# ════════════════════════════════════════════════════════════

@dataclass
class CaseModel:
    """一个 case 属性模型的完整实例。"""
    object: str
    dimensions: List[Dimension] = _field(default_factory=list)
    version: str = ""
    object_cn: str = ""
    object_code: str = ""
    object_code_declared: bool = False
    description: str = ""
    org_root: List[OrgNode] = _field(default_factory=list)   # 功能组织树的根
    sub_objects: List[OrgNode] = _field(default_factory=list)  # 前序展平（兼容旧用法）
    themes: List[Theme] = _field(default_factory=list)
    methods: List[str] = _field(default_factory=list)
    method_names: Dict[str, str] = _field(default_factory=dict)
    checks: List[str] = _field(default_factory=list)
    check_names: Dict[str, str] = _field(default_factory=dict)
    #: 模型声明的 DUT 断言（含 `tp_bindings`：这条断言保护哪些测试点）。
    assertions: List["Assertion"] = _field(default_factory=list)
    #: 行为域（状态 / 迁移 / 序列 / 时序）；None = 模型没启用行为建模。
    behavior: Optional[Any] = None
    #: **PATH 组**（端到端指令生命周期）—— 与功能组并列，回答"路径通不通"。
    path_groups: List[Any] = _field(default_factory=list)
    #: 配置域（DUT/特性配置空间）；None = 模型没启用配置建模。
    config_space: Optional[Any] = None
    cross_pairs: List[CrossPair] = _field(default_factory=list)
    cross_groups: List[CrossGroup] = _field(default_factory=list)
    env_required: List[str] = _field(default_factory=list)
    env_defaults: Dict[str, Any] = _field(default_factory=dict)
    #: **DUT 探针的采样配置**（`sampling:` 块）—— `sample: dut` 的字段靠它生成
    #: `bind` 语句。键：`dut_module`（bind 的目标**模块名**）/ `clock` / `reset`。
    #:
    #: 空 dict = 模型里没有 `sample: dut` 的字段，或者没声明这套配置 ——
    #: 后者是**要记账**的（写了 `sample: dut` 却没给 dut_module，生成不出探针）。
    sampling: Dict[str, Any] = _field(default_factory=dict)
    env_unknown_keys: List[str] = _field(default_factory=list)
    generation: Generation = _field(default_factory=Generation)
    case_defaults: CaseDefaults = _field(default_factory=CaseDefaults)
    resolve_report: ResolveReport = _field(default_factory=ResolveReport)
    source: str = ""
    field_index: Dict[str, Field] = _field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        self._rebuild_index()

    def _rebuild_index(self) -> None:
        index: Dict[str, Field] = {}
        for dim in self.dimensions:
            for fld in dim.fields:
                index.setdefault(fld.name, fld)
                index.setdefault(fld.qualified, fld)
        self.field_index = index

    # ════════════════════════════════════════════════════════
    # 基本视图
    # ════════════════════════════════════════════════════════

    @property
    def object_label(self) -> str:
        return f"{self.object} {self.object_cn}".strip()

    @property
    def all_fields(self) -> List[Field]:
        return [f for d in self.dimensions for f in d.fields]

    @property
    def leaf_nodes(self) -> List[OrgNode]:
        """功能组织树的叶子 —— 只有它们生成 case。"""
        return collect_leaves(self.org_root) if self.org_root else list(self.sub_objects)

    @property
    def tree_nodes(self) -> List[OrgNode]:
        """树里的全部节点（含分支）。"""
        return list(self.sub_objects)

    @property
    def leaves_without_subtree(self) -> List[OrgNode]:
        """退化情形：模型没写 sub_objects，用占位节点承载 case。"""
        if self.leaf_nodes:
            return self.leaf_nodes
        return [OrgNode(id="-", name="（未细分）", code="ALL", code_declared=True)]

    def node_codes(self) -> List[str]:
        return [n.code for n in self.tree_nodes]

    # ════════════════════════════════════════════════════════
    # 查询
    # ════════════════════════════════════════════════════════

    def dimension_candidates(self, ref: str) -> List[Dimension]:
        """精确 → 大小写 → 松匹配（简称），逐级放宽。"""
        exact = [d for d in self.dimensions if d.matches(ref)]
        if exact:
            return exact
        loose = [d for d in self.dimensions if d.contains(ref)]
        if len(loose) > 1:
            self.resolve_report.ambiguous_dims.append((ref, [d.key for d in loose]))
        return loose

    def dimension(self, ref: str) -> Optional[Dimension]:
        cands = self.dimension_candidates(ref)
        return cands[0] if cands else None

    def field(self, ref: str) -> Optional[Field]:
        if ref in self.field_index:
            return self.field_index[ref]
        low = (ref or "").lower()
        for key, fld in self.field_index.items():
            if key.lower() == low:
                return fld
        hits = [f for f in self.all_fields if (ref or "") and (ref in f.name or f.name in ref)]
        return hits[0] if len(hits) == 1 else None

    def node(self, ref: str) -> Optional[OrgNode]:
        """按 id 或名字找树节点（含分支）。"""
        for n in self.tree_nodes:
            if n.matches(ref):
                return n
        return None

    def resolve_nodes(self, ref: str) -> List[OrgNode]:
        """引用 → 目标叶子列表。

        指向分支时展开到它的全部叶子（这才是「专题作用于功能组织树」的意思）；
        `"*"` 表示全树。找不到就返回空列表，由调用方记悬空。
        """
        if is_wildcard(ref):
            return self.leaves_without_subtree
        node = self.node(ref)
        return node.leaves() if node is not None else []

    def theme(self, ref: str) -> Optional[Theme]:
        for t in self.themes:
            if t.key == ref or t.id == ref or t.name == ref:
                return t
        low = (ref or "").lower()
        for t in self.themes:
            if t.key.lower() == low or t.label.lower() == low:
                return t
        return None

    def cross_group(self, ref: str) -> Optional[CrossGroup]:
        for g in self.cross_groups:
            if g.key == ref or g.id == ref or g.name == ref:
                return g
        low = (ref or "").lower()
        for g in self.cross_groups:
            if g.key.lower() == low or g.label.lower() == low:
                return g
        return None

    # ════════════════════════════════════════════════════════
    # 引用解析
    # ════════════════════════════════════════════════════════

    def resolve(self) -> "CaseModel":
        """把 YAML 里的字符串引用绑到对象上；绑不上的原始文本记进 ResolveReport。"""
        self.resolve_report = ResolveReport()
        self._resolve_relations()
        self._resolve_cross()
        self._resolve_groups()
        self._resolve_themes()
        self._resolve_generation()
        self._resolve_dimension_nodes()
        self._resolve_linkage()
        self.resolve_cross_groups()
        return self

    def _resolve_relations(self) -> None:
        for dim in self.dimensions:
            for ref in list(dim.relation):
                if self.field(ref) is None:
                    self.resolve_report.relation_refs.append((dim.key, ref))

    def _resolve_cross(self) -> None:
        for pair in self.cross_pairs:
            pair.dim_a = self.dimension(pair.a)
            pair.dim_b = self.dimension(pair.b)
            if pair.dim_a is None or pair.dim_b is None:
                self.resolve_report.cross_refs.append((pair.a, pair.b))

    def _resolve_groups(self) -> None:
        for grp in self.cross_groups:
            grp.dims = []
            for ref in grp.dimensions:
                dim = self.dimension(ref)
                if dim is None:
                    grp.unresolved.append(ref)
                    self.resolve_report.group_refs.append((grp.key, ref))
                else:
                    grp.dims.append(dim)
            for ref in grp.sub_objects:
                if self.node(ref) is None:
                    self.resolve_report.group_sub_objects.append((grp.key, ref))

    def _resolve_themes(self) -> None:
        for theme in self.themes:
            theme.nodes = []
            theme.unresolved_nodes = []
            for ref in theme.applies_to:
                if is_wildcard(ref):
                    theme.nodes = self.leaves_without_subtree
                    theme.unresolved_nodes = []
                    break
                nodes = self.resolve_nodes(ref)
                if not nodes:
                    theme.unresolved_nodes.append(ref)
                    self.resolve_report.theme_nodes.append((theme.key, ref))
                else:
                    theme.nodes.extend(n for n in nodes if n not in theme.nodes)

            theme.dims = []
            theme.unresolved_dims = []
            if theme.covers_all_dimensions:
                theme.dims = list(self.dimensions)
            else:
                for ref in theme.dimensions:
                    dim = self.dimension(ref)
                    if dim is None:
                        theme.unresolved_dims.append(ref)
                        self.resolve_report.theme_dims.append((theme.key, ref))
                    elif dim not in theme.dims:
                        theme.dims.append(dim)

    def _resolve_generation(self) -> None:
        for ref in self.generation.dimensions:
            if self.dimension(ref) is None:
                self.resolve_report.gen_dims.append(ref)
        for ref in self.generation.groups:
            if self.cross_group(ref) is None:
                self.resolve_report.gen_groups.append(ref)
        for ref in self.generation.themes:
            if self.theme(ref) is None:
                self.resolve_report.gen_themes.append(ref)
        for ref in self.generation.sub_objects:
            if self.node(ref) is None:
                self.resolve_report.gen_sub_objects.append(ref)

    def _resolve_dimension_nodes(self) -> None:
        for dim in self.dimensions:
            for ref in dim.sub_objects:
                if self.node(ref) is None:
                    self.resolve_report.dim_sub_objects.append((dim.key, ref))

    def _resolve_linkage(self) -> None:
        """联动型字段的取值从目标字段回填。"""
        self._rebuild_index()
        for fld in self.all_fields:
            if not fld.is_linkage or fld.values or not fld.linked_to:
                continue
            target = self.field(fld.linked_to)
            if target is None:
                self.resolve_report.linkage_refs.append((fld.qualified, fld.linked_to))
                continue
            fld.values = ([v for v in (target.values or [])]
                          or list(target.cover_tokens()))

    def resolve_cross_groups(self) -> "CaseModel":
        """矩阵的必需对 → 隐式交叉组（文档十四节：每个 ★ 就是一个交叉组）。

        只在模型没有显式声明 cross_groups 时推导。
        """
        if self.cross_groups:
            return self
        groups: List[CrossGroup] = []
        seen: set = set()
        for pair in self.cross_pairs:
            if pair.level != "required" or not pair.resolved:
                continue
            keys = (pair.dim_a.key, pair.dim_b.key)
            if tuple(sorted(keys)) in seen:
                continue
            seen.add(tuple(sorted(keys)))
            groups.append(CrossGroup(
                id=f"XG-{len(groups) + 1:02d}",
                name=f"{pair.dim_a.name}×{pair.dim_b.name}",
                dimensions=list(keys),
                level="required",
                description="由 cross_matrix 的必需对推导",
                dims=[pair.dim_a, pair.dim_b],
                source="derived",
            ))
        self.cross_groups = groups
        return self

    # ════════════════════════════════════════════════════════
    # 汇总
    # ════════════════════════════════════════════════════════

    def summary(self) -> Dict[str, Any]:
        return {
            "object": self.object,
            "object_cn": self.object_cn,
            "object_label": self.object_label,
            "object_code": self.object_code,
            "version": self.version,
            "org_node_count": len(self.tree_nodes),
            "org_leaf_count": len(self.leaf_nodes),
            "sub_object_count": len(self.tree_nodes),   # 旧名，保留兼容
            "theme_count": len(self.themes),
            "priority_count": len({t.priority for t in self.themes}),
            "dimension_count": len(self.dimensions),
            "field_count": len(self.all_fields),
            "value_count": sum(len(f.cover_tokens()) for f in self.all_fields),
            "method_count": len(self.methods),
            "check_count": len(self.checks),
            "cross_pair_count": len(self.cross_pairs),
            "cross_group_count": len(self.cross_groups),
            "path_group_count": len(self.path_groups),
            "path_bin_count": sum(len(getattr(g, "bins", []) or [])
                                  for g in self.path_groups),
            "env_required": list(self.env_required),
            "source": self.source,
        }

    def layer_rows(self) -> List[Dict[str, Any]]:
        """逐层统计 —— 概览页与 CLI 概览共用。"""
        tree_sample = self._tree_outline(limit=8)
        return [
            {"layer": "L1", "name": "对象 Object", "role": "测什么主体",
             "count": 1, "detail": self.object_label, "items": [self.object_label]},
            {"layer": "L2", "name": "功能组织树 OrgTree", "role": "主体的层级分解",
             "count": len(self.tree_nodes),
             "detail": f"{len(self.leaf_nodes)} 个叶子　{tree_sample}",
             "items": [f"{n.path_label()}（{n.code}）" for n in self.tree_nodes]},
            {"layer": "TH", "name": "专题 Theme", "role": "横切的验证关注点",
             "count": len(self.themes),
             "detail": "、".join(f"{t.priority} {t.label}" for t in self.themes),
             "items": [f"{t.priority} {t.id} {t.label}" for t in self.themes]},
            {"layer": "L3", "name": "维度 Dimension", "role": "会变化的条件",
             "count": len(self.dimensions),
             "detail": "、".join(d.label for d in self.dimensions),
             "items": [f"{d.id} {d.label}" if d.id else d.label for d in self.dimensions]},
            {"layer": "L4", "name": "字段 Field", "role": "维度的取值字段",
             "count": len(self.all_fields),
             "detail": f"{sum(len(f.cover_tokens()) for f in self.all_fields)} 个取值点",
             "items": [f"{f.qualified} : {f.type_name}" for f in self.all_fields]},
            {"layer": "L5", "name": "方法 Method", "role": "怎么生成",
             "count": len(self.methods),
             "detail": "、".join(f"{m} {self.method_names.get(m, '')}".strip()
                                 for m in self.methods),
             "items": [f"{m} {self.method_names.get(m, '')}".strip() for m in self.methods]},
            {"layer": "L6", "name": "检查 Check", "role": "验证什么",
             "count": len(self.checks),
             "detail": "、".join(self.check_names.get(c, c) for c in self.checks),
             "items": [f"{c} {self.check_names.get(c, '')}".strip() for c in self.checks]},
            {"layer": "ENV", "name": "环境 Environment", "role": "执行属性 / 复现指纹",
             "count": len(self.env_required),
             "detail": "、".join(ENV_KEY_NAMES.get(k, k) for k in self.env_required)
                       or "未声明必需项",
             "items": [f"{k} {ENV_KEY_NAMES.get(k, '')}".strip()
                       for k in (self.env_required or list(self.env_defaults))]},
        ]

    def _tree_outline(self, limit: int = 8) -> str:
        """树的一行式轮廓：指令 → (结构仲裁, 发射解析)；读数据；计算；写数据"""
        def render(node: OrgNode) -> str:
            if node.is_leaf:
                return node.name
            inner = "、".join(render(c) for c in node.children)
            return f"{node.name} → ({inner})"
        parts = [render(r) for r in self.org_root[:limit]] if self.org_root else \
                [n.name for n in self.sub_objects[:limit]]
        more = "" if len(self.org_root or self.sub_objects) <= limit else " …"
        return "；".join(parts) + more

    def org_tree_rows(self) -> List[Dict[str, Any]]:
        """功能组织树的逐节点行 —— GUI 树表与报告共用。"""
        rows: List[Dict[str, Any]] = []
        for node in self.tree_nodes:
            rows.append({
                "id": node.id,
                "name": node.name,
                "code": node.code,
                "depth": node.depth,
                "path": node.path_label(),
                "is_leaf": node.is_leaf,
                "children": len(node.children),
                "leaves": len(node.leaves()),
                "indent": "  " * node.depth,
            })
        return rows

    def theme_rows(self) -> List[Dict[str, Any]]:
        """专题表 —— GUI 与报告共用。"""
        return [{
            "id": t.id,
            "name": t.label,
            "priority": t.priority,
            "kind": t.kind,
            "kind_name": t.kind_name,
            "target": t.target_label,
            "target_count": len(t.nodes) if t.is_structural else 0,
            "dimensions": t.dimension_label,
            "dim_scope": t.dim_scope,
            "dim_scope_name": t.dim_scope_name,
            "method": t.method or "（继承 generation）",
            "checks": "、".join(t.checks) or "（继承 case_defaults）",
            "expected_result": t.expected_result,
            "description": t.description,
        } for t in sort_themes(self.themes)]
