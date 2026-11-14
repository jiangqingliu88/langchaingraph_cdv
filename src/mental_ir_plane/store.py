"""Mental IR 的落盘/读回（`<run>/mental_ir/`）。

机器读 JSON，人读 YAML；`manifest.json` 记规范哈希与计数 —— 后续 verify /
coverage 引用它时，必须能回答"引用的是哪一版理解"。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from .model import MentalIR

MENTAL_IR_DIR = "mental_ir"


def mental_ir_path(run_dir: str | Path) -> Path:
    return Path(run_dir) / MENTAL_IR_DIR / "mental_ir.json"


def write_mental_ir(run_dir: str | Path, ir: MentalIR) -> dict[str, Any]:
    """写 `mental_ir.json` + `mental_ir.yaml` + `manifest.json`（原子写）。"""
    from src.runtime_plane.core.runtime.atomic import (
        atomic_write_json,
        atomic_write_text,
    )

    out = Path(run_dir) / MENTAL_IR_DIR
    out.mkdir(parents=True, exist_ok=True)
    payload = ir.model_dump(mode="json")
    json_path = out / "mental_ir.json"
    atomic_write_json(json_path, payload)
    yaml_path = out / "mental_ir.yaml"
    atomic_write_text(yaml_path, yaml.safe_dump(payload, allow_unicode=True, sort_keys=False))
    manifest = {
        "schema": "mental_ir_manifest_v1",
        "module": ir.module,
        "digest": ir.digest(),
        "generated_at": ir.generated_at,
        "generator": dict(ir.generator),
        "counts": ir.counts(),
        "files": {"json": json_path.name, "yaml": yaml_path.name},
    }
    manifest_path = out / "manifest.json"
    atomic_write_json(manifest_path, manifest)
    return {
        "dir": str(out),
        "json": str(json_path),
        "yaml": str(yaml_path),
        "manifest": str(manifest_path),
        "digest": manifest["digest"],
        "counts": manifest["counts"],
    }


def read_mental_ir(run_dir: str | Path) -> MentalIR | None:
    """读回 Mental IR；没有或坏了返回 None（调用方自己决定是否报错）。"""
    path = mental_ir_path(run_dir)
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        return MentalIR.model_validate(doc)
    except (OSError, ValueError):
        return None


__all__ = ["MENTAL_IR_DIR", "mental_ir_path", "write_mental_ir", "read_mental_ir"]
