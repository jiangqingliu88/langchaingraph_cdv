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
    进 DUT 才看得见。`sample: stimulus` 的走 `env_cov_bins.yaml` 的 `field_bins`，
    `sample: dut` 的走 `coverage/<模块>_cov_if.sv`（bind 的接口）+ `dut_bins`。
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

        assert ex._write_coverage_dut_channel(tmp_path) == {}
        cov = tmp_path / "coverage"
        assert not cov.exists() or not list(cov.glob("*.sv"))

    def test_dut_sourced_goes_to_the_interface_not_field_bins(self, tmp_path):
        """NPU 那 12 个信号在 env_cov 的事务通道里**一个都不可见** —— 塞进
        field_bins 只会让模板生成一堆引用不到信号的 bin。"""
        import shutil

        (tmp_path / "inputs").mkdir(parents=True)
        shutil.copy(self.NPU, tmp_path / "inputs" / "casemodel.yaml")
        ex = self._executor()
        assert ex._case_model_field_bins(tmp_path) == {}

        dut = ex._write_coverage_dut_channel(tmp_path)
        assert dut["dut_if"]["type"] == "npu_sched_cov_if"
        iface = tmp_path / "coverage" / "npu_sched_cov_if.sv"
        assert iface.is_file()
        text = iface.read_text(encoding="utf-8")
        assert "bind npu_sched npu_sched_cov_if u_npu_sched_cov_if" in text
        assert "queue_level" in text
        # 时钟与复位也是**端口** —— 组件靠它们时钟沿采样 + 复位屏蔽
        assert "input logic clk," in text and "input logic rst_n," in text
        # bins 表随身份一起交出去（模板出 `cg_dut` 要用）
        assert set(dut["dut_bins"]) >= {"queue_level", "dep_type"}

    def test_dut_bins_carry_ranges_and_illegal_bins(self, tmp_path):
        """`field_bins` 只表达得了单个整数；DUT 侧需要**区间**与**非法仓**。

        区间：水位 0-32 要分档（`{[1:7]}`），一个整数说不出来。
        非法仓：`illegal_bins` 命中即报错 —— 它必须在 `cg_dut` 里有位置。
        """
        import shutil

        (tmp_path / "inputs").mkdir(parents=True)
        shutil.copy(self.NPU, tmp_path / "inputs" / "casemodel.yaml")
        dut = self._executor()._write_coverage_dut_channel(tmp_path)

        lvl = {b["name"]: b for b in dut["dut_bins"]["queue_level"]}
        assert lvl["low"]["value"] == "[1:7]"          # 区间，不是整数
        assert lvl["illegal_over"]["illegal"] is True

    def test_no_case_model_writes_nothing(self, tmp_path):
        ex = self._executor()
        assert ex._case_model_field_bins(tmp_path) == {}
        assert ex._write_coverage_dut_channel(tmp_path) == {}
        assert not (tmp_path / "coverage").exists()


