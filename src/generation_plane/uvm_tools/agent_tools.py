"""
UVM Agent 工具集 —— 将独立 tool_* 模块包装为 LangChain @tool

每个 tool = 一个独立脚本 main.py + 一个 schema.yaml。
LLM 通过 @tool 装饰器调用 main.py 中的 run() 函数。
Jinja2 确定性生成模板，LLM 做完形填空。
"""
from src.runtime_plane.tools._lc_tool_compat import tool

from src.generation_plane.uvm_tools.tool_find_spec_yaml.main import run as _find_yaml_run
from src.generation_plane.uvm_tools.tool_jinja_render.main import run as _render_run
from src.generation_plane.uvm_tools.checking.tool_quality_report.main import run as _quality_run
from src.generation_plane.uvm_tools.checking.tool_check_static.main import run as _static_run
from src.generation_plane.uvm_tools.checking.tool_check_compile.main import run as _compile_run
from src.generation_plane.uvm_tools.checking.tool_check_loopback.main import run as _loopback_run
from src.generation_plane.uvm_tools.checking.tool_check_health.main import run as _health_run
from src.generation_plane.uvm_tools.tool_read_file.main import run as _read_run
from src.generation_plane.uvm_tools.tool_write_file.main import run as _write_run
from src.runtime_plane.tools.common.lib.uvm_context import ctx as _uvm_ctx  # re-export for agent use


@tool("find_spec_yaml")
def find_spec_yaml(spec_text: str) -> str:
    """从 spec 文本查找已有 YAML 或构造 agent/env/bench YAML 默认配置。
    输入 spec_text (Markdown)，返回 YAML 文件列表 JSON。"""
    return _find_yaml_run(spec_text)


@tool("jinja_render")
def jinja_render(output_dir: str = "", dest_dir: str = "") -> str:
    """Jinja2 确定性渲染 YAML → UVM SystemVerilog 骨架代码。
    生成 agent/driver/monitor/scoreboard 等完整类结构。
    `dest_dir` 可把渲染结果落到 run 根之外（VPlan 的 sv/ 暂存区）。"""
    return _render_run(output_dir, dest_dir)


@tool("quality_report")
def quality_report(output_dir: str = "") -> str:
    """三项质量评分: 静态检查 + 编译 + 闭环仿真。
    生成 quality_report.json，返回 PASS/FAIL + 评分。"""
    return _quality_run(output_dir)


@tool("check_static")
def check_static(env_dir: str = "") -> str:
    """静态检查: 验证所有预期的 UVM 文件（8 个 per agent）是否存在。"""
    return _static_run(env_dir)


@tool("check_compile")
def check_compile(env_dir: str = "") -> str:
    """编译检查: 使用 QuestaSim vlog 编译 UVM 环境，返回错误/警告统计。"""
    return _compile_run(env_dir)


@tool("check_loopback")
def check_loopback(env_dir: str = "") -> str:
    """闭环检查: 编译 + vsim 仿真每个 Agent 的 loopback TB。"""
    return _loopback_run(env_dir)


@tool("check_health")
def check_health(env_dir: str = "") -> str:
    """健康检查: 编译 UVM 环境顶层模块。"""
    return _health_run(env_dir)


@tool("read_file")
def read_file(path: str) -> str:
    """读取生成的 SystemVerilog 文件内容。"""
    return _read_run(path)


@tool("write_file")
def write_file(path_content: str) -> str:
    """写入/覆盖 SystemVerilog 文件。格式: 'filepath::content'。"""
    return _write_run(path_content)


# ── Tool Schema 注册（供 agent_tools.py 使用）──
def ensure_uvm_tool_registry():
    """返回 testbench_orchestrator 所有 Tool 的 ToolRegistry（单例）。"""
    import importlib
    global _registry_instance
    if "_registry_instance" in dir() and _registry_instance is not None:
        return _registry_instance

    from src.orchestration_plane.l2.communication.tool_system import Tool, ToolRegistry
    registry = ToolRegistry()
    registry.register_many([
        Tool("find_spec_yaml",
             description="从 spec 文本查找已有 YAML 或构造默认配置",
             input_schema={"type":"object","properties":{"spec_text":{"type":"string"}},"required":["spec_text"]},
             risk_level="write"),
        Tool("jinja_render",
             description="Jinja2 确定性渲染 YAML -> UVM 骨架代码",
             input_schema={"type":"object","properties":{
                 "output_dir":{"type":"string","default":""},
                 "dest_dir":{"type":"string","default":""}}},
             risk_level="write"),
        Tool("quality_report",
             description="静态+编译+闭环 三项质量评分",
             input_schema={"type":"object","properties":{"output_dir":{"type":"string","default":""}}},
             risk_level="safe"),
        Tool("check_static",
             description="验证所有预期 UVM 文件是否存在",
             input_schema={"type":"object","properties":{"env_dir":{"type":"string","default":""}}},
             risk_level="safe"),
        Tool("check_compile",
             description="QuestaSim vlog 编译检查",
             input_schema={"type":"object","properties":{"env_dir":{"type":"string","default":""}}},
             risk_level="safe"),
        Tool("check_loopback",
             description="闭环编译+仿真检查",
             input_schema={"type":"object","properties":{"env_dir":{"type":"string","default":""}}},
             risk_level="safe"),
        Tool("check_health",
             description="环境顶层编译健康检查",
             input_schema={"type":"object","properties":{"env_dir":{"type":"string","default":""}}},
             risk_level="safe"),
        Tool("read_file",
             description="读取生成的 SystemVerilog 文件",
             input_schema={"type":"object","properties":{"path":{"type":"string"}},"required":["path"]},
             risk_level="safe"),
        Tool("write_file",
             description="写入/覆盖 SystemVerilog 文件",
             input_schema={"type":"object","properties":{"path_content":{"type":"string"}},"required":["path_content"]},
             risk_level="write"),
    ])
    _registry_instance = registry
    return registry

_registry_instance = None
