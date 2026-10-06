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
    _normalize_agents_list,
    _normalize_harness,
    _normalize_scoreboards,
    _normalize_subenvs,
    main,
)

EXAMPLES = Path(__file__).parent / "examples" / "apb"


def _iface_name() -> str:
    """apb_interface.yaml 的 agent 名（= 生成类/目录前缀）。

    测试一律从这里取名字，不硬编码 —— 示例改大小写（APB ↔ apb）时测试不用动。
    """
    import yaml
    doc = yaml.safe_load((EXAMPLES / "apb_interface.yaml").read_text(encoding="utf-8"))
    return doc["interfaces"][0]["name"]


def _env_name() -> str:
    """apb_env.yaml 的 environment 名（= env 产物前缀）。"""
    import yaml
    doc = yaml.safe_load((EXAMPLES / "apb_env.yaml").read_text(encoding="utf-8"))
    return doc["environment"]["name"]


def _bench_name() -> str:
    """apb_bench.yaml 的 bench 名（= tb_top 文件名前缀）。"""
    import yaml
    doc = yaml.safe_load((EXAMPLES / "apb_bench.yaml").read_text(encoding="utf-8"))
    return doc["bench"]["name"]

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


def test_harness_bind_render():
    out = _render_harness({
        "name": "apb_harness", "bind_to": "apb_slave_dut",
        "interfaces": [{"name": "apb_if", "type": "apb_interface",
                        "agent_path": "apb_master_agent_h",
                        "connections": {"pclk": "pclk", "presetn": "presetn"}}],
    })
    assert "apb_interface apb_if(.pclk(pclk), .presetn(presetn));" in out
    # set_vifs 引用 harness 内实例化的 interface + 通配符
    assert 'uvm_config_db#(virtual apb_interface)::set(null, {path, ".apb_master_agent_h.*"}, "vif", apb_if);' in out
    assert "bind apb_slave_dut apb_harness harness();" in out


def test_harness_force_block_default():
    """每个 interface 自动生成 force/release 块，控制信号缺省 0（无需 YAML 配置）。"""
    out = _render_harness({
        "name": "h1", "bind_to": "dut",
        "interfaces": [{"name": "dut_if", "type": "dut_interface",
                        "agent_path": "a", "connections": {"clk": "clk", "data": "din"}}],
    })
    assert "logic dut_if_force_en = 0;" in out
    assert "force din = dut_if.data;" in out
    assert "release din;" in out
    assert "force clk = dut_if.clk;" in out


def test_harness_array_parameter_sub():
    out = _render_harness({
        "name": "reg_top_harness", "bind_to": "RegTopModule",
        "parameter": "NUM_CLIENTS",
        "interfaces": [{"name": "reg_if", "type": "reg_interface", "agent_path": "reg_a",
                        "count": "NUM_CLIENTS",
                        "connections": {"clk": "SysClk"}}],
        "sub_harnesses": [{"path": "chip_module.math.harness", "env_path": ".math_env"}],
    })
    assert "interface reg_top_harness#(parameter int NUM_CLIENTS = 1)();" in out
    assert "reg_interface reg_if[NUM_CLIENTS-1:0](.clk(SysClk));" in out
    assert "virtual interface reg_interface vif_0[NUM_CLIENTS];" in out
    assert "vif_0 = reg_if;" in out
    assert '".reg_a["' in out and '"vif", vif_0[i]);' in out
    assert "chip_module.math.harness.set_vifs({path, \".math_env\"});" in out
    assert "bind RegTopModule reg_top_harness#(.NUM_CLIENTS(NUM_CLIENTS)) harness();" in out