class TestTheDutChannelIsWiredIntoTheEnv:
    """**同一个信号只能有一个 covergroup 采它。**

    DUT 通道走「bind 的接口 + env 组件」，上一版管道走的是「自带 covergroup 的
    独立探针」。两个同时挂在 filelist 里 = 同一个信号被采两遍：`vcover` 报表里
    多一个 covergroup，签核的"功能覆盖率"被自己搅浑。所以切换通道时要把上一版
    的产物**清掉**，而且要**说出来**。
    """

    NPU = Path("specs/npu_sched/casemodel.yaml")

    def _run_dir(self, tmp_path):
        import shutil

        (tmp_path / "inputs").mkdir(parents=True)
        shutil.copy(self.NPU, tmp_path / "inputs" / "casemodel.yaml")
        return tmp_path

    def test_a_stale_probe_is_retired(self, tmp_path):
        from src.executors.verify.main import VerifyExecutor

        run = self._run_dir(tmp_path)
        (run / "coverage").mkdir()
        (run / "coverage" / "dut_probe.sv").write_text("// old\n", encoding="utf-8")

        VerifyExecutor()._write_coverage_dut_channel(run)
        assert not (run / "coverage" / "dut_probe.sv").exists(), \
            "上一版的探针还在 —— 它和接口采同一批信号，会重复计量"
        assert (run / "coverage" / "npu_sched_cov_if.sv").is_file()

    def test_the_identity_lands_in_the_contract_file(self, tmp_path):
        """身份必须并进 `env_cov_bins.yaml` —— env_cov 与 tb_top **都读那一份**。"""
        import json

        from src.executors.verify.main import VerifyExecutor

        run = self._run_dir(tmp_path)
        ex = VerifyExecutor()
        dut = ex._write_coverage_dut_channel(run)
        ex._write_env_cov_bins(run, [], dut)

        data = json.loads((run / "inputs" / "yaml" / "uvm" / "env_cov_bins.yaml")
                          .read_text(encoding="utf-8"))
        assert data["dut_if"]["type"] == "npu_sched_cov_if"
        assert data["dut_if"]["instance"] == "u_npu_sched_cov_if"
        assert data["dut_bins"]

    def test_the_schema_registers_the_new_keys(self):
        """schema 是 `additionalProperties: false` —— 没登记就是 **SystemExit**，
        之后任何一次渲染都被它挡住。实测加 `dut_if` 时正是撞在这里。"""
        import json

        schema = json.loads(Path(
            "src/tools/uvm_tools/tool_uvm/schema/uvm_config.schema.json"
        ).read_text(encoding="utf-8"))
        assert {"dut_if", "dut_bins"} <= set(schema["properties"])
        assert "dutCoverBin" in schema["$defs"]

    def test_both_templates_read_the_one_contract(self):
        """env_cov 与 tb_top **读同一个键**（`coverage_dut_if`）。

        单边有是有害的：组件声明了 `virtual <type>` 而 tb_top 没挂 →
        句柄永远为空 → 覆盖率恒 0%，而编译与加载**都不报错**。所以两份模板
        必须由同一个来源喂，缺席时**两边一致地没有**。
        """
        gen = Path("src/tools/uvm_tools/tool_uvm/gen_uvm.py").read_text(encoding="utf-8")
        env_tpl = Path("src/tools/uvm_tools/tool_uvm/templates/environment_templates"
                       "/env_cov.sv.j2").read_text(encoding="utf-8")
        tb_tpl = Path("src/tools/uvm_tools/tool_uvm/templates/bench_templates"
                      "/tb_top.sv.j2").read_text(encoding="utf-8")

        # 读端只有一个：`read_env_cov_bins`，两个渲染任务都经它取
        assert "def read_env_cov_bins(" in gen
        assert gen.count("read_env_cov_bins(self.output_dir)") == 2
        assert "_add_coverage_dut_context" in gen
        for tpl in (env_tpl, tb_tpl):
            assert "coverage_dut_if | default({})" in tpl
        # tb_top 只做"挂载方"：它写 config_db，不声明组件
        assert "config_db#(virtual {{ _dif.type }})::set" in tb_tpl
        assert "cov_vif" in tb_tpl and "cov_vif" in env_tpl

    def test_the_component_fails_loudly_when_the_handle_is_missing(self):
        """挂不上 = **接线错误**，不是"这次没覆盖率"。

        静默跑完只会给一个恒 0% 的数字，比停下来更难查（本仓库反复吃过
        "0% 与没有无从区分"的亏）。所以取不到句柄要 `uvm_fatal`。
        """
        env_tpl = Path("src/tools/uvm_tools/tool_uvm/templates/environment_templates"
                       "/env_cov.sv.j2").read_text(encoding="utf-8")
        assert "`uvm_fatal(" in env_tpl
        assert 'uvm_config_db#(virtual {{ _dif.type }})::get' in env_tpl
        # 采样必须**时钟沿 + 复位屏蔽**：复位期间的水位/决策是无意义值
        assert "@(posedge cov_vif.{{ _dif.clock }})" in env_tpl
        # 复位屏蔽 + 时钟沿采样。判据块（`chk_dut_one()`）跟采样在**同一个**
        # 复位屏蔽之下 —— 复位期间的值无意义，拿它判会造出一堆假违规
        assert "if (cov_vif.{{ _dif.reset }}) begin" in env_tpl
        assert "cg_dut.sample();" in env_tpl

    def test_the_dut_channel_is_reported_with_the_others(self):
        """两条通道的数要在**同一份报告**里 —— 各看各的就又要人工对账。"""
        env_tpl = Path("src/tools/uvm_tools/tool_uvm/templates/environment_templates"
                       "/env_cov.sv.j2").read_text(encoding="utf-8")
        assert '"功能覆盖率[dut]: %.1f%%"' in env_tpl


