"""
RunRepository —— run 数据访问层（磁盘扫描，唯一可靠来源）。

内存 `_runs` 会随进程重启丢失，数据库可能不完整，所以 CLI 查询命令以
output 目录为唯一可靠来源。每次 run 落盘到 `output/{prefix}_{user}_{timestamp}/`，
本层扫描这些目录，读取 manifest.json / report.json / coverage_result.json / 日志。

用法:
    from src.layers.l2_orchestration.run_repository import RunRepository
    repo = RunRepository("output")
    repo.list_runs()              # 所有 run 摘要
    repo.get_run("e2e_final_...")  # 单 run 完整数据
    repo.compare(a, b)             # 对比两次 run 覆盖率
    repo.logs(run_id, "compile")   # 阶段日志
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional


class RunRepository:
    """从 output 目录扫描 run 数据。"""

    def __init__(self, output_base: str = "output"):
        self.output_base = Path(output_base)

    # ═══════════════════════════════════════════════════════════
    # 扫描
    # ═══════════════════════════════════════════════════════════

    def list_runs(self, limit: int = 50) -> List[Dict[str, Any]]:
        """扫描 output/*/，返回 run 摘要列表（按目录名倒序，即新 run 在前）。"""
        if not self.output_base.exists():
            return []
        runs = []
        for d in sorted(self.output_base.iterdir(), reverse=True):
            if not d.is_dir() or d.name.startswith("."):
                continue
            manifest = d / "docs" / "manifest.json"
            if not manifest.exists():
                continue
            runs.append(self._summary(d, manifest))
            if len(runs) >= limit:
                break
        return runs

    def _summary(self, run_dir: Path, manifest_path: Path) -> Dict[str, Any]:
        m = self._read_json(manifest_path)
        report = self._read_json(run_dir / "report.json")
        return {
            "run_id": run_dir.name,
            "dir": str(run_dir),
            "final_coverage": m.get("final_coverage", 0),
            "target": m.get("target", 95),
            "converged": m.get("converged", False),
            "iterations": m.get("iterations", 0),
            "verdict": report.get("verdict", ""),
            "signoff_status": report.get("signoff_status", ""),
            "phases": m.get("phases", []),
            "evidence_valid": m.get("evidence", {}).get("chain_valid", False),
        }

    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        """读单 run 完整数据（manifest + report + coverage）。"""
        run_dir = self._resolve(run_id)
        if not run_dir:
            return None
        summary = self._summary(run_dir, run_dir / "docs" / "manifest.json")
        coverage = self._read_json(run_dir / "sim" / "coverage" / "coverage_result.json")
        coverage_detail = coverage.get("coverage", {}) if isinstance(coverage, dict) else {}
        summary["coverage_detail"] = coverage_detail
        summary["rtl_hashes"] = self._read_json(run_dir / "docs" / "manifest.json").get("rtl_hashes", {})
        return summary

    def compare(self, run_a: str, run_b: str) -> Dict[str, Any]:
        """对比两次 run 的覆盖率。"""
        a = self.get_run(run_a)
        b = self.get_run(run_b)
        if not a or not b:
            return {"error": f"run not found: {run_a if not a else run_b}"}
        ca, cb = a.get("final_coverage", 0), b.get("final_coverage", 0)
        return {
            "run_a": {"run_id": run_a, "coverage": ca},
            "run_b": {"run_id": run_b, "coverage": cb},
            "delta": round(cb - ca, 2),
            "trend": "up" if cb > ca else ("down" if cb < ca else "flat"),
        }

    def logs(self, run_id: str, stage: str = "") -> List[Dict[str, Any]]:
        """找 run 目录下的日志文件（sim.log / compile log / 任意 .log）。"""
        run_dir = self._resolve(run_id)
        if not run_dir:
            return []
        logs = []
        for f in sorted(run_dir.rglob("*.log")):
            if stage and stage.lower() not in f.name.lower():
                continue
            logs.append({"path": str(f), "size_kb": round(f.stat().st_size / 1024, 1),
                         "name": f.name})
        return logs

    def trend(self, metric: str = "coverage", limit: int = 30) -> List[Dict[str, Any]]:
        """最近 N 次 run 的指标趋势（供趋势图）。"""
        runs = self.list_runs(limit)
        # 按时间正序（旧→新）
        runs = list(reversed(runs))
        out = []
        for r in runs:
            out.append({
                "run_id": r["run_id"],
                "coverage": r["final_coverage"],
                "verdict": r["verdict"],
                "converged": r["converged"],
            })
        return out

    def failures(self, run_id: str) -> List[Dict[str, Any]]:
        """列出某 run 的失败阶段。"""
        run = self.get_run(run_id)
        if not run:
            return []
        failed = [p for p in run.get("phases", [])
                  if p.get("status") in ("failed", "error")]
        return failed

    # ═══════════════════════════════════════════════════════════
    # 辅助
    # ═══════════════════════════════════════════════════════════

    def _resolve(self, run_id: str) -> Optional[Path]:
        """解析 run_id → 目录（支持完整目录名或前缀匹配）。"""
        d = self.output_base / run_id
        if d.is_dir():
            return d
        # 前缀匹配
        if self.output_base.exists():
            for candidate in self.output_base.iterdir():
                if candidate.is_dir() and candidate.name.startswith(run_id):
                    return candidate
        return None

    @staticmethod
    def _read_json(path: Path) -> Dict[str, Any]:
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
