"""仓储层 —— 读文件、归一化，产出 `domain` 对象。

分层：`repository` 只 import `domain`，不 import `compile` / `analysis`。
"""
from .memmap import FIXTURE_FILE, default_memmap_path, load_memmap, memmap_from_dict
from .registries import (NON_INSTRUCTION_CLASS, OPS_REGISTRY_FILE, SCHEMA_DIR,
                         load_ops_registry, registry_provenance)
from .txn_registry import TXN_REGISTRY_FILE, load_txn_registry

__all__ = ["load_ops_registry", "registry_provenance", "SCHEMA_DIR",
           "OPS_REGISTRY_FILE", "NON_INSTRUCTION_CLASS",
           "load_txn_registry", "TXN_REGISTRY_FILE",
           "load_memmap", "memmap_from_dict", "default_memmap_path", "FIXTURE_FILE"]
