"""DUT 代码覆盖率的**回归合并口径**。

单测的 `merged.ucdb` 只跑一条 coverage test，代码覆盖率天然低；而回归 266 条
用例各自落了 `cov/*/questa.db`。功能覆盖率已经合并成 `plan_merged.ucdb`，但
**代码覆盖率没有** —— 因为 loopback TB 与 DUT TB 的层次不同，vcover 会打
"Design hierarchy mismatch" 并跳过一部分。

本模块只合并 **DUT 层次**的用例库（排除 loopback），单独产出
`plan_dut_code.ucdb` / `coverage_code_plan.txt`，回答：
“回归跑过的这些用例，对 DUT 的代码覆盖到底是多少”。

它是**对照口径**，不改变签核门禁（门禁仍是功能覆盖率）；结果写进
`coverage_result.json` 的 `code_plan`。
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Dict, List

SCHEMA = "code_coverage_plan_v1"


def dut_stores(output_dir: str | Path) -> List[Path]:
    """DUT 层次的覆盖率库（排除 loopback TB）。"""
    root = Path(output_dir)
    reg = root / "regression_run"
    if not reg.is_dir():
        return []
    return [p for p in sorted(reg.rglob("cov/*/questa.db"))
            if "loopback" not in p.parts]


def store_specs(od: Path, stores: List[Path]) -> List[str]:
    """coverstore → vcover merge 的 spec（相对 run 根，带 `cov/...`）。"""
    specs: List[str] = []
    for db in stores:
        store = db.parent
        data = sorted(store.glob("*.data"))
        stem = (data[0].stem if len(data) == 1
                else (store.name if not data else
                      max(data, key=lambda x: x.stat().st_mtime).stem))
        if (not stem) or stem in ("(null)", "null"):
            stem = ""
        try:
            rel = store.relative_to(od).as_posix()
        except ValueError:
            continue
        specs.append(rel if not stem else f"{rel}:{stem}")
    return specs


def merge_dut_code_coverage(output_dir: str | Path) -> Dict[str, Any]:
    """合并 DUT 用例库 → 代码覆盖率指标。失败返回 `{errors}`，不抛。"""
    from config.settings import questa_exe

    od = Path(output_dir).resolve()
    stores = dut_stores(od)
    if not stores:
        return {}
    out_dir = od / "sim" / "coverage"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "plan_dut_code.ucdb"
    report = out_dir / "reports" / "coverage_code_plan.txt"
    specs = store_specs(od, stores)
    if not specs:
        return {"stores": len(stores), "merged": 0,
                "errors": ["no merge specs"]}

    vcover = questa_exe("vcover.exe")
    if not vcover:
        return {"stores": len(stores), "merged": 0,
                "errors": ["vcover not found"]}
    inputs = out_dir / "plan_dut_code_inputs.txt"
    errors: List[str] = []
    warnings: List[str] = []
    try:
        inputs.write_text("\n".join(specs) + "\n", encoding="utf-8")
        proc = subprocess.run(
            [vcover, "merge", "-inputs", str(inputs), str(out)],
            cwd=str(od), capture_output=True, text=True,
            errors="replace", timeout=600)
        if proc.returncode != 0 or not out.is_file():
            errors.append(((proc.stdout or "") + (proc.stderr or "")).strip()[-300:])
            return {"stores": len(stores), "merged": 0, "errors": errors}
        tail = ((proc.stdout or "") + (proc.stderr or "")).strip()
        if "Design hierarchy mismatch" in tail:
            warnings.append("DUT 用例库内部层次不一致；仅合并同层次部分")
    except (OSError, subprocess.SubprocessError) as exc:
        return {"stores": len(stores), "merged": 0, "errors": [str(exc)]}

    try:
        r = subprocess.run([vcover, "report", "-codeAll", str(out)],
                           capture_output=True, text=True,
                           errors="replace", timeout=180)
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(r.stdout or "", encoding="utf-8", errors="replace")
        from src.tools.common.lib.collect_real_coverage import (
            _discover_dut_name, _parse_vcover_text)

        metrics = _parse_vcover_text(r.stdout or "", _discover_dut_name(od))
    except (OSError, subprocess.SubprocessError) as exc:
        errors.append(f"report: {exc}")
        return {"stores": len(stores), "merged": len(specs),
                "errors": errors, "warnings": warnings}

    return {
        "schema": SCHEMA,
        "stores": len(stores),
        "merged": len(specs),
        "ucdb": str(out),
        "report": str(report),
        "errors": errors,
        "warnings": warnings,
        **metrics,
    }
