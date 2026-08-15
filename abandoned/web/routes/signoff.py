"""
Signoff routes — 签核 CRUD + 审批 + 证据链 + Manifest
"""
from __future__ import annotations

import json, os, hashlib
from pathlib import Path
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, Body
from pydantic import BaseModel, Field

from src.core.auth import require_auth, require_admin, get_current_user
from src.database import repository

router = APIRouter(prefix="/api", tags=["signoff"])

WORKSPACE_ROOT = Path(os.environ.get("IC_VERIFY_WORKSPACE", Path.cwd())).resolve()
OUTPUT_ROOT = (WORKSPACE_ROOT / "output").resolve()


class SignoffCreateRequest(BaseModel):
    project_id: int = 0
    title: str
    report_type: str = "tapeout"
    summary: dict = Field(default_factory=dict)


# ═══════════════════════════════════════════════════════════
# 签核 CRUD
# ═══════════════════════════════════════════════════════════

@router.get("/signoffs")
async def list_signoffs(project_id: int = None):
    return {"signoffs": await repository.list_signoffs(project_id)}


@router.post("/signoffs")
async def create_signoff_api(req: SignoffCreateRequest, user: dict = Depends(require_auth)):
    """创建签核 — 路由层仅提取参数，业务逻辑在 SignoffService"""
    from src.core.services import get_signoff_service
    # 尝试获取最新 manifest
    run_id = ""
    manifest_hash = ""
    try:
        for mf in sorted(Path("output").glob("**/docs/manifest.json"),
                         key=lambda p: p.stat().st_mtime, reverse=True):
            data = json.loads(mf.read_text(encoding="utf-8"))
            run_id = data.get("run_id", "")
            manifest_hash = data.get("manifest_hash", "")
            break
    except Exception:
        pass

    svc = get_signoff_service()
    result = await svc.create(req.project_id, req.title, req.report_type,
                              req.summary, user["user_id"],
                              run_id=run_id, manifest_hash=manifest_hash)
    return result


@router.put("/signoffs/{sid}/approve")
async def approve_signoff(sid: int, comment: str = "", user: dict = Depends(require_auth)):
    """批准签核 — 路由层仅调用 Service，业务逻辑全部在 SignoffService"""
    from src.core.services import get_signoff_service
    svc = get_signoff_service()
    try:
        result = await svc.approve(
            sid, user["user_id"],
            user.get("display_name", user["username"]),
            user.get("role", ""), comment)
        return result
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/signoffs/{sid}/reject")
async def reject_signoff(sid: int, comment: str = "", user: dict = Depends(require_auth)):
    """驳回签核 — 路由层仅调用 Service"""
    from src.core.services import get_signoff_service
    svc = get_signoff_service()
    try:
        result = await svc.reject(
            sid, user["user_id"],
            user.get("display_name", user["username"]),
            user.get("role", ""), comment)
        return result
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/signoffs/{sid}")
async def soft_delete_signoff_endpoint(sid: int, user: dict = Depends(require_auth)):
    if user.get("role") not in ("admin", "verification_manager"):
        raise HTTPException(status_code=403, detail="仅管理员和SignOff 经理可以删除签核")
    ok = await repository.soft_delete_signoff(sid)
    if not ok:
        raise HTTPException(status_code=404, detail="签核不存在")
    await repository.add_audit_log(user["user_id"], user["username"], "signoff_soft_delete",
                                   str(sid), "软删除签核", role=user.get("role", ""),
                                   resource_type="signoff", is_privileged=True)
    return {"ok": True, "status": "deleted"}


@router.post("/signoffs/{sid}/archive")
async def archive_signoff_endpoint(sid: int, user: dict = Depends(require_auth)):
    ok = await repository.archive_signoff(sid)
    if not ok:
        raise HTTPException(status_code=404, detail="签核不存在")
    await repository.add_audit_log(user["user_id"], user["username"], "signoff_archive",
                                   str(sid), "归档签核", role=user.get("role", ""),
                                   resource_type="signoff")
    return {"ok": True, "status": "archived"}


# ═══════════════════════════════════════════════════════════
# 签核事件 & 证据
# ═══════════════════════════════════════════════════════════

@router.get("/signoffs/{sid}/events")
async def get_signoff_events_api(sid: int):
    events = await repository.get_signoff_events(sid)
    return {"signoff_id": sid, "events": events, "total": len(events)}


