# 覆盖率工具集 (coverage_tools)

收集和分析代码及功能覆盖率的工具集。

## Functions
- `collect_coverage(coverage_type)`: 收集覆盖率数据
- `analyze_coverage_gaps(coverage_data)`: 分析覆盖率缺口
- `generate_coverage_report(coverage_data)`: 生成覆盖率报告
- `suggest_coverage_tests(gap_analysis)`: 建议补充测试

## Class
- `CoverageTools`: LangChain Agent 使用的工具集类

## Consumed By
- `CoverageManager` agent

## Test
```bash
pytest src/runtime_plane/tools/checking/coverage_tools/ -v
```
