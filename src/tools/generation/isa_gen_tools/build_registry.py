"""维护脚本：把《指令编码总表》xlsx 编成 `schema/ops.registry.json`。

**不被运行时代码 import。** 它只在编码表更新时手工跑一次，产物进 git ——
于是"指令表变了吗"这件事在 diff 里看得见，而不是藏在某个二进制里。

用法（xlsx 路径**必须显式给** —— 不硬编码，见 `test_layering` 的路径守卫）：

    python -m src.tools.generation.isa_gen_tools.build_registry \
        --pre-drv "HM056_V2_ISA_Pre_Drv.xlsx" \
        --out src/tools/generation/isa_gen_tools/schema/ops.registry.json

为什么要有这一步而不是运行期直接读 xlsx
    两个理由，第二个更重要：
      · xlsx 是外部输入、不进仓库，运行期读它等于工具没法单独跑；
      · **"当前用的是哪一版编码表"应当是可审计的**。JSON 进 git 之后，
        哪天有人改了 funct7，diff 里看得见 —— 这比"运行时读一个可能被替换掉的
        文件"靠谱得多。

xlsx 里没有、这里补上的字段
    编码表只有"编码"那一半。工具要的还有"用法"那一半（配对、需要哪张 cfg、
    mask 语义），它们来自 `08_验证策略.md` §3.11 与 §3.2.1 —— 见下面的
    `PAIRING_OVERRIDES` / `_cfg_for`。**这两处是手工维护的，所以单独摆在
    显眼位置**，而不是散在解析逻辑里。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

#: sheet 名 → 指令大类（文档 §3.2 的七类）
SHEET_CLASS = {
    "ctrl": "control",
    "noc": "noc",
    "glsu": "glsu",
    "tmu": "tmv",
    "mpu": "mpu",
    "vpu": "vpu",
}

#: 配对关系 —— **手工维护**，来源是文档 §3.11 的"前置条件 / 硬约束"两列。
#:
#: 为什么不自动推：编码表里没有任何一列表达"这条 drv 必须先来一条 pre"，
#: 那是**事务**层的语义（§3.9）。按名字猜（"带 _pre_ 的就配对"）会在
#: `die_cluster_pre_xn` 这种"pre 但不配对任何 drv"的地方猜错。
PAIRING_OVERRIDES: Dict[str, str] = {
    # MPU：gemm 族必须先来一条 out_org/out_sc 的 pre（§3.11 MPU 组）
    "gemm_drv_xn": "pre_drv",
    "gemm_acc_drv_xn": "pre_drv",
    "gemm_dq_drv_xn": "pre_drv",
    "gemm_dq_acc_drv_xn": "pre_drv",
    # NoC：dst/src 强配对，中途不许插别的指令（§3.11 noc_pair_txn）
    "noc_drv_dst_xn": "dst_src",
    # GLSU：tdram 是 pre + drv 两段（§3.11 tdram_txn）
    "tld_dram_drv_xn": "pre_drv",
    "gtld_dram_drv_xn": "pre_drv",
    # VPU：向量运算族普遍是 pre + drv（§3.11 VPU 组）
    "vv_v_drv_xn": "pre_drv",
    "vvv_v_drv_xn": "pre_drv",
    "vs_v_drv_xn": "pre_drv",
    "vss_v_drv_xn": "pre_drv",
    "v_s_drv_xn": "pre_drv",
}

#: 名字前缀 → 需要先配的 cfg 表。文档 §3.11 各组的"前置条件"列。
CFG_BY_PREFIX = (
    ("tld", "tld_cfg"), ("gtld", "tld_cfg"), ("ttld", "tld_cfg"),
    ("tst", "tst_cfg"), ("gtst", "tst_cfg"), ("ttst", "tst_cfg"),
    ("gat", "tld_cfg"),
    ("noc", "noc_cfg"),
    ("bc_", "tmu_cfg"), ("vbc", "tmu_cfg"), ("tmov", "tmu_cfg"),
    ("setCIMExp", "tmu_cfg"), ("getCIMExp", "tmu_cfg"),
    ("gemm", "mpu_cfg"),
    ("v", "vpu_cfg"),                # 兜底：v 系列都吃 vpu_cfg
)


def _cfg_for(name: str) -> str:
    for prefix, table in CFG_BY_PREFIX:
        if name.startswith(prefix):
            return table
    return ""


#: 文档 §3.2 里那批**非指令 op** —— 它们不在编码表里（没有 funct7），
#: 但同样是 IR 的合法条目。分两个来源、分得很清楚，而不是混在一张表里
#: 让人以为它们也有编码。
#:
#: 格式：`(名字, 类别, 说明)`。类别对应文档 §3.2 表里"配置 / 数据 / 时序 /
#: 观测 / 并发 / 逃生口"那几行。
NON_INSTRUCTION_OPS = (
    # 配置（走 csr_agent，AXI-Lite）
    ("csr_write", "config", "CSR 写；dword 对齐"),
    ("csr_read", "config", "CSR 读"),
    ("intr_ack", "config", "W1C 清中断；语义独立于普通写"),
    ("peer_cfg", "config", "NoC Peer 参数（bresp_policy / err_inject / skew），运行期可调"),
    ("dram_cfg", "config", "DRAM 模型延迟与拥塞注入参数，运行期可调"),
    # 数据（preload_engine / CMI）
    ("mem_init", "data", "装载双通路：instr / backdoor"),
    ("mem_scrub", "data", "强制 SRAM 清零或 pattern 填充，防 X 传播"),
    # 时序
    ("wait_done", "timing", "等某个 tag 完成"),
    ("wait_cycles", "timing", "推进 N 拍；与 nop 不等价"),
    ("wait_event", "timing", "等事件池里的信号"),
    ("signal_event", "timing", "向事件池发信号"),
    ("nop", "timing", "序列级占位 / 对齐"),
    ("watchdog", "timing", "分段超时，后随直至标签；超时判失败"),
    # 观测 / 期望
    ("expect_rd", "observe", "xd=1 返回值检查（rsp 口）"),
    ("expect_write", "observe", "binds/writes 允许写集合的在线核对"),
    ("expect_region", "observe", "区域级中间态比对；**依赖 ISS 中途快照 A10**"),
    ("expect_intr", "observe", "中断断言：来源、时间窗、次数"),
    ("expect_perf", "observe", "性能断言"),
    ("perf_window", "observe", "性能统计窗口"),
    ("checkpoint", "observe", "显式中态对拍点（快照动作，非判定）"),
    ("expect_idle", "observe", "teardown 门禁：DUT 全部 master / 通道空闲"),
    # 并发
    ("batch_begin", "concurrency", "同拍竞争窗口开始"),
    ("batch_end", "concurrency", "同拍竞争窗口结束"),
    ("spawn_async", "concurrency", "后台长窗口活动"),
    # 逃生口（**仅用于负例**，文档 §3.2）
    ("raw_cmd", "escape", "直驱 CMD_SCH 口；仅负例，必须同轨配 expect_intr"),
    # 预留（电源 / 复位）
    ("reset", "reserved", "中程复位恢复；行为依赖 ISS-01"),
    ("pwr_ctl", "reserved", "上下电 / ICG；**A14 规格缺失，现阶段不允许进入回归**"),
)


def _normalize_encoding(row: Dict[str, Any], sheet_name: str):
    """行里的 funct7 / flags → 规范形式；不像编码就返回 (None, None)。

    为什么要容错而不是直接崩：编码表是**外部输入**，里面除了指令还有段标记、
    "暂时不做"的备注行、甚至整行合并的标题。遇到这种行就跳过 ——
    但调用方会**把它们报出来**（见 `build_ops`），不是静默丢。
    """
    raw_f = _text(row["funct7"]).replace(" ", "")
    raw_flags = _text(row["flags"]).replace("，", ",").replace(" ", "")
    if not raw_f or set(raw_f.replace("_", "")) - {"0", "1"}:
        return None, None
    parts = [p for p in raw_flags.split(",") if p != ""]
    if len(parts) != 3 or set("".join(parts)) - {"0", "1"}:
        return None, None
    if len(raw_f.replace("_", "")) != 7:
        return None, None
    return raw_f, [int(p) for p in parts]


def _role_for(raw_role: str) -> str:
    """表里的 `pre` / `drv` **原样保留**。

    早先我把"标了 drv 但没配对"的压成 `lone`，那是错的 —— 它把两件事
    揉在一起了：`role` 是"这条指令在事务里干什么"（表里写着的），
    `pairing` 才是"要不要配对"。绝大多数 drv 确实是自足的，
    但那由 `pairing: none` 表达，不该改写 role。
    """
    role = (raw_role or "").strip().lower()
    return role if role in ("pre", "drv") else "lone"



def read_sheet(ws) -> List[Dict[str, Any]]:
    """一个 sheet → 若干行。**先填合并单元格**，否则组信息只在首行有。"""
    grid = [[ws.cell(row=r, column=c).value for c in range(1, ws.max_column + 1)]
            for r in range(1, ws.max_row + 1)]
    for merged in ws.merged_cells.ranges:
        value = ws.cell(row=merged.min_row, column=merged.min_col).value
        for r in range(merged.min_row - 1, min(merged.max_row, len(grid))):
            for c in range(merged.min_col - 1, min(merged.max_col, ws.max_column)):
                grid[r][c] = value

    rows: List[Dict[str, Any]] = []
    section = ""            # "Nice 指令集" / "Vnice 指令集"
    role = ""
    sub_family = ""
    shift = _column_shift(grid)
    for raw in grid:
        first = _text(raw[0]) if raw else ""
        # 段头：一整行只有第一列有字，且是"N ICE/Vnice 指令集"
        if first.endswith("指令集"):
            section = first
            # 段切换要**重置**子族与角色：它们都是"向下粘"的，
            # 不重置的话 Nice 段最后一个子族会粘到 Vnice 段的头上
            # （`mv_m_drv_xn` 的 MV_M 曾经粘到了四条 `v1v2_pre_vn*` 上）。
            sub_family = ""
            role = ""
            continue
        if first in ("pre", "drv"):
            role = first
        # VPU 的列布局不同：col2 是子族，col3 是名字
        shift = _column_shift(grid)
        name = _text(raw[1 + shift]) if len(raw) > 1 + shift else ""
        if not name or name in ("Inst Name", "funct7"):
            continue
        if name.endswith("指令集"):
            continue
        # vpu 的 col2 与 col1 同名叫 "Inst Group"，但装的是子族
        # （V_S / VV_V / VS_V / V_V / M_V / MV_M）；pre 段里它填的是 "pre"，
        # 那不是子族，别记进来。
        family_hint = _text(raw[1]) if shift else ""
        if family_hint and family_hint not in ("Inst Name", "pre", "drv")                 and not family_hint.endswith("指令集"):
            sub_family = family_hint
        rows.append({
            "name": name,
            "section": section,
            "role_raw": role,
            "funct7": _text(raw[2 + shift]),
            "flags": _text(raw[3 + shift]),
            "opcode": _text(raw[7 + shift]) if len(raw) > 7 + shift else "",
            "fields": {
                "rdval": _text(raw[4 + shift]) if len(raw) > 4 + shift else "",
                "rs1val": _text(raw[5 + shift]) if len(raw) > 5 + shift else "",
                "rs2val": _text(raw[6 + shift]) if len(raw) > 6 + shift else "",
            },
            "sub_family": sub_family if shift else "",
            "trailing": [_text(v) for v in raw[8 + shift:] if _text(v)],
        })
    return rows


def _column_shift(grid) -> int:
    """这张表的列比标准布局**右移**了几列。

    vpu 多一个"子族"列（V_S / VV_V / VS_V / V_V / M_V），所以它的
    `Inst Name` 在第 3 列而不是第 2 列。

    **按"Inst Name 在哪一列"来认，不按 sheet 名硬编码** —— 表结构变了
    （比如哪天又给别的 sheet 加了列）时，这个判据跟着动；
    硬编码 `sheet == "vpu"` 则会安静地用错列，然后解出一堆垃圾。
    """
    if not grid:
        return 0
    head = [_text(v) for v in grid[0]]
    if "Inst Name" not in head:
        return 0
    return max(0, head.index("Inst Name") - 1)


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def build_ops(pre_drv: Path) -> List[Dict[str, Any]]:
    import openpyxl

    wb = openpyxl.load_workbook(pre_drv, data_only=True)
    ops: List[Dict[str, Any]] = []
    skipped: List[tuple] = []
    for sheet_name, op_class in SHEET_CLASS.items():
        if sheet_name not in wb.sheetnames:
            print(f"  ! 缺少 sheet {sheet_name}", file=sys.stderr)
            continue
        for row in read_sheet(wb[sheet_name]):
            name = row["name"]
            funct7, flags = _normalize_encoding(row, sheet_name)
            if funct7 is None and flags is None:
                skipped.append((sheet_name, name, row["funct7"], row["flags"]))
                continue
            family = "vnice" if "Vnice" in row["section"] else "nice"
            deferred = any("暂时不做" in t for t in row["trailing"])
            notes = "；".join(t for t in row["trailing"] if "暂时不做" not in t)
            ops.append({
                "name": name,
                "op_class": op_class,
                "isa_family": family,
                "funct7": funct7,
                "flags": flags,
                "opcode": row["opcode"],
                "role": _role_for(row["role_raw"]),
                "pairing": PAIRING_OVERRIDES.get(name, "none"),
                "cfg_required": _cfg_for(name),
                # NICE 读全局 group_mask 寄存器；VNICE 指令自带 6b_grp_mask
                "mask_semantics": "inline" if family == "vnice" else "global",
                "sub_family": row["sub_family"],
                "deferred": deferred,
                "fields": row["fields"],
                "notes": notes,
            })
    wb.close()
    if skipped:
        # **跳过要报账**：外部表里多出来的行可能是新指令、也可能是段标记。
        # 静默丢掉就等于"表更新了而工具不知道"——那是最难查的一类问题。
        print(f"跳过 {len(skipped)} 行（funct7/flags 不像编码）：", file=sys.stderr)
        for sheet_name, name, raw_f, raw_fl in skipped[:12]:
            print(f"  [{sheet_name}] {name!r} funct7={raw_f!r} flags={raw_fl!r}",
                  file=sys.stderr)
    ops.extend(_extra_ops())
    ops.sort(key=lambda r: (r["op_class"], r["funct7"] or "~~~~~~~",
                            r["flags"] or [0, 0, 0], r["name"]))
    return ops


def _extra_ops() -> List[Dict[str, Any]]:
    """§3.2 里那批非指令 op —— 没有编码，但有名字和用途。

    `op_class` 用 `"op"`（而不是某个 funct7 类）把它们与指令区分开：
    编码器看到 `op_class == "op"` 就知道这条不进指令流。
    """
    out = []
    for name, kind, note in NON_INSTRUCTION_OPS:
        out.append({
            "name": name,
            "op_class": "op",
            "isa_family": "nice",
            "funct7": "",
            "flags": None,
            "opcode": "",
            "role": "lone",
            "pairing": "none",
            "cfg_required": "",
            "mask_semantics": "global",
            "sub_family": kind,
            "deferred": False,
            "fields": {},
            "notes": note,
        })
    return out


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="isa_gen_build_registry")
    parser.add_argument("--pre-drv", required=True,
                        help="《指令编码总表》Pre/Drv 那份 xlsx 的路径")
    parser.add_argument("--out", required=True, help="输出的 ops.registry.json")
    args = parser.parse_args(argv)

    src = Path(args.pre_drv)
    if not src.is_file():
        print(f"找不到 {src}", file=sys.stderr)
        return 2

    ops = build_ops(src)
    payload = {
        "version": 1,
        "source": src.name,          # 只记文件名 —— 绝对路径会泄漏本机布局
        "ops": ops,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    print(f"写出 {len(ops)} 条 op → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
