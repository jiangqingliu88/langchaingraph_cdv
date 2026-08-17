from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, Float, DateTime, JSON, Boolean, ForeignKey
from sqlalchemy.orm import declarative_base, relationship
Base = declarative_base()

# ── 原有 ──

class TaskRecord(Base):
    __tablename__ = 'task_records'
    id = Column(Integer, primary_key=True)
    agent_role = Column(String(100))
    task_type = Column(String(100))
    input_text = Column(Text)
    output_text = Column(Text)
    status = Column(String(20))
    error_msg = Column(Text, nullable=True)
    execution_time = Column(Float, default=0)
    created_at = Column(DateTime, default=datetime.now)

class PipelineRun(Base):
    __tablename__ = 'pipeline_runs'
    id = Column(Integer, primary_key=True)
    run_id = Column(String(64), unique=True, nullable=False, index=True)  # 服务端生成，供 SSE/API 追踪
    project_id = Column(Integer, ForeignKey('projects.id'), nullable=True)
    workflow = Column(String(100))
    spec_file = Column(String(500))
    state = Column(String(30), default='running')  # running / completed / completed_with_errors / cancelled
    total_phases = Column(Integer)
    passed = Column(Integer)
    degraded = Column(Integer)
    failed = Column(Integer, default=0)
    total_time = Column(Float)
    phases_json = Column(JSON)        # 每个阶段的 [{name, status, time, score, ...}]
    results = Column(JSON)            # {"spec":"passed", ...}
    coverage_line_pct = Column(Float, default=0.0)
    coverage_branch_pct = Column(Float, default=0.0)
    coverage_toggle_pct = Column(Float, default=0.0)
    evidence_hash = Column(String(64), default='')
    manifest_hash = Column(String(64), default='')
    started_at = Column(DateTime, default=datetime.now)
    completed_at = Column(DateTime, nullable=True)
    is_archived = Column(Boolean, default=False)               # 已归档
    created_at = Column(DateTime, default=datetime.now)

# ── 企业级模型 ──

class User(Base):
    """用户"""
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), unique=True, nullable=False)
    password_hash = Column(String(256), nullable=False)
    display_name = Column(String(100))
    email = Column(String(200))
    role = Column(String(30), default='engineer')  # admin / verification_manager / senior_engineer / engineer / viewer
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)
    last_login = Column(DateTime, nullable=True)

class Project(Base):
    """项目"""
    __tablename__ = 'projects'
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, default='')
    owner_id = Column(Integer, ForeignKey('users.id'))
    status = Column(String(20), default='active')  # active / archived / deleted
    env_dir = Column(String(500), default='')
    testcase_dir = Column(String(500), default='')
    regression_dir = Column(String(500), default='')
    deleted_at = Column(DateTime, nullable=True)              # 软删除时间
    created_at = Column(DateTime, default=datetime.now)

class ProjectMember(Base):
    """项目成员"""
    __tablename__ = 'project_members'
    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey('projects.id'), nullable=False)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    role = Column(String(20), default='member')  # owner / admin / member / viewer
    joined_at = Column(DateTime, default=datetime.now)

class AuditLog(Base):
    """审计日志 — 企业级可追溯，带角色上下文和越权检测"""
    __tablename__ = 'audit_logs'
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=True)
    username = Column(String(50))
    role = Column(String(30), default='')      # 操作时的角色
    action = Column(String(100))               # login_success / pipeline_run / signoff_approve / evidence_export / access_denied
    resource_type = Column(String(50), default='')  # project / signoff / pipeline / evidence / auth / doc / user
    resource = Column(String(200))             # resource_id
    target_id = Column(String(200), default='')# 更明确的目标对象 ID
    detail = Column(Text, default='')
    before_state = Column(Text, default='')    # 变更前状态 (JSON)
    after_state = Column(Text, default='')     # 变更后状态 (JSON)
    access_result = Column(String(20), default='success')  # success / denied / error
    is_privileged_action = Column(Boolean, default=False)  # 是否为敏感操作
    ip_address = Column(String(50))
    user_agent = Column(String(300), default='')
    prev_hash = Column(String(64), default='')          # 前一条记录的链哈希
    chain_hash = Column(String(64), default='')         # 当前记录的链哈希
    chain_index = Column(Integer, default=0)            # 链序号
    created_at = Column(DateTime, default=datetime.now)

