# src/infra/project_isolation.py
"""
项目隔离管理 - 多项目数据隔离 + 权限控制
"""

from typing import Dict, List, Optional, Set
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import json
import hashlib


# ==================== 数据模型 ====================

class ProjectRole(Enum):
    """项目内角色"""
    OWNER = "owner"           # 项目负责人
    ADMIN = "admin"           # 项目管理员
    MEMBER = "member"         # 项目成员
    VIEWER = "viewer"         # 只读


@dataclass
class User:
    """用户"""
    id: str
    name: str
    email: str
    global_role: str = "engineer"  # 全局角色
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class ProjectMember:
    """项目成员"""
    user: User
    project_role: ProjectRole
    joined_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class Project:
    """项目"""
    id: str
    name: str
    description: str
    owner: User
    members: List[ProjectMember] = field(default_factory=list)
    status: str = "active"  # active / archived / deleted
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    env_dir: str = ""       # 环境目录
    testcase_dir: str = ""  # 测试用例目录
    regression_dir: str = ""# 回归结果目录


# ==================== 项目隔离管理器 ====================

class ProjectIsolationManager:
    """项目隔离管理器"""
    
    def __init__(self):
        self.projects: Dict[str, Project] = {}
        self._user_project_cache: Dict[str, List[str]] = {}  # user_id → project_ids
    
    # ===== 项目管理 =====
    
    def create_project(self, name: str, description: str, owner: User) -> Project:
        """创建项目"""
        project_id = self._generate_project_id(name)
        
        project = Project(
            id=project_id,
            name=name,
            description=description,
            owner=owner,
            members=[ProjectMember(user=owner, project_role=ProjectRole.OWNER)],
            env_dir=f"projects/{project_id}/env",
            testcase_dir=f"projects/{project_id}/testcases",
            regression_dir=f"projects/{project_id}/regression",
        )
        
        self.projects[project_id] = project
        self._cache_user_project(owner.id, project_id)
        return project
    
    def archive_project(self, project_id: str, user: User):
        """归档项目"""
        self._check_permission(project_id, user, [ProjectRole.OWNER, ProjectRole.ADMIN])
        self.projects[project_id].status = "archived"
    
    def delete_project(self, project_id: str, user: User):
        """删除项目"""
        self._check_permission(project_id, user, [ProjectRole.OWNER])
        self.projects[project_id].status = "deleted"
    
    # ===== 成员管理 =====
    
    def add_member(self, project_id: str, admin: User, new_user: User, role: ProjectRole):
        """添加项目成员"""
        self._check_permission(project_id, admin, [ProjectRole.OWNER, ProjectRole.ADMIN])
        
        project = self.projects[project_id]
        
        # 检查是否已在项目中
        if any(m.user.id == new_user.id for m in project.members):
            raise ValueError(f"用户 {new_user.name} 已在项目中")
        
        project.members.append(ProjectMember(user=new_user, project_role=role))
        self._cache_user_project(new_user.id, project_id)
    
    def remove_member(self, project_id: str, admin: User, target_user_id: str):
        """移除项目成员"""
        self._check_permission(project_id, admin, [ProjectRole.OWNER, ProjectRole.ADMIN])
        project = self.projects[project_id]
        project.members = [m for m in project.members if m.user.id != target_user_id]
        self._invalidate_cache(target_user_id)
    
    def update_member_role(self, project_id: str, admin: User, target_user_id: str, new_role: ProjectRole):
        """更新成员角色"""
        self._check_permission(project_id, admin, [ProjectRole.OWNER, ProjectRole.ADMIN])
        project = self.projects[project_id]
        for m in project.members:
            if m.user.id == target_user_id:
                m.project_role = new_role
                break
    
    # ===== 权限检查 =====
    
    def can_access_project(self, user: User, project_id: str) -> bool:
        """检查用户是否可以访问项目"""
        if user.global_role == "admin":
            return True
        project = self.projects.get(project_id)
        if not project:
            return False
        return any(m.user.id == user.id for m in project.members)
    
    def get_user_project_role(self, user: User, project_id: str) -> Optional[ProjectRole]:
        """获取用户在项目中的角色"""
        project = self.projects.get(project_id)
        if not project:
            return None
        for m in project.members:
            if m.user.id == user.id:
                return m.project_role
        return None
    
    def get_user_projects(self, user: User) -> List[Project]:
        """获取用户参与的所有项目"""
        if user.global_role == "admin":
            return list(self.projects.values())
        
        project_ids = self._user_project_cache.get(user.id, [])
        return [self.projects[pid] for pid in project_ids if pid in self.projects]
    
    def get_project_members(self, project_id: str, user: User) -> List[ProjectMember]:
        """获取项目成员列表（需要项目权限）"""
        self._check_access(project_id, user)
        return self.projects[project_id].members
    
    def _check_permission(self, project_id: str, user: User, allowed_roles: List[ProjectRole]):
        """检查用户是否有指定权限"""
        if user.global_role == "admin":
            return
        
        role = self.get_user_project_role(user, project_id)
        if not role or role not in allowed_roles:
            raise PermissionError(
                f"用户 {user.name} 在项目 {project_id} 中没有 {allowed_roles} 权限"
            )
    
    def _check_access(self, project_id: str, user: User):
        """检查用户是否可以访问项目"""
        if not self.can_access_project(user, project_id):
            raise PermissionError(
                f"用户 {user.name} 无权访问项目 {project_id}"
            )
    
    # ===== 数据隔离 =====
    
    def get_project_data(self, project_id: str, user: User, data_type: str) -> Dict:
        """获取项目数据（自动隔离）"""
        self._check_access(project_id, user)
        
        project = self.projects[project_id]
        role = self.get_user_project_role(user, project_id)
        
        base_data = {
            "project_id": project_id,
            "project_name": project.name,
            "user_role": role.value if role else "none",
        }
        
        # 根据角色返回不同数据
        if data_type == "env":
            base_data["env_dir"] = project.env_dir
            base_data["can_modify"] = role in [ProjectRole.OWNER, ProjectRole.ADMIN]
        
        elif data_type == "testcases":
            base_data["testcase_dir"] = project.testcase_dir
            base_data["can_run"] = role in [ProjectRole.OWNER, ProjectRole.ADMIN, ProjectRole.MEMBER]
            base_data["can_edit"] = role in [ProjectRole.OWNER, ProjectRole.ADMIN]
        
        elif data_type == "regression":
            base_data["regression_dir"] = project.regression_dir
            base_data["can_start"] = role in [ProjectRole.OWNER, ProjectRole.ADMIN, ProjectRole.MEMBER]
            base_data["can_stop"] = role in [ProjectRole.OWNER, ProjectRole.ADMIN]
        
        return base_data
    
    # ===== 内部方法 =====
    
    def _generate_project_id(self, name: str) -> str:
        """生成项目ID"""
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        hash_suffix = hashlib.md5(name.encode()).hexdigest()[:8]
        return f"prj_{timestamp}_{hash_suffix}"
    
    def _cache_user_project(self, user_id: str, project_id: str):
        if user_id not in self._user_project_cache:
            self._user_project_cache[user_id] = []
        if project_id not in self._user_project_cache[user_id]:
            self._user_project_cache[user_id].append(project_id)
    
    def _invalidate_cache(self, user_id: str):
        self._user_project_cache.pop(user_id, None)


