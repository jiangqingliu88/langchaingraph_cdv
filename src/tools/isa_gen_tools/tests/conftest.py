"""夹具 —— 两张**手工搭的**小注册表，够 M1 的领域测试用。

为什么不直接读 `schema/ops.registry.json`：那份表是 M2 从 xlsx 生成的，
M1 阶段还不存在。而且领域层的测试**本来就不该依赖真实数据** ——
它验的是"类型挡不挡得住"，用的例子越小编越好读。

真实注册表的正确性由 M2 自己的测试兜（逐行对 xlsx）。
"""
from __future__ import annotations

import pytest

from ..domain import (IsaFamily, MaskSemantics, OpClass, OpRegistry, OpRole,
                      OpSpec, PairingKind)


def op(name: str, op_class: OpClass, funct7: int, flags, *, role=OpRole.LONE,
       pairing=PairingKind.NONE, family=IsaFamily.NICE, deferred=False,
       cfg="", notes="") -> OpSpec:
    """造一条 op —— 参数顺序按"身份优先"，因为身份才是主键。"""
    return OpSpec(name=name, op_class=op_class, isa_family=family,
                  funct7=funct7, flags=flags, opcode="1011",
                  role=role, pairing=pairing, cfg_required=cfg,
                  mask_semantics=(MaskSemantics.INLINE_6B if family is IsaFamily.VNICE
                                  else MaskSemantics.GLOBAL),
                  deferred=deferred, notes=notes)


@pytest.fixture(scope="module")
def registry() -> OpRegistry:
    """一张覆盖各种形态的小表。

    刻意包含三样真实表里也有、且**容易做错**的东西：
      · 同 funct7 靠 flags 区分的两条（`noc_drv_dst/src`）—— 身份是四元组
      · 跨类同 funct7 的一对（`gtld_vn01` 声明在 GLSU 但 funct7 是 NoC 前缀）
      · 标了"暂时不做"的一条
    """
    return OpRegistry([
        op("group_mask_drv_xn", OpClass.CONTROL, 0b000_0000, (0, 1, 0)),
        op("npu_cfg_drv_xn", OpClass.CONTROL, 0b000_0001, (0, 1, 1), cfg="*_cfg"),
        op("sync_drv_xn", OpClass.CONTROL, 0b000_0100, (1, 0, 0)),
        op("fast_sync_drv_xn", OpClass.CONTROL, 0b000_0100, (0, 0, 0)),

        # 同 funct7、靠 flags 分 —— 真实表里最常见的那种
        # dst/src 这一对就是文档 §3.11 的 noc_pair_txn：强配对、中间不许插别的指令
        op("noc_drv_dst_xn", OpClass.NOC, 0b001_0000, (0, 0, 1),
           pairing=PairingKind.DST_SRC),
        op("noc_drv_src_xn", OpClass.NOC, 0b001_0000, (0, 1, 1)),
        op("noc_drv_xn", OpClass.NOC, 0b001_0001, (0, 1, 1)),

        op("die_cluster_pre_xn", OpClass.GLSU, 0b010_0000, (0, 1, 1), role=OpRole.PRE),
        op("tld_drv_xn", OpClass.GLSU, 0b010_0001, (0, 1, 1), cfg="tld_cfg"),
        # XL-02：与 tld 同 funct7 **且同 flags**，靠地址段区分（消不掉的碰撞）
        op("gtld_drv_xn", OpClass.GLSU, 0b010_0001, (0, 1, 1), cfg="tld_cfg",
           notes="XL-02 与 tld_drv_xn 同码，靠地址段 local/global 区分"),

        op("gemm_out_org_pre_xn", OpClass.MPU, 0b100_0000, (0, 1, 1), role=OpRole.PRE),
        op("gemm_drv_xn", OpClass.MPU, 0b100_0100, (0, 1, 1),
           pairing=PairingKind.PRE_DRV),

        op("v1v2_pre_xn", OpClass.VPU, 0b101_0000, (0, 1, 1), role=OpRole.PRE),
        op("vv_v_drv_xn", OpClass.VPU, 0b101_1000, (0, 1, 0)),
        op("vvv_v_drv_xn", OpClass.VPU, 0b101_1000, (0, 1, 1)),
        op("v_ss1_drv_xn", OpClass.VPU, 0b101_1011, (1, 1, 0), deferred=True),

        # VNICE 族 + 跨类碰撞（funct7 前缀 001 = NoC，却声明在 GLSU）
        op("noc_drv_vn01", OpClass.NOC, 0b001_0100, (0, 1, 1), family=IsaFamily.VNICE),
        op("gtld_drv_vn01", OpClass.GLSU, 0b001_0100, (0, 1, 1),
           family=IsaFamily.VNICE,
           notes="funct7 前缀是 NoC(001)，与 noc_drv_vn01 完全撞车 —— 表里的疑点"),
    ])
