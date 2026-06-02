#!/usr/bin/env python3
"""
基于 YAML 的验证回归管理工具
支持多 Build、Test 继承 Build、tag 筛选、pre/post 钩子

用法:
  python run.py --tags smoke                    # 运行 smoke 标签的测试
  python run.py --tags smoke,sanity             # 运行多个标签
  python run.py --test alu_smoke_test           # 运行单个测试
  python run.py --test alu_smoke_test --seed 999 # 指定 seed
  python run.py --tags functional --parallel 8  # 并行运行
  python run.py --tags smoke --list             # 仅列出，不运行
  python run.py --builds                        # 仅编译所有 Build
  python run.py --tags smoke --dry-run          # 干运行
"""

import os
import sys
import yaml
import time
import copy
import random
import signal
import argparse
import subprocess
from datetime import datetime
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
from enum import Enum


# ═══════════════════════════════════════════
# 数据结构
# ═══════════════════════════════════════════

class TestStatus(Enum):
    PENDING = "PENDING"
    COMPILING = "COMPILING"
    COMPILE_PASS = "COMPILE_PASS"
    COMPILE_FAIL = "COMPILE_FAIL"
    RUNNING = "RUNNING"
    PASS = "PASS"
    FAIL = "FAIL"
    TIMEOUT = "TIMEOUT"
    SKIP = "SKIP"


@dataclass
class BuildConfig:
    name: str
    description: str = ""
    parent: Optional[str] = None
    simulator: str = "vcs"
    pre_build: List[str] = field(default_factory=list)
    post_build: List[str] = field(default_factory=list)
    compile_options: List[str] = field(default_factory=list)
    filelist: str = ""
    top_module: str = ""
    output_dir: str = "./build"
    compile_timeout: int = 600
    waves: bool = False
    coverage: bool = False
    defines: Dict[str, Any] = field(default_factory=dict)
    executable: str = ""
    _resolved: bool = False

    def get_executable(self) -> str:
        if self.executable:
            return self.executable
        return os.path.join(self.output_dir, "simv")


@dataclass
class TestConfig:
    name: str
    build: str = ""
    tags: List[str] = field(default_factory=list)
    seed: Any = None
    count: int = 1
    sim_timeout: int = 3600
    verbosity: str = "UVM_MEDIUM"
    waves: bool = False
    coverage: bool = False
    retry: int = 0
    pre_run: List[str] = field(default_factory=list)
    post_run: List[str] = field(default_factory=list)
    plusargs: List[str] = field(default_factory=list)
    build_config: Optional[BuildConfig] = None


@dataclass
class TestResult:
    test_name: str
    tags: List[str]
    build_name: str
    status: TestStatus = TestStatus.PENDING
    seed: int = 0
    index: int = 0
    count: int = 1
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    duration: float = 0.0
    log_file: str = ""
    error_message: str = ""
    retry_count: int = 0


@dataclass
class BuildResult:
    build_name: str
    status: TestStatus = TestStatus.PENDING
    compile_log: str = ""
    compile_time: float = 0.0


# ═══════════════════════════════════════════
# 配置管理器
# ═══════════════════════════════════════════

