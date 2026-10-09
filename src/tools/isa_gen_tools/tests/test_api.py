"""api 与 cli —— 四个接入面、错误形状、以及 CLI 只做翻译。

api 的契约只有两条，但两条都硬：
  · 返回值一律是 **dict**（不是 JSON 字符串）
  · 失败返回 `{"error", "kind", "target", "fix"}`，**不抛**
    三件套缺一，报错就只能靠猜。
"""
from __future__ import annotations

import json

import pytest

from .. import api
from ..cli import build_parser, main as cli_main

GOOD = """meta: {name: api_demo, seed: 7}
resources: {cores: [0..3]}
txn_pool: {include: [mask_txn, tld_txn, gemm_txn, sync_txn]}
orchestration: {epochs: 2, epoch_boundary_sync: always}
alloc:
  - {name: img, pool: dram.share,     shape: [64,256], dtype: fp16, role: src}
  - {name: out, pool: lmem.core.spad, shape: [64,64],  dtype: fp16, role: dst}
  - {name: wgt, pool: lmem.core.cimc, shape: [64,64],  dtype: fp16, role: wgt}
  - {name: act, pool: lmem.core.spad, shape: [64,64],  dtype: fp16, role: in}
  - {name: res, pool: lmem.core.spad, shape: [64,64],  dtype: fp16, role: out}
"""


