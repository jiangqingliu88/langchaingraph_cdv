"""功能组织树 —— L2 子对象的层级形态。

设计模式：**Composite**。一个节点既可能是叶子（直接生成 case），也可能是分支
（自己的 case 由下面的叶子承担）。调用方对二者用同一套接口：
`leaves()` / `walk()` / `path()` 都把结构差异吃掉了 —— 所以专题的
`applies_to: [指令]` 指向一个分支时，不需要在调用处写 if，展开到叶子即可。

扁平列表是这棵树的特例（所有节点都是叶子），所以只写一层 sub_objects
的旧模型不用改一行。
"""
from __future__ import annotations

from dataclasses import dataclass, field as _field
from typing import Iterator, List, Optional

from .vocab import derive_code


@dataclass
class OrgNode:
    """功能组织树的一个节点。"""
    id: str
    name: str
    code: str = ""
    code_declared: bool = False
    description: str = ""
    #: 代号来源：declared（显式声明）/ name（从名字推导）/ id（从 id 抠）/ fallback（序号兜底）
    code_source: str = "declared"
    children: List["OrgNode"] = _field(default_factory=list)
    # 回指由树构建时接好；不参与比较与打印，否则 repr 会顺着 parent 无限展开
    parent: Optional["OrgNode"] = _field(default=None, repr=False, compare=False)

    # ── 结构判定 ──

    @property
    def key(self) -> str:
        return self.id or self.name

    @property
    def is_leaf(self) -> bool:
        return not self.children

    @property
    def is_branch(self) -> bool:
        return bool(self.children)

    @property
    def depth(self) -> int:
        d, node = 0, self.parent
        while node is not None:
            d += 1
            node = node.parent
        return d

    @property
    def label(self) -> str:
        return f"{self.name}（{self.code}）" if self.code else self.name

    # ── 遍历 ──

    def path(self) -> List[str]:
        """根 → 本节点的名字链。"""
        chain: List[str] = []
        node: Optional["OrgNode"] = self
        while node is not None:
            chain.append(node.name)
            node = node.parent
        return list(reversed(chain))

    def path_label(self) -> str:
        return " / ".join(self.path())

    def walk(self) -> Iterator["OrgNode"]:
        """前序遍历：自身 + 全部后代。"""
        yield self
        for child in self.children:
            yield from child.walk()

    def leaves(self) -> List["OrgNode"]:
        """本子树下的全部叶子 —— 专题展开的目标就是它。"""
        return [n for n in self.walk() if n.is_leaf]

    def branches(self) -> List["OrgNode"]:
        return [n for n in self.walk() if n.is_branch]

    # ── 匹配 ──

    def matches(self, ref: str) -> bool:
        r = (ref or "").strip()
        return bool(r) and (r in (self.id, self.name)
                            or r.lower() in (self.id.lower(), self.name.lower()))

    def __str__(self) -> str:                       # 便于日志与调试
        return f"{self.label}{'…' if self.is_branch else ''}"


def build_org_tree(raw: object, object_code: str = "") -> List[OrgNode]:
    """YAML 的 sub_objects 段 → 功能组织树（返回根节点列表）。

    递归构建，顺便把 parent 回指接好。代号（code）优先取显式声明，
    其次从名字推导，最后退化到 S01/S02… —— 用全局序号，保证同一棵树里唯一，
    否则两条叶子的 case_id 会撞车。
    """
    from .vocab import as_list          # 局部导入避免与本模块的循环引用
    import re

    counter = [0]

    def build(items: object, parent: Optional[OrgNode]) -> List[OrgNode]:
        nodes: List[OrgNode] = []
        for item in as_list(items):
            if isinstance(item, dict):
                nid = str(item.get("id") or "").strip()
                name = str(item.get("name") or nid).strip()
                code = str(item.get("code") or "").strip().upper()
                desc = str(item.get("description") or "")
                children_raw = item.get("children")
            else:
                nid = name = str(item).strip()
                code = desc = ""
                children_raw = None

            counter[0] += 1
            idx = counter[0]
            declared = bool(code)
            if declared:
                source = "declared"
            else:
                source = "name"
                code = derive_code(name)
                if not code:
                    source = "id"
                    letters = "".join(re.findall(r"[A-Za-z]+", nid)).upper()
                    if object_code and letters.startswith(object_code):
                        letters = letters[len(object_code):]
                    code = letters[:8]
                if not code:
                    source = "fallback"
                    code = f"S{idx:02d}"

            node = OrgNode(id=nid or f"S{idx:02d}", name=name, code=code,
                           code_declared=declared, code_source=source,
                           description=desc, parent=parent)
            node.children = build(children_raw, node) if children_raw else []
            nodes.append(node)
        return nodes

    return build(raw, None)


def flatten(nodes: List[OrgNode]) -> List[OrgNode]:
    """前序展平 —— 保持旧代码里 `model.sub_objects` 是个扁平列表的语义。"""
    out: List[OrgNode] = []
    for node in nodes:
        out.extend(node.walk())
    return out


def collect_leaves(nodes: List[OrgNode]) -> List[OrgNode]:
    out: List[OrgNode] = []
    for node in nodes:
        out.extend(node.leaves())
    return out