def test_harness_multi_instance_source_path():
    out = _render_harness({
        "name": "mc_harness", "bind_to": "math_coprocessor_module",
        "interfaces": [{"name": "mem_if", "type": "mem_interface", "bind_to": "memory_module",
                        "agent_path": "mem_agent[0]", "source_path": "cache.memory",
                        "connections": {"clk": "clk"}}],
    })
    assert "mem_interface mem_if(.clk(clk));" in out
    assert "vif\", mem_if);" in out


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
    # agent 类名走 type 显式声明（不由 interface + is_master 拼接）
    src["environment"]["agents"] = [
        {"name": "apb_master", "type": "apb_master_agent",
         "is_active": True, "is_master": True},
        {"name": "apb_slave", "type": "apb_slave_agent",
         "is_active": False, "is_master": False},
    ]
    tmp_yaml = tmp_path / "env_slave.yaml"
    tmp_yaml.write_text(yaml.safe_dump(src, allow_unicode=True, sort_keys=False),
                        encoding="utf-8")
    dest = tmp_path / "out"
    assert main(["-i", str(tmp_yaml), "-d", str(dest), "-q"]) == 0
    gen = (dest / "env" / "tests" / "APB_env_gen_test.sv").read_text(encoding="utf-8")
    base = (dest / "env" / "tests" / "APB_env_base_test.sv").read_text(encoding="utf-8")
    assert "apb_master_sequence apb_master_seq;" in gen
    assert "apb_slave_sequence apb_slave_seq;" in gen
    assert "cfg.apb_master_cfg.is_active = UVM_ACTIVE;" in base
    assert "cfg.apb_slave_cfg.is_active = UVM_PASSIVE;" in base
    assert "apb_master_seq.start(env.apb_master_agent_h.sequencer);" in base
    assert "apb_slave_seq.start" not in base


def test_env_agent_type_not_derived_from_interface():
    """agent 类名只认 YAML 的 type；不由 interface + is_master 拼 {iface}_{master|slave}_agent。"""
    out = _normalize_agents_list(
        [{"name": "apb_master", "interface": "apb", "is_master": True}])
    assert "type" not in out[0]
    out2 = _normalize_agents_list(
        [{"name": "apb_master", "type": "my_agent", "interface": "apb", "is_master": True}])
    assert out2[0]["type"] == "my_agent"   # 显式 type 原样保留，不被拼接覆盖


def test_subenv_type_not_derived_from_interface():
    """subenv 类名只认 YAML 的 type；不由 interface 拼 {iface}_system_env。"""
    out = _normalize_subenvs([{"name": "apb_sys_env", "interface": "apb"}])
    assert out[0]["type"] == "apb_sys_env"        # 退回 name，而非 apb_system_env
    out2 = _normalize_subenvs([{"name": "e", "type": "foo_system_env", "interface": "apb"}])
    assert out2[0]["type"] == "foo_system_env"


def test_explicit_agent_type_wins_in_generation(tmp_path):
    """端到端：显式 type 渲染进 env.sv 的句柄与实例化。"""
    import yaml
    src = yaml.safe_load((EXAMPLES / "apb_env.yaml").read_text(encoding="utf-8"))
    src["environment"]["agents"] = [
        {"name": "apb_master", "type": "apb_master_agent",
         "is_active": True, "is_master": True},
    ]
    tmp_yaml = tmp_path / "env_type.yaml"
    tmp_yaml.write_text(yaml.safe_dump(src, allow_unicode=True, sort_keys=False),
                        encoding="utf-8")
    dest = tmp_path / "out"
    assert main(["-i", str(tmp_yaml), "-d", str(dest), "-q"]) == 0
    env = (dest / "env" / "APB_env.sv").read_text(encoding="utf-8")
    assert "apb_master_agent apb_master_agent_h;" in env


def test_input_listfile_expands(tmp_path):
    """.f 清单文件（-f）展开成里面列的 YAML：注释/空行/编译选项行忽略。"""
    (tmp_path / "a.yaml").write_text("interfaces:\n  - {name: A}\n", encoding="utf-8")
    (tmp_path / "b.yaml").write_text("interfaces:\n  - {name: B}\n", encoding="utf-8")
    lf = tmp_path / "list.f"
    lf.write_text(
        "# 注释行\n"
        "a.yaml\n"            # 相对路径 → 按清单文件所在目录解析
        f"{tmp_path / 'b.yaml'}\n"   # 绝对路径原样
        "\n"
        "+incdir+somewhere\n"        # 编译选项行忽略
        "-timescale 1ns/1ps\n",
        encoding="utf-8")
    got = YAMLLoader.collect_paths([lf])
    assert [p.name for p in got] == ["a.yaml", "b.yaml"]
    assert all(p.exists() for p in got)


def test_input_listfile_end_to_end(tmp_path):
    """端到端：-f 传 .f 能真的生成（不再报 No YAML files were found）。"""
    src = EXAMPLES
    lf = tmp_path / "apb.f"
    lf.write_text("\n".join(str(src / n) for n in (
        "apb_interface.yaml", "apb_env.yaml", "apb_bench.yaml")) + "\n",
        encoding="utf-8")
    dest = tmp_path / "out"
    assert main(["-f", str(lf), "-d", str(dest), "-q"]) == 0
    assert (dest / "env" / "APB_env.sv").exists()


