"""L1 基础设施的模块级 helper（Phase 4 拆分）。

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
    from src.runtime_plane.infrastructure.infrastructure import InfrastructureManager
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
from src.runtime_plane.infrastructure import layout

logger = structlog.get_logger()


def _strip_test_prefix_local(name):
    """`strip_test_prefix` 的薄包装 —— 只削前缀 `test_`（**不是** `.replace`）。

    见 `regression_framework.core.config.strip_test_prefix` 的说明：
    `test_dir.replace('test_','')` 会把 `npu_type_test_run_1_seed_2001` 里的
    中间那个 `test_` 也吃掉，于是它永远匹配不上配置里的 `npu_type_test_run_1`。
    """
    from src.orchestration_plane.l2.regression_tools.regression_framework.core.config import (
        strip_test_prefix)
    return strip_test_prefix(name)


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
        # 只削**前缀**（`npu_type_test_run_1` 里中间那个 `test_` 不能被吃掉）
        from src.orchestration_plane.l2.regression_tools.regression_framework.core.config import (
            strip_test_prefix)
        name = strip_test_prefix(test.get("name", ""))
        if build and name:
            out.setdefault(build, set()).add(name)
    return out


def _stage_tests(stage_name: str, tests):
    """增量过滤只作用于 DUT 级；loopback 环境自检永远跑全。"""
    return None if stage_name == "loopback" else tests


