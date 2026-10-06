"""参考模型比对接线 —— 门禁判据 + env.yaml 接线 + predictor 真的不是空壳。

## 这条链为什么值得单独钉

「参考模型比对」曾经**断过一次**，而且断得很难看：`util_comp.sv.j2` 生成的
`process_<port>` 是个 `// TODO: override in derived class` 的空壳，它永不写
`out_port`。接上 scoreboard 之后 expected 侧恒为 0、actual 是一堆真事务 ——
于是每条用例都报 `scoreboard FAILED: extras=N`。那是**我们自己造出来的假失败**，
比"没有比对"糟得多：它会让整条回归的结论不可信。`examples/apb/apb_env.yaml`
里那段注释记的就是这一次。

所以这里钉三件事：

  1. 门禁**不能只凭黄金命中**就接 —— `match_golden()` 只按协议/信号名匹配，
     而本仓库自己的 `apb_uart` 就是个"长得像 APB、但 prdata 来自 FIFO"的设计
     （`assign prdata = fifo_rdata;`）。给它接寄存器镜像，每读一次错一次。
  2. 门禁**只在有证据**（registers 非空且全 RW）时放行。
  3. 放行时，渲染出来的 predictor **真的实现了镜像**（写更新、读给期望值、
     复位清零），而不是又退回 TODO 空壳。
"""
import json

import yaml

from src.tools.uvm_tools.tool_find_spec_yaml.main import (
    _gen_env_yaml,
    _ref_mirror_gate,
)
from src.tools.uvm_tools.tool_uvm.gen_uvm import TEMPLATES_DIR, JinjaRenderer

#: 一份像模像样的 APB 接口表（名字与 `apb_uart` 的 spec 一致）
APB_IFACES = [
    {"name": "pclk", "direction": "input", "protocol": "Clock"},
    {"name": "preset_n", "direction": "input", "protocol": "Reset"},
    {"name": "paddr[7:0]", "direction": "input", "protocol": "APB"},
    {"name": "pwdata[7:0]", "direction": "input", "protocol": "APB"},
    {"name": "prdata[7:0]", "direction": "output", "protocol": "APB"},
    {"name": "pwrite", "direction": "input", "protocol": "APB"},
    {"name": "psel", "direction": "input", "protocol": "APB"},
    {"name": "penable", "direction": "input", "protocol": "APB"},
]

AGENTS_SPEC = [
    ({"name": "apb_master", "interface": "apb", "is_master": True,
      "type": "apb_master_agent"}, {"name": "apb"}),
]


def _regs(*accesses):
    return [{"offset": f"0x{i:02x}", "name": f"R{i}", "width": 8, "access": a}
            for i, a in enumerate(accesses)]


class TestGateRefusesWithoutEvidence:
    """没证据就不接 —— 少一个比对是缺功能，接错一个是把结论弄脏。"""

    def test_no_registers_is_refused(self):
        """本仓库自己的 `apb_uart` 就是这种：长得像 APB，但没有寄存器语义证据。

        它命中 `apb_slave` 纯粹是因为接口名字里有 `paddr/prdata`（`match_golden`
        只按协议/名字匹配）。真接上去，读事务会逐条 mismatch —— 因为生成物里
        `prdata` 是 FIFO 直出的，不是寄存器堆。
        """
        assert _ref_mirror_gate("apb_uart", APB_IFACES, []) is None

    def test_ro_register_is_refused(self):
        """有只读寄存器 → 镜像读出来的期望值必然与 DUT 的真行为对不上。"""
        assert _ref_mirror_gate("dut", APB_IFACES, _regs("RW", "RO")) is None

    def test_wo_register_is_refused(self):
        assert _ref_mirror_gate("dut", APB_IFACES, _regs("RW", "WO")) is None

    def test_non_apb_design_is_refused(self):
        """没有 APB 迹象 → 黄金命中不了 → 不接。"""
        uart_only = [{"name": "clk", "direction": "input", "protocol": "Clock"},
                     {"name": "tx", "direction": "output", "protocol": "UART"}]
        assert _ref_mirror_gate("uart", uart_only, _regs("RW")) is None


