"""
InfrastructureManager — L1 基础设施层：统一管理三大件。

三件套（文件系统 / Git 仓库 / 覆盖率数据库）的协同，是"可复现、可审计、可追溯"的根基：

  1. 文件系统
     - 工作区（output_root）：每次 run 的产物，可丢弃，git ignore
     - 归档区（.signoffai/）：覆盖率数据库归档 + 版本清单，持久
  2. Git 仓库
     - 源代码（RTL/TB 生成器）版本化，覆盖率达标时打 tag
     - 产物不进 git，但用哈希关联到 tag（version_manifest.json）
  3. 覆盖率数据库（.ucdb / .vdb）
     - 几十 GB 不进 git，归档到 .signoffai/coverage_archive/，用硬链接避免复制
     - 每轮记录 SHA256，复现时回滚比对；LLM 只读降采样后的 text 汇总

用法:
    from src.layers.l1_infrastructure.infrastructure import InfrastructureManager
    infra = InfrastructureManager(output_root)
    infra.setup()
    ...
    infra.archive_coverage(round_num, ucdb_path)
    infra.write_version_manifest({...})
    infra.git_tag("v1.0", "coverage 95%")
    result = infra.verify_reproducible()
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

# 运行目录布局 —— **写端的落点也走契约**（`regression_run` 那一层叫什么、在哪）。
# 这里以前拼 `self.output_root / "regression_run"`，读端另拼一份，改一处漏一处。
from src.layers.l1_infrastructure import layout

logger = structlog.get_logger()



from .infra_helpers import (
    _strip_test_prefix_local,
    sha256_file,
    is_elab_failure_line,
    collect_hung_tests,
    classify_sim_failures,
    declared_tests_by_build,
    _stage_tests,
    logger,
)


class RegressionStageMixin:
    #: 分级回归的顺序与门控（第 4 位 = 这一级是否需要人工放行）。
    #: **一处定义**：`run_regression_staged` / `_stage_gates` / layout 都从它推。
    #: 3.0 拆文件时这一段丢了 → ops 直接 FAIL（实测 `'InfrastructureManager'
    #: object has no attribute 'REGRESSION_STAGES'`）。恢复原位。
    REGRESSION_STAGES = (
        ("loopback", "agent loopback 自检（SCB 必须全 match）", "loopback", True),
        ("p0", "P0 功能", "p0", False),
        ("p1", "P1 次功能（边界 + corner）", "p1", False),
        ("p2", "P2 压力", "p2", False),
        ("p3", "P3 错误 + 随机", "p3", False),
    )

    def run_regression(self, reg_yaml: str = None, mode: str = "local",
                       tests: str = None, tags: str = None,
                       exclude_tags: str = None,
                       overrides: list = None,
                       reference_mode: bool = False,
                       debug_mode: bool = False,
                       enabled_modes=None) -> dict:
        """L1 统一入口：吃 regression.yaml 批量跑回归 case（通过回归框架）。

        回归框架（regression_framwork）是成熟的执行器：ConfigBuilder 解析 yaml
        → ShellGenerator 生成脚本 → Scheduler 批量跑 build + test（每个 test 一个 case）。
        这里是 L1 对它的统一封装——上层（RegressionRunTool / ops agent）走这里，
        不各自散落调用回归框架。

        `enabled_modes`：这一轮要开的**仿真业务**（`cov` / `wave` / `debug_all` …，
        见 `src/layers/l2_orchestration/regression_tools/sim_modes.py`）。交给框架的
        `ConfigBuilder.build(enabled_modes=…)` → `apply_modes()` 把它落成聚合变量
        `MODE_OPTS`，仿真命令里的 `{{ MODE_OPTS }}` 就有了内容。
        不传 = 一门业务都不开（命令与从前逐字节一致）。

        返回 {status, passed, failed, unknown, total, report_path}。
        """
        reg_yaml = reg_yaml or str(self.output_root / "inputs" / "yaml" / "regression.yaml")
        if not Path(reg_yaml).exists():
            return {"status": "FAIL", "error": f"regression.yaml not found: {reg_yaml}"}

        try:
            # ── 0. 生成完整 filelist（UVM 环境此时已由 jinja_render 生成）──
            # regression.yaml 的 compile 命令引用 filelist.f，但 find_spec_yaml 生成
            # regression.yaml 时 agents/env/bench 尚未生成，故这里重新生成完整 filelist。
            try:
                from src.tools.common.lib.filelist import (build_filelist_for_tb,
                                                    derive_env_name)
                # 别在这里手写"取第一个 *_pkg.sv" —— 子包 `_parameters_pkg` 按字母序
                # 排在环境包前面，会把环境名猜错（见 `derive_env_name` 的说明）。
                env_name = derive_env_name(self.output_root)
                agents = []
                agents_dir = self.output_root / "agents"
                if agents_dir.exists():
                    agents = [{"name": d.name} for d in agents_dir.iterdir() if d.is_dir()]
                build_filelist_for_tb(self.output_root, agents, env_name, "filelist.f")
                # loopback filelist：每个 agent 一个 filelist_<ag>_lb.f，供 per-agent loopback build 编译
                try:
                    from src.tools.common.lib.filelist import build_loopback_filelist
                    for ag in agents:
                        build_loopback_filelist(self.output_root, ag["name"])
                except Exception as _lb_e:
                    logger.warning(f"loopback filelist 生成失败: {_lb_e}")
            except Exception as e:
                logger.warning(f"filelist 生成失败: {e}")

            # ── 1. ConfigBuilder 解析 regression.yaml（builds + tests）──
            from src.layers.l2_orchestration.regression_tools.regression_framework.core.config import (
                ConfigBuilder, make_tag_matcher)
            # `overrides` 是 `--set key=value` 那套：Reference Finder 逐版本重跑时，
            # 用它把配置里的绝对路径（WORK / filelist 之类）改写到**该版本自己的**
            # 工作目录 —— 不改写的话每个版本都会用同一份产物，等于没换版本。
            builder = ConfigBuilder(reg_yaml, overrides)
            # `enabled_modes` 必须在 `build()` 里落地：它写的是 `variables`，而
            # `variables` 是渲染上下文的一部分 —— 晚一步 `{{ MODE_OPTS }}` 就已经
            # 被渲染成空串了（框架 `build()` 里的注释也点了这一条）。
            config = builder.build(enabled_modes=enabled_modes)
            if enabled_modes:
                logger.info(f"仿真业务模式: {enabled_modes} → "
                            f"MODE_OPTS={config.get('variables', {}).get('MODE_OPTS', '')}")
            # tag 过滤判定（tags 只存在于 yaml，生成目录不带，所以必须从这里出）
            tag_match = make_tag_matcher(config, tags, exclude_tags)
            if tag_match:
                logger.info(f"回归 tag 过滤: include={tags or '-'} exclude={exclude_tags or '-'}")

            # ── 2. ShellGenerator 生成 build_*/test_* 目录 + 脚本 ──
            from src.layers.l2_orchestration.regression_tools.regression_framework.generators.shell import ShellGenerator
            # 分级回归时每级各占一个子目录（`run_regression_staged` 会设
            # `self._stage_tag`）。**否则每级都会 rmtree 掉整个 regression_run** ——
            # 全绿之后盘上只剩最后一级（p3）的 4 条，p0/p1/p2 跑过的日志/波形/
            # 覆盖率全没了（实测：28 个用例目录里只有 3 个有 sim.log）。
            # 分级回归的意义就是**每级的证据**，不能互相冲掉。
            # 非分级调用（`_stage_tag` 未设）路径与从前逐字节一致。
            root_dir = layout.regression_root(self.output_root)
            if getattr(self, "_stage_tag", ""):
                root_dir = root_dir / self._stage_tag
            root_dir = str(root_dir)
            # 清理**本级**上一次回归残留（state_file 会导致断点续跑跳过所有已完成任务）
            import shutil as _shutil
            if os.path.isdir(root_dir):
                _shutil.rmtree(root_dir, ignore_errors=True)
            # reference_mode：跑历史/参考版本时走 `ref_run_cmd`；
            # debug_mode：走 `debug_run_cmd` / `ref_debug_run_cmd`（见 shell.py 的矩阵）
            # **分级回归：每级的 build 目录只生成本级 tag 的用例。**
            #
            # 不裁剪时每次 build 都会铺全量脚本（实测 p0 目录 244 个 `sim.sh`，
            # 只跑 50 个），看起来像"大量用例没跑"。裁剪之后 `本级未跑` 与
            # `其它级预生成` 的歧义从源头消失 —— 目录里就是这一级要跑的。
            #
            # **只对分级路径生效**（`_stage_tag` 非空）。非分级调用保存原行为：
            # 生成全量树，之后可以换不同 `--tags` 复跑同一份目录。
            ShellGenerator().generate(
                config, root_dir, mode,
                reference_mode=reference_mode, debug_mode=debug_mode,
                test_filter=tag_match if getattr(self, "_stage_tag", "") else None,
                # 用例身份从 `<run>/coverage/testpoints.yaml` 反查 tp_id；
                # `root_dir` 是 `<run>/regression_run[/<stage>]`，不能往上猜。
                run_root=self.output_root)

            # ── 3. Scheduler 批量跑 build + test（扫描生成目录）──
            from src.layers.l2_orchestration.regression_tools.regression_framework.models.scheduler import Scheduler
            from src.layers.l2_orchestration.regression_tools.regression_framework.execution.strategy import LocalStrategy, MockStrategy
            from src.layers.l2_orchestration.regression_tools.regression_framework.models.task import TaskFactory
            import re as _re

            strategy = LocalStrategy() if mode == "local" else MockStrategy()
            # 不传 state_file：每次回归全新跑（不跨 run 续跑，避免第二轮跳过所有任务）
            #
            # **parallel_builds=1：本地回归串行跑。**
            # 并行跑多个 vsim 时，Questa 的 DPI trampoline 会在共享临时目录里撞车，
            # 后启动的那个直接挂：
            #   "Error: (vsim-3193) Load of ...\export_tramp.dll failed"
            #   "Fatal: (vsim-3772) Failed to load DPI trampoline shared library file"
            # 表现是**随机几条 case 假失败**（单独重跑同一条就过），会污染整轮结论。
            # 25 条 case 串行也就 ~80s，用确定性换这点时间值。
            # （非 LSF 策略下 Scheduler 的并行度就是 parallel_builds，见
            #   `_get_dynamic_parallelism`。）
            scheduler = Scheduler(strategy, parallel_builds=1)
            test_patterns = [_re.compile(p.strip()) for p in tests.split(",")] if tests else None

            # ── 只跑「这条 test 声明给这个 build」的组合 ──
            #
            # ShellGenerator 会给**每一个 build 目录**都生成**所有 test 的脚本目录**
            # （loopback 的 test 也会出现在 DUT build 下）。无差别地把它们都排进调度，
            # 就会跑出一堆跑不了的组合：那些目录里是给**另一个 top** 用的脚本，
            # 一跑就是 "Error loading design"，框架记成 `unknown`。
            #
            # 后果不止是多两条 unknown：`_elab_fail` 检测会在它们的 sim 日志里
            # 看到 "Error loading design"，于是**整轮回归被判成"编译级失败"**
            # （`compile: FAIL` / `elaboration_failed`），闭环被路由去
            # `debug_compile`（COMPILE_RETRY），**覆盖率阶段整段跳过** —— 覆盖率恒为 0%。
            # 实测踩过。
            #
            # ── 这张表为什么现在必须**无条件**生效 ──
            # 生成的 regression.yaml 现在 `include:` 了 `common_base.yaml`（仿真业务
            # 模式表的来源），那份文件自带 4 个 `VCS …` 的 build。它们没有任何 test
            # 挂在上面，所以这里必须把它们挡在调度外 —— 一旦漏进去，跑的就是
            # `VCS: command not found`，整轮回归连一条真 case 都跑不出来。
            #
            # 表从**已经建好的 `config`** 取，不再自己 `yaml.safe_load` 那份文件：
            #  · safe_load 不解析 include，取到的只是本地 tests —— 结果虽对，却是
            #    "恰好对"；config 是 ShellGenerator 实际吃进去的那份，目录名与它
            #    同源，对得上是对得上**在构造上**；
            #  · 原来解析失败时"退回跑全部 test 目录"的分支，在 include 之后会变成
            #    一颗地雷（解析一挂就去跑 VCS 的 build）。用 config 就没有这个分支了。
            tests_by_build: Dict[str, set] = declared_tests_by_build(config)

            build_dirs = sorted([d for d in os.listdir(root_dir)
                                 if d.startswith("build_") and os.path.isdir(os.path.join(root_dir, d))])
            # build 依赖：yaml 的 `depends` → 调度器的依赖图（名字已规整成任务名）
            from src.layers.l2_orchestration.regression_tools.regression_framework.core.config import (
                build_dependency_map)
            build_deps = build_dependency_map(config)
            added_builds = set()
            total_tests = 0
            for build_dir in build_dirs:
                build_path = os.path.join(root_dir, build_dir)
                build_name = build_dir.replace("build_", "")
                declared = tests_by_build.get(build_name, set())
                if not declared:
                    # 没有任何 test 声明给这个 build（如 common_base.yaml 带进来的
                    # 那几个 VCS build）—— 整目录跳过，连 build 任务都不排。
                    logger.debug(f"跳过无 test 声明的 build: {build_name}")
                    continue
                test_dirs = sorted([d for d in os.listdir(build_path)
                                    if d.startswith("test_") and os.path.isdir(os.path.join(build_path, d))])
                # 诊断：三道门（模式 / tag / 声明归属）逐个筛之前，先把"声明了什么、
                # 目录里实际有什么"摊开 —— 全被筛空时，这一行直接指出是哪边对不上。
                logger.info(f"[挑用例] build={build_name} declared={sorted(declared)} "
                            f"dirs={[_strip_test_prefix_local(d) for d in test_dirs]}")
                for test_dir in test_dirs:
                    test_name = _strip_test_prefix_local(test_dir)
                    if test_patterns and not any(p.search(test_name) for p in test_patterns):
                        continue
                    if tag_match and not tag_match(test_name):
                        continue
                    # 只跑声明给这个 build 的 test（见上面 tests_by_build 的说明）。
                    # 带 `_seed_<n>` 后缀的也认 —— ShellGenerator 在 test 有
                    # `local_vars.SEED` 时就是这么命名目录的（见 make_tag_matcher）。
                    if not (test_name in declared
                            or any(test_name.startswith(n + "_seed_") for n in declared)):
                        continue
                    if build_name not in added_builds:
                        scheduler.add_task(TaskFactory.create_build_task(
                            build_name, build_path, build_deps.get(build_name, [])))
                        added_builds.add(build_name)
                    scheduler.add_task(TaskFactory.create_test_task(
                        test_name, os.path.join(build_path, test_dir), build_name))
                    total_tests += 1

            scheduler.run(root_dir)

            # ── 4. 读 report_summary.txt ──
            report_path = os.path.join(root_dir, "report_summary.txt")
            report_text = ""
            passed = failed = unknown = 0
            if os.path.exists(report_path):
                report_text = Path(report_path).read_text(encoding="utf-8", errors="replace")
                for line in report_text.splitlines():
                    if line.startswith("Pass:"):
                        passed = int(line.split(":")[1].strip())
                    elif line.startswith("Fail:"):
                        failed = int(line.split(":")[1].strip())
                    elif line.startswith("Unknown:"):
                        unknown = int(line.split(":")[1].strip())

            # ── case 库回写：回归结果 → 更新用例状态（planned → passed/failed）──
            # case 库跨 run 共享，在项目根 .signoffai/（而非 run 目录）。
            #
            # 库对象是**注入**进来的（L1 不 import L4，见 `__init__`）。没注入
            # 就不回写 —— 但要说出来：回归结果默默不落库，比报错难查得多。
            if self._case_library is None:
                logger.warning("没有注入 case 库 —— 回归结果不会回写用例状态"
                               "（由 L2 的 hydrate_runtime 传入）")
            else:
                try:
                    import re as _re
                    for line in report_text.splitlines():
                        m = _re.match(r"(pass|fail|unknown)\s*:\s*(\S+)", line.strip())
                        if not m:
                            continue
                        st, tname = m.group(1), m.group(2)
                        # task.name 丢了 test_ 前缀（Scheduler 用 replace 去掉了），
                        # 补回以匹配 case 库用例名
                        cname = tname if tname.startswith("test_") else f"test_{tname}"
                        if st == "pass":
                            self._case_library.update_status(
                                cname, "passed", result={"new_coverage": 0})
                        elif st == "fail":
                            self._case_library.update_status(cname, "failed")
                except Exception as _e:
                    logger.warning(f"case 库回写失败: {_e}")

            # ── 5. elaboration/load 失败检测：vopt 多驱动等错误在 test 任务 load 阶段失败 ──
            # 这类是「编译级」失败（RTL 有问题），不是「测试」失败——必须标记 compile=FAIL，
            # 让上层 execution.py 路由到 COMPILE_RETRY（CompileSelfHealer），而非 RETRY_ENV。
            compile_fail = ""
            env_failures = []
            try:
                _elab_errs = []
                for _bd in os.listdir(root_dir):
                    _bp = os.path.join(root_dir, _bd)
                    if not _bd.startswith("build_") or not os.path.isdir(_bp):
                        continue
                    for _td in os.listdir(_bp):
                        _tp = os.path.join(_bp, _td)
                        if not _td.startswith("test_") or not os.path.isdir(_tp):
                            continue
                        # vsim 的日志由 run 模板的 `-l sim_vsim.log` 产出
                        #（`sim.log` 被框架的 `> sim.log 2>&1` 收尾重定向占着，
                        #  见 tool_find_spec_yaml 里 run 模板的说明）。
                        # 两个名字都看，兼容手工/旧脚本。
                        _sim_log = next(
                            (p for p in (os.path.join(_tp, "sim_vsim.log"),
                                         os.path.join(_tp, "sim.log"))
                             if os.path.exists(p)), "")
                        if not _sim_log:
                            continue
                        _txt = Path(_sim_log).read_text(encoding="utf-8", errors="replace")
                        # 逐行判（判据见 `is_elab_failure_line`：带 vopt 编号的
                        # Warning/Note 不算编译失败）
                        if not any(is_elab_failure_line(_ln)
                                   for _ln in _txt.splitlines()):
                            continue
                        # 先分设计级 / 环境级（判据见 `classify_sim_failures`）。
                        _design, _env = classify_sim_failures(_txt)
                        if _env:
                            env_failures.extend(f"{_td}: {ln[:200]}" for ln in _env)
                            logger.warning(
                                f"仿真环境故障（非设计错误），已记录不判编译失败: {_td}")
                        _elab_errs.extend(_design)
                if _elab_errs:
                    compile_fail = "\n".join(_elab_errs[:40])
            except Exception as _e:
                logger.warning(f"elaboration 失败检测失败: {_e}")

            result = {
                "status": "PASS" if failed == 0 and passed > 0 else "FAIL",
                "passed": passed,
                "failed": failed,
                "unknown": unknown,
                "total": passed + failed + unknown,
                "total_tests": total_tests,
                "root_dir": root_dir,
                "report_path": report_path,
                "report": report_text[-2000:],
            }
            # ── 挂死/看门狗超时从"功能失败"里摘出来（理由见 `_HANG_RE`）──
            # `status` 仍然是 FAIL（确实有 test 没跑过，不粉饰），但**给决策层一个
            # 分开的数**：`functional_failed`。不然它会拿挂死去改 RTL。
            hung = collect_hung_tests(root_dir)
            if hung:
                result["harness_failures"] = hung
                result["functional_failed"] = max(0, failed - len(hung))
                logger.warning(
                    f"{len(hung)} 个 test 属于**仿真挂死/看门狗超时**（bench/激励侧，"
                    f"不是 DUT 功能错）：{hung[:3]}")
            if compile_fail:
                result["compile"] = "FAIL"
                result["stderr"] = compile_fail
                result["elaboration_failed"] = True
            if env_failures:
                # 环境故障进结果、进报告，但不改 compile 判定 —— 既不被吞掉，
                # 也不把流水线引去改设计（见 `_EDA_ENV_FAIL_RE` 的注释）
                result["eda_env_failures"] = env_failures[:10]
            return result
        except Exception as e:
            logger.warning(f"回归执行失败: {e}")
            return {"status": "FAIL", "error": str(e)[:500]}

    @staticmethod
    def _stage_parts(stage):
        """一级的元组 → `(name, label, tags, gate)`。

        第 4 位（人工节点）**可省**：老调用方与测试传三元组 `(name,label,tags)`
        仍然合法，缺省 = 不设人工节点。兼容不是为了省事 —— `run_regression_staged`
        的 `stages` 参数是公开的，收窄了就是静默改契约。
        """
        name, label, tags = stage[0], stage[1], stage[2]
        gate = bool(stage[3]) if len(stage) > 3 else False
        return name, label, tags, gate

    @classmethod
    def regression_manual_gates(cls, stages=None) -> Dict[str, str]:
        """`{某级: 被它挡住的下一级}` —— **从 `REGRESSION_STAGES` 推出来**，不是另写一份。

        保留这个名字是因为它有用（审计记录里要记 `next`），但它是**派生的**：
        改 `REGRESSION_STAGES` 就跟着变，不可能与之失配。
        """
        seq = [cls._stage_parts(s) for s in (stages or cls.REGRESSION_STAGES)]
        return {seq[i][0]: seq[i + 1][0]
                for i in range(len(seq) - 1) if seq[i][3]}

    def run_regression_staged(self, stages=None, reg_yaml: str = None,
                              mode: str = "local", enabled_modes=None,
                              overrides: list = None,
                              auto_approve: bool = False,
                              tests: str = None) -> dict:
        """分级门控回归：按 tier 顺序跑，**前一级不过就不进下一级**。

        ## 门控判据（为什么 `unknown` 也拦）

        某一级 `failed > 0` **或** `unknown > 0` → 停。回归框架把"编译不过 /
        挂死被掐"记成 `unknown`，那是**没跑出结论**，拿它往下走等于在没验证过的
        基础上继续 —— 所以它和失败一样拦。

        ## 为什么循环里能"下一级"

        `run_regression` 每调一次会 `rmtree` 掉 `<output>/regression_run`（防断点
        续跑读到上次残留）。分级跑**正好利用这一点**：卡住的那一级就是最后一次调用，
        它的报告就在盘上 —— 出问题时人要看的就是那一份。全部通过时盘上是最后一级的
        结果；每一级的 passed/failed/unknown 都在返回值的 `stages` 里，不丢。

        ## 人工节点（`REGRESSION_STAGES` 第 4 位）

        某级 PASS 之后，若它是人工节点的**前一级**，且没有对应的放行记录 → 停，
        `status="WAITING_APPROVAL"`，`awaiting` 里写明停在哪、下一步是什么。
        放行用 `vagent regression approve`（写 `regression_approvals.json`，带审批人 /
        时间 / 意见），**且绑定证据**（那一级的 total/passed/failed 记进记录，
        对不上就当没批过）。再调一次本方法即可从下一级继续；已过的级会重跑一遍
        （不额外维护断点状态，`run_regression` 本来就会 rmtree 重建运行目录）。

        `auto_approve=True` 跳过全部人工节点（测试 / 无人值守用）——默认**不跳**。

        返回：
            {"status", "blocked_at", "blocked_reason",
             "stages": [{"name","label","tags","status","passed","failed","unknown"}...]}
        `status` = PASS 仅当每一级都 PASS；否则 FAIL 且 `blocked_at` 是卡住的那一级名。
        """
        stages = tuple(stages or self.REGRESSION_STAGES)
        results = []
        # 人工节点的判定只认**这一级自带的第 4 位** —— 不再另查一张表（见
        # `REGRESSION_STAGES` 上面那段：那张表会静默失配）
        for idx, raw in enumerate(stages):
            name, label, tags, gate = self._stage_parts(raw)
            # 每级各占一个运行子目录，互不 rmtree（见 `run_regression` 里那段）
            self._stage_tag = name
            logger.info(f"分级回归：进入 {name}（{label}）tags={tags}")
            # **loopback 级不吃增量过滤**：它是环境自检（SCB/连接/时钟复位），
            # 被"受影响用例"筛掉就会 EMPTY → 整轮 FAIL。增量只缩小 DUT 回归。
            r = self.run_regression(reg_yaml=reg_yaml, mode=mode, tags=tags,
                                    tests=_stage_tests(name, tests),
                                    overrides=overrides,
                                    enabled_modes=enabled_modes)
            failed = int(r.get("failed") or 0)
            unknown = int(r.get("unknown") or 0)
            # `total == 0`（这一级没有用例）不算失败，但要说出来 —— 静默跳过会让人
            # 以为"这一级跑过了、过了"。`error` 是真错（配置读不到之类），照传。
            total = int(r.get("total") or 0)
            if r.get("error"):
                status = "FAIL"
            elif total == 0:
                # **一条用例都没匹配到 → 绝不能判 PASS（假绿）。**
                # 实测踩过：`tags=loopback` 一级都没匹配上，五级全返回 total=0，
                # 门看着在、其实什么都没拦，整轮报"每级都过"。这比报错还坏 ——
                # 它把"过滤条件写错了"伪装成"全都通过了"。所以这里单列 EMPTY，
                # 且**同样拦下**（没跑过的级不能当作过了往下走）。
                status = "EMPTY"
            elif failed == 0 and unknown == 0:
                status = "PASS"
            else:
                status = "FAIL"
            stage = {
                "name": name, "label": label, "tags": tags,
                "status": status,
                "passed": int(r.get("passed") or 0),
                "failed": failed, "unknown": unknown,
                "total": total,
            }
            for k in ("error", "report_path"):
                if r.get(k):
                    stage[k] = r[k]
            results.append(stage)

            if stage["status"] != "PASS":
                if stage["status"] == "EMPTY":
                    reason = (f"{name}: 没有任何用例匹配 tag={tags!r} —— "
                              "分级筛选没生效（不是「都过了」，是「一条都没跑」）")
                else:
                    reason = (r.get("error")
                              or f"{name}: failed={failed} unknown={unknown}"
                                 f"（未出结论的不放行）")
                logger.warning(f"分级回归：{name} 未通过 → 不进下一级（{reason}）")
                summary = self._staged_summary("FAIL", name, reason, results)
                self._write_staged_summary(summary)
                return summary

            # ── 人工节点：这一级过了，但要不要往下烧机时由人说了算 ──
            nxt = self._stage_parts(stages[idx + 1]) if idx + 1 < len(stages) else None
            if not auto_approve and nxt is not None and gate:
                approval = self.read_stage_approval(name, stage)
                if approval is None:
                    reason = (f"{name} 已全过，但进 {nxt[0]} 前需要人工放行 —— "
                              f"确认后执行：vagent regression approve -o <run目录> "
                              f"--after {name} --by <你的名字>")
                    logger.warning(f"分级回归：停在人工节点 {name} → {nxt[0]}")
                    summary = self._staged_summary("WAITING_APPROVAL", name,
                                                   reason, results)
                    summary["awaiting"] = {
                        "after": name, "next": nxt[0], "next_label": nxt[1],
                        "hint": (f"vagent regression approve -o <run目录> "
                                 f"--after {name} --by <你的名字>"),
                    }
                    self._write_staged_summary(summary)
                    return summary
                logger.info(f"分级回归：人工节点 {name} → {nxt[0]} 已放行"
                            f"（by {approval.get('approver', '?')}"
                            f" @ {approval.get('at', '?')}）")

        summary = self._staged_summary("PASS", "", "", results)
        self._write_staged_summary(summary)
        return summary

    def _approvals_path(self) -> Path:
        return Path(self.output_root) / "regression_approvals.json"

    @classmethod
    def _evidence_of(cls, stage: dict) -> Dict[str, Any]:
        """抽出一级的"结论指纹"：放行绑的就是它。"""
        return {k: stage.get(k) for k in cls._APPROVAL_EVIDENCE_FIELDS}

    def read_stage_approval(self, after: str,
                            stage: dict | None = None) -> Optional[Dict[str, Any]]:
        """读 `after` 这一级的放行记录；没有 / 对不上证据 → None。

        传 `stage` 时会**比对证据**：记录里那一级的 total/passed/failed 若与当前
        结果不一致，视为未放行（批的是"这一份结果"，结果变了就得重新批）。
        """
        try:
            if not self._approvals_path().exists():
                return None
            data = json.loads(self._approvals_path().read_text(encoding="utf-8"))
        except Exception as exc:                       # noqa: BLE001 读不到＝没批过
            logger.warning(f"读分级放行记录失败（当作没批过）：{exc}")
            return None
        entries = [e for e in (data.get("approvals") or []) if e.get("after") == after]
        if not entries:
            return None
        latest = entries[-1]
        if stage is not None and latest.get("evidence") != self._evidence_of(stage):
            logger.warning(
                f"分级放行记录里的 {after} 证据与本次结果不一致 → 需重新放行"
                f"（记录 {latest.get('evidence')} vs 本次 {self._evidence_of(stage)}）")
            return None
        return latest

    def approve_stage(self, after: str, approver: str, note: str = "") -> Dict[str, Any]:
        """人工放行 `after` 这一级：下次分级回归即可进下一级。

        `approver` 是必填的——没有审批人的"已审批"不算审计证据。
        该级当前结果从 `regression_stages.json` 里取，绑进记录。
        """
        if not approver or not str(approver).strip():
            raise ValueError("approve_stage 需要审批人（--by），否则这条记录没有审计意义")
        stage = None
        stages_path = Path(self.output_root) / "regression_stages.json"
        try:
            if stages_path.exists():
                doc = json.loads(stages_path.read_text(encoding="utf-8"))
                for s in doc.get("stages") or []:
                    if s.get("name") == after:
                        stage = s
                        break
        except Exception as exc:                       # noqa: BLE001 取不到就记空证据
            logger.warning(f"读 regression_stages.json 失败（放行记录不带证据）：{exc}")

        entry = {
            "after": after,
            "next": self.regression_manual_gates().get(after, ""),
            "approver": str(approver).strip(),
            "note": note or "",
            "at": datetime.now().isoformat(timespec="seconds"),
            "evidence": self._evidence_of(stage) if stage else {},
        }
        path = self._approvals_path()
        doc = {"approvals": []}
        try:
            if path.exists():
                doc = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(doc, dict):
                    doc = {"approvals": []}
        except Exception:                              # noqa: BLE001 坏了就重起一份
            doc = {"approvals": []}
        doc.setdefault("approvals", []).append(entry)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(f"分级回归：{after} 已人工放行（by {entry['approver']}）")
        return entry

    def _write_staged_summary(self, summary: dict) -> None:
        """把分级结果**落盘**。

        为什么必须持久化：`run_regression` 每级都会 `rmtree` 掉 `regression_run`，
        盘上**只剩最后一级**的状态 —— loopback 到底跑没跑、过了没有，事后无处可查
        （实测就是这么丢的：想复查 loopback 那级，发现它的目录只剩一个 `sim.sh`）。
        这份 JSON 是"每级各跑了几条、过没过"的唯一事后证据。
        """
        try:
            import json
            path = Path(self.output_root) / "regression_stages.json"
            path.write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        except Exception as exc:                       # noqa: BLE001 落盘失败不该拖垮回归
            logger.warning(f"分级回归结果落盘失败（不影响回归本身）：{exc}")

    @staticmethod
    def _staged_summary(status: str, blocked_at: str, reason: str,
                        results: list) -> dict:
        """分级结果 + **顶层聚合** —— 上层（ops agent / 闭环）读的是 passed/failed，
        只给 `stages` 会让他们拿到 0，把"卡在 loopback"误读成"一条都没跑"。

        `report_path` 取**卡住那一级**（或最后一级）的 —— 出问题时人要看的就是它。
        """
        passed = sum(s["passed"] for s in results)
        failed = sum(s["failed"] for s in results)
        unknown = sum(s["unknown"] for s in results)
        last = results[-1] if results else {}
        return {
            "status": status, "blocked_at": blocked_at, "blocked_reason": reason,
            "stages": results,
            "passed": passed, "failed": failed, "unknown": unknown,
            "total": passed + failed + unknown,
            "report_path": last.get("report_path", ""),
        }

    @staticmethod
    def _sha256(path: Path) -> str:
        return sha256_file(path)

