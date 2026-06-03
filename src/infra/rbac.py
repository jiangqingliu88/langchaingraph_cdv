# src/infra/rbac.py
"""
RBAC 权限管理 - IC验证平台专用
"""

from enum import Enum
from typing import Dict, List, Set
from dataclasses import dataclass, field
import json


# ==================== 权限定义 ====================

class Permission(Enum):
    """权限枚举 - IC验证平台专用"""
    
    # 项目权限
    PROJECT_CREATE = "project:create"
    PROJECT_VIEW = "project:view"
    PROJECT_EDIT = "project:edit"
    PROJECT_DELETE = "project:delete"
    PROJECT_ARCHIVE = "project:archive"
    
    # Agent 权限
    AGENT_CONFIGURE = "agent:configure"       # 配置Agent参数
    AGENT_EXECUTE = "agent:execute"           # 运行Agent
    AGENT_VIEW_RESULT = "agent:view_result"   # 查看结果
    AGENT_EXPORT = "agent:export"             # 导出结果
    
    # 环境权限
    ENV_GENERATE = "env:generate"             # 生成验证环境
    ENV_MODIFY = "env:modify"                 # 修改环境代码
    ENV_COMPILE = "env:compile"               # 编译环境
    ENV_LOOPBACK = "env:loopback"             # 运行闭环验证
    
    # 测试用例权限
    TESTCASE_CREATE = "testcase:create"       # 创建测试用例
    TESTCASE_EDIT = "testcase:edit"           # 编辑测试用例
    TESTCASE_DELETE = "testcase:delete"       # 删除测试用例
    TESTCASE_RUN = "testcase:run"             # 运行测试用例
    TESTCASE_IMPORT = "testcase:import"       # 导入测试用例
    
    # 回归权限
    REGRESSION_START = "regression:start"     # 启动回归
    REGRESSION_STOP = "regression:stop"       # 停止回归
    REGRESSION_RERUN = "regression:rerun"     # 重跑失败
    REGRESSION_VIEW = "regression:view"       # 查看回归结果
    
    # 覆盖率权限
    COVERAGE_VIEW = "coverage:view"           # 查看覆盖率
    COVERAGE_MERGE = "coverage:merge"         # 合并覆盖率
    COVERAGE_EXPORT = "coverage:export"       # 导出覆盖率
    
    # 知识库权限
    LIBRARY_SEARCH = "library:search"         # 搜索知识库
    LIBRARY_BACKUP = "library:backup"         # 备份到知识库
    LIBRARY_DELETE = "library:delete"         # 删除知识库条目
    
    # 签核权限
    SIGNOFF_REQUEST = "signoff:request"       # 请求签核
    SIGNOFF_APPROVE = "signoff:approve"       # 批准签核
    SIGNOFF_REJECT = "signoff:reject"         # 拒绝签核
    
    # 管理权限
    USER_MANAGE = "admin:user_manage"         # 用户管理
    ROLE_MANAGE = "admin:role_manage"         # 角色管理
    SYSTEM_CONFIG = "admin:system_config"     # 系统配置
    AUDIT_VIEW = "admin:audit_view"           # 查看审计日志


# ==================== 角色定义 ====================

@dataclass
class Role:
    """角色定义"""
    name: str
    display_name: str
    description: str
    permissions: Set[Permission] = field(default_factory=set)