class TestGateAcceptsARealRegisterFile:
    def test_all_rw_is_accepted(self):
        got = _ref_mirror_gate("dut", APB_IFACES, _regs("RW", "RW"))
        assert got is not None
        assert got["nregs"] == 256          # 1 << addr_w(8)
        assert got["addr_w"] == 8
        assert got["data_w"] == 8
        assert "apb_slave" in got["source"]   # 出处要能回溯

    def test_widths_come_from_the_interfaces(self):
        ifs = [dict(i, name=i["name"].replace("[7:0]", "[15:0]"))
               for i in APB_IFACES]
        got = _ref_mirror_gate("dut", ifs, _regs("RW"))
        assert got["addr_w"] == 16 and got["data_w"] == 16
        assert got["nregs"] == 65536


class TestEmittedEnvYaml:
    def test_apb_uart_gets_no_scoreboard(self):
        """回归里的主力项目：门禁拦下，env.yaml 里**不该**出现 scoreboard。"""
        out = _gen_env_yaml("apb_uart", ["apb_master"], AGENTS_SPEC,
                            "pclk", "preset_n", [], APB_IFACES)
        assert "scoreboards:" not in out
        assert "tlm_connections:" not in out
        assert "util_components:" not in out

    def test_register_file_gets_the_full_wiring(self):
        out = _gen_env_yaml("dut", ["apb_master"], AGENTS_SPEC,
                            "pclk", "preset_n", _regs("RW", "RW"), APB_IFACES)
        doc = yaml.safe_load(out)                    # 必须是合法 YAML

        env = doc["environment"]
        assert env["analysis_components"] == [
            {"name": "apb_ref_pred", "type": "apb_ref_predictor"}]

        sb = env["scoreboards"][0]
        assert sb["name"] == "dut_scb"
        assert sb["sb_type"] == "in_order_scoreboard"
        assert sb["params"] == ["apb_master_seq_item", "apb_master_seq_item"]

        conns = {c["driver"]: c["receiver"] for c in env["tlm_connections"]}
        # actual 侧：DUT monitor 出的事务（env 模板建的 <agent>_agent_ap）
        assert conns["apb_master_agent_ap"] == "dut_scb.actual_export"
        # expected 侧：参考模型镜像
        assert conns["apb_ref_pred.out_port"] == "dut_scb.expected_export"

    def test_util_component_matches_the_analysis_component_type(self):
        """`analysis_components[].type` 必须**等于**生成的 util 类名 ——
        不然 env 模板渲染出一个不存在的类，`type_id::create` 直接编译不过。"""
        out = _gen_env_yaml("dut", ["apb_master"], AGENTS_SPEC,
                            "pclk", "preset_n", _regs("RW"), APB_IFACES)
        doc = yaml.safe_load(out)
        cls = doc["environment"]["analysis_components"][0]["type"]
        util = doc["util_components"][0]
        assert util["name"] == cls
        assert util["ref_model"]["nregs"] == 256


class TestPredictorIsNotAHollowStub:
    """渲染出来的 predictor 必须**真的**做镜像 —— 这是断链那一半的回归测试。"""

    def _render(self, with_mirror: bool) -> str:
        ctx = {
            "name": "apb_ref_predictor",
            "type": "uvm_component",
            "description": "",
            "analysis_exports": [{"name": "in_export",
                                  "type": "apb_master_seq_item"}],
            "analysis_ports": [{"name": "out_port",
                                "type": "apb_master_seq_item"}],
            "ref_model": ({"nregs": 256, "addr_w": 8, "data_w": 8,
                           "source": "golden apb_slave v1"} if with_mirror
                          else None),
        }
        return JinjaRenderer(TEMPLATES_DIR).render(
            "environment_templates/util_comp.sv.j2", ctx)

    def test_with_mirror_the_stub_is_gone(self):
        sv = self._render(with_mirror=True)
        assert "TODO: override in derived class" not in sv, \
            "镜像模式下不该再留空壳"
        # 镜像本体：寄存器数组 + 写更新 + 读给期望值 + 送到 out_port
        assert "m_regs" in sv
        assert "tr.pwrite" in sv and "m_regs[tr.paddr] = tr.pwdata" in sv
        assert "tr.prdata = (tr.paddr < 256) ? m_regs[tr.paddr] : '0;" in sv
        assert "send_output(tr);" in sv
        # 动态数组必须初始化，否则第一次读期望出 X → 假 mismatch
        assert "m_regs = new[256];" in sv
        assert "foreach (m_regs[i]) m_regs[i] = '0;" in sv

    def test_without_mirror_behaviour_is_unchanged(self):
        """不带 `ref_model` 的 util 组件：行为**逐字节不变**（还是空壳）。"""
        sv = self._render(with_mirror=False)
        assert "TODO: override in derived class" in sv
        assert "m_regs" not in sv
