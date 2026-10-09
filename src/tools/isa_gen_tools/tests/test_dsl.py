"""DSL —— 契约、一次报全、派生 seed。

最要紧的两条：
  · **校验一次把所有的错报出来**，不是抛第一个（使用者不该跑五趟）
  · **派生 seed 满足 E5**（加一个对象不动既有对象的取值）
"""
from __future__ import annotations

import json

import pytest
import yaml

from ..analysis import check_dsl_text, load_dsl
from ..analysis.schema_check import schema_file_matches_model
from ..domain import IsaGenError
from ..domain.dsl import derive_seed

#: 文档 §3.10.2 那份完整例子 —— 逐字抄下来的，它是契约的活样本
DOC_EXAMPLE = """
meta:
  name: rand_gemm_mix_001
  seed: 12345
  isa_rev: V0.8
  target: npu_subsystem_top

resources:
  cores: [0..3]
  spad_tiles: 8
  cimc_pages: 4
  dram: {share: auto, common: auto}

txn_pool:
  include: [tld_txn, tst_txn, gemm_txn, vpu_vv_txn, noc_xn_txn, sync_txn]
  weights: {tld_txn: 3, tst_txn: 2, gemm_txn: 4, vpu_vv_txn: 2, noc_xn_txn: 1, sync_txn: 1}

shape_space:
  dim0: [64, 128, 256, 512]
  dim1: [4, 8, 16, 32, 64]
  dim2: [1, 2, 3, 4]

precision_mix: {fp16: 0.5, bf16: 0.3, mxfp8: 0.2}

intent:
  hazard_density: 0.35
  tile_contention: 0.2
  mcast_mix: {unicast: 0.7, mcast4: 0.2, bcast: 0.1}
  fence_every_n_epochs: 4
  illegal_ratio: 0.0

orchestration:
  epochs: 16
  epoch_boundary_sync: random

harness:
  inst_agent: {gap_mode: random, gap_range: [0, 8], ready_throttle: 0.15}

alloc:
  - {name: img, pool: dram.share, shape: [1, 64, 256], dtype: fp16,
     pattern: gauss, exp_range: [-6, 6]}
  - {name: out, pool: lmem.core.spad, shape: [1, 64, 256], dtype: fp16}
"""

MINIMAL = "meta: {name: tiny}"


class TestDocExample:
    def test_the_documented_example_loads(self):
        """§3.10.2 那份例子必须能过 —— 它是契约的活样本。"""
        doc = load_dsl(DOC_EXAMPLE)
        assert doc.meta.name == "rand_gemm_mix_001"
        assert doc.meta.seed == 12345
        assert doc.orchestration.epochs == 16
        assert doc.intent.hazard_density == 0.35
        assert [a.name for a in doc.alloc] == ["img", "out"]

    def test_only_meta_is_required(self):
        assert load_dsl(MINIMAL).meta.name == "tiny"

    def test_round_trip_is_json_safe(self):
        """`to_dict()` 要能直接 json.dumps —— 落 case.json 用。"""
        payload = load_dsl(DOC_EXAMPLE).to_dict()
        assert json.loads(json.dumps(payload, ensure_ascii=False))["meta"]["name"] \
            == "rand_gemm_mix_001"


class TestSchemaErrors:
    def test_unknown_key_names_the_offender(self):
        """键名拼错必须点名 —— 静默忽略等于配置"看似生效实则失效"。"""
        issues = check_dsl_text("meta: {name: x}\nintend: {hazard_density: 1}")
        assert [i.rule for i in issues] == ["unknown_property"]
        assert "intend" in issues[0].target
        assert issues[0].fix

    def test_missing_meta(self):
        issues = check_dsl_text("intent: {hazard_density: 0.1}")
        assert any(i.rule == "required_missing" for i in issues)

    def test_all_errors_are_reported_at_once(self):
        """**一份 DSL 里五个键拼错，一次全报出来。**

        抛第一个的实现会让使用者改一次跑一次，来回五趟。
        """
        issues = check_dsl_text(
            "meta: {name: x}\n"
            "intent: {hazard_density: 5.0, nope: 1}\n"
            "orchestration: {epochs: 0}\n"
            "txn_pool: {weights: {a: -1}}\n")
        assert len([i for i in issues if i.is_error]) >= 4

    def test_out_of_range_ratio(self):
        issues = check_dsl_text("meta: {name: x}\nintent: {hazard_density: 1.5}")
        assert issues and issues[0].is_error

    def test_mix_must_sum_to_one(self):
        issues = check_dsl_text("meta: {name: x}\nprecision_mix: {fp16: 0.5, bf16: 0.2}")
        assert any("之和" in i.message for i in issues)

    def test_epochs_must_be_positive(self):
        issues = check_dsl_text("meta: {name: x}\norchestration: {epochs: 0}")
        assert issues and issues[0].is_error

    def test_negative_weight_is_rejected(self):
        issues = check_dsl_text("meta: {name: x}\ntxn_pool: {weights: {a: -1}}")
        assert issues and issues[0].is_error

    def test_empty_name_is_rejected(self):
        issues = check_dsl_text("meta: {name: '  '}")
        assert issues and issues[0].is_error


