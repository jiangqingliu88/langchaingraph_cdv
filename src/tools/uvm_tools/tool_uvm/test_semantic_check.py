"""SemanticValidator 规则测试（Phase B 约定：每条规则至少一个测试）"""
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))
from src.tools.uvm_tools.tool_uvm.gen_uvm import (
    AgentModel,
    BenchModel,
    ConstraintModel,
    EnvironmentModel,
    HarnessModel,
    YAMLLoader,
    _normalize_harness,
    main,
)
from src.tools.uvm_tools.tool_uvm.semantic_check import Issue, SemanticValidator

EXAMPLES = Path(__file__).parent / "examples"


def _agent(**kw):
    base = dict(name="A", agent_name="A", interface="A", interface_name="A")
    base.update(kw)
    return AgentModel(**base)


def _issues(kind, model):
    parsed = {kind: [model]}
    return [i for i in SemanticValidator.validate(parsed) if i.target == model.name]


def _by_rule(issues, rule_id):
    return [i for i in issues if i.rule == rule_id]


# ── agent 级 ──

def test_param_width_undefined_error():
    a = _agent(parameters=[{"name": "W", "value": 8}],
               ports=[{"name": "p", "dir": "output", "width": "WW"}])
    assert _by_rule(_issues("interfaces", a), "param_width_undefined")
    a2 = _agent(parameters=[{"name": "W", "value": 8}],
                ports=[{"name": "p", "dir": "output", "width": "W"}])
    assert not _by_rule(_issues("interfaces", a2), "param_width_undefined")


def test_txn_var_port_mismatch_warning():
    a = _agent(ports=[{"name": "paddr", "dir": "output", "width": 8}],
               transaction_vars=[{"name": "padr", "type": "bit [7:0]"}])
    assert _by_rule(_issues("interfaces", a), "txn_var_port_mismatch")
    # 控制端口无事务字段 → port_not_in_txn warning
    a2 = _agent(ports=[{"name": "penable", "dir": "output", "width": 1}],
                transaction_vars=[{"name": "paddr", "type": "bit [7:0]"}])
    issues = _issues("interfaces", a2)
    assert _by_rule(issues, "port_not_in_txn")
    assert _by_rule(issues, "txn_var_port_mismatch")


def test_agent_dup_name_errors():
    a = _agent(ports=[{"name": "p", "dir": "output", "width": 1},
                      {"name": "p", "dir": "output", "width": 1}])
    assert _by_rule(_issues("interfaces", a), "port_dup_name")
    a2 = _agent(transaction_vars=[{"name": "x", "type": "bit"},
                                  {"name": "x", "type": "bit"}])
    assert _by_rule(_issues("interfaces", a2), "txn_var_dup_name")


# ── env 级 ──

def test_analysis_port_dup_name_error():
    env = EnvironmentModel(name="E", env_name="E",
                           analysis_exports=[{"name": "ap", "type": "T", "connected_to": ""}],
                           analysis_ports=[{"name": "ap", "type": "T", "connected_to": ""}])
    assert _by_rule(_issues("environments", env), "analysis_port_dup_name")


def test_tlm_connection_unknown_ref_warning():
    env = EnvironmentModel(name="E", env_name="E",
                           tlm_connections=[{"driver": "ghost.mon_ap",
                                              "receiver": "apb_scb.exp"}])
    assert _by_rule(_issues("environments", env), "tlm_connection_unknown_ref")


def test_register_model_bus_unmatched_warning():
    from src.tools.uvm_tools.tool_uvm.gen_uvm import _normalize_register_model
    agents = [AgentModel(name="apb_master", agent_name="apb_master",
                         interface="apb", interface_name="apb",
                         agent_type="apb_master_agent")]
    rm = _normalize_register_model(
        [{"bus_name": "nowhere", "type": "ghost_agent"},
         {"reg_block_name": "rb", "type": "rb_t"}], agents)
    assert rm["bus_entry_seen"] and not rm["bus_matched"]
    env = EnvironmentModel(name="E", env_name="E", register_model=rm)
    env.agents.extend(agents)
    assert _by_rule(_issues("environments", env), "register_model_bus_unmatched")
    # 匹配上时无警告
    rm2 = _normalize_register_model(
        [{"bus_name": "apb", "type": "apb_master_agent"},
         {"reg_block_name": "rb", "type": "rb_t"}], agents)
    assert rm2["bus_matched"]
    env2 = EnvironmentModel(name="E2", env_name="E2", register_model=rm2)
    env2.agents.extend(agents)
    assert not _by_rule(_issues("environments", env2), "register_model_bus_unmatched")


