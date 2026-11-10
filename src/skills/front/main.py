"""前置分析智能体 —— 输入（RTL / spec / doc）→ 后面所有人吃的结构化设计信息。

## 为什么单开一个角色

这件事一直有人干（`tool_find_spec_yaml` 解 RTL 端口、`analyze_specification` 抽
spec），但它是**被调的工具**：产出的东西**没有 phase 记录**，出了事查不到是哪一步
产的。抬成角色之后，"这次的设计信息从哪来、是怎么解出来的"进证据链。

## 它到底产什么

**产结构化设计信息（`spec` / `design_arch`），不直接产那三个 yaml。**
三个 yaml（环境 / 用例建模 / 模型）是**下游**从它产的东西生成的 ——
顺序上必须是这样：`bench.yaml` 要知道 DUT 的顶层与端口，那是 design 之后才定的。

  · 环境 yaml     ← 下游 `tool_find_spec_yaml`（吃 spec/design_arch）
  · 用例建模 yaml  ← 下游同上（tags/build/run_cmd 由 agents + 用例库拼）
  · 模型 yaml     ← 下游 `ModelRegistry.to_util_component()`（TLM 1.0 装配单）

所以 front 的 **契约**是那三个 yaml 必须有源可溯 —— 而它的**产出**是它们的输入。

## 输入三选一（互斥规则与 CLI 一致）

  RTL 有、spec 无  → 读 RTL：顶层 module 名 → design_name；端口表 → interfaces
  spec 有、RTL 无  → 读 spec：`analyze_specification` 抽 design_name/interfaces/registers
  doc 可作补充     → 给语义（它不给结构）
  两者都无         → **响亮失败**（没有输入就别往下走）

**不从 RTL 猜寄存器**：地址译码有 `case (paddr[1:0])` 直连、`paddr[7:2]==0` 区间
判定、`regs[paddr]` 数组索引、DLAB 那种地址重载 —— 猜错就是"spec 说 16 个、
RTL 里 4 个"（实测亲手犯过）。推不出就**如实留空**。
"""
from typing import Any, Dict
from pathlib import Path
import os

import structlog

from src.layers.l2_orchestration.skills.base import ExecutorResult, BaseExecutor
from src.layers.l2_orchestration.skills.registry import register_executor

logger = structlog.get_logger()


def _apply_dplan_csv(doc: Dict[str, Any], path: Path) -> Dict[str, Any]:
    """用同目录的 dplan CSV 覆盖 JSON 的 interfaces/modules/model ports。

    CSV 是人工审阅/修正的入口；审阅后改过的值必须盖过机器 sidecar 的旧值。
    """
    from src.skills.front.vplan.dplan_csv import load_dplan_csvs

    prefix = path.stem[:-len("_dplan")] if path.stem.endswith("_dplan") \
        else path.stem
    csv_doc = load_dplan_csvs(path.parent, prefix)
    if not csv_doc:
        return doc
    out = dict(doc)
    for key in ("interfaces", "modules"):
        if csv_doc.get(key):
            out[key] = csv_doc[key]
    if csv_doc.get("model_contract"):
        merged = dict(out.get("model_contract") or {})
        merged["ports"] = csv_doc["model_contract"]["ports"]
        out["model_contract"] = merged
    return out


