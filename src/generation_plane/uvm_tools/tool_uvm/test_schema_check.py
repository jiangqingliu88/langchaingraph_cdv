"""SchemaChecker 测试（Phase B 约定：每条规则至少一个测试）

正向以 examples/ 下 5 个示例文件为契约（必须零误报，锁定旧别名面）；
负向用 YAML round-trip（safe_load → 改 → safe_dump 到 tmp_path）逐规则构造。
"""
import json
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "src").is_dir())))
from jsonschema import Draft202012Validator
from src.generation_plane.uvm_tools.tool_uvm.schema_check import (
    SCHEMA_PATH,
    SchemaChecker,
    main,
)

EXAMPLES = Path(__file__).parent / "examples" / "apb"   # APB 示例（schema 契约基准）
EXAMPLES_ROOT = Path(__file__).parent / "examples"      # 全部示例（apb + cmdsched）

checker = SchemaChecker()


def _write(tmp_path, name, doc):
    """dict → YAML 文件（round-trip 模式，同 test_semantic_check.py）。"""
    path = tmp_path / name
    path.write_text(
        yaml.safe_dump(doc, allow_unicode=True, sort_keys=False),
        encoding="utf-8")
    return path


def _check(doc, tmp_path, name="doc.yaml"):
    return checker.check([_write(tmp_path, name, doc)])


def _errors(issues):
    return [i for i in issues if i.severity == "error"]


def _warnings(issues):
    return [i for i in issues if i.severity == "warning"]


# ── 正向：示例文件即契约 ──

@pytest.mark.parametrize(
    "rel", [str(p.relative_to(EXAMPLES_ROOT)) for p in sorted(EXAMPLES_ROOT.rglob("*.yaml"))])
def test_examples_pass_clean(rel):
    assert checker.check([EXAMPLES_ROOT / rel]) == []


def test_all_examples_together_clean():
    assert checker.check([EXAMPLES_ROOT]) == []


def test_legacy_aliases_accepted(tmp_path):
    docs = {
        # interface 单数顶层键 + agent_name/interface_name/clk 别名
        "a1.yaml": {"interface": [{"agent_name": "A", "interface_name": "A_if",
                                   "clk": "clk", "ports": [
                                       {"name": "p", "dir": "output"}]}]},
        # agents dict-of-dict / dict-of-string 两种旧格式（env_name 已下线，改用 name）
        "a2.yaml": {"environment": {"name": "E",
                                    "agents": {"m": {"interface": "A"},
                                               "s": "A_if"}}},
        # bench_name 别名 + clk_rst 裸字符串列表
        "a3.yaml": {"bench": {"bench_name": "B", "clk_rst": {"clocks": ["clk"],
                                                            "resets": ["rst"]}}},
        # constraint list 格式 transaction_constraints + config 自由透传
        "a4.yaml": {"interfaces": [{"name": "A",
                                    "transaction_constraints": [
                                        {"name": "c1", "value": "{}"}],
                                    "config": {"priority": 3}}]},
        # env 级 agents[].is_active（标量 / active 别名）仍是合法输入
        "a5.yaml": {"environment": {"name": "E",
                                    "agents": [{"name": "m", "is_active": True},
                                               {"name": "s", "active": False}]}},
        # harness connect.path 旧别名 + count 字符串（参数名）
        "a6.yaml": {"harness": {"name": "h",
                                "connect": {"path": "tb.h"},
                                "interfaces": [{"name": "i", "type": "if_t",
                                                "count": "NUM_CLIENTS"}]}},
        # env 级 clk_rst 旧别名（缺 enabled）
        "a7.yaml": {"environment": {"name": "E",
                                    "clk_rst": {"clocks": [{"name": "clk"}]}}},
    }
    for name, doc in docs.items():
        assert checker.check([_write(tmp_path, name, doc)]) == [], name


# ── 负向：每类规则一条 ──

def test_interface_missing_name_error(tmp_path):
    issues = _check({"interfaces": [{"ports": []}]}, tmp_path)
    errs = _errors(issues)
    assert len(errs) == 1 and errs[0].rule == "missing_required"
    assert "name" in errs[0].message and "agent_name" in errs[0].message


