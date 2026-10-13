"""**三层模型的关联** —— case / 功能覆盖率 / 约束，三份 yaml 靠**名字**对齐。

## 为什么是"分散引用"而不是一张关联表

关联表（`association.yaml`）看着直观，但它是**第四份真相**：任何一边改了名，
你得记得同时改关联表 —— 而忘了改的那次，**没有任何东西会报**。

分散引用反过来：引用**写在用它的人那一侧**（coverage 里写 `matrix_ref`、
case 里写 `cover_bins`），由本模块做一次三向 join。多出来的引用字段是：
`cover_bins` / `matrix_ref` / `object_ref` / `applies_to` —— **都是作者本来就要写的**
（写 `cover_bins` 的时候他脑子里已经有一个 bin 名了），所以不是额外负担。

## 四条边（都靠名字，不靠位置）

    ① case.field.cover_bins  ──bin 名──►  coverage.coverpoints[].bins[].name
    ② case.cross_matrix 键   ──矩阵键──►  coverage.crosses[].matrix_ref
    ③ 约束.policies[].applies_to ──端口──► 约束.transactions[].name
    ④ case.themes[].method   ──映射──►   约束.combinator / policies

**① 和 ② 是硬边**（断了就是"声明的测试点没落成覆盖仓"/"组合关系没被覆盖"）——
`error`。**③ 和 ④ 是软边**（激励层没接上）—— `warning`，而且**只能查到一半**，
见下面「查不到的那一半」。

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

from typing import Any, Dict, List, Tuple

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
        notes.append("③ 只查了**约束内部**（applies_to 是否引用已声明的 transactions）——"
                     "端口名↔信号名的对应关系没有建模，所以'策略压的端口有没有对应"
                     "coverpoint'这半查不到")

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


def _raw_methods(case_text: str) -> Dict[str, str]:
    """case 模型里每个专题**原样写的** `method`（不经过归一）。

    为什么不能读 `theme.method`：`build_theme` 对认不出的方法返回空串 ——
    `method: NOPE` 与"没写"从模型上看不出区别（实测）。
    """
    import yaml as _yaml

    try:
        data = _yaml.safe_load(case_text) or {}
    except _yaml.YAMLError:
        return {}
    if not isinstance(data, dict):
        return {}
    out: Dict[str, str] = {}
    for t in (data.get("themes") or []):
        if isinstance(t, dict):
            out[str(t.get("id") or t.get("name") or "?")] =                 str(t.get("method") or "").strip()
    return out


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
