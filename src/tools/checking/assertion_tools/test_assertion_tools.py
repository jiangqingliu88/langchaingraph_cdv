"""Tests for assertion_tools"""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))
from src.tools.checking.assertion_tools import generate_sva_assertions


def test_generate_sva_assertions():
    """旧契约是"永远返回点东西"（最后兜底还返回过一段 JSON）—— 那让"生成不出来"
    和"生成出来了"长得一样。新契约：**有可断言的才出**，且必须是能编译的 module。"""
    assert generate_sva_assertions("{}") == ""          # 挂不上对象 → 不出

    code = generate_sva_assertions(json.dumps({
        "sampling": {"dut_module": "dut_x"},
        "interfaces": [{"name": "APB", "signals": {"psel": {}, "penable": {},
                                                   "paddr": {"width": 8}, "pwrite": {}}}]}))
    assert "module dut_x_sva" in code and "bind dut_x" in code
    assert code.count("assert property") >= 2
