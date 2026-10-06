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

logger = structlog.get_logger()


def sha256_file(path: str | Path, chunk_size: int = 65536) -> str:
    """分块计算文件 SHA256 —— 覆盖率数据库的唯一哈希实现。

    ucdb 动辄几十 GB，整文件 read_bytes() 会直接打爆内存。铁律二（覆盖率
    数据库版本固化）与此处共用同一份实现，避免再出现「一份分块、一份整读」
    的两套哈希。

    **没有路径就是空哈希，不是错误。** 调用方常这样写：
    `sha256_file(data.get("log_path", ""))` —— 仿真没跑起来时那个字段就是空串，
    而 `Path("")` 会变成 `Path(".")`：它在 `exists()` 上**是真的**（当前目录），
    于是 `open(".")` 抛 `PermissionError: [Errno 13] Permission denied: '.'`，
    把「这一步没产出日志」升级成整次运行崩掉。实测踩过一次：覆盖率阶段编译失败
    → 没有 log_path → 整个 run 挂在这么一句上。

    所以两件事都要挡住：**空/空白路径**直接返回空，**目录**（含 `.`）不当文件读。
    """
    if path is None or not str(path).strip():
        return ""
    p = Path(path)
    if not p.is_file():          # 不存在、或是目录（Path("") 就是 "."）都不读
        return ""
    sha = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            sha.update(chunk)
    return sha.hexdigest()


#: 「这是 elaboration 失败，该走 COMPILE_RETRY」的判据。
#:
#: **只认 `vopt-NNNN` 与 `Error loading design`。** 原来还带一条
#: `Error \(suppressible\)` —— 匹配得太宽：Questa 对**无害告警**也打
#: `** Error (suppressible): (vsim-3764) Stand-alone call to function 'get' ...`，
#: 于是每个正常跑完的仿真都被判成"编译级失败"，闭环被路由到
#: `debug_compile`（COMPILE_RETRY）而**整段跳过了覆盖率阶段** —— 覆盖率恒为 0%。
#: 真正致命的 elaboration 错误（多驱动、参数覆盖非法）打的是 `vopt-NNNN`。
#: **但光看编号会把警告和提示一起收进来** —— 见 `is_elab_failure_line` 的说明。
_VOPT_CODE_RE = r"vopt-\d+"
#: Questa 的严重度前缀
_SEVERITY_NOT_ERROR_RE = r"\*\*\s*(?:Warning|Note)"
_SEVERITY_ERROR_RE = r"\*\*\s*(?:Error|Fatal)"
#: 加载失败那一句（不带 `**` 前缀，编译级失败的经典收尾）
_ELAB_LOAD_FAIL_RE = r"Error loading design"


def is_elab_failure_line(line: str) -> bool:
    """这一行算不算「elaboration / 编译级失败」—— 判错一次的代价是整轮跳过覆盖率。

    ## 为什么不能只看 `vopt-NNNN`

    原判据是 `vopt-\\d+[^\\n]*`，见编号就收。**但 Questa 的警告和提示用的是同一个
    编号空间**，实测两条：

        # ** Warning: (vopt-13408) Code coverage will be disabled for some DUs…
        # ** Note: (vopt-143) Recognized 1 FSM in module "apb_master(fast)".

    这两句在**开着覆盖率编译**时必然出现（vopt 要为覆盖率做 FSM 识别）。于是一开
    覆盖率业务，整轮回归就被判成"RTL 编译不过"（`compile: FAIL` / `elaboration_failed`），
    决策引擎最高优先级的 COMPILE_RETRY 把它路由去**修 RTL**（而根本没有可修的错误），
    **覆盖率阶段整段跳过** —— 覆盖率恒为 0%。与上面 `_EDA_ENV_FAIL_RE` 记的那次事故
    同一个后果，触发点不同。实测踩过（`+cover` 那次）。

    ## 判法

      · 有 `** Error` / `** Fatal` 前缀**且**带 `vopt-NNNN` → 编译级失败；
      · 带 `vopt-NNNN` 但打的是 `** Warning` / `** Note` → **不算**；
      · `Error loading design` → 算（DPI/加载类故障由环境那条判据先行接管）。

    **刻意不收「任何 `** Error`」**：Questa 把断言失败也打成
    `# ** Error: tb.sv(9): Assertion a_check failed` —— 那是**仿真**失败，不是编译
    失败，收进来同样会把覆盖率阶段整段跳过。
    """
    import re

    if not line:
        return False
    has_vopt = bool(re.search(_VOPT_CODE_RE, line))
    if has_vopt and re.search(_SEVERITY_ERROR_RE, line):
        return True
    if has_vopt and not re.search(_SEVERITY_NOT_ERROR_RE, line):
        return True
    return bool(re.search(_ELAB_LOAD_FAIL_RE, line))


