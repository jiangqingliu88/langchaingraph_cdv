"""Unit Testing 专家 —— 纯 SystemVerilog testbench（不引入 UVM）。

流程：LLM 生成 TB → 写 `<run>/unit_test/` → `vlog` 编译 → `vsim -c` 运行 →
`report.json` 如实记录 compile/run 状态。没有 EDA 工具就写 SKIPPED，
**不把"生成了 TB"说成"测试通过"**。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import structlog

from src.agent_plane.common import (
    SpecialistError,
    now_iso,
    sha256_text,
    strip_code_fence,
)

logger = structlog.get_logger()

PROMPT_VERSION = "unit_test_tb_v1"
MAX_RTL_CHARS = 40_000
COMPILE_TIMEOUT = 300
SIM_TIMEOUT = 300

_MODULE_RE = re.compile(r"\bmodule\s+([A-Za-z_][A-Za-z0-9_]*)")


def _system_prompt(module: str) -> str:
    return f"""你是 SystemVerilog 单元测试工程师。为模块 `{module}` 写一个**纯 SV**
testbench（**不要 UVM**，不要 `uvm_pkg` / `uvm_*` 宏）。

要求：
  1. 生成一个自包含的 `module {module}_tb;` … `endmodule`；
  2. 产生时钟与复位，实例化 DUT（实例名 `dut`）；
  3. 覆盖关键输入组合与复位行为，用 `$display` 打印检查点；
  4. 失败用 `$error` / `$fatal` 报出，结束时 `$finish`；
  5. 不要引用不存在的层次路径或文件；
  6. 只输出 SV 代码，不要 markdown 围栏之外的任何解释。
