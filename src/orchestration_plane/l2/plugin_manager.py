"""
Plugin Manager — 工具插件发现与加载 (Phase 2)

支持三种插件形式:
  1. Python 包插件: 目录下有 tool.py，实现 ITool
  2. 单文件插件: 单个 .py 文件，顶层有 create_tool() 函数
  3. YAML 配置插件: tool.yaml 描述外部 CLI 工具（通过 CLIToolAdapter）

发现路径（按优先级）:
  - ~/.signoffai/plugins/       (用户级)
  - .signoffai/plugins/         (项目级)
  - src/runtime_plane/tools/                  (内置，向后兼容)
  - $SIGNOFFAI_PLUGIN_PATH      (环境变量)

用法:
  from src.orchestration_plane.l2.plugin_manager import PluginManager
  mgr = PluginManager()
  for tool, roles in mgr.discover():
      hub.register(tool, roles)
"""
from __future__ import annotations

import importlib
import importlib.util
import inspect
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Type

import structlog

from src.orchestration_plane.l2.communication.tool_protocol import ITool, ToolManifest, ToolRisk, ExecutionContext, BaseTool

logger = structlog.get_logger()


class PluginManager:
    """插件发现与加载管理器"""

    def __init__(self, plugin_dirs: List[str] = None):
        self._plugin_dirs = plugin_dirs or self._default_plugin_dirs()
        self._discovered: List[Tuple[ITool, Optional[List[str]]]] = []
        self._errors: List[Dict[str, Any]] = []

    @staticmethod
    def _default_plugin_dirs() -> List[str]:
        dirs = []
        # 用户级
        home = Path.home() / ".signoffai" / "plugins"
        dirs.append(str(home))
        # 项目级
        cwd = Path.cwd() / ".signoffai" / "plugins"
        dirs.append(str(cwd))
        # 内置
        builtin = Path(__file__).parent.parent / "tools"
        if builtin.exists():
            dirs.append(str(builtin.resolve()))
        # 环境变量
        env_path = os.environ.get("SIGNOFFAI_PLUGIN_PATH", "")
        if env_path:
            for p in env_path.split(os.pathsep):
                if p.strip():
                    dirs.append(p.strip())
        return dirs

    @property
    def plugin_dirs(self) -> List[str]:
        return list(self._plugin_dirs)

    @property
    def errors(self) -> List[Dict[str, Any]]:
        return list(self._errors)

    def add_plugin_dir(self, path: str) -> None:
        """动态添加插件搜索目录"""
        if path not in self._plugin_dirs:
            self._plugin_dirs.append(path)

    def discover(self) -> List[Tuple[ITool, Optional[List[str]]]]:
        """从所有插件目录发现工具。

        Returns:
          [(tool_instance, agent_roles)] 列表
          agent_roles 为 None 表示所有 Agent 可用
        """
        self._discovered = []
        self._errors = []

        for plugin_dir in self._plugin_dirs:
            p = Path(plugin_dir)
            if not p.exists():
                logger.debug(f"Plugin dir not found: {plugin_dir}")
                continue

            logger.info(f"Scanning plugins: {plugin_dir}")
            self._scan_directory(p)

        logger.info(f"Plugin discovery complete: {len(self._discovered)} tools, "
                     f"{len(self._errors)} errors")
        return self._discovered

    def _scan_directory(self, directory: Path) -> None:
        """扫描目录，发现所有插件"""
        if not directory.exists():
            return

        # 1. Python 包插件 (目录 + tool.py)
        for item in sorted(directory.iterdir()):
            if item.is_dir() and not item.name.startswith("_") and not item.name.startswith("."):
                tool_file = item / "tool.py"
                if tool_file.exists():
                    self._load_package_plugin(item)
                # 也可能有 tool.yaml
                yaml_file = item / "tool.yaml"
                if yaml_file.exists():
                    self._load_yaml_plugin(yaml_file)

            # 2. 单文件插件 (*.py)
            elif item.is_file() and item.suffix == ".py" and not item.name.startswith("_"):
                if item.name not in ("__init__.py", "tool.py"):
                    self._load_single_file_plugin(item)

            # 3. YAML 配置 (tool_*.yaml)
            elif item.is_file() and item.suffix in (".yaml", ".yml") and "tool" in item.name:
                self._load_yaml_plugin(item)

    def _load_package_plugin(self, package_dir: Path) -> None:
        """加载 Python 包插件"""
        try:
            # 动态导入
            spec = importlib.util.spec_from_file_location(
                package_dir.name, str(package_dir / "__init__.py")
            ) if (package_dir / "__init__.py").exists() else None

            tool_module = self._import_module_from_path(
                f"plugin_{package_dir.name}", str(package_dir / "tool.py")
            )

            tools = self._extract_tools_from_module(tool_module, str(package_dir))
            for tool, roles in tools:
                self._discovered.append((tool, roles))
                logger.info(f"  Plugin loaded: {tool.manifest.name} v{tool.manifest.version} (package)")

        except Exception as e:
            self._errors.append({"path": str(package_dir), "error": str(e)})
            logger.warning(f"Failed to load plugin '{package_dir}': {e}")

    def _load_single_file_plugin(self, file_path: Path) -> None:
        """加载单文件插件"""
        try:
            module = self._import_module_from_path(
                f"plugin_{file_path.stem}", str(file_path)
            )
            tools = self._extract_tools_from_module(module, str(file_path))
            for tool, roles in tools:
                self._discovered.append((tool, roles))
                logger.info(f"  Plugin loaded: {tool.manifest.name} v{tool.manifest.version} (single file)")

        except Exception as e:
            self._errors.append({"path": str(file_path), "error": str(e)})
            logger.warning(f"Failed to load plugin '{file_path}': {e}")

    def _load_yaml_plugin(self, yaml_path: Path) -> None:
        """加载 YAML 配置插件"""
        try:
            from src.orchestration_plane.l2.cli_tool_adapter import CLIToolAdapter
            adapter = CLIToolAdapter(str(yaml_path))
            tool = adapter.load()
            if tool:
                self._discovered.append((tool, None))
                logger.info(f"  CLI tool loaded: {tool.manifest.name} v{tool.manifest.version} (yaml)")
        except ImportError:
            logger.debug("CLIToolAdapter not available")
        except Exception as e:
            self._errors.append({"path": str(yaml_path), "error": str(e)})
            logger.warning(f"Failed to load YAML plugin '{yaml_path}': {e}")

    def _import_module_from_path(self, module_name: str, file_path: str):
        """从文件路径动态导入 Python 模块"""
        spec = importlib.util.spec_from_file_location(module_name, file_path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module

    def _extract_tools_from_module(self, module, source_path: str) -> List[Tuple[ITool, Optional[List[str]]]]:
        """从 Python 模块中提取 ITool 实例"""
        results = []

        # 1. 查找 ITool 子类实例
        for name, obj in inspect.getmembers(module):
            if name.startswith("_"):
                continue

            # 直接是 ITool 实例
            if isinstance(obj, ITool) and not isinstance(obj, type):
                roles = getattr(obj, "__agent_roles__", None)
                results.append((obj, roles))
                continue

            # 是 ITool 子类
            if inspect.isclass(obj) and issubclass(obj, ITool) and obj is not ITool:
                try:
                    instance = obj()
                    roles = getattr(instance, "__agent_roles__", None)
                    results.append((instance, roles))
                except Exception as e:
                    self._errors.append({"path": source_path, "class": name, "error": str(e)})

        # 2. 查找 create_tool() 工厂函数
        if hasattr(module, "create_tool"):
            try:
                tool = module.create_tool()
                if isinstance(tool, ITool):
                    roles = getattr(module, "__agent_roles__", None)
                    results.append((tool, roles))
            except Exception as e:
                self._errors.append({"path": source_path, "factory": "create_tool", "error": str(e)})

        # 3. 查找 get_tools() 函数 (兼容旧 CoverageTools 等)
        if hasattr(module, "get_tools"):
            try:
                tools = module.get_tools()
                if isinstance(tools, list):
                    for t in tools:
                        if isinstance(t, ITool):
                            results.append((t, None))
            except Exception as e:
                self._errors.append({"path": source_path, "factory": "get_tools", "error": str(e)})

        return results


# ═══════════════════════════════════════════════════════════════
# 示例: 第三方 VCS 工具插件
# ═══════════════════════════════════════════════════════════════

class VCSCompilePlugin(BaseTool):
    """示例: VCS 编译工具 —— 展示第三方如何实现 ITool"""

    @property
    def manifest(self) -> ToolManifest:
        from src.orchestration_plane.l2.communication.tool_protocol import ToolExample
        return ToolManifest(
            name="vcs_compile",
            version="1.0.0",
            description="Compile SystemVerilog design with Synopsys VCS. "
                        "Use this when you need to check if the design compiles without errors.",
            input_schema={
                "type": "object",
                "properties": {
                    "filelist": {"type": "string", "description": "Path to filelist.f"},
                    "top_module": {"type": "string", "description": "Top-level module name"},
                    "options": {"type": "string", "default": "-sverilog -debug_pp",
                                "description": "Additional VCS compile options"},
                },
                "required": ["filelist", "top_module"],
            },
            output_schema={
                "type": "object",
                "properties": {
                    "status": {"type": "string", "enum": ["PASS", "FAIL"]},
                    "errors": {"type": "integer"},
                    "warnings": {"type": "integer"},
                },
            },
            risk_level=ToolRisk.SAFE,
            timeout_s=600.0,
            requires_binaries=["vcs"],
            tags=["simulation", "synopsys", "compile"],
            category="simulation",
            author="SignOffAI",
            examples=[
                ToolExample(
                    description="Compile ALU with default options",
                    args={"filelist": "output/filelist.f", "top_module": "alu_tb_top"},
                    expected_output="status=PASS, errors=0",
                ),
            ],
            tips=["Ensure VCS_HOME is set", "Use -debug_pp for debug access"],
        )

    async def _execute_impl(self, args, context) -> ToolResult:
        filelist = args["filelist"]
        top = args["top_module"]
        options = args.get("options", "-sverilog -debug_pp")

        # Check VCS availability
        vcs_home = context.env.get("VCS_HOME", os.environ.get("VCS_HOME", ""))
        vcs_exe = os.path.join(vcs_home, "bin", "vcs") if vcs_home else "vcs"

        import subprocess
        try:
            result = subprocess.run(
                [vcs_exe, "-f", filelist, "-top", top] + options.split(),
                capture_output=True, text=True, timeout=self.manifest.timeout_s,
                cwd=context.working_dir,
            )
            import re
            error_count = len(re.findall(r"Error", result.stdout + result.stderr))
            warn_count = len(re.findall(r"Warning", result.stdout + result.stderr))
            return ToolResult.ok({
                "status": "PASS" if result.returncode == 0 else "FAIL",
                "errors": error_count,
                "warnings": warn_count,
                "log": (result.stdout + result.stderr)[-5000:],
            })
        except subprocess.TimeoutExpired:
            return ToolResult.fail("VCS compile timed out")
        except FileNotFoundError:
            return ToolResult.fail(f"VCS not found. Please set VCS_HOME or add vcs to PATH.")

    async def check_health(self) -> bool:
        import subprocess
        vcs_home = os.environ.get("VCS_HOME", "")
        vcs = os.path.join(vcs_home, "bin", "vcs") if vcs_home else "vcs"
        try:
            result = subprocess.run([vcs, "-help"], capture_output=True, timeout=10)
            return result.returncode == 0
        except Exception:
            return False