class TestTheRenderedFilesBothSidesOrNeither:
    """真的渲染一遍 —— **有 `dut_if` 就两边都出，没有就两边都不出**。

    这条链上唯一的灾难是"单边有"：组件声明了 `virtual <type>` 而 tb_top 没挂，
    于是句柄为空、覆盖率恒 0%，而**编译与加载都不报错**（`vcover` 只会说
    0.00%）。所以这里不看源码字符串，看**渲染出来的两个文件**。
    """

    EXAMPLES = Path("src/tools/uvm_tools/tool_uvm/examples/apb")

    DUT_IF = {
        "name": "apb_slave_cov_if", "type": "apb_slave_cov_if",
        "instance": "u_apb_slave_cov_if", "dut_module": "apb_slave_dut",
        "clock": "pclk", "reset": "presetn",
        "file": "coverage/apb_slave_cov_if.sv",
        "signals": ["paddr"],
        "coverpoints": [{"signal": "paddr", "sv_name": "cp_paddr",
                         "field": "paddr", "width": 8, "expr": ""}],
    }
    DUT_BINS = {"paddr": [
        {"name": "cp_zero", "value": "0", "illegal": False},
        {"name": "cp_mid", "value": "[1:127]", "illegal": False},
        {"name": "cp_over", "value": "[256:$]", "illegal": True},
    ]}

    def _render(self, tmp_path, with_dut: bool):
        import json
        import shutil

        ydir = tmp_path / "inputs" / "yaml" / "uvm"
        ydir.mkdir(parents=True)
        for src in self.EXAMPLES.glob("*.yaml"):
            shutil.copy(src, ydir / src.name)
        payload = {"cov_bins": []}
        if with_dut:
            payload["dut_if"] = self.DUT_IF
            payload["dut_bins"] = self.DUT_BINS
        (ydir / "env_cov_bins.yaml").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8")

        from src.tools.uvm_tools.tool_jinja_render.main import run

        assert json.loads(run(str(tmp_path)))["status"] == "ok"
        env = list((tmp_path / "env").glob("*_coverage.sv"))
        tb = list((tmp_path / "bench").glob("*_tb_top.sv"))
        assert len(env) == 1 and len(tb) == 1
        return (env[0].read_text(encoding="utf-8"),
                tb[0].read_text(encoding="utf-8"))

    def test_without_the_key_neither_file_mentions_the_channel(self, tmp_path):
        env, tb = self._render(tmp_path, with_dut=False)
        for text in (env, tb):
            assert "cov_vif" not in text
            assert "cg_dut" not in text
        assert "covergroup cg_" in env          # 事务通道那条照旧

    def test_with_the_key_both_files_carry_it(self, tmp_path):
        env, tb = self._render(tmp_path, with_dut=True)
        # 组件侧：句柄 + covergroup（信号走 vif）+ 时钟沿采样 + 取不到就 fatal
        assert "virtual apb_slave_cov_if cov_vif;" in env
        assert "coverpoint cov_vif.paddr" in env
        assert "bins cp_mid = {[1:127]};" in env        # 区间原样落进去
        assert "illegal_bins cp_over = {[256:$]};" in env
        assert "@(posedge cov_vif.pclk);" in env
        assert "if (cov_vif.presetn) begin" in env       # 复位周期不采、也不判
        assert "cg_dut.sample();" in env
        assert "`uvm_fatal(" in env
        # 挂载侧：层次路径 = DUT 实例 + bind 实例名
        assert 'uvm_config_db#(virtual apb_slave_cov_if)::set(' in tb
        assert "u_dut.u_apb_slave_cov_if" in tb


