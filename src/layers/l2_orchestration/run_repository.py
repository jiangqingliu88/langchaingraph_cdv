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


#: 终局事件 → 运行状态。**没有映射到的都算"还在跑"** —— 日志的最后一条是
#: 阶段事件（stage.finished 之类）时就该是这个答案。
_STATE_BY_KIND = {
    "run.finished": "completed",
    "run.failed": "failed",
    "run.cancelled": "cancelled",
    # 停在检查点上等人：这次 astream 结束了，但运行没结束
    "run.interrupted": "waiting",
}


class RunRepository:
    """从 output 目录扫描 run 数据。"""

    def __init__(self, output_base: str = "output"):
        self.output_base = Path(output_base)

    # ═══════════════════════════════════════════════════════════
    # 扫描
    # ═══════════════════════════════════════════════════════════

    def run_dirs(self) -> List[Path]:
        """所有可能的 run 目录，新的在前。

        **两种布局都要认**，因为仓库里两种都在用：

            output/<运行名>/             —— 本模块文档与 `-o output` 的意图
            output_<用户>_<时间戳>/       —— `make_output_root()` 实际产出的形状

        `make_output_root("output")` 给的是**前缀式**名字（`output_用户_时间戳`），
        落在 CWD 下当兄弟目录，不是 `output/` 的子目录。此前本模块只扫
        `output/*/`，于是 `vagent runs` 对真实产物恒为空 —— 不是没接线，
        是两边对"output 是父目录还是前缀"这个问题的答案不一致。

        与其改掉落盘约定（会让已有的输出目录全部失联），不如让读取侧两种都认。
        """
        found: List[Path] = []
        base = self.output_base
        if base.is_dir():
            found.extend(p for p in base.iterdir()
                         if p.is_dir() and not p.name.startswith("."))
        # 前缀式兄弟目录：output_<...> 与 output 同位于父目录下
        parent = base.parent if str(base.parent) else Path(".")
        try:
            found.extend(p for p in parent.glob(f"{base.name}_*")
                         if p.is_dir() and not p.name.startswith("."))
        except OSError:
            pass
        return sorted(set(found), key=lambda p: p.name, reverse=True)

    def list_runs(self, limit: int = 50) -> List[Dict[str, Any]]:
        """扫描所有 run 目录，返回摘要列表（按目录名倒序，即新 run 在前）。"""
        runs = []
        for d in self.run_dirs():
            manifest = d / "docs" / "manifest.json"
            if manifest.exists():
                runs.append(self._summary(d, manifest))
            else:
                ip = self._ip_summary(d)
                soc = ip or self._soc_summary(d)
                if soc:
                    runs.append({"run_id": d.name, "dir": str(d),
                                 "artifacts": True, "finished": True, **soc})
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
        manifest = run_dir / "docs" / "manifest.json"
        if manifest.exists():
            summary = self._summary(run_dir, manifest)
        else:
            summary = {"run_id": run_dir.name, "dir": str(run_dir)}
            summary.update(self._ip_summary(run_dir)
                           or self._soc_summary(run_dir))
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
    # 运行日志（见 run_journal 模块头）
    # ═══════════════════════════════════════════════════════════

    def journal(self, run_id: str, after_seq: int = 0) -> List[Dict[str, Any]]:
        """读某 run 的过程日志 —— **历史运行与实时运行走同一条读取路径**。

        这是本仓库"界面不该为跑着的 run 和跑完的 run 写两套渲染"那条设计的落点：
        数据都在 `docs/run_events.jsonl`，界面只是读它。

        返回 dict 而不是 RunEvent：本层的调用方（CLI / 界面 / bridge）是 JSON 世界，
        在这一层就转好，免得每个调用方各自 `to_dict()`。
        """
        run_dir = self._resolve(run_id)
        if not run_dir:
            return []
        from src.layers.l2_orchestration.run_journal import read_journal
        return [e.to_dict() for e in read_journal(run_dir, after_seq=after_seq)]

    def journal_summary(self, run_id: str) -> Dict[str, Any]:
        """日志的**概览** —— 界面上的运行列表用它显示"到哪一步了"。

        与 `_summary` 的区别：那个读最终产物（要跑完才有），这个读过程日志
        （跑着就有）。两者合起来才既能列"跑完的"又能列"正在跑的"。
        """
        events = self.journal(run_id)
        if not events:
            return {}
        stages = [e for e in events if e.get("stage")]
        finished = [e for e in events if e.get("kind") == "stage.finished"]
        failed = [e for e in events if e.get("kind") == "stage.failed"]
        last = events[-1]
        # 注意这里要的是"这次 astream 结束了没有"（含暂停），不是"运行结束没有"：
        # 暂停的运行不需要继续轮询，但它的状态是 waiting 而不是 completed。
        idle = last.get("kind") in ("run.finished", "run.failed", "run.cancelled",
                                    "run.interrupted")
        return {
            "run_id": last.get("run_id") or run_id,
            "event_count": len(events),
            "stage_count": len(finished),
            "failed_count": len(failed),
            "current_stage": last.get("stage", ""),
            "current_title": last.get("title", ""),
            "round": last.get("round", 0),
            # 五种收束方式，别混：跑完 / 失败 / 取消 / **等人** / 还在跑。
            # "等人"单独一档是必须的 —— 界面靠它决定显示审批条还是终态，
            # 归进 running 的话，一次暂停的运行看起来就像卡住了。
            "state": _STATE_BY_KIND.get(last.get("kind"), "running"),
            "started_at": events[0].get("ts", ""),
            "updated_at": last.get("ts", ""),
            "stages": [{"stage": e.get("stage", ""), "title": e.get("title", ""),
                        "round": e.get("round", 0), "status": e.get("status", ""),
                        "duration_s": e.get("duration_s", 0.0)}
                       for e in finished + failed],
            "last": last,
        }

    def discover_runs(self, limit: int = 50) -> List[Dict[str, Any]]:
        """**含未完成**的运行列表。

        `list_runs` 只认 `docs/manifest.json` —— 那是跑完才写的，所以正在跑的、
        或者跑挂了的 run 根本不出现在列表里。界面需要一个"现在有什么在跑"的视图，
        判据换成 `docs/run_events.jsonl` 存在。
        """
        out: List[Dict[str, Any]] = []
        for d in self.run_dirs():
            has_manifest = (d / "docs" / "manifest.json").exists()
            has_journal = (d / "docs" / "run_events.jsonl").exists()
            has_soc = (d / "soc" / "soc_run.json").exists()
            has_ip = (d / "ip" / "ip_run.json").exists()
            if not (has_manifest or has_journal or has_soc or has_ip):
                continue
            entry: Dict[str, Any] = {"run_id": d.name, "dir": str(d),
                                     "artifacts": has_manifest or has_soc or has_ip}
            if has_manifest:
                entry.update(self._summary(d, d / "docs" / "manifest.json"))
            entry.update(self.journal_summary(d.name))
            if has_soc:
                # 核心事件不是 RunJournal 格式；用 soc_run 的状态覆盖摘要。
                entry.update(self._soc_summary(d))
            if has_ip:
                entry.update(self._ip_summary(d))
            # `finished` 与 `artifacts` 是两件事：前者是"运行结束了"（日志里有终态事件），
            # 后者是"产物齐了"。跑挂的 run 有日志没产物；早期没有日志的 run 则相反 ——
            # 所以取两者的并，谁都不能单独回答"这个东西还活着吗"。
            entry["finished"] = bool(
                entry.get("state") in ("completed", "failed", "cancelled")
                or has_manifest or has_soc or has_ip)
            entry["run_id"] = d.name
            out.append(entry)
            if len(out) >= limit:
                break
        return out

    def _ip_summary(self, run_dir: Path) -> Dict[str, Any]:
        """IP 级 run（`ip/ip_run.json`）。"""
        doc = self._read_json(run_dir / "ip" / "ip_run.json")
        if not doc:
            return {}
        result = doc.get("result") or {}
        status = str(result.get("status") or "")
        passes = status.upper() == "PASS"
        return {
            "kind": "ip",
            "ip_id": doc.get("ip_id", ""),
            "state": "completed" if passes else "failed",
            "verdict": status,
            "signoff_status": status,
            "final_coverage": 0,
            "target": 0,
            "converged": passes,
            "iterations": 1,
            "evidence_valid": bool((doc.get("ip_evidence") or {}).get("path")),
            "ip_evidence": doc.get("ip_evidence") or {},
            "soc": doc.get("soc_summary") or {},
            "stages": [{"stage": "ip", "title": f"IP {doc.get('ip_id', '')}",
                        "status": "passed" if passes else "failed", "round": 1}],
        }

    def _soc_summary(self, run_dir: Path) -> Dict[str, Any]:
        """SoC 参考工程的 run 摘要（`soc/soc_run.json`，没有 manifest 也认）。"""
        doc = self._read_json(run_dir / "soc" / "soc_run.json")
        if not doc:
            return {}
        reg = doc.get("regression") or {}
        passes = str(reg.get("status") or "").upper() == "PASS"
        evidence = run_dir / "signoff_evidence" / "manifest.json"
        return {
            "kind": "soc",
            "state": "completed" if passes else "failed",
            "final_coverage": 0,
            "target": 0,
            "converged": passes,
            "iterations": 1,
            "verdict": reg.get("status") or "",
            "signoff_status": reg.get("status") or "",
            "evidence_valid": evidence.is_file(),
            "project": (doc.get("project") or {}).get("name", ""),
            "rtl_hash": (doc.get("project") or {}).get("rtl_hash", ""),
            "soc": doc,
            "stages": [{"stage": "soc", "title": "SoC 回归",
                        "status": "passed" if passes else "failed",
                        "round": 1}],
        }

    # ═══════════════════════════════════════════════════════════
    # 辅助
    # ═══════════════════════════════════════════════════════════

    def run_dir(self, run_id: str) -> Optional[Path]:
        """`_resolve` 的公开版 —— 别处要拿"这次运行的目录"时用这个。"""
        return self._resolve(run_id)

    def _resolve(self, run_id: str) -> Optional[Path]:
        """解析 run_id → 目录（支持完整目录名或前缀匹配）。"""
        d = self.output_base / run_id
        if d.is_dir():
            return d
        for candidate in self.run_dirs():
            if candidate.name.startswith(run_id):
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
