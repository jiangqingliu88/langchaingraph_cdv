"""单接口时序闭环编排：Source → IR → Binding → Monitor → RTL Evidence。

这不是全局协议签核；每个场景都有明确的期望运行结果，负例必须真的被监控器发现。
真实运行时只能通过 Runtime 的外部仿真后端，不能用主编排器直接臆造结果。
"""

from __future__ import annotations

import json
import shutil
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from src.engine_plane.interface_timing import check_temporal_ir
from src.generation_plane.interface_timing import write_monitor
from src.mental_ir_plane.interface_timing import (
    TimingContractError,
    source_hash,
    temporal_from_dict,
    to_specification_document,
)
from src.orchestration_plane.specification_workflow import SpecificationWorkflow
from src.runtime_plane.artifacts.chipstack_workspace import ChipStackWorkspace, _safe_name
from src.runtime_plane.tools.execution.interface_timing import SimulationResult, simulate
from src.runtime_plane.tools.specification_extraction import extract_rtl_facts


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _file_evidence(path: Path, out_root: Path) -> dict[str, Any]:
    try:
        root_relative = path.relative_to(out_root).as_posix()
    except ValueError:
        root_relative = str(path)
    return {"path": root_relative, "sha256": source_hash(path), "bytes": path.stat().st_size}


