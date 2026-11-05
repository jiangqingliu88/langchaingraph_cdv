"""命名契约 —— 测试点编号、UVM test 类名、整型投影。

## 为什么是框架的一部分

这些名字是**跨工具的契约**：`tp_id` 要贯穿用例库/回归/覆盖率/签核；
test 类名必须与 `uvm_tools.attr_class_slug` 逐字一致（两个包互不 import，
靠测试钉住）。所以它们不能散落在某个阶段的实现里 —— 放在框架的命名层，
所有阶段共用一套。
"""
from __future__ import annotations

import re
import zlib
from typing import Any, Iterable, List, Tuple

from ..domain.vocab import derive_code


def ascii_slug(text: Any) -> str:
    """任意文本 → `[a-z0-9_]`（小写）。非 ASCII 一律折成 `_`。"""
    return re.sub(r"[^A-Za-z0-9]+", "_", str(text or "")).strip("_").lower()


def int_value_of(token: Any, index: int) -> int:
    """取值 → 机器整型：数字优先，否则用下标（与 RTL 枚举编码一致）。"""
    try:
        return int(str(token).strip())
    except (TypeError, ValueError):
        return int(index)


def attr_class_slug(dim_ref: Any, value: Any, int_value: int) -> str:
    """`<维度>_p<取值>` —— 与 `uvm_tools.gen_uvm.attr_class_slug` 逐字一致。"""
    dim = ascii_slug(dim_ref) or "attr"
    text = str(value or "").strip()
    if re.fullmatch(r"[A-Za-z0-9_]+", text):
        return f"{dim}_p{text}"
    if isinstance(int_value, int):
        return f"{dim}_p{int_value}"
    return f"{dim}_p{zlib.crc32(text.encode('utf-8')) & 0xFFFF:04x}"


def attribute_test_name(env_name: str, dim_ref: Any, value: Any,
                        int_value: int) -> str:
    """一条属性测试的 UVM 类名 —— 与 `test_attr.sv.j2` 生成的完全一致。"""
    return f"{env_name}_{attr_class_slug(dim_ref, value, int_value)}_test"


def _tp_slug(text: Any) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", str(text or "")).strip("_").upper()


def tp_id_for(object_code: str, dim_ref: Any, value: Any,
              int_value: int) -> str:
    """稳定的测试点编号：`TP-<对象>-<维度>-<取值>`。"""
    code = _tp_slug(object_code) or "OBJ"
    dim = _tp_slug(dim_ref) or "DIM"
    text = str(value or "").strip()
    val = text.upper() if re.fullmatch(r"[A-Za-z0-9_]+", text) else f"V{int_value}"
    return f"TP-{code}-{dim}-{val}"


def unique_tp_id(base: str, used: set) -> str:
    """重名兜底：同维度两个字段给出同一个取值时，加序号而不是合并。"""
    name, n = base, 1
    while name in used:
        n += 1
        name = f"{base}_{n}"
    used.add(name)
    return name


def iter_value_points(model) -> Iterable[Tuple[Any, Any, int, Any, int, str]]:
    """`(dimension, field, index, point, int_value, tp_id)` 逐条产出。

    `model` 需要是 `resolve()` 过的。编号在这里**去重**：同维度两个字段
    给出同一个取值时加序号，不合并。
    """
    code = getattr(model, "object_code", "") or derive_code(model.object) or "OBJ"
    used: set = set()
    for dim in model.dimensions:
        dim_ref = dim.id or dim.name or dim.key
        for fld in dim.fields:
            for index, point in enumerate(fld.value_points()):
                iv = int_value_of(point.token, index)
                yield (dim, fld, index, point, iv,
                       unique_tp_id(tp_id_for(code, dim_ref, point.token, iv), used))
