"""IP 工程服务 —— 复用 SoC 工程适配层，不另造一套 IP 引擎。"""
from src.workbench.api.soc_service import (
    build_ip_release, ip_info, ip_plan, ip_status, list_ips, run_ip_regression,
    soc_ip_binding, soc_ip_release_matrix, verify_ip_release, write_ip_evidence,
)

__all__ = [
    "list_ips", "ip_info", "ip_plan", "ip_status", "write_ip_evidence",
    "build_ip_release", "verify_ip_release", "soc_ip_binding",
    "soc_ip_release_matrix", "run_ip_regression",
]
