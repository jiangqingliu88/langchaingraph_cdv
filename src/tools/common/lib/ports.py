"""端口名的**共享判定** —— 时钟/复位这些"不归生成器管"的信号。

## 为什么单独立一个文件

时钟/复位不是普通端口：它们的驱动者是 base 包里的 `clk_rst_agent`，不是
`tool_find_spec_yaml` 生成的那些 agent。于是凡是要给端口"找归属""排重"的地方，
都得先把它们择出去 —— 而"按什么判"这件事必须在**一处**：

  · `tool_find_spec_yaml` 生成 agent/bench 时按名字认时钟/复位；
  · `tool_check_env_arch` 的端口归属检查也要跳过它们。

各写一份就会漂，而漂的表现是**一处认得出、另一处认不出**：实测就是
`check_env_arch` 按 spec 的 `protocol` 字段跳过（`{"clock","reset","clk","rst"}`），
而 `--rtl` 路径生成的 spec **根本没有 `protocol` 字段** —— 于是 `clk` / `rst_n`
被当成"孤儿端口：无 agent 驱动"，`env_arch_check` 每轮 0 分，把一个正常的
环境判成 FAIL。

## 判定口径

按**名字**：`clk`/`clock`、`rst`/`reset`。宽松是故意的 —— `pclk`、`presetn`、
`rst_n`、`clk_sys` 都得认出来；漏认的代价是"把一个时钟当孤儿端口"（见上），
而误认的代价只是"一个真叫 `reset_done` 的数据端口没被检查"（罕见且无害）。
"""
from __future__ import annotations


def is_clock_port(name: str) -> bool:
    """名字像时钟（`clk` / `clock` / `pclk` / `clk_sys` …）。"""
    n = str(name or "").lower()
    return "clk" in n or "clock" in n


def is_reset_port(name: str) -> bool:
    """名字像复位（`rst` / `reset` / `rst_n` / `presetn` …）。"""
    n = str(name or "").lower()
    return "rst" in n or "reset" in n


def is_clock_or_reset(name: str) -> bool:
    """时钟或复位 —— 这两类由 base 包的 `clk_rst_agent` 驱动，不归生成器管。"""
    return is_clock_port(name) or is_reset_port(name)
