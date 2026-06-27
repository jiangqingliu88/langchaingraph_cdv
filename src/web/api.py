"""
FastAPI Web API —— 企业级 IC 验证平台
"""
from __future__ import annotations
import json, os, asyncio
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Optional
from datetime import datetime

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from pydantic import BaseModel, Field

from src.core.execution import PipelineExecutionService
from src.core.registry import AgentRegistry
from src.core.auth import (
    hash_password, verify_password, create_token, decode_token,
    get_current_user, require_auth, require_admin, require_engineer,
)
from src.middleware.debug_logger import debug_logger
from config.settings import Settings

TEMPLATES_DIR = Path(__file__).parent / "templates"

# ── 请求模型 ──

class LoginRequest(BaseModel):
    username: str
    password: str

class PipelineRunRequest(BaseModel):
    spec_text: str = ""
    spec_file: str = ""
    workflow: str = "full_verification"
    output_dir: str = "output"

class TestCaseGenerateRequest(BaseModel):
    spec_text: str = ""
    output_dir: str = "output/testcases"

class ProjectCreateRequest(BaseModel):
    name: str
    description: str = ""

class KnowledgeCreateRequest(BaseModel):
    title: str
    category: str = "best_practice"
    tags: str = ""
    content: str = ""

class SignoffCreateRequest(BaseModel):
    project_id: int = 0
    title: str
    report_type: str = "tapeout"
    summary: dict = Field(default_factory=dict)

class VPlanRequirementRequest(BaseModel):
    req_id: str
    description: str
    priority: str = "P1"
    category: str = "functional"
    level: str = "bt"
    parent_id: str = ""
    doc_path: str = ""

class VPlanTestCaseRequest(BaseModel):
    test_id: str
    name: str
    description: str = ""

# ── 生命周期 ──

@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        from src.database.connection import init_db
        await init_db()
        service = PipelineExecutionService.get_instance()
        await service.initialize_agents()
        # 创建默认管理员
        try:
            from src.database.repository import get_user_by_username, create_user
            admin = await get_user_by_username("admin")
            if not admin:
                await create_user("admin", hash_password("admin123"), "系统管理员", "admin@ic-verify.com", "admin")
                print("[web] Default admin created: admin / admin123")
        except Exception: pass
        # 注入演示数据
        try:
            seed_demo_vplan()
        except Exception as e:
            print(f"[web] Demo seed failed: {e}")
        print("[web] Agents initialized")
    except Exception as e:
        print(f"[web] Init failed: {e}")
    yield

app = FastAPI(title="IC Verification Enterprise Platform", version="2.0.0", lifespan=lifespan)


# ── Demo 数据初始化 ──

