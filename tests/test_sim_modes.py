"""**仿真业务模式** —— 从工具栏那个下拉，到仿真命令里那几个选项。

这条链有四段，任何一段断了都会表现成"开关点了没反应"，而没反应的原因各不相同：

  1. 词条表（`sim_modes.py`）与 `common_base.yaml` 的 `modes:` 表**对不对得上**
     —— 对不上就是"选了一个框架不认识的词条"，`apply_modes` 会告警忽略；
  2. 生成的 `regression.yaml` 有没有把机制带上（`include:` + 同名变量覆盖 +
     `{{ MODE_OPTS }}` 落点）—— 这是"生成物"那一段；
  3. `apply_modes` 拼出来的 `MODE_OPTS` 有没有真的进到 sim.sh —— 渲染那一段；
  4. **include 进来的 foreign build 有没有被挡在调度外** —— 这一段断了不是
     "没反应"，是**整轮回归连一条真 case 都跑不出来**（跑的是 `VCS …`）。

前两段与第四段都能在这里钉住；第三段在下面用真生成的脚本文件断言（不跑仿真）。
"""
from __future__ import annotations

import json

import pytest

from src.layers.l1_infrastructure.infrastructure import declared_tests_by_build
from src.tools.regression_tools import sim_modes as sm


# ════════════════════════════════════════════════════════════
# 1. 词条表：与 common_base.yaml 的 modes 表同源
# ════════════════════════════════════════════════════════════

def _common_base() -> dict:
    import yaml

    return yaml.safe_load(sm.common_base_path().read_text(encoding="utf-8")) or {}


class TestModeTable:
    def test_common_base_exists(self):
        """`include:` 的目标必须真的在 —— 否则框架会 warning 一句然后跳过，
        机制静默失效（生成的 yaml 看着完全正常）。"""
        assert sm.common_base_path().is_file()

    def test_covers_exactly_the_registered_modes(self):
        """词条表要**恰好**覆盖 common_base 的 `modes:` 键。

        少一个 → 界面上没有那个开关；多一个 → 选了也会被 apply_modes 忽略。
        两种都是"点了没反应"，所以两头都钉。
        """
        declared = set((_common_base().get("modes") or {}).keys())
        assert {m.mode for m in sm.all_modes()} == declared

    def test_variable_names_match_the_modes_mapping(self):
        """每个词条映射到的变量名要和 common_base 的 `modes:` 写的一致。"""
        mapping = _common_base().get("modes") or {}
        for mode in sm.all_modes():
            assert mapping.get(mode.mode) == mode.var, (
                f"{mode.mode} 在 common_base.yaml 里映射到 {mapping.get(mode.mode)!r}，"
                f"表里写的是 {mode.var!r}")

    def test_questa_values_override_the_vcs_ones(self):
        """**值不能照抄 common_base** —— 那份是 VCS 语义。

        这条不是在挑刺：`-cm line+cond+…` 拼进 vsim 会被判成未知选项，整轮回归全崩。
        所以除了"本后端没有开关"的那几项，每一项的值都必须与 common_base 不同。
        """
        base_vars = _common_base().get("variables") or {}
        for mode in sm.all_modes():
            if not mode.supported:
                assert mode.value == ""      # 没有开关 → 空串（apply_modes 会告警忽略）
                continue
            assert mode.value, f"{mode.mode} 标了 supported 却没有取值"
            assert mode.value != base_vars.get(mode.var), (
                f"{mode.mode} 的值和 common_base.yaml 的 VCS 取值一样：{mode.value!r}")

    def test_default_is_coverage_plus_wave(self):
        # 默认从 `cov` 改成 `cov+wave`：只开覆盖率的话，事后想看信号
        # 只能回去重跑一轮 —— 而重跑出来的未必是当时那个现场。
        assert sm.DEFAULT_MODE == "cov+wave"

    def test_unsupported_are_reported(self):
        assert set(sm.unsupported(["wave", "xprop", "upf"])) == {"xprop", "upf"}
        assert sm.unsupported(["wave"]) == []
        assert sm.unsupported("xprop,tprop") == ["xprop", "tprop"]


