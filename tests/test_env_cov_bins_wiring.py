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
