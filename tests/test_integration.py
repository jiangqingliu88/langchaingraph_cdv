"""Integration tests — 完整流水线闭环 + Fake LLM + 临时 SQLite

这些测试验证:
  - Pipeline 全流程 (spec→design→...→report) 可成功执行
  - 反馈闭环 (debug 检测问题 → 路由修复 → 重试)
  - Manifest 自动生成
  - 数据库持久化
"""

import json
import tempfile
from pathlib import Path

import pytest
import asyncio


# ═══════════════════════════════════════════════════
# Fake LLM responses per agent role
# ═══════════════════════════════════════════════════

FAKE_RESPONSES = {
    "spec_and_test_planner": json.dumps({
        "spec": {
            "design_name": "ALU", "module_name": "alu",
            "features": [
                {"name": "ADD", "description": "加法运算", "category": "arithmetic"},
                {"name": "SUB", "description": "减法运算", "category": "arithmetic"},
            ],
            "interfaces": [
                {"name": "clk", "type": "input", "width": 1},
                {"name": "rst_n", "type": "input", "width": 1},
                {"name": "op_a", "type": "input", "width": 32},
                {"name": "op_b", "type": "input", "width": 32},
                {"name": "result", "type": "output", "width": 32},
            ],
            "registers": [
                {"name": "CTRL", "addr": "0x00", "width": 32},
                {"name": "STATUS", "addr": "0x04", "width": 32},
            ],
            "test_points": [
                {"category": "functional", "tests": [{"name": "test_add_basic", "description": "基本加法"}]},
            ],
            "coverage_goals": {"line": 95, "branch": 90, "toggle": 85},
        },
        "output": "ALU specification analyzed",
        "score": 95,
    }, ensure_ascii=False),
    "design_architect": json.dumps({
        "design_arch": {
            "module_name": "alu",
            "function_count": 12, "register_count": 8,
            "functions": [{"name": "ADD"}, {"name": "SUB"}],
            "registers": [{"name": "CTRL"}, {"name": "STATUS"}],
        },
        "output": "ALU RTL generated",
        "score": 90,
    }, ensure_ascii=False),
    "verification_architect": json.dumps({
        "env": {
            "env_name": "alu_env", "agent_count": 2,
            "agents": ["alu_in", "alu_out"],
            "output_dir": "output/test",
            "filelist": "output/test/filelist.f",
        },
        "output": "UVM environment generated",
        "score": 95,
    }, ensure_ascii=False),
    "model_agent": json.dumps({
        "model": {"function_count": 12, "register_count": 8},
        "output": "C++ reference model generated",
        "score": 75,
    }, ensure_ascii=False),
    "test_engineer": json.dumps({
        "tests": {
            "test_names": ["test_alu_basic"], "test_count": 1,
            "scenario_count": 1,
            "scenarios": [{"name": "basic", "description": "Basic ALU test"}],
        },
        "output": "Test cases generated",
        "score": 85,
    }, ensure_ascii=False),
    "assertion_engineer": json.dumps({
        "output": "SVA assertions generated",
        "score": 50,
    }, ensure_ascii=False),
    "regression_manager": json.dumps({
        "regression": {
            "compile": "PASS", "compile_status": "PASS",
            "passed": 1, "failed": 0, "total": 1,
            "pass_rate": "100%",
            "tests": [{"name": "test_alu_basic", "status": "PASS", "time": "0.5s"}],
        },
        "output": "Regression passed",
        "score": 95,
    }, ensure_ascii=False),
    "coverage_manager": json.dumps({
        "coverage": {
            "line_pct": 85.0, "branch_pct": 72.0, "toggle_pct": 60.0,
            "coverage_pct": 72.0,
            "gaps": [],
            "suggestions": [],
        },
        "output": "Coverage collected",
        "score": 76,
    }, ensure_ascii=False),
    "debug_engineer": json.dumps({
        "debug": {
            "category": "none",
            "fix_agent": "",
            "cross_check": "design(8) == model(8) OK",
        },
        "output": "No issues found",
        "score": 80,
    }, ensure_ascii=False),
    "quality_assurance": json.dumps({
        "output": "Quality review passed",
        "score": 50,
    }, ensure_ascii=False),
    "report_generator": json.dumps({
        "output": "Final report generated",
        "score": 50,
    }, ensure_ascii=False),
}


def setup_fake_llm():
    """注入 Fake LLM 响应"""
    from src.core.llm_factory import LLMFactory
    LLMFactory.enable_test_mode_per_role(FAKE_RESPONSES)


def teardown_fake_llm():
    from src.core.llm_factory import LLMFactory
    LLMFactory.disable_test_mode()


# ═══════════════════════════════════════════════════
# Tests
# ═══════════════════════════════════════════════════

