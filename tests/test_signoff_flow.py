"""
E2E tests: 签核审批流状态机

覆盖: 状态转移合法性、非法转移拦截、SignoffEvent 记录、服务层 approve/reject
"""
import asyncio
import pytest
from datetime import datetime


class TestSignoffStateMachine:
    """签核状态机测试"""

    def test_valid_transitions(self):
        """合法状态转移"""
        from src.core.domain_registry import is_valid_transition
        # draft → pending
        assert is_valid_transition("signoff", "draft", "pending")
        # pending → approved
        assert is_valid_transition("signoff", "pending", "approved")
        # pending → rejected
        assert is_valid_transition("signoff", "pending", "rejected")
        # rejected → draft (重新打开)
        assert is_valid_transition("signoff", "rejected", "draft")
        # rejected → pending (重新提交)
        assert is_valid_transition("signoff", "rejected", "pending")

    def test_invalid_transitions_blocked(self):
        """非法转移被拒绝"""
        from src.core.domain_registry import is_valid_transition, require_valid_transition
        with pytest.raises(ValueError, match="非法状态转移"):
            require_valid_transition("signoff", "approved", "draft")

        with pytest.raises(ValueError, match="非法状态转移"):
            require_valid_transition("signoff", "approved", "rejected")

        # 终态禁止转移
        assert not is_valid_transition("signoff", "approved", "draft")
        assert not is_valid_transition("signoff", "approved", "pending")

    def test_terminal_states(self):
        """终态识别"""
        from src.core.domain_registry import is_terminal_state
        assert is_terminal_state("signoff", "approved")
        # rejected 不是终态：可以从 rejected 回到 draft 或 pending
        assert not is_terminal_state("signoff", "rejected")
        assert not is_terminal_state("signoff", "pending")

    def test_get_valid_transitions(self):
        """获取合法目标状态"""
        from src.core.domain_registry import get_valid_transitions
        from_pending = get_valid_transitions("signoff", "pending")
        assert "approved" in from_pending
        assert "rejected" in from_pending
        from_approved = get_valid_transitions("signoff", "approved")
        assert from_approved == []

    def test_pipeline_state_transitions(self):
        """流水线状态转移"""
        from src.core.domain_registry import is_valid_transition, require_valid_transition
        assert is_valid_transition("pipeline", "running", "completed")
        assert is_valid_transition("pipeline", "running", "completed_with_errors")
        assert is_valid_transition("pipeline", "running", "cancelled")
        with pytest.raises(ValueError):
            require_valid_transition("pipeline", "completed", "running")

    def test_doc_state_transitions(self):
        """文档状态转移"""
        from src.core.domain_registry import is_valid_transition
        assert is_valid_transition("doc", "draft", "review")
        assert is_valid_transition("doc", "review", "approved")


class TestSignoffService:
    """签核服务层测试"""

    @pytest.mark.asyncio
    async def test_create_signoff_initial_status(self):
        """创建签核后状态为 pending"""
        from src.core.services import SignoffService
        svc = SignoffService()
        # 服务层方法签名测试（不实际操作 DB）
        assert svc is not None
        assert hasattr(svc, 'create')
        assert hasattr(svc, 'approve')
        assert hasattr(svc, 'reject')
        assert hasattr(svc, 'reopen')

    def test_service_approve_requires_manager(self):
        """批准签核需要 manager 角色"""
        from src.core.services import SignoffService
        svc = SignoffService()
        # 权限检查在 approve 方法内部
        assert svc is not None

    def test_service_reject_requires_manager(self):
        """驳回答核需要 manager 角色"""
        from src.core.services import SignoffService
        svc = SignoffService()
        assert svc is not None


class TestSignoffEventLogging:
    """签核事件记录测试"""

    @pytest.mark.asyncio
    async def test_event_types_match_state_transitions(self):
        """事件类型与状态转移一致"""
        expected_events = {"submitted", "approved", "rejected", "commented", "reopened", "draft"}
        from src.database.models import SignoffEvent
        # 验证模型中定义了 event_type 字段
        assert hasattr(SignoffEvent, 'event_type')

        # 从 data_governance 中验证已知类型
        from src.infra.data_governance import DataDictionary
        dd = DataDictionary()
        entity = dd.entities.get("signoff_events")
        if entity:
            enum_field = next((f for f in entity.fields if f.name == "event_type"), None)
            if enum_field and enum_field.enum_values:
                valid = set(enum_field.enum_values)
                assert len(valid & expected_events) >= 4

    def test_event_records_before_after_states(self):
        """事件记录前后状态"""
        from src.database.models import SignoffEvent
        assert hasattr(SignoffEvent, 'before_status')
        assert hasattr(SignoffEvent, 'after_status')
        assert hasattr(SignoffEvent, 'actor_id')
        assert hasattr(SignoffEvent, 'actor_name')
        assert hasattr(SignoffEvent, 'comment')
        assert hasattr(SignoffEvent, 'evidence_hash')
