"""
信号级诊断 —— 把根因定位从"日志正则"升级成"证据矩阵分类"。

核心思想：LLM 不可能只靠看日志知道"为什么错"，错在 RTL / Env / Model 在信号
层面看起来可能完全一样。所以把根因定位变成一个**基于证据的分类问题**：

  工具做精确的"信号级对比"（三方数值 + 时序偏移）→ 产出证据矩阵
  LLM 做"模式识别和报告生成"（证据矩阵 → 分类 → 报告）
  规则引擎做"决策路由"（分类 → MODIFY_MODEL/MODIFY_RTL/MODIFY_ENV）

四步定位法：
  Step 1: compare_signal_values  信号级一致性检查（DUT vs Model vs Expected 三方对比）
  Step 2: analyze_timing          时序窗口检查（timing_shift：负=前递，正=stall）
  Step 3: verify_model            Model 行为验证（流水线级数 / bypass 支持）
  Step 4: verify_env              Env 激励检查（Scoreboard 参考模型 / Monitor 捕获）

用法:
    from src.executors.debug.tools.signal_diagnosis import (
        compare_signal_values, analyze_timing, build_evidence_matrix, classify_root_cause)
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


# ═══════════════════════════════════════════════════════════════
# 数据格式：信号时间线
# ═══════════════════════════════════════════════════════════════

def _normalize_trace(trace: Any) -> Dict[int, Any]:
    """把信号时间线统一成 {cycle: value}。

    支持 list[(cycle, value)]、dict{cycle: value}、list[value]（按序，cycle=0,1,2...）。
    """
    if trace is None:
        return {}
    if isinstance(trace, dict):
        return {int(k): v for k, v in trace.items()}
    if isinstance(trace, (list, tuple)):
        result = {}
        for i, item in enumerate(trace):
            if isinstance(item, (list, tuple)) and len(item) == 2:
                result[int(item[0])] = item[1]
            else:
                result[i] = item
        return result
    return {}


def _to_int(v: Any) -> Optional[int]:
    """把信号值统一成 int 便于比较（支持 0x 字符串、bit 串等）。"""
    if v is None:
        return None
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        s = v.strip().lower()
        try:
            if s.startswith("0x"):
                return int(s, 16)
            if s.startswith("0b"):
                return int(s, 2)
            # 去掉 'h / 'd 等 SV 字面量前缀
            if "'" in s:
                s = s.split("'", 1)[-1]
            return int(s, 0) if s else None
        except ValueError:
            # 可能是 "x" / "z" 等未知态
            return None
    return None


# ═══════════════════════════════════════════════════════════════
# Step 1: 信号级一致性检查
# ═══════════════════════════════════════════════════════════════

def compare_signal_values(dut: Any, model: Any, expected: Any) -> dict:
    """三方对比：DUT 输出 vs Model 预测 vs Scoreboard 期望。

    Args:
        dut: DUT 输出时间线
        model: 参考模型预测时间线
        expected: Scoreboard 期望时间线

    Returns:
        {
          "dut_vs_model": "match" | "mismatch" | "unavailable",
          "dut_vs_scoreboard": "match" | "mismatch" | "unavailable",
          "model_vs_scoreboard": ...,
          "mismatch_cycles": [...],
          "first_mismatch": {"cycle", "dut", "model", "expected"} | None,
          "cycles_compared": int,
        }
    """
    dut_t = _normalize_trace(dut)
    model_t = _normalize_trace(model)
    exp_t = _normalize_trace(expected)

    cycles = sorted(set(dut_t) | set(model_t) | set(exp_t))
    mismatch_cycles = []
    first_mismatch = None

    dut_avail = bool(dut_t)
    model_avail = bool(model_t)
    exp_avail = bool(exp_t)

    for c in cycles:
        dv = _to_int(dut_t.get(c))
        mv = _to_int(model_t.get(c))
        ev = _to_int(exp_t.get(c))
        # 只要有一方不一致（且三方都有值可比较）
        if dv is not None and mv is not None and dv != mv:
            mismatch_cycles.append(c)
            if first_mismatch is None:
                first_mismatch = {"cycle": c, "dut": dv, "model": mv, "expected": ev}
        if dv is not None and ev is not None and dv != ev:
            mismatch_cycles.append(c)
            if first_mismatch is None:
                first_mismatch = {"cycle": c, "dut": dv, "model": mv, "expected": ev}

    # 去重 + 排序
    mismatch_cycles = sorted(set(mismatch_cycles))

    def _cmp(a_avail, b_avail, a_t, b_t):
        if not a_avail or not b_avail:
            return "unavailable"
        keys = set(a_t) & set(b_t)
        if not keys:
            return "unavailable"
        return "match" if all(_to_int(a_t[k]) == _to_int(b_t[k]) for k in keys) else "mismatch"

    return {
        "dut_vs_model": _cmp(dut_avail, model_avail, dut_t, model_t),
        "dut_vs_scoreboard": _cmp(dut_avail, exp_avail, dut_t, exp_t),
        "model_vs_scoreboard": _cmp(model_avail, exp_avail, model_t, exp_t),
        "mismatch_cycles": mismatch_cycles,
        "first_mismatch": first_mismatch,
        "cycles_compared": len(cycles),
    }


# ═══════════════════════════════════════════════════════════════
# Step 2: 时序窗口检查
# ═══════════════════════════════════════════════════════════════

def analyze_timing(dut: Any, expected: Any, window: int = 5) -> dict:
    """检查 DUT 输出是否在 expected 的 ±window 拍内出现（时序错位）。

    Returns:
      {
        "timing_shift": int | None,   # None=未错位；负=提前（bypass）；正=延迟（stall）
        "suspected_cause": "pipeline_bypass" | "pipeline_stall" | "aligned" | "unknown",
      }
    """
    dut_t = _normalize_trace(dut)
    exp_t = _normalize_trace(expected)
    if not dut_t or not exp_t:
        return {"timing_shift": None, "suspected_cause": "unknown"}

    # 对每个 expected cycle，看 dut 值是否在 ±window 内出现
    best_shift = None
    for c, ev in exp_t.items():
        ev_i = _to_int(ev)
        if ev_i is None:
            continue
        for offset in range(-window, window + 1):
            dv = _to_int(dut_t.get(c + offset))
            if dv == ev_i and offset != 0:
                if best_shift is None or abs(offset) < abs(best_shift):
                    best_shift = offset

    if best_shift is None:
        return {"timing_shift": None, "suspected_cause": "aligned"}
    return {
        "timing_shift": best_shift,
        "suspected_cause": "pipeline_bypass" if best_shift < 0 else "pipeline_stall",
    }


# ═══════════════════════════════════════════════════════════════
# Step 3 & 4: Model / Env 行为验证
# ═══════════════════════════════════════════════════════════════

def verify_model(model_features: Dict[str, Any], dut_features: Dict[str, Any]) -> dict:
    """Model 行为验证：流水线级数 / bypass 支持对比。"""
    model_features = model_features or {}
    dut_features = dut_features or {}
    issues = []

    model_depth = model_features.get("pipeline_depth")
    dut_depth = dut_features.get("pipeline_depth")
    if model_depth is not None and dut_depth is not None and model_depth != dut_depth:
        issues.append({
            "type": "pipeline_depth_mismatch",
            "detail": f"Model={model_depth} stages, DUT={dut_depth} stages",
        })

    model_bypass = model_features.get("has_bypass", False)
    dut_bypass = dut_features.get("has_bypass", False)
    if dut_bypass and not model_bypass:
        issues.append({"type": "missing_bypass", "detail": "DUT 有 bypass，Model 无"})

    return {"model_issues": issues, "model_ok": not issues,
            "model_bypass_support": model_bypass, "dut_bypass_support": dut_bypass}


def verify_env(env_config: Dict[str, Any]) -> dict:
    """Env 激励检查：Scoreboard 参考模型 / Monitor 捕获完整性。"""
    env_config = env_config or {}
    issues = []

    if env_config.get("reference_model") not in (None, "", "correct_model_handle"):
        issues.append({"type": "wrong_model_reference",
                       "detail": f"scoreboard 参考模型 = {env_config.get('reference_model')}"})

    if env_config.get("monitor_captured_all") is False:
        issues.append({"type": "monitor_missing_signals", "detail": "Monitor 未捕获全部 DUT 输出"})

    return {"env_issues": issues, "env_ok": not issues}


# ═══════════════════════════════════════════════════════════════
# 证据矩阵 + 根因分类（决策表）
# ═══════════════════════════════════════════════════════════════

def build_evidence_matrix(signal_cmp: dict, timing: dict,
                          model_check: dict, env_check: dict) -> dict:
    """把四步结果汇总成结构化的证据矩阵（LLM 的唯一输入）。"""
    return {
        "dut_vs_scoreboard": signal_cmp.get("dut_vs_scoreboard"),
        "dut_vs_model": signal_cmp.get("dut_vs_model"),
        "model_vs_scoreboard": signal_cmp.get("model_vs_scoreboard"),
        "timing_shift": timing.get("timing_shift"),
        "suspected_cause": timing.get("suspected_cause"),
        "model_bypass_support": model_check.get("model_bypass_support"),
        "dut_bypass_support": model_check.get("dut_bypass_support"),
        "model_issues": model_check.get("model_issues", []),
        "env_issues": env_check.get("env_issues", []),
        "mismatch_cycles": signal_cmp.get("mismatch_cycles", []),
        "first_mismatch": signal_cmp.get("first_mismatch"),
    }


def classify_root_cause(evidence: Dict[str, Any]) -> dict:
    """根据证据矩阵映射到根因分类（决策表，可硬编码）。

    返回 {root_cause, confidence, reason, fix_target}。
    root_cause ∈ model_issue | rtl_issue | env_issue | unknown
    """
    dut_vs_sb = evidence.get("dut_vs_scoreboard")
    dut_vs_md = evidence.get("dut_vs_model")
    timing_shift = evidence.get("timing_shift")
    model_issues = evidence.get("model_issues", [])
    env_issues = evidence.get("env_issues", [])

    # ── env_issue：Scoreboard 配置错 / Monitor 漏采 ──
    if env_issues:
        return {
            "root_cause": "env_issue",
            "confidence": 90,
            "reason": f"Env 配置问题：{env_issues[0].get('type')}",
            "fix_target": "env",
        }

    # ── model_issue：DUT 与期望一致，但 Model 不一致（Model 预测错）──
    if dut_vs_sb == "match" and dut_vs_md == "mismatch":
        return {
            "root_cause": "model_issue",
            "confidence": 85,
            "reason": "DUT 输出与 Scoreboard 期望一致，但 Model 预测不一致 → Model 预测错",
            "fix_target": "model",
        }

    # ── model_issue：DUT 有 bypass 而 Model 无（时序错位 + 缺 bypass）──
    if (timing_shift is not None and timing_shift < 0
            and evidence.get("dut_bypass_support") and not evidence.get("model_bypass_support")):
        return {
            "root_cause": "model_issue",
            "confidence": 90,
            "reason": f"时序提前 {timing_shift} 拍（前递特征）+ DUT 有 bypass 而 Model 无 → Model 缺 bypass",
            "fix_target": "model",
        }

    # ── model_issue：Model 内部问题（流水线级数不匹配等）──
    if model_issues:
        return {
            "root_cause": "model_issue",
            "confidence": 80,
            "reason": f"Model 行为异常：{model_issues[0].get('type')}",
            "fix_target": "model",
        }

    # ── rtl_issue：DUT 与期望不一致，但 Model 与期望一致（DUT 输出错）──
    if dut_vs_sb == "mismatch" and (dut_vs_md == "match" or evidence.get("model_vs_scoreboard") == "match"):
        return {
            "root_cause": "rtl_issue",
            "confidence": 85,
            "reason": "DUT 输出与 Scoreboard 期望不一致，但 Model 与期望一致 → DUT 输出错",
            "fix_target": "rtl",
        }

    # ── rtl_issue：时序延迟（stall），且 bypass 都支持 → RTL 时序问题 ──
    if timing_shift is not None and timing_shift > 0:
        return {
            "root_cause": "rtl_issue",
            "confidence": 70,
            "reason": f"时序延迟 {timing_shift} 拍（stall 特征）→ RTL 时序问题",
            "fix_target": "rtl",
        }

    # ── unknown：证据不足 ──
    return {
        "root_cause": "unknown",
        "confidence": 0,
        "reason": "证据不足，无法定位（可能缺波形或参考模型数据）",
        "fix_target": "none",
    }


# ═══════════════════════════════════════════════════════════════
# 一站式入口
# ═══════════════════════════════════════════════════════════════

def diagnose(dut: Any, model: Any, expected: Any,
             model_features: Dict[str, Any] = None,
             dut_features: Dict[str, Any] = None,
             env_config: Dict[str, Any] = None,
             window: int = 5) -> dict:
    """一站式信号级诊断：四步 → 证据矩阵 → 根因分类。"""
    signal_cmp = compare_signal_values(dut, model, expected)
    timing = analyze_timing(dut, expected, window)
    model_check = verify_model(model_features, dut_features)
    env_check = verify_env(env_config)
    evidence = build_evidence_matrix(signal_cmp, timing, model_check, env_check)
    verdict = classify_root_cause(evidence)
    return {"evidence": evidence, "verdict": verdict,
            "signal_comparison": signal_cmp, "timing": timing}
