"""
FastAPI Web API —— 企业级 IC 验证平台
"""
from __future__ import annotations
import json, os, asyncio
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Optional
from datetime import datetime

from fastapi import FastAPI, Request, HTTPException, Depends, Body
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src.core.execution import PipelineExecutionService
from src.core.registry import AgentRegistry
from src.core.auth import (
    hash_password, verify_password, password_needs_rehash, create_token, decode_token,
    get_current_user, require_auth, require_admin, require_engineer,
)
from src.middleware.debug_logger import debug_logger
from config.settings import Settings

TEMPLATES_DIR = Path(__file__).parent / "templates"
WORKSPACE_ROOT = Path(os.environ.get("IC_VERIFY_WORKSPACE", Path.cwd())).resolve()
SPECS_DIR = (WORKSPACE_ROOT / "specs").resolve()
OUTPUT_ROOT = (WORKSPACE_ROOT / "output").resolve()
MAX_DOCUMENT_BYTES = 2 * 1024 * 1024


def _resolve_within(root: Path, value: str, *, suffixes: tuple[str, ...] | None = None) -> Path:
    """Resolve an API path without allowing absolute paths or directory traversal."""
    candidate = Path(value)
    if candidate.is_absolute():
        raise HTTPException(status_code=400, detail="absolute paths are not allowed")
    resolved = (root / candidate).resolve()
    if not resolved.is_relative_to(root):
        raise HTTPException(status_code=403, detail="path is outside the allowed workspace")
    if suffixes and resolved.suffix.lower() not in suffixes:
        raise HTTPException(status_code=400, detail="unsupported file type")
    return resolved


def _resolve_spec_path(value: str) -> Path:
    path = Path(value)
    if path.parts and path.parts[0].lower() == "specs":
        path = Path(*path.parts[1:])
    return _resolve_within(SPECS_DIR, str(path), suffixes=(".md",))


def _resolve_output_path(value: str) -> Path:
    path = Path(value or ".")
    if path.parts and path.parts[0].lower() == "output":
        path = Path(*path.parts[1:])
    return _resolve_within(OUTPUT_ROOT, str(path))

# ── 请求模型 ──

class LoginRequest(BaseModel):
    username: str
    password: str

class PipelineRunRequest(BaseModel):
    spec_text: str = ""
    spec_file: str = ""
    workflow: str = "full_verification"
    output_dir: str = "."
    run_type: str = "traditional"  # traditional | ai_exploration

class TestCaseGenerateRequest(BaseModel):
    spec_text: str = ""
    output_dir: str = "testcases"

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

# ── MD 文档生态请求模型 ──

class DocCreateRequest(BaseModel):
    project_id: int
    path: str
    title: str
    content: str
    level: str = 'module'
    tags: str = ''

class DocUpdateRequest(BaseModel):
    content: str
    change_summary: str = ''

class DocLinkRequest(BaseModel):
    source_id: int
    target_id: int
    relation_type: str = 'parent'
    description: str = ''

class RoleWorkflowBindingRequest(BaseModel):
    role: str
    workflow_name: str
    is_default: bool = False
    description: str = ""

# ── 生命周期 ──

@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        if os.environ.get("APP_ENV", "development").lower() == "production" and not os.environ.get("JWT_SECRET"):
            raise RuntimeError("JWT_SECRET must be configured in production")
        from src.database.connection import init_db
        await init_db()
        service = PipelineExecutionService.get_instance()
        await service.initialize_agents()
        # Bootstrap is explicit so production never exposes a predictable account.
        try:
            from src.database.repository import get_user_by_username, create_user
            bootstrap_password = os.environ.get("BOOTSTRAP_ADMIN_PASSWORD")
            if bootstrap_password:
                admin = await get_user_by_username("admin")
                if not admin:
                    await create_user("admin", hash_password(bootstrap_password), "系统管理员", "admin@signoffai.dev", "admin")
                    print("[web] Bootstrap administrator created (via BOOTSTRAP_ADMIN_PASSWORD)")
            elif os.environ.get("APP_ENV", "development") == "production":
                print("[web] WARNING: Production mode without BOOTSTRAP_ADMIN_PASSWORD. Admin account must be created manually.")
        except Exception: pass
        # 演示数据仅在显式开启 demo 模式时注入
        app_mode = os.environ.get("APP_MODE", "production").lower()
        demo_enabled = os.environ.get("DEMO_ENABLED", "0").lower() in ("1", "true", "yes")
        if app_mode == "demo" or demo_enabled:
            try:
                seed_demo_vplan()
                print("[web] Demo data seeded (APP_MODE=demo or DEMO_ENABLED=1)")
            except Exception as e:
                print(f"[web] Demo seed failed: {e}")
        else:
            print("[web] Demo mode disabled — running in production-safe mode")
        print("[web] Agents initialized")
    except Exception as e:
        print(f"[web] Init failed: {e}")
    yield

app = FastAPI(title="SignOffAI — IC Verification Signoff Platform", version="2.0.0", lifespan=lifespan)

# ── 注册子路由（业务域模块化） ──
from src.web.routes import signoff_router, pipeline_router, ppa_router, docs_router
app.include_router(signoff_router)
app.include_router(pipeline_router)
app.include_router(ppa_router)
app.include_router(docs_router)

# ── 静态文件 ──
_static_dir = Path(__file__).parent / "static"
_static_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")

# ── 统一错误处理 ──
from src.infra.error_handler import register_error_handlers
register_error_handlers(app)

# ── 插件系统启动 ──
@asynccontextmanager
async def plugin_lifespan(app: FastAPI):
    from src.infra.plugin_system import bootstrap_plugins
    await bootstrap_plugins()
    print("[web] Plugin system bootstrapped")
    yield

# 将插件启动合并到主 lifespan 中（在现有 lifespan 内部调用）

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
# 结构化文档编辑器 API
# ═══════════════════════════════════════════════════════════

@app.get("/api/editor/{path:path}")
async def editor_load(path: str):
    """加载文档为结构化 JSON（供编辑器使用）"""
    fp = _resolve_spec_path(path)
    if not fp.exists():
        raise HTTPException(status_code=404, detail="文档不存在")
    md_text = fp.read_text(encoding="utf-8")
    from src.core.doc_serializer import DocumentSerializer
    serializer = DocumentSerializer()
    doc = serializer.md_to_doc(md_text)
    return {"path": str(fp.relative_to(SPECS_DIR)), "doc": doc.to_dict(), "md_raw": md_text}


