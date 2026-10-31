"""IP 页面公共壳 —— IP 清单来自 `spec/ip_manifest.yaml`（经 bridge 白名单）。"""
from __future__ import annotations

from typing import Any, Dict, List

from ..base import ModuleBase
from ..soc.common import find_project_root


class IpModuleBase(ModuleBase):
    def __init__(self, ctx, spec) -> None:
        super().__init__(ctx, spec)
        self.project_root = find_project_root()
        self._ips: List[Dict[str, Any]] = []

    def load_ips(self) -> List[Dict[str, Any]]:
        payload = self.run_tool("ip.list", quiet=True,
                                root=str(self.project_root))
        self._ips = payload if isinstance(payload, list) else []
        return self._ips

    def ip_info(self, ip_id: str) -> Dict[str, Any]:
        payload = self.run_tool("ip.info", quiet=True,
                                root=str(self.project_root), ip_id=ip_id)
        return payload if isinstance(payload, dict) else {}