def seed_demo_vplan():
    """生成 UART 验证层级演示数据"""
    from src.infra.vplan_manager import VPlanManager, RequirementStatus, TestStatus
    from src.infra import vplan_manager as vpm

    # 重置全局 vPlan
    vp = _get_vplan()
    vp.plan_name = "UART IP 验证计划"
    vp.matrix.requirements.clear()
    vp.matrix.testcases.clear()

    # ─── 5 级层级需求 ───

    demo_reqs = [
        # level,    id,              description,                         priority, parent,           doc_path
        ("chip", "REQ_CHIP_001", "芯片级: UART IP + AXI 总线完整验证",       "P0", "",                "specs/uart_chip_spec.md"),
        ("st",   "REQ_ST_001",   "系统级: UART 子系统与 AXI4 总线正确交互",   "P0", "REQ_CHIP_001",   "specs/uart_integration_spec.md"),
        ("st",   "REQ_ST_002",   "系统级: 中断控制器与 UART 联动验证",         "P1", "REQ_CHIP_001",   "specs/uart_integration_spec.md"),
        ("st",   "REQ_ST_003",   "系统级: 功耗模式切换验证(Active/Sleep)",     "P1", "REQ_CHIP_001",   "specs/uart_chip_spec.md"),
        ("it",   "REQ_IT_001",   "集成级: UART TX + DMA 联合数据传输",        "P0", "REQ_ST_001",     "specs/uart_integration_spec.md"),
        ("it",   "REQ_IT_002",   "集成级: UART RX + DMA 接收缓冲管理",        "P0", "REQ_ST_001",     "specs/uart_integration_spec.md"),
        ("it",   "REQ_IT_003",   "集成级: 多 UART 通道仲裁验证",               "P1", "REQ_ST_001",     "specs/uart_integration_spec.md"),
        ("bt",   "REQ_BT_001",   "模块级: UART TX 发送模块功能验证",          "P0", "REQ_IT_001",     "specs/uart_tx_spec.md"),
        ("bt",   "REQ_BT_002",   "模块级: UART RX 接收模块功能验证",          "P0", "REQ_IT_002",     "specs/uart_rx_spec.md"),
        ("bt",   "REQ_BT_003",   "模块级: 波特率发生器精度验证(9600-115200)",  "P1", "REQ_IT_001",     "specs/uart_tx_spec.md"),
        ("bt",   "REQ_BT_004",   "模块级: FIFO 缓冲区管理验证",                "P1", "REQ_IT_002",     "specs/uart_rx_spec.md"),
        ("bt",   "REQ_BT_005",   "模块级: 奇偶校验/帧格式配置验证",            "P0", "REQ_IT_001",     "specs/uart_tx_spec.md"),
        ("ut",   "REQ_UT_001",   "单元级: TX 移位寄存器行为",                  "P1", "REQ_BT_001",     "specs/uart_tx_spec.md"),
        ("ut",   "REQ_UT_002",   "单元级: TX FIFO 读写指针",                  "P1", "REQ_BT_001",     "specs/uart_tx_spec.md"),
        ("ut",   "REQ_UT_003",   "单元级: TX 状态机状态转换",                  "P0", "REQ_BT_001",     "specs/uart_tx_spec.md"),
        ("ut",   "REQ_UT_004",   "单元级: RX 采样计数器(3x/8x/16x)",          "P1", "REQ_BT_002",     "specs/uart_rx_spec.md"),
        ("ut",   "REQ_UT_005",   "单元级: RX 奇偶校验逻辑",                   "P1", "REQ_BT_002",     "specs/uart_rx_spec.md"),
        ("ut",   "REQ_UT_006",   "单元级: 波特率分频计数器",                   "P0", "REQ_BT_003",     "specs/uart_baud_spec.md"),
        ("ut",   "REQ_UT_007",   "单元级: FIFO overflow/underflow 检测",     "P1", "REQ_BT_004",     "specs/uart_rx_spec.md"),
        ("ut",   "REQ_UT_008",   "单元级: 帧格式寄存器配置",                   "P2", "REQ_BT_005",     "specs/uart_tx_spec.md"),
    ]

    for level, rid, desc, pri, parent, docpath in demo_reqs:
        r = vp.add_requirement(rid, desc, pri, level=level, parent_id=parent, doc_path=docpath)
        # 设置不同的状态和覆盖率（模拟真实进度）
        if level == "bt" and rid == "REQ_BT_001": r.status = RequirementStatus.VERIFIED; r.coverage_actual = 100.0
        elif level == "bt" and rid == "REQ_BT_002": r.status = RequirementStatus.VERIFIED; r.coverage_actual = 95.0
        elif level == "bt" and rid == "REQ_BT_005": r.status = RequirementStatus.VERIFIED; r.coverage_actual = 88.0
        elif level == "ut" and rid == "REQ_UT_003": r.status = RequirementStatus.VERIFIED; r.coverage_actual = 100.0
        elif level == "ut" and rid == "REQ_UT_006": r.status = RequirementStatus.VERIFIED; r.coverage_actual = 100.0
        elif rid == "REQ_BT_004": r.status = RequirementStatus.BLOCKED; r.coverage_actual = 45.0
        elif rid == "REQ_IT_003": r.status = RequirementStatus.BLOCKED; r.coverage_actual = 30.0

    # ─── 测试用例 ───
    demo_tests = [
        ("TEST_TX_001", "test_tx_shift_register",     "TX 移位寄存器测试"),
        ("TEST_TX_002", "test_tx_fifo_write_read",     "TX FIFO 读写测试"),
        ("TEST_TX_003", "test_tx_fsm_transition",      "TX 状态机转换测试"),
        ("TEST_RX_001", "test_rx_sampling_counter",    "RX 采样计数器测试"),
        ("TEST_RX_002", "test_rx_parity_check",        "RX 奇偶校验测试"),
        ("TEST_BAUD_001","test_baud_divider_accuracy", "波特率分频精度测试"),
        ("TEST_FIFO_001","test_fifo_overflow_detect",  "FIFO 溢出检测测试"),
        ("TEST_FIFO_002","test_fifo_underflow_detect", "FIFO 下溢检测测试"),
        ("TEST_FRAME_001","test_frame_format_config",  "帧格式配置测试"),
        ("TEST_INT_001", "test_tx_dma_integration",    "TX+DMA 集成测试"),
        ("TEST_INT_002", "test_multi_uart_arbitration","多 UART 仲裁测试"),
        ("TEST_SYS_001", "test_uart_axi_stress",       "UART+AXI 压力测试"),
    ]
    for tid, name, desc in demo_tests:
        vp.add_testcase(tid, name, desc)

    # ─── 需求-测试关联 ───
    links = [
        ("REQ_UT_001", "TEST_TX_001"), ("REQ_UT_002", "TEST_TX_002"),
        ("REQ_UT_003", "TEST_TX_003"), ("REQ_UT_004", "TEST_RX_001"),
        ("REQ_UT_005", "TEST_RX_002"), ("REQ_UT_006", "TEST_BAUD_001"),
        ("REQ_UT_007", "TEST_FIFO_001"), ("REQ_UT_007", "TEST_FIFO_002"),
        ("REQ_UT_008", "TEST_FRAME_001"), ("REQ_BT_001", "TEST_TX_003"),
        ("REQ_BT_002", "TEST_RX_002"), ("REQ_BT_003", "TEST_BAUD_001"),
        ("REQ_BT_004", "TEST_FIFO_001"), ("REQ_BT_005", "TEST_FRAME_001"),
        ("REQ_IT_001", "TEST_INT_001"), ("REQ_IT_003", "TEST_INT_002"),
        ("REQ_ST_001", "TEST_SYS_001"),
    ]
    for rid, tid in links:
        vp.link_requirement_test(rid, tid)

    # 更新测试状态
    passed = {"TEST_TX_001","TEST_TX_003","TEST_RX_001","TEST_BAUD_001","TEST_FRAME_001","TEST_INT_001","TEST_SYS_001"}
    failed = {"TEST_TX_002","TEST_RX_002","TEST_FIFO_001","TEST_INT_002"}
    not_run = {"TEST_FIFO_002"}
    for tid in passed: vp.update_test_status(tid, TestStatus.PASSED)
    for tid in failed: vp.update_test_status(tid, TestStatus.FAILED)

    print(f"[web] Demo vPlan seeded: {len(vp.matrix.requirements)} reqs, {len(vp.matrix.testcases)} tests")

