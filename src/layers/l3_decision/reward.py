"""验证闭环的**粗连续奖励**——把“过/不过”拆成“往好的方向走了多少”。

## 为什么需要它

Cadence 能直接从求解器内部读连续信号（slack / DRC / IR drop）。SignOffAI 只有
命令行黑盒：`vlog` 返回码、`vsim` 的 `Errors: N`、`ucdb` 的 hitrate。奖励如果
只有 0/1，策略学到的是“全有全无”，平台期时没有任何方向。

这个模块把三层信号合成一个 0..1 的分数：

    compile   编译是否通过 + 错误/警告数量（秒级反馈）
    regression 通过率 + 运行深度（分钟级）
    coverage  计划覆盖率 + TP 命中率 + 种子多样性（更慢）

它不是“替代求解器”，而是**在现有黑盒上榨出最接近连续的近似**。
所有字段都只读已有产物，不新增一次 EDA 调用。
"""
from __future__ import annotations

import math
import re
from typing import Any, Dict, Optional, Tuple

_SCHEMA = "sim_reward_v1"

#: 三层权重。编译最快、覆盖率最慢但最接近目标；权重按“目标相关度”给。
WEIGHTS = {"compile": 0.25, "regression": 0.35, "coverage": 0.40}


def normalize_weights(raw: Any = None) -> Tuple[Dict[str, float], list]:
    """把策略文件里的 `reward_weights` 归一成 0..1 的三项权重。

    - 缺省 / 非映射 / 非数字 / 负数 / 总和为 0 → **回退默认权重**并返回原因；
    - 缺项用默认值补齐，未知键忽略；
    - 合法时按总和归一，保证 `total` 仍在 0..1（换权重不改量纲）。
    """
    if raw is None:
        return dict(WEIGHTS), []
    if not isinstance(raw, dict):
        return dict(WEIGHTS), ["reward_weights 必须是映射（compile/regression/coverage）"]

    issues: list = []
    merged: Dict[str, float] = {}
    for key, default in WEIGHTS.items():
        if key not in raw:
            merged[key] = default
            issues.append(f"reward_weights 缺少 {key}，用默认 {default}")
            continue
        try:
            value = float(raw[key])
        except (TypeError, ValueError):
            return dict(WEIGHTS), [f"reward_weights.{key} 不是数字: {raw[key]!r}"]
        if not math.isfinite(value) or value < 0:
            return dict(WEIGHTS), [f"reward_weights.{key} 必须是非负有限数: {value!r}"]
        merged[key] = value
    for key in raw:
        if key not in WEIGHTS:
            issues.append(f"忽略未知的 reward_weights 键: {key}")

    total = sum(merged.values())
    if total <= 0:
        return dict(WEIGHTS), issues + ["reward_weights 总和必须大于 0"]
    return {k: round(v / total, 6) for k, v in merged.items()}, issues


def weights_from_policy(policy: Any) -> Optional[Dict[str, Any]]:
    """从 `load_policy()` 的返回值（或原始策略 dict）取 `reward_weights`。"""
    raw = policy.get("raw") if isinstance(policy, dict) and "raw" in policy else policy
    if isinstance(raw, dict):
        return raw.get("reward_weights")
    return None

_ERRORS_RE = re.compile(r"Errors:\s*(\d+)", re.IGNORECASE)
_WARN_RE = re.compile(r"Warnings:\s*(\d+)", re.IGNORECASE)


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _compile_component(regression: Dict[str, Any]) -> Dict[str, Any]:
    status = str(regression.get("compile", "") or "").upper()
    stderr = str(regression.get("stderr", "") or
                 regression.get("compile_errors", "") or "")
    errors = 0
    warnings = 0
    m = _ERRORS_RE.search(stderr)
    if m:
        errors = int(m.group(1))
    m = _WARN_RE.search(stderr)
    if m:
        warnings = int(m.group(1))
    # **没有编译数据 ≠ 编译通过**：空 regression 时给 0，不能凭“没报错”给 1。
    has_data = bool(regression) or bool(status) or bool(stderr)
    passed = status == "PASS" or (not status and (
        _num(regression.get("passed"), 0) > 0
        or _num(regression.get("total"), 0) > 0))
    if not has_data:
        passed = False
    # 通过=1；不通过时按错误数衰减（0 错但状态失败仍给 0.5，避免全有全无）。
    score = 1.0 if passed else (0.5 if errors == 0 else max(0.0, 0.5 - errors / 40.0))
    if not has_data:
        score = 0.0
    return {"score": round(score, 4), "passed": passed,
            "errors": errors, "warnings": warnings,
            "status": status or ("PASS" if passed else "FAIL")}


