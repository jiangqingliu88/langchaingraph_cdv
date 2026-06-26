# src/regression_framework/models/scheduler.py
import os
import sys
import json
import time
import re
import hashlib
import subprocess
import sqlite3
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Set

from tqdm import tqdm

from ..core.logging_config import get_logger
from ..core.exceptions import ExecutionError
from .task import BuildTask, TestTask, Task
from ..execution.strategy import LsfStrategy, LocalStrategy, MockStrategy
from ..reporters.trend_db import TrendDatabase

logger = get_logger(__name__)

class Scheduler:
    def __init__(self, strategy, build_only=False, test_only=False,
                 parallel_builds=1, state_file=None, dry_run=False,
                 performance_threshold=0.2):
        self.strategy = strategy
        self.build_only = build_only
        self.test_only = test_only
        self.parallel_builds = parallel_builds
        self.state_file = state_file
        self.dry_run = dry_run
        self.performance_threshold = performance_threshold
        self.tasks = []
        self.task_map = {}
        self.completed = set()
        self.cache_dir = ".build_cache"
        self.start_time = None
        self.total_elapsed = 0.0
        self.total_elapsed_str = "N/A"

        if state_file and os.path.exists(state_file):
            with open(state_file, 'r') as f:
                self.completed = set(json.load(f).get('completed', []))

    def add_task(self, task: Task):
        self.tasks.append(task)
        self.task_map[task.name] = task

    def _build_dependency_graph(self):
        graph = {task.name: [] for task in self.tasks}
        for task in self.tasks:
            if hasattr(task, 'depends_on'):
                for dep in task.depends_on:
                    if dep in graph:
                        graph[task.name].append(dep)
        return graph

    def _topological_sort(self, graph):
        in_degree = {k: 0 for k in graph}
        for deps in graph.values():
            for d in deps:
                if d in in_degree:
                    in_degree[d] += 1
        queue = [k for k, v in in_degree.items() if v == 0]
        result = []
        while queue:
            node = queue.pop(0)
            result.append(node)
            for dep in graph.get(node, []):
                in_degree[dep] -= 1
                if in_degree[dep] == 0:
                    queue.append(dep)
        if len(result) != len(graph):
            raise ExecutionError("Circular dependency detected!")
        return result

    def _get_cache_key(self, build_name, build_conf):
        import json
        import hashlib
        data = {
            'name': build_name,
            'compile_opts': build_conf.get('compile_opts', []),
            'files': build_conf.get('files', []),
            'local_vars': build_conf.get('local_vars', {})
        }
        return hashlib.md5(json.dumps(data, sort_keys=True).encode()).hexdigest()

    def _restore_cache(self, build_name, cache_key, build_dir):
        cache_path = os.path.join(self.cache_dir, cache_key)
        if os.path.exists(cache_path):
            import shutil
            if os.path.exists(build_dir):
                shutil.rmtree(build_dir)
            shutil.copytree(cache_path, build_dir)
            logger.info(f"Restored build cache for {build_name}")
            return True
        return False

    def _save_cache(self, build_name, cache_key, build_dir):
        if not self.cache_dir:
            return
        os.makedirs(self.cache_dir, exist_ok=True)
        cache_path = os.path.join(self.cache_dir, cache_key)
        import shutil
        if os.path.exists(cache_path):
            shutil.rmtree(cache_path)
        shutil.copytree(build_dir, cache_path, ignore_dangling_symlinks=True)
        logger.info(f"Saved build cache for {build_name} ({cache_key})")

    def _get_dynamic_parallelism(self):
        if not isinstance(self.strategy, LsfStrategy):
            return self.parallel_builds
        try:
            output = subprocess.check_output("bqueues -o 'njobs'", shell=True, text=True)
            lines = output.strip().splitlines()
            total_jobs = 0
            for line in lines[1:]:
                if line.strip():
                    total_jobs += int(line.split()[0])
            if total_jobs > 1000:
                return max(1, self.parallel_builds // 2)
            elif total_jobs < 100:
                return min(8, self.parallel_builds * 2)
            return self.parallel_builds
        except:
            return self.parallel_builds

    def _save_state(self, root_dir):
        if self.state_file:
            with open(self.state_file, 'w') as f:
                json.dump({'completed': list(self.completed)}, f)

    def run(self, root_dir):
        self.start_time = time.time()
        logger.info(f"Regression started at {time.strftime('%Y-%m-%d %H:%M:%S')}")

        graph = self._build_dependency_graph()
        order = self._topological_sort(graph)
        order = [name for name in order if name not in self.completed]

        if self.dry_run:
            logger.info(f"[DRY-RUN] Would run {len(order)} tasks")
            for name in order:
                task = self.task_map[name]
                logger.info(f"  {name} ({task.work_dir})")
            return

        logger.info(f"[Scheduler] Running {len(order)} tasks (skipping {len(self.completed)} completed)")

        build_tasks = [self.task_map[name] for name in order if isinstance(self.task_map[name], BuildTask)]
        test_tasks = [self.task_map[name] for name in order if isinstance(self.task_map[name], TestTask)]

        stats = {'pass': 0, 'fail': 0, 'unknown': 0}

        # ---- Build 阶段 ----
        if build_tasks and not self.test_only:
            parallel = self._get_dynamic_parallelism()
            logger.info(f"Building {len(build_tasks)} builds with parallelism {parallel}")

            pbar_build = tqdm(total=len(build_tasks), desc="Building", unit="build", leave=True)
            build_stats = {'pass': 0, 'fail': 0, 'unknown': 0}

            with ThreadPoolExecutor(max_workers=parallel) as executor:
                futures = {}
                for task in build_tasks:
                    if hasattr(task, 'build_conf') and task.build_conf:
                        cache_key = self._get_cache_key(task.name, task.build_conf)
                        if self._restore_cache(task.name, cache_key, task.work_dir):
                            task.status = 'pass'
                            self.completed.add(task.name)
                            self._save_state(root_dir)
                            pbar_build.update(1)
                            continue
                    future = executor.submit(task.execute, self.strategy)
                    futures[future] = task

                for future in as_completed(futures):
                    task = futures[future]
                    try:
                        success = future.result()
                        if not isinstance(self.strategy, LsfStrategy):
                            build_stats[task.status] += 1
                        else:
                            # LSF模式下，状态在收集时确定
                            pass
                        if success and hasattr(task, 'build_conf') and task.build_conf:
                            cache_key = self._get_cache_key(task.name, task.build_conf)
                            self._save_cache(task.name, cache_key, task.work_dir)
                        self.completed.add(task.name)
                        self._save_state(root_dir)
                        if not isinstance(self.strategy, LsfStrategy):
                            pbar_build.set_postfix(build_stats)
                            pbar_build.update(1)
                    except Exception as e:
                        logger.error(f"Build {task.name} raised exception: {e}")
                        self.completed.add(task.name)
                        self._save_state(root_dir)
                        if not isinstance(self.strategy, LsfStrategy):
                            build_stats['fail'] += 1
                            pbar_build.set_postfix(build_stats)
                            pbar_build.update(1)

            pbar_build.close()

            if isinstance(self.strategy, LsfStrategy):
                self._collect_lsf_results(root_dir, task_type='build')

            if self.build_only:
                self._collect_lsf_results(root_dir) if isinstance(self.strategy, LsfStrategy) else None
                self._generate_report(root_dir)
                self.total_elapsed = time.time() - self.start_time
                self._format_total_time()
                logger.info(f"Regression finished. Total time: {self.total_elapsed_str}")
                return

        # ---- Test 阶段 ----
        if test_tasks and not self.build_only:
            logger.info(f"Running {len(test_tasks)} tests")
            pbar_test = tqdm(total=len(test_tasks), desc="Testing", unit="test", leave=True)
            test_stats = {'pass': 0, 'fail': 0, 'unknown': 0}

            for name in order:
                task = self.task_map.get(name)
                if not task or isinstance(task, BuildTask):
                    continue
                if self.test_only and not isinstance(task, TestTask):
                    continue

                task.execute(self.strategy)
                if not isinstance(self.strategy, LsfStrategy):
                    test_stats[task.status] += 1
                    pbar_test.set_postfix(test_stats)
                    pbar_test.update(1)
                self.completed.add(task.name)
                self._save_state(root_dir)

            if isinstance(self.strategy, LsfStrategy):
                pbar_test.close()
                self._collect_lsf_results(root_dir)
            else:
                pbar_test.close()

        # ---- 收集 LSF 结果（如果尚未收集） ----
        if isinstance(self.strategy, LsfStrategy):
            self._collect_lsf_results(root_dir)

        # ---- 性能检测 ----
        self._check_performance_degradation()

        # ---- 生成报告 ----
        self._generate_report(root_dir)

        self.total_elapsed = time.time() - self.start_time
        self._format_total_time()
        logger.info(f"Regression finished. Total time: {self.total_elapsed_str}")

    def _format_total_time(self):
        hours, rem = divmod(self.total_elapsed, 3600)
        minutes, seconds = divmod(rem, 60)
        self.total_elapsed_str = f"{int(hours):02d}:{int(minutes):02d}:{int(seconds):02d}"

    def _check_performance_degradation(self):
        """检测每个任务的仿真耗时是否相比历史平均值有显著增长"""
        db_path = TrendDatabase().db_path
        if not os.path.exists(db_path):
            return

        try:
            conn = sqlite3.connect(db_path)
            c = conn.cursor()
            for task in self.tasks:
                if task.sim_time <= 0:
                    continue
                # 查询该任务最近10次成功的平均耗时
                c.execute('''SELECT AVG(sim_time) FROM task_details
                             WHERE task_name=? AND status='pass' AND sim_time > 0
                             ORDER BY run_id DESC LIMIT 10''', (task.name,))
                row = c.fetchone()
                if row and row[0] is not None and row[0] > 0:
                    avg_time = row[0]
                    if task.sim_time > avg_time * (1 + self.performance_threshold):
                        task.performance_degraded = True
                        logger.warning(f"Performance degradation detected for {task.name}: "
                                       f"current={task.sim_time:.2f}s, avg={avg_time:.2f}s")
            conn.close()
        except Exception as e:
            logger.warning(f"Performance check failed: {e}")

    def _collect_lsf_results(self, root_dir, poll_interval=10, timeout=3600, task_type='all'):
        logger.info("[LSF] Waiting for all jobs to finish...")
        job_tasks = {task.job_id: task for task in self.tasks if task.job_id is not None}
        if not job_tasks:
            logger.info("No LSF jobs to wait for.")
            return

        pbar = tqdm(total=len(job_tasks), desc="LSF Collecting", unit="job", leave=True)
        stats = {'pass': 0, 'fail': 0, 'unknown': 0}

        elapsed = 0
        while job_tasks:
            job_ids_str = ' '.join(str(jid) for jid in job_tasks.keys())
            try:
                output = subprocess.check_output(f"bjobs -o 'id stat' {job_ids_str}", shell=True, text=True)
                lines = output.strip().splitlines()
                active_jids = set()
                for line in lines[1:]:
                    if not line.strip():
                        continue
                    parts = line.split()
                    if len(parts) >= 2:
                        jid = int(parts[0])
                        state = parts[1]
                        active_jids.add(jid)
                        if state in ('DONE', 'EXIT'):
                            task = job_tasks.get(jid)
                            if task:
                                self._parse_task_result(task)
                                stats[task.status] += 1
                                pbar.set_postfix(stats)
                                pbar.update(1)
                                del job_tasks[jid]
                for jid in list(job_tasks.keys()):
                    if jid not in active_jids:
                        task = job_tasks[jid]
                        self._parse_task_result(task)
                        stats[task.status] += 1
                        pbar.set_postfix(stats)
                        pbar.update(1)
                        del job_tasks[jid]
            except subprocess.CalledProcessError:
                pass

            if job_tasks:
                time.sleep(poll_interval)
                elapsed += poll_interval
                if elapsed > timeout:
                    logger.warning("Timeout waiting for jobs, marking remaining as unknown.")
                    for task in job_tasks.values():
                        task.status = 'unknown'
                        stats['unknown'] += 1
                        pbar.set_postfix(stats)
                        pbar.update(1)
                    job_tasks.clear()
        pbar.close()
        logger.info("All LSF jobs collected.")

    def _parse_task_result(self, task):
        """解析任务的仿真结果，提取状态、耗时和波形路径"""
        if task.start_time:
            task.elapsed = time.time() - task.start_time
        else:
            task.elapsed = 0.0

        # 解析状态
        log_file = os.path.join(task.work_dir, 'job.log')
        if os.path.exists(log_file):
            with open(log_file, 'r', encoding='utf-8') as f:
                content = f.read()
                if any(kw in content for kw in ('ERROR', 'FATAL', 'UVM_ERROR', 'FAILED')):
                    task.status = 'fail'
                else:
                    task.status = 'pass'
        else:
            task.status = 'unknown'

        # 解析仿真耗时
        time_log = os.path.join(task.work_dir, 'sim_time.log')
        if os.path.exists(time_log):
            with open(time_log, 'r') as f:
                for line in f:
                    if line.startswith('SIM_TIME='):
                        try:
                            task.sim_time = float(line.strip().split('=')[1])
                        except:
                            task.sim_time = 0.0
        else:
            task.sim_time = 0.0

        # 解析波形路径（仅当失败时）
        if task.status == 'fail':
            wave_log = os.path.join(task.work_dir, 'wave.log')
            if os.path.exists(wave_log):
                with open(wave_log, 'r') as f:
                    for line in f:
                        if line.startswith('WAVE_PATH='):
                            task.wave_path = line.strip().split('=', 1)[1]
                            if task.wave_path == 'NOT_FOUND':
                                task.wave_path = None
            else:
                task.wave_path = None

    def _generate_report(self, root_dir):
        from ..reporters.html import HtmlReporter
        from ..reporters.json import JsonReporter
        from ..reporters.trend_db import TrendDatabase

        # 创建符号链接
        for status in ['pass', 'fail', 'unknown']:
            os.makedirs(os.path.join(root_dir, status), exist_ok=True)

        def _create_link_or_fallback(src, dst):
            if os.name == 'nt':
                try:
                    os.symlink(src, dst, target_is_directory=os.path.isdir(src))
                    return
                except OSError:
                    with open(dst + '.txt', 'w', encoding='utf-8') as f:
                        f.write(f"Target: {src}\n")
                    os.makedirs(dst, exist_ok=True)
                    return
            else:
                os.symlink(src, dst)

        for task in self.tasks:
            src = task.work_dir
            if not os.path.exists(src):
                continue
            status_dir = os.path.join(root_dir, task.status)
            os.makedirs(status_dir, exist_ok=True)
            dst = os.path.join(status_dir, os.path.basename(src))
            if os.path.islink(dst) or os.path.exists(dst):
                if os.path.isdir(dst) and not os.path.islink(dst):
                    import shutil
                    shutil.rmtree(dst, ignore_errors=True)
                else:
                    os.remove(dst)
            _create_link_or_fallback(src, dst)

        # 统计
        stats = {'pass': 0, 'fail': 0, 'unknown': 0}
        for task in self.tasks:
            stats[task.status] += 1

        # 文本报告
        report_path = os.path.join(root_dir, 'report_summary.txt')
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write("Regression Summary\n")
            f.write(f"Total Time: {self.total_elapsed_str}\n")
            f.write(f"Total Tasks: {len(self.tasks)}\n")
            f.write(f"Pass: {stats['pass']}\n")
            f.write(f"Fail: {stats['fail']}\n")
            f.write(f"Unknown: {stats['unknown']}\n")
            f.write("\nDetailed list:\n")
            for task in self.tasks:
                perf_flag = " [PERF]" if getattr(task, 'performance_degraded', False) else ""
                wave_info = f" wave={task.wave_path}" if getattr(task, 'wave_path', None) else ""
                f.write(f"{task.status:8} : {task.name} ({task.work_dir}) [{task.elapsed:.2f}s]{perf_flag}{wave_info}\n")

        # HTML/JSON/Trend
        HtmlReporter().generate(self.tasks, root_dir, total_time=self.total_elapsed_str)
        JsonReporter().generate(self.tasks, root_dir, total_time=self.total_elapsed_str)
        TrendDatabase().save(self.tasks, root_dir)

        logger.info(f"Report generated in {root_dir}")