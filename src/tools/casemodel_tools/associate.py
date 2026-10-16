"""**三层模型的关联** —— case / 功能覆盖率 / 约束，三份 yaml 靠**名字**对齐。

## 为什么是"分散引用"而不是一张关联表

关联表（`association.yaml`）看着直观，但它是**第四份真相**：任何一边改了名，
你得记得同时改关联表 —— 而忘了改的那次，**没有任何东西会报**。

分散引用反过来：引用**写在用它的人那一侧**（coverage 里写 `matrix_ref`、
case 里写 `cover_bins`），由本模块做一次三向 join。多出来的引用字段是：
`cover_bins` / `matrix_ref` / `object_ref` / `applies_to` —— **都是作者本来就要写的**
（写 `cover_bins` 的时候他脑子里已经有一个 bin 名了），所以不是额外负担。

## 五条边（都靠名字，不靠位置）

    ① case.field.cover_bins  ──bin 名──►  coverage.coverpoints[].bins[].name
    ② case.cross_matrix 键   ──矩阵键──►  coverage.crosses[].matrix_ref
    ③ 约束.policies[].applies_to ──端口──► 约束.transactions[].name
    ④ case.themes[].method   ──映射──►   约束.combinator / policies
    ⑤ 约束.policies[].dimensions ──维度 ID──► coverage.coverpoints[].dimension

**①② 是硬边**（断了就是"声明的测试点没落成覆盖仓"/"组合关系没被覆盖"）—— `error`。
**③④⑤ 是软边**（激励层没接上）—— `warning`。

## 为什么要有 ⑤（三角形缺的那一边）

前四条只连成一个 **"V"**：case↔coverage（①②）、case↔约束（③④）——
**coverage↔约束之间一条边都没有**。于是"这条策略驱动的维度到底有没有人量它"
没人答得了（③ 只查约束内部，见下面「查不到的那一半」）。

⑤ 用 **dimension ID** 对齐：case 模型的 `dimensions[].id` 是两边共用的命名空间 ——
覆盖率侧写在 `coverpoint.dimension`，约束侧写在 `policy.dimensions`
（由 `build_constraint` 从 `themes[].dimensions` 推，并归一成 canonical key、
把通配 `"*"` 展开成全部维度）。**它不追端口名，改追维度 ID** ——
端口↔信号的对应没有建模，追不了；维度 ID 有。

## 为什么字段名与信号名**不该**一样

    case 模型： fields[].name: 指令类型      ← 建模概念（人可以写中文）
    coverage ： signal: instr_type          ← 实现名字（DUT 的端口）

它们本来就不同名，所以①号边**不能**靠"字段名 == signal"来判 —— 那正是
`parse_coverage_model` 一开始踩的坑（按名字找字段 → 全落空 → 取值全投影成 0，
而编译不报错）。真正的桥是 **`cover_bins` 的名字**。

## 查不到的那一半（诚实标注）

③ 说的是"策略压的端口要有对应 coverpoint"，但**端口名与信号名的对应关系没有建模**
（`transactions[].name` 是 agent 名 `apb_master`，而 coverpoint 的 `signal` 是
`instr_type`）—— 所以这里只查**约束内部**（`applies_to` 是否引用了已声明的
`transactions`），端口↔信号那一半**报不出来**，如实进 `notes`。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

#: 生成方法 → 它在约束层该长什么样。**是映射建议，不是硬判据** ——
#: 约束模型里没有"方法"这个字段，所以只能反着看"声明的方法有没有对应的策略/组合器"。
METHOD_TO_CONSTRAINT: Dict[str, str] = {
    "D": "定向策略（一条策略压住具体取值）+ APPLY_FIRST_MATCH",
    "G": "组合策略 + APPLY_ALL（维度之间两两组合）",
    "SPCL": "专项策略（推边界）+ APPLY_SEQUENTIAL",
    "RND": "加权随机策略 + APPLY_WEIGHTED",
    "RPLY": "回放策略（复用历史激励）",
}


def associate(case_text: str, coverage_text: str,
              constraint_text: str = "") -> Dict[str, Any]:
    """三份 yaml 文本 → 关联表 + dangling 报告。

    返回：`{links, issues, counts, notes, renderable, summary}`。
    `renderable` 为假表示"这组模型渲染不出可信的 SV"（有 error）。
    """
    from .coverage import parse_coverage_model
    from .repository import load_models_from_text

    issues: List[Dict[str, str]] = []
    notes: List[str] = []

    def _add(severity: str, edge: str, subject: str, message: str) -> None:
        issues.append({"severity": severity, "edge": edge,
                       "subject": subject, "message": message})

    # ── 解析 case 模型（两种写法都认：单对象 / `tests:` 列表）──
    try:
        models = load_models_from_text(case_text, source="<cases>")
    except Exception as exc:                        # noqa: BLE001 解析失败要报，不抛
        return {"error": f"case 模型解析失败: {exc}"}
    if not models:
        return {"error": "case 模型里没有任何对象"}
    case = models[0].resolve()

    cov_text = coverage_text
    cov = parse_coverage_model(coverage_text, case)
    for e in cov.errors:
        _add("error", "coverage", "coverage", e)

    # 边 ① ② 查的是"**作者声明了什么**"—— 所以拿**原始 yaml** 里的名字，不拿解析后的。
    #
    # 为什么：解析会把坏条目丢掉（bin 取值解析不了、交叉引用了不存在的 coverpoint），
    # 丢掉之后从产物里就看不见它们了 —— 拿产物去查会得到一串**级联误报**
    # （"case 声明了 6 个矩阵键没人引用"，而真相是"3 个交叉被丢了"）。丢的原因
    # 已经由 `cov.errors` 逐条报了，这里不该再拿它当第二遍证据。
    raw_bins, raw_refs = _raw_coverage(cov_text)

    # ── ① cover_bins ↔ bins.name ──
    field_bins: Dict[str, List[str]] = {}     # 字段 qualified → cover_bins
    for dim in case.dimensions:
        for fld in dim.fields:
            if fld.cover_bins:
                field_bins[fld.qualified] = [str(b) for b in fld.cover_bins
                                             if isinstance(b, str)]
    declared = {b for names in field_bins.values() for b in names}
    got = raw_bins or {b.name for cp in cov.coverpoints for b in cp.bins}

    for fld_q, names in field_bins.items():
        missing = [n for n in names if n not in got]
        if missing:
            _add("error", "①", fld_q,
                 f"字段 {fld_q} 的 `cover_bins` 里有 {len(missing)} 个 bin 名在覆盖率"
                 f"模型里**不存在**：{'、'.join(missing)} —— 这些测试点没落成覆盖仓")
    for extra in sorted(got - declared):
        if field_bins:                            # case 侧一个 cover_bins 都没写时不报
            _add("warning", "①", extra,
                 f"覆盖率模型的 bin `{extra}` 在 case 模型里**没有任何字段认领"
                 f"（没有出现在任何 `cover_bins` 里）—— 它是空转的：声明的覆盖率里"
                 f"有它，但没有测试点负责打它")

    # ── ② cross_matrix 键 ↔ matrix_ref ──
    matrix_keys = sorted((c.get("key") or "") for c in _raw_cross_keys(case_text))
    refs = raw_refs or {cx.matrix_ref for cx in cov.crosses if cx.matrix_ref}
    for ref in sorted(refs):
        if matrix_keys and ref not in matrix_keys:
            _add("error", "②", ref,
                 f"覆盖率模型的交叉引用了 `matrix_ref: {ref}`，但 case 模型的 "
                 f"`cross_matrix` 里**没有这个键**（那边有："
                 f"{'、'.join(matrix_keys)}）")
    for key in matrix_keys:
        if key and key not in refs:
            _add("error", "②", key,
                 f"case 模型的 `cross_matrix` 声明了 `{key}`，但覆盖率模型里"
                 f"**没有任何交叉引用它**（`matrix_ref`）—— 这条组合关系没被覆盖")

    # ── ③④ 约束模型（可选）──
    cons = _parse_constraint(constraint_text) if constraint_text else {}
    if cons:
        ports = {t.get("name") for t in cons.get("transactions", []) if t.get("name")}
        for pol in cons.get("policies", []):
            for port in (pol.get("applies_to") or []):
                if port not in ports:
                    _add("warning", "③", str(pol.get("name")),
                         f"策略 {pol.get('name')} 的 `applies_to` 引用了端口 {port!r}，"
                         f"但 `transactions` 里没声明它（那里有："
                         f"{'、'.join(sorted(p for p in ports if p)) or '无'}）")
        # 方法名从**原始 yaml** 取（不是 resolve 后的）：`build_theme` 会把认不出
        # 的方法**静默归一成空串** —— 从模型上看，`method: NOPE` 与"没写 method"
        # 长得一模一样，于是"作者写错了方法名"这件事永远报不出来。
        # 与边 ①② 同一条规矩：查"作者声明了什么"就读原始声明。
        raw_methods = _raw_methods(case_text)
        for theme_key, m in sorted(raw_methods.items()):
            if not m:
                continue
            if m not in METHOD_TO_CONSTRAINT:
                _add("warning", "④", str(m),
                     f"专题 {theme_key} 的生成方法 {m!r} 没有对应的约束层形态"
                     f"（认得的：{'、'.join(METHOD_TO_CONSTRAINT)}）—— "
                     f"注意 case 模型的解析器会把认不出的方法**静默归一成空**，"
                     f"所以模型上看不出来")
        # ── ⑤ 覆盖率 ↔ 约束（**靠 dimension 对齐**）──
        #
        # 前四条边把三份模型连成一个 "V"：case↔coverage（①②）、case↔约束（④）。
        # **coverage↔约束之间一条边都没有** —— 于是"这条策略驱动的那个维度，
        # 到底有没有人量它"没人答得了（原来的 ③ 只查约束内部，`notes` 里也承认了）。
        #
        # 桥墩是现成的：`class 模型` 的 `dimensions[].id` 两边都在用 ——
        # 覆盖率侧 `coverpoint.dimension`、约束侧 `policy.dimensions`（本文件
        # `build_constraint` 从 `themes[].dimensions` 推的）。同一个 ID 空间。
        #
        # 强度是 **warning**（软边，与 ③④ 同级）：约束是**激励层**，"驱动了没量"
        # 不阻断覆盖率渲染 —— 但要让人知道，否则那条策略就是白写的。
        cov_dims = {cp.dimension for cp in cov.coverpoints if cp.dimension}
        driven: set = set()
        for pol in cons.get("policies", []):
            for dim in (pol.get("dimensions") or []):
                driven.add(dim)
                if dim not in cov_dims:
                    _add("warning", "⑤", str(pol.get("name")),
                         f"策略 {pol.get('name')} 驱动维度 {dim!r}，但覆盖率模型里"
                         f"**没有 dimension 是它的 coverpoint** —— 这条约束驱动的东西"
                         f"没人量（覆盖率里有的："
                         f"{'、'.join(sorted(cov_dims)) or '无'}）")
        # 反向（"有人量、没人驱动"）：只在**给了约束模型**时才查 ——
        # 不给约束模型 = 这一层本来就缺，刷一片警告只会把人练成忽略它。
        for dim in sorted(cov_dims - driven):
            _add("warning", "⑤", dim,
                 f"维度 {dim!r} 有 coverpoint（有人量），但**没有任何策略驱动它** —— "
                 f"随机激励下这个覆盖点大概率扫不到（策略声明在专题的 `dimensions` 上）")
        notes.append("③ 只查了**约束内部**（applies_to 是否引用已声明的 transactions）——"
                     "端口名↔信号名的对应关系没有建模，所以'策略压的端口有没有对应"
                     "coverpoint'这半查不到")
        notes.append("⑤ 是上面那半的**替代问法**：不追端口名（那个没有建模），"
                     "改追 **dimension ID** —— 覆盖率侧 `coverpoint.dimension` 与"
                     "约束侧 `policy.dimensions` 是同一个 ID 空间。")

    return {
        "links": {
            "coverpoints": [_link_row(cp, field_bins) for cp in cov.coverpoints],
            "crosses": [{"name": cx.name, "refs": cx.refs,
                         "matrix_ref": cx.matrix_ref,
                         "resolved": (not matrix_keys) or cx.matrix_ref in matrix_keys}
                        for cx in cov.crosses],
            "methods": [{"theme": t.key, "method": t.method,
                         "constraint_form": METHOD_TO_CONSTRAINT.get(t.method, "")}
                        for t in case.themes if t.method],
        },
        "issues": issues,
        "counts": {
            "case_fields_with_bins": len(field_bins),
            "coverage_coverpoints": len(cov.coverpoints),
            "coverage_bins": len(got),
            "matrix_keys": len(matrix_keys),
            "crosses": len(cov.crosses),
            "error": sum(1 for i in issues if i["severity"] == "error"),
            "warning": sum(1 for i in issues if i["severity"] == "warning"),
        },
        "notes": notes + cov.notes,
        # 有 error 就**不许渲染 SV** —— 那会得到一份看着对、收的是错值的覆盖率模型
        "renderable": not any(i["severity"] == "error" for i in issues),
        "summary": _summary(issues, cov, case),
    }


def _link_row(cp, field_bins: Dict[str, List[str]]) -> Dict[str, Any]:
    """一个覆盖点的关联行：连到哪个 case 字段、那个字段在哪个维度。"""
    owner = next((q for q, names in field_bins.items()
                  if {b.name for b in cp.bins} & set(names)), "")
    return {"coverpoint": cp.sv_name, "signal": cp.signal,
            "bins": [b.name for b in cp.bins],
            "case_field": owner, "dimension": cp.dimension}


def _raw_themes(case_text: str) -> List[Dict[str, str]]:
    """case 模型里每个专题**原样写的**声明（顺序保持 yaml 里的顺序）。

    为什么不能读 `theme.method`：`build_theme` 对认不出的方法返回空串 ——
    `method: NOPE` 与"没写"从模型上看不出区别（实测）。要问"作者声明了什么"，
    就得读原始 yaml。这条规矩在 `associate` 边 ④ 已经吃过一次亏。
    """
    import yaml as _yaml

    try:
        data = _yaml.safe_load(case_text) or {}
    except _yaml.YAMLError:
        return []
    if not isinstance(data, dict):
        return []
    out: List[Dict[str, str]] = []
    for t in (data.get("themes") or []):
        if isinstance(t, dict):
            dims = t.get("dimensions")
            if isinstance(dims, str):
                dims = [dims]
            out.append({
                "key": str(t.get("id") or t.get("name") or "?"),
                "name": str(t.get("name") or ""),
                "method": str(t.get("method") or "").strip(),
                "priority": str(t.get("priority") or "").strip(),
                # **策略要驱动的维度**（`D_queue` 这些 ID）。它是
                # coverage↔constraint 那条边（`associate` 边 ⑤）的**桥墩**：
                # 覆盖率侧 coverpoint 也声明 `dimension`，两边同一个 ID 空间。
                # 读原始 yaml（与 method 同一条规矩）—— 解析后的 `Theme.dimensions`
                # 会丢掉解不出来的引用，而"作者声明了什么"才是要查的。
                "dimensions": [str(d) for d in
                               (dims if isinstance(dims, list) else []) if d],
            })
    return out


def _raw_methods(case_text: str) -> Dict[str, str]:
    """专题 key → 原样写的 `method`（`associate` 边 ④ 用）。"""
    return {t["key"]: t["method"] for t in _raw_themes(case_text)}


def _raw_coverage(text: str) -> Tuple[set, set]:
    """覆盖率模型的**原始声明** → `(所有 bin 名, 所有 matrix_ref)`。

    只回答"作者写了哪些名字"，不管它们能不能解析 —— 见 `associate` 里那段
    「为什么拿原始 yaml」。
    """
    import yaml as _yaml

    try:
        data = _yaml.safe_load(text) or {}
    except _yaml.YAMLError:
        return set(), set()
    if not isinstance(data, dict):
        return set(), set()
    bins = set()
    for cp in (data.get("coverpoints") or []):
        if isinstance(cp, dict):
            for b in (cp.get("bins") or []):
                if isinstance(b, dict) and b.get("name"):
                    bins.add(str(b["name"]))
    refs = {str(c["matrix_ref"]) for c in (data.get("crosses") or [])
            if isinstance(c, dict) and c.get("matrix_ref")}
    return bins, refs


def _raw_cross_keys(case_text: str) -> List[Dict[str, Any]]:
    """case 模型的 `cross_matrix` 键（原样取，不经过 resolve）。

    为什么不用 `model.cross_pairs`：那些是**解析过**的（引用的维度解不出来时
    仍然保留，但本函数要的是"作者写了哪些键"这个事实）。
    """
    import yaml as _yaml

    try:
        data = _yaml.safe_load(case_text) or {}
    except _yaml.YAMLError:
        return []
    if not isinstance(data, dict):
        return []
    # 单对象写法：顶层 `cross_matrix`；多对象写法：共享属性空间，也在顶层
    raw = data.get("cross_matrix")
    if isinstance(raw, dict):
        return [{"key": str(k)} for k in raw]
    if isinstance(raw, list):
        return [{"key": "×".join(str(x) for x in (x.get("pair") or []))}
                for x in raw if isinstance(x, dict)]
    return []


def _parse_constraint(text: str) -> Dict[str, Any]:
    """约束模型的**浅解析** —— 只取关联要用的三个字段。

    **不 import `gen_uvm`**：本包与 `uvm_tools` 之间只是**文件格式契约**（本仓库
    的规矩：工具互不 import）。所以这里自己读那三个键，认不出的原样留着。
    """
    import yaml as _yaml

    try:
        data = _yaml.safe_load(text) or {}
    except _yaml.YAMLError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        "transactions": [t for t in (data.get("transactions") or [])
                         if isinstance(t, dict)],
        "policies": [p for p in (data.get("policies") or []) if isinstance(p, dict)],
        "combinator": data.get("combinator") or {},
    }


def _summary(issues: List[Dict[str, str]], cov, case) -> str:
    errs = [i for i in issues if i["severity"] == "error"]
    if errs:
        return (f"关联有 {len(errs)} 处**断开** —— 这组模型渲染不出可信的 SV"
                f"（首条：{errs[0]['message'][:60]}）")
    return (f"{len(cov.coverpoints)} 覆盖点 / {len(cov.crosses)} 交叉 与 case 模型"
            f"关联完整")


# ════════════════════════════════════════════════════════════
# 约束模型生产者 —— 把 case 模型的「生成方法」落成策略 + 组合器
# ════════════════════════════════════════════════════════════
#
# 方法学的第三条腿：
#
#     case 模型     说「该测什么」    themes[].method   ← 生成方法（D/G/SPCL/RND/RPLY）
#     覆盖率模型    说「怎么量」      coverpoints / bins
#     约束模型      说「怎么驱动」    policies + combinator  ← 本函数产出
#
# **为什么必须有生产者**：`gen_uvm` 那套渲染（策略上下文 / 策略实现 / 组合器 /
# 工厂 / 协调序列）只认约束模型，而约束模型此前只能**手写** —— 手写的那份和 case
# 模型之间没有任何东西保证"专题声明的方法"真的落成了策略。写了 `method: G`，
# 约束层可以一条组合策略都没有，而**两边的 yaml 都自洽、都解析得过**。这条边
# （④）此前只能靠 `associate` 事后报，现在能生成，就能保证它从一开始就接上。

#: 生成方法 → `(策略名后缀, 组合器模式)`。
#: **键集必须与 `METHOD_TO_CONSTRAINT` 一致** —— 有单测钉住（漏一个，就等于
#: "这个人读的描述认得它、生产者却映射不出它"）。
METHOD_TO_POLICY: Dict[str, Tuple[str, str]] = {
    "D":    ("directed", "APPLY_FIRST_MATCH"),
    "G":    ("combo",    "APPLY_ALL"),
    "SPCL": ("special",  "APPLY_SEQUENTIAL"),
    "RND":  ("random",   "APPLY_WEIGHTED"),
    "RPLY": ("replay",   "APPLY_SEQUENTIAL"),
}

#: 组合器的 5 个模式 —— **一个都不能少**。那套渲染拿它当 `enum` 的取值表
#: （`env_cons_policy_combinator.j2`），而 `apply()` 里的 `case` 分支是**写死的**
#: 5 个：少任何一个，`case` 就比到未声明的标识符，**vlog 直接报错**（不是"少了
#: 个选项"，是编译不过）。所以这里全列，不按"有没有策略用它"裁剪。
COMBINATOR_MODES: List[str] = ["APPLY_ALL", "APPLY_WEIGHTED", "APPLY_FIRST_MATCH",
                               "APPLY_SEQUENTIAL", "APPLY_CHAIN"]

#: 专题优先级 → 策略 `priority`。不认得的落 `_DEFAULT_PRIORITY`（中间偏后）。
#:
#: 注意那套渲染里 `priority` 是**两用的**：`sort_by_priority` 按它**升序**排
#: （小的先应用 → P0 排最前，对），`select_weighted` 又拿它当**权重**
#: （大的更容易选中）。两个用途方向相反，但 P0 取小值在这两处都不别扭：先应用、
#: 且不主导随机 —— 精确用例本来就不该靠随机加权去撞。
_PRIORITY_OF: Dict[str, int] = {"P0": 10, "P1": 20, "P2": 30,
                                "P3": 40, "P4": 50, "P5": 60}
_DEFAULT_PRIORITY = 50

_HEADER = """\
# ============================================================
# 约束模型 —— **由 case 模型生成**（`vagent case-model constraints`）
# ============================================================
# 来源：case 模型 {source}
#
# 这是**结构骨架**，不是最终约束。case 模型知道的是建模语义（专题 / 维度 /
# 生成方法 / 优先级），不知道协议参数（地址对齐 / 容量 / 握手时序）—— 那些只能
# 由人补。所以每个策略都是**自定义名**（`gen_uvm` 对自定义名生成空 `apply`
# 骨架，语义校验层会提示"待填"），`params` 为空。
#
# 专题 → 策略：{mapping}
#
# **改了 case 模型就重跑本命令**，产物会整体覆盖本文件 —— 所以别在这里手改。
# 协议逻辑写在策略体里（`env/cons/` 下那几个 sv），不在本文件，覆盖是安全的。
#
# 文件放哪：被 `gen_uvm` 扫描的输入路径下都行，**文件名不参与识别** ——
# 认的是顶层有个 `constraint:` 键（`parse_documents`）。
# ============================================================
"""


def theme_policy_map(themes: List[Dict[str, str]]) -> Dict[str, str]:
    """专题 → 策略名（**与 `build_constraint` 逐字同名**）。

    抽出来是因为有两个读者：`build_constraint` 生成 `policies[]` 本体，
    `run_uvm_batches` 把策略名挂进 `batches[]`（批次 test 类 set 给 sequence）。
    **两份各推一次名字就会漂** —— 而漂了的表现最难查：config_db 里那个名字查不到
    策略，factory 静默回退默认组合器，回归照样跑绿，只是约束没生效。

    输入必须是 `_raw_themes` 的产物（作者**原样写的**声明），不是解析后的模型：
    认不出的 `method` 会被 `build_theme` 归一成空串，两者对不上（见 `_raw_themes`）。

    只有**认得的** method 才有条目；没写 method 的专题不在表里 —— 调用方据此
    知道"这一批没有模型给的约束"，而不是拿到一个编出来的名字。

    **查找别名**：另把 `name` 也登记为别名。`build_theme` 在专题没写 `id` 时把
    `id` 填成 `TH-{序号}`，而本表按原样写的 key（=`id or name`）建表 —— 只有
    `name` 的专题两边对不上，别名正好补上那一格。
    """
    ordered = sorted((t for t in themes if t["method"] in METHOD_TO_POLICY),
                     key=_theme_order)
    used: set = set()
    out: Dict[str, str] = {}
    for t in ordered:
        suffix, _mode = METHOD_TO_POLICY[t["method"]]
        name = _policy_name(t["key"], suffix, used)
        out[t["key"]] = name
        if t.get("name"):
            out.setdefault(t["name"], name)
    return out


def build_constraint(case_text: str,
                     ports: Optional[List[Any]] = None) -> Dict[str, Any]:
    """case 模型 → 约束模型（策略 + 组合器）的**骨架**。

    产出正好是 `gen_uvm.parse_constraint_model` 认的形状（顶层 `constraint` /
    `transactions` / `policies` / `combinator`），可以直接喂那套渲染。

    `ports` 是**显式输入**，不从 case 模型推 —— 因为两边说的不是一回事：

        case 模型    维度 / 字段名     「指令类型」「队列水位」      ← 建模概念
        约束模型     transactions     apb_master: APB_master_seq_item ← agent 名 + seq_item 类型

    端口名 ↔ 字段名之间的对应**没有建模**（见模块头「查不到的那一半」），推不出来，
    只能由调用方给。**没有端口就不生成** —— 那不是"生成一个空壳"，是一个真问题：
    `transactions` 为空时协调序列会渲染成**看着像有东西的空壳**
    （`{% for trans in transactions %}` 一次都不进，发送循环体是空的）。

    两种端口写法都收：`{"name": ..., "type": ...}` 与 `"name:type"`。
    """
    from .repository import load_models_from_text

    try:
        models = load_models_from_text(case_text, source="<cases>")
    except Exception as exc:                        # noqa: BLE001 解析失败要报，不抛
        return {"error": f"case 模型解析失败: {exc}"}
    if not models:
        return {"error": "case 模型里没有任何对象"}
    case = models[0].resolve()

    # 维度引用 → **canonical key**（`D_type`）。
    #
    # 专题里的 `dimensions: [指令类型]` 写的是**原始引用**（name 或 id 都行），
    # 而覆盖率侧的 `coverpoint.dimension` 是 `dim.key`（= `id or name`）。
    # 不归一就对不上 —— 实测：专题写 `指令类型`、coverpoint 写 `D_type`，
    # 于是 `associate` 边 ⑤ 把一条明明连上的边报成"没人驱动这个维度"。
    dim_alias: Dict[str, str] = {}
    _all_dims: List[str] = []
    for _d in getattr(case, "dimensions", []) or []:
        _all_dims.append(_d.key)
        for _alias in (_d.key, _d.id, _d.name):
            if _alias:
                dim_alias.setdefault(str(_alias), _d.key)

    def _dim_key(raw: str) -> str:
        """原始引用 → canonical key；**解不出来就原样留着** —— 那样边 ⑤ 会如实
        报"驱动了一个没有 coverpoint 的维度"，比悄悄丢掉它强。"""
        return dim_alias.get(str(raw), str(raw))

    from .domain.vocab import is_wildcard

    def _dim_keys(raw_dims: List[str]) -> List[str]:
        """专题的 `dimensions` → canonical key 列表（**通配要展开**）。

        `dimensions: ["*"]` 在 case 模型里的语义是"**全部维度**"（见
        `Theme.covers_all_dimensions` / `vocab.is_wildcard`）—— 照原样把 `'*'`
        带出去，`associate` 边 ⑤ 就会把所有维度都报成"没人驱动"
        （实测：npu_sched 的 TH-B11 是通配，于是 D_seq/D_priority/D_barrier
        三个维度被误报）。
        """
        out: List[str] = []
        for r in (raw_dims or []):
            out.extend(_all_dims if is_wildcard(r) else [_dim_key(r)])
        seen, uniq = set(), []
        for k in out:
            if k and k not in seen:
                seen.add(k)
                uniq.append(k)
        return uniq

    norm, bad = _norm_ports(ports)
    if bad:
        return {"error": f"端口写法认不出：{'、'.join(bad)} —— 用 "
                         f"`name:seq_item_type`（例如 `apb_master:APB_master_seq_item`）"}
    if not norm:
        return {"error": "没有端口（agent）就不生成约束模型 —— `transactions` 为空时"
                         "协调序列渲染出来是个空壳。用 `--port <name>:<seq_item_type>` "
                         "至少给一个端口"}
    dup = sorted({p["name"] for p in norm
                  if sum(1 for q in norm if q["name"] == p["name"]) > 1})
    if dup:
        return {"error": f"端口名重复：{'、'.join(dup)} —— `transactions` 是模板里"
                         f"逐项展开的，重复会展开两次（同一个 sequencer 出现两遍）"}

    themes = _raw_themes(case_text)
    if not themes:
        return {"error": "case 模型里没有 themes —— 没有专题就没有生成方法，"
                         "约束层无从映射"}

    unknown = [t for t in themes if t["method"] and t["method"] not in METHOD_TO_POLICY]
    if unknown:
        return {"error": "这些专题的生成方法映射不到约束层："
                         + "、".join(f"{t['key']}(method={t['method']})" for t in unknown)
                         + f" —— 认得的：{' / '.join(METHOD_TO_POLICY)}。"
                           "（`case-model associate` 的边 ④ 报的是同一件事："
                           "case 模型的解析器会把认不出的方法**静默归一成空**，"
                           "从解析后的模型上看不出来）"}

    # 按优先级排：P0 在前 → 它同时决定下面 `default_mode` 取谁。
    ordered = sorted((t for t in themes if t["method"]), key=_theme_order)

    # 名字**只从 `theme_policy_map` 来** —— 它同时被 `run_uvm_batches` 用
    #（批次 test 类 set 给 sequence 的就是这个串）。这里再推一次就会漂。
    policy_names = theme_policy_map(themes)
    policies: List[Dict[str, Any]] = []
    mapping: List[Tuple[str, str, str]] = []
    for t in ordered:
        mode = METHOD_TO_POLICY[t["method"]][1]
        name = policy_names[t["key"]]
        policies.append({
            "name": name,
            "description": f"{t['name'] or t['key']}（{t['method']} → {mode}）"
                           f" —— case 模型生成，协议参数待填",
            "priority": _PRIORITY_OF.get(t["priority"], _DEFAULT_PRIORITY),
            # 空的 `params`：**参数是协议知识，模型里没有** —— 编不出来的就留空，
            # 不编（编一个 `align: 4` 出来，人会以为它是从模型推出来的）
            "params": [],
            "applies_to": [p["name"] for p in norm],
            # **这条策略驱动哪些维度** —— 三模型强关联里 coverage↔constraint
            # 那条边的桥墩（`associate` 边 ⑤ 按 dimension 对齐）。它是模型**推得出来**的
            # （专题本来就声明了 dimensions），所以照实带上，不是编的。
            # **归一成 canonical key**：专题写的是原始引用（`指令类型` 也行），
            # 而覆盖率侧 `coverpoint.dimension` 是 `D_type` —— 不归一两条边对不上。
            "dimensions": _dim_keys(t["dimensions"]),
        })
        mapping.append((t["key"], name, mode))

    if not policies:
        return {"error": "case 模型的专题里没有一个声明了生成方法（method）—— "
                         "约束层无从生成。认得的：D（定向）/ G（组合）/ "
                         "SPCL（专项）/ RND（随机）/ RPLY（回放）"}

    # 默认模式取**优先级最高那个专题**的方法：出厂行为要跟最该先测的那批一致。
    # 取最松的（比如一律 APPLY_ALL）会让定向批次在默认配置下不再定向。
    default_mode = mapping[0][2]

    doc = {
        "constraint": {"name": f"{_snake(case.object or 'dut')}_cons"},
        "transactions": norm,
        "policies": policies,
        "combinator": {"default_mode": default_mode, "modes": list(COMBINATOR_MODES)},
    }

    import yaml as _yaml
    body = _yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=100)
    header = _HEADER.format(
        source=(case.object or "?"),
        mapping="、".join(f"{k}→{n}({m})" for k, n, m in mapping))

    skipped = [t["key"] for t in themes if not t["method"]]
    notes = [
        "策略是**结构骨架**：case 模型只有建模语义，没有协议参数 —— 所以 `params` "
        "为空、策略体在 gen_uvm 里落成空 apply 骨架，协议逻辑要人补（补在"
        "`env/cons/` 的策略里，不在这个 yaml）",
        f"`combinator.modes` 五个模式**全列**（不按有没有策略用它裁剪）——"
        f"组合器的 `case` 分支是写死的 5 个，少一个 vlog 就报未声明标识符",
        f"`default_mode` 取**优先级最高**那个专题的方法（{mapping[0][0]} → {default_mode}）",
        "端口（agents）是**人给的**，不是从 case 模型推的 —— 端口名 ↔ 字段名的对应"
        "没有建模，推不出来（`associate` 边 ③ 只查得到约束内部那一半）",
    ]
    if skipped:
        notes.append(f"这些专题没有声明 `method`，不驱动激励、没生成策略："
                     f"{'、'.join(skipped)}")

    return {
        "constraint": doc["constraint"],
        "transactions": norm,
        "policies": policies,
        "combinator": doc["combinator"],
        "constraint_yaml": header + body,
        "mapping": [{"theme": k, "policy": n, "mode": m} for k, n, m in mapping],
        "skipped_themes": skipped,
        "policy_count": len(policies),
        "default_mode": default_mode,
        "notes": notes,
    }


def _theme_order(theme: Dict[str, str]) -> int:
    """按优先级排专题 —— `sorted` 是稳定排序，同优先级的保持 yaml 里的先后。"""
    return _PRIORITY_OF.get(theme.get("priority") or "", _DEFAULT_PRIORITY)


def _norm_ports(ports: Optional[List[Any]]) -> Tuple[List[Dict[str, str]], List[str]]:
    """端口写法归一 → `([{name, type}], [认不出的原样])`。

    收两种：`{"name": "apb_master", "type": "APB_master_seq_item"}` 与
    `"apb_master:APB_master_seq_item"`（命令行那条用后者，手打快）。
    **认不出的原样退回去报** —— 不猜、不跳（跳了就是"给了 3 个端口，生成出来
    2 个"，而没人会去数）。
    """
    out: List[Dict[str, str]] = []
    bad: List[str] = []
    for p in (ports or []):
        if isinstance(p, dict):
            name = str(p.get("name") or "").strip()
            if name:
                out.append({"name": name, "type": str(p.get("type") or "").strip()})
                continue
        elif isinstance(p, str) and ":" in p:
            name, _, typ = p.partition(":")
            if name.strip():
                out.append({"name": name.strip(), "type": typ.strip()})
                continue
        bad.append(str(p))
    return out, bad


def _policy_name(theme_key: str, suffix: str, used: set) -> str:
    """专题 key + 方法后缀 → 策略名（唯一、合法 SV 标识符）。

    重名就加序号：两个专题 slug 撞车（`TH-A` 与 `th-a`）时**不合并** ——
    合并等于悄悄少一个策略。
    """
    base = f"p_{_snake(theme_key)}_{suffix}"
    name, n = base, 1
    while name in used:
        n += 1
        name = f"{base}_{n}"
    used.add(name)
    return name


def _snake(text: str) -> str:
    """任意名字 → `[a-z0-9_]` 且不以数字开头 —— 它要当 SV 标识符。

    **只看 ASCII**：`"指".isalnum()` 是 True（Python 的 `isalnum` 对汉字也返回
    真），放过去就会生成非 ASCII 标识符 —— `gen_uvm` 那边刚为此吃过一次亏
    （模块名成了 `声明`，而 `vlog` 报的是 "Errors: 0"）。
    """
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", str(text))     # NpuScheduler → Npu_Scheduler
    s = "".join(ch.lower() if (ch.isascii() and ch.isalnum()) else "_" for ch in text)
    while "__" in s:
        s = s.replace("__", "_")
    s = s.strip("_")
    if not s:
        return "x"
    return f"x{s}" if s[0].isdigit() else s
