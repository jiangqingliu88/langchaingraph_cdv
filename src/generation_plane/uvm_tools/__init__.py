"""
UVM 工具包 —— 独立封装的参数化代码生成器 + Agent 工具

    from src.generation_plane.uvm_tools import generate_uvm, uvm_tool
    result = generate_uvm("agent", yaml_string)

    # 手动调用 Agent 工具
    from src.generation_plane.uvm_tools.tools import generate_uvm_from_spec, _uvm_ctx
    _uvm_ctx.set(output_dir=Path("output"), agents=[], env_name="dut_env")
    result = generate_uvm_from_spec.func(spec_text)
"""
from .tool_uvm.generators.orchestrator import (  # noqa: F401
    generate_uvm, SUPPORTED_TOOL_TYPES,
)

# LangChain Tool 包装 —— AgentExecutor 要求 tools 为 BaseTool 实例
from langchain_core.tools import StructuredTool  # noqa: E402

uvm_tool = StructuredTool.from_function(
    func=generate_uvm,
    name="generate_uvm",
    description=(
        "参数化 UVM SystemVerilog 代码生成器。"
        "根据 tool_type 和 YAML 规格字符串生成对应的 UVM 组件代码。"
        "tool_type 可选: agent | env | bench | constraint | util。"
        "yaml_spec: 描述接口/环境的 YAML 字符串。"
        "返回生成的文件列表和代码摘要。"
    ),
)

# 从 tools 子模块导出 Agent 工具（手动测试用）
from .agent_tools import (  # noqa: E402, F401
    find_spec_yaml,
    jinja_render,
    quality_report,
    check_static,
    check_compile,
    check_loopback,
    check_health,
    read_file,
    write_file,
    _uvm_ctx,
    ensure_uvm_tool_registry,
)