class KnowledgeEntry(Base):
    """知识库条目"""
    __tablename__ = 'knowledge_entries'
    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(300), nullable=False)
    category = Column(String(50))      # protocol / uvm_pattern / bug_case / best_practice
    tags = Column(String(500))         # comma-separated
    content = Column(Text, default='')
    author_id = Column(Integer, ForeignKey('users.id'))
    version = Column(String(20), default='1.0')
    usage_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now)

class Signoff(Base):
    """签核记录 — 证据绑定，不可篡改"""
    __tablename__ = 'signoffs'
    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey('projects.id'))
    title = Column(String(300))
    report_type = Column(String(50))   # tapeout / milestone / coverage
    status = Column(String(20), default='draft')  # draft / pending / approved / rejected
    summary_json = Column(JSON)        # 报告摘要数据
    evidence_package_hash = Column(String(64), default='')  # 绑定的证据包 hash
    manifest_hash = Column(String(64), default='')          # 绑定的 manifest hash
    run_id = Column(String(64), default='')                 # 关联的流水线 run_id
    requester_id = Column(Integer, ForeignKey('users.id'))
    approver_id = Column(Integer, ForeignKey('users.id'), nullable=True)
    approved_by_name = Column(String(100), default='')      # 审批人用户名（冗余便于查询）
    approved_at = Column(DateTime, nullable=True)           # 审批时间
    reject_reason = Column(Text, default='')                # 驳回理由
    comment = Column(Text, default='')
    is_deleted = Column(Boolean, default=False)             # 软删除
    deleted_at = Column(DateTime, nullable=True)             # 软删除时间
    is_archived = Column(Boolean, default=False)             # 已归档
    version = Column(Integer, default=1)                     # 乐观锁版本号
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now)

    __table_args__ = (
        {'sqlite_autoincrement': True},
    )


class SignoffEvent(Base):
    """签核事件流 — 审批历史、状态变更、评论"""
    __tablename__ = 'signoff_events'
    id = Column(Integer, primary_key=True, autoincrement=True)
    signoff_id = Column(Integer, ForeignKey('signoffs.id'), nullable=False, index=True)
    event_type = Column(String(30), nullable=False)  # submitted / approved / rejected / commented / reopened / draft
    actor_id = Column(Integer, ForeignKey('users.id'), nullable=True)
    actor_name = Column(String(100), default='')
    actor_role = Column(String(30), default='')      # 执行动作时的角色
    comment = Column(Text, default='')
    before_status = Column(String(20), default='')   # 变更前状态
    after_status = Column(String(20), default='')    # 变更后状态
    evidence_hash = Column(String(64), default='')   # 动作关联的证据 hash
    created_at = Column(DateTime, default=datetime.now)

    __table_args__ = (
        {'sqlite_autoincrement': True},
    )


class Artifact(Base):
    """证据产物 — 每个可审计的产出文件或数据对象"""
    __tablename__ = 'artifacts'
    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey('projects.id'), nullable=True, index=True)
    run_id = Column(String(64), default='', index=True)     # 关联流水线 run
    signoff_id = Column(Integer, ForeignKey('signoffs.id'), nullable=True, index=True)
    artifact_type = Column(String(50), nullable=False)       # manifest / report / coverage / log / doc / testcase / evidence_package
    name = Column(String(300), nullable=False)
    path = Column(String(500), default='')
    content_hash = Column(String(64), default='')            # SHA256
    size_bytes = Column(Integer, default=0)
    metadata_json = Column(JSON, default={})
    created_at = Column(DateTime, default=datetime.now)

    __table_args__ = (
        {'sqlite_autoincrement': True},
    )


