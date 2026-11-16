"""Standalone 专家的公共骨架。

mental / formal / unit_test 这类"不挂 supervisor、可独立跑"的专家重复了同一套
生命周期：拼 messages → 调 LLM → 校验（失败带错误重试）→ 原子落盘。
这里只保留**一份**实现，避免三个专家各写一遍后校验/重试策略慢慢漂移。

边界：
  · 只做 LLM 文本/JSON 与落盘，不驱动流程；
  · 失败抛 `SpecialistError`，由 CLI/GUI 展示，不写半成品；
  · 不 import workbench（专家不反向依赖界面）。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import ValidationError

MAX_ATTEMPTS = 2


class SpecialistError(RuntimeError):
    """专家生成失败（LLM 不可用 / 输出不合法）—— 不写半成品。"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def strip_code_fence(text: str) -> str:
    """LLM 常把代码包在 ```systemverilog ... ``` 里 —— 去掉围栏再校验。"""
    raw = str(text or "").strip()
    if not raw.startswith("```"):
        return raw
    lines = raw.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def generate_json_object(
    messages: list[dict[str, str]],
    validate: Callable[[dict[str, Any]], Any],
    *,
    task_type: str,
    prompt_version: str,
    attempts: int = MAX_ATTEMPTS,
    repair_prefix: str = "上一次输出不合法",
) -> Any:
    """LLM → JSON 对象 → `validate(doc)`；失败带校验错误重试。

    `validate` 负责补字段（module/generator/anchors）并返回 pydantic 对象；
    抛出的 ValueError/ValidationError 会作为下一轮的修复提示。
    """
    from src.runtime_plane.tools.common.lib.llm_call import call_llm_messages

    feedback = ""
    last_error = ""
    for attempt in range(1, attempts + 1):
        extra = [{"role": "user", "content": feedback}] if feedback else []
        raw = call_llm_messages(
            messages + extra,
            output_schema={"type": "object"},
            prompt_version=prompt_version,
            task_type=task_type,
            output_format="json",
        )
        if not raw:
            last_error = "LLM 无输出（检查 LLM_API_KEY / 网络 / 代理）"
        else:
            try:
                doc = json.loads(raw)
                if not isinstance(doc, dict):
                    raise ValueError("顶层不是 JSON 对象")
                return validate(doc)
            except (ValueError, ValidationError) as exc:
                last_error = str(exc)[:800]
                feedback = f"{repair_prefix}：{last_error}\n请只输出修正后的 JSON 对象，不要在 JSON 外写解释。"
    raise SpecialistError(f"LLM 输出无法通过校验（{attempts} 次尝试）：{last_error}")


def write_json_artifact(
    run_dir: str | Path,
    subdir: str,
    stem: str,
    payload: dict[str, Any],
    *,
    manifest_schema: str,
    digest: str,
    counts: dict[str, Any],
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """`<run>/<subdir>/<stem>.{json,yaml}` + `manifest.json`（原子写）。"""
    import yaml

    from src.runtime_plane.core.runtime.atomic import (
        atomic_write_json,
        atomic_write_text,
    )

    out = Path(run_dir) / subdir
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / f"{stem}.json"
    atomic_write_json(json_path, payload)
    yaml_path = out / f"{stem}.yaml"
    atomic_write_text(yaml_path, yaml.safe_dump(payload, allow_unicode=True, sort_keys=False))
    manifest = {
        "schema": manifest_schema,
        "digest": digest,
        "counts": counts,
        "files": {"json": json_path.name, "yaml": yaml_path.name},
    }
    if extra:
        manifest.update(extra)
    manifest_path = out / "manifest.json"
    atomic_write_json(manifest_path, manifest)
    return {
        "dir": str(out),
        "json": str(json_path),
        "yaml": str(yaml_path),
        "manifest": str(manifest_path),
        "digest": digest,
        "counts": counts,
    }


__all__ = [
    "MAX_ATTEMPTS",
    "SpecialistError",
    "now_iso",
    "sha256_text",
    "strip_code_fence",
    "generate_json_object",
    "write_json_artifact",
]
