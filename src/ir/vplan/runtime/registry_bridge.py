"""VPlan 运行期模型 → 用例库（`TestcaseRegistry`）—— 把建模结果落成**可跑、可追踪的用例**。

## 为什么需要这道桥

运行期模型建的是"属性空间"，回归跑的是"用例"。中间少一段，两边口径就各说各话：

  · `regression.yaml` 由 `tool_find_spec_yaml::_generate_regression_yaml`
    **从用例库读出来再写**（`TestcaseRegistry.get_priority_order()`）；
  · 而用例库里 `constraints` 这一列**一直是空的** —— 全仓库没有一处调
    `register(..., constraints=...)`。属性组合（哪个维度取哪个值）断在运行期模型
    里，没进库，自然也没进回归声明。

于是"建模声明了 30 个覆盖点"和"回归里跑着 11 条"可以同时成立而没人发现。

## 落进去的粒度：**一个属性取值点 = 一条用例**

与 `api.run_uvm_tests` **严格 1:1**（那个函数也是"一条 = 一个 UVM_TEST = 一个
属性取值"）。两处粒度一致，回归里跑的条数才等于建模里声明的覆盖点数 ——
对不上就说明有东西漏了，这正是要能看出来的。

| 用例库列 | 来自 |
|---|---|
| `name`         | `test_<module>_<dim>_<field?>_<value>`（唯一、稳定、可 diff） |
| `priority`     | **覆盖该维度的最高优先级专题**（P0 压 P1）—— 不是按名字猜的表 |
| `scenario`     | 该专题（谁把这个取值点排进来的）；无专题时记维度 key |
| `constraints`  | `[{dimension, field, value}]` —— 属性组合本身 |
| `coverage_bin` | `<dim>.<field>[<value>]`（与既有的 `rd_burst_len[16]` 同形） |

## 优先级从专题来（这一条替代了硬编码表）

`register_from_spec` 里那张 `("performance", "throughput", "P2", ...)` 是**按名字
猜**的；这里从运行期模型的专题读 —— 建模里说哪个维度属于 P0，回归里就是 P0。
同一取值点被多个专题覆盖时取**最高**的那个（更早该跑）。

模型**没有声明专题**时（示例 `fc_flowcontrol.yaml` 就是），维度全部落到
`DEFAULT_PRIORITY` 并在 `notes` 里记账 —— **不假装有分层**。

## 名字的 ASCII 纪律

用例名会进目录名与脚本名（`TestcaseRegistry._safe_name` 的 docstring），所以
非 ASCII 取值不能直接进名字。中文取值**退化成它的下标** `v0/v1/...` 而**不是**
被 `_safe_name` 抹成空串 —— 后者会让 `无/首拍/尾拍/持续` 四个取值全叫
`case`，四条用例撞成一个名字（静默丢三条）。
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any, Dict, List, Optional

from .domain import CaseModelError, priority_rank
from .repository import load_models_from_text

#: 没被任何专题覆盖的维度落到这一级 —— 且**记账**（见返回值的 `notes`）。
DEFAULT_PRIORITY = "P1"


def _ascii_token(token: Any, index: int) -> str:
    """取值 → 能进名字的 ASCII 片段。非 ASCII 退化成下标，**不抹成空**。"""
    s = re.sub(r"[^0-9A-Za-z]+", "_", str(token)).strip("_")
    return s or f"v{index}"


def _dim_priority(model, dim) -> tuple[str, str]:
    """该维度该用哪个专题的优先级 → `(priority, theme_key)`。

    专题已按优先级排好（loader 的 `sort_themes`：`(rank, id)`），取**第一个**
    覆盖该维度的。`theme.dims` 由 `CaseModel.resolve()` 回填（含通配
    `dimensions` 留空的那些，它们覆盖全部维度）。

    没有任何专题覆盖 → `(DEFAULT_PRIORITY, "")`，由调用方记账。
    """
    for theme in model.themes:
        if any(d.key == dim.key for d in theme.dims):
            return theme.priority, theme.key
    return DEFAULT_PRIORITY, ""


def case_rows(yaml_text: str, module_name: str = "dut", *,
              max_cases: Optional[int] = None) -> Dict[str, Any]:
    """运行期模型 → 用例库的行（**不落库**，纯函数，好测）。

    返回：`{"cases": [...], "count", "total_before_cap", "truncated", "dropped",
            "notes", "uncovered_dimensions"}`；模型坏掉时返回 `{"error", "cases": []}`。
    """
    try:
        models = load_models_from_text(yaml_text, source="<vplan>")
    except CaseModelError as exc:
        return {"error": str(exc), "cases": [], "count": 0}
    if not models:
        return {"error": "运行期模型里没有模型", "cases": [], "count": 0}

    # `resolve()` 才有 `theme.dims`；它对同一模型幂等（各 `_resolve_*` 先清空）。
    model = models[0].resolve()

    notes: List[str] = []
    if not model.themes:
        notes.append(
            f"模型没有声明 themes —— 全部维度落到 {DEFAULT_PRIORITY}，"
            f"优先级不体现分层（补 `themes:` 才能按专题分级）")

    module = str(module_name or "dut")
    cases: List[Dict[str, Any]] = []
    uncovered: List[str] = []
    seen: Dict[str, int] = {}

    for dim in model.dimensions:
        priority, theme_key = _dim_priority(model, dim)
        if not theme_key:
            uncovered.append(dim.key)
        multi_field = len(dim.fields) > 1
        for fi, fld in enumerate(dim.fields):
            for vi, point in enumerate(fld.value_points()):
                parts = [module, dim.key]
                # 单字段维度不塞字段位（多数字段与维度同名，塞了只是噪音）；
                # 多字段维度**必须**塞 —— 否则不同字段的同名取值会撞名
                # （D_res 的「并发数 1」与「总元素数 1」实测会撞）。
                if multi_field:
                    parts.append(f"f{fi}")
                parts.append(_ascii_token(point.token, vi))
                name = _norm_name("_".join(parts))
                if name in seen:
                    # 撞名**不许静默**：改名 + 记账。撞名意味着命名规则没覆盖到
                    # 某种形状，是要修规则的信息，不是要吞掉的小事。
                    seen[name] += 1
                    name = f"{name}_{seen[name]}"
                    notes.append(f"用例名撞车，已加后缀去重：{name}")
                else:
                    seen[name] = 1
                cases.append({
                    "name": name,
                    "purpose": "functional",
                    "scenario": theme_key or dim.key,
                    "priority": priority,
                    "constraints": [{"dimension": dim.key, "field": fld.name,
                                     "value": point.token}],
                    "coverage_bin": f"{dim.key}.{fld.name}[{point.token}]",
                })

    total = len(cases)
    by_priority = Counter(c["priority"] for c in cases)

    # **声明的分级 ≠ 落地的分级**：一个取值点只归**最高**优先级覆盖它的那个专题，
    # 所以低优先级专题可能一个 case 都拿不到 —— 模型里 P0/P3 都声明了，落库却全在
    # P0（实测 apb_uart 就是这样：TH-ERR/TH-RND 两个 P3 专题产出 0 条）。
    # 后果是**分级回归跑到那一级会是空的**，而 `EMPTY` 在门控里是**拦下**（不是通过）。
    # 这条不说出来，就要等跑回归时对着"每级都空"反过来查模型。
    for _p in sorted({t.priority for t in model.themes} - set(by_priority)):
        notes.append(
            f"专题声明了 {_p}，但没有用例落在这一级（该维度已被更高优先级专题"
            f"点名）—— 分级回归跑到 {_p} 会是空的（EMPTY 会拦下整轮）")

    truncated = max_cases is not None and 0 <= max_cases < total
    if truncated:
        # 优先级在前（P0 先保住），同级保持声明顺序 —— 截断结果要能 diff
        order = sorted(range(total), key=lambda i: (priority_rank(cases[i]["priority"]), i))
        keep = sorted(order[:max_cases])
        dropped = [cases[i]["name"] for i in range(total) if i not in set(keep)]
        cases = [cases[i] for i in keep]
        notes.append(f"用例截断到 {max_cases} 条，丢弃 {len(dropped)} 条"
                     f"（优先保留高优先级）；用 max_cases 调整")

    return {"cases": cases, "count": len(cases), "total_before_cap": total,
            "truncated": truncated, "dropped": total - len(cases),
            "priority_counts": dict(sorted(by_priority.items())),
            "notes": notes, "uncovered_dimensions": sorted(set(uncovered))}


def _norm_name(name: str) -> str:
    """复用用例库的名字规整（目录名/脚本名不能含空格与中文）。"""
    from src.knowledge.testcase_registry import TestcaseRegistry
    return TestcaseRegistry._safe_name(name)                     # noqa: SLF001


def register_cases(yaml_text: str, module_name: str = "dut", *,
                   registry: Any = None,
                   db_path: Optional[str] = None,
                   max_cases: Optional[int] = None,
                   rtl_version_no: Optional[int] = None) -> Dict[str, Any]:
    """把行写进用例库。返回 `case_rows` 的结果 + `registered`。

    落点三选一，**优先级 `registry` > `db_path` > 默认库**：

      · `registry=`  调用方已经有一个库句柄（front agent 就有）—— 复用它，
                     不另开一个连接指向同一个文件；
      · `db_path=`   指定库文件；
      · 都不给       用 `TestcaseRegistry` 的默认库（项目根 `.signoffai/` 下的
                     **跨 run 共享库**）—— 与 `_generate_regression_yaml` 读的
                     是同一个库，这样"写的"和"读的"才不会又各开一份真相。

    每条用例都记上 **`module`**（结构化列）与注册时的 **`rtl_version_no`**
    （`None` = 这一轮没有 RTL / 不知道，不编一个 0 出来）。
    """
    out = case_rows(yaml_text, module_name, max_cases=max_cases)
    if out.get("error"):
        return out

    reg, owned = registry, False
    if reg is None:
        from src.knowledge.testcase_registry import TestcaseRegistry
        reg, owned = TestcaseRegistry(db_path), True
    try:
        for c in out["cases"]:
            reg.register(c["name"], purpose=c["purpose"], scenario=c["scenario"],
                         priority=c["priority"], constraints=c["constraints"],
                         coverage_bin=c["coverage_bin"],
                         module=module_name, rtl_version_no=rtl_version_no)
    finally:
        if owned:                     # 借来的句柄不许替人关
            reg.close()
    out["registered"] = len(out["cases"])
    return out
