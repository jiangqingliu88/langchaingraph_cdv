"""
数据库模型 - 使用SQLAlchemy ORM
"""
from datetime import datetime
from typing import Optional
from sqlalchemy import (
    Column, Integer, String, Text, Float, DateTime, 
    ForeignKey, JSON, Enum as SAEnum
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
import enum

Base = declarative_base()

class AgentRoleEnum(str, enum.Enum):
    ORCHESTRATOR = "verification_orchestrator"
    SPEC_PLANNER = "spec_and_test_planner"
    ARCHITECT = "verification_architect"
    SEQUENCE_ENGINEER = "sequence_engineer"
    ASSERTION_ENGINEER = "assertion_engineer"
    COVERAGE_MANAGER = "coverage_manager"
    REGRESSION_MANAGER = "regression_manager"
    DEBUG_ENGINEER = "debug_engineer"
    QUALITY_ASSURANCE = "quality_assurance"

class TaskStatusEnum(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"

class VerificationProject(Base):
    """验证项目"""
    __tablename__ = "verification_projects"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    spec_document = Column(Text)
    status = Column(String(50), default="active")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    
    # 关系
    tasks = relationship("VerificationTask", back_populates="project")
    sessions = relationship("VerificationSession", back_populates="project")

class VerificationTask(Base):
    """验证任务"""
    __tablename__ = "verification_tasks"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("verification_projects.id"))
    title = Column(String(255), nullable=False)
    description = Column(Text)
    agent_role = Column(String(50))
    status = Column(String(50), default=TaskStatusEnum.PENDING.value)
    priority = Column(Integer, default=1)
    input_data = Column(JSON)
    output_data = Column(JSON)
    error_message = Column(Text)
    execution_time = Column(Float)
    tokens_used = Column(Integer)
    created_at = Column(DateTime, default=datetime.now)
    completed_at = Column(DateTime)
    
    # 关系
    project = relationship("VerificationProject", back_populates="tasks")

class VerificationSession(Base):
    """验证会话"""
    __tablename__ = "verification_sessions"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(100), unique=True, nullable=False)
    project_id = Column(Integer, ForeignKey("verification_projects.id"))
    workflow_name = Column(String(100))
    status = Column(String(50))
    started_at = Column(DateTime, default=datetime.now)
    completed_at = Column(DateTime)
    results = Column(JSON)
    
    # 关系
    project = relationship("VerificationProject", back_populates="sessions")
    messages = relationship("AgentMessage", back_populates="session")

class AgentMessage(Base):
    """Agent消息记录"""
    __tablename__ = "agent_messages"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(Integer, ForeignKey("verification_sessions.id"))
    sender = Column(String(100))
    receiver = Column(String(100))
    message_type = Column(String(50))
    content = Column(JSON)
    timestamp = Column(DateTime, default=datetime.now)
    
    # 关系
    session = relationship("VerificationSession", back_populates="messages")

class CoverageData(Base):
    """覆盖率数据"""
    __tablename__ = "coverage_data"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("verification_projects.id"))
    metric_name = Column(String(100))
    total_bins = Column(Integer)
    hit_bins = Column(Integer)
    percentage = Column(Float)
    target = Column(Float)
    collected_at = Column(DateTime, default=datetime.now)