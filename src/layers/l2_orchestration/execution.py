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
                              approval_gate=None) -> dict:
        """七 Agent 闭环：design → model → verify → ops → coverage → [decision] → audit。

        决策层驱动迭代（5 动作），覆盖率达标收敛。
        target: 覆盖率目标（None=从统一配置 Settings.verification.coverage_target 读，默认 95）。
        design_style: 设计风格（baseline/pipeline/low_power），驱动策略包加载。
        approval_gate: 审批门控（None=自动；传入则高风险动作前审批）。
        """
        # 解析输出目录一次（幂等），避免每个 Agent 各自追加时间戳 → 目录不一致
        output_root = make_output_root(output_root)
        # 统一覆盖率目标来源（消除散落硬编码 95）
        if target is None:
            from src.layers.l2_orchestration.planning import get_coverage_target
            target = get_coverage_target()
        from src.layers.l3_decision.decision_engine import CoverageDrivenDecisionEngine, Observation
        # 初始化审计证据链（独立实例 + 局部变量：多模块流水并发时各模块证据链互不污染）
        file_audit = None
        try:
            from src.layers.l2_orchestration.evidence.file_audit import FileAuditTrail
            file_audit = FileAuditTrail(str(output_root))
        except Exception:
            pass

        if not self._initialized:
            await self.initialize_agents()

        ctx = {}
        phases = []
        coverage_history = []
        engine = CoverageDrivenDecisionEngine(target=target)

        # Event Bus：注册验证事件订阅者（KG 世界模型 + L3 决策 reactor 响应 L1 的异步事件）
        decision_reactor = None
        try:
            from src.layers.l2_orchestration.communication.verification_events import (
                register_verification_handlers, register_decision_reactor)
            register_verification_handlers()
            # RL Q 表持久化到项目根 .signoffai/（跨 run 学习，越用越聪明）
            _rl_path = str(Path.cwd() / ".signoffai" / "rl_policy.json")
            decision_reactor = register_decision_reactor(target=target, rl_json_path=_rl_path)
        except Exception:
            pass

        # ── Planning 阶段：长周期任务规划（目标分解 + 里程碑 + 收敛预测）──
        from src.layers.l2_orchestration.planning import CoveragePlanner
        planner = CoveragePlanner(target=target, start=0.0, max_rounds=max_rounds)
        phases.append({"name": "planning", "status": "planned",
                       "target": target, "milestones": planner.milestones})

        # ── L1 基础设施层：统一管理文件系统 / Git 仓库 / 覆盖率数据库 ──
        from src.layers.l1_infrastructure.infrastructure import InfrastructureManager
        infra = InfrastructureManager(output_root)
        infra.setup()

        # ── 驾驭层：统一预算 + 熔断 + 细粒度干预 + 决策可干预 ──
        from src.layers.l2_orchestration.governance.governor import Governor
        governor = Governor(output_root)

        # ── 用例状态库：场景分解 + 比例动态优化（数据驱动的用例管理）──
        # 跨 run 共享（用例 effectiveness / portfolio 权重跨 run 累积），放项目根 .signoffai/
        from src.layers.l4_memory.testcase_registry import TestcaseRegistry
        testcase_reg = TestcaseRegistry()

        # ── Exclude 状态库：允许放弃（四步闭环：发现→归因→审计→调规）──
        # 跨 run 共享（审计哈希链跨 run 连续），放项目根 .signoffai/
        from src.layers.l4_memory.exclude_registry import ExcludeRegistry
        exclude_reg = ExcludeRegistry()

        async def _run(role, label, params=None):
            """执行单个真实 Agent（execute_task）。"""
            t0 = __import__('time').time()
            agent = self.registry.get_agent_instance(role)
            if not agent:
                phases.append({"name": label, "status": "skipped", "score": 0})
                return {}
            task = {"ctx": ctx, "input": spec_text, "output_dir": output_root}
            if params:
                task["params"] = params
            try:
                result = await agent.execute_task(task)
                # 失败时也保留 data（含 regression 的 failed 详情），供回归门控决策
                data = result.data if isinstance(result.data, dict) else {}
                score = data.get("score", 0)
                status = "passed" if result.success else "failed"
                # 驾驭层：agent 执行成败反馈给 Governor（agent 级熔断，连续失败 → 升级人工）
                governor.after_action(role, success=result.success,
                                      eda=(1 if role in ("ops", "coverage") else 0))
                if not result.success:
                    logger.warning(f"agent '{role}' 执行失败，已反馈驾驭层（熔断计数 +1）")
            except Exception as e:
                logger.warning(f"{role} 执行失败: {e}")
                data, score, status = {}, 0, "error"
                governor.after_action(role, success=False,
                                      eda=(1 if role in ("ops", "coverage") else 0))
            ctx.update(data)
            phases.append({"name": label, "status": status, "score": score,
                           "time": round(__import__('time').time() - t0, 1)})

            # ── 审计证据链: 记录该 Agent 产出的文件（git diff + 理由）──
            self._record_agent_files(file_audit, role, data, params)
            return data

        # ── 顺序: design → model → verify ──
        await _run("design", "design")
        # 用例注册：design 之后 ctx["spec"] 就绪，用真实 design_name（而非硬编码 "dut"）
        try:
            _spec = ctx.get("spec", {}) if isinstance(ctx, dict) else {}
            if isinstance(_spec, dict):
                _module = _spec.get("design_name", "dut") or "dut"
                testcase_reg.register_from_spec(_spec, _module)
        except Exception:
            pass
        # SystemVerilog 参考模型（与 DUT 接口对齐，接入 env 做逐拍 compare）
        await _run("model", "model", {"model_type": "systemverilog"})
        await _run("verify", "verify", {"design_style": design_style})

        # ── env 架构验收：端口归属（静态）+ scoreboard 定向 case（仿真）──
        # 原为独立 CLI 命令 `vagent check-env-arch`，现接进闭环，在回归前就拦住 env 架构问题。
        _env_arch_phase = {"name": "env_arch_check", "status": "skipped", "score": 0}
        try:
            from src.tools.uvm_tools.tool_check_env_arch.main import check_env_arch as _check_env_arch
            from src.tools.lib.filelist import build_filelist_for_tb
            _fl_path = Path(output_root) / "inputs" / "filelists" / "filelist.f"
            if not _fl_path.exists():
                _env_name = "dut_env"
                for _p in sorted((Path(output_root) / "env").glob("*_pkg.sv")):
                    _env_name = _p.name.replace("_pkg.sv", "")
                    break
                _agents_dir = Path(output_root) / "agents"
                _agents = [{"name": d.name} for d in _agents_dir.iterdir() if d.is_dir()] \
                    if _agents_dir.exists() else []
                build_filelist_for_tb(Path(output_root), _agents, _env_name, "filelist.f")
            _env_arch = await asyncio.to_thread(_check_env_arch, str(output_root))
            _po = _env_arch.get("port_ownership", {}) or {}
            _sb = _env_arch.get("scoreboard", {}) or {}
            _arch_status = _env_arch.get("status", "FAIL")
            _ok = _arch_status == "PASS"
            _arch_phase_status = ("passed" if _ok
                                  else ("error" if _arch_status == "EDA_MISSING" else "failed"))
            _env_arch_phase = {
                "name": "env_arch_check",
                "status": _arch_phase_status,
                "score": 100 if _ok else 0,
                "port_ownership": _po.get("status"),
                "scoreboard": _sb.get("status"),
                "reason": (str(_po.get("message", "")) + " | " + str(_sb.get("message", "")))[:240],
            }
            if not _ok:
                logger.warning(f"env 架构验收未通过: {_env_arch_phase['reason']}")
        except Exception as _e:
            _env_arch_phase = {"name": "env_arch_check", "status": "error",
                               "score": 0, "reason": str(_e)[:160]}
            logger.warning(f"env 架构验收执行失败: {_e}")
        phases.append(_env_arch_phase)

        # ── 闭环: ops → coverage → [decision] ──
        final_coverage = 0.0
        effective_coverage = 0.0          # Exclude 调规后的有效覆盖率（决策层按此判断）
        exclude_effect = {}               # 每轮有效覆盖率明细（excluded/effective_total/...）
        compile_retries = 0
        iterations = 0
        eda_blocked = False               # EDA 缺失标记（终止闭环，失败响亮）
        seed = 0  # 随机种子（EXPAND_SEEDS 时递增，扩种 → 覆盖率变化）
        coverage_db_history = []  # 铁律 2：每轮覆盖率数据库版本固化记录
        prev_coverage = None       # 归因校准: 上一轮覆盖率
        last_action = None         # 归因校准: (action_type, reason, gap_reasons, unreachable_dims)
        for round_num in range(max_rounds):
            iterations += 1
            regress_data = await _run("ops", f"ops_r{round_num+1}", {"design_style": design_style})

            # 统一从 data["regression"] 取回归数据（ops 返回 {"regression": {...}}）
            regression = regress_data.get("regression", {}) \
                if isinstance(regress_data, dict) else {}

            # ── EDA 缺失检测（优先级最高：环境问题不是代码问题，终止闭环）──
            # 历史 bug：缺少 vlog/vsim 被决策层误判为"功能错 → REFACTOR_RTL"循环空转。
            # 现在显式标记并终止：BLOCKED_EDA_MISSING（失败响亮，给出安装指引）。
            if isinstance(regression, dict) and regression.get("eda_missing"):
                _eda_err = str(regression.get("error", ""))[:200]
                phases.append({"name": "eda_check", "status": "failed",
                               "reason": f"EDA 工具缺失: {_eda_err}"})
                logger.error(f"EDA 工具缺失，终止闭环（安装 QuestaSim 并加入 PATH 后重试）: {_eda_err}")
                eda_blocked = True
                break

            # ── 编译失败检测（优先级最高，编译不过后面全废）──
            compile_error = None
            if isinstance(regression, dict) and regression.get("compile") == "FAIL":
                try:
                    from src.layers.l1_infrastructure.compile_healer import CompileErrorAnalyzer
                    # 分析编译错误
                    stderr = regression.get("stderr", regression.get("compile_errors", ""))
                    cr = CompileErrorAnalyzer.analyze(str(stderr))
                    compile_error = {
                        "error_type": cr.error_type.value,
                        "message": cr.error_message,
                        "file": cr.error_file,
                        "line": cr.error_line,
                    }
                except Exception as e:
                    logger.warning(f"编译错误分析失败: {e}")

            # ── 回归门控：功能回归（不收集覆盖率）全部 pass 才进入 coverage ──
            # 决策：功能不正确（回归有失败）→ 收集覆盖率无意义，跳过 coverage 进 debug 修复
            failed = regression.get("failed", 0) if isinstance(regression, dict) else 0
            _cov_params = {"seed": seed, "round_num": round_num + 1}
            if failed and not compile_error:
                logger.info(f"功能回归 {failed} 失败 → 跳过 coverage，进入 debug 修复")
                cov_data = {}
                await _run("debug", f"debug_r{round_num+1}")
            elif compile_error:
                # 编译/elaboration 失败：跳过 coverage/debug（坏构建上再跑无意义），
                # 直接交由决策层 COMPILE_RETRY → CompileSelfHealer 自愈。
                logger.info(f"编译/elaboration 失败({compile_error.get('error_type','?')}) → 跳过 coverage，交由自愈器")
                cov_data = {}
            else:
                cov_data = await _run("coverage", f"coverage_r{round_num+1}", _cov_params)

            coverage = cov_data.get("coverage", {}) if isinstance(cov_data, dict) else {}
            gaps = cov_data.get("gaps", []) if isinstance(cov_data, dict) else []
            if isinstance(coverage, dict):
                final_coverage = coverage.get("overall_pct", coverage.get("coverage_pct", 0))
                if isinstance(final_coverage, str):
                    try: final_coverage = float(final_coverage)
                    except: final_coverage = 0.0
            # ── Exclude 四步闭环：自动发现 → 提议；已批准 → 有效覆盖率调规 ──
            coverage_map = cov_data.get("coverage_map", {}) if isinstance(cov_data, dict) else {}
            exclude_effect = {"excluded": 0, "effective_total": 0,
                              "effective_coverage": final_coverage}
            effective_coverage = final_coverage
            if isinstance(coverage_map, dict) and coverage_map.get("total"):
                calibration = cov_data.get("calibration", {}) if isinstance(cov_data, dict) else {}
                proposed = self._discover_excludes(exclude_reg, gaps, calibration)
                if proposed:
                    logger.info(f"Exclude 自动发现 {proposed} 处结构性不可达覆盖点，已提议（待审批）")
                exclude_effect = exclude_reg.effective_coverage_from_map(coverage_map)
                effective_coverage = exclude_effect.get("effective_coverage", final_coverage)
                if exclude_effect.get("excluded"):
                    logger.info(f"Exclude 调规：{exclude_effect['excluded']} 点已放弃，"
                                f"有效覆盖率 {effective_coverage}%（原始 {exclude_effect['raw_coverage']}%）")
            # ── 用例比例动态优化：覆盖率反馈 → 调 purpose 权重 → 影响下一轮优先级 ──
            try:
                _by_purpose = {
                    "functional": {"coverage": coverage.get("functional_pct", final_coverage),
                                   "sim_time": 0},
                    "protocol": {"coverage": coverage.get("branch_pct", 0), "sim_time": 0},
                    "corner": {"coverage": coverage.get("toggle_pct", 0), "sim_time": 0},
                }
                testcase_reg.optimize_portfolio({"by_purpose": _by_purpose}, round_num + 1)
            except Exception:
                pass
            # ── 归因校准: 上一轮决策动作的成效（delta 覆盖率为反馈信号）──
            if last_action is not None and prev_coverage is not None:
                try:
                    from src.layers.l4_memory.coverage_experience import get_coverage_experience_store
                    get_coverage_experience_store().record_round(
                        round_num + 1, last_action[0], last_action[1], last_action[2],
                        prev_coverage, final_coverage, last_action[3])
                    # 驾驭层：动作成效反馈到熔断器（覆盖率提升=成功，停滞=失败）
                    governor.after_action(last_action[0], success=(final_coverage > prev_coverage))
                except Exception as _e:
                    logger.warning(f"归因校准记录失败: {_e}")
            prev_coverage = final_coverage

            # ── Planning：进度对比里程碑 + 收敛预测 ──
            progress = planner.check_progress(round_num + 1, final_coverage)
            forecast = planner.predict_convergence(coverage_history)
            if not progress["on_track"]:
                logger.info(f"进度落后里程碑: {progress['coverage']}% vs 里程碑 {progress['milestone']}%"
                            f"（差距 {progress['gap']}%）")

            # 铁律 2：记录本轮覆盖率数据库（ucdb 哈希）+ 降采样汇总文件路径
            # 原始证据（仿真 log + VCD 波形）也记录进证据链（供人工检查 + 签核追溯）
            import hashlib as _hashlib
            _log_path = cov_data.get("log_path", "") if isinstance(cov_data, dict) else ""
            _vcd_path = cov_data.get("vcd_path", "") if isinstance(cov_data, dict) else ""
            def _file_sha(p):
                try:
                    return _hashlib.sha256(Path(p).read_bytes()).hexdigest()[:16] if p and Path(p).exists() else ""
                except Exception:
                    return ""
            coverage_db_history.append({
                "round": round_num + 1,
                "coverage_db": cov_data.get("coverage_db", {}) if isinstance(cov_data, dict) else {},
                "coverage_summary": cov_data.get("coverage_summary", "") if isinstance(cov_data, dict) else "",
                "coverage": final_coverage,
                "log_path": _log_path,
                "log_sha256": _file_sha(_log_path),
                "vcd_path": _vcd_path,
                "vcd_sha256": _file_sha(_vcd_path),
            })
            # 覆盖率数据库归档已由 L1 统一完成（CoverageCollectTool → infra.collect_coverage），
            # 此处不再手动 archive，避免与子进程归档重复。

            # 决策：按"有效覆盖率"判断（已批准的 Exclude 点从分母剔除，不再追不可达死代码）
            # 功能回归失败 → failed_tests 非空 → 决策层走 RETRY_ENV（环境自愈/重试），而非盲目补覆盖率
            _failed_tests = [f"functional_regress_r{round_num+1}"] if (failed and not compile_error) else []
            obs = Observation(
                iteration_id=round_num,
                coverage={"functional": effective_coverage},
                gaps=gaps,
                failed_tests=_failed_tests,
                coverage_history=coverage_history + [effective_coverage],
                compile_error=compile_error,
            )
            coverage_history.append(final_coverage)
            # 语义化：用 Verification Knowledge Graph 补 gap_paths（精准归因，非泛泛 generate test）
            try:
                from src.layers.l3_decision.decision_engine import enrich_observation
                _spec = ctx.get("spec", {}) if isinstance(ctx, dict) else {}
                if not _spec:
                    from pathlib import Path as _P
                    import json as _json
                    _sp = _P(output_root) / "spec.json"
                    if _sp.exists():
                        _spec = _json.loads(_sp.read_text(encoding="utf-8"))
                if _spec:
                    obs = await enrich_observation(obs, _spec)
            except Exception:
                pass
            # 事件驱动决策：发 COVERAGE_UPDATED（完整 Observation）→ DecisionReactor 决策 → 读结果
            if decision_reactor is not None:
                try:
                    from src.layers.l2_orchestration.communication.verification_events import publish_observation
                    await publish_observation(obs)
                    action = decision_reactor.last_action or engine.decide(obs)
                except Exception:
                    action = engine.decide(obs)
            else:
                action = engine.decide(obs)

            # ── 驾驭层：熔断 / 预算 / 干预 / 决策可干预 ──
            govern = governor.before_action(action.action_type)
            if not govern.allowed:
                if (govern.intervention
                        and govern.intervention.get("cmd") == "override_action"
                        and govern.intervention.get("action_type")):
                    # 人工 override：接管决策，强制指定动作
                    from src.layers.l3_decision.decision_engine import Action
                    action = Action(
                        action_type=govern.intervention["action_type"],
                        params={}, priority="HIGH",
                        reason=f"人工 override: {govern.reason}")
                    governor.intervention.clear()
                else:
                    # 熔断 / 预算耗尽 → 升级人工（人机协作，而非直接终止）
                    phases.append({"name": "governor", "status": "blocked",
                                   "reason": govern.reason})
                    logger.warning(f"驾驭层拦截: {govern.reason}")
                    decision = self._escalate_to_human(govern.reason, action.action_type)
                    if decision == "retry":
                        governor.breaker.reset(action.action_type)  # 人工放行，复位熔断
                        continue
                    else:
                        break  # abort / skip → 终止闭环

            # ── 审批门控：高风险动作（重构/改模型）前人工审批 ──
            if approval_gate and action.action_type in ("REFACTOR_RTL", "UPDATE_MODEL"):
                try:
                    from src.layers.l2_orchestration.governance.approval import ApprovalDecision
                    _decision = approval_gate.ask(action.action_type, action.reason,
                                                  risk_level="high")
                    if _decision == ApprovalDecision.REJECT:
                        phases.append({"name": "approval", "status": "rejected",
                                       "action": action.action_type})
                        logger.warning(f"人工审批拒绝: {action.action_type}")
                        break
                    elif _decision == ApprovalDecision.SKIP:
                        phases.append({"name": "approval", "status": "skipped",
                                       "action": action.action_type})
                        continue
                except Exception as e:
                    logger.warning(f"审批检查失败: {e}")

            phases.append({"name": "decision", "status": "decision",
                           "action": action.action_type, "reason": action.reason})

            # ── 归因校准: 记住本轮动作（供下一轮记录成效）──
            _gap_reasons = [g.get("reason") for g in gaps
                            if isinstance(g, dict) and g.get("reason")]
            _unreachable_dims = [g.get("dimension") for g in gaps
                                 if isinstance(g, dict) and g.get("reason") == "unreachable"
                                 and g.get("dimension")]
            last_action = (action.action_type, action.reason, _gap_reasons, _unreachable_dims)

            if action.action_type == "CONVERGE":
                _excl_note = (f"（有效覆盖率 {effective_coverage}%，Exclude {exclude_effect.get('excluded', 0)} 点）"
                              if exclude_effect.get("excluded") else "")
                logger.info(f"闭环收敛: 覆盖率 {final_coverage}% ≥ {target}%{_excl_note}")
                # 覆盖率首次达标 → 保存黄金基线（golden.tar.gz）
                try:
                    from src.layers.l1_infrastructure.golden_baseline import save_golden_baseline
                    golden_path = save_golden_baseline(
                        Path(output_root), {"functional": final_coverage}, target)
                    if golden_path:
                        logger.info(f"黄金基线已保存: {golden_path}")
                        phases.append({"name": "golden_baseline", "status": "saved",
                                       "path": golden_path})
                except Exception as e:
                    logger.warning(f"黄金基线保存失败: {e}")
                # 基础设施：版本固化（git tag + 版本清单）
                try:
                    infra.write_version_manifest({
                        "final_coverage": final_coverage,
                        "effective_coverage": effective_coverage,
                        "exclude_effect": exclude_effect,
                        "target": target,
                        "iterations": iterations,
                    })
                    tag_name = f"signoff_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                    tag_result = infra.git_tag(tag_name, f"coverage {final_coverage}%")
                    if tag_result.get("tagged"):
                        logger.info(f"版本已打 tag: {tag_name}")
                        phases.append({"name": "git_tag", "status": "tagged",
                                       "tag": tag_name})
                except Exception as e:
                    logger.warning(f"版本固化失败: {e}")
                break
            elif action.action_type == "COMPILE_RETRY":
                # 编译失败自愈
                compile_retries += 1
                from src.layers.l1_infrastructure.compile_healer import CompileSelfHealer
                healer = CompileSelfHealer(str(output_root))
                from src.layers.l1_infrastructure.compile_healer import CompileResult, CompileErrorType
                err = CompileResult(
                    success=False,
                    error_type=CompileErrorType(compile_error.get("error_type", "unknown")),
                    error_message=compile_error.get("message", ""),
                    error_file=compile_error.get("file"),
                    error_line=compile_error.get("line"),
                )
                heal = healer.heal(err)
                if heal["fixed"]:
                    logger.info(f"编译自愈({compile_retries}) 确定性修复: {heal['actions'][:2]}")
                    # 修复成功=进展，复位驾驭层熔断（否则连败 3 次会把自愈误判成失败熔断）
                    try:
                        governor.breaker.reset("COMPILE_RETRY")
                    except Exception:
                        pass
                else:
                    # 确定性修不了 → 交给 debug agent（LLM 重写出错文件，真修复 + 写回）
                    logger.info(f"确定性修复失败 → 交给 debug agent 修复 {compile_error.get('file','')}")
                    await _run("debug", f"debug_compile_r{compile_retries}",
                               {"compile_error": compile_error})
                if compile_retries >= 10:
                    logger.error(f"编译失败 10 次仍未修复: {compile_error.get('message','')}")
                    break
            elif action.action_type == "REFACTOR_RTL":
                # 回归守卫：改设计前强制跑 golden 用例集，<100% 拒绝本次修改
                try:
                    from src.layers.l1_infrastructure.golden_baseline import GuardianAgent
                    guardian = GuardianAgent(Path(output_root))
                    check = await guardian.pre_refactor_check()
                    if not check.get("allowed", False):
                        logger.warning(f"回归守卫拒绝设计修改: {check.get('reason')}")
                        phases.append({"name": "guardian", "status": "rejected",
                                       "reason": check.get("reason")})
                        break  # 破坏性变更被守卫拦截，终止闭环
                except Exception as e:
                    logger.warning(f"回归守卫检查失败: {e}")
                # 被动触发: 设计重构 → 改 design + 自动更新 model
                await _run("design", "design_fix", {"fix_agent": "rtl"})
                logger.info("设计重构 → 被动通知 model 更新（版本 +1）")
                await _run("model", "model_update", {"action": "update",
                                                     "reason": action.reason})
            elif action.action_type == "UPDATE_MODEL":
                # 主动触发: 比对失败 → 更新参考模型
                logger.info(f"比对失败 → 主动更新 model: {action.reason}")
                await _run("model", "model_diagnose", {"action": "update",
                                                       "reason": action.reason})
            elif action.action_type == "GENERATE_DIRECTED_TEST":
                # 按 gap 生成定向激励（不再是空骨架）
                await _run("verify", "verify_supplement",
                           {"supplement": True, "gaps": action.params.get("gaps", [])})
            elif action.action_type == "RELAX_CONSTRAINT":
                # 放宽约束：文本级修改 transaction 约束，下一轮重新编译仿真
                self._relax_transaction_constraints(output_root, action.params.get("gaps", []))
                logger.info(f"放宽约束: {action.reason}")
            elif action.action_type == "EXPAND_SEEDS":
                # 扩种：递增随机种子，下一轮 coverage 用新种子 → 覆盖率变化
                seed += int(action.params.get("count", 100)) if isinstance(action.params, dict) else 100
                logger.info(f"扩种 → seed={seed}（覆盖率停滞，尝试新随机激励）")

        # ── 签核 ──
        await _run("audit", "audit")

        # ── 审计证据链: 落盘 + 完整性校验 ──
        evidence_path = ""
        manifest_path = ""
        chain_valid = False
        total_changes = 0
        if file_audit is not None:
            try:
                chain = file_audit.to_dict()
                chain["chain_valid"] = file_audit.verify()
                chain_valid = chain["chain_valid"]
                total_changes = chain.get("total_changes", 0)
                docs_dir = Path(output_root) / "docs"
                docs_dir.mkdir(parents=True, exist_ok=True)
                evidence_path = str(docs_dir / "evidence_chain.json")
                Path(evidence_path).write_text(
                    json.dumps(chain, indent=2, ensure_ascii=False, default=str),
                    encoding="utf-8")
            except Exception as e:
                logger.warning(f"证据链落盘失败: {e}")

        # ── Manifest: 运行清单（输入/输出/决策/证据摘要 + 覆盖率版本固化）──
        try:
            docs_dir = Path(output_root) / "docs"
            docs_dir.mkdir(parents=True, exist_ok=True)
            # 铁律 2：RTL 代码哈希（连同覆盖率数据库一起固化版本）
            import hashlib
            rtl_hashes = {}
            rtl_dir = Path(output_root) / "rtl"
            if rtl_dir.exists():
                for sv in sorted(rtl_dir.glob("*.sv")):
                    rtl_hashes[sv.name] = hashlib.sha256(
                        sv.read_bytes()).hexdigest()[:16]
            manifest = {
                "architecture": "closed_loop_7agents",
                "target": target,
                "final_coverage": final_coverage,
                "effective_coverage": effective_coverage,
                "converged": effective_coverage >= target,
                "iterations": iterations,
                "phases": phases,
                "planning": {
                    "target": planner.target,
                    "milestones": planner.milestones,
                    "convergence_forecast": planner.predict_convergence(coverage_history),
                },
                "testcase_portfolio": testcase_reg.get_portfolio(),
                "testcase_stats": testcase_reg.get_stats(),
                "exclude": {
                    "stats": exclude_reg.stats(),
                    "effect": exclude_effect,
                    "approved_points": sorted(exclude_reg.get_excluded_points()),
                },
                "rtl_hashes": rtl_hashes,
                "coverage_db_history": coverage_db_history,
                # ── 可复现性（铁律补充）：记录本 run 的 LLM 调用审计 ──
                # prompt_hash = LLMQueryEngine 的 cache_key（prompt 内容的 SHA256 前缀），
                # 同一 prompt 再次调用可命中缓存/复现；历史缺口：manifest 不含 LLM I/O，
                # "vagent dump 复现" 无法追溯模型输入。
                "llm_audit": _collect_llm_audit(),
                "evidence": {
                    "total_changes": total_changes,
                    "chain_valid": chain_valid,
                    "evidence_path": evidence_path,
                },
            }
            manifest_path = str(docs_dir / "manifest.json")
            Path(manifest_path).write_text(
                json.dumps(manifest, indent=2, ensure_ascii=False, default=str),
                encoding="utf-8")
        except Exception as e:
            logger.warning(f"Manifest 落盘失败: {e}")

        # 汇总 Exclude 状态后释放 sqlite 连接（Windows 文件锁：跨 run 持久数据读完及时 close）
        exclude_stats = exclude_reg.stats()
        try:
            exclude_reg.close()
        except Exception:
            pass

        # 补齐 CLI 兼容字段（vagent verify 的返回结构需要这些）
        _passed = sum(1 for p in phases if p.get("status") == "passed")
        _total = len(phases)
        _run_id = f"run_{Path(output_root).name.split('_')[-1] if '_' in Path(output_root).name else 'closed_loop'}"

        return {
            "architecture": "closed_loop_7agents",
            "run_id": _run_id,
            "output_root": str(output_root),
            "phases": phases,
            "passed": _passed,
            "total": _total,
            "overall_score": round(effective_coverage, 1) if effective_coverage else 0,
            "final_coverage": final_coverage,
            "effective_coverage": effective_coverage,
            "converged": effective_coverage >= target,
            "eda_blocked": eda_blocked,
            "target": target,
            "iterations": iterations,
            "exclude": {"stats": exclude_stats, "effect": exclude_effect},
            "status": ("BLOCKED_EDA_MISSING" if eda_blocked
                       else ("CONVERGED" if effective_coverage >= target else "COMPLETED")),
            "evidence": {
                "total_changes": total_changes,
                "chain_valid": chain_valid,
                "evidence_path": evidence_path,
                "manifest_path": manifest_path,
            },
        }

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
