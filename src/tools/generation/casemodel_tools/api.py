"""工具的程序化接口 —— 吃 YAML 文本、吐 dict。

三个函数覆盖这个工具的全部能力，**零 LLM 依赖**（不 import langchain /
ToolHub）：任何 Python 调用方、脚本、或 Agent 适配器都可以直接用。

    run_validate(yaml_text)                     → JSON Schema 校验结果
    run_gaps(yaml_text, max_cases, cases_text)  → 完备性分析（可选反向核对）
    run_generate(yaml_text, max_cases, seed)    → case 属性表

CLI（cli.py）与 Agent 适配器（src/executors/verify/casemodel/）都走这里 ——
语义只此一份，包装各写各的。这也是「工具目录保持纯净」的落点：
本包不含任何面向 LLM 的代码。

返回值一律是 **dict**（不是 JSON 字符串）：需要字符串的调用方自己 json.dumps，
需要结构化数据的直接用 —— 两边都不用解析自己刚序列化的东西。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from .analysis import analyze
from .analysis.multi import analyze_many, generate_many
from .analysis.issues import count_by_severity
from .analysis.schema_check import SchemaChecker
from .domain import CaseModelError
from .domain.errors import CaseListError
from .repository import load_model_from_text, load_models_from_text
from .repository.case_list import cases_from_text

# 工具名 —— CLI、Agent 适配器、schema.yaml 三处共用同一批名字
TOOL_VALIDATE = "casemodel_validate"
TOOL_GAPS = "casemodel_gaps"
TOOL_GENERATE = "casemodel_generate"
#: 把属性取值摊平成 UVM 能吃的 tests 片段（**一条 = 一个 UVM_TEST**）。
#: 产物是**文本契约**，本工具不 import uvm_tools —— 见 `run_uvm_tests`
TOOL_UVM_TESTS = "casemodel_uvm_tests"
#: 把模型的覆盖点渲染成 SystemVerilog covergroup —— 见 `run_covergroups`。
#: 同样**不进 `TOOL_NAMES`**（那是给 Agent 的三面名单，见上面那段）。
TOOL_COVERGROUPS = "casemodel_covergroups"
#: 生成**一份完整的功能覆盖率计划**（覆盖点 + 批次 + 种子管理 + 需求追溯）。
TOOL_COVERAGE_PLAN = "casemodel_coverage_plan"

#: 三面（LangChain / ToolRegistry / ToolHub）共用的名单。
#: **`run_uvm_tests` 暂时不在里面**：进这个名单就得在 `src/executors/verify/casemodel/`
#: 的 `tool_specs()` 与 langchain 包装里各补一份，否则 `build_casemodel_tools()`
#: 会在 `classes[name]` 上 KeyError（踩过）。它是给人用的（`cli uvm-tests` /
#: `api.run_uvm_tests`），不是给 Agent 用的 —— 要接进 Agent 时再把它加进来，
#: 并同时补另外两面。
TOOL_NAMES = (TOOL_VALIDATE, TOOL_GAPS, TOOL_GENERATE)


def _issue_dicts(issues) -> List[Dict[str, str]]:
    return [{"severity": i.severity, "category": i.category, "rule": i.rule,
             "target": i.target, "message": i.message} for i in issues]


# ════════════════════════════════════════════════════════════
# validate
# ════════════════════════════════════════════════════════════

def run_validate(yaml_text: str) -> Dict[str, Any]:
    """YAML 文本 → JSON Schema 校验结果。

    只回答「文档写对了吗」；引用是否存在、层级是否错位由 run_gaps 回答。
    """
    if not isinstance(yaml_text, str) or not yaml_text.strip():
        return {"valid": False, "error_count": 1, "warning_count": 0,
                "issues": [{"severity": "error", "category": "schema",
                            "rule": "empty_input", "target": "<root>",
                            "message": "yaml_text 为空"}]}
    try:
        data = yaml.safe_load(yaml_text)
    except yaml.YAMLError as exc:
        return {"valid": False, "error_count": 1, "warning_count": 0,
                "issues": [{"severity": "error", "category": "schema",
                            "rule": "yaml_parse_error", "target": "<root>",
                            "message": f"YAML 解析失败: {exc}"}]}

    issues = SchemaChecker().check_data(data, Path("<inline>"))
    counts = count_by_severity(issues)
    return {
        "valid": counts["error"] == 0,
        "error_count": counts["error"],
        "warning_count": counts["warning"],
        "issues": _issue_dicts(issues),
    }


# ════════════════════════════════════════════════════════════
# gaps
# ════════════════════════════════════════════════════════════

def run_gaps(yaml_text: str, max_cases: Optional[int] = None,
             cases_text: Optional[str] = None) -> Dict[str, Any]:
    """YAML 文本 → 全量完备性分析。

    cases_text 给出时追加「模型 vs 实现」反向核对 —— 注意外部核对的缺陷
    不进模型评分（评分必须只是模型的属性，否则换一份 case 列表分数就变）。
    """
    try:
        models = load_models_from_text(yaml_text, source="<inline>")
    except CaseModelError as exc:
        return {"error": str(exc)}

    external = None
    if cases_text:
        try:
            external = cases_from_text(cases_text, hint=".yaml", source="<inline>")
        except CaseListError as exc:
            return {"error": f"外部 case 列表解析失败: {exc}"}

    # 单对象时它就是 analyze()；多对象时按「一套评分 + 每对象一棵树」合并
    result = analyze_many(models, max_cases=max_cases, external=external,
                          external_source="<inline>" if external else "")
    payload: Dict[str, Any] = {
        "object": result.model.object,
        "object_cn": result.model.object_cn,
        "object_count": len(models),
        "score": round(result.score.total, 1),
        "score_breakdown": {name: {"sub": round(sub, 4),
                                   "weighted": round(weighted, 2)}
                            for name, sub, weighted in result.score.rows()},
        "summary": result.summary(),
        "org_tree": result.node_rows(),
        "themes": result.theme_rows(),
        "coverage": [
            {"dimension": d.name, "hit": d.hit_count, "total": d.total,
             "ratio": round(d.ratio, 4),
             "missing": {f.field: f.missing for f in d.fields if f.missing}}
            for d in result.dimension_coverage],
        "issues": _issue_dicts(result.issues),
    }
    if result.external is not None:
        payload["external"] = result.external.to_dict()
    return payload


#: 「结构身份」类规则 —— 维度 id / 字段名这类**全局坐标**撞车的错。
#:
#: 为什么单列一份：JSON Schema 看不见它们（那是**语义**问题，schema 只管
#: 字段类型），只有 `run_gaps` 的规则层能报。而草稿里还有**已知且合理**的
#: error（`case_without_check`：草稿只出骨架，检查项由下游补）—— 把
#: `run_gaps` 的全部 error 都当门槛，草稿就永远写不出去。所以只挑这几条
#: **必须拦住**的。
#:
#: 实测代价：`pwdata` 与 `prdata` 各落一个 `D_DATA` 时 schema 全绿，下游却按
#: (维度, 取值) 展开出**重复测试点**、撞成**同一个 SV 类名** —— 编译期
#: Typedef 重定义 → work 库空 → `vsim` 找不到 top → 覆盖率归零。
IDENTITY_RULE_IDS = ("duplicate_dimension_id", "duplicate_field_name",
                     "unknown_dimension_ref", "unknown_field_ref",
                     "unknown_linkage_ref", "unknown_tree_node_ref",
                     "unknown_theme_ref", "unknown_cross_group_ref")


def blocking_issues(yaml_text: str) -> List[Dict[str, str]]:
    """结构身份类的 error 清单 —— 空列表 = 这份模型可以写盘。

    给「先出草稿、过不了就不写盘」那道闸用（见 front 的 casemodel 段）：
    schema 绿了不代表模型立得住，坐标撞车要到下游才炸，那时已经离现场很远了。
    """
    issues = run_gaps(yaml_text).get("issues") or []
    return [i for i in issues
            if i.get("severity") == "error" and i.get("rule") in IDENTITY_RULE_IDS]


# ════════════════════════════════════════════════════════════
# generate
# ════════════════════════════════════════════════════════════

def run_generate(yaml_text: str, max_cases: Optional[int] = None,
                 seed: Optional[int] = None) -> Dict[str, Any]:
    """YAML 文本 → case 属性表（文档十六节最小字段集 + 专题 / 树路径）。"""
    try:
        models = load_models_from_text(yaml_text, source="<inline>")
    except CaseModelError as exc:
        return {"error": str(exc)}

    # 多对象时每个对象各生成一套（case_id 的 TC-<对象代号>-… 前缀各自独立）
    result = generate_many(models, seed=seed, max_cases=max_cases)
    return {
        "count": result.count,
        "seed": result.seed,
        "driver": result.driver,
        "truncated": result.truncated,
        "dropped": result.dropped,
        "themes_used": result.themes_used,
        "priorities_used": result.priorities_used,
        "methods_used": result.methods_used,
        "notes": result.notes,
        "cases": [c.to_dict() for c in result.cases],
    }


def run_testpoints(yaml_text: str, *, env_name: str = "",
                   agents: Optional[Dict[str, List[str]]] = None,
                   module_name: str = "",
                   max_tests: Optional[int] = None) -> Dict[str, Any]:
    """YAML 文本 → **测试点 IR**（`coverage/testpoints.yaml` 的来源）。

    一条测试点 = 建模 → 激励 → 覆盖仓 → test 类 → 回归级 → 判据的公共主键。
    `agents` 是 `{agent 名: [事务字段名]}`，用来把 `stimulus` 解析到具体 agent
    （不给也能出 TP，只是 `realization.agent` 为空）。

    实现在 `plan.py`（纯函数，零 LLM）；这里只做**门面**，与 api 的其它入口
    放在一起，调用方不用记模块名。
    """
    from .plan import run_testpoints as _impl

    return _impl(yaml_text, env_name=env_name, agents=agents,
                 module_name=module_name, max_tests=max_tests)


def _ascii_key(text: str) -> str:
    """一段文本 → ASCII 标识符片段。

    **故意与 `uvm_tools` 里的同名逻辑各写一份**：本仓库的规矩是工具之间不互相
    import（见 readme 的分层约定）。两边的约定靠**各自的测试**钉住
    （都断言输出全 ASCII、且同一维度给出同一个键），不靠共享代码 ——
    共享代码就等于互相依赖。
    """
    import re as _re
    return _re.sub(r"[^A-Za-z0-9]+", "_", str(text)).strip("_").lower() or "attr"


def _int_value_of(token: str, index: int) -> int:
    """取值的整型投影：本身是数字就用它，否则用它在字段里的下标。

    数字优先是有意的 —— 反压比例 `50` 的机器通道该是 50 而不是「第 3 个取值」，
    消费方（sequence）拿到 50 才谈得上「按比例压」。
    """
    try:
        return int(str(token).strip())
    except (TypeError, ValueError):
        return index


def run_uvm_tests(yaml_text: str, *, dimensions: Optional[List[str]] = None,
                  max_tests: Optional[int] = None) -> Dict[str, Any]:
    """YAML 文本 → `tool_uvm` 的 `environment.tests` 片段。

    **一条 = 一个 UVM_TEST = 一个属性取值**：把模型里每个维度字段的取值点摊平成
    一份列表。产物是**文本**（一段 YAML），不是运行时调用 —— `uvm_tools` 不 import
    本工具，本工具也不 import 它；把这段贴进 env 清单的 `environment:` 下即可。

    `dimensions` 按维度 id / 名称 / key 过滤（不给就是全部维度）。
    `max_tests` 截断时**不静默**：`truncated` / `dropped` / `notes` 都记账，
    且**优先保留边界取值** —— 但边界是**跨维度按声明顺序**挑的，不是集中在某一个
    维度上。所以 `--max-tests 4` 拿到的是「前几个维度各自的边界值」，想只要反压
    比例的四个边界要同时给 `--dimensions D_ratio`。
    """
    try:
        models = load_models_from_text(yaml_text, source="<inline>")
    except CaseModelError as exc:
        return {"error": str(exc)}

    # `tests:` 列了多个对象时，**维度空间是共享的** —— 属性取值空间只有一个，
    # 所以这个列表与对象数无关，取第一个模型（= 共享空间）即可。
    # **必须 resolve**：联动字段（`linkage`）在解析时才展开成取值点，而
    # `plan.build_testpoints` 用的是 resolved 模型。不解析就会两边条数不同，
    # 于是"测试点 63 条 / 属性 test 20 条"，而没有任何地方报错。
    model = models[0].resolve()
    wanted = set(dimensions or ())
    picked: List[Dict[str, Any]] = []

    # **取值点遍历与测试点编号只走 `plan.py` 一处** —— 两处各推一次就会漂，
    # 而漂了的表现是"测试点归因到了另一条用例"这种查不出来的错。
    from .plan import iter_value_points

    for dim, fld, index, point, int_value, tp_id in iter_value_points(model):
        if wanted and not (wanted & {dim.id, dim.name, dim.key}):
            continue
        entry = {
            "dimension": dim.id or dim.name,
            "value": point.token,
            "key": _ascii_key(dim.id or dim.name),
            "int_value": int_value,
            # 测试点主键 —— 生成的 test 类、覆盖仓、回归报告都靠它对齐
            "tp_id": tp_id,
            # 只用于排序，不进 YAML —— schema 是 additionalProperties: false
            "_boundary": bool(point.boundary),
        }
        # 激励通道：维度声明了 `stimulus.field` 就把它一起带出去 —— 生成的
        # 属性 test 会把该字段钉在 config_db 上，master sequence 读它并约束事务。
        # 没有声明 = 观测型维度，条目里就没有 `field`（不写空串，免得下游把
        # 空串当成"已绑定"）。
        drive_field = getattr(dim, "stimulus_field", "") or ""
        if drive_field:
            entry["field"] = drive_field
        # **后门到达**：观测型维度没有输入引脚，测试里用 uvm_hdl_force 写入
        # 内部状态、采完覆盖再 release。路径是模型里的领域知识，原样透传。
        if str(getattr(dim, "realization_kind", "")).lower() == "backdoor":
            path = str(getattr(dim, "realization_path", "") or "").strip()
            if path:
                entry["backdoor_path"] = path
        # **sequence 场景**：场景名给人看，`values` 是逐笔事务取值 ——
        # 只有后者能生成"与其它 test 不同"的激励。没有 values 的 sequence
        # 仍然生成类骨架，但它建立不了可核对的差异（模板里如实标注）。
        if str(getattr(dim, "realization_kind", "")).lower() == "sequence":
            seq_name = str(getattr(dim, "realization_sequence", "") or "").strip()
            if seq_name:
                entry["sequence"] = seq_name
            by_token = getattr(dim, "realization_sequences", {}) or {}
            seq_values = list(by_token.get(str(point.token), []) or [])
            if not seq_values:
                seq_values = list(getattr(dim, "realization_values", []) or [])
            if seq_values:
                entry["sequence_values"] = seq_values
        picked.append(entry)

    total = len(picked)
    truncated = max_tests is not None and 0 <= max_tests < total
    notes: List[str] = []
    if truncated:
        # 边界优先 + 稳定的声明顺序（同 CaseBuilder 的纪律：截断要记账、
        # 结果要能 diff）
        order = sorted(range(total), key=lambda i: (not picked[i]["_boundary"], i))
        keep = sorted(order[:max_tests])
        picked = [picked[i] for i in keep]
        notes.append(
            f"tests 截断到 {max_tests} 条，丢弃 {total - len(picked)} 条"
            f"（优先保留边界取值）；用 --max-tests 调整")

    tests = [{k: v for k, v in entry.items() if not k.startswith("_")}
             for entry in picked]
    return {
        "count": len(tests),
        "total_before_cap": total,
        "truncated": truncated,
        "dropped": total - len(tests),
        "notes": notes,
        "dimensions_used": sorted({t["dimension"] for t in tests}),
        "tests": tests,
        "tests_yaml": yaml.safe_dump({"tests": tests}, allow_unicode=True,
                                     sort_keys=False),
    }


def run_covergroups(yaml_text: str, module_name: str = "dut",
                    extra_signals: List[Dict[str, Any]] = None,
                    tp_bitmap_width: int = 0) -> Dict[str, Any]:
    """YAML 文本 → 功能覆盖率模型 + 可编译的 SystemVerilog covergroup。

    **一条 = 一个覆盖点**：维度归类、字段承载取值、取值点是一个 bin、声明了可
    组合的 `cross_pair` 是一条 `cross`。规则与"为什么这么定"见
    `src/tools/generation/casemodel_tools/coverage.py` 的模块头 —— 那是方法学的唯一出处。

    与 `run_uvm_tests` 是**同一份分母的两面**：
      · `run_uvm_tests` 说"这些取值点各跑一条用例"（激励侧）；
      · 本函数说"这些取值点各收一个 bin"（度量侧）。
    两边都从 `field.value_points()` 派生，所以条数与 bin 数天然对得上 ——
    **对不上就说明有东西漏了**，这正是要能看出来的。

    产物是**文本**（一段 SV），本工具不写盘、不 import 任何 UVM/EDA 工具。
    """
    try:
        models = load_models_from_text(yaml_text, source="<inline>")
    except CaseModelError as exc:
        return {"error": str(exc)}

    from .coverage import (cov_interface_meta, coverage_model, dut_bins,
                           probe_ports, render_covergroup, render_cov_interface,
                           render_probe)

    # `resolve()` 才回填 `cross_pair.dim_a/dim_b` 与联动取值 —— 不解析就少
    # cross、少 bin，而且是**静默**少（见 coverage.py 的 `coverage_model`）。
    model = models[0].resolve()
    cm = coverage_model(model, module_name)
    payload = cm.as_dict()
    # **两条采样通道，两份产物**：事务字段那份给 env_cov 通道（monitor 采），
    # DUT 信号那份给 bind 探针（内部/端口都能采）。模型里没有 `sample: dut`
    # 的字段时 `probe_code` 是空串 —— 那是"不需要"，不是"生成失败"。
    payload["covergroup_code"] = render_covergroup(cm)
    payload["probe_code"] = render_probe(cm, model.sampling)
    payload["probe_ports"] = [cp.signal for cp in probe_ports(cm)]
    payload["sampling"] = dict(model.sampling)
    # DUT 通道的**接口**（env 组件持它采样）与它给组件用的 bins 表。
    # 名字/实例/时钟/复位都从 `cov_interface_meta` 出 —— 一处，见那里的注释。
    # `extra_signals`：断言规则要用、但没被任何覆盖点采的信号（`{name,width}`）。
    # 不引成端口的话，env 检查组读不到它们 —— 那条规则只能被跳过。
    payload["cov_interface"] = cov_interface_meta(
        cm, model.sampling, extra_signals=extra_signals,
        tp_bitmap_width=tp_bitmap_width) or {}
    payload["cov_interface_code"] = render_cov_interface(
        cm, model.sampling, extra_signals=extra_signals,
        tp_bitmap_width=tp_bitmap_width)
    payload["dut_bins"] = dut_bins(cm)
    if probe_ports(cm) and not payload["probe_code"]:
        payload["notes"].append(
            "模型里有 `sample: dut` 的字段，但没有 `sampling.dut_module` —— "
            "生成不出 bind 探针（不知道挂到哪个模块上）。补一段：\n"
            "    sampling:\n      dut_module: <DUT 的模块名>\n"
            "      clock: clk\n      reset: rst_n")
    return payload


def run_coverage_plan(yaml_text: str, module_name: str = "dut") -> Dict[str, Any]:
    """YAML 文本 → **一份完整的功能覆盖率计划**（`plan` dict + `plan_yaml` 文本）。

    **与 case 模型同批产出**：同一个来源、同一时刻生成，所以"覆盖点声明了 12 个、
    回归里只跑了 8 条"这种事能在一张表上直接看出来。

    四张脸各归各的读者（见 `coverage.coverage_plan` 的 docstring）：

        §3 覆盖点      谁在采、采什么、bin 是什么       → 生成 covergroup 的人
        §5 批次        这一批打哪个专题、跑哪个 test    → 回归
        §6 种子管理    这一批跑几条才算数               → 回归
        §8 需求追溯    哪条需求被谁验了                 → 签核的人
    """
    try:
        models = load_models_from_text(yaml_text, source="<inline>")
    except CaseModelError as exc:
        return {"error": str(exc)}

    from .coverage import coverage_model, coverage_plan

    model = models[0].resolve()
    cm = coverage_model(model, module_name)
    plan = coverage_plan(model, cm, module_name)
    return {"plan": plan,
            "plan_yaml": yaml.safe_dump(plan, allow_unicode=True, sort_keys=False),
            **plan["summary"]}


#: 工具名 → 实现，供适配器一次性遍历。
#: 与 `TOOL_NAMES` **必须一致**（有测试钉住）：适配器拿它建三面的工具表，
#: 多一个名字就会在 `classes[name]` 上 KeyError。
RUNNERS = {
    TOOL_VALIDATE: run_validate,
    TOOL_GAPS: run_gaps,
    TOOL_GENERATE: run_generate,
}


def run_uvm_batches(yaml_text: str, module_name: str = "dut") -> Dict[str, Any]:
    """YAML 文本 → `tool_uvm` 的 `environment.batches` 片段（**一条 = 一个批次**）。

    与 `run_uvm_tests` 是**两条平行的路**：

        run_uvm_tests    一条 = 一个**属性取值**（`D_type = VECTOR`）→ `{env}_<dim>_p<val>_test`
        run_uvm_batches  一条 = 一个**批次 / 专题**（`TH-B02 指令类型`）→ `npu_type_test`

    **为什么批次也要有 test 类**：没有它，回归里 `+UVM_TESTNAME=npu_type_test`
    会撞 UVM_FATAL(INVTST) —— 而那条路径被记成 pass（"测试名不存在"也是 exit 0，
    见 `_sim_run_cmd` 的注释）。也就是说：**批次跑不起来，反而看不出来**。

    类体里不铺激励（约束由**模型**给的策略类名指定，本工具只转述），只把"这一批
    打哪几个维度、用什么方法、**用哪个约束策略**"挂上 config_db —— 消费方
    （sequence）读它决定怎么激励。名字取自 `themes[].test`；**改了名字会记账**
    （回归的 `+UVM_TESTNAME` 靠它对齐）。

    `policy` 是从 `theme_policy_map`（`associate`）来的**策略类名**，与
    `build_constraint` 生成的 `policies[].name` 同名 —— 它就是"约束"这件事
    从模型走到 sequence 的那根线。**没有它就退回 plusargs**（`+POLICY_LIST`），
    所以空串不是错误，是"这一批没有模型给的约束"。
    """
    try:
        models = load_models_from_text(yaml_text, source="<inline>")
    except CaseModelError as exc:
        return {"error": str(exc)}

    from .associate import _raw_themes, theme_policy_map
    from .coverage import sv_ident

    model = models[0].resolve()
    # 按**原样写的**声明建表（认不出的 method 会被解析器归一成空，两者对不上）。
    raw_themes = _raw_themes(yaml_text)
    policy_names = theme_policy_map(raw_themes)
    # 作者**声明过的** method（原样）。要拿它判断"说了却没对上策略" ——
    # 解析后的 `th.method` 会把认不出的 method 归一成空串，用那个判就永远判不出来
    # （`method: NOPE` 与"没写"从模型上看不出区别，见 `_raw_themes` 的 docstring）。
    declared: Dict[str, str] = {}
    for _t in raw_themes:
        if _t["method"]:
            declared[_t["key"]] = _t["method"]
            if _t.get("name"):
                declared.setdefault(_t["name"], _t["method"])
    batches: List[Dict[str, Any]] = []
    notes: List[str] = []
    for th in model.themes:
        raw = str(th.test or "").strip()
        if not raw:
            notes.append(f"专题 {th.key} 没写 `test` —— 出不了 test 类，"
                         f"回归里这一批跑不了")
            continue
        name = sv_ident(raw, "")
        if not name:
            notes.append(f"专题 {th.key} 的 test 名 {raw!r} 折不成合法标识符 —— 跳过")
            continue
        if name != raw:
            notes.append(f"专题 {th.key} 的 test 名 {raw!r} 含非标识符字符，"
                         f"已折成 {name}（回归的 +UVM_TESTNAME 要用折后的）")
        policy = policy_names.get(th.key) or policy_names.get(th.name, "")
        said = declared.get(th.key) or declared.get(th.name, "")
        if said and not policy:
            # **声明了 method 却对不上策略** —— 这一批的约束不会生效。说出来，别静默：
            # 静默的表现正是"约束没生效、但回归全绿"。`build_constraint` 那边对同一
            # 件事是直接报错（认不出的 method 拒绝生成），这里只记账不拦 —— 批次 test
            # 本身仍然可跑，只是不带模型给的约束。
            notes.append(f"专题 {th.key} 声明了 method={said!r}，但它没有对应的约束策略"
                         f" —— 这一批的批次 test 不 set 策略名，sequence 会退回默认组合器")
        batches.append({
            "name": name,
            "theme": th.key,
            "dimensions": ",".join(d.id or d.name or d.key for d in (th.dims or [])),
            "method": th.method or "",
            "policy": policy,
            "priority": th.priority or "",
            "checks": ",".join(th.checks or []),
        })

    if not batches:
        return {"error": "模型里没有任何带 `test` 的专题"} if not model.themes else {
            "count": 0, "batches": [], "batches_yaml": "", "notes": notes}

    return {
        "count": len(batches),
        "batches": batches,
        "batches_yaml": yaml.safe_dump({"batches": batches}, allow_unicode=True,
                                       sort_keys=False),
        "notes": notes,
    }