class TestParseFailuresAreIssuesNotExceptions:
    """解析不了也是"这份 DSL 不行"的一种 —— 不该掀异常给调用方。"""

    def test_broken_yaml(self):
        issues = check_dsl_text("meta: {name: x\n")
        assert issues and issues[0].rule == "yaml_parse_error"

    def test_empty_document(self):
        assert check_dsl_text("").pop().rule == "empty_document"

    def test_top_level_is_a_list(self):
        assert check_dsl_text("- a\n- b\n").pop().rule == "not_a_mapping"

    def test_load_dsl_aggregates_into_one_error(self):
        """要用它（编译）时抛异常，但报错信息里**把所有的错一次列全**。"""
        with pytest.raises(IsaGenError) as info:
            load_dsl("meta: {name: x}\norchestration: {epochs: 0}\n"
                     "txn_pool: {weights: {a: -1}}")
        message = str(info.value)
        assert "2 处" in message and "epochs" in message


class TestSchemaFileMatchesModel:
    def test_generated_file_is_in_sync(self):
        """`schema/dsl.schema.json` 由 pydantic 模型生成 —— 对不上就是有人手改了它。

        这是"两份手写的契约一定会漂移"那个坑的堵法：契约文件存在（外部可读、
        可 diff），但**不可能**和代码对不上。
        """
        mismatch = schema_file_matches_model()
        assert mismatch is None, f"契约文件过时了：{mismatch}；跑 gen_dsl_schema 重生成"

    def test_the_file_is_a_real_json_schema(self):
        from ..analysis.schema_check import DSL_SCHEMA_FILE
        schema = json.loads(DSL_SCHEMA_FILE.read_text(encoding="utf-8"))
        assert schema["additionalProperties"] is False
        assert set(schema["properties"]) == {
            "meta", "resources", "txn_pool", "shape_space", "precision_mix",
            "intent", "orchestration", "harness", "alloc"}


class TestSeed:
    def test_seed_defaults_to_the_fallback_and_is_backfilled(self):
        """文档字段约定第 1 条：缺省取时间戳，**落盘的 case.json 回填实际 seed**。"""
        doc = load_dsl(MINIMAL)
        assert doc.meta.seed is None
        resolved = doc.seed_or(999)
        assert resolved == 999
        assert doc.with_seed(resolved).meta.seed == 999

    def test_derived_seed_is_deterministic(self):
        assert derive_seed(12345, "tensor:img") == derive_seed(12345, "tensor:img")

    def test_different_names_diverge(self):
        seeds = {derive_seed(12345, f"tensor:{n}") for n in ("a", "b", "c", "d")}
        assert len(seeds) == 4

    def test_different_cases_diverge(self):
        assert derive_seed(1, "x") != derive_seed(2, "x")

    def test_derived_seed_is_a_valid_rng_seed(self):
        """必须落在非负整数里 —— 负数种子在日志与复现脚本里都难用。"""
        for name in ("", "a", "张量", "tensor:with:colons"):
            assert 0 <= derive_seed(7, name) < (1 << 63)

    def test_adjacent_names_do_not_collide(self):
        """`a` 与 `ab` 这类相邻名字要分开 —— 简单相加那种做法会在这里撞。"""
        assert derive_seed(1, "a") != derive_seed(1, "ab")


def test_yaml_round_trip_of_the_example():
    """例子本身要是合法 YAML —— 抄错缩进时这条会先红。"""
    assert yaml.safe_load(DOC_EXAMPLE)["meta"]["seed"] == 12345
