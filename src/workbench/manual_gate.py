"""工具栏上「人工节点」开关的**选择与记忆**。

## 这个开关管什么

分级回归（loopback → p0 → p1 → p2 → p3）在 **loopback 全过之后**有一个
**人工节点**：那一级证的是"TB 自身自洽"（driver 发出的 == slave monitor 看到的），
要不要接着烧 P0 的机时由人拍板。配置在
`InfrastructureManager.REGRESSION_MANUAL_GATES`，放行用 `vagent regression approve`。

  · **开（拦截）** —— 跑到那儿停下，`status=WAITING_APPROVAL`，等人放行；
  · **关（放行）** —— 不拦，一口气跑完（`run_regression_staged(auto_approve=True)`）。

## 为什么默认是**开**

门是默认该在的。默认关掉等于"这个机制默认不存在"—— 那它就不是门，是选项。
这也和 CLI 那边一致：`run_regression_staged` 的 `auto_approve` 缺省就是 `False`。

## 为什么它和「仿真业务」一样是**运行的输入**，不是运行中的开关

`manual_gate` 决定闭环跑不跑得过那道放行点，写进 `RunRequest` → `PipelineState`，
跑完要能回答"这一轮为什么没停"。中途改一个界面控件去动已经在跑的图，那份记录
就是假的（同 `sim_modes.py` 里那段理由）。

## 存哪儿：**用户级**（`~/.signoffai/manual_gate.json`），不是项目级

和「仿真业务」刻意不同 —— 那个是**项目**的事（低功耗项目常开 `upf`、教学项目常开
`wave`，各记各的），所以它落在工作目录下的 `.signoffai/`。这个开关是**操作者**的事：

    「我现在坐在这儿，要不要被那道门拦一下？」

换个项目目录开工作台，人还是同一个人、答案还是同一个 —— 记到项目里就成了
"每个项目都得重设一次"，那是把人的偏好当成项目的属性。所以放用户级，
和项目登记表 / 插件目录（`~/.signoffai/` 下那几个）同口径。
"""
from __future__ import annotations

import json
from pathlib import Path

#: **用户级**记忆文件（与项目登记表、插件目录同目录同口径）
STORE = Path.home() / ".signoffai" / "manual_gate.json"

ON_LABEL = "人工节点：拦截"
OFF_LABEL = "人工节点：放行"


def load() -> bool:
    """人工节点是否**生效（拦截）**。缺省 `True`。

    读不到 / 写坏了都回落到 `True` —— 治理不能因为一份记忆文件不在就静默失效。
    """
    try:
        data = json.loads(STORE.read_text(encoding="utf-8"))
    except Exception:                                   # noqa: BLE001 读不到＝默认开
        return True
    if isinstance(data, dict) and "enabled" in data:
        return bool(data["enabled"])
    return True


def save(enabled: bool) -> None:
    """记住选择（下次启动运行生效）。"""
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps({"enabled": bool(enabled)}, ensure_ascii=False,
                                indent=2),
                     encoding="utf-8")


def label(enabled: bool) -> str:
    return ON_LABEL if enabled else OFF_LABEL
