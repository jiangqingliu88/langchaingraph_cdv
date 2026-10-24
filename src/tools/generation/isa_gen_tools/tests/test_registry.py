"""真实注册表 —— 从《指令编码总表》xlsx 编出来的那份。

与 `test_opcode.py` 的分工：那一份用**手工搭的小表**验领域逻辑，
这一份用**真表**验"编出来的东西对不对"。

真表里有一批**消不掉的疑点**（碰撞、类前缀不符）。这个文件的立场是：
把它们**逐条钉住** —— 数字变了就红，逼人去看是表更新了还是解析坏了。
既不替编码表做判断，也不假装它们不存在。
"""
from __future__ import annotations

import pytest

from ..domain import IsaFamily, OpClass, OpRole, PairingKind
from ..repository import load_ops_registry, registry_provenance


@pytest.fixture(scope="module")
def registry():
    return load_ops_registry()


@pytest.fixture(scope="module")
def encoded(registry):
    """有编码的那些（真指令）—— 非指令 op 另有 27 条。"""
    return [s for s in registry.all() if s.has_encoding]


class TestProvenance:
    def test_records_which_table_it_came_from(self):
        """**用的是哪一版编码表要可审计** —— 这是把 xlsx 编成 JSON 进 git 的理由。"""
        info = registry_provenance()
        assert info["version"] == 1
        assert "Pre_Drv" in info["source"]

    def test_source_is_a_filename_not_a_path(self):
        """只记文件名 —— 绝对路径会把开发机的目录结构泄进仓库。"""
        assert "/" not in registry_provenance()["source"]
        assert "\\" not in registry_provenance()["source"]


class TestCoverage:
    def test_counts_are_pinned(self, registry):
        """数量变了说明表更新了或解析坏了 —— 两种都该有人看一眼。"""
        assert len(registry) == 122
        assert len(registry.without_encoding()) == 27

    @pytest.mark.parametrize("cls,count", [
        (OpClass.CONTROL, 10), (OpClass.NOC, 7), (OpClass.GLSU, 31),
        (OpClass.TMV, 9), (OpClass.MPU, 7), (OpClass.VPU, 31),
    ])
    def test_per_class_counts(self, registry, cls, count):
        assert len(registry.of_class(cls)) == count

    def test_both_isa_families_are_present(self, registry):
        """NICE 与 VNICE 两套（opcode 1011 / 101011）都要有 —— 少一套就是解析漏了。"""
        assert len(registry.of_family(IsaFamily.NICE)) == 54
        assert len(registry.of_family(IsaFamily.VNICE)) == 41

    def test_every_encoded_op_has_a_full_identity(self, registry, encoded):
        """身份是 `(funct7, flags)` 四元组 —— 缺一个都编不出正确的指令字。"""
        for spec in encoded:
            assert spec.funct7 is not None, spec.name
            assert spec.flags is not None, spec.name
            assert spec.opcode, spec.name

    def test_non_instruction_ops_have_no_encoding(self, registry):
        """`csr_write` / `wait_done` / `expect_*` 这些不进指令流，没有 funct7 是对的。"""
        for name in ("csr_write", "mem_init", "wait_done", "expect_rd",
                     "batch_begin", "raw_cmd", "pwr_ctl"):
            spec = registry.get(name)
            assert not spec.has_encoding, name
            assert not spec.is_instruction if hasattr(spec, "is_instruction") else True

    def test_opcode_reflects_the_family(self, registry, encoded):
        """NICE = 1011（RV custom-0），VNICE = 101011（custom-1）。"""
        for spec in encoded:
            expected = "101011" if spec.isa_family is IsaFamily.VNICE else "1011"
            assert spec.opcode == expected, spec.name


class TestMaskSemantics:
    def test_family_decides_how_the_core_set_is_chosen(self, registry, encoded):
        """§3.2.1：NICE 读全局 group_mask 寄存器，VNICE 指令自带 6b_grp_mask。

        这一位**只影响编码**（两者在 IR 里都写成显式 mask），但它决定了
        编码器要不要在 mask 变化时插一条 `group_mask_drv_xn`。
        """
        for spec in encoded:
            expected = ("inline" if spec.isa_family is IsaFamily.VNICE
                        else "global")
            assert spec.mask_semantics.value == expected, spec.name


