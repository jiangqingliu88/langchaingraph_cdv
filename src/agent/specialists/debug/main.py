"""
根因追踪器 — 多跳因果推理 + 自动修复

Phase 1: Collect — 仿真日志 + 编译日志 + 波形
Phase 2: Classify — 12 类精细分类 + 指纹去重
Phase 3: Locate — 分类路由 + bisect 定位
Phase 4: Fix — auto_fix 模板匹配 → 应用 patch
Phase 5: Verify — 重跑失败 case 验证修复
"""
from typing import Dict, List, Any
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from src.layers.l2_orchestration.executors.base import BaseExecutor, ExecutorResult
from src.layers.l2_orchestration.executors.registry import register_executor
# 工具统一入口：走 ToolHub 的 schema 校验 + 审计回执，
# 而不是绕过 hub 直接 import 工具函数（见 call_tool 的 docstring）
from src.layers.l2_orchestration.communication.tool_hub import call_tool
from src.engine.diagnostics.main import (
    DebugTools, _classify_error, _fingerprint, fingerprint_error,
)
import asyncio, structlog, json, re
from pathlib import Path

logger = structlog.get_logger()


@register_executor("debug")
class DebugExecutor(BaseExecutor):
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
{{
  "hypothesis": "string — root cause explanation",
  "confidence": 0-100,
  "suggested_fix": "string — diff or description",
  "need_manual_review": true/false
}}"""),
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad")
        ])

    async def _get_tools(self) -> List:
        return self.debug_tools.get_tools()

    async def _execute(self, input_text: str) -> Dict[str, Any]:
        return {"output": await self._llm_analyze(input_text)}

    async def _llm_analyze(self, input_text: str) -> str:
        """调 LLM 做根因分析 —— **经集中式 Query Engine**。

        原先 Phase 6 走 `BaseExecutor.execute_task` 的 AgentExecutor 分支 —— 那是
        全仓唯一一处 AgentExecutor 用法（实测 2026-10-09：8 个 executor 里只有
        debug 的 `_executor` 被构造过）。但它挂的 7 个工具与本 agent 的五阶段
        管线**重复**：管线里已经用 `call_tool` 调过 collect_sim_log、
        fingerprint_error、bisect_failed_tests；而 prompt 只要求输出 JSON、
        不要求调工具。直连更简单，也不再依赖 langchain_classic。

        **为什么走 query_engine 而不是直接 `self.llm.ainvoke`**：
        直连时这次调用的 token 不计预算、不进审计 —— 而它正是"每轮只要还有
        未归类的错误就调一次"的那条路径，最容易在收敛不了时反复触发。
        `_llm_analyze` 是 async 而 engine 的 `query` 是同步的，所以过一层线程。
        """
        if not self.llm_available:
            return ""
        prompt = await self._get_prompt_template()
        if prompt is None:
            return ""
        try:
            msgs = await prompt.aformat_messages(
                chat_history=[], input=input_text, agent_scratchpad=[])
            # LangChain 的 role 名（human/ai）→ OpenAI 报文里的（user/assistant）
            _role = {"human": "user", "ai": "assistant"}
            payload = [{"role": _role.get(m.type, m.type),
                        "content": str(m.content)} for m in msgs]

            from src.layers.l2_orchestration.context.query_engine import (
                LLMQueryEngine,
            )
            # `site` 要自己给：这条**不经过 `lib.llm_call.call_llm`**（直连 engine），
            # 而那句"唯一漏斗"的算术只在漏斗里自动取调用点。不给的话审计记录的
            # 出处恒为空 —— 实测 15 条里 5 条是空的，全是这一条路。
            from src.tools.common.lib.llm_call import TEXT_SCHEMA, caller_site

            return await asyncio.to_thread(
                LLMQueryEngine.get_instance().query,
                self.task_type, payload, input_text, site=caller_site(),
                output_schema=TEXT_SCHEMA, output_format="text",
                prompt_version="debug-rootcause-v1",
                failure_policy="fallback") or ""
        except Exception as e:                      # noqa: BLE001
            logger.warning(f"LLM 根因分析失败: {e}")
            return ""

    # ═══════════════════════════════════════════════════════════
    # 主执行入口
    # ═══════════════════════════════════════════════════════════

    async def execute_task(self, task: Dict[str, Any]) -> ExecutorResult:
        """增强执行：收集→分类→定位→修复→验证 五阶段管线。"""
        ctx = task.get("ctx", {})
        output_dir = task.get("output_dir", "output")
        od = Path(output_dir)

        # ── Phase 0: EDA 可用性检查（失败响亮：没有 EDA 工具就没有任何诊断证据）──
        # 历史 bug：EDA 缺失导致无日志 → "No errors found" 95 分假通过。
        # 现在必须先确认 EDA 可用，否则返回 EDA_MISSING（score 0，success=False）。
        import shutil
        eda_found = [t for t in ("vlog", "vsim") if shutil.which(t)]
        if not eda_found:
            return ExecutorResult(success=False, data={
                "debug": {
                    "status": "EDA_MISSING",
                    "message": "未检测到 EDA 工具（vlog/vsim）。无法执行编译仿真，也就没有任何诊断证据。"
                               "请安装 QuestaSim 并加入 PATH，或在 .env 中配置 EDA 路径。",
                    "eda_tools_found": eda_found,
                },
                "score": 0,
            })

        # ── 编译/elaboration 错误定向修复：编排层把 compile_error 传进来，直接 LLM 重写出错文件 ──
        _params = task.get("params", {}) if isinstance(task.get("params"), dict) else {}
        _ce = _params.get("compile_error") if isinstance(_params.get("compile_error"), dict) else None
        if _ce:
            _fname = _ce.get("file", "")
            _msg = _ce.get("message", "")
            _fixed = self._llm_regenerate_file(str(od), _fname, _msg) if _fname else False
            logger.info(f"debug 编译错误定向修复: file={_fname} fixed={_fixed}")
            # 修复未成功 → 如实失败（success=False），由编排层决定是否重试/终止
            return ExecutorResult(success=_fixed, data={
                "debug": {"compile_fix": {"file": _fname, "fixed": _fixed,
                                          "message": _msg[:150]}},
                "score": 85 if _fixed else 20,
            })

        # ── Phase 1: Collect ──
        # 经 `call_tool` 调（而不是直接 import 函数）：走 ToolHub 的 schema 校验 +
        # 审计回执。注意 schema 声明 output_dir 是 string，传 Path 会被拒，故 str()。
        sim_result = json.loads(call_tool("collect_sim_log", {"output_dir": str(output_dir)}))
        compile_result = json.loads(call_tool("collect_compile_log", {"output_dir": str(output_dir)}))

        all_errors = []
        for log_entry in sim_result.get("errors", []):
            # **带上 log_file**：它是"这条错误属于哪条用例"的唯一线索 —— 靠它才能
            # 反查到那条用例目录、进而找到它的波形（见 `_find_case_wave`）。
            # 摊平时丢掉它，下面的波形诊断就无从下手。
            log_file = log_entry.get("log_file", "")
            for e in log_entry.get("errors", []):
                all_errors.append({**e, "log_file": log_file})
        for entry in compile_result.get("errors", []):
            all_errors.append({
                "message": entry.get("message", ""),
                "file": entry.get("file", ""),
                "line": entry.get("line", 0),
                "fingerprint": entry.get("fingerprint", ""),
                "severity": entry.get("severity", "error"),
            })

        if not all_errors:
            # 区分 clean 与 NO_EVIDENCE（历史 bug：无日志 = "No errors found" 95 分）
            # clean 的前提是"EDA 跑了且日志里确实没有错误"；
            # 没有任何仿真/编译日志 → 无法诊断 → NO_EVIDENCE（score 0，success=False）。
            logs_exist = (sim_result.get("logs_scanned", 0) > 0
                          or compile_result.get("logs_scanned", 0) > 0)
            if not logs_exist:
                return ExecutorResult(success=False, data={
                    "debug": {
                        "status": "NO_EVIDENCE",
                        "message": "未找到任何仿真/编译日志，无法诊断"
                                   "（可能是回归未执行、提前失败或日志路径异常）。",
                        "sim_logs_scanned": sim_result.get("logs_scanned", 0),
                        "compile_logs_scanned": compile_result.get("logs_scanned", 0),
                    },
                    "score": 0,
                })
            return ExecutorResult(success=True, data={
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

        # ── Phase 2.5: 信号级诊断（对 mismatch 类错误，证据矩阵分类替代正则甩 model）──
        signal_diagnosis = self._run_signal_diagnosis(
            output_dir, [e for e in unique.values()
                         if e["classification"]["category"] in ("model_mismatch", "unknown")])

        # ── Phase 3: Locate（多个独立失败时，缩小失败用例范围）──
        # 注意 `bisect_failed_tests` 只在**失败用例集合**里分批，不做代码版本
        # 溯源（不碰 git/change-list）—— 见该工具 docstring。
        by_category = {}
        for fp, err in unique.items():
            cat = err["classification"]["category"]
            by_category.setdefault(cat, []).append(err)

        bisect_data = {}
        if len(unique) > 2:
            failed_names = [f"{e.get('file', '')}:{e.get('line', 0)}" for e in unique.values()]
            bisect_data = json.loads(call_tool("bisect_failed_tests", {
                "input_json": json.dumps({"output_dir": str(output_dir),
                                          "failed_tests": failed_names})}))

        # ── Phase 3.5: 经验库命中（debug 成长：记忆复用 + 教训升级）──
        from src.knowledge.debug_experience import get_debug_experience_store
        experience = get_debug_experience_store()
        _reused_fps = {}      # fp -> experience（已验证修复，直接复用）
        _escalated_fps = {}   # fp -> experience（验证失败的修复，升级人工）
        for _fp in unique:
            _exp = experience.lookup(_fp)
            if not _exp:
                continue
            if _exp["confidence"] >= 0.8:
                _reused_fps[_fp] = _exp
            else:
                _escalated_fps[_fp] = _exp

        # ── Phase 4: Fix ──
        fixes_applied = []
        manual_review = []
        for fp, err in list(unique.items())[:5]:  # 最多修 5 个独立错误
            msg = err.get("message", "")

            # ── 成长: 已验证失败的修复 → 升级人工，不盲目重试 ──
            if fp in _escalated_fps:
                manual_review.append({
                    "fingerprint": fp, "error": msg[:150],
                    "reason": f"历史修复失败 {_escalated_fps[fp]['fail_count']} 次，升级人工",
                })
                continue

            # ── 成长: 已验证通过的修复 → 复用（仍走 EDA 重验，跳过分析）──
            _source = "experience_reuse" if fp in _reused_fps else "template"
            fix_result = json.loads(call_tool("auto_fix", {
                "input_json": json.dumps({"error_text": msg,
                                          "output_dir": str(output_dir)})}))
            if fix_result.get("matched"):
                # 记忆: 记录 fingerprint → fix_name（供下次命中复用）
                experience.record(
                    fp,
                    category=err["classification"]["category"],
                    root_cause="",
                    fix_name=fix_result.get("fix_name", ""),
                    fix_patch="",
                )
                if fix_result.get("patch_applied"):
                    fixes_applied.append({
                        "fingerprint": fp,
                        "error": msg[:150],
                        "fix_name": fix_result.get("fix_name"),
                        "file_modified": fix_result.get("file_modified"),
                        "source": _source,
                    })
            else:
                # ── LLM 兜底：模板无匹配 → call_llm 重写出错文件（真修复 + 写回，不是只记假设）──
                _fname = err.get("file", "")
                if _fname and self._llm_regenerate_file(output_dir, _fname, msg):
                    fixes_applied.append({
                        "fingerprint": fp,
                        "error": msg[:150],
                        "fix_name": "llm_regenerate",
                        "file_modified": _fname,
                        "source": "llm",
                    })
                    experience.record(
                        fp, category=err["classification"]["category"],
                        root_cause="", fix_name="llm_regenerate", fix_patch="")

        # ── Phase 5: Verify (rerun if fixes applied) ──
        verified = []
        for fix_entry in fixes_applied:
            # 尝试找到关联的 test
            for log_entry in sim_result.get("errors", []):
                for e in log_entry.get("errors", []):
                    if e.get("fingerprint") == fix_entry["fingerprint"]:
                        test_name = log_entry["log_file"].replace("sim_", "").replace(".log", "")
                        rerun = json.loads(call_tool("rerun_failed_test", {
                            "input_json": json.dumps({"output_dir": str(output_dir),
                                                      "test_name": test_name})}))
                        passed = rerun.get("status") == "PASS"
                        # ── 成长: 把 PASS/FAIL 写回经验库，校准 confidence ──
                        experience.record_result(fix_entry["fingerprint"], passed)
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

        # ── V2 Knowledge Graph：bug/fix 落库（跨 run 沉淀，供图溯源）──
        try:
            from src.layers.l3_decision.knowledge.persistence import record_bugs_and_fixes
            _bugs = []
            for _fp, _err in unique.items():
                _bugs.append({
                    "bug_id": _fp,
                    "description": _err.get("message", "")[:200],
                    "affected_signal": "",   # 从消息/文件提取，暂空
                    "affected_feature": (_err.get("classification") or {}).get("category", ""),
                    "severity": _err.get("severity", "error"),
                })
            _fixes = [{"bug_id": f["fingerprint"], "fix_id": f.get("fix_name", ""),
                       "description": f.get("error", "")[:200]} for f in fixes_applied]
            # **血缘**：这批 bug 是在 RTL 的哪一版上发现的。取不到就不带
            # （`record_bugs_and_fixes` 会跳过链接）—— 不编一个版本号出来。
            _rtl_mod, _rtl_v = "", None
            try:
                from src.knowledge.lineage import ensure_run_rtl_version
                _rv = ensure_run_rtl_version(od, run_id=str(od.name))
                _rtl_mod = _rv.get("module", "")
                _rtl_v = _rv.get("version_no")
            except Exception as _e:                    # noqa: BLE001 血缘不该阻断调试
                logger.warning(f"血缘：RTL 版本取不到（bug 将不带版本）: {_e}")
            await record_bugs_and_fixes(_bugs, _fixes, run_id=str(od.name),
                                        module=_rtl_mod, rtl_version_no=_rtl_v)
            logger.info(f"bug/fix 落库: {len(_bugs)} bug, {len(_fixes)} fix"
                        + (f"（RTL {_rtl_mod} v{_rtl_v}）" if _rtl_v else ""))
        except Exception as e:
            logger.warning(f"bug/fix 落库失败: {e}")

        # ── Event Bus：发布 BUG_DETECTED（异步通知订阅者：KG / 决策 / 其它 Agent）──
        try:
            from src.layers.l2_orchestration.communication.verification_events import publish_bug_detected
            for _fp, _err in list(unique.items())[:5]:
                await publish_bug_detected(
                    signature=_fp,
                    signal="",
                    category=(_err.get("classification") or {}).get("category", ""),
                )
        except Exception as e:
            logger.warning(f"发布 BUG_DETECTED 失败: {e}")

        debug_result = {
            "phase": {"collect": "done", "classify": "done", "locate": "done",
                      "fix": f"{fix_summary['applied']} applied", "verify": f"{fix_summary['verified']} passed"},
            "error_summary": error_summary,
            "by_category": by_category,
            "bisect": bisect_data,
            "fixes": fixes_applied,
            "verified": verified,
            "signal_diagnosis": signal_diagnosis,
            "growth": {
                "reused": len(_reused_fps),
                "escalated_to_manual": len(manual_review),
                "manual_review": manual_review,
                "recorded": len(fixes_applied),
                "experience_total": experience.stats()["total"],
            },
        }

        # ── Phase 6: LLM 深度分析 ──
        # **只要还有错误就必须叫 LLM** —— 不能用"自动修复模板一个都没应用"当开关。
        # 模板命中只说明"这条错误的**表象**见过"（套一个通用补丁），**不等于根因查清**；
        # 用 `applied == 0` 当条件，会让"模板一命中就再也没有 LLM 分析" ——
        # 而恰恰是这些命中得最顺手的错误最需要 LLM 说清根因。
        # 实测：loopback 的 SCB mismatch 走 `auto_fix` 命中后 `llm_analysis` 恒为空，
        # 于是根因分析整个缺位（不是 LLM 没能力，是根本没调它）。
        need_llm = error_summary["unique_errors"] > 0
        llm_analysis = {}

        if need_llm:
            task["input"] = json.dumps({
                "analyze_failures": True,
                "error_summary": error_summary,
                "top_errors": [{"msg": e["message"][:200], "category": e["classification"]["category"]}
                               for e in list(unique.values())[:3]],
                "fix": True,
            }, ensure_ascii=False)
            # 直连 LLM —— 不再经 `super().execute_task()` 的 AgentExecutor。
            # `_llm_analyze` 内部吞异常并返回空串，所以这里不需要 try/except。
            _hypothesis = await self._llm_analyze(task["input"])
            if _hypothesis:
                llm_analysis = {"llm_hypothesis": _hypothesis[:1000]}

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

        # ── 自动修复统计落盘（签核证据要能回答"修了几条、几条真过了"）──
        #
        # 不只看 "applied"：模板命中不等于修好。真正有意义的是
        # verified/applied 与问题类型的分布 —— 它们也是下一轮经验库校准的输入。
        try:
            _od = Path(str(output_dir))
            _stats = {
                "schema": "debug_autofix_stats_v1",
                "run": _od.name,
                "error_summary": error_summary,
                "fix_summary": {
                    **fix_summary,
                    "verified_pct": round(
                        100.0 * fix_summary["verified"] / fix_summary["applied"], 2)
                    if fix_summary["applied"] else 0.0,
                },
                "growth": debug_result.get("growth") or {},
                "llm_analysis_present": bool(llm_analysis),
                "manual_review": manual_review,
            }
            (_od / "docs").mkdir(parents=True, exist_ok=True)
            (_od / "docs" / "debug_stats.json").write_text(
                json.dumps(_stats, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as e:
            logger.warning(f"debug 自动修复统计落盘失败: {e}")

        return ExecutorResult(success=True, data={"debug": debug_result, "score": score})

    # ═══════════════════════════════════════════════════════════
    # 信号级诊断（证据矩阵分类，替代日志正则甩 model）
    # ═══════════════════════════════════════════════════════════

    def _run_signal_diagnosis(self, output_dir: str, errors: list) -> list:
        """对 mismatch 类错误，从日志提取 DUT/Model/Expected 值，产出证据矩阵 + 根因分类。

        LLM 不直接判断根因，而是基于信号级证据做分类。
        先查跨 run 经验库：命中同类错误则直接复用历史根因，跳过重复诊断。
        """
        from src.engine.diagnostics.signal_diagnosis import diagnose
        import hashlib
        results = []
        for err in errors:
            msg = err.get("message", "")
            fp = err.get("fingerprint", "") or hashlib.md5(msg.encode()).hexdigest()[:12]

            # ── 经验库查询命中：复用历史根因，跳过诊断 ──
            past = self._lookup_debug_experience(output_dir, fp)
            if past and past.get("root_cause") not in (None, "unknown"):
                results.append({
                    "fingerprint": fp,
                    "message": msg[:150],
                    "verdict": {"root_cause": past["root_cause"],
                                "reason": f"命中历史经验（{past.get('success_count', 1)} 次验证）：{past.get('fix_name', '')[:60]}",
                                "confidence": past.get("confidence", 0)},
                    "from_experience": True,
                })
                continue

            dut_val, model_val, exp_val = self._extract_mismatch_values(msg)
            # 波形补位：日志只给**单点**数值（`expected=0xA5 actual=0x00`），
            # 波形给**时间线** —— 而 `analyze_timing`（时序错位）要的正是时间线。
            # 取不到就当没有，绝不硬凑一条假时间线。
            wave_trace, wave_src = self._waveform_evidence(err, msg)

            if dut_val is None and model_val is None and exp_val is None and not wave_trace:
                # 日志与波形都没有可提取的信号值 → 记录"证据不足"，不强行分类
                results.append({
                    "fingerprint": fp,
                    "message": msg[:150],
                    "verdict": {"root_cause": "unknown",
                                "reason": "日志无信号值、用例也没有可比对的波形，"
                                          "无法做三方对比"},
                })
                continue
            diag = diagnose(
                dut=wave_trace or ({0: dut_val} if dut_val is not None else {}),
                model={0: model_val} if model_val is not None else {},
                expected={0: exp_val} if exp_val is not None else {},
            )
            # L5 进化：跨项目迁移——按根因语义（category）检索同类历史经验
            cross_project = self._lookup_cross_project(diag["verdict"]["root_cause"])
            # 跨 run 经验沉淀：把根因分类 + 修复方向写进经验库（下次同类错误直接命中）
            if diag["verdict"]["root_cause"] != "unknown":
                self._record_debug_experience(output_dir, err, diag)
            if cross_project:
                diag["cross_project"] = cross_project
            entry = {
                "fingerprint": fp,
                "message": msg[:150],
                "evidence": diag["evidence"],
                "verdict": diag["verdict"],
            }
            if wave_src:
                # 说明 DUT 时间线**来自哪条波形的哪个信号** —— 证据要可回溯
                entry["waveform"] = wave_src
            results.append(entry)
        return results

    @staticmethod
    def _lookup_debug_experience(output_dir: str, fp: str):
        """查 debug 经验库（sqlite，命中且 confidence>=0.8 才复用）。"""
        try:
            from src.knowledge.debug_experience import get_debug_experience_store
            return get_debug_experience_store().lookup(fp)
        except Exception:
            return None

    @staticmethod
    def _lookup_cross_project(root_cause: str):
        """L5 进化：跨项目迁移——按根因语义（category）检索同类历史经验。

        fingerprint 是"某个特定错误"，category 是"某类问题"（rtl_issue/
        model_issue）。fingerprint 未命中时，按 category 检索跨项目可复用的
        同类根因经验，返回 Top-3 供诊断参考。
        """
        try:
            from src.experience.growth import lookup_experience_by_category
            exps = lookup_experience_by_category(root_cause)
            if not exps:
                return []
            return [{"root_cause": e.get("root_cause", ""),
                     "fix_name": e.get("fix_name", ""),
                     "success_count": e.get("success_count", 0)}
                    for e in exps[:3]]
        except Exception:
            return []

    @staticmethod
    def _record_debug_experience(output_dir: str, err: dict, diag: dict):
        """把诊断结论沉淀到 debug 经验库（sqlite）。"""
        try:
            import hashlib
            from src.knowledge.debug_experience import get_debug_experience_store
            fp = err.get("fingerprint", "") or hashlib.md5(
                err.get("message", "").encode()).hexdigest()[:12]
            v = diag["verdict"]
            cat = (err.get("classification") or {}).get("category", "unknown")
            get_debug_experience_store().record(
                fp, category=cat, root_cause=v.get("root_cause", "unknown"),
                fix_name=v.get("reason", ""))
        except Exception:
            pass

    # ── 波形证据（log + 波形诊断的另一半）────────────────────────

    @staticmethod
    def _find_case_wave(log_file: str) -> str:
        """失败用例的波形文件（`.db` 优先 → `.wlf` → 用例目录下的 `vsim.wlf`）。

        `log_file` 是 `<用例目录>/sim_*.log`，所以用例目录 = 它的父目录 ——
        波形落点 `<用例目录>/waves/<test>.db` 由此得到。没有就给空串。
        """
        if not log_file:
            return ""
        case = Path(log_file).parent
        if not case.is_dir():
            return ""
        for pat in ("waves/*.db", "waves/*.wlf", "waves/*.vcd",
                    "*.db", "*.wlf", "vsim.wlf"):
            hits = [p for p in case.glob(pat) if p.is_file()]
            if hits:
                return str(max(hits, key=lambda p: p.stat().st_mtime))
        return ""

    @staticmethod
    def _signal_names_in(msg: str) -> List[str]:
        """从错误消息里挑出**可能是信号/寄存器名**的标识符。

        不追求精确 —— 真正的过滤在波形侧：`extract_signal_trace` 只返回波形里
        **确实存在**的同名信号，所以这里多挑几个噪声词也无所谓。
        ```
        reg CTRL mismatch: w=0xA5 r=0x00   → ["CTRL", ...]
        ```
        """
        stop = {"reg", "mismatch", "expected", "actual", "got", "want", "dut",
                "model", "error", "fail", "failed", "uvm_error", "uvm_fatal",
                "scb", "loop", "and", "the", "for", "with", "not", "when"}
        out: List[str] = []
        for tok in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", msg):
            if len(tok) < 2 or tok.lower() in stop or tok in out:
                continue
            # `0xA5` 会被切成 `xA5` —— 那是数值不是信号名，扔掉
            if re.fullmatch(r"[xX][0-9a-fA-F]+", tok):
                continue
            out.append(tok)
        return out[:8]

    @staticmethod
    def _waveform_evidence(err: Dict[str, Any], msg: str):
        """失败用例的波形 → `(dut_trace, source)`；取不到给 `({}, "")`。

        `source` 形如 `<波形路径>#<信号名>` —— 证据可回溯（这条时间线是从哪来的）。
        多个同名信号命中时，`extract_signal_trace` 取采样最多的那条；
        这里再取采样最多的**信号**当作 DUT 时间线。
        """
        wave = DebugExecutor._find_case_wave(err.get("log_file", ""))
        if not wave:
            return {}, ""
        names = DebugExecutor._signal_names_in(msg)
        if not names:
            return {}, ""
        try:
            from src.engine.diagnostics.waveform import extract_signal_trace

            traces = extract_signal_trace(wave, names)
        except Exception:                              # noqa: BLE001 波形是旁路证据
            return {}, ""
        # 按**消息里出现的先后**取第一个真存在的信号 —— 越靠前越可能是这条消息的
        # 主语（`reg CTRL mismatch: …` 的 CTRL）。取"采样最多"会把顺带被提一嘴的
        # 信号（`… penable=1`）当成主体，拿它的时间线去比对期望，结论就偏了。
        for name in names:
            if traces.get(name):
                return traces[name], f"{wave}#{name}"
        return {}, ""

    @staticmethod
    def _extract_mismatch_values(msg: str):
        """从 mismatch 日志提取 (dut_val, model_val, expected_val)。

        语义：scoreboard 的 expected/exp/want 来自参考模型 → 同时作为 model 和 expected；
        actual/got/dut 是 DUT 实际输出。
        支持格式：expected=0xA5 actual=0x00 / got 0x00 want 0xA5 / dut=0x00 model=0xA5
        """
        import re

        def _hx(s):
            m = re.search(r"0x([0-9a-fA-F]+)", s)
            if m:
                return int(m.group(1), 16)
            m = re.search(r"(?<![0-9a-fA-F])(\d+)(?![0-9a-fA-F])", s)
            return int(m.group(1)) if m else None

        dut = model = exp = None
        for key, val in re.findall(
                r"(dut|model|expected|actual|exp|got|want)\s*[=:\s]\s*(0x[0-9a-fA-F]+|\d+)",
                msg, re.IGNORECASE):
            v = _hx(val)
            k = key.lower()
            if k in ("dut", "actual", "got"):
                dut = v
            elif k == "model":
                model = v
            elif k in ("expected", "exp", "want"):
                # scoreboard 期望来自参考模型 → 同赋 model 和 expected
                if model is None:
                    model = v
                exp = v
        return dut, model, exp

    @staticmethod
    def _llm_regenerate_file(output_dir: str, fname: str, error_msg: str) -> bool:
        """LLM 兜底修复：读出错文件 → call_llm 产出修正版 → 写回。返回是否写回。

        这是 debug agent 的「真修复」落地：模板 auto_fix 覆盖不到的错误（RTL 多驱动、
        virtual interface 参数化等）由 LLM 重写出错文件，而非只记录假设。
        """
        try:
            from src.tools.common.lib.llm_call import CODE_SCHEMA, call_llm
            od = Path(output_dir)
            fpath = od / fname
            if not fpath.exists():
                cands = list(od.rglob(fname))
                fpath = cands[0] if cands else None
            if fpath is None:
                return False
            code = fpath.read_text(encoding="utf-8", errors="replace")
            prompt = (
                "你是 IC 验证/设计工程师。下面 SystemVerilog 文件有编译/elaboration 错误。\n"
                "只修复报错点，保留模块接口与整体结构，输出完整修正后的文件内容"
                "（含 module/endmodule 或 class/endclass）。"
            )
            fixed = call_llm(prompt, code, error_msg,
                             output_schema=CODE_SCHEMA,
                             prompt_version="debug-fix-file-v1")
            if not fixed or ("module" not in fixed and "class" not in fixed):
                return False
            # **走全项目唯一的写盘出口** —— 生成物（带 `自动生成 (tool_uvm` banner）
            # 只许改 `pragma custom` 区域，整份重写一律拒绝。
            #
            # 这里原来是无条件 `write_text`，而这个 prompt 明确要求"输出完整修正后的
            # 文件内容（含 class/endclass）" —— loopback 的 SCB 正是一个 class。
            # 实测：它把 SCB 重写成模板里根本没有的形状（`compare_one` + 裸 `pstrb`
            # 比较），而编译一塌，`-mfcu` 就带崩整个 work 库的注册 → `[INVTST]`
            # → loopback 挂 → 分级回归第一道门就断（每轮结果还都不同）。
            from src.layers.l1_infrastructure.generated_files import gated_write
            if not gated_write(fpath, fixed, logger=logger):
                logger.warning(f"拒绝整份重写生成物 {fpath.name}"
                               f" —— 只允许改 pragma custom 区域")
                return False
            return True
        except Exception:
            return False
