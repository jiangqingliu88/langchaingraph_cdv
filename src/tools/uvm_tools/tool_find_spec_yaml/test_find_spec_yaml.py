"""Tests for tool_find_spec_yaml —— 重点是 env.yaml 的 `interface` 字段来源。

不测 LLM 那条链路（要 spec 的 JSON + 外部依赖），只钉住**纯函数**的行为：
`_gen_env_yaml` 写出的 `interface:` 必须是**从上层（spec 的 agents[]）传下来的
接口名**，而不是 agent 自己的名字。
"""
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))
from src.tools.uvm_tools.tool_find_spec_yaml.main import (  # noqa: E402
    _dedupe_loopback_tests,
    _gen_env_yaml,
    _iface_name_of,
)


def _spec(agents):
    """spec 的 verification_architecture.agents → agents_spec 的 (agent, iface) 列表。

    这里 iface 内容对本函数不相关，给个最小 dict 即可。
    """
    return [(ag, {"name": ag.get("interface", "")}) for ag in agents]


class TestIfaceNameOf:
    def test_master_slave_collapse_to_interface(self):
        """一个接口出 master/slave 两个 agent，故接口名 = 名字去掉后缀。"""
        assert _iface_name_of("apb_master") == "apb"
        assert _iface_name_of("apb_slave") == "apb"

    def test_plain_name_unchanged(self):
        assert _iface_name_of("apb") == "apb"
        assert _iface_name_of("uart_in") == "uart_in"
        assert _iface_name_of("") == ""


class TestGenEnvYamlInterfaceField:
    """`interface:` 走 spec 传下来的字段，不是 agent 名。"""

    AGENTS = [
        {"name": "apb_master", "interface": "apb", "type": "UVM_ACTIVE"},
        {"name": "apb_slave", "interface": "apb", "type": "UVM_PASSIVE"},
    ]

    def _gen(self, agents=None):
        agents = self.AGENTS if agents is None else agents
        text = _gen_env_yaml("apb_uart", [a["name"] for a in agents],
                             _spec(agents), "pclk", "presetn")
        return yaml.safe_load(text)

    @staticmethod
    def _by_name(doc):
        return {a["name"]: a for a in doc["environment"]["agents"]}

    def test_both_agents_share_the_interface(self):
        """master/slave 两个 agent 都要写 `interface: apb`。

        写成 `interface: apb_master` 时，env 模板会渲染
        `import apb_master_pkg::*`（真实包叫 apb_pkg）→ 整条 env 链 "Invalid type"。
        """
        agents = self._by_name(self._gen())
        assert set(agents) == {"apb_master", "apb_slave"}
        assert agents["apb_master"]["interface"] == "apb"
        assert agents["apb_slave"]["interface"] == "apb"

    def test_is_active_follows_spec_type(self):
        agents = self._by_name(self._gen())
        assert agents["apb_master"]["is_active"] is True
        assert agents["apb_slave"]["is_active"] is False

    def test_is_master_and_type_are_emitted(self):
        """`type` 决定 env 模板推出来的 seq_item/config/sequence 类名。

        缺了它（或写成 `UVM_ACTIVE`）会渲染出不存在的 `apb_seq_item` /
        `apb_config` → 生成物 "near \\"::\\": syntax error"。
        """
        agents = self._by_name(self._gen())
        assert agents["apb_master"]["is_master"] is True
        assert agents["apb_master"]["type"] == "apb_master_agent"
        assert agents["apb_slave"]["is_master"] is False
        assert agents["apb_slave"]["type"] == "apb_slave_agent"

    def test_falls_back_to_name_suffix_when_spec_has_no_interface(self):
        """spec 没给 `interface` 时退化成"名字去后缀"，仍是接口名而非 agent 名。"""
        agents = self._by_name(self._gen([
            {"name": "spi_master", "type": "UVM_ACTIVE"},
            {"name": "spi_slave", "type": "UVM_PASSIVE"},
        ]))
        assert agents["spi_master"]["interface"] == "spi"
        assert agents["spi_slave"]["interface"] == "spi"
        assert agents["spi_master"]["type"] == "spi_master_agent"
        assert agents["spi_slave"]["type"] == "spi_slave_agent"

    def test_protocol_grouped_path_keeps_protocol_as_interface(self):
        """按协议分组那条路 agent 名就是协议名（apb），接口名自然也是 apb；
        它的 `type` 是**激活模式**（UVM_ACTIVE）不是类名，必须被换成真类名。"""
        agents = self._by_name(self._gen([{"name": "apb", "type": "UVM_ACTIVE"}]))
        assert agents["apb"]["interface"] == "apb"
        assert agents["apb"]["type"] == "apb_master_agent"

    def test_clock_reset_are_forwarded(self):
        agents = self._by_name(self._gen(self.AGENTS[:1]))
        assert agents["apb_master"]["clock"] == "pclk"
        assert agents["apb_master"]["reset"] == "presetn"

    def test_env_name_follows_module(self):
        assert self._gen()["environment"]["name"] == "apb_uart_env"


class TestDedupeLoopbackTests:
    """loopback 重名 test 的去重 —— 必须留**最后**那条（独立 build + 正确顶层）。"""

    @staticmethod
    def _block(name, build, top):
        return [f"  - name: {name}",
                f"    build: {build}",
                "    count: 1",
                f"    run_cmd: 'vsim {top}'",
                ""]

    def test_keeps_the_last_not_all(self):
        """两处都会产 loopback 用例：case 库那条（绑 DUT build + bench 顶层，**错**）
        排在前面，生成器那条（绑 *_loopback build + *_loopback_tb，**对**）排在后面。
        去重必须留后者 —— 全删会把对的那条也删掉。"""
        lines = (self._block("test_other", "build_dut", "bench_top")
                 + self._block("test_apb_loopback", "build_dut", "bench_top")
                 + self._block("test_apb_loopback", "build_m_apb_loopback",
                               "apb_loopback_tb"))
        out = _dedupe_loopback_tests(lines, {"test_apb_loopback"})
        joined = "\n".join(out)
        assert joined.count("name: test_apb_loopback") == 1
        assert "build_m_apb_loopback" in joined and "apb_loopback_tb" in joined
        assert "test_other" in joined                     # 无关用例没被动

    def test_single_occurrence_is_untouched(self):
        lines = self._block("test_apb_loopback", "build_m_apb_loopback",
                            "apb_loopback_tb")
        assert _dedupe_loopback_tests(lines, {"test_apb_loopback"}) == lines

    def test_no_names_is_noop(self):
        lines = self._block("test_apb_loopback", "b", "t")
        assert _dedupe_loopback_tests(lines, set()) == lines