class EvidenceLink(Base):
    """证据关联 — 把 artifact 和业务对象绑定"""
    __tablename__ = 'evidence_links'
    id = Column(Integer, primary_key=True, autoincrement=True)
    artifact_id = Column(Integer, ForeignKey('artifacts.id'), nullable=False, index=True)
    object_type = Column(String(30), nullable=False)   # signoff / pipeline_run / doc_document / regression
    object_id = Column(Integer, nullable=False)
    relation_type = Column(String(30), default='attached_to')  # attached_to / generated_by / referenced_by / verifies
    created_at = Column(DateTime, default=datetime.now)

    __table_args__ = (
        {'sqlite_autoincrement': True},
    )

class RegressionRecord(Base):
    """回归记录"""
    __tablename__ = 'regression_records'
    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey('projects.id'), nullable=True)
    run_name = Column(String(200))
    status = Column(String(20))        # running / completed / failed
    pass_count = Column(Integer, default=0)
    fail_count = Column(Integer, default=0)
    skip_count = Column(Integer, default=0)
    total_count = Column(Integer, default=0)
    duration_seconds = Column(Float, default=0)
    results_json = Column(JSON)
    created_at = Column(DateTime, default=datetime.now)

# ── MD 文档生态模型 ──

class DocDocument(Base):
    """MD 规格文档"""
    __tablename__ = 'doc_documents'
    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey('projects.id'), nullable=True)
    path = Column(String(500), unique=True, nullable=False)   # 相对路径: "alu/alu_arith_spec.md"
    title = Column(String(300))                                # 从 # 标题提取
    content = Column(Text, default='')                         # 完整 Markdown 原文
    content_hash = Column(String(64))                          # SHA256，快速检测变更
    level = Column(String(20), default='module')               # chip / subsystem / module / unit
    status = Column(String(20), default='draft')               # draft / review / approved / deprecated
    author_id = Column(Integer, ForeignKey('users.id'))
    tags = Column(String(500))                                 # 逗号分隔
    metadata_json = Column(JSON, default={})                   # 扩展元数据
    view_count = Column(Integer, default=0)
    is_deleted = Column(Boolean, default=False)                # 软删除
    deleted_at = Column(DateTime, nullable=True)
    is_archived = Column(Boolean, default=False)               # 已归档
    version = Column(Integer, default=1)                       # 乐观锁版本号
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now)

class DocVersion(Base):
    """文档版本历史"""
    __tablename__ = 'doc_versions'
    id = Column(Integer, primary_key=True, autoincrement=True)
    document_id = Column(Integer, ForeignKey('doc_documents.id'), nullable=False)
    version = Column(String(20))                               # "1.0", "2.1"
    content = Column(Text)                                     # 该版本的完整内容快照
    content_hash = Column(String(64))
    change_summary = Column(String(500))
    author_id = Column(Integer, ForeignKey('users.id'))
    parent_version_id = Column(Integer, nullable=True)         # 回溯父版本
    is_restored = Column(Boolean, default=False)               # 是否为回退版本
    created_at = Column(DateTime, default=datetime.now)

class DocRequirement(Base):
    """从 MD 文档中提取的需求条目"""
    __tablename__ = 'doc_requirements'
    id = Column(Integer, primary_key=True, autoincrement=True)
    document_id = Column(Integer, ForeignKey('doc_documents.id'), nullable=False)
    req_id = Column(String(100), nullable=False)               # "REQ_ALU_BT_001"
    description = Column(Text)                                 # 需求描述原文
    req_type = Column(String(30))                              # BT / UT / CHIP / PERF
    line_number = Column(Integer)                              # 在原文档中的行号
    is_covered = Column(Boolean, default=False)                # 是否有对应测试用例
    coverage_json = Column(JSON, default={})                   # 覆盖信息
    created_at = Column(DateTime, default=datetime.now)

# ═══════════════════════════════════════════════════════════
# 设计层三层映射模型 (需求 → 模块/功能点 → 测试点)
# ═══════════════════════════════════════════════════════════

