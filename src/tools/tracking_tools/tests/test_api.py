"""`run_tracking` 的契约。

钉三件事：
  · 正常 YAML → 两张表的行 + counts 形状对；
  · 失败（没路径 / 文件不在 / YAML 坏 / 顶层不是映射）→ 返回 `{"error"}`
    而不是抛异常（界面靠这个把话说清楚）；
  · 悬空的资产引用**不丢行**，只记账 —— 静默丢会让人误以为「这条测试点没资产」。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.tools.tracking_tools import run_tracking

GOOD = """\
project: demo
testpoints:
  - id: TP_001
    feature: 寄存器读写
    description: 回读一致
    priority: P0
    method: D
    status: done
    assets: [rtl_top, uvm_env]
  - id: TP_002
    feature: 中断
    assets: [missing_asset]
assets:
  - id: rtl_top
    type: rtl
    path: rtl/top.sv
    hash: abc123
    status: ok
    note: 顶层
  - id: uvm_env
    type: uvm_env
    path: env/top_env.sv
    status: ok
"""


def _write(tmp_path: Path, text: str, name: str = "tracking.yaml") -> str:
    target = tmp_path / name
    target.write_text(text, encoding="utf-8")
    return str(target)


class TestHappyPath:
    def test_shape(self, tmp_path):
        result = run_tracking(_write(tmp_path, GOOD))
        assert set(result) == {"project", "testpoints", "assets", "unresolved", "counts"}
        assert result["project"] == "demo"
        assert result["counts"] == {"testpoints": 2, "assets": 2, "unresolved": 1}

    def test_defaults_are_filled(self, tmp_path):
        """少写的键补默认值 —— 不因为漏一个字段就整份读不出来。"""
        result = run_tracking(_write(tmp_path, GOOD))
        tp2 = result["testpoints"][1]
        assert tp2["priority"] == "P1"      # 默认级别
        assert tp2["status"] == "planned"   # 默认状态
        assert tp2["id"] == "TP_002"        # id 保留

    def test_reverse_index_points_at_referencing_testpoints(self, tmp_path):
        """资产行反查引用了它的测试点 —— 界面联动靠这个。"""
        result = run_tracking(_write(tmp_path, GOOD))
        by_id = {a["id"]: a for a in result["assets"]}
        assert by_id["rtl_top"]["testpoint_refs"] == ["TP_001"]
        assert by_id["rtl_top"]["testpoints"] == "TP_001"
        assert by_id["uvm_env"]["testpoint_refs"] == ["TP_001"]

    def test_asset_refs_kept_as_list_for_linking(self, tmp_path):
        result = run_tracking(_write(tmp_path, GOOD))
        assert result["testpoints"][0]["asset_refs"] == ["rtl_top", "uvm_env"]
        # 显示串与清单串都在，界面不自己 split
        assert result["testpoints"][0]["assets"] == "rtl_top、uvm_env"


class TestDanglingReferences:
    def test_row_is_kept_not_dropped(self, tmp_path):
        result = run_tracking(_write(tmp_path, GOOD))
        assert [t["id"] for t in result["testpoints"]] == ["TP_001", "TP_002"]

    def test_dangling_is_recorded(self, tmp_path):
        result = run_tracking(_write(tmp_path, GOOD))
        assert result["unresolved"] == [{"testpoint": "TP_002", "asset": "missing_asset"}]
        assert result["testpoints"][1]["has_unresolved"] is True


class TestFailureIsLoud:
    def test_empty_path(self):
        assert "error" in run_tracking("")

    def test_missing_file(self):
        result = run_tracking("does/not/exist.yaml")
        assert "error" in result and "找不到" in result["error"]

    def test_directory_instead_of_file(self, tmp_path):
        assert "error" in run_tracking(str(tmp_path))

    def test_broken_yaml(self, tmp_path):
        result = run_tracking(_write(tmp_path, "project: [unclosed\n"))
        assert "error" in result

    def test_top_level_is_not_a_mapping(self, tmp_path):
        result = run_tracking(_write(tmp_path, "- just\n- a list\n"))
        assert "error" in result and "映射" in result["error"]

    def test_empty_file(self, tmp_path):
        assert "error" in run_tracking(_write(tmp_path, ""))

    def test_error_is_returned_not_raised(self):
        """契约：任何情况下都不抛 —— 界面靠返回值里的 `error` 说话。"""
        for bad in ("", "nope.yaml", "\x00"):
            assert isinstance(run_tracking(bad), dict)


class TestMissingSections:
    def test_only_testpoints(self, tmp_path):
        result = run_tracking(_write(tmp_path, "project: p\ntestpoints:\n  - id: T1\n"))
        assert result["counts"] == {"testpoints": 1, "assets": 0, "unresolved": 0}

    def test_empty_document_sections(self, tmp_path):
        result = run_tracking(_write(tmp_path, "project: p\n"))
        assert result["testpoints"] == [] and result["assets"] == []


@pytest.mark.parametrize("index", [0, 1])
def test_shipped_example_loads(tmp_path, index):
    """仓库里那份示例要能读进来 —— 它是清单默认指向的数据源。"""
    from src.tools.tracking_tools.tests import __file__ as pkg_file
    example = Path(pkg_file).resolve().parents[4] / "config" / "tracking" / "tracking.yaml"
    result = run_tracking(str(example))
    assert "error" not in result, result
    assert result["counts"]["testpoints"] > 0
    assert result["counts"]["assets"] > 0
