"""回归工具（ITool / MCP 协议）—— 把回归框架封装成标准 MCP 工具。

回归框架（regression_framwork）是一个成熟的执行器：吃 regression.yaml
（builds + tests），通过 ConfigBuilder → ShellGenerator → Scheduler 批量跑 case。
本模块把它封装成 ITool（MCP 协议），供上层（ops agent / guardian）通过
ToolHub + 子进程隔离调用，而不是直接 import 回归框架。

用法:
    from src.tools.regression_tools.regression_tool import RegressionRunTool
    from src.layers.l2_orchestration.communication.tool_hub import ToolHub
    hub = ToolHub.get_instance()
    hub.register(RegressionRunTool(), ["ops", "guardian"])
    result = await hub.invoke("regression.run", {"output_dir": "output/xxx"})
"""
from __future__ import annotations

from typing import Any, Dict
from pathlib import Path

from src.layers.l2_orchestration.communication.tool_protocol import (
    BaseTool, ToolManifest, ToolResult, ExecutionContext, ToolRisk,
)


class RegressionRunTool(BaseTool):
    """回归执行工具（MCP 协议）：吃 regression.yaml，批量跑 case。

    封装回归框架三步：ConfigBuilder（解析 yaml）→ ShellGenerator（生成脚本）
    → Scheduler（跑 build + test）。返回回归结果（pass/fail 统计 + report）。
    """

    @property
    def manifest(self) -> ToolManifest:
        return ToolManifest(
            name="regression.run",
            version="1.0.0",
            description="吃 regression.yaml 批量跑回归 case（编译 + 仿真），返回 pass/fail 统计 + 报告。",
            input_schema={
                "type": "object",
                "properties": {
                    "output_dir": {"type": "string", "description": "输出目录（含 inputs/yaml/regression.yaml）"},
                    "reg_yaml": {"type": "string", "description": "regression.yaml 路径，空则用 output_dir/inputs/yaml/regression.yaml"},
                    "mode": {"type": "string", "description": "执行模式 local/mock，默认 local"},
                    "tests": {"type": "string", "description": "逗号分隔的 test 名过滤，空则跑全部"},
                    "tags": {"type": "string", "description": "逗号分隔的 tag 过滤，命中任一即跑；空则不过滤"},
                    "exclude_tags": {"type": "string", "description": "逗号分隔的 tag 排除，优先于 tags"},
                },
                "required": ["output_dir"],
            },
            risk_level=ToolRisk.WRITE,
            timeout_s=900.0,
            requires_binaries=["vlog", "vsim"],
            category="simulation",
            tags=["regression", "questa", "mcp", "case"],
        )

    async def _execute_impl(self, args: Dict[str, Any],
                            context: ExecutionContext) -> ToolResult:
        output_dir = Path(args["output_dir"])
        if not output_dir.exists():
            return ToolResult.fail(f"output_dir not found: {output_dir}")

        reg_yaml = args.get("reg_yaml")
        mode = args.get("mode", "local")
        test_filter = args.get("tests", "")
        tag_filter = args.get("tags", "")
        exclude_tags = args.get("exclude_tags", "")

        try:
            # 统一走 L1 基础设施引擎：InfrastructureManager.run_regression
            # （内部吃 regression.yaml → 回归框架 ConfigBuilder/ShellGenerator/Scheduler 批量跑 case）
            from src.layers.l1_infrastructure.infrastructure import InfrastructureManager
            infra = InfrastructureManager(output_dir)
            result = infra.run_regression(reg_yaml, mode, test_filter,
                                          tag_filter, exclude_tags)
            if result.get("status") == "FAIL" and result.get("error"):
                return ToolResult.fail(result["error"])
            return ToolResult.ok(result)
        except Exception as e:
            return ToolResult.fail(str(e)[:500])


