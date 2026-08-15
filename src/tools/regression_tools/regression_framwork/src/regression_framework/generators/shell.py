# src/regression_framework/generators/shell.py
import os
import shutil
from jinja2 import Template
from ..core.logging_config import get_logger

logger = get_logger(__name__)

class ShellGenerator:
    def __init__(self):
        self.context = {}
        self.settings = {}
        self.simulators = {}
        self.default_sim = 'vcs'
        self.default_build = 'build_base'
        self.hooks_global = {}

    def generate(self, config: dict, root_dir: str, mode: str):
        self.context = config.get('global_vars', {}).copy()
        self.context.update(os.environ)
        self.settings = config.get('settings', {})
        self.simulators = self.settings.get('simulators', {})
        self.default_sim = self.settings.get('default_simulator', 'vcs')
        self.default_build = self.settings.get('default_build', 'build_base')
        self.hooks_global = self.settings.get('hooks', {})

        os.makedirs(root_dir, exist_ok=True)
        logger.info(f"Creating shell scripts in {root_dir} (mode={mode})")

        builds = self._collect_builds(config)
        for build_name, build_conf in builds.items():
            self._generate_build(build_name, build_conf, root_dir, mode, config)

        if mode in ('mock', 'local'):
            self._generate_run_all(root_dir, mode, builds)

    def _collect_builds(self, config):
        builds = {}
        for test in config.get('tests', []):
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
        for b in config.get('builds', []):
            name = b.get('name')
            if not name:
                continue
            if name not in builds or not builds[name]:
                # 覆盖空占位符或新增
                builds[name] = b
            else:
                # 合并：已有的 inline build 可能只有部分字段
                existing = builds[name]
                if isinstance(existing, dict):
                    merged = b.copy()
                    merged.update(existing)
                    builds[name] = merged
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

        build_tests = [t for t in config.get('tests', []) if t.get('build') == build_name]
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
        """生成 sim.sh，包含波形索引和性能计时"""
        with open(os.path.join(test_dir, 'sim.sh'), 'w', encoding='utf-8') as f:
            f.write("#!/bin/bash\n")
            if mode == 'mock':
                f.write(f"echo \"[MOCK] Test: {test_name} (seed={seed})\"\n")
                f.write(f"echo \"  {sim_cmd}\"\n")
            else:
                # 定义波形目录和文件路径
                wave_dir = os.path.join(test_dir, 'waves')
                wave_file = os.path.join(wave_dir, f"{test_name}.fsdb")
                f.write(f"mkdir -p {wave_dir}\n")
                # 计时并运行仿真
                f.write(f"start_time=$(date +%s.%N)\n")
                f.write(f"{sim_cmd} > sim.log 2>&1\n")
                f.write(f"ret=$?\n")
                f.write(f"end_time=$(date +%s.%N)\n")
                # 计算仿真耗时（用 python 而非 bc——Windows Git Bash 无 bc 命令）
                f.write(f"sim_time=$(python -c \"print($end_time - $start_time)\" 2>/dev/null || echo 0)\n")
                f.write(f"echo \"SIM_TIME=$sim_time\" > sim_time.log\n")
                # 如果失败，记录波形路径
                f.write(f"if [ $ret -ne 0 ]; then\n")
                f.write(f"    if [ -f {wave_file} ]; then\n")
                f.write(f"        echo \"WAVE_PATH={wave_file}\" > wave.log\n")
                f.write(f"    else\n")
                f.write(f"        echo \"WAVE_PATH=NOT_FOUND\" > wave.log\n")
                f.write(f"    fi\n")
                f.write(f"fi\n")
                f.write(f"exit $ret\n")
        os.chmod(os.path.join(test_dir, 'sim.sh'), 0o755)

    def _generate_run_all(self, root_dir, mode, builds):
        fname = 'run_all_mock.sh' if mode == 'mock' else 'run_all_local.sh'
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