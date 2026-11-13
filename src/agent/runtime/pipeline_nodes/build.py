"""executor 节点 · 构建

前段：前置分析 → 设计 → 参考模型 → 验证构建。每条都经 `_run_agent`。
"""
from __future__ import annotations

from typing import Any, Dict

from pathlib import Path
import json
import os

import structlog

from src.layers.l2_orchestration.runtime import (
    _rt, _run_agent,
)
from src.layers.l2_orchestration.state import PipelineState

logger = structlog.get_logger()


async def n_front(state: PipelineState, config) -> Dict[str, Any]:
    """前置分析：输入（RTL / spec / doc）→ 结构化设计信息（`spec` / `design_arch`）。

    这是一条链的**入口**：文档/RTL 进来，front 解出设计信息，后面所有人吃它。
    两个 yaml 家族（环境 / 模型 / 用例建模）都是**下游**从它产的东西生成的 ——
    顺序上必须如此（`bench.yaml` 要知道 DUT 顶层与端口，那是这一步定的）。

    `--rtl` 时它读 RTL（顶层 module 名 → design_name、端口表 → interfaces），
    **不让 design 再生成 RTL**（`bypass_design` 已置）。RTL 与 spec 互斥，
    两个都没有 → 它响亮失败，不往下走。
    """
    rt = _rt(config)
    data, phase = await _run_agent(rt, state, "front", "front")
    updates: Dict[str, Any] = {"phases": [phase]}
    if isinstance(data.get("spec"), dict) and data["spec"]:
        updates["spec"] = data["spec"]
    if isinstance(data.get("design_arch"), dict) and data["design_arch"]:
        updates["design_arch"] = data["design_arch"]
    # 没有输入：**在这里停**，别让 design 在一个不存在的设计上跑
    if phase.get("status") not in ("passed", "skipped"):
        logger.error("前置分析未通过（没有输入 / 解不出 design_name）→ 终止闭环")
        updates.update({"interrupted": True, "terminal_reason": "no_input"})
    return updates


def _rtl_version_no(state: PipelineState, module: str):
    """这一轮 RTL 的版本号（没有 RTL 就是 `None`）—— 注册用例时一起写上。

    用例是有版本的：RTL 换了版，"旧用例是在哪版上定的"就答不上来了。

    **`module` 必须由调用方显式给**：这里（design 节点）跑在 `spec.json` 落盘
    **之前** —— 让 `run_rtl_version_no` 自己去读 spec.json 兜底会读不到，然后落
    `"dut"`，于是同一份 RTL 在库里有两条版本记录（一条挂 `npu_sched`、一条挂
    `dut`），而**哪一条都不报错**（实测就是这么发现的）。模块名在这一步是已知的，
    就不要让下游去猜。
    """
    try:
        from src.knowledge.lineage import run_rtl_version_no
        return run_rtl_version_no(state.output_root, module=module)
    except Exception as e:                                 # noqa: BLE001
        logger.warning(f"血缘：RTL 版本取不到（用例将不带版本）: {e}")
        return None


def _spec_from_front(state: PipelineState) -> tuple:
    """bypass 模式复用 front 已解出的 spec/design_arch（没有则空）。

    front 在 bypass 之前已经跑过（`--rtl` 时也读了 RTL、还可能合并了 dplan
    sidecar）。若在这里按 `_parse_rtl_module(rtl_dir, "")` 重解析，多文件工程
    会选中**错误的模块**（实测：npu_sched/ 下 6 个文件解析成 `cmd_int_perf`，
    整条 UVM/回归都挂到子模块上）。front 的结论才是"这一轮的设计身份"。
    """
    spec = state.spec if isinstance(state.spec, dict) else {}
    if not (spec.get("design_name") and spec.get("interfaces")):
        return {}, {}
    arch = dict(state.design_arch) if isinstance(state.design_arch, dict) else {}
    arch.setdefault("module_name", spec["design_name"])
    arch.setdefault("interfaces", spec.get("interfaces") or [])
    arch.setdefault("registers", spec.get("registers") or [])
    arch.setdefault("function_hier", spec.get("function_hier") or {"children": []})
    logger.info(f"验证专注模式：复用 front spec design_name="
                f"{spec['design_name']} interfaces="
                f"{len(spec.get('interfaces') or [])}")
    return dict(spec), arch


