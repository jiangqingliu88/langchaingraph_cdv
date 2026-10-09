"""注册表的装载 —— JSON 数据 → `domain` 对象。

分层：`repository` 只 import `domain`（见 `domain/__init__.py` 的分层规则）。

**fail-closed**：读不进来就抛错，不吞。理由与 casemodel 的 schema 检查同一条 ——
一个"读不到就静默用空表"的加载器，会让生成器产出一份没有指令的 IR，
而调用方要到仿真里才发现"什么都没跑"。宁可起不来。

数据是**随包走的文件**（`schema/ops.registry.json`），不是运行时从外部读的：
  · 外部读 → 工具没法单独跑（那份 xlsx 在别人的桌面上）
  · 随包走 → "当前用的是哪一版编码表"在 git 里可审计
见 `build_registry.py` 的模块头。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..domain import (IsaFamily, MaskSemantics, OpClass, OpRegistry, OpRole,
                      OpSpec, PairingKind, RegistryError, parse_flags,
                      parse_funct7)

#: 数据目录 —— 与包同址，随包发布
SCHEMA_DIR = Path(__file__).resolve().parents[1] / "schema"
OPS_REGISTRY_FILE = SCHEMA_DIR / "ops.registry.json"

#: 非指令 op 在注册表里的 `op_class` 值（见 build_registry 的 `_extra_ops`）
NON_INSTRUCTION_CLASS = "op"


def load_ops_registry(path: Optional[Path] = None) -> OpRegistry:
    """读 `ops.registry.json` → `OpRegistry`。"""
    target = Path(path) if path else OPS_REGISTRY_FILE
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RegistryError(f"注册表文件不存在：{target}", target=str(target),
                            fix="确认 schema/ops.registry.json 随包发布了") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise RegistryError(f"注册表读不出来：{exc}", target=str(target),
                            fix="文件损坏；用 build_registry.py 重新生成") from exc

    entries = raw.get("ops") if isinstance(raw, dict) else raw
    if not isinstance(entries, list) or not entries:
        raise RegistryError(f"注册表里没有 ops 列表：{target}", target=str(target),
                            fix="用 build_registry.py 重新生成")
    return OpRegistry([_spec_from_dict(entry, target) for entry in entries])


def registry_provenance(path: Optional[Path] = None) -> Dict[str, Any]:
    """这份注册表是从哪来的 —— `run_ops` / `run_explain` 用它回答"用的哪版表"。"""
    target = Path(path) if path else OPS_REGISTRY_FILE
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {"version": raw.get("version"), "source": raw.get("source", ""),
            "file": target.name}


def _spec_from_dict(entry: Dict[str, Any], source: Any) -> OpSpec:
    name = str(entry.get("name", "")).strip()
    if not name:
        raise RegistryError("注册表里有一条没有 name 的 op", target=str(source))

    op_class_raw = str(entry.get("op_class", "")).strip().lower()
    if op_class_raw == NON_INSTRUCTION_CLASS:
        # 非指令 op（csr_write / wait_done / expect_*…）没有编码 —— 给它 `None`，
        # 而不是硬塞一个 CONTROL：塞进去会让按类查询把它们和真指令混在一起。
        op_class = None
    else:
        try:
            op_class = OpClass[op_class_raw.upper()]
        except KeyError as exc:
            raise RegistryError(
                f"{name} 的 op_class={op_class_raw!r} 不认识",
                target=name,
                fix=f"可选：{', '.join(c.name.lower() for c in OpClass)}, "
                    f"{NON_INSTRUCTION_CLASS}") from exc

    flags_raw = entry.get("flags")
    flags = None
    if isinstance(flags_raw, (list, tuple)) and len(flags_raw) == 3:
        flags = tuple(int(v) for v in flags_raw)
    elif isinstance(flags_raw, str) and flags_raw.strip():
        flags = parse_flags(flags_raw)

    try:
        return OpSpec(
            name=name,
            op_class=op_class,
            isa_family=IsaFamily(str(entry.get("isa_family", "nice")).lower()),
            funct7=parse_funct7(entry.get("funct7", "")),
            flags=flags,
            opcode=str(entry.get("opcode", "") or ""),
            role=OpRole(str(entry.get("role", "lone")).lower()),
            pairing=PairingKind(str(entry.get("pairing", "none")).lower()),
            cfg_required=str(entry.get("cfg_required", "") or ""),
            mask_semantics=MaskSemantics(
                str(entry.get("mask_semantics", "global")).lower()),
            sub_family=str(entry.get("sub_family", "") or ""),
            deferred=bool(entry.get("deferred", False)),
            notes=str(entry.get("notes", "") or ""),
        )
    except ValueError as exc:
        raise RegistryError(f"{name} 的字段取值不认识：{exc}", target=name,
                            fix="检查 ops.registry.json 该行；用 build_registry.py 重生成") from exc
