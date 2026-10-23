"""覆盖率库 → **人看得懂的东西** —— 给界面「点开用例的覆盖率」用的薄壳。

## 为什么"打开覆盖率"不是打开一个文件

覆盖率库（`questa.db` / `*.ucdb`）是二进制：双击它，操作系统要么不知道该用什么
打开、要么弹一个没有二进制的错误框。**人对不上账。** 能校对的是 HTML 报告 ——
`vcover report -html` 把每个 covergroup / bin 的命中数摊成一张可点的页面。

所以"打开覆盖率"的真实动作是**先生成报告、再打开 HTML**。这一步不做判断：
覆盖率算不算够是覆盖率阶段与签核门禁的事（见 `coverage_map` / `quality_guard`），
这里只负责把已经跑出来的库摊开给人看。

## 报告落在哪、什么时候复用

`<覆盖率库所在目录>/_vcover_html/`。**比库新就直接复用** —— 一条用例点第二次
不该再跑一遍 vcover。库重跑过（mtime 变新）就重建，不然人看的还是上一轮的数，
那比不显示更坏。
"""
from __future__ import annotations

import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, Tuple

#: HTML 报告目录名（落在覆盖率库旁边）
HTML_DIR_NAME = "_vcover_html"

#: Questa 的覆盖率库文件名 —— `vsim -coverstore <dir>` 在 `<dir>` 里产出的那个。
#: 旁边还有个 `<name>.data`，但 `vcover` **不认它**（实测 `vcover-6808`），
#: 别把它当库收进来。
QUESTA_DB_NAME = "questa.db"

#: vcover 超时：报告是分钟级以下的活，给足但别把界面挂死
_TIMEOUT_S = 300.0


def file_facts(path: Any) -> Dict[str, Any]:
    """一个产物文件的**事实**：在不在、多大、什么时候写的。

    页面靠它回答"这份产物是不是这轮跑出来的" —— 时间字段是为此存在的，
    不是装饰。读不到就当"没有"（`exists=False`），**不算错误**：可能就是没开
    那门业务，那是正常的，不是故障。
    """
    out: Dict[str, Any] = {"path": str(path or ""), "exists": False,
                           "kb": None, "time": ""}
    if not path:
        return out
    try:
        st = Path(path).stat()
    except OSError:
        return out
    out["exists"] = True
    out["kb"] = round(st.st_size / 1024, 1)
    out["time"] = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    return out


def find_run_coverage(run_dir: Any) -> Dict[str, Any]:
    """这次运行的**总覆盖率**落在哪 → `{dir, db, report}`（都过 `file_facts`）。

    两份产物各有各的用处，**都要报**：

      · `db`     —— `sim/coverage/merged.ucdb`，合并库。逐条用例的库要合并才
                    能看"整个环境覆盖了多少"，想自己重新出报告就靠它。
      · `report` —— `sim/coverage/reports/index.html`。**覆盖率阶段已经生成的那份**：
                    打开它最快，而且它就是当时 agent 看的那一份。优先用它，
                    没有才拿 db 现生成（见 `build_coverage_report`）。
    """
    cov_dir = Path(run_dir) / "sim" / "coverage"
    db = ""
    if cov_dir.is_dir():
        merged = cov_dir / "merged.ucdb"
        if merged.is_file():
            db = str(merged)
        else:
            newest = _newest(list(cov_dir.glob("*.ucdb")))
            db = str(newest) if newest else ""
    return {"dir": str(cov_dir), "db": file_facts(db),
            "report": file_facts(cov_dir / "reports" / "index.html")}


def functional_coverage_details(run_dir: Any) -> Tuple[list, str]:
    """逐 covergroup/coverpoint 的**实测**覆盖率 → `(covergroups, 文本路径)`。

    读的是覆盖率阶段留下的那份文本（`sim/coverage/reports/coverage_cvg.txt`，
    `vcover report -cvg -details` 的原始输出）—— **不重跑 vcover**：那要几分钟，
    而这份文件就是当时判定用的那一份，两边不一致才是问题。

    解析在 `src/tools/lib/collect_real_coverage._parse_cvg_details`（**一处实现**）：
    覆盖率工具这边只负责"文件在哪、读出来"，语法是那条链路自己的领域知识 ——
    抄一份到这里就是第二份真相。

    文件不在就返回 `([], "")`：这轮没跑到覆盖率收集，不是一个错误。
    """
    path = Path(run_dir) / "sim" / "coverage" / "reports" / "coverage_cvg.txt"
    if not path.is_file():
        return [], ""
    try:
        from src.tools.lib.collect_real_coverage import _parse_cvg_details

        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return [], ""
    return _parse_cvg_details(text), str(path)


