#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import argparse
import re
import logging

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from regression_framework.core.config import ConfigBuilder
from regression_framework.core.logging_config import setup_logging, get_logger
from regression_framework.models.scheduler import Scheduler
from regression_framework.models.task import TaskFactory
from regression_framework.execution.strategy import MockStrategy, LocalStrategy, LsfStrategy
from regression_framework.generators.shell import ShellGenerator
from regression_framework.generators.makefile import MakefileGenerator

logger = get_logger(__name__)

def main():
    parser = argparse.ArgumentParser(description='Regression Framework v2.0')
    parser.add_argument('--config', help='YAML configuration file')
    parser.add_argument('--action', choices=['generate', 'run', 'all'], default='all')
    parser.add_argument('--mode', choices=['mock', 'local', 'lsf'], default='mock')
    parser.add_argument('--input-dir', help='Root directory to run')
    parser.add_argument('--output-dir', help='Output directory')
    parser.add_argument('--backend', choices=['shell', 'makefile'], default='shell')
    parser.add_argument('--build-only', action='store_true')
    parser.add_argument('--test-only', action='store_true')
    parser.add_argument('--lsf-queue', default='normal')
    parser.add_argument('--lsf-project')
    parser.add_argument('--lsf-resource', default='rusage[mem=4096]')
    parser.add_argument('--tests', help='Comma-separated test names or regex patterns')
    parser.add_argument('--exclude-tests', help='Comma-separated test names or regex patterns to exclude')
    parser.add_argument('--builds', help='Comma-separated build names to filter')
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

    if args.action in ('generate', 'all'):
        builder = ConfigBuilder(args.config, args.set)
        config = builder.build(incremental=args.incremental, repo_path=args.repo_path)
        root_dir = args.output_dir or f"regression_{args.mode}_{__import__('datetime').datetime.now().strftime('%Y%m%d_%H%M%S')}"
        root_dir = root_dir.replace(' ', '_')
        if args.backend == 'shell':
            generator = ShellGenerator()
        else:
            generator = MakefileGenerator()
        generator.generate(config, root_dir, args.mode)
        logger.info(f"Generation completed. Output: {root_dir}")
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
                            performance_threshold=args.performance_threshold)
        build_dirs = [d for d in os.listdir(root_dir) if d.startswith('build_') and os.path.isdir(os.path.join(root_dir, d))]
        build_dirs.sort()
        
        test_patterns = [re.compile(p.strip()) for p in args.tests.split(',')] if args.tests else None
        exclude_patterns = [re.compile(p.strip()) for p in args.exclude_tests.split(',')] if args.exclude_tests else None
        build_filter = set(args.builds.split(',')) if args.builds else None
        
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
                test_name = test_dir.replace('test_', '')
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
                    build_task = TaskFactory.create_build_task(build_name, build_path)
                    scheduler.add_task(build_task)
                    added_builds.add(build_name)
                for test_dir in filtered_tests:
                    test_name = test_dir.replace('test_', '')
                    test_path = os.path.join(build_path, test_dir)
                    test_task = TaskFactory.create_test_task(test_name, test_path, build_name)
                    scheduler.add_task(test_task)
        
        scheduler.run(root_dir)

if __name__ == '__main__':
    main()