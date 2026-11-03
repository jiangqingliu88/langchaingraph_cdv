"""工程服务 facade：verify / optimize / coverage / soc / ip。"""
from src.app.services.verify_service import run_verify
from src.app.services.optimize_regression_service import analyze_plan, execute_plan
from src.app.services.coverage_closure_service import run_closure
from src.app.services.soc_service import (
    list_c_cases, run_c_case, run_c_project, run_ip_regression, run_soc_project,
)
from src.app.services.ip_service import (
    list_ips, ip_info, ip_plan, ip_status, write_ip_evidence, build_ip_release,
)

__all__ = [
    "run_verify",
    "analyze_plan", "execute_plan",
    "run_closure",
    "run_soc_project", "run_c_project", "run_c_case", "list_c_cases",
    "run_ip_regression",
    "list_ips", "ip_info", "ip_plan", "ip_status", "write_ip_evidence",
    "build_ip_release",
]
