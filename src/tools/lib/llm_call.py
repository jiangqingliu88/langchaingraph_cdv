"""LLM 调用的**唯一收口** —— 所有点状 LLM 都从这里出去。

这个模块为什么存在
    LLM 在本项目里是**点状**的：它不驱动流程（流程由 LangGraph 的边定死、
    决策由规则引擎定死），只在几个具体位置被调去"生成一段代码 / 给一个假设"。
    既然是点状的，就更该只有一个出口 —— 否则预算、缓存、审计会一半生效、
    一半不生效，而那种"一半"从任何单个调用点上都看不出来。

唯一出口是 `LLMQueryEngine.query()`
    它一次做四件事（见 `query_engine.py:60-80`）：
      · token 预算检查 —— 超限**直接返回空串**，不再往下调
      · 响应缓存 —— 同一个 prompt 不重复烧钱
      · 重试 + provider 降级
      · 审计 —— 每次调用记一条（`cache_key` 就是 prompt）

    **不要**改成 `LLMFactory.create_for_task(...)` + `llm.invoke(...)` ——
    那条路绕过上面四件事。本模块的历史版本（叫 `llm_custom_logic.py`）
    正是这么写的，同时 `llm_refine.call_llm` 里还有一份逐字节相同的副本，
    于是"修出错文件"这一个动作有两份实现，其中一份的 token 不计预算、
    不进审计 —— 而它恰好是最容易在循环里反复触发的兜底路径。
    合并成一份是这次改动的目的。

调用方（全部经 `call_llm`）
    · `executors/design`                     —— 写 IP 的 RTL / 写顶层连线
    · `tools/coverage_tools`                 —— 写覆盖率 gap 的定向驱动
    · `tools/uvm_tools/tool_find_spec_yaml`  —— 端口按协议分类
    · `lib/llm_refine`                       —— 转手给 debug 与仿真时序修复

报文格式说明
    `CODE: …` / `ERRORS: …` 这一层是给**修复类**调用准备的。生成类的调用方
    （design / coverage / find_spec_yaml）传 `code=""`、`errors=""`，真正的指令
    在 `prompt`（system 角色）里 —— 那层壳对它们是空转的；保留是为了不改变
    已经跑通的报文形状。
"""
from __future__ import annotations

from typing import Any, Dict, List

import structlog

logger = structlog.get_logger()


def call_llm(prompt: str, code: str, errors: str) -> str:
    """`prompt` → LLM 文本（经集中式 Query Engine：预算 + 缓存 + 降级 + 审计）。

    失败一律返回**空串**、不抛 —— 调用方拿它判"LLM 没给出东西"并走确定性回退
    （例如 design 的 `_is_valid_rtl` 会因此丢弃这次生成）。抛异常会把
    "LLM 挂了"升级成"流水线挂了"，那不是这一层该做的判断。
    """
    try:
        from src.layers.l2_orchestration.context.query_engine import (
            LLMQueryEngine,
        )
        user_msg = (f"CODE:\n{code[:3000]}\n\nERRORS:\n{errors[:1000]}\n\n"
                    f"Output ONLY the fixed complete code, no explanation.")
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": user_msg},
        ]
        content = LLMQueryEngine.get_instance().query(
            "code_generation", messages, cache_key=prompt)
        if not content:
            return ""
        # 模型偶尔还是会把代码包在 ``` 里 —— 剥掉，顺手认一下语言标记
        if "```" in content:
            block = content.split("```")[1]
            if block.startswith("systemverilog") or block.startswith("sv"):
                block = block.split("\n", 1)[1] if "\n" in block else block
            return block.strip()
        return content.strip()
    except Exception as e:                          # noqa: BLE001
        logger.warning(f"LLM call failed: {e}")
    return ""
