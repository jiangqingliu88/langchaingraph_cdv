"""Minimal RegressionRunner adapter — wraps vlog/vsim subprocess calls."""

import os, subprocess, time
from pathlib import Path


class RegressionRunner:
    """Lightweight regression runner for compile + sim."""

    # QuestaSim home — resolved at call-time from env or config
    @classmethod
    def _questa(cls):
        questa = os.environ.get("QUESTA_HOME", "f:/questasim64_2024.1/win64")
        # Fallback: if QUESTA_HOME is set but vlog.exe not found there, try default
        if questa and not os.path.exists(os.path.join(questa, "win64", "vlog.exe")):
            if not os.path.exists(os.path.join(questa, "vlog.exe")):
                default = "f:/questasim64_2024.1/win64"
                if os.path.exists(os.path.join(default, "vlog.exe")):
                    return default
        return questa

    def __init__(self, env_output_dir: str, filelist: str = "",
                 top_module: str = "", coverage: bool = False):
        self.output_dir = Path(env_output_dir)
        self.filelist = filelist
        self.top_module = top_module
        self.coverage = coverage
        self.work_dir = self.output_dir / "build" / "work"
        self.work_dir.mkdir(parents=True, exist_ok=True)

    def compile(self) -> dict:
        """Run vlog. Returns {status, errors, time_s, stderr}."""
        vlog = os.path.join(self._questa(), "win64", "vlog.exe")
        if not os.path.exists(vlog):
            # Try without win64
            vlog = os.path.join(self._questa(), "vlog.exe")
        if not os.path.exists(vlog):
            return {"status": "FAIL", "errors": 1, "time_s": 0,
                    "stderr": f"vlog not found at {vlog}"}

        wd = str(self.work_dir.resolve()).replace("\\", "/")
        fl = str(Path(self.filelist).resolve()).replace("\\", "/") if self.filelist else ""

        cmd = [vlog, "-work", wd, "-sv", "-mfcu", "+acc"]
        # UVM 库：缺了会导致 `uvm_macros.svh` / `uvm_object_utils` 未定义（coverage 编译失败根因）。
        # 与 regression.yaml 的 compile 模板保持一致：+incdir+uvm_src + uvm_pkg.sv。
        _questa_root = os.path.dirname(self._questa())
        _uvm_src = os.path.join(_questa_root, "verilog_src", "uvm-1.2", "src").replace("\\", "/")
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
        vsim = os.path.join(self._questa(), "win64", "vsim.exe")
        if not os.path.exists(vsim):
            vsim = os.path.join(self._questa(), "vsim.exe")
        if not os.path.exists(vsim):
            return {"status": "FAIL", "error": "vsim not found"}

        wd = str(self.work_dir.resolve()).replace("\\", "/")
        sim_dir = self.output_dir / "sim" / "dut"
        sim_dir.mkdir(parents=True, exist_ok=True)
        sim_str = str(sim_dir.resolve()).replace("\\", "/")

        cmd = [
            vsim, "-c",
            "-sv_lib", f"{self._questa().replace('win64','')}{os.environ.get('UVM_VERSION','uvm-1.2')}/win64/uvm_dpi",
            "-onfinish", "stop",
            "-wlf", f"{sim_str}/wave_{test_name}.wlf",
            "-work", wd,
            "-l", f"{sim_str}/sim_{test_name}.log",
        ]
        if self.coverage:
            cmd.append("-coverage")
            cov_dir = self.output_dir / "sim" / "coverage"
            cov_dir.mkdir(parents=True, exist_ok=True)
            cov_do = (
                f"coverage save -onexit {cov_dir.as_posix()}/{test_name}.ucdb; "
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
        return {
            "status": "PASS" if errors == 0 else "FAIL",
            "errors": errors,
            "test_name": test_name,
        }
