"""plusargs 语义 —— 后端方言 vs 测试语义，两条通道不能混。

这组测试钉的是**生成期**的四件事：

  ① `plusargs` 是整组透传，不再"每个一条用例"；
  ② 后端保留键（`+ntb_random_seed` / `+UVM_TESTNAME` / `-cm`…）不许手写；
  ③ 种子只从 `seeds` 出，plusargs 里不许出现 `{{ SEED }}`；
  ④ 有用户参数却没有 `{{ PLUSARGS }}` 注入点 → 生成期报错，不静默丢。
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from src.tools.execution.regression_tools import backend_profiles
from src.tools.execution.regression_tools.regression_framework.core.config import (
    ConfigBuilder)
from src.tools.execution.regression_tools.regression_framework.core.exceptions import (
    ConfigError)
from src.tools.execution.regression_tools.regression_framework.generators.shell import (
    ShellGenerator)


def _write_yaml(tmp_path: Path, tests: list, *, simulator: str = "questa") -> Path:
    doc = {
        "simulator": simulator,
        "variables": {"SEED": 12345},
        "builds": [{"name": "b", "top": "dut_tb", "run_cmd": "true"}],
        "tests": tests,
    }
    path = tmp_path / "inputs" / "yaml" / "regression.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False),
                    encoding="utf-8")
    return path


def _base_test(**extra) -> dict:
    test = {
        "name": "npu_type_test",
        "build": "b",
        "run_cmd": "echo BASE {{ PLUSARGS }} ; true",
    }
    test.update(extra)
    return test


def test_plusargs_are_passed_through_not_expanded(tmp_path):
    path = _write_yaml(tmp_path, [_base_test(plusargs=[
        "+preload=preload.hex", "+cfg_mode=perf"])])
    config = ConfigBuilder(str(path)).build()
    assert len(config["tests"]) == 1, "plusargs 不应再展开成多条用例"
    assert config["tests"][0]["plusargs"] == ["+preload=preload.hex",
                                              "+cfg_mode=perf"]


def test_plusarg_matrix_keeps_the_old_semantics(tmp_path):
    path = _write_yaml(tmp_path, [_base_test(
        run_cmd="echo {{ plusarg }}",
        plusarg_matrix=["+pb=1", "+pb=2"])])
    config = ConfigBuilder(str(path)).build()
    assert len(config["tests"]) == 2
    assert {t["local_vars"]["plusarg"] for t in config["tests"]} == {"+pb=1", "+pb=2"}
    assert all("plusarg_matrix" not in t for t in config["tests"])


def test_a_backend_reserved_plusarg_is_rejected(tmp_path):
    path = _write_yaml(tmp_path, [_base_test(plusargs=["+ntb_random_seed=7"])])
    with pytest.raises(ConfigError, match="ntb_random_seed"):
        ConfigBuilder(str(path)).build()


def test_a_seed_template_in_plusargs_is_rejected(tmp_path):
    path = _write_yaml(tmp_path, [_base_test(plusargs=["+my_seed={{ SEED }}"])])
    with pytest.raises(ConfigError, match="seeds"):
        ConfigBuilder(str(path)).build()


def test_seeds_expand_to_contiguous_runs(tmp_path):
    path = _write_yaml(tmp_path, [_base_test(seeds={"base": 2001, "count": 3})])
    config = ConfigBuilder(str(path)).build()
    assert [t["name"] for t in config["tests"]] == [
        "npu_type_test_run_1", "npu_type_test_run_2", "npu_type_test_run_3"]
    assert [t["local_vars"]["SEED"] for t in config["tests"]] == [2001, 2002, 2003]


def test_user_args_render_at_the_placeholder_in_order(tmp_path):
    path = _write_yaml(tmp_path, [_base_test(
        plusargs=["+preload=x.hex", "+cfg_mode=perf"],
        backend_args=["+voptargs=+acc"])])
    config = ConfigBuilder(str(path)).build()
    root = tmp_path / "regression_run"
    ShellGenerator().generate(config, str(root), "mock")
    sim = next(root.rglob("sim.sh")).read_text(encoding="utf-8")
    base = sim.index("BASE")
    pre = sim.index("+preload=x.hex")
    cfg = sim.index("+cfg_mode=perf")
    esc = sim.index("+voptargs=+acc")
    assert base < pre < cfg < esc, "顺序必须是：后端命令 → plusargs → backend_args"


def test_missing_plusargs_placeholder_fails_loudly(tmp_path):
    path = _write_yaml(tmp_path, [{
        "name": "t", "build": "b",
        "run_cmd": "echo BASE ; true",
        "plusargs": ["+preload=x.hex"],
    }])
    config = ConfigBuilder(str(path)).build()
    with pytest.raises(ConfigError, match="PLUSARGS"):
        ShellGenerator().generate(config, str(tmp_path / "regression_run"), "mock")


def test_questa_template_injects_before_the_check_chain():
    cmd = backend_profiles.render_sim_command("questa", "top", "t")
    assert "{{ PLUSARGS }}" in cmd
    assert cmd.index("{{ PLUSARGS }}") < cmd.index("; ["), \
        "用户参数必须在判据链 `;` 之前，否则不是给 vsim 的参数"


def test_an_unimplemented_backend_fails_loudly():
    with pytest.raises(ValueError, match="run_cmd"):
        backend_profiles.render_sim_command("vcs", "top", "t")


def test_backend_profile_detection_and_reserved_table():
    assert backend_profiles.detect_simulator(
        {"simulator": "Questa"}) == "questa"
    assert backend_profiles.detect_simulator(
        {"tests": [{"run_cmd": "vsim -c top"}]}) == "questa"
    assert backend_profiles.detect_simulator(
        {"tests": [{"run_cmd": "vcs -full64 top"}]}) == "vcs"
    errors, _ = backend_profiles.validate_plusargs(
        ["+UVM_TESTNAME=x"], "questa")
    assert errors and "uvm_testname" in errors[0].lower()
    errors, warnings = backend_profiles.validate_plusargs(
        ["+preload=x", "+preload=y"], "questa")
    assert not errors and warnings
