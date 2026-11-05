"""
规格分析工具集 — 从 spec 文本提取结构化信息
"""
from src.tools._lc_tool_compat import tool
import json
import re


@tool("analyze_specification")
def analyze_specification(spec_text: str = "") -> str:
    """分析IC设计规格文档，提取关键信息。

    输入: spec_text — 完整的规格文档 Markdown 文本
    返回: 从文本中实际提取的 design_name, interfaces, registers, features 等
    """
    result = {
        "design_name": "",
        "version": "1.0",
        "overview": "",
        "interfaces": [],
        "features": [],
        "registers": [],
        "interrupts": [],
    }

    if not spec_text or len(spec_text) < 50:
        return json.dumps({"error": "spec_text 太短或为空，无法分析"}, ensure_ascii=False)

    # ── 提取 design_name ──
    # 优先从 HTML 注释 <!-- module: xxx --> 提取（真模块名），回退到 # 一级标题
    module_m = re.search(r'<!--[\s\S]*?\bmodule\s*[:：]\s*([A-Za-z_]\w*)', spec_text)
    if module_m:
        result["design_name"] = module_m.group(1).strip()
    else:
        title_m = re.search(r'^#\s+(.+)', spec_text, re.MULTILINE)
        if title_m:
            result["design_name"] = title_m.group(1).strip()

    # 规范化 design_name：只保留字母/数字/下划线，其余转下划线
    # （文件名/EDA filelist 路径不能被空格或中文截断）
    result["design_name"] = re.sub(r'[^0-9A-Za-z_]+', '_',
                                   result["design_name"] or "dut").strip('_') or "dut"

    # ── 提取 overview ──
    overview_parts = []
    for m in re.finditer(r'(?:one_line_desc|one_paragraph_desc|概述|Overview)[:：]\s*(.+?)(?=\n\n|\n#)', spec_text, re.DOTALL | re.IGNORECASE):
        overview_parts.append(m.group(1).strip()[:500])
    if not overview_parts:
        # 取 ## 之前的介绍段落
        intro = re.split(r'\n##\s', spec_text)[0]
        overview_parts.append(intro[:300])
    result["overview"] = " ".join(overview_parts)[:800]

    # ── 提取 interfaces ──
    iface_pattern = re.finditer(
        r'\|\s*(\w[\w\[\]:]*)\s*\|\s*(\d+)\s*\|\s*(INPUT|OUTPUT|INOUT|input|output|inout)\s*\|\s*(\w*)\s*\|\s*(.*?)\s*\|',
        spec_text
    )
    for m in iface_pattern:
        result["interfaces"].append({
            "name": m.group(1).strip(),
            "data_width": int(m.group(2)),
            "direction": m.group(3).upper(),
            "protocol": m.group(4).strip() or "generic",
            "description": m.group(5).strip(),
        })

    # ── 提取 features（从 ## 章节标题） ──
    feature_sections = re.findall(r'^###\s+(.+)', spec_text, re.MULTILINE)
    for i, title in enumerate(feature_sections[:20]):
        clean = title.strip()
        if clean and len(clean) > 2 and clean.lower() not in ('overview', 'overview', 'block diagram'):
            result["features"].append({
                "name": clean,
                "priority": "P0" if i < 5 else "P1",
                "description": clean,
            })

    # ── 提取 registers ──
    reg_pattern = re.finditer(
        r'\|\s*(0x[0-9a-fA-F]+|\w+)\s*\|\s*(\w+)\s*\|\s*(\d+)\s*\|\s*(RO|RW|WO|ro|rw|wo)\s*\|\s*(.*?)\s*\|',
        spec_text
    )
    for m in reg_pattern:
        result["registers"].append({
            "offset": m.group(1).strip(),
            "name": m.group(2).strip(),
            "width": int(m.group(3)),
            "access": m.group(4).upper(),
            "description": m.group(5).strip()[:200],
        })

    # ── 提取 interrupts ──
    intr_pattern = re.finditer(
        r'interrupt_list.*?name:\s*"?(\w+)"?.*?desc:\s*"?([^"]+)"?',
        spec_text, re.DOTALL
    )
    for m in intr_pattern:
        result["interrupts"].append({"name": m.group(1), "description": m.group(2)[:100]})

    # ── 如果没有匹配到接口表格，尝试从 hjson 中解析 ──
    if not result["interfaces"] and "bus_interfaces" in spec_text:
        iface_hjson = re.findall(r'bus_interfaces:\s*\[(.*?)\]', spec_text, re.DOTALL)
        for block in iface_hjson:
            proto_m = re.findall(r'protocol:\s*"?(\w+)"?', block)
            dir_m = re.findall(r'direction:\s*"?(\w+)"?', block)
            for p, d in zip(proto_m, dir_m):
                result["interfaces"].append({"name": p, "protocol": p, "direction": d, "data_width": 32})

    return json.dumps(result, ensure_ascii=False, indent=2)


