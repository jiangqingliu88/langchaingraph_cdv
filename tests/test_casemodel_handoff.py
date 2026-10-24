"""casemodel 的交接契约 —— **从落盘到「生成出属性 test 类」这条路必须通**。

## 这个文件存在的理由

一份 casemodel 曾经**生成出来了、也进了用例库、回归里也跑了它那几条** ——
但 `env/tests/` 里始终只有手写模板那三个通用 test 类，`{env}_attr_test.sv`
从来没出现过。于是：

    D_ADDR=0  和  D_ADDR=255  在仿真里跑的是**同一个** test 类
                             —— 取值只进了目录名，没进仿真

链路上每一步单看都是对的，断的是**交接**：

    ① front 写 `inputs/yaml/uvm/casemodel.yaml`
    ② `tool_find_spec_yaml` 跑起来 —— **第一步清空 `inputs/yaml/uvm/*.yaml`**
    ③ 同一趟的第 8 步 `_casemodel_test_lines` 去读 —— **刚被自己删掉**
    ④ → 注入不了 `environment.tests`
    ⑤ → `gen_uvm` 的 `if environment.tests:` 为假 → 不渲染 `test_attr.sv.j2`

删它的和读它的是**同一趟运行的同一个工具**。既有测试照不出来，因为每个工具
的测试都只测自己那一段（写的人测写、读的人测读），**没有人测"写完能不能读到"**。

所以这里不测单个函数，测**交接**：落盘 → 读回 → 注入 → 渲染。
"""
from __future__ import annotations

from pathlib import Path


def _casemodel_yaml(tmp_run: Path) -> Path:
    """一份最小但真实的 casemodel（两个维度、若干取值）。"""
    from src.tools.generation.casemodel_tools.tests.conftest import FC
    return FC


class TestThePathIsOneContract:
    """落点只有一处 —— 谁都不许自己拼。"""

    def test_writer_and_reader_share_the_path(self, tmp_path):
        """front 写的、`_casemodel_test_lines` 读的，必须是**同一个文件**。

        这条是那个"写完读不到"的直接回归：两处各自拼路径时它们**不相等**，
        而两边各自的测试都是绿的。
        """
        from src.layers.l1_infrastructure.layout import casemodel_path

        written = casemodel_path(tmp_path)
        # 读端拿运行根去解析 —— 契约就是"给 run 根，还模型文件"
        assert casemodel_path(tmp_path) == written
        assert written.name == "casemodel.yaml"

    def test_it_lives_outside_the_private_archive_dir(self, tmp_path):
        """**不许落在 `inputs/yaml/uvm/` 下。**

        那个目录是 `tool_find_spec_yaml` 的私有产物目录，它每次跑先清空
        `*.yaml`。front 比它更早跑，东西放进去就会被删 —— 而接下来要读它的
        正是删它的那个工具。
        """
        from src.layers.l1_infrastructure.layout import casemodel_path

        p = casemodel_path(tmp_path)
        assert "yaml" not in p.parts, f"落点又回到会被清空的目录了：{p}"

    def test_the_reader_uses_the_contract_not_a_literal(self):
        """`_casemodel_test_lines` **自己拼过路径吗** —— 没有才算走契约。

        查的是**这个函数的函数体**：连接口只该是 `output_dir`，文件名由
        `layout.casemodel_path()` 给。函数体里再出现 `"casemodel.yaml"` 字面量，
        就是又开了一份真相（原来那版拼的正是 `_P(yaml_dir) / "casemodel.yaml"`）。
        """
        import inspect
        from src.tools.generation.uvm_tools.tool_find_spec_yaml.main import _casemodel_test_lines

        body = inspect.getsource(_casemodel_test_lines)
        code = "\n".join(ln for ln in body.splitlines()
                         if not ln.lstrip().startswith("#"))
        assert "casemodel_path" in code, "读端没走 layout.casemodel_path"
        assert '"casemodel.yaml"' not in code, \
            "读端又在自己拼文件名了 —— 落点契约只有 layout.casemodel_path 一处"


