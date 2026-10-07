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

import structlog

from src.layers.l2_orchestration.agents.base import AgentResult, BaseAgent
from src.layers.l2_orchestration.agents.registry import register_agent

logger = structlog.get_logger()


@register_agent("front")
class FrontAgent(BaseAgent):
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

        必须实现：`BaseAgent` 把它声明成 `@abstractmethod`，不实现的话
        `FrontAgent()` **实例化即 TypeError** —— 而 `execution.py` 的实例表
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

    async def execute_task(self, task: Dict[str, Any]) -> AgentResult:
        from src.layers.l1_infrastructure.output_config import make_output_root

        output_dir = Path(make_output_root(task.get("output_dir") or None))
        task["output_dir"] = str(output_dir)
        spec_text = str(task.get("input") or "")

        rtl_dir = output_dir / "rtl"
        rtl_files = sorted(rtl_dir.glob("*.sv")) if rtl_dir.is_dir() else []

        if not rtl_files and not spec_text.strip():
            # **没有输入就别往下走** —— 静默给一个 `design_name: dut` 会让后面
            # 整条链在一个不存在的设计上跑，最后报一堆看不懂的错。
            return AgentResult(
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
                from src.tools.uvm_tools.tool_find_spec_yaml.main import _parse_rtl_module
                rtl = _parse_rtl_module(rtl_dir, "") or {}
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
                from src.tools.spec_tools.main import analyze_specification
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

        if not info.get("design_name"):
            return AgentResult(success=False, data={"score": 0},
                               error="前置分析失败：没能解出 design_name（RTL 里没有 "
                                     "module 声明，spec 里也没有 design_name）")

        arch = {"module_name": info["design_name"],
                "interfaces": info.get("interfaces", []),
                "registers": info.get("registers", []),
                "function_hier": {"children": []}}

        # 用例库登记：design 之后 spec 就绪 —— 这里更早，用例库早一步可查
        try:
            if self.ctx_reg is not None:
                self.ctx_reg.register_from_spec(info, info["design_name"])
        except Exception:                              # noqa: BLE001 登记失败不阻断
            pass

        return AgentResult(
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