class DesignModule(Base):
    """设计模块 — DesignAgent 输出"""
    __tablename__ = 'design_modules'
    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey('projects.id'), nullable=True)
    name = Column(String(255), nullable=False)
    parent_id = Column(Integer, nullable=True)
    description = Column(Text, default='')
    interfaces = Column(JSON, default=[])      # [{name, direction, width, protocol}]
    signals = Column(JSON, default=[])          # [{name, type, description}]
    rtl_file = Column(String(500), default='')
    rtl_hash = Column(String(64), default='')
    created_at = Column(DateTime, default=datetime.now)

class DesignFeature(Base):
    """功能点 — 对应 spec features"""
    __tablename__ = 'design_features'
    id = Column(Integer, primary_key=True, autoincrement=True)
    module_id = Column(Integer, ForeignKey('design_modules.id'), nullable=False)
    name = Column(String(255), nullable=False)
    level = Column(String(10), default='P0')
    description = Column(Text, default='')
    keywords = Column(String(500), default='')
    spec_feature_ref = Column(String(100), default='')
    created_at = Column(DateTime, default=datetime.now)

class ReqFeatureMap(Base):
    """需求→功能点映射"""
    __tablename__ = 'req_feature_map'
    id = Column(Integer, primary_key=True, autoincrement=True)
    req_id = Column(String(50), nullable=False)
    feature_id = Column(Integer, ForeignKey('design_features.id'), nullable=False)
    mapping_type = Column(String(20), default='DIRECT')  # DIRECT / INFERRED / MANUAL
    confidence = Column(Float, default=1.0)
    mapped_by = Column(String(50), default='auto')
    created_at = Column(DateTime, default=datetime.now)

class FeatureTestpointMap(Base):
    """功能点→测试点映射"""
    __tablename__ = 'feature_testpoint_map'
    id = Column(Integer, primary_key=True, autoincrement=True)
    feature_id = Column(Integer, ForeignKey('design_features.id'), nullable=False)
    testpoint_id = Column(String(50), nullable=False)
    mapping_type = Column(String(20), default='DIRECT')
    created_at = Column(DateTime, default=datetime.now)

# ═══════════════════════════════════════════════════════════
# V2 Knowledge Graph 运行时语义模型（bin 命中 / bug / fix）
# 设计时子图在设计层三层映射模型；这三张表存运行时语义，跨 run 沉淀
# ═══════════════════════════════════════════════════════════

class CoverageBinRecord(Base):
    """覆盖率 bin 命中记录 — 每个 bin 的最新命中状态（跨 run 跟踪进度）"""
    __tablename__ = 'coverage_bin_records'
    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey('projects.id'), nullable=True)
    run_id = Column(String(64), default='', index=True)     # 最近一次写入的 run
    name = Column(String(255), nullable=False, index=True)   # bin 名（如 RX_DATA / overflow_corner）
    metric = Column(String(50), default='')                  # toggle / line / branch / register
    signal = Column(String(255), default='')                 # 关联信号
    module = Column(String(255), default='')                 # 关联模块（协议）
    hit = Column(Boolean, default=False)                     # 最近一次是否命中
    misses = Column(Integer, default=0)                      # 未命中次数
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    __table_args__ = (
        {'sqlite_autoincrement': True},
    )


class VerificationBug(Base):
    """验证缺陷 — 关联信号/功能，供图做 bug 溯源"""
    __tablename__ = 'verification_bugs'
    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey('projects.id'), nullable=True)
    bug_id = Column(String(100), nullable=False, index=True)
    description = Column(Text, default='')
    affected_signal = Column(String(255), default='')
    affected_feature = Column(String(255), default='')
    status = Column(String(20), default='open')              # open / fixed / closed
    severity = Column(String(10), default='P2')
    found_run_id = Column(String(64), default='')
    created_at = Column(DateTime, default=datetime.now)

    __table_args__ = (
        {'sqlite_autoincrement': True},
    )


