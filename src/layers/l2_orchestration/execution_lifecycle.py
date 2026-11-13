"""
Pipeline 执行服务 —— CLI 和 Web API 共享的验证流水线引擎

单例模式，管理 Agent 生命周期 + 流水线执行 + 运行状态追踪。
"""
from __future__ import annotations
import time, json, uuid, asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime
import structlog

from src.layers.l1_infrastructure.output_config import make_output_root
from src.layers.l2_orchestration.regression_tools import sim_modes as _sim_modes

from src.layers.l2_orchestration.executors.registry import ExecutorRegistry
from config.settings import Settings


from .execution_helpers import (
    _new_executor,
    _collect_llm_audit,
    _field,
    _round_of,
    _coverage_of,
    _result_of,
    _mirror_event,
    _translate_debug,
    _wire_approval_events,
    _translate_custom,
    _resolve_run_dir,
    _safe_checkpointer,
    _state_of,
    _interrupt_payload,
    _EXECUTOR_PATHS,
    logger,
)


class RunLifecycleSteps:
    async def initialize_agents(self) -> None:
        """初始化所有 12 个 Agent（幂等）"""
        if self._initialized:
            return

        agents = [(role, _new_executor(role)) for role in _EXECUTOR_PATHS]
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
        recorded = 0
        for fpath in files[:10]:  # 最多记录 10 个文件
            try:
                file_audit.record(str(fpath), reason or f"{role} 产出", role)
                recorded += 1
            except Exception:
                pass
        # **增量落盘**：每跑完一个 agent 就把链刷到磁盘。原先只在最后
        # （n_finalize）落一次，中途失败/中断的 run 在 docs/ 下没有任何审计证据
        # —— 而失败时才是审计最有用的时刻。见 FileAuditTrail.save_default。
        if recorded:
            file_audit.save_default()

    @staticmethod
    def _discover_excludes(exclude_reg, gaps: list, calibration: dict = None) -> int:
        """Exclude 四步闭环·第 1 步（自动发现）：结构性不可达覆盖点 → 提议放弃。

        归因分类（第 2 步）：coverage Agent 已在归因校准阶段把"多次 refactor 仍 0%"的
        unreachable 点筛入 `calibration.blacklisted_gaps`——这些点就是结构性死代码，
        直接提议 TYPE_UNREACHABLE。"规格不测/成本高"由工程师经 CLI 手动提议。
        返回本次提议数量。
        """
        try:
            from src.knowledge.exclude_registry import TYPE_UNREACHABLE
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

    def _register_run(self, run_id: str, output_root: str, spec_text: str = "") -> None:
        """把一次运行登记进内存表 —— 让 `watch` / `history` 的实时分支活过来。

        此前 `_runs` **从未被任何执行路径填充**（`get_run_status` 因此恒返回
        None），CLI 的 `watch` 只能退化到读 DB。内存表只是**加速**：
        唯一可靠来源仍然是 output 目录（见 run_repository 模块头）。
        """
        self._runs[run_id] = {
            "run_id": run_id,
            "workflow": "closed_loop_7agents",
            "state": "running",
            "current_phase": "",
            "phases": [],
            "spec": (spec_text or "")[:200],
            "output_root": str(output_root),
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "completed_at": "",
        }

    def _touch_run(self, run_id: str, phase: str = "") -> None:
        run = self._runs.get(run_id)
        if run and phase:
            run["current_phase"] = phase

    def _close_run(self, run_id: str, result: dict,
                   error: Optional[BaseException] = None,
                   cancelled: bool = False,
                   interrupted: bool = False) -> None:
        """收尾内存表。失败 / 取消 / **暂停**都要落地 —— 状态停在 running 是误导。"""
        run = self._runs.get(run_id)
        if run is None:
            return
        if error is not None:
            run["state"] = "failed"
        elif cancelled:
            run["state"] = "cancelled"
        elif interrupted:
            # "等人" 不是"跑完了"：界面据此显示审批条而不是终态
            run["state"] = "waiting"
        else:
            run["state"] = "completed"
        run["completed_at"] = datetime.now().isoformat(timespec="seconds")
        run["phases"] = list(result.get("phases", []) or [])
        run["passed"] = result.get("passed", 0)
        run["total"] = result.get("total", 0)
        run["overall_score"] = result.get("overall_score", 0)
        run["scores"] = result.get("scores", {}) or {}
        run["governance"] = result.get("governance", {}) or {}
        if result.get("final_coverage") is not None:
            run["final_coverage"] = result.get("final_coverage")

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