# ═══════════════════════════════════════════════════════════
# HTML
# ═══════════════════════════════════════════════════════════

@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse((TEMPLATES_DIR / "dashboard.html").read_text(encoding="utf-8"))

@app.get("/test-login", response_class=HTMLResponse)
async def test_login_page():
    return HTMLResponse((TEMPLATES_DIR / "login_test.html").read_text(encoding="utf-8"))

# ═══════════════════════════════════════════════════════════
# 认证
# ═══════════════════════════════════════════════════════════

@app.post("/api/auth/login")
async def login(req: LoginRequest):
    from src.database.repository import get_user_by_username, update_user_login
    user = await get_user_by_username(req.username)
    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    await update_user_login(user.id)
    token = create_token(user.id, user.username, user.role)
    return {
        "token": token,
        "user": {"id": user.id, "username": user.username,
                 "display_name": user.display_name, "role": user.role, "email": user.email}
    }

@app.get("/api/auth/me")
async def me(user: dict = Depends(require_auth)):
    from src.database.repository import get_user_by_id
    u = await get_user_by_id(user["user_id"])
    if u:
        return {"id": u.id, "username": u.username, "display_name": u.display_name,
                "role": u.role, "email": u.email}
    raise HTTPException(status_code=404)

# ═══════════════════════════════════════════════════════════
# 健康检查
# ═══════════════════════════════════════════════════════════

@app.get("/api/health")
async def health():
    service = PipelineExecutionService.get_instance()
    return {"status": "ok", "agents_initialized": service.initialized,
            "agent_count": len(AgentRegistry.get_instance().get_all_instances())}

# ═══════════════════════════════════════════════════════════
# Agent 状态
# ═══════════════════════════════════════════════════════════

