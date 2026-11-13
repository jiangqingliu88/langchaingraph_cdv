"""分级回归的目录裁剪 —— 每级的 build 目录只出现本级用例。

## 为什么要改

不裁剪时，每个 stage 的 build 都会铺出**全量** `sim.sh`（实测 p0 目录 244 个，
只跑 50 个）。人打开目录会以为"194 条用例没跑"—— 其实它们属于 p1/p2/p3。

裁剪之后，目录即本级用例集合；"本级未跑"与"其它级预生成"的歧义从源头消失。

**只对分级路径生效**：非分级调用仍生成全量树（可以换 `--tags` 复跑同一份目录）。
"""
from __future__ import annotations

from pathlib import Path

from src.orchestration_plane.l2.regression_tools.regression_framework.core.config import make_tag_matcher
from src.orchestration_plane.l2.regression_tools.regression_framework.generators.shell import ShellGenerator

CONFIG = {
    "variables": {"SEED": 1},
    "builds": [{"name": "b1", "top": "tb", "run_cmd": "echo build"}],
    "tests": [
        {"name": "t_p0", "build": "b1", "run_cmd": "echo p0", "tags": ["p0"]},
        {"name": "t_p1", "build": "b1", "run_cmd": "echo p1", "tags": ["p1"]},
        {"name": "t_both", "build": "b1", "run_cmd": "echo both", "tags": ["p0", "p1"]},
    ],
    "settings": {},
}


def _test_dirs(root: Path, build: str = "b1") -> set:
    d = root / f"build_{build}"
    return {p.name for p in d.iterdir() if p.is_dir() and p.name.startswith("test_")} \
        if d.is_dir() else set()


def test_without_filter_all_tests_are_generated(tmp_path):
    """非分级路径：保持原行为（全量树，便于换 tag 复跑）。"""
    ShellGenerator().generate(CONFIG, str(tmp_path), "mock")
    assert _test_dirs(tmp_path) == {"test_t_p0", "test_t_p1", "test_t_both"}


def test_stage_filter_prunes_to_the_stage(tmp_path):
    match = make_tag_matcher(CONFIG, "p0", None)
    ShellGenerator().generate(CONFIG, str(tmp_path), "mock", test_filter=match)
    # t_p1 不生成；t_p0 / t_both 都带 p0
    assert _test_dirs(tmp_path) == {"test_t_p0", "test_t_both"}


def test_build_scripts_are_still_generated(tmp_path):
    """裁剪只影响 **test 目录** —— build 脚本照旧（本级 test 依赖它）。"""
    match = make_tag_matcher(CONFIG, "p0", None)
    ShellGenerator().generate(CONFIG, str(tmp_path), "mock", test_filter=match)
    assert (tmp_path / "build_b1" / "build.sh").is_file()


def test_a_stage_with_no_matching_tests_generates_no_test_dirs(tmp_path):
    """没有任何用例的级 → 空目录而不是全量树（EMPTY 门才有意义）。"""
    match = make_tag_matcher(CONFIG, "p9", None)
    ShellGenerator().generate(CONFIG, str(tmp_path), "mock", test_filter=match)
    assert _test_dirs(tmp_path) == set()


def test_staged_run_passes_the_filter_and_normal_run_does_not(monkeypatch, tmp_path):
    """L1 的**分级**路径才裁剪；普通回归仍生成全量树。"""
    import yaml
    from src.runtime_plane.infrastructure.infrastructure import InfrastructureManager

    captured = {}

    class FakeGen:
        def generate(self, config, root_dir, mode, **kw):
            captured.update(kw)

    monkeypatch.setattr(
        "src.orchestration_plane.l2.regression_tools.regression_framework.generators.shell.ShellGenerator",
        lambda: FakeGen())

    reg = tmp_path / "regression.yaml"
    reg.write_text(yaml.safe_dump(CONFIG, allow_unicode=True), encoding="utf-8")

    mgr = InfrastructureManager(str(tmp_path / "out"))
    mgr.run_regression(reg_yaml=str(reg), mode="mock", tags="p0")
    assert captured.get("test_filter") is None      # 非分级：全量

    captured.clear()
    mgr._stage_tag = "p0"
    mgr.run_regression(reg_yaml=str(reg), mode="mock", tags="p0")
    assert captured.get("test_filter") is not None
    assert captured["test_filter"]("t_p0") and not captured["test_filter"]("t_p1")