class TestTheBindArtifactsGetCompiled:
    """两条 bind 产物都必须**进得了 filelist** —— 不进就是又一份"看着有、
    从没编译过"的产物（文件躺在磁盘上、人以为它在采，而 vlog 从没见过它）。

    两个 glob 都要收：`*_cov_if.sv` 是管道走的那条（接口 → env 组件），
    `*_probe.sv` 是没有 env 时的独立通道。
    """

    def _fl(self, tmp_path):
        from src.tools.lib.filelist import build_filelist_for_tb

        out = tmp_path / "output_x"
        (out / "rtl").mkdir(parents=True)
        (out / "rtl" / "dut.sv").write_text("module dut; endmodule\n", encoding="utf-8")
        (out / "coverage").mkdir()
        (out / "coverage" / "dut_probe.sv").write_text("// probe\n", encoding="utf-8")
        (out / "coverage" / "dut_cov_if.sv").write_text("// iface\n", encoding="utf-8")
        (out / "coverage" / "coverage_points.json").write_text("{}", encoding="utf-8")
        return build_filelist_for_tb(out, [], "dut_env").read_text(encoding="utf-8")

    def test_both_are_collected_after_the_rtl(self, tmp_path):
        fl = self._fl(tmp_path)
        assert "dut_probe.sv" in fl
        assert "dut_cov_if.sv" in fl
        # `bind <dut_module>` 要求目标模块已声明 —— 两个都得排在 RTL 之后
        assert fl.index("dut.sv") < fl.index("dut_probe.sv")
        assert fl.index("dut.sv") < fl.index("dut_cov_if.sv")

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
        # **不钉死数字**：这条的意图是"每个读模型的落点都走统一判据"，而落点会随
        # 功能增加（写计划 / 写 bins / 写 DUT 接口 / 给断言找 bind 目标 …）。原来钉
        # `== 3`，加第 4 个合法落点时它就成了绊脚石 —— 绊住的不是"有人自己拼路径"，
        # 而是"又多了一个读模型的地方"。真正的守卫是下面那条"别再本地实现一份"。
        # `>= 3` 而不是 `== 3`：意图是"读模型的地方都走统一判据"，而落点会随功能
        # 增加（写计划 / 写 bins / 写 DUT 接口 / 给断言找 bind 目标 …）。钉死数字
        # 绊住的是**又一个合法落点**，不是"有人自己拼路径"—— 后者由下面那条
        # `test_verify_has_no_local_copy_of_the_rule` 管（`candidates.append` 的禁令）。
        assert verify.count("_find_case_model(_spec_of(output_dir), output_dir)") >= 3
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

    def test_the_plan_is_written_before_the_regression_is_generated(self):
        """计划要**早于 `find_spec_yaml`** —— 回归的 `count`/`SEED` 就在那一步铺开。

        晚一步的话回归已经生成完了、批次一条都不在里面，而日志看不出任何异常
        （实测：`env/tests` 里批次 test 类都生成了，regression.yaml 里却 0 条）。

        **与 `env_cov_bins` 的方向相反**，别一起搬：那个落在 find_spec_yaml
        会清空的目录里，只能晚于它。
        """
        src = VERIFY_MAIN.read_text(encoding="utf-8")
        find = _line_of('call_tool("find_spec_yaml"')
        plan = _line_of("self._write_coverage_plan(output_dir")
        assert plan < find, (
            f"计划@{plan} 必须早于 find_spec_yaml@{find} —— "
            f"不然回归生成时读不到种子，批次一条都不进 regression.yaml")

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

    def test_the_test_package_includes_the_batch_file(self):
        """**产出来还不够，得有人 `include` 它** —— 不然那些类从没被编译过。

        实测（端到端 `verify --rtl specs/npu_sched`）：`_batch_test.sv` 文件在磁盘上、
        `GEN_BATCH_TC` 宏也在里面，但 `test_pkg.sv` 只 include 了 base/direct/gen/attr
        —— 于是 `+UVM_TESTNAME=npu_basic_test` 撞
        `UVM_FATAL (INVTST) test not found`，p0 卡在那一条上。

        filelist 只收 `env/tests/` 下的 **package**（`_packages_in`），`_batch_test.sv`
        不在那儿被单独编译 —— 这个 include 是它**唯一**进编译的路径。
        """
        tpl = Path("src/tools/uvm_tools/tool_uvm/templates/environment_templates"
                   "/test_templates/test_pkg.sv.j2").read_text(encoding="utf-8")
        assert "{%- if environment.batches %}" in tpl
        assert '`include "{{ environment.env_name }}_batch_test.sv"' in tpl
        # 批次类 extends `_gen_test` —— include 顺序必须在它之后
        assert tpl.index("_gen_test.sv") < tpl.index("_batch_test.sv")

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
        assert "_seed_lines(bname, seed_plan" in block
        # 末位那个是闭环"扩种"的种子偏移（`seed_expand.json`）—— 不带它，扩种
        # 动作就落不到回归上（见 tests/test_convergence_loop.py 那组）
        assert "seed_offset" in block


