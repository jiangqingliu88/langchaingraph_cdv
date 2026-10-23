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

from src.tools.casemodel_tools.associate import (
    COMBINATOR_MODES,
    METHOD_TO_CONSTRAINT,
    METHOD_TO_POLICY,
    associate,
    build_constraint,
)

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


# ══════════════════════════════════════════════════════════════
# 约束模型生产者 —— 方法学的第三条腿
# ══════════════════════════════════════════════════════════════
#
# 要钉住的就一件事：**它不生成空壳**。这个仓库里最贵的一类 bug 是
# "生成得出来、编译得过、东西是空的/错的" —— 一个空的 `transactions` 渲染出来
# 的协调序列正是那个形状（发送循环一次都不进），所以宁可不生成。

class TestTheConstraintProducer:
    PORTS = [{"name": "apb_master", "type": "APB_master_seq_item"}]

    def test_no_ports_is_an_error_not_an_empty_skeleton(self):
        p = build_constraint(CASES, [])
        assert "error" in p
        assert "空壳" in p["error"]

    def test_one_policy_per_theme_that_declares_a_method(self):
        p = build_constraint(CASES, self.PORTS)
        assert p["policy_count"] == 1
        # 定向（D）→ 自定义名策略 + 最严的组合模式
        assert p["policies"][0]["name"] == "p_th_p0_directed"
        assert p["default_mode"] == "APPLY_FIRST_MATCH"

    def test_the_ports_are_carried_verbatim(self):
        p = build_constraint(CASES, self.PORTS)
        assert p["transactions"] == [{"name": "apb_master",
                                      "type": "APB_master_seq_item"}]
        assert p["policies"][0]["applies_to"] == ["apb_master"]

    def test_a_port_written_name_colon_type_is_accepted(self):
        """命令行那条写法（手打快）与 dict 写法必须等价。"""
        assert (build_constraint(CASES, ["apb_master:APB_master_seq_item"])
                ["transactions"] == self.PORTS)

    def test_a_port_the_tool_cannot_read_is_refused_not_skipped(self):
        """**不跳、不猜** —— 跳过就是"给了 3 个端口、生成出 2 个"，而没人会去数。"""
        p = build_constraint(CASES, ["apb_master"])          # 缺 `:类型`
        assert "error" in p

    def test_duplicate_ports_are_refused(self):
        p = build_constraint(CASES, ["a:T", "a:T"])
        assert "error" in p and "重复" in p["error"]

    def test_an_unknown_method_is_an_error_not_a_silent_skip(self):
        """`build_theme` 把认不出的方法**静默归一成空** —— 这里必须拦住。"""
        p = build_constraint(CASES.replace("method: D", "method: NOPE"), self.PORTS)
        assert "error" in p and "NOPE" in p["error"]

    def test_no_method_at_all_is_an_error(self):
        p = build_constraint(CASES.replace(", method: D", ""), self.PORTS)
        assert "error" in p

    def test_the_default_mode_follows_the_top_priority_theme(self):
        """出厂行为跟 **P0** 那批一致 —— 取最松的会让定向批次不再定向。"""
        cases = CASES.replace(
            "  - {id: TH-P0, name: 基础, priority: P0, dimensions: [指令类型], method: D}",
            "  - {id: TH-P2, name: 随机, priority: P2, method: RND}\n"
            "  - {id: TH-P0, name: 基础, priority: P0, dimensions: [指令类型], method: G}")
        p = build_constraint(cases, self.PORTS)
        assert p["default_mode"] == "APPLY_ALL"          # P0 是 G，不是 P2 的加权随机
        assert [m["theme"] for m in p["mapping"]] == ["TH-P0", "TH-P2"]

    def test_every_mode_the_renderer_needs_is_emitted(self):
        """五个模式**全列**：组合器的 `case` 分支写死了 5 个，少一个 vlog 就报错。"""
        modes = build_constraint(CASES, self.PORTS)["combinator"]["modes"]
        assert modes == COMBINATOR_MODES
        assert len(modes) == 5

    def test_the_yaml_round_trips_and_keeps_the_parser_contract(self):
        """键名是**和 gen_uvm 之间的文件格式契约** —— 钉在这里，改坏了立刻红。"""
        p = build_constraint(CASES, self.PORTS)
        doc = yaml.safe_load(p["constraint_yaml"])
        assert set(doc) == {"constraint", "transactions", "policies", "combinator"}
        assert set(doc["policies"][0]) == {"name", "description", "priority",
                                           "params", "applies_to", "dimensions",
                                           "assignments", "backed"}
        assert doc["combinator"] == p["combinator"]
        # 策略名要能进 SV：ASCII
        assert doc["policies"][0]["name"].isascii()
        assert doc["constraint"]["name"].endswith("_cons")
        assert doc["constraint"]["name"].isascii()

    def test_an_observe_only_model_has_no_assignments(self):
        """没有 `stimulus.field` 的维度驱动不了 —— 策略如实标成骨架。"""
        p = build_constraint(CASES, self.PORTS)
        assert p["backed_policy_count"] == 0
        assert p["unbacked_policy_count"] == p["policy_count"]
        assert p["policies"][0]["assignments"] == []
        assert p["policies_are_skeletons"] is True

    def test_a_drivable_dimension_compiles_into_assignments(self):
        """`stimulus.field` + agent 字段 → `apply()` 里的真实赋值。

        这是"约束有没有在约束"从布尔声明变成**可执行代码**的那一步。
        """
        cases = CASES.replace(
            "        cover_bins: [cp_mac, cp_vec, cp_scl, cp_dma]",
            "        cover_bins: [cp_mac, cp_vec, cp_scl, cp_dma]\n"
            "    stimulus: {field: instr_type}")
        p = build_constraint(cases, self.PORTS,
                             agent_fields={"apb_master": ["instr_type"]})
        pol = p["policies"][0]
        assert pol["backed"] is True
        assert pol["assignments"] == [{
            "trans": "apb_master", "field": "instr_type",
            "values": [0, 1, 2, 3], "mode": "cycle"}]
        assert p["backed_policy_count"] == 1
        assert p["policies_are_skeletons"] is False

    def test_a_field_that_belongs_to_no_agent_is_reported_not_guessed(self):
        cases = CASES.replace(
            "        cover_bins: [cp_mac, cp_vec, cp_scl, cp_dma]",
            "        cover_bins: [cp_mac, cp_vec, cp_scl, cp_dma]\n"
            "    stimulus: {field: instr_typo}")
        p = build_constraint(cases, self.PORTS,
                             agent_fields={"apb_master": ["instr_type"]})
        assert p["policies"][0]["assignments"] == []
        assert any("instr_typo" in n for n in p["notes"])

    def test_the_generated_yaml_passes_the_association_edges(self):
        """**闭环**：生产者的产物喂回校验器，③④ 一条都不该报。"""
        payload = build_constraint(CASES, self.PORTS)
        a = associate(CASES, COVERAGE, payload["constraint_yaml"])
        assert not [i for i in a["issues"] if i["edge"] in ("③", "④")], a["issues"]