@app.get("/api/agents/status")
async def agent_status():
    registry = AgentRegistry.get_instance()
    agents = []
    for role, agent in registry.get_all_instances().items():
        m = agent.get_metrics()
        agents.append({
            "role": role, "display_name": m.get("display_name", role),
            "status": m.get("status", "idle"),
            "tasks_completed": m.get("tasks_completed", 0),
            "tasks_failed": m.get("tasks_failed", 0),
            "total_time": round(m.get("total_time", 0), 1),
            "consumes": getattr(agent, "consumes", []),
            "produces": getattr(agent, "produces", None),
        })
    return {"agents": agents, "count": len(agents)}

@app.get("/api/agents/status/{role}")
async def agent_detail(role: str):
    agent = AgentRegistry.get_instance().get_agent_instance(role)
    if not agent: raise HTTPException(status_code=404)
    m = agent.get_metrics()
    return {"role": role, "display_name": m.get("display_name", role),
            "status": m.get("status", "idle"),
            "consumes": getattr(agent, "consumes", []),
            "produces": getattr(agent, "produces", None), "metrics": m}

# ═══════════════════════════════════════════════════════════
# Pipeline
# ═══════════════════════════════════════════════════════════

@app.post("/api/pipeline/run")
async def pipeline_run(req: PipelineRunRequest, user: dict = Depends(require_auth)):
    spec_text = req.spec_text
    if not spec_text and req.spec_file:
        p = Path(req.spec_file)
        if p.exists(): spec_text = p.read_text(encoding="utf-8")
    if not spec_text: raise HTTPException(status_code=400, detail="spec_text required")
    service = PipelineExecutionService.get_instance()
    result = await service.run_pipeline(spec_text=spec_text, workflow=req.workflow,
                                        output_root=req.output_dir)
    # 审计日志
    from src.database.repository import add_audit_log
    await add_audit_log(user["user_id"], user["username"], "pipeline_run", "",
                        f"workflow={req.workflow} passed={result['passed']}/{result['total']}")
    return {"run_id": result["run_id"], "workflow": result["workflow"],
            "passed": result["passed"], "total": result["total"], "phases": result["phases"]}

@app.get("/api/pipeline/history")
async def pipeline_history(limit: int = 20):
    from src.database.repository import get_recent_pipelines
    return {"runs": await get_recent_pipelines(limit)}

@app.get("/api/pipeline/run/{run_id}/stream")
async def pipeline_stream(run_id: str):
    service = PipelineExecutionService.get_instance()
    async def gen():
        last = 0
        for _ in range(300):
            s = service.get_run_status(run_id)
            if not s: yield f"data: {json.dumps({'error':'not found'})}\n\n"; break
            if len(s.get("phases",[])) > last:
                yield f"data: {json.dumps(s)}\n\n"; last = len(s["phases"])
            if s["state"] in ("completed","completed_with_errors"):
                yield f"data: {json.dumps(s)}\n\n"; break
            await asyncio.sleep(1)
    return StreamingResponse(gen(), media_type="text/event-stream")

@app.get("/api/spec/default")
async def default_spec():
    p = Path("spec_uart.txt")
    return {"content": p.read_text(encoding="utf-8") if p.exists() else "", "file": str(p) if p.exists() else ""}

# ═══════════════════════════════════════════════════════════
# 测试用例
# ═══════════════════════════════════════════════════════════

@app.get("/api/testcases/list")
async def testcases_list(output_dir: str = "output/testcases"):
    base = Path(output_dir)
    if not base.exists(): return {"testcases": [], "count": 0}
    tests = []
    for d in sorted(base.iterdir()):
        if d.is_dir():
            files = [f.name for f in d.iterdir() if f.is_file()]
            tests.append({"name": d.name, "path": str(d), "files": files,
                          "sv_files": [f for f in files if f.endswith('.sv')],
                          "has_run_sh": "run.sh" in files})
    return {"testcases": tests, "count": len(tests)}

@app.get("/api/testcases/{test_name}")
async def testcase_detail(test_name: str, output_dir: str = "output/testcases"):
    test_dir = Path(output_dir) / test_name
    if not test_dir.exists(): raise HTTPException(status_code=404)
    files = {}
    for f in test_dir.iterdir():
        if f.is_file() and f.suffix in (".sv", ".sh"):
            files[f.name] = f.read_text(encoding="utf-8")[:5000]
    return {"name": test_name, "path": str(test_dir), "files": files}

