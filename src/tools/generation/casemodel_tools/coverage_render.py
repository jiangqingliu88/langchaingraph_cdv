"""覆盖率渲染 —— covergroup / probe / 覆盖率接口的 SystemVerilog 生成。

从 `casemodel_tools/coverage.py` 拆出；只吃模型、吐字符串，不读不写文件。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

import yaml

from .coverage_model import (
    MAX_BINS_PER_POINT, CoverBin, CoverPoint, CoverageModel, CrossBin, CrossPoint,
    _slug, sv_ident, sv_value,
)

DEFAULT_WIDTH = 32


def render_covergroup(cm: CoverageModel) -> str:
    """`CoverageModel` → 可编译的 SystemVerilog covergroup 文本。

    产出**一个** covergroup（cross 要求同作用域），**不自带采样事件** ——
    采样时钟是集成方的事（它才知道该挂哪个时钟/哪个接口）。例化与采样：

        cg_<module> cg = new();
        // 每条用例跑完（或每个事务到达时）
        cg.sample();

    这样切分是有意的：本工具**不认识** testbench 结构（铁律：工具只管自己的
    契约），把时钟写死在这里就等于替集成方做决定，而且多半是错的。
    """
    lines: List[str] = [
        f"// 功能覆盖率点 —— 由 case 模型生成（casemodel_tools.coverage）",
        f"// 一条 = 一个覆盖点；bin 名取自模型的 cover_bins 或取值本身。",
        f"// 采样由集成方负责：`{cm.covergroup} cg = new(); cg.sample();`",
        f"covergroup {cm.covergroup};",
    ]
    if not cm.coverpoints:
        lines.append("    // 模型里没有任何可取值的字段 —— 这个 covergroup 是空的")
    for cp in cm.coverpoints:
        lines.append(f"    cp_{cp.signal}: coverpoint {cp.signal} {{")
        for b in cp.bins + cp.illegal_bins:
            kind = "illegal_bins" if b.illegal else "bins"
            note = f"  // {b.token}" if b.token else ""
            if b.boundary and not b.illegal:
                note = f"  // {b.token}（边界）"
            lines.append(f"        {kind} {b.name} = {{{b.literal()}}};{note}")
        lines.append("    }")
    for cx in cm.crosses:
        # `cross` 支持 N 个 coverpoint（跨组 cross 就是三元及以上）；refs 用
        # `cx.refs` 而不是硬拼 `cp_<signal>` —— 作者可能给覆盖点起了别名。
        refs = list(cx.refs)
        ref_of = dict(zip(cx.signals, refs))
        if not cx.bins:
            lines.append(f"    {cx.name}: cross {', '.join(refs)};  // {cx.level}")
            continue
        lines.append(f"    {cx.name}: cross {', '.join(refs)} {{  // {cx.level}")
        for b in sorted(cx.bins, key=lambda x: x.illegal):
            terms = " && ".join(
                f"binsof({ref_of.get(sig, 'cp_' + sig)}.{name})"
                for sig, name in b.when.items())
            kind = "illegal_bins" if b.illegal else "bins"
            lines.append(f"        {kind} {b.name} = {terms};")
        lines.append("    }")
    lines.append("endgroup")
    return "\n".join(lines) + "\n"


DEFAULT_CLOCK = "clk"


DEFAULT_RESET = "rst_n"


DEFAULT_INSTANCE = "u_cg_probe"


def probe_ports(cm: CoverageModel) -> List[CoverPoint]:
    """探针要声明的端口 —— 就是 `sample: dut` 的那些覆盖点。"""
    return cm.by_source("dut")


def render_probe(cm: CoverageModel, sampling: Dict[str, Any] = None) -> str:
    """`CoverageModel` → 一个 **bind 进 DUT 的探针模块**（含 bind 语句）。

    ## 为什么必须是 bind

    DUT 的**输入端口、输出端口、内部寄存器**，对一个 `bind` 进去的模块来说
    **没有区别** —— 差别只在于"从哪看得见"。而：

      · monitor 的事务通道**只看得到激励侧**：队列水位、依赖类型、发射决策这些
        内部状态与输出端口，它一个都采不到。
      · 层次引用（`u_dut.u_sched.queue_level`）要把 tb_top 的实例名写死，
        换个 bench 就断。

    `bind` 不带这两个问题：挂到**模块**上，每个实例自动带一份；端口连接表达式
    在**目标模块作用域**里求值，所以 `queue_level` 这类内部名直接就能连（实测）。

    ## 采样

    covergroup **不自带事件**，由一句显式的采样驱动：

        always @(posedge clk) if (rst_n) cg.sample();

    复位周期不采（`reset` 给空就不加这个 `if`）—— 复位期间的水位/决策是
    无意义值，采进去只会把 bin 命中率弄脏。

    ## 生成不出探针的两种情形（都记账，由调用方决定）

      · 模型里没有 `sample: dut` 的字段 → 空串（不需要探针）
      · 没有 `sampling.dut_module` → 空串（**bind 的目标都不知道**）
    """
    sampling = sampling or {}
    cps = probe_ports(cm)
    if not cps:
        return ""
    dut_module = sv_ident(sampling.get("dut_module"), "")
    if not dut_module:
        return ""

    clock = sv_ident(sampling.get("clock") or DEFAULT_CLOCK, DEFAULT_CLOCK)
    # 复位给 `null` / 空串 = **不加屏蔽**（有的 DUT 用高有效复位，或者压根不采复位）
    reset = _slug(sampling.get("reset", DEFAULT_RESET)) or ""
    instance = sv_ident(sampling.get("instance") or DEFAULT_INSTANCE,
                        DEFAULT_INSTANCE)
    guard = f"if ({reset}) " if reset else ""

    # 探针的端口 = 时钟 + 复位 + 每个采样信号。**复位也得是端口** ——
    # 它同样活在 DUT 的作用域里，裸写在 `if` 里 probe.sv 当场报
    # `Undefined variable: 'rst_n'`（实测）。
    extra_ports = [clock] + ([reset] if reset else [])

    cg_name = f"{cm.covergroup}_dut"
    guard_macro = f"{cg_name.upper()}_SV"

    out: List[str] = [
        f"`ifndef {guard_macro}",
        f"`define {guard_macro}",
        "",
        "// DUT 信号的功能覆盖率 —— 由 case 模型生成（casemodel_tools.coverage）",
        f"// 用 `bind` 挂到 `{dut_module}` 上：该模块的**每个实例**都会带一份探针。",
        "//",
        "// 为什么走 bind 而不是从 monitor 采：monitor 只看得到**激励侧**，而",
        "// 队列水位 / 依赖类型 / 发射决策这些是内部状态与输出端口 —— 只有从 DUT",
        "// 内部才看得见。端口连接表达式在**目标模块作用域**里求值，所以内部名",
        "// 直接连过来即可。",
        "",
        f"module {cg_name}_probe (",
    ]
    for name in extra_ports:
        out.append(f"  input logic {name},")
    for i, cp in enumerate(cps):
        decl = f"[{cp.width - 1}:0] " if cp.width > 1 else ""
        sep = "," if i < len(cps) - 1 else ""
        src = cp.expr or cp.signal
        note = f"  // {cp.field}" + (f" ← {src}" if cp.expr else "")
        out.append(f"  input logic {decl}{cp.signal}{sep}{note}")
    out += [
        ");",
        "",
        f"  covergroup {cg_name};",
        "    option.per_instance = 1;",
    ]
    for cp in cps:
        out.append(f"    cp_{cp.signal}: coverpoint {cp.signal} {{")
        for b in cp.bins + cp.illegal_bins:
            kind = "illegal_bins" if b.illegal else "bins"
            note = f"  // {b.token}" if b.token else ""
            out.append(f"        {kind} {b.name} = {{{b.literal()}}};{note}")
        out.append("    }")
    for cx in cm.crosses:
        if cx.source != "dut":
            continue
        refs = list(cx.refs)
        ref_of = dict(zip(cx.signals, refs))
        if not cx.bins:
            out.append(f"    {cx.name}: cross {', '.join(refs)};")
            continue
        out.append(f"    {cx.name}: cross {', '.join(refs)} {{")
        for b in sorted(cx.bins, key=lambda x: x.illegal):
            terms = " && ".join(
                f"binsof({ref_of.get(sig, 'cp_' + sig)}.{name})"
                for sig, name in b.when.items())
            kind = "illegal_bins" if b.illegal else "bins"
            out.append(f"        {kind} {b.name} = {terms};")
        out.append("    }")
    out += [
        f"  endgroup",
        "",
        f"  {cg_name} cg = new();",
        "",
        "  // 采样：时钟沿，且**不在复位周期**（复位期间的水位/决策是无意义值）",
        f"  always @(posedge {clock}) {guard}cg.sample();",
        "endmodule",
        "",
        f"bind {dut_module} {cg_name}_probe {instance}(",
    ]
    # 连接表**不能有尾逗号**（`..., )` 是语法错误 —— 实测 vlog 报
    # `near ")": syntax error, expecting .* or '.'`）。所以攒完再 join。
    conns = [f"  .{n}({n})" for n in extra_ports]
    conns += [f"  .{cp.signal}({cp.expr or cp.signal})" for cp in cps]
    out.append(",\n".join(conns))
    out += [");", "", f"`endif  // {guard_macro}", ""]
    return "\n".join(out)


def _plan_paths(model: CaseModel, notes: List[str]) -> List[Dict[str, Any]]:
    """`path_groups` → 计划里的 `paths` 段（一条 bin 一行，状态 PENDING_BACKEND）。

    与功能覆盖点**并列**，不进功能覆盖率分母（执行后端 P1b 待接）。放进计划
    是为了让"路径视图"和"功能视图"在同一份材料里 —— 评审问"每组 100% 怎么
    证明路径通"时，能直接指向这份清单，而不是靠口头解释。
    """
    paths: List[Dict[str, Any]] = []
    for group in getattr(model, "path_groups", []) or []:
        bins = []
        for b in getattr(group, "bins", []) or []:
            bins.append({"name": b.name, "sequence": list(b.sequence),
                         "checks": list(b.checks), "requirement": b.requirement,
                         "timing": dict(b.timing or {})})
            if not b.requirement:
                notes.append(f"PATH 组 {group.id} 的 bin {b.name} 没有需求编号 —— "
                             f"追溯矩阵里认领不到它")
        paths.append({"id": group.id, "name": getattr(group, "name", "") or group.id,
                      "coverpoint": group.cp_name,
                      "sample": getattr(group, "sample", "path_seq"),
                      "groups": list(getattr(group, "groups", []) or []),
                      "bins": bins, "bin_count": len(bins),
                      "status": "PENDING_BACKEND", "covered_by": []})
    return paths


def _claimed_requirement(entry: Dict[str, Any]) -> bool:
    """需求是否被覆盖点 / 交叉 / PATH 任一方认领。"""
    return bool(entry["coverpoints"] or entry["crosses"] or entry["paths"])


def _claim_path_requirements(paths: List[Dict[str, Any]], slot_fn, refs_fn) -> None:
    """PATH 组也认领需求：只被路径覆盖的需求不是孤立需求。"""
    for p in paths:
        for b in p["bins"]:
            for r in refs_fn(b["requirement"]):
                slot = slot_fn(r)
                ref = f"{p['id']}.{b['name']}"
                if ref not in slot["paths"]:
                    slot["paths"].append(ref)


def coverage_plan(model: CaseModel, cm: CoverageModel,
                  module_name: str = "dut") -> Dict[str, Any]:
    """case 模型 + 覆盖点模型 → **一份完整的功能覆盖率计划**（dict，可 yaml 化）。

    ## 为什么单独一份，而不是散在几处

    覆盖这件事有四张脸，各有各的读者：

        §3 覆盖点     谁在采、采什么、bin 是什么   → 生成 covergroup 的人
        §5 批次       这一批打哪个专题、跑哪个 test → 回归
        §6 种子管理   这一批跑几条才算数            → 回归
        §8 需求追溯   哪条需求被谁验了              → 签核的人

    它们**同源**（都从同一份 case 模型派生），但分散在三四个文件里对账会很痛苦
    ——尤其是"覆盖点声明了 12 个、回归里只跑了 8 条"这种事，只有把两边摆在一张
    表上才看得出来。所以**一起生成**：与 case 模型同批落盘，谁都不许自己算一遍。

    ## 里面有什么是"推"出来的、什么是"抄"的

      · `coverpoints` / `crosses` —— 从模型**推**（bin 明细、来源通道、宽度）
      · `batch.seeds`             —— 模型里**抄**的（作者声明"这一批要跑够几条"）
      · `total_runs`              —— 推：`count + explore`（这才是要跑的总条数）
      · `traceability`            —— 推：按 `requirement` 把覆盖点/交叉/批次串起来
      · `covered_by`              —— 推：**哪个批次覆盖了这个覆盖点**（按专题的
        `dimensions` 反查）。这替代了文档 §4.5 那张"约束 → 覆盖点"表：约束在
        UVM sequence 里，模型看不见；但"哪个批次负责它"是模型能答的。

    ## 说得出来的与说不出来的

    覆盖点没有 `requirement`、批次没有 `test`/`seeds`、交叉没有 `cover_id` ——
    这些**留空并进 `notes`**，不编一个出来。签核表上引用的编号必须是文档里
    那个，编出来的编号比没有更坏。
    """
    notes: List[str] = []
    by_dim: Dict[str, List[str]] = {}
    for th in model.themes:
        for dim in (th.dims or []):
            by_dim.setdefault(dim.key, []).append(th.key)

    coverpoints: List[Dict[str, Any]] = []
    for cp in cm.coverpoints:
        coverpoints.append({
            "cover_id": cp.cover_id,
            "requirement": cp.requirement,
            "dimension": cp.dimension,
            "signal": cp.signal,
            "type": cp.type,
            "source": cp.source,
            "width": cp.width,
            "expr": cp.expr,
            "bins": [b.name for b in cp.bins],
            "illegal_bins": [b.name for b in cp.illegal_bins],
            "bin_count": len(cp.bins),
            "target": 100,
            "covered_by": by_dim.get(cp.dimension, []),
        })
        if not cp.cover_id:
            notes.append(f"覆盖点 {cp.signal} 没有 cover_id —— 追溯矩阵里引用不到它")

    crosses: List[Dict[str, Any]] = []
    for cx in cm.crosses:
        crosses.append({
            "cover_id": cx.cover_id,
            "requirement": cx.requirement,
            "name": cx.name,
            "dimensions": list(cx.dimensions),
            "level": cx.level,
            "source": cx.source,
            "bins": [b.name for b in cx.bins],
            "illegal_bins": [b.name for b in cx.bins if b.illegal],
            "bin_count": len(cx.bins),
            "target": 100,
            "covered_by": sorted({b for dim in cx.dimensions
                                  for b in by_dim.get(dim, [])}),
        })

    batches: List[Dict[str, Any]] = []
    for th in model.themes:
        seeds = dict(th.seeds or {})
        total = int(seeds.get("count", 0)) + int(seeds.get("explore", 0))
        batches.append({
            "theme": th.key,
            "name": th.label,
            "priority": th.priority,
            "test": th.test,
            "method": th.method,
            "checks": list(th.checks),
            "dimensions": [d.key for d in (th.dims or [])],
            "seeds": seeds,
            "total_runs": total,
        })
        if not th.test:
            notes.append(f"批次 {th.key} 没有 test 名 —— 回归里铺不成一条 test")
        elif not seeds:
            notes.append(f"批次 {th.key}（{th.test}）没有声明 seeds —— "
                         f"回归按默认跑一条，覆盖强度没被声明过")

    paths = _plan_paths(model, notes)

    # ── §8 需求追溯：把三张表按 requirement 串起来 ──
    #
    # **编号要拆**：一条交叉常同时对应两条需求（`REQ-NPU-002/005` 表示"这两条"）。
    # 不拆的话它自己成一条"需求 REQ-NPU-002/005"，而 REQ-NPU-002 那一行没有
    # 交叉 —— 追溯矩阵正好在**最该串起来的地方**断掉。
    reqs: Dict[str, Dict[str, Any]] = {}

    def _refs(raw: str) -> List[str]:
        """`REQ-NPU-002/005` → `["REQ-NPU-002", "REQ-NPU-005"]`。

        **后半段是省略前缀的写法**（`/005` 是 `/REQ-NPU-005` 的简写），照 `/`
        硬拆会得到一条叫 `005` 的"需求" —— 追溯矩阵上凭空多出一条，而真正的
        `REQ-NPU-005` 那一行仍然没有交叉。所以：**第一段的前缀补回给后面那些
        没有分隔符的段**。
        """
        parts = [x.strip() for x in re.split(r"[/、,，;；]", str(raw or ""))
                 if x.strip()]
        if not parts:
            return []
        m = re.match(r"^(.*[-_])", parts[0])       # 贪心 → 取到最后一个分隔符
        prefix = m.group(1) if m else ""
        return [parts[0]] + [x if re.search(r"[-_]", x) else prefix + x
                             for x in parts[1:]]

    def _slot(req: str) -> Dict[str, Any]:
        return reqs.setdefault(req, {"requirement": req, "coverpoints": [],
                                     "crosses": [], "batches": [], "paths": []})
    for cp in coverpoints:
        for r in _refs(cp["requirement"]):
            _slot(r)["coverpoints"].append(cp["cover_id"] or cp["signal"])
    for cx in crosses:
        for r in _refs(cx["requirement"]):
            _slot(r)["crosses"].append(cx["cover_id"] or cx["name"])
    for b in batches:
        for dim in b["dimensions"]:
            for cp in coverpoints:
                if cp["dimension"] != dim:
                    continue
                for r in _refs(cp["requirement"]):
                    slot = _slot(r)
                    if b["theme"] not in slot["batches"]:
                        slot["batches"].append(b["theme"])
    _claim_path_requirements(paths, _slot, _refs)

    # 「孤立需求」= 既没有覆盖点、也没有交叉认领它。
    # **只看 coverpoints 是错的**：一条需求由交叉覆盖（而不是某个覆盖点）完全
    # 正当 —— 按前者算会把 X_NPU_* 认领的那几条需求全判成孤立。
    #
    # 现在这份模型里它**不可能命中**（需求只从字段/交叉上"长"出来，没有独立的
    # `requirements:` 声明块）。留着是为了 §9.1 那个措辞不落空：等模型能单独
    # 声明需求时，这里自动开始生效。
    orphan_reqs = [r["requirement"] for r in reqs.values()
                   if not _claimed_requirement(r)]
    orphan_cps = [cp["signal"] for cp in coverpoints if not cp["requirement"]]
    if orphan_reqs:
        notes.append(f"有需求既没有覆盖点也没有交叉：{'、'.join(sorted(orphan_reqs))} "
                     f"—— 签核要的「无孤立需求」过不了")
    if orphan_cps:
        notes.append(f"有覆盖点没有需求编号：{'、'.join(sorted(orphan_cps))} "
                     f"—— 签核要的「无孤立覆盖点」过不了")

    return {
        "object": model.object,
        "object_cn": model.object_cn,
        "module": cm.module,
        "covergroup": cm.covergroup,
        "sampling": dict(model.sampling or {}),
        "coverpoints": coverpoints,
        "crosses": crosses,
        "batches": batches,
        "paths": paths,
        "traceability": [reqs[k] for k in sorted(reqs)],
        "summary": {
            "coverpoint_count": len(coverpoints),
            "bin_count": sum(c["bin_count"] for c in coverpoints),
            "cross_count": len(crosses),
            "cross_bin_count": sum(c["bin_count"] for c in crosses),
            "path_group_count": len(paths),
            "path_bin_count": sum(p["bin_count"] for p in paths),
            "illegal_bin_count": (sum(len(c["illegal_bins"]) for c in coverpoints)
                                  + sum(len(c["illegal_bins"]) for c in crosses)),
            "batch_count": len(batches),
            "requirement_count": len(reqs),
            "total_runs": sum(b["total_runs"] for b in batches),
        },
        "notes": list(dict.fromkeys(notes + list(cm.notes))),
    }


def _extra_signals(cps, extra_signals) -> List[Dict[str, Any]]:
    """断言规则要用、但**没有**被任何覆盖点采的信号 → 也引成接口端口。

    为什么必须引：env 组件的检查组通过**同一个 virtual interface** 读信号，
    接口上没有的它就够不着 —— 于是那条规则被跳过，"断言那一半"就没人查。
    规则声明的 `signals[{name,width}]` 自带位宽，拿来生成端口即可。

    已经在采样列表里的不重复引（会撞端口名），名字非法的直接丢（`sv_ident`）。
    """
    have = {cp.signal for cp in cps}
    out: List[Dict[str, Any]] = []
    for item in (extra_signals or []):
        if not isinstance(item, dict):
            continue
        name = sv_ident(item.get("name"), "")
        if not name or name in have:
            continue
        try:
            width = int(item.get("width") or 1)
        except (TypeError, ValueError):
            width = 1
        have.add(name)
        out.append({"name": name, "width": max(1, width)})
    return out


def cov_interface_meta(cm: CoverageModel, sampling: Dict[str, Any] = None,
                       if_name: str = "",
                       extra_signals: List[Dict[str, Any]] = None,
                       tp_bitmap_width: int = 0,
                       ) -> Optional[Dict[str, Any]]:
    """覆盖率接口的**全部身份信息** —— 一份，谁都不许自己推。

    三个地方要知道同一个名字：**生成方**（verify 按它落盘）、**消费方**
    （env 组件持 `virtual <type>`）、**挂载方**（tb_top 的 `config_db::set` 要写
    `<dut_instance>.u_<name>`）。三处各推一次就是"改了三个漏一个"的经典形状 ——
    本仓库为这类 bug 已经付过几次账（模块名、bin 名、覆盖点名各一次），所以这里
    把它做成**一个函数**，由契约文件带着走（`env_cov_bins.yaml` 的 `dut_if`）。

    拿不到就说拿不到（返回 `None`）：模型里没有 `sample: dut` 的字段、或者没写
    `sampling.dut_module`（**bind 的目标都不知道**）。调用方据此一个字都不生成 ——
    不生成半个挂不上东西的接口。
    """
    cps = probe_ports(cm)
    if not cps:
        return None
    sampling = sampling or {}
    dut = sv_ident(sampling.get("dut_module"), "")
    if not dut:
        return None
    # 名字**按 bind 的目标模块**取，不按 `cm.module`：管道里 `coverage_model` 的
    # module 常是占位的 "dut"（`run_covergroups(text, "dut")`），拼出来的
    # `dut_cov_if` 既没信息量、又会让不同项目撞同一个类型名。`dut_module` 是
    # 真实存在的那个模块名（没有它连 bind 都写不出来），拿它拼。
    name = sv_ident(if_name or f"{dut}_cov_if", "")
    if not name:
        return None
    clock = sv_ident(sampling.get("clock") or DEFAULT_CLOCK, DEFAULT_CLOCK)
    # 复位给 `null` / 空串 = **不屏蔽**（有的 DUT 高有效复位）—— 与探针同一条规矩
    reset = _slug(sampling.get("reset", DEFAULT_RESET)) or ""
    return {
        "name": name,                     # 接口类型名 = 文件名主干
        "type": name,
        # bind 那个实例名。**tb_top 挂 config_db 时要用它**：
        # `bind` 把实例放进**目标模块的作用域**，所以层次路径就是
        # `<dut 实例>.u_<name>`（实测：这么取到的句柄非空，见 tests）
        "instance": f"u_{name}",
        "dut_module": dut,
        "clock": clock,
        "reset": reset,
        # 采样信号在前，断言规则额外要的信号在后（`signals` 是 env 侧**能读到
        # 什么**的唯一口径：`checker_rules(available=...)` 按它判规则能不能查）
        "signals": ([cp.signal for cp in cps]
                    + [e["name"] for e in _extra_signals(cps, extra_signals)]),
        "extra_signals": _extra_signals(cps, extra_signals),
        # 测试点位图的位宽（0 = 这一轮不产位图）。接口里会多一个**非端口**
        # 变量 `logic [N-1:0] tp_seen`，由 env 覆盖率组件在仓命中时置位 ——
        # 打开波形就能看到"这一拍点亮了哪几个测试点"。
        "tp_bitmap_width": max(0, int(tp_bitmap_width or 0)),
        "coverpoints": [{"signal": cp.signal, "sv_name": cp.sv_name,
                         "field": cp.field, "width": cp.width,
                         "expr": cp.expr} for cp in cps],
        "file": f"coverage/{name}.sv",
    }


def dut_bins(cm: CoverageModel) -> Dict[str, List[Dict[str, Any]]]:
    """`sample: dut` 的覆盖点 → `{信号: [{name, value, illegal}]}`（给 env 组件用）。

    形状与 `field_bins`（case 模型那条通道）**故意一样** —— 两边都是"显式 bins 表"，
    模板可以同一套写法渲染，不必分两套。多出来的 `illegal` 是因为 DUT 侧常有
    `illegal_bins`（越界的水位、非法的决策组合），事务侧那张表暂时没有。
    """
    out: Dict[str, List[Dict[str, Any]]] = {}
    for cp in probe_ports(cm):
        rows = [{"name": b.name, "value": b.literal(), "illegal": bool(b.illegal)}
                for b in cp.bins + cp.illegal_bins]
        if rows:
            out[cp.signal] = rows
    return out


def parse_model_text(text: str) -> Dict[str, Any]:
    """case 模型文本 → dict（解析失败/不是映射 → 空 dict）。

    读不动不算错：覆盖率接口照旧能出，只是断言规则那半没有信号可用。
    """
    if not isinstance(text, str):
        return {}
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError:
        return {}
    return doc if isinstance(doc, dict) else {}


def assertion_signals(doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    """`assertions[].signals` → `[{name, width}]`（覆盖率接口要额外引的信号）。

    已经出现在采样覆盖点里的名字由 `_extra_signals` 去重 —— 这里只管把模型
    声明过的信号**全**交代出去，不在这边判重。
    """
    out: List[Dict[str, Any]] = []
    for decl in (doc.get("assertions") or []):
        if not isinstance(decl, dict):
            continue
        for sig in (decl.get("signals") or []):
            if isinstance(sig, dict) and sig.get("name"):
                out.append({"name": sig.get("name"),
                            "width": sig.get("width") or 1})
    return out


def checker_rules(decls: List[Dict[str, Any]],
                  available: List[str] = None) -> Dict[str, Any]:
    """模型声明的规则 → env 检查组件的**逐拍可求值**形式。

    ## 为什么要转一层

    SVA 的 `a |-> b` 是**时序蕴含**，直接写进 `if` 里不是合法表达式。但在"每个时钟沿
    各求值一次"的检查里，同拍蕴含等价于 `!a || b`（没有 `##` 延迟的规则都成立）——
    这是把同一条规则同时喂给 **SVA（bind 进 DUT）** 与 **env 检查组（UVM 收口）**
    的关键：**一份规则，两个执行点**，数出来的东西才对得上。

    带 `##` / `[*` 的时序规则**不转**（它们表达的是跨拍性质，逐拍 IF 表达不出来）——
    跳过并列出来，不假装检查了。

    `available` 是 env 那边**真能读到**的信号（覆盖率接口的端口）。规则里引用到
    接口没有的信号 → 同样跳过并列出来：**说"这条没查"比假装查了强**（用户口径里
    "没查"不该算过）。
    """
    have = set(available or [])
    rules: List[Dict[str, str]] = []
    skipped: List[str] = []
    for d in (decls or []):
        if not isinstance(d, dict):
            continue
        name = str(d.get("name") or "").strip()
        expr = str(d.get("expr") or "").strip()
        if not (name and expr):
            continue
        if any(t in expr for t in ("##", "[*", "[=", "throughout", "until")):
            skipped.append(f"{name}（时序规则：`##`/重复算子在逐拍检查里表达不出来）")
            continue
        sigs = [str(s.get("name")) for s in (d.get("signals") or [])
                if isinstance(s, dict) and s.get("name")]
        missing = [s for s in sigs if have and s not in have]
        if missing:
            skipped.append(f"{name}（引用到接口上没有的信号：{'、'.join(missing)}）")
            continue
        if "|->" in expr:
            left, _, right = expr.partition("|->")
            sv = f"!({left.strip()}) || ({right.strip()})"
        else:
            sv = f"({expr})"
        # **信号要加虚接口限定** —— 这段表达式最终活在 env 的覆盖率组件里
        #（`env_cov.sv.j2` 的一个 class），那里 `queue_level` 这种**裸名字是不可见的**：
        # DUT 的信号只能经虚接口句柄看见（与 `cg_dut` 的 `coverpoint vif.<信号>` 同理）。
        #
        # 不加限定的后果不是警告，是**编译不过** —— 实测整轮端到端：
        #     npu_sched_env_coverage.sv(272): Undefined variable: 'queue_level'
        #     …共 30 条 → `env_pkg` 整个作废 → `test_pkg` 找不到 env_pkg →
        #     `bench_tb_top` 找不到 test_pkg → `vopt-13130` → 回归 0/7、覆盖率恒 0%。
        # 而它**只在真编译时暴露**：生成侧、schema、单测全看不出来。
        #
        # 句柄名 `cov_vif` 是模板里那个（`env_cov.sv.j2` 的 build_phase 按它取
        # config_db）。**写死是有意的**：真改了名，编译会响亮地报
        # `cov_vif` 未声明，而不是留下一个恒真的检查。
        for _s in sigs:
            sv = re.sub(rf"\b{re.escape(_s)}\b", f"cov_vif.{_s}", sv)
        rules.append({"name": sv_ident(name, "chk"), "expr": sv,
                      "message": str(d.get("message") or name)})
    return {"rules": rules, "skipped": skipped}


def render_cov_interface(cm: CoverageModel, sampling: Dict[str, Any] = None,
                         if_name: str = "",
                         extra_signals: List[Dict[str, Any]] = None,
                         tp_bitmap_width: int = 0) -> str:
    """`CoverageModel` → **一个 bind 进 DUT 的接口**（把采样信号引出来）。

    ## 为什么是"接口"而不是"模块"

    `env/<env>_coverage.sv` 被 `include` 进 `env_pkg` —— **那里面只能是 class**
    （`environment.sv` 把它当 `uvm_component` 例化）。而 class **看不到 DUT 的信号**：
    输入/输出端口尚可经 `virtual interface` 够到，**内部状态**（队列水位、依赖类型）
    则连 virtual interface 也够不着 —— 它们不在任何一个接口上。

    所以信号得先被"引出来"：本函数产出的接口 `bind` 进 DUT，**端口连接表达式在
    目标模块作用域里求值**，于是内部名直接连得过去（实测 vlog 通过）。覆盖率
    组件持 `virtual <本接口>`，`coverpoint vif.<信号>` —— 端口与内部一视同仁。

    ## 与 `render_probe`（那条 bind **探针**）的分工

      `render_cov_interface` 只**引信号**（接口），采样与收口在组件里 ——
      走 UVM 那条正规路子（组件 `sample()`），覆盖率与 UVM 报告在一起。
      `render_probe` 自带 covergroup 与 `always` 采样（一条独立 **模块**）——
      不依赖 UVM，适合"没有 env 也要收覆盖率"的场合。

    两条都靠 `bind`，都靠"端口表达式在 DUT 作用域求值"这一条 SV 语义。

    `sampling` 里没写 `dut_module`（或者模型里根本没有 `sample: dut` 的字段）则返回
    空串 —— **不生成半成品**（一个挂不上东西的接口，编译得过、一个信号都不采）。
    """
    meta = cov_interface_meta(cm, sampling, if_name, extra_signals=extra_signals,
                              tp_bitmap_width=tp_bitmap_width)
    if meta is None:
        return ""
    cps = probe_ports(cm)
    name, dut = meta["name"], meta["dut_module"]
    macro = f"{name.upper()}_SV"

    # 端口 = 时钟 + 复位 + 每个采样信号。**时钟与复位也必须是端口**：
    # 它们同样活在 DUT 的作用域里，裸写在组件里没人连得过来（探针那边为同一个
    # 原因吃过一次亏：`if (rst_n)` 直接报 `Undefined variable`）。组件靠这三个
    # 端口时钟沿采样 + 复位屏蔽。
    extra_ports = [meta["clock"]] + ([meta["reset"]] if meta["reset"] else [])

    out: List[str] = [
        f"`ifndef {macro}",
        f"`define {macro}",
        "",
        "// 覆盖率采样接口 —— 由 case/覆盖率模型生成（casemodel_tools.coverage）",
        f"// `bind` 到 `{dut}`：端口连接表达式在该模块作用域里求值，",
        "// 所以输入端口 / 输出端口 / **内部寄存器** 一视同仁地连得进来。",
        "//",
        "// 它只**引信号**，不采样 —— 采样由 env 的覆盖率组件做（`coverpoint vif.<信号>`，",
        "// 时钟沿 + 复位屏蔽），这样覆盖率跟着 UVM 的报告走。",
        "//",
        f"// bind 出来的实例是 `{meta['instance']}`，它在 DUT 的作用域里 —— 所以",
        f"// tb_top 用层次路径挂给组件：`config_db::set(..., <dut 实例>.",
        f"// {meta['instance']})`。两边的名字都来自同一份 meta（`cov_interface_meta`）。",
        "",
        f"interface {name} (",
    ]
    # ⚠️ **必须是端口，不能是接口体内的变量**：`bind` 的 `.sig(expr)` 连的是
    # **被绑模块的端口**。写成 `interface X(); logic sig; endinterface` 时 vlog
    # **照样报 `Errors: 0`**（它压根不查 bind 的连接），要到 `vopt` 才报
    #     (vopt-2912) Port 'sig' not found in module 'X'
    # —— 所以这一层的验证**必须用 vopt，不能用 vlog**（实测踩过）。
    #
    # 一律 `input`：接口只**观察** DUT —— 输入端口是被驱动的网、输出端口也是，
    # 都只读一份值。声明成 `output` 会反过来去驱动 DUT。
    ports = [(n, 0, "") for n in extra_ports] + \
            [(cp.signal, cp.width, cp.field) for cp in cps] + \
            [(e["name"], e["width"], "") for e in meta.get("extra_signals") or []]
    for i, (sig, width, note) in enumerate(ports):
        decl = f"[{width - 1}:0] " if width > 1 else ""
        sep = "," if i < len(ports) - 1 else ""
        # 注释只在"建模里的名字与信号名不同"时才写 —— `// queue_level` 这种
        # 自己注释自己没有信息量（单模型路径下两者本来就同名）
        comment = f"  // {note}" if note and note != sig else ""
        out.append(f"  input logic {decl}{sig}{sep}{comment}")
    out.append(");")
    # `tp_seen` 是**接口体内的变量**，不是端口：它不来自 DUT，而是 env 覆盖率
    # 组件在本拍仓命中时置位。打开波形（visualizer -wavefile）就能看到
    # "第 i 位 = 第 i 条测试点在本拍/之前命中过"。位序见
    # `coverage/tp_bitmap.json`（一旦发布不重排）。
    width = int(meta.get("tp_bitmap_width") or 0)
    if width > 0:
        out += [
            "",
            f"  // 测试点位图（位序 = coverage/tp_bitmap.json 的 entries[].bit）",
            f"  logic [{width - 1}:0] tp_seen;",
        ]
    out += [
        f"endinterface : {name}",
        "",
        f"bind {dut} {name} {meta['instance']}(",
    ]
    conns = [f"  .{n}({n})" for n in extra_ports]
    conns += [f"  .{cp.signal}({cp.expr or cp.signal})" for cp in cps]
    conns += [f"  .{e['name']}({e['name']})"
              for e in meta.get("extra_signals") or []]
    out.append(",\n".join(conns))
    out += [");", "", f"`endif  // {macro}", ""]
    return "\n".join(out)
