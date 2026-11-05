"""op 注册表 —— 身份是四元组、碰撞要捞出来、疑点不许静默消解。

这一层最要紧的一条：**同一 funct7 下可以挂多条指令**（靠 xd/xs1/xs2 区分）。
把身份简单地记成 funct7，编码器就会把 dst 版编成 src 版 —— 语义层错，
仿真里表现为数据搬错方向，而不是报错。
"""
from __future__ import annotations

import pytest

from ..domain import (Collision, IsaFamily, MaskSemantics, OpClass, OpRegistry,
                      OpSpec, RegistryError, format_funct7, parse_flags,
                      parse_funct7)


class TestParsing:
    @pytest.mark.parametrize("text,expected", [
        ("000_0000", 0b0000000),
        ("000_0001", 0b0000001),
        ("101_1010", 0b1011010),
        ("011_0111", 0b0110111),
        ("0000000", 0),              # 不带下划线也认
    ])
    def test_funct7(self, text, expected):
        assert parse_funct7(text) == expected

    @pytest.mark.parametrize("text", [None, "", "/", "   "])
    def test_funct7_empty_means_none(self, text):
        assert parse_funct7(text) is None

    @pytest.mark.parametrize("bad", ["0000", "000_00000", "000_0002", "abc_defg"])
    def test_funct7_bad_shape_is_an_error(self, bad):
        """坏数据要报错，不要"尽力猜一个" —— 猜出来的 funct7 会编出错误的指令字。"""
        with pytest.raises(RegistryError, match="7 位二进制"):
            parse_funct7(bad)

    def test_funct7_round_trip(self):
        for value in (0, 1, 0b1011010, 0b0110111):
            assert parse_funct7(format_funct7(value)) == value

    @pytest.mark.parametrize("text,expected", [
        ("0，1，0", (0, 1, 0)),      # 编码表用的是全角逗号
        ("0,1,1", (0, 1, 1)),
        ("0， 1, 1", (0, 1, 1)),
    ])
    def test_flags(self, text, expected):
        assert parse_flags(text) == expected

    def test_flags_slash_means_none(self):
        assert parse_flags("/") is None

    def test_flags_bad_shape_is_an_error(self):
        with pytest.raises(RegistryError, match="0/1"):
            parse_flags("0，1")


class TestIdentity:
    def test_same_funct7_different_flags_are_different_ops(self, registry):
        """真实表里最常见的那种：两条指令共用一个 funct7。"""
        dst = registry.get("noc_drv_dst_xn")
        src = registry.get("noc_drv_src_xn")
        assert dst.funct7 == src.funct7
        assert dst.identity != src.identity

    def test_identity_is_funct7_plus_flags(self):
        spec = OpSpec(name="x", op_class=OpClass.NOC, funct7=5, flags=(0, 1, 0))
        assert spec.identity == (5, (0, 1, 0))

    def test_missing_encoding_is_visible(self):
        spec = OpSpec(name="x", op_class=OpClass.NOC, funct7=None, flags=None)
        assert not spec.has_encoding

    def test_op_class_derived_from_funct7(self, registry):
        """类就是 funct7 的高 3 位，不该有两份数据。"""
        spec = registry.get("tld_drv_xn")
        assert spec.op_class_from_funct7 is OpClass.GLSU


class TestCollisions:
    def test_same_funct7_same_flags_shows_up_as_a_collision(self, registry):
        """XL-02：`tld_drv_xn` 与 `gtld_drv_xn` 同 funct7 **且同 flags**。

        这一对**消不掉** —— 靠地址段（local/global）区分，不是靠编码位。
        工具没有立场替编码表做判断，但必须把它捞出来给人看。
        """
        found = {tuple(c.names) for c in registry.collisions()}
        assert ("gtld_drv_xn", "tld_drv_xn") in found

    def test_cross_class_collision_is_flagged(self, registry):
        """`gtld_drv_vn01` 声明在 GLSU，funct7 前缀却是 NoC(001)，和 noc 撞车。

        跨类碰撞比同类碰撞更可疑 —— 同一个 funct7 前缀本该只属于一个类。
        """
        cross = [c for c in registry.collisions() if c.cross_class]
        names = {n for c in cross for n in c.names}
        assert {"gtld_drv_vn01", "noc_drv_vn01"} <= names

    def test_collision_carries_the_funct7_text(self, registry):
        for collision in registry.collisions():
            assert isinstance(collision, Collision)
            assert len(collision.funct7_text) == 8      # "nnn_nnnn"

    def test_ops_without_encoding_are_not_collisions(self):
        """funct7 缺失不是"撞车"，是"没编完" —— 两者要分开。"""
        reg = OpRegistry([OpSpec(name="a", op_class=OpClass.NOC),
                          OpSpec(name="b", op_class=OpClass.NOC)])
        assert reg.collisions() == []
        assert len(reg.without_encoding()) == 2


class TestClassMismatch:
    def test_declared_class_disagreeing_with_funct7_is_reported(self, registry):
        """不修，只报 —— 是表的疑点就让它显出来。"""
        bad = {s.name for s in registry.class_mismatches()}
        assert "gtld_drv_vn01" in bad

    def test_consistent_ops_are_not_reported(self, registry):
        bad = {s.name for s in registry.class_mismatches()}
        assert "tld_drv_xn" not in bad
        assert "gemm_drv_xn" not in bad


class TestRegistryQueries:
    def test_duplicate_name_is_rejected(self):
        dup = [OpSpec(name="x", op_class=OpClass.NOC),
               OpSpec(name="x", op_class=OpClass.NOC)]
        with pytest.raises(RegistryError, match="重复"):
            OpRegistry(dup)

    def test_empty_registry_is_rejected(self):
        """fail-closed：注册表读不进来时宁可起不来，也不要拿着一半的表生成。"""
        with pytest.raises(RegistryError, match="空"):
            OpRegistry([])

    def test_unknown_name_suggests_near_matches(self, registry):
        with pytest.raises(RegistryError) as info:
            registry.get("tld_drv_typo")
        assert "tld" in str(info.value)

    def test_of_class_and_family(self, registry):
        assert {s.name for s in registry.of_class(OpClass.MPU)} == {
            "gemm_out_org_pre_xn", "gemm_drv_xn"}
        assert "noc_drv_vn01" in {s.name for s in registry.of_family(IsaFamily.VNICE)}
        assert "noc_drv_xn" in {s.name for s in registry.of_family(IsaFamily.NICE)}

    def test_deferred_ops_are_listed_separately(self, registry):
        """编码表标了"暂时不做"的，生成器不该选它 —— 所以要能一条命令列出来。"""
        assert {s.name for s in registry.deferred()} == {"v_ss1_drv_xn"}

    def test_names_are_sorted_and_stable(self, registry):
        assert registry.names() == sorted(registry.names())
        assert registry.names() == registry.names()