def _newest(paths: Iterable[Path]) -> Path | None:
    """候选里挑**最新写的**那个文件。

    一条用例可能有多轮覆盖数据（重跑留下的）。按 mtime 挑才对得上"最后跑出来的
    这一次"；按名字排是在挑文件名，不是在挑时间。目录不算（库是文件）。
    """
    files = [p for p in paths if p.is_file() and p.stat().st_size > 0]
    return max(files, key=lambda p: p.stat().st_mtime) if files else None


def find_coverage_db(test_dir: str | Path) -> Tuple[str, str]:
    """这条用例的**覆盖率库** → `(路径, 来源)`；没有就 `("", "none")`。

    两级来源，与波形那一列同一个口径（记录 > 现场，且都标出来源）：

      · `cm_dir` —— 配置指定的落点 `<用例目录>/cov/**`（回归的覆盖率业务把
        `-coverstore` 指到 `${EMAN_CM_DIR}`，框架把它设成 `<用例目录>/cov`）；
      · `sim_dir` —— 用例目录下仿真器默认落的 `*.ucdb`。

    都找不到就老实地给空 —— 不返回一个"看起来能打开"的假路径。
    """
    d = Path(test_dir)
    if not d.is_dir():
        return "", "none"

    cov_root = d / "cov"
    if cov_root.is_dir():
        hit = (_newest(cov_root.rglob(QUESTA_DB_NAME))
               or _newest(cov_root.rglob("*.ucdb")))
        if hit:
            return str(hit), "cm_dir"

    hit = _newest(list(d.glob("*.ucdb")) + list(d.glob("*.vdb")))
    if hit:
        return str(hit), "sim_dir"
    return "", "none"


def _vcover_binary() -> str:
    """`vcover` 可执行文件 —— 先问 Questa 安装目录，再回落 PATH（找不到给空串）。"""
    try:
        from config.settings import questa_exe

        cand = questa_exe("vcover.exe")
        if Path(cand).exists():
            return cand
    except Exception:                                  # noqa: BLE001 取不到就走 PATH
        pass
    return shutil.which("vcover") or shutil.which("vcover.exe") or ""


def materialize_ucdb(db_path: str, *, force: bool = False) -> Tuple[str, str]:
    """覆盖率库 → **可被 vcover / Visualizer 读取的 UCDB**，失败给 `(路径, 原因)`。

    ## 为什么需要这一步（实测）

    回归的 `-coverstore <store> -testname <test>` 产物是：

        <store>/questa.db        ← 覆盖率**存储索引**
        <store>/<test>.data      ← 实际数据

    `vcover report -cvg <store>/questa.db` 只报 **"No matching coverage data"**，
    代码覆盖率（`-codeAll`）却读得到 —— 也就是**功能覆盖率整段丢失**。原因不是
    没采到（用例日志里 covergroup 明明有命中），而是**读法不对**：

        vcover merge <out.ucdb> "<store>:<test>"

    才是 coverstore 的入口。转换后的 UCDB 同时能给 `vcover report` 和
    `visualizer -ucdbfile` 用。

    ## 缓存

    结果落在 `<store>/_ucdb/<test>.ucdb`；比 `questa.db` 新就直接复用 ——
    点第二次不该再等一次 merge。库重跑过（mtime 变新）就重做。

    **Windows 的冒号坑**：`<store>:<test>` 里的 `:` 会和盘符 `D:` 混淆（实测
    `vcover` 把整串当 UCDB 文件名打开失败）。所以命令在 `store.parent` 下执行，
    spec 只用**相对目录名**：`npu_basic_test:npu_basic_test`。
    """
    p = Path(db_path) if db_path else None
    if p is None or not p.exists():
        return "", f"覆盖率库不存在：{db_path or '(空)'}"
    if p.suffix.lower() == ".ucdb":
        return str(p), ""                     # 已经是 UCDB，不用转
    if p.name != QUESTA_DB_NAME:
        return str(p), ""                     # 其它格式直接交给 vcover 自己判

    store = p.parent
    data_files = sorted(store.glob("*.data"))
    test = (data_files[0].stem if len(data_files) == 1
            else (store.name if not data_files else
                  max(data_files, key=lambda x: x.stat().st_mtime).stem))
    # **`(null).data` 是 `-testname` 漏传的产物**（`cov+wave` 曾经的 bug）。
    # 这种 store 没有 test 名，`vcover merge "store:test"` 会崩（vcover 内部错误）；
    # 正确写法是只给 store 路径：`vcover merge out "cov/npu_basic_test"`，
    # 它会自己报 `Merging test cov/npu_basic_test:(null)`。输出名用目录名。
    null_test = (not test) or test in ("(null)", "null")
    if null_test:
        test = store.name
    out_dir = store / "_ucdb"
    # **输出必须是绝对路径**：`vcover` 的 `cwd` 被设成 `store.parent`（为了让
    # `store:test` 保持相对、避开盘符冒号），此时相对输出路径会落到那个 cwd 下
    # —— 实测 vcover 报 "...ucdb.questatmp: Failed to open in write mode"。
    out = (out_dir / f"{test}.ucdb").resolve()
    try:
        if (not force and out.is_file()
                and out.stat().st_mtime >= p.stat().st_mtime):
            return str(out), ""
    except OSError:
        pass

    vcover = _vcover_binary()
    if not vcover:
        return "", "找不到 vcover（QuestaSim 的覆盖率工具）—— 无法读取 coverstore"
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        # **spec 里必须带一层目录**（`cov/<test>`）：
        # `cwd=test_dir`，`store` 相对它是 `cov/<test>`；只写 `<test>:<test>`
        # 会被 vcover 当成一个目录名去找 `.../merged.mdata*`（实测）。
        # 带 test 名时是 `cov/<test>:<test>`；null test 时只给 `cov/<test>`。
        cwd = store.parent.parent
        rel = store.relative_to(cwd).as_posix()
        spec = rel if null_test else f"{rel}:{test}"
        proc = subprocess.run(
            [vcover, "merge", str(out), spec],
            cwd=str(cwd.resolve()), capture_output=True, text=True,
            errors="replace", timeout=_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError) as e:
        return "", f"vcover merge 跑不起来：{e}"
    if not out.is_file():
        tail = ((proc.stdout or "") + (proc.stderr or "")).strip()[-400:]
        return "", tail or f"vcover merge 没产出 UCDB（退出码 {proc.returncode}）"
    return str(out), ""


