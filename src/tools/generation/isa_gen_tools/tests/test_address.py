"""44 位全局地址 —— 往返、保留位、字段越界。

这一层的错**不会自己报出来**：地址算错只会让数据搬到别处，然后被当成实现缺陷。
所以测试盯的是"位段有没有错位"，尤其是那 11 位保留区。
"""
from __future__ import annotations

import pytest

from ..domain import (ADDR_BITS, FIELD_BITS, FIELD_SHIFTS, OFFSET_BITS, GlobalAddr,
                      IsaGenError, McastMode, MemFlag)


class TestLayout:
    def test_widths_add_up_to_44(self):
        """字段位宽加总必须正好 44 —— 多一位少一位都意味着布局被改错了。"""
        assert sum(FIELD_BITS.values()) + OFFSET_BITS == ADDR_BITS

    def test_reserved_gap_is_modelled_not_skipped(self):
        """保留区 [32:22] 必须真的占着位。

        跳过它的话 `Mem_Flag` 会挪到 `Core_ID` 上 —— 那种错**不报错**，
        只是让地址指向别处。所以这里断言的是"它占位"这件事本身。
        """
        shift, width = FIELD_SHIFTS["reserved"]
        assert (shift, width) == (22, 11)

    def test_field_shift_chain_is_contiguous(self):
        """从低位到高位，每段的起点紧接上一段的终点 —— 没有缝也没有重叠。"""
        ordered = sorted(FIELD_SHIFTS.items(), key=lambda kv: kv[1][0])
        expected = 0
        for name, (shift, width) in ordered:
            assert shift == expected, f"{name} 的起点 {shift} 与上一段结尾 {expected} 对不上"
            expected += width
        assert expected == ADDR_BITS


class TestKnownConflict:
    """文档自相矛盾的地方 —— **把矛盾钉成测试，而不是猜一个位宽盖过去**。

    布局里点名的字段减完，`区内偏移` 只剩 13 位 = 8KB；
    而 §3.12.5 说 SPAD 有 128KB、Share DRAM 有 2GB。13 位装不下任何一个。

    这条测试**故意会一直红着吗？不会** —— 它断言的是"矛盾此刻确实存在"。
    冻结版 memmap 到位、位宽被修正之后，这条测试会红，提醒改这里
    （那时它就从"记录问题"变成"该删了"）。
    """

    def test_offset_width_conflicts_with_region_sizes(self):
        offset_bytes = 1 << OFFSET_BITS                     # 8KB
        assert offset_bytes == 8192, "位宽变了 —— 这条测试的假设要跟着改"
        assert offset_bytes < 128 * 1024, "SPAD 是 128KB，13 位装不下"
        assert offset_bytes < 2 * 1024 ** 3, "Share DRAM 是 2GB，13 位更装不下"

    def test_the_17_bit_coincidence_is_recorded(self):
        """`Page_num(4) + 区内偏移(13) = 17 位 = 128KB`，正好是 SPAD 的大小。

        这个巧合很可能是答案（偏移其实是 `{Page_num, 区内偏移}` 两级），
        但没有规格佐证之前**不按它实现** —— 只把它记下来。
        """
        assert (FIELD_BITS["page_num"] + OFFSET_BITS) == 17
        assert (1 << 17) == 128 * 1024


class TestRoundTrip:
    @pytest.mark.parametrize("addr", [
        GlobalAddr(),
        GlobalAddr(die_id=3, cluster_id=2, core_id=15, offset=0x1000),
        GlobalAddr(mem_flag=int(MemFlag.SHARE_DRAM), offset=0x1FE0),
        GlobalAddr(mem_flag=int(MemFlag.COMMON_DRAM), core_id=5, page_num=9,
                   offset=0x1FE0),
        GlobalAddr(cimc_flag=1, page_num=3, offset=0x40),
        GlobalAddr(mcast_mode=int(McastMode.BCAST), die_id=1, cluster_id=1,
                   core_id=7, offset=0x40),
    ])
    def test_pack_unpack_is_lossless(self, addr):
        assert GlobalAddr.unpack(addr.pack()) == addr

    def test_pack_is_within_44_bits(self):
        addr = GlobalAddr(die_id=3, cluster_id=3, mcast_mode=15, mem_flag=7,
                          core_id=15, cimc_flag=1, page_num=15,
                          offset=(1 << OFFSET_BITS) - 32)
        assert 0 <= addr.pack() < (1 << ADDR_BITS)

    def test_reserved_bits_are_always_zero(self):
        """保留位不该被任何字段渗进去。"""
        addr = GlobalAddr(die_id=3, cluster_id=3, core_id=15, offset=0x1FE0)
        assert addr.reserved_bits == 0


class TestValidation:
    @pytest.mark.parametrize("field,bits", sorted(FIELD_BITS.items()))
    def test_out_of_range_is_rejected(self, field, bits):
        if field == "reserved":
            pytest.skip("保留位不是构造参数")
        with pytest.raises(IsaGenError, match=field):
            GlobalAddr(**{field: 1 << bits})

    def test_negative_is_rejected(self):
        with pytest.raises(IsaGenError, match="core_id"):
            GlobalAddr(core_id=-1)

    def test_offset_must_be_32_byte_aligned(self):
        """布局的低 5 位恒 0（32 字节对齐）—— 不对齐的地址在编码时会被悄悄截断。"""
        with pytest.raises(IsaGenError, match="对齐"):
            GlobalAddr(offset=0x21)
        GlobalAddr(offset=0x20)          # 对齐的没问题

    def test_unpack_rejects_out_of_range(self):
        with pytest.raises(IsaGenError, match="超出"):
            GlobalAddr.unpack(1 << ADDR_BITS)


class TestDerived:
    def test_region_key_splits_lmem_by_cimc_flag(self):
        """LMEM 再按 CIMC_flag 分成 SPAD / CIMC —— 同一块局部存储的两个面。"""
        assert GlobalAddr().region_key == "lmem.spad"
        assert GlobalAddr(cimc_flag=1).region_key == "lmem.cimc"
        assert GlobalAddr(mem_flag=int(MemFlag.SHARE_DRAM)).region_key == "dram.share"
        assert GlobalAddr(mem_flag=int(MemFlag.COMMON_DRAM)).region_key == "dram.common"

    def test_with_offset_keeps_everything_else(self):
        base = GlobalAddr(die_id=2, cluster_id=1, core_id=4, offset=0x1000)
        moved = base.with_offset(0x1FE0)
        assert moved.pack() != base.pack()
        assert (moved.die_id, moved.cluster_id, moved.core_id) == (2, 1, 4)

    def test_to_hex_is_44_bit_wide(self):
        assert GlobalAddr(die_id=1).to_hex().startswith("0x")
        assert len(GlobalAddr().to_hex()) == 2 + 11
