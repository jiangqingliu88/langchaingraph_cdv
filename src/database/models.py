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
    run_id = Column(String(64), unique=True, nullable=False)  # 服务端生成，供 SSE/API 追踪
    workflow = Column(String(100))
    spec_file = Column(String(500))
    state = Column(String(30), default='running')  # running / completed / completed_with_errors / cancelled
    total_phases = Column(Integer)
    passed = Column(Integer)
    degraded = Column(Integer)
    total_time = Column(Float)
    phases_json = Column(JSON)        # 每个阶段的 [{name, status, time, score, ...}]
    results = Column(JSON)            # {"spec":"passed", ...}
    started_at = Column(DateTime, default=datetime.now)
    completed_at = Column(DateTime, nullable=True)
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
    """审计日志"""
    __tablename__ = 'audit_logs'
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=True)
    username = Column(String(50))
    action = Column(String(100))       # pipeline_run / testcase_create / signoff_approve / ...
    resource = Column(String(200))     # project_id / test_name / ...
    detail = Column(Text, default='')
    ip_address = Column(String(50))
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
    """签核记录"""
    __tablename__ = 'signoffs'
    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey('projects.id'))
    title = Column(String(300))
    report_type = Column(String(50))   # tapeout / milestone / coverage
    status = Column(String(20), default='draft')  # draft / pending / approved / rejected
    summary_json = Column(JSON)        # 报告摘要数据
    requester_id = Column(Integer, ForeignKey('users.id'))
    approver_id = Column(Integer, ForeignKey('users.id'), nullable=True)
    comment = Column(Text, default='')
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now)

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

class DocRelation(Base):
    """文档间关系"""
    __tablename__ = 'doc_relations'
    id = Column(Integer, primary_key=True, autoincrement=True)
    source_id = Column(Integer, ForeignKey('doc_documents.id'), nullable=False)
    target_id = Column(Integer, ForeignKey('doc_documents.id'), nullable=False)
    relation_type = Column(String(30))                         # parent / child / implements / references
    description = Column(String(500))
    created_at = Column(DateTime, default=datetime.now)