def test_bench_tb_top_instantiates_interface_and_dut(tmp_path):
    """bench.interfaces + dut_module：tb_top 例化接口与 DUT，端口同名直连。"""  # noqa: E501
    yaml_file = EXAMPLES / "apb_bench.yaml"
    dest = tmp_path / "out"
    assert main(["-i", str(yaml_file), "-d", str(dest), "-q"]) == 0
    tb = (dest / "bench" / "APB_bench_tb_top.sv").read_text(encoding="utf-8")
    # 接口由 tb_top **直接例化**（bind 式 harness 已退役，模板里不再有 harness 分支）
    assert "apb_if apb_if_inst(" in tb
    # DUT 也由 tb_top 例化：模块名 bench.dut_module，实例名 bench.dut_instance，
    # 端口**按同名**直连接口实例
    assert "apb_slave_dut u_dut (" in tb
    assert ".paddr(apb_if_inst.paddr)" in tb
    assert ".prdata(apb_if_inst.prdata)" in tb
    # clk/rst 由 clk_rst_if 接口承载（环境 clk_rst_agent 驱动），DUT 端口直接接 vif
    assert ".pclk(pclk_vif.clk[0])" in tb
    assert ".presetn(pclk_vif.rst_n[0])" in tb
    assert "clk_rst_if pclk_vif();" in tb
    assert "always #" not in tb
    # vif 广播给各 agent（路径带通配，env 挂哪层都找得到）
    assert 'uvm_config_db#(virtual apb_if)::set(null, "*.apb_master_agent_h*", "vif"' in tb
    assert 'uvm_config_db#(virtual clk_rst_if)::set(null, "*", "pclk_vif"' in tb
    # 系统接口必须**实例化**：agent 包的 *_system_env / *_system_monitor 里
    # 引用 `virtual apb_system_if`，设计里没有它的实例时 Questa load 阶段报
    # vsim-8451，整个设计加载不了
    assert "apb_system_if apb_if_sys_if_inst();" in tb
    # 不再产 harness 文件
    assert not (dest / "bench" / "apb_harness.sv").exists()


def test_normalize_scoreboards_parameterized_class():
    """参数化类给 params：推导 typedef 别名，句柄改用别名。"""
    out = _normalize_scoreboards([{
        "name": "apb_scb", "sb_type": "in_order_scoreboard",
        "trans_type": "apb_master_seq_item",
        "params": ["apb_master_seq_item", "apb_master_seq_item"]}])
    assert out[0]["handle_type"] == "apb_scb_t"
    assert out[0]["typedef_decl"] == (
        "typedef in_order_scoreboard#(apb_master_seq_item, apb_master_seq_item) apb_scb_t;")
    # 非参数化：句柄直接用 sb_type，不产生 typedef
    out2 = _normalize_scoreboards([{"name": "s", "sb_type": "uvmf_in_order_scoreboard"}])
    assert out2[0]["handle_type"] == "uvmf_in_order_scoreboard"
    assert out2[0]["typedef_decl"] == ""
    # 没给 sb_type 时不硬造 typedef
    out3 = _normalize_scoreboards([{"name": "s2", "params": ["T"]}])
    assert out3[0]["typedef_decl"] == ""


def test_parameterized_scoreboard_typedef_in_env(tmp_path):
    """端到端：参数化 scoreboard 在 env.sv 里先 typedef 再声明句柄。"""
    import yaml
    cfg = yaml.safe_load((EXAMPLES / "apb_env.yaml").read_text(encoding="utf-8"))
    cfg["environment"]["scoreboards"] = [{
        "name": "apb_scb", "sb_type": "in_order_scoreboard",
        "trans_type": "apb_master_seq_item",
        "params": ["apb_master_seq_item", "apb_master_seq_item"]}]
    p = tmp_path / "env_scb.yaml"
    p.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False),
                 encoding="utf-8")
    dest = tmp_path / "out"
    # 需要 interface 提供 seq_item 类型名，故与 interface 一起喂
    assert main(["-i", str(EXAMPLES / "apb_interface.yaml"), str(p),
                 "-d", str(dest), "-q"]) == 0
    env = (dest / "env" / "APB_env.sv").read_text(encoding="utf-8")
    assert ("typedef in_order_scoreboard#(apb_master_seq_item, apb_master_seq_item) "
            "apb_scb_t;") in env
    assert "apb_scb_t apb_scb;" in env
    assert "apb_scb_t::type_id::create" in env
    # 参数化类名不再被当类型直接用
    assert "\n  in_order_scoreboard apb_scb;" not in env


