"""生成层的内部数据形状 —— 不读文件、不依赖 Jinja。

拆分层之后，`parsing` 负责把 YAML/spec 变成这些 dataclass，`generators`
只编排它们，`render` 只接收 ctx。这样测试可以分别断言：
    YAML → dataclass（parsing）
    dataclass → ctx（generators）
    ctx → 字符串（render）
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class Artifact:
    """一个待落盘产物。"""
    name: str
    section: str                 # inputs / env / coverage / regression / verdict
    path: str                    # 相对 run 目录
    required_keys: List[str] = field(default_factory=list)


@dataclass
class RegressionCase:
    name: str
    test: str = ""
    build: str = ""
    seeds_base: int = 0
    seeds_count: int = 1
    modes: List[str] = field(default_factory=list)
    plusargs: List[str] = field(default_factory=list)
    backend_args: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    stage: str = ""


@dataclass
class CoveragePlanSpec:
    module: str
    coverpoints: List[Dict[str, Any]] = field(default_factory=list)
    crosses: List[Dict[str, Any]] = field(default_factory=list)
    batches: List[Dict[str, Any]] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


@dataclass
class ConstraintSpec:
    module: str
    policies: List[Dict[str, Any]] = field(default_factory=list)
    transactions: List[Dict[str, str]] = field(default_factory=list)
    backing: Optional[Dict[str, Any]] = None


@dataclass
class EnvSpec:
    module: str
    agents: List[Dict[str, Any]] = field(default_factory=list)
    tests: List[Dict[str, Any]] = field(default_factory=list)
    batches: List[Dict[str, Any]] = field(default_factory=list)
    util_components: List[Dict[str, Any]] = field(default_factory=list)
    output_root: Optional[Path] = None

    def to_uvm_ir(self):
        """映射到统一 UVM IR（不渲染、不写文件；见 `generation/ir/`）。"""
        from .ir.uvm_ir import build_uvm_ir
        return build_uvm_ir(self)
