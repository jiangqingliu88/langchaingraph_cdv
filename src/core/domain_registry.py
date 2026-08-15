"""
统一命名与状态定义 — CentralizedEnums + NamingConvention + ConsistencyLinter

所有枚举和状态定义的唯一真实来源 (Single Source of Truth)。

命名规范:
  - 模块: snake_case (pipeline_executor, signoff_manager)
  - 类: PascalCase (PipelineRun, SignoffEvent)
  - 函数: snake_case (create_signoff, get_pipeline_status)
  - 常量: UPPER_SNAKE_CASE (MAX_DOCUMENT_BYTES, DEFAULT_TIMEOUT)
  - API 路径: /api/{resource}/{action} (/api/signoffs/{sid}/approve)
  - 数据库表: snake_case 复数 (signoffs, pipeline_runs, audit_logs)
  - 枚举值: snake_case (PIPELINE_STARTED, SIGNOFF_APPROVED)

领域状态汇总:
  - PipelineRun: running → completed / completed_with_errors / cancelled
  - Signoff:     draft → pending → approved / rejected
  - DocDocument: draft → review → approved → deprecated
  - Approval:    draft → submitted → under_review → approved / rejected
                  under_review → asked_back → under_review (追问-回复)
                  under_review → returned → revising → submitted (退回-重提)
  - Task:        todo → in_progress → in_review → done / blocked

用法:
  from src.core.domain_registry import (
      PipelineState, SignoffState, DocState,
      NamingValidator, validate_module_naming
  )
"""

from __future__ import annotations
from enum import Enum
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Set
import re
from pathlib import Path


# ═══════════════════════════════════════════════════════════
# 1. 统一状态枚举 (Single Source of Truth)
# ═══════════════════════════════════════════════════════════

class PipelineState(str, Enum):
    """流水线状态 — 唯一定义，其他模块引用此处"""
    RUNNING = "running"
    COMPLETED = "completed"
    COMPLETED_WITH_ERRORS = "completed_with_errors"
    CANCELLED = "cancelled"

    @classmethod
    def terminal_states(cls) -> Set["PipelineState"]:
        return {cls.COMPLETED, cls.COMPLETED_WITH_ERRORS, cls.CANCELLED}

    @classmethod
    def active_states(cls) -> Set["PipelineState"]:
        return {cls.RUNNING}


class SignoffState(str, Enum):
    """签核状态"""
    DRAFT = "draft"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    DELETED = "deleted"

    @classmethod
    def terminal_states(cls) -> Set["SignoffState"]:
        return {cls.APPROVED, cls.REJECTED, cls.DELETED}

    @classmethod
    def mutable_states(cls) -> Set["SignoffState"]:
        return {cls.DRAFT, cls.PENDING}


class DocState(str, Enum):
    """文档状态"""
    DRAFT = "draft"
    REVIEW = "review"
    APPROVED = "approved"
    DEPRECATED = "deprecated"


class ApprovalState(str, Enum):
    """审批状态（ApprovalWorkflow 专用）"""
    DRAFT = "draft"
    SUBMITTED = "submitted"
    UNDER_REVIEW = "under_review"
    ASKED_BACK = "asked_back"
    RETURNED = "returned"
    REVISING = "revising"
    APPROVED = "approved"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


class TaskState(str, Enum):
    """任务状态"""
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    IN_REVIEW = "in_review"
    DONE = "done"
    BLOCKED = "blocked"


class ProjectState(str, Enum):
    """项目状态"""
    ACTIVE = "active"
    ARCHIVED = "archived"
    DELETED = "deleted"


class ArtifactType(str, Enum):
    """证据产物类型"""
    MANIFEST = "manifest"
    REPORT = "report"
    COVERAGE = "coverage"
    LOG = "log"
    DOC = "doc"
    TESTCASE = "testcase"
    EVIDENCE_PACKAGE = "evidence_package"


# ═══════════════════════════════════════════════════════════
# 2. 状态转移规则（统一状态机）
# ═══════════════════════════════════════════════════════════

