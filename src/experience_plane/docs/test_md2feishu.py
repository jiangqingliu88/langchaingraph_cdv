"""md2feishu 单元测试 —— 转换契约 + 幂等性"""
import pytest

from src.experience_plane.docs.md2feishu import convert, main


def _c(text, note=False):
    return convert(text, src_name="x.md", note=note)


class TestTransforms:
    def test_heading_inline_code_stripped(self):
        # 只去掉反引号；残留的 $ 不擅自改，由 test_heading_with_dollar_warns 报出
        out, _ = _c("### 1.1 路径基准：`Sourceme` 与 `$WORK_PATH`\n")
        assert out.splitlines()[0] == "### 1.1 路径基准：Sourceme 与 $WORK_PATH"

    def test_heading_with_dollar_warns(self):
        _, w = _c("### 1.1 与 `$WORK_PATH`\n")
        assert any("标题有裸露的 $" in x for x in w)

    def test_relative_link_becomes_code(self):
        out, _ = _c("- [readme.md](readme.md) — 字段说明\n")
        assert out.splitlines()[0] == "- `readme.md` — 字段说明"

    def test_absolute_link_kept(self):
        src = "见 [Claude Code](https://claude.com/claude-code) 文档\n"
        out, _ = _c(src)
        assert out == src

    def test_prose_with_dollar_inside_code_is_safe(self):
        out, w = _c("一律以 `$WORK_PATH` 为根。\n")
        assert not w
        assert "`$WORK_PATH`" in out

    def test_bare_dollar_in_prose_warns(self):
        _, w = _c("价格是 $100 起步\n")
        assert any("正文有裸露的 $" in x for x in w)

    def test_bare_angle_tag_warns(self):
        # 刻意保守：`<3.13` 按 HTML 规则不算标签（标签名须以字母开头），
        # 但飞书解析器未必规矩，一律报出来让人定夺
        _, w = _c("依赖 Python ≥3.10 <3.13 与 pyyaml\n")
        assert any("<xxx" in x for x in w)
        _, w2 = _c("见 <name>_pkg 那个包\n")
        assert any("<xxx" in x for x in w2)
        # 比较运算有空格 → 不是标签起始，不报
        _, w3 = _c("满足 a < b 的关系\n")
        assert not any("<xxx" in x for x in w3)

    def test_code_block_untouched(self):
        src = "```\n### not a heading `kept`\n$WORK_PATH\n```\n"
        out, w = _c(src)
        assert out == src
        assert not w


class TestNote:
    def test_note_inserted_after_first_paragraph(self):
        out, _ = _c("# 标题\n\n正文一段。\n\n## 小节\n", note=True)
        lines = out.split("\n")
        assert lines[0] == "# 标题"
        assert "的飞书专用版" in out
        assert out.index("的飞书专用版") < out.index("## 小节")

    def test_note_not_inserted_when_disabled(self):
        out, _ = _c("# 标题\n\n正文。\n", note=False)
        assert "飞书专用版" not in out


class TestIdempotent:
    def test_convert_twice_is_identical(self):
        src = "# 标题\n\n正文 see `x`.\n\n## A\n\n- [rel.md](rel.md) — y\n"
        once, _ = _c(src, note=True)
        twice, _ = _c(once, note=True)
        assert twice == once

    def test_note_not_duplicated(self):
        once, _ = _c("# 标题\n\n正文。\n", note=True)
        twice, _ = _c(once, note=True)
        assert twice.count("的飞书专用版") == 1


class TestCli:
    def test_check_clean_returns_zero(self, tmp_path):
        p = tmp_path / "a.md"
        p.write_text("# T\n\n正文 `x`。\n", encoding="utf-8")
        assert main(["-i", str(p), "--check", "-q"]) == 0

    def test_check_dirty_returns_one(self, tmp_path):
        p = tmp_path / "b.md"
        p.write_text("# T\n\n价格 $5\n", encoding="utf-8")
        assert main(["-i", str(p), "--check", "-q"]) == 1

    def test_writes_default_output(self, tmp_path):
        p = tmp_path / "c.md"
        p.write_text("# T\n\n正文。\n", encoding="utf-8")
        assert main(["-i", str(p), "-q"]) == 0
        assert (tmp_path / "c.feishu.md").exists()

    def test_missing_input_returns_two(self, tmp_path):
        assert main(["-i", str(tmp_path / "nope.md"), "-q"]) == 2
