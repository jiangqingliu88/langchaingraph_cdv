"""覆盖率模型的**往返**与关联校验 —— 流水线里那条"对象 → 文本 → 对象"的路。

## 为什么需要往返

覆盖率模型有两条来路：

    CLI / 人写    coverage.yaml 文本   → `parse_coverage_model`
    流水线        case 模型 → `coverage_model()` **直接得到对象，没有文本**

而 `associate`（三模型关联校验）吃文本。于是流水线里跑不了关联校验 ——
`env/cons/` 与覆盖点之间的断点只活在终端上，进不了签核材料。

`coverage_model_to_dict()` 补上"对象 → 文本"这一步。**它与解析侧必须一一对应**：
字段名对不上不会报错，只会**静默少东西**（解析方 `item.get("x")` 拿到 `None`
就跳过该条，而调用方以为"关联通过"）。所以这里逐项钉住往返。

## 本文件顺带钉住的四个既有 bug（都在同一条链上，都是"看着没事、其实早坏了"）

  1. `_find_field` 对**对象形式**的 `cover_bins`（`{name: empty, at: 0}`）直接
     `TypeError` —— `set()` 里塞 dict。npu_sched 整份模型都用对象形式。
  2. `associate` 收集 case 侧 bin 名时用 `isinstance(b, str)` 过滤，
     **把对象形式全丢掉** → 边 ① 整条查不动，反向那条对每个 bin 误报。
  3. `coverage_model()` 造交叉时**从不填 `matrix_ref`**（恒空串）→ 边 ② 对所有
     `cross_matrix` 键都报"没有任何交叉引用它"（实测 7 条全报）。
  4. `_parse_coverpoint` 用**匹配到的字段**的维度，**忽略 yaml 里显式的
     `dimension:`** → 两个维度 bin 名相同时（`D_type` 与 `D_unit` 都是
     `[mac, vector, scalar, dma]`）判成第一个，而后果是边 ⑤ 报一条**指向错误
     方向**的告警。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.tools.generation.casemodel_tools.associate import associate, build_constraint
from src.tools.generation.casemodel_tools.coverage import (
    coverage_model,
    coverage_model_to_dict,
    declared_bin_names,
    parse_coverage_model,
)
from src.tools.generation.casemodel_tools.repository import load_models_from_text

NPU = Path("specs/npu_sched/casemodel.yaml")


@pytest.fixture(scope="module")
def npu():
    case_text = NPU.read_text(encoding="utf-8")
    model = load_models_from_text(case_text)[0].resolve()
    cm = coverage_model(model, "npu_sched")
    return case_text, model, cm


class TestTheRoundTripKeepsEverything:
    def test_coverpoints_and_crosses_survive(self, npu):
        _case, model, cm = npu
        back = parse_coverage_model(
            json.dumps(coverage_model_to_dict(cm), ensure_ascii=False), model)
        assert len(back.coverpoints) == len(cm.coverpoints)
        assert len(back.crosses) == len(cm.crosses), (
            "交叉丢了 —— 多半是序列化少了 `cross`（覆盖点名列表），"
            "解析侧读不到就判「少于两项」跳过")
        assert back.errors == [], back.errors

    def test_the_dimension_survives(self, npu):
        """**这条钉的是 bug 4**：`D_type` 与 `D_unit` 的 bin 名完全相同
        （`[mac, vector, scalar, dma]`），按名字找字段只会拿到**第一个**。

        显式 `dimension:` 是作者的**权威声明**，必须赢过那次猜测。
        """
        _case, model, cm = npu
        back = parse_coverage_model(
            json.dumps(coverage_model_to_dict(cm), ensure_ascii=False), model)
        assert {c.dimension for c in back.coverpoints} == \
            {c.dimension for c in cm.coverpoints}
        unit = next(c for c in back.coverpoints if c.signal == "issue_unit")
        assert unit.dimension == "D_unit", (
            f"issue_unit 被判成 {unit.dimension} —— 显式 dimension 没生效")

    def test_the_matrix_ref_survives(self, npu):
        """**这条钉的是 bug 3**：`matrix_ref` 为空 → 边 ② 变成一条死边。"""
        _case, _model, cm = npu
        assert all(cx.matrix_ref for cx in cm.crosses), \
            "有交叉的 matrix_ref 是空的 —— 边 ②（case 矩阵键 ↔ matrix_ref）查不动"
        back = parse_coverage_model(
            json.dumps(coverage_model_to_dict(cm), ensure_ascii=False), _model)
        assert {c.matrix_ref for c in back.crosses} == \
            {c.matrix_ref for c in cm.crosses}


class TestTheObjectFormBinsAreNotDropped:
    """**bug 1 与 bug 2**：对象形式的 `cover_bins` 走到哪都不能被丢掉。"""

    def test_declared_bin_names_reads_both_forms(self, npu):
        _case, model, _cm = npu
        fld = next(f for d in model.dimensions if d.key == "D_queue"
                   for f in d.fields)
        names = declared_bin_names(fld)
        # D_queue 用的是**对象形式**（`{name: empty, at: 0}` 等）
        assert {"empty", "low", "mid", "high", "near_full", "full"} <= names

    def test_the_edge_one_check_sees_the_object_form(self, npu):
        """边 ① 若把对象形式当空气，反向那条会对**每个** bin 误报。"""
        case_text, _model, cm = npu
        a = associate(case_text, json.dumps(coverage_model_to_dict(cm),
                                            ensure_ascii=False))
        one = [i for i in a["issues"] if i["edge"] == "①"]
        assert not [i for i in one if "没有任何字段认领" in i["message"]], \
            f"对象形式的 cover_bins 被当成不存在：{one[:2]}"


class TestTheWholeAssociationPassesOnTheRealModel:
    def test_no_errors_and_no_warnings(self, npu):
        """真实模型上五条边全通 —— 一条 error / warning 都不该有。

        这不是"凑个绿"，是这条链上四个 bug 的**汇总验收**：任何一个没修，
        这里都会红（② 报 7 条、① 报十几条、⑤ 报 4 条 —— 都实测过）。
        """
        case_text, _model, cm = npu
        cons = build_constraint(
            case_text, [{"name": "npu_sched_in",
                         "type": "npu_sched_in_master_seq_item"}])["constraint_yaml"]
        a = associate(case_text, json.dumps(coverage_model_to_dict(cm),
                                            ensure_ascii=False), cons)
        assert a["counts"]["error"] == 0, [i["message"] for i in a["issues"]
                                           if i["severity"] == "error"][:3]
        assert a["counts"]["warning"] == 0, [i["message"] for i in a["issues"]
                                             if i["severity"] == "warning"][:3]
        assert a["renderable"] is True
