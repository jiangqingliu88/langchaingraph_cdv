"""**三层模型的关联** —— case / 覆盖率 / 约束，四条边都靠名字对齐。

这一层要拦的是**跨文件的错**，而这类错**单看任何一个文件都发现不了**：

    case 模型写  `无依赖`      coverage 写 `NONE`
    case 模型写  `Vector`      coverage 写 `VECTOR`

两边的 yaml 各自都能过 schema、都能解析、都"看着对"。只有把两份摆在一起才看得出
它们说的**不是一回事** —— 而后果是覆盖率的 bin 收的是**另一个取值**（编译通过、
跑得动、数字是错的）。

所以这里重点钉三件事：
  1. **边 ① 靠 bin 名，不靠字段名**（字段是建模概念，signal 是实现名字，本来就不该同名）；
  2. **级联不误报**（解析丢掉的坏条目，不该让别的边跟着报一串"没人引用"）；
  3. **有 error 就不许渲染 SV**（半个 bin / 错的取值，比生成不了更坏）。
"""
from __future__ import annotations

import yaml

from src.tools.casemodel_tools.associate import associate

CASES = """
version: "1.0"
tests:
  - object: NpuScheduler
    object_code: NPU
    sub_objects: [{id: STG-01, name: 队列, code: QUEUE}]
dimensions:
  - id: D_type
    name: 指令类型
    fields:
      - name: 指令类型
        type: enum
        values: [MAC, Vector, Scalar, DMA]
        cover_bins: [cp_mac, cp_vec, cp_scl, cp_dma]
  - id: D_level
    name: 队列水位
    fields:
      - name: 队列水位
        type: range
        min: 0
        max: 32
        boundary: ["0", "8", "16", "32"]
        cover_bins: [cp_empty, cp_low, cp_high]
themes:
  - {id: TH-P0, name: 基础, priority: P0, dimensions: [指令类型], method: D}
cross_matrix:
  指令类型×队列水位: required
"""

COVERAGE = """
version: "1.0"
module:
  name: npu_sched
  object_ref: NpuScheduler
coverpoints:
  - id: CP_TYPE
    name: cp_instr_type
    signal: instr_type
    bins:
      - {name: cp_mac, values: [MAC]}
      - {name: cp_vec, values: [VECTOR]}
      - {name: cp_scl, values: [SCALAR]}
      - {name: cp_dma, values: [DMA]}
  - id: CP_LEVEL
    name: cp_queue_level
    signal: queue_level
    bins:
      - {name: cp_empty, values: [0]}
      - {name: cp_low,   ranges: [[1, 15]]}
      - {name: cp_high,  ranges: [[16, 32]]}
crosses:
  - id: X_TYPE_LEVEL
    name: X_type_level
    cross: [cp_instr_type, cp_queue_level]
    matrix_ref: 指令类型×队列水位
"""


def _assoc(cases: str = CASES, cov: str = COVERAGE, cons: str = "") -> dict:
    return associate(cases, cov, cons)


def _errors(payload: dict) -> list:
    return [i for i in payload["issues"] if i["severity"] == "error"]


class TestASelfConsistentPairPasses:
    """两边自洽时**一条 error 都不该有** —— 否则工具会被当成噪音关掉。"""

    def test_no_errors(self):
        p = _assoc()
        assert p["renderable"] is True, _errors(p)

    def test_the_link_table_names_the_case_field(self):
        """关联表要说清"这个覆盖点连到哪个 case 字段" —— 靠的是 **cover_bins 名字**。"""
        links = {l["coverpoint"]: l for l in _assoc()["links"]["coverpoints"]}
        assert links["cp_instr_type"]["case_field"] == "D_type.指令类型"
        assert links["cp_queue_level"]["case_field"] == "D_level.队列水位"

    def test_every_matrix_key_is_referenced(self):
        """② 边：case 声明的矩阵键要被覆盖率模型的 `matrix_ref` 引用。"""
        assert not [i for i in _assoc()["issues"] if i["edge"] == "②"]

    def test_the_method_mapping_is_reported(self):
        methods = _assoc()["links"]["methods"]
        assert methods and methods[0]["theme"] == "TH-P0"
        assert "定向" in methods[0]["constraint_form"]


class TestEdgeOneIsAboutBinNamesNotFieldNames:
    """**字段名与信号名不该一样** —— 边 ① 靠 `cover_bins` 的名字。

    实测踩过：按信号名找字段（`signal: instr_type` 去对 `fields[].name: 指令类型`）
    全落空，取值**全投影成 0**，而编译不报错 —— 每个 bin 收的都是 0。
    """

    def test_a_different_signal_name_still_links(self):
        cov = COVERAGE.replace("signal: instr_type", "signal: totally_another_name")
        p = _assoc(cov=cov)
        links = {l["coverpoint"]: l for l in p["links"]["coverpoints"]}
        assert links["cp_instr_type"]["case_field"] == "D_type.指令类型"

    def test_a_bin_name_the_case_model_never_declares_is_a_warning(self):
        """覆盖模型的 bin 没有 case 字段认领它 → 空转的仓（有人声明没人打）。"""
        cov = COVERAGE.replace("      - {name: cp_dma, values: [DMA]}",
                               "      - {name: cp_dma, values: [DMA]}\n"
                               "      - {name: cp_ghost, values: [MAC]}")
        p = _assoc(cov=cov)
        ghosts = [i for i in p["issues"] if i["subject"] == "cp_ghost"]
        assert ghosts and ghosts[0]["severity"] == "warning"

    def test_a_case_bin_missing_from_coverage_is_an_error(self):
        cov = COVERAGE.replace("      - {name: cp_scl, values: [SCALAR]}\n", "")
        p = _assoc(cov=cov)
        hits = [i for i in _errors(p) if i["edge"] == "①"]
        assert hits and "cp_scl" in hits[0]["message"]


