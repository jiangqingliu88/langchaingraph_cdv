"""多后端能力矩阵 —— 在 `backend_profiles` 的数据表上补「能做什么」。

不是新引擎：`backend_profiles` 仍是方言/命令模板的唯一来源；这里只回答
「这个后端是否支持 compile / sim / coverage / wave」，未支持的能力显式
报错，不静默降级。
"""
from __future__ import annotations

from typing import Any, Dict, Tuple

from src.layers.l2_orchestration.regression_tools.backend_profiles import (
    BACKENDS, normalize_backend, reserved_keys,
)

CAPABILITIES = ("compile", "sim", "coverage", "wave", "seed")

#: 能力表：仅登记**已验证**的项；未列出的能力一律 False。
CAPABILITY_MATRIX: Dict[str, Dict[str, bool]] = {
    "questa": {"compile": True, "sim": True, "coverage": True,
               "wave": True, "seed": True},
    "vcs": {"compile": True, "sim": True, "coverage": True,
            "wave": True, "seed": True},
    "verilator": {"compile": True, "sim": False, "coverage": False,
                  "wave": False, "seed": True},
    "icarus": {"compile": True, "sim": True, "coverage": False,
               "wave": False, "seed": False},
}


def capabilities(backend: str) -> Dict[str, bool]:
    name = normalize_backend(backend) or str(backend or "").strip().lower()
    return {cap: bool(CAPABILITY_MATRIX.get(name, {}).get(cap, False))
            for cap in CAPABILITIES}


def supports(backend: str, capability: str) -> Tuple[bool, str]:
    """返回 (supported, reason)。未支持时 reason 明确写出后端+能力。"""
    cap = str(capability or "").strip().lower()
    if cap not in CAPABILITIES:
        return False, f"未知能力 {capability!r}"
    name = normalize_backend(backend) or str(backend or "").strip().lower()
    if name not in BACKENDS:
        return False, f"未知后端 {backend!r}"
    ok = capabilities(name).get(cap, False)
    return ok, "" if ok else f"后端 {name!r} 未实现 {cap!r} 能力（显式失败，不降级）"


def profile(backend: str) -> Dict[str, Any]:
    name = normalize_backend(backend) or str(backend or "").strip().lower()
    return {
        "backend": name,
        "display": str((BACKENDS.get(name) or {}).get("display") or name),
        "capabilities": capabilities(name),
        "reserved_keys": sorted(reserved_keys(name)),
    }