def test_bench_clk_rst_legacy_alias(tmp_path):
    """bench 时钟复位：旧名 clk_rst 与 clk_rst_if 等价（照样接进 tb_top）。"""
    import yaml
    cfg = yaml.safe_load((EXAMPLES / "apb_bench.yaml").read_text(encoding="utf-8"))
    bench = dict(cfg["bench"])
    bench["clk_rst"] = bench.pop("clk_rst_if")      # 换回旧名
    cfg["bench"] = bench
    p = tmp_path / "legacy_clk.yaml"
    p.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False),
                 encoding="utf-8")
    dest = tmp_path / "out"
    assert main(["-i", str(p), "-d", str(dest), "-q"]) == 0
    tb = (dest / "bench" / "APB_bench_tb_top.sv").read_text(encoding="utf-8")
    assert ".pclk(pclk_vif.clk[0])" in tb
    assert ".presetn(pclk_vif.rst_n[0])" in tb


def test_meta_header_default_and_yaml_override(tmp_path):
    """所有生成文件继承 base_template.sv.j2 文件头；YAML meta 可覆盖。"""
    import yaml
    # 默认 meta：必须剥掉示例里的 meta 块，否则测到的是被覆盖后的 company，
    # 而不是 DEFAULT_META（examples/apb/apb_interface.yaml 自带 meta）
    _src = yaml.safe_load((EXAMPLES / "apb_interface.yaml").read_text(encoding="utf-8"))
    _src.pop("meta", None)
    default_yaml = tmp_path / "if_no_meta.yaml"
    default_yaml.write_text(yaml.safe_dump(_src, allow_unicode=True, sort_keys=False),
                            encoding="utf-8")
    dest1 = tmp_path / "o1"
    assert main(["-i", str(default_yaml), "-d", str(dest1), "-q"]) == 0
    a = _iface_name()
    sv = (dest1 / "agents" / f"{a}_agent" / "1_interface" / f"{a}_if.sv").read_text(encoding="utf-8")
    assert "SignOffAI（功能签核） — 商标与权利声明" in sv
    assert f"文件:     {a}_if.sv" in sv
    assert "创建时间:" in sv and "修改时间:" in sv and "联系邮箱:" in sv and "描述:" in sv
    # Makefile 用 # 注释
    mk = (dest1 / "agents" / f"{a}_agent" / "Makefile").read_text(encoding="utf-8")
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
    sv2 = (dest2 / "agents" / f"{a}_agent" / "1_interface" / f"{a}_if.sv").read_text(encoding="utf-8")
    assert "作者:     张三" in sv2
    assert "联系邮箱: zhangsan@example.com" in sv2
    assert "创建时间: 2026-09-01" in sv2


# ════════════════════════════════════════════════════════════
# Config file 注册机制（factory 字段注册）测试
# ════════════════════════════════════════════════════════════

def test_config_field_registration_all_configs(tmp_path):
    """所有继承 uvm_object 的 config 类都注册 uvm_object_utils_begin/end + uvm_field_*。"""
    dest = tmp_path / "out"
    assert main(["-i", str(EXAMPLES / "apb_interface.yaml"), "-d", str(dest), "-q"]) == 0
    agent_dir = dest / "agents" / "APB_agent"
    port = (agent_dir / "2_config" / "APB_port_config.sv").read_text(encoding="utf-8")
    system = (agent_dir / "5_agent" / "APB_system_config.sv").read_text(encoding="utf-8")
    for out in (port, system):
        assert "`uvm_object_utils_begin" in out
        assert "`uvm_object_utils_end" in out
        assert "`uvm_field_" in out
        assert "`uvm_object_utils(" not in out
    # vif 不支持 field 宏注册，注释说明
    assert "// vif: virtual interface，UVM field 宏不支持注册" in port
    # 单类 port_config：master 侧与 slave 侧字段注册并存
    assert "`uvm_field_enum(response_mode_e, response_mode, UVM_DEFAULT)" in port
    assert "`uvm_field_aa_int_int_unsigned(memory, UVM_DEFAULT)" in port
    assert "`uvm_field_aa_int_string(id_delay_map, UVM_DEFAULT)" in port
    assert "`uvm_field_int(drive_delay_min, UVM_DEFAULT)" in port
    # system：uvm_object 动态数组
    assert "`uvm_field_array_object(master_cfgs, UVM_DEFAULT)" in system


