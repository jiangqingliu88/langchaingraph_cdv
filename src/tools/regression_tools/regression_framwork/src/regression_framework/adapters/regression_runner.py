"""RegressionRunner —— vlog/vsim 调用的唯一咽喉。

铁律一（EDA 是唯一真理）：全仓所有编译/仿真判定都应经由此处，
PASS/FAIL 判据只在这里定义一次，避免出现「同一件事 4 份实现、判据还各不相同」。

PASS 判据（两条，缺一不可）：
  compile : 无 "** Error" 且 returncode == 0
  sim     : 无 UVM_ERROR/UVM_FATAL 且 returncode == 0

历史注记：本类的 compile_dir / sim_dir 两个参数曾在 449c0dce 被删除，
但 lib/compile.py 与 _tools_old.py 两个调用点仍在传参，导致二者每次调用都抛
TypeError，被上层 try/except 吞掉后 _verify_compilation 恒返回 False——
即铁律一长期处于失效状态。此处按 50e990db 的原语义恢复。
"""

import os, subprocess, time
from pathlib import Path

from config.settings import questa_exe, questa_home


class RegressionRunner:
    """Lightweight regression runner for compile + sim."""

    # QuestaSim 根目录（不含 win64）；解析规则见 config.settings.questa_home
    @classmethod
    def _questa(cls) -> str:
        return questa_home()

    def __init__(self, env_output_dir: str, filelist: str = "",
                 top_module: str = "", coverage: bool = False,
                 compile_dir: str = "", sim_dir: str = ""):
        self.output_dir = Path(env_output_dir)
        self.filelist = filelist
        self.top_module = top_module
        self.coverage = coverage

        # compile_dir: vlog work library 路径
        #   ""            → output_dir/build/work（兼容旧行为）
        #   "uvm_regress" → output_dir/uvm_regress/build/work（共享 work lib，增量编译）
        compile_base = self.output_dir / compile_dir if compile_dir else self.output_dir
        self.work_dir = compile_base / "build" / "work"
        self.work_dir.mkdir(parents=True, exist_ok=True)

        # sim_dir: vsim 仿真输出路径（日志/波形/ucdb）
        #   ""              → output_dir/sim
        #   "uvm_regress"   → output_dir/uvm_regress/sim（UVM phase）
        #   "test_regress"  → output_dir/test_regress/sim（regress phase）
        sim_base = self.output_dir / sim_dir if sim_dir else self.output_dir
        self.sim_root = sim_base / "sim"
        self.sim_root.mkdir(parents=True, exist_ok=True)

    def compile(self) -> dict:
        """Run vlog. Returns {status, errors, time_s, stderr}."""
        vlog = questa_exe("vlog.exe")
        if not os.path.exists(vlog):
            return {"status": "FAIL", "errors": 1, "time_s": 0,
                    "stderr": f"vlog not found at {vlog}"}

        wd = str(self.work_dir.resolve()).replace("\\", "/")
        fl = str(Path(self.filelist).resolve()).replace("\\", "/") if self.filelist else ""

        cmd = [vlog, "-work", wd, "-sv", "-mfcu", "+acc"]
        # UVM 库：缺了会导致 `uvm_macros.svh` / `uvm_object_utils` 未定义（coverage 编译失败根因）。
        # 与 regression.yaml 的 compile 模板保持一致：+incdir+uvm_src + uvm_pkg.sv。
        _uvm_src = os.path.join(questa_home(), "verilog_src", "uvm-1.2", "src").replace("\\", "/")
        _uvm_pkg = os.path.join(_uvm_src, "uvm_pkg.sv").replace("\\", "/")
        if os.path.exists(_uvm_pkg):
            cmd += [f"+incdir+{_uvm_src}", _uvm_pkg]
        if self.coverage:
            cmd.append("+cover=bcesf")  # branch/condition/expression/statement/fsm
        if fl:
            cmd += ["-f", fl]
        t0 = time.time()
        try:
            r = subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=120,
                              cwd=str(self.output_dir.resolve()))
        except subprocess.TimeoutExpired:
            return {"status": "FAIL", "errors": 1, "time_s": time.time() - t0,
                    "stderr": "Compile timeout"}

        errors = r.stderr.count("** Error") + r.stdout.count("** Error")
        status = "PASS" if errors == 0 and r.returncode == 0 else "FAIL"
        return {
            "status": status, "errors": errors,
            "time_s": round(time.time() - t0, 1),
            "stderr": r.stderr,
            "stdout": r.stdout,
        }

    def collect_coverage(self, test_name: str = "", uvm_test: str = "") -> dict:
        """Run vsim for a single test. Returns {status, ...}."""
        vsim = questa_exe("vsim.exe")
        if not os.path.exists(vsim):
            return {"status": "FAIL", "error": f"vsim not found at {vsim}"}

        wd = str(self.work_dir.resolve()).replace("\\", "/")
        dut_dir = self.sim_root / "dut"
        dut_dir.mkdir(parents=True, exist_ok=True)
        dut_str = str(dut_dir.resolve()).replace("\\", "/")

        cmd = [
            vsim, "-c",
            "-sv_lib", f"{questa_home()}/{os.environ.get('UVM_VERSION', 'uvm-1.2')}/win64/uvm_dpi",
            "-onfinish", "stop",
            "-wlf", f"{dut_str}/wave_{test_name}.wlf",
            "-work", wd,
            "-l", f"{dut_str}/sim_{test_name}.log",
        ]
        if self.coverage:
            cmd.append("-coverage")
            cov_dir = self.sim_root / "coverage"
            cov_dir.mkdir(parents=True, exist_ok=True)
            cov_do = (
                f"coverage save -onexit {cov_dir.resolve().as_posix()}/{test_name}.ucdb; "
                "log -r /*; run -all; quit -f"
            )
            cmd += ["-do", cov_do]
        else:
            cmd += ["-do", "log -r /*; run -all; quit -f"]
        cmd += [self.top_module, f"+UVM_TESTNAME={uvm_test}", "+UVM_TIMEOUT=100000"]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=300,
                              cwd=str(self.output_dir.resolve()))
        except subprocess.TimeoutExpired:
            return {"status": "FAIL", "error": "Sim timeout"}

        errors = r.stdout.count("UVM_ERROR") + r.stdout.count("UVM_FATAL")
        # 与 compile() 对齐：仿真非零退出同样判 FAIL（原来只看日志里的 UVM_ERROR，
        # vsim 崩溃/退出码非 0 但没打 UVM_ERROR 时会被误判为 PASS）
        return {
            "status": "PASS" if (errors == 0 and r.returncode == 0) else "FAIL",
            "errors": errors,
            "returncode": r.returncode,
            "test_name": test_name,
        }
