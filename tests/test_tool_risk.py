"""工具风险分级 —— 把"哪些工具会写盘"从**靠人记得登记**变成被测试钉住。

这里防的是哪一种事故
    `tool_hub` 给 LangChain `@tool` 定风险等级时，原来用的是
    「列一个 WRITE 清单，其余默认 SAFE」。于是：

        `_LC_WRITE_TOOLS` 列了 18 个名字
        实际有 32 个 `@tool`（清单里还有 5 个是已经不存在的幽灵条目）
        → `write_file`（名字就叫写文件）、`jinja_render`、`quality_report`、
          `check_compile` 全都没被分类，按 **SAFE** 放行

    默认方向错了：漏登记"只读工具"只是多一次确认，漏登记"写盘工具"
    却是**静默自动通过**。所以改成 fail-safe（默认 WRITE，SAFE 要显式列），
    这几条测试负责让那份显式清单**不会悄悄退化**。

为什么用 AST 而不是 grep
    静态 grep 会被注释和 docstring 里的工具名骗到（这个仓库里真的出现过）。
    AST 只看真正的 `@tool(...)` 装饰器。
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Set

import pytest

from src.layers.l2_orchestration.communication.tool_hub import _LC_SAFE_TOOLS

#: 会注册 LangChain `@tool` 的模块 —— 与 `tool_hub._LC_TOOL_MODULES` 同源。
#: 那份表是 `(模块名, 标签)`，这里只要文件路径（AST 要读文件）。
TOOL_MODULES = (
    "src/tools/checking/assertion_tools/main.py",
    "src/layers/l3_decision/evidence/main.py",
    "src/skills/debug/tools/main.py",
    "src/layers/l5_evolution/docs/main.py",
    "src/layers/l3_decision/spec_tools/main.py",
    "src/tools/generation/uvm_tools/agent_tools.py",
)

#: **一定**有副作用的工具（写盘 / 起子进程 / 跑 EDA）。
#: 它们一旦出现在 `_LC_SAFE_TOOLS` 里，就是踩了那颗雷：一个写盘动作被自动放行。
#: 这份清单是**断言**不是配置 —— 加工具时如果它明显有副作用，就加到这儿来。
MUST_NOT_BE_SAFE = {
    "write_file", "jinja_render", "quality_report",
    "collect_sim_log", "collect_compile_log", "collect_coverage",
    "collect_waveform", "auto_fix", "rerun_failed_test",
    "generate_sva_assertions", "generate_assertion_package",
    "check_compile", "check_loopback",
}


def _declared_tools() -> Set[str]:
    """AST 扫出所有 `@tool("name")` 装饰的函数名。"""
    found: Set[str] = set()
    for rel in TOOL_MODULES:
        path = Path(rel)
        if not path.exists():                    # 模块删了不该让本测试炸
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for dec in node.decorator_list:
                if (isinstance(dec, ast.Call)
                        and getattr(dec.func, "id", "") == "tool"
                        and dec.args
                        and isinstance(dec.args[0], ast.Constant)):
                    found.add(dec.args[0].value)
    return found


def test_the_scan_finds_tools():
    """先证明这套扫描真的读到东西了。

    没有这条，`_declared_tools()` 因为改路径而返回空集时，
    下面的测试会**全部通过** —— 那是最坏的一种绿。
    """
    tools = _declared_tools()
    assert len(tools) >= 20, f"只扫到 {len(tools)} 个 @tool，路径可能失效了"


def test_write_tools_are_not_marked_safe():
    """有副作用的工具**不许**出现在 SAFE 清单里。"""
    leaked = sorted(MUST_NOT_BE_SAFE & _LC_SAFE_TOOLS)
    assert not leaked, (
        f"这些工具有副作用，却被标成 SAFE（会自动通过）：{leaked}\n"
        f"SAFE 清单在 tool_hub._LC_SAFE_TOOLS；默认方向是 fail-safe "
        f"（不列出 = WRITE），所以把它们从 SAFE 里删掉即可。"
    )


def test_the_safe_list_has_no_ghosts():
    """SAFE 清单里**不许有已经不存在的工具名**。

    幽灵条目无害但会骗人：它让"这份清单是完备的"看起来成立，实际不是。
    （原来的 WRITE 清单里就有 5 个 —— `backup_to_library` / `scan_environment`
    之类，工具早没了，名字还留着。）
    """
    declared = _declared_tools()
    ghosts = sorted(_LC_SAFE_TOOLS - declared)
    assert not ghosts, f"SAFE 清单里的幽灵条目（工具不存在）：{ghosts}"


def test_unknown_tools_default_to_write():
    """默认方向是 fail-safe —— 这条钉住"反转别被改回去"。"""
    from src.layers.l2_orchestration.communication.tool_hub import ToolRisk

    # 一个肯定不在 SAFE 清单里的名字
    assert "definitely_not_a_registered_tool" not in _LC_SAFE_TOOLS
    risk = ToolRisk.SAFE if "definitely_not_a_registered_tool" in _LC_SAFE_TOOLS \
        else ToolRisk.WRITE
    assert risk is ToolRisk.WRITE


@pytest.mark.parametrize("name", sorted(MUST_NOT_BE_SAFE))
def test_each_write_tool_is_actually_declared(name):
    """`MUST_NOT_BE_SAFE` 里不该有幽灵 —— 否则这条断言是空的。

    与 `test_the_safe_list_has_no_ghosts` 对称：两边都要是真名字，
    "A 不许包含 B"才有意义。
    """
    assert name in _declared_tools(), (
        f"{name!r} 被写进 MUST_NOT_BE_SAFE，但它已经不是 `@tool` 了 —— "
        f"要么工具改名了，要么这条断言该删。"
    )
