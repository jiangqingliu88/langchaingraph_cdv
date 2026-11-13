"""设计结构预检 —— 在生成 RTL **之前**回答"这份 spec 能不能被验证"。

## 为什么需要它

现在很多结构问题要等到 `vlog` 编译、甚至回归失败才暴露：模块名是占位符、
接口表为空、端口重名、没有时钟/复位、寄存器偏移重复…… 这些都不是"设计
写错了"，而是"规格本身不够生成一个可仿真对象"。越晚发现，越容易被记成
LLM 的锅。

## 边界

预检只做**结构性、确定性的检查**，不判断功能对不对。它的输出进
`design_arch.precheck` 与 `result.design_precheck`：

  · `severity=error` —— 生成 RTL 没有意义（例如没有接口、模块名占位）；
  · `severity=warning` —— 能生成，但下游大概率出问题（例如没有复位）。

**不阻断流程**（由 design executor 决定）：一个 warning 不该让整轮停下，
但必须出现在证据里 —— 否则"为什么这轮这么难验"永远没人答得上来。
"""
from __future__ import annotations

from typing import Any, Dict, List

_PLACEHOLDERS = {"", "dut", "dut_top", "top", "chip", "block", "design",
                 "module", "unknown", "undefined"}
_CLOCK_NAMES = ("clk", "clock", "pclk", "aclk")
_RESET_NAMES = ("rst", "reset", "rst_n", "preset_n", "resetn")


def _issue(code: str, severity: str, message: str) -> Dict[str, str]:
    return {"code": code, "severity": severity, "message": message}


def precheck(spec: Dict[str, Any],
             design_arch: Dict[str, Any] = None) -> Dict[str, Any]:
    """spec（+ 可选 design_arch）→ 结构化预检结果。"""
    spec = spec if isinstance(spec, dict) else {}
    arch = design_arch if isinstance(design_arch, dict) else spec
    issues: List[Dict[str, str]] = []

    module = str(spec.get("design_name") or arch.get("module_name") or "").strip()
    if module.lower() in _PLACEHOLDERS:
        issues.append(_issue("MODULE_PLACEHOLDER", "error",
                             f"模块名是占位符/空：{module!r} —— 生成不出可仿真的顶层"))

    interfaces = arch.get("interfaces") or spec.get("interfaces") or []
    if not isinstance(interfaces, list) or not interfaces:
        issues.append(_issue("NO_INTERFACES", "error",
                             "接口表为空 —— 没有端口就没有可驱动的对象"))
        interfaces = []

    seen = {}
    for item in interfaces:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").split("[")[0].strip()
        if not name:
            issues.append(_issue("PORT_UNNAMED", "error", "存在没有名字的端口"))
            continue
        seen[name] = seen.get(name, 0) + 1
        try:
            width = int(item.get("data_width", item.get("width", 1)) or 1)
        except (TypeError, ValueError):
            width = 0
        if width <= 0:
            issues.append(_issue("PORT_BAD_WIDTH", "warning",
                                 f"端口 {name} 的位宽不是正整数：{item.get('data_width')!r}"))
    for name, n in sorted(seen.items()):
        if n > 1:
            issues.append(_issue("PORT_DUPLICATE", "error",
                                 f"端口 {name} 声明了 {n} 次 —— 生成的 module 端口表会重复"))

    lowered = {str(i.get("name") or "").lower() for i in interfaces
               if isinstance(i, dict)}
    protocols = {str(i.get("protocol") or "").lower() for i in interfaces
                 if isinstance(i, dict)}
    if not (any(k in n for n in lowered for k in _CLOCK_NAMES)
            or any("clock" in p for p in protocols)):
        issues.append(_issue("NO_CLOCK", "warning",
                             "没有识别到时钟端口（名字或 protocol）—— 时序与采样都无从谈起"))
    if not (any(k in n for n in lowered for k in _RESET_NAMES)
            or any("reset" in p or p == "rst" for p in protocols)):
        issues.append(_issue("NO_RESET", "warning",
                             "没有识别到复位端口 —— 仿真初值与 X 传播会很难解释"))

    outputs = [i for i in interfaces
               if isinstance(i, dict)
               and str(i.get("direction", "")).upper() in ("OUTPUT", "OUT")]
    if interfaces and not outputs:
        issues.append(_issue("NO_OUTPUT", "warning",
                             "没有任何输出端口 —— 覆盖率只能采内部状态，比对无处落地"))

    regs = arch.get("registers") or spec.get("registers") or []
    offsets = [str(r.get("offset")) for r in regs
               if isinstance(r, dict) and r.get("offset") is not None]
    dup_offsets = sorted({o for o in offsets if offsets.count(o) > 1})
    if dup_offsets:
        issues.append(_issue("REG_OFFSET_DUPLICATE", "warning",
                             f"寄存器偏移重复：{'、'.join(dup_offsets)} —— 读写会互相覆盖"))

    hier = arch.get("function_hier") or spec.get("function_hier") or {}
    children = hier.get("children") if isinstance(hier, dict) else None
    if not children:
        issues.append(_issue("NO_FUNCTION_HIER", "warning",
                             "功能层次为空 —— 测试点建模会缺少可归因的结构"))

    errors = sum(1 for i in issues if i["severity"] == "error")
    warnings = sum(1 for i in issues if i["severity"] == "warning")
    return {
        "schema": "design_precheck_v1",
        "module": module,
        "ok": errors == 0,
        "issues": issues,
        "counts": {"error": errors, "warning": warnings,
                   "interfaces": len(interfaces),
                   "registers": len(regs), "outputs": len(outputs)},
    }
