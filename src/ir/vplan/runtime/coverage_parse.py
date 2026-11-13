"""覆盖率解析 —— 从已有 SV / 清单里读回覆盖率模型。

VPlan 运行期模型的覆盖率解析；只做解析，不渲染。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from .coverage_model import (
    CoverBin, CoverPoint, CoverageModel, CrossBin, CrossPoint, _as_int,
    _derive_width, _derive_width_from_bins, _opt_int, _slug, sv_ident,
)
from .domain import token_of

def parse_coverage_model(coverage_yaml: str, case_model: "CaseModel" = None,
                         notes: List[str] = None) -> CoverageModel:
    """**独立的覆盖率模型 yaml** → `CoverageModel`。

    ## 它和 case 模型是两份、不是一份

    case 模型答"该测什么"（维度/取值/专题），覆盖率模型答"**怎么量**"
    （coverpoint / bin / cross）。分开的好处是改一边不动另一边；代价是
    **它们之间必须靠引用对齐** —— 见 `run_associate` 的五条关联边
    （①②③④ 走 bin 名/矩阵键/端口/方法，⑤ 走 dimension ID）。

    ## 为什么这个函数**需要 case 模型**（不是可选装饰）

    `case_model` 那一边的取值是**符号**（`MAC` / `首拍`），而 SV 的 `bins` 只能收
    **整型字面量**（`bins x = {MAC};` 只在 `MAC` 是该作用域的枚举常量时才合法，
    而生成器不知道对方的类型）。所以取值要走**下标投影**（与 `api._int_value_of`
    同一套）—— 而"`MAC` 是第几个"只有 case 模型的 `values:` 说得清。

    **不给 case 模型就投影不了**：那些 bin 会保留符号、`literal()` 给不出合法字面量。
    这时**记账**（`notes`）并继续 —— 覆盖率模型本身仍然可读、可校验关联，
    只是暂时渲染不成 SV。这不是"降级"，是"还差一份输入"。

    `cover_bins` / `cross_matrix` 在 case 模型那边是**引用**，在这里是**定义** ——
    这正是三层模型的核心分工：**引用与定义分开，靠名字对齐**。
    """
    import yaml as _yaml

    notes = notes if notes is not None else []
    try:
        data = _yaml.safe_load(coverage_yaml) or {}
    except _yaml.YAMLError as exc:
        notes.append(f"覆盖率模型 YAML 解析失败: {exc}")
        return CoverageModel(module="", covergroup="")

    mod = data.get("module") or {}
    module = sv_ident(mod.get("name") or "dut", "dut")
    cm = CoverageModel(module=module, covergroup=f"cg_{module}",
                       object_ref=str(mod.get("object_ref") or "").strip())

    for item in (data.get("coverpoints") or []):
        if not isinstance(item, dict):
            continue
        cp = _parse_coverpoint(item, case_model, notes, cm.errors)
        if cp is not None:
            cm.coverpoints.append(cp)

    names = {cp.cp_name or cp.signal for cp in cm.coverpoints}
    for item in (data.get("crosses") or []):
        if not isinstance(item, dict):
            continue
        cx = _parse_cross(item, cm, names, notes, cm.errors)
        if cx is not None:
            cm.crosses.append(cx)

    if not cm.object_ref:
        notes.append("覆盖率模型没有 `module.object_ref` —— 关联不到 case 模型的 L1 对象"
                     "（`run_associate` 的第一条边查的就是它）")
    # **别把 notes 丢了**：解析过程中攒的是本地 list，不回填的话
    # 「大小写不一致」这类提醒一条都到不了调用方（实测：notes 恒为 0）。
    cm.notes.extend(notes)
    return cm


def coverage_model_to_dict(cm: "CoverageModel") -> Dict[str, Any]:
    """`CoverageModel` → `parse_coverage_model` 认的形状（**互为逆**）。

    ## 为什么需要它

    覆盖率模型有两条来路：

        CLI / 人写    coverage.yaml 文本  → `parse_coverage_model`
        流水线        case 模型 → `coverage_model()` 直接得到对象（**没有文本**）

    而 `associate`（三模型关联校验）吃的是**文本**。流水线里因此跑不了关联校验 ——
    于是 `env/cons/` 与覆盖点之间的断点只活在终端上，进不了签核材料。
    本函数给那条路补上"对象 → 文本"这一步。

    ## 与解析侧**必须一一对应**

    字段名对不上就是静默丢东西（解析方 `item.get("name")` 拿到 `None` → 跳过该条，
    而调用方以为"关联通过"）。所以两个函数**放在同一个文件里紧挨着** —— 改一边
    时另一边就在眼前。有测试钉住往返（`test_coverage.py`）。
    """
    return {
        # 解析侧读 `data["module"]["name"]` —— **dict 不是字符串**（实测踩过：
        # 直接喂 `as_dict()` 的 `module` 字符串会 AttributeError）
        "module": {"name": cm.module, "object_ref": cm.object_ref},
        "coverpoints": [
            # 解析侧取 `name`（覆盖点名），而 `as_dict()` 那边叫 `cp_name`
            {"name": cp.sv_name, "signal": cp.signal, "dimension": cp.dimension,
             "cover_id": cp.cover_id, "requirement": cp.requirement,
             "bins": [b.as_dict() for b in cp.bins],
             "illegal_bins": [b.as_dict() for b in cp.illegal_bins]}
            for cp in cm.coverpoints],
        "crosses": [
            # 解析侧读 `cross`（**覆盖点名列表**）来定位交叉的两侧 ——
            # 少这一项的话 `_parse_cross` 直接判"少于两项"跳过，
            # 往返回来 crosses 从 7 变成 0（实测），而调用方看到的是
            # "交叉一条都没有"这种像是模型问题、其实是序列化漏字段的现象。
            {"name": cx.name, "cross": list(cx.refs),
             "matrix_ref": cx.matrix_ref,
             "cover_id": cx.cover_id, "requirement": cx.requirement,
             "dimensions": list(cx.dimensions), "level": cx.level}
            for cx in cm.crosses],
    }


def _parse_coverpoint(item: Dict[str, Any], case_model: "CaseModel",
                      notes: List[str], errors: List[str]) -> Optional[CoverPoint]:
    signal = sv_ident(item.get("signal"), "")
    if not signal:
        notes.append(f"覆盖点条目缺 `signal` —— 跳过（{item!r}）")
        return None
    name = str(item.get("name") or "").strip()
    # 字段靠 **bin 名**关联（不是 signal —— 见 `_find_field` 的 docstring）
    bin_names = [str(b.get("name") or "") for b in (item.get("bins") or [])
                 if isinstance(b, dict)]
    fld = _find_field(case_model, bin_names)
    # **显式写了 `dimension:` 就以它为准**，按 bin 名查到的只是兜底。
    #
    # 为什么必须这样：**不同维度的 bin 名可以完全相同** —— npu_sched 里
    # `D_type.instr_type` 与 `D_unit.issue_unit` 的 `cover_bins` 都是
    # `[mac, vector, scalar, dma]`，而 `_find_field` 按名字交集只返回**第一个**
    # 匹配。于是 `issue_unit` 这个覆盖点被判成 `D_type`（实测），
    # 而后果是 `associate` 边 ⑤ 报"`D_unit` 没有 coverpoint"——那是一条
    # 指向错误方向的告警（它让作者去查覆盖率模型，真凶是这里的歧义）。
    # 作者在 yaml 里写下的 `dimension` 是**权威声明**，优先级必须高于猜。
    explicit_dim = str(item.get("dimension") or "").strip()
    dim_key = explicit_dim or (fld.dim_key if fld is not None else "")
    if case_model is not None and fld is None:
        notes.append(f"覆盖点 {name or signal} 的 bin（{'、'.join(bin_names[:3])}"
                     f"{'…' if len(bin_names) > 3 else ''}）在 case 模型里"
                     f"**没有任何字段的 cover_bins 认领** —— ① 号关联断了"
                     f"（取值投影不了，只能给 0）")

    bins: List[CoverBin] = []
    used: set = set()
    for b in (item.get("bins") or []):
        if not isinstance(b, dict):
            continue
        cb = _parse_bin(b, fld, notes, name or signal, case_model, used, errors)
        if cb is not None:
            bins.append(cb)
    if not bins:
        notes.append(f"覆盖点 {name or signal} 一个 bin 都没有 —— 不出 coverpoint")
        return None
    # **默认 `dut`，与 case 模型那条路相反** —— 两个产物的性质不同：
    #   · case 模型的字段 → 事务字段（agent 采），所以那边默认 `stimulus`
    #   · 覆盖率模型的 `signal` 是 **DUT 的信号名**（`instr_type` / `queue_level`），
    #     端口与内部一视同仁地只有从 DUT 里才看得见
    # 想采事务字段（信号恰好也是 agent 的 transaction var）就显式写 `sample: stimulus`。
    source = str(item.get("sample") or "dut").strip().lower()
    if source not in ("dut", "stimulus"):
        notes.append(f"覆盖点 {name or signal} 的 `sample: {source}` 不认识 —— "
                     f"按 `dut` 处理（只有 `dut` / `stimulus` 两种）")
        source = "dut"
    # 位宽从**关联到的 case 字段**推（`_derive_width` 同一条）—— 覆盖率模型自己
    # 不写位宽（它写的是"采哪个信号"，位宽是那个信号的事）。推不出来的退到
    # bin 内容能容纳的位数，再退到 1 位。
    # 显式 `width` 优先：覆盖率模型认识的信号，位宽是**那个信号的事实**，不是
    # 从 bin 内容推出来的（`instr_opcode` 有 10 个取值 → 推出 4 位，而 DUT 端口
    # 是 8 位 —— vopt 报 "Connection width does not match"，而 vlog 不报）。
    explicit_w = item.get("width")
    if isinstance(explicit_w, int) and explicit_w > 0:
        width = explicit_w
    elif fld is not None:
        width = _derive_width(fld, bins)
    else:
        width = _derive_width_from_bins(bins)
    return CoverPoint(signal=signal, field=fld.name if fld is not None else signal,
                      dimension=dim_key, type=fld.type if fld is not None else "",
                      cp_name=name, bins=bins, source=source, width=width)


def _parse_bin(item: Dict[str, Any], fld, notes: List[str], where: str,
               case_model, used: set, errors: List[str]) -> Optional[CoverBin]:
    """一个 bin 条目 → `CoverBin`。三种内容：`values`（一个或多个）/ `ranges`。"""
    name = sv_ident(item.get("name"), "")
    if not name:
        notes.append(f"{where}：有个 bin 没有合法的 name —— 跳过（{item!r}）")
        return None
    if name in used:
        notes.append(f"{where}：bin 名 {name} 重复 —— 跳过（bins 重定义编译不过）")
        return None
    used.add(name)

    raw_vals = item.get("values")
    if raw_vals is None and item.get("value") is not None:
        raw_vals = [item["value"]]
    if raw_vals is not None:
        vals = raw_vals if isinstance(raw_vals, list) else [raw_vals]
        projected = [_project(v, fld, notes, where, case_model, errors) for v in vals]
        # **有一个解析不出来就整个 bin 丢掉** —— 半个 bin 收的是错的取值
        if any(v is None for v in projected):
            used.discard(name)
            return None
        if len(projected) == 1:
            return CoverBin(name=name, value=projected[0], token=str(vals[0]))
        return CoverBin(name=name, values=projected,
                        token=",".join(str(v) for v in vals))

    rngs = item.get("ranges") or ([item["range"]] if item.get("range") else None)
    if rngs:
        r = rngs[0]
        if not isinstance(r, (list, tuple)) or not r:
            notes.append(f"{where}：bin {name} 的 ranges 形状不对 —— 跳过（{item!r}）")
            return None
        lo = _opt_int(r[0])
        hi = _opt_int(r[1]) if len(r) > 1 else None
        if lo is None:
            notes.append(f"{where}：bin {name} 的区间下界不合法 —— 跳过")
            return None
        return CoverBin(name=name, lo=lo, hi=hi,
                        token=f"{lo}:{'$' if hi is None else hi}")
    notes.append(f"{where}：bin {name} 既没有 values 也没有 ranges —— 跳过")
    return None


def _project(v: Any, fld, notes: List[str], where: str, case_model,
             errors: List[str]) -> Optional[int]:
    """取值 → 整型字面量。数字直接用；符号去 case 模型的 `values:` 里查下标。

    三级匹配，**逐级放宽、每级都说出来**：

      1. **原样相等** —— 正常情况。
      2. **大小写无关** —— `Vector` 与 `VECTOR` 是同一个取值，按它匹配；
         但**记一条 note**：两份文件对同一个东西拼写不一致，是维护隐患。
      3. **对不上** —— 进 `errors`，**不默默给 0**。

    第 3 条为什么不能退化成 0：`bins x = {0};` 生成得出来、编译得过、跑得动，
    但它收的是**另一个取值**。于是覆盖率数字是错的 —— 比"生成不了"坏得多。

    跨语言尤其不能猜：case 模型写 `无依赖`、覆盖模型写 `NONE`，机器无从知道
    它们是一回事（实测：手写的两份样例就是这样）。**报出来让人显式对齐**。
    """
    text = str(v).strip()
    try:
        return int(text)
    except (TypeError, ValueError):
        pass
    if fld is not None:
        tokens = [str(token_of(c)) for c in fld.values]
        for i, tok in enumerate(tokens):
            if tok == text:
                return i
        low = text.casefold()
        for i, tok in enumerate(tokens):
            if tok.casefold() == low:
                notes.append(f"{where}：case 模型写 {tok!r}、覆盖模型写 {text!r} —— "
                             f"已按大小写无关匹配（第 {i} 个取值），建议两边统一")
                return i
        errors.append(
            f"{where}：取值 {text!r} 在 case 模型的字段 {fld.qualified!r} 里查不到"
            f"（那边的取值是 {tokens}）—— **两份模型对不上**。"
            f"要么把它改成那边的一个取值，要么在 case 模型里补上它")
        return None
    if case_model is None:
        errors.append(f"{where}：取值 {text!r} 是符号，但没有 case 模型可以查它的下标"
                      f" —— 渲染不了（先做 `run_associate` 把两边的名字对上）")
        return None
    errors.append(f"{where}：取值 {text!r} 找不到对应的 case 字段"
                  f"（覆盖点该关联不上任何字段）")
    return None


def _parse_cross(item: Dict[str, Any], cm: CoverageModel, names: set,
                 notes: List[str], errors: List[str]) -> Optional[CrossPoint]:
    refs = [str(x).strip() for x in (item.get("cross") or []) if str(x).strip()]
    name = str(item.get("name") or "").strip()
    if len(refs) < 2:
        notes.append(f"交叉条目 {name or item.get('id')!r} 的 `cross` 少于两项 —— 跳过")
        return None
    unknown = [r for r in refs if r not in names]
    if unknown:
        errors.append(
            f"交叉 {name or item.get('id')} 引用了**不存在的 coverpoint**："
            f"{'、'.join(unknown)}（这份模型里只有 "
            f"{'、'.join(sorted(names))}）—— 要么补一个同名 coverpoint，要么改引用")
        return None
    by_name = {cp.cp_name or cp.signal: cp for cp in cm.coverpoints}
    cps = [by_name[r] for r in refs]
    return CrossPoint(
        name=name or f"cx_{'_'.join(cps[i].signal for i in range(2))}",
        signals=[cp.signal for cp in cps], cp_refs=refs,
        level=str(item.get("level") or "required"),
        dimensions=[cp.dimension for cp in cps],
        cover_id=str(item.get("id") or "").strip(),
        matrix_ref=str(item.get("matrix_ref") or "").strip(),
        source=cps[0].source)


def _find_field(case_model: "CaseModel", bin_names: List[str]):
    """**按 `cover_bins` 的名字**找 case 模型的字段 —— 不是按信号名。

    ## 为什么不能按信号名

    两份模型对**同一件事**用的是不同的名字，而这是**对的**：

        case 模型： fields[].name: 指令类型      ← 建模概念（人可以写中文）
        coverage ： signal: instr_type          ← **实现名字**（DUT 的端口）

    字段名是"建模里管它叫什么"，`signal` 是"在 DUT 里它叫什么" —— 它们**本来
    就不该同名**（实测：手写的两份样例一个中文一个英文，按名字找直接全落空，
    所有取值退化成 0 而**编译不会报错**）。

    ## 真正的桥是 `cover_bins`

    作者在 case 模型的字段上写 `cover_bins: [cp_type_mac, ...]`，在 coverage
    模型的 bin 上写 `name: cp_type_mac` —— **同一个名字**。这就是三层模型里
    「引用与定义分开、靠名字对齐」那条分工，① 号关联边。

    所以：哪个字段的 `cover_bins` 与这个覆盖点的 bin 名**有交集**，就是它。
    """
    if case_model is None:
        return None
    want = {str(n) for n in bin_names if n}
    if not want:
        return None
    for dim in case_model.dimensions:
        for fld in dim.fields:
            if want & declared_bin_names(fld):
                return fld
    return None


def declared_bin_names(fld) -> set:
    """字段声明的**全部仓名** —— 字符串形式与对象形式都认。

    `cover_bins` 有两种写法（见 `Field.named_bins` / `Field.explicit_bins`）：

        cover_bins: [cp_mac, cp_vec]              ← 裸名字
        cover_bins:
          - {name: empty,   at: 0}                ← 对象（自带区间/取值）
          - {name: low,     range: [1, 7]}

    按名字找字段时**两边都得收**。原来这里直接 `set(fld.cover_bins)`：
    对象形式的 `dict` 不可哈希 → `TypeError` 当场崩（npu_sched 那种整份用
    对象形式声明的模型必踩）；就算侥幸不崩，只认字符串也会让这些字段
    **一个覆盖点都匹配不上**，而表现是"关联悄悄少了"。
    """
    out = {str(n) for n in (fld.named_bins() or []) if n}
    for b in (fld.explicit_bins() or []):
        name = b.get("name") if isinstance(b, dict) else None
        if name:
            out.add(str(name))
    return out
