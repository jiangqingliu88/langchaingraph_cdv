"""可玩池 —— **L1 场景约束**的落点。

文档 §3.12.7 给了一个交集：

    最终合法地址集 = memmap.yaml（全局合法性）
                  ∩ DSL.resources（本 case 可玩池）
                  ∩ 事务的硬约束（对齐 / 区域类型）

这个模块做**前两项的交集**；第三项在 `allocator.py` 里按事务逐条应用。

为什么把"可玩池"单独成一个概念
    全局合法 ≠ 这个 case 能用。memmap 说 Share DRAM 有 2GB，但一份 case
    可能只想在 `hot_dram` 那 16MB 里玩（为了把地址复用压到高概率）。
    把两者混在一起，分配器会到处撒点 —— 于是 RAW 冲突变成稀有事件，
    `hazard_density` 那个意图旋钮就调不动了。

**这一层不放宽任何东西**：它只做减法。L0（对齐、越界、伪空间）在这里
一条都不能松 —— 文档 §3.15 规则 2 明说缺口回灌只允许碰 L2。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from ..domain import LintError
from ..domain.dsl import DslDocument
from ..domain.memmap import MemMap, Region, parse_size


@dataclass(frozen=True)
class PlayPool:
    """一个可玩池 —— 指向某块 region，外加本 case 愿意用的容量。"""

    name: str
    region: Region
    capacity: int
    tiles: Optional[int] = None

    def to_dict(self) -> Dict[str, object]:
        out = {"name": self.name, "region": self.region.name,
               "capacity": self.capacity, "align": self.region.align}
        if self.tiles is not None:
            out["tiles"] = self.tiles
        return out


@dataclass(frozen=True)
class PlaySpace:
    """本 case 能用的地址空间。

    `pools` 是**按名字**的 —— `alloc` 条目用 `pool:` 引用它。
    `regions` 是允许直接按 region 名引用的那些（`alloc.pool` 也可以写 region 名）。
    """

    pools: Dict[str, PlayPool] = field(default_factory=dict)
    regions: Tuple[Region, ...] = ()
    excluded: Tuple[str, ...] = ()
    overlap_ratio: float = 0.0

    def pool(self, name: str) -> PlayPool:
        found = self.pools.get(name)
        if found is not None:
            return found
        # 没声明池时允许直接按 region 名引用 —— DSL 里 `pool: dram.share` 很常见
        region = next((r for r in self.regions if r.name == name), None)
        if region is None:
            known = ", ".join(sorted(self.pools)) or "（无）"
            raise LintError(
                f"pool {name!r} 既不是声明的池、也不是可用的 region",
                target=name,
                fix=f"可选池：{known}；可选 region："
                    f"{', '.join(r.name for r in self.regions)}")
        return PlayPool(name=region.name, region=region,
                        capacity=region.allocatable_size)

    def to_dict(self) -> Dict[str, object]:
        return {
            "pools": [p.to_dict() for p in sorted(self.pools.values(),
                                                  key=lambda p: p.name)],
            "regions": [r.name for r in self.regions],
            "excluded": list(self.excluded),
            "overlap_ratio": self.overlap_ratio,
        }


def build_play_space(dsl: DslDocument, memmap: MemMap) -> PlaySpace:
    """memmap ∩ DSL.resources → 可玩池。

    三种失败都报 `LintError`（文档 §3.12.6 把"未知区域"归为 lint 失败）：
      · `exclude` / `region_pools` / `dram.share` 里写了 memmap 没有的 region
      · 池声明的容量超过 region 的可分配量
      · 排除之后一块都不剩
    """
    excluded = tuple(dict.fromkeys(dsl.resources.exclude))
    for name in excluded:
        if memmap.find_region(name) is None:
            raise LintError(f"exclude 里的 {name!r} 不在 memmap 中",
                            target=name,
                            fix=f"memmap 里的区域：{', '.join(memmap.region_names())}")

    allowed: List[Region] = []
    for region in memmap.regions:
        if region.name in excluded:
            continue
        if _is_excluded_by_dram_scope(region, dsl):
            continue
        allowed.append(region)

    if not allowed:
        raise LintError("排除之后一块可用 region 都不剩",
                        target="resources.exclude",
                        fix="检查 exclude —— 它把 memmap 里的区域全排掉了")

    pools: Dict[str, PlayPool] = {}
    for pool_name, spec in dsl.resources.region_pools.items():
        region = _pool_region(pool_name, spec, memmap, allowed)
        capacity = region.allocatable_size
        if spec.size:
            declared = parse_size(spec.size)
            if declared > region.allocatable_size:
                raise LintError(
                    f"池 {pool_name} 声明 {spec.size}，超过 {region.name} 的"
                    f"可分配量 {region.allocatable_size} 字节",
                    target=f"resources.region_pools.{pool_name}.size",
                    fix="调小 size，或换一块更大的 region")
            capacity = declared
        pools[pool_name] = PlayPool(name=pool_name, region=region,
                                    capacity=capacity, tiles=spec.tiles)

    return PlaySpace(pools=pools, regions=tuple(allowed), excluded=excluded,
                     overlap_ratio=dsl.resources.overlap_ratio)


def _pool_region(pool_name: str, spec, memmap: MemMap,
                 allowed: List[Region]) -> Region:
    """池指向哪块 region —— 先按 `regions`，再按 `domains` 里的第一个。"""
    for candidate in spec.regions:
        region = memmap.find_region(candidate)
        if region is None:
            raise LintError(f"池 {pool_name} 引用的 region {candidate!r} 不在 memmap 中",
                            target=f"resources.region_pools.{pool_name}.regions",
                            fix=f"可选：{', '.join(memmap.region_names())}")
        if region not in allowed:
            raise LintError(f"池 {pool_name} 引用的 {candidate!r} 被 exclude 排掉了",
                            target=f"resources.region_pools.{pool_name}",
                            fix="从 exclude 里去掉，或换一块区域")
        return region
    for domain in spec.domains:
        match = next((r for r in allowed if r.domain == domain), None)
        if match is not None:
            return match
        raise LintError(f"池 {pool_name} 的 domain {domain!r} 没有对应 region",
                        target=f"resources.region_pools.{pool_name}.domains",
                        fix=f"memmap 里的 domain："
                            f"{', '.join(sorted({r.domain for r in memmap.regions}))}")
    raise LintError(f"池 {pool_name} 既没写 regions 也没写 domains",
                    target=f"resources.region_pools.{pool_name}",
                    fix="二者至少写一个")


def _is_excluded_by_dram_scope(region: Region, dsl: DslDocument) -> bool:
    """`resources.dram` 里列了具体区域时，只留那几块 DRAM。

    文档的写法是 `dram: {share: ["0x1_0000_0000..0x1_0FFF_FFFF"], common: auto}`——
    值可能是地址区间（字符串）或 `auto`。**只认 `auto` 与空**：
    地址区间的解析规则文档没给全（`..` 的端点含不含、多段怎么拼），
    与其猜，不如不接受 —— 写区间会得到一条明确的报错。
    """
    scope = dsl.resources.dram
    if region.domain.startswith("dram_share") and scope.share:
        return not _all_auto(scope.share, "resources.dram.share")
    if region.domain.startswith("dram_common") and scope.common:
        return not _all_auto([scope.common], "resources.dram.common")
    return False


def _all_auto(values: List[str], target: str) -> bool:
    for value in values:
        if str(value).strip().lower() != "auto":
            raise LintError(
                f"{target} 目前只支持 auto，不支持地址区间（{value!r}）",
                target=target,
                fix="文档没写清地址区间的端点语义，所以这里不猜 —— "
                    "改用 region_pools 声明可玩池")
    return True