class ConfigManager:
    def __init__(self, yaml_file: str):
        with open(yaml_file, 'r', encoding='utf-8') as f:
            raw = yaml.safe_load(f)

        cfg = raw['config']
        self.name = cfg['name']
        self.description = cfg.get('description', '')
        self.defaults = cfg.get('defaults', {})

        # 解析 Build
        self.builds: Dict[str, BuildConfig] = {}
        self._parse_builds(cfg.get('builds', []))

        # 解析 Test
        self.tests: Dict[str, TestConfig] = {}
        self._parse_tests(cfg.get('tests', []))

    def _parse_builds(self, raw_builds: list):
        for b in raw_builds:
            build = BuildConfig(
                name=b['name'],
                description=b.get('description', ''),
                parent=b.get('parent'),
                simulator=b.get('simulator', self.defaults.get('simulator', 'vcs')),
                pre_build=self._to_list(b.get('pre_build', [])),
                post_build=self._to_list(b.get('post_build', [])),
                compile_options=b.get('compile_options', []),
                filelist=b.get('filelist', ''),
                top_module=b.get('top_module', ''),
                output_dir=b.get('output_dir', './build'),
                compile_timeout=b.get('compile_timeout', self.defaults.get('compile_timeout', 600)),
                waves=b.get('waves', self.defaults.get('waves', False)),
                coverage=b.get('coverage', self.defaults.get('coverage', False)),
                defines=b.get('defines', {}),
                executable=b.get('executable', ''),
            )
            self.builds[build.name] = build

        # 解析继承
        for build in self.builds.values():
            self._resolve_build(build)

    def _resolve_build(self, build: BuildConfig, visited: set = None):
        if visited is None:
            visited = set()
        if build._resolved or not build.parent:
            build._resolved = True
            return
        if build.name in visited:
            raise ValueError(f"Circular build inheritance: {build.name}")
        visited.add(build.name)

        parent = self.builds.get(build.parent)
        if not parent:
            raise ValueError(f"Parent build '{build.parent}' not found for '{build.name}'")

        self._resolve_build(parent, visited)

        # 合并 compile_options
        build.compile_options = parent.compile_options + build.compile_options
        # 合并 defines
        merged = copy.deepcopy(parent.defines)
        merged.update(build.defines)
        build.defines = merged
        # 合并 pre/post
        build.pre_build = parent.pre_build + build.pre_build
        build.post_build = parent.post_build + build.post_build
        # 继承未设置的字段
        if not build.filelist:
            build.filelist = parent.filelist
        if not build.top_module:
            build.top_module = parent.top_module
        if not build.simulator or build.simulator == self.defaults.get('simulator'):
            build.simulator = parent.simulator

        build._resolved = True

    def _parse_tests(self, raw_tests: list):
        for t in raw_tests:
            build_name = t.get('build', '')
            test = TestConfig(
                name=t['name'],
                build=build_name,
                tags=t.get('tags', []),
                seed=t.get('seed'),
                count=t.get('count', self.defaults.get('count', 1)),
                sim_timeout=t.get('sim_timeout', self.defaults.get('sim_timeout', 3600)),
                verbosity=t.get('verbosity', self.defaults.get('verbosity', 'UVM_MEDIUM')),
                waves=t.get('waves', self.defaults.get('waves', False)),
                coverage=t.get('coverage', self.defaults.get('coverage', False)),
                retry=t.get('retry', self.defaults.get('retry', 0)),
                pre_run=self._to_list(t.get('pre_run', [])),
                post_run=self._to_list(t.get('post_run', [])),
                plusargs=t.get('plusargs', []),
                build_config=self.builds.get(build_name),
            )
            self.tests[test.name] = test

    @staticmethod
    def _to_list(val) -> List[str]:
        if val is None:
            return []
        if isinstance(val, str):
            return [val]
        return val

    def get_tests_by_tags(self, tags: List[str]) -> List[TestConfig]:
        tag_set = set(tags)
        result = []
        for test in self.tests.values():
            if tag_set & set(test.tags):
                result.append(test)
        return result

    def get_all_builds_for_tests(self, tests: List[TestConfig]) -> List[str]:
        builds = set()
        for t in tests:
            if t.build:
                builds.add(t.build)
        return list(builds)


# ═══════════════════════════════════════════
# Shell 执行器
# ═══════════════════════════════════════════

class ShellRunner:
    @staticmethod
    def run_commands(commands: List[str], env_vars: Dict[str, str],
                     cwd: str = ".", timeout: int = 300, label: str = "") -> bool:
        """执行命令列表，失败返回 False"""
        if not commands:
            return True

        merged_env = os.environ.copy()
        merged_env.update(env_vars)

        for cmd in commands:
            # 替换环境变量
            for k, v in env_vars.items():
                cmd = cmd.replace(f"${{{k}}}", str(v))
                cmd = cmd.replace(f"${k}", str(v))

            print(f"  [{label}] {cmd}")

            # 外部脚本检查权限
            script = cmd.split()[0]
            if (script.startswith('./') or script.startswith('/')) and os.path.exists(script):
                os.chmod(script, 0o755)

            try:
                result = subprocess.run(
                    cmd, shell=True, cwd=cwd, env=merged_env,
                    timeout=timeout, capture_output=True, text=True
                )
                if result.returncode != 0:
                    print(f"  [{label} FAIL] {result.stderr[-300:]}")
                    return False
            except subprocess.TimeoutExpired:
                print(f"  [{label} TIMEOUT] {timeout}s")
                return False

        return True


