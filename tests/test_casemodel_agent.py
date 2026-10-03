"""casemodel 工具的 Agent 接入面 —— 三层包装（LangChain / ToolRegistry / ToolHub）。

适配层在 `src/agents/verify/casemodel/`，工具本体在 `src/tools/casemodel_tools/`。
跨层集成测试放在仓库根的 tests/，工具自己的测试留在
`src/tools/casemodel_tools/tests/`。

最要紧的一条：三个面必须给出同一个答案 —— 否则同一个问题在
LangChain / ToolRegistry / ToolHub 上得到三种结论，排查是灾难。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.agents.verify.casemodel import (RUNNERS, TOOL_GAPS, TOOL_GENERATE,
                                         TOOL_NAMES, TOOL_VALIDATE,
                                         build_casemodel_tools,
                                         register_casemodel_tools, run_gaps,
                                         run_generate, run_validate, tool_specs)
from src.agents.verify.casemodel.registry import ensure_casemodel_tool_registry

EXAMPLES = (Path(__file__).resolve().parent.parent / "config"
            / "casemodel" / "examples")
CPU = EXAMPLES / "cpu_pipeline.yaml"
CPU_FLAWED = EXAMPLES / "cpu_pipeline_flawed.yaml"
FC = EXAMPLES / "fc_flowcontrol.yaml"
FC_REAL = EXAMPLES / "fc_real_cases.yaml"

CPU_TEXT = CPU.read_text(encoding="utf-8")
REAL_TEXT = FC_REAL.read_text(encoding="utf-8")


# ════════════════════════════════════════════════════════════
# adapters —— 三面共用的语义
# ════════════════════════════════════════════════════════════

def test_validate_reports_valid_and_problems():
    assert run_validate(CPU_TEXT)["valid"] is True
    bad = run_validate("object: X\nwidht: 1\n")
    assert bad["valid"] is False and bad["error_count"] >= 2


def test_validate_handles_empty_and_broken_yaml():
    assert run_validate("")["issues"][0]["rule"] == "empty_input"
    assert run_validate("a: [b")["issues"][0]["rule"] == "yaml_parse_error"


def test_gaps_returns_the_full_payload():
    payload = run_gaps(CPU_TEXT)
    assert payload["score"] > 0
    assert payload["org_tree"] and payload["themes"]
    assert payload["coverage"] and payload["issues"]
    assert payload["score_breakdown"]


def test_gaps_with_cases_attaches_external():
    payload = run_gaps(CPU_TEXT, cases_text=REAL_TEXT)
    # fc_real_cases 是 FlowControl 的列表 —— 对 CPU 模型来说字段全不认识
    assert payload["external"]["case_count"] == 45
    assert payload["external"]["unknown_fields"]


def test_gaps_reports_model_errors_as_error_key():
    assert "error" in run_gaps("object: [1, 2]")
    assert "error" in run_gaps("just a string")
    assert "error" in run_gaps(CPU_TEXT, cases_text="cases:\n  - {object: x}\n")


def test_generate_returns_attribute_table():
    payload = run_generate(CPU_TEXT, max_cases=5)
    assert payload["count"] == 5 and payload["truncated"]
    case = payload["cases"][0]
    assert {"case_id", "theme", "priority", "tree_path", "fields"} <= set(case)
    assert payload["driver"] == "themes"


def test_runners_registry_covers_the_tool_names():
    assert set(RUNNERS) == {TOOL_VALIDATE, TOOL_GAPS, TOOL_GENERATE}


# ════════════════════════════════════════════════════════════
# LangChain 面
# ════════════════════════════════════════════════════════════

def test_langchain_tools_return_json_strings():
    from src.agents.verify.casemodel.langchain_tools import (casemodel_gaps,
                                                                 casemodel_generate,
                                                                 casemodel_validate)
    assert json.loads(casemodel_validate(CPU_TEXT))["valid"] is True
    assert json.loads(casemodel_gaps(CPU_TEXT))["score"] > 0
    assert json.loads(casemodel_generate(CPU_TEXT, max_cases=3))["count"] == 3


def test_langchain_tool_objects_are_callable():
    """垫片保证 langchain-core 1.x 下工具对象仍可直接调用。"""
    from src.agents.verify.casemodel.langchain_tools import casemodel_validate
    assert json.loads(casemodel_validate(CPU_TEXT))["valid"] is True


def test_three_surfaces_agree():
    """同一个问题，三个面必须给同一个答案。"""
    from src.agents.verify.casemodel.langchain_tools import (casemodel_gaps,
                                                                 casemodel_generate,
                                                                 casemodel_validate)

    assert run_validate(CPU_TEXT) == json.loads(casemodel_validate(CPU_TEXT))
    assert run_gaps(CPU_TEXT)["score"] == \
        json.loads(casemodel_gaps(CPU_TEXT))["score"]
    assert run_generate(CPU_TEXT, max_cases=3)["count"] == \
        json.loads(casemodel_generate(CPU_TEXT, max_cases=3))["count"]


# ════════════════════════════════════════════════════════════
# 声明式 ToolRegistry
# ════════════════════════════════════════════════════════════

def test_declarative_registry_has_the_three_tools():
    reg = ensure_casemodel_tool_registry()
    assert set(reg._tools) == {TOOL_VALIDATE, TOOL_GAPS, TOOL_GENERATE}
    gaps = reg._tools[TOOL_GAPS]
    assert gaps.input_schema["required"] == ["yaml_text"]
    assert "cases_text" in gaps.input_schema["properties"]
    for tool in reg._tools.values():
        assert tool.risk_level == "safe"          # 声明式 registry 里是裸字符串


def test_declarative_registry_is_a_singleton():
    assert ensure_casemodel_tool_registry() is ensure_casemodel_tool_registry()


def test_agent_tools_registry_includes_casemodel():
    from src.layers.l2_orchestration.agents.agent_tools import register_all_tools
    reg = register_all_tools()
    assert {TOOL_VALIDATE, TOOL_GAPS, TOOL_GENERATE} <= set(reg._tools)


# ════════════════════════════════════════════════════════════
# ToolHub 的 ITool
# ════════════════════════════════════════════════════════════

def test_itool_manifests_are_valid_and_safe():
    tools = build_casemodel_tools()
    assert len(tools) == 3
    for tool in tools:
        manifest = tool.manifest
        assert manifest.validate() == []
        assert manifest.risk_level.value == "safe"
        assert manifest.category == "coverage"
        # LLM function.name 不能带点号或空格
        name = manifest.to_llm_function_spec()["function"]["name"]
        assert name.isidentifier()


def test_tool_specs_have_one_source_of_truth():
    specs = tool_specs()
    assert [s[0] for s in specs] == [TOOL_VALIDATE, TOOL_GAPS, TOOL_GENERATE]
    reg = ensure_casemodel_tool_registry()
    for name, desc, schema, risk in specs:
        assert reg._tools[name].description == desc
        assert reg._tools[name].input_schema == schema


@pytest.fixture(scope="module")
def hub():
    from src.layers.l2_orchestration.communication.tool_hub import ToolHub
    instance = ToolHub.get_instance()
    register_casemodel_tools(instance)
    return instance


def test_hub_registers_three_tools(hub):
    assert {"casemodel_validate", "casemodel_gaps", "casemodel_generate"} <= \
        set(hub._manifests)
    assert set(hub._by_category["coverage"]) >= {
        "casemodel_validate", "casemodel_gaps", "casemodel_generate"}


def test_hub_invoke_happy_path(hub):
    import asyncio
    result = asyncio.run(hub.invoke(TOOL_GAPS, {"yaml_text": CPU_TEXT}, None))
    assert result.success and result.data["score"] > 0
    # 纯确定性工具：无外部验证者（ADR-3 的凭证约定）
    assert result.verified_by == "none"


def test_hub_fails_on_unparseable_model(hub):
    """模型都建不出来时报 success=True 会让上游以为分析跑通了。"""
    import asyncio
    result = asyncio.run(hub.invoke(TOOL_GAPS, {"yaml_text": "not: a model"}, None))
    assert result.success is False and "object" in (result.error or "")


def test_hub_validate_invalid_is_still_success(hub):
    """validate 的「不合法」是校验结论，不是执行失败。"""
    import asyncio
    result = asyncio.run(hub.invoke(
        TOOL_VALIDATE, {"yaml_text": "object: X\ndimensions: []"}, None))
    assert result.success is True and result.data["valid"] is False


def test_hub_rejects_bad_arguments(hub):
    import asyncio
    result = asyncio.run(hub.invoke(TOOL_GAPS, {"wrong": 1}, None))
    assert result.success is False


def test_hub_generate_respects_max_cases(hub):
    import asyncio
    result = asyncio.run(hub.invoke(
        TOOL_GENERATE, {"yaml_text": CPU_TEXT, "max_cases": 2}, None))
    assert result.success and result.data["count"] == 2

