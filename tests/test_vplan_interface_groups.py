"""VPlan → UVM 接口分组/端口属性的回归测试。

覆盖四个曾经真实踩过的坑：
  · dplan 的 `modules[].interfaces` 只有端口名 → RTL/UVM 全被写成 1-bit inout；
  · verify 把全部端口压成一个 `cmd_if` → 无法按协议边界驱动；
  · `rstart` 被 `rst` 子串误判成复位；
  · run 一开始就建 agents/env/bench/build 这些 legacy 顶层目录。
"""
from __future__ import annotations

from pathlib import Path

from src.skills.front.dplan.extract import merge_contracts
from src.skills.front.vplan.extract import _top_ifaces
from src.skills.verify.main import _vplan_uvm_spec
from src.layers.l1_infrastructure.infrastructure import InfrastructureManager
from src.layers.l3_decision.vplan.execution import _json
from src.tools.common.lib.ports import is_clock_port, is_reset_port


FULL = [
    {"name": "clk", "data_width": 1, "direction": "INPUT", "protocol": "clock"},
    {"name": "rst_n", "data_width": 1, "direction": "INPUT", "protocol": "reset"},
    {"name": "disp_cmd_inst", "data_width": 74, "direction": "INPUT",
     "protocol": "valid-ready"},
    {"name": "cmd_xbr_ch0_req_wdata", "data_width": 512, "direction": "INPUT",
     "protocol": "config"},
    {"name": "cmd_xbr_ch1_icg_rstart", "data_width": 1, "direction": "OUTPUT",
     "protocol": "pulse"},
    {"name": "cmd_creg_int", "data_width": 1, "direction": "OUTPUT",
     "protocol": "interrupt"},
]

NAME_ONLY_TOP = [
    {"name": "clk", "data_width": 1, "direction": "INOUT", "protocol": ""},
    {"name": "rst_n", "data_width": 1, "direction": "INOUT", "protocol": ""},
    {"name": "disp_cmd_inst", "data_width": 1, "direction": "INOUT", "protocol": ""},
    {"name": "cmd_xbr_ch0_req_wdata", "data_width": 1, "direction": "INOUT",
     "protocol": ""},
    {"name": "cmd_xbr_ch1_icg_rstart", "data_width": 1, "direction": "INOUT",
     "protocol": ""},
    {"name": "cmd_creg_int", "data_width": 1, "direction": "INOUT", "protocol": ""},
]


def _spec():
    return {
        "design_name": "npu_sched",
        "architecture": {"top": "npu_sched"},
        "interfaces": [dict(i) for i in FULL],
        "modules": [{"name": "npu_sched", "level": "top",
                     "interfaces": [dict(i) for i in NAME_ONLY_TOP]}],
        "model_contract": {"ports": [dict(i) for i in NAME_ONLY_TOP]},
    }


def test_merge_contracts_enriches_name_only_module_ports():
    merged = merge_contracts({}, _spec())
    top = merged["modules"][0]["interfaces"]
    by_name = {i["name"]: i for i in top}
    assert by_name["disp_cmd_inst"]["data_width"] == 74
    assert by_name["disp_cmd_inst"]["direction"] == "INPUT"
    assert by_name["disp_cmd_inst"]["protocol"] == "valid-ready"
    assert by_name["cmd_xbr_ch0_req_wdata"]["data_width"] == 512
    mc_ports = {i["name"]: i for i in merged["model_contract"]["ports"]}
    assert mc_ports["cmd_xbr_ch0_req_wdata"]["data_width"] == 512


def test_vplan_uvm_spec_groups_by_protocol_and_keeps_widths(tmp_path):
    run = tmp_path / "run"
    (run / "inputs" / "vplan" / "data").mkdir(parents=True)
    (run / "inputs" / "vplan" / "data" / "execution_meta.csv").write_text(
        "version\n1\n", encoding="utf-8")

    spec = _vplan_uvm_spec(_spec(), run)
    ifaces = spec["interfaces"]
    by_name = {i["name"]: i for i in ifaces}
    assert by_name["disp_cmd_inst"]["data_width"] == 74
    assert by_name["disp_cmd_inst"]["protocol"] == "valid_ready"
    assert by_name["cmd_xbr_ch0_req_wdata"]["data_width"] == 512
    assert by_name["clk"]["protocol"] == "clock"
    assert by_name["rst_n"]["protocol"] == "reset"
    # 再也不是一个 cmd_if 大接口：至少 5 个不同协议边界
    assert len({i["protocol"] for i in ifaces}) >= 5
    assert "cmd_if" not in {i["protocol"] for i in ifaces}


