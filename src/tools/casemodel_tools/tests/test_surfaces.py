"""三个接入面 + 两个 CLI 入口。

最要紧的一条：三个面必须给出同一个答案 —— 否则同一个问题在
LangChain / ToolRegistry / ToolHub 上得到三种结论，排查是灾难。
"""
from __future__ import annotations

import json

import pytest
import yaml
from click.testing import CliRunner

from src.tools.casemodel_tools.agent import (RUNNERS, TOOL_GAPS, TOOL_GENERATE,
                                             TOOL_VALIDATE)
from src.tools.casemodel_tools.agent.adapters import (run_gaps, run_generate,
                                                      run_validate)
from src.tools.casemodel_tools.agent.registry import (build_casemodel_tools,
                                                       ensure_casemodel_tool_registry,
                                                       register_casemodel_tools,
                                                       tool_specs)
from src.tools.casemodel_tools.cli import main as cli_main

from .conftest import CPU, CPU_FLAWED, FC, FC_REAL

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
    from src.tools.casemodel_tools.agent.langchain_tools import (casemodel_gaps,
                                                                 casemodel_generate,
                                                                 casemodel_validate)
    assert json.loads(casemodel_validate(CPU_TEXT))["valid"] is True
    assert json.loads(casemodel_gaps(CPU_TEXT))["score"] > 0
    assert json.loads(casemodel_generate(CPU_TEXT, max_cases=3))["count"] == 3


def test_langchain_tool_objects_are_callable():
    """垫片保证 langchain-core 1.x 下工具对象仍可直接调用。"""
    from src.tools.casemodel_tools.agent.langchain_tools import casemodel_validate
    assert json.loads(casemodel_validate(CPU_TEXT))["valid"] is True


