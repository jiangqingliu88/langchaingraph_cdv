"""Formal 专家 —— 从 spec 生成形式化验证计划（独立路径）。

**边界**：只生成 Formal IR（性质/假设/证明义务/引擎需求），不假装跑过形式
引擎。`engine.ran=false` 是默认值；将来接入真实引擎时由引擎侧改写并给证据。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

from src.agent_plane.specialists.common import (
    SpecialistError,
    generate_json_object,
    now_iso,
    sha256_text,
    write_json_artifact,
)
from src.ir_plane.formal import FormalPlan

logger = structlog.get_logger()

PROMPT_VERSION = "formal_plan_v1"
MAX_SPEC_CHARS = 60_000


def _system_prompt(module: str) -> str:
    return f"""你是形式化验证架构师。阅读设计规格，输出该模块的 Formal IR JSON。

只输出一个 JSON 对象，字段：
  · module：{module}
  · clock / reset：时钟与复位信号名
  · properties：性质列表，每项 {{id, name, kind, expression, description}}
      - kind=assert：设计必须恒成立
      - kind=assume：环境/输入约束（形式化假设）
      - kind=cover：可达性/覆盖目标
      - expression 用 SVA 形式（如 `req |-> ##[1:4] ack`）
  · proof_obligations：证明义务列表，每项 {{id, property_ids, status, engine}}
      - **status 默认写 "not_run"**，不要假装已经证明
  · engine_requirements：需要哪些引擎能力（如 k-induction / BMC depth）
  · coverage_goals / notes：字符串列表

规则：
  1. 只依据规格里出现的接口与行为；拿不准的写进 notes，不要编造性质；
  2. 每条性质要短、可判定；assume 与 assert 分开；
  3. id 在整份 IR 内唯一（P1/PO1…）。
"""


def _messages(module: str, spec_text: str) -> List[Dict[str, str]]:
    return [
        {"role": "system", "content": _system_prompt(module)},
        {"role": "user", "content": spec_text[:MAX_SPEC_CHARS]},
    ]


def generate_formal_plan(spec_text: str, *, module: str,
                         spec_path: str = "",
                         output_dir: Optional[Path] = None) -> FormalPlan:
    if not str(module or "").strip():
        raise SpecialistError("module 不能为空")
    if not str(spec_text or "").strip():
        raise SpecialistError("spec 文本为空，无法生成 Formal IR")

    def validate(doc: Dict[str, Any]) -> FormalPlan:
        doc["module"] = module
        doc.setdefault("generated_at", now_iso())
        doc["generator"] = {"prompt_version": PROMPT_VERSION}
        anchors = list(doc.get("source_anchors") or [])
        if spec_path:
            anchors.insert(0, {
                "kind": "spec",
                "path": str(spec_path).replace("\\", "/"),
                "sha256": sha256_text(spec_text),
            })
        doc["source_anchors"] = anchors
        # 没有引擎就如实写清楚 —— 计划存在 ≠ 已经证明。
        doc.setdefault("engine", {"ran": False,
                                  "reason": "no formal engine configured"})
        plan = FormalPlan.model_validate(doc)
        logger.info(f"Formal IR：{module} · {plan.counts()}")
        return plan

    return generate_json_object(
        _messages(module, spec_text), validate,
        task_type="formal_plan", prompt_version=PROMPT_VERSION)


async def arun(spec_text: str, output_dir: str | Path, *, module: str = "",
               spec_path: str = "") -> Dict[str, Any]:
    from .graph import build_formal_graph

    final = await build_formal_graph().ainvoke({
        "spec_text": spec_text,
        "output_dir": str(output_dir),
        "module": module,
        "spec_path": spec_path,
    })
    return final["result"]


def run(spec_text: str, output_dir: str | Path, *, module: str = "",
        spec_path: str = "") -> Dict[str, Any]:
    import asyncio

    return asyncio.run(arun(spec_text, output_dir, module=module,
                            spec_path=spec_path))


def store_formal_plan(output_dir: str | Path, plan: FormalPlan) -> Dict[str, Any]:
    files = write_json_artifact(
        output_dir, "formal", "formal_plan", plan.model_dump(mode="json"),
        manifest_schema="formal_plan_manifest_v1",
        digest=plan.digest(), counts=plan.counts(),
        extra={"module": plan.module, "engine": plan.engine},
    )
    return files


__all__ = ["PROMPT_VERSION", "generate_formal_plan", "store_formal_plan",
           "arun", "run", "SpecialistError"]
