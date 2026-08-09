"""
RBAC Web Bridge — 将三层权限模型接入 FastAPI Web 层

三层权限:
  1. 平台级 (Platform): 管理员 / 审计管理员 / 平台运维
  2. 项目级 (Project):  owner / admin / member / viewer
  3. 流程级 (Process): 启动流水线 / 审批签核 / 导出证据 / 回退文档

用法:
  from src.infra.rbac_web import PermissionChecker, require_signoff_approve

  checker = PermissionChecker()
  checker.can_approve_signoff(user_role, project_id, user_id)

  @app.put("/api/signoffs/{sid}/approve")
  async def approve(sid: int, user=Depends(require_signoff_approve)):
      ...
"""

from __future__ import annotations
from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set
import json


# ═══════════════════════════════════════════════════════════
# 三层角色定义
# ═══════════════════════════════════════════════════════════

class PlatformRole(str, Enum):
    """平台级角色"""
    ADMIN = "admin"
    AUDIT_ADMIN = "audit_admin"
    PLATFORM_OPS = "platform_ops"


class ProjectRole(str, Enum):
    """项目级角色"""
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


class ProcessPermission(str, Enum):
    """流程级权限"""
    PIPELINE_START = "pipeline:start"
    PIPELINE_STOP = "pipeline:stop"
    SIGNOFF_APPROVE = "signoff:approve"
    SIGNOFF_REJECT = "signoff:reject"
    SIGNOFF_REQUEST = "signoff:request"
    EVIDENCE_EXPORT = "evidence:export"
    EVIDENCE_VERIFY = "evidence:verify"
    DOC_EDIT = "doc:edit"
    DOC_VERSION_RESTORE = "doc:version_restore"
    REGRESSION_RUN = "regression:run"
    COVERAGE_EXPORT = "coverage:export"
    USER_MANAGE = "user:manage"
    MODULE_ASSIGN = "module:assign"
    AUDIT_VIEW = "audit:view"
    TOKEN_VIEW = "token:view"


# ═══════════════════════════════════════════════════════════
# 角色→权限映射
# ═══════════════════════════════════════════════════════════

PLATFORM_PERMISSIONS: Dict[str, Set[ProcessPermission]] = {
    "admin": set(ProcessPermission),  # 全部权限
    "verification_manager": {
        ProcessPermission.PIPELINE_START,
        ProcessPermission.PIPELINE_STOP,
        ProcessPermission.SIGNOFF_APPROVE,
        ProcessPermission.SIGNOFF_REJECT,
        ProcessPermission.SIGNOFF_REQUEST,
        ProcessPermission.EVIDENCE_EXPORT,
        ProcessPermission.EVIDENCE_VERIFY,
        ProcessPermission.DOC_EDIT,
        ProcessPermission.DOC_VERSION_RESTORE,
        ProcessPermission.REGRESSION_RUN,
        ProcessPermission.COVERAGE_EXPORT,
        ProcessPermission.MODULE_ASSIGN,
        ProcessPermission.AUDIT_VIEW,
        ProcessPermission.TOKEN_VIEW,
    },
    "senior_engineer": {
        ProcessPermission.PIPELINE_START,
        ProcessPermission.SIGNOFF_REQUEST,
        ProcessPermission.EVIDENCE_EXPORT,
        ProcessPermission.EVIDENCE_VERIFY,
        ProcessPermission.REGRESSION_RUN,
        ProcessPermission.COVERAGE_EXPORT,
    },
    "engineer": {
        ProcessPermission.PIPELINE_START,
        ProcessPermission.SIGNOFF_REQUEST,
        ProcessPermission.EVIDENCE_VERIFY,
        ProcessPermission.REGRESSION_RUN,
    },
    "viewer": set(),  # 只读，无流程权限
}


