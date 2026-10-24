#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import json
import argparse
import re
import logging

# 按**包路径**导入（本文件现在是 `src/tools/execution/regression_tools/regression.py`，
# 不再依赖 `regression_framwork/src` 那层历史布局的 sys.path 拼接）。
# 用法：`python -m src.tools.execution.regression_tools.regression --config <yaml> ...`
from src.tools.execution.regression_tools.regression_framework.core.config import (
    ConfigBuilder, make_tag_matcher, collect_tags, build_dependency_map,
    strip_test_prefix)
from src.tools.execution.regression_tools.regression_framework.core.exceptions import ConfigError
from src.tools.execution.regression_tools.regression_framework.core.logging_config import setup_logging, get_logger
from src.tools.execution.regression_tools.regression_framework.models.scheduler import Scheduler
from src.tools.execution.regression_tools.regression_framework.models.task import TaskFactory
from src.tools.execution.regression_tools.regression_framework.execution.strategy import MockStrategy, LocalStrategy, LsfStrategy
from src.tools.execution.regression_tools.regression_framework.generators.shell import ShellGenerator
from src.tools.execution.regression_tools.regression_framework.generators.makefile import MakefileGenerator

logger = get_logger(__name__)


def _run_reference_finder(args) -> None:
    """`--reference-finder`：在版本区间上二分，定位首个失败的提交。

    区间与用例默认读配置里的 `reference_finder:` 块（ExecMan 的 EMC 也是这么
    配的），命令行 flag 只是覆盖它 —— 这样一次排查的参数可以随配置一起进版本
    控制，而不是散在一次性的命令行里。

    真正的机制（worktree 隔离 / 环境快照 / 二分）在 L1，见
    `src/layers/l1_infrastructure/reference_finder.py`；这里只做「框架的配置
    面 → 机制」的翻译。
    """
    if not args.config:
        logger.error("--reference-finder 需要 --config（区间可以从配置里的 reference_finder 块读）")
        sys.exit(1)

    # 只读 reference_finder 块（连带 schema 校验），**不做完整渲染** ——
    # run_cmd 里会引用只在逐版本运行时才存在的 RF_* 变量，完整渲染会误报未定义
    try:
        rf = ConfigBuilder(args.config, args.set).load_reference_finder()
    except ConfigError as e:
        logger.error(f"配置错误: {e}")
        sys.exit(1)
    good = args.ref_good or rf.get('good')
    test = args.ref_test or rf.get('test')
    if not good or not test:
        logger.error("缺少 good / test：在配置里写 `reference_finder: {good: ..., test: ...}`，"
                     "或用 --ref-good / --ref-test 给出")
        sys.exit(1)
    bad = args.ref_bad or rf.get('bad') or 'HEAD'
    paths = ([p.strip() for p in args.ref_paths.split(',') if p.strip()]
             if args.ref_paths else (rf.get('paths') or None))
    mode = rf.get('mode') or ('mock' if args.mode == 'mock' else 'local')
    work_root = (args.ref_work_root or rf.get('work_root')
                 or os.path.join(args.repo_path or '.', 'reference_finder_work'))

    try:
        from src.layers.l1_infrastructure.reference_finder import ReferenceFinder
        finder = ReferenceFinder(
            repo_path=args.repo_path or '.', work_root=work_root,
            reg_yaml=os.path.abspath(args.config), test_pattern=test,
            mode=mode, overrides=args.set, keep_worktrees=False,
            use_cache=not args.ref_no_cache, verbose=True,
            debug_at_boundary=(args.ref_debug_at_boundary
                               or bool(rf.get('debug_at_boundary'))))
        report = finder.find_first_bad(good, bad, paths=paths)
    except Exception as e:
        logger.error(f"溯源失败: {type(e).__name__}: {e}")
        sys.exit(1)

    if report.get('culprit'):
        print(f"\n引入提交: {report.get('culprit_short')} {report.get('subject', '')}")
        print(f"  最后一个好版本: {report.get('last_good_short')}")
        print(f"  置信度: {report.get('confidence')}")
        if report.get('changed_files'):
            print("  改动文件: " + ", ".join(report['changed_files'][:8]))
    else:
        print(f"\n未能定位: {report.get('reason', '')}")
    for c in report.get('caveats') or []:
        print(f"  ! {c}")
    for x in report.get('inconclusive_revisions') or []:
        print(f"  ? {x['short']} inconclusive: {x['detail']}")
    print(f"\n结论: {os.path.join(work_root, 'reference_finder_summary.md')}")