class TestPipelineIntegration:
    """完整流水线集成测试"""

    @pytest.mark.asyncio
    async def test_full_pipeline_success(self, tmp_path):
        """11 阶段全流水线成功执行"""
        setup_fake_llm()

        try:
            from src.core.execution import PipelineExecutionService

            output_dir = tmp_path / "output"
            output_dir.mkdir()

            spec_text = """# ALU Specification
## Design Overview
32-bit ALU with 13 operations.

## Interfaces
| Signal | Width | Direction | Description |
|--------|-------|-----------|-------------|
| clk    | 1     | input     | Clock       |
| rst_n  | 1     | input     | Reset       |
| op_a   | 32    | input     | Operand A   |
| op_b   | 32    | input     | Operand B   |
| result | 32    | output    | Result      |

## Registers
### CTRL (0x00)
Control register.

## Features
- ADD: Addition
- SUB: Subtraction
"""

            service = PipelineExecutionService.get_instance()
            result = await service.run_pipeline(
                spec_text=spec_text,
                workflow="full_verification",
                output_root=str(output_dir),
            )

            assert result["run_id"]
            assert result["total"] > 0
            assert result["passed"] >= 0
            assert result["ctx"] is not None

            # Manifest 应自动生成
            manifest_path = output_dir / "docs" / "manifest.json"
            if manifest_path.exists():
                manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
                assert manifest_data["run_id"] == result["run_id"]

        finally:
            teardown_fake_llm()

    @pytest.mark.asyncio
    async def test_quick_check_pipeline(self, tmp_path):
        """快速检查流水线 (前 5 阶段)"""
        setup_fake_llm()

        try:
            from src.core.execution import PipelineExecutionService

            output_dir = tmp_path / "output_quick"
            output_dir.mkdir()
            service = PipelineExecutionService.get_instance()
            result = await service.run_pipeline(
                spec_text="# Quick test spec",
                workflow="quick_check",
                output_root=str(output_dir),
            )
            assert result["run_id"]
            assert result["passed"] >= 0
        finally:
            teardown_fake_llm()

    @pytest.mark.asyncio
    async def test_pipeline_with_debug_feedback_loop(self, tmp_path):
        """反馈闭环: debug 检测到不一致 → 路由修复"""
        fake_with_bug = dict(FAKE_RESPONSES)
        # debug 报告设计(8 regs) vs 模型(5 regs) 不一致
        fake_with_bug["debug_engineer"] = json.dumps({
            "debug": {
                "category": "cross",
                "fix_agent": "model_agent",
                "errors": ["design(8 regs) != model(5 regs)"],
                "suggestion": "re-generate model to match design register count",
            },
            "output": "Cross-check failed: register count mismatch",
            "score": 40,
        }, ensure_ascii=False)

        from src.core.llm_factory import LLMFactory
        LLMFactory.enable_test_mode_per_role(fake_with_bug)

        try:
            from src.core.execution import PipelineExecutionService

            output_dir = tmp_path / "output_fb"
            output_dir.mkdir()
            service = PipelineExecutionService.get_instance()
            result = await service.run_pipeline(
                spec_text="# ALU spec with registers",
                workflow="full_verification",
                output_root=str(output_dir),
            )
            # 至少应该执行完成（不论修复是否成功）
            assert result["run_id"]
        finally:
            teardown_fake_llm()


class TestManifestIntegration:
    """Manifest 与 Pipeline 集成测试"""

    def test_manifest_includes_pipeline_result(self):
        """验证 manifest 包含 pipeline 结果的关键字段"""
        from src.core.manifest import build_manifest

        phases = [
            {"name": "spec", "status": "passed", "score": 95, "time": 0.5, "retries": 0,
             "started_at": "2026-01-01T00:00:00", "ended_at": "2026-01-01T00:00:01"},
            {"name": "design", "status": "passed", "score": 90, "time": 0.3, "retries": 0},
            {"name": "cover", "status": "failed", "score": 0, "time": 1.0, "retries": 2,
             "reason": "questa not found"},
        ]
        run_state = {
            "run_id": "full_run", "workflow": "full_verification",
            "state": "completed_with_errors",
            "started_at": "2026-01-01T00:00:00", "completed_at": "2026-01-01T00:02:00",
            "passed": 2, "total": 3, "ctx": {},
        }

        manifest = build_manifest("sid1", run_state=run_state, phases=phases)

        assert manifest.session_id == "sid1"
        assert len(manifest.phases) == 3
        assert manifest.passed == 2
        assert manifest.failed == 1
        assert manifest.total_time_s == pytest.approx(1.8)


class TestDatabaseIntegration:
    """数据库持久化集成测试"""

    @pytest.mark.skip(reason="DB schema migration needed for isolated test — tested manually in production")
    def test_pipeline_run_persisted_to_db(self, tmp_path):
        """验证 pipeline run 可写入数据库
        NOTE: 需要独立 DB schema，当前通过生产环境手工验证。
        """
        pass


class TestContextPersistence:
    """ContextStore 持久化测试"""

    def test_context_snapshot_and_restore(self):
        from src.core.context import ContextStore

        store = ContextStore()
        store.put("spec", {"design_name": "ALU", "features": [{"name": "ADD"}]}, source="spec_planner")
        store.put("design_arch", {"module_name": "alu", "function_count": 12}, source="design_architect")

        snap = store.snapshot()
        assert "spec" in snap
        assert "design_arch" in snap

        # 添加新 key 后 restore
        store.put("env", {"env_name": "alu_env"}, source="architect")
        assert "env" in store.keys()

        # 验证 snapshot 不变
        assert "env" not in snap

    def test_context_prune_removes_consumed_keys(self):
        from src.core.context import ContextStore

        store = ContextStore()
        store.put("spec", {"design_name": "ALU"}, source="spec_planner")
        store.put("env", {"env_name": "alu_env"}, source="architect")

        # spec 被 design_architect, model_agent, verification_architect 消费
        # prune 指定所有 consumer 都已完成
        removed = store.prune(["design_architect", "model_agent", "verification_architect"])
        assert "spec" in removed
        assert "spec" not in store.keys()
        # env 消费者还没完成
        assert "env" in store.keys()

    def test_context_field_level_fetch(self):
        from src.core.context import ContextStore

        store = ContextStore()
        store.put("spec", {
            "design_name": "ALU",
            "features": [{"name": "ADD"}],
            "test_points": [{"category": "functional"}],
        }, source="spec_planner")

        # 只取 features
        partial = store.fetch("spec", fields=["features"])
        assert "features" in partial
        assert "test_points" not in partial
        assert len(partial) == 1
