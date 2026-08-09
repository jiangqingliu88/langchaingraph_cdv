"""
CLI Tool Adapter — 将外部 CLI 工具适配为 ITool (Phase 2)

支持通过 YAML 配置零代码接入外部工具:
  - EDA 工具: VCS, QuestaSim, Verdi, JasperGold, SpyGlass
  - 自定义脚本: Python, Perl, Tcl, Shell
  - 报告工具: vcover, urg, cov_report

YAML 配置格式:
  tool.yaml:
    name: vcs_compile
    version: "1.0.0"
    description: Compile SystemVerilog with VCS
    risk_level: safe
    exec:
      command: vcs -f {filelist} -top {top_module} {options}
      working_dir: "{output_dir}"
    input_schema:
      type: object
      properties:
        filelist: {type: string}
        top_module: {type: string}
      required: [filelist, top_module]
    parse_output:
      status: {regex: "Compilation (succeeded|failed)", map: {succeeded: PASS, failed: FAIL}}

用法:
  from src.core.cli_tool_adapter import CLIToolAdapter, CLIToolLoader
  adapter = CLIToolAdapter("path/to/tool.yaml")
  tool = adapter.load()
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import structlog
import yaml as _yaml

from src.core.tool_protocol import (
    ITool, ToolManifest, ToolResult, ExecutionContext,
    ToolRisk, ToolStatus, ToolExample, BaseTool,
)

logger = structlog.get_logger()


class CLIToolAdapter:
    """将 YAML 配置的外部 CLI 工具适配为 ITool"""

    def __init__(self, config_path: str):
        self._config_path = Path(config_path)
        self._config: Dict[str, Any] = {}
        self._tool: Optional[CLIWrapperTool] = None

    def load(self) -> Optional[ITool]:
        """从 YAML 配置加载工具"""
        if not self._config_path.exists():
            logger.warning(f"CLI tool config not found: {self._config_path}")
            return None

        try:
            self._config = _yaml.safe_load(self._config_path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"Failed to parse {self._config_path}: {e}")
            return None

        if not isinstance(self._config, dict) or "name" not in self._config:
            logger.warning(f"Invalid tool config: missing 'name'")
            return None

        self._tool = CLIWrapperTool(self._config, str(self._config_path.parent))
        return self._tool

    @classmethod
    def from_dict(cls, config: Dict[str, Any], home_dir: str = ".") -> ITool:
        """直接从 dict 创建（无需 YAML 文件）"""
        return CLIWrapperTool(config, home_dir)


class CLIWrapperTool(BaseTool):
    """YAML 配置驱动的 CLI 工具包装器"""

    def __init__(self, config: Dict[str, Any], home_dir: str = "."):
        super().__init__()
        self._config = config
        self._home_dir = home_dir
        self._manifest = self._parse_manifest()

    @property
    def manifest(self) -> ToolManifest:
        return self._manifest

    def _parse_manifest(self) -> ToolManifest:
        c = self._config
        risk_map = {"safe": ToolRisk.SAFE, "write": ToolRisk.WRITE, "danger": ToolRisk.DANGER}

        # Parse examples
        examples = []
        for ex in c.get("examples", []):
            examples.append(ToolExample(
                description=ex.get("description", ""),
                args=ex.get("args", {}),
                expected_output=ex.get("expected_output", ""),
            ))

        return ToolManifest(
            name=c["name"],
            version=c.get("version", "1.0.0"),
            description=c.get("description", ""),
            input_schema=c.get("input_schema", {"type": "object", "properties": {}, "required": []}),
            output_schema=c.get("output_schema", {"type": "object", "properties": {}}),
            risk_level=risk_map.get(c.get("risk_level", "safe"), ToolRisk.SAFE),
            timeout_s=c.get("timeout_s", 300.0),
            retry_count=c.get("retry_count", 0),
            requires_binaries=c.get("requires_binaries", []),
            requires_packages=c.get("requires_packages", []),
            env_vars=c.get("env_vars", {}),
            author=c.get("author", ""),
            tags=c.get("tags", []),
            category=c.get("category", ""),
            status=ToolStatus.ACTIVE,
            examples=examples,
            tips=c.get("tips", []),
            homepage=c.get("homepage", ""),
        )

    async def _execute_impl(self, args: Dict[str, Any], context: ExecutionContext) -> ToolResult:
        exec_cfg = self._config.get("exec", {})
        command = exec_cfg.get("command", "")

        if not command:
            return ToolResult.fail("No 'exec.command' defined in tool config")

        # 模板替换: {arg_name} → arg value
        template_vars = dict(args)
        template_vars["output_dir"] = context.output_dir
        template_vars["working_dir"] = context.working_dir
        template_vars["project_name"] = context.project_name
        template_vars["run_id"] = context.run_id

        resolved_cmd = command
        for key, val in template_vars.items():
            resolved_cmd = resolved_cmd.replace(f"{{{key}}}", str(val))

        # 环境变量
        extra_env = {}
        for ev_key, ev_val in self._config.get("exec", {}).get("env", {}).items():
            # 支持 $VAR 展开
            expanded = os.path.expandvars(str(ev_val))
            extra_env[ev_key] = expanded

        # 工作目录
        working_dir = exec_cfg.get("working_dir", context.working_dir)
        working_dir = working_dir.format(**template_vars)
        if working_dir and Path(working_dir).exists():
            cwd = working_dir
        else:
            cwd = context.working_dir

        # 执行
        try:
            proc = await asyncio.create_subprocess_shell(
                resolved_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env={**os.environ, **extra_env},
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=self.manifest.timeout_s,
            )

            stdout_text = stdout.decode("utf-8", errors="replace")
            stderr_text = stderr.decode("utf-8", errors="replace")
            combined = stdout_text + "\n" + stderr_text

            # 解析输出
            parse_cfg = self._config.get("parse_output", {})
            data: Dict[str, Any] = {"raw_stdout": stdout_text[-5000:],
                                     "raw_stderr": stderr_text[-2000:],
                                     "returncode": proc.returncode}

            for field, rule in parse_cfg.items():
                regex = rule.get("regex", "")
                group = rule.get("group", 0)
                mapping = rule.get("map", {})
                default = rule.get("default", "")

                m = re.search(regex, combined)
                if m:
                    raw_value = m.group(group) if group else m.group(0)
                    data[field] = mapping.get(raw_value, raw_value) if mapping else raw_value
                else:
                    data[field] = default

            success = proc.returncode == 0
            return ToolResult(success=success, data=data,
                            error=stderr_text[:500] if not success else None)

        except asyncio.TimeoutError:
            return ToolResult.fail(f"CLI tool timed out after {self.manifest.timeout_s}s")
        except Exception as e:
            return ToolResult.fail(str(e)[:500])

    async def check_health(self) -> bool:
        # 检查 requires_binaries 中列出的二进制
        for binary in self.manifest.requires_binaries:
            import shutil
            if not shutil.which(binary):
                # 也检查 env_vars
                found = False
                for ev_key in self.manifest.env_vars:
                    ev_val = os.environ.get(ev_key, "")
                    binary_path = os.path.join(ev_val, "bin", binary)
                    if os.path.exists(binary_path):
                        found = True
                        break
                if not found:
                    logger.warning(f"Required binary '{binary}' not found for tool '{self.manifest.name}'")
                    return False
        return True


class CLIToolLoader:
    """批量发现 CLI 工具配置"""

    def __init__(self, search_dirs: List[str] = None):
        self._search_dirs = search_dirs or [
            ".signoffai/cli_tools/",
            "~/.signoffai/cli_tools/",
            "config/tools/",
        ]

    def discover(self) -> List[Tuple[ITool, Optional[List[str]]]]:
        """发现所有 CLI 工具"""
        tools = []
        for d in self._search_dirs:
            path = Path(d).expanduser()
            if not path.exists():
                continue
            for yaml_file in sorted(path.glob("*.yaml")):
                try:
                    adapter = CLIToolAdapter(str(yaml_file))
                    tool = adapter.load()
                    if tool:
                        # 检查 roles 配置
                        config = _yaml.safe_load(yaml_file.read_text(encoding="utf-8"))
                        roles = config.get("agent_roles", None)
                        tools.append((tool, roles))
                except Exception as e:
                    logger.warning(f"Failed to load CLI tool '{yaml_file}': {e}")
        return tools