def _rtl_missing_update(state: PipelineState, phase: Dict[str, Any],
                        arch: Dict[str, Any]) -> Dict[str, Any]:
    """design 没产出 RTL 时的门禁更新（Design 工具循环开启则先挂起）。"""
    why = arch.get("rtl_discarded") or []
    detail = "；".join(f"{d.get('ip')}: {d.get('why')}" for d in why) or "无 IP 产出"
    loop = os.environ.get("SIGNOFFAI_DESIGN_LOOP")
    if loop is None:
        loop = os.environ.get("SIGNOFFAI_AGENT_LOOP", "off")
    if loop.strip().lower() in ("1", "on", "true", "yes"):
        logger.warning(f"design 没产出 RTL，交给 Design 工具循环补写：{detail}")
        return {"rtl_missing": True,
                "phases": [phase, {"name": "rtl_gate", "status": "pending",
                                   "reason": f"design 未产出 RTL，进入 Design 工具循环；{detail}"}]}
    logger.error(f"design 没产出任何 RTL（rtl/ 是空的）→ 终止闭环。丢弃原因：{detail}")
    return {"interrupted": True, "terminal_reason": "rtl_missing",
            "phases": [phase, {"name": "rtl_gate", "status": "failed",
                               "reason": "design 没产出任何 RTL —— 没有可验的 DUT，"
                                         f"后面全都会连锁失败。丢弃详情：{detail}"}]}