#: 「这是**仿真环境**故障，不是设计（RTL）的错」的判据 —— 与上面那条互斥。
#:
#: 实测事故（一次真实闭环跑）：某个 case 的 vsim 报
#: `** Error: (vsim-3193) Load of "...\vsim_auto_compile.dll" failed` →
#: `** Fatal: (vsim-3772) Failed to load DPI auto compile shared library` →
#: `Error loading design`。那是 Questa 自己在 Windows 临时目录里自动编译的 DPI
#: 库加载失败（环境问题，重跑即过），但最后那句 `Error loading design` 正好命中
#: `is_elab_failure_line`，于是整轮被判成"RTL 编译不过" → 决策引擎最高优先级的
#: COMPILE_RETRY 把它路由去修 RTL（而根本没有可修的错误，`file=None`），
#: **整段跳过覆盖率阶段** → 覆盖率 0% → 该轮签核必然不过。
#:
#: 判法：**日志里出现环境故障签名、且没有任何 `vopt-NNNN`** 时，算环境故障。
#: 真·elaboration 错误（多驱动、参数覆盖非法）打的就是 `vopt-NNNN`，一条不少。
#: 两类都**如实记进结果**（`eda_env_failures`），只是后者才改 `compile` 判定 ——
#: 环境故障不该让流水线去改设计，但它也不该被吞掉。
_EDA_ENV_FAIL_RE = (r"vsim-3772|vsim-3193|auto compile shared library|"
                    r"Failed to load .*(?:[Dd][Pp][Ii]|shared library)|"
                    r"Unable to checkout .*licen[cs]e|Failed to obtain a licen[cs]e")


#: 「仿真挂死 / 看门狗超时」的判据 —— 这是 **bench 与激励的事，不是 DUT 功能错**。
#:
#: 实测：覆盖率缺口补出来的定向激励随机出来的事务，driver 等不到 DUT 握手就永久
#: 阻塞，看门狗把整个仿真掐掉（`UVM_FATAL [SIM_WATCHDOG] watchdog timeout`）。
#: 把它当"功能失败"的代价很具体：决策引擎按 `REFACTOR_RTL` 去**改 RTL** ——
#: 实测真跑了一轮 `design_fix`，改的是没坏的代码，而且这一轮的覆盖率白搭。
_HANG_RE = (r"SIM_WATCHDOG|watchdog timeout|GAPSEQ[^\n]*(?:timeout|超时)|"
            r"仿真\s*\d+\s*ns\s*内没有结束")