def _regression_component(regression: Dict[str, Any]) -> Dict[str, Any]:
    total = int(_num(regression.get("total"), 0))
    passed = int(_num(regression.get("passed"), 0))
    failed = int(_num(regression.get("failed"), 0))
    ratio = (passed / total) if total > 0 else 0.0
    # 挂死单独计：它常是 bench 侧问题，不能把 RTL 奖励打到 0。
    harness = len(regression.get("harness_failures") or [])
    score = ratio
    if total == 0:
        score = 0.0
    return {"score": round(score, 4), "passed": passed, "failed": failed,
            "total": total, "pass_ratio": round(ratio, 4),
            "harness_failures": harness}


def _coverage_component(coverage: Dict[str, Any], tp_matrix: Dict[str, Any],
                        seed_diversity: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    plan = _num(coverage.get("functional_pct", coverage.get("overall_pct")), 0.0)
    plan_score = max(0.0, min(1.0, plan / 100.0))

    # TP 命中率：可激励 + 后门 + 观测分栏；只把“有明确判据”的算进去。
    counts = (tp_matrix or {}).get("counts") or {}
    hit = sum(int(_num(counts.get(k))) for k in
              ("HIT", "OBSERVED", "BACKDOOR_HIT"))
    total = int(_num((tp_matrix or {}).get("total"), 0)) or sum(
        int(_num(v)) for v in counts.values())
    tp_score = (hit / total) if total > 0 else 0.0

    verdict = str((seed_diversity or {}).get("verdict") or "").upper()
    seed_score = {"DIVERSE": 1.0, "IDENTICAL": 0.5}.get(verdict, 0.0)

    # 覆盖率内部再分三份：计划 50% / TP 35% / 种子 15%
    score = 0.5 * plan_score + 0.35 * tp_score + 0.15 * seed_score
    return {"score": round(score, 4), "plan_pct": plan,
            "plan_score": round(plan_score, 4),
            "tp_hit": hit, "tp_total": total,
            "tp_score": round(tp_score, 4),
            "seed_verdict": verdict or "UNKNOWN",
            "seed_score": seed_score}


def compute_sim_reward(regression: Dict[str, Any] | None,
                       coverage: Dict[str, Any] | None,
                       tp_matrix: Dict[str, Any] | None = None,
                       seed_diversity: Dict[str, Any] | None = None,
                       weights: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """读已有产物 → 粗连续奖励（0..1）。

    纯函数：不读文件、不跑 EDA、不写盘。调用方负责把结果落
    `coverage/sim_reward.json` 并喂给决策/经验库。

    `weights` 通常来自模块签核策略的 `reward_weights`；无效配置**回退默认**
    并在 `weight_issues` 里说明原因（不静默改变量纲）。
    """
    regression = regression if isinstance(regression, dict) else {}
    coverage = coverage if isinstance(coverage, dict) else {}
    tp_matrix = tp_matrix if isinstance(tp_matrix, dict) else {}

    used_weights, weight_issues = normalize_weights(weights)
    comp = {
        "compile": _compile_component(regression),
        "regression": _regression_component(regression),
        "coverage": _coverage_component(coverage, tp_matrix, seed_diversity),
    }
    total = sum(used_weights[k] * comp[k]["score"] for k in used_weights)
    return {
        "schema": _SCHEMA,
        "total": round(total, 4),
        "weights": used_weights,
        "weight_issues": weight_issues,
        "components": comp,
        # 给决策层的直接建议：最弱的一层决定下一步该往哪使劲。
        "weakest": min(comp, key=lambda k: comp[k]["score"]),
    }