def test_top_ifaces_enriched_from_global_contract():
    """bootstrap 的顶层接口也要带位宽/方向/协议（否则维度全记成 1-bit）。"""
    spec = _spec()
    out = _top_ifaces(spec, spec["modules"])
    by_name = {i["name"]: i for i in out}
    assert by_name["disp_cmd_inst"]["data_width"] == 74
    assert by_name["disp_cmd_inst"]["direction"] == "INPUT"
    assert by_name["cmd_xbr_ch0_req_wdata"]["data_width"] == 512


def test_execution_meta_flow_yaml_sampling_parsed():
    """`execution_meta.csv` 的 sampling 是 YAML flow，不是 JSON。"""
    parsed = _json("{clock: clk, dut_module: npu_sched, reset: rst_n}", {})
    assert parsed["dut_module"] == "npu_sched"
    # 合法 JSON 仍优先；纯文本仍走默认值
    assert _json('{"a": 1}', {}) == {"a": 1}
    assert _json("not-json", {}) == {}


def test_reset_detection_does_not_match_rstart():
    assert is_reset_port("rst_n")
    assert is_reset_port("sys_reset")
    assert is_reset_port("presetn")
    assert not is_reset_port("cmd_xbar_ch1_icg_rstart")
    assert is_clock_port("clk")
    assert is_clock_port("clk_sys")


def test_setup_skips_legacy_dirs_in_vplan_layout(tmp_path, monkeypatch):
    monkeypatch.setenv("SIGNOFFAI_UVM_LAYOUT", "vplan")
    paths = InfrastructureManager(tmp_path / "run").setup()
    # 返回字典仍然完整（调用方不必改）
    assert {"rtl", "env", "agents", "bench", "build", "sim"} <= set(paths)
    for rel in ("agents", "env", "bench", "build"):
        assert not (Path(paths[rel])).exists(), rel
    assert (tmp_path / "run" / "rtl").is_dir()
    assert (tmp_path / "run" / "sim" / "coverage").is_dir()


def test_setup_keeps_legacy_dirs_when_explicitly_legacy(tmp_path, monkeypatch):
    monkeypatch.setenv("SIGNOFFAI_UVM_LAYOUT", "legacy")
    paths = InfrastructureManager(tmp_path / "run").setup()
    for rel in ("agents", "env", "bench", "build"):
        assert Path(paths[rel]).is_dir(), rel


def test_case_ids_from_batch_theme_tags():
    """VPlan 批次 test 的 CASE 身份在 `TH-TC_*` tag 里（不是 testpoints 反查）。"""
    from src.layers.l2_orchestration.regression_tools.regression_framework.generators.shell import _case_ids_for

    test = {"tags": ["p0", "batch", "TH-TC_CMD_INT_PERF_001"]}
    assert _case_ids_for(test, "npu_sched_env_directed_test", {}) == [
        "TC_CMD_INT_PERF_001"]
    # testpoints 反查优先，tag 只补缺
    got = _case_ids_for({"tags": ["TH-TC_SCHED_001"]}, "t",
                        {"t": ["TC_FROM_TP"]})
    assert got == ["TC_FROM_TP", "TC_SCHED_001"]


def test_bootstrap_interface_group_contracts():
    """docs/specs 也要按协议给接口分组契约（C-IF-GRP-*）与端口对照表。"""
    from src.skills.front.vplan.extract import (
        _interface_groups, _group_contract_rows)

    groups = _interface_groups(_spec()["interfaces"])
    assert set(groups) == {"valid_ready", "config", "pulse", "interrupt"}
    rows = {r["contract_id"]: r for r in _group_contract_rows(groups)}
    assert "C-IF-GRP-VALID_READY" in rows
    assert rows["C-IF-GRP-VALID_READY"]["object"] == "valid_ready"
    assert "disp_cmd_inst[74]" in rows["C-IF-GRP-VALID_READY"]["content"]
    assert "cmd_xbr_ch0_req_wdata[512]" in rows["C-IF-GRP-CONFIG"]["content"]