@tool("extract_features")
def extract_features(spec_text: str = "") -> str:
    """从规格中提取功能特性列表。

    输入: spec_text — 设计规格文本
    返回: basic_features, advanced_features, error_handling, power_features
    """
    if not spec_text or len(spec_text) < 50:
        return json.dumps({"error": "spec_text too short"}, ensure_ascii=False)

    text_lower = spec_text.lower()
    features = {
        "basic_features": [],
        "advanced_features": [],
        "error_handling": [],
        "power_features": [],
    }

    # 关键词匹配
    if "tx" in text_lower or "transmit" in text_lower or "发送" in spec_text:
        features["basic_features"].append("uart_tx")
    if "rx" in text_lower or "receive" in text_lower or "接收" in spec_text:
        features["basic_features"].append("uart_rx")
    if "fifo" in text_lower:
        features["basic_features"].append("fifo_buffered_io")
    if "baud" in text_lower or "nco" in text_lower:
        features["basic_features"].append("programmable_baud_rate")
    if "interrupt" in text_lower or "中断" in spec_text:
        features["basic_features"].append("interrupt_generation")
    if "loopback" in text_lower or "回环" in spec_text:
        features["advanced_features"].append("loopback_mode")
    if "parity" in text_lower:
        features["basic_features"].append("parity_support")
    if "watermark" in text_lower:
        features["advanced_features"].append("fifo_watermark")
    if "oversample" in text_lower or "oversampling" in text_lower:
        features["advanced_features"].append("rx_oversampling")
    if "parity" in text_lower:
        features["error_handling"].append("parity_error")
    if "frame" in text_lower or "framing" in text_lower:
        features["error_handling"].append("frame_error")
    if "overflow" in text_lower or "overrun" in text_lower:
        features["error_handling"].append("overflow_error")
    if "break" in text_lower:
        features["error_handling"].append("break_detection")
    if "sleep" in text_lower or "idle" in text_lower:
        features["power_features"].append("low_power_mode")
    if "glitch" in text_lower:
        features["error_handling"].append("glitch_filter")

    return json.dumps(features, ensure_ascii=False, indent=2)


@tool("generate_test_plan")
def generate_test_plan(spec_json_or_text: str = "") -> str:
    """基于需求生成测试计划。

    输入: spec_json_or_text — 规格分析 JSON 或规格文本
    返回: 基于实际提取特征的测试计划
    """
    if not spec_json_or_text:
        return json.dumps({"error": "empty input"}, ensure_ascii=False)

    # 尝试从输入中提取 features 和 interfaces
    features = []
    interfaces = []
    try:
        data = json.loads(spec_json_or_text)
        features = data.get("features", [])
        interfaces = data.get("interfaces", [])
    except (json.JSONDecodeError, TypeError):
        # 非 JSON，从文本提取
        pass

    test_plan = {
        "plan_name": "Auto-generated Verification Plan",
        "methodology": "UVM",
        "test_categories": [],
        "coverage_goals": {"code_coverage": 95.0, "functional_coverage": 100.0},
    }

    # 从 features 生成测试类别
    if features:
        test_plan["test_categories"].append({
            "category": "Basic Functionality",
            "priority": "High",
            "tests": [{"name": f"test_{f.get('name', f'feat_{i}')}", "type": "directed"}
                      for i, f in enumerate(features[:8]) if isinstance(f, dict)],
        })

    # 从 interfaces 生成接口测试
    if interfaces:
        iface_tests = [{"name": f"test_if_{iface.get('name', f'if_{i}')}", "type": "directed"}
                       for i, iface in enumerate(interfaces[:4]) if isinstance(iface, dict)]
        if iface_tests:
            test_plan["test_categories"].append({
                "category": "Interface Testing", "priority": "High", "tests": iface_tests,
            })

    # 标准类别
    test_plan["test_categories"].extend([
        {"category": "Error Injection", "priority": "Medium",
         "tests": [{"name": "test_parity_error", "type": "directed"},
                   {"name": "test_frame_error", "type": "directed"}]},
        {"category": "Stress", "priority": "Low",
         "tests": [{"name": "test_stress_tx_rx", "type": "constrained_random"}]},
    ])

    return json.dumps(test_plan, ensure_ascii=False, indent=2)


@tool("assess_risk")
def assess_risk(spec_analysis: str = "") -> str:
    """评估验证风险。

    输入: spec_analysis — 规格分析结果 JSON 或文本
    返回: 风险项列表
    """
    analysis_lower = spec_analysis.lower() if spec_analysis else ""

    risks = []

    if "clock" in analysis_lower or "clk" in analysis_lower:
        if "domain" in analysis_lower or "pclk" in analysis_lower or "多个" in spec_analysis:
            risks.append({"item": "Multiple clock domains", "risk": "High",
                          "mitigation": "CDC assertions + formal verification"})

    if "baud" in analysis_lower or "nco" in analysis_lower:
        risks.append({"item": "Baud rate generation accuracy (NCO rounding error)",
                      "risk": "Medium", "mitigation": "Constrained random + boundary test"})

    if "fifo" in analysis_lower:
        risks.append({"item": "FIFO overflow/underflow at boundaries",
                      "risk": "Medium", "mitigation": "Dedicated error injection tests + watermark tests"})

    if "interrupt" in analysis_lower or "中断" in spec_analysis:
        risks.append({"item": "Interrupt latency and concurrency",
                      "risk": "Medium", "mitigation": "Interrupt stress test with concurrent sources"})

    if "parity" in analysis_lower:
        risks.append({"item": "Parity bit corruption across baud rates",
                      "risk": "Low", "mitigation": "Parity error injection across all baud configs"})

    if not risks:
        risks.append({"item": "Insufficient spec detail", "risk": "Medium",
                      "mitigation": "Request more detailed spec documentation"})

    return json.dumps({"overall_risk": "Medium", "risk_items": risks}, ensure_ascii=False, indent=2)


class SpecAnalysisTools:
    def get_tools(self):
        return [analyze_specification, extract_features, generate_test_plan, assess_risk]
