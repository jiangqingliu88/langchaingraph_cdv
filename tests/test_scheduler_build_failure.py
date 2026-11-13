"""编译失败必须阻止 test 执行 —— 否则会用旧 work library 跑出假结果。"""
from __future__ import annotations

from pathlib import Path

from src.orchestration_plane.l2.regression_tools.regression_framework.models.scheduler import (
    Scheduler,
)
from src.orchestration_plane.l2.regression_tools.regression_framework.models.task import (
    BuildTask,
    TestTask,
)


class _FakeStrategy:
    def __init__(self):
        self.calls = []

    def run_script(self, script, work_dir, name):
        self.calls.append(name)
        return name != "build_bad"


def test_tests_are_skipped_when_build_fails(tmp_path: Path):
    root = tmp_path / "reg"
    root.mkdir()
    strategy = _FakeStrategy()
    scheduler = Scheduler(strategy, parallel_builds=1)
    scheduler.add_task(BuildTask("build_bad", str(tmp_path / "b")))
    scheduler.add_task(TestTask("t1", str(tmp_path / "t"), "build_bad"))
    scheduler._generate_report = lambda _root: None
    scheduler._check_performance_degradation = lambda: None

    scheduler.run(str(root))

    assert "build_bad" in strategy.calls
    assert "t1" not in strategy.calls
    assert scheduler.task_map["t1"].status == "fail"
    assert scheduler.task_map["build_bad"].status == "fail"