def test_interface_is_active_now_unknown_key(tmp_path):
    """interface 级 is_active 已下线：unknown key → error，不再静默生效。"""
    issues = _check({"interfaces": [{"name": "A", "is_active": True}]}, tmp_path)
    errs = _errors(issues)
    assert len(errs) == 1 and errs[0].rule == "unknown_property"
    assert errs[0].target.endswith("interfaces[0].is_active")


def test_interface_config_is_active_rejected(tmp_path):
    """旧读取路径 config.is_active 显式报错（而非静默忽略）；其余 config 键仍自由透传。"""
    issues = _check({"interfaces": [{"name": "A", "config": {"is_active": True}}]}, tmp_path)
    errs = _errors(issues)
    assert len(errs) == 1 and errs[0].rule == "removed_field"
    assert errs[0].target.endswith("interfaces[0].config")
    assert _check({"interfaces": [{"name": "A", "config": {"priority": 3}}]}, tmp_path) == []


def test_port_dir_enum_error(tmp_path):
    issues = _check({"interfaces": [{"name": "A", "ports": [
        {"name": "p", "dir": "inout"}]}]}, tmp_path)
    errs = _errors(issues)
    assert len(errs) == 1 and errs[0].rule == "invalid_enum"
    assert "ports[0].dir" in errs[0].target


def test_ports_not_list_type_error(tmp_path):
    issues = _check({"interfaces": [{"name": "A", "ports": {
        "name": "p", "dir": "output"}}]}, tmp_path)
    errs = _errors(issues)
    assert any(e.rule == "type_mismatch" for e in errs)


def test_typo_key_error(tmp_path):
    issues = _check({"interfaces": [{"name": "A",
                                     "reset_active_loww": True}]}, tmp_path)
    errs = _errors(issues)
    assert len(errs) == 1 and errs[0].rule == "unknown_property"
    assert "reset_active_loww" in errs[0].target
    assert _warnings(issues) == []
    # 未知键 → error，main 返回 1（拼错键不再静默通过）
    assert main([str(_write(tmp_path, "typo_only.yaml",
                            {"interfaces": [{"name": "A",
                                             "reset_active_loww": True}]})),
                 "-q"]) == 1


def test_env_agent_missing_name_and_type_error(tmp_path):
    issues = _check({"environment": {"name": "E",
                                     "agents": [{"interface": "apb"}]}},
                    tmp_path)
    errs = _errors(issues)
    assert len(errs) == 1 and errs[0].rule == "missing_required"


def test_env_harness_connect_missing_path_error(tmp_path):
    issues = _check({"environment": {"name": "E",
                                     "harness_connect": {"env_suffix": ".x"}}},
                    tmp_path)
    errs = _errors(issues)
    assert len(errs) == 1 and errs[0].rule == "missing_required"
    assert "path" in errs[0].message


def test_bench_harness_interface_missing_type_error(tmp_path):
    # 对应 _normalize_harness 静默丢弃场景（gen_uvm.py:730）
    issues = _check({"bench": {"name": "B", "harness": {"name": "h", "interfaces": [
        {"name": "apb_if"}]}}}, tmp_path)
    errs = _errors(issues)
    assert len(errs) == 1 and errs[0].rule == "missing_required"
    assert "type" in errs[0].message


def test_bench_clk_rst_bad_type_error(tmp_path):
    issues = _check({"bench": {"name": "B",
                               "clk_rst": {"clocks": "pclk"}}}, tmp_path)
    errs = _errors(issues)
    assert len(errs) == 1 and errs[0].rule == "type_mismatch"
    assert "clk_rst.clocks" in errs[0].target


def test_util_component_missing_name_error(tmp_path):
    issues = _check({"util_components": [{"type": "uvm_component"}]}, tmp_path)
    errs = _errors(issues)
    assert len(errs) == 1 and errs[0].rule == "missing_required"


def test_env_name_rejected_everywhere(tmp_path):
    """env_name 已从 schema 全部下线（env / bench / constraint 三处）。"""
    for i, doc in enumerate((
            {"environment": {"name": "E", "env_name": "E"}},
            {"bench": {"name": "B", "env_name": "E"}},
            {"constraint": {"name": "c", "env_name": "E"}})):
        issues = _check(doc, tmp_path, name=f"en{i}.yaml")
        errs = _errors(issues)
        assert errs, f"env_name 未被拒: {doc}"
        assert any("env_name" in e.target for e in errs), doc


