"""工程服务 facade：verify / optimize / coverage / soc / ip。"""
from src.interfaces.api.verify_service import (
    run_multi_module, run_multi_module_async, run_verify, run_verify_async,
)
from src.interfaces.api.optimize_regression_service import analyze_plan, execute_plan
from src.interfaces.api.coverage_closure_service import run_closure
from src.interfaces.api.soc_service import (
    list_c_cases, run_c_case, run_c_project, run_ip_regression, run_soc_project,
)
from src.interfaces.api.ip_service import (
    list_ips, ip_info, ip_plan, ip_status, write_ip_evidence, build_ip_release,
)
from src.interfaces.api.case_view_service import (
    artifact as case_artifact, case_gate, case_view, list_artifacts,
    rebuild_evidence,
)
from src.interfaces.api.manual_signoff_service import (
    manual_signoff, record_case_decision, seal_tb_rtl, unseal,
)
from src.interfaces.api.agent_mode_service import (
    agent_turn, last_session, render as render_agent, resume_turn,
)

__all__ = [
    "run_verify", "run_verify_async",
    "run_multi_module", "run_multi_module_async",
    "analyze_plan", "execute_plan",
    "run_closure",
    "run_soc_project", "run_c_project", "run_c_case", "list_c_cases",
    "run_ip_regression",
    "list_ips", "ip_info", "ip_plan", "ip_status", "write_ip_evidence",
    "build_ip_release",
    "case_artifact", "case_gate", "case_view", "list_artifacts",
    "rebuild_evidence",
    "manual_signoff", "record_case_decision", "seal_tb_rtl", "unseal",
    "agent_turn", "resume_turn", "last_session", "render_agent",
]
