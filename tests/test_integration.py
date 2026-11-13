"""Integration tests — 流水线闭环 + Manifest + 数据库 + Context 持久化

需要 LLM_API_KEY 的测试: 设置环境变量 RUN_INTEGRATION_TESTS=1 来启用。
不需要 LLM 的测试: 始终运行。
"""

import json
import os
from pathlib import Path

import pytest


# ═══════════════════════════════════════════════════
# Helper
# ═══════════════════════════════════════════════════

_requires_llm = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION_TESTS") != "1",
    reason="设置 RUN_INTEGRATION_TESTS=1 并配置 .env 中的 LLM_API_KEY 来运行",
)


# ═══════════════════════════════════════════════════
# Pipeline 集成测试 (需要真实 LLM)
# ═══════════════════════════════════════════════════

class TestManifestIntegration:
    """Manifest 与 Pipeline 集成测试"""

    def test_manifest_includes_pipeline_result(self):
        """验证 manifest 包含 pipeline 结果的关键字段"""
        from src.orchestration_plane.l2.evidence.manifest import ManifestBuilder

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

        manifest = ManifestBuilder().build("sid1", run_state=run_state, phases=phases)

        assert manifest.session_id == "sid1"
        assert len(manifest.phases) == 3
        assert manifest.passed == 2
        assert manifest.failed == 1


# ═══════════════════════════════════════════════════
# 数据库持久化 (需要独立 DB)
# ═══════════════════════════════════════════════════

class TestDatabaseIntegration:
    """数据库持久化集成测试"""

    @pytest.mark.skip(reason="需要独立 DB schema — 生产环境手工验证")
    def test_pipeline_run_persisted_to_db(self, tmp_path):
        pass


# ═══════════════════════════════════════════════════
# ContextStore 持久化测试 (不需要 LLM)
# ═══════════════════════════════════════════════════

class TestContextPersistence:
    """ContextStore 持久化测试"""

    def test_context_snapshot_and_restore(self):
        from src.orchestration_plane.l2.context.context import ContextStore

        store = ContextStore()
        store.put("spec", {"design_name": "ALU", "features": [{"name": "ADD"}]}, source="spec_planner")
        store.put("design_arch", {"module_name": "alu", "function_count": 12}, source="design_architect")

        snap = store.snapshot()
        assert "spec" in snap
        assert "design_arch" in snap

        store.put("env", {"env_name": "alu_env"}, source="architect")
        assert "env" in store.keys()
        assert "env" not in snap

    def test_context_prune_removes_consumed_keys(self):
        from src.orchestration_plane.l2.context.context import ContextStore

        store = ContextStore()
        store.put("spec", {"design_name": "ALU"}, source="spec_planner")
        store.put("env", {"env_name": "alu_env"}, source="architect")

        removed = store.prune(["design", "model", "rtl", "uvm"])
        assert "spec" in removed
        assert "spec" not in store.keys()
        assert "env" in store.keys()

    def test_context_field_level_fetch(self):
        from src.orchestration_plane.l2.context.context import ContextStore

        store = ContextStore()
        store.put("spec", {
            "design_name": "ALU",
            "features": [{"name": "ADD"}],
            "test_points": [{"category": "functional"}],
        }, source="spec_planner")

        partial = store.fetch("spec", fields=["features"])
        assert "features" in partial
        assert "test_points" not in partial
        assert len(partial) == 1