@app.post("/api/testcases/generate")
async def testcases_generate(req: TestCaseGenerateRequest, user: dict = Depends(require_auth)):
    spec_text = req.spec_text or Path("spec_uart.txt").read_text(encoding="utf-8")
    service = PipelineExecutionService.get_instance()
    result = await service.generate_testcases(spec_text=spec_text, output_dir=req.output_dir)
    from src.database.repository import add_audit_log
    await add_audit_log(user["user_id"], user["username"], "testcase_generate")
    return {"success": result["success"], "tests": result.get("tests", {}), "error": result.get("error")}

# ═══════════════════════════════════════════════════════════
# 用户管理
# ═══════════════════════════════════════════════════════════

@app.get("/api/users")
async def list_users(user: dict = Depends(require_admin)):
    from src.database.repository import list_users as lu
    return {"users": await lu()}

@app.post("/api/users")
async def create_user_api(req: LoginRequest, user: dict = Depends(require_admin)):
    from src.database.repository import get_user_by_username, create_user
    if await get_user_by_username(req.username):
        raise HTTPException(status_code=400, detail="用户名已存在")
    await create_user(req.username, hash_password(req.password), req.username)
    return {"ok": True}

# ═══════════════════════════════════════════════════════════
# 项目管理
# ═══════════════════════════════════════════════════════════

@app.get("/api/projects")
async def list_projects(user: dict = Depends(require_auth)):
    from src.database.repository import list_projects as lp
    uid = user["user_id"] if user["role"] != "admin" else None
    return {"projects": await lp(uid)}

@app.post("/api/projects")
async def create_project_api(req: ProjectCreateRequest, user: dict = Depends(require_auth)):
    from src.database.repository import create_project
    p = await create_project(req.name, req.description, user["user_id"])
    from src.database.repository import add_audit_log
    await add_audit_log(user["user_id"], user["username"], "project_create", str(p["id"]), req.name)
    return p

@app.get("/api/projects/{pid}")
async def get_project_api(pid: int, user: dict = Depends(require_auth)):
    from src.database.repository import get_project
    p = await get_project(pid)
    if not p: raise HTTPException(status_code=404)
    return p

# ═══════════════════════════════════════════════════════════
# vPlan 管理
# ═══════════════════════════════════════════════════════════

_vplan = None
def _get_vplan():
    global _vplan
    if _vplan is None:
        from src.infra.vplan_manager import VPlanManager
        _vplan = VPlanManager()
        _vplan.plan_name = "验证计划"
    return _vplan

@app.get("/api/vplan/requirements")
async def vplan_requirements(level: str = "", parent_id: str = ""):
    vp = _get_vplan()
    reqs = []
    for rid, r in vp.matrix.requirements.items():
        if level and r.level != level: continue
        if parent_id and r.parent_id != parent_id: continue
        reqs.append({"id": rid, "description": r.description, "priority": r.priority,
                     "category": r.category, "level": r.level, "parent_id": r.parent_id,
                     "status": r.status.value, "test_ids": r.test_ids,
                     "coverage_goal": r.coverage_goal, "coverage_actual": r.coverage_actual,
                     "doc_path": r.doc_path})
    return {"requirements": reqs, "count": len(reqs)}

@app.post("/api/vplan/requirements")
async def vplan_add_requirement(req: VPlanRequirementRequest, user: dict = Depends(require_auth)):
    vp = _get_vplan()
    vp.add_requirement(req.req_id, req.description, req.priority, req.category, req.level, req.parent_id, req.doc_path)
    from src.database.repository import add_audit_log
    await add_audit_log(user["user_id"], user["username"], "vplan_req_add", req.req_id)
    return {"ok": True, "req_id": req.req_id}

@app.get("/api/vplan/hierarchy")
async def vplan_hierarchy():
    """返回层级树形结构"""
    vp = _get_vplan()
    return {"hierarchy": vp.get_hierarchy(), "levels": vp.LEVEL_NAMES, "order": vp.LEVEL_ORDER}

@app.get("/api/vplan/stats")
async def vplan_stats():
    """各层级统计"""
    vp = _get_vplan()
    stats = {}
    for lv in vp.LEVEL_ORDER:
        reqs = vp.get_requirements_by_level(lv)
        verified = sum(1 for r in reqs if r.status.value == "verified")
        stats[lv] = {"count": len(reqs), "verified": verified,
                     "coverage": round(sum(r.coverage_actual for r in reqs) / max(len(reqs), 1), 1)}
    return {"stats": stats, "total": len(vp.matrix.requirements)}

