"""测试点 IR 序列化 —— VPlan 自带的一份实现。

manifest 里的 IR 哈希算的就是这份文本，所以落盘必须与哈希输入逐字节一致；
别处不得再拼一份 YAML。
"""
from __future__ import annotations

from typing import Any, Dict

FRAMEWORK_NAME = "signoff-methodology"
FRAMEWORK_VERSION = "1.0"


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
    # `config_instances` 是**执行实例维度**（同一 TP × 配置组合），体积随组合数
    # 放大且与 TP 语义无关；YAML（人读的 IR / manifest 哈希）不收录它，
    # JSON payload 里保留。这样 manifest 哈希仍与实际落盘的 YAML 一致。
    testpoints = [
        {k: v for k, v in tp.items() if k != "config_instances"}
        for tp in payload.get("testpoints", []) if isinstance(tp, dict)
    ]
    body = _yaml.safe_dump(
        {"version": FRAMEWORK_VERSION,
         "framework": FRAMEWORK_NAME,
         "count": payload.get("count", 0),
         "by_kind": payload.get("by_kind", {}),
         "by_stage": payload.get("by_stage", {}),
         "testpoints": testpoints},
        allow_unicode=True, sort_keys=False, width=110)
    return header + body
