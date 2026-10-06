"""**仿真业务模式** —— 一次回归"开哪一门仿真业务"（波形 / 覆盖率 / 调试…）。

## 这套机制从哪来

`common_base.yaml` 里有一张 `modes:` 表，把业务词条映射到**选项变量**：

    wave → wave_opt      cov → cov_opt      upf → upf_opt     …

回归框架的 `apply_modes()`（`regression_framework/core/config.py`）据此把选中的
那几项的值拼进聚合变量 `MODE_OPTS`，并顺手设 `<mode>_enabled: '1'` 供命令里
`{% if … %}` 分支。命令里写 `{{ MODE_OPTS | default("") }}` 就能拿到一串拼好的
选项 —— 于是"开哪门业务"变成**数据**，不是十八个 if。

所以生成 `regression.yaml` 时 `include:` 那份 `common_base.yaml`，模式名沿用它的表
（**一份语义来源**），不另起一套名字。

## 为什么这个文件里还要有一份"值"

`common_base.yaml` 里的值是 **VCS 语义**：`cov_opt: '-cm line+cond+fsm+tgl+branch+assert
-cm_dir ${EMAN_CM_DIR}'`、`wave_opt: '+DUMP_FILE=… +fsdb+force'`。本仓库的生成物走的是
**Questa**（`vlog` / `vsim`，见 `entity`：`tool_find_spec_yaml` 的 builds/tests）。
把 VCS 参数原样拼进 vsim 命令行，vsim 当场判"未知选项"、整轮回归跑不起来 —— 不是
少一个功能，是全线崩。

所以：**模式名对齐 common_base.yaml，值按本环境后端给**。生成 regression.yaml 时
这份表写成同名变量，覆盖 include 进来的 VCS 值（`_merge_config` 本地优先）。

## `supported=False` 的项为什么留着

Questa 没有对应开关的（xprop 是 VCS 专有；UPF 要 `vlog/vopt -pa_upf` 配套编译，
光给 vsim 加个开关不够），这里**照旧登记、值给空串**：

  · 登记 → 界面上仍看得见这门业务，人知道"选了会怎样"；
  · 空值 → `apply_modes` 会 **告警并忽略**（不是静默丢弃一个选项就完事）。

硬塞一个不存在的参数换来的是整轮回归崩掉 —— 那比"这门业务本后端没有"糟得多。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

#: 不选任何业务时用哪个 —— 「默认开覆盖率」（覆盖率是闭环的主指标）
DEFAULT_MODE = "cov"


class SimMode:
    """一门仿真业务：词条、选项变量名、本后端的取值。"""

    __slots__ = ("mode", "label", "var", "value", "supported", "note")

    def __init__(self, mode: str, label: str, var: str, value: str,
                 supported: bool = True, note: str = ""):
        self.mode = mode            #: 词条（common_base.yaml 的 modes 键）
        self.label = label          #: 界面上的中文名
        self.var = var              #: common_base.yaml 里对应的变量名
        self.value = value          #: 本后端（Questa）的取值；空串 = 本后端没有
        self.supported = supported
        self.note = note

    def as_dict(self) -> Dict[str, Any]:
        return {"mode": self.mode, "label": self.label, "var": self.var,
                "value": self.value, "supported": self.supported,
                "note": self.note}


#: 与 `common_base.yaml` 的 `modes:` 一一对应；值按 Questa 给。
#:
#: 每一条的取值都在本机 Questa 2024.1 的 `vsim -help` 里核过：
#:   -debugdb    → 生成 Schematic Debug 数据库（vsim.dbg）
#:   -qwavedb    → 生成 Visualizer 波形库 qwave.db（**这禁用 WLF**）
#:   -coverage   → 保留已使能的覆盖率统计（编译侧要 `vlog +cover`）
#:   +glitch/+delta → 记录毛刺 / delta（给 WLF 的日志细节）
MODES: List[SimMode] = [
    SimMode("cov", "覆盖率", "cov_opt",
            "-coverage -coverstore ${EMAN_CM_DIR}/${EMAN_TEST_NAME}"
            " -testname ${EMAN_TEST_NAME}",
            note="vsim 保留覆盖率统计并落一份覆盖率库（编译侧由 cov_enabled 追加 vlog +cover）"),
    SimMode("wave", "波形", "wave_opt",
            "-voptargs=+acc"
            " -qwavedb=+signal+class+wavefile=${EMAN_RUN_DIR}/waves/${EMAN_TEST_NAME}.db",
            note="每条用例一份 qwave.db（Visualizer 原生波形库，`visualizer -wavefile` 直接开）。"
                 "两处缺一不可：`-voptargs=+acc` 保 DUT 可见性 —— 不加则 vsim 默认把 DUT "
                 "优化掉，波形库里根本没有 DUT，hier 找不到、信号拉不出来；"
                 "`+signal+class` 连信号与 UVM 类一起记。**-qwavedb 会禁用 WLF**，见 glitch/delta。"),
    SimMode("debug_all", "调试（全量）", "debug_all", "-debugdb",
            note="生成 vsim.dbg，供交互式/Schematic 调试；对性能有影响"),
    SimMode("glitch", "毛刺", "glitch_opt", "+glitch",
            note="WLF 记录同一时刻的多次跳变。**与波形业务互斥**：波形走 -qwavedb 时 WLF 被禁用，"
                 "毛刺请改用 Visualizer 的 -showglitches"),
    SimMode("delta", "Delta", "delta_opt", "+delta",
            note="WLF 连同毛刺一起记 delta 号。**同 glitch：与 -qwavedb 波形业务互斥**"),
    SimMode("xprop", "X 传播", "xprop", "", supported=False,
            note="Questa 无 -xprop 开关（VCS 专有）——启用会被忽略并告警"),
    SimMode("tprop", "三态传播", "tprop", "", supported=False,
            note="同上：Questa 无对应开关"),
    SimMode("upf", "功耗（UPF）", "upf_opt", "", supported=False,
            note="需 vlog/vopt -pa_upf 配套编译，仅给 vsim 加开关不够"),
]

_BY_MODE = {m.mode: m for m in MODES}


def all_modes() -> List[SimMode]:
    return list(MODES)


def modes_dict() -> List[Dict[str, Any]]:
    """给界面用的纯数据（跨进程/JSON 安全）。"""
    return [m.as_dict() for m in MODES]


def get(mode: str) -> SimMode:
    return _BY_MODE[str(mode)]


def is_known(mode: str) -> bool:
    return str(mode) in _BY_MODE


def value_for(mode: str) -> str:
    """这个词条在本后端的取值；不认识的词条给空串（调用方按"没有"处理）。"""
    found = _BY_MODE.get(str(mode))
    return found.value if found else ""


def unsupported(selected: Any) -> List[str]:
    """选中的词条里，本后端**没有开关**的那些 —— 调用方拿它去告警。

    不能安静地过滤掉：人以为自己开了 X 传播，实际什么都没开，那比报错还坏。
    """
    if isinstance(selected, str):
        selected = [s.strip() for s in selected.split(",") if s.strip()]
    return [str(m) for m in (selected or [])
            if not _BY_MODE.get(str(m)) or not _BY_MODE[str(m)].supported]


def yaml_variables() -> Dict[str, str]:
    """写成 `regression.yaml` 的 `variables:` 那几条（变量名 → 取值）。"""
    return {m.var: m.value for m in MODES}


def common_base_path() -> Path:
    """`common_base.yaml` 的绝对路径 —— 生成 regression.yaml 时 `include:` 它。"""
    return Path(__file__).resolve().parent / "common_base.yaml"