def collect_hung_tests(root_dir) -> list:
    """回归目录里**挂死/看门狗超时**的 test，返回 `["build/test: 摘要", ...]`。

    和 `classify_sim_failures` 同一套路数：按**日志内容**归类，而不是按"失败"一刀切。
    区别是这一类的责任在 bench/激励侧，不在设计侧。

    日志名与那次检测一致（`sim_vsim.log`，兼容旧的 `sim.log`）。
    """
    import re

    hung = []
    try:
        for build in sorted(os.listdir(root_dir)):
            if not build.startswith("build_") or not os.path.isdir(
                    os.path.join(root_dir, build)):
                continue
            bpath = os.path.join(root_dir, build)
            for test in sorted(os.listdir(bpath)):
                tpath = os.path.join(bpath, test)
                if not test.startswith("test_") or not os.path.isdir(tpath):
                    continue
                log = next((p for p in (os.path.join(tpath, "sim_vsim.log"),
                                        os.path.join(tpath, "sim.log"))
                            if os.path.exists(p)), "")
                if not log:
                    continue
                text = Path(log).read_text(encoding="utf-8", errors="replace")
                hit = next((ln.strip() for ln in text.splitlines()
                            if re.search(_HANG_RE, ln)), "")
                if hit:
                    hung.append(f"{build}/{test}: {hit[:120]}")
    except Exception as e:                      # noqa: BLE001 归类失败不该拖垮回归
        logger.warning(f"挂死检测失败: {e}")
    return hung


def classify_sim_failures(text: str) -> tuple:
    """把一段 vsim 日志里的失败行分成「设计级」与「环境级」，返回 (设计, 环境)。

    两类的后果完全不同，所以必须分开：

      · **设计级**（`vopt-NNNN` 多驱动之类）→ 上层走 COMPILE_RETRY 去改 RTL；
      · **环境级**（DPI/动态库/license 加载不上）→ 只记录，**不能**引着流水线
        去改设计 —— 重跑一次通常就好了。

    `Error loading design` 这一句两边都可能出现，所以判法看**整段日志**：
    有环境签名、且全篇没有**编译级失败**才算环境级；两类同时出现时按设计级处理
    （宁可误报去修 RTL，也不能把真编译错误当成环境抖动放过去）。

    这里判的是"有没有**编译级失败**"而不是"有没有 `vopt-NNNN`"：带编号的
    Warning / Note 不算（见 `is_elab_failure_line`）。差别是真会咬人的 ——
    vopt 的覆盖率告警与 DPI 加载故障同时出现时，按"有编号就不是环境问题"
    会把一条干净的环境抖动判成 RTL 有错。

    单独一个函数是为了能被测试钉住 —— 这个判据判错一次，代价是整轮跳过覆盖率。
    """
    import re

    lines = text.splitlines()
    # 环境级的判据是「有环境签名、且**没有真·elaboration 错误**」。注意这里比的是
    # "带 vopt 编号的失败"，不是"任何失败行" —— `Error loading design` 两边都可能
    # 出现（它正是环境故障的收尾那一句），拿它来否决环境判定等于这条判据永远不成立。
    has_vopt_error = any(is_elab_failure_line(ln) and re.search(_VOPT_CODE_RE, ln)
                         for ln in lines)
    if any(re.search(_EDA_ENV_FAIL_RE, ln) for ln in lines) and not has_vopt_error:
        return [], [ln.strip() for ln in lines if re.search(_EDA_ENV_FAIL_RE, ln)]
    return [ln.strip() for ln in lines if is_elab_failure_line(ln)], []


def declared_tests_by_build(config: dict) -> Dict[str, set]:
    """`{build 任务名: {声明给这个 build 的 test 名}}` —— 名字已规整成生成目录那套。

    生成目录里 build 是 `build_<名>`、test 是 `test_<名>`，而框架记任务名时各剥一层
    前缀（`TaskFactory` / `normalize_build_name` 同一套口径），所以这里也剥。

    为什么单独抽成函数：`run_regression` 拿它当**白名单**用（只跑声明过的组合），
    而生成的 `regression.yaml` 因为 `include:` 了 `common_base.yaml`，会带上几个
    **不属于本项目**的 `VCS …` build。白名单一旦失效，那些 build 会被排进调度、
    跑的是一条不存在的命令，整轮回归连一条真 case 都出不来。所以这条不变量值得
    被测试直接钉住，而不是埋在 60 行调度代码中间。
    """
    out: Dict[str, set] = {}
    for test in (config.get("tests") or []):
        if not isinstance(test, dict):
            continue
        build = str(test.get("build", "")).replace("build_", "")
        name = str(test.get("name", "")).replace("test_", "")
        if build and name:
            out.setdefault(build, set()).add(name)
    return out


