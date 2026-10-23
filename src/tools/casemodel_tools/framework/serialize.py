"""IR 序列化 —— **一份实现，两个调用方**。

`MethodBundle.testpoints_yaml()` 与 `plan.testpoints_yaml(payload)` 必须产出
**逐字节相同**的文本：manifest 里的 IR 哈希算的就是这份文本。两处各写一份
的话，哈希会对不上实际落盘的文件 —— 而"文件被换过没有"正是证据链要回答的。
"""
from __future__ import annotations

from typing import Any, Dict

from .contracts import FRAMEWORK_NAME, FRAMEWORK_VERSION


def testpoints_yaml(payload: Dict[str, Any]) -> str:
    """payload（`MethodBundle.to_dict()` 的形状）→ YAML 文本。"""
    import yaml as _yaml

    header = (
        "# ============================================================\n"
        "# 测试点 IR —— **由 case 模型生成**，请勿手改\n"
        "# ============================================================\n"
        "# 一个 tp_id 就是一条：需求 → 激励 → 覆盖仓 → test → 回归级 → 判据。\n"
        "# `realization.kind` 决定它怎么被实现（可用注册表扩展）。\n"
    )
    body = _yaml.safe_dump(
        {"version": FRAMEWORK_VERSION,
         "framework": FRAMEWORK_NAME,
         "count": payload.get("count", 0),
         "by_kind": payload.get("by_kind", {}),
         "by_stage": payload.get("by_stage", {}),
         "testpoints": payload.get("testpoints", [])},
        allow_unicode=True, sort_keys=False, width=110)
    return header + body
