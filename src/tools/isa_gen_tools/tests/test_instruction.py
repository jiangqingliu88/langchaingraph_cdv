"""IR 指令条目 —— 数据通路契约、JSON 形状、funct7 不许手填。

三件最要紧的：
  · 张量出现在指令字段里 → `DataPathError`（§3.14.1 契约）
  · IR 里**没有** funct7 / inst_flag（§3.2.1："不允许在 IR 中手填"）
  · `to_dict()` 是唯一给 JSON 键命名的地方 —— schema 与导出器从这里对齐
"""
from __future__ import annotations

import pytest

from ..domain import IR_KEYS, DataPathError, Flags, IrInstruction, Operands


class TestFlags:
    def test_accepts_only_bits(self):
        for name in ("xd", "xs1", "xs2"):
            with pytest.raises(DataPathError, match=name):
                Flags(**{name: 2})

    def test_as_tuple_and_text(self):
        flags = Flags(0, 1, 0)
        assert flags.as_tuple == (0, 1, 0)
        assert flags.text == "0，1，0"

    def test_round_trip_from_tuple(self):
        assert Flags.from_tuple((1, 1, 0)) == Flags(1, 1, 0)

    def test_default_is_all_zero(self):
        assert Flags().as_tuple == (0, 0, 0)


class TestOperands:
    def test_to_dict_omits_none(self):
        assert Operands(rs1val=5).to_dict() == {"rs1val": 5}
        assert Operands().to_dict() == {}

    def test_scalars_of_every_flavour_are_fine(self):
        """标量该有的样子都放行：整数、十六进制字符串、空。"""
        for value in (0, 5, "0x1FFF", ""):
            IrInstruction(op="x", operands=Operands(rs1val=value))


class TestDataPathContract:
    """§3.14.1：**标量走指令字段，张量走内存**，两条通路互不交叉。"""

    @pytest.mark.parametrize("value", ["$t.img", "  $t.out  ",
                                       {"ref": "$t.img"}, {"ref": "$t.wgt", "core": 0}])
    def test_tensor_reference_in_operands_is_rejected(self, value):
        with pytest.raises(DataPathError) as info:
            IrInstruction(op="tld_drv_xn", operands=Operands(rs1val=value))
        assert "张量" in str(info.value)
        assert info.value.kind == "data_path"

    def test_hex_string_is_not_mistaken_for_a_tensor(self):
        """`0x...` 是标量该有的样子 —— 别把正常的地址字面量当成张量拦了。"""
        IrInstruction(op="tld_drv_xn", operands=Operands(rs1val="0x1_0004_0000"))

    def test_the_error_points_at_the_offending_field(self):
        with pytest.raises(DataPathError) as info:
            IrInstruction(op="gemm_drv_xn", operands=Operands(rs2val="$t.w"))
        assert info.value.target == "gemm_drv_xn.rs2val"
        assert "binds" in info.value.fix

    def test_missing_op_is_rejected(self):
        with pytest.raises(DataPathError, match="op"):
            IrInstruction(op="")


class TestJsonShape:
    def test_key_set_is_pinned(self):
        """IR 的键就是这些 —— 加字段要先改 `IR_KEYS` 和 `ir.schema.json`。

        casemodel 栽过一次"注释指着已删掉的东西"，这里用**单一命名点**避免它：
        `to_dict()` 是唯一给 JSON 键命名的地方。
        """
        assert IR_KEYS == ("op", "tag", "mask", "flags", "operands", "src", "dst",
                           "src_addr", "dst_addr", "binds", "writes", "cfg",
                           "fault", "extra")

    def test_empty_fields_are_omitted(self):
        """一片空键会把真正有信息的那几个埋掉 —— IR 是给人读、给 diff 看的。"""
        assert IrInstruction(op="sync_drv_xn").to_dict() == {"op": "sync_drv_xn"}

    def test_default_flags_are_omitted(self):
        assert "flags" not in IrInstruction(op="x").to_dict()
        assert IrInstruction(op="x", flags=Flags(1, 0, 0)).to_dict()["flags"] == {
            "xd": 1, "xs1": 0, "xs2": 0}

    def test_no_encoding_fields_may_be_hand_written(self):
        """§3.2.1：funct7 / inst_flag 由 op 名经注册表唯一推出，**不允许在 IR 里手填**。

        手填就有两处真相，而两处一定会漂移。
        """
        payload = IrInstruction(op="tld_drv_xn", mask="0x0003").to_dict()
        assert "funct7" not in payload
        assert "inst_flag" not in payload
        assert not any("funct" in k for k in payload)

    def test_internal_extra_keys_do_not_leak(self):
        """`_` 打头的是内部键（见 `funct7_hint`），不进 IR。"""
        ins = IrInstruction(op="x", extra={"_funct7": "010_0001", "note": "hi"})
        payload = ins.to_dict()
        assert payload["extra"] == {"note": "hi"}
        assert "_funct7" not in payload["extra"]

    def test_full_payload_shape(self):
        """对着文档 §3.0.2 那份 IR 样例的形状核一遍。"""
        ins = IrInstruction(
            op="tld_drv_xn", tag="L12", mask="0x0003", flags=Flags(0, 1, 1),
            operands=Operands(rs1val="0x1_0004_0000"),
            src={"ref": "$t.img"},
            src_addr="0x1_0004_0000",
            binds=("$t.img",),
            writes=({"ref": "$t.out", "range": "[0,64KB)"},))
        payload = ins.to_dict()
        assert payload["op"] == "tld_drv_xn"
        assert payload["tag"] == "L12"
        assert payload["mask"] == "0x0003"
        assert payload["binds"] == ["$t.img"]
        assert payload["writes"] == [{"ref": "$t.out", "range": "[0,64KB)"}]
        assert set(payload) <= set(IR_KEYS)


class TestRoundTrip:
    def test_from_dict_restores_everything(self):
        original = IrInstruction(
            op="npu_cfg_drv_xn", tag="L11", mask="0x0003", flags=Flags(0, 1, 1),
            operands=Operands(rs1val="0x0120_0001"),
            src_addr="0x1_0004_0000", binds=("$t.img",),
            writes=({"ref": "$t.out"},), cfg="tld_cfg",
            fault={"kind": "reserved_touch", "ref": "$t.img"})
        restored = IrInstruction.from_dict(original.to_dict())
        assert restored == original

    def test_from_dict_tolerates_missing_optionals(self):
        assert IrInstruction.from_dict({"op": "nop"}) == IrInstruction(op="nop")


class TestDerived:
    def test_mask_marks_it_as_a_real_instruction(self):
        """有 mask = 走 INST_DISP 的真指令；没有的一律是配置/时序/观测类 op。"""
        assert IrInstruction(op="tld_drv_xn", mask="0x1").is_instruction
        assert not IrInstruction(op="csr_write").is_instruction

    def test_with_extra_and_with_tag_do_not_mutate(self):
        base = IrInstruction(op="tld_drv_xn", tag="L1", mask="0x1")
        tagged = base.with_tag("L2")
        assert base.tag == "L1" and tagged.tag == "L2"
        extended = base.with_extra(note="x")
        assert base.extra == {} and extended.extra == {"note": "x"}

    def test_describe_is_readable(self):
        text = IrInstruction(op="tld_drv_xn", tag="L12", mask="0x3",
                             flags=Flags(0, 1, 1)).describe()
        assert "tld_drv_xn" in text and "tag=L12" in text and "flags=(0, 1, 1)" in text