# ═══════════════════════════════════════════
# Build 管理器
# ═══════════════════════════════════════════

class BuildManager:
    def __init__(self, config: ConfigManager):
        self.config = config
        self.results: Dict[str, BuildResult] = {}

    def compile(self, build_name: str, force: bool = False) -> BuildResult:
        build = self.config.builds.get(build_name)
        if not build:
            return BuildResult(build_name, TestStatus.COMPILE_FAIL)

        executable = build.get_executable()
        if not force and os.path.exists(executable):
            print(f"Build '{build_name}' already compiled, skip.")
            result = BuildResult(build_name, TestStatus.COMPILE_PASS)
            self.results[build_name] = result
            return result

        print(f"\n{'='*60}")
        print(f"Compiling: {build_name}")
        print(f"{'='*60}")

        os.makedirs(build.output_dir, exist_ok=True)

        env_vars = {
            'BUILD_NAME': build.name,
            'BUILD_DIR': build.output_dir,
            'TIMESTAMP': datetime.now().strftime('%Y%m%d_%H%M%S'),
        }

        # pre_build
        ok = ShellRunner.run_commands(
            build.pre_build, env_vars, cwd=build.output_dir, label="PRE_BUILD"
        )
        if not ok:
            result = BuildResult(build_name, TestStatus.COMPILE_FAIL)
            self.results[build_name] = result
            return result

        # 编译命令
        cmd = [build.simulator]
        cmd.extend(build.compile_options)
        for k, v in build.defines.items():
            cmd.append(f"+define+{k}={v}")
        if build.filelist:
            cmd.extend(['-f', build.filelist])
        if build.top_module:
            cmd.extend(['-top', build.top_module])
        cmd.extend(['-o', executable])

        log_file = os.path.join(build.output_dir, f"{build_name}_compile.log")
        print(f"  [COMPILE] {' '.join(cmd)}")
        print(f"  [LOG] {log_file}")

        start = time.time()
        try:
            with open(log_file, 'w') as f:
                proc = subprocess.run(cmd, timeout=build.compile_timeout,
                                      stdout=f, stderr=subprocess.STDOUT)
            elapsed = time.time() - start
            if proc.returncode == 0:
                print(f"  [COMPILE OK] {elapsed:.1f}s")
                result = BuildResult(build_name, TestStatus.COMPILE_PASS, log_file, elapsed)
            else:
                print(f"  [COMPILE FAIL] {elapsed:.1f}s")
                result = BuildResult(build_name, TestStatus.COMPILE_FAIL, log_file, elapsed)
        except subprocess.TimeoutExpired:
            print(f"  [COMPILE TIMEOUT] {build.compile_timeout}s")
            result = BuildResult(build_name, TestStatus.COMPILE_FAIL, log_file, build.compile_timeout)

        # post_build
        if result.status == TestStatus.COMPILE_PASS:
            ShellRunner.run_commands(
                build.post_build, env_vars, cwd=build.output_dir, label="POST_BUILD"
            )

        self.results[build_name] = result
        return result

    def compile_all(self, build_names: List[str], force: bool = False):
        order = self._resolve_order(build_names)
        for name in order:
            self.compile(name, force)

    def _resolve_order(self, build_names: List[str]) -> List[str]:
        order = []
        visited = set()

        def visit(name):
            if name in visited:
                return
            visited.add(name)
            build = self.config.builds.get(name)
            if build and build.parent and build.parent in self.config.builds:
                visit(build.parent)
            order.append(name)

        for name in build_names:
            visit(name)
        return order


# ═══════════════════════════════════════════
# Test 运行器
# ═══════════════════════════════════════════

