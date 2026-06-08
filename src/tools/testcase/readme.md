# 测试用例生成工具 (testcase)

从规格 YAML 和约束策略生成 UVM 测试用例。

## Functions (tools.py)
- `parse_test_points(spec_json)`: 解析测试点
- `map_policies_to_tests(input_json)`: 策略到测试的映射
- `build_scenario_yaml(scenarios_json)`: 构建场景 YAML
- `build_priority_rules(policies_json)`: 构建优先级规则
- `generate_test_cases(yaml_spec, output_dir)`: 生成测试用例
- `check_test_coverage(spec_json, scenarios_json)`: 检查测试覆盖

## Generator (generator.py)
- `TestCaseGenerator`: 测试用例生成器，支持矩阵模式和场景模式

## Entry Point
```bash
python -m src.tools.testcase.main ALU_constraint.yaml --all
python -m src.tools.testcase.main ALU_constraint.yaml --scenarios
python -m src.tools.testcase.main ALU_constraint.yaml --test 0
```

## Consumed By
- `TestEngineer` agent

## Test
```bash
pytest src/tools/testcase/ -v
```
