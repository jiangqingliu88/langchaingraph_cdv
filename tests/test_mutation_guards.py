"""变异测试的**目标有效性** —— 守卫改了，mutant 定义不能悄悄失效。

真正的变异执行在 `scripts/mutation_guards.py`（会改源码再跑 pytest，较慢，
不放进默认测试）。这里只钉住：每条 mutant 的目标片段仍然唯一存在、
对应测试文件还在。否则脚本会“因为找不到片段而跳过”，看起来全绿。
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_script():
    path = ROOT / "scripts" / "mutation_guards.py"
    spec = importlib.util.spec_from_file_location("mutation_guards", path)
    mod = importlib.util.module_from_spec(spec)
    # dataclass 需要模块已进 sys.modules 才能解析 __module__
    sys.modules["mutation_guards"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_every_mutant_targets_a_unique_existing_snippet():
    mod = _load_script()
    names = [m.name for m in mod.MUTATIONS]
    assert len(names) == len(set(names))
    for mutation in mod.MUTATIONS:
        path = ROOT / mutation.path
        assert path.is_file(), mutation.path
        text = path.read_text(encoding="utf-8")
        assert text.count(mutation.old) == 1, (
            f"{mutation.name}: 目标片段出现 {text.count(mutation.old)} 次"
            "（守卫代码改了？同步 mutation_guards.py）")
        assert (ROOT / mutation.tests).is_file(), mutation.tests


def test_the_mutation_set_covers_the_six_core_guards():
    mod = _load_script()
    assert {m.name for m in mod.MUTATIONS} == {
        "decision_hard_overridden", "steps_dag_missing_dependency",
        "plusargs_reserved_allowed", "file_audit_hash_skipped",
        "state_contract_wrong_owner", "tool_registry_empty_allowed",
        "source_terminal_accepts_anything",
    }