# 预定义角色
ROLES = {
    # 管理员 - 全部权限
    "admin": Role(
        name="admin",
        display_name="系统管理员",
        description="拥有所有权限，管理用户和系统配置",
        permissions=set(Permission)
    ),
    
    # 验证经理 - 管理权限
    "verification_manager": Role(
        name="verification_manager",
        display_name="验证经理",
        description="管理验证项目，审批签核，查看所有数据",
        permissions={
            # 项目
            Permission.PROJECT_CREATE, Permission.PROJECT_VIEW, Permission.PROJECT_EDIT,
            Permission.PROJECT_ARCHIVE,
            # Agent
            Permission.AGENT_CONFIGURE, Permission.AGENT_EXECUTE, 
            Permission.AGENT_VIEW_RESULT, Permission.AGENT_EXPORT,
            # 环境
            Permission.ENV_GENERATE, Permission.ENV_COMPILE, Permission.ENV_LOOPBACK,
            # 测试用例
            Permission.TESTCASE_CREATE, Permission.TESTCASE_EDIT, 
            Permission.TESTCASE_RUN, Permission.TESTCASE_IMPORT,
            # 回归
            Permission.REGRESSION_START, Permission.REGRESSION_STOP,
            Permission.REGRESSION_RERUN, Permission.REGRESSION_VIEW,
            # 覆盖率
            Permission.COVERAGE_VIEW, Permission.COVERAGE_MERGE, Permission.COVERAGE_EXPORT,
            # 知识库
            Permission.LIBRARY_SEARCH, Permission.LIBRARY_BACKUP,
            # 签核
            Permission.SIGNOFF_REQUEST, Permission.SIGNOFF_APPROVE, Permission.SIGNOFF_REJECT,
            # 查看审计
            Permission.AUDIT_VIEW,
        }
    ),
    
    # 高级验证工程师
    "senior_engineer": Role(
        name="senior_engineer",
        display_name="高级验证工程师",
        description="可以创建和运行测试，生成环境，备份知识库",
        permissions={
            Permission.PROJECT_VIEW, Permission.PROJECT_EDIT,
            Permission.AGENT_CONFIGURE, Permission.AGENT_EXECUTE,
            Permission.AGENT_VIEW_RESULT, Permission.AGENT_EXPORT,
            Permission.ENV_GENERATE, Permission.ENV_MODIFY,
            Permission.ENV_COMPILE, Permission.ENV_LOOPBACK,
            Permission.TESTCASE_CREATE, Permission.TESTCASE_EDIT,
            Permission.TESTCASE_RUN, Permission.TESTCASE_IMPORT,
            Permission.REGRESSION_START, Permission.REGRESSION_RERUN,
            Permission.REGRESSION_VIEW,
            Permission.COVERAGE_VIEW, Permission.COVERAGE_MERGE,
            Permission.LIBRARY_SEARCH, Permission.LIBRARY_BACKUP,
            Permission.SIGNOFF_REQUEST,
        }
    ),
    
    # 验证工程师
    "engineer": Role(
        name="engineer",
        display_name="验证工程师",
        description="运行测试，查看结果，不能修改环境配置",
        permissions={
            Permission.PROJECT_VIEW,
            Permission.AGENT_EXECUTE, Permission.AGENT_VIEW_RESULT,
            Permission.ENV_COMPILE, Permission.ENV_LOOPBACK,
            Permission.TESTCASE_CREATE, Permission.TESTCASE_EDIT,
            Permission.TESTCASE_RUN,
            Permission.REGRESSION_VIEW,
            Permission.COVERAGE_VIEW,
            Permission.LIBRARY_SEARCH,
        }
    ),
    
    # 只读观察者
    "viewer": Role(
        name="viewer",
        display_name="观察者",
        description="只能查看，不能修改或运行",
        permissions={
            Permission.PROJECT_VIEW,
            Permission.AGENT_VIEW_RESULT,
            Permission.REGRESSION_VIEW,
            Permission.COVERAGE_VIEW,
            Permission.LIBRARY_SEARCH,
        }
    ),
}


# ==================== 权限检查器 ====================

class RBACChecker:
    """RBAC 权限检查器"""
    
    def __init__(self):
        self.roles = ROLES.copy()
    
    def has_permission(self, user_role: str, permission: Permission) -> bool:
        """检查用户是否有某项权限"""
        role = self.roles.get(user_role)
        if not role:
            return False
        return permission in role.permissions
    
    def has_any_permission(self, user_role: str, permissions: List[Permission]) -> bool:
        """检查用户是否有任一权限"""
        return any(self.has_permission(user_role, p) for p in permissions)
    
    def has_all_permissions(self, user_role: str, permissions: List[Permission]) -> bool:
        """检查用户是否有所有权限"""
        return all(self.has_permission(user_role, p) for p in permissions)
    
    def get_user_permissions(self, user_role: str) -> List[str]:
        """获取用户所有权限"""
        role = self.roles.get(user_role)
        if not role:
            return []
        return [p.value for p in role.permissions]
    
    def check_and_raise(self, user_role: str, permission: Permission):
        """检查权限，无权限抛异常"""
        if not self.has_permission(user_role, permission):
            raise PermissionError(
                f"用户角色 '{user_role}' 没有权限 '{permission.value}'"
            )


# ==================== 权限检查装饰器 ====================

def require_permission(permission: Permission):
    """权限检查装饰器"""
    def decorator(func):
        def wrapper(self, *args, **kwargs):
            user_role = kwargs.get('user_role', getattr(self, 'user_role', 'viewer'))
            checker = RBACChecker()
            checker.check_and_raise(user_role, permission)
            return func(self, *args, **kwargs)
        return wrapper
    return decorator


# ==================== 使用示例 ====================

if __name__ == "__main__":
    checker = RBACChecker()
    
    # 场景1：工程师尝试生成环境
    print("工程师生成环境:", 
          checker.has_permission("engineer", Permission.ENV_GENERATE))  # False
    
    # 场景2：高级工程师生成环境
    print("高级工程师生成环境:", 
          checker.has_permission("senior_engineer", Permission.ENV_GENERATE))  # True
    
    # 场景3：经理审批签核
    print("经理审批签核:", 
          checker.has_permission("verification_manager", Permission.SIGNOFF_APPROVE))  # True
    
    # 场景4：观察者尝试运行测试
    print("观察者运行测试:", 
          checker.has_permission("viewer", Permission.TESTCASE_RUN))  # False