"""tensor_gen 主体 —— `preload.json` → 张量数据 + manifest（§3.12.9）。

     preload.json（只给句柄）──◄本模块►──► tensors/*.hex + manifest/*.json

本模块**纯**：吃 `preload` 与 `case`，吐数据与文本；写盘在 `export.py`。
（与 `api.py` 同一条纪律 —— 有副作用的地方只有一处，看得见。）

与 isa_gen 的边界（§3.14.4）
    isa_gen 只给 `ref` 句柄（`$t.img`），**从不碰数据**；
    数据由这里造。两边通过 registry 对齐 —— 但 registry 是 tensor_gen 写的，
    所以本模块顺带把它产出来（`registry` 段）。

确定性（E5）
    「派生 seed = hash(case_seed ⊕ name)」—— 用 `compile/sequencer.py` 的
    `Sequencer`，它已经是全仓"每个可随机对象各自一条流"的实现。
    **不复用的话就会出现两套派生规则**，而新增一个张量会改变既有张量的
    比特值 —— 那正是 E5 要防的（而且不报错）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from ..compile.sequencer import Sequencer
from .layout import Layout, layout_of
from .values import (DEFAULT_PATTERN, content_hash, make_values, pack_values,
                     to_hex_lines)


@dataclass
class TensorEntry:
    """一个张量的全部产物。"""

    name: str
    ref: str
    hex_text: str
    manifest: Dict[str, Any]
    n_bytes: int
    content_hash: str


@dataclass
class TensorBundle:
    """一次 tensor_gen 的全部产物。"""

    entries: List[TensorEntry] = field(default_factory=list)
    registry: Dict[str, Any] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)

    @property
    def total_bytes(self) -> int:
        return sum(e.n_bytes for e in self.entries)

    def by_name(self, name: str) -> Optional[TensorEntry]:
        for e in self.entries:
            if e.name == name:
                return e
        return None


def build_tensors(preload: Dict[str, Any], case: Dict[str, Any], *,
                  default_pattern: str = DEFAULT_PATTERN) -> TensorBundle:
    """`preload` + `case` → 张量数据与 manifest。

    每个对象**各自一条派生流**（E5）：`Sequencer(case_seed).draw(f"tensor:{name}")`。
    所以新增一个对象不会挪动既有对象的取值。
    """
    seed = _case_seed(case)
    seq = Sequencer(seed)

    bundle = TensorBundle()
    registry: Dict[str, Any] = {}

    for entry in (preload.get("entries") or []):
        name = str(entry.get("name") or "")
        ref = str(entry.get("ref") or f"$t.{name}")
        if not name:
            bundle.notes.append("preload 里有一条没有 name，跳过")
            continue

        layout = layout_of(entry.get("shape") or [1], str(entry.get("dtype") or "fp16"))
        pattern = str(entry.get("pattern") or default_pattern)

        # 一条派生流只服务这一个对象 —— 它内部的抽取顺序改了，也只有它自己受影响
        draw = seq.draw(f"tensor:{name}")
        values, scaled = make_values(layout, pattern=pattern, draw=draw,
                                     exp_range=entry.get("exp_range"))
        data = pack_values(values, layout.dtype)

        # 声明的 size 与布局算出来的对不上就是**真问题**：说明布局或
        # alloc 的 shape 有一个错了。响亮失败，不截断也不补齐。
        declared = entry.get("size")
        if isinstance(declared, int) and declared > 0 and layout.n_bytes > declared:
            raise ValueError(
                f"{name}: 布局需要 {layout.n_bytes} 字节，但 preload 只声明了 "
                f"{declared} 字节（shape={layout.shape} dtype={layout.dtype}）"
            )

        digest = content_hash(data)
        manifest = _manifest(name, ref, entry, layout, pattern, values,
                             scaled, digest, seed)

        bundle.entries.append(TensorEntry(
            name=name, ref=ref, hex_text=to_hex_lines(data),
            manifest=manifest, n_bytes=len(data), content_hash=digest))

        registry[name] = {
            "addr": _addr(entry),
            "shape": list(layout.dims),
            "dtype": layout.dtype,
            "layout": layout.to_manifest(),
            "value_range": manifest["value_range"],
            "exp_range": manifest["exp_range"],
        }
        if scaled:
            bundle.notes.append(
                f"{name}: 有值超出 exp_range，已按指数差缩放（E1，见 manifest.exp_range.scaled）")
        if layout.bc_only:
            bundle.notes.append(
                f"{name}: rem_dim0={layout.rem_dim0} ≠ 0 → 打 bc_only，只有 BC 类指令能引用（E4）")

    bundle.registry = {
        "$comment": "registry 分配记录 —— name → {addr, shape, dtype, layout, 值域, 指数域}；"
                    "isa_gen 的 ref 解析 / CMI preload / scoreboard 共用这一份（§3.14.4）",
        "seed": seed,
        "tensors": registry,
    }
    return bundle


def _case_seed(case: Dict[str, Any]) -> int:
    meta = (case or {}).get("meta") or {}
    seed = meta.get("seed")
    if seed is None:
        raise ValueError("case 里没有 meta.seed —— 张量取值没有可复现的根")
    return int(seed)


def _addr(entry: Dict[str, Any]) -> str:
    """`region` + `offset` → 一个十六进制地址字符串（照 §3.0.2 的写法）。"""
    offset = entry.get("offset") or "0x0"
    return str(offset)


def _manifest(name: str, ref: str, entry: Dict[str, Any], layout: Layout,
              pattern: str, values: Sequence[float], scaled: bool,
              digest: str, case_seed: int) -> Dict[str, Any]:
    """manifest schema v1.1（§3.12.9）—— 能填的填，填不了的显式 `null`。

    **不幻想**：E3（CIMC FP 分区的 EXP Shadow）要硬件侧规则、E8（dtype×区域×
    指令类的合法组合）要 Prec 总表 —— 两张表都还没接入，所以那两个字段
    是 `null` + 一条 note，而不是"看起来像填过了"。
    """
    finite = [v for v in values if v == v and abs(v) != float("inf")]
    return {
        # 身份
        "name": name, "ref": ref, "content_hash": digest,
        # 形状（与 T1 的 [dim2, dim1, dim0] 一致）
        "shape": list(layout.dims), "dtype": layout.dtype,
        # 布局
        "layout": {**layout.to_manifest(),
                   "storage": str(entry.get("region") or ""),
                   "base_addr": _addr(entry),
                   "align": 32 if layout.dtype in ("fp32", "fp16", "bf16") else 1},
        # 编码（E3 —— 需要硬件规则，尚未接入）
        "fp_split": None,
        # 值域
        "pattern": pattern,
        "value_range": ([min(finite), max(finite)] if finite else [0.0, 0.0]),
        "exp_range": {"declared": entry.get("exp_range"), "scaled": scaled},
        "special_values": {"mode": "allow", "ratio": 0.0,
                           "note": "E2：FP 特殊值默认允许，含特殊值的指令期望强制交 ISS"},
        # 索引语义（E6 —— gather 的 index 张量）
        "index_of": None,
        # 溯源 —— E5：派生 seed = hash(case_seed ⊕ name)。**记的是派生键**
        # （`compile/sequencer.py` 内部怎么 hash 是它的实现，这里不重算一遍 ——
        # 重算就是第二套派生规则，而两套规则迟早对不上）。
        "seed": {"parent_case_seed": case_seed, "stream": f"tensor:{name}"},
        "parent_case_seed": case_seed,
        "tool_version": "0.1",
        "memmap_version": str((entry.get("memmap_version") or "v1")),
        # 尚未接入的两块，显式说明
        "_pending": ["E3 CIMC FP 分区 EXP Shadow（需硬件规则）",
                     "E8 dtype×区域×指令类合法性（需 Prec 总表）"],
    }
