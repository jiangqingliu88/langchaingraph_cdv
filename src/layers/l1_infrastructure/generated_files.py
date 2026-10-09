"""生成物的**写盘边界** —— 全项目唯一的写盘出口。

## 为什么必须在 L1

`gen_uvm` 有 `pragma custom` 机制，设计是对的：**生成物的骨架归模板，人只改
`pragma custom` 区域**。但"谁在什么时候写了文件"这件事**没有边界**。

实测（同一个会话里反复踩）：

```
llm_refine.apply_llm_fixes()           整份重写 SCB → 非法 do_compare → 编译塌
llm_refine.llm_refine_compile_errors() 另一条路径、也有自己的 write_text
                                       （第一版只闸了前一条，立刻复发）
```

于是同一个模板，三轮运行产出三份**各不相同**的 `apb_loopback_scb.sv`
（实测行数 131 / 182 / 156，且**一份都不含**模板自带的 `SCB_LOOP_PASS`）——
loopback 时好时坏（7/7 → 4/7 → 5/7），而 loopback 是分级回归的**第一道门**，
它挂了后面 p0–p3 / 覆盖率 / 签核全不跑。

症状看起来是"怎么都跑不通"，根因是**跑通与否由那轮 LLM 写了什么决定**。

## 纪律

**所有对生成物（带 banner 的 `.sv` 等）的写入都必须走 `gated_write()`。**
谁再直接 `fpath.write_text(...)`，就是又开了一条暗路 —— 闸门写在"某条路径里"
等于没写，漏一条就前功尽弃。

`tests/test_generated_write_boundary.py` 会**扫全项目**找越界的写盘点，所以
"漏一条"从靠运气发现变成**结构上不可能**。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional, Union

#: 生成物签名 —— 由 `gen_uvm` 的 banner 模板（`base_template.sv.j2`）写出。
#: 与 `gen_uvm.REGION_MARKER` / banner 同源；一致性由契约测试钉住。
GENERATED_BANNER = "自动生成 (tool_uvm"

#: `pragma custom <slot> begin|end` 标记 —— **真相源是 `gen_uvm.REGION_MARKER`**。
#: 这里复刻一份供 L1 自用（L1 不 import tool_uvm：依赖方向是"上层依赖下层"）。
#: 两者一致性由契约测试钉住：改一边漏一边会红。
REGION_MARKER = re.compile(r"^\s*//\s*pragma\s+custom\s+(\w+)\s+(begin|end)\s*$")

#: 会被"整份重写"毁掉的生成物扩展名（UVM 源 + 脚本）。
GENERATED_SUFFIXES = (".sv", ".svh", ".v", ".f", ".tcl")


def is_generated(path_or_text: Union[Path, str], *, max_lines: int = 3) -> bool:
    """是不是生成物 —— 看**开头几行**有没有生成 banner。

    只看开头几行：正文里也可能出现"自动生成"字样（注释里讲这件事），
    全文匹配会把人手写的文件误判成生成物，那会让闸门**误拦合法的修改**。

    接受路径或文本：调用的地方有时只有文本（比如写盘前拿新旧两份比）。
    """
    if isinstance(path_or_text, Path):
        if not path_or_text.exists():
            return False
        try:
            text = path_or_text.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return False
    else:
        text = str(path_or_text)
    head = text.lstrip().splitlines()[:max_lines]
    return any(GENERATED_BANNER in ln for ln in head)


def skeleton(text: str) -> str:
    """**骨架** = 抹掉所有 `pragma custom` 区域**内容**后的文本（标记行保留）。

    生成物的骨架是模板说了算的，**不属于**可以自由改写的部分；`pragma custom`
    区域才是留给人的。改写后骨架应当逐字节不变 —— 这就是放行判据。
    """
    out, inside = [], False
    for ln in text.splitlines():
        m = REGION_MARKER.match(ln)
        if m:
            inside = m.group(2) == "begin"
            out.append(ln)
            continue
        if not inside:
            out.append(ln)
    return "\n".join(out)


def gate_reason(path: Path, new_text: str) -> Optional[str]:
    """这次写入**该不该拦** → 该拦返回原因，放行返回 `None`。

    拆出来是为了让"判据"可单测、可复用 —— 不写盘的调用方（比如只想预检）
    也能拿到同样的结论。
    """
    if not path.exists():
        return None                      # 新文件：没有骨架可比，放行
    try:
        old = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    if not is_generated(old):
        return None                      # 人手写的文件：本来就归人改
    if skeleton(old) == skeleton(new_text):
        return None                      # 只动了 pragma custom 区域 → 合法
    return (f"拒绝整份重写生成物 {path.name}（骨架与模板不一致）"
            f" —— 只允许改 pragma custom 区域")


def gated_write(path: Union[str, Path], text: str, *,
                logger=None) -> bool:
    """**全项目唯一的生成物写盘出口。** 返回是否真的写了。

    生成物 + 骨架不一致 → **拒绝并保留原文**（返回 False）；其余照写。

    调用方**必须**把 `False` 当作"被闸门拦下"单独记账 —— 别和"没有内容可写"
    混成一句。实测：混成 "LLM parse failed" 会让人去 prompt 上找原因，白查一轮。
    """
    p = Path(path)
    reason = gate_reason(p, text)
    if reason:
        if logger is not None:
            logger.warning(f"[write-gate] {reason}；已保留原文")
        return False
    p.write_text(text, encoding="utf-8")
    if logger is not None:
        logger.info(f"[write-gate] wrote {p.name} ({len(text)} bytes)")
    return True
