"""
E2E tests: Pipeline 失败路径与恢复

覆盖: 检查点保存/恢复、阶段超时、错误码分类、资源调度
"""
import pytest
import asyncio
from pathlib import Path
from datetime import datetime


class TestPipelineCheckpoint:
    """流水线检查点测试"""

    def test_checkpoint_creation(self):
        """创建检查点记录进度的信息"""
        from src.core.checkpoint import get_checkpoint_mgr
        mgr = get_checkpoint_mgr()
        cp = mgr.create("test_run_cp", "full_verification", 8)

        assert cp.run_id == "test_run_cp"
        assert cp.total_phases == 8
        assert cp.current_phase_index == 0
        assert cp.status == "running"
        assert cp.resume_count == 0

    def test_checkpoint_pause_resume(self):
        """暂停和恢复"""
        from src.core.checkpoint import get_checkpoint_mgr
        mgr = get_checkpoint_mgr()
        mgr.create("test_pause", "full_verification", 8)
        mgr.update("test_pause", "design_analysis", 2, "module_parse", 1)

        # 暂停
        ok = mgr.pause("test_pause")
        assert ok is True
        cp = mgr.get("test_pause")
        assert cp.status == "paused"

        # 恢复
        resumed = mgr.resume("test_pause")
        assert resumed is not None
        assert resumed.status == "resumed"
        assert resumed.resume_count == 1
        assert resumed.current_phase == "design_analysis"

    def test_checkpoint_list_paused(self):
        """列出所有暂停的流水线"""
        from src.core.checkpoint import get_checkpoint_mgr
        mgr = get_checkpoint_mgr()
        mgr.create("test_list_1", "full_verification", 8)
        mgr.create("test_list_2", "regression_only", 3)
        mgr.pause("test_list_1")
        mgr.pause("test_list_2")

        paused = mgr.list_paused()
        assert len(paused) >= 2
        run_ids = [p["run_id"] for p in paused]
        assert "test_list_1" in run_ids

    def test_checkpoint_progress_tracking(self):
        """检查点追踪阶段进度"""
        from src.core.checkpoint import get_checkpoint_mgr
        mgr = get_checkpoint_mgr()
        mgr.create("test_progress", "full_verification", 8)

        mgr.update("test_progress", "spec_analysis", 0)
        mgr.update("test_progress", "design_arch", 1)
        mgr.update("test_progress", "uvm_gen", 2)

        cp = mgr.get("test_progress")
        assert cp.current_phase == "uvm_gen"
        assert cp.current_phase_index == 2

    def test_resume_nonexistent_checkpoint(self):
        """恢复不存在的检查点返回 None"""
        from src.core.checkpoint import get_checkpoint_mgr
        mgr = get_checkpoint_mgr()
        cp = mgr.resume("nonexistent_run")
        assert cp is None


class TestErrorCodes:
    """错误码测试"""

    def test_error_code_categories(self):
        """错误码按模块分段"""
        from src.infra.error_handler import ErrorCode
        # 认证
        assert "E2001" in [e.value for e in ErrorCode]
        # 流水线
        assert "E3001" in [e.value for e in ErrorCode]
        # 签核
        assert "E4001" in [e.value for e in ErrorCode]
        # 数据库
        assert "E7001" in [e.value for e in ErrorCode]

    def test_platform_error_structure(self):
        """统一错误结构体包含所有必要字段"""
        from src.infra.error_handler import PlatformError, ErrorCode, ErrorSeverity, RecoveryAction
        e = PlatformError(
            code=ErrorCode.PIPELINE_TIMEOUT,
            message="Phase 'regression' timed out after 3600s",
            severity=ErrorSeverity.ERROR,
            recovery=RecoveryAction.RETRY,
            domain="pipeline",
            detail={"phase": "regression", "timeout_s": 3600},
        )
        d = e.to_dict()
        assert d["error_code"] == "E3004"
        assert d["message"].startswith("Phase")
        assert d["severity"] == "error"
        assert d["recovery"] == "retry"
        assert d["domain"] == "pipeline"

    def test_factory_helpers(self):
        """便捷构造函数"""
        from src.infra.error_handler import pipeline_error, signoff_error, db_error, ErrorCode, RecoveryAction
        pe = pipeline_error(ErrorCode.PIPELINE_PHASE_FAILED, "Phase failed", recovery=RecoveryAction.SKIP)
        assert pe.code == ErrorCode.PIPELINE_PHASE_FAILED
        assert pe.domain == "pipeline"

        se = signoff_error(ErrorCode.SIGNOFF_CONCURRENT_UPDATE, "Conflict")
        assert se.code == ErrorCode.SIGNOFF_CONCURRENT_UPDATE
        assert se.domain == "signoff"

    def test_recovery_registry(self):
        """恢复策略注册表"""
        from src.infra.error_handler import get_recovery_registry, ErrorCode
        reg = get_recovery_registry()
        rule = reg.get_rule(ErrorCode.DB_CONNECTION_ERROR)
        assert rule is not None
        assert rule.max_retries == 3
        assert rule.backoff_seconds > 0