def test_interface_tables_expand_every_port(tmp_path):
    """只保留逐端口表；不再写分组汇总的 interfaces.csv。"""
    import csv
    from src.skills.front.vplan.extract import (
        _interface_groups, _group_contract_rows, _write_interface_ports_table)

    groups = _interface_groups(_spec()["interfaces"])
    rows = _group_contract_rows(groups)
    _write_interface_ports_table(tmp_path, "npu_sched", groups, rows)
    assert not (tmp_path / "npu_sched_interfaces.csv").exists()

    with (tmp_path / "npu_sched_interface_ports.csv").open(
            encoding="utf-8-sig", newline="") as fh:
        ports = list(csv.DictReader(fh))
    assert len(ports) == sum(len(v) for v in groups.values())
    cfg = next(p for p in ports if p["interface_group"] == "config")
    assert cfg["port_name"] == "cmd_xbr_ch0_req_wdata"
    assert cfg["width"] == "512"
    assert cfg["direction"] == "INPUT"
    assert cfg["scope"] == "top" and cfg["module"] == "npu_sched"


def test_bit_fields_extracted_from_description():
    from src.skills.front.vplan.extract import _bit_fields

    assert _bit_fields(
        "指令信号：bit[2:0]=xd/xs1/xs2, bit[9:3]=func7, bit[41:10]=rs1val"
    ) == "bit[2:0]=xd/xs1/xs2|bit[9:3]=func7|bit[41:10]=rs1val"
    assert _bit_fields("") == ""


def test_master_interface_includes_config_start_done_release():
    """一个 master 的接口 = config + start + done + 释放，按模块归组。"""
    from src.skills.front.vplan.extract import (
        _group_name, _group_contract_rows, _interface_groups)
    from src.skills.verify.main import _interface_protocol

    cases = (("cmd_niu_dst_base_addr", "config", "niu"),
             ("cmd_niu_start", "pulse", "niu"),
             ("niu_cmd_inst0_done_vld", "pulse", "niu"),
             ("niu_cmd_inst0_page_rls_vld", "pulse", "niu"),
             ("cmd_glsu_start", "pulse", "glsu"),
             ("cmd_vpu_cfg_op", "config", "vpu"))
    for name, proto, group in cases:
        assert _group_name(proto, name) == group
        assert _interface_protocol({"name": name, "protocol": proto}) == group
    # 不属于 5 个 master 的端口仍按协议
    assert _group_name("config", "cmd_xbr_ch0_req_wdata") == "config"

    ifaces = [
        {"name": "cmd_niu_dst_base_addr", "data_width": 44,
         "direction": "OUTPUT", "protocol": "config"},
        {"name": "cmd_niu_start", "data_width": 1,
         "direction": "OUTPUT", "protocol": "pulse"},
        {"name": "niu_cmd_inst0_done_vld", "data_width": 1,
         "direction": "INPUT", "protocol": "pulse"},
        {"name": "niu_cmd_inst0_page_rls_vld", "data_width": 1,
         "direction": "INPUT", "protocol": "pulse"},
    ]
    rows = {r["contract_id"]: r for r in
            _group_contract_rows(_interface_groups(ifaces))}
    content = rows["C-IF-GRP-NIU"]["content"]
    assert "配置 1 / 启动 1 / 完成 1 / 释放 1" in content


def test_global_interfaces_not_in_module_table_are_kept():
    """模块表漏端口时，docs/specs 仍按全局 interfaces 分组（不丢 spec 端口）。"""
    from src.skills.front.vplan.extract import _interface_groups

    ifaces = list(_spec()["interfaces"]) + [
        {"name": "cmd_creg_mpu_exce0", "data_width": 32,
         "direction": "OUTPUT", "protocol": "interrupt"}]
    groups = _interface_groups(ifaces)
    names = [p["name"] for p in groups["interrupt"]]
    assert "cmd_creg_mpu_exce0" in names
