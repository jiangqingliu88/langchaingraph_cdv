"""Tests for tool_uvm"""
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))
from src.tools.uvm_tools.tool_uvm import UVMGenerator, JinjaRenderer, YAMLLoader
from src.tools.uvm_tools.tool_uvm.gen_uvm import (
    BANNER_MARKER,
    JinjaRenderer as _JinjaRenderer,
    RegionError,
    RegionInjector,
    TEMPLATES_DIR as _TEMPLATES_DIR,
    __version__,
    _normalize_harness,
    main,
)

EXAMPLES = Path(__file__).parent / "examples"

RENDERED = """// ============================================================
class apb_master_driver extends uvm_driver;
  virtual apb_if vif;
  // pragma custom field_decl begin
  // pragma custom field_decl end
  function void build_phase();
    // pragma custom build_logic begin
    // pragma custom build_logic end
  endfunction
endclass
"""


def test_imports():
    """Test that key classes are importable"""
    assert UVMGenerator is not None
    assert JinjaRenderer is not None
    assert YAMLLoader is not None


# ════════════════════════════════════════════════════════════
# RegionInjector 单元测试
# ════════════════════════════════════════════════════════════

def test_extract_blocks_basic():
    text = ("// pragma custom a begin\nline1\nline2\n// pragma custom a end\n"
            "// pragma custom b begin\n// pragma custom b end\n")
    assert RegionInjector.extract_blocks(text) == {"a": "line1\nline2", "b": ""}


def test_extract_blocks_errors():
    with pytest.raises(RegionError, match="not closed"):
        RegionInjector.extract_blocks("// pragma custom a begin\nx")
    with pytest.raises(RegionError, match="duplicate"):
        RegionInjector.extract_blocks(
            "// pragma custom a begin\n// pragma custom a end\n"
            "// pragma custom a begin\n// pragma custom a end\n")
    with pytest.raises(RegionError, match="nested"):
        RegionInjector.extract_blocks(
            "// pragma custom a begin\n// pragma custom b begin\n"
            "// pragma custom b end\n// pragma custom a end\n")


def test_inject_precedence_yaml_over_old_over_default():
    inj = RegionInjector()
    inj._old_blocks["f.sv"] = {"field_decl": "bit old_flag;"}
    # YAML 显式 > 旧文件
    text, report = inj.inject(RENDERED, {"field_decl": "bit yaml_flag;"}, "f.sv")
    assert "bit yaml_flag;" in text and "bit old_flag;" not in text
    assert report.blocks[0].source == "yaml"
    # 旧文件 > 模板默认
    text, report = inj.inject(RENDERED, {}, "f.sv")
    assert "bit old_flag;" in text
    assert report.blocks[0].source == "merged"


def test_inject_adds_banner():
    inj = RegionInjector()
    text, _ = inj.inject(RENDERED, {}, "f.sv")
    assert BANNER_MARKER in text
    assert "// pragma custom field_decl begin" in text


def test_inject_missing_block_error_and_skip():
    inj = RegionInjector()
    inj._old_blocks["f.sv"] = {"bogus": "x"}
    with pytest.raises(RegionError, match="no matching region"):
        inj.inject(RENDERED, {}, "f.sv")
    inj2 = RegionInjector(skip_missing=True)
    inj2._old_blocks["f.sv"] = {"bogus": "x"}
    _, report = inj2.inject(RENDERED, {}, "f.sv")
    assert report.missing == ["bogus"]


# ════════════════════════════════════════════════════════════
# CLI 测试
# ════════════════════════════════════════════════════════════