def write(tmp_path, text: str, name: str = "dsl.yaml"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


class TestToolNames:
    def test_runners_and_tool_names_stay_in_step(self):
        assert tuple(api.RUNNERS) == tuple(api.TOOL_NAMES)

    def test_names_are_snake_case(self):
        """点号会被带进 function.name，那是非法字符 —— 所以用下划线。"""
        for name in api.TOOL_NAMES:
            assert "." not in name and name.startswith("isa_gen_"), name


class TestValidate:
    def test_a_good_dsl_is_valid(self):
        assert api.run_validate(GOOD)["valid"] is True

    def test_an_empty_input_is_a_structured_error_not_an_exception(self):
        payload = api.run_validate("")
        assert payload["valid"] is False
        assert payload["issues"][0]["rule"] == "empty_input"

    def test_a_bad_dsl_reports_every_issue(self):
        payload = api.run_validate("meta: {name: x}\nintend: {hazard_density: 1}")
        assert payload["valid"] is False
        assert payload["issues"][0]["rule"] == "unknown_property"

    def test_issues_carry_a_fix(self):
        """`fix` 是"该改什么" —— 没有它，报错就只能靠猜。"""
        payload = api.run_validate("meta: {name: x}\nintend: {}")
        assert payload["issues"][0]["fix"]


class TestCompile:
    def test_the_full_payload(self):
        payload = api.run_compile(GOOD, max_txns=6)
        assert "error" not in payload
        for key in ("seed", "name", "txn_count", "ir", "case", "preload",
                    "expect", "allocations", "play_space", "notes", "memmap"):
            assert key in payload, key

    def test_the_seed_argument_overrides_the_declared_one(self):
        assert api.run_compile(GOOD, max_txns=3, seed=99)["seed"] == 99

    def test_deterministic_across_calls(self):
        a = api.run_compile(GOOD, max_txns=6)
        b = api.run_compile(GOOD, max_txns=6)
        assert json.dumps(a["ir"], sort_keys=True) == json.dumps(b["ir"], sort_keys=True)

    def test_a_broken_dsl_returns_the_error_shape(self):
        payload = api.run_compile("meta: [1, 2]\n")
        assert "error" in payload and payload["kind"]
        assert payload["fix"]

    def test_an_alloc_that_does_not_fit_is_a_named_error(self):
        """**编译期失败**，不是抛异常 —— 而且带 kind，能按类分发。"""
        text = GOOD.replace("shape: [64,256], dtype: fp16, role: src",
                            "shape: [4096,4096,256], dtype: fp32, role: src")
        payload = api.run_compile(text, max_txns=2)
        assert payload["kind"] == "alloc"
        assert "装不下" in payload["error"]

    def test_a_missing_transaction_is_a_named_error(self):
        text = GOOD.replace("include: [mask_txn, tld_txn, gemm_txn, sync_txn]",
                            "include: [nope_txn]")
        payload = api.run_compile(text, max_txns=2)
        assert payload["kind"] == "solver"

    def test_the_payload_is_json_serialisable(self):
        payload = api.run_compile(GOOD, max_txns=4)
        assert json.loads(json.dumps(payload, ensure_ascii=False))["name"] == "api_demo"

    def test_the_memmap_source_is_reported(self):
        """"这次跑的到底是不是冻结版" 是个会被反复问的问题。"""
        memmap = api.run_compile(GOOD, max_txns=3)["memmap"]
        assert memmap["source"].endswith(".yaml")


class TestExplain:
    def test_surfaces_the_table_anomalies(self):
        """工具不替编码表做判断，但必须让人看得见。"""
        payload = api.run_explain()
        assert payload["collisions"]
        assert payload["class_mismatches"]
        assert payload["deferred_txns"]

    def test_the_cross_class_collision_is_flagged(self):
        payload = api.run_explain()
        cross = [c for c in payload["collisions"] if c["cross_class"]]
        assert cross and "gtld_drv_vn01" in cross[0]["names"]

    def test_risks_say_whether_they_still_hold(self):
        """疑点可能已经被编码表修掉了 —— 那时这条提示就是噪音，
        所以要带回一个 `present` 字段说得清"现在还在不在"。"""
        risks = api.run_explain()["risks"]
        assert risks
        assert {r["present"] for r in risks} <= {"yes", "no"}
        assert all(r["code"] and r["detail"] for r in risks)

    def test_an_unknown_transaction_lists_the_known_ones(self):
        payload = api.run_explain("no_such_txn")
        assert payload["kind"] == "unknown_txn"
        assert payload["fix"]

    def test_a_known_transaction_shows_its_instruction_group(self):
        payload = api.run_explain("gemm_txn")
        assert payload["transaction"]["ops"] == ["gemm_out_org_pre_xn", "gemm_drv_xn"]
        assert len(payload["ops"]) == 2


class TestOps:
    def test_lists_the_registry(self):
        payload = api.run_ops()
        assert payload["count"] == 122
        assert payload["instruction_count"] == 95

    def test_says_which_ops_have_no_encoding(self):
        assert len(api.run_ops()["without_encoding"]) == 27

    def test_every_op_carries_a_funct7_or_is_marked_non_instruction(self):
        for op in api.run_ops()["ops"]:
            assert op["funct7"] or op["op_class"] is None, op["name"]


class TestCli:
    def test_help_lists_every_subcommand(self, capsys):
        with pytest.raises(SystemExit) as info:
            cli_main(["--help"])
        assert info.value.code == 0
        out = capsys.readouterr().out
        for name in ("validate", "compile", "explain", "ops"):
            assert name in out

    def test_subcommands_are_exactly_these_four(self):
        choices = set()
        for action in build_parser()._subparsers._group_actions:      # noqa: SLF001
            choices |= set(action.choices)
        assert choices == {"validate", "compile", "explain", "ops"}

    def test_validate_good_and_bad_exit_codes(self, tmp_path):
        assert cli_main(["validate", str(write(tmp_path, GOOD))]) == 0
        assert cli_main(["validate", str(write(tmp_path, "meta: [1]"))]) == 1

    def test_compile_writes_the_documented_artifacts(self, tmp_path, capsys):
        """按 §3.6 落盘 —— 缺失的那两份（seq.hex / tensors）**不写占位文件**：
        一个空的 seq.hex 比没有它更容易让人以为"生成过了"。"""
        out = tmp_path / "out"
        rc = cli_main(["compile", str(write(tmp_path, GOOD)),
                       "-o", str(out), "--max-txns", "4"])
        assert rc == 0
        assert {p.name for p in out.iterdir()} == {
            "case.json", "seq.ir.json", "preload.json", "expect.json"}

    def test_compile_json_is_parseable(self, tmp_path, capsys):
        assert cli_main(["compile", str(write(tmp_path, GOOD)),
                         "--json", "--max-txns", "3"]) == 0
        assert json.loads(capsys.readouterr().out)["name"] == "api_demo"

    def test_compile_failure_exits_1_and_prints_the_fix(self, tmp_path, capsys):
        bad = GOOD.replace("include: [mask_txn, tld_txn, gemm_txn, sync_txn]",
                           "include: [nope_txn]")
        assert cli_main(["compile", str(write(tmp_path, bad))]) == 1
        err = capsys.readouterr().err
        assert "[solver]" in err and "→" in err

    def test_a_missing_file_exits_2(self, tmp_path):
        assert cli_main(["validate", str(tmp_path / "nope.yaml")]) == 2

    def test_explain_and_ops_run(self, capsys):
        assert cli_main(["explain"]) == 0
        assert "疑点" in capsys.readouterr().out
        assert cli_main(["ops"]) == 0
        assert "funct7" in capsys.readouterr().out

    def test_the_cli_has_no_logic_of_its_own(self):
        """CLI 只做**参数翻译** —— 语义全在 api 里。

        两处各写一份逻辑，迟早有一处先改。这条守卫检的是"cli 里有没有
        自己造规则"：它不该 import 注册表或编译内部件，只用 api 的四个入口。
        """
        import ast
        from pathlib import Path
        source = Path(__file__).resolve().parents[1] / "cli.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        assert not any(m and ("repository" in m or "compile" in m or "domain" in m)
                       for m in imported), imported