@router.get("/signoffs/{sid}/evidence")
async def get_signoff_evidence(sid: int):
    sf = await repository.get_signoff_by_id(sid)
    if not sf:
        raise HTTPException(status_code=404, detail="签核记录不存在")

    summary = sf.get("summary", {}) or {}
    run_id = summary.get("run_id", "")
    manifest_data = None
    integrity = None

    if run_id:
        try:
            for mf in sorted(Path("output").glob("**/docs/manifest.json"),
                             key=lambda p: p.stat().st_mtime, reverse=True):
                try:
                    data = json.loads(mf.read_text(encoding="utf-8"))
                    if data.get("run_id") == run_id:
                        manifest_data = data
                        break
                except Exception:
                    pass
        except Exception:
            pass

    if run_id and manifest_data:
        try:
            from src.core.manifest import hash_json
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
        "signoff_id": sid, "status": sf.get("status", ""),
        "run_id": run_id, "manifest_hash": summary.get("manifest_hash", ""),
        "evidence_hash": summary.get("evidence_hash", ""),
        "manifest": manifest_data, "integrity": integrity, "summary": summary,
    }


@router.get("/signoffs/{sid}/timeline")
async def get_signoff_timeline(sid: int):
    logs = await repository.get_audit_logs(limit=200)
    related = []
    for log in logs:
        target = log.get("target", "") or log.get("target_id", "")
        action = log.get("action", "")
        if str(sid) in str(target) or action.startswith("signoff"):
            related.append({
                "id": log.get("id", 0), "username": log.get("username", ""),
                "action": action, "detail": log.get("detail", ""),
                "timestamp": str(log.get("created_at", "")),
            })

    sf = await repository.get_signoff_by_id(sid)
    timeline = []
    if sf:
        timeline.append({"event": "created", "title": "签核创建",
                         "description": f"创建签核: {sf.get('title', '')}",
                         "timestamp": str(sf.get("created_at", "")), "icon": "📝"})
        if sf.get("approved_at"):
            timeline.append({"event": "approved", "title": "签核批准",
                             "description": f"由 {sf.get('approved_by_name', 'N/A')} 批准",
                             "timestamp": str(sf.get("approved_at", "")), "icon": "✅"})
        elif sf.get("status") == "rejected":
            timeline.append({"event": "rejected", "title": "签核驳回",
                             "description": sf.get("reject_reason", ""),
                             "timestamp": str(sf.get("updated_at", "")), "icon": "❌"})

    icon_map = {"signoff_create": "📝", "signoff_approve": "✅", "signoff_reject": "❌",
                "evidence_export": "📦", "pipeline_run": "▶️"}
    for log in related:
        timeline.append({
            "event": log["action"], "title": log["action"].replace("_", " ").title(),
            "description": log.get("detail", ""), "timestamp": log["timestamp"],
            "icon": icon_map.get(log["action"], "📋"), "user": log["username"],
        })
    timeline.sort(key=lambda x: x.get("timestamp", ""))
    return {"signoff_id": sid, "timeline": timeline, "total_events": len(timeline)}


# ═══════════════════════════════════════════════════════════
# 证据产物 & 证据关联
# ═══════════════════════════════════════════════════════════

@router.get("/artifacts")
async def list_artifacts(run_id: str = "", signoff_id: int = None,
                         artifact_type: str = "", limit: int = 50):
    return {"artifacts": await repository.get_artifacts(run_id, signoff_id, artifact_type, limit)}


@router.post("/artifacts")
async def create_artifact_api(project_id: int = 0, run_id: str = "", signoff_id: int = 0,
                              artifact_type: str = "", name: str = "", path: str = "",
                              content_hash: str = "", size_bytes: int = 0,
                              user: dict = Depends(require_auth)):
    aid = await repository.create_artifact(project_id, run_id, signoff_id, artifact_type,
                                           name, path, content_hash, size_bytes)
    await repository.add_audit_log(user["user_id"], user["username"], "artifact_create",
                                   str(aid), f"{artifact_type}: {name}",
                                   role=user.get("role", ""), resource_type="artifact")
    return {"id": aid, "status": "registered"}


@router.get("/evidence-links")
async def list_evidence_links(object_type: str = "", object_id: int = None, limit: int = 50):
    return {"links": await repository.get_evidence_links(object_type, object_id, limit)}


