"""
工具测试
"""
import pytest
import json

from src.tools.spec_tools import SpecAnalysisTools
from src.tools.uvm_tools import UVMTools
from src.tools.debug_tools import DebugTools
from src.tools.coverage_tools import CoverageTools

class TestSpecTools:
    """测试规格工具"""
    
    def setup_method(self):
        self.tools = SpecAnalysisTools()
    
    def test_analyze_specification(self):
        """测试规格分析"""
        result = self.tools.analyze_specification("UART spec")
        data = json.loads(result)
        assert "design_name" in data
        assert "interfaces" in data
    
    def test_generate_test_plan(self):
        """测试测试计划生成"""
        result = self.tools.generate_test_plan("requirements")
        data = json.loads(result)
        assert "test_categories" in data
        assert len(data["test_categories"]) > 0

class TestUVMTools:
    """测试UVM工具"""
    
    def setup_method(self):
        self.tools = UVMTools()
    
    def test_generate_driver(self):
        """测试Driver生成"""
        result = self.tools.generate_uvm_driver("{}")
        assert "class uart_driver" in result
        assert "uvm_driver" in result
    
    def test_generate_monitor(self):
        """测试Monitor生成"""
        result = self.tools.generate_uvm_monitor("{}")
        assert "class uart_monitor" in result
        assert "analysis_port" in result
    
    def test_generate_scoreboard(self):
        """测试Scoreboard生成"""
        result = self.tools.generate_uvm_scoreboard("{}")
        assert "class uart_scoreboard" in result
        assert "predictor" in result

class TestDebugTools:
    """测试调试工具"""
    
    def setup_method(self):
        self.tools = DebugTools()
    
    def test_analyze_log(self):
        """测试日志分析"""
        result = self.tools.analyze_simulation_log("test.log")
        data = json.loads(result)
        assert "errors" in data
    
    def test_analyze_waveform(self):
        """测试波形分析"""
        result = self.tools.analyze_waveform("test.vcd")
        data = json.loads(result)
        assert "anomalies" in data

class TestCoverageTools:
    """测试覆盖率工具"""
    
    def setup_method(self):
        self.tools = CoverageTools()
    
    def test_collect_coverage(self):
        """测试覆盖率收集"""
        result = self.tools.collect_coverage("all")
        data = json.loads(result)
        assert "code_coverage" in data
        assert "functional_coverage" in data
    
    def test_analyze_gaps(self):
        """测试缺口分析"""
        result = self.tools.analyze_coverage_gaps("{}")
        data = json.loads(result)
        assert "critical_gaps" in data