"""SoC / IP 工程服务 —— CLI/Workbench 共用的 facade。

过渡实现：底层仍是 `src.workbench.cli.soc_adapter` / `soc_c_runner` 的工程适配函数
（它们已经是「读工程 + 调现有回归」的薄层）。等这些函数搬进 app 层后，
CLI 只保留参数解析。**不造第二套执行引擎。**
"""
from __future__ import annotations

from typing import Any, Dict, List


def _adapter():
    from src.workbench.cli import soc_adapter
    return soc_adapter


def run_soc_project(project_root, output=None) -> Dict[str, Any]:
    return _adapter().run_soc_project(project_root, output)


def run_c_project(project_root, case: str = "", output=None) -> Dict[str, Any]:
    from src.workbench.cli.soc_c_runner import run_c_case
    return run_c_case(project_root, case, output)


def run_c_case(project_root, case_id: str = "", output=None) -> Dict[str, Any]:
    """兼容 Workbench 绑定名 `soc.c_run`。"""
    return run_c_project(project_root, case_id, output)


def list_c_cases(project_root) -> List[Dict[str, Any]]:
    from src.workbench.cli.soc_c_runner import list_c_cases as _impl
    return _impl(project_root)


def project_info(project_root) -> Dict[str, Any]:
    return _adapter().project_info(project_root)


def list_soc_runs(base=".") -> List[Dict[str, Any]]:
    return _adapter().list_soc_runs(base)


def run_summary(run_root) -> Dict[str, Any]:
    return _adapter().run_summary(run_root)


def verify_soc_evidence(run_root) -> Dict[str, Any]:
    return _adapter().verify_soc_evidence(run_root)


def load_run_manifest(run_root) -> Dict[str, Any]:
    return _adapter().load_run_manifest(run_root)


def find_design(run_root, wave=None):
    return _adapter().find_design(run_root, wave)


def find_wave(run_root, test: str = ""):
    return _adapter().find_wave(run_root, test)


# ── IP ──
def list_ips(project_root) -> List[Dict[str, Any]]:
    return _adapter().list_ips(project_root)


def ip_info(project_root, ip_id: str) -> Dict[str, Any]:
    return _adapter().ip_info(project_root, ip_id)


def ip_plan(project_root, ip_id: str = "") -> Dict[str, Any]:
    return _adapter().ip_plan(project_root, ip_id)


def ip_status(project_root, ip_id: str, run_root="") -> Dict[str, Any]:
    return _adapter().ip_status(project_root, ip_id, run_root)


def write_ip_evidence(project_root, ip_id: str, run_root="") -> Dict[str, Any]:
    return _adapter().write_ip_evidence(project_root, ip_id, run_root)


def build_ip_release(project_root, ip_id: str, run_root="",
                     released_by: str = "") -> Dict[str, Any]:
    return _adapter().build_ip_release(project_root, ip_id, run_root, released_by)


def verify_ip_release(project_root, ip_id: str) -> Dict[str, Any]:
    return _adapter().verify_ip_release(project_root, ip_id)


def soc_ip_binding(project_root) -> List[Dict[str, Any]]:
    return _adapter().soc_ip_binding(project_root)


def soc_ip_release_matrix(project_root) -> List[Dict[str, Any]]:
    return _adapter().soc_ip_release_matrix(project_root)


def run_ip_regression(project_root, ip_id: str, output=None) -> Dict[str, Any]:
    return _adapter().run_ip_regression(project_root, ip_id, output)
