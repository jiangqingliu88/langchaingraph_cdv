"""`env_cov_bins.yaml` 的**落盘时机** —— 一行顺序错了，整条覆盖率模型静默失效。

## 这个文件存在的理由

verify 阶段要往 `inputs/yaml/uvm/env_cov_bins.yaml` 写两个键（策略包的语义 cross、
case 模型的边界 bin），供 `jinja_render` 渲染 `env_cov.sv.j2` 时用。

而 **`find_spec_yaml` 第一步就会清空那个目录**（它是该工具的私有产物目录）。原来的
落盘写在这一段之前 —— 于是：

    verify 开头   写 env_cov_bins.yaml
    find_spec_yaml 清空 inputs/yaml/uvm/*.yaml   ← 刚写的被删了
    jinja_render   渲染 env_cov.sv               ← 读不到，静默退回自动分箱

实测症状：`env_cov.sv` 里是 `v_zero/v_one/v_rest` 而不是模型的边界 bin，语义 cross
一个都没有，而**命令行与日志一切正常** —— 只有把渲染出来的 SV 打开看才发现。

所以这里钉住**顺序**（不是"有没有写"）：测试如果只跑 `_write_env_cov_bins` 会全绿，
而那正是当时漏掉的一类。
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

VERIFY_MAIN = Path("src/executors/verify/main.py")


def _source_lines() -> list:
    return VERIFY_MAIN.read_text(encoding="utf-8").splitlines()


def _line_of(needle: str, *, nth: int = 1) -> int:
    hits = [i for i, ln in enumerate(_source_lines(), 1) if needle in ln
            and not ln.lstrip().startswith("#")]
    assert len(hits) >= nth, f"源码里找不到第 {nth} 处 {needle!r}"
    return hits[nth - 1]


class TestTheWriteHappensAfterTheWipe:
    """落盘必须在 `find_spec_yaml` 之后、`jinja_render` 之前。"""

    def test_bins_are_written_between_the_two_tool_calls(self):
        find = _line_of('call_tool("find_spec_yaml"')
        write = _line_of("self._write_env_cov_bins(output_dir")
        render = _line_of('call_tool("jinja_render"')

        assert find < write < render, (
            f"顺序不对：find_spec_yaml@{find} / 写 bins@{write} / jinja_render@{render}。"
            f"find_spec_yaml 会**清空** inputs/yaml/uvm/*.yaml —— 写在它之前的 bins "
            f"会被删掉，env_cov 静默退回自动分箱。")

    def test_the_write_is_not_left_at_the_top_of_the_method(self):
        """反向断言：不许把落盘搬回策略包那一段（就是原来的错法）。

        策略包那段在方法开头，早于 `find_spec_yaml` —— 那里只该**攒** bin，不该写盘。
        """
        src = VERIFY_MAIN.read_text(encoding="utf-8")
        pack_block_start = src.index("策略包：按 design-style 加载")
        find_call = src.index('call_tool("find_spec_yaml"')
        early = src[pack_block_start:find_call]
        assert "_write_env_cov_bins" not in early, (
            "落盘又被搬回策略包那一段了 —— 那段在 find_spec_yaml 之前，会被清掉")


class TestWhatGetsWritten:
    """写下去的两个键分别服务什么。"""

    def _executor(self):
        from src.executors.verify.main import VerifyExecutor

        return VerifyExecutor()

    def test_model_bins_and_policy_crosses_both_land(self, tmp_path):
        import shutil

        spec = Path("specs/apb_uart/casemodel.yaml")
        (tmp_path / "inputs").mkdir(parents=True)
        shutil.copy(spec, tmp_path / "inputs" / "casemodel.yaml")

        self._executor()._write_env_cov_bins(
            tmp_path, [{"name": "cr_x", "signals": ["paddr", "pwrite"]}])
        data = json.loads((tmp_path / "inputs" / "yaml" / "uvm"
                           / "env_cov_bins.yaml").read_text(encoding="utf-8"))

        # 键名必须是 `cov_bins` —— 用错名字会让 gen_uvm 的 schema 检查报 error
        # 并 SystemExit，之后任何一次渲染都被它挡住（实测）
        assert "cov_bins" in data and data["cov_bins"][0]["name"] == "cr_x"
        assert [b["value"] for b in data["field_bins"]["paddr"]] == [0, 3, 4, 31, 32, 255]

    def test_no_model_still_writes_the_policy_crosses(self, tmp_path):
        """没有 case 模型是**降级**不是失败 —— 语义 cross 那条路不该被一起丢掉。"""
        self._executor()._write_env_cov_bins(tmp_path, [{"name": "cr_y"}])
        data = json.loads((tmp_path / "inputs" / "yaml" / "uvm"
                           / "env_cov_bins.yaml").read_text(encoding="utf-8"))
        assert data["cov_bins"] == [{"name": "cr_y"}]
        assert "field_bins" not in data

    def test_a_broken_write_does_not_raise(self, tmp_path):
        """落盘失败只记日志 —— 它不该拦住整个 env 生成（那时连覆盖率都没有了）。"""
        blocker = tmp_path / "inputs"
        blocker.write_text("我是文件不是目录", encoding="utf-8")
        self._executor()._write_env_cov_bins(tmp_path, [])   # 不抛即通过


class TestTheSchemaAcceptsBothKeys:
    """写下去的键必须过 `uvm_config.schema.json` —— 不过就是 **SystemExit**。

    那份 schema 是 `additionalProperties: false`：多一个没登记的键，`UVMGenerator.run()`
    的 schema 检查就报 error 并 `SystemExit`，**之后任何一次渲染都被它挡住**。
    实测：加 `field_bins` 时正是撞在这里，端到端直接挂在 `jinja_render` 之前
    （`schema_report.txt: unknown_property @ env_cov_bins.yaml::field_bins`）。

    所以"写端加了键"必须与"schema 登记了它"同一次提交 —— 这条测试就是那个约束。
    """

    def _check(self, tmp_path, payload):
        import shutil

        from src.tools.uvm_tools.tool_uvm.schema_check import SchemaChecker

        (tmp_path / "inputs" / "yaml" / "uvm").mkdir(parents=True)
        shutil.copy(Path("specs/apb_uart/casemodel.yaml"),
                    tmp_path / "inputs" / "casemodel.yaml")
        from src.executors.verify.main import VerifyExecutor

        VerifyExecutor()._write_env_cov_bins(tmp_path, payload)
        return SchemaChecker().check(
            [tmp_path / "inputs" / "yaml" / "uvm" / "env_cov_bins.yaml"])

    def test_the_full_payload_passes_the_schema(self, tmp_path):
        issues = self._check(tmp_path, [{"name": "cr_x", "signals": ["paddr"]}])
        assert not issues, f"schema 不认这几个键（渲染会被 SystemExit 挡住）：{issues}"

    def test_the_schema_registers_the_new_key(self):
        """直接查 schema —— 光看"这次过了"挡不住以后有人删掉那段定义。"""
        import json

        schema = json.loads(Path(
            "src/tools/uvm_tools/tool_uvm/schema/uvm_config.schema.json"
        ).read_text(encoding="utf-8"))
        assert "field_bins" in schema["properties"]
        assert "coverFieldBin" in schema["$defs"]


class TestTheTemplateStillReadsBothKeys:
    def test_field_bins_key_is_read_by_gen_uvm(self):
        """写端与读端**两个键名**要对得上 —— 对不上就是"写了但没人读"。"""
        src = Path("src/tools/uvm_tools/tool_uvm/gen_uvm.py").read_text(encoding="utf-8")
        assert 'data.get("field_bins")' in src
        assert 'coverage_field_bins' in src

    def test_the_template_uses_the_model_bins(self):
        tpl = Path("src/tools/uvm_tools/tool_uvm/templates/environment_templates"
                   "/env_cov.sv.j2").read_text(encoding="utf-8")
        assert "coverage_field_bins" in tpl
        # `| default({})` 不能少：渲染走 StrictUndefined，缺键会让整份渲染失败
        assert "coverage_field_bins | default({})" in tpl


class TestTheTwoSamplingChannelsSplit:
    """两条采样通道各写各的产物 —— 分不清就会给采不到的信号生成覆盖率。

    monitor 的事务通道只看得到**激励侧**；DUT 的内部状态与输出端口只有 bind
    进 DUT 才看得见。`sample: stimulus` 的走 `env_cov_bins.yaml`，
    `sample: dut` 的走 `coverage/dut_probe.sv`。
    """

    NPU = Path("specs/npu_sched/casemodel.yaml")
    APB = Path("specs/apb_uart/casemodel.yaml")

    def _executor(self):
        from src.executors.verify.main import VerifyExecutor

        return VerifyExecutor()

    def test_stimulus_only_goes_to_env_cov_bins(self, tmp_path):
        import shutil

        (tmp_path / "inputs").mkdir(parents=True)
        shutil.copy(self.APB, tmp_path / "inputs" / "casemodel.yaml")
        ex = self._executor()
        fb = ex._case_model_field_bins(tmp_path)
        assert set(fb) == {"paddr", "pwrite", "pwdata"}   # apb 全走事务通道

        ex._write_coverage_probe(tmp_path)
        assert not (tmp_path / "coverage" / "dut_probe.sv").exists()

    def test_dut_sourced_goes_to_the_probe_not_field_bins(self, tmp_path):
        """NPU 那 12 个信号在 env_cov 里**一个都不可见** —— 塞进 field_bins
        只会让模板生成一堆引用不到信号的 bin。"""
        import shutil

        (tmp_path / "inputs").mkdir(parents=True)
        shutil.copy(self.NPU, tmp_path / "inputs" / "casemodel.yaml")
        ex = self._executor()
        assert ex._case_model_field_bins(tmp_path) == {}

        ex._write_coverage_probe(tmp_path)
        probe = tmp_path / "coverage" / "dut_probe.sv"
        assert probe.is_file()
        text = probe.read_text(encoding="utf-8")
        assert "bind npu_sched" in text and "queue_level" in text
        assert "input logic clk," in text and "input logic rst_n," in text

    def test_range_and_illegal_bins_never_reach_env_cov(self, tmp_path):
        """`env_cov.sv.j2` 的 bin 语法只支持 `{v}` / `{[a:b]}`，**没有 illegal 的位置**。

        区间仓与非法仓留给探针那份 —— 那份才是完整的覆盖group。
        """
        import shutil

        (tmp_path / "inputs").mkdir(parents=True)
        shutil.copy(self.NPU, tmp_path / "inputs" / "casemodel.yaml")
        assert self._executor()._case_model_field_bins(tmp_path) == {}

    def test_no_case_model_writes_nothing(self, tmp_path):
        ex = self._executor()
        assert ex._case_model_field_bins(tmp_path) == {}
        ex._write_coverage_probe(tmp_path)
        assert not (tmp_path / "coverage").exists()


class TestTheProbeGetsCompiled:
    """探针必须**进得了 filelist** —— 不进就是又一份"看着有、从没编译过"的产物。"""

    def test_the_filelist_collects_it_after_the_rtl(self, tmp_path):
        from src.tools.lib.filelist import build_filelist_for_tb

        out = tmp_path / "output_x"
        (out / "rtl").mkdir(parents=True)
        (out / "rtl" / "dut.sv").write_text("module dut; endmodule\n", encoding="utf-8")
        (out / "coverage").mkdir()
        (out / "coverage" / "dut_probe.sv").write_text("// probe\n", encoding="utf-8")
        (out / "coverage" / "coverage_points.json").write_text("{}", encoding="utf-8")

        fl = build_filelist_for_tb(out, [], "dut_env").read_text(encoding="utf-8")
        assert "dut_probe.sv" in fl
        # `bind <dut_module>` 要求目标模块已声明 —— 探针必须排在 RTL 之后
        assert fl.index("dut.sv") < fl.index("dut_probe.sv")

    def test_non_sv_files_in_coverage_are_not_collected(self, tmp_path):
        """`coverage/` 里还躺着 json —— 一股脑收进来是给 vlog 塞垃圾。"""
        from src.tools.lib.filelist import build_filelist_for_tb

        out = tmp_path / "output_y"
        (out / "coverage").mkdir(parents=True)
        (out / "coverage" / "coverage_points.json").write_text("{}", encoding="utf-8")
        fl = build_filelist_for_tb(out, [], "dut_env").read_text(encoding="utf-8")
        assert "coverage_points.json" not in fl


class TestASimThatNeverRanIsNotAPass:
    """`sim_vsim.log` **不存在**时，判据必须判 FAIL —— 不能反过来判成通过。

    原来的判据是 `! grep -qE "<错>" sim_vsim.log`：日志不在时 `grep` 自己报错退出
    （非零），`!` 一取反就成了**通过**。于是"vsim 压根没起来"被记成 pass。

    实测踩过：环境里 vsim 崩了（连 `sim_vsim.log` 都没生成），一整轮回归全绿、
    覆盖率 0%，而每条用例的 `status.env` 都是 pass —— 看起来一切正常。

    修法是在 grep 之前加一句 `[ -s sim_vsim.log ] &&`：**先要求日志非空**，
    再谈里面有没有错。
    """

    RUN_CMD = Path("src/tools/uvm_tools/tool_find_spec_yaml/main.py")

    def test_the_verdict_requires_a_nonempty_log_first(self):
        src = self.RUN_CMD.read_text(encoding="utf-8")
        grep_at = src.index('! grep -qE "UVM_ERROR')
        guard = src.rindex("[ -s sim_vsim.log ]", 0, grep_at)
        assert guard > 0, "判据前没有 `[ -s sim_vsim.log ] &&` —— 日志缺失会被判成 pass"

    @pytest.mark.parametrize("content,expect_fail", [
        (None, True),        # 文件不存在
        ("", True),          # 空文件
        ("# 一切正常\n", False),
        ("# Errors: 2, Warnings: 0\n", True),
        ("# FATAL ERROR while loading design\n", True),
    ])
    def test_the_shell_predicate_matches_intent(self, tmp_path, content, expect_fail):
        import subprocess

        log = tmp_path / "sim_vsim.log"
        if content is not None:
            log.write_text(content, encoding="utf-8")
        # 与生成器里那句同形（`[ -s ] &&` 是这一条的全部要点）
        cmd = ('[ -s sim_vsim.log ] && '
               '! grep -qE "UVM_ERROR : *[1-9]|UVM_FATAL : *[1-9]'
               '|FATAL ERROR|Errors: *[1-9]" sim_vsim.log')
        r = subprocess.run(["sh", "-c", cmd], cwd=str(tmp_path),
                           capture_output=True, text=True)
        assert (r.returncode != 0) is expect_fail, (content, r.returncode)
