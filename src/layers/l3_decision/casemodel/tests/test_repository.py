"""repository 层 —— loader（YAML→模型）、case_list（真实 case 读入）、
exporters（属性表→四种格式）、schema_check（原始文档门禁）。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from src.layers.l3_decision.casemodel.analysis import SchemaChecker
from src.layers.l3_decision.casemodel.domain import CaseModelError
from src.layers.l3_decision.casemodel.domain.errors import CaseListError
from src.layers.l3_decision.casemodel.generation import generate
from src.layers.l3_decision.casemodel.repository import load_model, load_model_from_text
from src.layers.l3_decision.casemodel.repository.case_list import (cases_from_text,
                                                            load_cases)
from src.layers.l3_decision.casemodel.repository.exporters import (EXPORT_FORMATS,
                                                            export_cases)

from .conftest import CLEAN, CPU, FC_REAL


def check(checker, data, name="t.yaml"):
    return checker.check_data(data, Path(name))


@pytest.fixture(scope="module")
def checker():
    return SchemaChecker()


@pytest.fixture(scope="module")
def one_dim():
    return {"dimensions": [{"name": "D", "fields": [
        {"name": "f", "type": "enum", "values": ["a"]}]}]}


# ════════════════════════════════════════════════════════════
# loader
# ════════════════════════════════════════════════════════════

@pytest.mark.parametrize("path", CLEAN, ids=lambda p: p.name)
def test_clean_examples_load_and_resolve(path):
    # 示例里 fc_flowcontrol 用的是「tests: 列多个对象」写法 —— 合并体是它的
    # 「一个模型」视图
    from src.layers.l3_decision.casemodel.analysis.multi import merge_models
    from src.layers.l3_decision.casemodel.repository import load_models
    model = merge_models(load_models(path))
    assert model.object and model.dimensions
    assert not model.resolve_report.any


@pytest.mark.parametrize("path", CLEAN, ids=lambda p: p.name)
def test_clean_examples_pass_schema(checker, path):
    assert checker.check_file(path) == []


def test_model_requires_object_and_dimensions(one_dim):
    with pytest.raises(CaseModelError, match="object"):
        load_model_from_text(yaml.safe_dump({"dimensions": one_dim["dimensions"]}))
    with pytest.raises(CaseModelError, match="dimensions"):
        load_model_from_text(yaml.safe_dump({"object": "X"}))
    with pytest.raises(CaseModelError, match="object"):
        load_model_from_text(yaml.safe_dump({**one_dim, "object": [1, 2]}))


def test_loader_rejects_non_mapping_root():
    with pytest.raises(CaseModelError, match="mapping"):
        load_model_from_text("- a\n- b\n")


def test_loader_raises_filenotfound_not_model_error(tmp_path):
    """文件不存在必须是 FileNotFoundError —— 报成「模型无法构建」会误导排查。"""
    with pytest.raises(FileNotFoundError):
        load_model(tmp_path / "nope.yaml")


def test_method_and_check_aliases_normalised():
    model = load_model_from_text(yaml.safe_dump({
        "object": "X", "methods": ["RANDOM", "定向", "G"],
        "checks": ["功能", "CHECK-WBOX", "白盒检查"],
        "dimensions": [{"name": "D", "fields": [
            {"name": "f", "type": "enum", "values": ["a"]}]}]}))
    assert model.methods == ["RND", "D", "G"]
    assert model.checks == ["CHECK-FUNC", "CHECK-WBOX"]


def test_unknown_env_keys_are_kept_for_reporting():
    """未登记的键不静默丢弃 —— 否则配置「看似生效实则失效」。"""
    model = load_model_from_text(yaml.safe_dump({
        "object": "X", "environment": {"defaults": {"rtl_version": "v1", "bogus": 1}},
        "dimensions": [{"name": "D", "fields": [
            {"name": "f", "type": "enum", "values": ["a"]}]}]}))
    assert model.env_unknown_keys == ["bogus"]
    assert "bogus" not in model.case_defaults.environment
    assert model.case_defaults.environment["rtl_version"] == "v1"


def test_linkage_values_backfilled_from_target():
    model = load_model_from_text(yaml.safe_dump({
        "object": "X", "dimensions": [{"name": "D", "fields": [
            {"name": "长度", "type": "set", "values": [1, 8, "MAX"]},
            {"name": "元素数", "type": "linkage", "linked_to": "长度"}]}]}))
    assert model.field("元素数").cover_tokens() == ["1", "8", "MAX"]


def test_cross_matrix_accepts_map_and_list_forms():
    base = {"object": "X", "dimensions": [
        {"name": "A", "fields": [{"name": "fa", "type": "enum", "values": [1]}]},
        {"name": "B", "fields": [{"name": "fb", "type": "enum", "values": [1]}]}]}
    mapped = load_model_from_text(yaml.safe_dump(
        {**base, "cross_matrix": {"A×B": "required"}}))
    listed = load_model_from_text(yaml.safe_dump(
        {**base, "cross_matrix": [{"pair": ["A", "B"], "level": "required"}]}))
    assert mapped.cross_pairs[0].level == listed.cross_pairs[0].level == "required"


def test_derived_cross_groups_from_required_pairs():
    model = load_model_from_text(yaml.safe_dump({
        "object": "X", "cross_matrix": {"A×B": "required"},
        "dimensions": [
            {"name": "A", "fields": [{"name": "fa", "type": "enum", "values": [1]}]},
            {"name": "B", "fields": [{"name": "fb", "type": "enum", "values": [1]}]}]}))
    assert [g.id for g in model.cross_groups] == ["XG-01"]
    assert model.cross_groups[0].source == "derived"


def test_explicit_cross_groups_win_over_derivation(cpu):
    assert {g.source for g in cpu.cross_groups} == {"declared"}


# ════════════════════════════════════════════════════════════
# schema_check
# ════════════════════════════════════════════════════════════

def test_unknown_root_key_is_error(checker, one_dim):
    issues = check(checker, {**one_dim, "object": "X", "widht": 3})
    assert any(i.rule == "unknown_property" and "widht" in i.target for i in issues)


def test_field_type_key_mismatch_is_rejected(checker):
    issues = check(checker, {"object": "X", "dimensions": [
        {"name": "D", "fields": [{"name": "f", "type": "range", "min": 1,
                                  "max": 2, "values": [1]}]}]})
    assert any(i.rule == "forbidden_property" and "values" in i.message
               for i in issues)


def test_only_written_forbidden_keys_reported(checker):
    issues = check(checker, {"object": "X", "dimensions": [
        {"name": "D", "fields": [{"name": "f", "type": "enum", "values": ["a"],
                                  "min": 1}]}]})
    hits = [i for i in issues if i.rule == "forbidden_property"]
    assert len(hits) == 1
    assert "min" in hits[0].message and "max" not in hits[0].message


def test_nested_children_validated_recursively(checker):
    issues = check(checker, {"object": "X", "sub_objects": [
        {"id": "A", "name": "a", "children": [{"id": "B"}]}],   # 子节点缺 name
        "dimensions": [{"name": "D", "fields": [
            {"name": "f", "type": "enum", "values": ["a"]}]}]})
    assert any(i.rule == "missing_required" and "sub_objects[0].children[0]" in i.target
               for i in issues)


def test_theme_requires_priority(checker, one_dim):
    issues = check(checker, {**one_dim, "object": "X",
                             "themes": [{"id": "T", "name": "t"}]})
    assert any(i.rule == "missing_required" and "priority" in i.message
               for i in issues)


def test_theme_cross_group_needs_two_dimensions(checker):
    issues = check(checker, {"object": "X", "cross_groups": [
        {"id": "XG", "dimensions": ["A"]}], "dimensions": [
        {"name": "A", "fields": [{"name": "fa", "type": "enum", "values": [1]}]}]})
    assert any(i.rule == "too_few_items" for i in issues)


def test_non_mapping_root_rejected(checker):
    issues = check(checker, ["a", "b"])
    assert issues and issues[0].rule == "unknown_document_kind"


def test_directory_expansion_is_recursive(checker):
    from src.layers.l3_decision.casemodel.analysis.schema_check import collect_yaml_paths
    from .conftest import EXAMPLES
    found = collect_yaml_paths([EXAMPLES])
    names = {p.name for p in found}
    assert {"cpu_pipeline.yaml", "cpu_pipeline_flawed.yaml",
            "fc_flowcontrol.yaml", "fc_flawed.yaml",
            "fc_real_cases.yaml"} <= names


def test_case_list_is_not_a_model(checker):
    """fc_real_cases.yaml 是 case 列表而不是模型 —— 被拦下是正确行为。

    `cases:` 现在是**合法的模型段**（Case IR 三集合契约），所以这条外部列表
    不再以 `unknown_property` 被拒，而是以"缺必填 dimensions + 不是文档结构"
    被拒 —— 结论不变：它不是一份模型。
    """
    issues = checker.check_file(FC_REAL)
    assert {i.rule for i in issues} >= {"unknown_document_kind", "missing_required"}


# ════════════════════════════════════════════════════════════
# case_list（Repository）
# ════════════════════════════════════════════════════════════

def test_case_list_reads_all_four_shapes(tmp_path):
    one = ("case_id: TC-X-A-D-01\n"
           "theme: TH-1\npriority: P0\n"
           "fields: {指令长度: MAX, 反压模式: 尾拍}\n")
    # ① 单条 mapping
    p1 = tmp_path / "one.yaml"
    p1.write_text(one, encoding="utf-8")
    assert len(load_cases(p1)) == 1
    # ② {cases: [...]}
    p2 = tmp_path / "wrap.yaml"
    p2.write_text("cases:\n  - " + one.replace("\n", "\n    ").rstrip() + "\n",
                  encoding="utf-8")
    assert len(load_cases(p2)) == 1
    # ③ fields 写成 'k=v' 列表
    p3 = tmp_path / "list.yaml"
    p3.write_text("cases:\n  - case_id: TC-X-A-D-02\n"
                  "    fields: ['指令长度=MAX', '反压模式=尾拍']\n", encoding="utf-8")
    assert load_cases(p3)[0].fields == {"指令长度": "MAX", "反压模式": "尾拍"}
    # ④ CSV
    p4 = tmp_path / "cases.csv"
    p4.write_text("case_id,object,sub_object_id,theme,priority,tree_path,method,"
                  "fields,checks,environment\n"
                  "TC-X-A-D-01,X,A,TH-1,P0,'节点/A',D,指令长度=MAX,"
                  "CHECK-FUNC,rtl_version=v1\n", encoding="utf-8")
    c4 = load_cases(p4)[0]
    assert c4.theme == "TH-1" and c4.priority == "P0"
    assert c4.environment == {"rtl_version": "v1"}


def test_case_list_carries_the_new_fields(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("cases:\n  - case_id: TC-CPU-ARB-D-01\n    object: CpuPipeline\n"
                 "    sub_object_id: STG-01a\n    theme: TH-P0-CFG\n"
                 "    priority: P0\n    tree_path: 指令 / 仲裁\n"
                 "    cover_bins: [cp_a]\n    expected_result: 正确\n"
                 "    fields: {f: 1}\n", encoding="utf-8")
    case = load_cases(p)[0]
    assert case.priority == "P0" and case.tree_path == "指令 / 仲裁"
    assert case.cover_bins == ["cp_a"] and case.expected_result == "正确"


def test_case_list_rejects_item_without_id(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("cases:\n  - object: X\n", encoding="utf-8")
    with pytest.raises(CaseListError, match="case_id"):
        load_cases(p)


def test_case_list_rejects_unsupported_suffix(tmp_path):
    p = tmp_path / "c.txt"
    p.write_text("whatever", encoding="utf-8")
    with pytest.raises(CaseListError, match="不支持"):
        load_cases(p)


def test_case_list_missing_file_raises_filenotfound(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_cases(tmp_path / "nope.yaml")


def test_dangling_reference_example_reads(fc):
    """fc_real_cases.yaml 是 FlowControl 的 case 列表，字段名与模型对得上。"""
    cases = load_cases(FC_REAL)
    assert len(cases) == 45
    assert cases[0].fields


# ════════════════════════════════════════════════════════════
# exporters（Strategy）—— 与 case_list 同构，可闭环
# ════════════════════════════════════════════════════════════

def test_four_export_formats_registered():
    assert set(EXPORT_FORMATS) == {"table", "yaml", "json", "csv"}


@pytest.mark.parametrize("fmt", ["yaml", "json", "csv"])
def test_every_machine_format_round_trips_through_case_list(cpu, fmt):
    """生成 → 导出 → 读回，必须无损。这是「落盘 → 回喂核对」的前提。"""
    gen = generate(cpu)
    text = export_cases(gen.cases, fmt, seed=gen.seed)
    hint = f".{fmt}"
    back = cases_from_text(text, hint=hint, source="<roundtrip>")
    assert len(back) == gen.count
    for a, b in zip(gen.cases, back):
        assert a.case_id == b.case_id
        assert a.fields == b.fields
        assert a.theme == b.theme and a.priority == b.priority
        assert a.tree_path == b.tree_path
        assert a.sub_object_id == b.sub_object_id


def test_json_export_contains_meta(cpu):
    gen = generate(cpu, max_cases=5)
    payload = json.loads(export_cases(gen.cases, "json", seed=gen.seed,
                                      truncated=gen.truncated))
    assert payload["seed"] == gen.seed and payload["truncated"] is True
    assert len(payload["cases"]) == 5


def test_table_export_groups_by_theme(cpu):
    gen = generate(cpu, max_cases=8)
    text = export_cases(gen.cases, "table", seed=gen.seed)
    assert "case 属性表" in text and "字段" in text


def test_unknown_format_falls_back_to_table(cpu):
    gen = generate(cpu, max_cases=2)
    assert "case 属性表" in export_cases(gen.cases, "nope")


# ════════════════════════════════════════════════════════════
# 分层边界：本包是纯工具，不许有 LLM 依赖
# ════════════════════════════════════════════════════════════

def test_tool_package_has_no_llm_dependency():
    """工具目录必须能在不装 langchain 的环境里用。

    Agent / LangChain / ToolHub 的包装在 src/executors/verify/casemodel/ ——
    一旦工具里偷偷 import 了 langchain，脚本和别的工具就用不了它了。
    这条靠源码扫描固定，比运行时更难绕过。
    """
    root = Path(__file__).resolve().parent.parent
    offenders = []
    for path in root.rglob("*.py"):
        if "__pycache__" in str(path):
            continue
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith(("import ", "from ")) and "langchain" in stripped:
                offenders.append(f"{path.relative_to(root)}:{lineno}: {stripped}")
    assert not offenders, "工具包不该依赖 langchain：\n" + "\n".join(offenders)


def test_tool_package_does_not_import_the_agent_layer():
    """反向依赖也不行：工具不能 import src/executors 或 ToolHub。"""
    root = Path(__file__).resolve().parent.parent
    offenders = []
    for path in root.rglob("*.py"):
        if "__pycache__" in str(path):
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith(("import ", "from ")) and (
                    "src.executors" in stripped or "tool_hub" in stripped
                    or "tool_protocol" in stripped):
                offenders.append(f"{path.relative_to(root)}:{lineno}: {stripped}")
    assert not offenders, "工具包不该反向依赖 Agent 层：\n" + "\n".join(offenders)


def test_api_is_importable_without_langchain(monkeypatch):
    """运行时验证：api 只吃 YAML 文本、吐 dict，全程不需要 langchain。"""
    import builtins
    real_import = builtins.__import__

    def guard(name, *args, **kwargs):
        if name.split(".")[0].startswith("langchain"):
            raise ImportError(f"api 不该依赖 {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guard)
    from src.layers.l3_decision.casemodel import api
    text = CPU.read_text(encoding="utf-8")
    assert api.run_validate(text)["valid"] is True
    assert api.run_gaps(text)["score"] > 0
    assert api.run_generate(text, max_cases=2)["count"] == 2
