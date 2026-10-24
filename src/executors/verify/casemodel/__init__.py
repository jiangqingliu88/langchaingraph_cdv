"""casemodel 工具的 Agent 接入层 —— verify 角色消费。

工具本身在 `src/tools/generation/casemodel_tools/`（纯工具，零 LLM 依赖）；
本包是它在 Agent 框架里的三个包装面：

    langchain_tools.py   LangChain @tool 外壳
    registry.py          声明式 ToolRegistry + ToolHub 的 ITool

为什么放在 verify 下：casemodel 产出的是测试计划 / case 属性表，
消费它的是 verify（该角色已声明为 uvm + test + assert，且已在 import
testcase_tools）。工具目录因此保持纯净 —— 只有 domain / repository /
generation / analysis / view / cli / api。

三面共用 `casemodel_tools.api` 的实现与 tool_specs() 的工具名，
所以不会各给一个答案（见 tests/test_casemodel_agent.py）。
"""
from __future__ import annotations

from src.tools.generation.casemodel_tools.api import (RUNNERS, TOOL_GAPS, TOOL_GENERATE,
                                           TOOL_NAMES, TOOL_VALIDATE, run_gaps,
                                           run_generate, run_validate)

from .langchain_tools import (CASEMODEL_TOOLS, casemodel_gaps,
                              casemodel_generate, casemodel_validate)
from .registry import (build_casemodel_tools, ensure_casemodel_tool_registry,
                       register_casemodel_tools, tool_specs)

__all__ = [
    # 工具语义（从工具包的 api 转发，调用方不必记两个路径）
    "run_validate", "run_gaps", "run_generate", "RUNNERS",
    "TOOL_VALIDATE", "TOOL_GAPS", "TOOL_GENERATE", "TOOL_NAMES",
    # LangChain 面
    "casemodel_validate", "casemodel_gaps", "casemodel_generate",
    "CASEMODEL_TOOLS",
    # 注册面
    "tool_specs", "ensure_casemodel_tool_registry",
    "build_casemodel_tools", "register_casemodel_tools",
]
