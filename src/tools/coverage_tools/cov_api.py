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


def build_coverage_report(db_path: str, output_dir: str = "",
                          force: bool = False) -> Dict[str, Any]:
    """覆盖率库 → HTML 报告。返回 `{status, html, output_dir, cached, error}`。

    **失败响亮**：库不在 / vcover 找不到 / vcover 报错，都如实说清是哪一个 ——
    调用方（界面）据此告诉人"为什么点了没反应"。不抛异常。
    """
    db = Path(db_path) if db_path else None
    if db is None or not db.exists():
        return {"status": "FAIL", "error": f"覆盖率库不存在：{db_path or '(空)'}"}

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