class InfrastructureManager:
    """L1 基础设施层统一入口。"""

    def __init__(self, output_root: str | Path, repo_root: str | Path = None):
        self.output_root = Path(output_root)
        # 仓库根目录（git tag 打在这里，通常 = 项目根）
        self.repo_root = Path(repo_root) if repo_root else Path.cwd()

        # 归档区（持久，不随 output 丢弃）
        self.meta_dir = self.output_root / ".signoffai"
        self.coverage_archive = self.meta_dir / "coverage_archive"
        self.rtl_archive = self.meta_dir / "rtl_archive"

    # ═══════════════════════════════════════════════════════════════
    # 文件系统：目录布局
    # ═══════════════════════════════════════════════════════════════

    def setup(self) -> Dict[str, str]:
        """初始化标准目录布局，返回各目录路径。"""
        dirs = {
            "rtl": self.output_root / "rtl",
            "env": self.output_root / "env",
            "agents": self.output_root / "agents",
            "bench": self.output_root / "bench",
            "build": self.output_root / "build" / "work",
            "sim": self.output_root / "sim" / "coverage",
            "docs": self.output_root / "docs",
            "meta": self.meta_dir,
            "coverage_archive": self.coverage_archive,
            "rtl_archive": self.rtl_archive,
        }
        for d in dirs.values():
            d.mkdir(parents=True, exist_ok=True)
        return {k: str(v) for k, v in dirs.items()}

    # ═══════════════════════════════════════════════════════════════
    # 覆盖率数据库：归档 + 哈希固化
    # ═══════════════════════════════════════════════════════════════

    def collect_coverage(self, round_num: int = 0, top_module: str = "",
                         seed: int = 0, backend=None) -> dict:
        """L1 统一入口：委托覆盖率后端做 EDA 收集 + 自动归档固化覆盖率数据库。

        把「编译仿真 + 报告解析 + 数据库归档」整合成 L1 的一个能力：
        - EDA 工具差异由 CoverageBackend（questa/vcs）隔离
        - 覆盖率数据库归档（硬链接 + SHA256 固化）是 L1 职责，收集后自动完成
        - 上层（run_closed_loop / CoverageCollectTool）统一走这里，不各自散落 subprocess

        返回 backend.collect() 的原始结果 + archive 归档信息。
        """
        from src.layers.l1_infrastructure.coverage_backend import get_coverage_backend
        backend = backend or get_coverage_backend()
        result = backend.collect(self.output_root, top_module, seed)
        result["backend"] = backend.name
        # 自动归档（L1 职责：覆盖率数据库版本固化，复现时回滚比对）
        db_path = (result.get("coverage", {}).get("db_path")
                   or result.get("coverage", {}).get("ucdb_path")
                   or result.get("db_path", ""))
        if db_path:
            try:
                result["archive"] = self.archive_coverage(round_num, db_path)
            except Exception as e:
                logger.warning(f"覆盖率数据库归档失败: {e}")
                result["archive"] = {"error": str(e)[:200]}
        return result

    def compile(self, filelist: str, coverage: bool = True, backend=None) -> dict:
        """L1 统一入口：委托 EDA 后端编译 RTL + UVM 环境（vlog/vcs）。"""
        from src.layers.l1_infrastructure.eda_backend import get_eda_backend
        backend = backend or get_eda_backend()
        return backend.compile(self.output_root, filelist, coverage)

    def simulate(self, top_module: str, uvm_test: str = "", seed: int = 0,
                 coverage: bool = True, backend=None) -> dict:
        """L1 统一入口：委托 EDA 后端仿真（vsim/simv）。"""
        from src.layers.l1_infrastructure.eda_backend import get_eda_backend
        backend = backend or get_eda_backend()
        return backend.simulate(self.output_root, top_module, uvm_test, seed, coverage)

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
        见 `src/tools/regression_tools/sim_modes.py`）。交给框架的
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
                from src.tools.lib.filelist import (build_filelist_for_tb,
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
                    from src.tools.lib.filelist import build_loopback_filelist
                    for ag in agents:
                        build_loopback_filelist(self.output_root, ag["name"])
                except Exception as _lb_e:
                    logger.warning(f"loopback filelist 生成失败: {_lb_e}")
            except Exception as e:
                logger.warning(f"filelist 生成失败: {e}")

            # ── 1. ConfigBuilder 解析 regression.yaml（builds + tests）──
            from src.tools.regression_tools.regression_framework.core.config import (
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
            from src.tools.regression_tools.regression_framework.generators.shell import ShellGenerator
            root_dir = str(self.output_root / "regression_run")
            # 清理上一次回归残留（state_file 会导致断点续跑跳过所有已完成任务）
            import shutil as _shutil
            if os.path.isdir(root_dir):
                _shutil.rmtree(root_dir, ignore_errors=True)
            # reference_mode：跑历史/参考版本时走 `ref_run_cmd`；
            # debug_mode：走 `debug_run_cmd` / `ref_debug_run_cmd`（见 shell.py 的矩阵）
            ShellGenerator().generate(config, root_dir, mode,
                                      reference_mode=reference_mode,
                                      debug_mode=debug_mode)

            # ── 3. Scheduler 批量跑 build + test（扫描生成目录）──
            from src.tools.regression_tools.regression_framework.models.scheduler import Scheduler
            from src.tools.regression_tools.regression_framework.execution.strategy import LocalStrategy, MockStrategy
            from src.tools.regression_tools.regression_framework.models.task import TaskFactory
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
            from src.tools.regression_tools.regression_framework.core.config import (
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
                for test_dir in test_dirs:
                    test_name = test_dir.replace("test_", "")
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
            # case 库跨 run 共享，在项目根 .signoffai/（而非 run 目录）
            try:
                from src.layers.l4_memory.testcase_registry import TestcaseRegistry
                case_reg = TestcaseRegistry()
                import re as _re
                for line in report_text.splitlines():
                    m = _re.match(r"(pass|fail|unknown)\s*:\s*(\S+)", line.strip())
                    if not m:
                        continue
                    st, tname = m.group(1), m.group(2)
                    # task.name 丢了 test_ 前缀（Scheduler 用 replace 去掉了），补回以匹配 case 库用例名
                    cname = tname if tname.startswith("test_") else f"test_{tname}"
                    if st == "pass":
                        case_reg.update_status(cname, "passed", result={"new_coverage": 0})
                    elif st == "fail":
                        case_reg.update_status(cname, "failed")
                case_reg.close()
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

    # ── 分级门控回归 ────────────────────────────────────────────

    #: 分级顺序：**从最小自检到大面覆盖**。
    #: agent loopback 先证"环境自身自洽"（SCB 全 match），环境都不对就不该往下跑
    #: —— 后面几级的失败会全是同一个环境问题刷屏，把真正的 DUT 缺陷埋掉。
    #: `tags` 里的优先级标记（p0/p1…）就是分级的**唯一真相源**（生成用例时打好的）。
    REGRESSION_STAGES = (
        ("loopback", "agent loopback 自检（SCB 必须全 match）", "loopback"),
        ("p0", "P0 功能", "p0"),
        ("p1", "P1 次功能（边界 + corner）", "p1"),
        ("p2", "P2 压力", "p2"),
        ("p3", "P3 错误 + 随机", "p3"),
    )

    def run_regression_staged(self, stages=None, reg_yaml: str = None,
                              mode: str = "local", enabled_modes=None,
                              overrides: list = None) -> dict:
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

        返回：
            {"status", "blocked_at", "blocked_reason",
             "stages": [{"name","label","tags","status","passed","failed","unknown"}...]}
        `status` = PASS 仅当每一级都 PASS；否则 FAIL 且 `blocked_at` 是卡住的那一级名。
        """
        stages = tuple(stages or self.REGRESSION_STAGES)
        results = []
        for name, label, tags in stages:
            logger.info(f"分级回归：进入 {name}（{label}）tags={tags}")
            r = self.run_regression(reg_yaml=reg_yaml, mode=mode, tags=tags,
                                    overrides=overrides,
                                    enabled_modes=enabled_modes)
            failed = int(r.get("failed") or 0)
            unknown = int(r.get("unknown") or 0)
            # `total == 0`（这一级没有用例）不算失败，但要说出来 —— 静默跳过会让人
            # 以为"这一级跑过了、过了"。`error` 是真错（配置读不到之类），照传。
            stage = {
                "name": name, "label": label, "tags": tags,
                "status": "PASS" if (failed == 0 and unknown == 0 and not r.get("error"))
                          else "FAIL",
                "passed": int(r.get("passed") or 0),
                "failed": failed, "unknown": unknown,
                "total": int(r.get("total") or 0),
            }
            for k in ("error", "report_path"):
                if r.get(k):
                    stage[k] = r[k]
            results.append(stage)

            if stage["status"] != "PASS":
                reason = (r.get("error")
                          or f"{name}: failed={failed} unknown={unknown}"
                             f"（未出结论的不放行）")
                logger.warning(f"分级回归：{name} 未通过 → 不进下一级（{reason}）")
                return self._staged_summary("FAIL", name, reason, results)

        return self._staged_summary("PASS", "", "", results)

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

    def archive_coverage(self, round_num: int, ucdb_path: str | Path) -> dict:
        """归档覆盖率数据库（硬链接，避免几十 GB 复制）+ 记录 SHA256。

        返回 {round, ucdb_path, sha256, size}。复现时用 sha256 比对。
        """
        ucdb = Path(ucdb_path)
        result = {"round": round_num, "ucdb_path": str(ucdb),
                  "sha256": "", "size": 0, "archived": False}

        if not ucdb.exists():
            return result

        result["sha256"] = self._sha256(ucdb)
        result["size"] = ucdb.stat().st_size

        dest = self.coverage_archive / f"round_{round_num:02d}{ucdb.suffix}"
        try:
            if not dest.exists():
                # 优先硬链接（零拷贝），跨文件系统则退化为复制
                try:
                    os.link(ucdb, dest)
                except OSError:
                    import shutil
                    shutil.copy2(ucdb, dest)
            result["archived"] = True
            result["archive_path"] = str(dest)
            # 哈希 + 元数据落盘（供复现比对）
            (self.coverage_archive / f"round_{round_num:02d}.sha256").write_text(
                result["sha256"], encoding="utf-8")
        except Exception as e:
            logger.warning(f"覆盖率数据库归档失败: {e}")
        return result

    def archive_rtl(self, round_num: int = 0) -> dict:
        """归档 RTL 代码哈希（不进 git 的产物用哈希固化）。"""
        rtl_dir = self.output_root / "rtl"
        result = {"files": {}, "aggregate": ""}
        if not rtl_dir.exists():
            return result
        for sv in sorted(rtl_dir.glob("*.sv")):
            result["files"][sv.name] = self._sha256(sv)[:16]
        sha = hashlib.sha256()
        for name in sorted(result["files"]):
            sha.update(name.encode())
            sha.update(result["files"][name].encode())
        result["aggregate"] = sha.hexdigest()
        return result

    # ═══════════════════════════════════════════════════════════════
    # 版本清单：tag ↔ 产物哈希 关联
    # ═══════════════════════════════════════════════════════════════

    def write_version_manifest(self, extra: Dict[str, Any] = None) -> str:
        """写版本清单（tag ↔ 覆盖率数据库哈希 ↔ RTL 哈希）。"""
        manifest = {
            "generated_at": datetime.now().isoformat(),
            "output_root": str(self.output_root),
            "repo_root": str(self.repo_root),
            **(extra or {}),
        }
        # 汇总归档的覆盖率数据库哈希
        coverage_entries = []
        for sha_file in sorted(self.coverage_archive.glob("round_*.sha256")):
            coverage_entries.append({
                "round": sha_file.stem.replace("round_", ""),
                "sha256": sha_file.read_text(encoding="utf-8").strip(),
            })
        manifest["coverage_archives"] = coverage_entries
        manifest["rtl"] = self.archive_rtl()

        path = self.meta_dir / "version_manifest.json"
        path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False, default=str),
                        encoding="utf-8")
        return str(path)

    # ═══════════════════════════════════════════════════════════════
    # Git 仓库：版本 tag
    # ═══════════════════════════════════════════════════════════════

    def git_tag(self, tag_name: str, message: str = "") -> dict:
        """给源代码仓库打 git tag（产物不进 git，用哈希关联）。

        返回 {tagged, tag_name, commit, error}。失败不阻断（hash 固化仍是兜底）。
        """
        result = {"tagged": False, "tag_name": tag_name, "commit": "", "error": ""}
        try:
            if not (self.repo_root / ".git").exists():
                result["error"] = "not a git repository"
                return result
            # 记录当前 commit
            r = subprocess.run(["git", "-C", str(self.repo_root), "rev-parse", "--short", "HEAD"],
                               capture_output=True, text=True, timeout=10)
            result["commit"] = r.stdout.strip()
            # 打 tag（轻量 tag，覆盖已存在的同名 tag）
            subprocess.run(["git", "-C", str(self.repo_root), "tag", "-f", tag_name],
                           capture_output=True, text=True, timeout=10)
            result["tagged"] = True
        except Exception as e:
            result["error"] = str(e)[:200]
        return result

    # ═══════════════════════════════════════════════════════════════
    # 复现：哈希比对
    # ═══════════════════════════════════════════════════════════════

    def verify_reproducible(self) -> dict:
        """复现校验：比对当前工作区的覆盖率数据库/RTL 与归档哈希是否一致。

        返回 {reproducible, mismatches}。
        """
        mismatches = []
        # 比对当前 merged.ucdb 与归档的 round_*.sha256
        current_ucdb = self.output_root / "sim" / "coverage" / "merged.ucdb"
        if current_ucdb.exists():
            current_hash = self._sha256(current_ucdb)
            for sha_file in sorted(self.coverage_archive.glob("round_*.sha256")):
                archived_hash = sha_file.read_text(encoding="utf-8").strip()
                if archived_hash == current_hash:
                    break
            else:
                mismatches.append({
                    "type": "coverage_db",
                    "detail": "current merged.ucdb hash 与任何归档都不一致",
                })
        # 比对 RTL
        rtl_dir = self.output_root / "rtl"
        if rtl_dir.exists():
            current_rtl = self.archive_rtl()
            manifest_path = self.meta_dir / "version_manifest.json"
            if manifest_path.exists():
                try:
                    saved = json.loads(manifest_path.read_text(encoding="utf-8"))
                    saved_rtl = saved.get("rtl", {}).get("files", {})
                    if saved_rtl and saved_rtl != current_rtl.get("files", {}):
                        mismatches.append({"type": "rtl", "detail": "RTL 文件哈希与版本清单不一致"})
                except Exception:
                    pass
        return {"reproducible": not mismatches, "mismatches": mismatches}
