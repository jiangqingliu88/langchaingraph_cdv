"""
统一 Tool Schema 注册 — 所有 Agent 的 Tool 在此注册 JSON Schema

用法:
  from src.layers.l2_orchestration.agents.agent_tools import register_all_tools
  registry = register_all_tools()
  agent.tool_registry = registry  # BaseAgent 自动 wrap + validate
"""

from src.layers.l2_orchestration.communication.tool_system import Tool, ToolRegistry


def register_all_tools() -> ToolRegistry:
    """注册所有 Agent 的 Tool，含完整 JSON Schema。"""
    registry = ToolRegistry()

    # ═══════════════════════════════════════════════════
    # verification_architect (7 tools) — delegated to uvm_tools
    # ═══════════════════════════════════════════════════
    from src.tools.uvm_tools.agent_tools import ensure_uvm_tool_registry
    uvm_reg = ensure_uvm_tool_registry()
    for t in uvm_reg._tools.values():
        registry.register(t)

    # ═══════════════════════════════════════════════════
    # case 属性建模 (3 tools) — delegated to casemodel_tools
    #   casemodel_validate  Schema 校验
    #   casemodel_gaps      全量完备性分析（可带真实 case 列表反向核对）
    #   casemodel_generate  按属性组合生成 case 属性表
    # ═══════════════════════════════════════════════════
    from src.tools.casemodel_tools.agent.registry import (
        ensure_casemodel_tool_registry,
    )
    casemodel_reg = ensure_casemodel_tool_registry()
    for t in casemodel_reg._tools.values():
        registry.register(t)

    # ═══════════════════════════════════════════════════
    # model_agent (3 tools)
    # ═══════════════════════════════════════════════════
    registry.register_many([
        Tool("analyze_design_arch",
             description="分析设计架构 JSON，提取寄存器、操作、信号信息。",
             input_schema={"type":"object","properties":{"design_json":{"type":"string","description":"设计架构 JSON 字符串"}},"required":["design_json"]},
             risk_level="safe"),
        Tool("generate_ref_model",
             description="生成 C++ 参考模型 (.h/.cpp)。输入 analysis_json，返回模型代码。",
             input_schema={"type":"object","properties":{"analysis_json":{"type":"string","description":"分析结果 JSON"}},"required":["analysis_json"]},
             risk_level="write"),
        Tool("generate_test_vectors",
             description="为参考模型生成测试向量。输入 model_json，返回测试代码。",
             input_schema={"type":"object","properties":{"model_json":{"type":"string","description":"模型 JSON"}},"required":["model_json"]},
             risk_level="write"),
    ])

    # ═══════════════════════════════════════════════════
    # test_engineer (6 tools)
    # ═══════════════════════════════════════════════════
    registry.register_many([
        Tool("parse_test_points",
             description="从 spec JSON 中提取结构化测试点列表。",
             input_schema={"type":"object","properties":{"spec_json":{"type":"string","description":"Spec JSON 字符串"}},"required":["spec_json"]},
             risk_level="safe"),
        Tool("map_policies_to_tests",
             description="将测试点按分类映射到 constraint policies。",
             input_schema={"type":"object","properties":{"input_json":{"type":"string","description":"测试点 JSON"}},"required":["input_json"]},
             risk_level="safe"),
        Tool("build_scenario_yaml",
             description="将场景 JSON 转为 YAML 格式并保存到 output_dir。",
             input_schema={"type":"object","properties":{"scenarios_json":{"type":"string"},"output_dir":{"type":"string","default":""}},"required":["scenarios_json"]},
             risk_level="write"),
        Tool("build_priority_rules",
             description="根据策略列表生成优先级权重规则。",
             input_schema={"type":"object","properties":{"policies_json":{"type":"string"}},"required":["policies_json"]},
             risk_level="safe"),
        Tool("generate_test_cases",
             description="根据场景 YAML 生成 SV 测试代码。",
             input_schema={"type":"object","properties":{"yaml_spec":{"type":"string"},"output_dir":{"type":"string","default":"output/testcases"}},"required":["yaml_spec"]},
             risk_level="write"),
        Tool("check_test_coverage",
             description="对比 spec 测试点和生成的场景，检查覆盖率。",
             input_schema={"type":"object","properties":{"spec_json":{"type":"string"},"scenarios_json":{"type":"string"}},"required":["spec_json","scenarios_json"]},
             risk_level="safe"),
    ])

    # ═══════════════════════════════════════════════════
    # regression_manager (3 tools)
    # ═══════════════════════════════════════════════════
    registry.register_many([
        Tool("compile_env",
             description="编译 UVM 环境。输入 filelist 路径, output 目录, top 模块名。",
             input_schema={"type":"object","properties":{
                 "filelist":{"type":"string","description":"filelist 文件路径"},
                 "output_dir":{"type":"string","description":"输出目录"},
                 "top_module":{"type":"string","description":"顶层模块名"},
             },"required":["filelist","output_dir","top_module"]},
             risk_level="safe"),
        Tool("run_simulation",
             description="执行仿真测试。tests_json: [{name, uvm_test, top, coverage}]。",
             input_schema={"type":"object","properties":{
                 "output_dir":{"type":"string"},
                 "tests_json":{"type":"string","description":"JSON 数组 [{name, uvm_test, top}]"},
             },"required":["output_dir","tests_json"]},
             risk_level="danger"),  # 仿真可能长时间运行
        Tool("generate_regression_report",
             description="生成回归报告 (JSON+HTML)。tasks_json: [{name, status, elapsed}]。",
             input_schema={"type":"object","properties":{
                 "output_dir":{"type":"string"},
                 "tasks_json":{"type":"string","description":"[{name, status, elapsed}]"},
             },"required":["output_dir","tasks_json"]},
             risk_level="write"),
    ])

    # ═══════════════════════════════════════════════════
    # report_generator (2 tools)
    # ═══════════════════════════════════════════════════
    registry.register_many([
        Tool("generate_reports",
             description="生成 JSON+HTML 回归报告。tasks_json: [{name, status, elapsed}]。",
             input_schema={"type":"object","properties":{
                 "output_dir":{"type":"string"},
                 "tasks_json":{"type":"string"},
             },"required":["output_dir","tasks_json"]},
             risk_level="write"),
        Tool("query_trend_history",
             description="查询历史趋势数据。task_name 为空时返回运行历史。",
             input_schema={"type":"object","properties":{
                 "task_name":{"type":"string","default":""},
                 "limit":{"type":"integer","default":10},
             }},
             risk_level="safe"),
    ])

    return registry
