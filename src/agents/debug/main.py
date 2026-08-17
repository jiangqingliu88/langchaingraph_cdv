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

from src.layers.l2_orchestration.agents.base import BaseAgent, AgentResult
from src.layers.l2_orchestration.agents.registry import register_agent
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

        # ── 编译/elaboration 错误定向修复：编排层把 compile_error 传进来，直接 LLM 重写出错文件 ──
        _params = task.get("params", {}) if isinstance(task.get("params"), dict) else {}
        _ce = _params.get("compile_error") if isinstance(_params.get("compile_error"), dict) else None
        if _ce:
            _fname = _ce.get("file", "")
            _msg = _ce.get("message", "")
            _fixed = self._llm_regenerate_file(str(od), _fname, _msg) if _fname else False
            logger.info(f"debug 编译错误定向修复: file={_fname} fixed={_fixed}")
            return AgentResult(success=True, data={
                "debug": {"compile_fix": {"file": _fname, "fixed": _fixed,
                                          "message": _msg[:150]}},
                "score": 85 if _fixed else 20,
            })

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

        # ── Phase 2.5: 信号级诊断（对 mismatch 类错误，证据矩阵分类替代正则甩 model）──
        signal_diagnosis = self._run_signal_diagnosis(
            output_dir, [e for e in unique.values()
                         if e["classification"]["category"] in ("model_mismatch", "unknown")])

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

        # ── Phase 3.5: 经验库命中（debug 成长：记忆复用 + 教训升级）──
        from src.layers.l4_memory.debug_experience import get_debug_experience_store
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
            fix_result = json.loads(
                auto_fix(json.dumps({"error_text": msg, "output_dir": output_dir}))
            )
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
                        rerun = json.loads(
                            rerun_failed_test(json.dumps({"output_dir": output_dir, "test_name": test_name}))
                        )
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
            await record_bugs_and_fixes(_bugs, _fixes, run_id=str(od.name))
            logger.info(f"bug/fix 落库: {len(_bugs)} bug, {len(_fixes)} fix")
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

    # ═══════════════════════════════════════════════════════════
    # 信号级诊断（证据矩阵分类，替代日志正则甩 model）
    # ═══════════════════════════════════════════════════════════

    def _run_signal_diagnosis(self, output_dir: str, errors: list) -> list:
        """对 mismatch 类错误，从日志提取 DUT/Model/Expected 值，产出证据矩阵 + 根因分类。

        LLM 不直接判断根因，而是基于信号级证据做分类。
        先查跨 run 经验库：命中同类错误则直接复用历史根因，跳过重复诊断。
        """
        from src.tools.debug_tools.signal_diagnosis import diagnose
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
            if dut_val is None and model_val is None and exp_val is None:
                # 日志里没有可提取的信号值 → 记录"证据不足"，不强行分类
                results.append({
                    "fingerprint": fp,
                    "message": msg[:150],
                    "verdict": {"root_cause": "unknown",
                                "reason": "日志无信号值，无法做三方对比（需波形/参考模型数据）"},
                })
                continue
            diag = diagnose(
                dut={0: dut_val} if dut_val is not None else {},
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
            results.append({
                "fingerprint": fp,
                "message": msg[:150],
                "evidence": diag["evidence"],
                "verdict": diag["verdict"],
            })
        return results

    @staticmethod
    def _lookup_debug_experience(output_dir: str, fp: str):
        """查 debug 经验库（sqlite，命中且 confidence>=0.8 才复用）。"""
        try:
            from src.layers.l4_memory.debug_experience import get_debug_experience_store
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
            from src.layers.l5_evolution.growth import lookup_experience_by_category
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
            from src.layers.l4_memory.debug_experience import get_debug_experience_store
            fp = err.get("fingerprint", "") or hashlib.md5(
                err.get("message", "").encode()).hexdigest()[:12]
            v = diag["verdict"]
            cat = (err.get("classification") or {}).get("category", "unknown")
            get_debug_experience_store().record(
                fp, category=cat, root_cause=v.get("root_cause", "unknown"),
                fix_name=v.get("reason", ""))
        except Exception:
            pass

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
            from src.tools.lib.llm_refine import call_llm
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
            fixed = call_llm(prompt, code, error_msg)
            if not fixed or ("module" not in fixed and "class" not in fixed):
                return False
            fpath.write_text(fixed, encoding="utf-8")
            return True
        except Exception:
            return False