class TestModuleNameIsAlwaysAcii:
    """模块名只能从 **ASCII 标识符** 里取 —— `\w` 会吃中文，然后**不报错**。

    实测踩过：`--rtl` 模式的 spec 里有一句注记「端口来自 module 声明；registers
    未从 RTL 推断」，而取模块名的回退式是 `(?:#|module\s+)\s*(\w+)` ——
    Python 的 `\w` **匹配中文**，于是 `module 声明` 被当成一次模块声明，
    模块名解成 `声明`。后果是整套产物落成 `声明_env_*.sv` / `声明_in_agent/`：
    生成器一切正常、日志一切正常，只有目录名是错的。
    """

    _IDENT = r"[A-Za-z_][A-Za-z0-9_]*"

    def _extract(self, text: str) -> str:
        import re

        m = re.search(rf"module:\s*({self._IDENT})", text, re.IGNORECASE) or \
            re.search(rf"(?:#|module\s+)\s*({self._IDENT})", text, re.IGNORECASE)
        return m.group(1) if m else ""

    def test_a_chinese_word_after_module_is_not_a_module_name(self):
        assert self._extract("端口来自 module 声明；registers 未推断") == ""

    @pytest.mark.parametrize("text,want", [
        ("module npu_sched (input logic clk);", "npu_sched"),
        ("module: apb_uart\nlevel: BT", "apb_uart"),
        ("# apb_uart 模块", "apb_uart"),
    ])
    def test_real_declarations_still_work(self, text, want):
        assert self._extract(text) == want

    def test_the_source_uses_an_ascii_identifier_class(self):
        """钉住源码里的写法 —— 改回 `\w+` 就红。"""
        src = Path("src/tools/uvm_tools/tool_find_spec_yaml/main.py").read_text(
            encoding="utf-8")
        start = src.index("# ── 1. 确定模块名 ──")
        block = src[start:start + 1400]
        assert "[A-Za-z_][A-Za-z0-9_]*" in block
        assert "\w+)" not in block, (
            "取模块名的正则里又出现 `\w+` 了 —— 它匹配中文，"
            "一句散文就能把模块名带偏且不报错")