def test_env_config_field_registration(tmp_path):
    """env config 注册 config_vars + has_scoreboard + agent cfg 句柄。"""
    dest = tmp_path / "out"
    assert main(["-i", str(EXAMPLES / "apb_env.yaml"), "-d", str(dest), "-q"]) == 0
    e = _env_name()
    cfg = (dest / "env" / f"{e}_config.sv").read_text(encoding="utf-8")
    assert f"`uvm_object_utils_begin({e}_config)" in cfg
    assert "`uvm_field_int(has_scoreboard, UVM_DEFAULT)" in cfg
    assert "`uvm_field_object(apb_master_cfg, UVM_DEFAULT)" in cfg
    assert "`uvm_field_object(apb_slave_cfg, UVM_DEFAULT)" in cfg


def test_constraint_and_bench_env_name_backfilled(tmp_path):
    """env_name 下线的连带影响：bench / constraint 不写 env 名时，
    由本次解析出的 environment 回填 —— 产物前缀不能是空的。"""
    dest = tmp_path / "out"
    assert main(["-i", str(EXAMPLES / "apb_interface.yaml"),
                 str(EXAMPLES / "apb_env.yaml"),
                 str(EXAMPLES / "apb_bench.yaml"),
                 str(EXAMPLES / "apb_constraint.yaml"),
                 "-d", str(dest), "-q"]) == 0
    e = _env_name()
    assert (dest / "env" / "cons" / f"{e}_constraint_policy.sv").exists()
    tb = (dest / "bench" / f"{_bench_name()}_tb_top.sv").read_text(encoding="utf-8")
    assert f"import {e}_test_pkg::*;" in tb


def test_seq_item_field_registration(tmp_path):
    """seq_item 注册各自的 uvm_object_utils_begin/end；共用部分（xact_type +
    base_transaction_vars）落在基类 APB_base_seq_item，master/slave 继承它。"""
    dest = tmp_path / "out"
    assert main(["-i", str(EXAMPLES / "apb_interface.yaml"), "-d", str(dest), "-q"]) == 0
    a = _iface_name()
    tx_dir = dest / "agents" / f"{a}_agent" / "3_transaction_sequencer"
    base = (tx_dir / f"{a}_base_seq_item.sv").read_text(encoding="utf-8")
    master = (tx_dir / f"{a}_master_seq_item.sv").read_text(encoding="utf-8")
    slave = (tx_dir / f"{a}_slave_seq_item.sv").read_text(encoding="utf-8")
    for out in (base, master, slave):
        assert "`uvm_object_utils_begin" in out
        assert "`uvm_object_utils_end" in out
        assert "`uvm_object_utils(" not in out
    # base：xact_type enum + base_transaction_vars（两侧共用），且直接继承 uvm_sequence_item
    assert f"class {a}_base_seq_item extends uvm_sequence_item;" in base
    assert "`uvm_field_enum(xact_type_e, xact_type, UVM_DEFAULT)" in base
    assert "`uvm_field_int(addr, UVM_DEFAULT)" in base
    assert "`uvm_field_int(data, UVM_DEFAULT)" in base
    # master/slave 继承基类，只注册各自专有字段
    assert f"class {a}_master_seq_item extends {a}_base_seq_item;" in master
    assert f"class {a}_slave_seq_item extends {a}_base_seq_item;" in slave
    # xact_type 已上移到基类，派生类里不应再重复声明/注册
    for out in (master, slave):
        assert "`uvm_field_enum(xact_type_e, xact_type" not in out
        assert "typedef enum {READ, WRITE} xact_type_e;" not in out
    # master：按 is_master 划分的两组事务字段
    assert "`uvm_field_int(paddr, UVM_DEFAULT)" in master
    assert "`uvm_field_int(prdata, UVM_DEFAULT)" in master
    # slave：额外响应控制指令字段
    assert "`uvm_field_int(delay_cycles, UVM_DEFAULT)" in slave
    assert "`uvm_field_int(force_resp, UVM_DEFAULT)" in slave
    assert "`uvm_field_int(override_rdata, UVM_DEFAULT)" in slave