def _prebuilt_contract(output_dir: Path) -> Dict[str, Any]:
    """bootstrap 落盘的 dplan sidecar（JSON 机器 + CSV 人读）。

    同一个 run 里 front 只该抽一次契约：VPlan 表和设计/模型必须吃同一份。
    JSON 负责非表格字段；`interfaces/modules/model ports` 以同目录 CSV 为准
    （人工审阅改 CSV 后要生效）。找不到就返回空 dict（调用方决定是否再调 LLM）。
    """
    try:
        import json
        from src.layers.l1_infrastructure.layout import find_vplan_root
        from src.skills.front.vplan.dplan_csv import (
            load_dplan_csvs, load_dplan_summary)

        root = find_vplan_root(None, output_dir)
        if root is None:
            return {}
        spec_dir = Path(root) / "docs" / "specs"
        candidates = [Path(root) / "data" / "dplan_contract.json"]
        candidates += sorted(spec_dir.glob("*_dplan.json"))
        for path in candidates:
            if not path.is_file():
                continue
            doc = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(doc, dict) and doc.get("design_name"):
                return _apply_dplan_csv(doc, path)
        # JSON 不在、CSV 在：CSV 单独也能还原出契约（审阅场景）。
        for path in sorted(spec_dir.glob("*_dplan_interfaces.csv")):
            prefix = path.name[:-len("_dplan_interfaces.csv")]
            summary = load_dplan_summary(spec_dir, prefix)
            if not summary.get("design_name"):
                continue
            doc = dict(summary)
            doc.update(load_dplan_csvs(spec_dir, prefix))
            return doc
    except Exception as e:                         # noqa: BLE001 旁路
        logger.warning(f"front：dplan sidecar 读取失败（回退抽取）: {e}")
    return {}


def _apply_llm_contract(info: Dict[str, Any], spec_text: str,
                        sources: list, output_dir: Path) -> Dict[str, Any]:
    """补设计/模型契约：优先复用 bootstrap sidecar，否则按需调 LLM。"""
    from src.skills.front.dplan import merge_contracts

    prebuilt = _prebuilt_contract(output_dir)
    if prebuilt:
        sources.append("vplan_dplan_sidecar")
        logger.info(
            f"front：复用 dplan 契约 design_name={prebuilt.get('design_name')} "
            f"ports={len(prebuilt.get('interfaces') or [])} "
            f"modules={len(prebuilt.get('modules') or [])}")
        return merge_contracts(info, prebuilt)
    if os.environ.get("SIGNOFFAI_SPEC_LLM", "").strip().lower() not in (
            "1", "true", "yes"):
        return info
    try:
        from src.skills.front.dplan import extract_contracts

        hint = os.environ.get("SIGNOFFAI_DESIGN_NAME", "").strip()
        contract = extract_contracts(spec_text, module_hint=hint)
        if not contract:
            return info
        merged = merge_contracts(info, contract)
        sources.append("llm_spec_contract")
        logger.info(
            f"front：LLM spec 契约 design_name={merged.get('design_name')} "
            f"ports={len(merged.get('interfaces') or [])} "
            f"features={len(merged.get('features') or [])} "
            f"model_contract={'yes' if merged.get('model_contract') else 'no'}")
        return merged
    except Exception as e:                           # noqa: BLE001 失败退回确定性
        logger.warning(f"front：LLM spec 契约解析失败（退回确定性）: {e}")
        return info


def _function_children(info: Dict[str, Any]) -> list:
    """dplan 模块划分 → `function_hier.children`（不含 top）。

    没有模块就如实空着，不编假的子模块树；子模块接口留在各自节点上，
    TP 建模可归因到具体模块。
    """
    out = []
    for module in info.get("modules") or []:
        if not isinstance(module, dict) or not module.get("name"):
            continue
        if str(module.get("level") or "").lower() == "top":
            continue
        out.append({
            "name": str(module["name"]),
            "level": str(module.get("level") or "sub"),
            "function": str(module.get("function") or ""),
            "interfaces": module.get("interfaces") or [],
        })
    return out