class TestCrossLanguageMismatchIsReportedNotGuessed:
    """`无依赖` 与 `NONE` 是**同一个东西吗**？机器不知道 —— 所以报，不猜。

    猜错的代价：`bins x = {0};` 生成得出来、编译得过，收的却是**另一个取值**。
    """

    def test_a_symbol_missing_from_the_case_field_is_an_error(self):
        cases = CASES.replace("values: [MAC, Vector, Scalar, DMA]",
                              "values: [MAC, VECTOR, SCALAR, DMA]")
        cov = COVERAGE.replace("values: [VECTOR]", "values: [NOPE]")
        p = _assoc(cases=cases, cov=cov)
        hits = [i for i in _errors(p) if "NOPE" in i["message"]]
        assert hits, _errors(p)
        assert "对不上" in hits[0]["message"]

    def test_case_only_differences_match_but_are_noted(self):
        """`Vector` ↔ `VECTOR` 只是拼写不一致 —— 按大小写无关匹配，但要提醒统一。"""
        p = _assoc()          # CASES 写 Vector/Scalar，COVERAGE 写 VECTOR/SCALAR
        assert not _errors(p)
        assert any("大小写无关" in n for n in p["notes"])

    def test_an_unprojectable_value_kills_the_bin_not_the_whole_model(self):
        cov = COVERAGE.replace("values: [DMA]", "values: [NO_SUCH_VALUE]")
        p = _assoc(cov=cov)
        assert not p["renderable"]
        # 只有那一个 bin 出事，另一个覆盖点照常在关联表里
        assert any(l["coverpoint"] == "cp_queue_level"
                   for l in p["links"]["coverpoints"])


class TestCascadeIsNotReported:
    """**解析丢掉的坏条目，不该让别的边跟着报一串"没人引用"**。

    实测踩过：3 个交叉因为引用了不存在的 coverpoint 被丢掉，于是它们的
    `matrix_ref` 看不见了 —— 边 ② 一口气报了 6 条"case 声明的矩阵键没人引用"，
    而真相是"3 个交叉被丢了"。**丢的原因已经报过一遍了**，再报一遍是噪音。
    """

    def test_the_matrix_edge_still_sees_dropped_crosses_refs(self):
        # 把第二个 coverpoint 的名字改坏 → 那条交叉会被丢
        cov = COVERAGE.replace("name: cp_queue_level", "name: renamed_cp")
        p = _assoc(cov=cov)
        # 交叉确实被丢了（有 error 说它引用不存在）
        assert any("不存在的 coverpoint" in i["message"] for i in _errors(p))
        # 但**边 ② 不该因此报"没人引用"** —— matrix_ref 写在原始 yaml 里，看得见
        assert not [i for i in p["issues"] if i["edge"] == "②"]


class TestTheMatrixEdge:
    def test_a_key_nobody_references_is_an_error(self):
        cases = CASES + "\ncross_matrix_extra: {}\n" if False else CASES.replace(
            "  指令类型×队列水位: required",
            "  指令类型×队列水位: required\n  队列水位×指令类型: optional")
        p = _assoc(cases=cases)
        hits = [i for i in _errors(p) if i["edge"] == "②"]
        assert len(hits) == 1 and "队列水位×指令类型" in hits[0]["subject"]

    def test_a_matrix_ref_pointing_nowhere_is_an_error(self):
        cov = COVERAGE.replace("matrix_ref: 指令类型×队列水位",
                               "matrix_ref: 不存在的矩阵键")
        p = _assoc(cov=cov)
        hits = [i for i in _errors(p) if i["edge"] == "②"]
        assert hits and "不存在的矩阵键" in hits[0]["message"]


class TestTheConstraintEdges:
    """③④ 是**软边**，而且**只能查到一半** —— 查不到的那半要如实说。"""

    CONS = """
constraint:
  name: npu_cons
transactions:
  - { name: apb_master, type: APB_master_seq_item }
policies:
  - name: p_ok
    applies_to: [apb_master]
  - name: p_dangling
    applies_to: [no_such_port]
combinator:
  default_mode: APPLY_ALL
"""

    def test_a_dangling_applies_to_is_a_warning(self):
        p = _assoc(cons=self.CONS)
        hits = [i for i in p["issues"] if i["edge"] == "③"]
        assert hits and hits[0]["severity"] == "warning"
        assert "no_such_port" in hits[0]["message"]

    def test_the_half_that_cannot_be_checked_is_stated(self):
        """端口名↔信号名的对应关系**没有建模** —— 查不到就别说查到了。"""
        p = _assoc(cons=self.CONS)
        assert any("端口名↔信号名" in n for n in p["notes"])

    def test_an_unknown_method_is_a_warning(self):
        cases = CASES.replace("method: D", "method: NOPE")
        p = _assoc(cases=cases, cons=self.CONS)
        hits = [i for i in p["issues"] if i["edge"] == "④"]
        assert hits and "NOPE" in hits[0]["subject"]


class TestFailureIsLoud:
    def test_a_broken_case_model_returns_an_error_not_a_throw(self):
        assert "error" in _assoc(cases="- just\n- a\n- list\n")

    def test_an_empty_coverage_model_is_not_renderable(self):
        p = _assoc(cov="version: '1.0'\n")
        assert p["renderable"] is False