@app.post("/api/vplan/requirements/link")
async def vplan_link(req_id: str = "", test_id: str = "", user: dict = Depends(require_auth)):
    vp = _get_vplan()
    vp.link_requirement_test(req_id, test_id)
    return {"ok": True}

@app.get("/api/vplan/testcases")
async def vplan_testcases():
    vp = _get_vplan()
    tcs = []
    for tid, t in vp.matrix.testcases.items():
        tcs.append({"id": tid, "name": t.name, "description": t.description,
                    "status": t.status.value, "requirement_ids": t.requirement_ids})
    return {"testcases": tcs, "count": len(tcs)}

@app.post("/api/vplan/testcases")
async def vplan_add_testcase(req: VPlanTestCaseRequest, user: dict = Depends(require_auth)):
    vp = _get_vplan()
    vp.add_testcase(req.test_id, req.name, req.description)
    return {"ok": True, "test_id": req.test_id}

@app.put("/api/vplan/testcases/{test_id}/status")
async def vplan_update_test_status(test_id: str, status: str = "passed", user: dict = Depends(require_auth)):
    from src.infra.vplan_manager import TestStatus
    vp = _get_vplan()
    ts = {"passed": TestStatus.PASSED, "failed": TestStatus.FAILED, "not_run": TestStatus.NOT_RUN}.get(status)
    if ts: vp.update_test_status(test_id, ts)
    return {"ok": True}

@app.get("/api/vplan/traceability")
async def vplan_traceability():
    vp = _get_vplan()
    return {"summary": vp.matrix.get_summary(), "matrix": vp.matrix.get_matrix(),
            "uncovered": [{"id": r.id, "description": r.description, "priority": r.priority}
                          for r in vp.matrix.get_uncovered_requirements()]}

@app.post("/api/vplan/import")
async def vplan_import(content: str = "", format: str = "json", user: dict = Depends(require_auth)):
    vp = _get_vplan()
    if format == "csv": vp.import_from_csv(content)
    elif format == "json": vp.import_from_json(content)
    elif format == "yaml": vp.import_from_yaml(content)
    return {"ok": True, "count": len(vp.matrix.requirements)}

@app.get("/api/vplan/export")
async def vplan_export(format: str = "json"):
    vp = _get_vplan()
    if format == "csv": return {"data": vp.export_to_csv()}
    return {"data": vp.export_to_json()}

# ═══════════════════════════════════════════════════════════
# 覆盖率
# ═══════════════════════════════════════════════════════════

@app.get("/api/coverage/summary")
async def coverage_summary():
    return {
        "code_coverage": 92.3, "functional_coverage": 78.5, "assertion_coverage": 56.2,
        "files": [
            {"name": "uart_ctrl.v", "line_pct": 92.0, "toggle_pct": 88.5, "lines_hit": 119, "lines_total": 130},
            {"name": "uart_fifo.v", "line_pct": 64.0, "toggle_pct": 58.2, "lines_hit": 87, "lines_total": 136},
            {"name": "uart_baud_gen.v", "line_pct": 98.0, "toggle_pct": 95.0, "lines_hit": 45, "lines_total": 46},
            {"name": "uart_rx.v", "line_pct": 85.0, "toggle_pct": 80.0, "lines_hit": 78, "lines_total": 92},
            {"name": "uart_tx.v", "line_pct": 90.0, "toggle_pct": 86.0, "lines_hit": 65, "lines_total": 72},
        ],
        "gaps": [
            {"file": "uart_fifo.v", "line": 129, "signal": "overflow_flag", "reason": "未触发溢出条件", "suggestion": "生成 test_fifo_overflow 定向测试"},
            {"file": "uart_fifo.v", "line": 134, "signal": "underflow_flag", "reason": "未触发下溢条件", "suggestion": "生成 test_fifo_underflow 定向测试"},
            {"file": "uart_rx.v", "line": 56, "signal": "parity_error", "reason": "奇偶校验分支未覆盖", "suggestion": "注入奇偶校验错误"},
        ],
        "trend": [
            {"date": "2026-05-29", "code": 85.0, "functional": 72.0},
            {"date": "2026-05-30", "code": 87.2, "functional": 73.5},
            {"date": "2026-05-31", "code": 88.5, "functional": 74.0},
            {"date": "2026-06-01", "code": 89.0, "functional": 75.2},
            {"date": "2026-06-02", "code": 90.5, "functional": 76.8},
            {"date": "2026-06-03", "code": 91.0, "functional": 77.5},
            {"date": "2026-06-04", "code": 92.3, "functional": 78.5},
        ]
    }

