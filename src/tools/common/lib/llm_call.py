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

#: 输出契约 —— **每次调用都必须声明**。没有 schema 的 LLM 调用直接失败，
#: 不落盘、不进 pipeline（见 `query_engine.query`）。
TEXT_SCHEMA: Dict[str, Any] = {"type": "string", "minLength": 1}
#: 代码类输出（RTL / sequence body / 修复后的文件）至少是非空字符串。
#: 不用长度当质量判据 —— 有效性由 `_is_valid_rtl` / `vlog` 等下游检查回答。
CODE_SCHEMA: Dict[str, Any] = {"type": "string", "minLength": 1}
#: 分类/结构化输出：JSON 对象（具体字段由调用方再解析）。
JSON_OBJECT_SCHEMA: Dict[str, Any] = {"type": "object"}


def caller_site() -> str:
    """**自动**取调用点 `相对路径:行号` —— 不手写字符串。

    **公开**：不经过 `call_llm` 的调用点（`debug` 的根因分析是直连
    `LLMQueryEngine.query` 的，见那边的注释）也要能填 `site` ——
    否则那些记录的出处恒为空，事后问"这次是谁催的"就答不上来（实测：
    15 条审计里 5 条是空的，全是直连那条路）。

    手写的话，七处调用点各写一个 `site="design._generate_ip"`，改名/挪文件之后
    没人会去改它，审计里就会出现指向不存在函数的名字（比没有还坏：查的人会
    顺着它去找一个早就没有的东西）。

    跳过本模块自己的帧，取**第一个不在 `tools/lib/` 里的**调用者 —— 这样
    `llm_refine` 那类转手封装也不会把出处全记成 `llm_refine`。
    """
    import inspect
    import os

    this_file = os.path.abspath(__file__)
    stack = inspect.stack()[1:]
    fallback = None
    for frame_info in stack:
        fname = os.path.abspath(frame_info.filename)
        if fname == this_file or fname.endswith("llm_refine.py"):
            # 转手封装不算出处 —— 但要**留一个兜底**：栈里只有它的话
            # （实测有一条记录 `site` 成了空串），指向它也比空着强。
            fallback = fallback or frame_info
            continue
        try:
            rel = os.path.relpath(fname)
        except ValueError:                     # 跨盘符（Windows）
            rel = fname
        return f"{rel.replace(os.sep, '/')}:{frame_info.lineno}"
    chosen = fallback or (stack[-1] if stack else None)
    if chosen is None:
        return ""
    try:
        rel = os.path.relpath(os.path.abspath(chosen.filename))
    except ValueError:
        rel = chosen.filename
    return f"{rel.replace(os.sep, '/')}:{chosen.lineno}"


def call_llm(prompt: str, code: str, errors: str, *,
             output_schema: Dict[str, Any],
             prompt_version: str,
             output_format: str = "text",
             failure_policy: str = "fallback") -> str:
    """`prompt` → LLM 文本（经集中式 Query Engine：预算 + 缓存 + 契约 + 审计）。

    **`output_schema` 与 `prompt_version` 是必填的**（keyword-only）：
      · 没有 schema → `query_engine` 直接拒绝，不落盘、不进 pipeline；
      · `prompt_version` 进审计并参与缓存键 —— prompt 改了缓存自动失效。

    `failure_policy` 必须显式：
      · `fallback`（默认）：失败返回空串，调用方走确定性回退；
      · `fail_fast`：抛 `LLMContractError`（关键生成路径用）。

    `output_format="json"` 时输出先按 JSON 解析并过 schema，不合法即失败。
    """
    if not prompt_version:
        raise ValueError("call_llm 需要显式 prompt_version（缓存键与审计都靠它）")
    try:
        from src.layers.l2_orchestration.context.query_engine import (
            LLMContractError, LLMQueryEngine,
        )
    except Exception as e:                          # noqa: BLE001
        logger.warning(f"LLM 引擎不可用: {e}")
        return ""
    user_msg = (f"CODE:\n{code[:3000]}\n\nERRORS:\n{errors[:1000]}\n\n"
                f"Output ONLY the fixed complete code, no explanation.")
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": user_msg},
    ]
    try:
        return LLMQueryEngine.get_instance().query(
            "code_generation", messages, site=caller_site(),
            output_schema=output_schema, output_format=output_format,
            prompt_version=prompt_version, failure_policy=failure_policy)
    except LLMContractError:
        raise                                   # fail-fast 是契约，不吞
    except Exception as e:                          # noqa: BLE001
        logger.warning(f"LLM call failed: {e}")
    return ""


def call_llm_json(prompt: str, payload: str, *,
                  output_schema: Dict[str, Any],
                  prompt_version: str,
                  task_type: str = "structured",
                  failure_policy: str = "fallback") -> str:
    """通用结构化调用：`prompt` + `payload` → JSON 文本（仍走同一漏斗）。

    与 `call_llm` 的区别只在 user message 的拼法：`call_llm` 面向“给代码 +
    报错，返回修好的代码”，这里面向自由循环（plan / tool_call / observe）。
    预算、缓存、审计、schema 校验都和 `call_llm` 共用。
    """
    if not prompt_version:
        raise ValueError("call_llm_json 需要显式 prompt_version")
    try:
        from src.layers.l2_orchestration.context.query_engine import (
            LLMContractError, LLMQueryEngine,
        )
    except Exception as e:                          # noqa: BLE001
        logger.warning(f"LLM 引擎不可用: {e}")
        return ""
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": str(payload)[:60_000]},
    ]
    try:
        return LLMQueryEngine.get_instance().query(
            task_type, messages, site=caller_site(),
            output_schema=output_schema, output_format="json",
            prompt_version=prompt_version, failure_policy=failure_policy)
    except LLMContractError:
        raise
    except Exception as e:                          # noqa: BLE001
        logger.warning(f"LLM structured call failed: {e}")
    return ""


def call_llm_messages(messages: List[Dict[str, Any]], *,
                      output_schema: Dict[str, Any],
                      prompt_version: str,
                      task_type: str = "agent_loop",
                      failure_policy: str = "fallback") -> str:
    """Chat 形态的通用入口：调用方已经拼好 messages（system/user/assistant/tool）。"""
    if not prompt_version:
        raise ValueError("call_llm_messages 需要显式 prompt_version")
    try:
        from src.layers.l2_orchestration.context.query_engine import (
            LLMContractError, LLMQueryEngine,
        )
    except Exception as e:                          # noqa: BLE001
        logger.warning(f"LLM 引擎不可用: {e}")
        return ""
    try:
        return LLMQueryEngine.get_instance().query(
            task_type, messages, site=caller_site(),
            output_schema=output_schema, output_format="json",
            prompt_version=prompt_version, failure_policy=failure_policy)
    except LLMContractError:
        raise
    except Exception as e:                          # noqa: BLE001
        logger.warning(f"LLM chat call failed: {e}")
    return ""