class TestResourceScheduler:
    """资源调度测试"""

    def test_scheduler_default_pool(self):
        """默认资源池配置"""
        from src.infra.resource_scheduler import get_scheduler
        sched = get_scheduler()
        status = sched.get_status()
        assert status["pool"]["max_agents"] == 8
        assert status["pool"]["active_agents"] == 0

    def test_scheduler_configure(self):
        """动态配置资源池"""
        from src.infra.resource_scheduler import get_scheduler
        sched = get_scheduler()
        sched.configure(max_agents=4, max_regressions=1)
        status = sched.get_status()
        assert status["pool"]["max_agents"] == 4

    def test_dependency_graph_build(self):
        """依赖图构建"""
        from src.infra.resource_scheduler import get_dep_graph
        graph = get_dep_graph()
        d = graph.build_graph("full_verification")
        assert d["total_nodes"] == 11
        assert d["total_edges"] >= 10
        assert len(d["levels"]) >= 5

    def test_dependency_graph_agent_deps(self):
        """单个 agent 依赖查询"""
        from src.infra.resource_scheduler import get_dep_graph
        graph = get_dep_graph()
        deps = graph.get_agent_deps("coverage_manager")
        assert deps["role"] == "coverage_manager"
        assert "regression_manager" in deps["upstream"]
        assert "test_engineer" in deps["upstream"]

    def test_dependency_runnable_check(self):
        """依赖满足检查"""
        from src.infra.resource_scheduler import get_dep_graph
        graph = get_dep_graph()
        # test_engineer 依赖 verification_architect
        assert not graph.check_runnable("test_engineer", [])
        assert graph.check_runnable("test_engineer", ["verification_architect", "design_architect"])
        assert graph.check_runnable("spec_and_test_planner", [])


class TestContextSnapshot:
    """上下文快照测试"""

    def test_snapshot_capture(self):
        """捕获执行上下文"""
        from src.infra.context_snapshot import get_snapshotter
        snap = get_snapshotter()
        cp = snap.capture("test_run", "full_verification", "spec_analysis",
                          spec_text="UART IP specification v1.0")
        assert cp.snapshot_id.startswith("snap_test_run")
        assert cp.workflow == "full_verification"
        assert cp.spec_hash != ""
        assert cp.python_version != ""

    def test_snapshot_save_load(self):
        """保存和加载快照"""
        from src.infra.context_snapshot import get_snapshotter
        snap = get_snapshotter()
        snap.capture("test_save", "quick_check", "design", spec_text="Test spec")
        snap.save("snap_test_save_design")
        loaded = snap.load("snap_test_save_design")
        assert loaded is not None
        assert loaded["run_id"] == "test_save"

    def test_artifact_classification(self):
        """产物自动归类"""
        from src.infra.context_snapshot import ArtifactClassifier
        clf = ArtifactClassifier("output")
        # HTML + "report" in name → should match a report category
        r = clf.classify_file(Path("report_summary.html"))
        assert r is not None
        # JSON + "coverage" in name → coverage_report
        r2 = clf.classify_file(Path("coverage_report.json"))
        assert r2 is not None
        # .log extension → debug_log
        assert clf.classify_file(Path("error.log")) == "debug_log"
        # "manifest" in name → manifest
        r3 = clf.classify_file(Path("manifest.json"))
        assert r3 is not None
        # .sv → testcase or rtl_output
        r4 = clf.classify_file(Path("test_uart.sv"))
        assert r4 is not None

    def test_artifact_catalog(self):
        """产物分类目录"""
        from src.infra.context_snapshot import ArtifactClassifier
        clf = ArtifactClassifier("output")
        catalog = clf.get_catalog()
        assert len(catalog) == 13  # 13 categories