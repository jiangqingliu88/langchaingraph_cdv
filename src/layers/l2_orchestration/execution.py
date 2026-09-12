"""
Pipeline 执行服务 —— CLI 和 Web API 共享的验证流水线引擎

单例模式，管理 Agent 生命周期 + 流水线执行 + 运行状态追踪。
"""
from __future__ import annotations
import time, json, uuid, asyncio
from copy import deepcopy
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime
import structlog

from src.layers.l1_infrastructure.output_config import make_output_root

from src.layers.l2_orchestration.agents.registry import AgentRegistry
from src.agents.design import DesignAgent
from src.agents.model import ModelAgent
from src.agents.verify import VerifyAgent
from src.agents.ops import OpsAgent
from src.agents.coverage import CoverageAgent
from src.agents.debug import DebugAgent
from src.agents.audit import AuditAgent
from config.settings import Settings

logger = structlog.get_logger()


def _collect_llm_audit() -> dict:
    """收集本 run 的 LLM 调用审计（prompt 哈希 + 调用状态 + token 用量）。

    从 LLMQueryEngine 的 audit_log 读取（query_engine 记录每次调用的 cache_key =
    prompt 内容的 SHA256 前缀），落进 manifest 的 llm_audit 字段，
    支撑"同一 prompt 可复现调用"的可复现性承诺。
    失败返回空结构（不阻断 manifest 落盘）。
    """
    try:
        from src.layers.l2_orchestration.context.query_engine import LLMQueryEngine
        qe = LLMQueryEngine.get_instance()
        entries = list(getattr(qe, "audit_log", []) or [])[-50:]  # 最近 50 条
        budget = qe.get_budget_status()
        return {
            "call_count": len(entries),
            "prompt_hashes": [e.get("cache_key", "") for e in entries if e.get("cache_key")],
            "response_hashes": [e.get("response_sha", "") for e in entries if e.get("response_sha")],
            "statuses": {s: sum(1 for e in entries if e.get("status") == s)
                         for s in set(e.get("status", "") for e in entries)},
            "tokens_used": budget.get("tokens_used", 0),
            "budget": budget.get("budget", 0),
            "cache_hits": budget.get("cache_hits", 0),
        }
    except Exception as e:
        logger.warning(f"LLM 审计收集失败: {e}")
        return {"call_count": 0, "error": str(e)[:100]}