@router.post("/evidence-links")
async def create_evidence_link_api(artifact_id: int = 0, object_type: str = "",
                                   object_id: int = 0, relation_type: str = "attached_to",
                                   user: dict = Depends(require_auth)):
    lid = await repository.link_evidence(artifact_id, object_type, object_id, relation_type)
    await repository.add_audit_log(user["user_id"], user["username"], "evidence_link",
                                   str(lid), f"{object_type}#{object_id} <- artifact#{artifact_id}",
                                   role=user.get("role", ""), resource_type="evidence")
    return {"id": lid, "status": "linked"}


# ═══════════════════════════════════════════════════════════
# Manifest / 证据链 API
# ═══════════════════════════════════════════════════════════

def _resolve_output_path(value: str) -> Path:
    path = Path(value or ".")
    if path.parts and path.parts[0].lower() == "output":
        path = Path(*path.parts[1:])
    resolved = (OUTPUT_ROOT / path).resolve()
    if not resolved.is_relative_to(OUTPUT_ROOT):
        raise HTTPException(status_code=403, detail="path is outside the allowed workspace")
    return resolved


@router.get("/manifest/latest")
async def get_latest_manifest():
    from pathlib import Path
    import json
    docs_dirs = sorted(Path("output").glob("**/docs/manifest.json"),
                       key=lambda p: p.stat().st_mtime, reverse=True)
    if docs_dirs:
        try:
            return json.loads(docs_dirs[0].read_text(encoding="utf-8"))
        except Exception:
            pass
    fallback = sorted(Path("output").glob("*/docs/manifest.json"),
                      key=lambda p: p.stat().st_mtime, reverse=True)
    if fallback:
        try:
            return json.loads(fallback[0].read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"error": "no manifest found", "run_id": "", "session_id": ""}


@router.get("/manifest/{session_id}")
async def get_manifest(session_id: str):
    import json
    for pattern in [f"**/{session_id}/**/manifest.json", "**/docs/manifest.json"]:
        for mf in Path("output").glob(pattern):
            try:
                data = json.loads(mf.read_text(encoding="utf-8"))
                if data.get("session_id") == session_id:
                    return data
            except Exception:
                pass
    raise HTTPException(status_code=404, detail=f"Manifest not found for session {session_id}")


