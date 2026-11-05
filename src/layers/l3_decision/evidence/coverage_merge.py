"""回归逐用例覆盖库 → 计划覆盖率（vcover merge）—— 从采集文件拆出。

签核口径：95% 必须能回答"由哪些用例库合并而来"。这里只做合并与清单；
解析在 `cvg_parse`，采集入口仍在 `collect_real_coverage`。
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from config.settings import questa_exe

from .cvg_parse import _parse_cvg_text

def _write_merge_manifest(od: Path, out: Path, stores: list, specs: list,
                          merged: int, errors: list, warnings: list) -> str:
    """把"这次计划覆盖率由哪些库合并而来"落成机器可读清单。

    为什么不能只留 `plan_merged.ucdb`：签核要回答"95.23% 是从哪些用例库
    算出来的"。只有一份最终库，等于把**输入集合**藏了起来 —— 而输入集合
    正是可复现的那一半。清单里记相对路径 + 大小 + mtime + merged ucdb 的
    sha256；不复制库本体（体积大），但足以核对"是不是同一批输入"。
    """
    from src.layers.l1_infrastructure.infrastructure import sha256_file

    path = od / "coverage" / "plan_merge_manifest.json"
    old = []
    try:
        if path.is_file():
            old = (json.loads(path.read_text(encoding="utf-8", errors="replace"))
                   or {}).get("stores") or []
    except (OSError, ValueError):
        old = []
    old_by_rel = {e.get("path"): e for e in old if isinstance(e, dict)}

    entries = []
    for db in stores:
        try:
            rel = db.relative_to(od).as_posix()
        except ValueError:
            rel = str(db)
        try:
            st = db.stat()
            entry = {"path": rel, "size": st.st_size,
                     "mtime": int(st.st_mtime)}
        except OSError:
            entry = {"path": rel, "size": 0, "mtime": 0}
        # 单个 store 的 sha256 很贵（254 个库）。只在缓存里已有同路径同大小
        # 的旧值时复用；没有就留空（空 = 没算，不伪造）。
        prev = old_by_rel.get(rel)
        if prev and prev.get("size") == entry["size"]:
            entry["sha256"] = prev.get("sha256", "")
        else:
            entry["sha256"] = ""
        entries.append(entry)

    payload = {
        "schema": "plan_merge_manifest_v1",
        "store_count": len(stores),
        "merged_stores": merged,
        "stores": entries,
        "specs": list(specs),
        "merged_ucdb": str(out),
        "merged_sha256": sha256_file(out) if out.is_file() else "",
        "errors": errors,
        "warnings": warnings,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    except OSError:
        pass
    return str(path)

def merge_regression_coverage(od: Path) -> dict:
    """把**回归逐用例覆盖率库**合并成一份「计划覆盖率」。

    ## 为什么需要它（这是签核口径的问题，不是工具细节）

    原来的签核覆盖率来自覆盖率阶段**单独跑的一条 test**；而回归实际跑了 244 条
    用例，每条都 `-coverstore` 落了一份库。两个数字对不上时，签核用的是"另一条
    测试的覆盖率"—— 既不诚实，也让"补测试"对签核数字没有直接作用。

    这里把 `regression_run/**/cov/*/questa.db` 合并成 `plan_merged.ucdb`，
    并产出一份 `coverage_cvg_plan.txt` 供解析。签核与 TP 矩阵都改用它。

    ## coverstore 的读法（实测）

    - 有 `<test>.data`：`vcover merge "cov/<store>:<test>"`（cwd=用例目录）；
    - 只有 `(null).data`（历史 `-testname` 漏传）：`vcover merge "cov/<store>"`
      —— 带 `:test` 会让 vcover 崩溃。
    - **spec 必须带一层目录**（`cov/...`）；只写 `<store>:<test>` 会被当成目录名。

    合并是增量的（`-append`），244 条约 20 秒。失败**不抛**：返回 `errors`，
    调用方保留单测覆盖率并如实记账。
    """
    # **全部用绝对路径**：`cwd` + `-inputs` 的相对路径混用时，vcover 会把它
    # 当成另一份文件（实测 usage error）；绝对路径与手工验证过的命令一致。
    od = Path(od).resolve()
    reg_root = od / "regression_run"
    if not reg_root.is_dir():
        return {}
    stores = sorted(reg_root.rglob("cov/*/questa.db"))
    if not stores:
        return {}
    out_dir = od / "sim" / "coverage"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "plan_merged.ucdb"
    report_txt = out_dir / "reports" / "coverage_cvg_plan.txt"
    try:
        newest = max(p.stat().st_mtime for p in stores)
        if (out.is_file() and out.stat().st_mtime >= newest
                and report_txt.is_file()):
            # **缓存也要把解析结果带回来** —— 只给路径的话调用方拿不到
            # functional_pct，会误以为"计划覆盖率没生成"。
            detail = _parse_cvg_text(
                report_txt.read_text(encoding="utf-8", errors="replace"))
            manifest = od / "coverage" / "plan_merge_manifest.json"
            return {"ucdb": str(out), "report": str(report_txt),
                    "stores": len(stores), "merged": len(stores),
                    "functional_pct": detail.get("functional_pct", 0.0),
                    "functional_detail": detail, "cached": True,
                    "manifest": str(manifest) if manifest.is_file() else "",
                    "errors": [], "warnings": []}
    except OSError:
        pass

    vcover = questa_exe("vcover.exe")
    if not os.path.exists(vcover):
        return {"error": f"vcover not found: {vcover}", "stores": len(stores)}

    # **一条命令合并全部输入**（而不是逐条 `-append`）。
    #
    # 逐条 append 时 vcover 会在同一个输出文件上反复建/删锁；前一次锁没释放，
    # 下一条就报 "DB file ... in write mode"（实测）。一次给全量输入没有这个问题，
    # 也快得多（244 条约 20 秒）。
    #
    # spec 用**相对运行根**的路径（`regression_run/.../cov/<test>[:<test>]`）：
    # 绝对路径里的盘符冒号会和 coverstore 的 `store:test` 分隔符冲突。
    tmp = out.with_name("plan_merged_build.ucdb")
    # 清掉上一次中断留下的临时库 / 锁（vcover 对残留锁会拒绝写）
    for junk in (tmp, Path(str(tmp) + "._lock"),
                 Path(str(tmp) + ".questatmp")):
        try:
            junk.unlink()
        except OSError:
            pass
    specs = []
    for db in stores:
        store = db.parent
        data = sorted(store.glob("*.data"))
        stem = (data[0].stem if len(data) == 1
                else (store.name if not data else
                      max(data, key=lambda x: x.stat().st_mtime).stem))
        null_test = (not stem) or stem in ("(null)", "null")
        try:
            rel = store.relative_to(od).as_posix()
        except ValueError:
            continue
        specs.append(rel if null_test else f"{rel}:{stem}")
    errors = []
    warnings = []
    merged = 0
    if specs:
        # **用 `-inputs <cmdfile>`**：244 条 spec 直接上命令行会超过 Windows 的
        # 命令行长度上限（实测 `[WinError 206] 文件名或扩展名太长`）。
        cmdfile = out_dir / "plan_merge_inputs.txt"
        try:
            cmdfile.write_text("\n".join(specs) + "\n", encoding="utf-8")
            proc = subprocess.run([vcover, "merge", "-inputs", str(cmdfile), str(tmp)],
                                  cwd=str(od), capture_output=True, text=True,
                                  errors="replace", timeout=600)
        except (OSError, subprocess.SubprocessError) as e:
            errors.append(str(e))
            proc = None
        if proc is not None:
            if proc.returncode != 0 or not tmp.is_file():
                errors.append(((proc.stdout or "") + (proc.stderr or "")).strip()[-300:])
            else:
                merged = len(specs)
                # "Design hierarchy mismatch" 是**代码覆盖率**的合并告警
                # （loopback TB 与 DUT TB 的层次不同，属正常）；功能覆盖照样合并。
                # 不当错误处理，只留在 warnings 里供报告引用。
                tail = ((proc.stdout or "") + (proc.stderr or "")).strip()
                if "Design hierarchy mismatch" in tail:
                    warnings.append("部分用例的代码覆盖层次不同（loopback vs DUT），"
                                    "功能覆盖已合并；代码覆盖按层次跳过")

    if not tmp.is_file():
        return {"stores": len(stores), "merged": merged, "errors": errors}
    tmp.replace(out)

    detail = {}
    try:
        r = subprocess.run([vcover, "report", "-cvg", "-details", str(out)],
                           capture_output=True, text=True, errors="replace",
                           timeout=180)
        report_txt.parent.mkdir(parents=True, exist_ok=True)
        report_txt.write_text(r.stdout or "", encoding="utf-8", errors="replace")
        detail = _parse_cvg_text(r.stdout or "")
    except (OSError, subprocess.SubprocessError) as e:
        errors.append(f"report: {e}")
    manifest = _write_merge_manifest(od, out, stores, specs, merged,
                                     errors, warnings)
    return {"ucdb": str(out), "report": str(report_txt),
            "stores": len(stores), "merged": merged,
            "functional_pct": detail.get("functional_pct", 0.0),
            "functional_detail": detail, "manifest": manifest,
            "errors": errors, "warnings": warnings}
