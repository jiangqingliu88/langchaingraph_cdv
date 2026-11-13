"""应用服务边界 —— CLI / GUI 不得绕过 `src/app/services` 直连执行引擎。

历史问题：`cmd_verify.py` 直接 `PipelineExecutionService.get_instance()`，
走的是自己的预检（输出目录 / VPlan / 全量开关），GUI 又走
`run_service`，三处各写一遍 —— 改一处另外两条路不跟。

允许直连的地方只有：
    · `src/app/services/**`（facade 本体）
    · `src/orchestration_plane/l2/**`（引擎与 GUI 的线程边界 `run_service`）
测试目录不算产品代码；**注释里提到名字不算越界**（只扫 import）。
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = "PipelineExecutionService"


def _imports(path: Path) -> set:
    """文件里 import 进来的名字（不含注释/字符串里提到）。"""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return set()
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            names.update(alias.name.split(".")[-1] for alias in node.names)
    return names


def _product_files(root: Path):
    for path in root.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        yield path


#: 已登记的例外：它们用引擎做**初始化 / Agent 访问 / 回归辅助**，不负责
#: `verify` 的运行前预检。新增入口默认不允许直连；确有需要必须先登记。
ALLOWED_CLI_IMPORTS = {
    "src/workbench/cli/cmd_debug.py": "调试页读运行/Agent 状态",
    "src/workbench/cli/cmd_services.py": "optimize-regression 直接编排回归引擎",
    "src/workbench/cli/cmd_specs.py": "规格分析需要 Agent 实例",
    "src/workbench/cli/cmd_tools.py": "工具页需要 Agent 实例",
    "src/workbench/cli/commands.py": "_init_service / resume 等共享初始化",
    "src/workbench/cli/cmd_project.py": "工程/会话管理（3.0 新增）",
    "src/workbench/cli/cmd_session.py": "会话/人工签核（3.0 新增）",
}


def test_verify_cli_does_not_bypass_the_service_layer():
    path = ROOT / "src" / "workbench" / "cli" / "cmd_verify.py"
    assert TARGET not in _imports(path), (
        "cmd_verify 不得 import PipelineExecutionService —— 走 "
        "src.workbench.api.run_verify_async（预检在 VerifyRequest）")


def test_other_cli_engine_imports_are_explicitly_allowed():
    """其它 CLI 直连引擎是**已登记例外**；新增文件必须显式加进来。"""
    offenders = [p.relative_to(ROOT).as_posix()
                 for p in _product_files(ROOT / "src" / "cli")
                 if TARGET in _imports(p)
                 and p.relative_to(ROOT).as_posix() not in ALLOWED_CLI_IMPORTS]
    assert not offenders, (
        "新的 CLI 直连 PipelineExecutionService 未登记：\n"
        + "\n".join(offenders))


def test_gui_modules_do_not_bypass_the_service_layer():
    offenders = [p.relative_to(ROOT).as_posix()
                 for p in _product_files(ROOT / "src" / "workbench" / "modules")
                 if TARGET in _imports(p)]
    assert not offenders, (
        "GUI 模块不得 import PipelineExecutionService（走 run_service / app.services）：\n"
        + "\n".join(offenders))


def test_verify_request_is_the_shared_preflight():
    """CLI 与 GUI 必须共用同一份 `VerifyRequest`（含 prepare/审批/增量窗口）。"""
    from src.orchestration_plane.l2.run_service import RunRequest
    from src.orchestration_plane.l2.verify_request import VerifyRequest

    assert RunRequest is VerifyRequest
    for method in ("prepare", "approval_gate", "incremental_env", "resolved_spec",
                   "snapshot"):
        assert hasattr(VerifyRequest, method), method
