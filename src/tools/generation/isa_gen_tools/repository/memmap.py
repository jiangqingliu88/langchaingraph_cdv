"""memmap 的装载 —— YAML → `domain.memmap.MemMap`。

**fail-closed**：读不到就抛。一份"读不到就用空表"的 memmap 会让分配器
认为"没有任何合法区域"，然后要么产出空 IR、要么把张量放在无处 ——
两种都在仿真里才暴露。宁可起不来。

路径**可配置**：冻结版 `verification/memmap.yaml` 到位后换路径即可，
代码不用动。缺省指向包内的 `fixtures/memmap.yaml`（**重建样例，非冻结版**）。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from ..domain import IsaGenError, RegistryError
from ..domain.memmap import MemMap, Region, parse_size

#: 包内样例 —— 从文档 §3.12.5 的结构重建的，**不是冻结版**
FIXTURE_FILE = Path(__file__).resolve().parents[1] / "fixtures" / "memmap.yaml"

#: 冻结版应当放的位置（文档 §3.12.5 说的）—— 存在就优先用它
FROZEN_CANDIDATES = (
    Path("verification/memmap.yaml"),
    Path("config/memmap.yaml"),
)


def default_memmap_path() -> Optional[Path]:
    """优先用冻结版；没有就退回包内样例。两处都没有返回 None。"""
    for candidate in FROZEN_CANDIDATES:
        if candidate.is_file():
            return candidate
    return FIXTURE_FILE if FIXTURE_FILE.is_file() else None


def load_memmap(path: Optional[Path] = None) -> MemMap:
    """读 memmap。不给路径时按 `default_memmap_path()` 找。"""
    target = Path(path) if path else default_memmap_path()
    if target is None:
        raise RegistryError(
            "找不到 memmap.yaml",
            fix="放到 verification/memmap.yaml，或显式给路径；"
                "包内 fixtures/memmap.yaml 是从文档重建的样例")
    try:
        raw = yaml.safe_load(target.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RegistryError(f"memmap 文件不存在：{target}", target=str(target)) from exc
    except (OSError, yaml.YAMLError) as exc:
        raise RegistryError(f"memmap 读不出来：{exc}", target=str(target),
                            fix="检查 YAML 语法") from exc
    if not isinstance(raw, dict):
        raise RegistryError(f"memmap 顶层必须是 mapping：{target}", target=str(target))
    return memmap_from_dict(raw, source=target.name)


def memmap_from_dict(data: Dict[str, Any], *, source: str = "<dict>") -> MemMap:
    regions: List[Region] = []
    for index, entry in enumerate(data.get("regions") or []):
        if not isinstance(entry, dict):
            raise RegistryError(f"regions[{index}] 必须是 mapping", target=source)
        regions.append(_region_from_dict(entry, source))
    if not regions:
        # 空 memmap 不是"宽松"，是"没得选" —— 分配器拿它会一个合法地址都找不到
        raise RegistryError("memmap 里没有任何 region", target=source,
                            fix="至少要有 lmem 与 dram 各一块")

    names = [r.name for r in regions]
    duplicates = sorted({n for n in names if names.count(n) > 1})
    if duplicates:
        raise RegistryError(f"region 名重复：{duplicates}", target=source,
                            fix="区域名是唯一键，重名会让按名查拿到错的那块")

    return MemMap(
        version=int(data.get("version", 1)),
        chips=dict(data.get("chip") or {}),
        peers=tuple(dict(p) for p in (data.get("peers") or [])),
        regions=tuple(regions),
        reserved=tuple(_interval(x, source) for x in (data.get("reserved") or [])),
        aliases=tuple(dict(a) for a in (data.get("aliases") or [])),
        source=source,
    )


def _region_from_dict(entry: Dict[str, Any], source: str) -> Region:
    name = str(entry.get("name") or "").strip()
    if not name:
        raise RegistryError("region 缺 name", target=source)
    base = _number(entry.get("base", 0), f"{name}.base")
    size = parse_size(entry.get("size", 0))
    real = entry.get("real_size")
    return Region(
        name=name,
        domain=str(entry.get("domain") or ""),
        base=base,
        size=size,
        per=str(entry.get("per") or ""),
        align=int(_number(entry.get("align", 32), f"{name}.align")),
        granule=int(parse_size(entry["granule"])) if entry.get("granule") else 0,
        banks=int(entry.get("banks") or 0),
        real_size=int(parse_size(real)) if real is not None else None,
        comment=str(entry.get("comment") or ""),
    )


def _number(value: Any, where: str) -> int:
    """`"0x1_0000_0000"` / `4096` → int。下划线只是给人分段看的。"""
    if isinstance(value, bool):
        raise RegistryError(f"{where} 不能是布尔值")
    if isinstance(value, int):
        return value
    text = str(value).strip().replace("_", "")
    try:
        return int(text, 0)          # 0x.. / 0b.. / 十进制都认
    except ValueError as exc:
        raise RegistryError(f"{where} 看不懂：{value!r}", target=where,
                            fix="形如 0x1_0000_0000 或 4096") from exc


def _interval(value: Any, source: str) -> Tuple[int, int]:
    """`[low, high]` → 闭区间。**含两端** —— 文档里就是这么写的。"""
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise RegistryError(f"reserved 的区间要写成 [low, high]，拿到 {value!r}",
                            target=source)
    low, high = _number(value[0], "reserved.low"), _number(value[1], "reserved.high")
    if low > high:
        raise RegistryError(f"reserved 区间反了：[{low:#x}, {high:#x}]", target=source)
    return low, high
