"""落盘 —— 按文档 §3.6 的布局写出编译产物。

**这是本工具唯一有副作用的模块。** 单独放一个文件而不是塞进 `api.py`，
是为了让那条界线看得见：`api.py` 的四个 `run_*` 都是纯的（进 dict 出 dict），
要写盘就得显式走到这里。

为什么 CLI 与界面共用它
    两处各写一遍落盘逻辑，迟早有一处先改 —— 而"落盘布局"是文档规定的契约
    （§3.6），不是各人的实现细节。

**缺什么就少写什么**：`seq.hex` 要编码器（v0 没有）、`tensors/` 要 tensor_gen
（独立工具）。不写空占位文件 —— 一个空的 `seq.hex` 比没有它更容易让人
以为"生成过了"。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

#: 文件名 → 从编译产物里取哪一段。`None` 表示取 `ir`。
ARTIFACTS: Tuple[Tuple[str, Any], ...] = (
    ("case.json", "case"),
    ("seq.ir.json", None),
    ("preload.json", "preload"),
    ("expect.json", "expect"),
)

#: 本工具**不产**的那两份，以及为什么 —— 一起给出去，省得人找
NOT_PRODUCED = (
    ("seq.hex", "要编码器（IR → 32bit），不在本工具"),
    ("tensors/*.hex", "要 tensor_gen（独立工具），本工具只给 ref 句柄"),
)


def write_artifacts(out_dir: str | Path, payload: Dict[str, Any]) -> Dict[str, Any]:
    """把编译产物写进目录。

    **返回 dict 而不是文件名列表** —— 这个工具的调用面（bridge / Agent 适配器）
    统一约定 `run_*` 进 dict 出 dict，落盘这条也不例外。返回 list 的话，
    界面那边写 `result.get("written")` 会拿到 `AttributeError: 'list' object
    has no attribute 'get'`（这个 bug 真的出现过）。

    失败抛 `OSError` —— 调用方（CLI / 界面）自己决定怎么报。
    这一层不吞异常：写不进去是真实故障，不是"渲染问题"。
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written: List[str] = []
    for filename, key in ARTIFACTS:
        body = payload.get("ir", {}) if key is None else payload.get(key, {})
        (out / filename).write_text(
            json.dumps(body, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        written.append(filename)
    return {"out_dir": str(out), "written": written,
            "not_produced": [{"file": name, "reason": why}
                             for name, why in NOT_PRODUCED]}
