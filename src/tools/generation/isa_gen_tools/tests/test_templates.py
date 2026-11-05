"""事务注册表与模板 —— 声明 → 实例，以及"配对与 ref 都不许凭空造"。

两条要害：
  · 事务里的指令组是**一起造出来的**，孤立的一条配对指令不可表达
  · `ref` **只认分配过的对象** —— 凭空造 ref 正是文档 §3.0 契约 2 要挡的事
"""
from __future__ import annotations

import pytest

from ..analysis import load_dsl
from ..compile import (Sequencer, allocate, build_play_space, instantiate,
                       instantiate_all, ref)
from ..domain import (PairingKind, RegistryError, UnresolvedRefError, WhitelistError)
from ..repository import (load_memmap, load_ops_registry, load_txn_registry)

OPS = load_ops_registry()
TXNS = load_txn_registry(ops=OPS)
MEM = load_memmap()


def plan_for(text: str):
    doc = load_dsl(text)
    return allocate(doc, build_play_space(doc, MEM), MEM, seed=11)


def build(txn_id: str, *, plan=None, mask="0x0003", draw=None):
    return instantiate(TXNS.get(txn_id), registry=OPS, mask=mask, plan=plan,
                       draw=draw)


#: 形状刻意小：[64,64] fp16 = 8KB，六个 SPAD 对象加起来仍在 128KB 里。
#: 测试要验的是**角色怎么对上**，不是分配器能装多大 —— 装满溢出会把
#: 这两件事混在一起报错。
ALLOC = """meta: {name: t, seed: 11}
alloc:
  - {name: img,   pool: dram.share,     shape: [64,256], dtype: fp16, role: src}
  - {name: out,   pool: lmem.core.spad, shape: [64,64],  dtype: fp16, role: dst}
  - {name: wgt,   pool: lmem.core.cimc, shape: [64,64],  dtype: fp16, role: wgt}
  - {name: act,   pool: lmem.core.spad, shape: [64,64],  dtype: fp16, role: in}
  - {name: res,   pool: lmem.core.spad, shape: [64,64],  dtype: fp16, role: out}
  - {name: a1,    pool: lmem.core.spad, shape: [64],     dtype: fp16, role: in1}
  - {name: a2,    pool: lmem.core.spad, shape: [64],     dtype: fp16, role: in2}
  - {name: org,   pool: lmem.core.spad, shape: [64,64],  dtype: fp16, role: origin}
"""


class TestRegistryLoader:
    def test_every_transaction_references_real_ops(self):
        """**装载时就校验**两个数据源对得上 —— 漏过去的话生成器要到造事务时才发现。"""
        registry = load_txn_registry(ops=OPS)
        assert len(registry) == 33
        assert len(registry.available()) == 32

    def test_the_unavailable_one_is_recorded_not_deleted(self):
        """`rd_csr_txn`：文档列为 Control 指令，编码表里没有。

        **不发明编码** —— 记为不可用，理由留在 note 里。删掉的话，
        "文档与编码表不一致"这件事就没人看得见了。
        """
        deferred = TXNS.deferred()
        assert [t.id for t in deferred] == ["rd_csr_txn"]
        assert "编码总表" in deferred[0].note

    def test_a_bad_op_name_is_caught_at_load_time(self):
        with pytest.raises(RegistryError, match="对不上"):
            load_txn_registry(ops=OPS).validate_against(OPS) if False else \
                _validate_with_bogus_op()

    def test_groups(self):
        assert set(TXNS.groups()) == {"control", "noc", "glsu", "tmv", "mpu", "vpu"}


def _validate_with_bogus_op():
    from ..domain import TransactionRegistry, TxnSpec
    TransactionRegistry([
        TxnSpec(id="bogus", ops=("no_such_op_anywhere",)),
    ]).validate_against(OPS)


class TestPairingIsStructural:
    def test_a_paired_transaction_carries_both_instructions(self):
        txn = build("gemm_txn")
        assert txn.op_names == ("gemm_out_org_pre_xn", "gemm_drv_xn")
        assert txn.pairing.kind is PairingKind.PRE_DRV

    def test_the_noc_pair_is_strict(self):
        txn = build("noc_pair_txn")
        assert txn.pairing.kind is PairingKind.DST_SRC
        assert txn.pairing.adjacency == "strict"

    def test_an_op_needing_a_pre_cannot_be_built_alone(self):
        """**孤立的一条 `gemm_drv_xn` 造不出来。** 这是那条不变式的正面证明。"""
        from ..domain import TxnSpec
        broken = TxnSpec(id="broken", ops=("gemm_drv_xn",))
        with pytest.raises(WhitelistError, match="配对"):
            instantiate(broken, registry=OPS)

    def test_flags_come_from_the_registry_not_the_template(self):
        """指令身份的一半是 flags —— 手填会编出错误的指令字。"""
        txn = build("noc_pair_txn")
        dst = OPS.get("noc_drv_dst_xn")
        ins = next(i for i in txn.instructions if i.op == "noc_drv_dst_xn")
        assert ins.flags.as_tuple == dst.flags