def _write_dplan_inputs(output_dir: Path, info: Dict[str, Any]) -> None:
    """把 dplan（设计/模型契约）与 VPlan 项目做对齐映射（不比较相等）。"""
    try:
        from src.layers.l1_infrastructure.layout import find_vplan_root

        root = find_vplan_root(None, output_dir)
        if root is None:
            return
        from src.layers.l3_decision.vplan import load_project
        from src.layers.l3_decision.dplan import (
            build_dplan_map, write_dplan_contracts)

        result = write_dplan_contracts(output_dir, info, load_project(root))
        doc = build_dplan_map(info, load_project(root))
        cov = doc["coverage"]
        logger.info(
            f"dplan↔VPlan：feature {cov['dplan_mapped']}/{doc['dplan']['features']}"
            f" 已对齐；VPlan 需求未覆盖 {len(cov['vplan_unmapped_requirements'])} 条；"
            f"契约命中 {len(cov['mapped_contracts'])}/{cov['contract_count']}"
            f" → {result['base']}")
        for name in cov["dplan_unmapped"][:3]:
            logger.warning(f"dplan feature 未对齐 VPlan：{name}")
    except Exception as e:                         # noqa: BLE001 映射是旁路
        logger.warning(f"dplan↔VPlan 对齐失败: {e}")


