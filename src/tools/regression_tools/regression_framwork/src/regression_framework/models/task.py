# src/regression_framework/models/task.py
import os
import time
from abc import ABC, abstractmethod

class Task(ABC):
    def __init__(self, name: str, work_dir: str, script_path: str):
        self.name = name
        self.work_dir = work_dir
        self.script_path = script_path
        self.depends_on = []
        self.status = 'unknown'
        self.job_id = None
        self.fingerprint = 'unknown'
        self.cache_key = None
        # 任务耗时相关
        self.start_time = None
        self.elapsed = 0.0
        # 性能与波形相关（新增）
        self.sim_time = 0.0           # 仿真耗时（秒）
        self.wave_path = None         # 波形文件路径（失败时）
        self.performance_degraded = False  # 是否性能衰退

    @abstractmethod
    def execute(self, executor) -> bool:
        pass

class BuildTask(Task):
    def __init__(self, build_name: str, build_dir: str):
        super().__init__(build_name, build_dir, os.path.join(build_dir, 'build.sh'))
        self.pre_script = os.path.join(build_dir, 'pre_build.sh') if os.path.exists(os.path.join(build_dir, 'pre_build.sh')) else None
        self.post_script = os.path.join(build_dir, 'post_build.sh') if os.path.exists(os.path.join(build_dir, 'post_build.sh')) else None
        self.build_conf = None

    def execute(self, executor) -> bool:
        self.start_time = time.time()
        if isinstance(executor, LsfStrategy):
            job_id = executor.run_script(self.script_path, self.work_dir, self.name)
            self.job_id = job_id
            return True
        else:
            if self.pre_script:
                if not executor.run_script(self.pre_script, self.work_dir, f"{self.name}_pre"):
                    self.status = 'fail'
                    self.elapsed = time.time() - self.start_time
                    return False
            if not executor.run_script(self.script_path, self.work_dir, self.name):
                self.status = 'fail'
                self.elapsed = time.time() - self.start_time
                return False
            if self.post_script:
                if not executor.run_script(self.post_script, self.work_dir, f"{self.name}_post"):
                    self.status = 'fail'
                    self.elapsed = time.time() - self.start_time
                    return False
            self.status = 'pass'
            self.elapsed = time.time() - self.start_time
            return True

class TestTask(Task):
    def __init__(self, test_name: str, test_dir: str, build_name: str):
        super().__init__(test_name, test_dir, os.path.join(test_dir, 'sim.sh'))
        self.build_name = build_name
        self.pre_script = os.path.join(test_dir, 'pre_sim.sh') if os.path.exists(os.path.join(test_dir, 'pre_sim.sh')) else None
        self.post_script = os.path.join(test_dir, 'post_sim.sh') if os.path.exists(os.path.join(test_dir, 'post_sim.sh')) else None

    def execute(self, executor) -> bool:
        self.start_time = time.time()
        if isinstance(executor, LsfStrategy):
            job_id = executor.run_script(self.script_path, self.work_dir, self.name)
            self.job_id = job_id
            return True
        else:
            if self.pre_script:
                if not executor.run_script(self.pre_script, self.work_dir, f"{self.name}_pre"):
                    self.status = 'fail'
                    self.elapsed = time.time() - self.start_time
                    return False
            if not executor.run_script(self.script_path, self.work_dir, self.name):
                self.status = 'fail'
                self.elapsed = time.time() - self.start_time
                return False
            if self.post_script:
                if not executor.run_script(self.post_script, self.work_dir, f"{self.name}_post"):
                    self.status = 'fail'
                    self.elapsed = time.time() - self.start_time
                    return False
            # ── 判定不以退出码为准：vsim 'quit -f' 即使 UVM_FATAL 也返回 0 ──
            # INVTST（test not found）等致命错会漏判成 pass，必须解析 sim.log 的 UVM 汇总。
            self.status = 'fail' if self._uvm_failed() else 'pass'
            self.elapsed = time.time() - self.start_time
            return True

    def _uvm_failed(self) -> bool:
        """解析 sim.log：UVM_ERROR/UVM_FATAL 计数 > 0 或 Questa ** Error 即判失败。"""
        import re
        log = os.path.join(self.work_dir, 'sim.log')
        if not os.path.exists(log):
            return False
        try:
            with open(log, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
        except Exception:
            return False
        # UVM 汇总: "# UVM_ERROR :    N" / "# UVM_FATAL :    N"
        for m in re.finditer(r'UVM_(?:ERROR|FATAL)\s*:\s*(\d+)', content):
            if int(m.group(1)) > 0:
                return True
        # Questa 硬错误（vopt/vlog 等）
        if re.search(r'\*\*\s*Error', content):
            return True
        return False

class TaskFactory:
    """任务工厂 - 根据扫描到的目录结构创建 Build/Test 任务"""

    @staticmethod
    def create_build_task(build_name: str, build_path: str) -> BuildTask:
        """根据 build 目录创建 BuildTask"""
        return BuildTask(build_name, build_path)

    @staticmethod
    def create_test_task(test_name: str, test_path: str, build_name: str) -> TestTask:
        """根据 test 目录创建 TestTask"""
        return TestTask(test_name, test_path, build_name)


# 避免循环导入
from ..execution.strategy import LsfStrategy