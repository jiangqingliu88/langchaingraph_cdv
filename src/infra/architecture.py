"""
架构约束与分层规范 — Domain Boundaries + Layer Separation + Architecture Validator

六层架构:
  Interface  ── API 端点、CLI 命令、WebSocket/SSE
  Service    ── 业务逻辑编排、工作流、事务管理
  Domain     ── 核心实体、值对象、领域规则
  Repository ── 数据持久化、查询、缓存
  Infra      ── 横切关注点: 安全、监控、消息、模板
  Tool       ── 外部工具封装: UVM、VCS、Verdi

六个 Bounded Context:
  1. Verification (验证执行)    — Pipeline、Regression、Coverage、Testcase
  2. Signoff    (签核审批)      — Signoff、ApprovalWorkflow、Evidence、Manifest
  3. Document   (文档管理)      — DocDocument、DocVersion、DocRequirement
  4. Design     (设计追溯)      — DesignModule、DesignFeature、ReqFeatureMap
  5. Platform   (平台治理)      — User、Project、RBAC、Audit、Template
  6. Intelligence (AI 引擎)     — DebugCopilot、VPlan、SmartRegression、AutoFix

每层必须实现的抽象:
  - Interface:  only routing + validation + response formatting
  - Service:    business orchestration, calls Repository + Domain
  - Repository: pure data access, no business logic
  - Domain:     entities + value objects + domain rules

用法:
  python -m src.infra.architecture --validate
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple
from abc import ABC, abstractmethod
import re
import os
from pathlib import Path


# ═══════════════════════════════════════════════════════════
# 1. 领域边界定义
# ═══════════════════════════════════════════════════════════

class BoundedContext(str, Enum):
    """限界上下文 — 领域边界"""
    VERIFICATION = "verification"
    SIGNOFF = "signoff"
    DOCUMENT = "document"
    DESIGN = "design"
    PLATFORM = "platform"
    INTELLIGENCE = "intelligence"


class ArchitectureLayer(str, Enum):
    """架构分层"""
    INTERFACE = "interface"    # API / CLI / SSE
    SERVICE = "service"        # Business logic
    DOMAIN = "domain"          # Entities + rules
    REPOSITORY = "repository"  # Data access
    INFRA = "infra"            # Cross-cutting
    TOOL = "tool"              # External tools


@dataclass
class ModuleDef:
    """模块定义 — 所属领域、所属层、暴露接口、依赖关系"""
    name: str
    path: str
    context: BoundedContext
    layer: ArchitectureLayer
    description: str = ""
    exports: List[str] = field(default_factory=list)       # 对外暴露的符号
    depends_on: List[str] = field(default_factory=list)     # 依赖的其他模块
    depended_by: List[str] = field(default_factory=list)    # 被哪些模块依赖


class DomainMap:
    """领域映射 — 定义所有模块的领域归属和分层"""

    def __init__(self):
        self._modules: Dict[str, ModuleDef] = {}
        self._define_all()

    def _define_all(self):
        """定义所有模块的领域归属"""

        # ═══ Verification Context ═══
        ctx = BoundedContext.VERIFICATION
        self._add(ModuleDef("pipeline", "src/core/execution.py", ctx, ArchitectureLayer.SERVICE,
                            "流水线执行编排", exports=["PipelineExecutionService"],
                            depends_on=["registry", "engines"]))
        self._add(ModuleDef("regression", "src/agents/regress", ctx, ArchitectureLayer.SERVICE,
                            "失败聚类", exports=["RegressAgent"]))
        self._add(ModuleDef("coverage", "src/agents/cover", ctx, ArchitectureLayer.SERVICE,
                            "覆盖率缺口解释", exports=["CoverAgent"]))
        self._add(ModuleDef("testcase", "src/tools/testcase_tools", ctx, ArchitectureLayer.TOOL,
                            "测试用例生成", exports=["TestCaseGenerator"]))
        self._add(ModuleDef("engines", "src/core/engines.py", ctx, ArchitectureLayer.DOMAIN,
                            "差异化引擎", exports=["VPlanGenerator","CoverageDrivenRegressor","DebugCopilot","RegressionTriage"]))

        # ═══ Signoff Context ═══
        ctx = BoundedContext.SIGNOFF
        self._add(ModuleDef("signoff_api", "src/web/api.py (signoff routes)", ctx, ArchitectureLayer.INTERFACE,
                            "签核 API 端点"))
        self._add(ModuleDef("signoff_repo", "src/database/repository.py (signoff)", ctx, ArchitectureLayer.REPOSITORY,
                            "签核数据访问", exports=["create_signoff","list_signoffs","get_signoff_by_id","update_signoff"]))
        self._add(ModuleDef("manifest", "src/core/manifest.py", ctx, ArchitectureLayer.DOMAIN,
                            "证据清单", exports=["build_manifest","ManifestBuilder","export_evidence_package","hash_json"]))
        self._add(ModuleDef("evidence", "src/core/evidence.py", ctx, ArchitectureLayer.DOMAIN,
                            "证据链", exports=["EvidenceChain"]))
        self._add(ModuleDef("approval", "src/infra/approval_workflow.py", ctx, ArchitectureLayer.DOMAIN,
                            "审批工作流", exports=["ApprovalWorkflow","ReviewAction","ReviewStatus"]))
        self._add(ModuleDef("signoff_events", "src/database/models.py (SignoffEvent)", ctx, ArchitectureLayer.DOMAIN,
                            "签核事件实体"))

        # ═══ Document Context ═══
        ctx = BoundedContext.DOCUMENT
        self._add(ModuleDef("doc_api", "src/web/api.py (doc routes)", ctx, ArchitectureLayer.INTERFACE,
                            "文档 API 端点"))
        self._add(ModuleDef("doc_repo", "src/database/repository.py (docs)", ctx, ArchitectureLayer.REPOSITORY,
                            "文档数据访问"))
        self._add(ModuleDef("doc_serializer", "src/core/doc_serializer.py", ctx, ArchitectureLayer.DOMAIN,
                            "文档序列化"))
        self._add(ModuleDef("doc_models", "src/database/models.py (DocDocument/DocVersion/DocRequirement)", ctx, ArchitectureLayer.DOMAIN,
                            "文档实体"))

        # ═══ Design Context ═══
        ctx = BoundedContext.DESIGN
        self._add(ModuleDef("design_api", "src/web/api.py (design routes)", ctx, ArchitectureLayer.INTERFACE,
                            "设计 API 端点"))
        self._add(ModuleDef("design_mapper", "src/core/design_mapper.py", ctx, ArchitectureLayer.DOMAIN,
                            "设计映射"))
        self._add(ModuleDef("design_models", "src/database/models.py (DesignModule/Feature/Map)", ctx, ArchitectureLayer.DOMAIN,
                            "设计实体"))
        self._add(ModuleDef("design", "src/agents/design", ctx, ArchitectureLayer.SERVICE,
                            "模块分解器 Agent"))

        # ═══ Platform Context ═══
        ctx = BoundedContext.PLATFORM
        self._add(ModuleDef("auth", "src/core/auth.py", ctx, ArchitectureLayer.INFRA,
                            "认证授权", exports=["hash_password","verify_password","create_token","get_current_user","require_auth"]))
        self._add(ModuleDef("rbac", "src/infra/rbac.py", ctx, ArchitectureLayer.INFRA,
                            "RBAC 权限", exports=["Permission","Role","RBACChecker"]))
        self._add(ModuleDef("rbac_web", "src/infra/rbac_web.py", ctx, ArchitectureLayer.INFRA,
                            "RBAC Web 桥接", exports=["PermissionChecker","ProcessPermission"]))
        self._add(ModuleDef("audit", "src/database/models.py (AuditLog) + repository.py", ctx, ArchitectureLayer.INFRA,
                            "审计日志"))
        self._add(ModuleDef("users", "src/database/repository.py (users)", ctx, ArchitectureLayer.REPOSITORY,
                            "用户数据访问"))
        self._add(ModuleDef("projects", "src/database/repository.py (projects)", ctx, ArchitectureLayer.REPOSITORY,
                            "项目数据访问"))
        self._add(ModuleDef("template", "src/infra/template_system.py", ctx, ArchitectureLayer.INFRA,
                            "模板系统", exports=["TemplateRegistry","TemplateInstantiator"]))
        self._add(ModuleDef("data_governance", "src/infra/data_governance.py", ctx, ArchitectureLayer.INFRA,
                            "数据治理", exports=["DataDictionary","ModelValidator","ConsistencyChecker"]))
        self._add(ModuleDef("event_bus", "src/infra/event_bus.py", ctx, ArchitectureLayer.INFRA,
                            "事件总线", exports=["EventBus","StandardEvent","WorkflowHandlers"]))
        self._add(ModuleDef("observability", "src/infra/observability.py", ctx, ArchitectureLayer.INFRA,
                            "可观测性", exports=["MetricsCollector","SlowQueryDetector","HealthChecker"]))
        self._add(ModuleDef("security", "src/infra/security.py", ctx, ArchitectureLayer.INFRA,
                            "安全", exports=["AuditChain","RateLimiter","InputSanitizer","KeyManager"]))
        self._add(ModuleDef("health_monitor", "src/infra/health_monitor.py", ctx, ArchitectureLayer.INFRA,
                            "健康监控", exports=["HealthMonitor","StuckDetector","GapScanner"]))
        self._add(ModuleDef("collaboration", "src/infra/collaboration.py", ctx, ArchitectureLayer.INFRA,
                            "协作", exports=["ReviewGateManager","CommentSystem","TaskManager"]))
        self._add(ModuleDef("project_isolation", "src/infra/project_isolation.py", ctx, ArchitectureLayer.INFRA,
                            "项目隔离"))

        # ═══ Intelligence Context ═══
        ctx = BoundedContext.INTELLIGENCE
        self._add(ModuleDef("debug_copilot", "src/agents/debug", ctx, ArchitectureLayer.SERVICE,
                            "根因追踪", exports=["DebugAgent"]))
        self._add(ModuleDef("auto_fix", "src/infra/auto_fix_engine.py", ctx, ArchitectureLayer.SERVICE,
                            "自动修复引擎", exports=["AutoFixEngine","FailureAnalyzer","FixRecommender"]))
        self._add(ModuleDef("business_glossary", "src/infra/business_glossary.py", ctx, ArchitectureLayer.DOMAIN,
                            "业务术语", exports=["BusinessGlossary","DecisionTracer"]))
        self._add(ModuleDef("impact_analyzer", "src/infra/impact_analyzer.py", ctx, ArchitectureLayer.SERVICE,
                            "影响分析", exports=["ImpactAnalyzer","RuleRegistry","ChangeApprovalChain"]))
        self._add(ModuleDef("vplan", "src/infra/vplan_manager.py", ctx, ArchitectureLayer.DOMAIN,
                            "验证计划管理", exports=["VPlanManager"]))

    def _add(self, mod: ModuleDef):
        self._modules[mod.name] = mod

    def get_module(self, name: str) -> Optional[ModuleDef]:
        return self._modules.get(name)

    def get_modules_by_context(self, context: BoundedContext) -> List[ModuleDef]:
        return [m for m in self._modules.values() if m.context == context]

    def get_modules_by_layer(self, layer: ArchitectureLayer) -> List[ModuleDef]:
        return [m for m in self._modules.values() if m.layer == layer]

    def get_all_modules(self) -> List[ModuleDef]:
        return list(self._modules.values())

    def to_markdown(self) -> str:
        """导出架构文档"""
        lines = ["# SignOffAI 架构文档", "", "## 领域边界", ""]
        for ctx in BoundedContext:
            lines.append(f"### {ctx.value.upper()}")
            mods = self.get_modules_by_context(ctx)
            for layer in ArchitectureLayer:
                layer_mods = [m for m in mods if m.layer == layer]
                if layer_mods:
                    lines.append(f"**{layer.value}:** " + ", ".join(m.name for m in layer_mods))
            lines.append("")
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
# 2. 分层基类
# ═══════════════════════════════════════════════════════════

class BaseRepository(ABC):
    """仓库层基类 — 纯数据访问，禁止包含业务逻辑"""

    def __init__(self):
        self._access_count = 0

    @property
    def access_count(self) -> int:
        return self._access_count

    def _increment_access(self):
        self._access_count += 1


class BaseService(ABC):
    """服务层基类 — 业务编排，可调用 Repository 和 Domain"""

    def __init__(self):
        self._call_count = 0

    @property
    def call_count(self) -> int:
        return self._call_count

    def _increment_call(self):
        self._call_count += 1


class BaseDomainEntity(ABC):
    """领域实体基类"""

    @abstractmethod
    def to_dict(self) -> dict:
        """序列化为字典"""
        ...

    @classmethod
    @abstractmethod
    def from_dict(cls, data: dict) -> "BaseDomainEntity":
        """从字典反序列化"""
        ...

    def validate(self) -> Tuple[bool, List[str]]:
        """验证实体完整性。返回 (是否有效, 问题列表)"""
        return True, []


class BaseValueObject:
    """值对象基类 — 不可变，按值比较"""

    def __eq__(self, other):
        if not isinstance(other, self.__class__):
            return False
        return self.__dict__ == other.__dict__

    def __hash__(self):
        return hash(tuple(sorted(self.__dict__.items())))


# ═══════════════════════════════════════════════════════════
# 3. 接口契约
# ═══════════════════════════════════════════════════════════

@dataclass
class ApiContract:
    """API 端点契约"""
    method: str           # GET / POST / PUT / DELETE
    path: str             # /api/signoffs/{sid}/approve
    description: str
    context: BoundedContext
    auth_required: bool = True
    rate_limit_key: str = ""
    request_schema: dict = field(default_factory=dict)
    response_schema: dict = field(default_factory=dict)


class ApiContractRegistry:
    """API 契约注册中心 — 确保所有端点在领域映射中有归属"""

    def __init__(self, domain_map: DomainMap):
        self.domain_map = domain_map
        self._contracts: List[ApiContract] = []

    def register(self, contract: ApiContract):
        self._contracts.append(contract)

    def get_contracts_by_context(self, context: BoundedContext) -> List[ApiContract]:
        return [c for c in self._contracts if c.context == context]

    def find_unmapped_endpoints(self) -> List[str]:
        """发现不在领域映射中的端点"""
        mapped_paths = {m.path for m in self.domain_map.get_all_modules()}
        unmapped = []
        for c in self._contracts:
            if not any(c.path.startswith(mp) for mp in mapped_paths if mp):
                unmapped.append(c.path)
        return unmapped

    def validate(self) -> Tuple[bool, List[str]]:
        """验证所有 API 端点是否符合架构约束"""
        issues = []
        for c in self._contracts:
            # 检查是否有归属领域
            if not c.context:
                issues.append(f"端点 {c.method} {c.path} 未分配 BoundedContext")
            # 检查路径命名规范
            if not re.match(r'^/api/[a-z][a-z0-9/-]*$', c.path):
                issues.append(f"端点路径不符合规范: {c.path}")
        return len(issues) == 0, issues


# ═══════════════════════════════════════════════════════════
# 4. 架构校验器
# ═══════════════════════════════════════════════════════════

@dataclass
class ArchitectureViolation:
    """架构违规"""
    module: str
    violation: str
    severity: str  # error / warning
    fix: str = ""


class ArchitectureValidator:
    """架构一致性校验器 — 运行时可检查架构约束"""

    def __init__(self, domain_map: DomainMap = None):
        self.domain_map = domain_map or DomainMap()

    def check_layer_isolation(self) -> List[ArchitectureViolation]:
        """检查分层隔离 — repository 不能包含业务逻辑"""
        violations = []
        # 检查 repository.py 是否只做数据访问
        repo_file = Path("src/database/repository.py")
        if repo_file.exists():
            content = repo_file.read_text(encoding="utf-8")
            # 检查是否有业务逻辑模式（不应该在 repository 中出现）
            business_patterns = [
                (r'import.*event_bus', 'Repository 不应直接使用 EventBus'),
                (r'import.*approval_workflow', 'Repository 不应直接使用审批工作流'),
                (r'from src\.core\.engines', 'Repository 不应引用引擎层'),
            ]
            for pattern, msg in business_patterns:
                if re.search(pattern, content):
                    violations.append(ArchitectureViolation("repository", msg, "warning",
                                         "将业务逻辑移到 Service 层"))
        return violations

    def check_domain_boundaries(self) -> List[ArchitectureViolation]:
        """检查领域边界 — 不应跨领域直接引用内部实现"""
        violations = []
        infra_files = list(Path("src/infra").glob("*.py"))
        for f in infra_files:
            content = f.read_text(encoding="utf-8")
            # Infra 层不应直接访问数据库模型
            if re.search(r'from src\.database\.models import', content):
                violations.append(ArchitectureViolation(
                    f.name, f"Infra 层直接引用数据库模型，应通过 Repository 层",
                    "error", f"将数据访问移到 src/database/repository.py"))
        return violations

    def check_naming_convention(self) -> List[ArchitectureViolation]:
        """检查命名规范"""
        violations = []
        # API 路径规范
        api_file = Path("src/web/api.py")
        if api_file.exists():
            content = api_file.read_text(encoding="utf-8")
            paths = re.findall(r'@app\.\w+\("([^"]+)"\)', content)
            for p in paths:
                if not p.startswith('/api/') and p not in ('/', '/test-login'):
                    violations.append(ArchitectureViolation(
                        "api.py", f"API 路径不以 /api/ 开头: {p}", "warning",
                        f"改为 /api{p} 或确认为特殊路由"))
        return violations

    def check_all(self) -> List[ArchitectureViolation]:
        violations = []
        violations.extend(self.check_layer_isolation())
        violations.extend(self.check_domain_boundaries())
        violations.extend(self.check_naming_convention())
        return violations


# ═══════════════════════════════════════════════════════════
# 全局
# ═══════════════════════════════════════════════════════════

_domain_map: Optional[DomainMap] = None


def get_domain_map() -> DomainMap:
    global _domain_map
    if _domain_map is None:
        _domain_map = DomainMap()
    return _domain_map