def test_bench_without_env_name_ok(tmp_path):
    """bench 不写 env_name 合法：env 名由本次解析出的 environment 回填。"""
    issues = _check({"bench": {"name": "B", "dut_instance": "u_dut"}},
                    tmp_path, name="nb.yaml")
    assert not _errors(issues)


def test_scoreboard_generative_keys_rejected(tmp_path):
    """生成式计分板已下线：mode/expected_from/actual_from 等键应被拒（不再是静默接受）。"""
    issues = _check({"environment": {"name": "E", "scoreboards": [
        {"name": "scb_gen", "mode": "inorder", "expected_from": "pred",
         "actual_from": "slave", "key_field": "req_id"}]}}, tmp_path)
    errs = _errors(issues)
    assert errs and all(e.rule == "unknown_property" for e in errs)
    for key in ("mode", "expected_from", "actual_from", "key_field"):
        assert any(key in e.target for e in errs), f"{key} 未被拒"


def test_scoreboard_sb_type_accepted(tmp_path):
    """sb_type 接法是唯一保留的写法。"""
    issues = _check({"environment": {"name": "E", "scoreboards": [
        {"name": "apb_scb", "sb_type": "in_order_scoreboard",
         "trans_type": "apb_master_seq_item"}]}}, tmp_path)
    assert not _errors(issues)


def test_combinator_bad_enum_error(tmp_path):
    issues = _check({"constraint": {"name": "c"},
                     "combinator": {"default_mode": "APPLY_ALL_TYPO"}},
                    tmp_path)
    errs = _errors(issues)
    assert len(errs) == 1 and errs[0].rule == "invalid_enum"
    assert "default_mode" in errs[0].target


def test_top_level_unknown_key_error(tmp_path):
    issues = _check({"interfaces": [{"name": "A"}],
                     "interfases": [{"name": "B"}]}, tmp_path)
    errs = _errors(issues)
    assert len(errs) == 1 and errs[0].rule == "unknown_property"


def test_meta_only_document_error(tmp_path):
    issues = _check({"meta": {"author": "x"}}, tmp_path)
    errs = _errors(issues)
    assert len(errs) == 1 and errs[0].rule == "unknown_document_kind"


def test_non_dict_document_error(tmp_path):
    issues = _check([{"name": "A"}], tmp_path, name="bare_list.yaml")
    errs = _errors(issues)
    assert len(errs) == 1 and errs[0].rule == "unknown_document_kind"


