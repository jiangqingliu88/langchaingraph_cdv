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

# 判定一条 case 失败的日志关键字。抽成常量是为了让「脚本里导出的
# `EMAN_ERROR_PATTERN`」和「调度器实际判定用的模式」是同一份 —— 之前这两处
# 各写各的（关键字散在 `_parse_task_result` 里），迟早漂移。
ERROR_PATTERN = r'ERROR|FATAL|UVM_ERROR|FAILED'


def _failed_builds(tasks) -> Set[str]:
    return {t.name for t in tasks if t.status == 'fail'}


def _run_test_task(task, failed_builds, strategy) -> None:
    """执行 test；若依赖 build 失败则标记失败并**不执行**。"""
    if task.build_name in failed_builds:
        task.status = 'fail'
        logger.warning(
            f"跳过 {task.name}: 依赖的 build {task.build_name} 编译失败"
            f"（不允许用旧 work library 跑出假结果）")
        return
    task.execute(strategy)


class Scheduler:
    def __init__(self, strategy, build_only=False, test_only=False,
                 parallel_builds=1, state_file=None, dry_run=False,
                 performance_threshold=0.2, lsf_report_interval=60,
                 lsf_max_jobs=0):
        self.strategy = strategy
        self.build_only = build_only
        self.test_only = test_only
        self.parallel_builds = parallel_builds
        self.state_file = state_file
        self.dry_run = dry_run
        self.performance_threshold = performance_threshold
        # LSF 专用：轮询间隔（秒）与同时在飞的最大作业数（0 = 不限）。
        # 只在 LsfStrategy 下有意义；local/mock 路径完全不看这两个值。
        self.lsf_report_interval = lsf_report_interval or 60
        self.lsf_max_jobs = lsf_max_jobs or 0
        self.tasks = []
        self.task_map = {}
        self.completed = set()
        # 已解析过结果的 LSF job id：分批提交时同一批只会被收一次，收尾那次
        # 「收全体」也不会把前面批次重复计一遍（job_id 保留给报告用，不置空）。
        self.collected_job_ids = set()
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
        """返回**依赖在前**的拓扑序：每个 node 都排在它依赖的 node 之后。

        graph[node] = node 依赖的节点列表。Kahn：入度 = 这个 node 还有几个依赖
        没排完；依赖排完（入度归零）才轮到它。
        """
        in_degree = {k: len(v) for k, v in graph.items()}
        queue = deque(k for k, v in in_degree.items() if v == 0)
        result = []
        while queue:
            node = queue.popleft()
            result.append(node)
            # 谁依赖 node，谁的入度就减一
            for dependent, deps in graph.items():
                if node in deps:
                    in_degree[dependent] -= 1
                    if in_degree[dependent] == 0:
                        queue.append(dependent)
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
            # 有 build 依赖时串行：`order` 已是依赖在前的拓扑序，但并行提交不会
            # 等待依赖跑完，`depends` 就白声明了。串行是这里能给出的确定性保证。
            has_build_deps = any(getattr(t, 'depends_on', None) for t in build_tasks)
            parallel = 1 if has_build_deps else self._get_dynamic_parallelism()
            if has_build_deps and self.parallel_builds > 1:
                logger.info("检测到 build 依赖，编译阶段串行执行以保证依赖顺序")
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
            # **编译失败的 build，其 test 一律不跑。**
            #
            # 不跳过会非常危险：`vlog` 失败时上一次成功的 work library 可能还在，
            # `vsim work.tb` 照样能起 —— 于是用**旧库**跑出一份看似正常的
            # pass/fail。实测 SoC 例子：枚举越界导致 vlog 报错，但回归只用旧库
            # 跑了 1.4us，TB 读到全 X，报告成"测试失败"而不是"编译失败"。
            failed_builds = _failed_builds(build_tasks)
            logger.info(f"Running {len(test_tasks)} tests")
            pbar_test = tqdm(total=len(test_tasks), desc="Testing", unit="test", leave=True)
            test_stats = {'pass': 0, 'fail': 0, 'unknown': 0}

            # LSF 限流：`--lsf-max-jobs N` 时按 N 个一批「提交 → 等完 → 再提交」，
            # 避免一口气把整个回归塞进队列（会挤爆共享集群，也会让 bjobs 轮询变成
            # 几千行的噪声）。0 / 非 LSF 都走原来的「全提交、最后统一收」。
            batch_size = self.lsf_max_jobs if isinstance(self.strategy, LsfStrategy) else 0
            batch = []

            for name in order:
                task = self.task_map.get(name)
                if not task or isinstance(task, BuildTask):
                    continue
                if self.test_only and not isinstance(task, TestTask):
                    continue

                _run_test_task(task, failed_builds, self.strategy)
                if not isinstance(self.strategy, LsfStrategy):
                    test_stats[task.status] += 1
                    pbar_test.set_postfix(test_stats)
                    pbar_test.update(1)
                else:
                    batch.append(task)
                self.completed.add(task.name)
                self._save_state(root_dir)

                if batch_size and len(batch) >= batch_size:
                    self._collect_lsf_results(root_dir, only_tasks=batch)
                    batch = []

            if isinstance(self.strategy, LsfStrategy):
                pbar_test.close()
                # 收尾：先收掉最后不足一批的尾巴，再兜一次全体（build 阶段的作业
                # 如果前面没收过，也在这里落定）。
                if batch:
                    self._collect_lsf_results(root_dir, only_tasks=batch)
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

    def _collect_lsf_results(self, root_dir, poll_interval=None, timeout=3600,
                             task_type='all', only_tasks=None):
        logger.info("[LSF] Waiting for all jobs to finish...")
        poll_interval = poll_interval or self.lsf_report_interval
        # `only_tasks` 给「分批提交」用：只等这一批的作业，而不是 self.tasks 全体
        # （全体里混着还没提交、job_id 为 None 的任务，也混着上一批已收完的）。
        pending = self.tasks if only_tasks is None else only_tasks
        job_tasks = {task.job_id: task for task in pending
                     if task.job_id is not None and task.job_id not in self.collected_job_ids}
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
                                self.collected_job_ids.add(jid)
                                stats[task.status] += 1
                                pbar.set_postfix(stats)
                                pbar.update(1)
                                del job_tasks[jid]
                for jid in list(job_tasks.keys()):
                    if jid not in active_jids:
                        task = job_tasks[jid]
                        self._parse_task_result(task)
                        self.collected_job_ids.add(jid)
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
                    for jid, task in job_tasks.items():
                        task.status = 'unknown'
                        self.collected_job_ids.add(jid)
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
                if re.search(ERROR_PATTERN, content):
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

        # 解析波形路径 —— **不看成败**：通过用例的波形同样要能点开看
        # （只为失败的用例记波形，等于"跑挂了才有波形"，而回看通过用例的
        #  波形恰恰是很常见的动作）。
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

        # `EMAN_BASE_STATUS` / `EMAN_CUSTOM_STATUS` 是**产出**不是输入：脚本跑的时候
        # 还不知道结果，所以生成脚本时不给值；判完在这里落盘，供下游（post 处理、
        # 报告、CI 脚本）读走。现在没有自定义规则，custom 就等于 base。
        for task in self.tasks:
            try:
                status_file = os.path.join(task.work_dir, 'status.env')
                with open(status_file, 'w', encoding='utf-8') as f:
                    f.write(f"EMAN_BASE_STATUS={task.status}\n")
                    f.write(f"EMAN_CUSTOM_STATUS={task.status}\n")
                    # build 任务没有 TESTCASE 这个概念，写它自己的名字
                    if isinstance(task, TestTask):
                        f.write(f"EMAN_TESTCASE={task.name}\n")
                    else:
                        f.write(f"EMAN_BUILD_NAME={task.name}\n")
            except OSError as e:
                logger.warning(f"status.env 写入失败 {task.work_dir}: {e}")

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