class VerificationFix(Base):
    """验证修复 — bug 的修复记录"""
    __tablename__ = 'verification_fixes'
    id = Column(Integer, primary_key=True, autoincrement=True)
    bug_id = Column(String(100), nullable=False, index=True)
    fix_id = Column(String(100), nullable=False)
    description = Column(Text, default='')
    created_at = Column(DateTime, default=datetime.now)

    __table_args__ = (
        {'sqlite_autoincrement': True},
    )

class DocRelation(Base):
    """文档间关系"""
    __tablename__ = 'doc_relations'
    id = Column(Integer, primary_key=True, autoincrement=True)
    source_id = Column(Integer, ForeignKey('doc_documents.id'), nullable=False)
    target_id = Column(Integer, ForeignKey('doc_documents.id'), nullable=False)
    relation_type = Column(String(30))                         # parent / child / implements / references
    description = Column(String(500))
    created_at = Column(DateTime, default=datetime.now)

# ═══════════════════════════════════════════════════════════
# PPA Signoff 模型 (Power / Performance / Area)
# ═══════════════════════════════════════════════════════════

class PPAMetric(Base):
    """PPA 签核的量化指标 — 单条 target vs actual 对比"""
    __tablename__ = 'ppa_metrics'
    id = Column(Integer, primary_key=True, autoincrement=True)
    signoff_id = Column(Integer, ForeignKey('signoffs.id'), nullable=False, index=True)
    category = Column(String(20), nullable=False, index=True)   # power / performance / area
    metric_name = Column(String(100), nullable=False)           # total_power / dynamic_power / leakage_power / fmax / setup_worst / cell_area / gate_count / utilization
    target_value = Column(Float, default=0.0)                   # 目标值
    actual_value = Column(Float, default=0.0)                   # 实际值
    unit = Column(String(20), default='')                       # mW / MHz / GHz / mm² / gates / %
    pass_status = Column(String(20), default='pending')         # pass / fail / marginal / pending
    margin_pct = Column(Float, default=0.0)                     # 裕量百分比 ((actual-target)/target*100 或反向)
    source_file = Column(String(500), default='')               # 数据来源报告文件路径
    source_hash = Column(String(64), default='')                # 源文件 hash，防篡改
    notes = Column(Text, default='')
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now)

    __table_args__ = (
        {'sqlite_autoincrement': True},
    )


class PPACorner(Base):
    """PPA 多工艺角 (PVT corner) 分析 — 每个 corner 一条记录"""
    __tablename__ = 'ppa_corners'
    id = Column(Integer, primary_key=True, autoincrement=True)
    signoff_id = Column(Integer, ForeignKey('signoffs.id'), nullable=False, index=True)
    corner_name = Column(String(50), nullable=False)            # ss_0p99v_125c / ff_1p21v_m40c / tt_1p1v_25c
    pvt_desc = Column(String(100), default='')                  # PVT 组合可读描述
    total_power_mw = Column(Float, default=0.0)                 # 总功耗 (mW)
    dynamic_power_mw = Column(Float, default=0.0)               # 动态功耗 (mW)
    leakage_power_mw = Column(Float, default=0.0)               # 漏电功耗 (mW)
    fmax_mhz = Column(Float, default=0.0)                       # 最高频率 (MHz)
    setup_worst_ns = Column(Float, default=0.0)                 # 最差 setup 裕量 (ns)
    hold_worst_ns = Column(Float, default=0.0)                  # 最差 hold 裕量 (ns)
    area_mm2 = Column(Float, default=0.0)                       # 面积 (mm²)
    cell_count = Column(Integer, default=0)                     # 标准单元数量
    utilization_pct = Column(Float, default=0.0)                # 利用率 (%)
    extra_json = Column(JSON, default={})                       # 完整 corner 报告扩展数据
    created_at = Column(DateTime, default=datetime.now)

    __table_args__ = (
        {'sqlite_autoincrement': True},
    )


