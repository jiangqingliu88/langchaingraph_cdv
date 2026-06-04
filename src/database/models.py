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
    bypass = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.now)

class PipelineRun(Base):
    __tablename__ = 'pipeline_runs'
    id = Column(Integer, primary_key=True)
    workflow = Column(String(100))
    spec_file = Column(String(500))
    total_phases = Column(Integer)
    passed = Column(Integer)
    degraded = Column(Integer)
    total_time = Column(Float)
    results = Column(JSON)
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