PROJECT_PERMISSIONS: Dict[str, Set[ProcessPermission]] = {
    "owner": {
        ProcessPermission.PIPELINE_START, ProcessPermission.PIPELINE_STOP,
        ProcessPermission.SIGNOFF_APPROVE, ProcessPermission.SIGNOFF_REJECT,
        ProcessPermission.SIGNOFF_REQUEST,
        ProcessPermission.EVIDENCE_EXPORT, ProcessPermission.EVIDENCE_VERIFY,
        ProcessPermission.DOC_EDIT, ProcessPermission.DOC_VERSION_RESTORE,
        ProcessPermission.REGRESSION_RUN, ProcessPermission.COVERAGE_EXPORT,
        ProcessPermission.MODULE_ASSIGN,
    },
    "admin": {
        ProcessPermission.PIPELINE_START, ProcessPermission.PIPELINE_STOP,
        ProcessPermission.SIGNOFF_APPROVE, ProcessPermission.SIGNOFF_REJECT,
        ProcessPermission.SIGNOFF_REQUEST,
        ProcessPermission.EVIDENCE_EXPORT, ProcessPermission.EVIDENCE_VERIFY,
        ProcessPermission.DOC_EDIT, ProcessPermission.REGRESSION_RUN,
    },
    "member": {
        ProcessPermission.PIPELINE_START, ProcessPermission.SIGNOFF_REQUEST,
        ProcessPermission.EVIDENCE_VERIFY, ProcessPermission.REGRESSION_RUN,
    },
    "viewer": set(),
}


# ═══════════════════════════════════════════════════════════
# 统一权限检查器
# ═══════════════════════════════════════════════════════════

@dataclass
class PermissionCheckResult:
    allowed: bool
    reason: str = ""
    required_role: str = ""
    user_role: str = ""


class PermissionChecker:
    """三层统一权限检查器 — 平台 > 项目 > 流程"""

    def __init__(self):
        self.platform_perms = PLATFORM_PERMISSIONS
        self.project_perms = PROJECT_PERMISSIONS

    # ── 平台级检查 ──

    def get_platform_permissions(self, platform_role: str) -> Set[ProcessPermission]:
        """获取平台角色拥有的所有流程权限"""
        return self.platform_perms.get(platform_role, set())

    def has_platform_permission(self, platform_role: str, perm: ProcessPermission) -> PermissionCheckResult:
        """检查平台角色是否有某流程权限"""
        allowed = perm in self.platform_perms.get(platform_role, set())
        return PermissionCheckResult(
            allowed=allowed,
            reason="平台级授权" if allowed else f"角色 '{platform_role}' 无此权限",
            required_role="admin or verification_manager",
            user_role=platform_role,
        )

    # ── 项目级检查 ──

    def get_project_permissions(self, project_role: str) -> Set[ProcessPermission]:
        """获取项目角色拥有的所有流程权限"""
        return self.project_perms.get(project_role, set())

    def has_project_permission(self, project_role: str, perm: ProcessPermission) -> PermissionCheckResult:
        """检查项目角色是否有某流程权限"""
        allowed = perm in self.project_perms.get(project_role, set())
        return PermissionCheckResult(
            allowed=allowed,
            reason="项目级授权" if allowed else f"项目角色 '{project_role}' 无此权限",
            required_role="owner or admin",
            user_role=project_role,
        )

    # ── 综合检查（平台 + 项目取并集） ──

    def check(self, platform_role: str, project_role: str = "",
              perm: ProcessPermission = None) -> PermissionCheckResult:
        """综合权限检查 — 平台权限和项目权限取并集"""
        platform_allowed = perm in self.platform_perms.get(platform_role, set())
        project_allowed = perm in self.project_perms.get(project_role, set()) if project_role else False

        if platform_allowed or project_allowed:
            source = []
            if platform_allowed: source.append("平台级")
            if project_allowed: source.append("项目级")
            return PermissionCheckResult(allowed=True, reason=" + ".join(source) + "授权",
                                         user_role=f"{platform_role}/{project_role}" if project_role else platform_role)
        return PermissionCheckResult(
            allowed=False,
            reason=f"角色 '{platform_role}' + 项目角色 '{project_role}' 均无此权限",
            required_role="verification_manager or project owner",
            user_role=platform_role,
        )

    # ── 便捷方法 ──

    def can_approve_signoff(self, platform_role: str, project_id: int = 0,
                             user_id: int = 0) -> PermissionCheckResult:
        return self.check(platform_role, "", ProcessPermission.SIGNOFF_APPROVE)

    def can_edit_docs(self, platform_role: str, project_id: int = 0,
                      user_id: int = 0) -> PermissionCheckResult:
        return self.check(platform_role, "", ProcessPermission.DOC_EDIT)

    def can_export_evidence(self, platform_role: str, project_id: int = 0,
                            user_id: int = 0) -> PermissionCheckResult:
        return self.check(platform_role, "", ProcessPermission.EVIDENCE_EXPORT)

    def can_run_pipeline(self, platform_role: str, project_id: int = 0,
                         user_id: int = 0) -> PermissionCheckResult:
        return self.check(platform_role, "", ProcessPermission.PIPELINE_START)

    def can_view_audit(self, platform_role: str) -> PermissionCheckResult:
        return self.check(platform_role, "", ProcessPermission.AUDIT_VIEW)