# ════════════════════════════════════════════════════════════
# 2. 生成物：regression.yaml 要带上这套机制
# ════════════════════════════════════════════════════════════

class _StubRegistry:
    """替掉用例库 —— 用例库是**跨 run 共享的项目级**产物，测试不能依赖它。

    给一条 `planned` 的用例，走的就是生成器的主路径（case 库对齐那一支）。
    """

    def __init__(self, *_a, **_k):
        pass

    def get_priority_order(self, **_k):
        return [{"name": "case_smoke", "priority": "P1", "scenario": "smoke",
                 "status": "planned"}]

    def register(self, *_a, **_k):
        pass

    def close(self):
        pass


@pytest.fixture
def generated_yaml(tmp_path, monkeypatch) -> str:
    """真跑一遍生成器，返回 regression.yaml 的正文。"""
    from src.layers.l4_memory import testcase_registry as registry_mod
    from src.tools.uvm_tools.tool_find_spec_yaml import main as gen

    monkeypatch.setattr(registry_mod, "TestcaseRegistry", _StubRegistry)

    out = tmp_path / "output_x"
    (out / "inputs" / "filelists").mkdir(parents=True)
    (out / "inputs" / "filelists" / "filelist.f").write_text("rtl/dut.sv\n", encoding="utf-8")
    (out / "spec.json").write_text(json.dumps({"test_points": []}), encoding="utf-8")

    path = gen._generate_regression_yaml(out, out / "inputs" / "yaml",
                                        "dut", "dut_env", "dut", [])
    return path.read_text(encoding="utf-8")


class TestGeneratedManifest:
    def test_includes_common_base(self, generated_yaml):
        """用户要的就是这一条：生成物**带上** common_base.yaml。

        用 `include:` 而不是把它的内容抄一遍 —— 抄一遍就是第二份真相，
        模式表以后在 common_base 里加了词条，生成物这边不会知道。
        """
        import yaml

        doc = yaml.safe_load(generated_yaml)
        assert [str(p) for p in doc["include"]] == [sm.common_base_path().as_posix()]

    def test_carries_the_mode_variables(self, generated_yaml):
        """同名变量要**就地覆盖**成 Questa 取值（合并规则是本地优先）。"""
        import yaml

        variables = yaml.safe_load(generated_yaml)["variables"]
        for var, value in sm.yaml_variables().items():
            assert variables[var] == value, f"{var} 没写进去 / 值不对"

    def test_sim_command_renders_mode_opts(self, generated_yaml):
        assert '{{ MODE_OPTS | default("") }}' in generated_yaml

    def test_compile_command_is_coverage_gated(self, generated_yaml):
        """覆盖率是编译期使能的：`+cover` 必须挂在 build 上，且**按开关**。

        不带 `{% if %}` 直接写死 `+cover`，等于把"默认开覆盖率"变成"永远开"——
        不选覆盖率的那几门业务的仿真都会被插桩拖慢。
        """
        assert "{% if cov_enabled | default(false) %}+cover{% endif %}" in generated_yaml