class PPAConstraint(Base):
    """PPA 约束与门限规则 — 可配置、可变更审批"""
    __tablename__ = 'ppa_constraints'
    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey('projects.id'), nullable=True, index=True)
    category = Column(String(20), nullable=False)               # power / performance / area
    metric_name = Column(String(100), nullable=False)           # total_power / fmax / cell_area 等
    constraint_type = Column(String(20), default='max')         # max(不超过) / min(不低于) / range(区间)
    threshold_value = Column(Float, default=0.0)               # 门限值
    unit = Column(String(20), default='')                       # mW / MHz / mm² / gates
    margin_required_pct = Column(Float, default=10.0)           # 要求的设计裕量 (%)
    severity = Column(String(10), default='P1')                 # P0(必须满足) / P1(建议满足) / P2(参考)
    is_active = Column(Boolean, default=True)                   # 是否启用
    description = Column(String(300), default='')
    created_by = Column(Integer, ForeignKey('users.id'), nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now)

    __table_args__ = (
        {'sqlite_autoincrement': True},
    )

# ═══════════════════════════════════════════════════════════
# 平台基础设施模型
# ═══════════════════════════════════════════════════════════

class SchemaVersion(Base):
    """数据库 schema 版本追踪 — 支持平滑迁移"""
    __tablename__ = 'schema_versions'
    id = Column(Integer, primary_key=True, autoincrement=True)
    version = Column(String(20), unique=True, nullable=False)
    description = Column(String(300))
    applied_at = Column(DateTime, default=datetime.now)
    checksum = Column(String(64), default='')

    __table_args__ = (
        {'sqlite_autoincrement': True},
    )


class Permission(Base):
    """动作级权限"""
    __tablename__ = 'permissions'
    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(50), unique=True, nullable=False)
    name = Column(String(100), nullable=False)
    resource_type = Column(String(30), default='')
    action = Column(String(30), default='')
    description = Column(String(200), default='')
    created_at = Column(DateTime, default=datetime.now)

    __table_args__ = (
        {'sqlite_autoincrement': True},
    )


class RolePermission(Base):
    """角色-权限关联"""
    __tablename__ = 'role_permissions'
    id = Column(Integer, primary_key=True, autoincrement=True)
    role = Column(String(30), nullable=False, index=True)
    permission_id = Column(Integer, ForeignKey('permissions.id'), nullable=False)
    granted_by = Column(Integer, ForeignKey('users.id'), nullable=True)
    granted_at = Column(DateTime, default=datetime.now)

    __table_args__ = (
        {'sqlite_autoincrement': True},
    )


class WorkflowTrigger(Base):
    """事件驱动的自动化工作流触发规则"""
    __tablename__ = 'workflow_triggers'
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    event_type = Column(String(50), nullable=False)
    trigger_action = Column(String(50), nullable=False)
    target_type = Column(String(30), default='')
    target_value = Column(String(200), default='')
    is_active = Column(Boolean, default=True)
    config_json = Column(JSON, default={})
    created_by = Column(Integer, ForeignKey('users.id'), nullable=True)
    created_at = Column(DateTime, default=datetime.now)

    __table_args__ = (
        {'sqlite_autoincrement': True},
    )


class RoleWorkflowBinding(Base):
    """角色→工作流绑定 — 管理员可配置不同角色可用的工作流及默认工作流"""
    __tablename__ = 'role_workflow_bindings'
    id = Column(Integer, primary_key=True, autoincrement=True)
    role = Column(String(30), nullable=False, index=True)      # admin / verification_manager / senior_engineer / engineer / viewer
    workflow_name = Column(String(100), nullable=False)         # full_verification / quick_check / regression_only / ppa_analysis
    is_default = Column(Boolean, default=False)                 # 是否该角色的默认工作流
    is_active = Column(Boolean, default=True)                   # 是否启用
    description = Column(String(300), default='')
    created_by = Column(Integer, ForeignKey('users.id'), nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now)

    __table_args__ = (
        {'sqlite_autoincrement': True},
    )
