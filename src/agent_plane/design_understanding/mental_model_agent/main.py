"""Mental 专家 —— 从 spec 生成「心智模型 IR」（独立 CLI/服务路径）。

这一版**不进 supervisor 闭环**：先作为可独立运行的专家，把「理解」沉淀成可
审阅的 Mental IR；稳定后再考虑挂到 verify 之前。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog
from pydantic import ValidationError

from src.mental_ir_plane import MentalIR, SourceAnchor

logger = structlog.get_logger()

PROMPT_VERSION = "mental_ir_v1"
MAX_SPEC_CHARS = 60_000
MAX_ATTEMPTS = 2


class MentalIRError(RuntimeError):
    """生成 Mental IR 失败（LLM 不可用 / 输出不合法）—— 不写半成品。"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _system_prompt(module: str) -> str:
    return f"""你是 IC 验证架构师。阅读设计规格，输出该模块的「心智模型 IR」JSON。

目标不是复述规格，而是把**理解**摊开，供人审阅、供后续验证使用：
  · goals：设计必须被证明成立的核心验证目标（id=G1/G2…，priority=P0..P3）；
  · assumptions：继续验证所依赖、但规格没有显式保证的前提（id=A1…）；
  · ambiguities：规格没写清、会影响验证策略的问题（id=Q1…；
    blocking=true 表示必须先澄清才能继续）；
  · verification_intents：可执行的验证意图（id=VI1…），写清它证明哪些
    goal_ids、期望什么证据（evidence_expected）；
  · risks：设计/验证风险（id=R1…，severity=low/medium/high + mitigation）。

规则：
  1. 只写规格支持的内容；拿不准的放进 ambiguities，不要编成 goals；
  2. 每条都要简短、可判定，不要写泛泛而谈的套话；
  3. id 在整份 IR 内唯一；
  4. 只输出一个 JSON 对象，字段：
     module, goals, assumptions, ambiguities, verification_intents, risks, notes
模块名：{module}
"""


def _messages(module: str, spec_text: str, feedback: str = "") -> list[dict[str, str]]:
    msgs = [
        {"role": "system", "content": _system_prompt(module)},
        {"role": "user", "content": spec_text[:MAX_SPEC_CHARS]},
    ]
    if feedback:
        msgs.append({"role": "user", "content": feedback})
    return msgs


def _artifact_anchors(output_dir: Path) -> list[SourceAnchor]:
    """已有 case_ir / testpoints 时记锚点 —— 引用的是哪一版输入要能回答。"""
    anchors: list[SourceAnchor] = []
    for kind, rel in (("case_ir", "coverage/case_ir.json"), ("testpoints", "coverage/testpoints.json")):
        path = output_dir / rel
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        anchors.append(SourceAnchor(kind=kind, path=rel, sha256=_sha256(text)))
    return anchors


def generate_mental_ir(spec_text: str, *, module: str, spec_path: str = "", output_dir: Path | None = None) -> MentalIR:
    """调一次（必要时带修复反馈再调一次）LLM，返回已校验的 Mental IR。"""
    if not str(module or "").strip():
        raise MentalIRError("module 不能为空")
    if not str(spec_text or "").strip():
        raise MentalIRError("spec 文本为空，无法生成 Mental IR")

    from src.runtime_plane.tools.common.lib.llm_call import call_llm_messages

    feedback = ""
    last_error = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        raw = call_llm_messages(
            _messages(module, spec_text, feedback),
            output_schema={"type": "object"},
            prompt_version=PROMPT_VERSION,
            task_type="mental_ir",
            output_format="json",
        )
        if not raw:
            last_error = "LLM 无输出（检查 LLM_API_KEY / 网络 / 代理）"
        else:
            try:
                doc = json.loads(raw)
                if not isinstance(doc, dict):
                    raise ValueError("顶层不是 JSON 对象")
                doc["module"] = module
                doc.setdefault("generated_at", _now())
                doc["generator"] = {
                    "prompt_version": PROMPT_VERSION,
                    "attempt": attempt,
                }
                anchors: list[dict[str, Any]] = list(doc.get("source_anchors") or [])
                if spec_path:
                    anchors.insert(
                        0,
                        {
                            "kind": "spec",
                            "path": str(spec_path).replace("\\", "/"),
                            "sha256": _sha256(spec_text),
                        },
                    )
                if output_dir is not None:
                    anchors.extend(a.model_dump() for a in _artifact_anchors(Path(output_dir)))
                doc["source_anchors"] = anchors
                ir = MentalIR.model_validate(doc)
                logger.info(f"Mental IR：{module} · {ir.counts()}")
                return ir
            except (ValueError, ValidationError) as exc:
                last_error = str(exc)[:800]
                feedback = f"上一次输出不合法：{last_error}\n请只输出修正后的 JSON 对象，不要在 JSON 外写解释。"
        logger.warning(f"Mental IR 生成失败（attempt {attempt}/{MAX_ATTEMPTS}）: {last_error[:200]}")
    raise MentalIRError(f"无法生成 Mental IR（{MAX_ATTEMPTS} 次尝试）：{last_error}")


async def arun(spec_text: str, output_dir: str | Path, *, module: str = "", spec_path: str = "") -> dict[str, Any]:
    """异步入口：走 mental 子图（generate → store）。"""
    from .graph import build_mental_graph

    graph = build_mental_graph()
    final = await graph.ainvoke(
        {
            "spec_text": spec_text,
            "output_dir": str(output_dir),
            "module": module,
            "spec_path": spec_path,
        }
    )
    return final["result"]


def run(spec_text: str, output_dir: str | Path, *, module: str = "", spec_path: str = "") -> dict[str, Any]:
    """同步入口（CLI/服务用）。"""
    import asyncio

    return asyncio.run(arun(spec_text, output_dir, module=module, spec_path=spec_path))


__all__ = ["MentalIRError", "PROMPT_VERSION", "generate_mental_ir", "arun", "run"]
