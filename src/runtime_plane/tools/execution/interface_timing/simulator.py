"""真实 SystemVerilog 仿真执行。

仅当外部 iverilog/vvp 实际启动并结束时，simulation_kind 才是 rtl_simulation。
工具不存在、编译失败、脚本失败、格式不完整均为 INCOMPLETE，绝不伪造 PASS。
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


# Runtime 只消费结构化接口，不 import Generation/IR，避免反向依赖。
# 调用方可传 _IRSpec / _MonitorSpec；这里是它们的读取契约。
class _IRSpec(Protocol):
    clock: Any
    signals: list[Any]
    rules: list[Any]

    def content_hash(self) -> str: ...


class _MonitorSpec(Protocol):
    rule_id: str
    path: Path
    module: str
    valid: str
    ready: str
    stable_signals: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]: ...


def _verilog_exe(name: str) -> str:
    home = os.environ.get("IVERILOG_HOME")
    installed = (
        (Path(home) / "bin" / f"{name}.exe")
        if home
        else Path(os.environ.get("LOCALAPPDATA", "")) / "SignOffAI/tools/iverilog-v14/bin" / f"{name}.exe"
    )
    if installed.is_file():
        return str(installed)
    explicit = os.environ.get(f"INTERFACE_TIMING_{name.upper()}")
    if explicit and Path(explicit).is_file():
        return explicit
    return shutil.which(name) or ""


def _safe_data_width(ir: _IRSpec) -> int:
    values = [
        next(s for s in ir.signals if s.name == name).width
        for name in ir.rules[0].stable_signals
        if name != ir.rules[0].valid
    ]
    return values[0] if values else 1


def _render_testbench(ir: _IRSpec, monitor: _MonitorSpec, seed: int, dut_module: str) -> str:
    valid, ready = monitor.valid, monitor.ready
    clock, reset = ir.clock.name, ir.clock.reset
    width = _safe_data_width(ir)
    payload = (0x101 ^ int(seed)) & ((1 << width) - 1)
    data_name = next((name for name in monitor.stable_signals if name != valid), "")
    data_port = f".{data_name}({data_name})" if data_name else ""
    data_assignment = f"req_data = {width}'h{payload:x};" if data_name else ""
    return f"""`timescale 1ps/1ps
module tb_stream;
    reg {clock} = 0;
    reg {reset} = {"1" if ir.clock.reset_active_high else "0"};
    reg {ready} = 0;
    reg req_valid = 0;
    reg [{width - 1}:0] req_data = 0;
    wire {valid};
    wire [{width - 1}:0] {data_name};
    integer seed = {int(seed)};

    always #({ir.clock.period_ps / 2}) {clock} = ~{clock};

    {dut_module} dut (
        .{clock}({clock}),
        .{reset}({reset}),
        .{ready}({ready}),
        .req_valid(req_valid),
        .req_data(req_data),
        .{valid}({valid}),
        {data_port}
    );

    {monitor.module} mon (
        .{clock}({clock}),
        .{reset}({reset}),
        .{valid}({valid}),
        .{ready}({ready}),
        .{data_name}({data_name})
    );

    initial begin
        $dumpfile("timing_wave.vcd");
        $dumpvars(0, tb_stream);
        repeat (3) @(negedge {clock});
        {reset} = {"0" if ir.clock.reset_active_high else "1"};
        @(negedge {clock});
        {data_assignment}
        req_valid = 1'b1;
        @(negedge {clock});
        req_valid = 1'b0;
        // 保留两个完整背压周期，再完成一次握手，避免空样例 PASS。
        repeat (2) @(negedge {clock});
        {ready} = 1'b1;
        @(negedge {clock});
        {ready} = 1'b0;
        repeat (2) @(negedge {clock});
        $display("TIMING_RESULT rule={ir.rules[0].rule_id} violations=%0d handshakes=%0d blocked=%0d unknown=%0d",
                 mon.violations, mon.handshakes, mon.blocked_samples, mon.unknown_samples);
        $finish;
    end
endmodule
"""


def _run(command: list[str], cwd: Path, log_path: Path) -> tuple[int, str]:
    with log_path.open("w", encoding="utf-8") as log:
        log.write("COMMAND: " + " ".join(command) + "\n")
        log.flush()
        try:
            process = subprocess.run(
                command, cwd=str(cwd), stdout=log, stderr=subprocess.STDOUT, timeout=45, check=False
            )
            return process.returncode, ""
        except (OSError, subprocess.TimeoutExpired) as exc:
            log.write(f"EXECUTION_ERROR: {exc}\n")
            return -1, str(exc)


@dataclass
class SimulationResult:
    status: str
    report: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, **self.report}


def _evaluate_monitor_text(text: str, expected_rule: str, base: dict[str, Any]) -> SimulationResult:
    """只解析格式一致的 monitor 结果；规则 ID 不同不能冒充本次证明。"""
    match = re.search(r"TIMING_RESULT rule=(\S+) violations=(\d+) handshakes=(\d+) blocked=(\d+) unknown=(\d+)", text)
    if not match:
        return SimulationResult("INCOMPLETE", {**base, "reason": "simulation 没有可识别结果"})
    rule, violations, handshakes, blocked, unknown = match.groups()
    if rule != expected_rule:
        return SimulationResult("INCOMPLETE", {**base, "reason": f"monitor 结果规则不匹配：{rule} != {expected_rule}"})
    counts = {
        "violations": int(violations),
        "handshakes": int(handshakes),
        "blocked_samples": int(blocked),
        "unknown_samples": int(unknown),
    }
    if counts["unknown_samples"]:
        status = "INCOMPLETE"
    elif counts["violations"]:
        status = "FAIL"
    elif counts["blocked_samples"] and counts["handshakes"]:
        status = "PASS"
    else:
        status = "INCOMPLETE"
    return SimulationResult(status, {**base, "rule_id": rule, "counts": counts})


def simulate(
    ir: _IRSpec,
    monitor: _MonitorSpec,
    rtl_file: str | Path,
    out_dir: str | Path,
    *,
    seed: int,
    dut_module: str = "stream_master_model",
) -> SimulationResult:
    output = Path(out_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    compiler, runtime = _verilog_exe("iverilog"), _verilog_exe("vvp")
    base = {
        "schema": "interface_runtime_evidence_v1",
        "seed": seed,
        "stimulus": "one directed request with backpressure",
        "seed_usage": "request payload = 0x101 XOR seed",
        "simulation_kind": "unavailable",
        "interface_ir_hash": ir.content_hash(),
        "rtl_source": str(Path(rtl_file).resolve()),
        "require_observation": {"blocked_samples": 1, "handshakes": 1},
    }
    if not compiler or not runtime:
        return SimulationResult(
            "INCOMPLETE",
            {
                **base,
                "reason": "iverilog/vvp 未安装或安全软件阻止使用；未执行 RTL 仿真",
                "tool_discovery": [
                    "PATH",
                    "INTERFACE_TIMING_IVERILOG/VVP",
                    "%LOCALAPPDATA%/SignOffAI/tools/iverilog-v14/bin",
                ],
            },
        )
    bench = output / "tb_stream.sv"
    bench.write_text(_render_testbench(ir, monitor, seed, dut_module), encoding="utf-8", newline="\n")
    binary = output / "stream_sim.vvp"
    code, error = _run(
        [
            compiler,
            "-g2012",
            "-s",
            "tb_stream",
            "-o",
            str(binary),
            str(monitor.path),
            str(Path(rtl_file).resolve()),
            str(bench),
        ],
        output,
        output / "compile.log",
    )
    base["simulation_kind"] = "rtl_simulation"
    base["compiler"] = compiler
    if code != 0:
        return SimulationResult("INCOMPLETE", {**base, "reason": error or f"编译失败：{code}"})
    version_log = output / "tool_version.log"
    _run([compiler, "-V"], output, version_log)
    with (output / "simulate.log").open("a", encoding="utf-8"):
        pass
    code, error = _run([runtime, str(binary)], output, output / "simulate.log")
    if code != 0:
        return SimulationResult("INCOMPLETE", {**base, "reason": error or f"仿真执行失败：{code}"})
    text = (output / "simulate.log").read_text(encoding="utf-8", errors="replace")
    result = _evaluate_monitor_text(text, ir.rules[0].rule_id, base)
    result.report.update(
        {
            "waveform": str(output / "timing_wave.vcd") if (output / "timing_wave.vcd").is_file() else "",
            "monitor": monitor.to_dict(),
            "logs": ["compile.log", "simulate.log", "tool_version.log"],
        }
    )
    return result


__all__ = ["SimulationResult", "simulate"]
