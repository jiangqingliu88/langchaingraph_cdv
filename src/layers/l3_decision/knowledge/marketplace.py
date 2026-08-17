"""
签核证据 marketplace（V4）—— 把验证知识打包成可跨项目复用的「签核证据包」

V4 的目标之一：验证知识不是一次性的，而是可导出的资产。一个项目签核完成后，
它的 KG（需求→功能→模块→信号→bin→bug→fix）+ 覆盖率摘要打包成一个 JSON 包，
其它项目导入后复用（跨项目迁移）。

包结构:
  {
    "version": "1.0",
    "project": "...",
    "graph": {nodes, edges},       # VerificationGraph.to_dict()
    "signoff": {coverage, bugs, fixes}
  }

用法:
    from src.layers.l3_decision.knowledge.marketplace import (
        export_signoff_package, load_signoff_package)
    export_signoff_package(graph, "gemm", {"functional": 96.0}, "gemm_signoff.json")
    pkg, graph = load_signoff_package("gemm_signoff.json")
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from .graph import VerificationGraph


def export_signoff_package(graph: VerificationGraph, project_name: str,
                           coverage: Dict[str, float], output_path: str,
                           bugs: List[Dict] = None, fixes: List[Dict] = None) -> str:
    """导出签核证据包（KG + 覆盖率 + bug/fix 历史）到 JSON。"""
    package = {
        "version": "1.0",
        "project": project_name,
        "graph": graph.to_dict(),
        "signoff": {
            "coverage": coverage,
            "bugs": bugs or [],
            "fixes": fixes or [],
        },
    }
    p = Path(output_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(package, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(p)


def load_signoff_package(package_path: str) -> Dict[str, Any]:
    """加载签核证据包，返回 {project, graph, signoff}。"""
    data = json.loads(Path(package_path).read_text(encoding="utf-8"))
    return {
        "project": data.get("project", ""),
        "graph": VerificationGraph.from_dict(data.get("graph", {})),
        "signoff": data.get("signoff", {}),
        "version": data.get("version", "1.0"),
    }


def merge_package_into_graph(target: VerificationGraph, package: Dict[str, Any]) -> int:
    """把签核证据包里的图合并进目标图（跨项目复用），返回新增节点数。"""
    before = len(target)
    target.merge(package["graph"])
    return len(target) - before
