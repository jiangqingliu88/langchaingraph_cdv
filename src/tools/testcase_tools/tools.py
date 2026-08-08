"""
测试用例工具集 —— 供 TestCaseEngineer Agent 调用

   parse_test_points     — spec JSON → 结构化 test 列表
   map_policies_to_tests — test 分类 → 策略场景映射
   build_scenario_yaml   — 场景 JSON → ALU_constraint.yaml 格式
   build_priority_rules  — 策略列表 → 权重规则
   generate_test_cases   — YAML → SV 测试代码
   check_test_coverage   — 覆盖率检查
"""
import json, yaml, os, tempfile
from datetime import datetime
from pathlib import Path
from typing import Dict

from langchain.tools import tool

# ═══════════════════════════════════════════════════════════
# 分类→策略映射表
# ═══════════════════════════════════════════════════════════
CATEGORY_POLICY_MAP: Dict[str, dict] = {
    "basic_function": {
        "policies": ["precision_consistency", "compute_mode"],
        "mode": "APPLY_SEQUENTIAL", "priority": "P0", "repeat": 5,
    },
    "configuration": {
        "policies": ["precision_consistency", "compute_mode", "data_dependency"],
        "mode": "APPLY_SEQUENTIAL", "priority": "P0", "repeat": 10,
    },
    "error_injection": {
        "policies": ["boundary_overflow", "concurrent_access"],
        "mode": "APPLY_FIRST_MATCH", "priority": "P1", "repeat": 20,
    },
    "corner_cases": {
        "policies": ["boundary_overflow", "mem_capacity", "data_dependency"],
        "mode": "APPLY_WEIGHTED", "priority": "P1", "repeat": 30,
    },
    "stress": {
        "policies": ["mem_capacity", "boundary_overflow", "concurrent_access", "power_performance"],
        "mode": "APPLY_ALL", "priority": "P2", "repeat": 50, "timeout": 7200,
    },
    "concurrent": {
        "policies": ["concurrent_access", "data_dependency"],
        "mode": "APPLY_CHAIN", "priority": "P1", "repeat": 30,
    },
}


@tool("parse_test_points")
def parse_test_points(spec_json: str) -> str:
    """从 spec_planner 输出 JSON 中提取 test_points，返回结构化测试列表"""
    try:
        data = json.loads(spec_json) if isinstance(spec_json, str) else spec_json
    except (json.JSONDecodeError, TypeError):
        return json.dumps({"error": "Invalid JSON input"}, ensure_ascii=False)
    tp = data.get("test_points", data if isinstance(data, list) else [])
    if isinstance(tp, dict):
        tp = [tp]
    result = {"total_categories": 0, "total_tests": 0, "categories": []}
    if isinstance(tp, list):
        for cat in tp:
            tests = cat.get("tests", []) if isinstance(cat, dict) else []
            result["total_tests"] += len(tests)
            result["total_categories"] += 1
            result["categories"].append({
                "category": cat.get("category", "unknown") if isinstance(cat, dict) else str(cat),
                "test_count": len(tests),
                "tests": [{"name": t.get("name", t) if isinstance(t, dict) else str(t),
                           "description": t.get("description", "") if isinstance(t, dict) else ""}
                          for t in tests],
            })
    return json.dumps(result, indent=2, ensure_ascii=False)


@tool("map_policies_to_tests")
def map_policies_to_tests(input_json: str) -> str:
    """将 test_points 按分类映射到 constraint policies，返回场景定义"""
    try:
        data = json.loads(input_json) if isinstance(input_json, str) else input_json
    except (json.JSONDecodeError, TypeError):
        return json.dumps({"error": "Invalid JSON"}, ensure_ascii=False)
    categories = data.get("categories", [])
    available = data.get("available_policies", [])
    scenarios = []
    for cat in categories:
        cat_name = cat["category"]
        mapping = CATEGORY_POLICY_MAP.get(cat_name, CATEGORY_POLICY_MAP["basic_function"])
        # 过滤只保留实际可用的策略
        policies = [p for p in mapping["policies"] if not available or p in available] or mapping["policies"]
        scenario = {
            "name": f"{cat_name}_test",
            "description": f"{cat_name} — {cat['test_count']} 个测试用例",
            "timeout": mapping.get("timeout", 600),
            "combinator_mode": mapping["mode"],
            "policies": policies,
            "priority": mapping["priority"],
            "repeat": mapping["repeat"],
            "source_tests": [t["name"] for t in cat.get("tests", [])],
        }
        scenarios.append(scenario)
    return json.dumps({"scenarios": scenarios}, indent=2, ensure_ascii=False)