def test_three_surfaces_agree():
    """同一个问题，三个面必须给同一个答案。"""
    from src.tools.casemodel_tools.agent.langchain_tools import (casemodel_gaps,
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


# ════════════════════════════════════════════════════════════
# 独立 CLI（cli.py）
# ════════════════════════════════════════════════════════════

def test_cli_help_lists_every_subcommand():
    with pytest.raises(SystemExit) as exc:
        cli_main(["--help"])
    assert exc.value.code == 0


def test_cli_check_exit_codes():
    assert cli_main(["check", str(CPU)]) == 0
    assert cli_main(["check", str(CPU_FLAWED)]) == 0     # 语法合法，语义有问题


def test_cli_check_directory(capsys):
    from .conftest import EXAMPLES
    assert cli_main(["check", str(EXAMPLES), "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    by_name = {p["file"].split("\\")[-1].split("/")[-1]: p for p in payload}
    assert by_name["cpu_pipeline.yaml"]["valid"] is True
    assert by_name["fc_real_cases.yaml"]["valid"] is False   # 它是 case 列表


def test_cli_analyze_exit_code_reflects_errors():
    assert cli_main(["analyze", str(CPU)]) == 0
    assert cli_main(["analyze", str(CPU_FLAWED)]) == 1


def test_cli_analyze_json_payload(capsys):
    cli_main(["analyze", str(CPU), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["summary"]["case_count"] > 0
    assert payload["themes"] and payload["org_tree"]
    assert payload["score_total"] > 0
    assert "external" not in payload            # 没给 --cases


def test_cli_analyze_with_cases_and_report(tmp_path, capsys):
    report = tmp_path / "r.txt"
    assert cli_main(["analyze", str(FC), "--cases", str(FC_REAL),
                     "--report", str(report)]) == 1
    out = capsys.readouterr().out
    assert "真实 case 核对" in out and "评分必须只是模型的属性" in out
    assert "真实 case 核对" in report.read_text(encoding="utf-8")


def test_cli_analyze_with_cases_json(capsys):
    cli_main(["analyze", str(FC), "--cases", str(FC_REAL), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["external"]["case_count"] == 45


def test_cli_tree_and_matrix(capsys):
    assert cli_main(["tree", str(CPU)]) == 0
    assert "功能组织树" in capsys.readouterr().out
    assert cli_main(["matrix", str(CPU)]) == 0
    assert "维度交叉矩阵" in capsys.readouterr().out


def test_cli_rules(capsys):
    assert cli_main(["rules"]) == 0
    assert "校验规则" in capsys.readouterr().out
    assert cli_main(["rules", "--json"]) == 0
    assert len(json.loads(capsys.readouterr().out)) >= 45


@pytest.mark.parametrize("fmt", ["yaml", "json", "csv", "table"])
def test_cli_generate_formats(capsys, fmt):
    assert cli_main(["generate", str(CPU), "--format", fmt,
                     "--max-cases", "3"]) == 0
    assert capsys.readouterr().out.strip()


def test_cli_generate_writes_file_and_reports_notes(tmp_path, capsys):
    out = tmp_path / "cases.yaml"
    assert cli_main(["generate", str(CPU), "--format", "yaml",
                     "--out", str(out), "--max-cases", "4"]) == 0
    assert "已写出" in capsys.readouterr().out
    assert len(yaml.safe_load(out.read_text(encoding="utf-8"))["cases"]) == 4


def test_cli_seed_override(capsys):
    cli_main(["generate", str(CPU), "--format", "json", "--seed", "9"])
    assert json.loads(capsys.readouterr().out)["seed"] == 9


def test_cli_missing_file_is_exit_2(tmp_path):
    assert cli_main(["analyze", str(tmp_path / "nope.yaml")]) == 2


def test_cli_rejects_broken_yaml(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("- not\n- a\n- mapping\n", encoding="utf-8")
    assert cli_main(["analyze", str(bad)]) == 2


# ════════════════════════════════════════════════════════════
# vagent case-model（主 CLI）
# ════════════════════════════════════════════════════════════

def vagent(args):
    from src.cli.commands import cli
    return CliRunner().invoke(cli, args, catch_exceptions=False)


def test_vagent_group_has_all_subcommands():
    res = vagent(["case-model", "--help"])
    assert res.exit_code == 0
    for sub in ("check", "analyze", "generate", "gui", "tree", "rules"):
        assert sub in res.output


def test_vagent_check_and_analyze_exit_codes():
    assert vagent(["case-model", "check", str(CPU)]).exit_code == 0
    assert vagent(["case-model", "analyze", str(CPU)]).exit_code == 0
    assert vagent(["case-model", "analyze", str(CPU_FLAWED)]).exit_code == 1


def test_vagent_analyze_with_cases(tmp_path):
    report = tmp_path / "r.txt"
    res = vagent(["case-model", "analyze", str(FC), "--cases", str(FC_REAL),
                  "--report", str(report)])
    assert res.exit_code == 1                   # 真实 case 有 error
    assert "真实 case 核对" in res.output
    assert report.exists()


def test_vagent_analyze_json_has_external():
    res = vagent(["case-model", "analyze", str(FC), "--cases", str(FC_REAL),
                  "--json"])
    payload = json.loads(res.output)
    assert payload["external"]["case_count"] == 45


def test_vagent_tree_and_rules():
    assert "功能组织树" in vagent(["case-model", "tree", str(CPU)]).output
    assert "校验规则" in vagent(["case-model", "rules"]).output


def test_vagent_generate_to_file(tmp_path):
    out = tmp_path / "c.yaml"
    res = vagent(["case-model", "generate", str(CPU), "-f", "yaml",
                  "-o", str(out), "--max-cases", "3"])
    assert res.exit_code == 0
    assert len(yaml.safe_load(out.read_text(encoding="utf-8"))["cases"]) == 3


def test_vagent_generate_table_to_stdout():
    res = vagent(["case-model", "generate", str(CPU), "--max-cases", "2"])
    assert res.exit_code == 0 and "case 属性表" in res.output