class PipelineExecutionService:
    """流水线执行服务（单例）"""

    _instance: Optional[PipelineExecutionService] = None

    def __init__(self):
        self.settings = Settings.get_instance()
        self.registry = AgentRegistry.get_instance()
        self._initialized = False
        self._runs: Dict[str, dict] = {}  # run_id → {state, phases, results, ctx}

    @classmethod
    def get_instance(cls) -> PipelineExecutionService:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ── Agent 生命周期 ──

    async def initialize_agents(self) -> None:
        """初始化所有 12 个 Agent（幂等）"""
        if self._initialized:
            return

        agents = [
            ("design",   DesignAgent()),
            ("model",    ModelAgent()),
            ("verify",   VerifyAgent()),
            ("ops",      OpsAgent()),
            ("coverage", CoverageAgent()),
            ("debug",    DebugAgent()),
            ("audit",    AuditAgent()),
        ]
        for role, agent in agents:
            await agent.initialize()
            self.registry.set_agent_instance(role, agent)

        self._initialized = True
        logger.info("All agents initialized via PipelineExecutionService")

    @property
    def initialized(self) -> bool:
        return self._initialized

    def _relax_transaction_constraints(self, output_root: str, gaps: list):
        """放宽约束：把被 constraint 型 gap 限制的信号约束放宽到全位宽范围。

        文本级修改 agents/*/*_transaction.sv 里的 `inside {[0:MAX]}` → 全范围，
        下一轮 coverage 重新编译仿真后，高位 toggle 不再是约束型缺口。
        """
        import re
        try:
            signals = {g.get("location", "").split("[")[0]
                       for g in gaps if isinstance(g, dict) and g.get("reason") == "constraint"}
            if not signals:
                return
            for tx_file in Path(output_root).glob("agents/*/*_transaction.sv"):
                text = tx_file.read_text(encoding="utf-8", errors="replace")
                widths = {}
                for m in re.finditer(r"rand\s+bit\s*\[(\d+):0\]\s+(\w+)\s*;", text):
                    widths[m.group(2)] = int(m.group(1)) + 1
                changed = False
                for sig in signals:
                    w = widths.get(sig)
                    if not w:
                        continue
                    full_max = (1 << w) - 1
                    pat = re.compile(r"(" + re.escape(sig) + r"\s+inside\s*\{\s*\[0:)\d+(\]\s*\})")
                    text, n = pat.subn(r"\g<1>" + str(full_max) + r"\g<2>", text)
                    if n > 0:
                        changed = True
                if changed:
                    tx_file.write_text(text, encoding="utf-8", errors="replace")
        except Exception as e:
            logger.warning(f"放宽约束失败: {e}")

    @staticmethod
    def _escalate_to_human(reason: str, action_type: str) -> str:
        """升级人工：熔断/预算耗尽时，让人工决定 retry（复位熔断）/ abort（终止）。

        返回 "retry" 或 "abort"。
        """
        try:
            from src.layers.l2_orchestration.governance.quality_guard import EscalationConsole
            decision = EscalationConsole.ask(
                f"governor:{action_type}",
                [f"驾驭层拦截: {reason}"],
                {"action_type": action_type, "reason": reason},
            )
            # EscalationConsole 返回 retry/accept_fallback/skip/abort
            return decision if decision in ("retry", "abort") else "abort"
        except Exception:
            # 终端不可用（如 CI）→ 默认 abort（终止，人工后续介入）
            return "abort"

    def _record_agent_files(self, file_audit, role: str, data: dict, params: dict = None):
        """审计证据链：记录 Agent 产出的文件（git diff + 修改理由）。

        file_audit 作为参数传入（而非 self._file_audit），保证多模块流水并发时
        各模块证据链互不污染。
        """
        if file_audit is None:
            return
        # 从 data 里提取文件列表
        files = []
        reason = ""
        for key in ("design_arch", "model", "tests", "rtl", "regression"):
            if isinstance(data.get(key), dict):
                val = data[key]
                if isinstance(val.get("files"), list):
                    files.extend(val["files"])
                elif isinstance(val.get("written_files"), list):
                    files.extend(val["written_files"])
        # 参数里的 reason（如比对失败、死代码）
        if isinstance(params, dict):
            reason = params.get("reason", "")
        for fpath in files[:10]:  # 最多记录 10 个文件
            try:
                file_audit.record(str(fpath), reason or f"{role} 产出", role)
            except Exception:
                pass

    @staticmethod
    def _discover_excludes(exclude_reg, gaps: list, calibration: dict = None) -> int:
        """Exclude 四步闭环·第 1 步（自动发现）：结构性不可达覆盖点 → 提议放弃。

        归因分类（第 2 步）：coverage Agent 已在归因校准阶段把"多次 refactor 仍 0%"的
        unreachable 点筛入 `calibration.blacklisted_gaps`——这些点就是结构性死代码，
        直接提议 TYPE_UNREACHABLE。"规格不测/成本高"由工程师经 CLI 手动提议。
        返回本次提议数量。
        """
        try:
            from src.layers.l4_memory.exclude_registry import TYPE_UNREACHABLE
            blacklisted = (calibration or {}).get("blacklisted_gaps", []) or []
            if not blacklisted:
                return 0
            existing = exclude_reg.get_all_points()
            proposed = 0
            for g in blacklisted:
                if not isinstance(g, dict):
                    continue
                dim = g.get("dimension", "")
                point = str(g.get("location") or g.get("signal") or dim or "unknown")
                if not point or point == "unknown" or point in existing:
                    continue
                exclude_reg.propose_exclude(
                    point,
                    reason=f"结构性死代码：{dim} 多次重构后覆盖率仍为 0%",
                    exclude_type=TYPE_UNREACHABLE,
                    evidence=f"unreachable 黑名单命中（dimension={dim}）",
                )
                existing.add(point)
                proposed += 1
            return proposed
        except Exception as e:
            logger.warning(f"Exclude 自动发现失败: {e}")
            return 0

    @staticmethod
    def _llm_repair_compile_error(output_root: str, compile_error: dict) -> bool:
        """LLM 兜底修复编译错误（确定性自愈失败时调用）。

        读出错文件 → LLM 产出修正版 → 写回。仅 LLM 改写 RTL，不改接口结构。
        返回是否实际写回。
        """
        try:
            from src.tools.lib.llm_refine import call_llm
            fname = (compile_error or {}).get("file", "")
            if not fname:
                logger.warning("LLM 兜底：无文件名，跳过")
                return False
            fpath = Path(output_root) / fname
            if not fpath.exists():
                cands = list(Path(output_root).rglob(fname))
                fpath = cands[0] if cands else None
            if fpath is None:
                logger.warning(f"LLM 兜底：找不到文件 {fname}")
                return False
            code = fpath.read_text(encoding="utf-8", errors="replace")
            msg = (compile_error or {}).get("message", "")
            prompt = (
                "你是 IC 设计工程师。下面 SystemVerilog 模块有编译/elaboration 错误。\n"
                "只修复报错点，保留模块接口与整体结构，输出完整修正后的 module（含 module/endmodule）。"
            )
            fixed = call_llm(prompt, code, msg)
            if not fixed or "module" not in fixed or "endmodule" not in fixed:
                logger.warning(f"LLM 兜底：返回无效代码，未写回 {fname}")
                return False
            fpath.write_text(fixed, encoding="utf-8")
            logger.info(f"LLM 兜底：已重写 {fname}")
            return True
        except Exception as e:
            logger.warning(f"LLM 兜底修复失败: {e}")
            return False

    async def run_closed_loop(self, spec_text: str, output_root: str = "output",
                              target: Optional[float] = None, max_rounds: int = 5,
                              design_style: str = "baseline",
                              bypass_design_model: bool = False,
                              approval_gate=None) -> dict:
        """七 Agent 闭环：design → model → verify → ops → coverage → [decision] → audit。

        控制流已由图承载（src/layers/l2_orchestration/graph.py 的 StateGraph），
        本方法只做四件事：解析入口参数 → 建运行期上下文 → 跑图 → 返回结果。

        为什么能把 626 行命令式函数换掉而不改行为：
          原函数的「共享状态」绝大部分其实是控制流（阶段顺序 + 动作分流），
          真实数据流是 _run() 的返回值；逐节点的映射见 graph.py 顶部注释。
        签名与返回结构保持不变，CLI / REPL / run_multi_module 无需改动。

        target: 覆盖率目标（None=从统一配置 Settings.verification.coverage_target 读）。
        design_style: 设计风格（baseline/pipeline/low_power）。
        bypass_design_model: True = 验证专注模式，跳过 design/model。
        approval_gate: 审批门控（None=自动；传入则高风险动作前审批）。
        """
        # 解析输出目录一次（幂等），避免每个 Agent 各自追加时间戳 → 目录不一致
        output_root = make_output_root(output_root)
        # 统一覆盖率目标来源（消除散落硬编码 95）
        if target is None:
            from src.layers.l2_orchestration.planning import get_coverage_target
            target = get_coverage_target()

        if not self._initialized:
            await self.initialize_agents()

        from src.layers.l2_orchestration.graph import (
            Runtime, build_closed_loop_graph, recursion_limit)
        from src.layers.l2_orchestration.state import PipelineState

        rt = Runtime(self, spec_text, approval_gate=approval_gate)
        graph = build_closed_loop_graph()

        initial = PipelineState(
            run_id=Path(output_root).name,
            output_root=str(output_root),
            target=float(target),
            max_rounds=int(max_rounds),
            design_style=design_style,
            bypass_design_model=bool(bypass_design_model),
        )
        config = {
            "configurable": {"rt": rt},
            # LangGraph 数的是 superstep 而非轮次，一轮约 6-10 步
            "recursion_limit": recursion_limit(int(max_rounds)),
        }
        final = await graph.ainvoke(initial, config)
        # LangGraph 对 pydantic 状态返回模型实例；defensive 地兼容 dict
        result = (final.get("result") if isinstance(final, dict)
                  else getattr(final, "result", None))
        return result or {}

    async def run_multi_module(self, module_specs: List[dict], output_root: str = "output",
                               target: Optional[float] = None, max_rounds: int = 5,
                               design_style: str = "baseline", max_concurrency: int = 4,
                               approval_gate=None) -> List[dict]:
        """多模块软件流水：并发跑多个闭环，EDA 等待期间互相推进（不阻塞）。

        与"多 DUT"的区别：这里的"多模块"是多个验证任务/规格的流水并行——
        模块 A 在 EDA 编译仿真（to_thread 线程里）时，模块 B 的 LLM 生成
        （design/model/verify）在事件循环里继续推进，不空转、不完全阻塞。

        module_specs: [{"name", "spec_file"|"spec_text", "target"?, "max_rounds"?, "design_style"?}, ...]
        每个模块独立 output_root/<name> + 独立证据链（FileAuditTrail 实例隔离，见 run_closed_loop）。

        返回与输入同序的结果列表（单个模块异常以 Exception 形式留在结果里）。
        """
        from src.layers.l2_orchestration.pipeline_scheduler import PipelineScheduler
        from src.layers.l1_infrastructure.output_config import make_output_root

        # 先确保 agent 初始化（避免多任务并发时重复初始化竞态）
        if not self._initialized:
            await self.initialize_agents()

        base_root = make_output_root(output_root)
        sched = PipelineScheduler(max_concurrency=max_concurrency)

        def _make_task(m: dict, idx: int):
            name = (m.get("name") or f"module_{idx + 1}").replace("/", "_").replace("\\", "_")
            spec = m.get("spec_text", "")
            if not spec and m.get("spec_file"):
                try:
                    spec = Path(m["spec_file"]).read_text(encoding="utf-8", errors="replace")
                except Exception as e:
                    spec = ""
                    logger.warning(f"模块 {name} spec 读取失败: {e}")
            # 每个模块独立带时间戳子目录（make_output_root 幂等，互不冲突）
            sub_root = make_output_root(str(Path(base_root) / name))

            async def _run():
                return await self.run_closed_loop(
                    spec_text=spec, output_root=sub_root,
                    target=m.get("target", target),
                    max_rounds=m.get("max_rounds", max_rounds),
                    design_style=m.get("design_style", design_style),
                    approval_gate=approval_gate,
                )
            return _run

        tasks = [_make_task(m, i) for i, m in enumerate(module_specs)]
        return await sched.waterfall(tasks)

    # ── 运行状态查询 ──

    def get_run_status(self, run_id: str) -> Optional[dict]:
        """获取运行状态（供 SSE 轮询 / 前端查询）。优先内存，其次 DB。"""
        run = self._runs.get(run_id)
        if not run:
            return None
        return {
            "run_id": run["run_id"],
            "state": run["state"],
            "current_phase": run["current_phase"],
            "phases": run["phases"],
            "passed": run.get("passed", 0),
            "total": run.get("total", 0),
            "overall_score": run.get("overall_score", 0),
            "scores": run.get("scores", {}),
            "governance": run.get("governance", {}),
            "output_root": run.get("output_root", ""),
            "started_at": run.get("started_at", ""),
            "completed_at": run.get("completed_at", ""),
        }

    def list_runs(self) -> List[dict]:
        """列出所有运行"""
        return [
            {"run_id": r["run_id"], "workflow": r["workflow"],
             "state": r["state"], "started_at": r["started_at"]}
            for r in self._runs.values()
        ]

    # ── 单 Agent 执行 ──

    async def run_single_agent(
        self, role: str, input_text: str
    ) -> dict:
        """执行单个 Agent，返回 {success, output, error}"""
        if not self._initialized:
            await self.initialize_agents()

        agent = self.registry.get_agent_instance(role)
        if not agent:
            return {"success": False, "error": f"Agent not found: {role}"}

        task = {"ctx": {}, "input": input_text}
        r = await agent.execute_task(task)
        return {
            "success": r.success,
            "output": r.data.get("output", "") if r.data else "",
            "error": r.error,
        }

    # ── 测试用例生成 ──

    async def generate_testcases(
        self, spec_text: str, output_dir: str = "output/testcases"
    ) -> dict:
        """运行 test_engineer Agent 生成测试用例"""
        if not self._initialized:
            await self.initialize_agents()

        ctx = {
            "spec": {"test_points": []},
            "env": {"env_name": "dut_env"},
        }

        agent = self.registry.get_agent_instance("test")
        if not agent:
            return {"success": False, "error": "test_engineer not found"}

        task = {
            "ctx": ctx,
            "input": json.dumps({
                "test_points": [],
                "env": ctx["env"],
            }),
            "output_dir": output_dir,
        }

        r = await agent.execute_task(task)
        return {
            "success": r.success,
            "tests": r.data.get("tests", {}),
            "output": r.data.get("output", ""),
            "error": r.error,
        }