def test_harness_connect_path_missing_error():
    env = EnvironmentModel(name="E", env_name="E",
                           harness_connect={"env_suffix": ".x"})
    assert _by_rule(_issues("environments", env), "harness_connect_path_missing")


# ── bench 级 ──

def test_bench_dut_port_wire_undefined_error():
    bench = BenchModel(name="B", env_name="E",
                       wire_decls=[{"name": "paddr", "width": 32}],
                       clk_rst={"clocks": [{"name": "pclk"}],
                                "resets": [{"name": "presetn"}]},
                       dut={"module": "m", "instance": "u",
                            "ports": [{"name": "pclk", "connection": "pclk"},
                                      {"name": "paddr", "connection": "paddr"},
                                      {"name": "pwdata", "connection": "ghost"}]})
    assert _by_rule(_issues("benches", bench), "dut_port_wire_undefined")


def test_bench_agent_wire_undefined_skipped_with_harness():
    from src.tools.uvm_tools.tool_uvm.gen_uvm import BenchAgentEntry
    bench = BenchModel(name="B", env_name="E", harness={"name": "h"},
                       agents={"A": BenchAgentEntry(
                           name="A", interface="A",
                           connections=[{"port": "p", "wire": "ghost"}])})
    assert not _by_rule(_issues("benches", bench), "agent_wire_undefined")


# ── constraint 级 ──

def _cons_issues(cm):
    return [(i.rule, i.severity)
            for i in SemanticValidator.validate({"constraints": [cm]})]


def test_constraint_rules():
    ok = ConstraintModel(name="c", env_name="E",
                         transactions=[{"name": "weight", "type": "T"},
                                       {"name": "input", "type": "T"}],
                         policies=[{"name": "concurrent_access",
                                    "applies_to": ["weight", "input"]}])
    assert _cons_issues(ok) == []   # 内置名 + applies_to 命中 → 无警告
    bad = ConstraintModel(name="c", env_name="E",
                          transactions=[{"name": "w", "type": "T"},
                                        {"name": "w", "type": "T"}],
                          policies=[{"name": "p1", "applies_to": ["ghost"]},
                                    {"name": "p1", "applies_to": ["w"]}])
    issues = _cons_issues(bad)
    assert ("txn_dup_name", "error") in issues
    assert ("policy_dup_name", "error") in issues
    assert ("policy_applies_to_unknown", "error") in issues
    # 自定义名 → warning（空 apply 骨架）
    assert ("policy_unknown_name", "warning") in issues


# ── harness 级 ──

def test_harness_bind_to_missing_error():
    h = _normalize_harness({"name": "h1"})
    assert _by_rule(_issues("harnesses", h), "bind_to_missing")


def test_harness_if_empty_connections_warning():
    h = _normalize_harness({"name": "h1", "bind_to": "dut",
                            "interfaces": [{"name": "i", "type": "T"}]})
    assert _by_rule(_issues("harnesses", h), "if_empty_connections")


# ── 集成：error 阻断 + 报告落盘 ──

def test_run_blocks_on_errors_and_writes_report(tmp_path):
    import yaml
    src = yaml.safe_load((EXAMPLES / "apb_env.yaml").read_text(encoding="utf-8"))
    # 显式构造同名 analysis_exports/analysis_ports，触发 dup_name 规则（不依赖示例条目）
    src["environment"]["analysis_exports"] = [{"name": "dup_ap"}]
    src["environment"]["analysis_ports"] = [{"name": "dup_ap"}]
    tmp_yaml = tmp_path / "env_bad.yaml"
    tmp_yaml.write_text(yaml.safe_dump(src, allow_unicode=True, sort_keys=False),
                        encoding="utf-8")
    dest = tmp_path / "out"
    with pytest.raises(SystemExit):
        main(["-i", str(tmp_yaml), "-d", str(dest), "-q"])
    report = (dest / "validation_report.txt").read_text(encoding="utf-8")
    assert "analysis_port_dup_name" in report
    assert "[ERROR]" in report


def test_warnings_do_not_block(tmp_path):
    import yaml
    src = yaml.safe_load((EXAMPLES / "apb_env.yaml").read_text(encoding="utf-8"))
    src["environment"]["tlm_connections"].append(
        {"driver": "ghost.mon_ap", "receiver": "apb_scb.exp"})
    tmp_yaml = tmp_path / "env_warn.yaml"
    tmp_yaml.write_text(yaml.safe_dump(src, allow_unicode=True, sort_keys=False),
                        encoding="utf-8")
    dest = tmp_path / "out"
    assert main(["-i", str(tmp_yaml), "-d", str(dest), "-q"]) == 0
    report = (dest / "validation_report.txt").read_text(encoding="utf-8")
    assert "tlm_connection_unknown_ref" in report and "[WARNING]" in report
