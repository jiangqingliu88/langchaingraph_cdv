"""LLM 修复的**写盘闸门** —— 不许整份重写 `gen_uvm` 生成的文件。

## 这个文件存在的理由

loopback 的 `<ag>_loopback_scb.sv` 是**模板生成物**，但 `apply_llm_fixes` 原来
无条件 `write_text` —— 每轮 LLM 拿到 500 字 sim log 就把整份重写一遍。实测三轮
产出三份各不相同的文件（行数 131 / 182 / 156，且**一份都不含**模板自带的
`SCB_LOOP_PASS` 标记），loopback 结果 7/7 → 4/7 → 5/7。

loopback 是分级回归第一道门，它挂了后面全不跑。所以症状是"每轮死在不同地方"，
**跑通与否由那轮 LLM 写了什么决定，而不是由代码决定**。

这里钉的就是那条闸门：生成物的骨架（`pragma custom` 之外）不许被 LLM 改。
"""
from __future__ import annotations

import pytest

#: 一份**带生成 banner** 的假生成物（形状照 `gen_uvm` 的产物：banner + 类体）
GENERATED = """\
// ════════════════════════════════════════════════════════════════
// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域
// ════════════════════════════════════════════════════════════════

class apb_loopback_scb extends uvm_scoreboard;
  // pragma custom body begin
  // pragma custom body end
endclass
"""

#: 人手写的（**没有** banner）—— 闸门不该管它
HANDWRITTEN = """\
class my_helper;
  int x;
endclass
"""


def _payload(tag: str, body: str) -> str:
    return f"===FILE:{tag}===\n{body}\n"


class TestTheGate:
    def test_a_wholesale_rewrite_of_a_generated_file_is_refused(self, tmp_path):
        """**核心那条**：LLM 整份重写生成物 → 原文件必须一字不改。"""
        from src.tools.lib.llm_refine import apply_llm_fixes

        f = tmp_path / "apb_loopback_scb.sv"
        f.write_text(GENERATED, encoding="utf-8")
        evil = ('// ════════════════════════════════════════════════════════════════\n'
                '// 自动生成 (tool_uvm v0.1.0) — 请勿直接修改；自定义代码写入 pragma custom 区域\n'
                '// ════════════════════════════════════════════════════════════════\n'
                'class apb_loopback_scb extends uvm_scoreboard;\n'
                '  virtual function void do_compare(apb_master_seq_item exp);\n'
                '  endfunction\nendclass\n')

        fixed = apply_llm_fixes(_payload("scoreboard", evil), {"scoreboard": f})

        assert fixed == 0, "整份重写被放行了 —— 闸门没生效"
        assert getattr(apply_llm_fixes, "refused", 0) == 1, "拒绝了却没计数"
        assert f.read_text(encoding="utf-8") == GENERATED, "原文件被改动了"

    def test_a_write_into_a_custom_region_is_allowed(self, tmp_path):
        """**只动 `pragma custom` 区域** → 放行（那是留给人的地方）。"""
        from src.tools.lib.llm_refine import apply_llm_fixes

        f = tmp_path / "x_scb.sv"
        f.write_text(GENERATED, encoding="utf-8")
        edited = GENERATED.replace(
            "  // pragma custom body begin\n  // pragma custom body end",
            "  // pragma custom body begin\n  int my_counter = 7;\n"
            "  // pragma custom body end")

        fixed = apply_llm_fixes(_payload("scoreboard", edited), {"scoreboard": f})

        # 写盘前会 `code.strip()`（既有行为，去尾换行）—— 比较时就按它比
        assert fixed == 1 and f.read_text(encoding="utf-8") == edited.strip()

    def test_handwritten_files_are_not_gated(self, tmp_path):
        """**没有 banner 的文件**不受这条闸门约束 —— 它本来就是给人改的。"""
        from src.tools.lib.llm_refine import apply_llm_fixes

        f = tmp_path / "my_helper.sv"
        f.write_text(HANDWRITTEN, encoding="utf-8")
        # 注意要 >50 字节：`apply_llm_fixes` 对过短的片段本来就判 "short tag"
        new = "class my_helper;\n" + "  int y = 42;   // 手写文件，该被放行\n" * 3 + "endclass\n"

        assert apply_llm_fixes(_payload("helper", new), {"helper": f}) == 1
        assert f.read_text(encoding="utf-8") == new.strip()

    def test_a_new_file_is_written(self, tmp_path):
        """目标还不存在（没有原文可比）→ 照写 —— 闸门管的是"覆盖生成物"。"""
        from src.tools.lib.llm_refine import apply_llm_fixes

        f = tmp_path / "brand_new.sv"
        body = "class brand_new;\n" + "  // pad\n" * 12 + "endclass\n"
        assert apply_llm_fixes(_payload("new", body), {"new": f}) == 1

    def test_refusal_is_reported_apart_from_no_output(self, tmp_path):
        """拒绝**不该**被报成 "LLM parse failed" —— 那会让人去 prompt 上找原因。"""
        from src.tools.lib import llm_refine

        assert hasattr(llm_refine.apply_llm_fixes, "refused"), \
            "拒绝计数没暴露给调用方 —— 外面只能当成解析失败"


