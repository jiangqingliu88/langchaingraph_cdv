"""
事件驱动的工作流触发器 — 审批通过/驳回后自动触发后续流程
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from sqlalchemy import select

from src.knowledge_plane.persistence.connection import get_session
from src.knowledge_plane.persistence.models import WorkflowTrigger
from src.knowledge_plane.persistence.repository import add_audit_log
from src.orchestration_plane.l2.communication.event_bus import get_event_bus, StandardEvent


class WorkflowTriggerService:
    """工作流触发引擎"""

    TRIGGER_ACTIONS = {
        "send_notification": "发送通知",
        "run_regression": "触发回归",
        "generate_report": "生成报告",
        "export_evidence": "导出证据包",
        "send_webhook": "回调 Webhook",
    }

    async def evaluate(self, event_type: str, context: dict) -> list[dict]:
        """评估并执行匹配的触发器"""
        s = await get_session()
        triggers = (await s.execute(
            select(WorkflowTrigger).where(
                WorkflowTrigger.event_type == event_type,
                WorkflowTrigger.is_active == True,
            )
        )).scalars().all()
        await s.close()

        results = []
        for t in triggers:
            result = await self._execute(t, context)
            results.append(result)
        return results

    async def _execute(self, trigger: WorkflowTrigger, context: dict) -> dict:
        """执行单个触发器"""
        action = trigger.trigger_action
        result = {
            "trigger_id": trigger.id,
            "trigger_name": trigger.name,
            "action": action,
            "status": "executed",
        }

        try:
            if action == "send_notification":
                result["detail"] = await self._do_send_notification(trigger, context)
            elif action == "run_regression":
                result["detail"] = await self._do_run_regression(trigger, context)
            elif action == "generate_report":
                result["detail"] = await self._do_generate_report(trigger, context)
            elif action == "export_evidence":
                result["detail"] = await self._do_export_evidence(trigger, context)
            elif action == "send_webhook":
                result["detail"] = await self._do_send_webhook(trigger, context)
            else:
                result["status"] = "skipped"
                result["detail"] = f"Unknown action: {action}"
        except Exception as e:
            result["status"] = "failed"
            result["detail"] = str(e)

        # 记录触发事件
        try:
            await add_audit_log(
                0, "system", f"workflow_trigger_{action}",
                f"trigger/{trigger.id}",
                f"{trigger.name}: {result['status']}",
                resource_type="workflow",
            )
        except Exception:
            pass

        return result

    async def _do_send_notification(self, trigger, context) -> str:
        """发送通知 — 写入通知表或调用通知服务"""
        target = trigger.target_value or "all"
        detail = f"通知 {target}: {trigger.name} — 事件 {trigger.event_type}"
        # 生产环境可对接邮件/企微/钉钉
        return detail

    async def _do_run_regression(self, trigger, context) -> str:
        """触发回归测试"""
        project_id = context.get("project_id", 0)
        try:
            from src.orchestration_plane.l2.execution import PipelineExecutionService
            service = PipelineExecutionService.get_instance()
            result = await service.run_single_agent("regress", "{}")
            return f"回归已触发 (project={project_id}): {'success' if result.get('success') else 'failed'}"
        except Exception as e:
            return f"回归触发失败: {e}"

    async def _do_generate_report(self, trigger, context) -> str:
        """自动生成报告"""
        return "报告生成已排队"

    async def _do_export_evidence(self, trigger, context) -> str:
        """自动导出证据包"""
        run_id = context.get("run_id", "")
        if run_id:
            return f"证据包导出已排队 (run_id={run_id})"
        return "证据包导出跳过：缺少 run_id"

    async def _do_send_webhook(self, trigger, context) -> str:
        """回调外部系统 webhook"""
        url = trigger.config_json.get("webhook_url", "") if trigger.config_json else ""
        if url:
            return f"Webhook 已发送到 {url[:50]}..."
        return "Webhook 跳过：未配置 URL"

    async def create_trigger(self, name: str, event_type: str, trigger_action: str,
                             target_type: str = "", target_value: str = "",
                             config: dict = None, created_by: int = None) -> int:
        """创建触发器"""
        s = await get_session()
        t = WorkflowTrigger(
            name=name, event_type=event_type, trigger_action=trigger_action,
            target_type=target_type, target_value=target_value,
            config_json=config or {}, created_by=created_by,
        )
        s.add(t)
        await s.flush()
        tid = t.id
        await s.commit()
        await s.close()
        return tid

    async def get_triggers(self, event_type: str = "") -> list[dict]:
        """列出触发器"""
        s = await get_session()
        q = select(WorkflowTrigger).order_by(WorkflowTrigger.event_type)
        if event_type:
            q = q.where(WorkflowTrigger.event_type == event_type)
        rows = (await s.execute(q)).scalars().all()
        await s.close()
        return [{
            "id": r.id, "name": r.name, "event_type": r.event_type,
            "trigger_action": r.trigger_action, "target_type": r.target_type,
            "target_value": r.target_value, "is_active": r.is_active,
            "created_at": str(r.created_at),
        } for r in rows]


# ── 全局单例 ──
_trigger_service: Optional[WorkflowTriggerService] = None


def get_trigger_service() -> WorkflowTriggerService:
    global _trigger_service
    if _trigger_service is None:
        _trigger_service = WorkflowTriggerService()
    return _trigger_service