@app.post("/api/editor/{path:path}")
async def editor_save(path: str, payload: dict, user: dict = Depends(require_auth)):
    """保存结构化 JSON → 渲染 MD → 写回文件 — 仅经理可编辑"""
    role = user.get("role", "")
    if role not in ("admin", "verification_manager"):
        raise HTTPException(status_code=403, detail="仅 SignOff 经理可以编辑规格文档")
    try:
        from src.core.doc_serializer import DocumentSerializer, StructuredDocument
        serializer = DocumentSerializer()

        if "doc" in payload:
            doc = StructuredDocument.from_dict(payload["doc"])
        else:
            doc = serializer.md_to_doc(payload.get("md_raw", ""))

        md_text = serializer.doc_to_md(doc)
        fp = _resolve_spec_path(path)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(md_text, encoding="utf-8")

        try:
            from src.database.repository import add_audit_log
            await add_audit_log(user["user_id"], user["username"], "doc_editor_save",
                                str(fp.relative_to(SPECS_DIR)),
                                f"requirements={len(doc.requirements)} interfaces={len(doc.interfaces)}")
        except Exception: pass

        return {"ok": True, "path": str(fp.relative_to(SPECS_DIR)), "md": md_text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Editor save failed: {str(e)}")


# ═══════════════════════════════════════════════════════════
# 设计层三层映射 API
# ═══════════════════════════════════════════════════════════

@app.get("/api/design/mapping/{project_id}")
async def get_design_mapping(project_id: int = 0):
    """获取三层映射矩阵: 需求→模块→功能点→测试点"""
    from src.core.design_mapper import DesignArchitectMapper
    mapper = DesignArchitectMapper()
    return await mapper.get_mapping_report(project_id)


@app.get("/api/design/modules/{project_id}")
async def get_design_modules(project_id: int = 0):
    """获取模块列表 + 功能点"""
    from src.database.connection import get_session
    from src.database.models import DesignModule, DesignFeature
    from sqlalchemy import select
    s = await get_session()
    modules = (await s.execute(select(DesignModule).where(DesignModule.project_id == project_id if project_id else True))).scalars().all()
    result = []
    for m in modules:
        feats = (await s.execute(select(DesignFeature).where(DesignFeature.module_id == m.id))).scalars().all()
        result.append({
            "id": m.id, "name": m.name, "description": m.description,
            "interfaces": m.interfaces, "signals": m.signals,
            "rtl_file": m.rtl_file, "rtl_hash": m.rtl_hash,
            "features": [{"id": f.id, "name": f.name, "level": f.level, "keywords": f.keywords} for f in feats],
        })
    await s.close()
    return {"modules": result, "total": len(result)}


@app.post("/api/design/modules/upload")
async def upload_design_modules(project_id: int = 0, md_text: str = "", user: dict = Depends(require_auth)):
    """上传模块划分 MD → 解析并存储"""
    from src.core.design_mapper import DesignArchitectMapper
    mapper = DesignArchitectMapper()
    modules = mapper.parse_md_modules(md_text)

    # 获取需求
    vp = _get_vplan()
    requirements = [{"id": r.id, "description": r.description}
                    for r in (vp.matrix.requirements.values() if hasattr(vp, 'matrix') else [])]

    mappings = mapper.match_req_to_features(requirements, modules)
    stored = await mapper.store(project_id, modules, mappings)

    from src.database.repository import add_audit_log
    await add_audit_log(user["user_id"], user["username"], "design_upload",
                        f"project/{project_id}",
                        f"modules={stored['modules']} features={stored['features']} mappings={stored['mappings']}")

    return {"ok": True, "stored": stored, "modules_parsed": len(modules)}


@app.patch("/api/design/mapping/{mapping_id}")
async def update_design_mapping(mapping_id: int, req_id: str = "", feature_id: int = 0,
                                 mapping_type: str = "MANUAL", user: dict = Depends(require_auth)):
    """手动调整映射关系"""
    from src.database.connection import get_session
    from src.database.models import ReqFeatureMap
    from sqlalchemy import select
    s = await get_session()
    m = (await s.execute(select(ReqFeatureMap).where(ReqFeatureMap.id == mapping_id))).scalar_one_or_none()
    if m:
        if req_id: m.req_id = req_id
        if feature_id: m.feature_id = feature_id
        m.mapping_type = mapping_type
        m.mapped_by = user.get("username", "manual")
        await s.commit()
    await s.close()
    return {"ok": m is not None}


@app.get("/api/design/trace/{req_id}")
async def trace_requirement(req_id: str):
    """单个需求的完整追溯链: 需求→模块→功能点→测试点"""
    from src.database.connection import get_session
    from src.database.models import ReqFeatureMap, DesignFeature, DesignModule, FeatureTestpointMap
    from sqlalchemy import select
    s = await get_session()
    mappings = (await s.execute(select(ReqFeatureMap).where(ReqFeatureMap.req_id == req_id))).scalars().all()
    chain = {"req_id": req_id, "mappings": []}
    for m in mappings:
        feat = (await s.execute(select(DesignFeature).where(DesignFeature.id == m.feature_id))).scalar_one_or_none()
        mod = None
        tps = []
        if feat:
            mod = (await s.execute(select(DesignModule).where(DesignModule.id == feat.module_id))).scalar_one_or_none()
            tp_rows = (await s.execute(select(FeatureTestpointMap).where(FeatureTestpointMap.feature_id == feat.id))).scalars().all()
            tps = [t.testpoint_id for t in tp_rows]
        chain["mappings"].append({
            "mapping_type": m.mapping_type, "confidence": m.confidence,
            "module": mod.name if mod else "", "module_rtl_hash": mod.rtl_hash if mod else "",
            "feature": feat.name if feat else "", "feature_level": feat.level if feat else "",
            "testpoints": tps,
        })
    await s.close()
    return chain


# ═══════════════════════════════════════════════════════════
# Agent 契约 & 状态监控 API
# ═══════════════════════════════════════════════════════════

@app.get("/api/agents/contracts")
async def list_agent_contracts():
    """列出所有 Agent 的 I/O 契约 — consumes/produces/tools/min_score"""
    service = PipelineExecutionService.get_instance()
    if not service.initialized:
        await service.initialize_agents()
    contracts = {}
    for role, agent in service.registry.get_all_instances().items():
        contracts[role] = {
            "display_name": getattr(agent, 'display_name', role),
            "task_type": getattr(agent, 'task_type', ''),
            "consumes": getattr(agent, 'consumes', []),
            "produces": getattr(agent, 'produces', ''),
            "min_score": getattr(agent, 'min_score', 50),
            "max_retries": getattr(agent, 'max_retries', 2),
            "tools": [t.name if hasattr(t, 'name') else str(t) for t in (getattr(agent, 'tools', None) or [])],
            "status": getattr(agent, 'status', 'unknown'),
        }
    return {"agents": contracts, "total": len(contracts)}


@app.get("/api/agents/status")
async def get_agent_status():
    """获取所有 Agent 的运行状态、指标和健康度"""
    service = PipelineExecutionService.get_instance()
    if not service.initialized:
        await service.initialize_agents()
    agents_status = []
    for role, agent in service.registry.get_all_instances().items():
        metrics = agent.get_metrics() if hasattr(agent, 'get_metrics') else {}
        agents_status.append({
            "role": role,
            "display_name": getattr(agent, 'display_name', role),
            "status": str(getattr(agent, 'status', 'unknown')),
            "task_type": getattr(agent, 'task_type', ''),
            "produces": getattr(agent, 'produces', ''),
            "tasks_completed": metrics.get("tasks_completed", 0),
            "success_rate": metrics.get("success_rate", 0),
            "avg_execution_time": metrics.get("avg_execution_time", 0),
            "last_error": metrics.get("last_error", ""),
            "tools_count": len(getattr(agent, 'tools', None) or []),
        })
    return {"agents": agents_status, "total": len(agents_status),
            "healthy": sum(1 for a in agents_status if a["status"] == "idle"),
            "busy": sum(1 for a in agents_status if a["status"] != "idle")}


# ═══════════════════════════════════════════════════════════
# vPlan 导出 & 覆盖率 Diff
# ═══════════════════════════════════════════════════════════

@app.get("/api/vplan/export")
async def export_vplan(project_id: int = 0):
    """导出完整 vPlan — 需求树 + 用例映射 + 覆盖率目标"""
    from src.database.repository import list_projects
    # 收集需求层级
    try:
        vp = _get_vplan()
        reqs = [{"id": r.id, "description": r.description, "level": r.level,
                 "status": r.status.value if hasattr(r.status, 'value') else str(r.status),
                 "coverage": r.coverage_actual}
                for r in (vp.matrix.requirements.values() if hasattr(vp, 'matrix') else [])]
        tests = [{"id": t.id, "name": t.name, "status": t.status.value if hasattr(t.status, 'value') else str(t.status)}
                 for t in (vp.matrix.testcases.values() if hasattr(vp, 'matrix') else [])]
        return {"project_id": project_id, "requirements": reqs, "testcases": tests,
                "total_requirements": len(reqs), "total_testcases": len(tests)}
    except Exception as e:
        return {"error": str(e), "note": "运行一次流水线以生成 vPlan 数据"}


@app.get("/api/coverage/diff")
async def coverage_diff(run_id_1: str = "", run_id_2: str = ""):
    """比较两次回归的覆盖率变化"""
    from pathlib import Path
    import json

    def load_cov(run_id: str) -> dict:
        for ef in sorted(Path("output").glob("**/evidence_chain.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                data = json.loads(ef.read_text(encoding="utf-8"))
                if run_id in data.get("run_id", ""):
                    cov = {}
                    for layer in data.get("layers", {}).values():
                        for item in layer.get("items", []):
                            detail = item.get("detail", {})
                            if "line" in detail:
                                cov = detail
                    return cov
            except Exception:
                pass
        return {}

    cov1 = load_cov(run_id_1) if run_id_1 else {}
    cov2 = load_cov(run_id_2) if run_id_2 else {}

    diff = {}
    for key in ["line", "branch", "toggle"]:
        v1 = cov1.get(key, 0)
        v2 = cov2.get(key, 0)
        diff[key] = {"before": v1, "after": v2, "delta": round(v2 - v1, 1),
                      "trend": "up" if v2 > v1 else ("down" if v2 < v1 else "flat")}

    return {"run_1": run_id_1, "run_2": run_id_2, "coverage_diff": diff,
            "summary": f"Line: {diff['line']['delta']:+.1f}%, Branch: {diff['branch']['delta']:+.1f}%, Toggle: {diff['toggle']['delta']:+.1f}%"}


# ═══════════════════════════════════════════════════════════
# 项目访问控制 & 签核状态机
# ═══════════════════════════════════════════════════════════

async def require_project_access(project_id: int = 0, user: dict = Depends(require_auth)):
    """验证用户是否有指定项目的访问权限。无 project_id 则跳过检查。"""
    if not project_id:
        return user
    if user.get("role") in ("admin", "verification_manager"):
        return user
    from src.database.repository import list_projects, add_audit_log
    projects = await list_projects(user["user_id"])
    if project_id not in {p["id"] for p in projects}:
        try: await add_audit_log(user["user_id"], user.get("username",""), "access_denied", f"project/{project_id}", "项目访问被拒绝")
        except Exception: pass
        raise HTTPException(status_code=403, detail="无权访问该项目")
    return user


SIGNOFF_TRANSITIONS = {
    "draft":   ["pending", "deleted"],
    "pending": ["approved", "rejected", "draft"],
    "approved": [],
    "rejected": ["draft", "pending"],
    "deleted":  [],
}


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
async def login(req: LoginRequest, request: Request = None):
    # 速率限制检查
    try:
        from src.infra.security import get_rate_limiter, RATE_LIMITS
        limiter = get_rate_limiter()
        ip = request.client.host if request else "unknown"
        result = limiter.check(f"login:{ip}",
                               max_calls=RATE_LIMITS["login"]["max_calls"],
                               window_s=RATE_LIMITS["login"]["window_s"])
        if not result.allowed:
            raise HTTPException(status_code=429, detail=f"登录尝试过于频繁，请 {result.retry_after_s:.0f} 秒后重试")
    except HTTPException: raise
    except Exception: pass

    from src.database.repository import get_user_by_username, update_user_login, update_user_password, add_audit_log
    user = await get_user_by_username(req.username)
    if not user or not verify_password(req.password, user.password_hash):
        # Log failed attempt
        ip = request.client.host if request else "unknown"
        try: await add_audit_log(0, req.username, "login_failed", "auth", f"IP: {ip}")
        except Exception: pass
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if password_needs_rehash(user.password_hash):
        await update_user_password(user.id, hash_password(req.password))
    await update_user_login(user.id)
    token = create_token(user.id, user.username, user.role)
    # Log successful login
    ip = request.client.host if request else "unknown"
    try: await add_audit_log(user.id, user.username, "login_success", "auth", f"IP: {ip}")
    except Exception: pass
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
async def pipeline_run(req: PipelineRunRequest, user: dict = Depends(require_auth),
                       _perm: dict = Depends(lambda: None)):
    """启动验证流水线——立即返回 run_id，后台异步执行。"""
    spec_text = req.spec_text
    if not spec_text and req.spec_file:
        p = _resolve_spec_path(req.spec_file)
        if p.exists():
            if p.stat().st_size > MAX_DOCUMENT_BYTES:
                raise HTTPException(status_code=413, detail="spec file is too large")
            spec_text = p.read_text(encoding="utf-8")
    if not spec_text: raise HTTPException(status_code=400, detail="spec_text required")
    service = PipelineExecutionService.get_instance()
    if not service.initialized:
        await service.initialize_agents()

    # 生成 run_id 并立即创建 DB 记录
    import uuid
    run_id = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    output_root = str(_resolve_output_path(req.output_dir))

    # 记录 run_type 到 ctx（供 manifest 使用）
    service._run_types = getattr(service, '_run_types', {})
    service._run_types[run_id] = req.run_type

    # 后台执行流水线
    async def _run():
        started = __import__('time').time()
        try:
            await service.run_pipeline(spec_text=spec_text, workflow=req.workflow,
                                       output_root=output_root, run_id=run_id)
            # 记录可观测性指标
            try:
                duration = __import__('time').time() - started
                from src.infra.observability import get_metrics
                state_obj = service.get_run_status(run_id) or {}
                phases = state_obj.get("phases", [])
                get_metrics().record_pipeline_run(
                    run_id=run_id, workflow=req.workflow,
                    state=state_obj.get("state", "completed"),
                    duration_s=duration,
                    phases_total=len(phases),
                    phases_passed=sum(1 for p in phases if p.get("status") == "passed"),
                    phases_failed=sum(1 for p in phases if p.get("status") in ("failed", "error")),
                    started_at=str(state_obj.get("started_at", "")),
                    completed_at=str(state_obj.get("completed_at", ""))
                )
            except Exception: pass

            # 发布事件
            try:
                from src.infra.event_bus import get_event_bus, StandardEvent
                bus = get_event_bus()
                state_obj = service.get_run_status(run_id) or {}
                if state_obj.get("state") == "completed_with_errors":
                    await bus.publish(StandardEvent.PIPELINE_FAILED,
                                      {"run_id": run_id, "workflow": req.workflow,
                                       "error": "Pipeline completed with errors"},
                                      source="api.pipeline")
                else:
                    await bus.publish(StandardEvent.PIPELINE_COMPLETED,
                                      {"run_id": run_id, "workflow": req.workflow,
                                       "project_id": 0},
                                      source="api.pipeline")
            except Exception: pass
        except Exception as e:
            logger.error("pipeline background task failed", run_id=run_id, error=str(e))

    asyncio.create_task(_run())

    # 审计日志（仅记录启动）
    from src.database.repository import add_audit_log
    await add_audit_log(user["user_id"], user["username"], "pipeline_run", run_id,
                        f"workflow={req.workflow} started")
    return {"run_id": run_id, "workflow": req.workflow, "status": "started", "run_type": req.run_type}


@app.get("/api/pipeline/{run_id}/stream")
async def pipeline_sse_stream(run_id: str):
    """SSE 实时推送管线状态（供前端 EventSource 连接）"""
    from src.web.sse import subscribe, unsubscribe

    async def event_generator():
        q = await subscribe(run_id)
        try:
            # 先发当前快照
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
                    # Check if still running
                    state = service.get_run_status(run_id)
                    if state and state.get("state") in ("completed", "completed_with_errors"):
                        yield f"data: {json.dumps({'event': 'run_complete', 'data': state}, ensure_ascii=False)}\n\n"
                        break
        except asyncio.CancelledError:
            pass
        finally:
            unsubscribe(run_id, q)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )

@app.get("/api/pipeline/history")
async def pipeline_history(limit: int = 20):
    from src.database.repository import get_recent_pipelines
    return {"runs": await get_recent_pipelines(limit)}

@app.get("/api/pipeline/run/{run_id}")
async def pipeline_run_status(run_id: str):
    """查询单个运行状态（内存优先，重启后 DB 回退）。"""
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


@app.get("/api/pipeline/run/{run_id}/stream")
async def pipeline_stream(run_id: str):
    """SSE 流式推送运行状态。优先读内存（运行中），服务重启后回退到 DB。"""
    service = PipelineExecutionService.get_instance()
    async def gen():
        last = 0
        for _ in range(900):  # max 15 min
            s = service.get_run_status(run_id)
            # 内存中没有 → DB 回退
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
    base = _resolve_output_path(output_dir)
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
    test_dir = _resolve_within(_resolve_output_path(output_dir), test_name)
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
    result = await service.generate_testcases(spec_text=spec_text, output_dir=str(_resolve_output_path(req.output_dir)))
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
    # 生产模式：读取真实 run 的 ctx.coverage
    if os.environ.get("APP_MODE", "demo").lower() != "demo":
        service = PipelineExecutionService.get_instance()
        # 尝试从最近的 run 获取
        runs = service.list_runs()
        if runs:
            run = service._runs.get(runs[-1]["run_id"], {})
            ctx = run.get("ctx", {})
            cov = ctx.get("coverage", {}) if hasattr(ctx, 'get') else {}
            if isinstance(cov, dict) and cov.get("line_pct"):
                return {
                    "line_pct": cov.get("line_pct", 0),
                    "branch_pct": cov.get("branch_pct", 0),
                    "toggle_pct": cov.get("toggle_pct", 0),
                    "coverage_pct": cov.get("coverage_pct", 0),
                    "gaps": cov.get("gaps", []),
                    "suggestions": cov.get("suggestions", []),
                    "_source": "run_result",
                }

    # 演示模式：返回 DEMO 标记的数据
    return {
        "code_coverage": 92.3, "functional_coverage": 78.5, "assertion_coverage": 56.2, "_demo": True,
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
    """回归执行 —— demo 模式返回模拟数据，生产模式调用真实 RegressionManager。"""
    if os.environ.get("APP_MODE", "demo").lower() == "demo":
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
                              "completed", passed, failed, 0, len(tests), duration, {"results": results, "_demo": True})
        from src.database.repository import add_audit_log
        await add_audit_log(user["user_id"], user["username"], "regression_run", "", f"{passed}/{len(tests)} passed (demo)")
        return {"status": "completed", "passed": passed, "failed": failed, "total": len(tests),
                "duration": duration, "results": results, "_demo": True}

    # ── 生产模式：调用真实 RegressionManager ──
    service = PipelineExecutionService.get_instance()
    result = await service.run_single_agent("regression_manager", json.dumps({"retry": False}))
    from src.database.repository import add_audit_log
    await add_audit_log(user["user_id"], user["username"], "regression_run", "", str(result.get("output", ""))[:200])
    return {"success": result["success"], "output": result.get("output", ""), "error": result.get("error")}

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
    # Gather evidence info
    run_id = ""; manifest_hash = ""
    try:
        from pathlib import Path; import json
        for mf in sorted(Path("output").glob("**/docs/manifest.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            data = json.loads(mf.read_text(encoding="utf-8"))
            run_id = data.get("run_id", "")
            manifest_hash = data.get("manifest_hash", "")
            break
    except Exception: pass

    sid = await create_signoff(req.project_id, req.title, req.report_type,
                                req.summary, user["user_id"],
                                run_id=run_id, manifest_hash=manifest_hash)
    await add_audit_log(user["user_id"], user["username"], "signoff_create", str(sid),
                        req.title, role=user.get("role", ""),
                        resource_type="signoff", is_privileged=True)
    return {"id": sid, "status": "pending", "run_id": run_id}

@app.put("/api/signoffs/{sid}/approve")
async def approve_signoff(sid: int, comment: str = "", user: dict = Depends(require_auth)):
    """批准签核 — 仅管理员和验证经理，自动记录审批事件和审计日志"""
    user_role = user.get("role", "")
    if user_role not in ("admin", "verification_manager"):
        # 越权尝试审计
        from src.database.repository import add_audit_log
        await add_audit_log(user["user_id"], user["username"], "signoff_approve_denied", str(sid),
                            f"越权尝试批准签核", role=user_role, resource_type="signoff",
                            access_result="denied", is_privileged=True)
        raise HTTPException(status_code=403, detail="仅 SignOff 经理可以批准签核")

    from src.database.repository import update_signoff, add_audit_log, get_signoff_by_id
    sf = await get_signoff_by_id(sid)
    if not sf:
        raise HTTPException(status_code=404, detail="签核记录不存在")
    if sf.get("status") not in ("pending",):
        raise HTTPException(status_code=400, detail=f"签核状态 '{sf.get('status')}' 不可批准，仅 pending 状态可批准")

    ok = await update_signoff(sid, "approved", user["user_id"], comment,
                              approver_name=user.get("display_name", user["username"]))

    # 增强审计日志 — 记录角色上下文和状态变更
    await add_audit_log(
        user["user_id"], user["username"], "signoff_approve", str(sid),
        f"状态: pending->approved | 意见: {comment[:100]}",
        role=user_role, resource_type="signoff",
        access_result="success", is_privileged=True,
        before_state="pending", after_state="approved"
    )

    # 发布事件 + 记录签核周期指标
    try:
        from src.infra.event_bus import get_event_bus, StandardEvent
        bus = get_event_bus()
        await bus.publish(StandardEvent.SIGNOFF_APPROVED, {
            "signoff_id": sid, "approver": user["username"],
            "evidence_hash": sf.get("manifest_hash", ""),
            "user_id": user["user_id"], "role": user_role,
        }, source="api.signoff")
    except Exception: pass

    # 触发工作流
    try:
        from src.infra.workflow_triggers import get_trigger_service
        svc = get_trigger_service()
        await svc.evaluate("signoff_approved", {
            "signoff_id": sid, "project_id": sf.get("project_id", 0),
            "approver": user.get("username", ""), "role": user_role,
        })
    except Exception: pass

    try:
        from src.infra.observability import get_metrics
        created = sf.get("created_at", "")
        if created:
            from datetime import datetime as dt
            c_time = dt.fromisoformat(str(created))
            cycle_min = (dt.now() - c_time).total_seconds() / 60
            get_metrics().record_signoff_cycle(sid, sf.get("title", ""), "approved",
                                                cycle_min, user["username"],
                                                created_at=str(created),
                                                approved_at=dt.now().isoformat())
    except Exception: pass

    return {"ok": ok, "status": "approved", "locked": True}

@app.put("/api/signoffs/{sid}/reject")
async def reject_signoff(sid: int, comment: str = "", user: dict = Depends(require_auth)):
    """驳回签核 — 仅管理员和验证经理，自动记录驳回事件"""
    user_role = user.get("role", "")
    if user_role not in ("admin", "verification_manager"):
        from src.database.repository import add_audit_log
        await add_audit_log(user["user_id"], user["username"], "signoff_reject_denied", str(sid),
                            f"越权尝试驳回签核", role=user_role, resource_type="signoff",
                            access_result="denied", is_privileged=True)
        raise HTTPException(status_code=403, detail="仅 SignOff 经理可以驳回签核")

    from src.database.repository import update_signoff, add_audit_log, get_signoff_by_id
    sf = await get_signoff_by_id(sid)
    if not sf:
        raise HTTPException(status_code=404, detail="签核记录不存在")
    if sf.get("status") not in ("pending",):
        raise HTTPException(status_code=400, detail=f"签核状态 '{sf.get('status')}' 不可驳回，仅 pending 状态可驳回")

    ok = await update_signoff(sid, "rejected", user["user_id"], comment, reject_reason=comment)
    await add_audit_log(
        user["user_id"], user["username"], "signoff_reject", str(sid),
        f"状态: pending->rejected | 理由: {comment[:100]}",
        role=user_role, resource_type="signoff",
        access_result="success", is_privileged=True,
        before_state="pending", after_state="rejected"
    )

    # 发布事件
    try:
        from src.infra.event_bus import get_event_bus, StandardEvent
        bus = get_event_bus()
        await bus.publish(StandardEvent.SIGNOFF_REJECTED, {
            "signoff_id": sid, "reason": comment,
            "user_id": user["user_id"], "role": user_role,
        }, source="api.signoff")
    except Exception: pass

    # 触发工作流
    try:
        from src.infra.workflow_triggers import get_trigger_service
        svc = get_trigger_service()
        await svc.evaluate("signoff_rejected", {
            "signoff_id": sid, "project_id": sf.get("project_id", 0),
            "reason": comment, "rejected_by": user.get("username", ""),
        })
    except Exception: pass

    return {"ok": ok, "status": "rejected"}

# ═══════════════════════════════════════════════════════════
# Manifest / 证据链 API (SignOffAI 核心)
# ═══════════════════════════════════════════════════════════

@app.get("/api/manifest/latest")
async def get_latest_manifest():
    """获取最新的 manifest 摘要（供前端签核页面展示证据链）"""
    from pathlib import Path
    import json
    # 扫描 output 目录寻找最新的 manifest.json
    docs_dirs = sorted(Path("output").glob("**/docs/manifest.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if docs_dirs:
        try:
            return json.loads(docs_dirs[0].read_text(encoding="utf-8"))
        except Exception:
            pass
    # fallback: 扫描所有 output 子目录
    fallback = sorted(Path("output").glob("*/docs/manifest.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if fallback:
        try:
            return json.loads(fallback[0].read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"error": "no manifest found", "run_id": "", "session_id": ""}


@app.get("/api/manifest/{session_id}")
async def get_manifest(session_id: str):
    """获取指定 session 的完整 manifest"""
    from pathlib import Path
    import json
    for pattern in [f"**/{session_id}/**/manifest.json", f"**/docs/manifest.json"]:
        for mf in Path("output").glob(pattern):
            try:
                data = json.loads(mf.read_text(encoding="utf-8"))
                if data.get("session_id") == session_id:
                    return data
            except Exception:
                pass
    # 尝试从 execution logs 重建
    try:
        from src.core.manifest import build_manifest, list_sessions
        manifest = build_manifest(session_id)
        return json.loads(ManifestBuilder().to_json(manifest))
    except Exception:
        raise HTTPException(status_code=404, detail=f"Manifest not found for session {session_id}")


@app.get("/api/manifest/{session_id}/export")
async def export_evidence_package(session_id: str, user: dict = Depends(get_current_user)):
    """导出签核证据包 (zip)"""
    import tempfile
    from pathlib import Path
    from fastapi.responses import FileResponse

    try:
        from src.core.manifest import export_evidence_package as export_pkg
        from src.database.repository import add_audit_log
        # 审计：证据包导出
        username = user.get("username", "anonymous") if user else "anonymous"
        uid = user.get("user_id", 0) if user else 0
        try: await add_audit_log(uid, username, "evidence_export", session_id, "证据包导出")
        except Exception: pass

        tmp_dir = Path(tempfile.mkdtemp())
        zip_path = tmp_dir / f"signoffai_evidence_{session_id}.zip"
        result = export_pkg(session_id, str(zip_path))
        return FileResponse(
            path=str(result),
            media_type="application/zip",
            filename=f"signoffai_evidence_{session_id}.zip",
            headers={"X-Evidence-Hash": "See manifest.json in archive"},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Evidence export failed: {e}")


@app.get("/api/manifest")
async def list_manifests():
    """列出所有 manifest sessions"""
    from src.core.manifest import list_sessions
    return {"sessions": list_sessions()}


@app.get("/api/engines/latest")
async def get_latest_engines():
    """获取五大差异化引擎的最新输出"""
    from pathlib import Path
    import json
    for ef in sorted(Path("output").glob("**/docs/engines.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            return json.loads(ef.read_text(encoding="utf-8"))
        except Exception:
            pass
    raise HTTPException(status_code=404, detail="No engines output found — run vagent verify first")


# ═══════════════════════════════════════════════════════════
# 五大引擎独立 API
# ═══════════════════════════════════════════════════════════

@app.post("/api/engines/vplan")
async def generate_vplan(spec_text: str = "", module_name: str = ""):
    """从 MD 规格自动生成验证计划"""
    from src.core.engines import VPlanGenerator
    gen = VPlanGenerator()
    vplan = gen.generate(spec_text, module_name)
    return {
        "module": module_name or "auto",
        "requirements": [{"id": r["id"], "description": r["description"]} for r in vplan.requirements],
        "coverage_points": [{"name": cp.name, "description": cp.description, "category": cp.category, "target": cp.target} for cp in vplan.coverage_points],
        "testcases": [{"name": tc.name, "description": tc.description, "level": tc.level, "coverage_points": tc.coverage_points} for tc in vplan.testcases],
        "risk_items": vplan.risk_items,
        "coverage_targets": vplan.coverage_targets,
        "signoff_criteria": vplan.signoff_criteria,
        "traceability": vplan.traceability_matrix,
    }


@app.post("/api/engines/smart-regression")
async def smart_regression(coverage_data: dict = None, testcases: List[dict] = None):
    """覆盖率驱动的智能回归选择"""
    from src.core.engines import CoverageDrivenRegressor
    reg = CoverageDrivenRegressor(coverage_data or {}, testcases or [])
    plan = reg.select()
    return {
        "selected": plan.selected_tests,
        "skipped": plan.skipped_tests,
        "gaps_addressed": plan.coverage_gaps_addressed,
        "estimated_runtime": plan.estimated_runtime,
        "original_runtime": plan.original_runtime,
        "time_saved_pct": plan.time_saved_pct,
    }


@app.post("/api/engines/debug")
async def debug_copilot(log_text: str = ""):
    """仿真日志自动分析 + 根因定位"""
    from src.core.engines import DebugCopilot
    copilot = DebugCopilot()
    insights = copilot.analyze(log_text)
    return {
        "insights": [{"type": i.error_type, "location": i.location, "root_cause": i.root_cause, "suggested_fix": i.suggested_fix, "confidence": i.confidence, "auto_fixable": i.auto_fixable} for i in insights],
        "time_saved": copilot.time_saved_estimate(insights),
        "total_insights": len(insights),
    }


@app.post("/api/engines/triage")
async def regression_triage(failed_logs: List[dict] = None):
    """批量回归智能研判"""
    from src.core.engines import RegressionTriage
    triage = RegressionTriage()
    result = triage.classify(failed_logs or [])
    return {
        "total": result.total, "failed": result.failed,
        "root_causes": result.root_causes,
        "recommended_actions": result.recommended_actions,
        "estimated_manual_time": result.estimated_manual_time,
        "estimated_ai_time": result.estimated_ai_time,
    }


@app.get("/api/evidence/latest")
async def get_latest_evidence():
    """获取最新证据链"""
    from pathlib import Path
    import json
    for ef in sorted(Path("output").glob("**/evidence_chain.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            return json.loads(ef.read_text(encoding="utf-8"))
        except Exception:
            pass
    raise HTTPException(status_code=404, detail="No evidence chain found")


@app.get("/api/evidence/{run_id}")
async def get_evidence_chain(run_id: str):
    """获取指定 run 的 5 层证据链"""
    from pathlib import Path
    import json
    for ef in sorted(Path("output").glob("**/evidence_chain.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            data = json.loads(ef.read_text(encoding="utf-8"))
            rid = data.get("run_id", "")
            if rid == run_id or run_id in rid or rid.endswith(run_id[-12:]):
                return data
        except Exception:
            pass
    raise HTTPException(status_code=404, detail=f"Evidence chain not found for {run_id}")


@app.get("/api/manifest/{session_id}/verify")
async def verify_manifest_integrity(session_id: str):
    """验证证据包完整性：检查 manifest hash、阶段 hash、文件是否缺失或被篡改"""
    from pathlib import Path
    import json, hashlib

    result = {
        "session_id": session_id,
        "valid": False,
        "manifest_hash_ok": False,
        "evidence_hash_ok": False,
        "phases_complete": False,
        "file_count": 0,
        "missing_files": [],
        "hash_mismatches": [],
        "issues": [],
    }

    # 查找 manifest — 多种路径模式
    manifest_data = None
    manifest_path = None
    patterns = [f"**/{session_id}/**/manifest.json", "**/docs/manifest.json", "**/manifest.json"]
    for pattern in patterns:
        for mf in sorted(Path("output").glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                data = json.loads(mf.read_text(encoding="utf-8"))
                if (data.get("session_id") == session_id
                    or data.get("run_id") == session_id
                    or (data.get("run_id", "").endswith(session_id[-6:]) and len(session_id) >= 6)):
                    manifest_data = data
                    manifest_path = mf
                    break
            except Exception:
                pass
        if manifest_data:
            break

    if not manifest_data:
        result["issues"].append("Manifest not found")
        return result

    # 1. Manifest hash 自校验
    stored_hash = manifest_data.get("manifest_hash", "")
    calc_data = {k: v for k, v in manifest_data.items() if k != "manifest_hash"}
    from src.core.manifest import hash_json
    calc_hash = hash_json(calc_data)
    result["manifest_hash_ok"] = stored_hash == calc_hash
    if not result["manifest_hash_ok"]:
        result["issues"].append("Manifest hash mismatch — evidence may be tampered")

    # 2. 阶段完整性
    phases = manifest_data.get("phases", [])
    total = manifest_data.get("total_phases", len(phases))
    result["phases_complete"] = len(phases) == total
    result["total_phases"] = total
    result["phases_completed"] = len(phases)
    skipped = sum(1 for p in phases if p.get("status") == "skipped")
    result["phases_passed"] = sum(1 for p in phases if p.get("status") == "passed")
    result["phases_failed"] = sum(1 for p in phases if p.get("status") in ("failed", "error"))
    result["phases_degraded"] = sum(1 for p in phases if p.get("status") == "degraded")
    result["phases_skipped"] = skipped

    # 3. 文件完整性
    output_root = manifest_data.get("output_root", "")
    output_path = Path(output_root)
    if not output_path.is_absolute():
        output_path = Path(os.getcwd()) / output_root
    if output_root and output_path.exists():
        all_files = []
        for f in output_path.rglob("*"):
            if f.is_file() and not f.name.startswith("."):
                all_files.append(f)
        result["file_count"] = len(all_files)

        # Check against phase artifacts
        for p in phases:
            for art in p.get("artifacts", []):
                art_path = output_path / art
                if not art_path.exists():
                    result["missing_files"].append(art)
                else:
                    expected_hash = p.get("artifact_hashes", {}).get(art, "")
                    if expected_hash:
                        actual = hashlib.sha256(art_path.read_bytes()).hexdigest()
                        if actual != expected_hash:
                            result["hash_mismatches"].append({"file": art, "expected": expected_hash[:16], "actual": actual[:16]})

    # 4. Evidence hash 校验
    stored_evidence = manifest_data.get("evidence_hash", "")
    if stored_evidence and result["file_count"] > 0:
        from src.core.manifest import ManifestBuilder
        mb = ManifestBuilder()
        files_list = [str(f.relative_to(output_root)) for f in output_path.rglob("*") if f.is_file()]
        calc_evidence = mb._compute_aggregate_hash(output_path, files_list)
        result["evidence_hash_ok"] = stored_evidence == calc_evidence

    result["valid"] = (
        result["manifest_hash_ok"]
        and len(result["missing_files"]) == 0
        and len(result["hash_mismatches"]) == 0
    )

    # 5. 结论
    if result["valid"]:
        result["conclusion"] = "🟢 证据链完整，未被篡改"
    elif result["manifest_hash_ok"]:
        result["conclusion"] = "🟡 证据链部分可验证，存在文件缺失或变更"
    else:
        result["conclusion"] = "🔴 证据链已被篡改或损坏"

    return result


# ═══════════════════════════════════════════════════════════
# 版本管理 API — RTL/UVM/Env 代码版本追踪
# ═══════════════════════════════════════════════════════════

@app.get("/api/versions")
async def list_versions():
    """列出所有 pipeline run 作为版本记录，包含 RTL/UVM hash"""
    from pathlib import Path
    import json, hashlib
    versions = []
    seen = set()

    for mf in sorted(Path("output").glob("**/docs/manifest.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            data = json.loads(mf.read_text(encoding="utf-8"))
            run_id = data.get("run_id", "")
            if not run_id or run_id in seen:
                continue
            seen.add(run_id)

            # 提取各阶段产物 hash
            rtl_hash = uvm_hash = model_hash = ""
            file_count = data.get("output_file_count", 0)
            for p in data.get("phases", []):
                ah = p.get("artifact_hashes", {})
                if p.get("phase_name") == "design" and ah:
                    rtl_hash = list(ah.values())[0] if ah else ""
                elif p.get("phase_name") == "UVM" and ah:
                    uvm_hash = list(ah.values())[0] if ah else ""
                elif p.get("phase_name") == "model" and ah:
                    model_hash = list(ah.values())[0] if ah else ""

            versions.append({
                "run_id": run_id,
                "workflow": data.get("workflow", ""),
                "state": data.get("state", ""),
                "started_at": data.get("started_at", ""),
                "total_phases": data.get("total_phases", 0),
                "passed": data.get("passed", 0),
                "overall_score": data.get("overall_score", 0),
                "evidence_hash": data.get("evidence_hash", ""),
                "manifest_hash": data.get("manifest_hash", ""),
                "rtl_hash": rtl_hash,
                "uvm_hash": uvm_hash,
                "model_hash": model_hash,
                "file_count": file_count,
            })
        except Exception:
            pass

    return {"versions": versions}


@app.get("/api/versions/{run_id}")
async def get_version_detail(run_id: str):
    """获取某个版本的详细信息，包含完整文件清单及 hash"""
    from pathlib import Path
    import json, hashlib

    for mf in sorted(Path("output").glob("**/docs/manifest.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            data = json.loads(mf.read_text(encoding="utf-8"))
            if data.get("run_id") != run_id:
                continue

            # 按阶段分组文件
            phase_files = {}
            for p in data.get("phases", []):
                pname = p.get("phase_name", "")
                artifacts = p.get("artifacts", [])
                hashes = p.get("artifact_hashes", {})
                if artifacts:
                    phase_files[pname] = {
                        "status": p.get("status", ""),
                        "score": p.get("score", 0),
                        "elapsed_s": p.get("elapsed_s", 0),
                        "files": [{"path": a, "hash": hashes.get(a, "")} for a in artifacts],
                    }

            # 扫描实际产物目录
            output_root = data.get("output_root", "")
            actual_files = []
            if output_root and output_path.exists():
                for f in sorted(output_path.rglob("*")):
                    if f.is_file() and not f.name.startswith("."):
                        rel = str(f.relative_to(output_root))
                        sha = hashlib.sha256(f.read_bytes()).hexdigest()
                        actual_files.append({
                            "path": rel,
                            "hash": sha,
                            "size": f.stat().st_size,
                        })

            return {
                "run_id": run_id,
                "workflow": data.get("workflow", ""),
                "started_at": data.get("started_at", ""),
                "completed_at": data.get("completed_at", ""),
                "evidence_hash": data.get("evidence_hash", ""),
                "manifest_hash": data.get("manifest_hash", ""),
                "phases": data.get("phases", []),
                "phase_files": phase_files,
                "files": actual_files[:200],  # 截断
                "total_files": len(actual_files),
            }
        except Exception:
            pass

    raise HTTPException(status_code=404, detail=f"Version not found: {run_id}")


# ═══════════════════════════════════════════════════════════
# 多模块聚合 API — SignOff 经理总览
# ═══════════════════════════════════════════════════════════

@app.get("/api/modules")
async def list_modules():
    """聚合所有模块的 AI 验证进展 — SignOff 经理总览"""
    from pathlib import Path
    import json, hashlib
    from datetime import datetime

    modules = {}
    # 从 specs/ 目录发现所有模块
    specs_dir = SPECS_DIR
    if specs_dir.exists():
        for md_file in sorted(specs_dir.glob("**/*.md")):
            # 提取模块名 = 目录名
            mod_name = md_file.parent.name if md_file.parent != specs_dir else md_file.stem
            if mod_name not in modules:
                modules[mod_name] = {
                    "name": mod_name,
                    "specs": [],
                    "runs": [],
                    "latest_status": "unknown",
                    "latest_score": 0,
                    "latest_passed": 0,
                    "latest_total": 0,
                    "latest_time": "",
                    "evidence_hash": "",
                    "coverage": {"line": 0, "branch": 0, "toggle": 0},
                }
            modules[mod_name]["specs"].append({
                "file": md_file.name,
                "path": str(md_file.relative_to(specs_dir)),
                "modified": datetime.fromtimestamp(md_file.stat().st_mtime).isoformat(),
            })

    # 从 manifest 聚合运行数据
    for mf in sorted(Path("output").glob("**/docs/manifest.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            data = json.loads(mf.read_text(encoding="utf-8"))
            run_id = data.get("run_id", "")
            metadata = data.get("metadata", {})

            # 尝试从 ctx 推断模块名
            mod_name = "default"
            ctx_keys = metadata.get("ctx_keys", [])
            if isinstance(ctx_keys, list) and ctx_keys:
                spec_data = None
                # Try to find spec data with design_name
                for k in ctx_keys:
                    pass  # can't easily extract from ctx here

            # 从 manifest 阶段数据推断
            for p in data.get("phases", []):
                ah = p.get("artifact_hashes", {})
                artifacts = p.get("artifacts", [])

            # 用 output_root 的父目录作为模块名
            out_root = Path(data.get("output_root", ""))
            if out_root.parts:
                # output/<spec_name>/... 或 output/<run_id>/...
                idx = 0
                for i, part in enumerate(out_root.parts):
                    if part == "output" and i + 1 < len(out_root.parts):
                        idx = i + 1
                pot_name = out_root.parts[idx] if idx < len(out_root.parts) else out_root.name
                if pot_name not in ("output", "docs", ""):
                    mod_name = pot_name

            if mod_name not in modules:
                modules[mod_name] = {"name": mod_name, "specs": [], "runs": [],
                                    "latest_status": "unknown", "latest_score": 0,
                                    "latest_passed": 0, "latest_total": 0, "latest_time": "",
                                    "evidence_hash": "", "coverage": {"line": 0, "branch": 0, "toggle": 0}}

            modules[mod_name]["runs"].append({
                "run_id": run_id,
                "workflow": data.get("workflow", ""),
                "state": data.get("state", ""),
                "passed": data.get("passed", 0),
                "total": data.get("total_phases", 0),
                "score": data.get("overall_score", 0),
                "started_at": data.get("started_at", ""),
                "evidence_hash": data.get("evidence_hash", ""),
            })

            # 更新最新状态
            if not modules[mod_name]["latest_time"] or data.get("started_at", "") > modules[mod_name]["latest_time"]:
                modules[mod_name]["latest_status"] = data.get("state", "unknown")
                modules[mod_name]["latest_score"] = data.get("overall_score", 0)
                modules[mod_name]["latest_passed"] = data.get("passed", 0)
                modules[mod_name]["latest_total"] = data.get("total_phases", 0)
                modules[mod_name]["latest_time"] = data.get("started_at", "")
                modules[mod_name]["evidence_hash"] = data.get("evidence_hash", "")

                # 提取覆盖率
                cov = metadata.get("coverage", {})
                if isinstance(cov, dict):
                    modules[mod_name]["coverage"] = {
                        "line": cov.get("line_pct", 0),
                        "branch": cov.get("branch_pct", 0),
                        "toggle": cov.get("toggle_pct", 0),
                    }

        except Exception:
            pass

    # 计算整体统计
    all_modules = list(modules.values())
    for m in all_modules:
        m["runs"] = m["runs"][:5]  # 只保留最近 5 次
        m["run_count"] = len(m["runs"])

    total_runs = sum(m["run_count"] for m in all_modules)
    total_passed = sum(1 for m in all_modules if m["latest_status"] == "completed" and m["latest_passed"] == m["latest_total"])
    total_with_errors = sum(1 for m in all_modules if m["latest_status"] == "completed_with_errors")
    total_active = sum(1 for m in all_modules if m["latest_status"] in ("running",))

    return {
        "modules": all_modules,
        "total_modules": len(all_modules),
        "total_runs": total_runs,
        "total_passed": total_passed,
        "total_with_errors": total_with_errors,
        "total_active": total_active,
        "overall_health": "good" if total_passed == len(all_modules) and len(all_modules) > 0 else (
            "warning" if total_passed > 0 or total_with_errors > 0 else "idle"),
    }


@app.get("/api/modules/{module_name}")
async def get_module_detail(module_name: str):
    """获取单个模块的详细验证进展"""
    data = await list_modules()
    for m in data.get("modules", []):
        if m["name"] == module_name:
            return m
    raise HTTPException(status_code=404, detail=f"Module not found: {module_name}")


# ═══════════════════════════════════════════════════════════
# 模块分配 & 权限过滤 API
# ═══════════════════════════════════════════════════════════

@app.get("/api/my-modules")
async def list_my_modules(user: dict = Depends(get_current_user)):
    """返回当前工程师负责的模块（经理可看全部）"""
    data = await list_modules()
    all_mods = data.get("modules", [])

    # 管理员和SignOff 经理看全部
    role = user.get("role", "") if user else ""
    if role in ("admin", "verification_manager"):
        return data

    # 工程师只看分配给自己（通过 ProjectMember）的模块
    user_id = user.get("user_id") if user else 0
    try:
        from src.database.repository import list_projects
        projects = await list_projects(user_id)
        assigned_names = {p["name"] for p in projects}
        my_mods = [m for m in all_mods if m["name"] in assigned_names]
        return {**data, "modules": my_mods, "total_modules": len(my_mods), "filtered": True}
    except Exception:
        # 无分配则返回空
        return {**data, "modules": [], "total_modules": 0, "filtered": True, "message": "无模块分配 — 请联系SignOff 经理"}


@app.post("/api/modules/assign")
async def assign_module(module_name: str = "", username: str = "", user: dict = Depends(require_auth)):
    """管理员/经理将工程师分配到模块 — 参数从 query string 读取"""
    if user.get("role") not in ("admin", "verification_manager"):
        raise HTTPException(status_code=403, detail="仅管理员和SignOff 经理可以分配模块")

    from src.database.repository import get_user_by_username, create_project, list_projects
    eng = await get_user_by_username(username)
    if not eng:
        raise HTTPException(status_code=404, detail=f"用户不存在: {username}")

    # 创建或获取 project（模块=项目）
    pid = None
    existing = await list_projects()
    for p in existing:
        if p["name"] == module_name:
            pid = p["id"]
            break

    if not pid:
        result = await create_project(module_name, f"AI 验证模块: {module_name}", user["user_id"])
        pid = result["id"]

    # 将工程师加入项目
    from src.database.connection import get_session
    from src.database.models import ProjectMember
    s = await get_session()
    from sqlalchemy import select
    existing_member = await s.execute(
        select(ProjectMember).where(ProjectMember.project_id == pid, ProjectMember.user_id == eng.id)
    )
    if not existing_member.scalar_one_or_none():
        s.add(ProjectMember(project_id=pid, user_id=eng.id, role="member"))
        await s.commit()
    await s.close()

    from src.database.repository import add_audit_log
    await add_audit_log(user["user_id"], user["username"], "module_assign",
                        module_name, f"分配工程师 {username}")

    return {"ok": True, "module": module_name, "engineer": username}


@app.get("/api/modules/{module_name}/members")
async def get_module_members(module_name: str):
    """查看模块的分配成员"""
    from src.database.repository import list_projects
    projects = await list_projects()
    pid = None
    for p in projects:
        if p["name"] == module_name:
            pid = p["id"]
            break
    if not pid:
        return {"members": [], "module": module_name}

    from src.database.connection import get_session
    from src.database.models import ProjectMember, User
    from sqlalchemy import select
    s = await get_session()
    result = await s.execute(select(ProjectMember).where(ProjectMember.project_id == pid))
    members = []
    for pm in result.scalars().all():
        u_result = await s.execute(select(User).where(User.id == pm.user_id))
        u = u_result.scalar_one_or_none()
        if u:
            members.append({"username": u.username, "display_name": u.display_name, "role": pm.role})
    await s.close()
    return {"module": module_name, "members": members}


# ═══════════════════════════════════════════════════════════
# Token 用量统计 API
# ═══════════════════════════════════════════════════════════

@app.get("/api/token-usage")
async def get_token_usage(days: int = 7):
    """汇总 Token 用量（从 execution logs 聚合）"""
    from pathlib import Path
    import json
    from datetime import datetime, timedelta

    cutoff = datetime.now() - timedelta(days=days)
    total_tokens = 0
    total_llm_calls = 0
    per_agent = {}
    daily = {}

    exec_dir = Path("logs/execution")
    if exec_dir.exists():
        for f in sorted(exec_dir.glob("exec_*.jsonl"), reverse=True):
            try:
                for line in f.read_text(encoding="utf-8").strip().split("\n"):
                    if not line.strip():
                        continue
                    evt = json.loads(line)
                    if evt.get("event") != "llm_call":
                        continue
                    ts = evt.get("timestamp", "")
                    if ts:
                        try:
                            evt_time = datetime.fromisoformat(ts)
                            if evt_time < cutoff:
                                continue
                        except Exception:
                            pass
                    tokens = evt.get("tokens", 0)
                    total_tokens += tokens
                    total_llm_calls += 1
                    agent = evt.get("agent", "unknown")
                    per_agent[agent] = per_agent.get(agent, 0) + tokens
                    day = ts[:10] if ts else "unknown"
                    daily[day] = daily.get(day, 0) + tokens
            except Exception:
                pass

    return {
        "total_tokens": total_tokens,
        "total_llm_calls": total_llm_calls,
        "period_days": days,
        "per_agent": per_agent,
        "daily": [{"date": k, "tokens": v} for k, v in sorted(daily.items())],
        "estimated_cost": round(total_tokens / 1000 * 0.002, 2),  # ~$0.002/1K tokens estimate
    }


# ═══════════════════════════════════════════════════════════
# AI 智能错误分析 (Human-in-the-loop)
# ═══════════════════════════════════════════════════════════

@app.post("/api/ai/analyze-error")
async def ai_analyze_error(phase_name: str = "", error_log: str = "", agent_role: str = ""):
    import re
    suggestions = []; category = "unknown"; summary = ""
    log_lower = error_log.lower()

    compile_errors = re.findall(r"\*\*\s*Error[:\s]*(.*?)(?=\n|$)", error_log, re.IGNORECASE)
    uvm_errors = re.findall(r"UVM_ERROR.*?(\S.*?)(?=\n|$)", error_log, re.IGNORECASE)
    uvm_fatals = re.findall(r"UVM_FATAL.*?(\S.*?)(?=\n|$)", error_log, re.IGNORECASE)

    if compile_errors:
        category = "compile"
        summary = f"编译阶段发现 {len(compile_errors)} 个错误"
        for err in compile_errors:
            ec = err.strip()[:200]
            if "could not find field" in ec.lower():
                field = re.search(r"field\s+'(\w+)'", ec, re.IGNORECASE)
                suggestions.append({"type":"missing_field","severity":"medium","diagnosis":f"接口信号 '{field.group(1) if field else 'unknown'}' 在目标模块中不存在","fix":"检查 interface 定义，确认信号名拼写正确，或从 driver/monitor 中移除对该信号的引用","auto_fixable":True})
            elif "undefined" in ec.lower():
                suggestions.append({"type":"undefined_identifier","severity":"high","diagnosis":f"未定义的标识符: '{ec[:80]}'","fix":"检查是否缺少 include 或 import","auto_fixable":False})
            else:
                suggestions.append({"type":"syntax_error","severity":"medium","diagnosis":ec,"fix":"请检查对应行号的语法","auto_fixable":False})

    if uvm_errors or uvm_fatals:
        category = category or "simulation"
        total = len(uvm_errors) + len(uvm_fatals)
        if not summary:
            summary = f"仿真阶段发现 {total} 个 UVM 错误 (ERROR:{len(uvm_errors)}, FATAL:{len(uvm_fatals)})"
        for err in (uvm_fatals + uvm_errors)[:5]:
            ec = err.strip()[:200]
            if "scoreboard" in ec.lower() and "mismatch" in ec.lower():
                suggestions.append({"type":"scoreboard_mismatch","severity":"high","diagnosis":"Scoreboard 比对失败：参考模型输出与 DUT 输出不一致","fix":"1. 检查 C++ 参考模型实现逻辑\n2. 检查 DUT RTL 运算逻辑\n3. 比对波形定位第一个不一致的 cycle\n4. 确认时序对齐","auto_fixable":False})
            elif "timeout" in ec.lower():
                suggestions.append({"type":"sim_timeout","severity":"high","diagnosis":"仿真超时 — 可能由死锁、无限循环或等待条件未满足导致","fix":"1. 增大 UVM_TIMEOUT 值\n2. 检查 phase objection\n3. 检查 driver 是否正确发送 sequence","auto_fixable":False})
            else:
                suggestions.append({"type":"uvm_error","severity":"medium","diagnosis":ec,"fix":"查看详细日志定位具体原因","auto_fixable":False})

    if not suggestions:
        category = "general"
        summary = "未识别到已知错误模式，建议人工审查日志"
        key_lines = [l.strip() for l in error_log.split("\n") if "error" in l.lower() or "fail" in l.lower() or "fatal" in l.lower()][:5]
        if key_lines:
            suggestions.append({"type":"unknown","severity":"medium","diagnosis":"日志中包含以下可疑行:\n" + "\n".join(key_lines),"fix":"建议将完整日志提交给SignOff 经理进行人工分析","auto_fixable":False})

    return {"category":category,"summary":summary,"phase":phase_name,"agent":agent_role,"suggestions":suggestions,"suggestion_count":len(suggestions),"auto_fixable_count":sum(1 for s in suggestions if s.get("auto_fixable")),"timestamp":datetime.now().isoformat()}


# ═══════════════════════════════════════════════════════════
# 门限双轨 API — AI 找方向 + 传统盖章
# ═══════════════════════════════════════════════════════════

@app.get("/api/modules/{module_name}/gating")
async def get_module_gating(module_name: str):
    """获取模块的门限双轨状态：传统已验证 + AI 待验证"""
    data = await list_modules()
    module = None
    for m in data.get("modules", []):
        if m["name"] == module_name:
            module = m
            break
    if not module:
        raise HTTPException(status_code=404, detail=f"Module not found: {module_name}")

    # 分析该模块所有 runs
    traditional_verified = 0
    ai_pending = 0
    traditional_runs = []
    ai_runs = []

    for run in module.get("runs", []):
        is_ai = "ai" in run.get("workflow", "").lower()
        if is_ai:
            ai_runs.append(run)
            # AI 产出的覆盖率需要传统验证
            ai_pending += run.get("passed", 0)
        else:
            traditional_runs.append(run)
            # 传统轨的结果可以直接计数
            traditional_verified += run.get("passed", 0)

    # 计算覆盖率门限
    cov = module.get("coverage", {})
    traditional_cov = cov.get("line", 0)
    # AI 发现但未验证的额外覆盖（估算为 10-15%）
    ai_estimated_cov = min(15, max(0, 95 - traditional_cov)) if traditional_cov > 0 else 0

    total_phases = module.get("latest_total", 17)
    trad_pct = round(traditional_verified / max(total_phases * max(len(traditional_runs), 1), 1) * 100)
    ai_pct = round(ai_pending / max(total_phases * max(len(ai_runs), 1), 1) * 30) if ai_runs else 0

    # 门限判定
    threshold = 85  # 传统覆盖率门限
    gating_status = "open"  # open | partial | locked
    if traditional_cov >= threshold:
        gating_status = "locked"  # 传统已达到门限，可以签核
    elif traditional_cov >= threshold * 0.7:
        gating_status = "partial"  # 接近门限，AI 探索中

    return {
        "module": module_name,
        "gating_status": gating_status,
        "threshold": threshold,
        "traditional": {
            "coverage": traditional_cov,
            "verified_phases": traditional_verified,
            "run_count": len(traditional_runs),
            "color": "#3b82f6",  # deep blue
            "label": "传统已验证",
        },
        "ai": {
            "pending_phases": ai_pending,
            "run_count": len(ai_runs),
            "estimated_extra_coverage": ai_estimated_cov,
            "color": "#60a5fa",  # light blue
            "label": "AI 待传统验证",
        },
        "total_coverage_estimated": min(100, traditional_cov + ai_estimated_cov),
        "gap_to_threshold": max(0, threshold - traditional_cov),
        "recommendation": (
            "已达到签核门限 ✅" if gating_status == "locked"
            else f"AI 探索中，距门限还差 {max(0, threshold - traditional_cov)}% 覆盖率"
            if gating_status == "partial"
            else "请先运行传统仿真建立基线"
        ),
    }


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
    ctx = {"spec": {}, "env": {"env_name": "dut_env"}}
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
    ctx = {"spec": {}, "env": {"env_name": "dut_env"}}
    task = {"ctx": ctx, "input": req.spec_text or "UART IP with AXI interface"}
    r = await agent.execute_task(task)
    return {"success": r.success, "design_arch": r.data.get("design_arch", {}), "output": r.data.get("output", ""), "error": r.error}

# ═══════════════════════════════════════════════════════════
# 文档库 —— MD 规格文档管理
# ═══════════════════════════════════════════════════════════

@app.get("/api/docs")
async def list_docs(user: dict = Depends(get_current_user)):
    """列出规格文档 — 经理看全部，工程师只看已分配模块的文档"""
    role = user.get("role", "") if user else ""
    user_id = user.get("user_id", 0) if user else 0

    # 工程师只看分配模块的文档
    allowed_dirs = None
    if role not in ("admin", "verification_manager", ""):
        try:
            from src.database.repository import list_projects
            projects = await list_projects(user_id)
            allowed_dirs = {p["name"] for p in projects}
        except Exception:
            allowed_dirs = set()

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
            # 工程师过滤：只显示已分配模块目录下的文档
            parent_dir = f.parent.name if f.parent != SPECS_DIR else ""
            if allowed_dirs is not None and parent_dir and parent_dir not in allowed_dirs:
                continue

            rel = str(f.relative_to(SPECS_DIR)).replace("\\", "/")
            docs.append({
                "path": str(f),
                "name": f.name,
                "rel_path": rel,
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
    fp = _resolve_spec_path(path)
    if not fp.exists():
        raise HTTPException(status_code=404, detail="文档不存在")
    content = fp.read_text(encoding="utf-8")
    # 解析出关联需求
    import re
    req_ids = list(set(re.findall(r'\*\*REQ_\w+\*\*', content)))
    return {"path": str(fp), "name": fp.name, "content": content,
            "lines": len(content.split("\n")), "linked_reqs": req_ids}

@app.post("/api/docs/{path:path}")
async def write_doc(path: str, content: str = "", user: dict = Depends(require_auth)):
    """保存规格文档 — 文件系统 + SQL 双写 + 版本历史"""
    role = user.get("role", "")
    if role not in ("admin", "verification_manager"):
        raise HTTPException(status_code=403, detail="仅 SignOff 经理可以编辑规格文档")
    if not content:
        raise HTTPException(status_code=400, detail="content is required")
    if len(content.encode("utf-8")) > MAX_DOCUMENT_BYTES:
        raise HTTPException(status_code=413, detail="document too large")
    fp = _resolve_spec_path(path)
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(content, encoding="utf-8")

    # 同步到 SQL 文档生态 + 版本历史
    try:
        from src.database.repository import create_document, update_document, add_audit_log
        import hashlib
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        # 查找是否已有记录
        from src.database.repository import search_documents
        existing = await search_documents(keyword=fp.stem, limit=1)
        if existing and len(existing.get("docs", [])) > 0:
            doc = existing["docs"][0]
            await update_document(doc["id"], content, user["user_id"], f"保存于 {fp.name}")
        else:
            # 提取标题
            title = fp.stem
            for line in content.split("\n"):
                if line.startswith("# "): title = line[2:].strip(); break
            await create_document(0, str(fp.relative_to(SPECS_DIR)), title, content, user["user_id"])
    except Exception: pass

    try:
        from src.database.repository import add_audit_log
        await add_audit_log(user["user_id"], user["username"], "doc_save", str(fp))
    except Exception: pass
    return {"ok": True, "path": str(fp)}

# ═══════════════════════════════════════════════════════════
# 文档生态 API v2 —— SQL 后端
# ═══════════════════════════════════════════════════════════

@app.post("/api/v2/docs")
async def v2_create_doc(req: DocCreateRequest, current_user=Depends(require_auth)):
    from src.database import repository
    doc_id = await repository.create_document(
        req.project_id, req.path, req.title, req.content, current_user['id'], req.level, req.tags
    )
    await repository.add_audit_log(current_user['id'], current_user.get('username', ''), 'doc.create',
                                   f'doc/{doc_id}', f'创建文档: {req.path}')
    return {"id": doc_id, "status": "created"}

@app.put("/api/v2/docs/{doc_id}")
async def v2_update_doc(doc_id: int, req: DocUpdateRequest, current_user=Depends(require_auth)):
    from src.database import repository
    result = await repository.update_document(doc_id, req.content, current_user['id'], req.change_summary)
    if result == 0:
        raise HTTPException(status_code=404, detail="文档不存在")
    await repository.add_audit_log(current_user['id'], current_user.get('username', ''), 'doc.update',
                                   f'doc/{doc_id}', f'更新文档: {req.change_summary}')
    return {"id": result, "status": "updated"}

@app.get("/api/v2/docs/{doc_id}")
async def v2_get_doc(doc_id: int):
    from src.database import repository
    doc = await repository.get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    return doc

@app.get("/api/v2/docs")
async def v2_search_docs(project_id: int = None, level: str = None, keyword: str = '',
                           req_id: str = '', tags: str = '', limit: int = 50):
    from src.database import repository
    return await repository.search_documents(project_id, level, keyword, req_id, tags, limit)

@app.get("/api/v2/docs/{doc_id}/versions")
async def v2_get_versions(doc_id: int):
    """获取文档的版本历史"""
    from src.database.connection import get_session
    from src.database.models import DocVersion
    from sqlalchemy import select, desc
    s = await get_session()
    rows = (await s.execute(select(DocVersion).where(DocVersion.document_id == doc_id).order_by(desc(DocVersion.created_at)).limit(20))).scalars().all()
    versions = [{"id": r.id, "version": r.version, "content_hash": r.content_hash,
                 "change_summary": r.change_summary, "created_at": str(r.created_at),
                 "author_id": r.author_id} for r in rows]
    await s.close()
    return {"doc_id": doc_id, "versions": versions, "count": len(versions)}

@app.get("/api/v2/docs/{doc_id}/versions/{version_id}")
async def v2_get_version_content(doc_id: int, version_id: int):
    """获取特定版本的内容"""
    from src.database.connection import get_session
    from src.database.models import DocVersion
    from sqlalchemy import select
    s = await get_session()
    v = (await s.execute(select(DocVersion).where(DocVersion.id == version_id, DocVersion.document_id == doc_id))).scalar_one_or_none()
    await s.close()
    if not v:
        raise HTTPException(status_code=404, detail="版本不存在")
    return {"id": v.id, "version": v.version, "content": v.content, "content_hash": v.content_hash,
            "change_summary": v.change_summary, "created_at": str(v.created_at)}

@app.post("/api/v2/docs/{doc_id}/versions/{version_id}/restore")
async def v2_restore_version(doc_id: int, version_id: int, current_user=Depends(require_auth)):
    """回退文档到指定版本"""
    from src.database.connection import get_session
    from src.database.models import DocVersion
    from src.database import repository
    from sqlalchemy import select
    s = await get_session()
    v = (await s.execute(select(DocVersion).where(DocVersion.id == version_id, DocVersion.document_id == doc_id))).scalar_one_or_none()
    await s.close()
    if not v:
        raise HTTPException(status_code=404, detail="版本不存在")
    result = await repository.update_document(doc_id, v.content, current_user['id'],
                                               f"回退到版本 {v.version}")
    if result == 0:
        raise HTTPException(status_code=404, detail="文档不存在")
    await repository.add_audit_log(current_user['id'], current_user.get('username', ''), 'doc.restore',
                                   f'doc/{doc_id}', f'回退到版本 {v.version}')
    return {"id": result, "status": "restored", "version": v.version}


@app.get("/api/v2/requirements/{req_id}")
async def v2_get_req_trace(req_id: str):
    from src.database import repository
    r = await repository.get_requirement_trace(req_id)
    if not r:
        raise HTTPException(status_code=404, detail="需求 ID 不存在")
    return r

@app.get("/api/v2/requirements")
async def v2_list_requirements(project_id: int = None):
    from src.database import repository
    return {"requirements": await repository.list_all_requirements(project_id)}

@app.post("/api/v2/docs/links")
async def v2_link_docs(req: DocLinkRequest, current_user=Depends(require_auth)):
    from src.database import repository
    link_id = await repository.link_documents(req.source_id, req.target_id, req.relation_type, req.description)
    await repository.add_audit_log(current_user['id'], current_user.get('username', ''), 'doc.link',
                                   f'link/{link_id}', f'{req.source_id} -> {req.target_id} ({req.relation_type})')
    return {"id": link_id, "status": "linked"}

@app.get("/api/v2/docs/tree/{project_id}")
async def v2_get_doc_tree(project_id: int, root: str = None):
    from src.database import repository
    return await repository.get_document_tree(project_id, root)

@app.post("/api/v2/docs/sync")
async def v2_sync_docs(project_id: int = 1, current_user=Depends(require_admin)):
    from src.database import repository
    from config.settings import Settings
    settings = Settings()
    specs_dir = settings.SPECS_DIR if hasattr(settings, 'SPECS_DIR') else str(SPECS_DIR)
    result = await repository.sync_fs_to_db(specs_dir, project_id, current_user['id'])
    await repository.add_audit_log(current_user['id'], current_user.get('username', ''), 'doc.sync',
                                   'sync/', f'新建{result["created"]} 更新{result["updated"]} 跳过{result["skipped"]}')
    return result

# ═══════════════════════════════════════════════════════════
# 工具治理 API — Tool Registry + Sandbox
# ═══════════════════════════════════════════════════════════

@app.get("/api/tools/list")
async def list_tools():
    """列出所有已注册工具及其 schema、风险等级"""
    from src.core.tool_system import ToolRegistry, register_builtin_tools, RISK_RULES
    registry = ToolRegistry()
    register_builtin_tools(registry)

    # Also collect tools from agent contracts
    service = PipelineExecutionService.get_instance()
    agent_tools = {}
    if service.initialized:
        for role, agent in service.registry.get_all_instances().items():
            agent_tools_list = []
            for t in (getattr(agent, 'tools', None) or []):
                if hasattr(t, 'name'):
                    agent_tools_list.append({"name": t.name, "description": getattr(t, 'description', '')[:100]})
            if agent_tools_list:
                agent_tools[role] = agent_tools_list

    return {
        "registry": registry.get_stats(),
        "risk_levels": RISK_RULES,
        "agent_tools": agent_tools,
        "total_agent_tools": sum(len(v) for v in agent_tools.values()),
    }


@app.get("/api/tools/sandbox")
async def get_sandbox_config():
    """获取沙箱配置和统计"""
    from src.core.tool_system import RISK_RULES
    return {
        "risk_rules": RISK_RULES,
        "config": {
            "auto_approve_safe": True,
            "console_confirm_write": True,
            "block_danger": True,
            "allowed_root": str(WORKSPACE_ROOT),
        },
        "stats": {
            "total_tools_registered": 3,  # builtin count
            "safe_tools": 1,
            "write_tools": 1,
            "danger_tools": 1,
        },
    }


@app.get("/api/tools/history")
async def get_tool_history(limit: int = 50):
    """获取工具调用历史记录"""
    from src.core.tool_system import ToolRegistry, register_builtin_tools
    registry = ToolRegistry()
    register_builtin_tools(registry)
    # Also try to get registry from pipeline service
    service = PipelineExecutionService.get_instance()
    if service.initialized:
        for agent in service.registry.get_all_instances().values():
            agent_registry = getattr(agent, 'tool_registry', None)
            if agent_registry:
                return {"history": agent_registry.get_history(limit), "total": agent_registry._total_calls}
    return {"history": registry.get_history(limit), "note": "使用独立 registry（Agent 未初始化）"}


@app.get("/api/tools/{tool_name}")
async def get_tool_detail(tool_name: str):
    """获取单个工具的详细信息"""
    from src.core.tool_system import ToolRegistry, register_builtin_tools
    registry = ToolRegistry()
    register_builtin_tools(registry)
    tool = registry.get(tool_name)
    if not tool:
        raise HTTPException(status_code=404, detail=f"Tool not found: {tool_name}")
    return {
        "name": tool.name,
        "description": tool.description,
        "risk_level": tool.risk_level,
        "input_schema": tool.input_schema,
        "has_handler": tool.handler is not None,
        "llm_spec": tool.to_llm_description(),
    }


# ═══════════════════════════════════════════════════════════
# 签核证据链增强 API — 时间线 + 证据门禁
# ═══════════════════════════════════════════════════════════

@app.get("/api/signoffs/{sid}/evidence")
async def get_signoff_evidence(sid: int):
    """获取签核关联的完整证据链（manifest + evidence + integrity）"""
    from src.database.repository import get_signoff_by_id
    sf = await get_signoff_by_id(sid)
    if not sf:
        raise HTTPException(status_code=404, detail="签核记录不存在")

    summary = sf.get("summary", {}) or {}
    run_id = summary.get("run_id", "")
    manifest_hash = summary.get("manifest_hash", "")

    # 尝试获取完整 manifest
    manifest_data = None
    integrity = None
    if run_id:
        try:
            from pathlib import Path
            import json
            for mf in sorted(Path("output").glob("**/docs/manifest.json"), key=lambda p: p.stat().st_mtime, reverse=True):
                try:
                    data = json.loads(mf.read_text(encoding="utf-8"))
                    if data.get("run_id") == run_id:
                        manifest_data = data
                        break
                except Exception:
                    pass
        except Exception:
            pass

    # 完整性校验
    if run_id:
        try:
            # Reuse verify logic
            from src.core.manifest import hash_json
            import hashlib
            if manifest_data:
                stored_hash = manifest_data.get("manifest_hash", "")
                calc_data = {k: v for k, v in manifest_data.items() if k != "manifest_hash"}
                calc_hash = hash_json(calc_data)
                manifest_ok = stored_hash == calc_hash

                phases = manifest_data.get("phases", [])
                total = manifest_data.get("total_phases", len(phases))

                integrity = {
                    "manifest_hash_ok": manifest_ok,
                    "phases_complete": len(phases) == total,
                    "phases_passed": sum(1 for p in phases if p.get("status") == "passed"),
                    "phases_failed": sum(1 for p in phases if p.get("status") in ("failed", "error")),
                    "total_phases": total,
                    "valid": manifest_ok and len(phases) == total,
                    "conclusion": "🟢 证据链完整" if (manifest_ok and len(phases) == total) else "🔴 证据链存在问题",
                }
        except Exception:
            pass

    return {
        "signoff_id": sid,
        "status": sf.get("status", ""),
        "run_id": run_id,
        "manifest_hash": manifest_hash,
        "evidence_hash": summary.get("evidence_hash", ""),
        "manifest": manifest_data,
        "integrity": integrity,
        "summary": summary,
    }


@app.get("/api/signoffs/{sid}/timeline")
async def get_signoff_timeline(sid: int):
    """获取签核的完整时间线（创建→证据关联→审批→锁定）"""
    from src.database.repository import get_audit_logs
    # Get all audit logs related to this signoff
    logs = await get_audit_logs(limit=200)
    related = []
    for log in logs:
        target = log.get("target", "") or log.get("target_id", "")
        if str(sid) in str(target) or log.get("action", "") in ("signoff_create", "signoff_approve", "signoff_reject", "evidence_export", "pipeline_run"):
            if str(sid) in str(target) or log.get("action", "").startswith("signoff"):
                related.append({
                    "id": log.get("id", 0),
                    "username": log.get("username", ""),
                    "action": log.get("action", ""),
                    "detail": log.get("detail", ""),
                    "timestamp": str(log.get("created_at", "")),
                })

    # Also get the signoff itself
    from src.database.repository import get_signoff_by_id
    sf = await get_signoff_by_id(sid)

    timeline = []
    if sf:
        timeline.append({
            "event": "created",
            "title": "签核创建",
            "description": f"创建签核: {sf.get('title', '')}",
            "timestamp": str(sf.get("created_at", "")),
            "icon": "📝",
        })
        if sf.get("approved_at"):
            timeline.append({
                "event": "approved",
                "title": "签核批准",
                "description": f"由 {sf.get('approved_by_name', 'N/A')} 批准",
                "timestamp": str(sf.get("approved_at", "")),
                "icon": "✅",
            })
        elif sf.get("status") == "rejected":
            timeline.append({
                "event": "rejected",
                "title": "签核驳回",
                "description": sf.get("reject_reason", ""),
                "timestamp": str(sf.get("updated_at", "")),
                "icon": "❌",
            })

    # Add audit trail events
    for log in related:
        icon_map = {"signoff_create": "📝", "signoff_approve": "✅", "signoff_reject": "❌",
                    "evidence_export": "📦", "pipeline_run": "▶️"}
        timeline.append({
            "event": log["action"],
            "title": log["action"].replace("_", " ").title(),
            "description": log.get("detail", ""),
            "timestamp": log["timestamp"],
            "icon": icon_map.get(log["action"], "📋"),
            "user": log["username"],
        })

    # Sort by timestamp
    timeline.sort(key=lambda x: x.get("timestamp", ""))
    return {"signoff_id": sid, "timeline": timeline, "total_events": len(timeline)}


# ═══════════════════════════════════════════════════════════
# 签核事件 + 证据对象 API（数据库模型升级）
# ═══════════════════════════════════════════════════════════

@app.get("/api/signoffs/{sid}/events")
async def get_signoff_events_api(sid: int):
    """获取签核的完整事件流（审批历史、状态变更）"""
    from src.database.repository import get_signoff_events
    events = await get_signoff_events(sid)
    return {"signoff_id": sid, "events": events, "total": len(events)}


@app.get("/api/artifacts")
async def list_artifacts(run_id: str = "", signoff_id: int = None, artifact_type: str = "", limit: int = 50):
    """列出证据产物 — 支持按 run_id / signoff_id / type 过滤"""
    from src.database.repository import get_artifacts
    return {"artifacts": await get_artifacts(run_id, signoff_id, artifact_type, limit)}


@app.post("/api/artifacts")
async def create_artifact_api(project_id: int = 0, run_id: str = "", signoff_id: int = 0,
                              artifact_type: str = "", name: str = "", path: str = "",
                              content_hash: str = "", size_bytes: int = 0,
                              user: dict = Depends(require_auth)):
    """注册一个证据产物"""
    from src.database.repository import create_artifact, add_audit_log
    aid = await create_artifact(project_id, run_id, signoff_id, artifact_type, name,
                                path, content_hash, size_bytes)
    await add_audit_log(user["user_id"], user["username"], "artifact_create", str(aid),
                        f"{artifact_type}: {name}", role=user.get("role", ""),
                        resource_type="artifact")
    return {"id": aid, "status": "registered"}


@app.get("/api/evidence-links")
async def list_evidence_links(object_type: str = "", object_id: int = None, limit: int = 50):
    """列出证据关联"""
    from src.database.repository import get_evidence_links
    return {"links": await get_evidence_links(object_type, object_id, limit)}


@app.post("/api/evidence-links")
async def create_evidence_link_api(artifact_id: int = 0, object_type: str = "",
                                    object_id: int = 0, relation_type: str = "attached_to",
                                    user: dict = Depends(require_auth)):
    """创建证据关联"""
    from src.database.repository import link_evidence, add_audit_log
    lid = await link_evidence(artifact_id, object_type, object_id, relation_type)
    await add_audit_log(user["user_id"], user["username"], "evidence_link", str(lid),
                        f"{object_type}#{object_id} <- artifact#{artifact_id} ({relation_type})",
                        role=user.get("role", ""), resource_type="evidence")
    return {"id": lid, "status": "linked"}


# ═══════════════════════════════════════════════════════════
# 增强审计 API — 支持角色上下文和越权过滤
# ═══════════════════════════════════════════════════════════

@app.get("/api/audit/enhanced")
async def enhanced_audit_logs(limit: int = 50, action: str = "", role: str = "",
                               access_result: str = "", user: dict = Depends(require_admin)):
    """增强审计日志 — 支持按操作类型、角色、访问结果(成功/越权)过滤"""
    from src.database.repository import get_audit_logs
    logs = await get_audit_logs(limit=limit, action_filter=action or None,
                                role_filter=role or None, access_result=access_result or None)
    # 统计
    total = len(logs)
    denied = sum(1 for l in logs if l.get("access_result") == "denied")
    privileged = sum(1 for l in logs if l.get("is_privileged_action"))
    return {
        "logs": logs,
        "total": total,
        "denied_count": denied,
        "privileged_count": privileged,
        "filters": {"action": action, "role": role, "access_result": access_result},
    }


@app.get("/api/audit/summary")
async def audit_summary(days: int = 7, user: dict = Depends(require_admin)):
    """审计摘要 — 按角色、操作类型、访问结果聚合"""
    from src.database.repository import get_audit_logs
    logs = await get_audit_logs(limit=500)
    from datetime import datetime, timedelta
    cutoff = datetime.now() - timedelta(days=days)

    by_role = {}
    by_action = {}
    by_result = {"success": 0, "denied": 0, "error": 0}
    for log in logs:
        try:
            ts = datetime.fromisoformat(str(log.get("created_at", "")))
            if ts < cutoff: continue
        except: pass
        role = log.get("role", "unknown")
        action = log.get("action", "unknown")
        result = log.get("access_result", "success")
        by_role[role] = by_role.get(role, 0) + 1
        by_action[action] = by_action.get(action, 0) + 1
        if result in by_result: by_result[result] += 1

    return {
        "period_days": days,
        "total_actions": sum(by_role.values()),
        "by_role": [{"role": k, "count": v} for k, v in sorted(by_role.items(), key=lambda x: -x[1])],
        "by_action": [{"action": k, "count": v} for k, v in sorted(by_action.items(), key=lambda x: -x[1])[:10]],
        "by_result": by_result,
    }


# ═══════════════════════════════════════════════════════════
# 平台化能力 API — 数据治理 + 事件总线 + 可观测性 + 安全
# ═══════════════════════════════════════════════════════════

# ── 数据字典 ──

@app.get("/api/governance/data-dictionary")
async def get_data_dictionary(user: dict = Depends(require_auth)):
    """获取统一数据字典 — 所有实体定义、状态机、字段约束"""
    from src.infra.data_governance import get_data_dictionary as get_dd
    dd = get_dd()
    entities = {}
    for name, entity in dd.entities.items():
        entities[name] = {
            "table_name": entity.table_name,
            "display_name": entity.display_name,
            "description": entity.description,
            "fields": [{
                "name": f.name, "type": f.type, "required": f.required,
                "max_length": f.max_length, "enum_values": f.enum_values,
                "description": f.description,
            } for f in entity.fields],
            "state_machine": entity.state_machine,
            "unique_constraints": entity.unique_constraints,
            "foreign_keys": entity.foreign_keys,
        }
    return {"entities": entities, "total_entities": len(entities)}


@app.get("/api/governance/data-dictionary/export")
async def export_data_dictionary_api(user: dict = Depends(require_admin)):
    """导出 Markdown 数据字典"""
    from src.infra.data_governance import export_data_dictionary
    path = export_data_dictionary()
    return {"path": path, "format": "markdown"}


@app.get("/api/governance/consistency-check")
async def run_consistency_check(user: dict = Depends(require_admin)):
    """运行跨表一致性检查"""
    from src.infra.data_governance import ConsistencyChecker
    checker = ConsistencyChecker()
    issues = await checker.check_all()
    return {
        "total_issues": len(issues),
        "errors": sum(1 for i in issues if i.severity == "error"),
        "warnings": sum(1 for i in issues if i.severity == "warning"),
        "issues": [{"entity": i.entity, "entity_id": i.entity_id,
                     "issue": i.issue, "severity": i.severity,
                     "related_entity": i.related_entity} for i in issues],
    }


# ── 事件总线 ──

@app.get("/api/events/history")
async def get_event_history(event_type: str = "", limit: int = 50, user: dict = Depends(require_auth)):
    """获取事件历史"""
    from src.infra.event_bus import get_event_bus, StandardEvent
    bus = get_event_bus()
    evt_type = StandardEvent(event_type) if event_type else None
    return {"events": bus.get_history(evt_type, limit), "stats": bus.get_stats()}


@app.get("/api/events/stats")
async def get_event_stats(user: dict = Depends(require_auth)):
    """获取事件总线统计"""
    from src.infra.event_bus import get_event_bus
    return get_event_bus().get_stats()


# ── 可观测性仪表盘 ──

@app.get("/api/observability/dashboard")
async def observability_dashboard(user: dict = Depends(require_admin)):
    """运维仪表盘 — 流水线耗时、签核周期、模块失败率、API 延迟"""
    from src.infra.observability import get_metrics, get_slow_query_detector
    metrics = get_metrics()
    slow = get_slow_query_detector()
    stats = metrics.get_dashboard_stats()
    stats["slow_queries"] = {
        "summary": slow.get_summary(),
        "recent": slow.get_slow_queries(10),
    }
    return stats


@app.get("/api/observability/pipeline-timeline")
async def pipeline_timeline(limit: int = 30, user: dict = Depends(require_auth)):
    """获取流水线时间线（趋势图数据）"""
    from src.infra.observability import get_metrics
    return {"timeline": get_metrics().get_pipeline_timeline(limit)}


@app.get("/api/observability/health")
async def system_health():
    """系统健康检查（公开端点）"""
    from src.infra.observability import HealthChecker
    return await HealthChecker.check_all()


# ── 安全 ──

@app.get("/api/security/audit-chain/verify")
async def verify_audit_chain(user: dict = Depends(require_admin)):
    """验证审计链完整性 — 检测是否被篡改"""
    from src.infra.security import get_audit_chain
    chain = get_audit_chain()
    valid, message = chain.verify()
    return {
        "valid": valid,
        "message": message,
        "chain_info": chain.get_chain_info(),
    }


@app.get("/api/security/audit-chain/export")
async def export_audit_chain(user: dict = Depends(require_admin)):
    """导出审计链（前 50 条）"""
    from src.infra.security import get_audit_chain
    return {"chain": get_audit_chain().export_chain()[-50:]}


@app.get("/api/security/rate-limits")
async def get_rate_limits(user: dict = Depends(require_admin)):
    """获取速率限制器状态"""
    from src.infra.security import get_rate_limiter, RATE_LIMITS
    limiter = get_rate_limiter()
    return {
        "config": RATE_LIMITS,
        "current_status": limiter.get_status(),
    }


# ═══════════════════════════════════════════════════════════
# 业务口径 + 可解释性 + 协作 + 影响评估 + 健康监控 API
# ═══════════════════════════════════════════════════════════

# ── 业务术语表 ──

@app.get("/api/glossary")
async def get_glossary():
    """获取统一业务术语表"""
    from src.infra.business_glossary import get_glossary as get_gloss
    g = get_gloss()
    return {"terms": g.export_glossary(), "total": len(g.all_terms())}


@app.get("/api/glossary/check/{term}")
async def check_business_term(term: str, line_pct: float = 0, branch_pct: float = 0,
                               toggle_pct: float = 0, score: float = 0,
                               regression_pass_rate: float = 0):
    """检查给定指标是否满足某业务口径"""
    from src.infra.business_glossary import get_glossary as get_gloss
    g = get_gloss()
    metrics = {"line_pct": line_pct, "branch_pct": branch_pct, "toggle_pct": toggle_pct,
               "score": score, "regression_pass_rate": regression_pass_rate}
    ok, reason, failures = g.check(term, metrics)
    return {"term": term, "ok": ok, "reason": reason, "failures": failures, "checked_metrics": metrics}


# ── 决策追溯 ──

@app.get("/api/decisions/recent")
async def get_recent_decisions(limit: int = 20, user: dict = Depends(require_auth)):
    """获取最近的 AI 决策追溯"""
    from src.infra.business_glossary import get_tracer
    tracer = get_tracer()
    traces = tracer.get_recent_traces(limit)
    return {"traces": [{"decision_id": t.decision_id, "decision_type": t.decision_type,
             "timestamp": t.timestamp, "final_conclusion": t.final_conclusion,
             "overall_confidence": t.overall_confidence,
             "human_review_required": t.human_review_required,
             "steps_count": len(t.steps)} for t in traces], "total": len(traces)}


@app.get("/api/decisions/{decision_id}")
async def get_decision_detail(decision_id: str, user: dict = Depends(require_auth)):
    """获取决策的完整推理链"""
    from src.infra.business_glossary import get_tracer
    tracer = get_tracer()
    trace = tracer.get_trace(decision_id)
    if not trace: raise HTTPException(status_code=404, detail="决策不存在")
    return {"decision_id": trace.decision_id, "decision_type": trace.decision_type,
            "steps": [{"step": s.step_number, "description": s.description,
                        "evidence": s.evidence, "rule": s.rule_applied,
                        "conclusion": s.conclusion, "confidence": s.confidence}
                      for s in trace.steps],
            "evidence_sources": trace.evidence_sources,
            "final_conclusion": trace.final_conclusion,
            "overall_confidence": trace.overall_confidence,
            "human_review_required": trace.human_review_required,
            "review_reason": trace.review_reason,
            "report": tracer.generate_explainability_report(decision_id)}


@app.get("/api/decisions/review-required")
async def get_decisions_requiring_review(user: dict = Depends(require_auth)):
    """获取所有需要人工审核的决策"""
    from src.infra.business_glossary import get_tracer
    traces = get_tracer().get_traces_requiring_review()
    return {"traces": [{"decision_id": t.decision_id, "decision_type": t.decision_type,
             "confidence": t.overall_confidence, "reason": t.review_reason}
            for t in traces], "total": len(traces)}


# ── 协作 ──

@app.get("/api/collaboration/gates/{object_key:path}")
async def get_review_gates(object_key: str):
    """获取对象的审核门禁状态"""
    from src.infra.collaboration import get_gate_manager
    gm = get_gate_manager()
    passed, results = gm.check_all_gates(object_key)
    return {"object_key": object_key, "all_passed": passed,
            "gates": [{"gate_id": r.gate_id, "passed": r.passed,
                        "reason": r.reason, "escalation": r.escalation_required}
                      for r in results]}


@app.post("/api/collaboration/gates/{object_key:path}/approve")
async def approve_gate(object_key: str, gate_id: str = "", comment: str = "",
                        user: dict = Depends(require_auth)):
    """审批通过一个门禁"""
    from src.infra.collaboration import get_gate_manager
    gm = get_gate_manager()
    result = gm.approve_gate(object_key, gate_id, user["username"],
                              user.get("role", ""), comment)
    return {"passed": result.passed, "gate_id": result.gate_id,
            "reason": result.reason, "missing_approvals": result.missing_approvals}


@app.get("/api/collaboration/comments/{object_type}/{object_id}")
async def get_comments(object_type: str, object_id: int):
    """获取评论线程"""
    from src.infra.collaboration import get_comment_system
    return {"threads": get_comment_system().get_thread(object_type, object_id)}


@app.post("/api/collaboration/comments")
async def add_comment(object_type: str = "", object_id: int = 0, content: str = "",
                      parent_id: str = "", user: dict = Depends(require_auth)):
    """添加评论（支持 @mentions）"""
    from src.infra.collaboration import get_comment_system
    cs = get_comment_system()
    comment = cs.add_comment(object_type, object_id, user["username"],
                              content, user.get("role", ""), parent_id)
    return {"comment_id": comment.comment_id, "mentions": comment.mentions}


@app.get("/api/collaboration/notifications")
async def get_notifications(unread_only: bool = False, user: dict = Depends(require_auth)):
    """获取用户通知"""
    from src.infra.collaboration import get_comment_system
    cs = get_comment_system()
    return {"notifications": cs.get_notifications(user["username"], unread_only),
            "unread": cs.get_unread_count(user["username"])}


@app.get("/api/collaboration/tasks")
async def get_my_tasks(status: str = "", user: dict = Depends(require_auth)):
    """获取我的任务"""
    from src.infra.collaboration import get_task_manager, TaskStatus
    tm = get_task_manager()
    status_filter = TaskStatus(status) if status else None
    tasks = tm.get_user_tasks(user["username"], status_filter)
    return {"tasks": [{"task_id": t.task_id, "title": t.title, "status": t.status.value,
             "priority": t.priority, "due_date": t.due_date,
             "handoff_count": len(t.handoff_history)} for t in tasks], "total": len(tasks)}


# ── 影响评估 ──

@app.get("/api/rules")
async def get_rules(category: str = "", user: dict = Depends(require_auth)):
    """获取所有可配置规则"""
    from src.infra.impact_analyzer import get_rule_registry
    registry = get_rule_registry()
    rules = registry.get_all_rules()
    if category: rules = [r for r in rules if r.category.value == category]
    return {"rules": [{"rule_id": r.rule_id, "name": r.name, "category": r.category.value,
             "current_value": r.current_value, "version": r.version,
             "usage_count": r.usage_count, "affects": r.affects} for r in rules], "total": len(rules)}


@app.post("/api/rules/analyze-change")
async def analyze_rule_change(rule_id: str = "", new_value: str = "",
                               user: dict = Depends(require_auth)):
    """分析规则变更的影响范围（模拟，不执行）"""
    from src.infra.impact_analyzer import get_impact_analyzer
    import json as _json
    try: parsed_value = _json.loads(new_value)
    except Exception: parsed_value = new_value
    analyzer = get_impact_analyzer()
    report = analyzer.analyze_change(rule_id, parsed_value, user["username"], "API analysis")
    return {"rule_id": report.rule_id, "old_value": report.old_value,
            "new_value": report.new_value, "risk": report.risk.value,
            "affected_projects": report.affected_projects,
            "affected_signoffs": report.affected_signoffs,
            "affected_rules": report.affected_rules,
            "affected_functions": report.affected_functions,
            "recommendations": report.recommendations,
            "requires_approval": report.requires_approval,
            "rollback_plan": report.rollback_plan}


@app.post("/api/rules/change")
async def execute_rule_change(rule_id: str = "", new_value: str = "", reason: str = "",
                               user: dict = Depends(require_admin)):
    """执行规则变更（需管理员权限）"""
    from src.infra.impact_analyzer import get_rule_registry, get_impact_analyzer
    import json as _json
    try: parsed_value = _json.loads(new_value)
    except Exception: parsed_value = new_value
    analyzer = get_impact_analyzer()
    report = analyzer.analyze_change(rule_id, parsed_value, user["username"], reason)
    if report.risk.value in ("high", "critical") and not reason:
        raise HTTPException(status_code=400, detail=f"风险等级 {report.risk.value}，必须提供变更理由")
    registry = get_rule_registry()
    change = registry.change_rule(rule_id, parsed_value, user["username"], reason)
    from src.database.repository import add_audit_log
    await add_audit_log(user["user_id"], user["username"], "rule_change", rule_id,
                        f"{change.old_value} -> {change.new_value}",
                        role=user.get("role",""), resource_type="rule", is_privileged=True)
    return {"ok": True, "rule_id": rule_id, "version": change.version_after,
            "risk": report.risk.value}


# ── 健康监控 ──

@app.get("/api/health/full-check")
async def run_health_check(user: dict = Depends(require_admin)):
    """运行全面的平台健康检查"""
    from src.infra.health_monitor import get_health_monitor
    monitor = get_health_monitor()
    report = await monitor.run_full_check()
    return {"timestamp": report.timestamp, "overall_health": report.overall_health,
            "stuck_workflows": report.stuck_workflows, "timeout_items": report.timeout_items,
            "evidence_gaps": report.evidence_gaps, "coverage_gaps": report.coverage_gaps,
            "rule_anomalies": report.rule_anomalies, "active_alerts": report.active_alerts,
            "stuck_details": [{"type": s.object_type, "id": s.object_id,
             "state": s.current_state, "stuck_hours": s.stuck_hours,
             "recommendation": s.recommendation} for s in report.stuck_details],
            "gap_details": [{"type": g.gap_type, "severity": g.severity,
             "description": g.description, "recommendation": g.recommendation}
             for g in report.gap_details[:20]]}


@app.get("/api/health/quick")
async def quick_health_check():
    """快速健康检查（公开端点）"""
    from src.infra.health_monitor import get_health_monitor
    return get_health_monitor().quick_check()


@app.get("/api/health/alerts")
async def get_alerts(level: str = "", user: dict = Depends(require_auth)):
    """获取活跃告警"""
    from src.infra.health_monitor import AlertLevel, get_health_monitor
    monitor = get_health_monitor()
    lvl = AlertLevel(level) if level else None
    alerts = monitor.alerts.get_active_alerts(lvl)
    return {"alerts": [{"alert_id": a.alert_id, "level": a.level.value,
             "title": a.title, "description": a.description, "source": a.source,
             "detected_at": a.detected_at, "acknowledged": a.acknowledged}
            for a in alerts], "total": len(alerts), "summary": monitor.alerts.get_summary()}


# ═══════════════════════════════════════════════════════════
# 审批协作 + 模板系统 + 自动修复 API
# ═══════════════════════════════════════════════════════════

# ── 审批工作流 ──

@app.get("/api/approval/{object_type}/{object_id}")
async def get_approval_status(object_type: str, object_id: int):
    """获取审批状态和线程化历史"""
    from src.infra.approval_workflow import get_approval_workflow
    wf = get_approval_workflow()
    return {
        "status": wf.get_status(object_type, object_id).value,
        "round": wf.get_round(object_type, object_id),
        "history": wf.get_threaded_history(object_type, object_id),
        "summary": wf.get_summary(object_type, object_id),
        "available_actions": [],  # need user context
    }


@app.get("/api/approval/{object_type}/{object_id}/actions")
async def get_available_actions(object_type: str, object_id: int,
                                 user: dict = Depends(require_auth)):
    """获取当前用户可执行的审批动作"""
    from src.infra.approval_workflow import get_approval_workflow
    wf = get_approval_workflow()
    actions = wf.can_actor(object_type, object_id, user.get("role", "engineer"))
    return {"actions": [a.value for a in actions]}


@app.post("/api/approval/{object_type}/{object_id}/submit")
async def submit_for_approval(object_type: str, object_id: int, comment: str = "",
                               user: dict = Depends(require_auth)):
    """提交审批"""
    from src.infra.approval_workflow import get_approval_workflow
    wf = get_approval_workflow()
    try:
        entry = wf.submit(object_type, object_id, user["username"],
                          user.get("role", "engineer"), comment)
        return {"ok": True, "entry_id": entry.entry_id, "status": entry.status_after}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/approval/{object_type}/{object_id}/approve")
async def approve_workflow(object_type: str, object_id: int, comment: str = "",
                            user: dict = Depends(require_auth)):
    """批准"""
    from src.infra.approval_workflow import get_approval_workflow
    wf = get_approval_workflow()
    try:
        entry = wf.approve(object_type, object_id, user["username"],
                           user.get("role", ""), comment)
        return {"ok": True, "entry_id": entry.entry_id, "status": entry.status_after}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/approval/{object_type}/{object_id}/ask-back")
async def ask_back_approval(object_type: str, object_id: int, question: str = "",
                             user: dict = Depends(require_auth)):
    """追问"""
    from src.infra.approval_workflow import get_approval_workflow
    wf = get_approval_workflow()
    try:
        entry = wf.ask_back(object_type, object_id, user["username"],
                            user.get("role", ""), question)
        return {"ok": True, "entry_id": entry.entry_id, "status": entry.status_after}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/approval/{object_type}/{object_id}/return")
async def return_for_revision(object_type: str, object_id: int, notes: str = "",
                               user: dict = Depends(require_auth)):
    """退回修改"""
    from src.infra.approval_workflow import get_approval_workflow
    wf = get_approval_workflow()
    try:
        entry = wf.return_for_revision(object_type, object_id, user["username"],
                                        user.get("role", ""), notes)
        return {"ok": True, "entry_id": entry.entry_id, "status": entry.status_after}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/approval/{object_type}/{object_id}/resubmit")
async def resubmit_approval(object_type: str, object_id: int, comment: str = "",
                             user: dict = Depends(require_auth)):
    """修改后重新提交"""
    from src.infra.approval_workflow import get_approval_workflow
    wf = get_approval_workflow()
    try:
        wf.start_revision(object_type, object_id, user["username"], user.get("role", ""))
        entry = wf.resubmit(object_type, object_id, user["username"],
                            user.get("role", ""), comment)
        return {"ok": True, "entry_id": entry.entry_id, "status": entry.status_after}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── 模板系统 ──

@app.get("/api/templates")
async def list_templates(template_type: str = "", tag: str = ""):
    """获取可用模板"""
    from src.infra.template_system import get_template_registry, TemplateType
    registry = get_template_registry()
    if tag:
        templates = registry.get_templates_by_tag(tag)
    elif template_type:
        templates = registry.get_all_templates(TemplateType(template_type))
    else:
        templates = registry.get_all_templates()
    return {"templates": [{"template_id": t.template_id, "name": t.name,
             "type": t.template_type.value, "version": t.version,
             "tags": t.tags, "usage_count": t.usage_count,
             "description": t.description} for t in templates], "total": len(templates)}


@app.get("/api/templates/reusable")
async def get_reusable_assets(project_id: int = 0):
    """获取可跨项目复用的资产"""
    from src.infra.template_system import get_template_registry
    return {"assets": get_template_registry().get_reusable_assets(project_id)}


@app.post("/api/templates/instantiate")
async def instantiate_template(template_id: str = "", project_id: int = 0,
                                overrides: str = "{}",
                                user: dict = Depends(require_auth)):
    """从模板实例化配置"""
    from src.infra.template_system import get_template_instantiator
    import json as _json
    try: overrides_dict = _json.loads(overrides)
    except Exception: overrides_dict = {}
    instantiator = get_template_instantiator()
    config = instantiator.instantiate(template_id, project_id, overrides_dict)
    return config


# ── 自动修复引擎 ──

@app.post("/api/auto-fix/analyze")
async def analyze_and_suggest_fix(error_log: str = "", context_json: str = "{}",
                                   user: dict = Depends(require_auth)):
    """分析错误并推荐修复方案（含自动修复检测）"""
    from src.infra.auto_fix_engine import get_auto_fix_engine
    import json as _json
    try: context = _json.loads(context_json)
    except Exception: context = {}
    engine = get_auto_fix_engine()
    result = engine.analyze_and_suggest(error_log, context)
    return {
        "category": result.analysis.category.value,
        "root_cause": result.analysis.root_cause,
        "location": result.analysis.location,
        "severity": result.analysis.severity,
        "confidence": result.analysis.confidence,
        "auto_fixable": result.auto_fixable,
        "auto_fix_reason": result.auto_fix_reason,
        "suggestions": [{"title": s.title, "description": s.description,
                          "auto_fixable": s.auto_fixable,
                          "estimated_effort_minutes": s.estimated_effort_minutes,
                          "success_rate": s.success_rate,
                          "risk_level": s.risk_level}
                        for s in result.suggestions[:5]],
        "fix_script": result.fix_script,
        "recommended_action": result.recommended_action,
    }


@app.post("/api/auto-fix/verify")
async def verify_fix(original_log: str = "", after_log: str = "",
                      user: dict = Depends(require_auth)):
    """验证修复效果"""
    from src.infra.auto_fix_engine import get_auto_fix_engine, FailureAnalyzer, FixSuggestion
    engine = get_auto_fix_engine()
    analyzer = FailureAnalyzer()
    analysis = analyzer.analyze(original_log)
    dummy_fix = FixSuggestion("verify", "Manual fix", "User-applied fix", "manual_fix")
    verification = engine.verify_fix(dummy_fix, analysis, after_log)
    return {
        "verified": verification.verified,
        "original_error_gone": verification.original_error_gone,
        "new_errors": verification.new_errors,
        "side_effects": verification.side_effects,
        "recommendation": verification.recommendation,
    }


@app.get("/api/auto-fix/history")
async def get_auto_fix_history(limit: int = 20, user: dict = Depends(require_auth)):
    """获取自动修复历史"""
    from src.infra.auto_fix_engine import get_auto_fix_engine
    return {"history": get_auto_fix_engine().get_history(limit)}


# ── 变更审批链 ──

@app.post("/api/rules/request-change")
async def request_rule_change(rule_id: str = "", new_value: str = "", reason: str = "",
                               user: dict = Depends(require_auth)):
    """发起规则变更请求（高风险需审批）"""
    from src.infra.impact_analyzer import get_rule_registry, get_impact_analyzer, ChangeApprovalChain
    import json as _json
    try: parsed_value = _json.loads(new_value)
    except Exception: parsed_value = new_value
    analyzer = get_impact_analyzer()
    registry = get_rule_registry()
    chain = ChangeApprovalChain(analyzer, registry)
    cr = chain.request_change(rule_id, parsed_value, user["username"], reason)
    return {"request_id": cr.request_id, "status": cr.status,
            "requires_approval": cr.impact_report.requires_approval,
            "risk": cr.impact_report.risk.value}


@app.post("/api/rules/approve-change/{request_id}")
async def approve_rule_change(request_id: str, user: dict = Depends(require_admin)):
    """审批规则变更请求"""
    from src.infra.impact_analyzer import get_rule_registry, get_impact_analyzer, ChangeApprovalChain
    analyzer = get_impact_analyzer()
    registry = get_rule_registry()
    chain = ChangeApprovalChain(analyzer, registry)
    try:
        cr = chain.approve_change(request_id, user["username"])
        return {"ok": True, "request_id": request_id, "status": cr.status}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ═══════════════════════════════════════════════════════════
# 架构校验 + 命名一致性 + 领域映射 API
# ═══════════════════════════════════════════════════════════

@app.get("/api/architecture/domain-map")
async def get_domain_map(user: dict = Depends(require_auth)):
    """获取领域映射 — 所有模块的领域归属和分层"""
    from src.infra.architecture import get_domain_map, BoundedContext, ArchitectureLayer
    dm = get_domain_map()
    contexts = {}
    for ctx in BoundedContext:
        mods = dm.get_modules_by_context(ctx)
        contexts[ctx.value] = {
            "total_modules": len(mods),
            "by_layer": {layer.value: [m.name for m in mods if m.layer == layer]
                         for layer in ArchitectureLayer if any(m.layer == layer for m in mods)},
        }
    return {"contexts": contexts, "total_modules": len(dm.get_all_modules())}


@app.get("/api/architecture/validate")
async def validate_architecture(user: dict = Depends(require_admin)):
    """运行架构一致性校验"""
    from src.infra.architecture import ArchitectureValidator
    from src.core.domain_registry import ConsistencyLinter
    arch_issues = ArchitectureValidator().check_all()
    lint_issues = ConsistencyLinter().lint_all()
    return {
        "architecture_violations": [{"module": v.module, "violation": v.violation,
                                       "severity": v.severity, "fix": v.fix}
                                      for v in arch_issues],
        "consistency_issues": [{"category": i.category, "location": i.location,
                                 "description": i.description, "severity": i.severity}
                                for i in lint_issues],
        "total_issues": len(arch_issues) + len(lint_issues),
        "healthy": len(arch_issues) == 0,
    }


@app.get("/api/architecture/state-machine")
async def get_state_machine(domain: str = ""):
    """获取状态机定义"""
    from src.core.domain_registry import STATE_TRANSITIONS, is_valid_transition, get_valid_transitions
    if domain and domain in STATE_TRANSITIONS:
        return {"domain": domain, "transitions": STATE_TRANSITIONS[domain]}
    return {"domains": list(STATE_TRANSITIONS.keys()),
            "transitions": {k: {ks: vs for ks, vs in v.items()} for k, v in STATE_TRANSITIONS.items()}}


@app.get("/api/architecture/state-machine/check")
async def check_state_transition(domain: str = "", from_state: str = "", to_state: str = ""):
    """校验状态转移是否合法"""
    from src.core.domain_registry import is_valid_transition, is_terminal_state
    valid = is_valid_transition(domain, from_state, to_state)
    terminal = is_terminal_state(domain, from_state)
    return {"domain": domain, "from": from_state, "to": to_state,
            "valid": valid, "from_is_terminal": terminal}


@app.get("/api/architecture/naming-scan")
async def scan_naming(directory: str = "src", user: dict = Depends(require_admin)):
    """扫描命名规范违规"""
    from src.core.domain_registry import NamingValidator
    validator = NamingValidator()
    violations = validator.scan_directory(directory)
    return {"violations": [{"location": v.location, "name": v.name,
                             "expected": v.expected, "severity": v.severity}
                            for v in violations[:50]],
            "total": len(violations)}


# ── 调试日志 ──
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


# ═══════════════════════════════════════════════════════════
# 平台基础设施 API (todo0 优化)
# ═══════════════════════════════════════════════════════════

# ── 审计链验证 ──

@app.get("/api/audit/chain/verify")
async def verify_audit_chain_integrity(user: dict = Depends(require_admin)):
    """验证审计哈希链的完整性 — 检测篡改/删除"""
    from src.database.repository import verify_audit_chain
    result = await verify_audit_chain()
    return result


# ── 数据库备份 ──

@app.post("/api/admin/backup")
async def create_database_backup(user: dict = Depends(require_admin)):
    """创建数据库备份"""
    from src.database.backup import backup_database, get_db_stats
    path = backup_database()
    stats = get_db_stats()
    return {"backup_path": path, "stats": stats, "status": "done"}


@app.get("/api/admin/db-stats")
async def get_database_stats(user: dict = Depends(require_admin)):
    """获取数据库统计信息"""
    from src.database.backup import get_db_stats
    return get_db_stats()


# ── 权限管理 ──

@app.get("/api/admin/permissions")
async def list_all_permissions(user: dict = Depends(require_admin)):
    """列出所有权限及角色分配"""
    from src.database.connection import get_session
    from src.database.models import Permission, RolePermission
    from sqlalchemy import select
    s = await get_session()
    perms = (await s.execute(select(Permission).order_by(Permission.resource_type, Permission.code))).scalars().all()
    role_perms = (await s.execute(select(RolePermission))).scalars().all()
    await s.close()

    rp_map = {}
    for rp in role_perms:
        rp_map.setdefault(rp.role, []).append(rp.permission_id)

    return {
        "permissions": [{"id": p.id, "code": p.code, "name": p.name,
                         "resource_type": p.resource_type, "action": p.action} for p in perms],
        "roles": {role: pids for role, pids in rp_map.items()},
        "total_permissions": len(perms),
    }


@app.post("/api/admin/permissions/check")
async def check_user_permission(code: str = "", user: dict = Depends(require_auth)):
    """检查当前用户是否有指定权限"""
    role = user.get("role", "viewer")
    from src.database.connection import get_session
    from src.database.models import Permission, RolePermission
    from sqlalchemy import select
    s = await get_session()
    perm = (await s.execute(select(Permission).where(Permission.code == code))).scalar_one_or_none()
    if not perm:
        await s.close()
        return {"code": code, "has_permission": False, "reason": "权限码不存在"}
    rp = (await s.execute(
        select(RolePermission).where(RolePermission.role == role, RolePermission.permission_id == perm.id)
    )).scalar_one_or_none()
    await s.close()
    return {"code": code, "has_permission": rp is not None, "role": role}


# ── 工作流触发器管理 ──

@app.get("/api/admin/workflow-triggers")
async def list_workflow_triggers(event_type: str = "", user: dict = Depends(require_admin)):
    """列出工作流触发器"""
    from src.infra.workflow_triggers import get_trigger_service
    svc = get_trigger_service()
    return {"triggers": await svc.get_triggers(event_type)}


@app.post("/api/admin/workflow-triggers")
async def create_workflow_trigger(name: str = "", event_type: str = "", trigger_action: str = "",
                                   target_type: str = "", target_value: str = "",
                                   user: dict = Depends(require_admin)):
    """创建工作流触发器"""
    from src.infra.workflow_triggers import get_trigger_service
    svc = get_trigger_service()
    tid = await svc.create_trigger(name, event_type, trigger_action, target_type, target_value)
    from src.database.repository import add_audit_log
    await add_audit_log(user["user_id"], user["username"], "trigger_create", str(tid),
                        f"{name}: {event_type} -> {trigger_action}",
                        role=user.get("role", ""), resource_type="workflow", is_privileged=True)
    return {"id": tid, "status": "created"}


# ── 迁移管理 ──

@app.get("/api/admin/migrations")
async def get_migration_status(user: dict = Depends(require_admin)):
    """查看数据库迁移状态"""
    import sqlite3
    from pathlib import Path
    db_path = Path("ic_verification.db")
    if not db_path.exists():
        return {"applied": [], "pending": []}
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute("SELECT version, description, applied_at FROM schema_versions ORDER BY id").fetchall()
    except Exception:
        rows = []
    conn.close()
    return {"applied": [{"version": r[0], "description": r[1], "applied_at": r[2]} for r in rows]}


@app.post("/api/admin/migrations/run")
async def run_migrations(user: dict = Depends(require_admin)):
    """手动执行数据库迁移"""
    from src.database.migrations import run_migrations, seed_permissions
    run_migrations()
    seed_permissions()
    from src.database.repository import add_audit_log
    await add_audit_log(user["user_id"], user["username"], "migration_run", "db/migrations",
                        "手动触发迁移", role=user.get("role", ""), resource_type="system", is_privileged=True)
    return {"status": "done"}


# ── 软删除/归档 API ──

@app.delete("/api/signoffs/{sid}")
async def soft_delete_signoff_endpoint(sid: int, user: dict = Depends(require_auth)):
    """软删除签核（仅管理员/经理）"""
    if user.get("role") not in ("admin", "verification_manager"):
        raise HTTPException(status_code=403, detail="仅管理员和SignOff 经理可以删除签核")
    from src.database.repository import soft_delete_signoff, add_audit_log
    ok = await soft_delete_signoff(sid)
    if not ok:
        raise HTTPException(status_code=404, detail="签核不存在")
    await add_audit_log(user["user_id"], user["username"], "signoff_soft_delete", str(sid),
                        "软删除签核", role=user.get("role", ""), resource_type="signoff", is_privileged=True)
    return {"ok": True, "status": "deleted"}


@app.post("/api/signoffs/{sid}/archive")
async def archive_signoff_endpoint(sid: int, user: dict = Depends(require_auth)):
    """归档签核"""
    from src.database.repository import archive_signoff, add_audit_log
    ok = await archive_signoff(sid)
    if not ok:
        raise HTTPException(status_code=404, detail="签核不存在")
    await add_audit_log(user["user_id"], user["username"], "signoff_archive", str(sid),
                        "归档签核", role=user.get("role", ""), resource_type="signoff")
    return {"ok": True, "status": "archived"}


# ═══════════════════════════════════════════════════════════
# 运营仪表盘 API
# ═══════════════════════════════════════════════════════════

@app.get("/api/ops/dashboard")
async def ops_dashboard(user: dict = Depends(require_admin)):
    """运营仪表盘 — 最慢流程、最常失败模块、签核耗时分布"""
    from src.infra.observability import get_metrics, get_slow_query_detector
    metrics = get_metrics()
    stats = metrics.get_dashboard_stats()

    # 增强: 添加业务层面的聚合
    try:
        from src.database.repository import get_audit_logs, list_signoffs
        recent_audit = await get_audit_logs(limit=500)
        signoffs = await list_signoffs()

        # 用户活跃度
        user_actions = {}
        for log in recent_audit:
            u = log.get("username", "unknown")
            action = log.get("action", "unknown")
            if u not in user_actions:
                user_actions[u] = {"total": 0, "actions": {}}
            user_actions[u]["total"] += 1
            user_actions[u]["actions"][action] = user_actions[u]["actions"].get(action, 0) + 1

        # 签核周期分布
        signoff_stats = {"total": len(signoffs), "approved": 0, "pending": 0, "rejected": 0}
        for s in signoffs:
            st = s.get("status", "")
            if st in signoff_stats:
                signoff_stats[st] += 1

        stats["business"] = {
            "top_users": sorted(
                [{"username": u, "actions": d["total"], "top_action": max(d["actions"], key=d["actions"].get)}
                 for u, d in user_actions.items()],
                key=lambda x: -x["actions"]
            )[:10],
            "signoff_distribution": signoff_stats,
            "total_audit_records": len(recent_audit),
        }
    except Exception:
        pass

    return stats


@app.get("/api/ops/slow-flows")
async def get_slow_flows(user: dict = Depends(require_admin)):
    """最慢的流水线/签核流程"""
    from src.infra.observability import get_metrics
    metrics = get_metrics()
    stats = metrics.get_dashboard_stats()
    return {
        "slowest_pipelines": sorted(
            [{"run_id": p.run_id, "workflow": p.workflow, "duration_s": p.duration_s,
              "state": p.state, "started_at": p.started_at}
             for p in metrics._pipeline_runs],
            key=lambda x: -x["duration_s"]
        )[:10],
        "slowest_signoffs": sorted(
            [{"signoff_id": s.signoff_id, "title": s.title, "cycle_time_minutes": s.cycle_time_minutes}
             for s in metrics._signoff_cycles],
            key=lambda x: -x["cycle_time_minutes"]
        )[:10],
        "api_stats": stats.get("performance", {}),
    }


@app.get("/api/ops/errors")
async def get_error_summary(user: dict = Depends(require_admin)):
    """错误统计摘要"""
    from src.infra.observability import get_metrics
    metrics = get_metrics()
    stats = metrics.get_dashboard_stats()
    return {
        "error_summary": stats.get("errors", []),
        "module_failure_rates": stats.get("modules", {}).get("failure_rates", []),
    }


# ═══════════════════════════════════════════════════════════
# 插件管理 API
# ═══════════════════════════════════════════════════════════

@app.get("/api/admin/plugins")
async def list_plugins(user: dict = Depends(require_admin)):
    """列出所有已注册插件"""
    from src.infra.plugin_system import get_plugin_registry, ExtensionPoint
    registry = get_plugin_registry()
    plugins = []
    for pid, plugin in registry._plugins.items():
        plugins.append({
            "plugin_id": pid,
            "plugin_name": plugin.plugin_name,
            "extension_point": plugin.extension_point.value,
        })
    return {
        "plugins": plugins,
        "total": len(plugins),
        "extensions": registry.list_extensions(),
        "available_points": [e.value for e in ExtensionPoint],
    }


@app.post("/api/admin/plugins/bootstrap")
async def bootstrap_plugins_endpoint(user: dict = Depends(require_admin)):
    """手动触发插件系统初始化"""
    from src.infra.plugin_system import bootstrap_plugins
    registry = await bootstrap_plugins()
    return {"status": "bootstrapped", "plugins": len(registry._plugins)}


# ═══════════════════════════════════════════════════════════
# 领域边界 & 状态机检查 API
# ═══════════════════════════════════════════════════════════

@app.get("/api/domain/contexts")
async def list_bounded_contexts(user: dict = Depends(require_auth)):
    """列出所有限界上下文及其状态机"""
    from src.core.domain_registry import (
        PipelineState, SignoffState, DocState
    )
    from src.core.domain_registry import STATE_TRANSITIONS
    return {
        "contexts": {
            "pipeline": {
                "states": [s.value for s in PipelineState],
                "terminal": [s.value for s in PipelineState.terminal_states()],
            },
            "signoff": {
                "states": [s.value for s in SignoffState],
                "terminal": [s.value for s in SignoffState.terminal_states()],
            },
            "document": {
                "states": [s.value for s in DocState],
            },
        },
        "transitions": STATE_TRANSITIONS,
    }


# ═══════════════════════════════════════════════════════════
# 上下文快照 + 产物归类 API
# ═══════════════════════════════════════════════════════════

@app.post("/api/snapshots/capture")
async def capture_context_snapshot(run_id: str = "", workflow: str = "", phase: str = "",
                                   spec_text: str = "", user: dict = Depends(require_auth)):
    """捕获当前执行上下文快照"""
    from src.infra.context_snapshot import get_snapshotter
    snap = get_snapshotter().capture(run_id, workflow, phase, spec_text)
    if run_id:
        get_snapshotter().save(snap.snapshot_id)
    return {"snapshot_id": snap.snapshot_id, "status": "captured"}


@app.get("/api/snapshots")
async def list_snapshots(run_id: str = "", user: dict = Depends(require_auth)):
    """列出上下文快照"""
    from src.infra.context_snapshot import get_snapshotter
    return {"snapshots": get_snapshotter().list_snapshots(run_id)}


@app.get("/api/snapshots/{snapshot_id}")
async def get_snapshot(snapshot_id: str, user: dict = Depends(require_auth)):
    """获取指定快照详情"""
    from src.infra.context_snapshot import get_snapshotter
    snap = get_snapshotter().load(snapshot_id)
    if not snap:
        raise HTTPException(status_code=404, detail="快照不存在")
    return snap


@app.post("/api/artifacts/organize")
async def organize_artifacts(source_dir: str = "", dry_run: bool = False,
                             user: dict = Depends(require_admin)):
    """自动归类产物到分类目录"""
    from src.infra.context_snapshot import ArtifactClassifier
    classifier = ArtifactClassifier("output")
    result = classifier.organize(source_dir or None, dry_run)
    return result


@app.get("/api/artifacts/catalog")
async def get_artifact_catalog(user: dict = Depends(require_auth)):
    """获取产物分类目录"""
    from src.infra.context_snapshot import ArtifactClassifier
    classifier = ArtifactClassifier("output")
    return {"catalog": classifier.get_catalog()}


# ═══════════════════════════════════════════════════════════
# 失败聚类 + 知识复用 API
# ═══════════════════════════════════════════════════════════

@app.post("/api/ops/failure-cluster")
async def cluster_failures(failed_logs: list[dict] = None,
                           user: dict = Depends(require_auth)):
    """对失败日志进行聚类分析"""
    from src.infra.failure_cluster import get_failure_cluster
    engine = get_failure_cluster()
    return engine.analyze(failed_logs or [])


@app.post("/api/knowledge/extract")
async def extract_knowledge(run_id: str = "", success: bool = True,
                            phases: list[dict] = None, error_log: str = "",
                            user: dict = Depends(require_auth)):
    """从执行经验中自动提取知识"""
    from src.infra.failure_cluster import get_knowledge_extractor, get_failure_cluster
    extractor = get_knowledge_extractor()
    suggestions = []

    if success:
        suggestions = extractor.extract_from_success(run_id, phases or [])
    elif error_log:
        cluster_result = get_failure_cluster().analyze(
            [{"run_id": run_id, "error_log": error_log, "timestamp": datetime.now().isoformat()}])
        if cluster_result["clusters"]:
            s = extractor.extract_from_failure(run_id, error_log, cluster_result["clusters"][0])
            suggestions = [s]

    for s in suggestions:
        await extractor.auto_store(s)

    return {
        "run_id": run_id,
        "extracted": len(suggestions),
        "suggestions": [{"type": s.type, "title": s.title, "confidence": s.confidence} for s in suggestions],
    }


# ═══════════════════════════════════════════════════════════
# 批量操作 API
# ═══════════════════════════════════════════════════════════

@app.post("/api/batch/approve-signoffs")
async def batch_approve_signoffs(signoff_ids: list[int] = None, comment: str = "",
                                 user: dict = Depends(require_auth)):
    """批量批准签核"""
    if user.get("role") not in ("admin", "verification_manager"):
        raise HTTPException(status_code=403, detail="仅管理员和SignOff 经理可以批量批准")
    from src.infra.failure_cluster import get_batch_ops
    ops = get_batch_ops()
    result = await ops.batch_approve_signoffs(
        signoff_ids or [], user["user_id"],
        user.get("display_name", user["username"]), comment)
    from src.database.repository import add_audit_log
    await add_audit_log(user["user_id"], user["username"], "batch_approve",
                        "", f"{result.succeeded}/{result.total} approved",
                        role=user.get("role", ""), is_privileged=True)
    return {
        "operation": result.operation, "total": result.total,
        "succeeded": result.succeeded, "failed": result.failed,
        "skipped": result.skipped, "details": result.details,
    }


@app.post("/api/batch/sync-docs")
async def batch_sync_docs(project_ids: list[int] = None,
                          user: dict = Depends(require_admin)):
    """批量同步项目文档"""
    from src.infra.failure_cluster import get_batch_ops
    ops = get_batch_ops()
    result = await ops.batch_sync_docs(project_ids or [], user["user_id"])
    return {
        "operation": result.operation, "total": result.total,
        "succeeded": result.succeeded, "failed": result.failed,
        "details": result.details,
    }


# ═══════════════════════════════════════════════════════════
# 用户行为分析 API
# ═══════════════════════════════════════════════════════════

@app.post("/api/ops/track-action")
async def track_user_action(action: str = "", page: str = "", duration_ms: float = 0,
                            result: str = "success", detail: str = "",
                            user: dict = Depends(require_auth)):
    """记录用户操作（前端自动调用）"""
    from src.infra.behavior_analyzer import get_behavior_tracker
    tracker = get_behavior_tracker()
    tracker.track(
        username=user.get("username", "anonymous"),
        action=action, page=page,
        duration_ms=duration_ms, result=result, detail=detail,
    )
    return {"status": "tracked"}


@app.get("/api/ops/behavior-analysis")
async def get_behavior_analysis(days: int = 7, user: dict = Depends(require_admin)):
    """获取用户行为分析报告"""
    from src.infra.behavior_analyzer import get_behavior_tracker
    tracker = get_behavior_tracker()
    return tracker.get_analysis(days)


@app.get("/api/ops/stuck-points")
async def get_stuck_points(user: dict = Depends(require_admin)):
    """获取最常卡住的操作步骤"""
    from src.infra.behavior_analyzer import get_behavior_tracker
    tracker = get_behavior_tracker()
    return {"stuck_points": tracker.get_stuck_points()}


# ═══════════════════════════════════════════════════════════
# 文档一致性检查 API
# ═══════════════════════════════════════════════════════════

@app.get("/api/docs/consistency-check")
async def check_docs_consistency(spec_dir: str = "specs", doc_id: int = None,
                                 user: dict = Depends(require_auth)):
    """运行文档-代码一致性检查"""
    from src.infra.behavior_analyzer import get_doc_checker
    checker = get_doc_checker()

    result = checker.check_all(spec_dir)

    if doc_id:
        hash_issues = checker.check_spec_hash_integrity(doc_id)
        result["hash_check"] = {
            "issues": [{"type": i.type, "severity": i.severity,
                        "description": i.description} for i in hash_issues],
            "match": len(hash_issues) == 0,
        }

    return result


@app.post("/api/docs/consistency-check/auto-fix")
async def auto_fix_consistency_issues(user: dict = Depends(require_engineer)):
    """自动修复可自动处理的文档一致性问题"""
    from src.infra.behavior_analyzer import get_doc_checker
    checker = get_doc_checker()
    issues = checker.check_all()

    fixed = 0
    for i in issues.get("issues", []):
        if i.get("type") == "hash_mismatch":
            try:
                from src.database.repository import sync_fs_to_db
                await sync_fs_to_db("specs", 1, user["user_id"])
                fixed += 1
            except Exception:
                pass

    return {"fixed": fixed, "total_issues": issues.get("total_issues", 0)}


# ═══════════════════════════════════════════════════════════
# 流水线检查点 API (暂停/恢复/断点续跑)
# ═══════════════════════════════════════════════════════════

@app.post("/api/pipeline/{run_id}/pause")
async def pause_pipeline(run_id: str, user: dict = Depends(require_auth)):
    """暂停流水线"""
    from src.core.checkpoint import get_checkpoint_mgr
    mgr = get_checkpoint_mgr()
    ok = mgr.pause(run_id)
    if not ok:
        raise HTTPException(status_code=404, detail="检查点不存在，请先运行流水线")
    return {"ok": True, "run_id": run_id, "status": "paused"}


@app.post("/api/pipeline/{run_id}/resume")
async def resume_pipeline(run_id: str, user: dict = Depends(require_auth)):
    """从检查点恢复流水线"""
    from src.core.checkpoint import get_checkpoint_mgr
    from src.core.execution import PipelineExecutionService
    mgr = get_checkpoint_mgr()
    cp = mgr.resume(run_id)
    if not cp:
        raise HTTPException(status_code=404, detail="检查点不存在")
    return {
        "run_id": run_id, "status": "resumed",
        "resume_from": cp.current_phase,
        "progress": f"{cp.current_phase_index+1}/{cp.total_phases}",
        "resume_count": cp.resume_count,
    }


@app.get("/api/pipeline/checkpoints")
async def list_checkpoints(user: dict = Depends(require_auth)):
    """列出所有暂停的流水线"""
    from src.core.checkpoint import get_checkpoint_mgr
    mgr = get_checkpoint_mgr()
    return {"paused": mgr.list_paused()}


@app.get("/api/pipeline/{run_id}/checkpoint")
async def get_checkpoint(run_id: str, user: dict = Depends(require_auth)):
    """获取流水线的当前检查点"""
    from src.core.checkpoint import get_checkpoint_mgr
    cp = get_checkpoint_mgr().get(run_id)
    if not cp:
        raise HTTPException(status_code=404, detail="检查点不存在")
    return cp.to_dict()


# ═══════════════════════════════════════════════════════════
# 任务依赖图 API
# ═══════════════════════════════════════════════════════════

@app.get("/api/pipeline/dependency-graph")
async def get_dependency_graph(workflow: str = "full_verification",
                               user: dict = Depends(require_auth)):
    """获取任务依赖图（供前端渲染）"""
    from src.infra.resource_scheduler import get_dep_graph
    graph = get_dep_graph()
    return graph.build_graph(workflow)


@app.get("/api/pipeline/agent-deps/{role}")
async def get_agent_dependencies(role: str, user: dict = Depends(require_auth)):
    """获取单个 Agent 的上下游依赖"""
    from src.infra.resource_scheduler import get_dep_graph
    return get_dep_graph().get_agent_deps(role)


# ═══════════════════════════════════════════════════════════
# 资源调度 API
# ═══════════════════════════════════════════════════════════

@app.get("/api/admin/resources")
async def get_resource_status(user: dict = Depends(require_admin)):
    """获取资源池状态"""
    from src.infra.resource_scheduler import get_scheduler
    return get_scheduler().get_status()


@app.post("/api/admin/resources/configure")
async def configure_resources(max_agents: int = None, max_regressions: int = None,
                              user: dict = Depends(require_admin)):
    """配置资源池参数"""
    from src.infra.resource_scheduler import get_scheduler
    get_scheduler().configure(max_agents=max_agents, max_regressions=max_regressions)
    return {"ok": True, "status": get_scheduler().get_status()}


# ═══════════════════════════════════════════════════════════
# 配置化工作流 API
# ═══════════════════════════════════════════════════════════

@app.get("/api/workflows")
async def list_workflow_templates(user: dict = Depends(require_auth)):
    """列出所有工作流模板"""
    from src.infra.workflow_config import get_workflow_registry
    registry = get_workflow_registry()
    return {"workflows": registry.list_all()}


@app.get("/api/workflows/{name}")
async def get_workflow_detail(name: str, user: dict = Depends(require_auth)):
    """获取工作流模板详情（含步骤依赖）"""
    from src.infra.workflow_config import get_workflow_registry
    registry = get_workflow_registry()
    deps = registry.get_step_deps(name)
    tmpl = registry.get(name)
    if not tmpl:
        raise HTTPException(status_code=404, detail="模板不存在")
    return {**tmpl.to_dict(), "step_deps": deps}


@app.post("/api/workflows")
async def create_workflow_template(name: str = "", description: str = "",
                                   category: str = "custom", steps: list[dict] = None,
                                   user: dict = Depends(require_auth)):
    """创建自定义工作流模板"""
    from src.infra.workflow_config import get_workflow_registry
    registry = get_workflow_registry()
    data = {"name": name, "description": description,
            "category": category, "steps": steps or []}
    tmpl = registry.create_from_dict(data)
    errors = registry.validate(tmpl)
    if errors:
        raise HTTPException(status_code=400, detail={"errors": errors})
    registry.register(tmpl)
    return {"name": name, "status": "created", "steps": len(steps or [])}


@app.get("/api/workflows/{name}/validate")
async def validate_workflow(name: str, user: dict = Depends(require_auth)):
    """验证工作流合法性"""
    from src.infra.workflow_config import get_workflow_registry
    registry = get_workflow_registry()
    tmpl = registry.get(name)
    if not tmpl:
        raise HTTPException(status_code=404, detail="模板不存在")
    errors = registry.validate(tmpl)
    return {"name": name, "valid": len(errors) == 0, "errors": errors}


@app.get("/api/workflows/{name}/export")
async def export_workflow_yaml(name: str, user: dict = Depends(require_auth)):
    """导出工作流为 YAML"""
    from src.infra.workflow_config import get_workflow_registry
    registry = get_workflow_registry()
    yaml_str = registry.export_to_yaml(name)
    if not yaml_str:
        raise HTTPException(status_code=404, detail="模板不存在")
    return {"name": name, "yaml": yaml_str}


# ═══════════════════════════════════════════════════════════
# 角色→工作流绑定管理 (Admin only)
# ═══════════════════════════════════════════════════════════

@app.get("/api/admin/role-workflow-bindings")
async def list_role_workflow_bindings_api(role: str = "", user: dict = Depends(require_admin)):
    """列出所有角色→工作流绑定（管理员）"""
    from src.database.repository import list_role_workflow_bindings as lrwb
    from src.infra.workflow_config import get_workflow_registry
    bindings = await lrwb(role)
    registry = get_workflow_registry()
    available_workflows = [w["name"] for w in registry.list_all()]
    return {"bindings": bindings, "available_workflows": available_workflows}


@app.post("/api/admin/role-workflow-bindings")
async def create_role_workflow_binding_api(req: RoleWorkflowBindingRequest,
                                            user: dict = Depends(require_admin)):
    """创建角色→工作流绑定（管理员）"""
    from src.database.repository import create_role_workflow_binding
    from src.infra.workflow_config import get_workflow_registry
    registry = get_workflow_registry()
    available = [w["name"] for w in registry.list_all()]
    if req.workflow_name not in available:
        raise HTTPException(status_code=400,
                           detail=f"未知工作流: {req.workflow_name}，可用: {available}")
    bid = await create_role_workflow_binding(
        req.role, req.workflow_name, req.is_default, req.description, user["user_id"])
    from src.database.repository import add_audit_log
    await add_audit_log(user["user_id"], user["username"], "rwb_create", str(bid),
                        f"role={req.role} workflow={req.workflow_name} default={req.is_default}",
                        role=user.get("role", ""), resource_type="workflow", is_privileged=True)
    return {"id": bid, "status": "created"}


@app.put("/api/admin/role-workflow-bindings/{binding_id}")
async def update_role_workflow_binding_api(binding_id: int,
                                            req: RoleWorkflowBindingRequest,
                                            user: dict = Depends(require_admin)):
    """更新角色→工作流绑定（管理员）"""
    from src.database.repository import update_role_workflow_binding, get_role_workflow_binding
    from src.infra.workflow_config import get_workflow_registry
    existing = await get_role_workflow_binding(binding_id)
    if not existing:
        raise HTTPException(status_code=404, detail="绑定不存在")
    registry = get_workflow_registry()
    available = [w["name"] for w in registry.list_all()]
    if req.workflow_name not in available:
        raise HTTPException(status_code=400,
                           detail=f"未知工作流: {req.workflow_name}，可用: {available}")
    ok = await update_role_workflow_binding(binding_id,
        role=req.role, workflow_name=req.workflow_name,
        is_default=req.is_default, description=req.description)
    from src.database.repository import add_audit_log
    await add_audit_log(user["user_id"], user["username"], "rwb_update", str(binding_id),
                        f"role={req.role} workflow={req.workflow_name} default={req.is_default}",
                        role=user.get("role", ""), resource_type="workflow", is_privileged=True)
    return {"ok": ok}


@app.delete("/api/admin/role-workflow-bindings/{binding_id}")
async def delete_role_workflow_binding_api(binding_id: int,
                                            user: dict = Depends(require_admin)):
    """删除角色→工作流绑定（管理员）"""
    from src.database.repository import delete_role_workflow_binding, get_role_workflow_binding
    existing = await get_role_workflow_binding(binding_id)
    if not existing:
        raise HTTPException(status_code=404, detail="绑定不存在")
    ok = await delete_role_workflow_binding(binding_id)
    from src.database.repository import add_audit_log
    await add_audit_log(user["user_id"], user["username"], "rwb_delete", str(binding_id),
                        f"role={existing.role} workflow={existing.workflow_name}",
                        role=user.get("role", ""), resource_type="workflow", is_privileged=True)
    return {"ok": ok}


@app.get("/api/my-allowed-workflows")
async def get_my_allowed_workflows(user: dict = Depends(require_auth)):
    """返回当前用户角色可用的工作流列表 + 默认工作流"""
    from src.database.repository import get_allowed_workflows_for_role, get_default_workflow_for_role
    role = user.get("role", "engineer")
    allowed = await get_allowed_workflows_for_role(role)
    default_wf = await get_default_workflow_for_role(role)
    return {"role": role, "allowed_workflows": allowed, "default_workflow": default_wf}


# ═══════════════════════════════════════════════════════════
# 多租户 API
# ═══════════════════════════════════════════════════════════

@app.get("/api/admin/tenants")
async def list_tenants(user: dict = Depends(require_admin)):
    """列出所有租户"""
    from src.infra.platform_health import get_tenant_mgr
    return {"tenants": get_tenant_mgr().list_tenants()}


@app.post("/api/admin/tenants")
async def create_tenant(tenant_id: str = "", name: str = "", description: str = "",
                        user: dict = Depends(require_admin)):
    """创建租户"""
    from src.infra.platform_health import get_tenant_mgr
    tenant = get_tenant_mgr().create_tenant(tenant_id, name, description)
    return {"tenant_id": tenant.tenant_id, "name": tenant.name, "status": "created"}


# ═══════════════════════════════════════════════════════════
# 平台健康管理 API
# ═══════════════════════════════════════════════════════════

@app.get("/api/admin/health-check")
async def run_platform_health_check(user: dict = Depends(require_admin)):
    """运行平台全面健康检查"""
    from src.infra.platform_health import get_health_monitor
    return get_health_monitor().check_all()


@app.get("/api/admin/expired-rules")
async def get_expired_rules(days: int = 90, user: dict = Depends(require_admin)):
    """获取过期规则列表"""
    from src.infra.platform_health import get_health_monitor
    return {"expired": get_health_monitor().get_expired_rules(days=days)}