async def n_design(state: PipelineState, config) -> Dict[str, Any]:
    """design（或 bypass 模式下从 spec 直接解析）。"""
    rt = _rt(config)
    if state.bypass_design or state.bypass_design_model:
        logger.info("验证专注模式：bypass design/model，直接进入 verify（预置 RTL + 黄金模型）")
        spec, arch = _spec_from_front(state)
        # ── RTL 是**唯一输入**时：规格从 DUT 分析出来 ──
        # `--rtl` 与 spec 互斥（CLI 已挡），所以这里 spec_text 是空的 —— 再走
        # `analyze_specification("")` 只会解出 `design_name: dut` 这种假名字。
        # 改成读 RTL：顶层 module 名 → design_name，端口表 → interfaces。
        _rtl_dir = Path(state.output_root) / "rtl"
        _rtl_mods = sorted(_rtl_dir.glob("*.sv")) if _rtl_dir.is_dir() else []
        if not spec and _rtl_mods and not (rt.spec_text or "").strip():
            try:
                import os as _os
                from src.generation.uvm_tools.tool_find_spec_yaml.main import _parse_rtl_module
                _hint = _os.environ.get("SIGNOFFAI_DESIGN_NAME", "").strip()
                _rtl = _parse_rtl_module(_rtl_dir, _hint) or {}
                _m = _rtl.get("module_name") or ""
                if not _m:
                    # 没指名就先按第一个文件里的 module 名兜（`_parse_rtl_module`
                    # 有四级回退，通常已能给出一个）
                    import re as _re
                    _m = (_re.search(r"module\s+(\w+)", _rtl_mods[0].read_text(
                        encoding="utf-8", errors="replace")) or [None, ""])[1]
                spec = {
                    "design_name": _m or "dut",
                    "interfaces": [{"name": q.get("name", ""),
                                    "direction": q.get("direction", "input"),
                                    "data_width": q.get("width", 1)}
                                   for q in (_rtl.get("ports") or [])],
                    # ⚠️ **不从 RTL 猜寄存器**：地址译码有 `case (paddr[1:0])` 直连、
                    # 有 `paddr[7:2]==0` 区间判定、有 `regs[paddr]` 数组索引、还有
                    # DLAB 那种地址重载 —— 猜错就是"spec 说 16 个、RTL 里 4 个"
                    # （实测亲手犯过）。推不出就**如实留空**，宁可少生成用例，
                    # 也不给一份假的寄存器表当规格。
                    "registers": [],
                    "_source": "rtl_analysis",
                    "_note": "本规格由 RTL 分析生成（端口来自 module 声明）；"
                             "registers 未从 RTL 推断，如需寄存器用例请补 spec",
                }
                logger.info(f"RTL 分析：design_name={spec['design_name']} "
                            f"ports={len(spec['interfaces'])}（registers 未推断）")
            except Exception as e:                     # noqa: BLE001 分析失败不该炸
                logger.warning(f"RTL 分析失败，回退最小 spec: {e}")
                spec = {}
        try:
            from src.layers.l3_decision.spec_tools.main import analyze_specification
            _raw = (analyze_specification(rt.spec_text) if not spec
                    else json.dumps(spec, ensure_ascii=False))
            spec = (json.loads(_raw)
                    if isinstance(_raw, str) and _raw.strip().startswith("{") else {})
            if not isinstance(spec, dict) or not spec.get("design_name"):
                spec = {"design_name": "dut"}
            _module = spec.get("design_name", "dut") or "dut"
            arch = {"module_name": _module,
                    "interfaces": spec.get("interfaces", []),
                    "registers": spec.get("registers", []),
                    "function_hier": {"children": []}}
            rt.testcase_reg.register_from_spec(spec, _module,
                                               rtl_version_no=_rtl_version_no(state, _module))
        except Exception as e:
            logger.warning(f"验证专注模式 spec 解析失败（回退最小 spec）: {e}")
            spec = {"design_name": "dut"}
            arch = {"module_name": "dut", "interfaces": [],
                    "registers": [], "function_hier": {"children": []}}
        _phases = [{"name": "design", "status": "skipped", "score": 0}]
        # 只有**连 model 一起跳**时才记 model 跳过。`--rtl`（bypass_design）
        # 不跳 model —— 记成 skipped 会让人以为参考模型没生成。
        if state.bypass_design_model:
            _phases.append({"name": "model", "status": "skipped", "score": 0})
        return {"spec": spec, "design_arch": arch, "phases": _phases}

    data, phase = await _run_agent(rt, state, "design", "design")
    # 用例注册：design 之后 spec 就绪，用真实 design_name（而非硬编码 "dut"）
    try:
        _spec = data.get("spec", {})
        if isinstance(_spec, dict):
            rt.testcase_reg.register_from_spec(
                _spec, _spec.get("design_name", "dut") or "dut",
                rtl_version_no=_rtl_version_no(
                    state, _spec.get("design_name", "dut") or "dut"))
    except Exception:
        pass

    updates: Dict[str, Any] = {"phases": [phase]}
    # 沿用原语义：失败时保留旧值，不被 None 覆盖
    if isinstance(data.get("spec"), dict):
        updates["spec"] = data["spec"]
    if isinstance(data.get("design_arch"), dict):
        updates["design_arch"] = data["design_arch"]

    # ── RTL 门禁：**没有可验的 RTL 就响亮停下** ──
    # design 的每条失败路径都是 `warning + continue`（LLM 产出残缺 / vlog 不过 /
    # 写手异常）。全丢光时 `rtl/` 是空的，而流程原来照常往下跑 —— 最后在编译期
    # 报一屏 `Module 'xxx' is not defined`，失败原因只剩日志里一行 warning。
    # 实测就是这么塌的（加了寄存器表之后 design 没产出任何 RTL）。
    # 与其拿一个空 `rtl/` 走完整条闭环，不如**在这里停下、把原因说清**。
    _arch = updates.get("design_arch") or {}
    _rtl_files = list((Path(state.output_root) / "rtl").glob("*.sv"))         if (Path(state.output_root) / "rtl").is_dir() else []
    if not _rtl_files:
        updates.update(_rtl_missing_update(state, phase, _arch))
    return updates


async def n_model(state: PipelineState, config) -> Dict[str, Any]:
    rt = _rt(config)
    # bypass 模式下 design/model 的 phase 已在 n_design 追加，这里直接跳过
    if state.bypass_design_model:
        return {}
    data, phase = await _run_agent(rt, state, "model", "model",
                                   {"model_type": "systemverilog"})
    updates: Dict[str, Any] = {"phases": [phase]}
    if isinstance(data.get("model"), dict):
        updates["model"] = data["model"]
    return updates


async def n_verify(state: PipelineState, config) -> Dict[str, Any]:
    rt = _rt(config)
    data, phase = await _run_agent(rt, state, "verify", "verify",
                                   {"design_style": state.design_style})
    updates: Dict[str, Any] = {"phases": [phase]}
    if isinstance(data.get("tests"), dict):
        updates["tests"] = data["tests"]
    return updates


