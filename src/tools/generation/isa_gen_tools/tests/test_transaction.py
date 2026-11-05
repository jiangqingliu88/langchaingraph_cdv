"""事务与 IR 程序 —— **配对由类型保证，不是由检查保证**。

这一份是四条不变式里最要紧那条的落点（§3.9：随机化的最小单元是事务）。
测试要证明的是两件相反的事：

  1. 正常路径**造不出**孤立的配对指令（类型挡着）
  2. 逃生口（裸 dict 反序列化）**进不来**半拉子配对（兜底断言挡着）

第 1 条证明"我们不会产出坏 IR"，第 2 条证明"别人给的坏 IR 也进不来"。
只测第 1 条是不够的 —— 那条断言就成了一句没人验证过的宣言。
"""
from __future__ import annotations

import pytest

from ..domain import (IrInstruction, IrProgram, PairingError, PairingKind,
                      Transaction, WhitelistError, build_transaction)

PRE = IrInstruction(op="gemm_out_org_pre_xn", mask="0x0003", flags=None)
DRV = IrInstruction(op="gemm_drv_xn", mask="0x0003")


class TestTransactionShape:
    def test_empty_transaction_is_rejected(self):
        with pytest.raises(PairingError, match="没有任何指令"):
            Transaction(id="t1", op="gemm_drv_xn", instructions=())

    def test_missing_id_is_rejected(self):
        with pytest.raises(WhitelistError, match="id"):
            Transaction(id="", op="x", instructions=(DRV,))

    def test_instructions_are_an_ordered_tuple(self):
        txn = Transaction(id="t1", op="gemm_drv_xn", instructions=(PRE, DRV))
        assert txn.op_names == ("gemm_out_org_pre_xn", "gemm_drv_xn")


class TestPairingIsStructural:
    """正常路径：按注册表组装，缺配对的那一步当场报错。"""

    def test_paired_op_without_its_pre_is_rejected(self, registry):
        """`gemm_drv_xn` 在注册表里是 `PRE_DRV` —— 单独一条不许成事务。

        这是文档 §3.11「组合白名单」那条规格的落点：报告在**生成期**，
        不是等到仿真里发现 GEMM 算错了。
        """
        with pytest.raises(WhitelistError) as info:
            build_transaction(txn_id="t1", op="gemm_drv_xn",
                              instructions=(DRV,), registry=registry)
        assert info.value.kind == "whitelist"
        assert "配对" in info.value.message

    def test_paired_op_with_its_pre_is_fine(self, registry):
        txn = build_transaction(txn_id="t1", op="gemm_drv_xn",
                                instructions=(PRE, DRV), registry=registry)
        assert txn.pairing.kind is PairingKind.PRE_DRV
        assert txn.pairing.requires_group

    def test_lone_op_needs_no_partner(self, registry):
        txn = build_transaction(
            txn_id="t1", op="group_mask_drv_xn",
            instructions=(IrInstruction(op="group_mask_drv_xn", mask="0x3"),),
            registry=registry)
        assert txn.pairing.kind is PairingKind.NONE

    def test_dst_src_pairing_is_marked_strict(self, registry):
        """`noc_pair_txn` 是"中途不允许插入其他指令" —— 那个约束要在值上看得出来。"""
        dst = IrInstruction(op="noc_drv_dst_xn", mask="0x3")
        src = IrInstruction(op="noc_drv_src_xn", mask="0x3")
        txn = build_transaction(txn_id="t1", op="noc_drv_dst_xn",
                                instructions=(dst, src), registry=registry)
        assert txn.pairing.kind is PairingKind.DST_SRC
        assert txn.pairing.adjacency == "strict"

    def test_unknown_op_is_not_pair_checked(self, registry):
        """注册表里没有的 op（csr_write / mem_init 这类非指令 op）不该被配对检查绊住。"""
        txn = build_transaction(
            txn_id="t1", op="csr_write",
            instructions=(IrInstruction(op="csr_write"),), registry=registry)
        assert txn.pairing.kind is PairingKind.NONE


class TestPairingTripwire:
    """逃生口：裸 dict 反序列化进来的半拉子配对要被挡住。"""

    def test_from_instructions_rejects_a_lone_paired_op(self, registry):
        """**这条证明兜底断言是活的。**

        正常路径造不出这种 IR（上面那组测试证明了），但"读一份别人给的
        历史 IR"可以。缺了 pre 的 IR 在仿真里表现为 GEMM 结果不对 ——
        那是拿几个小时的仿真时间去查一个生成期就能回答的问题。
        """
        with pytest.raises(PairingError) as info:
            IrProgram.from_instructions([DRV], registry=registry)
        assert info.value.kind == "pairing"
        # 拦在 `Transaction.__post_init__`（单指令事务声明了配对）——
        # 比 `IrProgram.verify_pairing` 早一步。两道都是配对的守卫，谁先响都对。
        assert "配对" in info.value.message

    def test_from_instructions_accepts_unpaired_ops(self, registry):
        program = IrProgram.from_instructions(
            [IrInstruction(op="group_mask_drv_xn", mask="0x3")], registry=registry)
        assert len(program) == 1

    def test_from_transactions_path_cannot_trip_it(self, registry):
        """正常路径永远到不了那条断言 —— 这正是设计意图。"""
        txn = build_transaction(txn_id="t1", op="gemm_drv_xn",
                                instructions=(PRE, DRV), registry=registry)
        program = IrProgram.from_transactions([txn])
        assert program.op_sequence == ("gemm_out_org_pre_xn", "gemm_drv_xn")


class TestProgram:
    def test_flattening_keeps_transaction_order(self):
        a = Transaction(id="a", op="sync_drv_xn",
                        instructions=(IrInstruction(op="sync_drv_xn"),))
        b = Transaction(id="b", op="nop",
                        instructions=(IrInstruction(op="nop"),))
        program = IrProgram.from_transactions([a, b])
        assert program.op_sequence == ("sync_drv_xn", "nop")

    def test_tensor_refs_aggregate_across_a_transaction(self):
        """事务的 `binds/writes` 是**整组**的 —— 比对模块按事务索引，不按单条指令。"""
        pre = IrInstruction(op="gemm_out_org_pre_xn", mask="0x3",
                            binds=("$t.in",), writes=({"ref": "$t.out"},))
        drv = IrInstruction(op="gemm_drv_xn", mask="0x3",
                            binds=("$t.in", "$t.w"), writes=({"ref": "$t.out"},))
        txn = Transaction(id="t1", op="gemm_drv_xn", instructions=(pre, drv))
        assert txn.binds == ("$t.in", "$t.w")
        assert txn.writes == ({"ref": "$t.out"},)

    def test_to_dict_shape(self):
        txn = Transaction(id="t1", op="sync_drv_xn",
                          instructions=(IrInstruction(op="sync_drv_xn", tag="L1"),))
        program = IrProgram.from_transactions([txn], name="demo", seed=7,
                                              isa_rev="V0.8")
        payload = program.to_dict()
        assert payload["name"] == "demo" and payload["seed"] == 7
        assert payload["instructions"][0]["tag"] == "L1"
        # 事务那份也带着 —— 配对/硬约束/效应的语义在 IR 里查得到
        assert payload["transactions"][0]["id"] == "t1"

    def test_summary_counts(self):
        txn = Transaction(id="t1", op="nop", instructions=(IrInstruction(op="nop"),))
        summary = IrProgram.from_transactions([txn]).summary()
        assert summary["txn_count"] == 1 and summary["instruction_count"] == 1
        assert summary["op_histogram"] == {"nop": 1}
