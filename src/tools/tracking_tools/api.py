"""跟踪表工具的程序化接口 —— 读一份 YAML，吐 dict。

只有一个函数 `run_tracking(path)`：把 `tracking.yaml` 里的测试点与验证资产
规范化成两张表的行，并做**引用一致性检查**（测试点引用的资产是否存在）。

失败**响亮**（与全仓库一致）：文件没有、YAML 坏、顶层不是一个映射 —— 一律
返回 `{"error": "...（怎么修）"}` 而不是抛异常，让界面把它变成一条横幅。
**悬空的资产引用不丢行**：行照常返回，引用对不上的在 `counts.unresolved`
与 `unresolved` 里记账 —— 静默丢会让人以为「这条测试点没有资产」，而真相是
「它引的资产没登记」。

返回值一律是 **dict**（不是 JSON 字符串）：需要字符串的调用方自己 json.dumps。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import yaml

#: 测试点表每行补齐的默认值 —— 少写一个键不该让整份文件读不出来
_TESTPOINT_DEFAULTS = {
    "feature": "", "description": "", "priority": "P1",
    "method": "", "status": "planned",
}
#: 验证资产表每行补齐的默认值
_ASSET_DEFAULTS = {
    "type": "", "path": "", "hash": "", "status": "", "note": "",
}


def run_tracking(path: str = "") -> Dict[str, Any]:
    """tracking.yaml → 测试点 / 验证资产两张表的行。

    返回：`{"project", "testpoints": [...], "assets": [...],
             "counts": {...}, "unresolved": [...]}`
    """
    if not isinstance(path, str) or not path.strip():
        return {"error": "没有给 tracking.yaml 的路径"}

    target = Path(path)
    if not target.exists():
        return {"error": f"找不到跟踪表文件：{target}"
                         f"（清单里模块的 `input:` 指向它，相对清单目录解析）"}
    if target.is_dir():
        return {"error": f"跟踪表路径是一个目录而不是文件：{target}"}

    try:
        text = target.read_text(encoding="utf-8")
    except OSError as exc:
        return {"error": f"读不了跟踪表 {target}：{exc}"}

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        return {"error": f"跟踪表 YAML 解析失败：{exc}"}

    if data is None:
        return {"error": f"跟踪表是空的：{target}"}
    if not isinstance(data, dict):
        return {"error": "跟踪表顶层必须是一个映射（要有 project / testpoints / assets）"}

    assets = _normalize_assets(data.get("assets"))
    asset_ids = {a["id"] for a in assets}
    testpoints, unresolved, ref_index = _normalize_testpoints(
        data.get("testpoints"), asset_ids)

    # 反向索引：某资产被哪些测试点引用 —— 资产页显示 + 跨表高亮联动。
    # `testpoints` 是给表格直接显示的字符串；`testpoint_refs` 是列表，供联动。
    for asset in assets:
        refs = ref_index.get(asset["id"], [])
        asset["testpoints"] = "、".join(refs)
        asset["testpoint_refs"] = refs

    return {
        "project": str(data.get("project", "") or ""),
        "testpoints": testpoints,
        "assets": assets,
        "unresolved": unresolved,
        "counts": {
            "testpoints": len(testpoints),
            "assets": len(assets),
            "unresolved": len(unresolved),
        },
    }


def _normalize_testpoints(raw: Any, asset_ids: set) -> tuple:
    """测试点列表 → (行, 悬空引用清单, 资产→引用它的测试点 索引)。

    引用到的资产 id 收集成 `assets`（逗号分隔的字符串）供表格直接显示；
    对不上的记进 `unresolved`，**行不丢**。
    """
    testpoints: List[Dict[str, Any]] = []
    unresolved: List[Dict[str, str]] = []
    ref_index: Dict[str, List[str]] = {}

    for index, entry in enumerate(raw or []):
        if not isinstance(entry, dict):
            continue
        row = dict(_TESTPOINT_DEFAULTS)
        row["id"] = str(entry.get("id", f"TP_{index + 1:03d}"))
        for key in _TESTPOINT_DEFAULTS:
            if entry.get(key) not in (None, ""):
                row[key] = str(entry[key])

        refs = entry.get("assets") or []
        if isinstance(refs, str):
            refs = [refs]
        refs = [str(r) for r in refs]
        row["assets"] = "、".join(refs)
        #: 引用清单（列表，不去重）—— 界面跨表高亮靠它，别拿 `assets` 去 split
        row["asset_refs"] = refs

        for ref in refs:
            if ref in asset_ids:
                ref_index.setdefault(ref, []).append(row["id"])
            else:
                row["has_unresolved"] = True
                unresolved.append({"testpoint": row["id"], "asset": ref})

        testpoints.append(row)

    return testpoints, unresolved, ref_index


def _normalize_assets(raw: Any) -> List[Dict[str, Any]]:
    """验证资产列表 → 行（补默认值）。"""
    assets: List[Dict[str, Any]] = []
    for index, entry in enumerate(raw or []):
        if not isinstance(entry, dict):
            continue
        row = dict(_ASSET_DEFAULTS)
        row["id"] = str(entry.get("id", f"ASSET_{index + 1:03d}"))
        for key in _ASSET_DEFAULTS:
            if entry.get(key) not in (None, ""):
                row[key] = str(entry[key])
        assets.append(row)
    return assets