class TemporalSlicePipeline:
    def __init__(
        self,
        fixture_root: str | Path,
        out_root: str | Path,
        *,
        simulate_backend: Callable[..., SimulationResult] | None = None,
        layout: str = "chipstack",
        top_design_name: str | None = None,
    ) -> None:
        self.root = Path(fixture_root).resolve()
        self.workspace_root = Path(out_root).resolve()
        if layout not in ("chipstack", "legacy"):
            raise ValueError("layout 必须是 chipstack 或 legacy")
        self.layout = layout
        self.top_design_name = top_design_name or self.root.name
        if self.layout == "chipstack":
            _safe_name(self.top_design_name)
        self.simulate_backend = simulate_backend or simulate
        self.run_id = f"run-{time.time_ns()}"
        self.out = self._new_output_root()

    def _new_output_root(self) -> Path:
        base = (
            self.workspace_root / "Archive" / self.run_id
            if self.layout == "chipstack"
            else self.workspace_root / self.run_id
        )
        return base

    def run(self, *, seed: int = 4242) -> dict[str, Any]:
        if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
            raise ValueError("seed 必须为非负整数")
        # 同一编排器重复运行也保留独立历史，不覆盖上一次 raw artifacts。
        self.run_id = f"run-{time.time_ns()}"
        self.out = self._new_output_root()
        result = self._execute(seed=seed)
        # 解析失败也保持一致的输出形状，不能因此丢失未完成状态。
        result.setdefault("scenarios", [])
        if self.layout == "legacy":
            return result
        workspace = ChipStackWorkspace(self.workspace_root, self.top_design_name, self.run_id, self.out)
        return workspace.publish(result, seed=seed)

    def _execute(self, *, seed: int = 4242) -> dict[str, Any]:
        try:
            ir = temporal_from_dict(self._load_intent())
        except (OSError, UnicodeError, ValueError, TimingContractError) as exc:
            return {
                "schema": "interface_slice_evidence_v1",
                "overall_status": "INCOMPLETE",
                "stage": "parse",
                "reason": str(exc),
                "simulation_kind": "not_started",
            }
        base = self._prepare(ir)
        binding_file = self.root / "rtl/pass_master.sv"
        ports = extract_rtl_facts(binding_file).get("ports") or []
        report = check_temporal_ir(ir, ports, self.root)
        (self.out / "contract").mkdir(parents=True, exist_ok=True)
        _write_json(self.out / "contract/interface_timing.json", ir.to_dict())
        _write_json(self.out / "contract/binding_report.json", report.to_dict())
        if report.status != "VALIDATED":
            base["binding_report"] = report.to_dict()
            base["overall_status"] = "CONFLICT" if report.status == "CONFLICT" else "INCOMPLETE"
            base["stage"] = "binding_validation"
            base["scenarios"] = []
            base["simulation_kind"] = "not_started"
            base["reason"] = "来源、RTL 绑定或规则确认未通过，禁止生成 monitor"
            base["evidence_manifest"] = str(self._write_manifest(base))
            return base
        try:
            specification = SpecificationWorkflow().run(to_specification_document(ir, report))
        except (TimingContractError, ValueError) as exc:
            base["binding_report"] = report.to_dict()
            base["overall_status"] = "INCOMPLETE"
            base["stage"] = "specification_compilation"
            base["reason"] = str(exc)
            base["evidence_manifest"] = str(self._write_manifest(base))
            return base
        base["specification_readiness"] = specification.to_dict()
        _write_json(self.out / "contract/specification_readiness.json", specification.to_dict())
        if specification.status != "VALIDATED" or not specification.execution_allowed:
            base["overall_status"] = "CONFLICT" if specification.status == "CONFLICT" else "INCOMPLETE"
            base["stage"] = "specification_compilation"
            base["reason"] = "同一 Temporal IR 在原 Specification 主链未就绪，禁止生成 monitor"
            base["evidence_manifest"] = str(self._write_manifest(base))
            return base
        try:
            monitor = write_monitor(ir, self.out / "monitors")
        except ValueError as exc:
            return {
                "overall_status": "INCOMPLETE",
                "stage": "monitor_generation",
                "reason": str(exc),
                "binding_report": report.to_dict(),
            }
        base["binding_report"] = report.to_dict()
        base["monitor"] = monitor.to_dict()
        base["scenarios"] = [
            self._scenario(ir, monitor, seed, name, rtl, expected)
            for name, rtl, expected in (
                ("positive", "pass_master.sv", "PASS"),
                ("negative_control", "fail_master.sv", "FAIL"),
            )
        ]
        statuses = [row["actual_status"] for row in base["scenarios"]]
        matched = [row["expectation_met"] for row in base["scenarios"]]
        base["overall_status"] = self._overall_status(base["scenarios"], matched)
        base["expectation_met"] = all(matched)
        base["consequence"] = (
            "这组有限场景满足预期；并不证明所有 AXI 时序或 AI 自动理解均正确。"
            if base["overall_status"] == "PASS"
            else "存在未满足的场景、缺失执行或明确违规，不能宣称接口验证通过"
        )
        base["antivacuity"] = {
            "positive_must_observe": {"blocked_samples_gt": 0, "handshakes_gt": 0},
            "negative_control_must_report": "payload_change_during_backpressure",
            "negative_fail_is_expected": True,
        }
        base["simulation_kind"] = base["scenarios"][0]["runtime"].get("simulation_kind")
        evidence_path = self._write_manifest(base)
        base["evidence_manifest"] = str(evidence_path)
        base["statuses"] = statuses
        return base

    def _load_intent(self) -> dict[str, Any]:
        import yaml

        path = self.root / "intents/structured.yaml"
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8", errors="strict"))
        except yaml.YAMLError as exc:
            raise TimingContractError(f"intent YAML 非法：{exc}") from exc
        if not isinstance(doc, dict):
            raise TimingContractError("结构化 intent 根节点必须是对象")
        return doc

    def _prepare(self, ir: Any) -> dict[str, Any]:
        shutil.copytree(self.root / "source", self.out / "source", dirs_exist_ok=True)
        shutil.copytree(self.root / "rtl", self.out / "rtl", dirs_exist_ok=True)
        return {
            "schema": "interface_slice_evidence_v1",
            "interface_ir": ir.to_dict(),
            "interface_ir_hash": ir.content_hash(),
            "input_mode": ir.metadata.get("input_mode", "unknown"),
            "source_snapshot_hash": source_hash(self.root / "source/spec.md"),
        }

    def _scenario(self, ir: Any, monitor: Any, seed: int, name: str, rtl: str, expected: str) -> dict[str, Any]:
        category = self.out / "runs" / name
        result = self.simulate_backend(ir, monitor, self.root / "rtl" / rtl, category, seed=seed)
        payload = result.to_dict()
        _write_json(category / "runtime.json", payload)
        return {
            "scenario": name,
            "rtl": rtl,
            "expected_status": expected,
            "actual_status": result.status,
            "expectation_met": result.status == expected,
            "runtime": payload,
        }

    @staticmethod
    def _overall_status(scenarios: list[dict[str, Any]], matched: list[bool]) -> str:
        if not matched:
            return "INCOMPLETE"
        if all(matched):
            return "PASS"
        if any(row["actual_status"] == "INCOMPLETE" for row in scenarios):
            return "INCOMPLETE"
        return "FAIL"

    def _write_manifest(self, base: dict[str, Any]) -> Path:
        traces = [{"from": "source/spec.md", "to": base["interface_ir_hash"], "relation": "grounds"}]
        if "monitor" in base:
            traces.append(
                {"from": base["interface_ir_hash"], "to": base["monitor"]["path"], "relation": "compiles_into"}
            )
        if "specification_readiness" in base:
            traces.append(
                {
                    "from": base["interface_ir_hash"],
                    "to": base["specification_readiness"]["spec_hash"],
                    "relation": "joins_specification_contract",
                }
            )
        for row in base.get("scenarios", []):
            runtime = row["runtime"]
            traces.append(
                {
                    "from": base["monitor"]["rule_id"],
                    "to": f"runs/{row['scenario']}/runtime.json",
                    "relation": "observed_by",
                    "expected": row["expected_status"],
                    "actual": row["actual_status"],
                    "runtime_kind": runtime.get("simulation_kind"),
                }
            )
            traces.extend(
                {"from": f"runs/{row['scenario']}/runtime.json", "to": rel, "relation": "backs"}
                for rel in runtime.get("logs") or []
            )
            if runtime.get("waveform"):
                traces.append(
                    {"from": f"runs/{row['scenario']}/runtime.json", "to": runtime["waveform"], "relation": "waves"}
                )
        files = []
        for file in sorted(self.out.rglob("*")):
            if file.is_file() and file.name != "manifest.json":
                files.append(_file_evidence(file, self.out))
        manifest = {
            **base,
            "traceability": traces,
            "artifacts": files,
            "scope": "single AXI4-Stream master + one handshake stability rule",
            "not_covered": ["其他协议与多时钟", "TLAST/乱序/CDC", "LLM 对任意原文的完整理解", "跨 Run STALE 传播"],
            "simulation_is_proof_only_for_this_rule_and_scenarios": True,
        }
        manifest["rtl_simulation_completed"] = bool(base.get("scenarios")) and all(
            row["runtime"].get("simulation_kind") == "rtl_simulation" and row["actual_status"] in ("PASS", "FAIL")
            for row in base["scenarios"]
        )
        path = self.out / "manifest.json"
        _write_json(path, manifest)
        return path


__all__ = ["TemporalSlicePipeline"]