# ==================== 使用示例 ====================

if __name__ == "__main__":
    # 创建用户
    alice = User(id="u001", name="Alice", email="alice@company.com", global_role="engineer")
    bob = User(id="u002", name="Bob", email="bob@company.com", global_role="engineer")
    admin = User(id="u003", name="Charlie", email="charlie@company.com", global_role="admin")
    
    manager = ProjectIsolationManager()
    
    # Alice 创建项目A
    project_a = manager.create_project("芯片X验证", "5G基带芯片验证", alice)
    print(f"项目A: {project_a.id}")
    
    # Bob 创建项目B
    project_b = manager.create_project("芯片Y验证", "AI加速器验证", bob)
    print(f"项目B: {project_b.id}")
    
    # Alice 的项目A，Bob 无权访问
    print("\nBob 访问项目A:", manager.can_access_project(bob, project_a.id))  # False
    
    # Alice 添加 Bob 到项目A
    manager.add_member(project_a.id, alice, bob, ProjectRole.MEMBER)
    print("Bob 访问项目A:", manager.can_access_project(bob, project_a.id))  # True
    
    # Alice 的项目列表
    print("\nAlice 的项目:", [p.name for p in manager.get_user_projects(alice)])
    # ['芯片X验证']
    
    # Bob 的项目列表
    print("Bob 的项目:", [p.name for p in manager.get_user_projects(bob)])
    # ['芯片Y验证', '芯片X验证']
    
    # Admin 能看到所有项目
    print("Admin 的项目:", [p.name for p in manager.get_user_projects(admin)])
    # ['芯片X验证', '芯片Y验证']
    
    # Bob 只有 MEMBER 权限，不能修改项目A成员
    try:
        manager.add_member(project_a.id, bob, alice, ProjectRole.ADMIN)
    except PermissionError as e:
        print(f"\n权限错误: {e}")  # Bob 没有权限