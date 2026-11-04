# 规格分析工具集 (spec_tools)

分析 IC 设计规格文档，提取关键信息的工具集。

## Functions
- `analyze_specification(spec_text)`: 分析规格文档，提取设计名/接口/特性
- `extract_features(spec_text)`: 提取基本特性列表
- `generate_test_plan(requirements)`: 生成测试计划（ST/IT/BT 三级）
- `assess_risk(spec_analysis)`: 风险评估

## Class
- `SpecAnalysisTools`: LangChain Agent 使用的工具集类

## Usage
```python
from src.tools.checking.spec_tools import analyze_specification, extract_features
result = analyze_specification("UART design spec")
features = extract_features("UART spec")
```

## Consumed By
- `SpecAndTestPlanner` agent

## Test
```bash
pytest src/tools/checking/spec_tools/ -v
```
