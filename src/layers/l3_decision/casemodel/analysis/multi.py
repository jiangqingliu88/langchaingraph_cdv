"""多对象模型 —— 一份文件描述 N 个被测对象时的合并。

清单里的两种写法：

    object: FlowControl          # 写法一：一个对象
    sub_objects: [...]

    tests:                       # 写法二：N 个对象，共享下面的属性空间
      - {object: FlowControl, object_code: FC, sub_objects: [...]}
      - {object: Arbiter,     object_code: ARB, sub_objects: [...]}

**合并语义**（与用户确认过）：

| 产物 | 怎么办 | 为什么 |
|---|---|---|
| 交叉矩阵 / 取值覆盖 / 维度级规则 | **算一次** | 它们只依赖共享的维度空间，对每个对象都一样 |
| 功能组织树 / case / 组织树规则 | **每个对象各一份** | 树是各对象的 |
| 完备性评分 | **一个数** | 评分是**属性空间**的属性，不是某个对象的 |

实现上**不重写分析链**，而是把 N 个模型**合成一个**：`org_root` 拼接、其余字段
取共享空间；case 则**按对象分别生成**再拼起来 —— 因为 `case_id` 的前缀是
`TC-<对象代号>-…`，合并成一棵树之后就再也分不出哪个节点属于哪个对象了，
只能在各对象自己的上下文里生成。

合成体走原来的 `analyze()` —— 于是上表三条是它天然的结果，`score` / `matrix` /
`coverage` 一行都不用改。这也是为什么这里只有几十行：**变化被吸收在「模型长什么样」
这一层，没有渗进判定逻辑**。
"""
from __future__ import annotations

from dataclasses import replace
from typing import List, Optional, Sequence

from ..domain import CaseModel, ExternalCase
from ..generation import GenerationResult, generate
from .facade import analyze
from .result import AnalysisResult


def merge_models(models: Sequence[CaseModel], *, source: str = "") -> CaseModel:
    """N 个模型 → 一个合并体：org_root 拼接，其余取共享空间（第一个）。

    `object_code` 保留第一个的 —— 它只影响 `case_id` 前缀，而 case 是外面
    按对象分别生成好传进来的，不走合并体的 `object_code`（见模块头）。
    """
    if len(models) == 1:
        return models[0]

    head = models[0]
    roots, flat = [], []
    for model in models:
        roots.extend(model.org_root)
        flat.extend(model.sub_objects)

    return replace(
        head,
        object="+".join(m.object for m in models),
        object_cn="、".join(n for n in (m.object_cn for m in models) if n),
        description=" / ".join(n for n in (m.description for m in models) if n),
        org_root=roots,
        sub_objects=flat,
        source=source or head.source,
    )


def generate_many(models: Sequence[CaseModel], *, seed: Optional[int] = None,
                  max_cases: Optional[int] = None) -> GenerationResult:
    """每个对象各生成一套 case，拼成一个结果。

    `max_cases` 是**每个对象各自**的上限，不是全局的：全局上限会让排在后面的
    对象被前面的挤光 —— 那不是「给每个对象都测一测」的意思。
    """
    parts = [generate(m, seed=seed, max_cases=max_cases) for m in models]
    first = parts[0]
    return GenerationResult(
        cases=[c for part in parts for c in part.cases],
        themes_used=_union(p.themes_used for p in parts),
        priorities_used=_union(p.priorities_used for p in parts),
        groups_used=_union(p.groups_used for p in parts),
        methods_used=_union(p.methods_used for p in parts),
        total_before_cap=sum(p.total_before_cap for p in parts),
        truncated=any(p.truncated for p in parts),
        dropped=sum(p.dropped for p in parts),
        notes=[n for p in parts for n in p.notes],
        seed=first.seed,
        driver=first.driver,
    )


def analyze_many(models: Sequence[CaseModel], *, seed: Optional[int] = None,
                 max_cases: Optional[int] = None,
                 external: Optional[Sequence[ExternalCase]] = None,
                 external_source: str = "") -> AnalysisResult:
    """一组模型的完备性分析。单对象时就是 `analyze()` 本身。

    多对象时：case 按对象分别生成（保住各自的 case_id 前缀），再把合成体交给
    `analyze()` 算矩阵 / 覆盖 / 规则 / 评分。
    """
    if len(models) == 1:
        return analyze(models[0], seed=seed, max_cases=max_cases,
                       external=external, external_source=external_source)

    generation = generate_many(models, seed=seed, max_cases=max_cases)
    return analyze(merge_models(models), generation=generation,
                   external=external, external_source=external_source)


def _union(lists) -> List[str]:
    """保序去重 —— 各对象的「用到了哪些专题/方法」合并成一份。"""
    seen: List[str] = []
    for items in lists:
        for item in items:
            if item not in seen:
                seen.append(item)
    return seen
