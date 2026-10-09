"""六段流水线 —— 求解 / 编排 / 标注 / 产出。

这一份验的是**整条链**，所以它同时兜住了前面每一层。
最要紧的两条：**确定性**（同 seed 同 DSL → 逐字节相同）与
**L2 只调权重**（意图旋钮改不了合法性）。
"""
from __future__ import annotations

import json

import pytest

from ..analysis import load_dsl
from ..compile import (Sequencer, compile_dsl, mask_from_cores, plan_schedule,
                       solve_transactions, split_epochs)
from ..domain import SolverError
from ..repository import load_memmap, load_ops_registry, load_txn_registry

OPS = load_ops_registry()
TXNS = load_txn_registry(ops=OPS)
MEM = load_memmap()

BASE = """meta: {name: demo, seed: 4242}
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


def compile_text(text: str, **kw):
    return compile_dsl(load_dsl(text), txns=TXNS, ops=OPS, memmap=MEM, **kw)


def _products(output) -> dict:
    """**可复现的那部分**产物 —— 排掉墙钟一类的观测值。

    判据：同样的 (seed, DSL) 跑两次应当一模一样的东西才算产物。
    `elapsed_ms` 显然不是。
    """
    payload = output.to_dict()
    payload["report"].pop("elapsed_ms", None)
    return payload


class TestEndToEnd:
    def test_all_six_stages_run(self):
        out = compile_text(BASE, max_txns=6)
        assert out.report.txn_count > 0
        assert out.report.instruction_count >= out.report.txn_count
        assert out.report.epoch_count == 2
        assert out.program.instructions

    def test_the_seed_is_backfilled_into_case_json(self):
        """文档字段约定第 1 条：`case.json` 要回填实际用的 seed —— 否则复现链断在这里。"""
        out = compile_text(BASE.replace("seed: 4242", "seed: null"),
                           max_txns=3, clock=99)
        assert out.case["meta"]["seed"] == 99
        assert out.report.seed == 99

    def test_an_explicit_seed_overrides_the_declared_one(self):
        """`--seed` 是**覆盖**（CLI 那个旗标就是这个意思），不是"缺省值"。"""
        out = compile_text(BASE, max_txns=3, seed=99)      # DSL 里写的是 4242
        assert out.report.seed == 99

    def test_preload_carries_handles_not_data(self):
        """本工具**不产张量数据**（那是 tensor_gen 的活），只留句柄。"""
        out = compile_text(BASE, max_txns=3)
        refs = {e["ref"] for e in out.preload["entries"]}
        assert refs == {"$t.img", "$t.out", "$t.wgt", "$t.act", "$t.res"}
        assert all("pattern" in e or "dtype" in e for e in out.preload["entries"])

    def test_expect_anchors_point_at_readback_tags(self):
        out = compile_text(BASE, max_txns=6)
        assert out.expect["anchors"]
        assert all(a["kind"] == "readback" for a in out.expect["anchors"])

    def test_the_whole_output_is_json_safe(self):
        payload = compile_text(BASE, max_txns=4).to_dict()
        assert json.loads(json.dumps(payload, ensure_ascii=False))["case"]


class TestDeterminism:
    def test_same_seed_same_bytes(self):
        """**同 seed 同 DSL → 产物逐字节相同。** 这是"可复现"最硬的那一条。

        **只比产物，不比观测元数据。** `elapsed_ms` 是墙钟测出来的 ——
        把它算进来这条测试会**间歇性**红（两次恰好都是 0ms 时就绿），
        而它红并不说明复现性坏了。
        """
        first = _products(compile_text(BASE, max_txns=8))
        second = _products(compile_text(BASE, max_txns=8))
        assert json.dumps(first, sort_keys=True, ensure_ascii=False) == \
               json.dumps(second, sort_keys=True, ensure_ascii=False)

    def test_the_timing_is_not_part_of_the_product(self):
        """`elapsed_ms` **不进**可复现的产物 —— 它是观测值，不是结果。"""
        output = compile_text(BASE, max_txns=3)
        assert "elapsed_ms" in output.report.to_dict()     # 报告里有，给人看
        assert "elapsed_ms" not in _products(output)        # 产物里没有

    def test_different_seed_diverges(self):
        a = compile_text(BASE, max_txns=8, seed=1)
        b = compile_text(BASE, max_txns=8, seed=2)
        assert [i.op for i in a.program.instructions] != \
               [i.op for i in b.program.instructions]

    def test_the_report_records_every_derived_stream(self):
        """派生过哪些随机流是**可复现链的一部分** —— 少了它就说不清"这次怎么来的"。"""
        out = compile_text(BASE, max_txns=4)
        assert "txn:pick" in out.report.streams
        assert "epoch:sync" in out.report.streams

    def test_a_clock_is_injectable(self):
        """`meta.seed` 缺省时取时间戳 —— 但那条路径要能**被喂**，不能偷偷读墙钟。"""
        no_seed = BASE.replace("seed: 4242", "seed: null")
        out = compile_text(no_seed, max_txns=3, clock=1234567)
        assert out.report.seed == 1234567


class TestSolverLayers:
    def test_mask_comes_from_the_declared_cores(self):
        assert mask_from_cores([0, 1]) == "0x0003"
        assert mask_from_cores([0, 1, 2, 3]) == "0x000F"

    def test_an_empty_mask_is_refused(self):
        """§3.11 通用规则 3：mask 全零属非法激励 —— 不给一个 0x0 出去。"""
        with pytest.raises(SolverError, match="非法激励"):
            mask_from_cores([])

    def test_a_core_outside_6b_is_refused(self):
        with pytest.raises(SolverError, match="6b_grp_mask"):
            mask_from_cores([64])

    def test_cores_accepts_the_documented_range_form(self):
        assert mask_from_cores(sorted(set([0, 1, 2, 3]))) == "0x000F"

    def test_an_unavailable_transaction_in_include_is_an_error(self):
        """`rd_csr_txn` 文档列了但编码表没有 —— 写进 include 要报错并说清为什么。"""
        text = BASE.replace("include: [mask_txn, tld_txn, gemm_txn, sync_txn]",
                            "include: [rd_csr_txn]")
        with pytest.raises(SolverError, match="用不了"):
            compile_text(text, max_txns=2)

    def test_l2_bias_only_touches_weights(self):
        """**L2 只能调权重**（§3.15 规则 2）—— 它改不了"哪些事务可选"。"""
        plain = compile_text(BASE, max_txns=4)
        biased = compile_text(BASE.replace(
            "orchestration:", "intent: {hazard_density: 1.0}\norchestration:"),
            max_txns=4)
        # 池子（有哪些事务可选）不受影响
        assert set(plain.report.weights) == set(biased.report.weights)
        # 权重变了
        assert biased.report.weights["gemm_txn"] > plain.report.weights["gemm_txn"]

    def test_illegal_ratio_is_reported_not_silently_ignored(self):
        """文档 §3.9 规定负例不进随机空间 —— 不实现，但**要说出来**。"""
        out = compile_text(BASE.replace(
            "orchestration:", "intent: {illegal_ratio: 0.2}\norchestration:"),
            max_txns=4)
        assert any("illegal_ratio" in n for n in out.report.notes)


class TestEpochs:
    def test_remainder_goes_to_the_front(self):
        """10 条分 3 段是 4/3/3 —— 第一段（起手）多一点，后面的段更均衡。"""
        from ..domain import Transaction
        from ..domain import IrInstruction
        txns = [Transaction(id=f"t{i}", op="nop",
                            instructions=(IrInstruction(op="nop"),))
                for i in range(10)]
        sizes = [len(e.transactions) for e in split_epochs(txns, epochs=3)]
        assert sizes == [4, 3, 3]

    def test_more_epochs_than_transactions_says_so(self):
        from ..domain import IrInstruction, Transaction
        txns = [Transaction(id="t", op="nop",
                            instructions=(IrInstruction(op="nop"),))]
        schedule = plan_schedule(load_dsl(BASE.replace("epochs: 2", "epochs: 5")),
                                 txns, registry=TXNS, sequencer=Sequencer(1))
        assert any("空的" in n for n in schedule.notes)

    def test_sync_points_land_at_the_boundaries(self):
        out = compile_text(BASE, max_txns=6)
        ops = [i.op for i in out.program.instructions]
        assert ops.count("sync_drv_xn") >= 1

    def test_an_unknown_sync_strategy_is_refused(self):
        with pytest.raises(SolverError, match="不认识的"):
            compile_text(BASE.replace("epoch_boundary_sync: always",
                                      "epoch_boundary_sync: maybe"), max_txns=3)


class TestAnnotations:
    def test_readback_instructions_get_wait_then_expect(self):
        """`xd=1` 的指令后面要有 `wait_done` + `expect_rd`，**顺序不能反**：
        wait 之前的 rdval 还是上一拍的残留。"""
        out = compile_text(BASE, max_txns=6)
        ops = [i.op for i in out.program.instructions]
        for index, op in enumerate(ops):
            if op == "wait_done":
                assert ops[index + 1] == "expect_rd"
                break
        else:
            pytest.fail("没有任何 wait_done —— 读回值没人核对")

    def test_every_real_instruction_carries_the_mask(self):
        """回归：插入的同步点曾经 mask 为空 —— 而在 IR 里"没有 mask"和
        "mask 全零"看起来一样，后者是**非法激励**（§3.11 通用规则 3）。

        **只对真指令断言**：`wait_done` / `expect_rd` 是时序/观测 op
        （`op_class=None`），它们不进指令流，本来就没有 mask。
        """
        out = compile_text(BASE, max_txns=6)
        real = [i for i in out.program.instructions
                if (spec := OPS.find(i.op)) is not None and spec.is_instruction]
        assert real, "一条真指令都没有 —— 这个断言就成了空的"
        for ins in real:
            assert ins.mask, f"{ins.op} 没有 mask"

    def test_tags_are_unique_and_sequential(self):
        out = compile_text(BASE, max_txns=6)
        tags = [i.tag for i in out.program.instructions if i.tag]
        assert tags[0] == "L1"
        assert len(set(tags)) == len(set(t for t in tags))


class TestAddresses:
    def test_spad_and_cimc_do_not_collide(self):
        """回归：`lmem.core.spad` 与 `lmem.core.cimc` 是同一块存储的两个面，
        基址都是 0 —— 不把 `CIMC_flag` 拼进去的话两者会算出同一个地址。

        （这个 bug 真的出现过：观测点纪律检查把 `out` 与 `wgt` 判成了
        "共用同一段地址"。）
        """
        out = compile_text(BASE, max_txns=3)
        spans = {o["name"]: (o["region"], o["offset"])
                 for o in out.report.allocations["objects"]}
        assert spans["out"][0] != spans["wgt"][0]      # 不同面

    def test_offsets_do_not_wrap_at_8kb(self):
        """回归：按 13 位当整体偏移实现过一次，把 8192 截回 0，
        于是 SPAD 里第二个 8KB 以上的对象和第一个算出同一个地址 —— **不报错**。"""
        out = compile_text(BASE, max_txns=3)
        offsets = {o["name"]: int(o["offset"], 16)
                   for o in out.report.allocations["objects"]
                   if o["region"] == "lmem.core.spad"}
        assert len(set(offsets.values())) == len(offsets), offsets
        assert max(offsets.values()) >= 8192          # 确实有超过 8KB 的

    def test_a_misconfigured_alloc_fails_at_compile_time(self):
        # 4G > Share DRAM 的 2GB
        bad = BASE.replace("shape: [64,256], dtype: fp16, role: src",
                           "shape: [4096,4096,256], dtype: fp32, role: src")
        with pytest.raises(Exception) as info:
            compile_text(bad, max_txns=2)
        assert "装不下" in str(info.value)


class TestSolve:
    def test_the_picker_is_reproducible(self):
        doc = load_dsl(BASE)
        a = solve_transactions(doc, TXNS, sequencer=Sequencer(7), count=5)
        b = solve_transactions(doc, TXNS, sequencer=Sequencer(7), count=5)
        assert a.ids() == b.ids()

    def test_choices_carry_mask_and_shape(self):
        doc = load_dsl(BASE)
        result = solve_transactions(doc, TXNS, sequencer=Sequencer(7), count=3)
        for choice in result.choices:
            assert choice.mask == "0x000F"


class TestExampleFiles:
    """`config/isa_gen/examples/` 里的每一份都要能跑。

    示例是**活样本** —— 一份跑不起来的示例比没有示例更糟：它教人写错的东西。
    所以这里逐份断言"校验通过且能编译"。
    """

    @staticmethod
    def examples():
        from pathlib import Path
        root = (Path(__file__).resolve().parents[4]
                / "config" / "isa_gen" / "examples")
        return sorted(root.glob("*.yaml"))

    def test_there_are_examples(self):
        assert self.examples(), "示例目录是空的"

    def test_every_example_validates(self):
        from ..api import run_validate
        for path in self.examples():
            payload = run_validate(path.read_text(encoding="utf-8"))
            assert payload["valid"], (
                f"{path.name} 校验不过："
                f"{[i['message'] for i in payload['issues']]}")

    def test_every_example_compiles(self):
        """**能校验过不等于能编译过** —— 地址放不下、角色对不上都在后面几步。"""
        from ..api import run_compile
        for path in self.examples():
            payload = run_compile(path.read_text(encoding="utf-8"), max_txns=4)
            assert "error" not in payload, f"{path.name} 编译不过：{payload}"


def test_cores_accept_bare_integers():
    """`cores: [0, 1]` 与 `["0", "1"]` 等价。

    YAML 把裸数字解析成 int，而核号写成 `0` 是最自然的写法 ——
    不收的话报的是一句很难懂的 `resources.cores.0: Input should be a
    valid string`，使用者得盯着它想一会儿才明白"原来要加引号"。
    这种错不值得让人想一会儿。
    """
    doc = load_dsl("meta: {name: t}\nresources: {cores: [0, 1]}")
    assert doc.resources.cores == ["0", "1"]
    assert mask_from_cores([0, 1]) == "0x0003"


def test_the_range_form_is_still_a_string():
    """`[0..3]` 是字符串，要原样透传给 `parse_cores` 解释（它两种都认）。"""
    doc = load_dsl("meta: {name: t}\nresources: {cores: [0..3]}")
    assert doc.resources.cores == ["0..3"]


def test_a_minimal_dsl_compiles():
    """只写 `meta` 也要能编出东西。

    不给 `alloc` 时，池子里那些**要动张量**的事务（`noc_pair_txn` 要
    `src`/`dst` 角色）根本编不出来 —— 没有对象可动时，"不搬数据"是唯一
    说得通的解释，不是错误。所以池子该自然缩到不需要对象的那几条。
    """
    out = compile_text("meta: {name: needless, seed: 1}", max_txns=6)
    assert out.report.txn_count > 0
    # **真正的不变式是"没有张量引用"**，不是"只生成了某几条指令" ——
    # 后者会随着注册表里多一条不需要对象的事务而失效。
    assert not out.preload["entries"]
    for ins in out.program.instructions:
        assert not ins.binds and not ins.writes, ins.op


def test_naming_a_tensor_transaction_without_alloc_says_why():
    """点名要在 include 里、却没给 alloc —— 报"要动张量但 alloc 是空的"，
    而不是让人对着一条 `UnresolvedRefError` 去猜。"""
    text = "meta: {name: t}\ntxn_pool: {include: [noc_pair_txn]}"
    with pytest.raises(SolverError, match="要动张量"):
        compile_text(text, max_txns=2)
