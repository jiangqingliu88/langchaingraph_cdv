"""
断言工具集 - 使用Jinja2模板生成SVA断言和形式验证属性
"""
from langchain.tools import tool, BaseTool
from typing import Dict, List, Any, Optional
import json
import structlog

from src.tools.templates import render_template, TemplateLoader

logger = structlog.get_logger()

class AssertionTools:
    """断言生成工具集"""
    
    def __init__(self):
        self.template_loader = TemplateLoader.get_instance()
    
    def get_tools(self) -> List[BaseTool]:
        """获取所有断言工具"""
        return [
            self.generate_sva_assertions,
            self.generate_immediate_assertions,
            self.generate_concurrent_assertions,
            self.generate_formal_properties,
            self.generate_cdc_assertions,
            self.generate_cover_properties,
            self.generate_assertion_package,
            self.analyze_assertion_coverage,
            self.generate_assertion_bindings,
        ]
    
    def get_protocol_tools(self) -> List[BaseTool]:
        """获取协议相关断言工具"""
        return [
            self.generate_sva_assertions,
            self.generate_cover_properties,
        ]
    
    def get_formal_tools(self) -> List[BaseTool]:
        """获取形式验证工具"""
        return [
            self.generate_formal_properties,
            self.generate_cdc_assertions,
        ]
    
    @tool("generate_sva_assertions")
    def generate_sva_assertions(self, specs: str) -> str:
        """
        生成SVA断言代码
        
        参数:
        specs: JSON格式的断言规格
        {
            "design_name": "uart_controller",
            "clock_signal": "clk",
            "reset_signal": "rst_n",
            "package_name": "uart_assertions_pkg",
            "assertions": [
                {
                    "type": "concurrent",
                    "property_name": "valid_stable",
                    "severity": "Error",
                    "property": "valid && !ready |=> $stable(data)",
                    "disable_condition": "!rst_n",
                    "message": "Data changed while valid asserted"
                }
            ],
            "cover_properties": [...],
            "assertion_bindings": [...]
        }
        """
        try:
            data = self._parse_input(specs)
        except json.JSONDecodeError:
            data = self._get_default_sva_spec()
        
        context = {
            "design_name": data.get("design_name", "dut"),
            "clock_signal": data.get("clock_signal", "clk"),
            "reset_signal": data.get("reset_signal", "rst_n"),
            "package_name": data.get("package_name", None),
            "assertions": data.get("assertions", []),
            "cover_properties": data.get("cover_properties", []),
            "assertion_bindings": data.get("assertion_bindings", [])
        }
        
        # 为每个断言设置默认值
        for assertion in context["assertions"]:
            assertion.setdefault("clock_edge", f"posedge {context['clock_signal']}")
            assertion.setdefault("severity", "Error")
            assertion.setdefault("disable_condition", f"!{context['reset_signal']}")
        
        try:
            return render_template("assertion/sva_assertions.j2", **context)
        except Exception as e:
            logger.error(f"SVA断言模板渲染失败", error=str(e))
            return f"// Error generating SVA assertions: {str(e)}"
    
    @tool("generate_immediate_assertions")
    def generate_immediate_assertions(self, specs: str) -> str:
        """
        生成即时断言(Immediate Assertions)
        
        参数:
        specs: JSON格式
        {
            "assertions": [
                {
                    "label": "check_data",
                    "condition": "data !== 'x",
                    "severity": "Error",
                    "message": "Data contains unknown value"
                }
            ]
        }
        """
        try:
            data = self._parse_input(specs)
        except json.JSONDecodeError:
            data = {"assertions": []}
        
        assertions_code = []
        
        for assertion in data.get("assertions", []):
            label = assertion.get("label", "")
            condition = assertion.get("condition", "1'b0")
            severity = assertion.get("severity", "error")
            message = assertion.get("message", "Assertion failed")
            action = assertion.get("action", "")
            
            code = f"{label}: " if label else ""
            code += f"assert ({condition})"
            code += f"\n    else ${{severity}}(\"{message}\")"
            if action:
                code += f"\n    else begin\n        {action}\n    end"
            
            assertions_code.append(code)
        
        return "\n\n".join(assertions_code)
    
    @tool("generate_concurrent_assertions")
    def generate_concurrent_assertions(self, specs: str) -> str:
        """
        生成并发断言(Concurrent Assertions)
        """
        try:
            data = self._parse_input(specs)
        except json.JSONDecodeError:
            data = {"clock_signal": "clk", "assertions": []}
        
        clock = data.get("clock_signal", "clk")
        reset = data.get("reset_signal", "rst_n")
        assertions_code = []
        
        for assertion in data.get("assertions", []):
            prop_name = assertion.get("property_name", f"prop_{id(assertion)}")
            severity = assertion.get("severity", "error")
            message = assertion.get("message", "Concurrent assertion failed")
            
            code = f"property {prop_name};\n"
            code += f"    @(posedge {clock})\n"
            
            if assertion.get("disable_condition"):
                code += f"    disable iff ({assertion['disable_condition']})\n"
            elif reset:
                code += f"    disable iff (!{reset})\n"
            
            code += f"    {assertion.get('property', '1'b0)};\n"
            code += f"endproperty\n"
            
            label = assertion.get("label", "")
            if label:
                code += f"{label}: "
            code += f"assert property({prop_name})\n"
            code += f"    else ${{severity}}(\"{message}\", $time);"
            
            assertions_code.append(code)
        
        return "\n\n".join(assertions_code)
    
    @tool("generate_formal_properties")
    def generate_formal_properties(self, specs: str) -> str:
        """
        生成形式验证属性
        """
        try:
            data = self._parse_input(specs)
        except json.JSONDecodeError:
            data = self._get_default_formal_spec()
        
        context = {
            "design_name": data.get("design_name", "dut"),
            "clock_signal": data.get("clock_signal", "clk"),
            "reset_signal": data.get("reset_signal", "rst_n"),
            "formal_properties": data.get("formal_properties", []),
            "assumptions": data.get("assumptions", []),
            "fairness_constraints": data.get("fairness_constraints", [])
        }
        
        try:
            return render_template("assertion/formal_properties.j2", **context)
        except Exception as e:
            logger.error(f"形式验证属性模板渲染失败", error=str(e))
            return f"// Error generating formal properties: {str(e)}"
    
    @tool("generate_cdc_assertions")
    def generate_cdc_assertions(self, specs: str) -> str:
        """
        生成CDC(Clock Domain Crossing)断言
        """
        try:
            data = self._parse_input(specs)
        except json.JSONDecodeError:
            data = self._get_default_cdc_spec()
        
        context = {
            "design_name": data.get("design_name", "dut"),
            "cdc_paths": data.get("cdc_paths", []),
            "cdc_coverage": data.get("cdc_coverage", [])
        }
        
        try:
            return render_template("assertion/cdc_assertions.j2", **context)
        except Exception as e:
            logger.error(f"CDC断言模板渲染失败", error=str(e))
            return f"// Error generating CDC assertions: {str(e)}"
    
    @tool("generate_cover_properties")
    def generate_cover_properties(self, specs: str) -> str:
        """
        生成Cover Properties
        """
        try:
            data = self._parse_input(specs)
        except json.JSONDecodeError:
            data = {"clock_signal": "clk", "cover_properties": []}
        
        clock = data.get("clock_signal", "clk")
        covers_code = []
        
        for cover in data.get("cover_properties", []):
            label = cover.get("label", "")
            description = cover.get("description", "")
            property_text = cover.get("property", "1'b0")
            
            code = f"// {description}\n" if description else ""
            if label:
                code += f"{label}: "
            code += f"cover property(\n"
            code += f"    @(posedge {clock})\n"
            code += f"    {property_text}\n"
            code += f");"
            
            covers_code.append(code)
        
        return "\n\n".join(covers_code)
    
    @tool("generate_assertion_package")
    def generate_assertion_package(self, specs: str) -> str:
        """
        生成断言包文件
        """
        try:
            data = self._parse_input(specs)
        except json.JSONDecodeError:
            data = self._get_default_package_spec()
        
        package_code = f"""
// ============================================
// Assertion Package: {data.get('package_name', 'assertions_pkg')}
// ============================================

package {data.get('package_name', 'assertions_pkg')};
    
    {chr(10).join(data.get('includes', []))}
    
    {chr(10).join(data.get('assertion_modules', []))}
    
endpackage : {data.get('package_name', 'assertions_pkg')}
        """
        return package_code
    
    @tool("analyze_assertion_coverage")
    def analyze_assertion_coverage(self, assertion_data: str) -> str:
        """
        分析断言覆盖率
        """
        try:
            data = self._parse_input(assertion_data)
        except json.JSONDecodeError:
            data = {}
        
        # 分析断言覆盖率
        total = data.get("total_assertions", 0)
        covered = data.get("covered_assertions", 0)
        failed = data.get("failed_assertions", 0)
        vacuous = data.get("vacuous_assertions", 0)
        
        coverage_rate = (covered / total * 100) if total > 0 else 0
        
        analysis = {
            "assertion_coverage_summary": {
                "total_assertions": total,
                "attempted": covered + failed + vacuous,
                "succeeded": covered,
                "failed": failed,
                "vacuous": vacuous,
                "coverage_rate": f"{coverage_rate:.1f}%"
            },
            "by_type": data.get("by_type", {}),
            "by_module": data.get("by_module", {}),
            "uncovered_assertions": data.get("uncovered_assertions", []),
            "recommendations": self._generate_coverage_recommendations(data)
        }
        
        return json.dumps(analysis, indent=2)
    
    @tool("generate_assertion_bindings")
    def generate_assertion_bindings(self, specs: str) -> str:
        """
        生成断言绑定代码
        """
        try:
            data = self._parse_input(specs)
        except json.JSONDecodeError:
            data = {"bindings": []}
        
        bindings_code = []
        
        for binding in data.get("bindings", []):
            module_path = binding.get("module_path", "dut")
            assertion_module = binding.get("assertion_module", "assertions")
            instance_name = binding.get("instance_name", f"u_{assertion_module}")
            ports = binding.get("ports", [])
            
            code = f"bind {module_path} {assertion_module} {instance_name} (\n"
            code += ",\n".join(f"    .{port}({port})" for port in ports)
            code += "\n);"
            
            bindings_code.append(code)
        
        return "\n\n".join(bindings_code)
    
    def _parse_input(self, input_data: str) -> Dict:
        """解析输入数据"""
        if isinstance(input_data, str):
            try:
                return json.loads(input_data)
            except json.JSONDecodeError:
                # 尝试从文本中提取JSON
                import re
                json_match = re.search(r'\{.*\}', input_data, re.DOTALL)
                if json_match:
                    return json.loads(json_match.group())
                raise
        return input_data
    
    def _generate_coverage_recommendations(self, data: Dict) -> List[str]:
        """生成覆盖率改进建议"""
        recommendations = []
        
        uncovered = data.get("uncovered_assertions", [])
        if uncovered:
            recommendations.append(
                f"Add test cases to trigger {len(uncovered)} uncovered assertions"
            )
        
        vacuous_count = data.get("vacuous_assertions", 0)
        if vacuous_count > 0:
            recommendations.append(
                f"Review {vacuous_count} vacuous assertions - may have incorrect antecedents"
            )
        
        failed_count = data.get("failed_assertions", 0)
        if failed_count > 0:
            recommendations.append(
                f"Debug {failed_count} failing assertions - possible design bugs"
            )
        
        # 按类型建议
        by_type = data.get("by_type", {})
        for assert_type, coverage in by_type.items():
            if coverage < 90:
                recommendations.append(
                    f"Improve {assert_type} assertion coverage (currently {coverage}%)"
                )
        
        return recommendations if recommendations else [
            "Assertion coverage is adequate",
            "Consider adding more corner case assertions"
        ]
    
    # ==================== 默认规格 ====================
    
    def _get_default_sva_spec(self) -> Dict:
        return {
            "design_name": "dut",
            "clock_signal": "clk",
            "reset_signal": "rst_n",
            "assertions": [
                {
                    "type": "concurrent",
                    "property_name": "valid_stable",
                    "severity": "Error",
                    "description": "Data must be stable when valid is asserted",
                    "property": "valid && !ready |=> $stable(data)",
                    "disable_condition": "!rst_n",
                    "message": "Data changed while valid asserted and ready low"
                }
            ]
        }
    
    def _get_default_formal_spec(self) -> Dict:
        return {
            "design_name": "dut",
            "clock_signal": "clk",
            "reset_signal": "rst_n",
            "formal_properties": [
                {
                    "name": "safety_no_deadlock",
                    "type": "safety",
                    "description": "No deadlock condition",
                    "property": "state != DEADLOCK",
                    "error_message": "Deadlock detected"
                }
            ]
        }
    
    def _get_default_cdc_spec(self) -> Dict:
        return {
            "design_name": "dut",
            "cdc_paths": [
                {
                    "source_clock": "clk1",
                    "dest_clock": "clk2",
                    "signal_name": "data_crossing",
                    "synchronizer_type": "2-stage",
                    "sync_signal": "data_sync",
                    "reset_signal": "rst_n",
                    "data_stable_check": True,
                    "data_signal": "data_source",
                    "transfer_active": "transfer_en"
                }
            ]
        }
    
    def _get_default_package_spec(self) -> Dict:
        return {
            "package_name": "assertions_pkg",
            "includes": [
                '`include "sva_assertions.sv"',
                '`include "cdc_assertions.sv"'
            ],
            "assertion_modules": []
        }