def test_config_vars_field_macro_mapping():
    """config_vars 类型 → uvm_field_* 映射：整型→int、string→string、其余→enum。"""
    r = _JinjaRenderer(_TEMPLATES_DIR)
    ctx = {
        "environment": {"env_name": "T_env"},
        "agents": [],
        "config_vars": [
            {"type": "int", "name": "a"},
            {"type": "bit [7:0]", "name": "b"},
            {"type": "string", "name": "c"},
            {"type": "MyEnum_e", "name": "d"},
        ],
        "config_constraints": [],
    }
    out = r.render("environment_templates/env_config.sv.j2", ctx)
    assert "`uvm_field_int(a, UVM_DEFAULT)" in out
    assert "`uvm_field_int(b, UVM_DEFAULT)" in out
    assert "`uvm_field_string(c, UVM_DEFAULT)" in out
    assert "`uvm_field_enum(MyEnum_e, d, UVM_DEFAULT)" in out


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


# ════════════════════════════════════════════════════════════
# 属性测试：一条 environment.tests = 一个 UVM_TEST = 一个属性取值
# ════════════════════════════════════════════════════════════

from src.tools.uvm_tools.tool_uvm.gen_uvm import (   # noqa: E402
    EnvironmentModel, _normalize_tests, attr_class_slug, attr_int_value, attr_key,
)

RATIO_TESTS = [
    {"dimension": "D_ratio", "value": "0", "key": "fc_ratio", "int_value": 0},
    {"dimension": "D_ratio", "value": "10", "key": "fc_ratio", "int_value": 10},
    {"dimension": "D_ratio", "value": "50", "key": "fc_ratio", "int_value": 50},
    {"dimension": "D_mode", "value": "首拍", "key": "fc_mode", "int_value": 1},
]


def _env_spec_with_tests(tests):
    """apb_env.yaml 加一段 tests: —— 其余原样，保证只测新东西。"""
    import yaml
    doc = yaml.safe_load((EXAMPLES / "apb_env.yaml").read_text(encoding="utf-8"))
    doc["environment"]["tests"] = tests
    return doc


def _generate(tmp_path, tests, name="env_tests.yaml"):
    import yaml
    src = tmp_path / name
    src.write_text(yaml.safe_dump(_env_spec_with_tests(tests), allow_unicode=True,
                                  sort_keys=False), encoding="utf-8")
    dest = tmp_path / f"out_{src.stem}"
    assert main(["-i", str(src), "-d", str(dest), "-q"]) == 0
    return dest


class TestNormalizeTests:
    def test_empty_shapes(self):
        for raw in (None, "", [], "x", {}):
            assert _normalize_tests(raw) == []

    def test_drops_entries_missing_dimension_or_value(self):
        assert _normalize_tests([
            {"dimension": "D"},
            {"value": "1"},
            "not-a-dict",
            {"dimension": "D", "value": "1"},
        ]) == [{"dimension": "D", "value": "1", "key": "", "int_value": None, "base": ""}]

    def test_keeps_int_zero_distinct_from_absent(self):
        """`int_value: 0` 和「没给」是两回事 —— 前者是给定的值，后者要推导。"""
        kept = _normalize_tests([{"dimension": "D", "value": "0", "int_value": 0}])
        assert kept[0]["int_value"] == 0
        assert _normalize_tests([{"dimension": "D", "value": "0"}])[0]["int_value"] is None

    def test_environment_model_exposes_it(self):
        env = EnvironmentModel(name="e", env_name="e", tests=_normalize_tests(RATIO_TESTS))
        assert env.to_context()["tests"][0]["dimension"] == "D_ratio"

    def test_default_is_empty(self):
        assert EnvironmentModel(name="e", env_name="e").to_context()["tests"] == []


