"""一份模型测多个对象 —— `tests:` 写法的扇出与合并。

清单里现在有两种等价写法：

    object: FlowControl          # 写法一：一个对象
    dimensions: [...]

    tests:                       # 写法二：N 个对象，共享下面那一套属性空间
      - {object: FlowControl, object_code: FC}
      - {object: Arbiter,     object_code: ARB}
    dimensions: [...]

这套测试钉两件事：

1. **扇出是纯叠加** —— 共享段落到每个对象头上，条目里的键覆盖共享键。
   多对象没有自己的解析路径，每个对象仍然走 `model_from_dict`。
2. **合并语义**（与用户确认过的「一套评分 + 每对象一棵树」）—— 矩阵 / 取值
   覆盖 / 评分是**属性空间**的属性，只算一次；组织树与 case 是**各对象**的，
   每人一份。case 尤其不能合并后再生成：`case_id` 的前缀带着对象代号，
   合成一棵树之后就再也分不出哪个节点属于哪个对象了。
"""
from __future__ import annotations

import pytest
import yaml

from src.layers.l3_decision.casemodel.analysis import analyze
from src.layers.l3_decision.casemodel.analysis.multi import (analyze_many, generate_many,
                                                      merge_models)
from src.layers.l3_decision.casemodel.domain import CaseModelError
from src.layers.l3_decision.casemodel.repository import (load_models,
                                                  load_models_from_text)

from .conftest import CPU, FC


# ════════════════════════════════════════════════════════════
# 造模型
# ════════════════════════════════════════════════════════════

def dimension(dim_id="D_x", values=("A", "B")):
    return {"id": dim_id, "name": dim_id, "fields": [
        {"name": f"{dim_id}_f", "type": "set", "values": list(values)}]}


def two_objects():
    """写法二的骨架：两个对象 + 一套共享属性空间。

    专题是 case 的唯一来源（没有专题就没有 case），所以共享段里必须有一个 ——
    这和真实清单一样。
    """
    return {
        "tests": [
            {"object": "FlowControl", "object_cn": "流控", "object_code": "FC",
             "sub_objects": [{"id": "FC-01", "name": "接收侧", "code": "RECV"}]},
            {"object": "Arbiter", "object_cn": "仲裁", "object_code": "ARB",
             "sub_objects": [{"id": "ARB-01", "name": "轮询", "code": "RR"}]},
        ],
        "dimensions": [dimension()],
        "themes": [{"id": "TH-P0-ALL", "name": "全量", "priority": "P0",
                    "applies_to": ["接收侧", "轮询"],
                    "dimensions": ["D_x"], "method": "D"}],
        "methods": ["D", "RND"],
        "checks": ["FUNC"],
        "generation": {"seed": 7},
    }


def load(data):
    return load_models_from_text(yaml.safe_dump(data, allow_unicode=True))


# ════════════════════════════════════════════════════════════
# 扇出
# ════════════════════════════════════════════════════════════

class TestFanOut:
    def test_top_level_object_is_still_one_model(self):
        """写法一没被写法二挤掉 —— 老清单一直有效。"""
        models = load_models(CPU)
        assert len(models) == 1
        assert models[0].object == "CpuPipeline"

    def test_one_model_per_entry(self):
        models = load(two_objects())
        assert [m.object for m in models] == ["FlowControl", "Arbiter"]
        assert [m.object_code for m in models] == ["FC", "ARB"]

    def test_shared_space_reaches_every_object(self):
        """共享的维度 / 方法 / 检查 / 生成参数，每个对象都拿得到。"""
        for model in load(two_objects()):
            assert [d.id for d in model.dimensions] == ["D_x"]
            assert model.methods == ["D", "RND"]
            assert model.checks == ["CHECK-FUNC"]      # 代号经 vocab 归一
            assert model.generation.seed == 7

    def test_entry_overrides_the_shared_key(self):
        data = two_objects()
        data["tests"][1]["object_cn"] = "轮询仲裁"
        assert [m.object_cn for m in load(data)] == ["流控", "轮询仲裁"]

    def test_each_object_keeps_its_own_tree(self):
        models = load(two_objects())
        assert [n.name for n in models[0].org_root] == ["接收侧"]
        assert [n.name for n in models[1].org_root] == ["轮询"]

    def test_source_records_which_object_it_came_from(self):
        """source 一路带着对象名 —— 报错说得出「是哪一个对象的问题」。"""
        models = load(two_objects())
        assert models[0].source.endswith("FlowControl")
        assert models[1].source.endswith("Arbiter")


