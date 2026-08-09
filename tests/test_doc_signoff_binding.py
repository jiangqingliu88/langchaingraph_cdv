"""
E2E tests: 文档工作流与签核联动

覆盖: 文档状态转移 / doc-signoff 绑定 / 文档追踪链 / 一致性检查
"""
import pytest
import asyncio


class TestDocStateTransitions:
    """文档状态转移测试"""

    def test_doc_state_enums(self):
        """DocState 枚举完整性"""
        from src.core.domain_registry import DocState
        states = {s.value for s in DocState}
        assert "draft" in states
        assert "review" in states
        assert "approved" in states
        assert "deprecated" in states

    def test_doc_valid_transitions(self):
        """合法转移"""
        from src.core.domain_registry import is_valid_transition
        assert is_valid_transition("doc", "draft", "review")
        assert is_valid_transition("doc", "review", "approved")
        assert is_valid_transition("doc", "approved", "deprecated")

    def test_doc_invalid_transitions_blocked(self):
        """非法转移拦截"""
        from src.core.domain_registry import require_valid_transition
        with pytest.raises(ValueError):
            require_valid_transition("doc", "approved", "draft")
        with pytest.raises(ValueError):
            require_valid_transition("doc", "deprecated", "review")


class TestDocSignoffBinding:
    """文档-签核绑定测试"""

    def test_binding_service_available(self):
        """绑定服务可创建"""
        from src.infra.doc_signoff_binding import DocSignoffBinding
        binder = DocSignoffBinding()
        assert binder is not None
        assert hasattr(binder, 'on_doc_updated')
        assert hasattr(binder, 'on_doc_approved')
        assert hasattr(binder, 'get_doc_trace')

    def test_binding_has_all_methods(self):
        """绑定服务方法签名正确"""
        from src.infra.doc_signoff_binding import DocSignoffBinding
        binder = DocSignoffBinding()
        import inspect

        # on_doc_updated 接受 doc_id, author_id, author_name, change_summary
        sig = inspect.signature(binder.on_doc_updated)
        params = list(sig.parameters.keys())
        assert "doc_id" in params
        assert "author_id" in params
        assert "change_summary" in params

        # on_doc_approved 接受 doc_id, actor_id, actor_name
        sig2 = inspect.signature(binder.on_doc_approved)
        params2 = list(sig2.parameters.keys())
        assert "doc_id" in params2

        # get_doc_trace 接受 doc_id
        sig3 = inspect.signature(binder.get_doc_trace)
        assert "doc_id" in list(sig3.parameters.keys())


class TestDocService:
    """文档服务层测试"""

    def test_doc_service_methods(self):
        """DocService 方法签名"""
        from src.core.services import DocService, get_doc_service
        svc = get_doc_service()
        assert hasattr(svc, 'update')
        assert hasattr(svc, 'submit_for_review')
        assert hasattr(svc, 'approve')
        assert hasattr(svc, 'deprecate')

    @pytest.mark.asyncio
    async def test_doc_service_rejects_edit_when_not_found(self):
        """不存在的文档被编辑时抛出异常"""
        from src.core.services import DocService
        svc = DocService()
        with pytest.raises(ValueError):
            await svc.update(999999, "new content", 1, "test")


class TestDocConsistencyChecker:
    """文档一致性检查测试"""

    def test_checker_finds_spec_reqs(self):
        """能找到 spec 文件中的需求"""
        from src.infra.behavior_analyzer import DocConsistencyChecker
        checker = DocConsistencyChecker()
        issues = checker.check_spec_vs_tests("specs", "output/testcases")
        assert isinstance(issues, list)

    def test_checker_all_method(self):
        """check_all 返回结构完整"""
        from src.infra.behavior_analyzer import DocConsistencyChecker
        checker = DocConsistencyChecker()
        result = checker.check_all("specs")
        assert "total_issues" in result
        assert "critical" in result
        assert "warnings" in result
        assert "healthy" in result
        assert "issues" in result


