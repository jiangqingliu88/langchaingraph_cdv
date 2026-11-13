"""关键守卫的**变异测试** —— 证明测试真的能抓住回归。

普通测试证明“现在是对的”；变异测试故意把守卫改坏，再跑对应测试：
测试必须失败（mutant killed）。如果测试仍然通过，说明那条守卫其实没被
测到（mutant survived）。

只对最贵的几条不变量做，不追求覆盖率：
  · 硬失败不能被软策略覆盖
  · verify 7 步依赖不能少
  · 后端保留 plusargs 不能手写
  · 文件审计链不能跳过哈希
  · State 字段契约不能写错属主
  · 工具空映射不能静默通过
  · `source` 标签不能乱配动作

用法：
    python scripts/mutation_guards.py            # 全跑，有 survived 则 exit 1
    python scripts/mutation_guards.py --json     # 机器读
    python scripts/mutation_guards.py --only decision_hard_overridden
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Mutation:
    name: str
    path: str
    old: str
    new: str
    tests: str


MUTATIONS: List[Mutation] = [
    Mutation(
        name="decision_hard_overridden",
        path="src/ir_plane/decision/decision_engine.py",
        old="return self.hard_action(observation) or self.soft_action(observation)",
        new="return self.soft_action(observation)",
        tests="tests/test_decision_phases.py",
    ),
    Mutation(
        name="steps_dag_missing_dependency",
        path="src/engine_plane/verify/steps_dag.py",
        old='        "env_cov_bins", deps=("dut_channel",),',
        new='        "env_cov_bins", deps=(),',
        tests="tests/test_verify_steps_dag.py",
    ),
    Mutation(
        name="plusargs_reserved_allowed",
        path="src/orchestration_plane/l2/regression_tools/backend_profiles.py",
        old="        if key in reserved:",
        new="        if False and key in reserved:",
        tests="tests/test_plusargs_semantics.py",
    ),
    Mutation(
        name="file_audit_hash_skipped",
        path="src/orchestration_plane/l2/evidence/file_audit.py",
        old='            if r.get("hash") != expect:',
        new='            if False and r.get("hash") != expect:',
        tests="tests/test_human_edit_evidence.py",
    ),
    Mutation(
        name="state_contract_wrong_owner",
        path="src/orchestration_plane/l2/state.py",
        old='"sim_reward":        {"writers": ("coverage",),',
        new='"sim_reward":        {"writers": ("design",),',
        tests="tests/test_state_contracts.py",
    ),
    Mutation(
        name="tool_registry_empty_allowed",
        path="src/orchestration_plane/l2/communication/tool_hub.py",
        old="        undeclared = sorted(empty - cls.EXECUTORS_WITHOUT_HUB_TOOLS)",
        new="        undeclared = []",
        tests="tests/test_tool_registry.py",
    ),
    Mutation(
        name="source_terminal_accepts_anything",
        path="src/ir_plane/decision/decision_engine.py",
        old='    "terminal": frozenset(TERMINAL_ACTIONS),',
        new='    "terminal": frozenset(ALL_ACTIONS),',
        tests="tests/test_source_transitions.py",
    ),
    Mutation(
        # 判据退化成子串匹配 → 逐条 SB 的 `mismatched=0` 能把"聚合脏"骗成通过
        name="scb_pass_anchor_loosened",
        path="src/orchestration_plane/l2/regression_tools/backend_profiles.py",
        old=("    'grep -qE \"(\\\\[SCB_DUT\\\\]|Scoreboard:).*mismatched=0\" "
             "sim_vsim.log '"),
        new="    'grep -qE \"mismatched=0\" sim_vsim.log '",
        tests="tests/test_per_sb_scoreboard.py",
    ),
    Mutation(
        # 归属靠猜（名字对不上也发逐条行）→ "不猜" 的测试必须红
        name="scoreboard_rules_guessed",
        path="src/engine_plane/verify/dut_checker.py",
        old=("        owned = [str(n) for n in (sb.get(\"rules\") or []) "
             "if str(n) in known]"),
        new=("        owned = ([str(n) for n in (sb.get(\"rules\") or [])]\n"
             "                 or sorted(known)[:1])"),
        tests="tests/test_per_sb_scoreboard.py",
    ),
]


def _run(path: Path, mutation: Mutation) -> dict:
    original = path.read_text(encoding="utf-8")
    count = original.count(mutation.old)
    if count != 1:
        return {**asdict(mutation), "status": "invalid",
                "detail": f"目标片段出现 {count} 次（应为 1 次）"}
    mutated = original.replace(mutation.old, mutation.new, 1)
    try:
        path.write_text(mutated, encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", mutation.tests, "-q"],
            cwd=str(ROOT), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=300)
        killed = proc.returncode != 0
        return {
            **asdict(mutation),
            "status": "killed" if killed else "survived",
            "returncode": proc.returncode,
            "tail": "\n".join((proc.stdout or "").strip().splitlines()[-3:]),
        }
    finally:
        path.write_text(original, encoding="utf-8")


def main(argv: List[str] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--only", default="", help="只跑名字匹配的 mutant")
    args = parser.parse_args(argv)

    chosen = [m for m in MUTATIONS if not args.only or args.only in m.name]
    results = []
    for mutation in chosen:
        path = ROOT / mutation.path
        if not path.is_file():
            results.append({**asdict(mutation), "status": "invalid",
                            "detail": "文件不存在"})
            continue
        result = _run(path, mutation)
        results.append(result)
        if not args.json:
            print(f"[{result['status']:8}] {mutation.name}")
            if result["status"] != "killed":
                print(f"           {result.get('detail') or result.get('tail','')}")

    killed = sum(1 for r in results if r["status"] == "killed")
    total = len(results)
    report = {"killed": killed, "total": total,
              "score": round(killed / total, 3) if total else 0.0,
              "results": results}
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"\nmutation score: {killed}/{total} = {report['score']:.0%}")
    # 验收：关键守卫必须 100% killed
    return 0 if total and killed == total else 1


if __name__ == "__main__":
    sys.exit(main())
