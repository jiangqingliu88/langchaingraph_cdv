"""清单契约 —— 本文件**不需要 Qt**，这正是「清单不依赖界面」的证据。"""
from __future__ import annotations

from pathlib import Path

import pytest

from ..config import default_manifest_path, resolve_input, resolve_manifest_path
from ..manifest import (ManifestError, builtin_manifest, describe, load_manifest,
                        load_manifest_text, try_load_manifest)


def test_shipped_manifest_parses():
    manifest = load_manifest(default_manifest_path())
    assert [m.id for m in manifest.enabled_modules()] == [
        # 七条 agent 线的产出总览（清单里的书写顺序）
        "design.output", "model.output", "ops.output",
        "ops.regression_status", "ops.regression_wave", "ops.regression_coverage",
        "coverage.output", "audit.output",
        "ide.ip_spec", "ide.manual_nodes",
        "coverage.excludes",
        "debug.sim_log", "debug.fingerprint", "debug.output",
        "verify.output", "verify.casemodel",
        # 流程与证据线：流程视图 + 编排 + 运行历史 + 证据 + 跟踪 + 对比 + 签核 + 趋势 + 决策 + 清单
        "flow.task", "flow.diagram", "flow.artifacts", "flow.pipeline", "flow.runs", "flow.evidence",
        "flow.tracking", "flow.todo", "flow.drafts", "flow.compare", "flow.signoff", "flow.trend",
        "flow.decision", "flow.manifest"]
    # flow 排在设计时之后、运行时之前（`order: 8`）—— 贯穿层是入口，不是附录
    assert [g.id for g in manifest.sorted_groups()] == [
        "ide", "flow", "design", "model", "verify", "ops",
        "coverage", "debug", "audit"]


def test_shipped_manifest_is_grouped_into_three_sections():
    """业务域 → 业务线 的三段：设计时 / 贯穿层 / 运行时。

    域的顺序由**域内最小 order** 决定 —— `ide`(5) 是流程上游排最前；
    贯穿层 `flow`(8) 排在运行时(10) **前面**：那一条线装的是任务总览、验证流程、
    运行历史、运行对比、签核判定 —— 一进界面就要用的**入口**，不是附录。
    """
    manifest = load_manifest(default_manifest_path())
    assert [(section, [g.id for g in groups]) for section, groups in manifest.sections()] == [
        ("设计时", ["ide"]),
        ("贯穿层", ["flow"]),
        ("运行时", ["design", "model", "verify", "ops",
                      "coverage", "debug", "audit"]),
    ]


def test_manifest_without_section_is_flat():
    """没写 `section` 的清单只得到一个空域 —— 导航树据此走平铺的老路。"""
    manifest = load_manifest_text(
        "groups:\n"
        "  - {id: a, title: A, order: 1}\n"
        "  - {id: b, title: B, order: 2}\n"
        "modules: []", source="<flat>")
    assert [(section, [g.id for g in groups]) for section, groups in manifest.sections()] == [
        ("", ["a", "b"])]


def test_unset_section_sorts_last():
    """没归类的域压在最后 —— 它是「还没归类」，不该插在真域前面。"""
    manifest = load_manifest_text(
        "groups:\n"
        "  - {id: loose, title: 散装, order: 1}\n"
        "  - {id: real, title: 有域, order: 2, section: 甲域}\n"
        "modules: []", source="<mixed>")
    assert [section for section, _ in manifest.sections()] == ["甲域", ""]


def test_shipped_manifest_module_inputs_point_at_real_files():
    """清单里写的 `input` 都得真的存在 —— 路径写错了界面只会安静地不加载。"""
    from ..config import resolve_input

    manifest_path = default_manifest_path()
    for spec in load_manifest(manifest_path).enabled_modules():
        if not spec.input:
            continue
        target = resolve_input(manifest_path, spec.input)
        assert target.exists(), f"{spec.id} 的 input 不存在：{target}"


def test_unknown_key_names_the_offending_field():
    """写错键名必须点名，而不是被静默忽略 —— 静默忽略会让人以为界面坏了。"""
    with pytest.raises(ManifestError) as info:
        load_manifest_text(
            "groups: [{id: a, title: A}]\n"
            "modules: [{id: x, title: X, group: a, factory: m:C, dock: bottom}]")
    assert "modules.0.dock" in str(info.value)


def test_dangling_group_is_rejected():
    with pytest.raises(ManifestError) as info:
        load_manifest_text(
            "groups: [{id: a, title: A}]\n"
            "modules: [{id: x, title: X, group: zzz, factory: m:C}]")
    message = str(info.value)
    assert "zzz" in message and "不在 groups 里" in message


def test_duplicate_module_id_is_rejected():
    with pytest.raises(ManifestError) as info:
        load_manifest_text(
            "groups: [{id: a, title: A}]\n"
            "modules:\n"
            "  - {id: x, title: X, group: a, factory: m:C}\n"
            "  - {id: x, title: Y, group: a, factory: m:D}")
    assert "id 重复" in str(info.value)


