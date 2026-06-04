"""
Verify_run 程序化封装 —— 供 Agent 直接调用，不依赖命令行

用法:
    from src.tools.compilesim.regression_wrapper import RegressionRunner
    runner = RegressionRunner(env_output_dir="generated/uart", filelist="generated/uart/filelist.f")
    result = runner.run(tests=["test_smoke"], tags=["smoke"])
"""
import os, yaml, json, tempfile, subprocess, time
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional

# QuestaSim 路径
QUESTA = "f:/questasim64_2024.1/win64"
UVM_SRC = "f:/questasim64_2024.1/verilog_src/uvm-1.2/src"


class RegressionRunner:
    """轻量回归运行器 —— 生成 YAML → 编译 → 仿真 → 收集结果"""

    def __init__(self, env_output_dir: str, filelist: str = "",
                 top_module: str = "uart_bench_tb_top",
                 simulator: str = "echo", coverage: bool = False,
                 work_dir: str = ""):
        self.env_dir = Path(env_output_dir)
        self.filelist = str(Path(filelist).resolve()) if filelist else ""
        self.top_module = top_module
        self.simulator = simulator
        self.coverage = coverage
        self.work_dir = Path(work_dir) if work_dir else (self.env_dir / "build" / "work")
        self.vlib = os.path.join(QUESTA, "vlib.exe")
        self.vlog = os.path.join(QUESTA, "vlog.exe")
        self.vsim = os.path.join(QUESTA, "vsim.exe")
        self.vcover = os.path.join(QUESTA, "vcover.exe")
        self.uvm_pkg = os.path.join(UVM_SRC, "uvm_pkg.sv")
        self.cov_dir = self.work_dir.parent / "coverage"

    # ── 动态生成 YAML ──

    def _build_yaml(self, tests: List[Dict], build_name: str = "auto_build",
                    tags: List[str] = None, compile_only: bool = False) -> dict:
        """从测试列表构造 regress YAML"""
        tags = tags or ["smoke"]
        test_configs = []
        for t in tests:
            tc = {
                "name": t.get("name", t.get("test_name", "test")),
                "build": build_name, "tags": tags,
                "seed": t.get("seed", 1), "count": t.get("count", 1),
                "sim_timeout": t.get("sim_timeout", 300),
            }
            if t.get("plusargs"):
                tc["plusargs"] = t["plusargs"]
            test_configs.append(tc)

        return {
            "config": {
                "name": "auto_regression",
                "description": f"Auto-generated {datetime.now().isoformat()}",
                "defaults": {
                    "simulator": self.simulator, "compile_timeout": 600,
                    "sim_timeout": 600, "verbosity": "UVM_MEDIUM",
                },
                "builds": [{
                    "name": build_name, "simulator": self.simulator,
                    "pre_build": [
                        "bash -c 'mkdir -p " + str(self.work_dir) + "'",
                        "bash -c '" + self.vlib + " " + str(self.work_dir) + "'",
                        "bash -c '" + self.vlog + " -work " + str(self.work_dir)
                        + " -sv +incdir+" + UVM_SRC + " -timescale=1ns/1ps "
                        + self.uvm_pkg + " -f " + self.filelist + "'",
                    ],
                    "filelist": self.filelist, "top_module": self.top_module,
                    "output_dir": str(self.work_dir.parent),
                    "compile_timeout": 300,
                }],
                "tests": test_configs,
            }
        }

    # ── 编译 ──

    def compile(self) -> Dict:
        """编译 UVM 环境，返回 {status, errors, time_s}"""
        t0 = time.time()
        self.work_dir.mkdir(parents=True, exist_ok=True)

        # vlib
        r1 = subprocess.run([self.vlib, str(self.work_dir)],
                            capture_output=True, text=True, timeout=60)
        if r1.returncode != 0 and "already exists" not in r1.stdout:
            return {"status": "FAIL", "errors": 1, "time_s": time.time() - t0, "stderr": r1.stderr[:500]}

        # vlog（coverage 模式加 +acc）
        vlog_cmd = [
            self.vlog, "-work", str(self.work_dir), "-sv",
            "+incdir+" + UVM_SRC, "-timescale=1ns/1ps",
        ]
        if self.coverage:
            vlog_cmd.append("+acc")
        vlog_cmd += [self.uvm_pkg, "-f", self.filelist]
        r2 = subprocess.run(vlog_cmd, capture_output=True, text=True, timeout=300)
        errs = r2.stdout.count("** Error")
        return {
            "status": "PASS" if r2.returncode == 0 else "FAIL",
            "errors": errs, "time_s": round(time.time() - t0, 1),
        }

    # ── 运行单个测试 ──

    def _run_one_test(self, yaml_data: dict, test_name: str  ) -> Dict:
        """通过 Verify_run 子进程跑单个测试"""
        tf = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8")
        try:
            yaml.dump(yaml_data, tf)
            tf.close()
            proc = subprocess.run([
                "python", "src/tools/compilesim/Verify_run.py",
                "-c", tf.name, "--test", test_name, "--builds",
            ], capture_output=True, text=True, timeout=600,
               cwd=str(Path.cwd()))
            passed = proc.returncode == 0
            return {
                "name": test_name, "status": "PASS" if passed else "FAIL",
                "returncode": proc.returncode,
                "stderr_tail": proc.stderr[-300:] if proc.stderr else "",
            }
        finally:
            try: os.unlink(tf.name)
            except: pass

    # ── 真实覆盖率收集 ──

    def collect_coverage(self, test_name: str, uvm_test: str = "") -> Dict:
        """运行单次仿真 + -coverage + vcover report，返回真实覆盖率数字"""
        self.cov_dir.mkdir(parents=True, exist_ok=True)
        test_tag = uvm_test or test_name
        ucdb = str(self.cov_dir / f"{test_name}.ucdb")

        # vsim -coverage
        vsim_cmd = [
            self.vsim, "-c", "-coverage", "-do",
            f"run -all; coverage save {ucdb}; quit",
            "-work", str(self.work_dir),
            "-L", "uvm", self.top_module,
            "+UVM_TESTNAME=" + test_tag,
        ]
        r = subprocess.run(vsim_cmd, capture_output=True, text=True, timeout=300,
                           cwd=str(self.work_dir.parent))

        if not Path(ucdb).exists():
            return {"status": "FAIL", "error": "ucdb not generated", "test": test_name}

        # vcover report
        r2 = subprocess.run([
            self.vcover, "report", "-details", ucdb,
        ], capture_output=True, text=True, timeout=60)

        # 解析 vcover report 输出
        lines = r2.stdout.split("\n")
        cov_data = {"test": test_name, "status": "PASS" if r.returncode == 0 else "FAIL"}
        current_section = None
        for line in lines:
            line = line.strip()
            if "Statement Coverage" in line or "Line Coverage" in line:
                current_section = "line"
            elif "Branch Coverage" in line:
                current_section = "branch"
            elif "Toggle Coverage" in line:
                current_section = "toggle"
            elif "FSM" in line and "Coverage" in line:
                current_section = "fsm"
            elif "%" in line and current_section:
                # parse "85.2%" style output
                try:
                    pct_str = line.split("%")[0].strip().split()[-1]
                    pct = float(pct_str)
                    cov_data[f"{current_section}_pct"] = pct
                except (ValueError, IndexError):
                    pass

        # 汇总
        cov_data.setdefault("line_pct", 0)
        cov_data.setdefault("branch_pct", 0)
        cov_data.setdefault("toggle_pct", 0)
        cov_data.setdefault("fsm_pct", 0)
        return cov_data

    # ── 完整回归 ──

    def run(self, tests: List[Dict] = None, tags: List[str] = None,
            compile_only: bool = False) -> Dict:
        """
        执行完整回归: 编译 → 运行测试 → 收集结果

        Args:
            tests: [{"name": "test_xxx", "plusargs": [...], ...}, ...]
            tags: ["smoke", "regression"]
        Returns:
            {compile: {...}, tests: [...], summary: {...}}
        """
        t0 = time.time()
        tests = tests or []
        tags = tags or ["smoke"]

        result = {"compile": {}, "tests": [], "summary": {}}

        # 编译
        result["compile"] = self.compile()
        if result["compile"]["status"] == "FAIL":
            result["summary"] = {"total": 0, "passed": 0, "compile": "FAIL"}
            return result

        if compile_only:
            result["summary"] = {"compile": "PASS", "tests": 0}
            return result

        # 运行测试
        for t in tests:
            test_name = t.get("name", t.get("test_name", "test"))
            yaml_data = self._build_yaml([t], tags=tags)
            tr = self._run_one_test(yaml_data, test_name)
            # 如果开启 coverage，收集真实覆盖率
            if self.coverage and tr["status"] == "PASS":
                uvm_test = t.get("uvm_test", test_name)
                cov = self.collect_coverage(test_name, uvm_test)
                tr["coverage"] = cov
            result["tests"].append(tr)

        passed = sum(1 for t in result["tests"] if t["status"] == "PASS")
        total = len(result["tests"])
        result["summary"] = {
            "total": total, "passed": passed,
            "compile": result["compile"]["status"],
            "pass_rate": f"{int(passed*100/max(total,1))}%",
            "total_time_s": round(time.time() - t0, 1),
        }
        return result


# ── 快捷入口（兼容旧接口）──

def run_regression(filelist: str, env_output_dir: str, tests: List[Dict],
                   top_module: str = "uart_bench_tb_top") -> Dict:
    """快捷入口"""
    runner = RegressionRunner(
        env_output_dir=env_output_dir,
        filelist=filelist,
        top_module=top_module,
    )
    return runner.run(tests=tests)