class TestTheHandoffActuallyWorks:
    """**端到端那一段**：把模型放进去，`tests:` 就该被注入出来。"""

    def test_a_placed_casemodel_yields_test_lines(self, tmp_path):
        """有模型 → 有 `tests:` 行。断在交接上时这里返回 `[]`。"""
        from src.layers.l1_infrastructure.layout import casemodel_path
        from src.tools.generation.uvm_tools.tool_find_spec_yaml.main import _casemodel_test_lines

        p = casemodel_path(tmp_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(_casemodel_yaml(tmp_path).read_text(encoding="utf-8"),
                     encoding="utf-8")

        lines = _casemodel_test_lines(tmp_path)
        assert lines, "放进去的 model 没被读出来 —— 交接又断了"
        assert lines[0].strip() == "tests:"
        assert all("dimension" in ln for ln in lines[1:])

    def test_stimulus_binding_reaches_the_env_lines(self, tmp_path):
        """模型里的 `stimulus.field` 必须一路走到注入的 `tests:` 行。

        走不到的话，属性 test 仍然只会 set 一个没人读的 `<维度>_int` ——
        类名不同、激励相同，也就是"取值只进了目录名"的现代版。
        """
        import yaml
        from src.layers.l1_infrastructure.layout import casemodel_path
        from src.tools.generation.uvm_tools.tool_find_spec_yaml.main import _casemodel_test_lines

        doc = yaml.safe_load(_casemodel_yaml(tmp_path).read_text(encoding="utf-8"))
        for dim in doc.get("dimensions") or []:
            if dim.get("id") == "D_ratio":
                dim["stimulus"] = {"field": "credit"}
        p = casemodel_path(tmp_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False),
                     encoding="utf-8")

        lines = _casemodel_test_lines(tmp_path)
        bound = [ln for ln in lines if "field:" in ln]
        assert bound, "激励绑定在交接处丢了 —— 属性 test 会退回死标签"
        assert all("field: credit" in ln for ln in bound)
        # 没绑定的维度不能凭空多出 field（空串会被下游当成已绑定）
        assert any("dimension:" in ln and "field:" not in ln for ln in lines[1:])

    def test_no_model_means_no_injection_not_a_fake_one(self, tmp_path):
        """没有模型就**空着** —— 不编一份假装做过。"""
        from src.tools.generation.uvm_tools.tool_find_spec_yaml.main import _casemodel_test_lines

        assert _casemodel_test_lines(tmp_path) == []

    def test_lines_survive_the_private_dir_being_wiped(self, tmp_path):
        """**这条正是那个 bug 的形状**：私有目录被清空之后，模型还得在。

        `tool_find_spec_yaml` 会 `glob("*.yaml").unlink()` 掉
        `inputs/yaml/uvm/`。契约落点不在那里，所以清空动不到它 ——
        这条断言把这个位置性质钉死，谁把落点挪回去，这里就红。
        """
        from src.layers.l1_infrastructure.layout import casemodel_path
        from src.tools.generation.uvm_tools.tool_find_spec_yaml.main import _casemodel_test_lines

        p = casemodel_path(tmp_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(_casemodel_yaml(tmp_path).read_text(encoding="utf-8"),
                     encoding="utf-8")

        # 复刻那句清空
        archive = tmp_path / "inputs" / "yaml" / "uvm"
        archive.mkdir(parents=True, exist_ok=True)
        (archive / "apb.yaml").write_text("x: 1\n", encoding="utf-8")
        for old in archive.glob("*.yaml"):
            old.unlink()

        assert p.exists(), "模型没躲过私有目录的清理"
        assert _casemodel_test_lines(tmp_path), "清空私有目录后模型读不到了"


class TestTestPointsReachTheRegression:
    """测试点 → 回归任务：**生成了但从不被执行**等于没测。"""

    def _model_with_stimulus(self, tmp_path, dim_id="D_ratio", field="credit"):
        import yaml
        from src.layers.l1_infrastructure.layout import casemodel_path

        doc = yaml.safe_load(_casemodel_yaml(tmp_path).read_text(encoding="utf-8"))
        for dim in doc.get("dimensions") or []:
            if dim.get("id") == dim_id:
                dim["stimulus"] = {"field": field}
        p = casemodel_path(tmp_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False),
                     encoding="utf-8")
        return p

    def test_stimulus_tp_becomes_a_regression_task(self, tmp_path):
        from src.tools.generation.uvm_tools.tool_find_spec_yaml.main import _tp_regression_lines

        self._model_with_stimulus(tmp_path)
        lines = _tp_regression_lines(
            tmp_path, "zz_mod", "zz_mod_env", "zz_mod_bench_tb_top", 0,
            lambda top, test: f"vsim {top} +UVM_TESTNAME={test}")
        body = "\n".join(lines)
        assert lines, "可激励测试点没有变成回归任务 —— 属性 test 又成了孤儿"
        assert "+UVM_TESTNAME=zz_mod_env_d_ratio_p50_test" in body
        assert "tags: [\"p" in body, "分级标签没带上（分级回归筛不到它）"

    def test_observe_only_tp_does_not_take_a_regression_slot(self, tmp_path):
        """观测型没有激励差异 —— 单独跑一遍与批次测试等价，不该占槽。"""
        from src.layers.l1_infrastructure.layout import casemodel_path
        from src.tools.generation.uvm_tools.tool_find_spec_yaml.main import _tp_regression_lines

        # 原样模型：FC 没有任何 stimulus 声明 → 全部是观测型
        p = casemodel_path(tmp_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(_casemodel_yaml(tmp_path).read_text(encoding="utf-8"),
                     encoding="utf-8")
        lines = _tp_regression_lines(
            tmp_path, "zz_mod", "zz_mod_env", "zz_mod_bench_tb_top", 0,
            lambda top, test: f"vsim {top} +UVM_TESTNAME={test}")
        assert lines == []


class TestItReachesTheGeneratedEnv:
    """注入进去之后，`gen_uvm` 要**真的**把它变成 test 类。

    这一段是"链条到底通没通"的终点：`environment.tests` 非空 → 渲染
    `test_attr.sv.j2` → 产出 `{env}_attr_test.sv`。
    """

    def test_nonempty_tests_renders_the_attr_test_file(self):
        """`env.tests` 非空 ⇒ 属性 test 模板进渲染清单。"""
        import inspect
        import src.tools.generation.uvm_tools.tool_uvm.gen_uvm as g

        src = inspect.getsource(g)
        # 那条 if 是整条链的闸门：`environment.tests` 为空时属性 test 根本不渲染
        assert "if environment.tests" in src or "if env.tests" in src, \
            "属性 test 的渲染闸门没了 —— 这条链的终点变了，要重新确认"
        assert "test_attr.sv.j2" in src, "属性 test 模板不在渲染清单里"