class TestRenderedScripts:
    """真跑一遍 ConfigBuilder + ShellGenerator，看 sim.sh 里到底有没有选项。"""

    def _render(self, generated_yaml, tmp_path, enabled_modes):
        import shutil

        from src.tools.regression_tools.regression_framework.core.config import (
            ConfigBuilder)
        from src.tools.regression_tools.regression_framework.generators.shell import (
            ShellGenerator)

        yml = tmp_path / "inputs" / "yaml"
        yml.mkdir(parents=True, exist_ok=True)
        cfg_path = yml / "regression.yaml"
        cfg_path.write_text(generated_yaml, encoding="utf-8")

        config = ConfigBuilder(str(cfg_path)).build(enabled_modes=enabled_modes)
        root = tmp_path / "regression_run"
        shutil.rmtree(root, ignore_errors=True)
        ShellGenerator().generate(config, str(root), "local")
        build = next(p for p in root.iterdir() if p.name.startswith("build_")
                     and p.name.endswith("_dut"))
        test_dir = next(p for p in build.iterdir() if p.name.startswith("test_"))
        return (config, (test_dir / "sim.sh").read_text(encoding="utf-8"),
                (build / "build.sh").read_text(encoding="utf-8"))

    def test_wave_mode_lands_in_the_sim_command(self, generated_yaml, tmp_path):
        _config, sim_sh, build_sh = self._render(generated_yaml, tmp_path, ["wave"])
        # 波形业务两件事缺一不可：
        #   · `-voptargs=+acc` 保 DUT 可见性（否则波形库里没有 DUT，hier 拉不出信号）
        #   · `-qwavedb=+signal+class` 落 Visualizer 原生的 qwave.db（Visualizer 只认它）
        assert "-voptargs=+acc" in sim_sh
        assert "-qwavedb=+signal+class" in sim_sh
        assert "waves/${EMAN_TEST_NAME}.db" in sim_sh
        # 波形业务不使能覆盖率编译 —— 两门业务是分开的
        assert "+cover" not in build_sh

    def test_cov_mode_instruments_both_sides(self, generated_yaml, tmp_path):
        _config, sim_sh, build_sh = self._render(generated_yaml, tmp_path, ["cov"])
        assert "-coverage" in sim_sh
        assert "+cover" in build_sh

    def test_combined_mode_still_instruments_the_compile(self, generated_yaml, tmp_path):
        """组合模式（默认的 `cov+wave`）**也要**给 vlog 加 `+cover`。

        这条是实测踩出来的：`apply_modes` 只设 `<mode>_enabled`，于是
        `cov+wave` 设的是 `cov+wave_enabled`，而 build 的 run_cmd 判的是
        `cov_enabled` —— DUT 编译少了 `+cover`，vsim 报 (vsim-8634)
        「Code was not compiled with coverage options」，**覆盖率恒为 0**。
        而 `MODE_OPTS` 是对的，命令行看上去完全正常，从日志里极难发现。
        """
        _config, sim_sh, build_sh = self._render(generated_yaml, tmp_path, ["cov+wave"])
        assert "-coverage" in sim_sh          # 运行时收覆盖率
        assert "-qwavedb" in sim_sh           # 顺带落波形
        assert "+cover" in build_sh           # 编译侧必须被使能（本条的要点）
        assert "+SCB_OFF" not in sim_sh       # 覆盖率轮 scoreboard 照常结算

    def test_no_mode_leaves_the_command_alone(self, generated_yaml, tmp_path):
        """什么都不开时命令里不该多出任何选项（`MODE_OPTS` 未定义 → default 空串）。

        裸 `{{ MODE_OPTS }}` 在这里会抛 UndefinedError（渲染是 StrictUndefined），
        所以这条同时钉住"必须写 `| default(...)`"。
        """
        _config, sim_sh, build_sh = self._render(generated_yaml, tmp_path, None)
        assert "-coverage" not in sim_sh and "-wlf" not in sim_sh
        assert "-qwavedb" not in sim_sh and "-voptargs" not in sim_sh
        assert "+cover" not in build_sh
        assert "MODE_OPTS" not in sim_sh          # 模板已经渲染掉了

    def test_unsupported_mode_is_ignored_not_injected(self, generated_yaml, tmp_path):
        """本后端没有开关的业务（xprop/upf）**不能**往命令行里塞东西。

        它的值是空串，`apply_modes` 会告警忽略 —— 这里的断言是"结果里确实没有"。
        """
        config, sim_sh, build_sh = self._render(generated_yaml, tmp_path, ["upf"])
        assert config.get("variables", {}).get("MODE_OPTS") is None
        assert "MODE_OPTS" not in sim_sh


