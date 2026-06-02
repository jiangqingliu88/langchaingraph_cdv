# ==================== 1. 创建 models.py ====================
with open('src/database/models.py', 'w', encoding='utf-8') as f:
    f.write('''"""Database models"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, Float, DateTime, JSON
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class TaskRecord(Base):
    __tablename__ = "task_records"
    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_role = Column(String(100))
    task_type = Column(String(100))
    input_text = Column(Text)
    output_text = Column(Text)
    status = Column(String(20))
    error_msg = Column(Text, nullable=True)
    execution_time = Column(Float, default=0.0)
    bypass = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.now)

class PipelineRun(Base):
    __tablename__ = "pipeline_runs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    workflow = Column(String(100))
    spec_file = Column(String(500))
    total_phases = Column(Integer)
    passed = Column(Integer)
    degraded = Column(Integer)
    total_time = Column(Float)
    results = Column(JSON)
    created_at = Column(DateTime, default=datetime.now)
''')
print('models.py created')

# ==================== 2. 创建 connection.py ====================
with open('src/database/connection.py', 'w', encoding='utf-8') as f:
    f.write('''"""Database connection"""
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from config.settings import Settings

_engine = None
_session_factory = None

async def init_db():
    global _engine, _session_factory
    if _engine is None:
        settings = Settings.get_instance()
        _engine = create_async_engine(settings.database.url, echo=False)
        _session_factory = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)
        async with _engine.begin() as conn:
            from src.database.models import Base
            await conn.run_sync(Base.metadata.create_all)

async def get_session() -> AsyncSession:
    if _session_factory is None:
        await init_db()
    return _session_factory()
''')
print('connection.py created')

# ==================== 3. 创建 repository.py ====================
with open('src/database/repository.py', 'w', encoding='utf-8') as f:
    f.write('''"""Data repository"""
import json
from datetime import datetime
from sqlalchemy import select, desc
from src.database.connection import get_session
from src.database.models import TaskRecord, PipelineRun

async def save_task(agent_role, task_type, input_text, output_text, status, error=None, exec_time=0, bypass=False):
    session = await get_session()
    record = TaskRecord(
        agent_role=agent_role,
        task_type=task_type,
        input_text=input_text[:5000],
        output_text=str(output_text)[:10000],
        status=status,
        error_msg=error,
        execution_time=exec_time,
        bypass=1 if bypass else 0,
    )
    session.add(record)
    await session.commit()
    await session.close()
    return record.id

async def save_pipeline_run(workflow, spec_file, total, passed, degraded, total_time, results):
    session = await get_session()
    record = PipelineRun(
        workflow=workflow,
        spec_file=spec_file,
        total_phases=total,
        passed=passed,
        degraded=degraded,
        total_time=total_time,
        results=results,
    )
    session.add(record)
    await session.commit()
    await session.close()
    return record.id

async def get_recent_tasks(limit=20):
    session = await get_session()
    result = await session.execute(
        select(TaskRecord).order_by(desc(TaskRecord.created_at)).limit(limit)
    )
    tasks = result.scalars().all()
    await session.close()
    return [
        {"agent": t.agent_role, "status": t.status, "time": t.execution_time, "created": str(t.created_at)}
        for t in tasks
    ]

async def get_recent_pipelines(limit=10):
    session = await get_session()
    result = await session.execute(
        select(PipelineRun).order_by(desc(PipelineRun.created_at)).limit(limit)
    )
    runs = result.scalars().all()
    await session.close()
    return [
        {"workflow": r.workflow, "passed": r.passed, "total": r.total_phases, "time": r.total_time, "created": str(r.created_at)}
        for r in runs
    ]
''')
print('repository.py created')