STATE_TRANSITIONS: Dict[str, Dict[str, List[str]]] = {
    "pipeline": {
        PipelineState.RUNNING: [PipelineState.COMPLETED, PipelineState.COMPLETED_WITH_ERRORS, PipelineState.CANCELLED],
        PipelineState.COMPLETED: [],
        PipelineState.COMPLETED_WITH_ERRORS: [],
        PipelineState.CANCELLED: [],
    },
    "signoff": {
        SignoffState.DRAFT: [SignoffState.PENDING, SignoffState.DELETED],
        SignoffState.PENDING: [SignoffState.APPROVED, SignoffState.REJECTED, SignoffState.DRAFT],
        SignoffState.APPROVED: [],
        SignoffState.REJECTED: [SignoffState.DRAFT, SignoffState.PENDING],
        SignoffState.DELETED: [],
    },
    "doc": {
        DocState.DRAFT: [DocState.REVIEW, DocState.DEPRECATED],
        DocState.REVIEW: [DocState.APPROVED, DocState.DRAFT],
        DocState.APPROVED: [DocState.DEPRECATED],
        DocState.DEPRECATED: [],
    },
    "approval": {
        ApprovalState.DRAFT: [ApprovalState.SUBMITTED],
        ApprovalState.SUBMITTED: [ApprovalState.UNDER_REVIEW, ApprovalState.WITHDRAWN],
        ApprovalState.UNDER_REVIEW: [ApprovalState.APPROVED, ApprovalState.REJECTED,
                                      ApprovalState.ASKED_BACK, ApprovalState.RETURNED],
        ApprovalState.ASKED_BACK: [ApprovalState.UNDER_REVIEW],
        ApprovalState.RETURNED: [ApprovalState.REVISING],
        ApprovalState.REVISING: [ApprovalState.SUBMITTED],
        ApprovalState.APPROVED: [],
        ApprovalState.REJECTED: [],
        ApprovalState.WITHDRAWN: [],
    },
    "task": {
        TaskState.TODO: [TaskState.IN_PROGRESS, TaskState.BLOCKED],
        TaskState.IN_PROGRESS: [TaskState.IN_REVIEW, TaskState.DONE, TaskState.BLOCKED],
        TaskState.IN_REVIEW: [TaskState.DONE, TaskState.TODO, TaskState.BLOCKED],
        TaskState.DONE: [],
        TaskState.BLOCKED: [TaskState.TODO, TaskState.IN_PROGRESS],
    },
    "project": {
        ProjectState.ACTIVE: [ProjectState.ARCHIVED, ProjectState.DELETED],
        ProjectState.ARCHIVED: [ProjectState.ACTIVE, ProjectState.DELETED],
        ProjectState.DELETED: [],
    },
}


def is_valid_transition(domain: str, from_state: str, to_state: str) -> bool:
    """校验状态转移是否合法"""
    transitions = STATE_TRANSITIONS.get(domain, {})
    return to_state in transitions.get(from_state, [])


def get_valid_transitions(domain: str, from_state: str) -> List[str]:
    """获取当前状态的合法目标状态"""
    transitions = STATE_TRANSITIONS.get(domain, {})
    return transitions.get(from_state, [])


def is_terminal_state(domain: str, state: str) -> bool:
    """判断是否为终态"""
    transitions = STATE_TRANSITIONS.get(domain, {})
    return len(transitions.get(state, [])) == 0


def require_valid_transition(domain: str, from_state: str, to_state: str) -> None:
    """强制校验状态转移，非法时抛 ValueError
    调用方应捕获并返回 400 Bad Request
    """
    if from_state == to_state:
        return
    if not is_valid_transition(domain, from_state, to_state):
        valid = get_valid_transitions(domain, from_state)
        raise ValueError(
            f"非法状态转移 [{domain}]: '{from_state}' → '{to_state}'。"
            f"允许: {valid if valid else '(终态，不允许转移)'}"
        )


# ═══════════════════════════════════════════════════════════
# 3. 统一命名规范
# ═══════════════════════════════════════════════════════════

