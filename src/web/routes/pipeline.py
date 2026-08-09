"""
Pipeline routes — 流水线执行 + SSE 流 + 历史
"""
from __future__ import annotations

import json, os, asyncio, uuid
from pathlib import Path
from datetime import datetime

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from src.core.auth import require_auth, get_current_user
from src.core.execution import PipelineExecutionService

router = APIRouter(prefix="/api", tags=["pipeline"])

WORKSPACE_ROOT = Path(os.environ.get("IC_VERIFY_WORKSPACE", Path.cwd())).resolve()
SPECS_DIR = (WORKSPACE_ROOT / "specs").resolve()
OUTPUT_ROOT = (WORKSPACE_ROOT / "output").resolve()
MAX_DOCUMENT_BYTES = 2 * 1024 * 1024


def _resolve_spec_path(value: str) -> Path:
    path = Path(value)
    if path.parts and path.parts[0].lower() == "specs":
        path = Path(*path.parts[1:])
    candidate = Path(value)
    if candidate.is_absolute():
        raise HTTPException(status_code=400, detail="absolute paths are not allowed")
    resolved = (SPECS_DIR / path).resolve()
    if not resolved.is_relative_to(SPECS_DIR):
        raise HTTPException(status_code=403, detail="path is outside the allowed workspace")
    if resolved.suffix.lower() != ".md":
        raise HTTPException(status_code=400, detail="unsupported file type")
    return resolved


def _resolve_output_path(value: str) -> Path:
    path = Path(value or ".")
    if path.parts and path.parts[0].lower() == "output":
        path = Path(*path.parts[1:])
    resolved = (OUTPUT_ROOT / path).resolve()
    if not resolved.is_relative_to(OUTPUT_ROOT):
        raise HTTPException(status_code=403, detail="path is outside the allowed workspace")
    return resolved


class PipelineRunRequest(BaseModel):
    spec_text: str = ""
    spec_file: str = ""
    workflow: str = "full_verification"
    output_dir: str = "."
    run_type: str = "traditional"


class TestCaseGenerateRequest(BaseModel):
    spec_text: str = ""
    output_dir: str = "testcases"


@router.post("/pipeline/run")
async def pipeline_run(req: PipelineRunRequest, user: dict = Depends(require_auth)):
    spec_text = req.spec_text
    if not spec_text and req.spec_file:
        p = _resolve_spec_path(req.spec_file)
        if p.exists():
            if p.stat().st_size > MAX_DOCUMENT_BYTES:
                raise HTTPException(status_code=413, detail="spec file is too large")
            spec_text = p.read_text(encoding="utf-8")
    if not spec_text:
        raise HTTPException(status_code=400, detail="spec_text required")

    service = PipelineExecutionService.get_instance()
    if not service.initialized:
        await service.initialize_agents()

    # ── 基于角色的工作流选择 ──
    user_role = user.get("role", "engineer")
    from src.database.repository import get_allowed_workflows_for_role, get_default_workflow_for_role
    allowed_workflows = await get_allowed_workflows_for_role(user_role)
    default_workflow = await get_default_workflow_for_role(user_role)

    if req.workflow and req.workflow != "full_verification":
        # 用户显式指定了非默认工作流，校验权限
        if req.workflow not in allowed_workflows:
            raise HTTPException(
                status_code=403,
                detail=f"角色 '{user_role}' 无权使用工作流 '{req.workflow}'。可用: {allowed_workflows}"
            )
        resolved_workflow = req.workflow
    elif req.workflow == "full_verification" and "full_verification" not in allowed_workflows:
        # 前端默认传 full_verification 但角色不允许 → 切换为角色的默认工作流
        resolved_workflow = default_workflow
    else:
        resolved_workflow = req.workflow or default_workflow

    run_id = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    output_root = str(_resolve_output_path(req.output_dir))

    service._run_types = getattr(service, '_run_types', {})
    service._run_types[run_id] = req.run_type

    app_mode = os.environ.get("APP_MODE", "demo").lower()

    async def _run():
        import time
        started = time.time()
        try:
            await service.run_pipeline(spec_text=spec_text, workflow=resolved_workflow,
                                       output_root=output_root, run_id=run_id)
            duration = time.time() - started
            try:
                from src.infra.observability import get_metrics
                state_obj = service.get_run_status(run_id) or {}
                phases = state_obj.get("phases", [])
                get_metrics().record_pipeline_run(
                    run_id=run_id, workflow=resolved_workflow,
                    state=state_obj.get("state", "completed"),
                    duration_s=duration,
                    phases_total=len(phases),
                    phases_passed=sum(1 for p in phases if p.get("status") == "passed"),
                    phases_failed=sum(1 for p in phases if p.get("status") in ("failed", "error")),
                    started_at=str(state_obj.get("started_at", "")),
                    completed_at=str(state_obj.get("completed_at", "")))
            except Exception:
                pass

            try:
                from src.infra.event_bus import get_event_bus, StandardEvent
                bus = get_event_bus()
                state_obj = service.get_run_status(run_id) or {}
                event = StandardEvent.PIPELINE_FAILED if state_obj.get("state") == "completed_with_errors" else StandardEvent.PIPELINE_COMPLETED
                await bus.publish(event, {"run_id": run_id, "workflow": resolved_workflow}, source="api.pipeline")
            except Exception:
                pass
        except Exception as e:
            pass

    asyncio.create_task(_run())

    from src.database.repository import add_audit_log
    await add_audit_log(user["user_id"], user["username"], "pipeline_run", run_id,
                        f"workflow={resolved_workflow} role={user_role} started run_type={req.run_type}")
    return {"run_id": run_id, "workflow": resolved_workflow, "status": "started",
            "run_type": req.run_type, "role": user_role}