class ReferenceFinderTool(BaseTool):
    """溯源查找工具（MCP 协议）：定位「哪个提交引入了这个失败」。

    在 `good..bad` 区间内二分：worktree 隔离每个版本 → 跑指定用例 → 收敛到
    第一个失败的提交。结论连同**环境快照**一起落盘 —— 这是它区别于
    `git bisect` 的地方：换台机器还能复核「当时是在什么环境下得出的这个结论」。

    注意：本工具会为每个被检查的版本做一次完整编译 + 仿真，成本是分钟级；
    结论有缓存（键含环境摘要），重复查询不会重跑。
    """

    @property
    def manifest(self) -> ToolManifest:
        return ToolManifest(
            name="regression.reference_finder",
            version="1.0.0",
            description="在 good..bad 提交区间内二分定位首个失败的提交（逐版本 worktree 隔离 + 复用回归框架跑单用例），结论含环境快照，可审计。",
            input_schema={
                "type": "object",
                "properties": {
                    "repo_path": {"type": "string", "description": "git 仓库路径"},
                    "good": {"type": "string", "description": "已知通过的提交（起点）"},
                    "bad": {"type": "string", "description": "已知失败的提交（终点，通常 HEAD）"},
                    "reg_yaml": {"type": "string", "description": "回归配置 yaml 路径（版本间保持同一份）"},
                    "test_pattern": {"type": "string", "description": "要复现的用例名/正则"},
                    "work_root": {"type": "string", "description": "工作目录（worktree 与结论落这里）"},
                    "mode": {"type": "string", "description": "执行模式 mock/local，默认 mock"},
                    "paths": {"type": "string", "description": "逗号分隔，只考虑这些路径下的提交"},
                },
                "required": ["repo_path", "good", "bad", "reg_yaml", "test_pattern", "work_root"],
            },
            risk_level=ToolRisk.WRITE,
            timeout_s=3600.0,      # 逐版本编译仿真，分钟级，给足
            requires_binaries=["git"],
            category="regression",
            tags=["regression", "reference-finder", "bisect", "evidence"],
        )

    async def _execute_impl(self, args: Dict[str, Any],
                            context: ExecutionContext) -> ToolResult:
        import asyncio
        repo = args["repo_path"]
        work_root = args["work_root"]
        paths = [p.strip() for p in (args.get("paths") or "").split(",") if p.strip()] or None

        def _run():
            from src.layers.l1_infrastructure.reference_finder import ReferenceFinder
            finder = ReferenceFinder(
                repo_path=repo, work_root=work_root,
                reg_yaml=args["reg_yaml"], test_pattern=args["test_pattern"],
                mode=args.get("mode", "mock"), verbose=False)
            return finder.find_first_bad(args["good"], args["bad"], paths=paths)

        try:
            report = await asyncio.to_thread(_run)
            return ToolResult.ok(report)
        except Exception as e:
            return ToolResult.fail(f"{type(e).__name__}: {str(e)[:400]}")


class CoverageCollectTool(BaseTool):
    """覆盖率收集工具（MCP 协议）：走 L1 InfrastructureManager.collect_coverage。

    coverage agent 通过子进程隔离调用本工具，EDA 崩溃不拖垮主流程。
    """

    @property
    def manifest(self) -> ToolManifest:
        return ToolManifest(
            name="coverage.collect",
            version="1.0.0",
            description="收集覆盖率（编译 + 仿真 + ucdb → 统一覆盖率格式），返回覆盖率指标 + 原始证据（log/vcd）。",
            input_schema={
                "type": "object",
                "properties": {
                    "output_dir": {"type": "string", "description": "输出目录"},
                    "seed": {"type": "integer", "description": "随机种子（扩种用）"},
                    "round_num": {"type": "integer", "description": "闭环轮次（覆盖率数据库归档用）"},
                },
                "required": ["output_dir"],
            },
            risk_level=ToolRisk.WRITE,
            timeout_s=600.0,
            requires_binaries=["vlog", "vsim", "vcover"],
            category="coverage",
            tags=["coverage", "questa", "mcp"],
        )

    async def _execute_impl(self, args: Dict[str, Any],
                            context: ExecutionContext) -> ToolResult:
        import asyncio
        output_dir = args["output_dir"]
        seed = args.get("seed", 0)
        round_num = args.get("round_num", 0)
        top_module = args.get("top_module", "")
        try:
            # 统一走 L1 基础设施引擎：InfrastructureManager.collect_coverage
            from src.layers.l1_infrastructure.infrastructure import InfrastructureManager
            infra = InfrastructureManager(output_dir)
            result = await asyncio.to_thread(
                infra.collect_coverage, round_num, top_module, seed)
            return ToolResult.ok(result)
        except Exception as e:
            return ToolResult.fail(str(e)[:500])