class TestAttrFilters:
    def test_explicit_key_wins_verbatim(self):
        assert attr_key({"dimension": "D_ratio", "key": "FC_Ratio"}) == "FC_Ratio"

    def test_key_derived_from_dimension_is_ascii(self):
        key = attr_key({"dimension": "反压比例"})
        assert key.isascii() and key

    def test_int_value_prefers_explicit(self):
        assert attr_int_value({"value": "x", "int_value": 7}) == 7

    def test_int_value_parses_numeric_token(self):
        assert attr_int_value({"value": "50"}) == 50

    def test_int_value_falls_back_to_zero(self):
        assert attr_int_value({"value": "首拍"}) == 0

    def test_ascii_value_keeps_its_own_slug(self):
        assert attr_class_slug({"dimension": "D_ratio", "value": "50"}) == "d_ratio_p50"

    def test_non_ascii_value_projects_through_int_value(self):
        slug = attr_class_slug({"dimension": "D_mode", "value": "首拍", "int_value": 1})
        assert slug == "d_mode_p1"

    def test_slug_is_always_a_valid_identifier(self):
        import re
        for entry in ({"dimension": "D_ratio", "value": "50"},
                      {"dimension": "反压模式", "value": "首拍", "int_value": 2},
                      {"dimension": "反压模式", "value": "尾拍"}):
            assert re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*",
                                attr_class_slug(entry)), entry

    def test_two_non_ascii_values_without_int_do_not_collide(self):
        """两个中文取值都没给 int_value 时不能撞成同一个类名 —— 那是编译错误。"""
        a = attr_class_slug({"dimension": "m", "value": "首拍"})
        b = attr_class_slug({"dimension": "m", "value": "尾拍"})
        assert a != b


class TestRenderedAttrTests:
    def test_one_class_per_attribute_value(self, tmp_path):
        dest = _generate(tmp_path, RATIO_TESTS)
        text = (dest / "env" / "tests" / f"{_iface_name()}_env_attr_test.sv") \
            .read_text(encoding="utf-8") if False else None
        attr_files = list(dest.rglob("*_env_attr_test.sv"))
        assert len(attr_files) == 1
        body = attr_files[0].read_text(encoding="utf-8")
        invocations = [l for l in body.splitlines() if l.strip().startswith("`GEN_ATTR_TC(")]
        assert len(invocations) == len(RATIO_TESTS)

    def test_class_names_and_config_db_keys(self, tmp_path):
        dest = _generate(tmp_path, RATIO_TESTS)
        body = list(dest.rglob("*_env_attr_test.sv"))[0].read_text(encoding="utf-8")
        assert "_d_ratio_p50_test" in body
        assert "_d_mode_p1_test" in body
        assert '"fc_ratio"' in body and "50" in body

    def test_non_ascii_value_stays_out_of_sv_literals(self, tmp_path):
        """中文取值只进注释 —— 进字面量就是 locale 隐患。"""
        dest = _generate(tmp_path, RATIO_TESTS)
        body = list(dest.rglob("*_env_attr_test.sv"))[0].read_text(encoding="utf-8")
        for line in body.splitlines():
            code = line.split("//")[0]
            if 'uvm_config_db' in code or code.strip().startswith("`GEN_ATTR_TC("):
                assert "首拍" not in code, line

    def test_macro_body_uses_block_comments(self, tmp_path):
        """宏体内必须是 /* */：`//` 会把行尾的反斜杠一起吃掉，宏定义当场断掉。"""
        dest = _generate(tmp_path, RATIO_TESTS)
        body = list(dest.rglob("*_env_attr_test.sv"))[0].read_text(encoding="utf-8")
        macro = body[body.index("`define GEN_ATTR_TC"):body.index("endclass", body.index("`define GEN_ATTR_TC"))]
        for line in macro.splitlines():
            if line.rstrip().endswith("\\"):
                assert "//" not in line, f"宏体内出现 // 注释：{line}"

    def test_test_pkg_includes_the_attr_file(self, tmp_path):
        dest = _generate(tmp_path, RATIO_TESTS)
        pkg = list(dest.rglob("*_test_pkg.sv"))[0].read_text(encoding="utf-8")
        assert "_env_attr_test.sv" in pkg

    def test_get_pattern_is_documented(self, tmp_path):
        """消费方拿不到键名就没法用 —— 生成的类里必须带着精确的 ::get 示例。"""
        dest = _generate(tmp_path, RATIO_TESTS)
        body = list(dest.rglob("*_env_attr_test.sv"))[0].read_text(encoding="utf-8")
        assert 'uvm_config_db#(int)::get(this, "", "fc_ratio_int"' in body


