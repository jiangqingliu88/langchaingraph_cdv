"""tool_testgen 测试：xlsx → tc_pkg + 定向约束 + 拆 seq + traceability"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "src").is_dir())))
from src.generation_plane.uvm_tools.tool_uvmtestgen.main import (
    make_template,
    main,
    parse_directed_constraints,
    parse_seq_flow,
    read_testpoints,
    render_constraints_svh,
    render_tc_pkg,
    render_trace,
    validate,
)

#: apb 例子已挪进 `examples/apb/` 子目录 —— 指向 `examples/` 本身会 FileNotFound
EXAMPLES = Path(__file__).parent.parent / "tool_uvm" / "examples" / "apb"


def _make_xlsx(path: Path):
    make_template(path)


def test_parse_directed_constraints():
    lines, errors = parse_directed_constraints(
        "paddr==32'h1000; pwrite==1; pwdata inside {[0:255]}; psel dist {1:=90, 0:=10};")
    assert errors == []
    assert lines == ["paddr == 32'h1000;", "pwrite == 1;",
                     "pwdata inside {[0:255]};", "psel dist {1:=90, 0:=10};"]
    _l2, err2 = parse_directed_constraints("paddr=1;")   # 单等号非法
    assert err2


def test_parse_seq_flow():
    assert parse_seq_flow("apb_random_wr_seq(10); apb_b2b_wr_seq(1);") == (
        "structured", [("apb_random_wr_seq", 10), ("apb_b2b_wr_seq", 1)])
    assert parse_seq_flow("step1: 随机写; step2: 比对;") == ("simple", [])
    assert parse_seq_flow("") == ("simple", [])


def test_make_template_and_generate(tmp_path):
    xlsx = tmp_path / "tp.xlsx"
    _make_xlsx(xlsx)
    assert xlsx.is_file()
    data = read_testpoints(xlsx)
    assert len(data["testpoints"]) == 2
    assert data["meta"]["module_name"] == "APB_env"
    assert data["meta"]["bus_seq_item"] == "apb_master_seq_item"
    assert validate(data, bus_seq_item="apb_master_seq_item") == []

    sv = render_tc_pkg(data, "apb_master_seq_item")
    # approved 行 → 完整类（含定向约束 override）
    assert "class APB_env_gen_test_APB_TP_001 extends APB_env_gen_test;" in sv
    assert "set_type_override_by_type(apb_master_seq_item::get_type()," in sv
    assert "APB_env_gen_test_APB_TP_001_seq_item_c::get_type());" in sv
    # reviewed 行 → 注释保留（tc_com "-" 渲染为默认 config 类）
    assert "// class APB_env_gen_test_APB_TP_002 extends APB_env_gen_test;" in sv
    assert "[status=REVIEWED]" in sv

    cons = render_constraints_svh(data, "apb_master_seq_item")
    assert "class APB_env_gen_test_APB_TP_001_seq_item_c extends apb_master_seq_item;" in cons
    assert "paddr == 32'h1000;" in cons
    assert "class APB_env_gen_test_APB_TP_001_flow_seq extends APB_env_virtual_base_seq;" in cons
    assert "apb_random_wr_seq s1 = apb_random_wr_seq::type_id::create(\"s1\");" in cons
    # reviewed 行的约束/骨架注释保留
    assert "// class APB_env_gen_test_APB_TP_002_flow_seq" in cons

    trace = render_trace(data)
    assert "| APB_FEAT_WR | APB_TP_001 | APB back-to-back 写传输 | P0 |" in trace
    assert "## By Feature" in trace and "### APB_FEAT_WR" in trace


def test_cli_flow_with_yaml(tmp_path, capsys):
    xlsx = tmp_path / "tp.xlsx"
    _make_xlsx(xlsx)
    yaml_file = EXAMPLES / "apb_interface.yaml"
    assert main(["-i", str(xlsx), "-y", str(yaml_file),
                 "-d", str(tmp_path / "out"), "-q"]) == 0
    assert (tmp_path / "out" / "APB_env_tc_pkg.sv").is_file()
    assert (tmp_path / "out" / "APB_env_tc_constraints.svh").is_file()
    assert (tmp_path / "out" / "testpoint_trace.md").is_file()
    with pytest.raises(SystemExit) as e:
        main(["--version"])
    assert e.value.code == 0


def test_validate_dup_id_and_bad_priority_and_unknown_seq(tmp_path):
    from openpyxl import load_workbook
    xlsx = tmp_path / "tp.xlsx"
    _make_xlsx(xlsx)
    wb = load_workbook(xlsx)
    ws = wb["testpoints"]
    ws["B3"] = "APB_TP_001"        # id 列（B）重复
    ws["F3"] = "P9"                # priority 列（F）非法
    ws["J3"] = "ghost_seq"         # tc_seq 列（J）不在 sequences 表
    wb.save(xlsx)
    errors = validate(read_testpoints(xlsx), bus_seq_item="apb_master_seq_item")
    assert any("重复" in e for e in errors)
    assert any("priority" in e for e in errors)
    assert any("ghost_seq" in e for e in errors)


def test_validate_constraints_field_and_bus_item(tmp_path):
    """定向约束字段名校验（-y 提供 txn fields）+ 缺 bus_seq_item 报错。"""
    from openpyxl import load_workbook
    xlsx = tmp_path / "tp.xlsx"
    _make_xlsx(xlsx)
    wb = load_workbook(xlsx)
    ws = wb["testpoints"]
    ws["K2"] = "paddr==1; ghost_field==2;"   # ghost_field 不在 transaction_vars
    wb.save(xlsx)
    data = read_testpoints(xlsx)
    fields = {"paddr", "pwrite", "pwdata", "prdata", "pslverr", "psel", "penable", "pready"}
    errors = validate(data, bus_seq_item="apb_master_seq_item", txn_fields=fields)
    assert any("ghost_field" in e for e in errors)
    # 无 bus_seq_item + 有约束 → 报错
    errors2 = validate(data, bus_seq_item="", txn_fields=None)
    assert any("bus seq_item" in e for e in errors2)


def test_run_loop_closed_without_simulator(tmp_path, monkeypatch):
    """闭环 ④⑤：testgen → testrun（无仿真器全 SKIP）→ xlsx execution 回写 + 签核证据包。"""
    import json
    import shutil
    from openpyxl import load_workbook
    # 强制「无仿真器」路径（本机可能装了 QuestaSim，vlog 在 PATH 上）
    monkeypatch.setattr(shutil, "which", lambda name: None)
    from src.generation_plane.uvm_tools.tool_testrun.main import main as tr_main
    xlsx = tmp_path / "tp.xlsx"
    _make_xlsx(xlsx)
    dest = tmp_path / "out"
    assert main(["-i", str(xlsx), "-d", str(dest), "-q"]) == 0
    assert tr_main(["-p", str(dest / "regression_plan.yaml"),
                    "-d", str(dest), "--signoff-package",
                    "--inputs", str(EXAMPLES / "apb_interface.yaml"), "-q"]) == 0
    r = json.load(open(dest / "test_run_results.json", encoding="utf-8"))
    assert r["results"] and all(x["status"] == "skip" for x in r["results"])
    wb = load_workbook(xlsx)
    assert "execution" in wb.sheetnames
    assert (dest / "test_run_results.md").is_file()
    # 签核证据包
    pkg = next((dest / "signoff").glob("*"))
    m = json.load(open(pkg / "manifest.json", encoding="utf-8"))
    assert m["inputs"] and m["outputs"]
    assert all(x["sha256"] for x in m["inputs"] + m["outputs"])
    assert "签核证据包" in (pkg / "signoff_summary.md").read_text(encoding="utf-8")


def test_validate_missing_meta_and_empty(tmp_path):
    from openpyxl import Workbook
    xlsx = tmp_path / "tp.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "testpoints"
    ws.append(["feature_id", "id", "feature", "description", "priority", "tc_com",
               "tc_reg", "tc_seq", "checker", "func_coverage", "review_status"])
    wb.save(xlsx)
    errors = validate(read_testpoints(xlsx))
    assert any("module_name" in e for e in errors)