class TestTheGapStimulusGoesIntoMainPhase:
    """gap 定向激励要注进 **`main_phase`** —— 注进 `configure_phase` 等于注进
    一个**永远等不到应答**的地方。

    生成的测试里 `configure_phase` 与 `main_phase` **各有一句**
    `phase.raise_objection(this);`，而注入原来是 `str.replace(..., 1)` ——
    取的是文件里第一句，也就是 `configure_phase`。

    实测（端到端 `verify --rtl specs/npu_sched`，p0 挂 1 条）：
    `configure_phase` 跑在 **run_phase 之前**，而 `start_item/finish_item` 靠
    **sequencer 的 run_phase** 递送事务 —— 递不出去，于是激励自己那条 20us 超时
    先报 `[GAPSEQ] 定向激励超时：20000 ns 内对手方未应答`，紧跟着
    `[SEQ] neither the item's sequencer ... to start item` 把整条测试判失败。
    看着像"DUT 不应答"，其实是**相位用错了**。
    """

    _TEST = """\
class foo_gen_test extends bar_base_test;
  task configure_phase(uvm_phase phase);
    super.configure_phase(phase);
    phase.raise_objection(this);
    phase.drop_objection(this);
  endtask

  task main_phase(uvm_phase phase);
    super.main_phase(phase);
    phase.raise_objection(this);
    phase.drop_objection(this);
  endtask
endclass
"""

    def test_the_anchor_is_the_one_inside_main_phase(self):
        from src.executors.verify.main import _main_phase_objection_at

        at = _main_phase_objection_at(self._TEST)
        assert at > 0
        # 锚点必须在 `main_phase` 之后（`configure_phase` 里那句在它之前）
        assert at > self._TEST.index("task main_phase")
        assert at > self._TEST.index("configure_phase")

    def test_no_main_phase_is_reported_not_guessed(self):
        """找不到 `main_phase` 就**不注入**并说一声 —— 退回"注到第一句"正是那个 bug。"""
        from src.executors.verify.main import _main_phase_objection_at

        assert _main_phase_objection_at("task only_configure(uvm_phase p); endtask") == -1


class TestTheGapSequenceIsRunnable:
    """gap 激励还要**跑得起来**：延时带单位、只注能收激励的 agent。

    两条都是实测撞出来的（端到端 `verify --rtl specs/npu_sched`，p0 卡在一条上）：

      · `#(GAP_TXN_TIMEOUT_NS)` 解析成 **20ns**（那个文件没有 `` `timescale ``，
        时间单位跟着编译单元走，实测是 1ps）—— 每轮都假报"定向激励超时"。
      · 给 **passive** agent 也注一条 —— 它的 `sequencer` 根本没建出来（模板里
        是 `if (cfg.is_active == UVM_ACTIVE)` 里建的），`start_item` 当场
        `UVM_FATAL [SEQ] neither the item's sequencer ...`。
    """

    GAPS = [{"dimension": "toggle", "location": "queue_level[5:4]", "reason": "toggle"}]

    def _seq(self):
        from src.tools.coverage_tools.main import generate_gap_directed_seq

        return generate_gap_directed_seq("npu_sched_in", self.GAPS,
                                         {"queue_level": 6},
                                         item_class="npu_sched_in_master_item")

    def test_the_timeout_delay_carries_its_unit(self):
        code = self._seq()
        assert "#(GAP_TXN_TIMEOUT_NS * 1ns);" in code, "延时又变成裸数字了"
        assert "#(GAP_TXN_TIMEOUT_NS);" not in code, (
            "裸 `#(GAP_TXN_TIMEOUT_NS)` 会跟着编译单元的时间单位走 —— 实测是 1ps，"
            "于是 20000 只等 20ns，每轮都假报超时")

    def test_a_timeout_is_not_reported_as_completed(self):
        code = self._seq()
        assert "bit timed_out = 0;" in code
        assert "timed_out = 1;" in code
        # "completed" 必须在 `if (!timed_out)` 之下 —— 超时了还打"完成"是假日志
        assert "if (!timed_out)" in code
        assert code.index("if (!timed_out)") < code.index("Gap stimulation completed")

    def test_passive_agents_are_read_from_the_model(self, tmp_path):
        """活性**问模型**（`env.yaml` 的 `is_active`），不从生成物里猜。"""
        from src.tools.lib.env_introspect import env_active_agents

        ydir = tmp_path / "inputs" / "yaml" / "uvm"
        ydir.mkdir(parents=True)
        (ydir / "env.yaml").write_text(
            "environment:\n"
            "  name: x_env\n"
            "  agents:\n"
            "    - {name: x_in, is_active: true}\n"
            "    - {name: x_out, is_active: false}\n"
            "    - {name: x_default}\n", encoding="utf-8")
        assert env_active_agents(tmp_path) == {"x_in_agent": True,
                                               "x_out_agent": False,
                                               "x_default_agent": True}

    def test_an_unreadable_model_is_empty_not_optimistic(self, tmp_path):
        """读不到模型 → **空字典**（不是"全都 active"）。

        注错是**必然** fatal（passive agent 没有 sequencer），不注只是少一段激励
        —— 所以读不到时宁可一个都不注，并记日志。
        """
        from src.tools.lib.env_introspect import env_active_agents

        assert env_active_agents(tmp_path) == {}

    def test_the_injector_consults_it(self):
        src = Path("src/executors/verify/main.py").read_text(encoding="utf-8")
        assert "env_active_agents(output_dir)" in src
        assert "passive agent" in src
        # 判断必须发生在**写文件之前**：注了再发现不该注，文件已经落盘了
        assert src.index("env_active_agents(output_dir)") < src.rindex("_gap_seq.sv")


