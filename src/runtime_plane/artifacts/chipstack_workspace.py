"""ChipStack 风格的产物工作区投影（Runtime Plane）。

只组织已经产生的 IR、RTL、checker、日志和证据，不代替形式验证、PPA、lint
或调试 Agent 的工作。任何未执行的能力写 NOT_RUN，绝不向工具目录塞假结果。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.runtime_plane.core.provenance.graph import ProvenanceGraph

_RESERVED_UNUSED = {
    "formal_agent": "未调用形式验证工具（例如 JasperGold），不提供 formal proof",
    "rtl_early_estimation_agent": "未执行面积/功耗/性能估算，不生成 PPA 数值",
    "lint_autofix": "未运行代码 lint/自动修复，不宣称 RTL 已清理",
    "compile_n_fix": "未运行编译修复 Agent；编译问题请查 simulation_agent 的实际日志",
}


def _safe_name(value: str) -> str:
    value = str(value or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", value) or value in (".", ".."):
        raise ValueError(f"设计名不能作为安全目录名：{value!r}")
    return value


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="strict"))
    except (OSError, ValueError):
        return default


def _sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _status(path: Path, status: str, reason: str, **extra: Any) -> None:
    payload = {"status": status, "reason": reason, **extra}
    if status in ("NOT_RUN", "NOT_GENERATED", "NOT_COPIED"):
        payload.setdefault("performed", False)
    _write_json(path, payload)


def _copy_tree(source: Path, target: Path) -> None:
    if source.is_dir():
        shutil.copytree(source, target, dirs_exist_ok=True)


@dataclass(frozen=True)
class PublishedWorkspace:
    design_name: str
    run_id: str
    project_root: Path
    archive_manifest: Path

    def to_dict(self, workspace_root: Path) -> dict[str, Any]:
        return {
            "schema": "chipstack_workspace_v1",
            "design_name": self.design_name,
            "run_id": self.run_id,
            "project_root": str(self.project_root),
            "workspace_root": str(workspace_root),
            "archive_manifest": str(self.archive_manifest),
        }


class ChipStackWorkspace:
    """一个专用工作区；不是对既有 Cadence 数据库的迁移或接管。"""

    def __init__(self, root: str | Path, design_name: str, run_id: str, archive: str | Path) -> None:
        self.root = Path(root).resolve()
        self.design_name = _safe_name(design_name)
        self.run_id = run_id
        self.project = (self.root / self.design_name).resolve()
        self.archive = Path(archive).resolve()
        for path in (self.project, self.archive):
            path.relative_to(self.root)

    def publish(self, result: dict[str, Any], *, seed: int) -> dict[str, Any]:
        manifest = self.archive / "manifest.json"
        existing = _read_json(manifest, None)
        if manifest.is_file() and existing is None:
            raise ValueError("manifest.json 不可读或格式不正确，拒绝覆盖已有证据")
        if isinstance(existing, dict):
            result = {**existing, **result}
        result["evidence_manifest"] = str(manifest)
        result.setdefault("artifacts", [])
        result.setdefault("rtl_simulation_completed", False)
        self.project.mkdir(parents=True, exist_ok=True)
        self._publish_mental_model(result)
        self._publish_rtl()
        self._publish_uvm(result)
        self._publish_simulation(result, seed)
        self._publish_coverage(result)
        self._publish_unused_agents()
        self._publish_logs(result, seed)
        publication = PublishedWorkspace(self.design_name, self.run_id, self.project, manifest)
        result["workspace"] = publication.to_dict(self.root)
        _write_json(manifest, result)
        # 项目入口的文件与 Archive 同步，后续历史仍由 Archive 保留。
        self._index_sqlite(result, seed)
        self._write_run_manifest(result, seed)
        _write_json(self.project / "run_manifest.json", result)
        return result

    def _publish_mental_model(self, result: dict[str, Any]) -> None:
        root = self.project / "mental_model_agent"
        root.mkdir(parents=True, exist_ok=True)
        for source_name, target_name in (
            ("interface_timing.json", "temporal_ir.json"),
            ("binding_report.json", "binding_report.json"),
            ("specification_readiness.json", "specification_readiness.json"),
        ):
            source = self.archive / "contract" / source_name
            if source.is_file():
                shutil.copy2(source, root / target_name)
        ir = result.get("interface_ir")
        if ir:
            text = self._human_model(ir, result.get("binding_report"), result.get("specification_readiness"))
            (root / "mental_model.md").write_text(text, encoding="utf-8")
        else:
            _status(root / "status.json", "INCOMPLETE", "输入未形成可共享的 Temporal IR")
        _write_json(root / "traceability.json", result.get("traceability") or [])
        graph = ProvenanceGraph(self.run_id)
        seen: set[str] = set()
        for row in result.get("traceability") or []:
            source, target = str(row["from"]), str(row["to"])
            for node in (source, target):
                if node not in seen:
                    graph.add_node(node, "artifact", label=node)
                    seen.add(node)
            confidence = "exact" if row.get("runtime_kind", "rtl_simulation") == "rtl_simulation" else "weak"
            graph.add_edge(source, target, "derived_from", evidence=row.get("relation", ""), confidence=confidence)
        (root / "provenance.jsonl").write_text(graph.to_jsonl(), encoding="utf-8")
        _write_json(root / "provenance_summary.json", graph.summary())

    @staticmethod
    def _human_model(ir: dict[str, Any], binding: dict[str, Any] | None, specification: dict[str, Any] | None) -> str:
        lines = [
            f"# {ir['interface_id']} — bounded mental model",
            "",
            "这是从确认的结构化语义生成的共享理解，不是 LLM 已理解全部设计的声明。",
            f"Binding: `{(binding or {}).get('status', 'UNKNOWN')}`",
            f"Specification: `{(specification or {}).get('status', 'UNKNOWN')}`",
            "",
            f"- Protocol: `{ir.get('protocol')}`",
            f"- Interface group: `{ir.get('interface_group')}`",
            f"- Status: `{ir.get('status')}`",
            f"- Input mode: `{(ir.get('metadata') or {}).get('input_mode', 'unknown')}`",
            f"- Clock: `{ir.get('clock', {}).get('name')}`, period_ps=`{ir.get('clock', {}).get('period_ps')}`",
            "",
            "## Signal bindings",
        ]
        for signal in ir.get("signals") or []:
            lines.append(
                f"- `{signal['role']}` → `{signal['name']}` (width={signal['width']}, {signal['binding_status']})"
            )
        lines.extend(["", "## Rules and provenance"])
        for rule in ir.get("rules") or []:
            anchor = rule.get("anchor") or {}
            lines.extend(
                [
                    f"- `{rule['rule_id']}`: {rule['kind']}",
                    f"  - valid=`{rule['valid']}`, ready=`{rule['ready']}`",
                    f"  - stable_signals={rule['stable_signals']}",
                    f"  - source=`{anchor.get('locator')}`:{anchor.get('line_start')}-{anchor.get('line_end')}",
                    f"  - quote: {anchor.get('quote')}",
                ]
            )
        lines.extend(
            [
                "",
                "## Explicit unknowns",
                *(f"- {item}" for item in ir.get("unknowns") or []),
                "",
                "超出这个接口与规则子集的内容没有被推断为已证明。",
            ]
        )
        return "\n".join(lines) + "\n"

    def _publish_rtl(self) -> None:
        root = self.project / "rtl_generation"
        if (self.archive / "rtl").is_dir():
            _copy_tree(self.archive / "rtl", root / "reference_inputs")
            _status(
                root / "status.json", "REFERENCE_COPY", "这是源 RTL 快照；本轮没有 AI 生成或修改 DUT，也没有 ECO 提交。"
            )
        else:
            _status(root / "status.json", "NOT_COPIED", "解析/准备阶段未形成可用的源 RTL 快照")

    def _publish_uvm(self, result: dict[str, Any]) -> None:
        root = self.project / "uvm_agent"
        monitor = result.get("monitor")
        if monitor:
            source = Path(monitor["path"])
            target = root / "monitors" / source.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            _write_json(root / "monitor_manifest.json", monitor)
        else:
            _status(root / "status.json", "NOT_GENERATED", "绑定检查未通过，没有生成 monitor")
        for name in ("positive", "negative_control"):
            bench = self.archive / "runs" / name / "tb_stream.sv"
            if bench.is_file():
                (root / "testbench").mkdir(parents=True, exist_ok=True)
                shutil.copy2(bench, root / "testbench" / f"{name}_tb.sv")

    def _publish_simulation(self, result: dict[str, Any], seed: int) -> None:
        root = self.project / "simulation_agent"
        for scenario in result.get("scenarios") or []:
            name = scenario["scenario"]
            _copy_tree(self.archive / "runs" / name, root / name)
            _write_json(
                root / name / "execution_manifest.json",
                {
                    "expected_status": scenario.get("expected_status"),
                    "actual_status": scenario.get("actual_status"),
                    "expectation_met": scenario.get("expectation_met"),
                    "simulation_kind": scenario.get("runtime", {}).get("simulation_kind"),
                    "seed": seed,
                    "rtl": scenario.get("rtl"),
                },
            )

    def _publish_coverage(self, result: dict[str, Any]) -> None:
        actual_rtl = result.get("simulation_kind") == "rtl_simulation"
        rows = []
        for row in result.get("scenarios") or []:
            runtime = row["runtime"]
            rows.append(
                {
                    "scenario": row["scenario"],
                    "actual_status": row["actual_status"],
                    "expected_status": row["expected_status"],
                    "counts": runtime.get("counts") if actual_rtl else None,
                }
            )
        _write_json(
            self.project / "functional_coverage_agent/coverage.json",
            {
                "schema": "interface_scenario_coverage_v1",
                "rows": rows,
                "scope": "仅当前 VALID/READY/DATA 场景，不是完整功能覆盖率或 100% 闭合",
            },
        )
        open_obligations = [
            {
                "scenario": row["scenario"],
                "expected": row["expected_status"],
                "actual": row["actual_status"],
                "simulation_kind": row["runtime"].get("simulation_kind"),
            }
            for row in result.get("scenarios") or []
            if not row.get("expectation_met")
        ]
        for name in result.get("interface_ir", {}).get("unknowns") or []:
            open_obligations.append({"unknown": name, "actual": "INCOMPLETE"})
        closure = "BOUNDED_EXPECTATIONS_MET" if result.get("overall_status") == "PASS" and actual_rtl else "INCOMPLETE"
        _status(
            self.project / "coverage_closure_agent/status.json",
            closure,
            "只评价已声明场景；不是所有协议覆盖率闭合，也不是签核"
            if not open_obligations
            else "存在未证明场景，先运行/修复运行时证据",
            open_obligations=open_obligations,
        )

    def _publish_unused_agents(self) -> None:
        for name, reason in _RESERVED_UNUSED.items():
            _status(self.project / name / "status.json", "NOT_RUN", reason)

    def _publish_logs(self, result: dict[str, Any], seed: int) -> None:
        debug = {
            "binding_issues": result.get("binding_report", {}).get("issues") or [],
            "runtime_findings": [
                {
                    "scenario": row["scenario"],
                    "expected": row["expected_status"],
                    "actual": row["actual_status"],
                    "expected_negative_control": row["scenario"] == "negative_control",
                    "reason": row["runtime"].get("reason"),
                }
                for row in result.get("scenarios") or []
            ],
            "no_llm_root_cause_claim": True,
        }
        _write_json(self.project / "dv_debug/findings.json", debug)
        ordinary = [
            {
                "stage": result.get("stage", "completed"),
                "status": result.get("overall_status"),
                "simulation_kind": result.get("simulation_kind"),
            }
        ]
        lines = (json.dumps(row, ensure_ascii=False, sort_keys=True) for row in ordinary)
        logs = self.root / ".symphony_logs"
        logs.mkdir(parents=True, exist_ok=True)
        with (logs / f"{self.run_id}.jsonl").open("w", encoding="utf-8") as fh:
            for line in lines:
                fh.write(line + "\n")
        _write_json(
            self.root / ".cli_logs" / f"{self.run_id}.json",
            {
                "command": "interface-timing run-slice",
                "design_name": self.design_name,
                "seed": seed,
                "simulation_kind": result.get("simulation_kind"),
                "simulation_executed": result.get("simulation_kind") == "rtl_simulation",
                "archive": str(self.archive.relative_to(self.root)),
                "captured": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            },
        )
        # structured authoring 不是聊天对话；没有对话内容就不伪造 TUI 聊天历史。
        _write_json(
            self.root / "tui/sessions" / f"{self.run_id}.json",
            {
                "mode": result.get("input_mode", "unknown"),
                "llm_used": False,
                "reason": "本轮为结构化语义输入，没有 LLM 会话",
                "records": [],
            },
        )

    def _index_sqlite(self, result: dict[str, Any], seed: int) -> None:
        database = self.root / "artifacts.sqlite"
        manifest = self.archive / "manifest.json"
        rows = result.get("artifacts") or []
        binding_status = result.get("binding_report", {}).get("status", "UNKNOWN")
        with closing(sqlite3.connect(database)) as connection, connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    design_name TEXT NOT NULL,
                    seed INTEGER NOT NULL,
                    overall_status TEXT NOT NULL,
                    specification_status TEXT NOT NULL,
                    binding_status TEXT NOT NULL,
                    simulation_kind TEXT NOT NULL,
                    manifest_path TEXT NOT NULL,
                    manifest_sha256 TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    UNIQUE(run_id, design_name)
                );
                CREATE TABLE IF NOT EXISTS artifact_files (
                    run_id TEXT NOT NULL, design_name TEXT NOT NULL,
                    artifact_path TEXT NOT NULL, sha256 TEXT NOT NULL,
                    byte_count INTEGER, FOREIGN KEY(run_id, design_name)
                        REFERENCES runs(run_id, design_name), UNIQUE(run_id, artifact_path)
                );
                CREATE INDEX IF NOT EXISTS runs_by_design ON runs(design_name, id DESC);
            """)
            recorded_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
            connection.execute(
                "INSERT INTO runs(run_id, design_name, seed, overall_status, "
                "specification_status, binding_status, simulation_kind, manifest_path, "
                "manifest_sha256, recorded_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    self.run_id,
                    self.design_name,
                    seed,
                    result.get("overall_status"),
                    result.get("specification_readiness", {}).get("status", "UNKNOWN"),
                    binding_status,
                    result.get("simulation_kind", "not_started"),
                    str(manifest.relative_to(self.root)),
                    _sha256(manifest),
                    recorded_at,
                ),
            )
            for row in rows:
                artifact = self.archive / row["path"]
                if artifact.is_file():
                    connection.execute(
                        "INSERT INTO artifact_files(run_id, design_name, artifact_path, "
                        "sha256, byte_count) VALUES (?, ?, ?, ?, ?)",
                        (
                            self.run_id,
                            self.design_name,
                            str(artifact.relative_to(self.root)),
                            _sha256(artifact),
                            artifact.stat().st_size,
                        ),
                    )

    def _write_run_manifest(self, result: dict[str, Any], seed: int) -> None:
        path = self.root / "run_manifest.json"
        prior = _read_json(path, {"designs": {}})
        designs = dict(prior.get("designs") or {})
        designs[self.design_name] = {
            "latest_run_id": self.run_id,
            "manifest": str((self.archive / "manifest.json").relative_to(self.root)),
            "overall_status": result.get("overall_status"),
            "simulation_kind": result.get("simulation_kind"),
            "project_directory": self.design_name,
        }
        _write_json(
            path,
            {
                "schema": "chipstack_workspace_v1",
                "layout_scope": "运行产物组织；非 Cadence 服务集成",
                "latest_design": self.design_name,
                "latest_run_id": self.run_id,
                "seed": seed,
                "designs": designs,
                "database": "artifacts.sqlite",
                "database_role": "only workspace artifact index; no legacy lineage DB replacement",
            },
        )


def read_workspace_runs(root: str | Path, design_name: str | None = None) -> list[dict[str, Any]]:
    path = Path(root) / "artifacts.sqlite"
    if not path.is_file():
        return []
    with closing(sqlite3.connect(path)) as connection:
        connection.row_factory = sqlite3.Row
        sql = "SELECT * FROM runs"
        parameters: tuple[Any, ...] = ()
        if design_name:
            sql += " WHERE design_name = ?"
            parameters = (design_name,)
        sql += " ORDER BY id"
        rows = connection.execute(sql, parameters).fetchall()
        return [dict(row) for row in rows]


__all__ = ["ChipStackWorkspace", "PublishedWorkspace", "read_workspace_runs"]