class TestForeignBuildsStayOut:
    """include 带进来的 VCS build **不能**被排进调度。"""

    def test_common_base_builds_have_no_tests_declared(self, generated_yaml, tmp_path):
        """白名单里（=会被调度的）只剩本项目的 build。

        这条不变量是 `run_regression` 那道白名单的地基：一旦某个 test 声明到了
        common_base 的 build 上，那条 `VCS …` 命令就会被真跑，整轮回归全崩。
        """
        from src.tools.regression_tools.regression_framework.core.config import (
            ConfigBuilder)

        yml = tmp_path / "inputs" / "yaml"
        yml.mkdir(parents=True, exist_ok=True)
        cfg_path = yml / "regression.yaml"
        cfg_path.write_text(generated_yaml, encoding="utf-8")
        config = ConfigBuilder(str(cfg_path)).build()

        foreign = {b["name"] for b in config["builds"] if b["name"] != "build_dut_dut"}
        assert foreign, "include 没生效的话这条测试就失去意义了"
        scheduled = set(declared_tests_by_build(config))
        assert scheduled & foreign == set()

    def test_declared_tests_by_build_normalises_names(self):
        config = {"tests": [{"name": "test_a", "build": "build_b"},
                            {"name": "test_c", "build": "build_b"},
                            {"name": "no_build"}]}
        assert declared_tests_by_build(config) == {"b": {"a", "c"}}


# ════════════════════════════════════════════════════════════
# 3. 运行请求：词条归一
# ════════════════════════════════════════════════════════════

class TestRunRequestNormalisation:
    def test_default_is_coverage_plus_wave(self):
        """不选 → 工具层的 `DEFAULT_MODE`（`cov+wave`）。

        **断言的是常量而不是字面量** —— 默认值只有一份定义，改它不该
        让这条测试跟着改（那说明默认值散成了两份）。
        """
        from src.layers.l2_orchestration.run_service import _normalize_sim_modes
        from src.tools.regression_tools import sim_modes as sm

        assert _normalize_sim_modes(None) == [sm.DEFAULT_MODE]

    def test_accepts_string_and_list(self):
        from src.layers.l2_orchestration.run_service import _normalize_sim_modes

        assert _normalize_sim_modes("wave") == ["wave"]
        assert _normalize_sim_modes(["wave", "cov"]) == ["wave", "cov"]
        assert _normalize_sim_modes("wave,cov") == ["wave", "cov"]

    def test_explicit_empty_means_none(self):
        """`[]` 是**明确的"不开"**，不能被当成"没给"回落到覆盖率。"""
        from src.layers.l2_orchestration.run_service import _normalize_sim_modes

        assert _normalize_sim_modes([]) == []

    def test_unknown_tokens_are_dropped(self):
        from src.layers.l2_orchestration.run_service import _normalize_sim_modes

        assert _normalize_sim_modes(["wave", "no_such_business"]) == ["wave"]

    def test_duplicates_collapse(self):
        from src.layers.l2_orchestration.run_service import _normalize_sim_modes

        assert _normalize_sim_modes(["wave", "wave"]) == ["wave"]


# ════════════════════════════════════════════════════════════
# 4. 波形列：数据层扫出来的路径
# ════════════════════════════════════════════════════════════

