"""裸 spec + dplan 契约 → VPlan 项目骨架（front bootstrap）。

钉住三件事：

1. bootstrap 产出的表能被 `load_project` 原样读回（spec hash 必须对得上，
   Windows 换行也不能让 meta 立刻漂移）；
2. 状态从 `assume` / `planned` 起步 —— 没有执行证据就不冒充 active/covered；
3. 契约/模块/接口计数来自契约本身，不是写死常量。
"""
from __future__ import annotations

import csv
import hashlib
import json

from src.skills.front.vplan import bootstrap_project
from src.layers.l3_decision.vplan import load_project

SPEC_TEXT = """# demo pipeline

demo 是一个两级的流水线，decode 出指令，top 汇总结果。

## 接口
- clk / rst_n
- din[7:0]
"""

CONTRACT = {
    "design_name": "demo",
    "overview": "两级 demo 流水线",
    "interfaces": [
        {"name": "clk", "data_width": 1, "direction": "INPUT"},
        {"name": "rst_n", "data_width": 1, "direction": "INPUT"},
        {"name": "din", "data_width": 8, "direction": "INPUT"},
        {"name": "dout", "data_width": 8, "direction": "OUTPUT"},
    ],
    "architecture": {"top": "demo", "stages": ["decode"],
                     "method": "两级流水线"},
    "modules": [
        {"name": "demo", "level": "top", "function": "汇总 decode 结果",
         "interfaces": [
             {"name": "clk", "data_width": 1, "direction": "INPUT"},
             {"name": "rst_n", "data_width": 1, "direction": "INPUT"},
             {"name": "din", "data_width": 8, "direction": "INPUT"},
             {"name": "dout", "data_width": 8, "direction": "OUTPUT"},
         ],
         "combinational": ["dout = stage_q"],
         "sequential": ["stage_q <= din"]},
        {"name": "decode", "level": "sub", "function": "解析指令",
         "interfaces": [{"name": "din", "data_width": 8,
                         "direction": "INPUT"}],
         "combinational": ["op = din[1:0]"],
         "sequential": ["valid_q <= din[2]"]},
    ],
    "model_contract": {
        "module": "demo",
        "ports": [{"name": "din", "data_width": 8, "direction": "INPUT"}],
        "behaviors": [{"name": "pass_through", "when": "din[2]",
                       "expect": "dout == din", "checks": ["sva"]}],
    },
}


def _rows(path):
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def test_bootstrap_writes_a_loadable_project(tmp_path):
    summary = bootstrap_project(tmp_path, SPEC_TEXT, CONTRACT)

    assert summary["modules"] == 2
    # 2 条功能契约 + 1 条接口组契约（clk/rst_n/din/dout 归组）。
    assert summary["contracts"] == 3
    assert summary["interfaces"] == 4

    proj = load_project(tmp_path)
    # VPlan 的模块规范名 = 项目目录名（run/env/资产都从它派生）。
    assert proj.module == tmp_path.name
    assert proj.dut == tmp_path.name
    assert len(proj.contracts) == 3
    assert len(proj.testpoints) == 2
    assert len(proj.cases) == 2
    assert proj.status_counts == {"assume": 3}
    assert proj.tp_status_counts == {"planned": 2}
    assert proj.case_status_counts == {"planned": 2}


def test_bootstrap_spec_hash_matches_file_bytes(tmp_path):
    bootstrap_project(tmp_path, SPEC_TEXT, CONTRACT)

    prefix = tmp_path.name
    spec_dir = tmp_path / "docs" / "specs"
    meta = json.loads(
        (spec_dir / f"{prefix}_spec_meta.json").read_text(encoding="utf-8"))
    raw = (spec_dir / f"{prefix}.md").read_bytes()
    assert meta["spec_hash"] == hashlib.sha256(raw).hexdigest()
    assert meta["source"] == f"docs/specs/{prefix}.md"

    # 再读一次要过 hash 校验（不触发 spec drift 报错）。
    assert load_project(tmp_path).spec_hash == meta["spec_hash"]


def test_bootstrap_projects_assets_without_evidence(tmp_path):
    bootstrap_project(tmp_path, SPEC_TEXT, CONTRACT)

    prefix = tmp_path.name
    tps = _rows(tmp_path / "docs" / "specs" / f"{prefix}_testpoints.csv")
    assert {row["tp_id"] for row in tps} == {"TP_DEMO_001", "TP_DECODE_001"}
    assert all(row["status"] == "planned" for row in tps)
    assert all(row["contract_id"] for row in tps)

    matrix = _rows(tmp_path / "data" / "contract_matrix" / "func.csv")
    assert [row["contract_id"] for row in matrix] == [
        "C-FUNC-DEMO-001", "C-FUNC-DECODE-002"]
    assert all(row["status"] == "assume" for row in matrix)

    meta = _rows(tmp_path / "data" / "execution_meta.csv")
    assert meta and meta[0]["object"] == tmp_path.name
    dims = _rows(tmp_path / "data" / "dimensions.csv")
    # clk/rst_n 是时钟/复位，不生成激励维度。
    assert {row["field_name"] for row in dims} == {"din", "dout"}
    # 一个字段一个维度：id 重复会让属性测试类撞名（vlog-2426）。
    dim_ids = [row["dimension_id"] for row in dims]
    assert len(dim_ids) == len(set(dim_ids)) == 2
    assert dim_ids == ["D_DIN", "D_DOUT"]

    assertions = _rows(tmp_path / "data" / "assertions.csv")
    assert assertions and assertions[0]["name"] == "pass_through"
    assert "din[2]" in assertions[0]["expr"]

    assert (tmp_path / "cases" / "TC_DEMO_001.yaml").is_file()
    assert (tmp_path / "cases" / "TC_DECODE_001.yaml").is_file()