class TestFanOutErrors:
    def test_empty_tests_is_an_error(self):
        with pytest.raises(CaseModelError, match="tests"):
            load({"tests": [], "dimensions": [dimension()]})

    def test_tests_must_be_a_list(self):
        with pytest.raises(CaseModelError, match="tests"):
            load({"tests": {"object": "X"}, "dimensions": [dimension()]})

    def test_entry_must_be_a_mapping(self):
        with pytest.raises(CaseModelError, match=r"tests\[1\]"):
            load({"tests": [{"object": "A"}, "B"], "dimensions": [dimension()]})

    def test_duplicate_object_code_is_rejected(self):
        """代号会进 `case_id` 的 `TC-<代号>-…`，撞了就会产出重名的 case。

        这是**报错而不是警告**：重名 case 在回归结果里是分不开的。
        """
        data = two_objects()
        data["tests"][1]["object_code"] = "FC"
        with pytest.raises(CaseModelError, match="object_code"):
            load(data)

    def test_distinct_codes_are_fine(self):
        data = two_objects()
        data["tests"][1]["object_code"] = "ARB"
        assert len(load(data)) == 2

    def test_derived_codes_can_collide_too(self):
        """没写 object_code 时按对象名推 —— 推出来一样也得拦。"""
        data = two_objects()
        for entry in data["tests"]:
            entry.pop("object_code")
        data["tests"][1]["object"] = "FlowControl"     # 同名 → 同代号
        with pytest.raises(CaseModelError, match="object_code"):
            load(data)


# ════════════════════════════════════════════════════════════
# 合并
# ════════════════════════════════════════════════════════════

class TestMerge:
    def test_one_model_merges_to_itself(self):
        """单对象时是恒等 —— 于是单对象那条路上的行为一个字节都没变。"""
        (model,) = load_models(CPU)
        assert merge_models([model]) is model

    def test_names_are_joined_not_overwritten(self):
        merged = merge_models(load(two_objects()))
        assert merged.object == "FlowControl+Arbiter"
        assert merged.object_cn == "流控、仲裁"

    def test_trees_are_concatenated(self):
        merged = merge_models(load(two_objects()))
        assert [n.name for n in merged.org_root] == ["接收侧", "轮询"]
        assert [n.name for n in merged.sub_objects] == ["接收侧", "轮询"]

    def test_attribute_space_comes_from_the_head(self):
        """维度空间只有一个（它就是共享段），不是把两边拼起来。"""
        merged = merge_models(load(two_objects()))
        assert [d.id for d in merged.dimensions] == ["D_x"]
        assert merged.methods == ["D", "RND"]

    def test_merge_does_not_mutate_the_inputs(self):
        models = load(two_objects())
        before = [m.object for m in models]
        merge_models(models)
        assert [m.object for m in models] == before


# ════════════════════════════════════════════════════════════
# 生成 / 分析
# ════════════════════════════════════════════════════════════

class TestMany:
    def test_case_ids_keep_their_object_prefix(self):
        """每个对象的 case_id 前缀是它自己的代号 —— 合并成一棵树就分不出来了，
        所以 case 必须在各对象的上下文里生成（这就是 generate_many 存在的理由）。"""
        result = generate_many(load(two_objects()))
        prefixes = {c.case_id.split("-")[1] for c in result.cases}
        assert prefixes == {"FC", "ARB"}

    def test_cases_carry_their_own_object_name(self):
        result = generate_many(load(two_objects()))
        assert {c.object for c in result.cases} == {"FlowControl", "Arbiter"}

    def test_max_cases_is_per_object_not_global(self):
        """全局上限会让排在后面的对象被前面的挤光 —— 那不是「每个对象都测一测」。"""
        models = load(two_objects())
        capped = generate_many(models, max_cases=1)
        assert {c.object for c in capped.cases} == {"FlowControl", "Arbiter"}

    def test_used_sets_are_unioned_without_duplicates(self):
        """两个对象用的是同一套专题 —— 合并后不能变成两条。"""
        result = generate_many(load(two_objects()))
        assert result.themes_used == ["TH-P0-ALL"]
        assert result.methods_used == ["D"]

    def test_analyze_many_of_one_model_is_plain_analyze(self):
        (model,) = load_models(CPU)
        assert analyze_many([model]).score.total == analyze(model).score.total

    def test_one_score_for_the_whole_attribute_space(self):
        """评分只有一个数 —— 它是属性空间的属性，不是某个对象的。"""
        result = analyze_many(load(two_objects()))
        assert isinstance(result.score.total, float)

    def test_report_names_every_object(self):
        result = analyze_many(load(two_objects()))
        assert result.model.object == "FlowControl+Arbiter"

    def test_coverage_and_matrix_are_computed_once(self):
        """维度级的结构只依赖共享空间：给一个对象还是两个，它都不该变。"""
        one = analyze_many(load({**two_objects(), "tests": [two_objects()["tests"][0]]}))
        two = analyze_many(load(two_objects()))
        assert len(one.dimension_coverage) == len(two.dimension_coverage)
        assert {d.total for d in one.dimension_coverage} == \
               {d.total for d in two.dimension_coverage}


# ════════════════════════════════════════════════════════════
# 示例清单
# ════════════════════════════════════════════════════════════

@pytest.mark.parametrize("path", (CPU, FC), ids=lambda p: p.name)
def test_examples_load_through_the_many_path(path):
    """示例清单（含 `tests:` 写法）从 `load_models` 进来就能分析，不用特判。"""
    models = load_models(path)
    assert models
    assert analyze_many(models).model.dimensions