class NamingConvention:
    """命名规范定义"""

    # 模块命名: snake_case
    MODULE_PATTERN = re.compile(r'^[a-z][a-z0-9_]*\.py$')

    # 类命名: PascalCase
    CLASS_PATTERN = re.compile(r'^[A-Z][a-zA-Z0-9]+$')

    # 函数/方法命名: snake_case
    FUNCTION_PATTERN = re.compile(r'^[a-z][a-z0-9_]*$')
    # 私有函数: _snake_case
    PRIVATE_FUNCTION_PATTERN = re.compile(r'^_[a-z][a-z0-9_]*$')

    # 常量命名: UPPER_SNAKE_CASE
    CONSTANT_PATTERN = re.compile(r'^[A-Z][A-Z0-9_]*$')

    # API 路径: /api/{resource}[/{action}]  — 允许 FastAPI 路径参数 {param} 和 :path
    API_PATH_PATTERN = re.compile(r'^/api/[a-z][a-z0-9/_{}:.-]*$')

    # 数据库表: snake_case 复数
    TABLE_PATTERN = re.compile(r'^[a-z][a-z0-9_]*s$')

    # 枚举值: snake_case
    ENUM_VALUE_PATTERN = re.compile(r'^[a-z][a-z0-9_]*$')


@dataclass
class NamingViolation:
    """命名违规"""
    location: str      # 文件:行号
    name: str          # 违规的名称
    expected: str      # 期望的格式
    actual: str        # 实际的格式
    severity: str = "warning"


class NamingValidator:
    """命名一致性校验器"""

    def __init__(self):
        self._convention = NamingConvention()

    def validate_module_name(self, filepath: str) -> Optional[NamingViolation]:
        """校验模块文件名"""
        name = Path(filepath).name
        if name.startswith('__'): return None  # __init__.py 等无视
        if not self._convention.MODULE_PATTERN.match(name):
            return NamingViolation(filepath, name, "snake_case.py", name)
        return None

    def validate_class_name(self, name: str, location: str = "") -> Optional[NamingViolation]:
        """校验类名"""
        if not self._convention.CLASS_PATTERN.match(name):
            return NamingViolation(location, name, "PascalCase", name)
        return None

    def validate_function_name(self, name: str, location: str = "") -> Optional[NamingViolation]:
        """校验函数名"""
        if name.startswith('_'): return None  # 私有/魔术方法
        if not self._convention.FUNCTION_PATTERN.match(name):
            return NamingViolation(location, name, "snake_case", name)
        return None

    def validate_api_path(self, path: str) -> Optional[NamingViolation]:
        """校验 API 路径"""
        if path in ('/', '/test-login'): return None  # 特殊路由
        if not self._convention.API_PATH_PATTERN.match(path):
            return NamingViolation("api.py", path, "/api/{resource}/{action}", path)
        return None

    def validate_table_name(self, name: str) -> Optional[NamingViolation]:
        """校验数据库表名"""
        if not self._convention.TABLE_PATTERN.match(name):
            return NamingViolation(f"models.py:{name}", name, "snake_case 复数", name)
        return None

    def scan_file(self, filepath: str) -> List[NamingViolation]:
        """扫描单个文件的命名违规"""
        violations = []
        p = Path(filepath)
        if not p.exists():
            return violations

        # 检查模块名
        v = self.validate_module_name(filepath)
        if v: violations.append(v)

        content = p.read_text(encoding="utf-8", errors="replace")
        lines = content.split('\n')

        for i, line in enumerate(lines):
            location = f"{filepath}:{i+1}"

            # 检查类定义
            class_match = re.match(r'^class\s+(\w+)', line.strip())
            if class_match:
                v = self.validate_class_name(class_match.group(1), location)
                if v: violations.append(v)

            # 检查函数定义
            func_match = re.match(r'^(?:async\s+)?def\s+(\w+)', line.strip())
            if func_match:
                v = self.validate_function_name(func_match.group(1), location)
                if v: violations.append(v)

        return violations

    def scan_directory(self, directory: str, exclude_patterns: List[str] = None) -> List[NamingViolation]:
        """扫描目录下所有 Python 文件的命名违规"""
        violations = []
        exclude = set(exclude_patterns or [])
        exclude.add('__init__.py')
        exclude.add('test_')

        for py_file in Path(directory).rglob("*.py"):
            if any(py_file.name.startswith(e) for e in exclude):
                continue
            violations.extend(self.scan_file(str(py_file)))

        return violations