def test_duplicate_group_id_is_rejected():
    with pytest.raises(ManifestError) as info:
        load_manifest_text(
            "groups: [{id: a, title: A}, {id: a, title: B}]\nmodules: []")
    assert "groups 里 id 重复" in str(info.value)


def test_bad_area_value_is_rejected():
    with pytest.raises(ManifestError) as info:
        load_manifest_text(
            "groups: [{id: a, title: A}]\n"
            "modules: [{id: x, title: X, group: a, factory: m:C, area: middle}]")
    assert "modules.0.area" in str(info.value)


def test_empty_file_points_at_the_missing_content():
    with pytest.raises(ManifestError) as info:
        load_manifest_text("")
    assert "空" in str(info.value)


def test_missing_file_reports_the_path(tmp_path):
    missing = tmp_path / "nope.yaml"
    with pytest.raises(ManifestError) as info:
        load_manifest(missing)
    assert "nope.yaml" in str(info.value)


def test_try_load_returns_error_instead_of_raising():
    manifest, error = try_load_manifest(default_manifest_path())
    assert error is None and manifest is not None

    manifest, error = try_load_manifest(Path("does-not-exist.yaml"))
    assert manifest is None and isinstance(error, ManifestError)


def test_builtin_manifest_has_groups_but_no_modules():
    """兜底清单刻意是空的 —— 给假的模块列表会让人以为加载成功了。"""
    manifest = builtin_manifest()
    assert len(manifest.groups) == 3
    assert manifest.modules == []


def test_describe_counts_enabled_modules():
    manifest = load_manifest(default_manifest_path())
    assert "30 个模块" in describe(manifest)
    assert describe(None) == "清单：无"


class TestOrdering:
    """中央标签页的顺序 = 业务线 order 优先，然后才是模块 order。"""

    @staticmethod
    def _manifest():
        return load_manifest_text(
            "groups:\n"
            "  - {id: b, title: B, order: 20}\n"
            "  - {id: a, title: A, order: 10}\n"
            "modules:\n"
            "  - {id: a.late, title: A后, group: a, factory: m:C, order: 90}\n"
            "  - {id: b.early, title: B先, group: b, factory: m:C, order: 1}\n"
            "  - {id: a.first, title: A先, group: a, factory: m:C, order: 1}")

    def test_group_order_beats_module_order(self):
        assert [m.id for m in self._manifest().modules_in("center")] == [
            "a.first", "a.late", "b.early"]

    def test_modules_of_filters_by_group(self):
        manifest = self._manifest()
        assert [m.id for m in manifest.modules_of("a")] == ["a.first", "a.late"]
        assert manifest.module("b.early").title == "B先"
        assert manifest.module("nope") is None

    def test_disabled_modules_are_skipped(self):
        # id 刻意避开 on/off：YAML 1.1 会把它们解析成布尔值 True/False
        manifest = load_manifest_text(
            "groups: [{id: a, title: A}]\n"
            "modules:\n"
            "  - {id: keep, title: 开, group: a, factory: m:C, enabled: true}\n"
            "  - {id: drop, title: 关, group: a, factory: m:C, enabled: false}")
        assert [m.id for m in manifest.enabled_modules()] == ["keep"]
        assert [m.id for m in manifest.modules_in("center")] == ["keep"]


class TestPathResolution:
    def test_relative_input_is_relative_to_the_manifest(self, tmp_path):
        manifest_path = tmp_path / "config" / "workbench.yaml"
        resolved = resolve_input(manifest_path, "examples/demo.yaml")
        assert resolved == (tmp_path / "config" / "examples" / "demo.yaml").resolve()

    def test_absolute_input_passes_through(self, tmp_path):
        absolute = tmp_path / "elsewhere" / "demo.yaml"
        assert resolve_input(tmp_path / "m.yaml", str(absolute)) == absolute

    def test_blank_input_is_none_not_an_error(self, tmp_path):
        assert resolve_input(tmp_path / "m.yaml", "") is None
        assert resolve_input(tmp_path / "m.yaml", "   ") is None

    def test_manifest_path_falls_back_to_default(self, monkeypatch):
        monkeypatch.delenv("WORKBENCH_MANIFEST", raising=False)
        assert resolve_manifest_path(None) == default_manifest_path()
        assert resolve_manifest_path("") == default_manifest_path()

    def test_manifest_path_honours_env_var(self, monkeypatch, tmp_path):
        target = tmp_path / "custom.yaml"
        monkeypatch.setenv("WORKBENCH_MANIFEST", str(target))
        assert default_manifest_path() == target

    def test_explicit_path_beats_env_var(self, monkeypatch, tmp_path):
        monkeypatch.setenv("WORKBENCH_MANIFEST", str(tmp_path / "env.yaml"))
        given = tmp_path / "given.yaml"
        assert resolve_manifest_path(given) == given