class TestThePolicyCarriesTheDimensionsItDrives:
    """策略要带 `dimensions` —— 它是 coverage↔constraint 那条边（⑤）的桥墩。

    ## 为什么这个字段值钱

    没有它，三份模型只连成 "V"：case↔coverage（①②）、case↔约束（④），
    **coverage↔约束之间一条边都没有** —— "这条策略驱动的维度到底有没有人量它"
    没人答得了。`dimensions` 一加，两条边就闭合了。

    ## 两个必须归一的地方（都实测踩过）

      · **别名 → canonical key**：专题写 `dimensions: [指令类型]`（name），
        而覆盖率侧是 `coverpoint.dimension == D_type`（id）—— 不归一，
        一条明明连上的边会被报成"没人驱动这个维度"。
      · **通配要展开**：`dimensions: ["*"]` 的语义是"全部维度"
        （`Theme.covers_all_dimensions`）—— 照原样带个 `'*'` 出去，
        所有维度都会被报成没人驱动（npu_sched 的 TH-B11 正是通配）。
    """

    PORTS = [{"name": "apb_master", "type": "APB_master_seq_item"}]

    def test_the_theme_dimension_is_carried_as_a_canonical_key(self):
        p = build_constraint(CASES, self.PORTS)
        # CASES 的专题写 `dimensions: [指令类型]`（name），维度 id 是 D_type
        assert p["policies"][0]["dimensions"] == ["D_type"]

    def test_a_wildcard_theme_drives_every_dimension(self):
        cases = CASES.replace("dimensions: [指令类型]", 'dimensions: ["*"]')
        p = build_constraint(cases, self.PORTS)
        assert set(p["policies"][0]["dimensions"]) == {"D_type", "D_level"}
        assert "*" not in p["policies"][0]["dimensions"], \
            "通配没展开 —— 边 ⑤ 会把所有维度都报成没人驱动"

    def test_an_unresolvable_dimension_reference_is_kept_verbatim(self):
        """解不出来的引用**原样留着** —— 边 ⑤ 会如实报它，比悄悄丢掉强。"""
        cases = CASES.replace("dimensions: [指令类型]", "dimensions: [D_NO_SUCH]")
        p = build_constraint(cases, self.PORTS)
        assert p["policies"][0]["dimensions"] == ["D_NO_SUCH"]


