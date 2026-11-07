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

from src.tools.generation.uvm_tools.tool_find_spec_yaml.main import (
    _gen_env_yaml,
    _ref_mirror_gate,
)
from src.tools.generation.uvm_tools.generation.constants import TEMPLATES_DIR
from src.tools.generation.uvm_tools.generation.render.jinja_renderer import JinjaRenderer

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


class TestGeneratorForwardsTheModelBody:
    """**生成器**那一侧也必须转发 `body` —— 模板支持、生成器丢掉，等于白写。

    上面那组测试**直接喂 ctx**，所以它测不到生成器。曾经就是这样：模板的
    `{% if body %}` 分支写好了、单测全绿，而 `generate_utils` 的 ctx 里根本没有
    `body` 这个键 —— 于是 SQL 模型库里的 TLM 1.0 语义一路白存，渲染出来的还是
    空壳。这条走**真生成器**，把「模板支持」升级成「端到端真的进得去」。
    """

    def test_body_from_the_registry_reaches_the_generated_file(self, tmp_path):
        from src.tools.generation.uvm_tools.generation.generators.orchestrator import UVMGenerator

        gen = UVMGenerator(JinjaRenderer(TEMPLATES_DIR), output_root=tmp_path)
        body = "tr.prdata = m_regs[tr.paddr];\n// 事务级语义\n"
        out = gen.generate_utils([{
            "name": "apb_uart_ref",
            "type": "tlm10_component",
            "description": "事务级参考模型",
            "analysis_exports": [{"name": "in_export",
                                  "type": "apb_master_seq_item"}],
            "analysis_ports": [{"name": "out_port",
                                "type": "apb_master_seq_item"}],
            "body": body,
        }])
        assert out, "util 组件没生成出来"
        sv = out[0].read_text(encoding="utf-8")
        assert "m_regs[tr.paddr]" in sv, \
            "模型语义没进生成物 —— 生成器的 ctx 把 `body` 丢了"
        assert "TODO: override in derived class" not in sv
        # 出处要带上：人得能看出这段语义是哪一版模型给的
        assert "model_registry" in sv

    def test_without_body_the_stub_is_still_the_stub(self, tmp_path):
        """没给 `body` 又没给 `ref_model`：仍是空壳（行为不变）。"""
        from src.tools.generation.uvm_tools.generation.generators.orchestrator import UVMGenerator

        gen = UVMGenerator(JinjaRenderer(TEMPLATES_DIR), output_root=tmp_path)
        out = gen.generate_utils([{
            "name": "plain_util",
            "analysis_exports": [{"name": "in_export", "type": "seq_item"}],
            "analysis_ports": [{"name": "out_port", "type": "seq_item"}],
        }])
        sv = out[0].read_text(encoding="utf-8")
        assert "TODO: override in derived class" in sv
