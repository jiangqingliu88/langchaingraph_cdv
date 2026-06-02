from sqlalchemy import select, desc
from src.database.connection import get_session
from src.database.models import TaskRecord, PipelineRun
async def save_task(role, ttype, inp, out, status, error=None, extime=0, bypass=False):
    s = await get_session()
    r = TaskRecord(agent_role=role, task_type=ttype, input_text=str(inp)[:5000], output_text=str(out)[:10000], status=status, error_msg=error, execution_time=extime, bypass=1 if bypass else 0)
    s.add(r)
    await s.commit()
    await s.close()
async def save_pipeline_run(wf, spec, total, passed, degraded, ttime, results):
    s = await get_session()
    r = PipelineRun(workflow=wf, spec_file=spec, total_phases=total, passed=passed, degraded=degraded, total_time=ttime, results=results)
    s.add(r)
    await s.commit()
    await s.close()
async def get_recent_tasks(limit=20):
    s = await get_session()
    result = await s.execute(select(TaskRecord).order_by(desc(TaskRecord.created_at)).limit(limit))
    tasks = result.scalars().all()
    await s.close()
    return [{'agent': t.agent_role, 'status': t.status, 'time': t.execution_time, 'created': str(t.created_at)} for t in tasks]
async def get_recent_pipelines(limit=10):
    s = await get_session()
    result = await s.execute(select(PipelineRun).order_by(desc(PipelineRun.created_at)).limit(limit))
    runs = result.scalars().all()
    await s.close()
    return [{'workflow': r.workflow, 'passed': r.passed, 'total': r.total_phases, 'time': r.total_time, 'created': str(r.created_at)} for r in runs]