class TestTheCoverageConstraintEdge:
    """边 ⑤：**覆盖率 ↔ 约束**，按 dimension 对齐。

    这条边补的是三角形缺的那一边 —— 前四条只连成 "V"。它答的问题很具体：
    「这条策略驱动的那个维度，有没有人量它」（反向：这个覆盖点有没有人驱动）。
    """

    PORTS = [{"name": "apb_master", "type": "APB_master_seq_item"}]

    #: 专题驱动**两个**维度 —— 与 `COVERAGE` 的两个 coverpoint 一一对上。
    #: 基线 `CASES` 只驱动 `指令类型`（D_type），于是 `D_level` 天生没人驱动
    #: —— 那本身是一条**真的** ⑤ 发现（见下面那条测试），不是"干净的基线"。
    CASES_CLEAN = CASES.replace("dimensions: [指令类型]",
                                "dimensions: [指令类型, 队列水位]")

    def _cons(self, cases: str = CASES) -> str:
        return build_constraint(cases, self.PORTS)["constraint_yaml"]

    def test_a_self_consistent_triple_has_no_edge_five_issues(self):
        """两边都连上时**一条都不该报** —— 否则工具会被当噪音关掉。"""
        p = associate(self.CASES_CLEAN, COVERAGE, self._cons(self.CASES_CLEAN))
        assert not [i for i in p["issues"] if i["edge"] == "⑤"], p["issues"]

    def test_a_driven_dimension_nobody_measures_is_reported(self):
        """策略驱动的维度在覆盖率里没有 coverpoint —— 这条约束白写了。"""
        cons = self._cons(self.CASES_CLEAN.replace(
            "dimensions: [指令类型, 队列水位]", "dimensions: [D_TYPE_TYPO]"))
        p = associate(self.CASES_CLEAN, COVERAGE, cons)
        msgs = [i["message"] for i in p["issues"] if i["edge"] == "⑤"]
        assert any("D_TYPE_TYPO" in m for m in msgs), msgs

    def test_a_measured_dimension_nobody_drives_is_reported(self):
        """反向：有人量的维度没有任何策略驱动 —— 随机激励下大概率扫不到。

        基线 `CASES` 正是这个样子（只驱动 D_type，而 COVERAGE 量了 D_level），
        所以这里直接用基线，不用造特例。
        """
        p = associate(CASES, COVERAGE, self._cons(CASES))
        msgs = [i["message"] for i in p["issues"] if i["edge"] == "⑤"]
        assert any("D_level" in m for m in msgs), msgs
        assert not any("D_type" in m for m in msgs), \
            "D_type 有策略驱动（专题声明了它）—— 不该报"

    def test_no_constraint_model_means_no_edge_five_noise(self):
        """没给约束模型 = 激励层本来就缺，**不该**刷一片 ⑤ 警告。"""
        p = associate(CASES, COVERAGE, "")
        assert not [i for i in p["issues"] if i["edge"] == "⑤"]

    def test_edge_five_is_a_warning_not_an_error(self):
        """软边：约束是**激励层**，"驱动了没量"不该阻断覆盖率渲染。"""
        cases = self.CASES_CLEAN.replace("dimensions: [指令类型, 队列水位]",
                                         "dimensions: [D_NOPE]")
        p = associate(cases, COVERAGE, self._cons(cases))
        five = [i for i in p["issues"] if i["edge"] == "⑤"]
        assert five and all(i["severity"] == "warning" for i in five)
        assert p["renderable"] is True


class TestTheTwoMethodTablesAgree:
    """`METHOD_TO_CONSTRAINT` 给人看、`METHOD_TO_POLICY` 给机器用 —— 键集必须一致。

    漏一个的后果很具体：`associate` 边 ④ 认得那个方法（不报警），生产者却映射不出
    策略（拒绝生成）—— 同一个方法，两个工具的答案不一样。
    """

    def test_the_key_sets_match(self):
        assert set(METHOD_TO_CONSTRAINT) == set(METHOD_TO_POLICY)

    def test_every_mapped_mode_is_one_the_renderer_knows(self):
        for suffix, mode in METHOD_TO_POLICY.values():
            assert mode in COMBINATOR_MODES, f"{suffix} → {mode} 不在组合器模式表里"
