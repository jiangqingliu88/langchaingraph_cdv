"""工具栏上「仿真业务」下拉的**选择与记忆**。

## 这个文件只干一件事

"有哪些仿真业务、各自对应什么选项变量"是工具层的事，表在
`src/layers/l2_orchestration/regression_tools/sim_modes.py` —— 这里**不另写一份**，只负责：

  1. 把那张表喂给工具栏下拉；
  2. 把选中的词条**记住**，下次开工作台还是它。

选中的词条随 `pipeline.start` 进入这次运行（`RunRequest.sim_modes`），最后落到
回归框架的 `MODE_OPTS`（详见工具层的 `sim_modes.py` 与回归框架的 `apply_modes`）。

## 存哪儿

`.signoffai/sim_modes.json` —— 与其它项目级记忆（`rule_stats.db` / `hint_stats.db` /
用例库）同目录、同口径：**相对工作目录 ⇒ 项目隔离是现成的**。换个项目目录开
工作台，读的就是另一份 —— 低功耗项目常开 `upf`、教学项目常开 `wave`，各记各的。

## 「无」为什么是个显式取值

词条用一个**字符串**存（`"cov"` / `"wave"` / … / `"none"`），不是一个可能为空的
列表：`"没存过"` 和 `"人明确选了无"` 是两件事 —— 前者该回落到默认（覆盖率），
后者该**就按无跑**。用空列表表达"无"，这两种情况在文件里长得一模一样，于是
选过一次"无"之后会被当成没存过、又自己跳回覆盖率（那是静默篡改人的选择）。

## 为什么只让选一门，而默认那一门是 `cov+wave`

下拉是**单选**：`apply_modes` 收列表，但"同时开波形+覆盖率+功耗"在一次回归里
既拖慢仿真、又让"这一轮为什么慢"没法归因。要三门并列的话 CLI 那边是
`--sim-mode wave --sim-mode cov`（可重复），界面这层保持单一、可解释。

单选能表达"两个都要"，靠的是工具层把组合**做成一个词条**（`cov+wave` → 
`cov_wave_opt`）。所以默认值和 CLI 是同一个：**都取工具层的 `DEFAULT_MODE`**，
界面这边不另定一份。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List

#: 项目级记忆文件（相对工作目录 —— 项目隔离靠它）
STORE = Path(".signoffai") / "sim_modes.json"

#: 「一门业务都不开」的词条（命令与从前逐字节一致）
NONE_MODE = "none"
NONE_LABEL = "无（不注入选项）"


def mode_items() -> List[dict]:
    """下拉要的条目 —— 直接来自工具层那张表，顺序也照它。"""
    from src.layers.l2_orchestration.regression_tools import sim_modes as tool_modes

    items = [{"mode": NONE_MODE, "label": NONE_LABEL, "note": "回归按命令原样跑",
              "supported": True}]
    for m in tool_modes.all_modes():
        label = m.label if m.supported else f"{m.label}（本后端无开关）"
        items.append({"mode": m.mode, "label": label, "note": m.note,
                      "supported": m.supported})
    return items


def default_mode() -> str:
    from src.layers.l2_orchestration.regression_tools import sim_modes as tool_modes

    return tool_modes.DEFAULT_MODE


def load() -> str:
    """上次选的词条（读不到 / 坏了 → 用工具层的默认 `cov+wave`；**不抛**）。"""
    try:
        data = json.loads(STORE.read_text(encoding="utf-8"))
        mode = str(data.get("mode", "")).strip()
    except (OSError, ValueError):
        return default_mode()
    return mode or default_mode()


def save(mode: str) -> None:
    """记住选择。**失败不抛** —— 记不上不该拦着人跑回归。"""
    try:
        STORE.parent.mkdir(parents=True, exist_ok=True)
        STORE.write_text(json.dumps({"mode": str(mode or NONE_MODE)},
                                    ensure_ascii=False, indent=2),
                         encoding="utf-8")
    except OSError:
        pass


def selected_modes(mode: str = None) -> List[str]:
    """词条 → 交给运行请求的**仿真业务表**（`"none"` → `[]`）。

    `None` 表示"调用方没给"，交回默认 —— 与 `"none"`（人就选了无）区分开。
    """
    mode = load() if mode is None else str(mode)
    if not mode or mode == NONE_MODE:
        return []
    return [mode]