# ═══════════════════════════════════════════════════════════
# 4. 一致性 Linter
# ═══════════════════════════════════════════════════════════

@dataclass
class ConsistencyIssue:
    """一致性问题"""
    category: str        # naming / state / layer / duplicate
    location: str
    description: str
    severity: str = "warning"


class ConsistencyLinter:
    """全局一致性检查器"""

    def __init__(self):
        self._naming = NamingValidator()

    def check_state_consistency(self) -> List[ConsistencyIssue]:
        """检查各模块使用的状态字符串是否与统一定义一致（web 已移除，无 api.py 可扫描）"""
        return []

    def check_duplicate_definitions(self) -> List[ConsistencyIssue]:
        """检查重复定义（如多处定义了相同的状态字符串）"""
        issues = []
        # 检查是否有模块自己定义了状态枚举而不是引用 domain_registry
        infra_files = Path("src/infra").glob("*.py")
        for f in infra_files:
            content = f.read_text(encoding="utf-8", errors="replace")
            # 检测自定义的 status 枚举
            custom_enums = re.findall(r'class\s+(\w*[Ss]tatus\w*)\s*\(.*Enum\)', content)
            for enum_name in custom_enums:
                if enum_name not in ('GateStatus', 'TaskStatus', 'ReviewStatus'):
                    issues.append(ConsistencyIssue(
                        "duplicate", f.name,
                        f"文件定义了独立的 Status 枚举 '{enum_name}'，建议使用 src/core/domain_registry.py 中的统一定义",
                        "warning"))
        return issues

    def check_api_path_consistency(self) -> List[ConsistencyIssue]:
        """检查 API 路径命名一致性（web 已移除，无 api.py 可扫描）"""
        return []

    def check_table_naming(self) -> List[ConsistencyIssue]:
        """检查数据库表命名"""
        issues = []
        models_file = Path("src/database/models.py")
        if models_file.exists():
            content = models_file.read_text(encoding="utf-8")
            tables = re.findall(r"__tablename__\s*=\s*'(\w+)'", content)
            for t in tables:
                v = self._naming.validate_table_name(t)
                if v:
                    issues.append(ConsistencyIssue("naming", f"models.py:{t}",
                                                   f"数据库表名不符合规范: {t}", "warning"))
        return issues

    def lint_all(self) -> List[ConsistencyIssue]:
        issues = []
        issues.extend(self.check_state_consistency())
        issues.extend(self.check_duplicate_definitions())
        issues.extend(self.check_api_path_consistency())
        issues.extend(self.check_table_naming())
        return issues


# ═══════════════════════════════════════════════════════════
# 5. 全局便捷函数
# ═══════════════════════════════════════════════════════════

def validate_all() -> Tuple[bool, List[Any]]:
    """运行所有校验"""
    from src.infra.architecture import ArchitectureValidator
    arch_issues = ArchitectureValidator().check_all()
    consistency_issues = ConsistencyLinter().lint_all()
    naming_issues = NamingValidator().scan_directory("src", exclude_patterns=["test_", "__init__"])

    all_issues = list(arch_issues) + list(consistency_issues) + list(naming_issues)
    return len(all_issues) == 0, all_issues


def export_state_machine_doc() -> str:
    """导出状态机文档"""
    lines = ["# SignOffAI 状态机文档", ""]
    for domain, transitions in STATE_TRANSITIONS.items():
        lines.append(f"## {domain}")
        for from_state, to_states in transitions.items():
            if to_states:
                lines.append(f"  `{from_state}` → {', '.join(f'`{t}`' for t in to_states)}")
            else:
                lines.append(f"  `{from_state}` → (终态)")
        lines.append("")
    return "\n".join(lines)
