"""
低代码/配置化流程编辑器 — YAML 驱动的工作流定义

定义验证流程模板、步骤、条件分支，支持 API 动态创建/修改
"""
from __future__ import annotations

import yaml
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class WorkflowStep:
    """工作流步骤"""
    name: str
    agent_role: str = ""
    description: str = ""
    condition: str = ""          # 执行条件表达式
    on_failure: str = "stop"     # stop / skip / retry
    max_retries: int = 1
    timeout_s: int = 300
    required: bool = True
    depends_on: list = field(default_factory=list)


@dataclass
class WorkflowTemplate:
    """工作流模板"""
    name: str
    version: str = "1.0"
    description: str = ""
    category: str = "verification"     # verification / regression / signoff / ppa
    steps: list[WorkflowStep] = field(default_factory=list)
    triggers: list[dict] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "name": self.name, "version": self.version,
            "description": self.description, "category": self.category,
            "steps": [{"name": s.name, "agent_role": s.agent_role,
                       "condition": s.condition, "on_failure": s.on_failure,
                       "max_retries": s.max_retries, "timeout_s": s.timeout_s,
                       "required": s.required, "depends_on": s.depends_on}
                      for s in self.steps],
            "triggers": self.triggers,
            "metadata": self.metadata,
        }


# ── 内置模板 ──

BUILTIN_TEMPLATES = {
    "full_verification": WorkflowTemplate(
        name="full_verification",
        description="完整 AI 验证流水线：规格分析 -> 架构设计 -> UVM生成 -> 测试 -> 回归 -> 覆盖率 -> 报告",
        category="verification",
        steps=[
            WorkflowStep("vplan", "spec_and_test_planner", "生成验证计划", on_failure="stop", max_retries=2),
            WorkflowStep("design", "design_architect", "设计架构分析", depends_on=["vplan"], on_failure="skip"),
            WorkflowStep("uvm", "verification_architect", "生成 UVM 环境", depends_on=["design"], on_failure="retry", max_retries=3),
            WorkflowStep("tests", "test_engineer", "生成测试用例", depends_on=["uvm"], on_failure="retry", max_retries=2),
            WorkflowStep("regression", "regression_manager", "运行回归", depends_on=["tests"], on_failure="retry", max_retries=1, timeout_s=3600),
            WorkflowStep("coverage", "coverage_manager", "覆盖率分析", depends_on=["regression"], on_failure="skip"),
            WorkflowStep("qa", "quality_assurance", "质量审核", depends_on=["coverage"], on_failure="stop"),
            WorkflowStep("report", "report_generator", "生成签核报告", depends_on=["qa"], on_failure="stop"),
        ],
    ),
    "quick_check": WorkflowTemplate(
        name="quick_check",
        description="快速检查：仅规格分析 + 设计检查，不跑仿真",
        category="verification",
        steps=[
            WorkflowStep("vplan", "spec_and_test_planner", "生成验证计划"),
            WorkflowStep("design", "design_architect", "设计架构分析", depends_on=["vplan"]),
            WorkflowStep("qa", "quality_assurance", "质量审核", depends_on=["design"]),
        ],
    ),
    "regression_only": WorkflowTemplate(
        name="regression_only",
        description="仅回归：编译 + 仿真 + 覆盖率",
        category="regression",
        steps=[
            WorkflowStep("regression", "regression_manager", "运行回归", timeout_s=3600),
            WorkflowStep("coverage", "coverage_manager", "覆盖率分析", depends_on=["regression"]),
            WorkflowStep("report", "report_generator", "生成报告", depends_on=["coverage"]),
        ],
    ),
    "ppa_analysis": WorkflowTemplate(
        name="ppa_analysis",
        description="PPA 签核：功耗 + 性能 + 面积分析",
        category="ppa",
        steps=[
            WorkflowStep("power", "coverage_manager", "功耗分析"),
            WorkflowStep("timing", "coverage_manager", "时序分析"),
            WorkflowStep("area", "coverage_manager", "面积分析"),
            WorkflowStep("ppa_report", "report_generator", "PPA 签核报告", depends_on=["power", "timing", "area"]),
        ],
    ),
}


class WorkflowRegistry:
    """工作流注册表 — 管理所有流程模板"""

    def __init__(self):
        self._templates: dict[str, WorkflowTemplate] = dict(BUILTIN_TEMPLATES)

    def get(self, name: str) -> Optional[WorkflowTemplate]:
        return self._templates.get(name)

    def list_all(self) -> list[dict]:
        return [{
            "name": t.name, "version": t.version,
            "description": t.description, "category": t.category,
            "steps_count": len(t.steps),
        } for t in self._templates.values()]

    def register(self, template: WorkflowTemplate):
        self._templates[template.name] = template

    def create_from_dict(self, data: dict) -> WorkflowTemplate:
        """从 dict 创建模板"""
        steps = [WorkflowStep(**s) for s in data.get("steps", [])]
        return WorkflowTemplate(
            name=data["name"], version=data.get("version", "1.0"),
            description=data.get("description", ""),
            category=data.get("category", "custom"),
            steps=steps,
            triggers=data.get("triggers", []),
            metadata=data.get("metadata", {}),
        )

    def get_step_deps(self, template_name: str) -> dict:
        """获取模板的步骤依赖关系"""
        tmpl = self.get(template_name)
        if not tmpl:
            return {}
        return {
            "template": template_name,
            "steps": [{"name": s.name, "agent": s.agent_role,
                       "depends_on": s.depends_on,
                       "on_failure": s.on_failure,
                       "required": s.required}
                      for s in tmpl.steps],
        }

    def validate(self, template: WorkflowTemplate) -> list[str]:
        """验证工作流是否合法（无循环依赖等）"""
        errors = []
        step_names = {s.name for s in template.steps}

        for s in template.steps:
            for dep in s.depends_on:
                if dep not in step_names:
                    errors.append(f"步骤 '{s.name}' 依赖未知步骤 '{dep}'")
                if dep == s.name:
                    errors.append(f"步骤 '{s.name}' 不能依赖自身")

        # 简单环检测
        visited = set()
        path = []

        def has_cycle(name: str) -> bool:
            if name in path:
                return True
            if name in visited:
                return False
            visited.add(name)
            path.append(name)
            step = next((s for s in template.steps if s.name == name), None)
            if step:
                for dep in step.depends_on:
                    if has_cycle(dep):
                        return True
            path.pop()
            return False

        for s in template.steps:
            if has_cycle(s.name):
                errors.append(f"检测到循环依赖")
                break

        return errors

    def export_to_yaml(self, template_name: str) -> str:
        """导出模板为 YAML"""
        tmpl = self.get(template_name)
        if not tmpl:
            return ""
        return yaml.dump(tmpl.to_dict(), default_flow_style=False, allow_unicode=True)


# ── 全局 ──
_workflow_registry: Optional[WorkflowRegistry] = None


def get_workflow_registry() -> WorkflowRegistry:
    global _workflow_registry
    if _workflow_registry is None:
        _workflow_registry = WorkflowRegistry()
    return _workflow_registry