class TestPolicyRuleEngine:
    """策略规则引擎测试"""

    def test_builtin_rules_registered(self):
        """内置规则已注册"""
        from src.core.rules_engine import get_policy_engine
        engine = get_policy_engine()
        rules = engine.get_rules()
        assert len(rules) == 11

    def test_approval_gate_rules(self):
        """审批门禁规则"""
        from src.core.rules_engine import get_policy_engine
        engine = get_policy_engine()
        gate_rules = engine.get_active("approval_gate")
        assert len(gate_rules) >= 2

    def test_evidence_integrity_rules(self):
        """证据完整性规则"""
        from src.core.rules_engine import get_policy_engine
        engine = get_policy_engine()
        ev_rules = engine.get_active("evidence_integrity")
        assert len(ev_rules) >= 2

    def test_signoff_gate_check(self):
        """签核门禁检查"""
        from src.core.rules_engine import get_policy_engine
        engine = get_policy_engine()
        result = engine.check_signoff_gates(
            {"manifest_hash": "abc", "report_type": "tapeout"},
            {"coverage": {"line_pct": 98}, "regression": {"pass_rate": 99}},
            {},
        )
        assert result["all_pass"] is True
        assert result["can_approve"] is True
        assert len(result["gates"]) >= 2

    def test_signoff_gate_blocks_when_no_evidence(self):
        """无证据时门禁拦截"""
        from src.core.rules_engine import get_policy_engine
        engine = get_policy_engine()
        result = engine.check_signoff_gates(
            {"manifest_hash": "", "evidence_package_hash": "", "report_type": "tapeout"},
            {"coverage": {"line_pct": 90}, "regression": {"pass_rate": 85}},
            {},
        )
        assert result["all_pass"] is False
        assert len(result["blockers"]) >= 1

    def test_evidence_integrity_check(self):
        """证据完整性检查"""
        from src.core.rules_engine import get_policy_engine
        engine = get_policy_engine()
        result = engine.check_evidence_integrity(
            {"manifest_hash": "", "phases": []},
            [],
        )
        assert "all_pass" in result
        assert "checks" in result

    def test_rule_enable_disable(self):
        """规则启用/禁用"""
        from src.core.rules_engine import get_policy_engine
        engine = get_policy_engine()
        engine.disable_rule("approval_dual_review")
        active = engine.get_active("approval_gate")
        rule_ids = [r.rule_id for r in active]
        assert "approval_dual_review" not in rule_ids

        engine.enable_rule("approval_dual_review")
        active = engine.get_active("approval_gate")
        rule_ids = [r.rule_id for r in active]
        assert "approval_dual_review" in rule_ids


class TestDiContainer:
    """依赖注入容器测试"""

    def test_container_resolves_services(self):
        """容器能解析所有已注册服务"""
        from src.core.container import container
        ss = container.signoff_service()
        ds = container.doc_service()
        ps = container.pipeline_service()
        assert ss is not None
        assert ds is not None
        assert ps is not None

    def test_container_resolves_infrastructure(self):
        """容器能解析基础设施组件"""
        from src.core.container import container
        rules = container.rules_engine()
        bus = container.event_bus()
        assert rules is not None
        assert bus is not None

    def test_container_override_for_testing(self):
        """容器支持 mock 注入"""
        from src.core.container import container
        mock_svc = object()
        container.override("signoff_service", mock_svc)
        assert container.resolve("signoff_service") is mock_svc
        # 清理
        container.reset()

    def test_container_rejects_unknown_dependency(self):
        """未注册依赖抛错"""
        from src.core.container import AppContainer
        c = AppContainer()
        with pytest.raises(KeyError, match="未注册"):
            c.resolve("nonexistent_service")


class TestWorkflowConfig:
    """配置化工作流测试"""

    def test_builtin_templates(self):
        """内置模板已注册"""
        from src.infra.workflow_config import get_workflow_registry
        reg = get_workflow_registry()
        tmpls = reg.list_all()
        assert len(tmpls) == 4
        names = [t["name"] for t in tmpls]
        assert "full_verification" in names
        assert "quick_check" in names
        assert "regression_only" in names
        assert "ppa_analysis" in names

    def test_template_step_deps(self):
        """步骤依赖关系正确"""
        from src.infra.workflow_config import get_workflow_registry
        reg = get_workflow_registry()
        deps = reg.get_step_deps("full_verification")
        assert deps["template"] == "full_verification"
        steps = deps["steps"]
        # 最后一个步骤依赖前面的步骤
        last = steps[-1]
        assert len(last["depends_on"]) > 0

    def test_workflow_validation(self):
        """工作流验证检测循环依赖"""
        from src.infra.workflow_config import WorkflowRegistry, WorkflowTemplate, WorkflowStep
        reg = WorkflowRegistry()
        # 创建有循环依赖的模板
        bad = WorkflowTemplate(
            name="bad_flow",
            steps=[
                WorkflowStep("step1", "agent1", depends_on=["step2"]),
                WorkflowStep("step2", "agent2", depends_on=["step1"]),
            ],
        )
        errors = reg.validate(bad)
        assert len(errors) > 0

    def test_workflow_export_yaml(self):
        """工作流导出 YAML"""
        from src.infra.workflow_config import get_workflow_registry
        reg = get_workflow_registry()
        yaml_str = reg.export_to_yaml("full_verification")
        assert "full_verification" in yaml_str
        assert "steps" in yaml_str


class TestPlatformHealth:
    """平台健康检查测试"""

    def test_health_monitor_runs(self):
        """健康检查可执行"""
        from src.infra.platform_health import get_health_monitor
        monitor = get_health_monitor()
        result = monitor.check_all()
        assert "healthy" in result
        assert "total_issues" in result
        assert "issues" in result

    def test_tenant_manager(self):
        """租户管理器"""
        from src.infra.platform_health import get_tenant_mgr
        mgr = get_tenant_mgr()
        assert mgr is not None
        assert hasattr(mgr, 'create_tenant')
        assert hasattr(mgr, 'list_tenants')
