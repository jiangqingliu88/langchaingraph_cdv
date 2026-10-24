"""「打开波形 / 打开覆盖率报告」—— 三个回归页**共用的唯一实现**。

## 为什么不各写各的

分开写三遍的代价不是代码量，是**行为会漂**：一个页面复用了已有报告、另一个每次
都重跑 vcover，人就会觉得"有的页面快有的页面慢，是不是坏了"。而"参考哪份报告"
恰恰是有对错的一件事：覆盖率阶段已经生成过一份 HTML（`reports/index.html`），
**那一份就是当时 agent 看过的**，打开它又快又对得上账；没有才现生成。

## 两处必须说清的边界

  · **覆盖率库不是报告 —— 但有两种"打开"**。`questa.db` / `.ucdb` 是二进制，双击
    什么都不发生，所以有两条互补的路：
      - **HTML 报告**（`open_case_coverage` / `open_total_coverage`）：`vcover`
        现生成/复用 HTML，交给浏览器 —— 看"整份结论"。
      - **Visualizer**（`open_case_coverage_visualizer` /
        `open_total_coverage_visualizer`）：`visualizer -ucdbfile <库>` —— 可下钻，
        点 0 覆盖的 bin 跳源码。**选项是 `-ucdbfile`**（实测 `-ucdb` 报
        `Unknown option`；`-viewcov` 也可用，但不带调试能力）。
    报告生成不了时**退到打开库所在目录**：让人至少摸得到东西，比"点了没反应"强。
  · **波形按格式选工具，任何一条都不能代劳另一条**（都是实测结论）：
      - `qwave.db`（本仓库 `vsim -qwavedb=+signal+class+wavefile=` 的产物）
        → **`visualizer -wavefile <db>`**。Visualizer 只认 qwavedb：喂 `.wlf`
        会当场 `Error[230]: … is not a qwavedb file` 然后退出。
      - `.wlf`（旧产物 / `vsim -wlf`）→ **`vsim -view <wlf>`**（经典波形窗）。
        别指望 Visualizer（不认），也别指望系统关联：`.wlf` 在 Windows 上没有
        默认程序（实测 `AssocQueryString` 落到 `OpenWith.exe`，即"选择打开方式"
        弹窗），`QDesktopServices.openUrl` 点了既不开也不报错。
    两条路都**显式接返回/捕获异常**，不"假报成功"。
  · **失败要说清是哪一种**。库不在 / 没开这门业务 / vcover 找不到 / vcover 报错，
    四种原因的处置完全不同（等回归跑完 / 切业务 / 装 Questa / 看库本身），
    所以状态栏里给的是**具体那一句**，不是笼统的"打开失败"。
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any


def missing_artifact_note(mode: str, noun: str) -> str:
    """没有产物时，表格那一格填的说明 —— **两页共用同一句**（一处实现，不会漂）。

    空列会被读成"路径没加上 / 这页坏了"，而真实原因往往是这轮没开那门仿真业务。
    一句里给三件事：**哪门业务没开**、**所以没有这个文件**、**去哪开**。
    """
    return (f"（本轮回归没开「{mode}」业务 —— 不产生{noun}；"
            "工具栏「仿真业务」下拉可切）")


def _open_path(module, path: str) -> None:
    """交给操作系统的默认程序 —— **只用于 HTML 报告 / 目录**（浏览器、资源管理器）。

    波形**不走这里**（见 `open_wave`）：`.wlf`/`.db` 都没有合适的系统关联，
    交给 ShellExecute 只会弹"选择打开方式"。
    """
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices

    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


def _questa_bin(name: str) -> str:
    """Questa 安装目录下的可执行文件（`visualizer.exe` / `vsim.exe`）。

    统一走 `config.settings.questa_home`（优先 `QUESTA_HOME` 环境变量），再回落 PATH。
    """
    import shutil

    from config.settings import questa_home

    root = questa_home()
    for c in (os.path.join(root, "win64"), root):
        exe = os.path.join(c, name)
        if os.path.exists(exe):
            return exe
    for cmd in (name, os.path.splitext(name)[0]):
        found = shutil.which(cmd)
        if found:
            return found
    return ""


def visualizer_exe() -> str:
    """Questa Visualizer 路径（开 qwave.db 用）。"""
    return _questa_bin("visualizer.exe")


def vsim_exe() -> str:
    """Questa `vsim` 路径（`vsim -view` 开 .wlf 用）。"""
    return _questa_bin("vsim.exe")


def _ensure_designfile(db_path: str) -> str:
    """给 Visualizer 准备**设计索引**（`design.db`）—— 波形窗要的 hier + 源码。

    ## 为什么只给 `-wavefile` 不够

    `visualizer -wavefile qwave.db` 只拿到波形数据：**没有设计层次、点信号也
    跳不到源码**。Visualizer 的完整用法是成对的：

        vopt <top> -o opt +acc -designfile design.db
        visualizer -designfile design.db -wavefile qwave.db

    `design.db` 由 `vopt` 生成（实测 3.5MB / ~5s）。回归的仿真只跑 `vsim
    -voptargs=+acc`，不会落这个文件 —— 所以这里**按需生成**、生成后缓存：
    同一个 build 下所有用例共用一份，只有第一次打开要等几秒。

    失败不抛：返回空串，调用方退回 `visualizer -wavefile`（没 hier，但波形能看）。
    """
    db = Path(db_path)
    # `<build>/test_x/waves/x.db` → build = 上三级；布局不认得就退回两级
    build = db.parents[2] if db.parent.name.lower() == "waves" else db.parent
    if not build.is_dir():
        return ""
    design = build / "design.db"
    if design.is_file() and design.stat().st_size > 0:
        return str(design)

    vopt = _questa_bin("vopt.exe")
    if not vopt:
        return ""
    top = _top_from_sim_scripts(build)
    if not top:
        return ""
    try:
        # `-o` 只收**设计名**（不是路径）；`-work work` 要求 cwd=build
        proc = subprocess.run(
            [vopt, "-work", "work", top, "-o", "vis_opt", "+acc",
             "-designfile", "design.db"],
            cwd=str(build), capture_output=True, text=True,
            errors="replace", timeout=180)
    except (OSError, subprocess.SubprocessError):
        return ""
    if design.is_file() and design.stat().st_size > 0:
        return str(design)
    return ""


def _top_from_sim_scripts(build: Path) -> str:
    """从任意一条用例的 `sim.sh` 里认出顶层模块名。

    `vsim ... -work <work> <top> +UVM_TESTNAME=...` —— `-work` 后面两个 token
    才是 top（中间那个是库路径）。找不到就给空串，不猜。
    """
    for sim in sorted(build.glob("test_*/sim.sh")):
        try:
            text = sim.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        m = re.search(r"-work\s+\S+\s+([A-Za-z_][\w$]*)", text)
        if m:
            return m.group(1)
    return ""


def open_wave(module, path: str, what: str = "波形") -> None:
    """打开一条用例的波形 —— **按扩展名选对工具**（见模块头 "按格式选工具"）。

    `qwave.db` → `visualizer -wavefile`；`.wlf` → `vsim -view`。
    """
    if not path or not Path(path).exists():
        module.set_status(f"这条用例没有{what} —— 这轮回归的仿真业务里没开 `wave`"
                          "（工具栏「仿真业务」下拉可切）")
        return

    is_wlf = Path(path).suffix.lower() == ".wlf"
    if is_wlf:
        # **`-view` 只打开数据集，不自动把信号加到波形窗** —— 窗口是空的，
        # 看起来就像"打不开"。`-do "add wave -r /*"` 把 WLF 里记录的信号铺出来。
        exe, args, label = vsim_exe(), ["-view", str(path),
                                        "-do", "add wave -r /*"], "vsim -view"
    else:
        # **成对给 Visualizer 设计索引**：只有 `-wavefile` 时波形能看，但
        # 没有模块 hier、点信号也跳不到源码。`design.db` 由 vopt 按需生成
        # （同一 build 共用一份，第一次几秒）。
        design = _ensure_designfile(str(path))
        exe = visualizer_exe()
        if design:
            args, label = ["-designfile", design, "-wavefile", str(path)], "Questa Visualizer"
        else:
            args, label = ["-wavefile", str(path)], "Questa Visualizer（无设计索引）"

    if not exe:
        module.set_status(f"找不到打开波形的程序（{label}）—— 装了 QuestaSim 才能开波形："
                          f"{path}")
        return

    kwargs: dict[str, Any] = {}
    if os.name == "nt":
        kwargs["creationflags"] = 0x00000008  # DETACHED_PROCESS：GUI 独立存活
    if is_wlf:
        # **必须给 vsim 一个不 EOF 的 stdin**：GUI 进程里 Popen 继承到的 stdin
        # 是关闭的，vsim 跑完 `-do` 后读 stdin 立刻 EOF → **当场退出**（实测：
        # poll() 立刻返回 0，窗口一闪而过）。PIPE 只要**父进程还持有**就不 EOF；
        # 所以进程对象要挂在 module 上，别被 GC 掉。
        kwargs["stdin"] = subprocess.PIPE
    try:
        proc = subprocess.Popen([exe, *args], **kwargs)
    except OSError as exc:
        module.set_status(f"{what}打开失败（{label}）：{exc}")
        return
    if is_wlf:
        procs = getattr(module, "_wave_procs", None)
        if procs is None:
            procs = []
            module._wave_procs = procs
        procs[:] = [p for p in procs if p.poll() is None]
        procs.append(proc)
    if is_wlf:
        module.set_status(
            f"已用 vsim -view 打开{what}（Visualizer 只认 qwavedb；这轮回归没开 "
            f"wave 业务，所以只有 WLF）：{path}")
    else:
        module.set_status(f"已用 {label} 打开{what}：{path}")


def _show_report(module, report: Any, cached_note: str = "") -> bool:
    """`build_coverage_report` 的结果 → 打开它；成了返回 True。"""
    if not isinstance(report, dict) or report.get("status") != "PASS":
        why = (report or {}).get("error", "没拿到报告路径") if isinstance(report, dict) else ""
        module.set_status(f"覆盖率报告生成不了：{why}")
        return False
    _open_path(module, report["html"])
    module.set_status(f"已打开覆盖率报告{cached_note}：{report['html']}")
    return True


def _reveal(module, path: str) -> None:
    """报告生成不了时的兜底：把库/目录摆到眼前（别让这一下白点）。"""
    if path and Path(path).exists():
        target = str(Path(path).parent if Path(path).is_file() else Path(path))
        _open_path(module, target)
        module.set_status(f"报告生成不了，已打开所在目录：{target}")


def _launch_visualizer_ucdb(module, db_path: str, what: str) -> None:
    """`visualizer -ucdbfile <库>` —— 覆盖率交互式下钻（哪个 module/bin 没满）。

    **选项必须是 `-ucdbfile`**：实测 `visualizer -ucdb` 报 `Unknown option: -ucdb`
    然后退出。`questa.db`（`vsim -coverstore` 产物）、单用例 `.ucdb`、`vcover merge`
    后的合并库，三种都能开。

    **`questa.db` 要先转 UCDB**：它是 coverstore 索引，Visualizer 直接读它
    看不到功能覆盖率（与 `vcover` 同一条坑，见
    `coverage_tools.cov_api.materialize_ucdb`）。
    """
    if not db_path or not Path(db_path).exists():
        module.set_status(f"没有{what}的覆盖率库：{db_path or '(空)'}")
        return
    try:
        from src.tools.checking.coverage_tools.cov_api import materialize_ucdb

        ucdb, why = materialize_ucdb(str(db_path))
    except Exception as exc:                           # noqa: BLE001 界面不炸
        ucdb, why = "", str(exc)
    if why:
        module.set_status(f"{what}打开失败：{why}")
        return
    db_path = ucdb

    exe = visualizer_exe()
    if not exe:
        module.set_status(f"找不到 Questa Visualizer（visualizer.exe）—— "
                          f"装了 QuestaSim 才能开{what}：{db_path}")
        return
    kwargs: dict[str, Any] = {}
    if os.name == "nt":
        kwargs["creationflags"] = 0x00000008  # DETACHED_PROCESS
    try:
        subprocess.Popen([exe, "-ucdbfile", str(db_path)], **kwargs)
    except OSError as exc:
        module.set_status(f"{what}打开失败（Questa Visualizer）：{exc}")
        return
    module.set_status(f"已用 Questa Visualizer 打开{what}：{db_path}")


def open_case_coverage(module, db_path: str) -> None:
    """打开**一条用例**的覆盖率报告（库 → HTML → 浏览器）。"""
    if not db_path or not Path(db_path).exists():
        module.set_status("这条用例没有覆盖率库 —— 这轮回归的仿真业务里没开 `cov`"
                          "（工具栏「仿真业务」下拉可切）")
        return
    report = module.run_tool("flow.coverage_report", quiet=True, force=True,
                             db_path=db_path)
    if not _show_report(module, report,
                        "（复用已有报告）" if (report or {}).get("cached") else "（刚生成）"):
        _reveal(module, db_path)


def open_case_coverage_visualizer(module, db_path: str) -> None:
    """用 Visualizer 打开**一条用例**的覆盖率库 —— 看这个 test 覆盖到啥。

    与 `open_case_coverage`（HTML 报告，看"整份报告"）互补：这里是**可下钻**的
    交互视图（点 0 覆盖的 bin → 跳源码）。
    """
    if not db_path or not Path(db_path).exists():
        module.set_status("这条用例没有覆盖率库 —— 这轮回归的仿真业务里没开 `cov`"
                          "（工具栏「仿真业务」下拉可切）")
        return
    _launch_visualizer_ucdb(module, db_path, "这条用例的覆盖率")


def open_total_coverage(module, run_dir: str) -> None:
    """打开这次运行的**总覆盖率**报告。

    **优先用覆盖率阶段留下的那一份**（`sim/coverage/reports/index.html`）：
    它已经在了、就是当时 agent 看的那一份，打开是瞬时的。只有它不在时才拿合并
    库（`merged.ucdb`）现生成一份 —— 那是几分钟级动作里的一次性代价，值得。
    """
    if not run_dir:
        module.set_status("先选一次运行，再看总覆盖率")
        return
    info = module.run_tool("flow.run_coverage", quiet=True, run_dir=run_dir)
    if not isinstance(info, dict) or info.get("error") or module.report_payload_error(info):
        return

    report = info.get("report") or {}
    if report.get("exists"):
        _open_path(module, report["path"])
        module.set_status(f"已打开总覆盖率报告（覆盖率阶段生成的那一份）：{report['path']}")
        return

    db = (info.get("db") or {}).get("path") or ""
    if not db:
        module.set_status("这次运行没有总覆盖率产物 —— 还没跑到覆盖率收集，"
                          "或者收集中断（见「覆盖率」页）")
        return
    built = module.run_tool("flow.coverage_report", quiet=True, force=True,
                            db_path=db)
    if not _show_report(module, built, "（从合并库现生成）"):
        _reveal(module, db)


def open_total_coverage_visualizer(module, run_dir: str) -> None:
    """用 Visualizer 打开这次运行的**合并覆盖率库** —— 看"整体还差啥"。

    口径与 `open_total_coverage` 同源：都取 `flow.run_coverage` 报的合并库
    （`merged.ucdb`）。区别只在**打开方式**：HTML 报告看整份结论，Visualizer 看
    可下钻的缺口（哪个 module/covergroup/bin 还没满）。
    """
    if not run_dir:
        module.set_status("先选一次运行，再看总覆盖率")
        return
    info = module.run_tool("flow.run_coverage", quiet=True, run_dir=run_dir)
    if not isinstance(info, dict) or info.get("error") or module.report_payload_error(info):
        return
    db = (info.get("db") or {}).get("path") or ""
    if not db:
        module.set_status("这次运行没有总覆盖率产物 —— 还没跑到覆盖率收集，"
                          "或者收集中断（见「覆盖率」页）")
        return
    _launch_visualizer_ucdb(module, db, "总覆盖率（合并库）")
