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


class TestOneAnswerForWhichCaseModel:
    """「这次运行用哪份 case 模型」**只能有一个判据**。

    原来这条链上有两个读法：verify 分解测试点走 `_find_case_model`（认识
    `config/`），覆盖率侧生成覆盖点走 `casemodel_path()`（**只认 `inputs/`**）。
    于是同一个 run 里两件事拿的是两份不同的模型，而**两边都觉得自己对** ——
    分解出来的测试点与生成的覆盖点对不上，却没有任何一处报错。
    """

    def _layout(self):
        from src.layers.l1_infrastructure import layout

        return layout

    def test_specs_adjacent_model_wins_over_the_front_draft(self, tmp_path, monkeypatch):
        """`specs/<模块>/casemodel.yaml`（人写模型最自然的位置）优先于 front 的草稿。"""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "specs" / "npu_sched").mkdir(parents=True)
        hand = tmp_path / "specs" / "npu_sched" / "casemodel.yaml"
        hand.write_text("version: '1'\n", encoding="utf-8")
        run = tmp_path / "output_x"
        (run / "inputs").mkdir(parents=True)
        (run / "inputs" / "casemodel.yaml").write_text("version: '1'\n", encoding="utf-8")

        got = self._layout().find_case_model({"design_name": "npu_sched"}, run)
        assert got == Path("specs") / "npu_sched" / "casemodel.yaml"

    def test_config_is_the_project_level_fallback(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "config" / "casemodel").mkdir(parents=True)
        (tmp_path / "config" / "casemodel" / "dut.yaml").write_text(
            "version: '1'\n", encoding="utf-8")
        run = tmp_path / "output_x"
        (run / "inputs").mkdir(parents=True)
        (run / "inputs" / "casemodel.yaml").write_text("version: '1'\n", encoding="utf-8")

        got = self._layout().find_case_model({"design_name": "dut"}, run)
        assert got == Path("config") / "casemodel" / "dut.yaml"

    def test_the_front_draft_is_the_last_resort(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        run = tmp_path / "output_x"
        (run / "inputs").mkdir(parents=True)
        (run / "inputs" / "casemodel.yaml").write_text("version: '1'\n", encoding="utf-8")
        assert self._layout().find_case_model({"design_name": "dut"}, run) == \
            self._layout().casemodel_path(run)

    def test_nothing_anywhere_returns_none_not_an_invented_path(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert self._layout().find_case_model({"design_name": "ghost"},
                                              tmp_path / "output_x") is None

    def test_all_three_readers_go_through_it(self):
        """verify 的两个写盘器 + coverage 的生成器，**都不许自己拼路径**。"""
        verify = Path("src/executors/verify/main.py").read_text(encoding="utf-8")
        coverage = Path("src/executors/coverage/main.py").read_text(encoding="utf-8")

        # verify：写 field_bins 的、写 DUT 探针的、写覆盖率计划的，都得走统一判据
        assert verify.count("_find_case_model(_spec_of(output_dir), output_dir)") == 3
        # coverage：不再直接读 casemodel_path
        assert "casemodel_path(output_dir)" not in coverage.replace(
            "from src.layers.l1_infrastructure.layout import casemodel_path", "")
        assert "find_case_model(spec, output_dir)" in coverage

    def test_verify_has_no_local_copy_of_the_rule(self):
        """verify 那份**转发**到 layout —— 本地再实现一份就又是两个判据了。"""
        src = Path("src/executors/verify/main.py").read_text(encoding="utf-8")
        start = src.index("def _find_case_model(")
        body = src[start:start + 900]
        assert "from src.layers.l1_infrastructure.layout import find_case_model" in body
        # 本地不许再挑候选（`candidates.append` 是旧实现的标志）
        assert "candidates.append" not in body


class TestSeedsReachTheRegression:
    """种子管理：**声明在模型里 → 计划里 → 回归的 count/SEED**。

    回归框架早就会按 `count` 展开、每条塞 `local_vars.SEED = base + i - 1`
    （`config.expand_count`）—— 缺的从来不是机制，而是"种子从哪来"。现在它来自
    **与 case 模型同批落盘的覆盖率计划**，回归只读不算。
    """

    NPU = Path("specs/npu_sched/casemodel.yaml")

    def _plan_dir(self, tmp_path):
        from src.tools.casemodel_tools.api import run_coverage_plan

        (tmp_path / "coverage").mkdir(parents=True, exist_ok=True)
        plan = run_coverage_plan(self.NPU.read_text(encoding="utf-8"), "npu_sched")
        (tmp_path / "coverage" / "coverage_plan.yaml").write_text(
            plan["plan_yaml"], encoding="utf-8")
        return tmp_path

    def test_the_plan_is_read_into_a_test_keyed_map(self, tmp_path):
        from src.tools.uvm_tools.tool_find_spec_yaml.main import _seed_plan

        sp = _seed_plan(self._plan_dir(tmp_path))
        assert len(sp) == 11
        # 种子 + 批次元数据（回归铺 test 时两样都要：种子给 count/SEED，
        # theme/priority 给 tags —— 分级回归就是按 p0..p3 筛的）
        assert {k: sp["npu_type_test"][k] for k in ("base", "count", "explore")} ==             {"base": 2001, "count": 15, "explore": 3}
        assert sp["npu_type_test"]["theme"] == "TH-B02"
        assert sp["npu_type_test"]["priority"] == "P0"

    def test_count_is_baseline_plus_explore(self, tmp_path):
        """探索种子**并进总次数** —— 跑法一样，只是目的不同。"""
        from src.tools.uvm_tools.tool_find_spec_yaml.main import (_seed_lines,
                                                                  _seed_plan)

        lines = _seed_lines("npu_type_test", _seed_plan(self._plan_dir(tmp_path)))
        assert "    count: 18" in lines          # 15 基线 + 3 探索
        assert "    variables: {SEED: 2001}" in lines

    def test_a_test_the_plan_does_not_know_keeps_count_one(self, tmp_path):
        """**不编一个种子出来** —— 没声明就照旧跑一条。"""
        from src.tools.uvm_tools.tool_find_spec_yaml.main import (_seed_lines,
                                                                  _seed_plan)

        assert _seed_lines("apb_uart_D_ADDR_0", _seed_plan(self._plan_dir(tmp_path))) \
            == ["    count: 1"]

    def test_no_plan_at_all_degrades_quietly(self, tmp_path):
        from src.tools.uvm_tools.tool_find_spec_yaml.main import (_seed_lines,
                                                                  _seed_plan)

        assert _seed_plan(tmp_path) == {}
        assert _seed_lines("anything", {}) == ["    count: 1"]

    def test_the_seed_reaches_the_simulator(self):
        """`count` 展开出来的 N 条若不把 SEED 送进 vsim，跑的是**同一组随机数** ——
        名字变了、跑的东西没变（`_seed_base` 的注释记着这个坑）。"""
        src = Path("src/tools/uvm_tools/tool_find_spec_yaml/main.py").read_text(
            encoding="utf-8")
        assert "+ntb_random_seed={{ SEED }}" in src

    def test_the_regression_generator_actually_consults_the_plan(self):
        src = Path("src/tools/uvm_tools/tool_find_spec_yaml/main.py").read_text(
            encoding="utf-8")
        assert "seed_plan = _seed_plan(output_dir)" in src
        # 每条 test 都得过 `_seed_lines`，不能有一条自己写死 count: 1
        assert "count: 1" not in src.replace("return [\"    count: 1\"]", "") \
            .replace('回归按默认 `count: 1` 跑', "") \
            .replace('计划里没有就 `count: 1`', "")


class TestThePlanIsWrittenWithTheCaseModel:
    """计划必须**与 case 模型同批**落盘 —— 回归在 ops 阶段就读它。"""

    def test_verify_writes_it_next_to_the_probe(self):
        src = VERIFY_MAIN.read_text(encoding="utf-8")
        assert "self._write_coverage_plan(output_dir)" in src
        # 与另两条覆盖率产物同一段（都在 find_spec_yaml 之后、jinja_render 之前）
        find = _line_of('call_tool("find_spec_yaml"')
        plan = _line_of("self._write_coverage_plan(output_dir")
        render = _line_of('call_tool("jinja_render"')
        assert find < plan < render

    def test_it_lands_as_coverage_plan_yaml(self, tmp_path):
        import shutil

        from src.executors.verify.main import VerifyExecutor

        (tmp_path / "inputs").mkdir(parents=True)
        shutil.copy("specs/npu_sched/casemodel.yaml",
                    tmp_path / "inputs" / "casemodel.yaml")
        VerifyExecutor()._write_coverage_plan(tmp_path)
        out = tmp_path / "coverage" / "coverage_plan.yaml"
        assert out.is_file()
        import yaml
        plan = yaml.safe_load(out.read_text(encoding="utf-8"))
        assert plan["summary"]["coverpoint_count"] == 12
        assert len(plan["batches"]) == 11


class TestBatchTestsAreRunnable:
    """批次要能在回归里**真跑起来** —— 光有种子不够，还得有个同名的 test 类。

    没有 `npu_type_test` 这个 UVM 类，`+UVM_TESTNAME=npu_type_test` 会撞
    `UVM_FATAL (INVTST) test not found`，而 **vsim 仍然 exit 0** ——
    于是"这一批跑不起来"被记成 pass，看不出来。
    """

    NPU = Path("specs/npu_sched/casemodel.yaml")

    def test_the_model_yields_one_class_per_batch(self):
        from src.tools.casemodel_tools.api import run_uvm_batches

        p = run_uvm_batches(self.NPU.read_text(encoding="utf-8"), "npu_sched")
        assert p["count"] == 11
        assert p["batches"][1]["name"] == "npu_type_test"
        assert p["batches"][1]["theme"] == "TH-B02"

    def test_a_batch_without_a_test_name_is_noted(self):
        from src.tools.casemodel_tools.api import run_uvm_batches
        import yaml

        model = yaml.safe_load(self.NPU.read_text(encoding="utf-8"))
        del model["themes"][0]["test"]
        out = run_uvm_batches(yaml.safe_dump(model, allow_unicode=True))
        assert out["count"] == 10
        assert any("没写 `test`" in n for n in out["notes"])

    def test_the_template_renders_one_class_per_batch(self):
        """与 `_attr_test` 同形的宏 —— **类名必须取自 `batches[].name`**。"""
        tpl = Path("src/tools/uvm_tools/tool_uvm/templates/environment_templates"
                   "/test_templates/test_batch.sv.j2")
        assert tpl.is_file(), "批次 test 模板不在 —— `environment.batches` 没人渲染"
        text = tpl.read_text(encoding="utf-8")
        assert "`define GEN_BATCH_TC" in text
        assert "`GEN_BATCH_TC({{ b.name }}" in text
        # 宏体内只能有 /* */ 注释（`//` 会吃掉行尾反斜杠，宏当场断掉）
        macro = text[text.index("`define GEN_BATCH_TC"):text.index("{% for")]
        assert "//" not in macro.replace("/*", "").replace("*/", "")

    def test_the_render_task_produces_it(self):
        src = Path("src/tools/uvm_tools/tool_uvm/gen_uvm.py").read_text(encoding="utf-8")
        assert "ENVIRONMENT_BATCH_TEST_TEMPLATES" in src
        assert "if environment.batches:" in src
        assert "_normalize_batches" in src

    def test_the_injection_carries_batches_into_env_yaml(self, tmp_path):
        import shutil

        from src.layers.l1_infrastructure.layout import casemodel_path
        from src.tools.uvm_tools.tool_find_spec_yaml.main import _casemodel_test_lines

        (tmp_path / "inputs").mkdir(parents=True)
        shutil.copy(self.NPU, casemodel_path(tmp_path))
        lines = _casemodel_test_lines(tmp_path)
        assert "  batches:" in lines
        assert any("npu_type_test" in ln for ln in lines)

    def test_the_regression_emits_one_test_per_batch(self):
        src = Path("src/tools/uvm_tools/tool_find_spec_yaml/main.py").read_text(encoding="utf-8")
        block = src[src.index("批次测试（**一条 = 一个 UVM_TEST = 一个批次/专题**）"):]
        block = block[:block.index("loopback 测试")]
        assert "_sim_run_cmd(dut_top, bname)" in block, \
            "+UVM_TESTNAME 必须是**批次名**，否则对不上生成的类"
        assert "_seed_lines(bname, seed_plan)" in block