class TestNoTestsRegression:
    """没有 tests: 的工程（apb）产物必须和以前一模一样。"""

    def test_no_attr_file_is_emitted(self, tmp_path):
        dest = tmp_path / "plain"
        assert main(["-i", str(EXAMPLES / "apb_env.yaml"), "-d", str(dest), "-q"]) == 0
        assert list(dest.rglob("*_attr_test.sv")) == []

    def test_test_pkg_does_not_mention_attr(self, tmp_path):
        dest = tmp_path / "plain2"
        assert main(["-i", str(EXAMPLES / "apb_env.yaml"), "-d", str(dest), "-q"]) == 0
        pkg = list(dest.rglob("*_test_pkg.sv"))[0].read_text(encoding="utf-8")
        assert "_attr_test" not in pkg

    def test_gen_test_still_carries_the_original_macro(self, tmp_path):
        """`GEN_TOP_TC` 是字符串宏，改它签名会打断所有既有调用 —— 钉住。"""
        dest = tmp_path / "plain3"
        assert main(["-i", str(EXAMPLES / "apb_env.yaml"), "-d", str(dest), "-q"]) == 0
        gen = list(dest.rglob("*_gen_test.sv"))[0].read_text(encoding="utf-8")
        assert "`define GEN_TOP_TC(tc_name, tc_com, tc_reg, tc_seq)" in gen


# ════════════════════════════════════════════════════════════
# interface 从端信号：对外 wire + TB 影子变量
# ════════════════════════════════════════════════════════════
#
# 从端驱动的信号（dir: input）在接口里是**两个名字**：
#   `<name>`     : 对外 wire（DUT 直连在这里，master monitor 采样它）
#   `<name>_slv` : TB 从端变量（缺省 'z），**slave_cb 的 output 驱动它**
#   `assign <name> = <name>_slv;`
#
# 这样每个变量只有一个驱动源：DUT 直连 `<name>` 时，`<name>_slv` 保持 'z、
# 让位给 DUT 的强驱动（wire 语义）。否则就回到老写法：从端时钟块直接 output
# `<name>`，只要 DUT 也直连它，vopt 就判 "multiply driven"，设计加载不了。
#
# slave_cb 的方向**永远**与 master_cb 相反（这是「反向驱动」），有没有 DUT 都一样。

_IFACE_PORTS = [
    {"name": "paddr", "dir": "output", "width": "8"},
    {"name": "prdata", "dir": "input", "width": "8"},
    {"name": "pslverr", "dir": "input", "width": "1"},
]


def _render_interface() -> str:
    ctx = {
        "agent": {"name": "apb", "clock": "pclk", "reset": "presetn",
                  "protocol": "apb"},
        "clock": "pclk",
        "reset": "presetn",
        "ports": _IFACE_PORTS,
    }
    return _JinjaRenderer(_TEMPLATES_DIR).render(
        "interface_templates/interface.sv.j2", ctx)


def _cb_body(text: str, name: str) -> str:
    return text.split(f"clocking {name}", 1)[1].split("endclocking", 1)[0]


def test_slave_clocking_block_drives_the_tb_shadow_variable():
    """slave_cb 方向与 master_cb 相反，驱动的是从端影子变量 `<sig>_slv`。"""
    cb = _cb_body(_render_interface(), "slave_cb")
    assert "output prdata_slv;" in cb
    assert "output pslverr_slv;" in cb
    assert "input  paddr;" in cb


def test_master_clocking_block_unchanged():
    cb = _cb_body(_render_interface(), "master_cb")
    assert "output paddr;" in cb
    assert "input  prdata;" in cb
    assert "input  pslverr;" in cb


def test_slave_side_signals_are_wire_with_z_default_shadow():
    """对外是 wire、影子变量缺省 'z，中间一条 assign —— 每变量单驱动源。"""
    text = _render_interface()
    assert "wire  [8-1:0] prdata;" in text
    assert "logic [8-1:0] prdata_slv = 'z;" in text
    assert "assign prdata = prdata_slv;" in text
    assert "wire  pslverr;" in text
    assert "logic pslverr_slv = 'z;" in text
    assert "assign pslverr = pslverr_slv;" in text
    # master 驱动的信号保持普通 logic（不需要影子变量）
    assert "logic [8-1:0] paddr;" in text
    assert "paddr_slv" not in text
