"""
根因追踪器 — 多跳因果推理 + 自动修复

Phase 1: Collect — 仿真日志 + 编译日志 + 波形
Phase 2: Classify — 12 类精细分类 + 指纹去重
Phase 3: Locate — 分类路由 + bisect 定位
Phase 4: Fix — auto_fix 模板匹配 → 应用 patch
Phase 5: Verify — 重跑失败 case 验证修复
"""
from typing import Dict, List, Any
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder

from src.core.base import BaseAgent, AgentResult
from src.core.registry import register_agent
from src.tools.debug_tools.main import (
    DebugTools, _classify_error, _fingerprint,
    collect_sim_log, collect_compile_log,
    bisect_test, auto_fix, rerun_failed_test,
    fingerprint_error,
)
import structlog, json, re
from pathlib import Path

logger = structlog.get_logger()


@register_agent("debug")
class DebugAgent(BaseAgent):
    """根因追踪器 — 假设→验证→排除→确认 多轮迭代"""

    task_type = "debug_analysis"
    consumes = ["regression", "tests", "env"]
    produces = "debug"

    MAX_HYPOTHESIS_ROUNDS = 3

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(
            role="debug", display_name="调试工程师",
            description="多跳因果推理：收集→分类→定位→修复→验证",
            config=config or {})
        self.debug_tools = DebugTools()
        self.min_score = 30

    async def _setup(self):
        logger.info(f"{self.display_name} 初始化完成 (real tools + hypothesis loop)")

    async def _get_prompt_template(self):
        return ChatPromptTemplate.from_messages([
            ("system", """你是 IC 验证调试专家。收到错误分类和上下文后：

1. 阅读错误分类结果 + 上下文
2. 提出根因假设: "Root cause is X because Y"
3. 如 auto_fix 未匹配 → 手动给出修复代码 (diff 格式)
4. 如 auto_fix 已应用 → 判断修复是否正确

输出 JSON:
{
  "hypothesis": "string — root cause explanation",
  "confidence": 0-100,
  "suggested_fix": "string — diff or description",
  "need_manual_review": true/false
}"""),
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad")
        ])

    async def _get_tools(self) -> List:
        return self.debug_tools.get_tools()

    async def _execute(self, input_text: str) -> Dict[str, Any]:
        if self._executor:
            return await self._executor.ainvoke({"input": input_text})
        return {"output": "Agent未初始化"}

    # ═══════════════════════════════════════════════════════════
    # 主执行入口
    # ═══════════════════════════════════════════════════════════

    async def execute_task(self, task: Dict[str, Any]) -> AgentResult:
        """增强执行：收集→分类→定位→修复→验证 五阶段管线。"""
        ctx = task.get("ctx", {})
        output_dir = task.get("output_dir", "output")
        od = Path(output_dir)

        # ── Phase 1: Collect ──
        sim_result = json.loads(collect_sim_log(output_dir))
        compile_result = json.loads(collect_compile_log(output_dir))

        all_errors = []
        for log_entry in sim_result.get("errors", []):
            all_errors.extend(log_entry.get("errors", []))
        for entry in compile_result.get("errors", []):
            all_errors.append({
                "message": entry.get("message", ""),
                "file": entry.get("file", ""),
                "line": entry.get("line", 0),
                "fingerprint": entry.get("fingerprint", ""),
                "severity": entry.get("severity", "error"),
            })

        if not all_errors:
            return AgentResult(success=True, data={
                "debug": {"status": "clean", "message": "No errors found"},
                "score": 95,
            })

        # ── Phase 2: Classify + Fingerprint ──
        classified = []
        for err in all_errors:
            msg = err.get("message", str(err))
            fp = err.get("fingerprint", "") or _fingerprint(msg)
            classification = _classify_error(msg) if msg else {"category": "unknown"}
            classified.append({
                **err,
                "fingerprint": fp,
                "classification": classification,
            })

        # 按 fingerprint 去重
        unique = {}
        for err in classified:
            fp = err["fingerprint"]
            if fp not in unique:
                unique[fp] = err

        # ── Phase 3: Locate (bisect if multiple unique failures) ──
        by_category = {}
        for fp, err in unique.items():
            cat = err["classification"]["category"]
            by_category.setdefault(cat, []).append(err)

        bisect_data = {}
        if len(unique) > 2:
            failed_names = [f"{e.get('file', '')}:{e.get('line', 0)}" for e in unique.values()]
            bisect_data = json.loads(
                bisect_test(json.dumps({"output_dir": output_dir, "failed_tests": failed_names}))
            )

        # ── Phase 4: Fix ──
        fixes_applied = []
        for fp, err in list(unique.items())[:5]:  # 最多修 5 个独立错误
            msg = err.get("message", "")
            fix_result = json.loads(
                auto_fix(json.dumps({"error_text": msg, "output_dir": output_dir}))
            )
            if fix_result.get("matched") and fix_result.get("patch_applied"):
                fixes_applied.append({
                    "fingerprint": fp,
                    "error": msg[:150],
                    "fix_name": fix_result.get("fix_name"),
                    "file_modified": fix_result.get("file_modified"),
                })

        # ── Phase 5: Verify (rerun if fixes applied) ──
        verified = []
        for fix_entry in fixes_applied:
            # 尝试找到关联的 test
            for log_entry in sim_result.get("errors", []):
                for e in log_entry.get("errors", []):
                    if e.get("fingerprint") == fix_entry["fingerprint"]:
                        test_name = log_entry["log_file"].replace("sim_", "").replace(".log", "")
                        rerun = json.loads(
                            rerun_failed_test(json.dumps({"output_dir": output_dir, "test_name": test_name}))
                        )
                        verified.append({"test": test_name, "fix": fix_entry["fix_name"],
                                         "status": rerun.get("status")})

        # ── 构建 debug report ──
        error_summary = {
            "total_errors": len(all_errors),
            "unique_errors": len(unique),
            "categories": {cat: len(errs) for cat, errs in by_category.items()},
            "common_category": max(by_category, key=lambda k: len(by_category[k])) if by_category else "none",
        }

        fix_summary = {
            "applied": len(fixes_applied),
            "verified": sum(1 for v in verified if v.get("status") == "PASS"),
            "failed": sum(1 for v in verified if v.get("status") != "PASS"),
        }

        debug_result = {
            "phase": {"collect": "done", "classify": "done", "locate": "done",
                      "fix": f"{fix_summary['applied']} applied", "verify": f"{fix_summary['verified']} passed"},
            "error_summary": error_summary,
            "by_category": by_category,
            "bisect": bisect_data,
            "fixes": fixes_applied,
            "verified": verified,
        }

        # ── Phase 6: LLM 深度分析（可选） ──
        need_llm = (fix_summary["applied"] == 0 and error_summary["unique_errors"] > 0)
        llm_analysis = {}

        if need_llm:
            task["input"] = json.dumps({
                "analyze_failures": True,
                "error_summary": error_summary,
                "top_errors": [{"msg": e["message"][:200], "category": e["classification"]["category"]}
                               for e in list(unique.values())[:3]],
                "fix": True,
            }, ensure_ascii=False)
            try:
                llm_result = await super().execute_task(task)
                if llm_result.success and isinstance(llm_result.data, dict):
                    llm_analysis = {"llm_hypothesis": llm_result.data.get("output", "")[:1000]}
            except Exception:
                pass

        debug_result["llm_analysis"] = llm_analysis

        # ── 写入 ctx 黑板书 ──
        if hasattr(ctx, 'put'):
            ctx.put("debug", debug_result, source="debug_agent")
        elif isinstance(ctx, dict):
            ctx["debug"] = debug_result

        # 评分
        base = 60
        if fix_summary["applied"] > 0:
            base += 15
        if fix_summary["verified"] > 0:
            base += 10
        if error_summary["unique_errors"] <= 3:
            base += 10
        score = min(base, 95)

        return AgentResult(success=True, data={"debug": debug_result, "score": score})