class TestRunner:
    def __init__(self, config: ConfigManager, build_mgr: BuildManager):
        self.config = config
        self.build_mgr = build_mgr
        self.log_dir = "./test_logs"
        self.results: List[TestResult] = []

    def generate_seeds(self, seed_config, count: int) -> List[int]:
        if seed_config is None or seed_config == 'random':
            return [random.randint(1, 2**31 - 1) for _ in range(count)]
        base = int(seed_config)
        return [base + i for i in range(count)]

    def run_test(self, test: TestConfig) -> List[TestResult]:
        build = test.build_config
        if not build:
            print(f"Build '{test.build}' not found, skip test '{test.name}'")
            return [TestResult(test.name, test.tags, test.build, TestStatus.SKIP)]

        build_result = self.build_mgr.results.get(test.build)
        if not build_result or build_result.status != TestStatus.COMPILE_PASS:
            print(f"Build '{test.build}' not compiled, skip test '{test.name}'")
            return [TestResult(test.name, test.tags, test.build, TestStatus.SKIP)]

        executable = build.get_executable()
        os.makedirs(self.log_dir, exist_ok=True)

        # 生成 seeds
        seeds = self.generate_seeds(test.seed, test.count)

        results = []
        for i, seed in enumerate(seeds):
            result = self._run_single(test, build, executable, seed, i + 1)
            results.append(result)

            # 重试
            retry = 0
            while result.status != TestStatus.PASS and retry < test.retry:
                retry += 1
                new_seed = random.randint(1, 2**31 - 1)
                print(f"  Retry {retry}/{test.retry} with seed={new_seed}")
                result = self._run_single(test, build, executable, new_seed, i + 1)
                result.retry_count = retry
                results.append(result)

        return results

    def _run_single(self, test: TestConfig, build: BuildConfig,
                    executable: str, seed: int, index: int) -> TestResult:
        log_file = os.path.join(self.log_dir, f"{test.name}_{seed}.log")

        result = TestResult(
            test_name=test.name,
            tags=test.tags,
            build_name=test.build,
            status=TestStatus.RUNNING,
            seed=seed,
            index=index,
            count=test.count,
            log_file=log_file,
        )

        env_vars = {
            'TEST_NAME': test.name,
            'BUILD_NAME': test.build,
            'SEED': str(seed),
            'INDEX': str(index),
            'COUNT': str(test.count),
            'LOG_FILE': log_file,
            'SIM_DIR': build.output_dir,
            'TAGS': ','.join(test.tags),
            'TIMESTAMP': datetime.now().strftime('%Y%m%d_%H%M%S'),
        }

        # pre_run
        ok = ShellRunner.run_commands(test.pre_run, env_vars, label="PRE_RUN")
        if not ok:
            result.status = TestStatus.SKIP
            result.error_message = "pre_run failed"
            self._print_result(result)
            return result

        # 仿真
        sim_cmd = [executable]
        sim_cmd.append(f"+ntb_random_seed={seed}")
        sim_cmd.append(f"+UVM_VERBOSITY={test.verbosity}")
        sim_cmd.extend(test.plusargs)
        if test.waves or build.waves:
            sim_cmd.append("+DUMP_WAVES")

        print(f"  [SIM] {test.name} seed={seed} [{index}/{test.count}]")
        print(f"  [LOG] {log_file}")

        result.start_time = datetime.now()
        try:
            with open(log_file, 'w') as f:
                proc = subprocess.run(sim_cmd, timeout=test.sim_timeout,
                                      stdout=f, stderr=subprocess.STDOUT)
            result.end_time = datetime.now()
            result.duration = (result.end_time - result.start_time).total_seconds()

            if proc.returncode == 0:
                with open(log_file, 'r') as f:
                    content = f.read()
                if 'UVM_FATAL' in content or 'UVM_ERROR' in content:
                    result.status = TestStatus.FAIL
                    result.error_message = "UVM_ERROR/UVM_FATAL in log"
                else:
                    result.status = TestStatus.PASS
            else:
                result.status = TestStatus.FAIL
                result.error_message = f"Exit code: {proc.returncode}"
        except subprocess.TimeoutExpired:
            result.status = TestStatus.TIMEOUT
            result.end_time = datetime.now()
            result.duration = test.sim_timeout
            result.error_message = f"Timeout {test.sim_timeout}s"

        # post_run
        env_vars['LOG_FILE'] = log_file
        ShellRunner.run_commands(test.post_run, env_vars, label="POST_RUN")

        self._print_result(result)
        return result

    def _print_result(self, result: TestResult):
        colors = {
            TestStatus.PASS: '\033[92m',
            TestStatus.FAIL: '\033[91m',
            TestStatus.TIMEOUT: '\033[93m',
            TestStatus.SKIP: '\033[90m',
        }
        reset = '\033[0m'
        color = colors.get(result.status, '')
        extra = f" [{result.index}/{result.count}]" if result.count > 1 else ""
        print(f"  [{color}{result.status.value:>8}{reset}] {result.test_name}{extra} "
              f"seed={result.seed} ({result.duration:.1f}s)")

    def print_summary(self):
        results = self.results
        total = len(results)
        passed = sum(1 for r in results if r.status == TestStatus.PASS)
        failed = sum(1 for r in results if r.status == TestStatus.FAIL)
        timeout = sum(1 for r in results if r.status == TestStatus.TIMEOUT)
        skipped = sum(1 for r in results if r.status == TestStatus.SKIP)

        print(f"\n{'='*60}")
        print("SUMMARY")
        print(f"{'='*60}")
        print(f"Total:   {total}")
        print(f"Passed:  {passed}")
        print(f"Failed:  {failed}")
        print(f"Timeout: {timeout}")
        print(f"Skipped: {skipped}")
        print(f"{'='*60}")

        if failed > 0:
            print("\nFailed tests:")
            for r in results:
                if r.status == TestStatus.FAIL:
                    print(f"  - {r.test_name} seed={r.seed}: {r.error_message}")


