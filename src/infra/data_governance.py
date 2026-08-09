"""
统一数据模型治理 — Data Dictionary + Model Validator + Consistency Checker

三件事:
  1. DataDictionary — 所有领域对象的统一定义（字段名、类型、约束、状态机）
  2. ModelValidator — 运行时校验模型是否符合数据字典约定
  3. ConsistencyChecker — 跨表一致性检查（孤儿引用、状态冲突、hash 断裂）

用法:
  from src.infra.data_governance import DataDictionary, ModelValidator

  dd = DataDictionary()
  validator = ModelValidator(dd)
  issues = validator.validate_model(Signoff, {"status": "approved"})
  # → [] (no issues) or [{"field": "...", "issue": "..."}]

  checker = ConsistencyChecker()
  broken = await checker.check_evidence_integrity()
  # → [{"artifact_id": 5, "issue": "hash mismatch with manifest"}]
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple
from datetime import datetime
import re


# ═══════════════════════════════════════════════════════════
# 统一数据字典
# ═══════════════════════════════════════════════════════════

@dataclass
class FieldDef:
    """字段定义"""
    name: str
    type: str                    # str / int / float / bool / datetime / json / text
    required: bool = False
    max_length: int = 0
    default: Any = None
    description: str = ""
    enum_values: List[str] = field(default_factory=list)  # 约束枚举值
    nullable: bool = True
    indexed: bool = False


@dataclass
class EntityDef:
    """实体定义 — 对应一张数据库表"""
    table_name: str
    display_name: str
    description: str
    fields: List[FieldDef] = field(default_factory=list)
    state_machine: Dict[str, List[str]] = field(default_factory=dict)  # status: [valid_next_statuses]
    unique_constraints: List[List[str]] = field(default_factory=list)
    foreign_keys: Dict[str, str] = field(default_factory=dict)  # field: target_table.field


class DataDictionary:
    """统一数据字典 — 所有领域对象的标准定义"""

    def __init__(self):
        self.entities: Dict[str, EntityDef] = {}
        self._define_all()

    def _define_all(self):
        """定义所有核心实体"""

        # ── 用户 ──
        self.entities["users"] = EntityDef(
            table_name="users",
            display_name="用户",
            description="平台用户账户",
            fields=[
                FieldDef("id", "int", required=True, description="主键"),
                FieldDef("username", "str", required=True, max_length=50, description="登录名"),
                FieldDef("password_hash", "str", required=True, max_length=256, description="PBKDF2 密码哈希"),
                FieldDef("display_name", "str", max_length=100, description="显示名称"),
                FieldDef("email", "str", max_length=200, description="邮箱"),
                FieldDef("role", "str", required=True, max_length=30, default="engineer",
                         enum_values=["admin", "verification_manager", "senior_engineer", "engineer", "viewer"],
                         description="平台角色"),
                FieldDef("is_active", "bool", default=True, description="是否激活"),
                FieldDef("created_at", "datetime", description="创建时间"),
                FieldDef("last_login", "datetime", nullable=True, description="最后登录"),
            ],
            unique_constraints=[["username"]],
        )

        # ── 项目 ──
        self.entities["projects"] = EntityDef(
            table_name="projects",
            display_name="项目",
            description="验证项目",
            fields=[
                FieldDef("id", "int", required=True),
                FieldDef("name", "str", required=True, max_length=200, description="项目名称"),
                FieldDef("description", "str", max_length=500, description="项目描述"),
                FieldDef("owner_id", "int", description="项目负责人"),
                FieldDef("status", "str", max_length=20, default="active",
                         enum_values=["active", "archived", "deleted"], description="项目状态"),
                FieldDef("created_at", "datetime"),
            ],
            state_machine={"active": ["archived", "deleted"], "archived": ["active", "deleted"], "deleted": []},
            foreign_keys={"owner_id": "users.id"},
        )

        # ── 签核 ──
        self.entities["signoffs"] = EntityDef(
            table_name="signoffs",
            display_name="签核记录",
            description="签核请求，绑定证据链",
            fields=[
                FieldDef("id", "int", required=True),
                FieldDef("project_id", "int", description="关联项目"),
                FieldDef("title", "str", required=True, max_length=300, description="签核标题"),
                FieldDef("report_type", "str", max_length=50,
                         enum_values=["tapeout", "milestone", "coverage",
                                     "ppa_power", "ppa_performance", "ppa_area", "ppa_full"],
                         description="签核类型"),
                FieldDef("status", "str", required=True, max_length=20, default="draft",
                         enum_values=["draft", "pending", "approved", "rejected"], description="签核状态"),
                FieldDef("summary_json", "json", description="报告摘要"),
                FieldDef("evidence_package_hash", "str", max_length=64, description="证据包 hash"),
                FieldDef("manifest_hash", "str", max_length=64, description="Manifest hash"),
                FieldDef("run_id", "str", max_length=64, description="关联流水线"),
                FieldDef("requester_id", "int", description="申请人"),
                FieldDef("approver_id", "int", nullable=True, description="审批人"),
                FieldDef("approved_by_name", "str", max_length=100, description="审批人姓名"),
                FieldDef("approved_at", "datetime", nullable=True, description="审批时间"),
                FieldDef("reject_reason", "str", max_length=500, description="驳回理由"),
                FieldDef("comment", "str", max_length=500, description="备注"),
                FieldDef("is_deleted", "bool", default=False, description="软删除"),
                FieldDef("created_at", "datetime"),
                FieldDef("updated_at", "datetime"),
            ],
            state_machine={
                "draft": ["pending", "deleted"],
                "pending": ["approved", "rejected", "draft"],
                "approved": [], "rejected": ["draft", "pending"],
            },
            foreign_keys={"project_id": "projects.id", "requester_id": "users.id", "approver_id": "users.id"},
        )

        # ── 签核事件 ──
        self.entities["signoff_events"] = EntityDef(
            table_name="signoff_events",
            display_name="签核事件",
            description="签核审批历史事件流",
            fields=[
                FieldDef("id", "int", required=True),
                FieldDef("signoff_id", "int", required=True, indexed=True),
                FieldDef("event_type", "str", required=True, max_length=30,
                         enum_values=["submitted", "approved", "rejected", "commented", "reopened", "draft"]),
                FieldDef("actor_id", "int", nullable=True),
                FieldDef("actor_name", "str", max_length=100),
                FieldDef("actor_role", "str", max_length=30, description="操作时的角色"),
                FieldDef("comment", "str", max_length=500),
                FieldDef("before_status", "str", max_length=20),
                FieldDef("after_status", "str", max_length=20),
                FieldDef("evidence_hash", "str", max_length=64),
                FieldDef("created_at", "datetime"),
            ],
            foreign_keys={"signoff_id": "signoffs.id"},
        )

        # ── 证据产物 ──
        self.entities["artifacts"] = EntityDef(
            table_name="artifacts",
            display_name="证据产物",
            description="可审计的证据文件/数据对象",
            fields=[
                FieldDef("id", "int", required=True),
                FieldDef("project_id", "int", indexed=True),
                FieldDef("run_id", "str", max_length=64, indexed=True),
                FieldDef("signoff_id", "int", indexed=True, nullable=True),
                FieldDef("artifact_type", "str", required=True, max_length=50,
                         enum_values=["manifest", "report", "coverage", "log", "doc", "testcase", "evidence_package"]),
                FieldDef("name", "str", required=True, max_length=300),
                FieldDef("path", "str", max_length=500),
                FieldDef("content_hash", "str", max_length=64),
                FieldDef("size_bytes", "int", default=0),
                FieldDef("metadata_json", "json"),
                FieldDef("created_at", "datetime"),
            ],
            foreign_keys={"project_id": "projects.id", "signoff_id": "signoffs.id"},
        )

        # ── 证据关联 ──
        self.entities["evidence_links"] = EntityDef(
            table_name="evidence_links",
            display_name="证据关联",
            description="证据与业务对象的多对多绑定",
            fields=[
                FieldDef("id", "int", required=True),
                FieldDef("artifact_id", "int", required=True, indexed=True),
                FieldDef("object_type", "str", required=True, max_length=30,
                         enum_values=["signoff", "pipeline_run", "doc_document", "regression"]),
                FieldDef("object_id", "int", required=True),
                FieldDef("relation_type", "str", max_length=30, default="attached_to",
                         enum_values=["attached_to", "generated_by", "referenced_by", "verifies"]),
                FieldDef("created_at", "datetime"),
            ],
            foreign_keys={"artifact_id": "artifacts.id"},
        )

        # ── PPA 签核 ──
        self.entities["ppa_metrics"] = EntityDef(
            table_name="ppa_metrics",
            display_name="PPA 签核指标",
            description="Power / Performance / Area 量化指标 — target vs actual 对比",
            fields=[
                FieldDef("id", "int", required=True),
                FieldDef("signoff_id", "int", required=True, indexed=True),
                FieldDef("category", "str", required=True, max_length=20, indexed=True,
                         enum_values=["power", "performance", "area"]),
                FieldDef("metric_name", "str", required=True, max_length=100),
                FieldDef("target_value", "float", default=0.0),
                FieldDef("actual_value", "float", default=0.0),
                FieldDef("unit", "str", max_length=20),
                FieldDef("pass_status", "str", max_length=20, default="pending",
                         enum_values=["pending", "pass", "fail", "marginal"]),
                FieldDef("margin_pct", "float", default=0.0),
                FieldDef("source_file", "str", max_length=500),
                FieldDef("source_hash", "str", max_length=64),
                FieldDef("notes", "text"),
                FieldDef("created_at", "datetime"),
                FieldDef("updated_at", "datetime"),
            ],
            foreign_keys={"signoff_id": "signoffs.id"},
        )

        self.entities["ppa_corners"] = EntityDef(
            table_name="ppa_corners",
            display_name="PPA 工艺角数据",
            description="多 PVT corner 的 PPA 全维度分析数据",
            fields=[
                FieldDef("id", "int", required=True),
                FieldDef("signoff_id", "int", required=True, indexed=True),
                FieldDef("corner_name", "str", required=True, max_length=50),
                FieldDef("pvt_desc", "str", max_length=100),
                FieldDef("total_power_mw", "float", default=0.0),
                FieldDef("dynamic_power_mw", "float", default=0.0),
                FieldDef("leakage_power_mw", "float", default=0.0),
                FieldDef("fmax_mhz", "float", default=0.0),
                FieldDef("setup_worst_ns", "float", default=0.0),
                FieldDef("hold_worst_ns", "float", default=0.0),
                FieldDef("area_mm2", "float", default=0.0),
                FieldDef("cell_count", "int", default=0),
                FieldDef("utilization_pct", "float", default=0.0),
                FieldDef("extra_json", "json"),
                FieldDef("created_at", "datetime"),
            ],
            foreign_keys={"signoff_id": "signoffs.id"},
        )

        self.entities["ppa_constraints"] = EntityDef(
            table_name="ppa_constraints",
            display_name="PPA 门限规则",
            description="可配置的 PPA 约束门限，支持变更审批",
            fields=[
                FieldDef("id", "int", required=True),
                FieldDef("project_id", "int", indexed=True, nullable=True),
                FieldDef("category", "str", required=True, max_length=20,
                         enum_values=["power", "performance", "area"]),
                FieldDef("metric_name", "str", required=True, max_length=100),
                FieldDef("constraint_type", "str", max_length=20, default="max",
                         enum_values=["max", "min", "range"]),
                FieldDef("threshold_value", "float", default=0.0),
                FieldDef("unit", "str", max_length=20),
                FieldDef("margin_required_pct", "float", default=10.0),
                FieldDef("severity", "str", max_length=10, default="P1",
                         enum_values=["P0", "P1", "P2"]),
                FieldDef("is_active", "bool", default=True),
                FieldDef("description", "str", max_length=300),
                FieldDef("created_by", "int", nullable=True),
                FieldDef("created_at", "datetime"),
                FieldDef("updated_at", "datetime"),
            ],
            foreign_keys={"project_id": "projects.id", "created_by": "users.id"},
        )

        # ── 流水线运行 ──
        self.entities["pipeline_runs"] = EntityDef(
            table_name="pipeline_runs",
            display_name="流水线运行",
            description="AI 验证流水线执行记录",
            fields=[
                FieldDef("id", "int", required=True),
                FieldDef("run_id", "str", required=True, max_length=64, indexed=True),
                FieldDef("project_id", "int", nullable=True),
                FieldDef("workflow", "str", max_length=100),
                FieldDef("spec_file", "str", max_length=500),
                FieldDef("state", "str", max_length=30, default="running",
                         enum_values=["running", "completed", "completed_with_errors", "cancelled"]),
                FieldDef("total_phases", "int"),
                FieldDef("passed", "int"),
                FieldDef("degraded", "int"),
                FieldDef("failed", "int", default=0),
                FieldDef("total_time", "float"),
                FieldDef("phases_json", "json"),
                FieldDef("results", "json"),
                FieldDef("coverage_line_pct", "float", default=0.0),
                FieldDef("coverage_branch_pct", "float", default=0.0),
                FieldDef("coverage_toggle_pct", "float", default=0.0),
                FieldDef("evidence_hash", "str", max_length=64),
                FieldDef("manifest_hash", "str", max_length=64),
                FieldDef("started_at", "datetime"),
                FieldDef("completed_at", "datetime", nullable=True),
                FieldDef("created_at", "datetime"),
            ],
            state_machine={
                "running": ["completed", "completed_with_errors", "cancelled"],
                "completed": [], "completed_with_errors": [], "cancelled": [],
            },
            unique_constraints=[["run_id"]],
        )

        # ── 文档 ──
        self.entities["doc_documents"] = EntityDef(
            table_name="doc_documents",
            display_name="规格文档",
            description="MD 规格文档",
            fields=[
                FieldDef("id", "int", required=True),
                FieldDef("project_id", "int", nullable=True),
                FieldDef("path", "str", required=True, max_length=500),
                FieldDef("title", "str", max_length=300),
                FieldDef("content", "text"),
                FieldDef("content_hash", "str", max_length=64),
                FieldDef("level", "str", max_length=20, default="module",
                         enum_values=["chip", "subsystem", "module", "unit"]),
                FieldDef("status", "str", max_length=20, default="draft",
                         enum_values=["draft", "review", "approved", "deprecated"]),
                FieldDef("author_id", "int"),
                FieldDef("tags", "str", max_length=500),
                FieldDef("metadata_json", "json"),
                FieldDef("view_count", "int", default=0),
                FieldDef("created_at", "datetime"),
                FieldDef("updated_at", "datetime"),
            ],
            state_machine={
                "draft": ["review", "deprecated"], "review": ["approved", "draft"],
                "approved": ["deprecated"], "deprecated": [],
            },
            unique_constraints=[["path"]],
        )

        # ── 审计日志 ──
        self.entities["audit_logs"] = EntityDef(
            table_name="audit_logs",
            display_name="审计日志",
            description="不可篡改的操作审计记录",
            fields=[
                FieldDef("id", "int", required=True),
                FieldDef("user_id", "int", nullable=True),
                FieldDef("username", "str", max_length=50),
                FieldDef("role", "str", max_length=30, description="操作时的角色"),
                FieldDef("action", "str", required=True, max_length=100),
                FieldDef("resource_type", "str", max_length=50, description="资源类型"),
                FieldDef("resource", "str", max_length=200, description="资源标识"),
                FieldDef("target_id", "str", max_length=200),
                FieldDef("detail", "text"),
                FieldDef("before_state", "text"),
                FieldDef("after_state", "text"),
                FieldDef("access_result", "str", max_length=20, default="success",
                         enum_values=["success", "denied", "error"]),
                FieldDef("is_privileged_action", "bool", default=False),
                FieldDef("ip_address", "str", max_length=50),
                FieldDef("user_agent", "str", max_length=300),
                FieldDef("created_at", "datetime"),
            ],
        )

    # ── 查询方法 ──

    def get_entity(self, table_name: str) -> Optional[EntityDef]:
        return self.entities.get(table_name)

    def get_all_tables(self) -> List[str]:
        return list(self.entities.keys())

    def get_state_machine(self, table_name: str) -> Dict[str, List[str]]:
        entity = self.entities.get(table_name)
        return entity.state_machine if entity else {}

    def is_valid_transition(self, table_name: str, from_status: str, to_status: str) -> bool:
        sm = self.get_state_machine(table_name)
        return to_status in sm.get(from_status, [])

    def get_required_fields(self, table_name: str) -> List[str]:
        entity = self.entities.get(table_name)
        if not entity: return []
        return [f.name for f in entity.fields if f.required]

    def get_enum_values(self, table_name: str, field_name: str) -> List[str]:
        entity = self.entities.get(table_name)
        if not entity: return []
        for f in entity.fields:
            if f.name == field_name:
                return f.enum_values
        return []

    def to_markdown(self) -> str:
        """导出为 Markdown 数据字典文档"""
        lines = ["# SignOffAI 数据字典", "", f"生成时间: {datetime.now().isoformat()}", ""]
        for name, entity in self.entities.items():
            lines.append(f"## {entity.display_name} (`{entity.table_name}`)")
            lines.append(f"")
            lines.append(f"{entity.description}")
            lines.append(f"")
            lines.append("| 字段 | 类型 | 必填 | 约束 | 说明 |")
            lines.append("|------|------|------|------|------|")
            for f in entity.fields:
                constraints = []
                if f.max_length: constraints.append(f"≤{f.max_length}")
                if f.enum_values: constraints.append(f"enum: [{', '.join(f.enum_values)}]")
                if f.indexed: constraints.append("INDEXED")
                lines.append(f"| {f.name} | {f.type} | {'✅' if f.required else ''} | {', '.join(constraints)} | {f.description} |")
            lines.append("")
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
# 模型校验器
# ═══════════════════════════════════════════════════════════

@dataclass
class ValidationIssue:
    field: str
    issue: str
    severity: str  # error / warning / info
    suggestion: str = ""


class ModelValidator:
    """运行时校验数据是否符合数据字典约定"""

    def __init__(self, dictionary: DataDictionary = None):
        self.dd = dictionary or DataDictionary()

    def validate_model(self, table_name: str, data: dict) -> List[ValidationIssue]:
        """校验一条数据记录是否符合数据字典"""
        issues = []
        entity = self.dd.get_entity(table_name)
        if not entity:
            return [ValidationIssue("", f"Unknown table: {table_name}", "error")]

        field_map = {f.name: f for f in entity.fields}

        # 检查必填字段
        for f in entity.fields:
            if f.required and f.name not in data:
                issues.append(ValidationIssue(f.name, f"必填字段缺失", "error", f"请提供 {f.description}"))
            if f.name in data and data[f.name] is not None:
                issues.extend(self._validate_field(f, data[f.name]))

        # 检查未知字段
        for key in data:
            if key not in field_map:
                issues.append(ValidationIssue(key, f"数据字典中未定义的字段", "warning", "可能是废弃字段或拼写错误"))

        return issues

    def _validate_field(self, field: FieldDef, value: Any) -> List[ValidationIssue]:
        issues = []
        name = field.name

        # 类型检查
        type_checks = {
            "str": str, "text": str, "int": int, "float": (int, float),
            "bool": bool, "json": (dict, list), "datetime": str,
        }
        expected = type_checks.get(field.type)
        if expected and not isinstance(value, expected):
            issues.append(ValidationIssue(name, f"类型错误: 期望 {field.type}, 实际 {type(value).__name__}", "error"))

        # 长度检查
        if field.max_length and isinstance(value, str) and len(value) > field.max_length:
            issues.append(ValidationIssue(name, f"字符串过长: {len(value)} > {field.max_length}", "warning",
                                          f"截断到 {field.max_length} 字符"))

        # 枚举检查
        if field.enum_values and isinstance(value, str) and value not in field.enum_values:
            issues.append(ValidationIssue(name, f"枚举值无效: '{value}' not in {field.enum_values}", "error",
                                          f"允许的值: {', '.join(field.enum_values)}"))

        return issues

    def validate_state_transition(self, table_name: str, from_status: str, to_status: str) -> ValidationIssue | None:
        """校验状态转换是否合法"""
        if not self.dd.is_valid_transition(table_name, from_status, to_status):
            valid = self.dd.get_state_machine(table_name).get(from_status, [])
            return ValidationIssue("status", f"非法状态转换: {from_status} → {to_status}", "error",
                                   f"允许的目标状态: {', '.join(valid) if valid else '无 (终态)'}")
        return None


# ═══════════════════════════════════════════════════════════
# 一致性检查器
# ═══════════════════════════════════════════════════════════

@dataclass
class ConsistencyIssue:
    entity: str
    entity_id: int
    issue: str
    severity: str  # error / warning
    related_entity: str = ""


class ConsistencyChecker:
    """跨表一致性检查 — 孤儿引用、状态冲突、hash 断裂"""

    async def check_all(self) -> List[ConsistencyIssue]:
        """运行所有一致性检查"""
        issues = []
        issues.extend(await self.check_orphan_references())
        issues.extend(await self.check_state_conflicts())
        issues.extend(await self.check_evidence_integrity())
        return issues

    async def check_orphan_references(self) -> List[ConsistencyIssue]:
        """检查孤儿引用 — signoff → pipeline_run, artifact → signoff 等"""
        issues = []
        try:
            from src.database.connection import get_session
            from src.database.models import Signoff, PipelineRun, Artifact, EvidenceLink, Project
            from sqlalchemy import select

            s = await get_session()

            # Signoff with non-existent run_id
            signoffs = (await s.execute(select(Signoff).where(Signoff.run_id != ""))).scalars().all()
            for sf in signoffs:
                if sf.run_id:
                    run = (await s.execute(select(PipelineRun).where(PipelineRun.run_id == sf.run_id))).scalar_one_or_none()
                    if not run:
                        issues.append(ConsistencyIssue("signoffs", sf.id,
                            f"签核引用了不存在的流水线 run_id: {sf.run_id}", "warning", "pipeline_runs"))

            # Artifact with non-existent signoff_id
            artifacts = (await s.execute(select(Artifact).where(Artifact.signoff_id.isnot(None)))).scalars().all()
            for a in artifacts:
                if a.signoff_id:
                    sf = (await s.execute(select(Signoff).where(Signoff.id == a.signoff_id))).scalar_one_or_none()
                    if not sf:
                        issues.append(ConsistencyIssue("artifacts", a.id,
                            f"证据产物引用了已删除的签核 signoff_id={a.signoff_id}", "warning", "signoffs"))

            # EvidenceLink with non-existent artifact
            links = (await s.execute(select(EvidenceLink))).scalars().all()
            for link in links:
                art = (await s.execute(select(Artifact).where(Artifact.id == link.artifact_id))).scalar_one_or_none()
                if not art:
                    issues.append(ConsistencyIssue("evidence_links", link.id,
                        f"证据关联引用了不存在的 artifact_id={link.artifact_id}", "error", "artifacts"))

            await s.close()
        except Exception as e:
            issues.append(ConsistencyIssue("system", 0, f"孤儿引用检查失败: {e}", "error"))
        return issues

    async def check_state_conflicts(self) -> List[ConsistencyIssue]:
        """检查状态冲突 — 已批准的签核不应有关联的运行中流水线"""
        issues = []
        try:
            from src.database.connection import get_session
            from src.database.models import Signoff, PipelineRun
            from sqlalchemy import select

            s = await get_session()
            approved = (await s.execute(select(Signoff).where(Signoff.status == "approved"))).scalars().all()
            for sf in approved:
                if sf.run_id:
                    run = (await s.execute(select(PipelineRun).where(PipelineRun.run_id == sf.run_id))).scalar_one_or_none()
                    if run and run.state == "running":
                        issues.append(ConsistencyIssue("signoffs", sf.id,
                            f"已批准的签核关联了仍在运行的流水线 {sf.run_id}", "warning", "pipeline_runs"))
            await s.close()
        except Exception as e:
            issues.append(ConsistencyIssue("system", 0, f"状态冲突检查失败: {e}", "error"))
        return issues

    async def check_evidence_integrity(self) -> List[ConsistencyIssue]:
        """检查证据完整性 — manifest hash 链是否断裂"""
        issues = []
        try:
            from src.database.connection import get_session
            from src.database.models import Signoff, Artifact
            from sqlalchemy import select

            s = await get_session()
            # 有 manifest_hash 但没有对应 artifact 的签核
            signoffs = (await s.execute(select(Signoff).where(Signoff.manifest_hash != ""))).scalars().all()
            for sf in signoffs:
                arts = (await s.execute(select(Artifact).where(
                    Artifact.signoff_id == sf.id, Artifact.artifact_type == "manifest"))).scalars().all()
                if not arts:
                    issues.append(ConsistencyIssue("signoffs", sf.id,
                        f"签核有 manifest_hash 但没有对应的 manifest artifact", "warning", "artifacts"))

            # Artifact with hash mismatch with linked signoff
            artifacts = (await s.execute(select(Artifact).where(Artifact.artifact_type == "manifest"))).scalars().all()
            for a in artifacts:
                if a.signoff_id and a.content_hash:
                    ssf = (await s.execute(select(Signoff).where(Signoff.id == a.signoff_id))).scalar_one_or_none()
                    if ssf and ssf.manifest_hash and a.content_hash != ssf.manifest_hash:
                        issues.append(ConsistencyIssue("artifacts", a.id,
                            f"Manifest artifact hash ({a.content_hash[:12]}...) 与签核 manifest_hash ({ssf.manifest_hash[:12]}...) 不一致",
                            "error", "signoffs"))

            await s.close()
        except Exception as e:
            issues.append(ConsistencyIssue("system", 0, f"证据完整性检查失败: {e}", "error"))
        return issues


# ═══════════════════════════════════════════════════════════
# 数据字典导出工具
# ═══════════════════════════════════════════════════════════

def export_data_dictionary(output_path: str = "docs/DATA_DICTIONARY.md"):
    """导出 Markdown 数据字典到文件"""
    dd = DataDictionary()
    md = dd.to_markdown()
    from pathlib import Path
    p = Path(output_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(md, encoding="utf-8")
    return str(p)


# ═══════════════════════════════════════════════════════════
# 全局实例
# ═══════════════════════════════════════════════════════════

_data_dictionary: Optional[DataDictionary] = None


def get_data_dictionary() -> DataDictionary:
    global _data_dictionary
    if _data_dictionary is None:
        _data_dictionary = DataDictionary()
    return _data_dictionary


def get_validator() -> ModelValidator:
    return ModelValidator(get_data_dictionary())
