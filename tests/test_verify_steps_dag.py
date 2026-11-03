"""verify 内部 8 步顺序 —— 从“注释约定”变成“代码会检查”。

这些测试不跑 UVM：只钉住 DAG 声明、拓扑校验和执行期记录器。
顺序错一步的真实代价是**静默少产物**（bins 被清空 / 约束没进渲染），
所以这里值得多锁几层。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.executors.verify.steps_dag import (
    STEPS,
    STEP_NAMES,
    Step,
    StepOrderError,
    StepRecorder,
    validate_steps,
)


EXPECTED = (
    "coverage_plan", "find_spec_yaml", "testpoints_prebuild", "dut_channel",
    "env_cov_bins", "constraint_yaml", "association_report", "jinja_render",
)


def test_declared_dag_is_the_expected_linear_chain():
    assert STEP_NAMES == EXPECTED
    assert len(STEPS) == 8
    # 声明顺序必须与拓扑序一致（这就是 yaml/渲染之间的真实依赖）
    assert validate_steps() == EXPECTED


def test_each_step_after_the_first_has_a_real_dependency():
    for prev, cur in zip(STEPS, STEPS[1:]):
        assert cur.deps == (prev.name,), (
            f"{cur.name} 没有显式依赖 {prev.name} —— 顺序会退回注释约定")


def test_unknown_dependency_is_rejected():
    bad = (Step("a"), Step("b", deps=("missing",)))
    with pytest.raises(StepOrderError, match="不存在"):
        validate_steps(bad)


def test_cycle_is_rejected():
    bad = (Step("a", deps=("b",)), Step("b", deps=("a",)))
    with pytest.raises(StepOrderError, match="成环"):
        validate_steps(bad)


def test_duplicate_name_is_rejected():
    with pytest.raises(StepOrderError, match="重名"):
        validate_steps((Step("a"), Step("a")))


def test_recorder_rejects_a_step_before_its_dependency():
    rec = StepRecorder()
    rec.mark("coverage_plan")
    with pytest.raises(StepOrderError, match="前置未执行"):
        rec.mark("dut_channel")            # 跳过了 find_spec_yaml


def test_recorder_rejects_undeclared_step():
    with pytest.raises(StepOrderError, match="未声明"):
        StepRecorder().mark("not_a_step")


def test_recorder_finish_requires_every_step():
    rec = StepRecorder()
    rec.mark("coverage_plan")
    with pytest.raises(StepOrderError, match="未执行"):
        rec.finish()
    for name in EXPECTED[1:]:
        rec.mark(name)
    assert rec.finish() == EXPECTED


def test_recorder_detects_a_swap_of_independent_steps_only_if_asked():
    """DAG 只约束依赖；但 verify 这 7 步是线性写入，声明顺序也要能校验。"""
    steps = (Step("a"), Step("b"))
    rec = StepRecorder(steps)
    rec.mark("b")
    rec.mark("a")
    with pytest.raises(StepOrderError, match="声明顺序"):
        rec.assert_matches_declared_order()


def test_verify_executor_marks_steps_in_declared_order():
    """源码级守卫：`execute_task` 里 mark 的先后必须与 DAG 一致。"""
    src = Path("src/executors/verify/main.py").read_text(encoding="utf-8")
    positions = [src.index(f'steps.mark("{name}")') for name in EXPECTED]
    assert positions == sorted(positions)
    assert "steps.finish()" in src