# 会话文件：跑完落在输出根目录下，记录这次用的 config 路径与 run 元数据。
# `--reuse-config` 靠它把上次的 config 找回来，`--parent-session` 靠它记父子关联。
SESSION_FILE = '.regression_session.json'

def main():
    parser = argparse.ArgumentParser(description='Regression Framework v2.0')
    parser.add_argument('--config', help='YAML configuration file')
    parser.add_argument('--check', action='store_true',
                        help='Validate the YAML (syntax + schema) then exit')
    # ── Reference Finder（溯源定位）：框架自身的能力，不是外挂 ──
    # 「哪个提交引入了这个失败」。区间与用例默认取配置里的 `reference_finder:` 块，
    # 也可用下面的 flag 覆盖。
    parser.add_argument('--reference-finder', action='store_true',
                        help='溯源定位：在 good..bad 区间二分找出首个失败的提交')
    parser.add_argument('--ref-good', help='已知通过的提交（覆盖配置里的 reference_finder.good）')
    parser.add_argument('--ref-bad', default=None, help='已知失败的提交（默认 HEAD）')
    parser.add_argument('--ref-test', help='要复现的用例名/正则（覆盖 reference_finder.test）')
    parser.add_argument('--ref-paths', help='逗号分隔，只考虑这些路径下的提交')
    parser.add_argument('--ref-work-root',
                        help='工作目录（worktree 与结论落这里），默认 <repo>/reference_finder_work')
    parser.add_argument('--ref-no-cache', action='store_true', help='忽略结论缓存，强制重跑')
    parser.add_argument('--ref-debug-at-boundary', action='store_true',
                        help='定位到之后，在边界两个版本上补跑 Debug Run（产出对比素材）')
    parser.add_argument('--action', choices=['generate', 'run', 'all'], default='all')
    # **默认 local**：本工具默认在本机跑，不往服务器投递。要上集群得显式
    # `--mode lsf`（配套 --lsf-* 参数），不存在"没选就默默提交"的路径。
    parser.add_argument('--mode', choices=['mock', 'local', 'lsf'], default='local',
                        help='Where to run: local=this machine (default) / lsf=submit to LSF cluster / mock=generate only')
    parser.add_argument('--input-dir', help='Root directory to run')
    parser.add_argument('--output-dir', help='Output directory')
    parser.add_argument('--backend', choices=['shell', 'makefile'], default='shell')
    parser.add_argument('--build-only', action='store_true')
    parser.add_argument('--test-only', action='store_true')
    # Debug Run：走 `debug_run_cmd`（开波形、放详细日志），比普通跑慢得多，
    # 只在要给调试分析提供素材时才用。ExecMan 的「备用命令字段」矩阵里的一维。
    parser.add_argument('--debug-run', action='store_true',
                        help='调试跑法：用 debug_run_cmd / ref_debug_run_cmd')
    parser.add_argument('--lsf-queue', default='normal')
    parser.add_argument('--lsf-project')
    parser.add_argument('--lsf-resource', default='rusage[mem=4096]')
    parser.add_argument('--lsf-max-jobs', type=int, default=0,
                        help='Max concurrent LSF test jobs (0 = unlimited, submit all at once)')
    parser.add_argument('--lsf-report-interval', type=int, default=60,
                        help='Seconds between LSF job polls (default: 60)')
    parser.add_argument('--tests', help='Comma-separated test names or regex patterns')
    parser.add_argument('--exclude-tests', help='Comma-separated test names or regex patterns to exclude')
    parser.add_argument('--builds', help='Comma-separated build names to filter')
    parser.add_argument('--tag', '--tags', dest='tags',
                        help='Comma-separated tags to include (test kept if it has ANY of them)')
    parser.add_argument('--exclude-tags', help='Comma-separated tags to exclude (takes precedence over --tags)')
    parser.add_argument('--prune-tests', action='store_true',
                        help='Generate only the test directories matching --tags/--exclude-tags '
                             '(分级回归的 L1 路径默认这么做；手工调用需要显式打开)')
    parser.add_argument('--show-tags', action='store_true',
                        help='List all tags defined in the configuration file, then exit')
    parser.add_argument('--show-tests', action='store_true',
                        help='List tests of each tag (or only of --tags if given), then exit')
    parser.add_argument('--enable', '--enable-modes', dest='enable_modes',
                        help='Comma-separated mode names to enable (keys of the `modes:` block)')
    parser.add_argument('--reuse-config', action='store_true',
                        help='Reuse the config saved by a previous session (read from --input-dir)')
    parser.add_argument('--parent-session',
                        help='Parent session name to associate this rerun session with')
    parser.add_argument('--parallel-builds', type=int, default=1)
    parser.add_argument('--incremental', action='store_true')
    parser.add_argument('--repo-path', default='.')
    parser.add_argument('--rerun-failed', help='Rerun failed tests from previous run')
    parser.add_argument('--set', action='append', help='Override config key=value')
    parser.add_argument('--log-file', help='Log file path')
    parser.add_argument('--dry-run', action='store_true', help='Print tasks without executing')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    parser.add_argument('--performance-threshold', type=float, default=0.2,
                    help='Performance degradation threshold (default: 0.2 = 20% slower)')
    args = parser.parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    setup_logging(args.log_file, log_level)

    if args.reference_finder:
        _run_reference_finder(args)
        return

    if args.rerun_failed:
        import shutil
        src_root = args.rerun_failed
        if not os.path.isdir(src_root):
            logger.error(f"{src_root} is not a valid directory")
            sys.exit(1)
        report_file = os.path.join(src_root, 'report_summary.txt')
        if not os.path.exists(report_file):
            logger.error(f"report_summary.txt not found in {src_root}")
            sys.exit(1)
        failed_dirs = []
        with open(report_file, 'r', encoding='utf-8') as f:
            for line in f:
                if line.startswith('fail'):
                    parts = line.split()
                    if len(parts) >= 4:
                        wd = parts[3].strip('()')
                        if os.path.exists(wd):
                            failed_dirs.append(wd)
        if not failed_dirs:
            logger.info("No failed tests found.")
            return
        new_root = args.output_dir or f"rerun_failed_{__import__('datetime').datetime.now().strftime('%Y%m%d_%H%M%S')}"
        new_root = new_root.replace(' ', '_')
        os.makedirs(new_root, exist_ok=True)
        build_paths = {os.path.dirname(wd) for wd in failed_dirs}
        for build_dir in build_paths:
            build_name = os.path.basename(build_dir)
            new_build = os.path.join(new_root, build_name)
            os.makedirs(new_build, exist_ok=True)
            for f in os.listdir(build_dir):
                if f.endswith('.sh'):
                    shutil.copy2(os.path.join(build_dir, f), new_build)
            for wd in failed_dirs:
                if os.path.dirname(wd) == build_dir:
                    test_name = os.path.basename(wd)
                    new_test = os.path.join(new_build, test_name)
                    os.makedirs(new_test, exist_ok=True)
                    for f in os.listdir(wd):
                        if f.endswith('.sh'):
                            shutil.copy2(os.path.join(wd, f), new_test)
        logger.info(f"✅ Copied {len(failed_dirs)} failed tests to {new_root}")
        return

    # ── 会话：--reuse-config 从上次跑完留下的会话文件里找回 config 路径 ──
    # 本地单机场景没有服务端会话库，就落在输出根目录下一个 json 里（见文件末尾写回）。
    session_path = None
    _session_root = args.input_dir or args.output_dir
    if _session_root:
        session_path = os.path.join(_session_root, SESSION_FILE)
    if args.reuse_config:
        if args.config:
            logger.info("--reuse-config 与 --config 同时给出，以 --config 为准。")
        elif session_path and os.path.exists(session_path):
            with open(session_path, encoding='utf-8') as f:
                saved = json.load(f)
            saved_cfg = saved.get('config_path')
            if saved_cfg and os.path.exists(saved_cfg):
                args.config = saved_cfg
                logger.info(f"--reuse-config: 复用上次会话的配置 {saved_cfg}")
            else:
                logger.error(f"--reuse-config: 会话里的 config_path 已失效（{saved_cfg}）；请显式给 --config")
                sys.exit(1)
        else:
            logger.error(f"--reuse-config: 找不到会话文件 {session_path or '<需要 --input-dir 或 --output-dir>'}；请显式给 --config")
            sys.exit(1)

    # ── 只读命令：--check / --show-tags / --show-tests ──
    # 三个都只需要 --config，不该被 --action 的校验挡住，所以放在它前面。
    if args.check or args.show_tags or args.show_tests:
        if not args.config:
            logger.error("--check / --show-tags / --show-tests 需要 --config")
            sys.exit(1)
        try:
            _cfg = ConfigBuilder(args.config, args.set).build(
                incremental=args.incremental, repo_path=args.repo_path,
                enabled_modes=args.enable_modes)
        except ConfigError as e:
            # --check 是给 CI 的 lint 入口，校验失败要一条干净的错误 + 退出码 1，
            # 不要把 jsonschema 的栈打出来。
            logger.error(f"配置校验失败: {e}")
            sys.exit(1)

        if args.check:
            print(f"OK: {_cfg.get('config_name') or args.config} - "
                  f"{len(_cfg.get('builds') or [])} builds / {len(_cfg.get('tests') or [])} tests")
            return

        tags_map = collect_tags(_cfg)
        if args.show_tags:
            if not tags_map:
                print("(no tags defined)")
            for tag in sorted(tags_map):
                print(f"{tag}\t{len(tags_map[tag])}")
            return

        # --show-tests：按 tag 分组列出用例；给了 --tags 就只列那几组。
        want = {t.strip() for t in (args.tags or '').split(',') if t.strip()}
        drop = {t.strip() for t in (args.exclude_tags or '').split(',') if t.strip()}
        shown = 0
        for tag in sorted(tags_map):
            if (want and tag not in want) or tag in drop:
                continue
            print(f"[{tag}] {', '.join(tags_map[tag])}")
            shown += 1
        if not shown:
            print("(no matching tags)")
        return

    if args.build_only and args.test_only:
        logger.error("--build-only and --test-only cannot be used together")
        sys.exit(1)

    if args.action in ('run', 'all') and not args.config and not args.input_dir:
        logger.error("Provide --config or --input-dir for run/all")
        sys.exit(1)
    if args.action in ('generate', 'all') and not args.config:
        logger.error("Provide --config for generate/all")
        sys.exit(1)

    generated_dir = None
    config = None

    if args.action in ('generate', 'all'):
        root_dir = args.output_dir or f"regression_{args.mode}_{__import__('datetime').datetime.now().strftime('%Y%m%d_%H%M%S')}"
        root_dir = root_dir.replace(' ', '_')
        if args.backend == 'shell':
            generator = ShellGenerator()
        else:
            generator = MakefileGenerator()
        try:
            builder = ConfigBuilder(args.config, args.set)
            config = builder.build(incremental=args.incremental, repo_path=args.repo_path,
                                   enabled_modes=args.enable_modes)
            # `run_cmd` 是延迟到生成器里渲染的（那里才有 local_vars），所以未定义
            # 变量的报错会从 generate 里抛出来 —— 两个阶段一起包。
            #
            # `--prune-tests`：按 tag 裁剪**生成的目录**（默认不裁，保留全量树；
            # 分级回归走 L1 时默认裁剪，见 `infrastructure.run_regression`）。
            gen_filter = None
            if args.prune_tests and (args.tags or args.exclude_tags):
                if args.backend != 'shell':
                    logger.warning("--prune-tests 只支持 shell 后端；"
                                   "makefile 后端仍生成全量 test 目录。")
                else:
                    gen_filter = make_tag_matcher(config, args.tags, args.exclude_tags)
            if gen_filter is not None:
                generator.generate(config, root_dir, args.mode,
                                   debug_mode=args.debug_run, test_filter=gen_filter)
            else:
                generator.generate(config, root_dir, args.mode,
                                   debug_mode=args.debug_run)
        except ConfigError as e:
            # 配置本身有问题（变量引用未定义 / 模板语法错误 / schema 不合法）——
            # 这是给人看的错误，一条消息 + 退出码 1，不要甩 jsonschema/jinja 的栈。
            logger.error(f"配置错误: {e}")
            sys.exit(1)
        logger.info(f"Generation completed. Output: {root_dir}")
        if args.action == 'generate' and (args.tags or args.exclude_tags):
            if args.prune_tests:
                logger.info("已按 --tags 裁剪生成的 test 目录（--prune-tests）。")
            else:
                # 默认不裁剪：留着全部 test 目录，之后能用不同 --tags 复跑同一份
                # 树（`--action run --input-dir <root>`）。过滤在 run 阶段做。
                logger.info("--tags/--exclude-tags 只在 run 阶段生效；本次 generate 仍生成"
                            "全部 test 目录（要裁剪加 --prune-tests）。")
        generated_dir = root_dir
        if args.action == 'generate':
            return

    if args.action in ('run', 'all'):
        if args.action == 'all' and not args.input_dir and generated_dir:
            args.input_dir = generated_dir
        root_dir = args.input_dir or args.output_dir
        if not root_dir or not os.path.isdir(root_dir):
            logger.error(f"Invalid input directory: {root_dir}")
            sys.exit(1)

        if args.mode == 'mock':
            strategy = MockStrategy()
        elif args.mode == 'local':
            strategy = LocalStrategy()
        elif args.mode == 'lsf':
            strategy = LsfStrategy(queue=args.lsf_queue, project=args.lsf_project, resource=args.lsf_resource)
        else:
            logger.error(f"Unknown mode: {args.mode}")
            sys.exit(1)

        state_file = os.path.join(root_dir, '.regression_state.json')
        scheduler = Scheduler(strategy,
                            build_only=args.build_only,
                            test_only=args.test_only,
                            parallel_builds=args.parallel_builds,
                            state_file=state_file,
                            dry_run=args.dry_run,
                            performance_threshold=args.performance_threshold,
                            lsf_report_interval=args.lsf_report_interval,
                            lsf_max_jobs=args.lsf_max_jobs)
        build_dirs = [d for d in os.listdir(root_dir) if d.startswith('build_') and os.path.isdir(os.path.join(root_dir, d))]
        build_dirs.sort()
        
        test_patterns = [re.compile(p.strip()) for p in args.tests.split(',')] if args.tests else None
        exclude_patterns = [re.compile(p.strip()) for p in args.exclude_tests.split(',')] if args.exclude_tests else None
        build_filter = set(args.builds.split(',')) if args.builds else None

        # tag 过滤：tags 只存在 yaml 里、生成目录不带，所以必须拿到 config 才能解析。
        # `--action all`（默认）时上面已经建好了；只 `--action run` 时靠再解析一次
        # `--config`。两者都没有（纯 --input-dir 跑一个已有的目录）就没法过滤，出声提醒。
        tag_match = None
        if args.tags or args.exclude_tags:
            cfg = config
            if cfg is None and args.config:
                cfg = ConfigBuilder(args.config, args.set).build(
                    incremental=args.incremental, repo_path=args.repo_path,
                    enabled_modes=args.enable_modes)
            if cfg is None:
                logger.warning("--tags/--exclude-tags 需要 --config 才能解析（`--action run` 只给 "
                               "--input-dir 时无法知道 test 的 tag），本次不过滤。")
            else:
                tag_match = make_tag_matcher(cfg, args.tags, args.exclude_tags)
                logger.info(f"Tag filter: include={args.tags or '-'} exclude={args.exclude_tags or '-'}")

        # build 依赖：yaml 的 `depends` → 任务依赖图（没有 config 时无从得知，退化成无依赖）
        build_deps = build_dependency_map(config) if config else {}

        added_builds = set()
        for build_dir in build_dirs:
            build_path = os.path.join(root_dir, build_dir)
            build_name = build_dir.replace('build_', '')
            if build_filter and build_name not in build_filter:
                continue
            test_dirs = [d for d in os.listdir(build_path) if d.startswith('test_') and os.path.isdir(os.path.join(build_path, d))]
            test_dirs.sort()
            filtered_tests = []
            for test_dir in test_dirs:
                test_name = strip_test_prefix(test_dir)
                if tag_match and not tag_match(test_name):
                    continue
                if test_patterns:
                    matched = any(p.search(test_name) for p in test_patterns)
                    if not matched:
                        continue
                if exclude_patterns:
                    excluded = any(p.search(test_name) for p in exclude_patterns)
                    if excluded:
                        continue
                filtered_tests.append(test_dir)
            if filtered_tests:
                if build_name not in added_builds:
                    build_task = TaskFactory.create_build_task(
                        build_name, build_path, build_deps.get(build_name, []))
                    scheduler.add_task(build_task)
                    added_builds.add(build_name)
                for test_dir in filtered_tests:
                    test_name = strip_test_prefix(test_dir)
                    test_path = os.path.join(build_path, test_dir)
                    test_task = TaskFactory.create_test_task(test_name, test_path, build_name)
                    scheduler.add_task(test_task)
        
        scheduler.run(root_dir)

        # ── 会话落盘：把这次用的 config 和统计写进输出目录 ──
        # 供下一轮 `--reuse-config`（找回 config，省得再写一遍 --config）和
        # `--parent-session`（把重跑批次挂到原会话上）用。
        try:
            stats = {'pass': 0, 'fail': 0, 'unknown': 0}
            for task in scheduler.tasks:
                stats[task.status] = stats.get(task.status, 0) + 1
            session = {
                'session_id': os.path.basename(os.path.abspath(root_dir)),
                'config_path': os.path.abspath(args.config) if args.config else None,
                'mode': args.mode,
                'parent_session': args.parent_session,
                'counts': stats,
            }
            with open(os.path.join(root_dir, SESSION_FILE), 'w', encoding='utf-8') as f:
                json.dump(session, f, ensure_ascii=False, indent=2)
            logger.info(f"Session saved: {os.path.join(root_dir, SESSION_FILE)}")
        except Exception as e:
            logger.warning(f"会话文件写入失败（不影响回归结果）: {e}")

if __name__ == '__main__':
    main()