def test_front_reuses_bootstrap_dplan_sidecar(tmp_path):
    """bootstrap 与执行期必须吃同一份契约，不能再抽一次（否则接口数会漂）。"""
    import shutil

    from src.skills.front.main import _prebuilt_contract

    project = tmp_path / "npu_sched"
    bootstrap_project(project, SPEC_TEXT, CONTRACT)
    run = tmp_path / "run"
    (run / "inputs").mkdir(parents=True)
    shutil.copytree(project, run / "inputs" / "vplan")

    doc = _prebuilt_contract(run)
    assert doc["design_name"] == "npu_sched"
    assert [m["name"] for m in doc["modules"]] == ["demo", "decode"]


def _tables_contract() -> dict:
    from src.skills.front.vplan.validate import FIELDS, TOPICS

    features = [
        {"feature_no": "1", "feature_id": "F-DEMO", "feature_level": "root",
         "parent_feature_id": "-", "feature_l1": "DEMO", "feature_l2": "-",
         "feature_l3": "-", "description": "demo 主功能域",
         "applicable_topics": "|".join(TOPICS)},
        {"feature_no": "1.1", "feature_id": "F-DEC", "feature_level": "leaf",
         "parent_feature_id": "F-DEMO", "feature_l1": "DEMO",
         "feature_l2": "DEC", "feature_l3": "-", "description": "译码",
         "applicable_topics": "接口|数据值域"},
    ]
    contract = dict(CONTRACT)
    contract.update({
        "features": features,
        "requirements": [{"req_id": "R-SPEC-01", "spec_section": "1.3-1",
                          "description": "译码正确", "feature_ids": "F-DEC",
                          "priority": "P0", "notes": ""}],
        "topics": [{"topic": t, "applicability": "applicable",
                    "reason": "bootstrap"} for t in TOPICS],
        "contracts": [
            {"contract_id": "C-IF-HS-001", "category": "接口",
             "content": "din valid/ready 握手", "check_method": "SVA",
             "gate": "契约测试", "spec_ref": "1.3-1",
             "status": "已转 assume", "class": "if", "object": "cmd_if",
             "owner": "dv_if", "p_level": "P0",
             "check_artifact": "spec_if_artifact"},
            {"contract_id": "C-FUNC-DEC-001", "category": "功能",
             "content": "译码结果与 ISA 一致", "check_method": "SCB",
             "gate": "契约测试", "spec_ref": "1.3-1",
             "status": "已转 assume", "class": "func", "object": "功能",
             "owner": "dv_func", "p_level": "P0",
             "check_artifact": "spec_func_artifact"},
        ],
        "testpoints": [{
            "tp_id": "TP_DEC_001", "feature_id": "F-DEC", "topic": "接口",
            "spec_ref": "1.3-1", "contract_id": "C-IF-HS-001",
            "test_point": "din 握手", "stimulus": "din=1",
            "expected": "dout=din", "check_method": "SVA",
            "case_plan": "TC_DEC_001", "priority": "P0",
            "status": "planned", "notes": ""}],
        "cases": [{
            "case_id": "TC_DEC_001", "test_name": "dec_test", "batch": "1",
            "contract_ids": "C-IF-HS-001|C-FUNC-DEC-001",
            "covergroups": "CG_DEC", "checks": "dec_sva|dec_scb",
            "owner": "dv", "status": "planned", "notes": "译码"}],
    })
    contract["_expected_headers"] = FIELDS
    return contract


def test_bootstrap_uses_llm_tables_and_checks_format(tmp_path):
    from src.skills.front.vplan.validate import FIELDS

    contract = _tables_contract()
    project = tmp_path / "demo"
    summary = bootstrap_project(project, SPEC_TEXT, contract)

    assert summary["validation"]["ok"]
    assert summary["features"] == 2 and summary["contracts"] == 3
    assert summary["testpoints"] == 1 and summary["cases"] == 1

    spec_dir = project / "docs" / "specs"
    for name, fields in FIELDS.items():
        with (spec_dir / f"demo_{name}.csv").open(
                encoding="utf-8-sig", newline="") as fh:
            header = next(csv.reader(fh))
        assert tuple(header) == fields, name

    # 契约矩阵按 class 分文件，字段与参考项目一致。
    assert (project / "data" / "contract_matrix" / "if.csv").is_file()
    func = _rows(project / "data" / "contract_matrix" / "func.csv")
    assert func[0]["contract_id"] == "C-FUNC-DEC-001"
    assert func[0]["status"] == "assume"

    proj = load_project(project)
    assert len(proj.contracts) == 3
    assert [tp["tp_id"] for tp in proj.testpoints] == ["TP_DEC_001"]


def test_bootstrap_rejects_broken_references(tmp_path):
    import pytest

    from src.skills.front.vplan import ProjectFormatError

    contract = _tables_contract()
    contract["testpoints"][0]["case_plan"] = "TC_MISSING_001"
    with pytest.raises(ProjectFormatError) as exc:
        bootstrap_project(tmp_path / "demo", SPEC_TEXT, contract)
    assert "未知 case" in str(exc.value)


def test_old_style_features_fall_back_to_a_valid_table(tmp_path):
    """确定性解析的 features 只有 name 没有 feature_id，不能当表用。"""
    contract = dict(CONTRACT)
    contract["features"] = [{"name": "legacy feature", "priority": "P0"}]
    summary = bootstrap_project(tmp_path / "demo", SPEC_TEXT, contract)
    assert summary["validation"]["ok"]
    features = _rows(tmp_path / "demo" / "docs" / "specs" / "demo_features.csv")
    assert features and all(row["feature_id"] for row in features)
    assert features[0]["feature_level"] == "root"
