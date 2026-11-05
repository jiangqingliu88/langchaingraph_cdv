"""从生成出来的环境里读「接线」与「文件位置」—— 两处都必须读、不许猜。

这一组钉的是同一类错误的第二次和第三次复现：**一处改了布局/命名，另一处照旧猜**。

  · 覆盖率编译的 filelist 漏了 UVM 库（0% 覆盖率）—— 已由复用回归那份解决；
  · 补定向激励按平铺名找文件（每个 agent 都被跳过，产出 0 个文件，FAIL 20）；
  · 补激励写死 `{agent}_agent_h` / `{agent}_base_seq`（名字全不对，生成的代码
    编译不过，被 EDA 门禁退回空实现）。

上面三条的后果都是"看着跑了、其实没跑"。所以这里要么按布局读、要么如实返回
空/None，让调用方有机会说"没找到"。
"""
from __future__ import annotations

import pytest

from src.tools.common.lib.env_introspect import (binding_for_agent, env_agent_bindings)
from src.tools.common.lib.filelist import agent_layout

#: 生成器产出的真实布局（编号子目录）
ENV_SV = """\
class apb_uart_env extends uvm_env;
  apb_master_agent apb_agent_h;
  uart_master_agent uart_agent_h;
endclass
"""

AGENT_SV = """\
class apb_master_agent extends uvm_agent;
  apb_master_sequencer sequencer;
  apb_master_driver driver;
endclass
"""

SEQR_SV = """\
class apb_master_sequencer extends uvm_sequencer #(apb_master_seq_item);
endclass
"""

SEQ_ITEM_SV = """\
class apb_base_seq_item extends uvm_sequence_item;
  rand bit [7:0] paddr;
  rand bit pwrite;
endclass
"""


@pytest.fixture()
def run_dir(tmp_path):
    (tmp_path / "env").mkdir()
    (tmp_path / "env" / "apb_uart_env.sv").write_text(ENV_SV, encoding="utf-8")
    agent = tmp_path / "agents" / "apb_agent"
    (agent / "1_interface").mkdir(parents=True)
    (agent / "3_transaction_sequencer").mkdir()
    (agent / "5_agent").mkdir()
    (agent / "7_sequence").mkdir()
    (agent / "1_interface" / "apb_if.sv").write_text(
        "interface apb_if;\n  clocking master_cb;\n    output paddr;\n  endclocking\n"
        "endinterface\n", encoding="utf-8")
    (agent / "3_transaction_sequencer" / "apb_base_seq_item.sv").write_text(
        SEQ_ITEM_SV, encoding="utf-8")
    (agent / "3_transaction_sequencer" / "apb_master_sequencer.sv").write_text(
        SEQR_SV, encoding="utf-8")
    (agent / "5_agent" / "apb_master_agent.sv").write_text(AGENT_SV, encoding="utf-8")
    (agent / "7_sequence" / "apb_master_sequence.sv").write_text(
        "class apb_master_sequence extends uvm_sequence #(apb_base_seq_item);\n"
        "endclass\n", encoding="utf-8")
    (agent / "apb_pkg.sv").write_text("package apb_pkg;\nendpackage\n", encoding="utf-8")
    (agent / "apb_typedefs_pkg.sv").write_text("package apb_typedefs_pkg;\nendpackage\n",
                                               encoding="utf-8")
    return tmp_path


class TestAgentLayout:
    """`agent_layout` 认的是**编号子目录**布局（`1_interface/`、`3_transaction_sequencer/`）。"""

    def test_finds_files_in_the_numbered_layout(self, run_dir):
        layout = agent_layout(run_dir / "agents" / "apb_agent")
        assert [p.name for p in layout["interface"]] == ["apb_if.sv"]
        assert [p.name for p in layout["seq_items"]] == ["apb_base_seq_item.sv"]
        assert layout["package"].name == "apb_pkg.sv"     # 不是 _typedefs_pkg
        assert [p.name for p in layout["sequences"]] == ["apb_master_sequence.sv"]

    def test_missing_dir_yields_empty_not_error(self, tmp_path):
        layout = agent_layout(tmp_path / "nope")
        assert layout == {"interface": [], "seq_items": [], "package": None,
                          "sequences": []}

    def test_flat_layout_still_recognised(self, tmp_path):
        """旧布局（平铺名）也认 —— 目录里的老运行还在。"""
        d = tmp_path / "agent"
        d.mkdir()
        (d / "dut_in_interface.sv").write_text("interface dut_in_interface;\nendinterface\n",
                                               encoding="utf-8")
        (d / "dut_in_transaction.sv").write_text("class t;\nendclass\n", encoding="utf-8")
        (d / "dut_in_pkg.sv").write_text("package dut_in_pkg;\nendpackage\n", encoding="utf-8")
        layout = agent_layout(d)
        assert [p.name for p in layout["interface"]] == ["dut_in_interface.sv"]
        assert [p.name for p in layout["seq_items"]] == ["dut_in_transaction.sv"]
        assert layout["package"].name == "dut_in_pkg.sv"


class TestEnvAgentBindings:
    """接线（句柄 / 序列器成员 / 事务项类型）只能从文件里读出来。"""

    def test_resolves_handle_member_and_item(self, run_dir):
        bindings = env_agent_bindings(run_dir)
        apb = next(b for b in bindings if b["handle"] == "apb_agent_h")
        assert apb["agent_type"] == "apb_master_agent"
        assert apb["sequencer"] == "apb_master_sequencer"
        assert apb["item"] == "apb_master_seq_item"
        # 成员名模板给的是 `sequencer`（不是 uvm 惯用的 `sqr`）—— 也要读出来
        assert apb["member"] == "sequencer"
        assert "unresolved" not in apb

    def test_maps_agent_dir_to_handle(self, run_dir):
        bindings = env_agent_bindings(run_dir)
        assert binding_for_agent(bindings, "apb_agent")["handle"] == "apb_agent_h"
        assert binding_for_agent(bindings, "nope_agent") is None

    def test_unresolved_when_sequencer_type_is_unknown(self, tmp_path):
        """读不出事务项类型就如实标 unresolved —— 别让调用方拿它去生成代码。"""
        (tmp_path / "env").mkdir()
        (tmp_path / "env" / "x_env.sv").write_text(
            "class x_env;\n  y_agent y_agent_h;\nendclass\n", encoding="utf-8")
        (tmp_path / "agents").mkdir()
        (tmp_path / "agents" / "y.sv").write_text(
            "class y_agent extends uvm_agent;\n  y_sequencer sequencer;\nendclass\n",
            encoding="utf-8")
        bindings = env_agent_bindings(tmp_path)
        assert bindings and bindings[0].get("unresolved")
