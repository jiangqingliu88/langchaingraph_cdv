"""vcover 文本解析 —— **一处实现**（`collect_real_coverage` 只做 re-export）。

从 1600 行的采集文件里拆出来：解析是纯函数（不碰 EDA/文件系统），
合并、种子分析、逐用例取证都读它；混在采集文件里时，任何一处改正则都要
在 1600 行里找。
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

def _parse_cvg_text(text: str) -> dict:
    """解析 `vcover report -cvg` 输出，提取功能覆盖率。

    输出长这样（实测）：

        Enabled Coverage              Bins      Hits    Misses  Coverage
        Covergroups                      3        na        na    34.24%
            Coverpoints/Crosses          9        na        na        na
                Covergroup Bins       4360        64      4296     1.46%
        TOTAL COVERGROUP COVERAGE: 34.24%  COVERGROUP TYPES: 3

    两行两个数，含义不同、都要：
      · `Covergroups … 34.24%` —— **covergroup 级**：有多少个 covergroup 被完整覆盖；
      · `Covergroup Bins … 1.46%` —— **bin 级**：4360 个 bin 只命中 64 个。

    `functional_pct` 取**后者**（bin 命中率）—— 那才是"功能盖了多少"，前者只要
    covergroup 里有一个 bin 没中就掉到很低，粗到没有指导意义。

    **不能"把所有百分比抓出来求平均"**（原来是这么写的）：那段文本里同一个数字
    出现三次（Covergroups 行、TOTAL 行、Total By Instance 行），平均下来正好把
    1.46% 那条冲淡 —— 实测报出 26.0%，而真值是 1.46%。`covergroup_count` 同理，
    原来数的是"出现了几个百分号"。
    """
    result = {"functional_pct": 0.0, "covergroup_count": 0, "raw_pcts": [],
              "covergroup_pct": 0.0, "bin_hits": 0, "bin_total": 0}
    if not text:
        return result

    def _counts(label: str):
        """`<label> <bins> <hits> <misses> <pct>%` —— 前三个是计数（可能带千分位逗号，
        也可能是 `na`），最后一个是百分比字符串。"""
        m = re.search(label + r"\s+([\d,]+)\s+([\d,]+)\s+([\d,]+)\s+(\d+\.?\d*)%", text)
        if not m:
            return None
        return (int(m.group(1).replace(",", "")), int(m.group(2).replace(",", "")),
                int(m.group(3).replace(",", "")), float(m.group(4)))

    bins_row = _counts("Covergroup Bins")
    if bins_row:
        total, hits, _misses, pct = bins_row
        result.update(bin_total=total, bin_hits=hits, functional_pct=pct)

    # `Covergroups  3  na  na  34.24%` —— 这行的中间两列是 `na`（没有"bin 数"一说）
    cg_row = re.search(r"Covergroups\s+([\d,]+)\s+\S+\s+\S+\s+(\d+\.?\d*)%", text)
    if cg_row:
        result["covergroup_pct"] = float(cg_row.group(2))
    types = re.search(r"COVERGROUP TYPES:\s*(\d+)", text)
    if types:
        result["covergroup_count"] = int(types.group(1))
    elif cg_row:
        result["covergroup_count"] = int(cg_row.group(1).replace(",", ""))

    result["raw_pcts"] = [float(m) for m in re.findall(r"(\d+\.?\d*)%", text)]
    result["covergroups"] = _parse_cvg_details(text)
    return result


#: `-cvg -details` 里的三行结构（`Coverpoint` / `Cross` 缩进更深，但都靠行首词认）。
_CG_TYPE_RE = re.compile(r"^\s*TYPE\s+(\S+)\s*$", re.M)
_CG_CP_RE = re.compile(r"^\s*Coverpoint\s+(\S+)\s+(\d+\.?\d*)%", re.M)
_CG_CROSS_RE = re.compile(r"^\s*Cross\s+(\S+)\s+(\d+\.?\d*)%", re.M)
_CG_PCT_RE = re.compile(r"^\s*(\d+\.?\d*)%")

def _parse_cvg_details(text: str) -> list:
    """`vcover report -cvg -details` → `[{name, path, goal, actual, coverpoints,
    crosses, cross_actual}]`。

    形状对齐 `config/evidence_schema.yaml` 的 `functional_coverage_layer`
    `evidence_fields.covergroups`（`name` / `goal` / `actual` / `coverpoints` /
    `crosses`）—— 证据链那边读的就是这几个键，键名对不上就等于没有。

    实测输出长这样（`-cvg` 单独用时**没有**这一段，见上面 cmd3 的注释）：

        TYPE /apb_uart_env_pkg/apb_uart_env_coverage/cg_apb
                                                       71.42%        100          -    Uncovered
            Coverpoint cp_paddr                                66.66%        100 ...
            Cross cross_all                                    33.33%        100 ...

    `TYPE` 那一行给全路径（**末段才是 covergroup 名**），百分比在**下一行**的首列 ——
    这是 vcover 的排版，不是我们选的。
    """
    if not text:
        return []
    # 只看 `COVERGROUP COVERAGE:` 那一段。`-details` 的输出有**两段**：
    #   ① "Coverage Report by instance with details"  —— 逐实例（含每个 bin 的命中数）
    #   ② "COVERGROUP COVERAGE:"                      —— 逐 **type**
    # 两段的 `TYPE` 行一模一样，照全文抓会把每个 covergroup 收两遍（实测 3 个变 6 个），
    # 而证据链要的是"有几个 covergroup 类型、各自多少" —— 那就是第 ② 段。
    head = text.find("COVERGROUP COVERAGE:")
    seg_text = text[head:] if head >= 0 else text

    out: list = []
    matches = list(_CG_TYPE_RE.finditer(seg_text))
    for i, m in enumerate(matches):
        # 本 covergroup 的段落：从这一行的结尾到下一个 TYPE 的开头
        end = matches[i + 1].start() if i + 1 < len(matches) else len(seg_text)
        seg = seg_text[m.end():end]
        path = m.group(1)
        pct_m = _CG_PCT_RE.search(seg)
        actual = float(pct_m.group(1)) if pct_m else 0.0
        coverpoints = [{"name": n, "actual": float(p)}
                       for n, p in _CG_CP_RE.findall(seg)]
        crosses = [{"name": n, "actual": float(p)}
                   for n, p in _CG_CROSS_RE.findall(seg)]
        # `five_layer` 的 `func_cov_cross` 读的是 `cross_actual`（不是 crosses 列表）。
        # **不给就是默认 100 分**——那会让"一个 cross 都没跑"悄悄通过门禁，
        # 所以这里按最差的那个 cross 如实给。
        cross_actual = min((c["actual"] for c in crosses), default=100.0)
        out.append({
            "name": path.rsplit("/", 1)[-1],
            "path": path,
            "goal": 100.0,
            "actual": actual,
            "coverpoints": coverpoints,
            "crosses": crosses,
            "cross_actual": cross_actual,
        })

    # 兜底去重：没有 `COVERGROUP COVERAGE:` 标记时（格式变了）仍按全路径收一遍，
    # 同一个路径只留第一次 —— 宁可少几行，也不要把同一个 covergroup 报两次。
    seen: set = set()
    return [c for c in out if not (c["path"] in seen or seen.add(c["path"]))]

def _parse_cvg_bin_hits(text: str) -> dict:
    """`vcover -cvg -details` → `{covergroup: {coverpoint: {bin: hits}}}`。

    只扫**第一段**（`COVERGROUP COVERAGE:` 之前）—— 那段的 `TYPE` 行下带着
    逐 bin 的命中数；第二段只有 covergroup 级百分比。两段都扫会把同一个 bin
    收两遍（见 `_parse_cvg_details` 的注释）。
    """
    out: dict = {}
    head = text.find("COVERGROUP COVERAGE:")
    seg = text[:head] if head >= 0 else text
    cg = cp = ""
    for ln in seg.splitlines():
        m = re.match(r"\s*TYPE\s+(\S+)\s*$", ln)
        if m:
            cg = m.group(1).rstrip("/").split("/")[-1]
            out.setdefault(cg, {})
            cp = ""
            continue
        m = re.match(r"\s*Coverpoint\s+(\S+)\s+", ln)
        if m:
            cp = m.group(1)
            if cg:
                out[cg].setdefault(cp, {})
            continue
        m = re.match(r"\s*(?:illegal_)?bin\s+(\S+)\s+(\d+)", ln)
        if m and cg and cp:
            name, hits = m.group(1), int(m.group(2))
            bins = out[cg][cp]
            # 同一 bin 在段内只出现一次；重复时取最大（防御性，不累加）
            bins[name] = max(bins.get(name, 0), hits)
    return out
