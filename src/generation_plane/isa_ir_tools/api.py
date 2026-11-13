"""Dict-in/dict-out adapters for the workbench.

The workbench never imports the tool package; it reaches these functions
through ``src/workbench/bridge/catalog.py``.  Keep this module free of Qt and
free of imports from outside ``isa_ir_tools``.
"""
from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
from typing import Any

from .cmd_compile import CompileError
from .core import TensorGenError
from .ir_flow import FixedIRFlow, IRFlowError
from .isa_versions import normalize_address_schema

_STAGE_LOGS = ("stage1.log", "stage2.log", "stage3.log")


def _jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


def _error(exc: BaseException) -> dict:
    return {
        "code": getattr(exc, "code", type(exc).__name__),
        "line": getattr(exc, "line", None),
        "message": str(exc),
    }


def _action_rows(flow: FixedIRFlow) -> list[dict]:
    rows = []
    for index, action in enumerate(flow.actions):
        fields = action.get("fields", {})
        rows.append({
            "index": index,
            "line": action.get("source", {}).get("line"),
            "kind": "control" if "passthrough" in action else "isa",
            "op": action.get("op", ""),
            "fields": _jsonable(fields),
            "fields_text": ", ".join(f"{key}={value}" for key, value in fields.items()),
        })
    return rows


def _decode(source_text: str, *, isa_revision=None, cfg_lint=True) -> FixedIRFlow:
    return FixedIRFlow(source_text, "<workbench>", cfg_lint=bool(cfg_lint),
                       isa_revision=isa_revision).parse()


def run_validate(source_text: str, isa_revision=None, cfg_lint: bool = True) -> dict:
    """Parse an IR source (or resolved seq.ir) without writing anything."""
    if not isinstance(source_text, str) or not source_text.strip():
        return {"ok": False,
                "error": {"code": "EMPTY_SOURCE", "line": None,
                          "message": "IR source is empty"}}
    try:
        flow = _decode(source_text, isa_revision=isa_revision, cfg_lint=cfg_lint)
    except (IRFlowError, CompileError, TensorGenError, ValueError, OSError) as exc:
        return {"ok": False, "error": _error(exc)}
    actions = _action_rows(flow)
    return {
        "ok": True,
        "isa_revision": flow.isa_revision,
        "address_schema": flow.address_schema,
        "case": _jsonable(flow.case),
        "profile": _jsonable(flow.profile),
        "counts": {
            "tensors": len(flow.tensors),
            "views": len(flow.views),
            "scalars": len(flow.scalars),
            "actions": len(actions),
            "instructions": sum(1 for row in actions if row["kind"] == "isa"),
            "controls": sum(1 for row in actions if row["kind"] == "control"),
        },
        "tensors": [{"name": name, "shape": tensor.get("shape"),
                     "dtype": tensor.get("dtype")}
                    for name, tensor in flow.tensors.items()],
        "views": [{"name": name, "tensor": view.get("tensor"),
                   "kind": view.get("kind", "reserve_view")}
                  for name, view in flow.views.items()],
        "actions": actions,
    }


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def run_build(source_text: str, out_dir: str, target: str = "standalone",
              core_id: int = 0, isa_revision=None, cfg_lint: bool = True,
              csr_clk_rst: bool = False) -> dict:
    """Run the three-stage flow and return the produced command program.

    Writes a bundle under ``out_dir`` (01_tensors / 02_ir / 03_commands).
    """
    if not isinstance(source_text, str) or not source_text.strip():
        return {"ok": False,
                "error": {"code": "EMPTY_SOURCE", "line": None,
                          "message": "IR source is empty"}}
    if target != "standalone":
        return {"ok": False,
                "error": {"code": "UNSUPPORTED_TARGET", "line": None,
                          "message": "cluster instr dispatch format is not defined yet"}}
    bundle = Path(out_dir).expanduser().resolve()
    bundle.mkdir(parents=True, exist_ok=True)
    source = bundle / "source.ir.txt"
    source.write_text(source_text, encoding="utf-8")

    from .run_flow import main as run_flow_main

    argv = [str(source), "--target", target, "--core-id", str(core_id),
            "--out-dir", str(bundle)]
    if isa_revision:
        argv += ["--isa-revision", isa_revision]
    if not cfg_lint:
        argv.append("--no-cfg-lint")
    if csr_clk_rst:
        argv.append("--csr-clk-rst")

    console = io.StringIO()
    try:
        with contextlib.redirect_stdout(console):
            code = run_flow_main(argv)
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 2
    except Exception as exc:  # keep the UI alive; report the cause as data
        return {"ok": False, "bundle": str(bundle), "source": str(source),
                "error": _error(exc), "console": console.getvalue()}

    report = _read_json(bundle / "pipeline.report.json") or {}
    commands = _read_json(bundle / "03_commands" / "commands.json")
    seq_ir = _read_text(bundle / "02_ir" / "seq.ir")
    logs = {name: _read_text(bundle / name) for name in _STAGE_LOGS}
    files = sorted(str(path.relative_to(bundle)).replace("\\", "/")
                   for path in bundle.rglob("*") if path.is_file())
    ok = code == 0
    return {
        "ok": ok,
        "bundle": str(bundle),
        "source": str(source),
        "stages": report.get("stages", []),
        "isa_revision": report.get("isa_revision"),
        "address_schema": normalize_address_schema(report.get("address_schema", "")),
        "seq_ir": seq_ir,
        "commands_json": commands,
        "logs": logs,
        "files": files,
        "console": console.getvalue(),
        "error": None if ok else {
            "code": "FLOW_FAILED",
            "line": None,
            "message": "flow failed; see stage logs",
        },
    }
