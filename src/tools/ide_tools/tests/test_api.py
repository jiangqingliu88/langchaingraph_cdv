"""`run_manual_nodes` / `validate_text` 的契约。

钉三件事：
  · 仓库里的样例（清单默认指向的数据源）必须校验通过；
  · 四类典型违规各自报得出来：缺必填 / 未知键 / 非法枚举 / 顶层非映射；
  · 失败（没路径 / 文件不在 / YAML 坏）→ `{"error"}`，不抛异常。
另外：**校验不通过不算 `error`** —— 那是正常结果，`valid: false` + issues。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.tools.ide_tools import run_manual_nodes
from src.tools.ide_tools.api import load_manual_nodes, validate_text

GOOD = """\
version: 1
project: demo
nodes:
  - id: decide_approve_refactor
    title: 重构 RTL 审批
    kind: approval
    after: decide
    action: REFACTOR_RTL
    prompt: 请审阅覆盖率缺口。
    default: reject
    timeout_s: 600
    required: true
  - id: model_review
    kind: review
    after: model
"""


def _write(tmp_path: Path, text: str) -> str:
    target = tmp_path / "manual_nodes.yaml"
    target.write_text(text, encoding="utf-8")
    return str(target)


def _rules(result) -> set:
    return {i["rule"] for i in result["issues"]}


class TestHappyPath:
    def test_valid_document(self, tmp_path):
        result = run_manual_nodes(_write(tmp_path, GOOD))
        assert result == {"valid": True, "error_count": 0,
                          "warning_count": 0, "issues": []}

    def test_validate_text_matches_file(self, tmp_path):
        assert validate_text(GOOD)["valid"] is True


class TestViolations:
    def test_missing_required_id(self):
        result = validate_text("nodes:\n  - title: 没 id\n")
        assert result["valid"] is False
        assert "missing_required" in _rules(result)

    def test_unknown_key_is_an_error(self):
        result = validate_text("nodes:\n  - {id: a, typo: 1}\n")
        assert "unknown_property" in _rules(result)

    def test_bad_enum(self):
        result = validate_text("nodes:\n  - {id: a, kind: wat}\n")
        assert "invalid_enum" in _rules(result)

    def test_bad_stage_in_after(self):
        result = validate_text("nodes:\n  - {id: a, after: not_a_stage}\n")
        assert "invalid_enum" in _rules(result)

    def test_top_level_not_a_mapping(self):
        result = validate_text("- just\n- a list\n")
        assert result["valid"] is False

    def test_nodes_missing(self):
        result = validate_text("version: 1\n")
        assert "missing_required" in _rules(result)

    def test_timeout_must_be_non_negative(self):
        result = validate_text("nodes:\n  - {id: a, timeout_s: -5}\n")
        assert result["valid"] is False

    def test_issue_carries_severity_and_target(self):
        result = validate_text("nodes:\n  - {id: a, typo: 1}\n", "x.yaml")
        issue = next(i for i in result["issues"] if i["rule"] == "unknown_property")
        assert issue["severity"] == "error"
        assert issue["target"].startswith("x.yaml::")


class TestFailureIsLoud:
    def test_empty_path(self):
        assert "error" in run_manual_nodes("")

    def test_missing_file(self):
        result = run_manual_nodes("does/not/exist.yaml")
        assert "error" in result and "找不到" in result["error"]

    def test_directory_instead_of_file(self, tmp_path):
        assert "error" in run_manual_nodes(str(tmp_path))

    def test_broken_yaml(self, tmp_path):
        result = run_manual_nodes(_write(tmp_path, "nodes: [unclosed\n"))
        assert result["valid"] is False          # YAML 坏 → 一条 yaml_parse_error
        assert "yaml_parse_error" in _rules(result)

    def test_never_raises(self):
        for bad in ("", "nope.yaml", "\x00"):
            assert isinstance(run_manual_nodes(bad), dict)


def test_shipped_example_is_valid():
    """仓库里那份样例必须过 —— 它是清单默认指向的数据源，校验门禁不能红。"""
    from src.tools.ide_tools.tests import __file__ as pkg_file
    example = Path(pkg_file).resolve().parents[4] / "config" / "ide" / "manual_nodes.yaml"
    result = run_manual_nodes(str(example))
    assert "error" not in result, result
    assert result["valid"] is True, result["issues"]


def test_schema_is_loadable_and_self_valid():
    """schema 自身要能过 check_schema 自检（SchemaChecker 构造时就会跑）。"""
    from src.tools.ide_tools.api import SCHEMA_PATH
    from src.tools.casemodel_tools.analysis.schema_check import SchemaChecker

    assert SCHEMA_PATH.exists()
    SchemaChecker(SCHEMA_PATH)                 # 构造即自检，坏了会 SystemExit


@pytest.mark.parametrize("key", ["kind", "after", "default"])
def test_enum_fields_reject_unknown_values(key):
    result = validate_text(f"nodes:\n  - {{id: a, {key}: definitely_not_valid}}\n")
    assert "invalid_enum" in _rules(result)


# ═══════════════════════════════════════════════════════════════
# 解析器 —— 让声明真正能被闭环读进去
# ═══════════════════════════════════════════════════════════════
#
# 在此之前这一层**只有校验、没有解析**：闭环（graph.py）无从读起，于是那份声明
# 一直只是一份"看起来像配置"的文档。

class TestLoadManualNodes:
    def test_it_parses_the_shipped_declaration(self):
        nodes = load_manual_nodes()
        ids = [n["id"] for n in nodes]
        assert "decide_approve_refactor" in ids
        assert "decide_approve_model" in ids

    def test_it_keeps_only_the_meaningful_keys(self, tmp_path):
        """只取 NODE_KEYS —— 解析器不能成为绕过 schema 的后门。"""
        target = tmp_path / "m.yaml"
        target.write_text(
            "version: 1\n"
            "nodes:\n"
            "  - id: a\n"
            "    after: decide\n"
            "    action: REFACTOR_RTL\n"
            "    prompt: 看一眼\n"
            "    default: reject\n"
            "    没用的键: 1\n", encoding="utf-8")
        node = load_manual_nodes(str(target))[0]
        assert node["id"] == "a" and node["action"] == "REFACTOR_RTL"
        assert "没用的键" not in node

    def test_it_fills_the_optional_defaults(self, tmp_path):
        target = tmp_path / "m.yaml"
        target.write_text("nodes:\n  - {id: a, after: decide}\n", encoding="utf-8")
        node = load_manual_nodes(str(target))[0]
        assert node["kind"] == "approval"
        assert node["default"] == "skip"       # 没写默认 → 保守：跳过
        assert node["required"] is True

    def test_entries_without_an_id_or_a_stage_are_dropped(self, tmp_path):
        """没有挂载点的节点对闭环没有意义，留着只会在匹配时制造意外。"""
        target = tmp_path / "m.yaml"
        target.write_text(
            "nodes:\n"
            "  - {after: decide}\n"
            "  - {id: b}\n"
            "  - {id: c, after: verify}\n", encoding="utf-8")
        assert [n["id"] for n in load_manual_nodes(str(target))] == ["c"]

    def test_a_missing_file_is_an_empty_declaration_not_an_error(self):
        """**坏文件等于空声明，不抛。** 否则"没人写声明"和"声明写坏了"会变成
        同一件事 —— 而它们不该是同一件事（见 graph.py 的兜底名单）。"""
        assert load_manual_nodes("/definitely/not/here.yaml") == []

    def test_a_broken_yaml_is_an_empty_declaration(self, tmp_path):
        target = tmp_path / "m.yaml"
        target.write_text("nodes: [{{{ 这不是 yaml\n", encoding="utf-8")
        assert load_manual_nodes(str(target)) == []

    def test_a_non_mapping_document_is_an_empty_declaration(self, tmp_path):
        target = tmp_path / "m.yaml"
        target.write_text("- 1\n- 2\n", encoding="utf-8")
        assert load_manual_nodes(str(target)) == []

    def test_a_null_nodes_key_is_an_empty_declaration(self, tmp_path):
        target = tmp_path / "m.yaml"
        target.write_text("version: 1\nnodes:\n", encoding="utf-8")
        assert load_manual_nodes(str(target)) == []
