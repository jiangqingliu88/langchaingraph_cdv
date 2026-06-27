"""
UVM 工具包 —— 独立封装的参数化代码生成器

    from src.tools.uvm_tools import generate_uvm, uvm_tool
    result = generate_uvm("agent", yaml_string)
    result = generate_uvm("env", yaml_string)
    result = generate_uvm("bench", yaml_string)
    result = generate_uvm("constraint", yaml_string)
    result = generate_uvm("util", yaml_string)
"""
from .tool_uvm.gen_uvm import generate_uvm, SUPPORTED_TOOL_TYPES  # noqa: F401

# LangChain Tool 包装 —— AgentExecutor 要求 tools 为 BaseTool 实例
from langchain.tools import StructuredTool  # noqa: E402

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