def test_cli_version(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main(["--version"])
    assert exc_info.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_cli_clean_only_banner_signed(tmp_path, capsys):
    (tmp_path / "a.sv").write_text(BANNER_MARKER + "\n// gen\n", encoding="utf-8")
    (tmp_path / "b.sv").write_text("// hand written\n", encoding="utf-8")
    assert main(["-c", "-d", str(tmp_path)]) == 0
    assert not (tmp_path / "a.sv").exists()
    assert (tmp_path / "b.sv").exists()


def test_cli_merge_roundtrip_preserves_hand_edit(tmp_path):
    yaml_file = EXAMPLES / "apb_interface.yaml"
    dest = tmp_path / "out"
    src = tmp_path / "src"
    # 1) 首次生成
    assert main(["-i", str(yaml_file), "-d", str(dest), "-q"]) == 0
    # 2) 拷贝为 merge source 并手改 field_decl 区域
    shutil.copytree(dest, src)
    f = src / "agents" / "APB_agent" / "4_driver_monitor" / "APB_master_driver.sv"
    text = f.read_text(encoding="utf-8")
    text = text.replace(
        "  // pragma custom field_decl begin\n  // pragma custom field_decl end",
        "  // pragma custom field_decl begin\n  bit hand_flag;\n"
        "  // pragma custom field_decl end")
    f.write_text(text, encoding="utf-8")
    # 3) 合并生成 → 手改内容应被保留
    assert main(["-i", str(yaml_file), "-d", str(dest),
                 "-m", str(src), "--merge_no_backup", "-q"]) == 0
    out = (dest / "agents" / "APB_agent" / "4_driver_monitor" / "APB_master_driver.sv"
           ).read_text(encoding="utf-8")
    assert "bit hand_flag;" in out


def test_cli_missing_block_raises_without_skip(tmp_path):
    yaml_file = EXAMPLES / "apb_interface.yaml"
    dest = tmp_path / "out"
    src = tmp_path / "src"
    assert main(["-i", str(yaml_file), "-d", str(dest), "-q"]) == 0
    shutil.copytree(dest, src)
    f = src / "agents" / "APB_agent" / "4_driver_monitor" / "APB_master_driver.sv"
    text = f.read_text(encoding="utf-8")
    text = text.replace(
        "  // pragma custom field_decl begin",
        "  // pragma custom bogus_slot begin\n  // pragma custom bogus_slot end\n"
        "  // pragma custom field_decl begin")
    f.write_text(text, encoding="utf-8")
    assert main(["-i", str(yaml_file), "-d", str(dest),
                 "-m", str(src), "--merge_no_backup", "-q"]) == 1
    assert main(["-i", str(yaml_file), "-d", str(dest),
                 "-m", str(src), "--merge_no_backup", "-s", "-q"]) == 0


# ════════════════════════════════════════════════════════════
# UVM Harness（bind 式）测试
# ════════════════════════════════════════════════════════════

def _render_harness(data):
    h = _normalize_harness(data)
    ctx = {"harness": h, **h.to_context()}
    return _JinjaRenderer(_TEMPLATES_DIR).render("bench_templates/harness.sv.j2", ctx)


def test_harness_bind_style():
    out = _render_harness({
        "name": "apb_harness", "bind_to": "apb_slave_dut", "style": "bind",
        "interfaces": [{"name": "apb_if", "type": "apb_interface",
                        "agent_path": "apb_master_agent_h",
                        "connections": {"pclk": "pclk", "presetn": "presetn"}}],
    })
    assert "bind apb_slave_dut apb_interface apb_if(.pclk(pclk), .presetn(presetn));" in out
    # set_vifs 向上查找 + 通配符
    assert 'uvm_config_db#(virtual apb_interface)::set(null, {path, ".apb_master_agent_h.*"}, "vif", apb_slave_dut.apb_if);' in out
    assert "bind apb_slave_dut apb_harness harness();" in out


def test_harness_inside_array_parameter_sub():
    out = _render_harness({
        "name": "reg_top_harness", "bind_to": "RegTopModule", "style": "inside",
        "parameter": "NUM_CLIENTS",
        "interfaces": [{"name": "reg_if", "type": "reg_interface", "agent_path": "reg_a",
                        "count": "NUM_CLIENTS",
                        "connections": {"clk": "SysClk"}}],
        "sub_harnesses": [{"path": "chip_module.math.harness", "env_path": ".math_env"}],
    })
    assert "interface reg_top_harness#(parameter int NUM_CLIENTS = 1)();" in out
    assert "reg_interface reg_if[NUM_CLIENTS-1:0](.clk(RegTopModule.SysClk));" in out
    assert "virtual interface reg_interface vif_0[NUM_CLIENTS];" in out
    assert '".reg_a["' in out and '"vif", vif_0[i]);' in out
    assert "chip_module.math.harness.set_vifs({path, \".math_env\"});" in out
    assert "bind RegTopModule reg_top_harness#(.NUM_CLIENTS(NUM_CLIENTS)) harness();" in out


def test_harness_multi_instance_source_path():
    out = _render_harness({
        "name": "mc_harness", "bind_to": "math_coprocessor_module", "style": "bind",
        "interfaces": [{"name": "mem_if", "type": "mem_interface", "bind_to": "memory_module",
                        "agent_path": "mem_agent[0]", "source_path": "cache.memory",
                        "connections": {"clk": "clk"}}],
    })
    assert "bind memory_module mem_interface mem_if(.clk(clk));" in out
    assert "vif\", memory_module.cache.memory.mem_if);" in out


def test_harness_generate_uvm_tool_type():
    from src.tools.uvm_tools.tool_uvm.gen_uvm import generate_uvm
    out = generate_uvm("harness", "harness:\n  name: h1\n  bind_to: dut_mod\n"
                        "  interfaces:\n"
                        "    - { name: i1, type: if1, agent_path: ag, connections: { clk: clk } }\n")
    assert out.startswith("Harness: h1") and "h1.sv" in out


def test_env_agents_is_master_and_is_active(tmp_path):
    """env agents 的 is_master/is_active：gen_test 按角色声明序列，
    test_base 按 is_active 渲染模式、slave 不启动序列。"""
    import yaml
    src = yaml.safe_load((EXAMPLES / "apb_env.yaml").read_text(encoding="utf-8"))
    src["environment"]["agents"] = [
        {"type": "apb_master_agent", "is_active": True, "is_master": True},
        {"type": "apb_slave_agent", "is_active": False, "is_master": False},
    ]
    tmp_yaml = tmp_path / "env_slave.yaml"
    tmp_yaml.write_text(yaml.safe_dump(src, allow_unicode=True, sort_keys=False),
                        encoding="utf-8")
    dest = tmp_path / "out"
    assert main(["-i", str(tmp_yaml), "-d", str(dest), "-q"]) == 0
    gen = (dest / "env" / "tests" / "APB_env_gen_test.sv").read_text(encoding="utf-8")
    base = (dest / "env" / "tests" / "APB_env_base_test.sv").read_text(encoding="utf-8")
    assert "apb_master_master_sequence apb_master_master_seq;" in gen
    assert "apb_slave_slave_sequence apb_slave_slave_seq;" in gen
    assert "cfg.apb_master_cfg.is_active = UVM_ACTIVE;" in base
    assert "cfg.apb_slave_cfg.is_active = UVM_PASSIVE;" in base
    assert "apb_master_seq.start(env.apb_master_agent_h.sqr);" in base
    assert "apb_slave_seq.start" not in base


def test_bench_with_harness_skips_tb_top_interface(tmp_path):
    """bench.harness 存在时：tb_top 不实例化接口/config_db set，harness 文件生成。"""
    yaml_file = EXAMPLES / "apb_bench.yaml"
    dest = tmp_path / "out"
    assert main(["-i", str(yaml_file), "-d", str(dest), "-q"]) == 0
    tb = (dest / "bench" / "APB_bench_tb_top.sv").read_text(encoding="utf-8")
    assert "apb_interface apb_if" not in tb
    assert "uvm_config_db#(virtual" not in tb
    harness = (dest / "bench" / "apb_harness.sv").read_text(encoding="utf-8")
    assert "bind apb_slave_dut apb_interface apb_if(" in harness
    assert "function void set_vifs" in harness


def test_meta_header_default_and_yaml_override(tmp_path):
    """所有生成文件继承 base_template.sv.j2 文件头；YAML meta 可覆盖。"""
    import yaml
    # 默认 meta
    dest1 = tmp_path / "o1"
    assert main(["-i", str(EXAMPLES / "apb_interface.yaml"), "-d", str(dest1), "-q"]) == 0
    sv = (dest1 / "agents" / "APB_agent" / "1_interface" / "APB_if.sv").read_text(encoding="utf-8")
    assert "SignOffAI（功能签核） — 商标与权利声明" in sv
    assert "文件:     APB_if.sv" in sv
    assert "创建时间:" in sv and "修改时间:" in sv and "联系邮箱:" in sv and "描述:" in sv
    # Makefile 用 # 注释
    mk = (dest1 / "agents" / "APB_agent" / "Makefile").read_text(encoding="utf-8")
    assert "\n#   SignOffAI" in mk
    assert "//   SignOffAI" not in mk
    # YAML meta 覆盖
    src = yaml.safe_load((EXAMPLES / "apb_interface.yaml").read_text(encoding="utf-8"))
    src["meta"] = {"author": "张三", "email": "zhangsan@example.com", "created": "2026-09-01"}
    tmp_yaml = tmp_path / "if_meta.yaml"
    tmp_yaml.write_text(yaml.safe_dump(src, allow_unicode=True, sort_keys=False),
                        encoding="utf-8")
    dest2 = tmp_path / "o2"
    assert main(["-i", str(tmp_yaml), "-d", str(dest2), "-q"]) == 0
    sv2 = (dest2 / "agents" / "APB_agent" / "1_interface" / "APB_if.sv").read_text(encoding="utf-8")
    assert "作者:     张三" in sv2
    assert "联系邮箱: zhangsan@example.com" in sv2
    assert "创建时间: 2026-09-01" in sv2


def test_cli_generate_filter_and_skip(tmp_path, capsys):
    yaml_file = EXAMPLES / "apb_interface.yaml"
    dest = tmp_path / "out"
    assert main(["-i", str(yaml_file), "-d", str(dest), "-q"]) == 0
    # 默认跳过已存在文件
    assert main(["-i", str(yaml_file), "-d", str(dest), "-q"]) == 0
    capsys.readouterr()
    assert main(["-i", str(yaml_file), "-d", str(dest)]) == 0
    out = capsys.readouterr().out
    assert "skipped" in out
    # -g 不存在 → SystemExit 报错
    with pytest.raises(SystemExit):
        main(["-i", str(yaml_file), "-d", str(dest), "-g", "NOPE", "-q"])