"""


def _messages(module: str, rtl_text: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": _system_prompt(module)},
        {"role": "user", "content": f"RTL:\n{rtl_text[:MAX_RTL_CHARS]}"},
    ]


def _validate_tb(text: str, module: str) -> str:
    tb = strip_code_fence(text)
    if "module" not in tb or "endmodule" not in tb:
        raise ValueError("输出不是完整的 SystemVerilog module（缺 module/endmodule）")
    if "uvm_" in tb.lower():
        raise ValueError("输出包含 UVM 代码；本模式要求纯 SV testbench")
    if f"{module}_tb" not in tb:
        raise ValueError(f"testbench module 名必须是 {module}_tb")
    return tb


def generate_tb(rtl_text: str, *, module: str, attempts: int = 2) -> str:
    from src.runtime_plane.tools.common.lib.llm_call import call_llm_messages

    if not str(rtl_text or "").strip():
        raise SpecialistError("RTL 文本为空，无法生成 testbench")
    feedback = ""
    last = ""
    for attempt in range(1, attempts + 1):
        messages = _messages(module, rtl_text)
        if feedback:
            messages.append({"role": "user", "content": feedback})
        raw = call_llm_messages(
            messages,
            output_schema={"type": "string"},
            prompt_version=PROMPT_VERSION,
            task_type="unit_test_tb",
            output_format="text",
        )
        if not raw:
            last = "LLM 无输出（检查 LLM_API_KEY / 网络 / 代理）"
        else:
            try:
                return _validate_tb(raw, module)
            except ValueError as exc:
                last = str(exc)
                feedback = f"上一次输出不合法：{last}\n请只输出修正后的纯 SV testbench。"
        logger.warning(f"Unit Test TB 生成失败（attempt {attempt}）：{last[:200]}")
    raise SpecialistError(f"无法生成 unit testbench（{attempts} 次尝试）：{last}")


def _run_cmd(cmd: list[str], cwd: Path, log_path: Path, timeout: int) -> dict[str, Any]:
    try:
        proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=timeout, check=False)
        log_path.write_text((proc.stdout or "") + "\n" + (proc.stderr or ""), encoding="utf-8")
        return {"returncode": proc.returncode, "log": str(log_path)}
    except FileNotFoundError:
        return {"returncode": 127, "log": "", "missing_tool": cmd[0]}
    except subprocess.TimeoutExpired:
        log_path.write_text(f"TIMEOUT after {timeout}s", encoding="utf-8")
        return {"returncode": 124, "log": str(log_path), "timeout": True}


def _sim_errors(log_path: Path) -> int:
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0
    match = re.search(r"Errors:\s*(\d+)", text)
    if match:
        return int(match.group(1))
    return 1 if re.search(r"\$fatal|\bFATAL\b|Fatal:", text) else 0


def run(
    rtl_path: str | Path, output_dir: str | Path, *, module: str = "", compile: bool = True, simulate: bool = True
) -> dict[str, Any]:
    """生成 TB → 编译 → 运行 → report。同步入口（CLI 用）。"""
    rtl = Path(rtl_path)
    if not rtl.is_file():
        raise SpecialistError(f"RTL 文件不存在：{rtl}")
    rtl_text = rtl.read_text(encoding="utf-8", errors="replace")
    mod = module.strip() or next((m.group(1) for m in _MODULE_RE.finditer(rtl_text)), rtl.stem)

    tb_text = generate_tb(rtl_text, module=mod)
    out = Path(output_dir) / "unit_test"
    out.mkdir(parents=True, exist_ok=True)
    rtl_dir = out / "rtl"
    rtl_dir.mkdir(exist_ok=True)
    rtl_copy = rtl_dir / rtl.name
    shutil.copy2(rtl, rtl_copy)
    tb_path = out / f"{mod}_tb.sv"
    tb_path.write_text(tb_text + "\n", encoding="utf-8")

    report: dict[str, Any] = {
        "schema": "unit_test_report_v1",
        "module": mod,
        "generated_at": now_iso(),
        "generator": {"prompt_version": PROMPT_VERSION},
        "rtl": {"path": str(rtl_copy), "sha256": sha256_text(rtl_text)},
        "tb": {"path": str(tb_path), "sha256": sha256_text(tb_text)},
        "compile": {"status": "SKIPPED", "returncode": None, "log": ""},
        "run": {"status": "SKIPPED", "returncode": None, "log": "", "errors": 0},
    }

    if compile:
        if not shutil.which("vlog"):
            report["compile"]["reason"] = "vlog 不在 PATH"
        else:
            res = _run_cmd(["vlog", "-sv", str(rtl_copy), str(tb_path)], out, out / "compile.log", COMPILE_TIMEOUT)
            ok = res.get("returncode") == 0 and not res.get("missing_tool")
            report["compile"].update(
                {
                    "status": "PASS" if ok else "FAIL",
                    "returncode": res.get("returncode"),
                    "log": res.get("log", ""),
                }
            )
            if res.get("missing_tool"):
                report["compile"]["reason"] = f"{res['missing_tool']} 不在 PATH"

    if simulate and report["compile"]["status"] == "PASS":
        if not shutil.which("vsim"):
            report["run"]["reason"] = "vsim 不在 PATH"
        else:
            res = _run_cmd(["vsim", "-c", "-do", "run -all; quit -f", f"{mod}_tb"], out, out / "sim.log", SIM_TIMEOUT)
            log_path = Path(res.get("log") or "")
            errors = _sim_errors(log_path) if log_path.is_file() else 0
            ok = res.get("returncode") == 0 and errors == 0
            report["run"].update(
                {
                    "status": "PASS" if ok else "FAIL",
                    "returncode": res.get("returncode"),
                    "log": res.get("log", ""),
                    "errors": errors,
                }
            )
            if res.get("missing_tool"):
                report["run"]["reason"] = f"{res['missing_tool']} 不在 PATH"

    # 总体状态：只有真的跑过且零错误才算 PASS
    if report["run"]["status"] == "PASS":
        report["status"] = "PASS"
    elif report["compile"]["status"] == "FAIL":
        report["status"] = "COMPILE_FAIL"
    elif report["run"]["status"] == "FAIL":
        report["status"] = "RUN_FAIL"
    else:
        report["status"] = "GENERATED_ONLY"

    report_path = out / "report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"Unit Test：{mod} · {report['status']} → {report_path}")
    return {
        "status": report["status"],
        "module": mod,
        "tb": str(tb_path),
        "report": str(report_path),
        "compile": report["compile"]["status"],
        "run": report["run"]["status"],
    }


async def arun(
    rtl_path: str | Path, output_dir: str | Path, *, module: str = "", compile: bool = True, simulate: bool = True
) -> dict[str, Any]:
    from .graph import build_unit_test_graph

    final = await build_unit_test_graph().ainvoke(
        {
            "rtl_path": str(rtl_path),
            "output_dir": str(output_dir),
            "module": module,
            "compile": compile,
            "simulate": simulate,
        }
    )
    return final["result"]


def run_async(
    rtl_path: str | Path, output_dir: str | Path, *, module: str = "", compile: bool = True, simulate: bool = True
) -> dict[str, Any]:
    import asyncio

    return asyncio.run(arun(rtl_path, output_dir, module=module, compile=compile, simulate=simulate))


__all__ = ["PROMPT_VERSION", "SpecialistError", "generate_tb", "run", "arun", "run_async"]
