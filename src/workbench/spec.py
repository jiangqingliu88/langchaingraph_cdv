"""界面清单的数据契约 —— 就是 `config/workbench.yaml` 的 schema。

设计模式：**Specification 对象的声明式版本**。平台的每一处可配置点都在
这里有一个字段，别处不再有「约定俗成的键」。想知道清单能写什么，读这个
文件；想加一个新的可配置点，先在这里加字段。

`extra="forbid"` 是刻意的：清单里写错一个键名（`dock:` 而不是 `area:`）
如果被静默忽略，用户会以为界面坏了，而实际是自己拼错了。宁可启动时报错。

**本模块不 import Qt** —— 清单解析要在没有显示器的地方也能跑（测试、
`--check` 自检、CI）。主题名这里只当一个字符串，它的合法性由 `app.py`
在真正切主题时校验（那时才有 `PALETTES` 可查）。
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, model_validator

#: 模块停靠位置。`center` 是中央工作区（标签页），其余三个是 QDockWidget 区。
Area = Literal["center", "left", "right", "bottom"]

AREAS: Tuple[Area, ...] = ("center", "left", "right", "bottom")

#: 工具返回值的归一化方式。`auto` = 嗅探（字符串以 { 或 [ 开头就当 JSON）。
ToolKind = Literal["auto", "text", "json", "filesystem"]


class WindowSpec(BaseModel):
    """窗口级设置。"""

    model_config = ConfigDict(extra="forbid")

    title: str = "SignOffAI · 验证工作台"
    size: Tuple[int, int] = (1520, 940)
    min_size: Tuple[int, int] = (1080, 680)
    #: 留空 = 用平台默认主题（`ui.theme.DEFAULT_THEME`）。
    #: 不在这里写死主题名，是为了让本模块不依赖 Qt。
    theme: str = ""
    #: 关窗口时是否保存 / 启动时是否恢复几何与 Dock 布局
    restore_layout: bool = True


class ToolSpec(BaseModel):
    """模块与某个工具的绑定声明。

    `name` 是 `bridge.catalog.BINDINGS` 里的键，不是 python 路径 —— 清单
    里出现 python 路径会让人以为「这里可以随便写」，而绑定表是可审计的。
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    kind: ToolKind = "auto"
    #: 调用时固定合并进去的实参（模块自己的额外参数再覆盖它）
    args: Dict[str, Any] = Field(default_factory=dict)


class GroupSpec(BaseModel):
    """一条业务线。作用是「菜单分组」+「排序权重」+「归属哪个业务域」。"""

    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    order: int = 100
    #: 是否在菜单栏生成一个同名菜单
    menu: bool = True
    #: **业务域** —— 业务线之上的一层，导航树据此建三级树（域 → 业务线 → 模块）。
    #: 空串 = 不分组，业务线直接摊在树根（写清单时可以不写这个字段）。
    #:
    #: 域的顺序由**域内最小 order** 决定（业务线本来就有先后，域跟着走）；
    #: 没写 section 的那些统一压到最后 —— 它们是"还没归类"，不该插在真域前面。
    section: str = ""


class ModuleSpec(BaseModel):
    """一个模块（一个标签页，或一个 Dock）。"""

    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    group: str
    #: `"包.模块:类名"` —— 由 `loader.resolve()` 解析
    factory: str
    area: Area = "center"
    #: 同区域内按 (group.order, order) 升序
    order: int = 100
    #: 本模块自己的业务输入（YAML 或别的文件），相对清单所在目录解析。
    #: 留空 = 模块启动时不加载任何输入，由用户自己打开。
    input: str = ""
    #: 主绑定工具
    tool: Optional[ToolSpec] = None
    #: 模块自定义配置（列宽、默认值、订阅的话题…），模块自己解释
    params: Dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    #: true = 该视图没有真实数据源，界面上必须常驻「演示数据」横幅
    placeholder: bool = False


class WorkbenchManifest(BaseModel):
    """一份完整的界面清单。"""

    model_config = ConfigDict(extra="forbid")

    version: int = 1
    window: WindowSpec = Field(default_factory=WindowSpec)
    groups: List[GroupSpec] = Field(default_factory=list)
    modules: List[ModuleSpec] = Field(default_factory=list)

    # ── 跨字段校验 ──

    @model_validator(mode="after")
    def _validate_cross_refs(self) -> "WorkbenchManifest":
        seen_group = set()
        for group in self.groups:
            if group.id in seen_group:
                raise ValueError(f"groups 里 id 重复：{group.id!r}")
            seen_group.add(group.id)

        seen_module = set()
        for module in self.modules:
            if module.id in seen_module:
                raise ValueError(f"modules 里 id 重复：{module.id!r}")
            seen_module.add(module.id)
            if module.group not in seen_group:
                raise ValueError(
                    f"模块 {module.id!r} 的 group={module.group!r} 不在 groups 里"
                    f"（已有：{sorted(seen_group) or '空'}）")
        return self

    # ── 查询 ──

    def module(self, module_id: str) -> Optional[ModuleSpec]:
        for spec in self.modules:
            if spec.id == module_id:
                return spec
        return None

    def group(self, group_id: str) -> Optional[GroupSpec]:
        for group in self.groups:
            if group.id == group_id:
                return group
        return None

    def enabled_modules(self) -> List[ModuleSpec]:
        return [m for m in self.modules if m.enabled]

    def sorted_groups(self) -> List[GroupSpec]:
        return sorted(self.groups, key=lambda g: (g.order, g.id))

    def sections(self) -> List[Tuple[str, List[GroupSpec]]]:
        """业务域 → 该域下的业务线（已按 order 排好）。

        域的顺序 = **域内最小 order 首次出现的顺序**（`sorted_groups()` 是
        order 升序的，所以按它扫一遍、dict 记住首次出现即可）。没写 section 的
        统一压到最后。

        **向后兼容**：不写 `section` 的清单只会得到 `[("", [全部业务线])]` ——
        调用方（导航树）据此走"平铺"那条老路，行为与加这个字段之前完全一致。
        """
        buckets: Dict[str, List[GroupSpec]] = {}
        for group in self.sorted_groups():
            buckets.setdefault(group.section, []).append(group)
        # 稳定排序：只按"是不是空域"分两类，同类保持插入顺序（= 域内最小 order）
        return sorted(buckets.items(), key=lambda item: item[0] == "")

    def modules_of(self, group_id: str, area: Optional[str] = None) -> List[ModuleSpec]:
        """某业务线（可选再按区域过滤）的模块，按 (order, id) 升序。"""
        picked = [m for m in self.enabled_modules()
                  if m.group == group_id and (area is None or m.area == area)]
        return sorted(picked, key=lambda m: (m.order, m.id))

    def modules_in(self, area: str) -> List[ModuleSpec]:
        """某区域的全部模块，按 (业务线 order, order, id) 升序 —— 这就是
        页签的排布顺序 —— 同一窗格里也是这个先后。"""
        picked = [m for m in self.enabled_modules() if m.area == area]
        return sorted(picked, key=lambda m: (self._group_order(m.group),
                                             m.order, m.id))

    def _group_order(self, group_id: str) -> int:
        group = self.group(group_id)
        return group.order if group else 10_000