@register_executor("front")
class FrontExecutor(BaseExecutor):
    """前置分析 = 读输入 + 解出结构化设计信息。"""

    task_type = "code_generation"
    consumes = []
    produces = "spec"

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(role="front", display_name="前置分析智能体",
                         description="RTL / spec / doc → 结构化设计信息（喂下游三个 yaml）",
                         config=config or {})

    async def _setup(self):
        """子类特定初始化 —— front 是**纯分析**角色：不接 LLM、不挂工具，
        全部工作由 `execute_task` 调确定性工具/分析完成（见模块 docstring）。

        必须实现：`BaseExecutor` 把它声明成 `@abstractmethod`，不实现的话
        `FrontExecutor()` **实例化即 TypeError** —— 而 `execution.py` 的实例表
        是在导入期构造的，一个抽象方法没实现会把整个运行服务带崩
        （实测：连带 84 个测试失败）。
        """
        self.ctx_reg = getattr(self, "ctx_reg", None)

    async def _get_prompt_template(self):
        return None

    async def _get_tools(self):
        return []

    async def _execute(self, input_text: str):
        return input_text

    # ── 主入口 ──────────────────────────────────────────────

    async def execute_task(self, task: Dict[str, Any]) -> ExecutorResult:
        from src.layers.l1_infrastructure.output_config import make_output_root

        output_dir = Path(make_output_root(task.get("output_dir") or None))
        task["output_dir"] = str(output_dir)
        spec_text = str(task.get("input") or "")

        rtl_dir = output_dir / "rtl"
        rtl_files = sorted(rtl_dir.glob("*.sv")) if rtl_dir.is_dir() else []

        if not rtl_files and not spec_text.strip():
            # **没有输入就别往下走** —— 静默给一个 `design_name: dut` 会让后面
            # 整条链在一个不存在的设计上跑，最后报一堆看不懂的错。
            return ExecutorResult(
                success=False,
                data={"score": 0},
                error="前置分析失败：既没有 RTL（<run>/rtl/ 为空）也没有 spec —— "
                      "没有输入。请给 spec，或用 `--rtl <目录>` 给 RTL。",
                metadata={"phase": "front", "no_input": True})

        info: Dict[str, Any] = {}
        sources = []

        # ① RTL：顶层 module 名 + 端口表（**调工具**，确定性）
        if rtl_files:
            try:
                import os as _os
                from src.tools.generation.uvm_tools.tool_find_spec_yaml.main import _parse_rtl_module
                # 顶层模块名有 hint 就用它：多文件 RTL 里空名字只能靠启发式猜，
                # 实测 6 个文件选中了子模块 cmd_int_perf。
                rtl = _parse_rtl_module(
                    rtl_dir, _os.environ.get("SIGNOFFAI_DESIGN_NAME", "").strip()) or {}
                info["design_name"] = rtl.get("module_name") or "dut"
                info["interfaces"] = [
                    {"name": p.get("name", ""),
                     "direction": p.get("direction", "input"),
                     "data_width": p.get("width", 1)}
                    for p in (rtl.get("ports") or [])]
                # 寄存器**不猜**（见模块 docstring）
                info["registers"] = []
                info["_source"] = "rtl_analysis"
                info["_note"] = ("规格由 RTL 分析生成（端口来自 module 声明）；"
                                 "registers 未从 RTL 推断 —— 如需寄存器用例请补 spec")
                sources.append(f"rtl({len(rtl_files)} files)")
                logger.info(f"front：RTL 分析 design_name={info['design_name']} "
                            f"ports={len(info['interfaces'])}（registers 未推断）")
            except Exception as e:                     # noqa: BLE001 分析失败不该炸
                logger.warning(f"front：RTL 分析失败: {e}")

        # ② spec：抽 design_name/interfaces/registers/features（确定性）
        if spec_text.strip():
            try:
                import json as _json
                from src.layers.l3_decision.spec_tools.main import analyze_specification
                raw = analyze_specification(spec_text)
                doc = _json.loads(raw) if isinstance(raw, str) and raw.strip().startswith("{") else {}
                if isinstance(doc, dict):
                    # RTL 已经解出端口时**以 RTL 为准**（它是实现，spec 是意图）；
                    # 只补 spec 有而 RTL 给不出的字段（registers/features）。
                    for k in ("design_name", "registers", "features", "overview"):
                        if doc.get(k) and not info.get(k):
                            info[k] = doc[k]
                    info.setdefault("interfaces", doc.get("interfaces", []))
                    sources.append("spec")
                    logger.info(f"front：spec 分析 design_name={info.get('design_name')} "
                                f"registers={len(info.get('registers') or [])}")
            except Exception as e:                     # noqa: BLE001
                logger.warning(f"front：spec 分析失败: {e}")

        info = _apply_llm_contract(info, spec_text, sources, output_dir)
        _write_dplan_inputs(output_dir, info)

        if not info.get("design_name"):
            return ExecutorResult(success=False, data={"score": 0},
                               error="前置分析失败：没能解出 design_name（RTL 里没有 "
                                     "module 声明，spec 里也没有 design_name）")

        # `precheck` 读的是 spec 本体（不是 design_arch），所以层次两处都要带。
        hier = {"children": _function_children(info)}
        info["function_hier"] = hier
        arch = {"module_name": info["design_name"],
                "interfaces": info.get("interfaces", []),
                "registers": info.get("registers", []),
                "model_contract": info.get("model_contract", {}),
                "function_hier": hier}

        # 用例库登记：design 之后 spec 就绪 —— 这里更早，用例库早一步可查
        #
        # 登记时把**这一轮的 RTL 版本**一起写上：用例是有版本的（RTL 换了版，
        # 旧用例是在哪版上定的就答不上来了）。版本走 `ensure_run_rtl_version`
        # 这一个入口（与 debug / finalize 共用），拿不到就是 None，不编一个 0。
        rtl_version_no = None
        try:
            from src.layers.l4_memory.lineage import run_rtl_version_no
            rtl_version_no = run_rtl_version_no(output_dir,
                                                module=info["design_name"])
        except Exception as e:                         # noqa: BLE001 血缘不该阻断分解
            logger.warning(f"血缘：这一轮的 RTL 版本取不到（用例将不带版本）: {e}")
        try:
            if self.ctx_reg is not None:
                self.ctx_reg.register_from_spec(info, info["design_name"],
                                                rtl_version_no=rtl_version_no)
        except Exception:                              # noqa: BLE001 登记失败不阻断
            pass

        return ExecutorResult(
            success=True,
            data={"spec": info, "design_arch": arch, "score": 90,
                  "sources": sources,
                  "front": {"sources": sources,
                            "design_name": info["design_name"],
                            "ports": len(info.get("interfaces", [])),
                            "registers": len(info.get("registers") or []),
                            "register_source": info.get("_source", "")}},
            metadata={"phase": "front"})

    #: 用例库句柄，由外部（init 节点）注入；没有就跳过登记
    ctx_reg = None