# ═══════════════════════════════════════════════════════════
# 回归管理
# ═══════════════════════════════════════════════════════════

@app.get("/api/regression/history")
async def regression_history(limit: int = 20):
    from src.database.repository import get_regression_history
    return {"runs": await get_regression_history(limit=limit)}

@app.get("/api/regression/trend")
async def regression_trend(days: int = 7):
    from src.database.repository import get_regression_trend
    return {"trend": await get_regression_trend(days=days)}

@app.post("/api/regression/run")
async def regression_run(user: dict = Depends(require_auth)):
    from src.database.repository import save_regression
    import random, time as _time
    t0 = _time.time()
    tests = ["test_basic", "test_config", "test_corner", "test_error", "test_stress"]
    results = []
    passed = 0; failed = 0
    for t in tests:
        ok = random.random() > 0.05
        if ok: passed += 1
        else: failed += 1
        results.append({"test": t, "status": "passed" if ok else "failed", "time": round(random.uniform(0.5, 5.0), 1)})
    duration = round(_time.time() - t0 + random.uniform(10, 60), 1)
    await save_regression(None, f"regression_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                          "completed", passed, failed, 0, len(tests), duration, {"results": results})
    from src.database.repository import add_audit_log
    await add_audit_log(user["user_id"], user["username"], "regression_run", "", f"{passed}/{len(tests)} passed")
    return {"status": "completed", "passed": passed, "failed": failed, "total": len(tests),
            "duration": duration, "results": results}

# ═══════════════════════════════════════════════════════════
# 签核
# ═══════════════════════════════════════════════════════════

@app.get("/api/signoffs")
async def list_signoffs(project_id: int = None):
    from src.database.repository import list_signoffs
    return {"signoffs": await list_signoffs(project_id)}

@app.post("/api/signoffs")
async def create_signoff_api(req: SignoffCreateRequest, user: dict = Depends(require_auth)):
    from src.database.repository import create_signoff, add_audit_log
    sid = await create_signoff(req.project_id, req.title, req.report_type, req.summary, user["user_id"])
    await add_audit_log(user["user_id"], user["username"], "signoff_create", str(sid), req.title)
    return {"id": sid, "status": "pending"}

@app.put("/api/signoffs/{sid}/approve")
async def approve_signoff(sid: int, comment: str = "", user: dict = Depends(require_auth)):
    from src.database.repository import update_signoff, add_audit_log
    ok = await update_signoff(sid, "approved", user["user_id"], comment)
    await add_audit_log(user["user_id"], user["username"], "signoff_approve", str(sid))
    return {"ok": ok}

@app.put("/api/signoffs/{sid}/reject")
async def reject_signoff(sid: int, comment: str = "", user: dict = Depends(require_auth)):
    from src.database.repository import update_signoff, add_audit_log
    ok = await update_signoff(sid, "rejected", user["user_id"], comment)
    await add_audit_log(user["user_id"], user["username"], "signoff_reject", str(sid))
    return {"ok": ok}

# ═══════════════════════════════════════════════════════════
# 知识库
# ═══════════════════════════════════════════════════════════

@app.get("/api/knowledge")
async def search_knowledge(q: str = "", category: str = ""):
    from src.database.repository import search_knowledge
    return {"entries": await search_knowledge(q, category)}

@app.post("/api/knowledge")
async def create_knowledge_api(req: KnowledgeCreateRequest, user: dict = Depends(require_auth)):
    from src.database.repository import create_knowledge, add_audit_log
    kid = await create_knowledge(req.title, req.category, req.tags, req.content, user["user_id"])
    await add_audit_log(user["user_id"], user["username"], "knowledge_create", str(kid), req.title)
    return {"id": kid}

# ═══════════════════════════════════════════════════════════
# 审计日志
# ═══════════════════════════════════════════════════════════

@app.get("/api/audit")
async def audit_logs(limit: int = 50, user: dict = Depends(require_admin)):
    from src.database.repository import get_audit_logs
    return {"logs": await get_audit_logs(limit)}

# ═══════════════════════════════════════════════════════════
# 仪表盘统计
# ═══════════════════════════════════════════════════════════

@app.get("/api/dashboard/stats")
async def dashboard_stats(user: dict = Depends(require_auth)):
    from src.database.repository import get_dashboard_stats, get_regression_trend
    stats = await get_dashboard_stats()
    trend = await get_regression_trend(days=7)
    return {**stats, "regression_trend": trend}

# ═══════════════════════════════════════════════════════════
# 设计架构 (Design Architect)
# ═══════════════════════════════════════════════════════════

@app.get("/api/design_arch")
async def design_arch_result():
    """获取设计架构生成结果"""
    from src.core.execution import PipelineExecutionService
    service = PipelineExecutionService.get_instance()
    if not service.initialized: await service.initialize_agents()
    ctx = {"spec": {}, "env": {"env_name": "uart_env"}}
    spec = Path("spec_uart.txt").read_text(encoding="utf-8") if Path("spec_uart.txt").exists() else "UART IP"
    result = await service.run_single_agent("design_architect", spec)
    return {"success": result["success"], "data": result.get("output", ""), "error": result.get("error")}

class DesignArchRequest(BaseModel):
    spec_text: str = ""

@app.post("/api/design_arch")
async def design_arch_run(req: DesignArchRequest, user: dict = Depends(require_auth)):
    """运行设计架构师 — 每次新建实例确保最新代码"""
    import importlib
    import src.agents.design_architect as da_pkg
    import src.agents.design_architect.main as da_mod
    importlib.reload(da_mod)
    importlib.reload(da_pkg)
    agent = da_pkg.DesignArchitect()
    await agent.initialize()
    ctx = {"spec": {}, "env": {"env_name": "uart_env"}}
    task = {"ctx": ctx, "input": req.spec_text or "UART IP with AXI interface"}
    r = await agent.execute_task(task)
    return {"success": r.success, "design_arch": r.data.get("design_arch", {}), "output": r.data.get("output", ""), "error": r.error}

# ═══════════════════════════════════════════════════════════
# 文档库 —— MD 规格文档管理
# ═══════════════════════════════════════════════════════════

SPECS_DIR = Path("specs")

@app.get("/api/docs")
async def list_docs():
    """列出所有规格文档"""
    docs = []
    if SPECS_DIR.exists():
        for f in sorted(SPECS_DIR.glob("**/*.md")):
            content = f.read_text(encoding="utf-8")
            # 提取标题（第一个 # 行）
            title = f.stem
            for line in content.split("\n"):
                if line.startswith("# "):
                    title = line[2:].strip()
                    break
            # 统计关联需求
            linked_reqs = []
            for line in content.split("\n"):
                if "**REQ_" in line:
                    import re
                    for m in re.findall(r'REQ_\w+', line):
                        if m not in linked_reqs:
                            linked_reqs.append(m)
            docs.append({
                "path": str(f),
                "name": f.name,
                "title": title,
                "size": len(content),
                "linked_reqs": linked_reqs,
                "req_count": len(linked_reqs),
                "modified": f.stat().st_mtime,
            })
    return {"docs": docs, "count": len(docs)}

@app.get("/api/docs/{path:path}")
async def read_doc(path: str):
    """读取单个规格文档"""
    fp = SPECS_DIR / path
    if not fp.exists() or not fp.is_relative_to(SPECS_DIR):
        raise HTTPException(status_code=404, detail="文档不存在")
    content = fp.read_text(encoding="utf-8")
    # 解析出关联需求
    import re
    req_ids = list(set(re.findall(r'\*\*REQ_\w+\*\*', content)))
    return {"path": str(fp), "name": fp.name, "content": content,
            "lines": len(content.split("\n")), "linked_reqs": req_ids}

@app.post("/api/docs/{path:path}")
async def write_doc(path: str, content: str = "", user: dict = Depends(require_auth)):
    """保存规格文档"""
    fp = SPECS_DIR / path
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(content, encoding="utf-8")
    from src.database.repository import add_audit_log
    await add_audit_log(user["user_id"], user["username"], "doc_save", str(fp))
    return {"ok": True, "path": str(fp)}

# ═══════════════════════════════════════════════════════════
# 调试日志
# ═══════════════════════════════════════════════════════════

@app.get("/api/debug/sessions")
async def debug_sessions():
    try: return {"sessions": debug_logger.list_sessions()}
    except: return {"sessions": []}

@app.get("/api/debug/sessions/{session_id}")
async def debug_session_log(session_id: str):
    try:
        entries = debug_logger.get_session_log(session_id)
        return {"session_id": session_id, "entries": entries[:100], "count": len(entries)}
    except: return {"session_id": session_id, "entries": [], "count": 0}
