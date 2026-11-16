"""Mental IR：模型/落盘/专家生成/CLI 的回归测试。

外部依赖（LLM）全部打桩，不联网；测的是"校验 + 落盘 + 不写半成品"。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from src.mental_ir_plane import (
    MentalIR,
    mental_ir_path,
    read_mental_ir,
    write_mental_ir,
)

FIXTURE = {
    "goals": [
        {"id": "G1", "statement": "调度器按优先级分发指令", "priority": "P0", "source_refs": ["spec:3.1"]},
    ],
    "assumptions": [
        {"id": "A1", "statement": "SPAD 容量是固定值", "rationale": "spec 未给动态配置", "risk_if_wrong": "覆盖点缺失"},
    ],
    "ambiguities": [
        {
            "id": "Q1",
            "question": "低功耗模式下是否仍响应中断？",
            "why_it_matters": "影响激励与断言",
            "blocking": True,
            "needs_human": True,
        },
    ],
    "verification_intents": [
        {"id": "VI1", "statement": "对高优先级指令做抢占检查", "goal_ids": ["G1"], "evidence_expected": ["SCB", "SVA"]},
    ],
    "risks": [
        {"id": "R1", "description": "优先级反转", "severity": "high", "mitigation": "定向激励"},
    ],
    "notes": ["示例 fixture，不代表真实设计"],
}


def _ir(**over):
    doc = {
        "module": "npu_sched",
        "generated_at": "2026-01-01T00:00:00+00:00",
        "generator": {"prompt_version": "mental_ir_v1"},
        **FIXTURE,
    }
    doc.update(over)
    return MentalIR.model_validate(doc)


def test_model_rejects_duplicate_ids():
    doc = {"module": "m", **FIXTURE, "goals": [*FIXTURE["goals"], {"id": "G1", "statement": "dup"}]}
    with pytest.raises(Exception):
        MentalIR.model_validate(doc)


def test_digest_ignores_timestamp_and_generator():
    a = _ir(generated_at="2026-01-01T00:00:00+00:00", generator={"prompt_version": "v1", "attempt": 1})
    b = _ir(generated_at="2026-02-02T00:00:00+00:00", generator={"prompt_version": "v2", "attempt": 2})
    assert a.digest() == b.digest()
    assert len(a.digest()) == 64


def test_model_accepts_llm_style_aliases():
    """LLM 常见的换名/标量写法要被宽容接住，而不是整份重试。

    实测 deepseek 第一版把 `question` 写成 `statement`、`evidence_expected`
    写成一句话、severity 写成中文 —— 这些都不该让整份 IR 作废。
    """
    ir = MentalIR.model_validate(
        {
            "module": "m",
            "goals": [{"id": "G1", "description": "目标", "priority": "high"}],
            "assumptions": [{"id": "A1", "assumption": "前提"}],
            "ambiguities": [{"id": "Q1", "statement": "没写清？", "blocking": "是"}],
            "verification_intents": [{"id": "VI1", "description": "意图", "goals": "G1", "evidence": "SCB；SVA"}],
            "risks": [{"id": "R1", "risk": "风险", "severity": "高", "mitigation": "加激励"}],
        }
    )
    assert ir.goals[0].priority == "P0"
    assert ir.ambiguities[0].blocking is True
    assert ir.verification_intents[0].goal_ids == ["G1"]
    assert ir.verification_intents[0].evidence_expected == ["SCB", "SVA"]
    assert ir.risks[0].severity == "high"


def test_store_round_trip(tmp_path):
    ir = _ir()
    files = write_mental_ir(tmp_path, ir)
    assert Path(files["json"]).is_file()
    assert Path(files["yaml"]).is_file()
    assert Path(files["manifest"]).is_file()
    back = read_mental_ir(tmp_path)
    assert back is not None and back.digest() == ir.digest()
    manifest = json.loads(Path(files["manifest"]).read_text(encoding="utf-8"))
    assert manifest["digest"] == ir.digest()
    assert manifest["counts"]["blocking_ambiguities"] == 1
    assert mental_ir_path(tmp_path).is_file()


def test_generate_validates_and_writes(tmp_path, monkeypatch):
    from src.agent_plane.design_understanding.mental_model_agent import main as mental

    monkeypatch.setattr(
        "src.runtime_plane.tools.common.lib.llm_call.call_llm_messages",
        lambda *a, **k: json.dumps(FIXTURE),
        raising=True,
    )
    ir = mental.generate_mental_ir(
        "module: npu_sched\n...", module="npu_sched", spec_path="spec.md", output_dir=tmp_path
    )
    assert ir.module == "npu_sched"
    assert ir.source_anchors[0].kind == "spec"
    assert len(ir.source_anchors[0].sha256) == 64
    result = mental.run("module: npu_sched\n...", tmp_path, module="npu_sched", spec_path="spec.md")
    assert result["status"] == "ok"
    assert result["counts"]["goals"] == 1
    assert (tmp_path / "mental_ir" / "mental_ir.json").is_file()


def test_generate_does_not_write_on_llm_failure(tmp_path, monkeypatch):
    from src.agent_plane.design_understanding.mental_model_agent import main as mental

    monkeypatch.setattr(
        "src.runtime_plane.tools.common.lib.llm_call.call_llm_messages", lambda *a, **k: "", raising=True
    )
    with pytest.raises(mental.MentalIRError):
        mental.run("module: m", tmp_path, module="m")
    assert not (tmp_path / "mental_ir").exists()


def test_cli_build(tmp_path, monkeypatch):
    from src.workbench.cli.commands import cli

    monkeypatch.setattr(
        "src.runtime_plane.tools.common.lib.llm_call.call_llm_messages",
        lambda *a, **k: json.dumps(FIXTURE),
        raising=True,
    )
    spec = tmp_path / "npu_sched.md"
    spec.write_text("module: npu_sched\n", encoding="utf-8")
    out = tmp_path / "run"
    result = CliRunner().invoke(cli, ["mental", "build", str(spec), "-o", str(out), "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["module"] == "npu_sched"
    assert (out / "mental_ir" / "mental_ir.json").is_file()