# ═══════════════════════════════════════════════════════════
# FastAPI 依赖注入
# ═══════════════════════════════════════════════════════════

from fastapi import HTTPException, Depends
from src.core.auth import require_auth


_checker = PermissionChecker()


def _make_permission_dependency(perm: ProcessPermission, error_msg: str):
    """工厂函数 — 生成 FastAPI 权限依赖"""
    async def dependency(user: dict = Depends(require_auth)):
        role = user.get("role", "viewer")
        result = _checker.check(role, perm=perm)
        if not result.allowed:
            from src.database.repository import add_audit_log
            try:
                await add_audit_log(
                    user.get("user_id", 0), user.get("username", ""),
                    f"permission_denied", str(perm.value),
                    f"需要: {result.required_role}, 当前: {result.user_role}",
                    role=role, resource_type="auth",
                    access_result="denied", is_privileged=True,
                )
            except Exception: pass
            raise HTTPException(status_code=403, detail=error_msg)
        return user
    return dependency


# ── 预定义权限依赖 ──

require_signoff_approve = _make_permission_dependency(
    ProcessPermission.SIGNOFF_APPROVE, "仅 SignOff 经理可以批准签核"
)
require_signoff_reject = _make_permission_dependency(
    ProcessPermission.SIGNOFF_REJECT, "仅 SignOff 经理可以驳回签核"
)
require_evidence_export = _make_permission_dependency(
    ProcessPermission.EVIDENCE_EXPORT, "无权导出证据"
)
require_doc_edit = _make_permission_dependency(
    ProcessPermission.DOC_EDIT, "仅 SignOff 经理可以编辑文档"
)
require_doc_restore = _make_permission_dependency(
    ProcessPermission.DOC_VERSION_RESTORE, "仅 SignOff 经理可以回退文档版本"
)
require_regression_run = _make_permission_dependency(
    ProcessPermission.REGRESSION_RUN, "无权运行回归"
)


# ═══════════════════════════════════════════════════════════
# 审计上下文辅助
# ═══════════════════════════════════════════════════════════

async def audit_action(user: dict, action: str, resource: str = "",
                       detail: str = "", is_privileged: bool = False,
                       access_result: str = "success"):
    """统一的审计动作记录"""
    from src.database.repository import add_audit_log
    await add_audit_log(
        user_id=user.get("user_id", 0),
        username=user.get("username", ""),
        action=action,
        resource=resource,
        detail=detail,
        role=user.get("role", ""),
        access_result=access_result,
        is_privileged=is_privileged,
    )


def get_permission_checker() -> PermissionChecker:
    """获取全局权限检查器实例"""
    return _checker