@tool("build_scenario_yaml")
def build_scenario_yaml(scenarios_json: str, output_dir: str = "") -> str:
    """将场景 JSON 转为 YAML 并保存到 output_dir/inputs/yaml/（如果提供）"""
    try:
        data = json.loads(scenarios_json) if isinstance(scenarios_json, str) else scenarios_json
    except (json.JSONDecodeError, TypeError):
        return "# Error: Invalid JSON input"
    scenarios = data.get("scenarios", [])
    yaml_data = {
        "env_name": data.get("env_name", "uart_env"),
        "project_name": data.get("project_name", "project"),
        "scenarios": [],
    }
    for s in scenarios:
        entry = {
            "name": s["name"], "description": s.get("description", ""),
            "timeout": s.get("timeout", 600),
            "combinator_mode": s.get("combinator_mode", "APPLY_ALL"),
            "policies": s.get("policies", []),
        }
        if "priority_rules" in s:
            entry["priority_rules"] = s["priority_rules"]
        if "repeat" in s:
            entry["repeat"] = s["repeat"]
        if "params_override" in s:
            entry["params_override"] = s["params_override"]
        yaml_data["scenarios"].append(entry)

    yaml_str = yaml.dump(yaml_data, default_flow_style=False, allow_unicode=True, sort_keys=False)

    # Save to disk if output_dir provided
    if output_dir:
        test_yaml_dir = Path(output_dir) / "inputs" / "yaml" / "agent_test"
        test_yaml_dir.mkdir(parents=True, exist_ok=True)
        save_path = test_yaml_dir / "scenarios.yaml"
        save_path.write_text(yaml_str, encoding="utf-8", errors="replace")

    return yaml_str


@tool("generate_test_cases")
def generate_test_cases(yaml_spec: str, output_dir: str = "output/testcases") -> str:
    """根据场景 YAML 调用 TestCaseGenerator 生成 SV 测试代码。同时保存 YAML 到 inputs/yaml/。"""
    from src.tools.testcase_tools.generator import TestCaseGenerator

    # Save input YAML to inputs/yaml/agent_test/ for traceability
    test_yaml_dir = Path(output_dir) / "inputs" / "yaml" / "agent_test"
    test_yaml_dir.mkdir(parents=True, exist_ok=True)
    (test_yaml_dir / "test_config.yaml").write_text(yaml_spec, encoding="utf-8", errors="replace")

    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8")
    try:
        tmp.write(yaml_spec)
        tmp.close()
        gen = TestCaseGenerator(tmp.name)
        # Write generated test code under output_dir/testcases/
        test_out = str(Path(output_dir) / "testcases")
        return json.dumps(gen.generate_all(test_out), indent=2, ensure_ascii=False)
    finally:
        try: os.unlink(tmp.name)
        except Exception: pass


@tool("check_test_coverage")
def check_test_coverage(spec_json: str, scenarios_json: str) -> str:
    """对比 spec test_points 和生成的场景，检查覆盖率"""
    try:
        spec = json.loads(spec_json) if isinstance(spec_json, str) else spec_json
        sc = json.loads(scenarios_json) if isinstance(scenarios_json, str) else scenarios_json
    except (json.JSONDecodeError, TypeError):
        return json.dumps({"error": "Invalid JSON"}, ensure_ascii=False)
    all_tests = []
    for cat in spec.get("test_points", spec.get("categories", [])):
        for t in cat.get("tests", []):
            all_tests.append({"name": t.get("name", str(t)), "category": cat.get("category", "?")})
    covered = set()
    for s in sc.get("scenarios", []):
        for t in s.get("source_tests", []):
            covered.add(t)
    uncovered = [t for t in all_tests if t["name"] not in covered]
    result = {
        "total_test_points": len(all_tests), "covered": len(covered), "uncovered": len(uncovered),
        "coverage_pct": f"{len(covered)*100//len(all_tests) if all_tests else 0}%",
        "uncovered_items": uncovered, "status": "PASS" if not uncovered else "WARN",
    }
    return json.dumps(result, indent=2, ensure_ascii=False)


@tool("build_priority_rules")
def build_priority_rules(policies_json: str) -> str:
    """根据策略列表生成优先级规则（越高权重越优先）"""
    try:
        data = json.loads(policies_json) if isinstance(policies_json, str) else policies_json
    except (json.JSONDecodeError, TypeError):
        return json.dumps({"error": "Invalid JSON"}, ensure_ascii=False)
    policies = data.get("policies", data if isinstance(data, list) else [])
    rules = []
    for i, p in enumerate(policies):
        rules.append({"policy": p if isinstance(p, str) else p.get("name", str(p)), "weight": max(10 - i, 1)})
    return json.dumps({"priority_rules": rules}, indent=2, ensure_ascii=False)
