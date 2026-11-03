"""`validate_uvm` 的产物判据必须认得生成器**当前**的布局。

历史坑：判据写死成 `agents/<agent>/<agent>_<file>.sv` 扁平命名，而生成器早已
改成「分目录 + 模块前缀」（`agents/npu_in_agent/5_agent/npu_system_env.sv`）。
结果每次 verify 都报 `missing 16 UVM files` —— 一个**永远为真**的假红灯。
这里锁住三种情况：当前布局 PASS、旧布局 PASS、真缺文件才报。
"""
from __future__ import annotations

from pathlib import Path

from src.layers.l2_orchestration.governance.quality_guard import (
    Verdict, validate_uvm,
)

_CURRENT = {
    "1_interface/mod_if.sv": "interface mod_if; endinterface",
    "3_transaction_sequencer/mod_base_seq_item.sv": "class t; endclass",
    "3_transaction_sequencer/mod_master_sequencer.sv": "class s; endclass",
    "4_driver_monitor/mod_master_driver.sv": "class d; endclass",
    "4_driver_monitor/mod_port_monitor.sv": "class m; endclass",
    "5_agent/mod_master_agent.sv": "class a; endclass",
    "5_agent/mod_system_env.sv": "class e; endclass",
    "7_sequence/mod_master_sequence.sv": "class q; endclass",
    "mod_pkg.sv": "package p; endpackage",
}

_FLAT = {
    "mod_agent_env_pkg.sv": "",
    "mod_agent_env.sv": "",
    "mod_agent_agent.sv": "",
    "mod_agent_driver.sv": "",
    "mod_agent_monitor.sv": "",
    "mod_agent_transaction.sv": "",
    "mod_agent_sequence.sv": "",
}


def _build(tmp_path: Path, files: dict) -> Path:
    agent_dir = tmp_path / "agents" / "mod_agent"
    for rel, text in files.items():
        path = agent_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return tmp_path


def test_current_layout_passes(tmp_path):
    """分目录 + 模块前缀（生成器现在的布局）不该报缺文件。"""
    od = _build(tmp_path, _CURRENT)
    result = validate_uvm({"env_name": "mod_agent"}, str(od))
    assert result.verdict is Verdict.PASS, result.issues
    assert result.issues == []


def test_flat_layout_still_passes(tmp_path):
    """旧的扁平命名（`<agent>_env.sv`）同样要认 —— 两代布局共存。"""
    od = _build(tmp_path, _FLAT)
    result = validate_uvm({"env_name": "mod_agent"}, str(od))
    assert result.verdict is Verdict.PASS, result.issues


def test_missing_artifact_is_reported(tmp_path):
    """真缺 driver：报的应当是**类名**，不是一长串绝对路径。"""
    files = dict(_CURRENT)
    del files["4_driver_monitor/mod_master_driver.sv"]
    od = _build(tmp_path, files)
    result = validate_uvm({"env_name": "mod_agent"}, str(od))
    assert result.verdict is Verdict.FALLBACK
    joined = " ".join(result.issues)
    assert "driver" in joined
    assert "mod_agent/" in joined
    assert str(tmp_path) not in joined


def test_scoreboard_is_optional(tmp_path):
    """scoreboard 按 ref_mirror_gate 有意不生成 —— 不能当硬缺口。"""
    od = _build(tmp_path, _CURRENT)
    result = validate_uvm({"env_name": "mod_agent"}, str(od))
    assert "scoreboard" not in " ".join(result.issues)
