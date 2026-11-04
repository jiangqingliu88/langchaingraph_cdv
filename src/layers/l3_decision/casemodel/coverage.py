"""**case 建模 → 功能覆盖率方法学** —— 把模型里的覆盖点变成真的 SystemVerilog covergroup。

按职责拆到同目录下的几个模块，本文件只做**统一入口**（旧导入路径保持不变）：

    coverage_model.py   覆盖点/仓/交叉的数据形状 + case 模型 → covergroup 模型
    coverage_render.py  covergroup / probe / 覆盖率接口的 SV 生成
    coverage_parse.py   从已有 SV / 清单里读回模型

## 为什么单开这一层

case 模型（`domain/`）**已经把功能覆盖点建模出来了**：维度是归类、字段承载取值、
取值点 `ValuePoint` 是"分母的刻度"、`cross_pair` 声明维度之间要不要一起组合。
但这些一直**只活在模型里**：

  · `analysis/coverage.py` 算的命中率，分母是模型**自己声明的取值点**，分子是
    **case 表里有没有这个取值** —— 它回答的是"用例写全了没有"，**不是**
    "仿真真的打到了没有"。这两个问题差得很远，而只有后者能签核。
  · 全仓唯一的 covergroup 生成器（`executors/coverage/functional_coverage.py`）
    是 **spec 驱动**的骨架（只给 opcode 枚举 bin），**不认识** case 模型。

于是证据链一直显示 `Covergroup/Coverpoint/Cross 模型: 0/4`。这一层补上那个缺的
转换：**模型里的覆盖点 → 能编译、能采样、能被 `vcover` 统计的 covergroup**。

## 方法学（规则只此一份，文档与实现同源）

| 模型里的东西 | 变成 | 为什么 |
|---|---|---|
| 一个 `CaseModel` | **一个** `covergroup cg_<module>` | cross 要求两个 coverpoint 同作用域，所以合一个而不是每维度一个 |
| `Dimension` | 一组 coverpoint（它的每个字段一个） | 维度是归类，不承载取值 |
| `Field` | `coverpoint <field.name>` | **字段名就是接口信号名**（`front` 从 spec 的 interfaces 取，见 `_draft_casemodel`） |
| `ValuePoint`（取值点） | 一个 `bins` | 取值点就是覆盖分母的刻度 |
| ↑ 但**给了显式仓时不是一比一** | 多个取值点落进一个仓 | 值域划分（`{[1:7]}`）天然多对一 —— 用例按取值点生成、覆盖率按仓收 |
| `Field.cover_bins` | bin 的**名字** | 作者能命名就让作者命名（`bins_for` 已实现对齐规则） |
| `CrossPair`（required/optional） | `cross cp_a, cp_b;` | 声明了要一起组合的维度就该有 cross；`forbidden` 是禁止组合，不生成 |

## 三条纪律

**一、生成的 SV 必须能编译。** 所以取值的字面量走**整型投影**（与
`api.run_uvm_tests` 的 `int_value` 同一套）：取值本身是数字就用它，否则用它在
字段里的下标。中文取值 `首拍` 直接写进 `bins x = {首拍};` 是编译错误；投影成下标
则合法，而原取值以注释留在旁边（`bins b0 = {0}; // 首拍`）—— 语义没丢，编译器也没炸。

**二、算不出来就说出来。** 字段一个取值点都没有、cross 引用的维度解不出来、
维度没有字段 —— 这些**不静默跳过**，进 `notes` 记账。一个"看起来生成了、
其实少了一半 bin"的 covergroup 比一个报错的更坏。

**三、每个 bin 必须至少有一个取值点能打到。** 这是"激励侧与度量侧同一份分母"
的**准确说法**（不是"一比一"—— 给了显式仓时天然多对一）：

    用例按 `value_points()` 生成（一个取值点一条 test）
    覆盖率按 `bins` 收（一个仓可能盖住好几个取值点）

多对一无害，**空洞致命**：某个仓一个取值点都打不到 → 声明的覆盖率**永远封顶**，
而 covergroup 编译通过、回归跑得过、日志一切正常。由 `run_gaps` 的
`cover_bin_unreachable` 拦 —— 实测踩过：`cluster_id` 写了 4 个显式仓却没给
`boundary`，`RangeField` 退化到 `[min, max]`，c1/c2 永远打不到。

## 与 `analysis/coverage.py` 的分工

那一层算的是"**用例写全了没有**"（模型 vs case 表），这一层产出的是
"**仿真打到了没有**"的度量装置（covergroup → vcover）。两者都要有，
但**不能混为一谈** —— 前者的 100% 不代表后者是 100%。
"""
from __future__ import annotations

from .coverage_model import (  # noqa: F401
    CROSSABLE_LEVELS, MAX_BINS_PER_POINT, CoverBin, CoverPoint, CoverageModel,
    CrossBin, CrossPoint, _as_int, _attach_crosses, _bin_name, _coverpoint,
    _cross_bins, _derive_width, _derive_width_from_bins, _explicit_bins,
    _match_bin, _opt_int, _slug, coverage_model, sv_ident, sv_value,
)
from .coverage_parse import (  # noqa: F401
    _find_field, _parse_bin, _parse_coverpoint, _parse_cross, _project,
    coverage_model_to_dict, declared_bin_names, parse_coverage_model,
)
from .coverage_render import (  # noqa: F401
    DEFAULT_CLOCK, DEFAULT_INSTANCE, DEFAULT_RESET, DEFAULT_WIDTH,
    assertion_signals, checker_rules, cov_interface_meta, coverage_plan,
    dut_bins, parse_model_text, probe_ports, render_covergroup,
    render_cov_interface, render_probe,
)
