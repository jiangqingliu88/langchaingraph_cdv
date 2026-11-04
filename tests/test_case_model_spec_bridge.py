"""spec → case 模型的桥 —— 闭环里原来缺的那一步。

闭环的 verify 阶段要拿 case 模型分解测试点，而**没有任何一步产它**：三个来源
（`spec["case_model"]` / 人放的 `inputs/casemodel.yaml` / 项目级 config）在自动跑
的时候通常都命不中，于是那一步常年"跳过"，覆盖率收敛只能靠随机激励。

桥的原则是**不编**：功能点、接口信号、中断都是 spec 里已有的字段，机械映射成
case 模型的结构。所以这里的测试查两件事 —— 结构合法（能被 casemodel 工具吃下去），
以及"spec 里没有的东西不许出现"。
"""
from __future__ import annotations

import pytest

from src.layers.l3_decision.casemodel.spec_bridge import case_model_from_spec, case_model_yaml

SPEC = {
    "design_name": "apb_uart",
    "features": [
        {"name": "APB 寄存器读写", "priority": "P0"},
        {"name": "UART 发送", "priority": "P0"},
        {"name": "UART 接收", "priority": "P1"},
    ],
    "interfaces": [
        {"name": "pclk", "data_width": 1, "direction": "INPUT", "protocol": "Clock"},
        {"name": "paddr[7:0]", "data_width": 8, "direction": "INPUT", "protocol": "APB"},
        {"name": "pwdata[7:0]", "data_width": 8, "direction": "INPUT", "protocol": "APB"},
    ],
    "interrupts": [{"name": "tx_done"}, {"name": "rx_valid"}],
}


class TestStructure:

    def test_leaves_come_from_features(self):
        model = case_model_from_spec(SPEC)
        leaves = model["tests"][0]["sub_objects"]
        assert [leaf["name"] for leaf in leaves] == [
            "APB 寄存器读写", "UART 发送", "UART 接收"]

    def test_leaf_codes_are_unique(self):
        """叶子代号重复是组织树**硬错误**。

        `UART 发送` 与 `UART 接收` 都会被拼成 `UART` —— 一开始就是这么撞的，
        而后果不只是扣分：评分器在那种模型上直接 KeyError 崩掉。
        """
        codes = [leaf["code"] for leaf in case_model_from_spec(SPEC)["tests"][0]["sub_objects"]]
        assert len(codes) == len(set(codes)), codes

    def test_dimensions_come_from_data_signals_only(self):
        """时钟不当维度 —— 它不是"取值空间"。"""
        names = [d["name"] for d in case_model_from_spec(SPEC)["dimensions"]]
        assert "paddr" in names and "pwdata" in names
        assert "pclk" not in names

    def test_boundary_values_cover_both_ends(self):
        """边界专题只推边界取值 —— 边界没标出来就推不到，覆盖率两端也就补不上。"""
        pa = next(d for d in case_model_from_spec(SPEC)["dimensions"] if d["name"] == "paddr")
        boundary = [int(v) for v in pa["fields"][0]["boundary"]]
        assert 0 in boundary and 255 in boundary

    def test_nothing_invented_when_spec_is_bare(self):
        """spec 里没功能点也没信号 —— 返回空，而不是编一份空模型假装做过。"""
        assert case_model_from_spec({}) == {}
        assert case_model_yaml({}) == ""
        assert case_model_from_spec({"design_name": "x"}) == {}


class TestUsableByTheCasemodelTools:
    """合成的模型要真能被 casemodel 工具吃下去 —— 结构合法才算桥接上了。"""

    def test_analyze_and_generate_succeed(self):
        from src.layers.l3_decision.casemodel.api import run_gaps, run_generate

        yaml_text = case_model_yaml(SPEC)
        gaps = run_gaps(yaml_text)
        assert not gaps.get("error"), gaps
        assert gaps.get("score", 0) > 60

        result = run_generate(yaml_text)
        assert not result.get("error"), result
        assert result.get("count", 0) > 0

    def test_every_leaf_is_reached_by_a_theme(self):
        """专题得把每个叶子都打到 —— 否则评分器会报"叶子没有专题覆盖"。"""
        from src.layers.l3_decision.casemodel.api import run_gaps

        gaps = run_gaps(case_model_yaml(SPEC))
        reasons = str(gaps.get("reasons", ""))
        assert "叶子没有专题覆盖" not in reasons
