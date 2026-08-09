"""
流程模板系统 — WorkflowTemplates + TemplateInheritance + CrossProjectReuse

让常见流程可以复用和定制:
  1. TemplateRegistry — 模板注册中心，支持版本和继承
  2. TemplateInstantiator — 从模板创建实际配置
  3. CrossProjectAssetPool — 跨项目资产复用池

模板类型:
  - verification_workflow: 验证流水线模板
  - signoff_checklist: 签核检查清单模板
  - regression_rule: 回归规则模板
  - coverage_target: 覆盖率目标模板
  - doc_structure: 文档结构模板
  - review_gate: 审核门禁模板

用法:
  from src.infra.template_system import TemplateRegistry, TemplateInstantiator

  registry = TemplateRegistry()
  registry.register_template("uart_ip_full", "verification_workflow", {...})

  instantiator = TemplateInstantiator(registry)
  config = instantiator.instantiate("uart_ip_full", project_id=5, overrides={...})
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
import copy
import json


# ═══════════════════════════════════════════════════════════
# 模板类型
# ═══════════════════════════════════════════════════════════

class TemplateType(str, Enum):
    VERIFICATION_WORKFLOW = "verification_workflow"
    SIGNOFF_CHECKLIST = "signoff_checklist"
    REGRESSION_RULE = "regression_rule"
    COVERAGE_TARGET = "coverage_target"
    DOC_STRUCTURE = "doc_structure"
    REVIEW_GATE = "review_gate"


@dataclass
class Template:
    """模板定义"""
    template_id: str
    name: str
    description: str
    template_type: TemplateType
    version: int = 1
    content: Dict[str, Any] = field(default_factory=dict)  # 模板内容
    parent_template_id: str = ""       # 继承自哪个模板
    overrides: Dict[str, Any] = field(default_factory=dict)  # 覆盖父模板的字段
    tags: List[str] = field(default_factory=list)
    is_active: bool = True
    usage_count: int = 0
    created_by: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = ""
    change_history: List[dict] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════
# 预定义模板
# ═══════════════════════════════════════════════════════════

DEFAULT_TEMPLATES = {
    # ── 验证流程模板 ──
    "full_verification": Template(
        template_id="full_verification",
        name="完整验证流程",
        description="适用于 tape-out 级签核的完整 17 阶段验证流程",
        template_type=TemplateType.VERIFICATION_WORKFLOW,
        content={
            "phases": ["spec","design","model","ifspec","rtlsign","vplan","tpoint",
                       "rtm","UVM","test","assert","regress","cover","debug","qa","report","vclose"],
            "mandatory_phases": ["spec","design","vplan","UVM","cover","report","vclose"],
            "coverage_targets": {"line": 85, "branch": 75, "toggle": 60},
            "score_threshold": 70,
            "max_duration_minutes": 180,
            "auto_retry": False,
            "review_gates": ["evidence_integrity", "coverage_adequate", "regression_pass", "final_approval"],
        },
        tags=["tapeout", "full", "production"],
    ),
    "quick_check": Template(
        template_id="quick_check",
        name="快速检查流程",
        description="适用于快速迭代验证的 5 阶段轻量流程",
        template_type=TemplateType.VERIFICATION_WORKFLOW,
        content={
            "phases": ["spec","design","UVM","cover","report"],
            "mandatory_phases": ["spec","design","cover"],
            "coverage_targets": {"line": 60, "branch": 50, "toggle": 40},
            "score_threshold": 50,
            "max_duration_minutes": 30,
            "auto_retry": True,
            "review_gates": ["basic_check"],
        },
        tags=["quick", "iteration", "development"],
    ),
    "ai_exploration": Template(
        template_id="ai_exploration",
        name="AI 探索流程",
        description="AI 驱动的覆盖率探索和 corner case 发现",
        template_type=TemplateType.VERIFICATION_WORKFLOW,
        content={
            "phases": ["spec","design","vplan","UVM","smart_regression","debug","cover","report"],
            "mandatory_phases": ["spec","design","cover"],
            "coverage_targets": {"line": 70, "branch": 60, "toggle": 50},
            "score_threshold": 55,
            "max_duration_minutes": 120,
            "auto_retry": True,
            "ai_driven": True,
            "review_gates": ["ai_findings_review"],
        },
        tags=["ai", "exploration", "coverage"],
    ),

    # ── 签核清单模板 ──
    "tapeout_checklist": Template(
        template_id="tapeout_checklist",
        name="Tape-out 签核清单",
        description="芯片流片前的完整签核检查清单",
        template_type=TemplateType.SIGNOFF_CHECKLIST,
        content={
            "items": [
                {"id": "cov_line", "name": "行覆盖率达标", "threshold": 85, "mandatory": True},
                {"id": "cov_branch", "name": "分支覆盖率达标", "threshold": 75, "mandatory": True},
                {"id": "cov_toggle", "name": "翻转覆盖率达标", "threshold": 60, "mandatory": True},
                {"id": "regression_pass", "name": "回归测试通过率 >= 95%", "threshold": 95, "mandatory": True},
                {"id": "evidence_chain", "name": "5 层证据链完整", "mandatory": True},
                {"id": "manifest_hash", "name": "Manifest hash 校验通过", "mandatory": True},
                {"id": "audit_chain", "name": "审计链未断裂", "mandatory": True},
                {"id": "rtl_frozen", "name": "RTL 代码冻结", "mandatory": True},
                {"id": "uvm_frozen", "name": "UVM 环境冻结", "mandatory": False},
                {"id": "doc_approved", "name": "规格文档已审批", "mandatory": True},
            ],
        },
        tags=["tapeout", "final", "production"],
    ),

    # ── 覆盖率目标模板 ──
    "asic_coverage_target": Template(
        template_id="asic_coverage_target",
        name="ASIC 覆盖率目标",
        description="标准 ASIC 项目覆盖率目标",
        template_type=TemplateType.COVERAGE_TARGET,
        content={
            "targets": {"line": 85, "branch": 75, "toggle": 60, "assertion": 50, "functional": 80},
            "waiver_policy": "manager_approval",
            "merge_strategy": "per_module",
        },
        tags=["asic", "standard"],
    ),
    "fpga_coverage_target": Template(
        template_id="fpga_coverage_target",
        name="FPGA 覆盖率目标",
        description="FPGA 原型验证覆盖率目标（适度放宽）",
        template_type=TemplateType.COVERAGE_TARGET,
        content={
            "targets": {"line": 75, "branch": 60, "toggle": 45, "assertion": 30, "functional": 70},
            "waiver_policy": "auto",
            "merge_strategy": "per_project",
        },
        tags=["fpga", "prototype"],
    ),

    # ── 审核门禁模板 ──
    "standard_review_gates": Template(
        template_id="standard_review_gates",
        name="标准审核门禁",
        description="标准四级审核门禁链",
        template_type=TemplateType.REVIEW_GATE,
        content={
            "gates": [
                {"id": "evidence_check", "name": "证据完整性检查", "priority": "critical",
                 "required_roles": ["verification_manager"], "min_approvals": 1, "timeout_hours": 24},
                {"id": "coverage_check", "name": "覆盖率达标检查", "priority": "high",
                 "required_roles": ["verification_manager"], "min_approvals": 1, "timeout_hours": 48},
                {"id": "regression_check", "name": "回归通过率检查", "priority": "high",
                 "required_roles": ["verification_manager", "senior_engineer"], "min_approvals": 1},
                {"id": "final_approval", "name": "最终审批", "priority": "critical",
                 "required_roles": ["verification_manager"], "min_approvals": 1, "timeout_hours": 72},
            ],
        },
        tags=["standard", "four-gate"],
    ),
}


# ═══════════════════════════════════════════════════════════
# 模板注册中心
# ═══════════════════════════════════════════════════════════

class TemplateRegistry:
    """模板注册中心 — 支持版本、继承、跨项目复用"""

    def __init__(self):
        self._templates: Dict[str, Template] = {}
        self._project_usage: Dict[str, Set[int]] = {}  # template_id → {project_ids}
        self._register_defaults()

    def _register_defaults(self):
        for tid, tmpl in DEFAULT_TEMPLATES.items():
            self._templates[tid] = copy.deepcopy(tmpl)

    def register_template(self, template_id: str, name: str, description: str,
                          template_type: TemplateType, content: dict,
                          parent_template_id: str = "", tags: List[str] = None,
                          created_by: str = "") -> Template:
        """注册新模板"""
        if template_id in self._templates:
            # 新版本
            existing = self._templates[template_id]
            existing.version += 1
            existing.content = content
            existing.updated_at = datetime.now().isoformat()
            existing.change_history.append({
                "version": existing.version, "changed_by": created_by,
                "timestamp": existing.updated_at,
            })
            return existing

        tmpl = Template(
            template_id=template_id, name=name, description=description,
            template_type=template_type, content=content,
            parent_template_id=parent_template_id, tags=tags or [],
            created_by=created_by,
        )
        self._templates[template_id] = tmpl
        return tmpl

    def get_template(self, template_id: str) -> Optional[Template]:
        return self._templates.get(template_id)

    def get_all_templates(self, template_type: TemplateType = None) -> List[Template]:
        templates = list(self._templates.values())
        if template_type:
            templates = [t for t in templates if t.template_type == template_type]
        return templates

    def get_templates_by_tag(self, tag: str) -> List[Template]:
        return [t for t in self._templates.values() if tag in t.tags]

    def record_usage(self, template_id: str, project_id: int):
        """记录模板被项目使用"""
        if template_id not in self._project_usage:
            self._project_usage[template_id] = set()
        self._project_usage[template_id].add(project_id)
        tmpl = self._templates.get(template_id)
        if tmpl: tmpl.usage_count += 1

    def get_template_usage(self, template_id: str) -> Set[int]:
        return self._project_usage.get(template_id, set())

    def get_reusable_assets(self, project_id: int = None) -> List[dict]:
        """获取可跨项目复用的资产列表"""
        assets = []
        for tid, tmpl in self._templates.items():
            if not tmpl.is_active: continue
            used_by = self._project_usage.get(tid, set())
            if project_id is None or project_id not in used_by:
                assets.append({
                    "template_id": tid, "name": tmpl.name,
                    "type": tmpl.template_type.value, "version": tmpl.version,
                    "tags": tmpl.tags, "usage_count": tmpl.usage_count,
                    "used_by_projects": list(used_by),
                })
        return sorted(assets, key=lambda a: -a["usage_count"])

    def duplicate_template(self, source_id: str, new_id: str, created_by: str,
                           overrides: dict = None) -> Template:
        """复制模板（派生）"""
        source = self._templates.get(source_id)
        if not source: raise ValueError(f"Source template not found: {source_id}")
        new_content = copy.deepcopy(source.content)
        if overrides: new_content.update(overrides)
        return self.register_template(
            new_id, f"{source.name} (派生)", f"派生自 {source_id}",
            source.template_type, new_content,
            parent_template_id=source_id, tags=source.tags,
            created_by=created_by,
        )


# ═══════════════════════════════════════════════════════════
# 模板实例化器
# ═══════════════════════════════════════════════════════════

class TemplateInstantiator:
    """从模板创建实际配置 — 支持覆盖和继承"""

    def __init__(self, registry: TemplateRegistry):
        self.registry = registry

    def instantiate(self, template_id: str, project_id: int = 0,
                    overrides: Dict[str, Any] = None) -> Dict[str, Any]:
        """从模板实例化配置"""
        tmpl = self.registry.get_template(template_id)
        if not tmpl:
            raise ValueError(f"Template not found: {template_id}")

        # 解析继承链
        content = self._resolve_inheritance(tmpl)

        # 应用覆盖
        if overrides:
            content = self._deep_merge(content, overrides)

        # 记录使用
        if project_id:
            self.registry.record_usage(template_id, project_id)

        return {
            "template_id": template_id,
            "template_name": tmpl.name,
            "template_version": tmpl.version,
            "project_id": project_id,
            "config": content,
            "instantiated_at": datetime.now().isoformat(),
        }

    def _resolve_inheritance(self, tmpl: Template) -> dict:
        """解析模板继承链"""
        content = copy.deepcopy(tmpl.content)

        # 如果有父模板，先解析父模板
        if tmpl.parent_template_id:
            parent = self.registry.get_template(tmpl.parent_template_id)
            if parent:
                parent_content = self._resolve_inheritance(parent)
                content = self._deep_merge(parent_content, content)

        # 应用当前模板的覆盖
        if tmpl.overrides:
            content = self._deep_merge(content, tmpl.overrides)

        return content

    def _deep_merge(self, base: dict, override: dict) -> dict:
        """深度合并两个字典"""
        result = copy.deepcopy(base)
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = copy.deepcopy(value)
        return result

    def compare_templates(self, template_id_1: str, template_id_2: str) -> dict:
        """比较两个模板的差异"""
        t1 = self.registry.get_template(template_id_1)
        t2 = self.registry.get_template(template_id_2)
        if not t1 or not t2: return {"error": "Template not found"}

        c1 = self._resolve_inheritance(t1)
        c2 = self._resolve_inheritance(t2)

        all_keys = set(c1.keys()) | set(c2.keys())
        diffs = {}
        for key in all_keys:
            v1 = c1.get(key)
            v2 = c2.get(key)
            if v1 != v2:
                diffs[key] = {"template_1": v1, "template_2": v2}

        return {
            "template_1": {"id": template_id_1, "name": t1.name, "version": t1.version},
            "template_2": {"id": template_id_2, "name": t2.name, "version": t2.version},
            "differences": diffs,
            "total_diffs": len(diffs),
        }


# ═══════════════════════════════════════════════════════════
# 全局实例
# ═══════════════════════════════════════════════════════════

_template_registry: Optional[TemplateRegistry] = None
_instantiator: Optional[TemplateInstantiator] = None


def get_template_registry() -> TemplateRegistry:
    global _template_registry
    if _template_registry is None:
        _template_registry = TemplateRegistry()
    return _template_registry


def get_template_instantiator() -> TemplateInstantiator:
    global _instantiator
    if _instantiator is None:
        _instantiator = TemplateInstantiator(get_template_registry())
    return _instantiator
