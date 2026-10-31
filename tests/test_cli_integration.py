"""
CLI 集成测试 — 覆盖核心命令和审批门控

用法:
  pytest tests/test_cli_integration.py -v
  pytest tests/test_cli_integration.py -v -k "test_approval"
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner


# ── Fixtures ───────────────────────────────────────────────

@pytest.fixture
def runner():
    """Click CLI test runner"""
    return CliRunner()


@pytest.fixture
def sample_spec():
    """创建临时 Spec 文件"""
    with tempfile.NamedTemporaryFile(
        mode='w', suffix='.md', delete=False, encoding='utf-8'
    ) as f:
        f.write("""# UART 模块规格

## 功能描述
UART 串行收发模块，支持 8N1 格式，波特率可配置。

## 接口
- APB 配置接口
- TX 串行输出
- RX 串行输入
- IRQ 中断输出

## 测试点
- 基本收发
- 波特率切换
- FIFO 满/空
- 错误检测
""")
        return Path(f.name)


# ── 1. approval.py 单元测试 ─────────────────────────────────

class TestApprovalGate:
    def test_auto_mode_bypasses_all(self):
        """auto 模式：全部自动通过，不等待输入"""
        from src.layers.l2_orchestration.governance.approval import create_approval_gate, ApprovalDecision
        gate = create_approval_gate("auto")
        assert gate.mode.value == "auto"
        assert not gate.requires_approval("any_stage", "critical")

        record = gate.ask("write_rtl", "mock summary", "low")
        assert record.decision == ApprovalDecision.APPROVE
        assert "自动通过" in record.reason

    def test_interactive_mode_requires_all(self):
        """interactive 模式：所有阶段都需要审批"""
        from src.layers.l2_orchestration.governance.approval import create_approval_gate, ApprovalMode
        gate = create_approval_gate("interactive")
        assert gate.mode == ApprovalMode.INTERACTIVE
        assert gate.requires_approval("any_stage", "low")

    def test_interactive_approve(self):
        """交互模式下输入 'y' → approve"""
        from src.layers.l2_orchestration.governance.approval import ApprovalGate, ApprovalMode, ApprovalDecision
        gate = ApprovalGate(mode=ApprovalMode.INTERACTIVE, input_func=lambda _: "y")
        record = gate.ask("write_rtl", "mock", "low")
        assert record.decision == ApprovalDecision.APPROVE

    def test_interactive_reject(self):
        """交互模式下输入 'n' → reject"""
        from src.layers.l2_orchestration.governance.approval import ApprovalGate, ApprovalMode, ApprovalDecision
        gate = ApprovalGate(mode=ApprovalMode.INTERACTIVE, input_func=lambda _: "n")
        record = gate.ask("UVM", "mock", "medium")
        assert record.decision == ApprovalDecision.REJECT

    def test_interactive_skip(self):
        """交互模式下输入 's' → skip"""
        from src.layers.l2_orchestration.governance.approval import ApprovalGate, ApprovalMode, ApprovalDecision
        gate = ApprovalGate(mode=ApprovalMode.INTERACTIVE, input_func=lambda _: "s")
        record = gate.ask("cover", "mock", "low")
        assert record.decision == ApprovalDecision.SKIP

    def test_threshold_mode(self):
        """threshold 模式：只有高风险才审批"""
        from src.layers.l2_orchestration.governance.approval import ApprovalGate, ApprovalMode
        gate = ApprovalGate(mode=ApprovalMode.THRESHOLD, risk_threshold="high")
        assert not gate.requires_approval("low_risk", "low")
        assert not gate.requires_approval("medium_risk", "medium")
        assert gate.requires_approval("high_risk", "high")
        assert gate.requires_approval("critical", "critical")

    def test_summary_json(self):
        """审批摘要可以序列化为 JSON"""
        from src.layers.l2_orchestration.governance.approval import ApprovalGate, ApprovalMode
        gate = ApprovalGate(mode=ApprovalMode.INTERACTIVE, input_func=lambda _: "y")
        gate.ask("design", "passed", "low")
        gate.ask("UVM", "passed", "low")

        summary = gate.summary()
        assert summary["total_gates"] == 2
        assert summary["approved"] == 2
        assert summary["rejected"] == 0

        json_str = gate.to_json()
        parsed = json.loads(json_str)
        assert parsed["total_gates"] == 2


# ── 3. CLI 命令测试 ─────────────────────────────────────────

class TestCLIBasicCommands:
    def test_help(self, runner):
        """vagent --help"""
        from src.cli.commands import cli
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "SignOffAI" in result.output

    def test_init(self, runner):
        """vagent init"""
        from src.cli.commands import cli
        with tempfile.TemporaryDirectory() as tmp:
            result = runner.invoke(cli, ["init", "--output-dir", tmp])
            assert result.exit_code == 0
            # make_output_root creates {tmp}_{user}_{YYYYMMDD_HHMMSS} as sibling of tmp
            # search for docs/ in parent directory (tmp_dir or sibling dirs)
            parent = Path(tmp).parent
            found = False
            for d in parent.iterdir():
                if d.is_dir() and (d / "docs").exists():
                    found = True
                    break
            assert found, f"docs/ not found under any sibling of {tmp}"



class TestCLISubcommandsExist:
    """确保所有子命令都可调用"""

    def test_signoff_subcommands(self, runner):
        from src.cli.commands import cli
        for cmd in ["generate", "export", "verify", "checklist", "diff"]:
            result = runner.invoke(cli, ["signoff", cmd, "--help"])
            assert result.exit_code == 0, f"signoff {cmd} failed"

    def test_diff_subcommands(self, runner):
        from src.cli.commands import cli
        for cmd in ["coverage", "spec", "regression"]:
            result = runner.invoke(cli, ["diff", cmd, "--help"])
            assert result.exit_code == 0, f"diff {cmd} failed"

    def test_tool_subcommands(self, runner):
        from src.cli.commands import cli
        for cmd in ["list", "show", "call", "history"]:
            result = runner.invoke(cli, ["tool", cmd, "--help"])
            assert result.exit_code == 0, f"tool {cmd} failed"

    def test_agent_subcommands(self, runner):
        from src.cli.commands import cli
        for cmd in ["list", "show", "run"]:
            result = runner.invoke(cli, ["agent", cmd, "--help"])
            assert result.exit_code == 0, f"agent {cmd} failed"

    def test_debug_subcommands(self, runner):
        from src.cli.commands import cli
        for cmd in ["log", "analyze", "repl"]:
            result = runner.invoke(cli, ["debug", cmd, "--help"])
            assert result.exit_code == 0, f"debug {cmd} failed"

    def test_config_subcommands(self, runner):
        from src.cli.commands import cli
        for cmd in ["show", "set", "init", "validate"]:
            result = runner.invoke(cli, ["config", cmd, "--help"])
            assert result.exit_code == 0, f"config {cmd} failed"

    def test_project_subcommands(self, runner):
        from src.cli.commands import cli
        for cmd in ["init", "status", "info", "list", "clean"]:
            result = runner.invoke(cli, ["project", cmd, "--help"])
            assert result.exit_code == 0, f"project {cmd} failed"

    def test_spec_subcommands(self, runner):
        from src.cli.commands import cli
        for cmd in ["analyze", "validate", "convert", "trace"]:
            result = runner.invoke(cli, ["spec", cmd, "--help"])
            assert result.exit_code == 0, f"spec {cmd} failed"

    def test_ci_subcommands(self, runner):
        from src.cli.commands import cli
        for cmd in ["verify", "check", "precheck"]:
            result = runner.invoke(cli, ["ci", cmd, "--help"])
            assert result.exit_code == 0, f"ci {cmd} failed"

    def test_regression_subcommands(self, runner):
        from src.cli.commands import cli
        for cmd in ["run", "report", "trend", "compare"]:
            result = runner.invoke(cli, ["regression", cmd, "--help"])
            assert result.exit_code == 0, f"regression {cmd} failed"

    def test_coverage_subcommands(self, runner):
        from src.cli.commands import cli
        for cmd in ["report", "gaps", "trend", "merge"]:
            result = runner.invoke(cli, ["coverage", cmd, "--help"])
            assert result.exit_code == 0, f"coverage {cmd} failed"

    def test_env_subcommands(self, runner):
        from src.cli.commands import cli
        for cmd in ["generate", "validate", "compile", "template"]:
            result = runner.invoke(cli, ["env", cmd, "--help"])
            assert result.exit_code == 0, f"env {cmd} failed"


# ── 4. ContextStore.summary() 测试 ──────────────────────────

class TestContextStoreSummary:
    def test_summary_returns_structure(self):
        from src.layers.l2_orchestration.context.context import ContextStore
        store = ContextStore()
        store.put("spec", {"features": ["f1"]}, source="spec_planner")
        store.put("design_arch", {"modules": ["m1"]}, source="design_architect")

        s = store.summary()
        assert "keys" in s
        assert "entry_count" in s
        assert "sources" in s
        assert "snapshot" in s
        assert s["entry_count"] == 2
        assert "spec_planner" in s["sources"]
        assert "design_architect" in s["sources"]




# ── 8. dvsim 移除验证 ───────────────────────────────────────

class TestDvsimRemoval:
    def test_dvsim_directories_absent(self):
        """确认 dvsim 目录已删除"""
        assert not Path("src/tools/dvsim").exists(), "dvsim should be removed"
        assert not Path("src/tools/dvsim_adapter").exists(), "dvsim_adapter should be removed"

    def test_no_dvsim_import_in_agents(self):
        """确认没有 Agent 引用 dvsim"""
        import ast
        for agent_dir in Path("src/executors").iterdir():
            if agent_dir.is_dir():
                for py_file in agent_dir.rglob("*.py"):
                    code = py_file.read_text(encoding="utf-8", errors="replace")
                    assert "import dvsim" not in code, \
                        f"{py_file} imports dvsim"
                    assert "from dvsim" not in code, \
                        f"{py_file} imports from dvsim"


# ── 9. 三类工程服务工作流（同一条 CLI/执行链路）────────────

class TestEngineeringServiceCommands:
    def test_workflow_commands_are_registered(self, runner):
        from src.cli.commands import cli
        for cmd in ["optimize-regression", "coverage-closure",
                    "metrics", "incremental"]:
            result = runner.invoke(cli, [cmd, "--help"])
            assert result.exit_code == 0, f"{cmd} --help failed: {result.output}"

    def test_verify_accepts_config_and_rtl(self, runner):
        from src.cli.commands import cli
        result = runner.invoke(cli, ["verify", "--help"])
        assert result.exit_code == 0
        assert "--config" in result.output
        assert "--rtl" in result.output

    def test_soc_subcommands_are_registered(self, runner):
        from src.cli.commands import cli
        for cmd in ["check", "golden", "run"]:
            result = runner.invoke(cli, ["soc", cmd, "--help"])
            assert result.exit_code == 0, f"soc {cmd}: {result.output}"