# ═══════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description='Regression Manager')
    parser.add_argument('-c', '--config', default='tests.yaml', help='YAML config file')
    parser.add_argument('--tags', help='Filter by tags (comma separated)')
    parser.add_argument('--test', help='Run specific test')
    parser.add_argument('--seed', type=int, help='Override seed')
    parser.add_argument('--builds', action='store_true', help='Compile all builds only')
    parser.add_argument('--force', action='store_true', help='Force recompile')
    parser.add_argument('--parallel', type=int, default=1, help='Parallel jobs')
    parser.add_argument('--list', action='store_true', help='List tests only')
    parser.add_argument('--dry-run', action='store_true', help='Dry run')
    args = parser.parse_args()

    # 加载配置
    cfg_mgr = ConfigManager(args.config)
    build_mgr = BuildManager(cfg_mgr)
    runner = TestRunner(cfg_mgr, build_mgr)

    # 选择测试
    if args.test:
        test = cfg_mgr.tests.get(args.test)
        if not test:
            print(f"Test '{args.test}' not found")
            sys.exit(1)
        if args.seed is not None:
            test.seed = args.seed
        tests = [test]
    elif args.tags:
        tags = [t.strip() for t in args.tags.split(',')]
        tests = cfg_mgr.get_tests_by_tags(tags)
        if not tests:
            print(f"No tests found for tags: {args.tags}")
            sys.exit(1)
    else:
        print("Specify --tags or --test")
        sys.exit(1)

    print(f"\nTests selected: {len(tests)}")
    for t in tests:
        print(f"  - {t.name} [{', '.join(t.tags)}] build={t.build} count={t.count}")

    if args.list or args.dry_run:
        return

    # 全局 pre_run
    defaults = cfg_mgr.defaults
    global_env = {'TIMESTAMP': datetime.now().strftime('%Y%m%d_%H%M%S')}
    ShellRunner.run_commands(
        ConfigManager._to_list(defaults.get('pre_run', [])), global_env, label="GLOBAL_PRE"
    )

    # 编译所有需要的 Build
    build_names = cfg_mgr.get_all_builds_for_tests(tests)
    build_mgr.compile_all(build_names, args.force)

    if args.builds:
        return

    # 运行测试
    if args.parallel > 1:
        with ProcessPoolExecutor(max_workers=args.parallel) as executor:
            futures = {executor.submit(runner.run_test, t): t for t in tests}
            for future in as_completed(futures):
                results = future.result()
                runner.results.extend(results)
    else:
        for t in tests:
            results = runner.run_test(t)
            runner.results.extend(results)

    # 全局 post_run
    ShellRunner.run_commands(
        ConfigManager._to_list(defaults.get('post_run', [])), global_env, label="GLOBAL_POST"
    )

    # 摘要
    runner.print_summary()

    # 退出码
    failed = sum(1 for r in runner.results if r.status == TestStatus.FAIL)
    sys.exit(0 if failed == 0 else 1)


if __name__ == '__main__':
    main()