class TestWaveColumn:
    def _status(self, root):
        from src.tools.flow_tools.api import run_regression_status

        return run_regression_status(str(root))

    def test_reports_the_wave_config_specified(self, tmp_path):
        """`waves/` 下有波形 → 列出来，来源标 `waves_dir`。"""
        d = tmp_path / "regression_run" / "build_b1" / "test_t1"
        (d / "waves").mkdir(parents=True)
        (d / "waves" / "t1.wlf").write_bytes(b"wlf")
        (d / "status.env").write_text("EMAN_BASE_STATUS=pass\n", encoding="utf-8")

        row = next(r for r in self._status(tmp_path)["rows"] if r["name"] == "t1")
        assert row["wave"].endswith("t1.wlf")
        assert row["wave_source"] == "waves_dir"

    def test_falls_back_to_the_simulator_default_location(self, tmp_path):
        """没开 `waves/` 落点时的 `vsim.wlf` 也算 —— 它是真实存在的现场。

        框架自己写的 `wave_path` 是**记录**（现在通过/失败都写，落 `<test>/waves/
        <test>.db`）；这里钉的是**现场扫描**那条兜底：磁盘上真有 `vsim.wlf` 就得认出来，
        不能因为"记录里没有"就把这列判空。
        """
        d = tmp_path / "regression_run" / "build_b1" / "test_t1"
        d.mkdir(parents=True)
        (d / "vsim.wlf").write_bytes(b"wlf")
        (d / "status.env").write_text("EMAN_BASE_STATUS=pass\n", encoding="utf-8")

        row = next(r for r in self._status(tmp_path)["rows"] if r["name"] == "t1")
        assert row["wave"].endswith("vsim.wlf")
        assert row["wave_source"] == "sim_dir"

    def test_no_wave_is_empty_and_explained(self, tmp_path):
        """没有波形时给空串，并在 notes 里说明"这轮没开波形业务"。

        不给路径也不给原因的话，空列会被读成"波形丢了"。
        """
        d = tmp_path / "regression_run" / "build_b1" / "test_t1"
        d.mkdir(parents=True)
        (d / "status.env").write_text("EMAN_BASE_STATUS=pass\n", encoding="utf-8")

        payload = self._status(tmp_path)
        row = next(r for r in payload["rows"] if r["name"] == "t1")
        assert row["wave"] == "" and row["wave_source"] == "none"
        assert any("wave" in n for n in payload["notes"])

    def test_newest_wave_wins(self, tmp_path):
        """一条用例有多个波形（重跑留下的）→ 取最新写的那个，不是按名字排。"""
        import os
        import time

        d = tmp_path / "regression_run" / "build_b1" / "test_t1"
        (d / "waves").mkdir(parents=True)
        old = d / "waves" / "aaa.wlf"
        new = d / "waves" / "zzz.wlf"
        old.write_bytes(b"old")
        new.write_bytes(b"new")
        os.utime(old, (1000, 1000))
        os.utime(new, (time.time(), time.time()))

        row = next(r for r in self._status(tmp_path)["rows"] if r["name"] == "t1")
        assert row["wave"].endswith("zzz.wlf")


class TestCoverageColumn:
    """覆盖率列 —— 口径与波形列一致（记录 > 现场，来源标出来）。"""

    def _status(self, root):
        from src.tools.flow_tools.api import run_regression_status

        return run_regression_status(str(root))

    def _row(self, tmp_path, name="t1"):
        return next(r for r in self._status(tmp_path)["rows"] if r["name"] == name)

    def test_reports_the_configured_location(self, tmp_path):
        """覆盖率业务的落点是 `${EMAN_CM_DIR}`（框架设成 `<用例目录>/cov`）。"""
        db = (tmp_path / "regression_run" / "build_b1" / "test_t1"
              / "cov" / "t1" / "questa.db")
        db.parent.mkdir(parents=True)
        db.write_bytes(b"db")
        (db.parent / "t1.data").write_bytes(b"data")     # 副产品，不是库

        row = self._row(tmp_path)
        assert row["cov"].endswith("questa.db")
        assert row["cov_source"] == "cm_dir"

    def test_no_coverage_is_empty_and_explained(self, tmp_path):
        d = tmp_path / "regression_run" / "build_b1" / "test_t1"
        d.mkdir(parents=True)
        (d / "status.env").write_text("EMAN_BASE_STATUS=pass\n", encoding="utf-8")

        payload = self._status(tmp_path)
        row = next(r for r in payload["rows"] if r["name"] == "t1")
        assert row["cov"] == "" and row["cov_source"] == "none"
        assert any("覆盖率" in n for n in payload["notes"])


