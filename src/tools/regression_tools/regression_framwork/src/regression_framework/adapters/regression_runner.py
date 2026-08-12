"""Minimal RegressionRunner adapter — wraps vlog/vsim subprocess calls."""

import os, subprocess, time
from pathlib import Path


class RegressionRunner:
    """Lightweight regression runner for compile + sim."""

    # QuestaSim home — resolved from env var QUESTA_HOME, then common paths
    _COMMON_QUESTA_PATHS = [
        "f:/questasim64_2024.1/win64",
        "f:/questasim64_2024.1",
        "c:/questasim64_2024.1/win64",
        "c:/questasim64_2024.1",
        "f:/questasim64_2023.3/win64",
        "c:/modeltech/win64",
        "/usr/local/mentor/questasim/bin",
        "/opt/mentor/questasim/bin",
    ]

    @classmethod
    def _questa(cls):
        # 1. 环境变量 QUESTA_HOME（最高优先级）
        questa = os.environ.get("QUESTA_HOME", "")
        if questa:
            for candidate in [questa, os.path.join(questa, "win64"), os.path.join(questa, "bin")]:
                if os.path.exists(os.path.join(candidate, "vlog.exe")):
                    return candidate
                if os.path.exists(os.path.join(candidate, "vlog")):  # Linux
                    return candidate

        # 2. 常见安装路径
        for path in cls._COMMON_QUESTA_PATHS:
            if os.path.exists(os.path.join(path, "vlog.exe")):
                return path
            if os.path.exists(os.path.join(path, "vlog")):  # Linux
                return path

        # 3. PATH 中搜索
        import shutil as _shutil
        for cmd in ["vlog.exe", "vlog"]:
            found = _shutil.which(cmd)
            if found:
                return str(Path(found).parent)

        # 4. 回退默认
        return os.environ.get("QUESTA_HOME", "f:/questasim64_2024.1/win64")

    def __init__(self, env_output_dir: str, filelist: str = "",
                 top_module: str = "", coverage: bool = False,
                 compile_dir: str = "", sim_dir: str = ""):
        self.output_dir = Path(env_output_dir)
        self.filelist = filelist
        self.top_module = top_module
        self.coverage = coverage

        # compile_dir: vlog work library 路径
        #   ""              → output_dir/build/work (兼容旧行为)
        #   "uvm_regress"   → output_dir/uvm_regress/build/work (共享 work lib)
        compile_base = self.output_dir / compile_dir if compile_dir else self.output_dir
        self.work_dir = compile_base / "build" / "work"
        self.work_dir.mkdir(parents=True, exist_ok=True)

        # sim_dir: vsim 仿真输出路径 (日志/波形/ucdb)
        #   ""              → output_dir/sim (兼容旧行为)
        #   "uvm_regress"   → output_dir/uvm_regress/sim (UVM phase)
        #   "test_regress"  → output_dir/test_regress/sim (regress phase)
        sim_base = self.output_dir / sim_dir if sim_dir else self.output_dir
        self.sim_root = sim_base / "sim"
        self.sim_root.mkdir(parents=True, exist_ok=True)

    def compile(self) -> dict:
        """Run vlog. Returns {status, errors, time_s, stderr}."""
        vlog = os.path.join(self._questa(), "vlog.exe")
        if not os.path.exists(vlog):
            return {"status": "FAIL", "errors": 1, "time_s": 0,
                    "stderr": f"vlog not found at {vlog}"}

        wd = str(self.work_dir.resolve()).replace("\\", "/")
        fl = str(Path(self.filelist).resolve()).replace("\\", "/") if self.filelist else ""

        # 设置 UVM 源文件路径（QuestaSim verilog_src/uvm-1.2）
        questa_root = os.path.dirname(self._questa())  # win64/.. → questa root
        uvm_src_dir = os.path.join(questa_root, "verilog_src", "uvm-1.2", "src")
        uvm_pkg_path = os.path.join(uvm_src_dir, "uvm_pkg.sv")
        questa_uvm_dir = os.path.join(questa_root, "verilog_src", "questa_uvm_pkg-1.2")
        questa_uvm_pkg = os.path.join(questa_uvm_dir, "questa_uvm_pkg.sv") if os.path.exists(questa_uvm_dir) else ""

        cmd = [vlog, "-work", wd, "-sv", "-mfcu", "+acc"]
        # 先编译 UVM 包（如果源文件存在）
        if os.path.exists(uvm_pkg_path):
            cmd += ["+incdir+" + uvm_src_dir.replace("\\", "/"),
                    uvm_pkg_path.replace("\\", "/")]
            # 同时编译 questa_uvm_pkg（Questa 专用 UVM 扩展）
            if questa_uvm_pkg and os.path.exists(questa_uvm_pkg):
                cmd += ["+incdir+" + questa_uvm_dir.replace("\\", "/"),
                        questa_uvm_pkg.replace("\\", "/")]
        if self.coverage:
            cmd += ["-cover", "sbceft"]
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
        questa = self._questa()
        vsim = os.path.join(questa, "vsim.exe")
        if not os.path.exists(vsim):
            # 尝试在 win64 子目录下查找（_questa 可能返回了不包含 win64 的父目录）
            vsim = os.path.join(questa, "win64", "vsim.exe")
        if not os.path.exists(vsim):
            return {"status": "FAIL", "error": f"vsim not found at {vsim}"}

        wd = str(self.work_dir.resolve()).replace("\\", "/")
        dut_dir = self.sim_root / "dut"
        dut_dir.mkdir(parents=True, exist_ok=True)
        dut_str = str(dut_dir.resolve()).replace("\\", "/")

        cmd = [
            vsim, "-c",
            "-sv_lib", f"{self._questa().replace('win64','')}{os.environ.get('UVM_VERSION','uvm-1.2')}/win64/uvm_dpi",
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
        return {
            "status": "PASS" if errors == 0 else "FAIL",
            "errors": errors,
            "test_name": test_name,
        }