@router.get("/pipeline/{run_id}/stream")
async def pipeline_sse_stream(run_id: str):
    from src.web.sse import subscribe, unsubscribe

    async def event_generator():
        q = await subscribe(run_id)
        try:
            service = PipelineExecutionService.get_instance()
            state = service.get_run_status(run_id)
            if state:
                yield f"data: {json.dumps({'event': 'snapshot', 'data': state}, ensure_ascii=False)}\n\n"
            while True:
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=30)
                    yield f"data: {msg}\n\n"
                except asyncio.TimeoutError:
                    yield f"data: {json.dumps({'event': 'heartbeat', 'data': {}}, ensure_ascii=False)}\n\n"
                    state = service.get_run_status(run_id)
                    if state and state.get("state") in ("completed", "completed_with_errors"):
                        yield f"data: {json.dumps({'event': 'run_complete', 'data': state}, ensure_ascii=False)}\n\n"
                        break
        except asyncio.CancelledError:
            pass
        finally:
            unsubscribe(run_id, q)

    return StreamingResponse(
        event_generator(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@router.get("/pipeline/history")
async def pipeline_history(limit: int = 20):
    from src.database.repository import get_recent_pipelines
    return {"runs": await get_recent_pipelines(limit)}


@router.get("/pipeline/run/{run_id}")
async def pipeline_run_status(run_id: str):
    service = PipelineExecutionService.get_instance()
    s = service.get_run_status(run_id)
    if s:
        return s
    try:
        from src.database.repository import get_pipeline_run_by_run_id
        db_run = await get_pipeline_run_by_run_id(run_id)
        if db_run:
            return db_run
    except Exception:
        pass
    raise HTTPException(status_code=404, detail="run not found")


@router.get("/pipeline/run/{run_id}/stream")
async def pipeline_stream(run_id: str):
    service = PipelineExecutionService.get_instance()
    async def gen():
        last = 0
        for _ in range(900):
            s = service.get_run_status(run_id)
            if not s:
                try:
                    from src.database.repository import get_pipeline_run_by_run_id
                    db_run = await get_pipeline_run_by_run_id(run_id)
                    if db_run:
                        yield f"data: {json.dumps(db_run)}\n\n"
                    else:
                        yield f"data: {json.dumps({'error':'not found'})}\n\n"
                except Exception:
                    yield f"data: {json.dumps({'error':'not found'})}\n\n"
                break
            if len(s.get("phases", [])) > last:
                yield f"data: {json.dumps(s)}\n\n"
                last = len(s["phases"])
            if s["state"] in ("completed", "completed_with_errors"):
                yield f"data: {json.dumps(s)}\n\n"
                break
            await asyncio.sleep(1)
    return StreamingResponse(gen(), media_type="text/event-stream")


@router.get("/spec/default")
async def default_spec():
    p = Path("spec_uart.txt")
    return {"content": p.read_text(encoding="utf-8") if p.exists() else "", "file": str(p) if p.exists() else ""}


@router.get("/testcases/list")
async def testcases_list(output_dir: str = "output/testcases"):
    base = _resolve_output_path(output_dir)
    if not base.exists():
        return {"testcases": [], "count": 0}
    tests = []
    for d in sorted(base.iterdir()):
        if d.is_dir():
            files = [f.name for f in d.iterdir() if f.is_file()]
            tests.append({"name": d.name, "path": str(d), "files": files,
                          "sv_files": [f for f in files if f.endswith('.sv')],
                          "has_run_sh": "run.sh" in files})
    return {"testcases": tests, "count": len(tests)}


@router.get("/testcases/{test_name}")
async def testcase_detail(test_name: str, output_dir: str = "output/testcases"):
    test_dir = _resolve_output_path(output_dir) / test_name
    test_dir = (Path(_resolve_output_path(output_dir)) / test_name).resolve()
    if not test_dir.is_relative_to(_resolve_output_path(output_dir)):
        raise HTTPException(status_code=403, detail="path is outside the allowed workspace")
    if not test_dir.exists():
        raise HTTPException(status_code=404)
    files = {}
    for f in test_dir.iterdir():
        if f.is_file() and f.suffix in (".sv", ".sh"):
            files[f.name] = f.read_text(encoding="utf-8")[:5000]
    return {"name": test_name, "path": str(test_dir), "files": files}


@router.post("/testcases/generate")
async def testcases_generate(req: TestCaseGenerateRequest, user: dict = Depends(require_auth)):
    spec_text = req.spec_text or Path("spec_uart.txt").read_text(encoding="utf-8")
    service = PipelineExecutionService.get_instance()
    result = await service.generate_testcases(spec_text=spec_text, output_dir=str(_resolve_output_path(req.output_dir)))
    from src.database.repository import add_audit_log
    await add_audit_log(user["user_id"], user["username"], "testcase_generate")
    return {"success": result["success"], "tests": result.get("tests", {}), "error": result.get("error")}
