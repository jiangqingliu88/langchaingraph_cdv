"""`run_uvm_tests` —— 把属性取值摊平成 UVM 的 `environment.tests` 片段。

**一条 = 一个 UVM_TEST = 一个属性取值**。这是本工具与 `uvm_tools` 之间唯一的
接触面，而且是**文本契约**（一段 YAML），不是 import —— 所以这里同时钉住
「产物形状对得上」与「两边没有互相依赖」。
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from src.tools.casemodel_tools.api import (TOOL_NAMES, TOOL_UVM_TESTS, RUNNERS,
                                           run_uvm_tests)

from .conftest import FC

FC_TEXT = FC.read_text(encoding="utf-8")

#: tool_uvm 的 schema 对键名是 additionalProperties:false —— 多一个键就生成失败
ALLOWED_KEYS = {"dimension", "value", "key", "int_value", "base"}


class TestSurfaces:
    """`run_uvm_tests` 走哪几个接入面 —— 以及**不走**哪个。"""

    def test_is_human_facing_not_an_agent_tool(self):
        """它给人用（CLI `uvm-tests` / `api.run_uvm_tests`），不进 Agent 那三面。

        进 `RUNNERS` / `TOOL_NAMES` 就得在 `src/executors/verify/casemodel/` 的
        `tool_specs()` 与 langchain 包装里各补一份，否则 `build_casemodel_tools()`
        会在 `classes[name]` 上 KeyError（踩过）。所以暂不接。

        这条钉的是**当时的决定**，不是「永远不接」：哪天真接进 Agent，连同这条
        断言一起改 —— 别悄悄把名字塞进 `RUNNERS` 了事。
        """
        assert TOOL_UVM_TESTS not in RUNNERS
        assert TOOL_UVM_TESTS not in TOOL_NAMES
        # 名字本身仍是公开常量：CLI、文档、未来的适配器都用这个字符串
        assert TOOL_UVM_TESTS == "casemodel_uvm_tests"

    def test_runners_and_tool_names_stay_in_step(self):
        """适配器拿 `RUNNERS` 建三面的工具表，与 `TOOL_NAMES` 必须一一对应。

        多一个名字 → 建表时 `classes[name]` KeyError；少一个 → 工具被静默漏掉，
        而且漏得没人知道。所以这里按顺序钉死，不是比集合。
        """
        assert tuple(RUNNERS) == tuple(TOOL_NAMES)

    def test_reachable_through_the_cli(self):
        """人用的入口是 `cli uvm-tests` —— 它得真的在。"""
        from src.tools.casemodel_tools.cli import build_parser
        choices = set()
        for action in build_parser()._subparsers._group_actions:   # noqa: SLF001
            choices |= set(action.choices)
        assert "uvm-tests" in choices


def test_one_entry_per_attribute_value():
    """每个 (维度, 取值) 一条 —— 条数就是 UVM_TEST 的条数。"""
    result = run_uvm_tests(FC_TEXT, dimensions=["D_ratio"])
    assert result["count"] == 4
    assert [t["value"] for t in result["tests"]] == ["0", "10", "50", "100"]
    assert {t["key"] for t in result["tests"]} == {"d_ratio"}


def test_all_dimensions_are_covered_by_default():
    result = run_uvm_tests(FC_TEXT)
    assert set(result["dimensions_used"]) == {
        "D_length", "D_mode", "D_ratio", "D_dur", "D_if", "D_res"}
    assert result["count"] > 10


def test_dimension_filter_matches_id_name_or_key():
    by_id = run_uvm_tests(FC_TEXT, dimensions=["D_ratio"])["count"]
    by_name = run_uvm_tests(FC_TEXT, dimensions=["反压比例"])["count"]
    assert by_id == by_name == 4


def test_int_value_prefers_the_number_itself():
    """反压比例 50 的机器通道该是 50，不是「第 3 个取值」。"""
    tests = run_uvm_tests(FC_TEXT, dimensions=["D_ratio"])["tests"]
    assert [t["int_value"] for t in tests] == [0, 10, 50, 100]


def test_non_numeric_values_fall_back_to_index():
    """非数字取值（反压模式是中文枚举）用下标 —— 它只是通道值，语义由消费方定。"""
    tests = run_uvm_tests(FC_TEXT, dimensions=["D_mode"])["tests"]
    assert [t["int_value"] for t in tests] == list(range(len(tests)))


class TestShape:
    """产物形状必须正好是 tool_uvm 那个 schema 认的形状。"""

    def test_no_internal_keys_leak_into_the_payload(self):
        tests = run_uvm_tests(FC_TEXT)["tests"]
        for entry in tests:
            assert set(entry) <= ALLOWED_KEYS, f"多出了 {set(entry) - ALLOWED_KEYS}"

    def test_keys_are_ascii(self):
        """config_db 的键会进 SV 字面量，必须全 ASCII。"""
        for entry in run_uvm_tests(FC_TEXT)["tests"]:
            assert entry["key"].isascii() and re.fullmatch(
                r"[A-Za-z_][A-Za-z0-9_]*", entry["key"]), entry["key"]

    def test_tests_yaml_round_trips(self):
        result = run_uvm_tests(FC_TEXT, dimensions=["D_ratio"])
        loaded = yaml.safe_load(result["tests_yaml"])
        assert len(loaded["tests"]) == result["count"]
        assert loaded["tests"][0]["dimension"] == "D_ratio"

    def test_payload_is_paste_ready(self):
        """`tests_yaml` 就是能直接贴进 env 清单 `environment:` 下的那一段。"""
        body = run_uvm_tests(FC_TEXT, dimensions=["D_ratio"])["tests_yaml"]
        assert body.lstrip().startswith("tests:")
        assert yaml.safe_load(body)["tests"]


class TestCap:
    def test_no_cap_by_default(self):
        result = run_uvm_tests(FC_TEXT)
        assert result["truncated"] is False
        assert result["dropped"] == 0
        assert result["count"] == result["total_before_cap"]

    def test_cap_truncates_and_accounts_for_it(self):
        """截断不许静默 —— 丢了几个 test 必须说出来。"""
        result = run_uvm_tests(FC_TEXT, max_tests=4)
        assert result["count"] == 4
        assert result["truncated"] is True
        assert result["dropped"] == result["total_before_cap"] - 4
        assert result["notes"], "截断了却没有任何说明"

    def test_cap_keeps_boundary_values_first(self):
        """边界取值优先（SPCL 专项只推边界）—— 截断时先保住它们。"""
        capped = run_uvm_tests(FC_TEXT, max_tests=4)["tests"]
        assert set(t["dimension"] for t in capped) == {"D_length", "D_ratio"}

    def test_cap_is_stable(self):
        """同样的输入给同样的顺序 —— 截断结果要能 diff。"""
        first = run_uvm_tests(FC_TEXT, max_tests=6)["tests"]
        second = run_uvm_tests(FC_TEXT, max_tests=6)["tests"]
        assert first == second


def test_broken_model_returns_error_not_exception():
    assert "error" in run_uvm_tests("object: [1, 2]\ndimensions: []\n")


def test_does_not_import_uvm_tools():
    """分层守卫：本工具与 uvm_tools 之间只有**文件格式契约**，没有 import。

    真依赖上了的话，「换个 UVM 模板」会变成「改这个工具」—— 两边就锁死了。
    """
    code = (
        "import sys\n"
        "import src.tools.casemodel_tools.api\n"
        "bad = [m for m in sys.modules if m.startswith('src.tools.uvm_tools')]\n"
        "print(bad)\n"
    )
    result = subprocess.run([sys.executable, "-c", code],
                            cwd=str(Path(__file__).resolve().parents[4]),
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "[]"