@router.get("/manifest/{session_id}/export")
async def export_evidence_package(session_id: str, user: dict = Depends(get_current_user)):
    import tempfile
    from fastapi.responses import FileResponse
    try:
        from src.core.manifest import export_evidence_package as export_pkg
        username = user.get("username", "anonymous") if user else "anonymous"
        uid = user.get("user_id", 0) if user else 0
        try:
            await repository.add_audit_log(uid, username, "evidence_export", session_id, "证据包导出")
        except Exception:
            pass
        tmp_dir = Path(tempfile.mkdtemp())
        zip_path = tmp_dir / f"signoffai_evidence_{session_id}.zip"
        result = export_pkg(session_id, str(zip_path))
        return FileResponse(
            path=str(result), media_type="application/zip",
            filename=f"signoffai_evidence_{session_id}.zip",
            headers={"X-Evidence-Hash": "See manifest.json in archive"},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Evidence export failed: {e}")


@router.get("/manifest")
async def list_manifests():
    from src.core.manifest import list_sessions
    return {"sessions": list_sessions()}


@router.get("/manifest/{session_id}/verify")
async def verify_manifest_integrity(session_id: str):
    import json, hashlib
    result = {
        "session_id": session_id, "valid": False,
        "manifest_hash_ok": False, "evidence_hash_ok": False,
        "phases_complete": False, "file_count": 0,
        "missing_files": [], "hash_mismatches": [], "issues": [],
    }

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

    stored_hash = manifest_data.get("manifest_hash", "")
    calc_data = {k: v for k, v in manifest_data.items() if k != "manifest_hash"}
    from src.core.manifest import hash_json
    calc_hash = hash_json(calc_data)
    result["manifest_hash_ok"] = stored_hash == calc_hash
    if not result["manifest_hash_ok"]:
        result["issues"].append("Manifest hash mismatch — evidence may be tampered")

    phases = manifest_data.get("phases", [])
    total = manifest_data.get("total_phases", len(phases))
    result["phases_complete"] = len(phases) == total
    result["total_phases"] = total
    result["phases_completed"] = len(phases)

    output_root = manifest_data.get("output_root", "")
    output_path = Path(output_root)
    if not output_path.is_absolute():
        output_path = Path(os.getcwd()) / output_root
    if output_root and output_path.exists():
        all_files = [f for f in output_path.rglob("*") if f.is_file() and not f.name.startswith(".")]
        result["file_count"] = len(all_files)
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
                            result["hash_mismatches"].append({
                                "file": art, "expected": expected_hash[:16],
                                "actual": actual[:16],
                            })

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
    if result["valid"]:
        result["conclusion"] = "🟢 证据链完整，未被篡改"
    elif result["manifest_hash_ok"]:
        result["conclusion"] = "🟡 证据链部分可验证，存在文件缺失或变更"
    else:
        result["conclusion"] = "🔴 证据链已被篡改或损坏"

    return result


@router.get("/evidence/latest")
async def get_latest_evidence():
    import json
    for ef in sorted(Path("output").glob("**/evidence_chain.json"),
                     key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            return json.loads(ef.read_text(encoding="utf-8"))
        except Exception:
            pass
    raise HTTPException(status_code=404, detail="No evidence chain found")


@router.get("/evidence/{run_id}")
async def get_evidence_chain(run_id: str):
    import json
    for ef in sorted(Path("output").glob("**/evidence_chain.json"),
                     key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            data = json.loads(ef.read_text(encoding="utf-8"))
            rid = data.get("run_id", "")
            if rid == run_id or run_id in rid or rid.endswith(run_id[-12:]):
                return data
        except Exception:
            pass
    raise HTTPException(status_code=404, detail=f"Evidence chain not found for {run_id}")


@router.get("/engines/latest")
async def get_latest_engines():
    import json
    for ef in sorted(Path("output").glob("**/docs/engines.json"),
                     key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            return json.loads(ef.read_text(encoding="utf-8"))
        except Exception:
            pass
    raise HTTPException(status_code=404, detail="No engines output found — run vagent verify first")


# ═══════════════════════════════════════════════════════════
# 五大引擎独立 API
# ═══════════════════════════════════════════════════════════

from typing import List as TypingList


@router.post("/engines/vplan")
async def generate_vplan(spec_text: str = "", module_name: str = ""):
    from src.core.engines import VPlanGenerator
    gen = VPlanGenerator()
    vplan = gen.generate(spec_text, module_name)
    return {
        "module": module_name or "auto",
        "requirements": [{"id": r["id"], "description": r["description"]} for r in vplan.requirements],
        "coverage_points": [{"name": cp.name, "description": cp.description,
                             "category": cp.category, "target": cp.target}
                            for cp in vplan.coverage_points],
        "testcases": [{"name": tc.name, "description": tc.description,
                       "level": tc.level, "coverage_points": tc.coverage_points}
                      for tc in vplan.testcases],
        "risk_items": vplan.risk_items,
        "coverage_targets": vplan.coverage_targets,
        "signoff_criteria": vplan.signoff_criteria,
        "traceability": vplan.traceability_matrix,
    }


@router.post("/engines/smart-regression")
async def smart_regression(coverage_data: dict = None, testcases: TypingList[dict] = None):
    from src.core.engines import CoverageDrivenRegressor
    reg = CoverageDrivenRegressor(coverage_data or {}, testcases or [])
    plan = reg.select()
    return {
        "selected": plan.selected_tests, "skipped": plan.skipped_tests,
        "gaps_addressed": plan.coverage_gaps_addressed,
        "estimated_runtime": plan.estimated_runtime,
        "original_runtime": plan.original_runtime,
        "time_saved_pct": plan.time_saved_pct,
    }


@router.post("/engines/debug")
async def debug_copilot(log_text: str = ""):
    from src.core.engines import DebugCopilot
    copilot = DebugCopilot()
    insights = copilot.analyze(log_text)
    return {
        "insights": [{"type": i.error_type, "location": i.location,
                      "root_cause": i.root_cause, "suggested_fix": i.suggested_fix,
                      "confidence": i.confidence, "auto_fixable": i.auto_fixable}
                     for i in insights],
        "time_saved": copilot.time_saved_estimate(insights),
        "total_insights": len(insights),
    }


@router.post("/engines/triage")
async def regression_triage(failed_logs: TypingList[dict] = None):
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