def test_malformed_yaml_error(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("interfaces:\n  - name: [unclosed\n", encoding="utf-8")
    issues = checker.check([bad])
    errs = _errors(issues)
    assert len(errs) == 1 and errs[0].rule == "yaml_parse_error"


def test_empty_file_error(tmp_path):
    empty = tmp_path / "empty.yaml"
    empty.write_text("", encoding="utf-8")
    issues = checker.check([empty])
    errs = _errors(issues)
    assert len(errs) == 1 and errs[0].rule == "unknown_document_kind"


def test_multiple_typos_fan_out(tmp_path):
    issues = _check({"environment": {"name": "E", "enabledd": 1,
                                     "agentsx": []}}, tmp_path)
    errs = _errors(issues)
    assert len(errs) == 2
    assert {e.rule for e in errs} == {"unknown_property"}


# ── CLI / 元测试 ──

def test_main_returns_zero_on_examples():
    assert main(["-i", str(EXAMPLES_ROOT), "-q"]) == 0


def test_main_returns_one_on_error(tmp_path):
    _write(tmp_path, "bad.yaml", {"interfaces": [{"ports": []}]})
    assert main(["-i", str(tmp_path), "-q"]) == 1


def test_main_report_file_written(tmp_path):
    _write(tmp_path, "bad.yaml", {"interfaces": [{"ports": []}]})
    report = tmp_path / "report.txt"
    assert main([str(tmp_path / "bad.yaml"), "--report", str(report), "-q"]) == 1
    text = report.read_text(encoding="utf-8")
    assert "Schema check report (tool_uvm)" in text
    assert "[ERROR] missing_required" in text


def test_cwd_independent(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert SchemaChecker().check([EXAMPLES / "apb_env.yaml"]) == []


def test_directory_input_collects_all():
    issues = checker.check([EXAMPLES_ROOT])
    assert issues == []


def test_schema_is_valid_jsonschema():
    Draft202012Validator.check_schema(
        json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))


# ── 集成：gen_uvm 生成流程 Phase 0（error 阻断 / --skip-schema-check）──

def test_gen_blocks_on_schema_error(tmp_path):
    from src.generation_plane.uvm_tools.tool_uvm.generators.cli import main as gen_main
    _write(tmp_path, "bad.yaml", {"interfaces": [{"ports": []}]})
    dest = tmp_path / "out"
    with pytest.raises(SystemExit):
        gen_main(["-i", str(tmp_path / "bad.yaml"), "-d", str(dest), "-q"])
    report = (dest / "schema_report.txt").read_text(encoding="utf-8")
    assert "[ERROR] missing_required" in report


def test_gen_blocks_on_unknown_key(tmp_path):
    from src.generation_plane.uvm_tools.tool_uvm.generators.cli import main as gen_main
    src = yaml.safe_load((EXAMPLES / "apb_interface.yaml").read_text(encoding="utf-8"))
    src["interfaces"][0]["reset_active_loww"] = True  # 拼错键 → unknown key error
    tmp_yaml = _write(tmp_path, "typo.yaml", src)
    dest = tmp_path / "out"
    with pytest.raises(SystemExit):
        gen_main(["-i", str(tmp_yaml), "-d", str(dest), "-q"])
    report = (dest / "schema_report.txt").read_text(encoding="utf-8")
    assert "[ERROR] unknown_property" in report
    assert "reset_active_loww" in report


def test_gen_skip_schema_check_bypasses(tmp_path):
    from src.generation_plane.uvm_tools.tool_uvm.generators.cli import main as gen_main
    src = yaml.safe_load((EXAMPLES / "apb_interface.yaml").read_text(encoding="utf-8"))
    src["interfaces"][0]["ports"][0]["dir"] = "inout"  # 非法枚举 → schema error
    tmp_yaml = _write(tmp_path, "bad.yaml", src)
    dest = tmp_path / "out"
    with pytest.raises(SystemExit):
        gen_main(["-i", str(tmp_yaml), "-d", str(dest), "-q"])
    dest2 = tmp_path / "out2"
    assert gen_main(["-i", str(tmp_yaml), "-d", str(dest2),
                     "--skip-schema-check", "-q"]) == 0
    assert not (dest2 / "schema_report.txt").exists()


# ── 属性测试（environment.tests）：一条 = 一个 UVM_TEST = 一个属性取值 ──

def _env_with_tests(tests):
    return {"environment": {"name": "FC_env", "agents": [], "tests": tests}}


def test_env_tests_accepted(tmp_path):
    """带 tests: 的 env 必须是干净的 —— 这是整条属性链的入口。"""
    doc = _env_with_tests([
        {"dimension": "D_ratio", "value": "0", "key": "fc_ratio", "int_value": 0},
        {"dimension": "D_mode", "value": "首拍", "key": "fc_mode", "int_value": 1},
    ])
    assert _errors(_check(doc, tmp_path)) == []


def test_env_test_entry_value_may_be_number(tmp_path):
    """取值写数字也认（YAML 里 `value: 50` 不带引号是常态）。"""
    doc = _env_with_tests([{"dimension": "D_ratio", "value": 50}])
    assert _errors(_check(doc, tmp_path)) == []


def test_env_test_entry_requires_dimension_and_value(tmp_path):
    doc = _env_with_tests([{"dimension": "D_ratio"}])
    assert any(i.rule == "missing_required" for i in _errors(_check(doc, tmp_path)))


def test_env_test_entry_rejects_unknown_key(tmp_path):
    """条目里写错键名要报错，不能静默忽略 —— 静默忽略会让属性悄悄失效。"""
    doc = _env_with_tests([{"dimension": "D_ratio", "value": "0", "dimension_id": "D_ratio"}])
    assert [i.rule for i in _errors(_check(doc, tmp_path))] == ["unknown_property"]


def test_env_test_int_value_must_be_integer(tmp_path):
    doc = _env_with_tests([{"dimension": "D_ratio", "value": "0", "int_value": "五十"}])
    assert [i.rule for i in _errors(_check(doc, tmp_path))] == ["type_mismatch"]


def test_env_tests_must_be_a_list(tmp_path):
    doc = {"environment": {"name": "FC_env", "agents": [], "tests": {"dimension": "D"}}}
    assert [i.rule for i in _errors(_check(doc, tmp_path))] == ["type_mismatch"]
