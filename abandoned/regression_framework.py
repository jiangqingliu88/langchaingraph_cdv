#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
回归框架 - 企业级特性全集（优化版）
移除 matrix 关键字，改用更清晰的 parameters + combinations
"""

import os
import sys
import yaml
import subprocess
import itertools
import argparse
import importlib
import re
import time
import json
import sqlite3
import shutil
from copy import deepcopy
from jinja2 import Template
from datetime import datetime
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Callable, Set
from dataclasses import dataclass, field
from pathlib import Path

# ============================================================
# 数据类定义
# ============================================================

@dataclass
class Config:
    global_vars: Dict[str, Any] = field(default_factory=dict)
    settings: Dict[str, Any] = field(default_factory=dict)
    builds: List[Dict[str, Any]] = field(default_factory=list)
    tests: List[Dict[str, Any]] = field(default_factory=list)
    resource_pools: List[Dict[str, Any]] = field(default_factory=list)
    notifications: Dict[str, Any] = field(default_factory=dict)

# ============================================================
# 配置构建器（无 matrix，使用 parameters + combinations）
# ============================================================

class ConfigBuilder:
    def __init__(self, yaml_file: str):
        self.yaml_file = yaml_file
        self.context = {}
        self.config = Config()
        self.plugin_dir = "plugins"

    def load_yaml_with_includes(self, filepath: str, base_dir: str = None) -> dict:
        if base_dir is None:
            base_dir = os.path.dirname(filepath) or '.'
        with open(filepath, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        if 'includes' in data:
            for inc in data['includes']:
                inc_path = os.path.join(base_dir, inc)
                if not os.path.exists(inc_path):
                    print(f"Warning: include file '{inc_path}' not found, skipping.")
                    continue
                inc_data = self.load_yaml_with_includes(inc_path, base_dir)
                data = self._merge_config(inc_data, data)
        return data

    def _merge_config(self, base: dict, override: dict) -> dict:
        if not isinstance(base, dict) or not isinstance(override, dict):
            return deepcopy(override)
        result = deepcopy(base)
        for key, val in override.items():
            if key in result:
                if isinstance(result[key], dict) and isinstance(val, dict):
                    result[key] = self._merge_config(result[key], val)
                elif key == 'tests' and isinstance(result[key], list) and isinstance(val, list):
                    result[key] = result[key] + val
                elif key == 'builds' and isinstance(result[key], list) and isinstance(val, list):
                    existing_names = {b['name'] for b in result[key]}
                    for b in val:
                        if b['name'] in existing_names:
                            for idx, old in enumerate(result[key]):
                                if old['name'] == b['name']:
                                    result[key][idx] = self._merge_config(old, b)
                                    break
                        else:
                            result[key].append(b)
                else:
                    result[key] = deepcopy(val)
            else:
                result[key] = deepcopy(val)
        return result

    def substitute_vars(self, obj, context: dict):
        if isinstance(obj, str):
            return Template(obj).render(**context)
        elif isinstance(obj, list):
            return [self.substitute_vars(item, context) for item in obj]
        elif isinstance(obj, dict):
            return {k: self.substitute_vars(v, context) for k, v in obj.items()}
        else:
            return obj

    def expand_combinations(self, tests: list) -> list:
        """
        展开参数组合（替代 matrix）
        每个 test 可定义 parameters 字典，框架自动生成所有组合。
        示例：
          parameters:
            MODE: [ADD, SUB]
            WIDTH: [8, 16]
          将生成 2*2=4 个实例。
        """
        expanded = []
        for test in tests:
            params = test.pop('parameters', None)
            if not params:
                expanded.append(test)
                continue
            # 兼容旧格式：如果 parameters 是列表，合并为字典
            if isinstance(params, list):
                merged = {}
                for item in params:
                    if isinstance(item, dict):
                        for k, v in item.items():
                            merged.setdefault(k, []).extend(v) if k in merged else merged.update({k: v})
                params = merged
            # 展开笛卡尔积
            keys = list(params.keys())
            values = [params[k] for k in keys]
            for combo in itertools.product(*values):
                new_test = deepcopy(test)
                param_dict = dict(zip(keys, combo))
                # 生成名称
                name_suffix = '_'.join([f"{k}_{v}" for k, v in zip(keys, combo)])
                new_test['name'] = f"{test['name']}_{name_suffix}"
                if 'local_vars' not in new_test:
                    new_test['local_vars'] = {}
                for k, v in param_dict.items():
                    new_test['local_vars'][k] = v
                expanded.append(new_test)
        return expanded

    def expand_count(self, tests: list, default_count: int) -> list:
        expanded = []
        for test in tests:
            count = test.pop('count', default_count)
            base_seed = test.get('local_vars', {}).get('SEED', None)
            for i in range(1, count + 1):
                new_test = deepcopy(test)
                if count > 1:
                    new_test['name'] = f"{test['name']}_run_{i}"
                    if base_seed is not None:
                        if 'local_vars' not in new_test:
                            new_test['local_vars'] = {}
                        new_test['local_vars']['SEED'] = base_seed + i - 1
                expanded.append(new_test)
        return expanded

    def filter_by_git_changes(self, tests: list, repo_path: str = '.') -> list:
        if not os.path.isdir(os.path.join(repo_path, '.git')):
            return tests
        try:
            output = subprocess.check_output(
                ["git", "-C", repo_path, "diff", "--name-only", "HEAD~1"],
                text=True
            )
            changed_files = set(output.strip().splitlines())
            if not changed_files:
                return tests
            filtered = []
            for test in tests:
                patterns = test.get('file_pattern', [])
                if not patterns:
                    filtered.append(test)
                else:
                    import fnmatch
                    for cf in changed_files:
                        for pattern in patterns:
                            if fnmatch.fnmatch(cf, pattern):
                                filtered.append(test)
                                break
                        else:
                            continue
                        break
            return filtered
        except Exception as e:
            print(f"Git filtering failed: {e}, running all tests.")
            return tests

    def build(self, incremental=False, repo_path='.'):
        raw = self.load_yaml_with_includes(self.yaml_file)
        raw = self._resolve_extends(raw)
        global_vars = raw.get('global_vars', {})
        self.context = global_vars.copy()
        self.context.update(os.environ)

        substituted = self.substitute_vars(raw, self.context)

        settings = substituted.get('settings', {})
        default_count = settings.get('default_count', 1)
        tests = substituted.get('tests', [])
        tests = self.expand_combinations(tests)   # 替代 expand_matrix
        tests = self.expand_count(tests, default_count)

        if incremental:
            tests = self.filter_by_git_changes(tests, repo_path)

        substituted['tests'] = tests

        self.config.global_vars = substituted.get('global_vars', {})
        self.config.settings = substituted.get('settings', {})
        self.config.builds = substituted.get('builds', [])
        self.config.tests = tests
        self.config.resource_pools = substituted.get('resource_pools', [])
        self.config.notifications = substituted.get('notifications', {})
        return self.config

    def _resolve_extends(self, data: dict) -> dict:
        if 'extends' in data:
            base_path = data.pop('extends')
            base_dir = os.path.dirname(self.yaml_file) or '.'
            base_full = os.path.join(base_dir, base_path)
            if not os.path.exists(base_full):
                print(f"Warning: base config '{base_full}' not found, skipping extends.")
                return data
            base_data = self.load_yaml_with_includes(base_full, base_dir)
            merged = self._merge_config(base_data, data)
            return merged
        return data

# ============================================================
# 任务抽象 (Command 模式)
# ============================================================

class Task(ABC):
    def __init__(self, name: str, work_dir: str, script_path: str):
        self.name = name
        self.work_dir = work_dir
        self.script_path = script_path
        self.depends_on = []
        self.status = 'unknown'
        self.job_id = None  # For LSF
        self.fingerprint = 'unknown'

    @abstractmethod
    def execute(self, executor) -> bool:
        pass

class BuildTask(Task):
    def __init__(self, build_name: str, build_dir: str):
        super().__init__(build_name, build_dir, os.path.join(build_dir, 'build.sh'))
        self.pre_script = os.path.join(build_dir, 'pre_build.sh') if os.path.exists(os.path.join(build_dir, 'pre_build.sh')) else None
        self.post_script = os.path.join(build_dir, 'post_build.sh') if os.path.exists(os.path.join(build_dir, 'post_build.sh')) else None

    def execute(self, executor) -> bool:
        if isinstance(executor, LsfStrategy):
            job_id = executor.run_script(self.script_path, self.work_dir, self.name)
            self.job_id = job_id
            return True
        else:
            if self.pre_script:
                if not executor.run_script(self.pre_script, self.work_dir, f"{self.name}_pre"):
                    self.status = 'fail'
                    return False
            if not executor.run_script(self.script_path, self.work_dir, self.name):
                self.status = 'fail'
                return False
            if self.post_script:
                if not executor.run_script(self.post_script, self.work_dir, f"{self.name}_post"):
                    self.status = 'fail'
                    return False
            self.status = 'pass'
            return True

class TestTask(Task):
    def __init__(self, test_name: str, test_dir: str, build_name: str):
        super().__init__(test_name, test_dir, os.path.join(test_dir, 'sim.sh'))
        self.build_name = build_name
        self.pre_script = os.path.join(test_dir, 'pre_sim.sh') if os.path.exists(os.path.join(test_dir, 'pre_sim.sh')) else None
        self.post_script = os.path.join(test_dir, 'post_sim.sh') if os.path.exists(os.path.join(test_dir, 'post_sim.sh')) else None

    def execute(self, executor) -> bool:
        if isinstance(executor, LsfStrategy):
            job_id = executor.run_script(self.script_path, self.work_dir, self.name)
            self.job_id = job_id
            return True
        else:
            if self.pre_script:
                if not executor.run_script(self.pre_script, self.work_dir, f"{self.name}_pre"):
                    self.status = 'fail'
                    return False
            if not executor.run_script(self.script_path, self.work_dir, self.name):
                self.status = 'fail'
                return False
            if self.post_script:
                if not executor.run_script(self.post_script, self.work_dir, f"{self.name}_post"):
                    self.status = 'fail'
                    return False
            self.status = 'pass'
            return True

class TaskFactory:
    @staticmethod
    def create_build_task(build_name, build_dir):
        return BuildTask(build_name, build_dir)

    @staticmethod
    def create_test_task(test_name, test_dir, build_name):
        return TestTask(test_name, test_dir, build_name)

# ============================================================
# 执行策略 (Strategy 模式)
# ============================================================

class ExecutionStrategy(ABC):
    @abstractmethod
    def run_script(self, script_path: str, cwd: str, job_name: str = None, timeout: int = None, retry: int = 0):
        """返回：对于LSF返回作业ID，对于local/mock返回布尔值"""
        pass

class MockStrategy(ExecutionStrategy):
    def run_script(self, script_path, cwd, job_name=None, timeout=None, retry=0):
        print(f"[MOCK] Would execute {script_path} in {cwd}")
        return True

class LocalStrategy(ExecutionStrategy):
    def run_script(self, script_path, cwd, job_name=None, timeout=None, retry=0):
        if not os.path.exists(script_path):
            print(f"  [SKIP] {script_path} not found")
            return True
        print(f"  [LOCAL] Executing {script_path} in {cwd}")
        try:
            subprocess.run([script_path], cwd=cwd, check=True, shell=False)
            return True
        except subprocess.CalledProcessError as e:
            print(f"  [ERROR] {script_path} failed with exit code {e.returncode}")
            return False

class LsfStrategy(ExecutionStrategy):
    def __init__(self, queue='normal', project=None, resource='rusage[mem=4096]'):
        self.queue = queue
        self.project = project
        self.resource = resource

    def run_script(self, script_path, cwd, job_name=None, timeout=None, retry=0):
        if not os.path.exists(script_path):
            print(f"  [SKIP] {script_path} not found")
            return None
        if job_name is None:
            job_name = os.path.basename(os.path.dirname(script_path)) + '_' + os.path.basename(script_path).replace('.sh', '')
        cmd = f"bsub -J \"{job_name}\" -q {self.queue}"
        if self.project:
            cmd += f" -P {self.project}"
        if self.resource:
            cmd += f" -R \"{self.resource}\""
        if timeout:
            cmd += f" -W {timeout}"
        log_file = os.path.join(cwd, 'job.log')
        cmd += f" -o {log_file} -e {log_file}"
        cmd += f" 'cd {cwd} && ./{os.path.basename(script_path)}'"
        print(f"  [LSF] Submitting: {cmd}")
        try:
            output = subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT, text=True)
            m = re.search(r'Job <(\d+)>', output)
            if m:
                job_id = int(m.group(1))
                print(f"  [LSF] Submitted job {job_id}")
                return job_id
            else:
                print(f"  [LSF] Warning: Could not parse job ID from output: {output}")
                return None
        except subprocess.CalledProcessError as e:
            print(f"  [ERROR] LSF submission failed: {e.output}")
            return None

# ============================================================
# 调度器 (Scheduler) - 核心调度逻辑
# ============================================================

class Scheduler:
    def __init__(self, strategy: ExecutionStrategy, build_only=False, test_only=False,
                 parallel_builds=1, state_file=None):
        self.strategy = strategy
        self.build_only = build_only
        self.test_only = test_only
        self.parallel_builds = parallel_builds
        self.state_file = state_file
        self.tasks = []
        self.task_map = {}
        self.completed = set()

        if state_file and os.path.exists(state_file):
            with open(state_file, 'r', encoding='utf-8') as f:
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
            print("Error: Circular dependency detected!")
            sys.exit(1)
        return result

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
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump({'completed': list(self.completed)}, f)
# ============================================================
# 调度器继续 (LSF结果收集、报告生成)
# ============================================================

    def run(self, root_dir):
        graph = self._build_dependency_graph()
        order = self._topological_sort(graph)
        order = [name for name in order if name not in self.completed]

        print(f"[Scheduler] Running {len(order)} tasks (skipping {len(self.completed)} completed)")

        build_tasks = [self.task_map[name] for name in order if isinstance(self.task_map[name], BuildTask)]
        test_tasks = [self.task_map[name] for name in order if isinstance(self.task_map[name], TestTask)]

        if build_tasks and not self.test_only:
            parallel = self._get_dynamic_parallelism()
            print(f"[Scheduler] Building {len(build_tasks)} builds with parallelism {parallel}")
            from concurrent.futures import ThreadPoolExecutor, as_completed
            with ThreadPoolExecutor(max_workers=parallel) as executor:
                futures = {executor.submit(task.execute, self.strategy): task for task in build_tasks}
                for future in as_completed(futures):
                    task = futures[future]
                    try:
                        success = future.result()
                        if not success and not isinstance(self.strategy, LsfStrategy):
                            print(f"[ERROR] Build {task.name} failed.")
                        self.completed.add(task.name)
                        self._save_state(root_dir)
                    except Exception as e:
                        print(f"[ERROR] Build {task.name} raised exception: {e}")
            if self.build_only:
                self._generate_report(root_dir)
                return

        for name in order:
            task = self.task_map.get(name)
            if not task or isinstance(task, BuildTask):
                continue
            if self.test_only and not isinstance(task, TestTask):
                continue
            print(f"\n[Task] {task.name}")
            success = task.execute(self.strategy)
            if not success and not isinstance(self.strategy, LsfStrategy):
                print(f"[ERROR] Task {task.name} failed.")
            self.completed.add(task.name)
            self._save_state(root_dir)

        if isinstance(self.strategy, LsfStrategy):
            self._collect_lsf_results(root_dir)

        self._generate_report(root_dir)

    def _collect_lsf_results(self, root_dir, poll_interval=10, timeout=3600):
        print("[LSF] Waiting for all jobs to finish...")
        job_tasks = {task.job_id: task for task in self.tasks if task.job_id is not None}
        if not job_tasks:
            print("[LSF] No jobs to wait for.")
            return

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
                                log_file = os.path.join(task.work_dir, 'job.log')
                                task.fingerprint = self._extract_error_fingerprint(log_file)
                                if os.path.exists(log_file):
                                    with open(log_file, 'r', encoding='utf-8') as f:
                                        content = f.read()
                                        if any(kw in content for kw in ('ERROR', 'FATAL', 'UVM_ERROR', 'FAILED')):
                                            task.status = 'fail'
                                        else:
                                            task.status = 'pass'
                                else:
                                    task.status = 'unknown'
                                del job_tasks[jid]
                for jid in list(job_tasks.keys()):
                    if jid not in active_jids:
                        task = job_tasks[jid]
                        log_file = os.path.join(task.work_dir, 'job.log')
                        task.fingerprint = self._extract_error_fingerprint(log_file)
                        if os.path.exists(log_file):
                            with open(log_file, 'r', encoding='utf-8') as f:
                                content = f.read()
                                if any(kw in content for kw in ('ERROR', 'FATAL', 'UVM_ERROR', 'FAILED')):
                                    task.status = 'fail'
                                else:
                                    task.status = 'pass'
                        else:
                            task.status = 'unknown'
                        del job_tasks[jid]
            except subprocess.CalledProcessError:
                pass

            if job_tasks:
                print(f"[LSF] Still waiting for {len(job_tasks)} jobs...")
                time.sleep(poll_interval)
                elapsed += poll_interval
                if elapsed > timeout:
                    print("[LSF] Timeout waiting for jobs, marking remaining as unknown.")
                    for task in job_tasks.values():
                        task.status = 'unknown'
                    break
        print("[LSF] All jobs collected.")

    def _extract_error_fingerprint(self, log_path):
        patterns = {
            'AXI_TIMEOUT': re.compile(r'AXI.*timeout', re.I),
            'UVM_FATAL': re.compile(r'UVM_FATAL', re.I),
            'LSB_MISMATCH': re.compile(r'Expected.*Got', re.I),
        }
        if not os.path.exists(log_path):
            return 'unknown'
        with open(log_path, 'r', encoding='utf-8') as f:
            content = f.read()
        for name, pat in patterns.items():
            if pat.search(content):
                return name
        return 'other_error' if 'ERROR' in content or 'FAILED' in content else 'pass'

    def _generate_report(self, root_dir):
        # 文本报告
        stats = {'pass': 0, 'fail': 0, 'unknown': 0}
        for task in self.tasks:
            stats[task.status] += 1
        report_path = os.path.join(root_dir, 'report_summary.txt')
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write("Regression Summary\n")
            f.write(f"Total: {len(self.tasks)}\n")
            f.write(f"Pass: {stats['pass']}\n")
            f.write(f"Fail: {stats['fail']}\n")
            f.write(f"Unknown: {stats['unknown']}\n")
            f.write("\nDetailed list:\n")
            for task in self.tasks:
                f.write(f"{task.status:8} : {task.name} ({task.work_dir})\n")
        print(f"[Report] Summary written to {report_path}")

        # HTML, JSON, 趋势
        self._generate_html_report(root_dir)
        self._generate_json_report(root_dir)
        self._save_trend(root_dir)

        # 创建 pass/fail/unknown 符号链接
        for status in ['pass', 'fail', 'unknown']:
            os.makedirs(os.path.join(root_dir, status), exist_ok=True)
        for task in self.tasks:
            src = task.work_dir
            if not os.path.exists(src):
                continue
            dst = os.path.join(root_dir, task.status, os.path.basename(src))
            if os.path.islink(dst) or os.path.exists(dst):
                os.remove(dst)
            os.symlink(src, dst)

    def _generate_html_report(self, root_dir):
        total = len(self.tasks)
        stats = {'pass': 0, 'fail': 0, 'unknown': 0}
        build_groups = {}
        for task in self.tasks:
            stats[task.status] += 1
            if isinstance(task, TestTask):
                build_key = task.build_name
            else:
                build_key = task.name
            if build_key not in build_groups:
                build_groups[build_key] = {'pass': 0, 'fail': 0, 'unknown': 0, 'total': 0, 'tasks': []}
            build_groups[build_key][task.status] += 1
            build_groups[build_key]['total'] += 1
            build_groups[build_key]['tasks'].append(task)

        pass_rate = (stats['pass'] / total * 100) if total > 0 else 0
        context = {
            'title': 'Regression Report',
            'generated': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'root_dir': root_dir,
            'total': total,
            'pass': stats['pass'],
            'fail': stats['fail'],
            'unknown': stats['unknown'],
            'pass_rate': f"{pass_rate:.1f}",
            'build_groups': build_groups,
        }
        template_str = '''<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>{{ title }}</title>
<style>
    body { font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }
    .container { max-width: 1200px; margin: auto; background: white; padding: 20px; border-radius: 8px; }
    h1 { color: #333; }
    .summary { display: flex; gap: 20px; flex-wrap: wrap; margin: 20px 0; }
    .summary-card { background: #f9f9f9; padding: 15px 25px; border-radius: 5px; flex: 1; min-width: 100px; text-align: center; }
    .summary-card .number { font-size: 28px; font-weight: bold; }
    .pass .number { color: #4CAF50; }
    .fail .number { color: #f44336; }
    .unknown .number { color: #ff9800; }
    .pass-rate { font-size: 24px; font-weight: bold; color: #2196F3; }
    .build-section { margin: 30px 0; border: 1px solid #ddd; border-radius: 5px; }
    .build-header { background: #e0e0e0; padding: 10px 15px; cursor: pointer; font-weight: bold; display: flex; justify-content: space-between; }
    .build-header:hover { background: #d0d0d0; }
    .test-table { width: 100%; border-collapse: collapse; }
    .test-table th, .test-table td { padding: 8px 12px; text-align: left; border-bottom: 1px solid #eee; }
    .test-table th { background: #f2f2f2; }
    .status-badge { padding: 2px 10px; border-radius: 12px; color: white; font-size: 12px; font-weight: bold; }
    .status-pass { background: #4CAF50; }
    .status-fail { background: #f44336; }
    .status-unknown { background: #ff9800; }
    .test-dir { font-size: 12px; color: #888; }
</style>
</head>
<body>
<div class="container">
    <h1>{{ title }}</h1>
    <p>Generated: {{ generated }} | Root: <code>{{ root_dir }}</code></p>
    <div class="summary">
        <div class="summary-card"><div class="number">{{ total }}</div><div class="label">Total</div></div>
        <div class="summary-card pass"><div class="number">{{ pass }}</div><div class="label">Pass</div></div>
        <div class="summary-card fail"><div class="number">{{ fail }}</div><div class="label">Fail</div></div>
        <div class="summary-card unknown"><div class="number">{{ unknown }}</div><div class="label">Unknown</div></div>
        <div class="summary-card"><div class="pass-rate">{{ pass_rate }}%</div><div class="label">Pass Rate</div></div>
    </div>
    {% for build_name, group in build_groups.items() %}
    <div class="build-section">
        <div class="build-header" onclick="this.nextElementSibling.style.display=this.nextElementSibling.style.display==='none'?'block':'none'">
            <span>Build: {{ build_name }}</span>
            <span class="build-stats">Total: {{ group.total }} | Pass: {{ group.pass }} | Fail: {{ group.fail }} | Unknown: {{ group.unknown }}</span>
        </div>
        <div class="build-tests" style="display:block;">
            <table class="test-table">
                <thead><tr><th>Test</th><th>Status</th><th>Directory</th><th>Job ID</th><th>Fingerprint</th></tr></thead>
                <tbody>
                {% for task in group.tasks %}
                <tr>
                    <td>{{ task.name }}</td>
                    <td><span class="status-badge status-{{ task.status }}">{{ task.status.upper() }}</span></td>
                    <td class="test-dir"><a href="{{ task.work_dir }}">{{ task.work_dir }}</a></td>
                    <td>{% if task.job_id %}{{ task.job_id }}{% endif %}</td>
                    <td>{{ task.fingerprint }}</td>
                </tr>
                {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
    {% endfor %}
</div>
</body>
</html>'''
        from jinja2 import Template
        template = Template(template_str)
        html_content = template.render(**context)
        html_path = os.path.join(root_dir, 'report.html')
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        print(f"[Report] HTML report: {html_path}")

    def _generate_json_report(self, root_dir):
        data = {
            'timestamp': datetime.now().isoformat(),
            'root_dir': root_dir,
            'total': len(self.tasks),
            'stats': {'pass': 0, 'fail': 0, 'unknown': 0},
            'tasks': []
        }
        for task in self.tasks:
            data['stats'][task.status] += 1
            data['tasks'].append({
                'name': task.name,
                'status': task.status,
                'work_dir': task.work_dir,
                'job_id': getattr(task, 'job_id', None),
                'fingerprint': getattr(task, 'fingerprint', 'unknown')
            })
        json_path = os.path.join(root_dir, 'report.json')
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        print(f"[Report] JSON report: {json_path}")

    def _save_trend(self, root_dir):
        try:
            db_path = os.path.join(os.path.dirname(root_dir), 'regression_trend.db')
            conn = sqlite3.connect(db_path)
            c = conn.cursor()
            c.execute('''CREATE TABLE IF NOT EXISTS runs
                         (id INTEGER PRIMARY KEY AUTOINCREMENT,
                          timestamp TEXT,
                          root_dir TEXT,
                          total INTEGER,
                          pass INTEGER,
                          fail INTEGER,
                          unknown INTEGER)''')
            stats = {'pass': 0, 'fail': 0, 'unknown': 0}
            for task in self.tasks:
                stats[task.status] += 1
            c.execute("INSERT INTO runs (timestamp, root_dir, total, pass, fail, unknown) VALUES (?,?,?,?,?,?)",
                      (datetime.now().isoformat(), root_dir, len(self.tasks), stats['pass'], stats['fail'], stats['unknown']))
            conn.commit()
            conn.close()
            print(f"[Trend] Saved to {db_path}")
        except Exception as e:
            print(f"[Trend] Save failed: {e}")

# ============================================================
# 通知模块 (Notifier)
# ============================================================

class Notifier(ABC):
    @abstractmethod
    def notify(self, summary: dict, report_url: str):
        pass

class SlackNotifier(Notifier):
    def __init__(self, webhook_url):
        self.webhook_url = webhook_url

    def notify(self, summary, report_url):
        try:
            import requests
            message = {
                "text": f"Regression Report: {summary['pass_rate']}% passed ({summary['pass']}/{summary['total']})",
                "attachments": [{"title": "Details", "text": f"HTML report: {report_url}"}]
            }
            requests.post(self.webhook_url, json=message)
            print(f"[Notify] Slack notification sent to {self.webhook_url}")
        except Exception as e:
            print(f"[Notify] Slack failed: {e}")

class EmailNotifier(Notifier):
    def __init__(self, smtp_server, sender, recipients):
        self.smtp_server = smtp_server
        self.sender = sender
        self.recipients = recipients

    def notify(self, summary, report_url):
        # 实现邮件发送（略）
        print(f"[Notify] Email would be sent to {self.recipients}")
# ============================================================
# 输出生成器 (Generator)
# ============================================================

class Generator(ABC):
    @abstractmethod
    def generate(self, config: Config, root_dir: str, mode: str):
        pass

class ShellGenerator(Generator):
    def __init__(self):
        self.context = {}
        self.settings = {}
        self.simulators = {}
        self.default_sim = 'vcs'
        self.default_build = 'build_base'
        self.hooks_global = {}

    def generate(self, config: Config, root_dir: str, mode: str):
        self.context = config.global_vars.copy()
        self.context.update(os.environ)
        self.settings = config.settings
        self.simulators = self.settings.get('simulators', {})
        self.default_sim = self.settings.get('default_simulator', 'vcs')
        self.default_build = self.settings.get('default_build', 'build_base')
        self.hooks_global = self.settings.get('hooks', {})

        os.makedirs(root_dir, exist_ok=True)
        print(f"[Generator] Creating shell scripts in {root_dir} (mode={mode})")

        builds = self._collect_builds(config)
        for build_name, build_conf in builds.items():
            self._generate_build(build_name, build_conf, root_dir, mode, config)

        if mode in ('mock', 'local'):
            self._generate_run_all(root_dir, mode, builds)

    def _collect_builds(self, config):
        builds = {}
        for test in config.tests:
            build = test.get('build')
            if isinstance(build, dict):
                build_name = build.get('name', 'inline_' + test['name'])
                builds[build_name] = build
                test['build'] = build_name
            elif isinstance(build, str):
                if build not in builds:
                    builds[build] = {}
            else:
                test['build'] = self.default_build
                if self.default_build not in builds:
                    builds[self.default_build] = {}
        for b in config.builds:
            if b['name'] not in builds:
                builds[b['name']] = b
            else:
                # Merge: test-referenced build may have empty dict; overlay actual config
                existing = builds[b['name']]
                if isinstance(existing, dict):
                    existing.update(b)
                else:
                    builds[b['name']] = b
        return builds

    def _generate_build(self, build_name, build_conf, root_dir, mode, config):
        build_dir = os.path.join(root_dir, f"build_{build_name}")
        os.makedirs(build_dir, exist_ok=True)
        b_context = self.context.copy()
        b_context.update(build_conf.get('local_vars', {}))

        pre_cmd = build_conf.get('hooks', {}).get('pre_build') or self.hooks_global.get('pre_build')
        if pre_cmd:
            pre_cmd = self._substitute(pre_cmd, b_context)
            self._write_script(os.path.join(build_dir, 'pre_build.sh'), pre_cmd, "pre_build", mode)

        sim = build_conf.get('simulator', self.default_sim)
        opts = build_conf.get('compile_opts', [])
        files = build_conf.get('files', [])
        opts_str = ' '.join([self._substitute(opt, b_context) for opt in opts])
        files_str = ' '.join(files)
        compile_tmpl = self.simulators.get(sim, {}).get('compile', 'vcs -full64 -sverilog {opts} {files}')
        compile_cmd = compile_tmpl.format(opts=opts_str, files=files_str)

        post_build_cmd = build_conf.get('hooks', {}).get('post_build') or self.hooks_global.get('post_build')
        if post_build_cmd:
            post_build_cmd = self._substitute(post_build_cmd, b_context)

        self._write_build_script(build_dir, build_name, compile_cmd, b_context, post_build_cmd, mode)

        if post_build_cmd:
            self._write_script(os.path.join(build_dir, 'post_build.sh'), post_build_cmd, "post_build", mode)

        build_tests = [t for t in config.tests if t.get('build') == build_name]
        for test in build_tests:
            test_name = test['name']
            seed = test.get('local_vars', {}).get('SEED', None)
            subdir = f"test_{test_name}_seed_{seed}" if seed is not None else f"test_{test_name}"
            test_dir = os.path.join(build_dir, subdir)
            os.makedirs(test_dir, exist_ok=True)
            t_context = self.context.copy()
            t_context.update(test.get('local_vars', {}))

            pre_sim_cmd = test.get('hooks', {}).get('pre_sim') or self.hooks_global.get('pre_sim')
            if pre_sim_cmd:
                pre_sim_cmd = self._substitute(pre_sim_cmd, t_context)
                self._write_script(os.path.join(test_dir, 'pre_sim.sh'), pre_sim_cmd, "pre_sim", mode)

            run_opts_raw = test.get('run_opts', [])
            run_opts = ' '.join([self._substitute(opt, t_context) for opt in run_opts_raw])
            sim_tmpl = self.simulators.get(sim, {}).get('run', './simv {run_opts}')
            sim_cmd = sim_tmpl.format(run_opts=run_opts)
            self._write_sim_script(test_dir, test_name, seed, sim_cmd, mode)

            post_sim_cmd = test.get('hooks', {}).get('post_sim') or self.hooks_global.get('post_sim')
            if post_sim_cmd:
                post_sim_cmd = self._substitute(post_sim_cmd, t_context)
                self._write_script(os.path.join(test_dir, 'post_sim.sh'), post_sim_cmd, "post_sim", mode)

    def _substitute(self, text, context):
        # First: Jinja2 {{ var }} for globals
        result = Template(text).render(**context)
        # Second: ${var} for test-local vars (survives ConfigBuilder pass)
        import re
        def _repl(m):
            key = m.group(1)
            return str(context.get(key, m.group(0)))
        result = re.sub(r'\$\{(\w+)\}', _repl, result)
        return result

    def _write_script(self, path, cmd, label, mode):
        with open(path, 'w', encoding='utf-8') as f:
            f.write("#!/bin/bash\n")
            if mode == 'mock':
                f.write(f"echo \"[MOCK] {label}: {cmd}\"\n")
            else:
                f.write(f"{cmd}\n")
        os.chmod(path, 0o755)

    def _write_build_script(self, build_dir, build_name, compile_cmd, context, post_build_cmd, mode):
        with open(os.path.join(build_dir, 'build.sh'), 'w', encoding='utf-8') as f:
            f.write("#!/bin/bash\n")
            if mode == 'mock':
                f.write(f"echo \"[MOCK] Build {build_name}\"\n")
                f.write(f"echo \"  {compile_cmd}\"\n")
                if post_build_cmd:
                    f.write(f"echo \"  post_build: {post_build_cmd}\"\n")
            else:
                f.write(f"{compile_cmd}\n")
                if post_build_cmd:
                    f.write(f"{post_build_cmd}\n")
        os.chmod(os.path.join(build_dir, 'build.sh'), 0o755)

    def _write_sim_script(self, test_dir, test_name, seed, sim_cmd, mode):
        with open(os.path.join(test_dir, 'sim.sh'), 'w', encoding='utf-8') as f:
            f.write("#!/bin/bash\n")
            if mode == 'mock':
                f.write(f"echo \"[MOCK] Test: {test_name} (seed={seed})\"\n")
                f.write(f"echo \"  {sim_cmd}\"\n")
            else:
                f.write(f"{sim_cmd} > sim.log 2>&1\n")
        os.chmod(os.path.join(test_dir, 'sim.sh'), 0o755)

    def _generate_run_all(self, root_dir, mode, builds):
        if mode == 'mock':
            fname = 'run_all_mock.sh'
        else:
            fname = 'run_all_local.sh'
        path = os.path.join(root_dir, fname)
        with open(path, 'w', encoding='utf-8') as f:
            f.write("#!/bin/bash\n")
            f.write(f"echo \"Running regression in {root_dir} (mode={mode})\"\n")
            if mode == 'local':
                f.write("set -e\n")
            for build_name in builds.keys():
                f.write(f"echo \"--- Build {build_name} ---\"\n")
                f.write(f"cd build_{build_name} && ./build.sh && cd ..\n")
                f.write(f"for testdir in build_{build_name}/test_*; do\n")
                f.write(f"  if [ -d \"$testdir\" ]; then\n")
                f.write(f"    cd $testdir && ./sim.sh && cd ../..\n")
                f.write(f"  fi\n")
                f.write(f"done\n")
        os.chmod(path, 0o755)

class MakefileGenerator(Generator):
    def generate(self, config: Config, root_dir: str, mode: str):
        os.makedirs(root_dir, exist_ok=True)
        print(f"[Generator] Creating Makefile in {root_dir}")
        with open(os.path.join(root_dir, 'Makefile'), 'w', encoding='utf-8') as f:
            f.write(".PHONY: all build test clean\n\n")
            f.write("all: build test\n\n")
            f.write("build:\n")
            for build in config.builds:
                f.write(f"\tcd build_{build['name']} && ./build.sh\n")
            f.write("\ntest:\n")
            for test in config.tests:
                build_name = test.get('build', 'build_base')
                if isinstance(build_name, dict):
                    build_name = build_name.get('name', 'build_base')
                test_name = test['name']
                seed = test.get('local_vars', {}).get('SEED', None)
                subdir = f"test_{test_name}_seed_{seed}" if seed is not None else f"test_{test_name}"
                f.write(f"\tcd build_{build_name}/{subdir} && ./sim.sh\n")
            f.write("\nclean:\n")
            f.write("\trm -rf build_* test_*\n")

# ============================================================
# 主程序入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(description='Full Regression Framework')
    parser.add_argument('--config', help='YAML configuration file')
    parser.add_argument('--action', choices=['generate', 'run', 'all'], default='all',
                        help='Action to perform')
    parser.add_argument('--mode', choices=['mock', 'local', 'lsf'], default='mock',
                        help='Execution mode')
    parser.add_argument('--input-dir', help='Root directory to run')
    parser.add_argument('--output-dir', help='Output root directory (auto-generated by default)')
    parser.add_argument('--backend', choices=['shell', 'makefile'], default='shell',
                        help='Output backend')
    parser.add_argument('--build-only', action='store_true', help='Only build, skip tests')
    parser.add_argument('--test-only', action='store_true', help='Only run tests, skip builds')
    parser.add_argument('--lsf-queue', default='normal', help='LSF queue')
    parser.add_argument('--lsf-project', help='LSF project')
    parser.add_argument('--lsf-resource', default='rusage[mem=4096]', help='LSF resource')
    parser.add_argument('--tests', help='Comma-separated list of test names to run')
    parser.add_argument('--tags', help='Comma-separated tags to include')
    parser.add_argument('--exclude-tags', help='Comma-separated tags to exclude')
    parser.add_argument('--parallel-builds', type=int, default=1, help='Number of parallel builds')
    parser.add_argument('--incremental', action='store_true', help='Enable incremental regression based on git changes')
    parser.add_argument('--repo-path', default='.', help='Git repository path for incremental')
    parser.add_argument('--rerun-failed', help='Root directory of previous regression run to rerun failed tests')
    parser.add_argument('--notify-slack', help='Slack webhook URL for notification')
    parser.add_argument('--notify-email', help='Email recipients (comma separated) for notification')
    args = parser.parse_args()

    # ==================== 处理 --rerun-failed ====================
    if args.rerun_failed:
        src_root = args.rerun_failed
        if not os.path.isdir(src_root):
            print(f"Error: {src_root} is not a valid directory")
            sys.exit(1)
        report_file = os.path.join(src_root, 'report_summary.txt')
        if not os.path.exists(report_file):
            print(f"Error: report_summary.txt not found in {src_root}")
            sys.exit(1)

        failed_work_dirs = []
        with open(report_file, 'r', encoding='utf-8') as f:
            for line in f:
                if line.startswith('fail'):
                    parts = line.split()
                    if len(parts) >= 4:
                        work_dir = parts[3].strip('()')
                        if os.path.exists(work_dir):
                            failed_work_dirs.append(work_dir)

        if not failed_work_dirs:
            print("No failed tests found.")
            return

        new_root = args.output_dir if args.output_dir else f"rerun_failed_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        new_root = new_root.replace(' ', '_')
        os.makedirs(new_root, exist_ok=True)
        print(f"Creating rerun directory: {new_root}")

        build_paths = set()
        for wd in failed_work_dirs:
            build_dir = os.path.dirname(wd)
            build_paths.add(build_dir)

        for build_dir in build_paths:
            build_name = os.path.basename(build_dir)
            new_build_dir = os.path.join(new_root, build_name)
            os.makedirs(new_build_dir, exist_ok=True)
            for f in os.listdir(build_dir):
                if f.endswith('.sh') and os.path.isfile(os.path.join(build_dir, f)):
                    shutil.copy2(os.path.join(build_dir, f), new_build_dir)
            for wd in failed_work_dirs:
                if os.path.dirname(wd) == build_dir:
                    test_dir = os.path.basename(wd)
                    new_test_dir = os.path.join(new_build_dir, test_dir)
                    os.makedirs(new_test_dir, exist_ok=True)
                    for f in os.listdir(wd):
                        if f.endswith('.sh') and os.path.isfile(os.path.join(wd, f)):
                            shutil.copy2(os.path.join(wd, f), new_test_dir)

        readme_path = os.path.join(new_root, 'README.txt')
        with open(readme_path, 'w', encoding='utf-8') as f:
            f.write(f"Rerun of failed tests from {src_root}\n")
            f.write(f"Failed test count: {len(failed_work_dirs)}\n")
            f.write("\nTo run manually, cd into each test directory and execute ./sim.sh\n")
        print(f"✅ Failed tests copied to {new_root}")
        return

    # ==================== 常规流程 ====================
    if args.build_only and args.test_only:
        print("Error: --build-only and --test-only cannot be used together")
        sys.exit(1)

    if args.action in ('run', 'all') and not args.config and not args.input_dir:
        print("Error: for 'run' or 'all', provide --config or --input-dir")
        sys.exit(1)

    if args.action in ('generate', 'all') and not args.config:
        print("Error: for 'generate' or 'all', provide --config")
        sys.exit(1)

    tags_filter = None
    exclude_tags_filter = None
    tests_filter = None
    if args.tags:
        tags_filter = [t.strip() for t in args.tags.split(',') if t.strip()]
    if args.exclude_tags:
        exclude_tags_filter = [t.strip() for t in args.exclude_tags.split(',') if t.strip()]
    if args.tests:
        tests_filter = [t.strip() for t in args.tests.split(',') if t.strip()]

    generated_dir = None

    # ---------- Generate phase ----------
    if args.action in ('generate', 'all'):
        builder = ConfigBuilder(args.config)
        config = builder.build(incremental=args.incremental, repo_path=args.repo_path)
        root_dir = args.output_dir if args.output_dir else f"regression_{args.mode}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        root_dir = root_dir.replace(' ', '_')
        if args.backend == 'shell':
            generator = ShellGenerator()
        elif args.backend == 'makefile':
            generator = MakefileGenerator()
        else:
            print(f"Unknown backend: {args.backend}")
            sys.exit(1)
        generator.generate(config, root_dir, args.mode)
        print(f"Generation completed. Output: {root_dir}")
        generated_dir = root_dir
        if args.action == 'generate':
            return

    # ---------- Run phase ----------
    if args.action in ('run', 'all'):
        if args.action == 'all' and not args.input_dir and generated_dir:
            args.input_dir = generated_dir
        root_dir = args.input_dir if args.input_dir else (args.output_dir if args.output_dir else None)
        if not root_dir:
            print("Error: need --input-dir or --output-dir for run")
            sys.exit(1)
        if not os.path.isdir(root_dir):
            print(f"Error: directory {root_dir} not found")
            sys.exit(1)

        # 构建执行策略
        if args.mode == 'mock':
            strategy = MockStrategy()
        elif args.mode == 'local':
            strategy = LocalStrategy()
        elif args.mode == 'lsf':
            strategy = LsfStrategy(queue=args.lsf_queue, project=args.lsf_project, resource=args.lsf_resource)
        else:
            print(f"Unknown mode: {args.mode}")
            sys.exit(1)

        # 状态文件（用于断点续跑）
        state_file = os.path.join(root_dir, '.regression_state.json')
        scheduler = Scheduler(strategy, build_only=args.build_only, test_only=args.test_only,
                              parallel_builds=args.parallel_builds, state_file=state_file)

        # 扫描目录，创建任务
        build_dirs = [d for d in os.listdir(root_dir) if d.startswith('build_') and os.path.isdir(os.path.join(root_dir, d))]
        build_dirs.sort()
        added_builds = set()

        for build_dir in build_dirs:
            build_path = os.path.join(root_dir, build_dir)
            build_name = build_dir.replace('build_', '')
            test_dirs = [d for d in os.listdir(build_path) if d.startswith('test_') and os.path.isdir(os.path.join(build_path, d))]
            test_dirs.sort()

            # 过滤测试
            filtered_test_dirs = []
            for test_dir in test_dirs:
                test_name = test_dir.replace('test_', '')
                # 名称过滤
                if tests_filter is not None and test_name not in tests_filter:
                    continue
                # 标签过滤（需要从 test 目录中读取标签？目前只支持从 YAML 中过滤，运行阶段无法获取标签）
                # 所以标签过滤在生成阶段已经应用，这里不再重复过滤
                filtered_test_dirs.append(test_dir)

            if filtered_test_dirs:
                if build_name not in added_builds:
                    build_task = TaskFactory.create_build_task(build_name, build_path)
                    scheduler.add_task(build_task)
                    added_builds.add(build_name)

                for test_dir in filtered_test_dirs:
                    test_name = test_dir.replace('test_', '')
                    test_path = os.path.join(build_path, test_dir)
                    test_task = TaskFactory.create_test_task(test_name, test_path, build_name)
                    scheduler.add_task(test_task)

        scheduler.run(root_dir)

        # 通知（如果有配置）
        if args.notify_slack:
            summary = {'total': len(scheduler.tasks), 'pass': 0, 'fail': 0, 'unknown': 0, 'pass_rate': 0}
            for task in scheduler.tasks:
                summary[task.status] += 1
            summary['pass_rate'] = (summary['pass'] / summary['total'] * 100) if summary['total'] > 0 else 0
            notifier = SlackNotifier(args.notify_slack)
            report_url = f"file://{os.path.abspath(os.path.join(root_dir, 'report.html'))}"
            notifier.notify(summary, report_url)

if __name__ == '__main__':
    main()