class TestTheRtlPortTableIsParsedWhole:
    """端口表要**一个不漏** —— 注释不能吃掉端口，注释里的 `)` 不能截断表。

    实测（端到端 `verify --rtl specs/npu_sched` 跑完，两个覆盖点恒 0%）：
    `instr_valid` / `barrier_type` / `op_priority` / `issue_valid` 这 4 个端口的
    **段首都带着注释**（上一个端口的行尾注释、或一段 `// ── 分组 ──`），而匹配用的
    是**锚定**的 `re.match` —— 整段匹配不上 → 端口**静默消失**，14 个解出 10 个。

    后果离原因很远：agent 少了信号 → **没人驱动** → 对应覆盖点永远 0%，
    而且没有一行日志说端口丢了（是覆盖率通道把这件事报出来的）。
    """

    NPU = Path("specs/npu_sched")

    def _ports(self, rtl_dir):
        from src.tools.uvm_tools.tool_find_spec_yaml.main import _parse_rtl_module

        return {p["name"]: p for p in _parse_rtl_module(rtl_dir, "")["ports"]}

    def test_the_ports_behind_comments_are_not_swallowed(self):
        ports = self._ports(self.NPU)
        assert len(ports) == 14, f"端口数不对：{sorted(ports)}"
        for name, width in (("instr_valid", 1), ("barrier_type", 2),
                            ("op_priority", 2), ("issue_valid", 1)):
            assert name in ports, f"{name} 又被注释吃掉了"
            assert ports[name]["width"] == width

    def test_the_parsed_ports_match_the_dut_header(self):
        """端口表就是 spec 的契约 —— 解出来的必须与 RTL 头逐字对得上。"""
        import re

        text = (self.NPU / "npu_sched.sv").read_text(encoding="utf-8")
        head = text[text.index("module npu_sched"):text.index(");")]
        want = set(re.findall(
            r"^\s*(?:input|output)\s+logic\s*(?:\[[^\]]*\])?\s*(\w+)", head, re.M))
        assert set(self._ports(self.NPU)) == want

    def test_a_paren_inside_a_port_comment_does_not_truncate_the_table(self, tmp_path):
        """`\\(([^)]*)\\)` 会在**第一个** `)` 处收尾 —— 注释里一个 `(async)`
        就能把后面所有端口截掉。与"注释吃掉端口"是同一类故障（表少了几行，
        没人报）。"""
        rtl = tmp_path / "rtl"
        rtl.mkdir()
        (rtl / "dut.sv").write_text(
            "module dut (\n"
            "  input  logic clk,           // 时钟 (async 说明)\n"
            "  input  logic [7:0] addr,    // 地址\n"
            "  output logic [31:0] rdata   // 读数据\n"
            ");\n"
            "endmodule\n", encoding="utf-8")
        assert set(self._ports(rtl)) == {"clk", "addr", "rdata"}

    def test_a_module_with_parameters_still_parses(self, tmp_path):
        """`#( parameter ... )` 参数表在前 —— 端口表是它**后面**那个括号。"""
        rtl = tmp_path / "rtl"
        rtl.mkdir()
        (rtl / "dut.sv").write_text(
            "module dut #(parameter W = 8) (\n"
            "  input logic clk,\n"
            "  input logic [W-1:0] data\n"
            ");\n"
            "endmodule\n", encoding="utf-8")
        ports = self._ports(rtl)
        assert set(ports) == {"clk", "data"}