class TestArtifactFacts:
    """每行还带**大小与时间** —— "逐条校对"那两页要拿它判断这份产物新不新。"""

    def _status(self, root):
        from src.tools.flow_tools.api import run_regression_status

        return run_regression_status(str(root))

    def _row(self, tmp_path):
        d = tmp_path / "regression_run" / "build_b1" / "test_t1"
        (d / "waves").mkdir(parents=True)
        (d / "waves" / "t1.wlf").write_bytes(b"w" * 3072)
        (d / "cov" / "t1").mkdir(parents=True)
        (d / "cov" / "t1" / "questa.db").write_bytes(b"d" * 1024)
        return next(r for r in self._status(tmp_path)["rows"] if r["name"] == "t1")

    def test_size_and_time_are_reported(self, tmp_path):
        row = self._row(tmp_path)
        assert row["wave_kb"] == 3.0 and row["cov_kb"] == 1.0
        assert row["wave_time"].count(":") == 2      # YYYY-MM-DD HH:MM:SS
        assert row["cov_time"].startswith("20")

    def test_missing_artifacts_have_no_size(self, tmp_path):
        """没有产物时给**空**，不是 0 KB —— 0 和"没有"是两件事。"""
        d = tmp_path / "regression_run" / "build_b1" / "test_t1"
        d.mkdir(parents=True)
        (d / "status.env").write_text("EMAN_BASE_STATUS=pass\n", encoding="utf-8")

        row = next(r for r in self._status(tmp_path)["rows"] if r["name"] == "t1")
        assert row["wave_kb"] is None and row["cov_kb"] is None
        assert row["wave_time"] == "" and row["cov_time"] == ""


# ════════════════════════════════════════════════════════════
# 5. 工作台侧：选择与记忆
# ════════════════════════════════════════════════════════════

class TestWorkbenchSelection:
    def test_items_come_from_the_tool_table(self, monkeypatch, tmp_path):
        from src.workbench import sim_modes as ui

        monkeypatch.setattr(ui, "STORE", tmp_path / "sim_modes.json")
        items = ui.mode_items()
        assert items[0]["mode"] == ui.NONE_MODE            # 「无」排在最前
        assert [i["mode"] for i in items[1:]] == [m.mode for m in sm.all_modes()]

    def test_missing_store_falls_back_to_the_tool_default(self, monkeypatch, tmp_path):
        """界面侧没存过 → 跟工具层的默认走（不自己定一份）。"""
        from src.tools.regression_tools import sim_modes as tool_modes
        from src.workbench import sim_modes as ui

        monkeypatch.setattr(ui, "STORE", tmp_path / "nope.json")
        assert ui.load() == tool_modes.DEFAULT_MODE
        assert ui.selected_modes() == [tool_modes.DEFAULT_MODE]

    def test_saved_none_stays_none(self, monkeypatch, tmp_path):
        """选过「无」之后要**保持无** —— 不能因为存储里是空的就又跳回覆盖率。

        「没存过」和「人明确选了无」是两件事；混成一件就是在静默篡改人的选择。
        """
        from src.workbench import sim_modes as ui

        store = tmp_path / "sim_modes.json"
        monkeypatch.setattr(ui, "STORE", store)
        ui.save(ui.NONE_MODE)
        assert ui.load() == ui.NONE_MODE
        assert ui.selected_modes() == []

    def test_round_trip(self, monkeypatch, tmp_path):
        from src.workbench import sim_modes as ui

        monkeypatch.setattr(ui, "STORE", tmp_path / "sim_modes.json")
        ui.save("wave")
        assert ui.load() == "wave"
        assert ui.selected_modes() == ["wave"]