class TestDataFlow:
    """`binds/writes` 只认分配过的对象 —— 凭空造 ref 是文档明文禁止的。"""

    def test_a_move_transaction_binds_src_and_writes_dst(self):
        txn = build("tld_txn", plan=plan_for(ALLOC))
        assert txn.binds == (ref("img"),)
        assert [w["ref"] for w in txn.writes] == [ref("out")]

    def test_a_compute_transaction_carries_its_tensors(self):
        """文档 §3.14.4 第 2 条：MPU/VPU 计算类**必须**携带 binds/writes。"""
        txn = build("gemm_txn", plan=plan_for(ALLOC))
        assert ref("act") in txn.binds and ref("wgt") in txn.binds
        assert [w["ref"] for w in txn.writes] == [ref("res")]

    def test_register_and_region_names_do_not_become_refs(self):
        """回归：第一版把效应里的 `nice`（寄存器名）、`dram_to_lmem`（方向）
        都收成了张量引用，造出了 `$t.nice` 这种解析不了的东西。

        文档 §3.0 契约 2：**`ref` 解析失败 = 生成期失败**，不允许静默越界。
        凭空造 ref 正好是它要挡的那件事。
        """
        plan = plan_for(ALLOC)
        for txn_id in ("mask_txn", "cfg_txn", "sync_txn"):
            txn = build(txn_id, plan=plan)
            assert txn.binds == () and txn.writes == (), txn_id

    def test_a_missing_role_is_a_compile_error_not_a_guess(self):
        """DSL 声明的角色对不上事务要的角色 → `UnresolvedRefError`。

        这条证明"角色没声明"不会被静默跳过 —— 那种情况会产出**没有 binds/writes
        的计算事务**，而文档 §3.14.4 要求它必须有。宁可报错。
        """
        # 这份 alloc 缺 `scale`（gemm_dq_txn 要用）
        thin = """meta: {name: t, seed: 11}
alloc:
  - {name: wgt, pool: lmem.core.cimc, shape: [64,64], dtype: fp16, role: wgt}
  - {name: act, pool: lmem.core.spad, shape: [64,64], dtype: fp16, role: in}
  - {name: res, pool: lmem.core.spad, shape: [64,64], dtype: fp16, role: out}
"""
        with pytest.raises(UnresolvedRefError) as info:
            build("gemm_dq_txn", plan=plan_for(thin))
        assert "scale" in str(info.value)
        assert info.value.fix and "role" in info.value.fix

    def test_references_only_point_at_allocated_objects(self):
        """生成出来的每个 ref 都要能在分配计划里找到 —— 这是那条契约的正面验证。"""
        plan = plan_for(ALLOC)
        known = {ref(n) for n in plan.names()}
        for txn_id in ("tld_txn", "gemm_txn", "gemm_acc_txn"):
            txn = build(txn_id, plan=plan)
            assert set(txn.binds) <= known, txn_id

    def test_no_plan_means_no_refs(self):
        """没有地址分配时（sync / mask 这类）不该造出 ref。"""
        assert build("sync_txn").binds == ()


class TestInstantiateAll:
    def test_tags_are_sequential_and_stable(self):
        plan = plan_for(ALLOC)
        specs = [TXNS.get(i) for i in ("mask_txn", "tld_txn", "sync_txn")]
        first = instantiate_all(specs, registry=OPS, mask="0x3", plan=plan)
        second = instantiate_all(specs, registry=OPS, mask="0x3", plan=plan)
        assert [t.instructions[0].tag for t in first] == ["T01", "T02", "T03"]
        assert [t.to_dict() for t in first] == [t.to_dict() for t in second]

    def test_mask_reaches_every_instruction(self):
        """mask 是这一组的目标核集合 —— 配对组里两条都要带上。"""
        txn = build("gemm_txn", plan=plan_for(ALLOC), mask="0x0007")
        assert {i.mask for i in txn.instructions} == {"0x0007"}

    def test_addresses_come_from_the_plan(self):
        plan = plan_for(ALLOC)
        txn = build("tld_txn", plan=plan, draw=Sequencer(3).draw("addr"))
        addr = txn.instructions[0].src_addr
        assert addr.startswith("0x")
        assert int(addr, 16) in set(plan.bindings.values())
