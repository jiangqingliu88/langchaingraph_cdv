from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, Float, DateTime, JSON
from sqlalchemy.orm import declarative_base
Base = declarative_base()
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