class TestThereIsExactlyOneWriteExit:
    """**闸门写在"某条路径里"等于没写** —— 这里钉死"只有一个写盘出口"。

    实测踩过：第一版只闸了 `apply_llm_fixes`（仿真路径），漏了
    `llm_refine_compile_errors`（编译路径）自己的 `write_text`。结果编译失败时
    那条暗路把 SCB 整份重写成了模板与 LLM 的**混合体**（`compare_one` + `pstrb`
    都不是模板里的东西）→ `act.pstrb` 找不到 → `-mfcu` 连带整个 work 库注册塌掉
    → `[INVTST]` → loopback 断在第一道门。

    这条不是"测某个函数"，是**测文件结构**：源码里除 `gated_write` 外不许再有
    `write_text`。谁再开一条暗路，这里就红。
    """

    def test_only_gated_write_writes_files(self):
        import re
        from pathlib import Path as _P
        import src.tools.lib.llm_refine as m

        src = _P(m.__file__).read_text(encoding="utf-8")
        # 去掉三引号块（docstring 里会**讲**这件事，那不是写盘出口 —— 实测误判过）
        src = re.sub(r'""".*?"""', "", src, flags=re.DOTALL)
        lines = src.splitlines()
        # 定位 gated_write 的函数体范围（到下一个顶层 def 为止）
        start = next(i for i, l in enumerate(lines) if l.startswith("def gated_write("))
        end = next((i for i in range(start + 1, len(lines))
                    if lines[i].startswith("def ")), len(lines))

        offenders = []
        for i, line in enumerate(lines):
            if "write_text(" not in line:
                continue
            code = re.sub(r"#.*$", "", line)              # 去掉行尾注释
            if "write_text(" not in code:
                continue                                  # 只是注释里提到
            if not (start <= i < end):
                offenders.append(f"{i + 1}: {line.strip()}")
        assert not offenders, (
            "`llm_refine` 里出现了 `gated_write` 之外的写盘出口 —— "
            f"闸门会被绕过：{offenders}")

    def test_both_known_paths_go_through_it(self):
        """两条已知路径都必须调 `gated_write`（漏一条就是实测踩过的那次）。"""
        import inspect
        from src.tools.lib import llm_refine as m

        for fn in (m.apply_llm_fixes, m.llm_refine_compile_errors):
            body = inspect.getsource(fn)
            assert "gated_write(" in body, f"{fn.__name__} 绕过了写盘闸门"


class TestTheBannerMarkerStaysInStepWithGenUvm:
    """复刻的正则/banner 必须与 `gen_uvm`（真相源）一致 —— 改一边漏一边要红。"""

    def test_banner_matches_the_real_generated_files(self):
        """拿**真盘上**的生成物验 banner —— 不是拿我自己编的字符串验。"""
        from pathlib import Path

        samples = []
        for run in sorted(Path(".").glob("output_jiang_*/agents/*/loopback/*_loopback_env.sv")):
            samples.append(run)
            if len(samples) >= 3:
                break
        if not samples:
            pytest.skip("盘上没有历史 run 的生成物可验")

        from src.tools.lib.llm_refine import _is_generated_file
        for s in samples:
            assert _is_generated_file(s.read_text(encoding="utf-8", errors="replace")), \
                f"{s} 是生成物，但 banner 没被认出来"

    def test_the_custom_marker_matches_gen_uvm(self):
        """`_CUSTOM_MARKER` 与 `gen_uvm.REGION_MARKER` 对同一批样例判定一致。"""
        from src.tools.lib.llm_refine import _CUSTOM_MARKER
        from src.tools.uvm_tools.tool_uvm.gen_uvm import REGION_MARKER

        for line in ("  // pragma custom body begin",
                     "// pragma custom template end",
                     "  //   pragma   custom   x   begin  ",
                     "  // not a marker",
                     "  int x = 1;"):
            mine = _CUSTOM_MARKER.match(line)
            theirs = REGION_MARKER.match(line)
            assert bool(mine) == bool(theirs), f"判定不一致：{line!r}"
            if mine and theirs:
                assert mine.group(1, 2) == theirs.group(1, 2), f"捕获组不一致：{line!r}"