class TestRolesAndPairing:
    def test_declared_roles_come_from_the_sheet(self, registry, encoded):
        """编码表的 Inst Group 列写 `pre`/`drv` —— 原样保留。

        早先的解析把"标了 drv 但没配对"压成 `lone`，那是把两件事揉在一起了：
        role 是"干什么"，pairing 才是"要不要配对"。
        """
        roles = {s.role for s in encoded}
        assert roles == {OpRole.PRE, OpRole.DRV}
        assert sum(1 for s in encoded if s.role is OpRole.PRE) == 13
        assert sum(1 for s in encoded if s.role is OpRole.DRV) == 82

    def test_pairing_is_hand_maintained_and_small(self, registry):
        """配对关系不在编码表里（那是**事务**层语义），由 `PAIRING_OVERRIDES`
        手工维护。所以它只有一小撮 —— 一大片就说明有东西被自动猜进去了。
        """
        paired = [s for s in registry.all()
                  if s.pairing is not PairingKind.NONE]
        assert len(paired) == 11
        assert {s.pairing for s in paired} == {PairingKind.PRE_DRV,
                                               PairingKind.DST_SRC}

    def test_the_noc_pair_is_marked_dst_src(self, registry):
        """§3.11 noc_pair_txn：dst/src 强配对，中途不许插别的指令。"""
        assert registry.get("noc_drv_dst_xn").pairing is PairingKind.DST_SRC

    def test_gemm_family_requires_its_pre(self, registry):
        for name in ("gemm_drv_xn", "gemm_acc_drv_xn", "gemm_dq_drv_xn",
                     "gemm_dq_acc_drv_xn"):
            assert registry.get(name).pairing is PairingKind.PRE_DRV, name

    def test_cfg_requirement_is_derived_from_the_name(self, registry):
        """§3.11 各组的"前置条件"列 —— 按名字前缀推。"""
        assert registry.get("tld_drv_xn").cfg_required == "tld_cfg"
        assert registry.get("tst_drv_xn").cfg_required == "tst_cfg"
        assert registry.get("noc_drv_xn").cfg_required == "noc_cfg"
        assert registry.get("gemm_drv_xn").cfg_required == "mpu_cfg"


class TestDeferred:
    def test_ops_marked_not_yet_done_are_listed(self, registry):
        """编码表标了"暂时不做"的 —— 生成器不该选它们。"""
        assert {s.name for s in registry.deferred()} == {
            "v_ss1_drv_xn", "v_ss2_drv_xn", "vvs_v_drv_xn", "vs_vv_drv_xn",
            "v_ss1_drv_vn01", "v_ss1_drv_vn11"}

    def test_the_reason_lives_in_the_flag_not_the_notes(self, registry):
        """`暂不做` 由 `deferred` 标志承载，notes 里不再重复一遍 ——
        同一件事两处记着就一定会对不上。"""
        assert all(s.deferred for s in registry.deferred())
        assert all("暂时不做" not in s.notes for s in registry.deferred())


class TestRealTableAnomalies:
    """**编码表里的疑点** —— 逐条钉住，不修、不藏。

    这些不是我们的 bug，是表本身值得问一句的地方。工具没有立场替它判断，
    但必须让使用者看得见 —— `run_explain` 就是干这个的（M6）。
    """

    def test_same_funct7_same_flags_collisions_are_real(self, registry):
        """`tld_drv_xn` 与 `gtld_drv_xn` 完全同码 —— 文档标为 XL-02。

        真表里还有几组同 funct7 但 flags 不同的（那些是**正常**的，
        靠 flags 区分），所以这里只断言"消不掉的那几组"确实被捞出来了。
        """
        unresolvable = [c for c in registry.collisions()]
        names = {n for c in unresolvable for n in c.names}
        assert "tld_drv_xn" in names and "gtld_drv_xn" in names
        assert len(unresolvable) == 6

    def test_there_is_a_cross_class_collision(self, registry):
        """`gtld_drv_vn01` 声明在 GLSU(010)，funct7 却是 `001_0100`（NoC 前缀），
        和 `noc_drv_vn01` 完全撞车。跨类碰撞比同类更可疑。"""
        cross = [c for c in registry.collisions() if c.cross_class]
        assert len(cross) == 1
        assert "gtld_drv_vn01" in cross[0].names

    def test_class_prefix_mismatches_are_counted(self, registry):
        """16 条指令的 funct7 高 3 位与它所在 sheet 的类对不上。

        两组：glsu 的 `g*_vn*` 系列用了 001（NoC 前缀），
        vpu 的 `v*_vn*` 系列用了 100（MPU 前缀）。

        **不修**：改 funct7 是改指令语义，那是编码表作者的事。
        """
        bad = registry.class_mismatches()
        assert len(bad) == 16
        assert all(s.name.endswith(("vn01", "vn11")) for s in bad)

    def test_vpu_sub_families_are_captured(self, registry):
        """vpu 多一列子族 —— 解析要按"Inst Name 在第几列"认，不按 sheet 名硬编码。"""
        vpu = registry.of_class(OpClass.VPU)
        families = {s.sub_family for s in vpu}
        assert {"V_S", "VV_V", "VS_V", "V_V", "M_V", "MV_M"} <= families

    def test_sub_family_does_not_leak_across_sections(self, registry):
        """子族是"向下粘"的，段切换时必须重置。

        `mv_m_drv_xn`（Nice 段最后一个）的 MV_M 曾经粘到了 Vnice 段头上的
        四条 `v1v2_pre_vn*` —— 那四条 pre 根本没有子族。
        """
        for name in ("v1v2_pre_vn01", "v1s1_pre_vn11", "v_v_drv_xn"):
            assert registry.get(name).sub_family != "MV_M", name
        assert registry.get("mv_m_drv_xn").sub_family == "MV_M"