def build_coverage_report(db_path: str, output_dir: str = "",
                          force: bool = False) -> Dict[str, Any]:
    """覆盖率库 → HTML 报告。返回 `{status, html, output_dir, cached, error}`。

    **失败响亮**：库不在 / vcover 找不到 / vcover 报错，都如实说清是哪一个 ——
    调用方（界面）据此告诉人"为什么点了没反应"。不抛异常。
    """
    raw = Path(db_path) if db_path else None
    if raw is None or not raw.exists():
        return {"status": "FAIL", "error": f"覆盖率库不存在：{db_path or '(空)'}"}

    # coverstore（`questa.db`）先转成 UCDB —— 否则 `vcover report -cvg` 只能读到
    # 代码覆盖率，功能覆盖率会**静默丢失**（见 `materialize_ucdb` 的实测说明）。
    materialized, why = materialize_ucdb(str(raw), force=force)
    if why:
        return {"status": "FAIL", "db": str(raw), "error": why}
    db = Path(materialized)

    out = Path(output_dir) if output_dir else db.parent / HTML_DIR_NAME
    index = out / "index.html"
    try:
        # 库跑过之后没再动过 → 旧报告还能用（点第二次不该再等等几秒）
        if (not force and index.is_file()
                and index.stat().st_mtime >= db.stat().st_mtime):
            return {"status": "PASS", "html": str(index), "output_dir": str(out),
                    "cached": True, "db": str(db)}
    except OSError:
        pass

    vcover = _vcover_binary()
    if not vcover:
        return {"status": "FAIL", "db": str(db),
                "error": "找不到 vcover（QuestaSim 的覆盖率工具）—— 报告生成不了"}
    try:
        out.mkdir(parents=True, exist_ok=True)
        proc = subprocess.run(
            [vcover, "report", "-html", "-output", out.as_posix(), db.as_posix()],
            capture_output=True, text=True, errors="replace", timeout=_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError) as e:
        return {"status": "FAIL", "db": str(db), "error": f"vcover 跑不起来：{e}"}

    if not index.is_file():
        tail = ((proc.stdout or "") + (proc.stderr or "")).strip()[-400:]
        return {"status": "FAIL", "db": str(db), "returncode": proc.returncode,
                "error": tail or f"vcover 没产出 index.html（退出码 {proc.returncode}）"}

    return {"status": "PASS", "html": str(index), "output_dir": str(out),
            "cached": False, "db": str(db), "returncode": proc.returncode}
