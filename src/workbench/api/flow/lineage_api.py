"""血缘视角的查询/对比 —— CLI 的那一半。

`compare_runs(baseline, current)` 早就有了，缺的是**"baseline 是谁"**：
调用方得自己记住首次那两个目录名（`output_npu2_jiang_20261012_230152` 这种），
记错了比比皆是，而且没有任何东西会报。这里把血缘库里的锚点接上去：

    resolve_baseline_for(module)      → 这个模块的首次 run（锚点）
    baseline_of_run(run_dir)          → 从 **一次具体的 run** 反查它的模块与锚点
    compare_against_baseline(run)     → 直接出 `compare_runs` 的结果

口径要说清：基准 = **每个模块的第一次 run**（`run_baselines` 表，首次写入后不再改）。
"相对最初那版偏了多少"是复现与签核都要回答的问题，而且它是**单调**的；
"上一轮"会随跑的次数漂（同一个 RTL 版本跑三次，"上一轮"是三次不同的东西）。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from src.knowledge_plane.lineage import LineageStore


def resolve_baseline_for(module: str) -> Optional[Dict[str, Any]]:
    """模块 → 首次 run 的锚点（`{run_id, version_no, name}`）；没锚过返回 None。"""
    if not module:
        return None
    store = LineageStore()
    try:
        return store.get_baseline(str(module).strip())
    finally:
        store.close()                                      # Windows 文件锁


def baseline_of_run(run_dir) -> Optional[Dict[str, Any]]:
    """**从一次具体的 run** 反查它的模块与基准 —— CLI 只拿到目录时走这条。

    先看这个 run 跑的是哪一版（`run_rtl_bindings`）；那条记录里就带着模块名，
    再拿模块名去查锚点。这个 run 自己**没被绑过版本**（老 run / 没有 RTL）时
    返回 None —— 那是"不知道"，不是"没有基准"。
    """
    run_id = Path(run_dir).name
    store = LineageStore()
    try:
        binding = store.version_by_run(run_id)
        if not binding:
            return None
        base = store.get_baseline(binding["module"])
        if not base:
            return None
        return {**base, "current_version_no": binding["version_no"],
                "current_version": binding["name"], "run_id_current": run_id}
    finally:
        store.close()


def module_candidates(repo_root=".") -> list:
    """仓库里能枚举出来的**模块名**集合 —— 给老用例归位用。

    三个来源，都是"这个设计确实存在过"的证据：

      · `specs/<模块>/` 目录名
      · 各 run 的 `spec.json` 里 `design_name`
      · 用例库里**已有的**非空 `module` 值（新写入的行）

    为什么要枚举而不是按名字猜：归位要判"这个名字属于哪个模块"，而
    `test_apb_uart_case_basic` 同时命中 `apb` 与 `apb_uart`。有了一份真模块名
    清单，就能**取最长匹配**（`apb_uart` 赢），不会把 A 的用例算到 B 头上。
    """
    root = Path(repo_root)
    mods = {p.name for p in (root / "specs").glob("*") if p.is_dir()}
    for sp in root.glob("output_*/spec.json"):
        try:
            import json as _json
            dn = (_json.loads(sp.read_text(encoding="utf-8",
                                            errors="replace")) or {}).get("design_name")
            if dn:
                mods.add(str(dn))
        except Exception:                                  # noqa: BLE001
            continue
    store = LineageStore()
    try:
        mods |= {v["module"] for v in store.list_versions("")}
    finally:
        store.close()
    mods.discard("")
    mods.discard("dut")            # 兜底名，不是模块身份
    return sorted(mods)


def bind_testcase_modules(candidates=None, db_path: Optional[str] = None,
                          apply: bool = False) -> Dict[str, Any]:
    """把用例库里的老行归位（`TestcaseRegistry.bind_modules` 的入口）。

    `candidates` 缺省时现枚举（`module_candidates()`）。干跑（`apply=False`）
    也返回完整归属表 —— 让人先看一眼再写。
    """
    from src.knowledge_plane.testcase_registry import TestcaseRegistry

    cands = list(candidates) if candidates else module_candidates()
    reg = TestcaseRegistry(db_path)
    try:
        out = reg.bind_modules(cands, apply=apply)
    finally:
        reg.close()
    out["candidates"] = sorted(cands)
    return out


def lineage_versions(module: str = "") -> list:
    """版本表（`module` 空则全部）。"""
    store = LineageStore()
    try:
        return store.list_versions(module)
    finally:
        store.close()


def prune_lineage(keep_last: int = 50, module: str = "",
                  dry_run: bool = False) -> Dict[str, Any]:
    """清理**孤儿**版本行（见 `LineageStore.prune` 的三条判据）。

    默认 `dry_run=True` —— 先给人看一眼要删什么再动手。这张库是签核回溯的锚，
    删错一条（比如某个基准）会让"这版和最初那版差多少"永久答不出来。
    """
    store = LineageStore()
    try:
        return store.prune(keep_last=keep_last, module=module, dry_run=dry_run)
    finally:
        store.close()


def lineage_bugs(module: str = "", version_no: Optional[int] = None) -> list:
    """bug ↔ RTL 版本（`module`/`version_no` 都可缺省）。"""
    store = LineageStore()
    try:
        return store.bugs_of_version(module, version_no)
    finally:
        store.close()


def compare_against_baseline(current: str, baseline: str = "",
                             module: str = "") -> Dict[str, Any]:
    """`current` run 与**它的基准**对比（`baseline` 显式给了就用它）。

    显式 `baseline` 优先：人可能就是想比另外那一次。自动解析失败时**明说**，
    不让上层拿一个空结果去当成"没有差异"。
    """
    from src.workbench.api.flow.api import compare_runs

    base_dir = ""
    if baseline:
        base_dir = str(baseline)
    else:
        anchor = baseline_of_run(current)
        if anchor is not None:
            base_dir = _run_dir_of(anchor["run_id"])
        elif module:
            anchor = resolve_baseline_for(module)
            if anchor is not None:
                base_dir = _run_dir_of(anchor["run_id"])
    if not base_dir:
        return {"error": "这个 run 没有血缘锚点（没绑过 RTL 版本，或还没有过首次会话）"
                         "—— 用 `vagent lineage baseline <模块>` 看看锚在哪，"
                         "或显式给 `--baseline <目录>`"}
    result = compare_runs(baseline=base_dir, current=str(current))
    result["baseline_dir"] = base_dir
    return result


def _run_dir_of(run_id: str) -> str:
    """`run_id`（= run 目录名）→ **目录路径**。

    先按 run_id 直接找（相对 cwd / output 目录），再走 `RunRepository` 的发现逻辑
    —— 那份逻辑认识两种布局（`output/<name>/` 与 `output_<user>_<ts>/`），
    自己再拼一次路径就会漏掉一种。
    """
    p = Path(run_id)
    if p.is_dir():
        return str(p)
    try:
        from src.orchestration_plane.l2.run_repository import RunRepository

        for d in RunRepository().run_dirs():
            if Path(d).name == run_id:
                return str(d)
    except Exception:                                      # noqa: BLE001
        pass
    return run_id
