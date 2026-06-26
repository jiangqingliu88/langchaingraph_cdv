#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
通用回归框架 - 支持插件化matrix、DAG依赖、多后端、多执行策略
"""

import os
import sys
import yaml
import subprocess
import itertools
import argparse
import importlib
from copy import deepcopy
from jinja2 import Template
from datetime import datetime
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass, field

# ============================================================
# 1. 配置数据类
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
# 2. 配置构建器
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
        with open(filepath, 'r') as f:
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

    def expand_matrix(self, tests: list) -> list:
        expanded = []
        for test in tests:
            if 'matrix' not in test:
                expanded.append(test)
                continue
            matrix_items = test.pop('matrix')
            all_params = {}
            for item in matrix_items:
                if 'plugin' in item:
                    func_name = item.pop('plugin')
                    func = self._load_plugin(func_name)
                    args = item.get('args', {})
                    result = func(**args)
                    for k, v in result.items():
                        all_params.setdefault(k, []).extend(v)
                else:
                    for k, v in item.items():
                        if not isinstance(v, list):
                            v = [v]
                        all_params.setdefault(k, []).extend(v)
            name_format = test.pop('name_format', None)
            keys = list(all_params.keys())
            values = [all_params[k] for k in keys]
            idx = 0
            for combo in itertools.product(*values):
                new_test = deepcopy(test)
                param_dict = dict(zip(keys, combo))
                if name_format:
                    context = param_dict.copy()
                    context['idx'] = idx
                    name = name_format.format(**context)
                else:
                    if len(param_dict) <= 2:
                        suffix = '_'.join([str(v) for v in param_dict.values()])
                    else:
                        first_two = [str(v) for v in list(param_dict.values())[:2]]
                        suffix = '_'.join(first_two) + '_etc'
                    name = f"{test['name']}_{suffix}"
                new_test['name'] = name
                if 'local_vars' not in new_test:
                    new_test['local_vars'] = {}
                for k, v in param_dict.items():
                    new_test['local_vars'][k] = v
                expanded.append(new_test)
                idx += 1
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

    def _load_plugin(self, name: str) -> Callable:
        module_name = f"{self.plugin_dir}.matrix_functions"
        try:
            module = importlib.import_module(module_name)
            return getattr(module, name)
        except (ImportError, AttributeError) as e:
            print(f"Error loading plugin {name}: {e}")
            sys.exit(1)

    def build(self) -> Config:
        raw = self.load_yaml_with_includes(self.yaml_file)
        raw = self._resolve_extends(raw)
        global_vars = raw.get('global_vars', {})
        self.context = global_vars.copy()
        self.context.update(os.environ)

        substituted = self.substitute_vars(raw, self.context)

        settings = substituted.get('settings', {})
        default_count = settings.get('default_count', 1)
        tests = substituted.get('tests', [])
        tests = self.expand_matrix(tests)
        tests = self.expand_count(tests, default_count)
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
# 3. 任务抽象
# ============================================================

class Task(ABC):
    def __init__(self, name: str, work_dir: str, script_path: str):
        self.name = name
        self.work_dir = work_dir
        self.script_path = script_path
        self.depends_on = []

    @abstractmethod
    def execute(self, executor) -> bool:
        pass

class BuildTask(Task):
    def __init__(self, build_name: str, build_dir: str):
        super().__init__(build_name, build_dir, os.path.join(build_dir, 'build.sh'))
        self.pre_script = os.path.join(build_dir, 'pre_build.sh') if os.path.exists(os.path.join(build_dir, 'pre_build.sh')) else None
        self.post_script = os.path.join(build_dir, 'post_build.sh') if os.path.exists(os.path.join(build_dir, 'post_build.sh')) else None

    def execute(self, executor) -> bool:
        if self.pre_script:
            if not executor.run_script(self.pre_script, self.work_dir, f"{self.name}_pre"):
                return False
        if not executor.run_script(self.script_path, self.work_dir, self.name):
            return False
        if self.post_script:
            if not executor.run_script(self.post_script, self.work_dir, f"{self.name}_post"):
                return False
        return True

class TestTask(Task):
    def __init__(self, test_name: str, test_dir: str, build_name: str):
        super().__init__(test_name, test_dir, os.path.join(test_dir, 'sim.sh'))
        self.build_name = build_name
        self.pre_script = os.path.join(test_dir, 'pre_sim.sh') if os.path.exists(os.path.join(test_dir, 'pre_sim.sh')) else None
        self.post_script = os.path.join(test_dir, 'post_sim.sh') if os.path.exists(os.path.join(test_dir, 'post_sim.sh')) else None

    def execute(self, executor) -> bool:
        if self.pre_script:
            if not executor.run_script(self.pre_script, self.work_dir, f"{self.name}_pre"):
                return False
        if not executor.run_script(self.script_path, self.work_dir, self.name):
            return False
        if self.post_script:
            if not executor.run_script(self.post_script, self.work_dir, f"{self.name}_post"):
                return False
        return True

class TaskFactory:
    @staticmethod
    def create_build_task(build_name, build_dir):
        return BuildTask(build_name, build_dir)

    @staticmethod
    def create_test_task(test_name, test_dir, build_name):
        return TestTask(test_name, test_dir, build_name)

# ============================================================
# 4. 执行策略
# ============================================================

class ExecutionStrategy(ABC):
    @abstractmethod
    def run_script(self, script_path: str, cwd: str, job_name: str = None, timeout: int = None, retry: int = 0) -> bool:
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
            return True
        if job_name is None:
            job_name = os.path.basename(os.path.dirname(script_path)) + '_' + os.path.basename(script_path).replace('.sh', '')
        cmd = f"bsub -J \"{job_name}\" -q {self.queue}"
        if self.project:
            cmd += f" -P {self.project}"
        if self.resource:
            cmd += f" -R \"{self.resource}\""
        if timeout:
            cmd += f" -W {timeout}"
        cmd += f" 'cd {cwd} && ./{os.path.basename(script_path)}'"
        print(f"  [LSF] Submitting: {cmd}")
        try:
            subprocess.run(cmd, shell=True, check=True)
            return True
        except subprocess.CalledProcessError as e:
            print(f"  [ERROR] LSF submission failed: {e}")
            return False

# ============================================================
# 5. 调度器（DAG）
# ============================================================

class Scheduler:
    def __init__(self, strategy: ExecutionStrategy, build_only=False, test_only=False):
        self.strategy = strategy
        self.build_only = build_only
        self.test_only = test_only
        self.tasks = []
        self.task_map = {}

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

    def run(self):
        graph = self._build_dependency_graph()
        order = self._topological_sort(graph)
        print(f"[Scheduler] Running {len(order)} tasks in topological order")
        for name in order:
            task = self.task_map.get(name)
            if not task:
                continue
            if self.build_only and isinstance(task, TestTask):
                continue
            if self.test_only and isinstance(task, BuildTask):
                continue
            print(f"\n[Task] {task.name}")
            success = task.execute(self.strategy)
            if not success:
                print(f"[ERROR] Task {task.name} failed.")
                if not isinstance(self.strategy, LsfStrategy):
                    break
            else:
                print(f"[Task] {task.name} completed.")

# ============================================================
# 6. 输出生成器
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
            self._generate_build(build_name, build_conf, root_dir, mode)

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
        return builds

    def _generate_build(self, build_name, build_conf, root_dir, mode):
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
        return Template(text).render(**context)

    def _write_script(self, path, cmd, label, mode):
        with open(path, 'w') as f:
            f.write("#!/bin/bash\n")
            if mode == 'mock':
                f.write(f"echo \"[MOCK] {label}: {cmd}\"\n")
            else:
                f.write(f"{cmd}\n")
        os.chmod(path, 0o755)

    def _write_build_script(self, build_dir, build_name, compile_cmd, context, post_build_cmd, mode):
        with open(os.path.join(build_dir, 'build.sh'), 'w') as f:
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
        with open(os.path.join(test_dir, 'sim.sh'), 'w') as f:
            f.write("#!/bin/bash\n")
            if mode == 'mock':
                f.write(f"echo \"[MOCK] Test: {test_name} (seed={seed})\"\n")
                f.write(f"echo \"  {sim_cmd}\"\n")
            else:
                f.write(f"{sim_cmd}\n")
        os.chmod(os.path.join(test_dir, 'sim.sh'), 0o755)

    def _generate_run_all(self, root_dir, mode, builds):
        if mode == 'mock':
            fname = 'run_all_mock.sh'
        else:
            fname = 'run_all_local.sh'
        path = os.path.join(root_dir, fname)
        with open(path, 'w') as f:
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
        with open(os.path.join(root_dir, 'Makefile'), 'w') as f:
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
# 7. 主程序
# ============================================================

def main():
    parser = argparse.ArgumentParser(description='Regression Framework')
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
    parser.add_argument('--tests', help='Comma-separated list of test names to run (e.g., test_alu_ADD,test_alu_SUB)')
    # 新增 --rerun-failed
    parser.add_argument('--rerun-failed', help='Root directory of a previous regression run, to extract failed tests and copy scripts to a new directory')
    args = parser.parse_args()

    # ---------- 处理 --rerun-failed ----------
    if args.rerun_failed:
        src_root = args.rerun_failed
        if not os.path.isdir(src_root):
            print(f"Error: {src_root} is not a valid directory")
            sys.exit(1)
        report_file = os.path.join(src_root, 'report_summary.txt')
        if not os.path.exists(report_file):
            print(f"Error: report_summary.txt not found in {src_root}")
            sys.exit(1)

        # 提取失败用例的工作目录
        failed_work_dirs = []
        with open(report_file, 'r') as f:
            for line in f:
                if line.startswith('fail'):
                    parts = line.split()
                    if len(parts) >= 4:
                        # 格式: fail : test_name (work_dir)
                        work_dir = parts[3].strip('()')
                        if os.path.exists(work_dir):
                            failed_work_dirs.append(work_dir)

        if not failed_work_dirs:
            print("No failed tests found.")
            return

        # 创建新目录
        new_root = args.output_dir if args.output_dir else f"rerun_failed_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        new_root = new_root.replace(' ', '_')
        os.makedirs(new_root, exist_ok=True)
        print(f"Creating rerun directory: {new_root}")

        # 收集需要复制的 build 目录（去重）
        build_paths = set()
        for wd in failed_work_dirs:
            # wd 类似于 build_xxx/test_yyy_seed_zzz
            build_dir = os.path.dirname(wd)
            build_paths.add(build_dir)

        # 复制 build 目录下的所有 .sh 文件，以及失败 test 子目录下的 .sh 文件
        for build_dir in build_paths:
            build_name = os.path.basename(build_dir)
            new_build_dir = os.path.join(new_root, build_name)
            os.makedirs(new_build_dir, exist_ok=True)
            # 复制 build 根目录下的 .sh 文件
            for f in os.listdir(build_dir):
                if f.endswith('.sh') and os.path.isfile(os.path.join(build_dir, f)):
                    shutil.copy2(os.path.join(build_dir, f), new_build_dir)
            # 复制该 build 下属于失败列表的 test 子目录
            for wd in failed_work_dirs:
                if os.path.dirname(wd) == build_dir:
                    test_dir = os.path.basename(wd)
                    new_test_dir = os.path.join(new_build_dir, test_dir)
                    os.makedirs(new_test_dir, exist_ok=True)
                    for f in os.listdir(wd):
                        if f.endswith('.sh') and os.path.isfile(os.path.join(wd, f)):
                            shutil.copy2(os.path.join(wd, f), new_test_dir)

        # 生成一个简单的 README
        readme_path = os.path.join(new_root, 'README.txt')
        with open(readme_path, 'w') as f:
            f.write(f"Rerun of failed tests from {src_root}\n")
            f.write(f"Failed test count: {len(failed_work_dirs)}\n")
            f.write("\nTo run manually, cd into each test directory and execute ./sim.sh\n")
            f.write("Or use the framework again on this new directory:\n")
            f.write(f"  python regression_framework.py --action run --mode local --input-dir {new_root}\n")
            f.write(f"  python regression_framework.py --action run --mode lsf --input-dir {new_root}\n")

        print(f"✅ Failed tests copied to {new_root}")
        print(f"   Total failed tests: {len(failed_work_dirs)}")
        print(f"   Run ./{os.path.basename(new_root)}/README.txt for instructions.")
        return  # 完成 rerun-failed 后退出

    # ---------- 原有逻辑（generate/run/all） ----------
    if args.build_only and args.test_only:
        print("Error: --build-only and --test-only cannot be used together")
        sys.exit(1)

    if args.action in ('run', 'all') and not args.config and not args.input_dir:
        print("Error: for 'run' or 'all', provide --config or --input-dir")
        sys.exit(1)

    if args.action in ('generate', 'all') and not args.config:
        print("Error: for 'generate' or 'all', provide --config")
        sys.exit(1)

    tests_filter = None
    if args.tests:
        tests_filter = [t.strip() for t in args.tests.split(',') if t.strip()]

    generated_dir = None

    # Generate phase
    if args.action in ('generate', 'all'):
        builder = ConfigBuilder(args.config)
        config = builder.build()
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

    # Run phase
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

        if args.mode == 'mock':
            strategy = MockStrategy()
        elif args.mode == 'local':
            strategy = LocalStrategy()
        elif args.mode == 'lsf':
            strategy = LsfStrategy(queue=args.lsf_queue, project=args.lsf_project, resource=args.lsf_resource)
        else:
            print(f"Unknown mode: {args.mode}")
            sys.exit(1)

        scheduler = Scheduler(strategy, build_only=args.build_only, test_only=args.test_only)

        # 扫描目录，创建任务（应用 --tests 过滤）
        build_dirs = [d for d in os.listdir(root_dir) if d.startswith('build_') and os.path.isdir(os.path.join(root_dir, d))]
        build_dirs.sort()
        added_builds = set()

        for build_dir in build_dirs:
            build_path = os.path.join(root_dir, build_dir)
            build_name = build_dir.replace('build_', '')
            test_dirs = [d for d in os.listdir(build_path) if d.startswith('test_') and os.path.isdir(os.path.join(build_path, d))]
            test_dirs.sort()

            has_matched = False
            if tests_filter is not None:
                for test_dir in test_dirs:
                    test_name = test_dir.replace('test_', '')
                    if test_name in tests_filter:
                        has_matched = True
                        break
            else:
                has_matched = True

            if has_matched or tests_filter is None:
                if build_name not in added_builds:
                    build_task = TaskFactory.create_build_task(build_name, build_path)
                    scheduler.add_task(build_task)
                    added_builds.add(build_name)

                for test_dir in test_dirs:
                    test_name = test_dir.replace('test_', '')
                    if tests_filter is None or test_name in tests_filter:
                        test_path = os.path.join(build_path, test_dir)
                        test_task = TaskFactory.create_test_task(test_name, test_path, build_name)
                        scheduler.add_task(test_task)

        if tests_filter is not None and not any(isinstance(t, TestTask) for t in scheduler.tasks):
            print(f"Warning: No tests matching {tests_filter} found in {root_dir}")

        scheduler.run(root_dir)

if __name__ == '__main__':
    main()