"""落盘 —— 按文档 §3.6 的布局写出编译产物。

**这是本工具唯一有副作用的模块。** 单独放一个文件而不是塞进 `api.py`，
是为了让那条界线看得见：`api.py` 的四个 `run_*` 都是纯的（进 dict 出 dict），
要写盘就得显式走到这里。

为什么 CLI 与界面共用它
    两处各写一遍落盘逻辑，迟早有一处先改 —— 而"落盘布局"是文档规定的契约
    （§3.6），不是各人的实现细节。

**缺什么就少写什么**：`tensors/` 要 tensor_gen（独立工具）。不写空占位文件
—— 一个空的 `seq.hex` 比没有它更容易让人以为"生成过了"。

`seq.hex` / `reg-init.txt` 由 `encode/` 那层产（§3.1 的 L3）。它们**不是 JSON**
（ISS 要按行读 32bit 字），所以走单独一条写入路径。
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

#: L3 编码产物 —— 文本，不是 JSON。`(文件名, encode dict 里的键)`。
#: `seq.lst` 是**人读的**：`seq.hex` 只有裸 32bit 字，看不出是哪条指令。
#: 两者逐行对应（第 n 个字的 off = n*4），可对着 ISS 的 PC 找。
TEXT_ARTIFACTS: Tuple[Tuple[str, str], ...] = (
    ("seq.hex", "seq_hex"),
    ("seq.lst", "listing"),
    ("reg-init.txt", "reg_init"),
)

#: 本工具**不产**的那些，以及为什么 —— 一起给出去，省得人找。
#: 现在是**空的**：§3.6 的六件套已经全了（`seq.hex` 由 `encode/` 产、
#: `tensors/` 由 `tensors/` 产）。留着这个常量是为了下次再有缺口时
#: 有个明确的落点 —— 而不是让调用方去猜"少的那份是漏了还是本来就没有"。
NOT_PRODUCED: Tuple[Tuple[str, str], ...] = ()


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

    # ── L3 编码产物（§3.1）—— 文本 ──
    # 编码失败时 `encode` 里是 `{"error", "kind"}`，那就**不写** ——
    # 不写空文件（同一条纪律：空的 seq.hex 比没有它更容易让人以为生成过了）。
    encode = payload.get("encode") or {}
    warnings: List[str] = []
    for filename, key in TEXT_ARTIFACTS:
        body = encode.get(key)
        if not body:
            continue
        (out / filename).write_text(body, encoding="utf-8")
        written.append(filename)
    if encode.get("gaps"):
        warnings = [f"{g.get('op')}.{g.get('slot')}（{g.get('enable')}=1）"
                    for g in encode["gaps"]]

    # ── tensor_gen 产物（§3.12.9）──
    # 每个张量两份：数据（`tensors/<name>.hex`）与自述（`manifest/<name>.json`）。
    # 再加一份 `registry.json` —— 它是 isa_gen 的 ref 解析 / CMI preload /
    # scoreboard 共用的**唯一枢纽**（§3.14.4）。
    tensors = payload.get("tensors") or {}
    for entry in (tensors.get("entries") or []):
        name = str(entry.get("name") or "")
        if not name:
            continue
        tdir = out / "tensors"
        tdir.mkdir(exist_ok=True)
        (tdir / f"{name}.hex").write_text(entry.get("hex") or "", encoding="utf-8")
        written.append(f"tensors/{name}.hex")

        mdir = out / "manifest"
        mdir.mkdir(exist_ok=True)
        (mdir / f"{name}.json").write_text(
            json.dumps(entry.get("manifest") or {}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        written.append(f"manifest/{name}.json")

    if tensors.get("registry"):
        (out / "registry.json").write_text(
            json.dumps(tensors["registry"], ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        written.append("registry.json")

    not_produced: List[Dict[str, str]] = [
        {"file": name, "reason": why} for name, why in NOT_PRODUCED]
    if encode.get("error"):
        not_produced.append({"file": "seq.hex / reg-init.txt",
                             "reason": f"编码失败：{encode['error']}"})
    if tensors.get("error"):
        not_produced.append({"file": "tensors/ · manifest/ · registry.json",
                             "reason": f"tensor_gen 失败：{tensors['error']}"})

    return {"out_dir": str(out), "written": written,
            # 有 gap = 某些指令字里那一槽是 0（读 x0）。**必须让调用方看见** ——
            # 0 是合法操作数，仿真不会在那里报错。
            "operand_gaps": warnings,
            "tensor_notes": list(tensors.get("notes") or []),
            "not_produced": not_produced}
