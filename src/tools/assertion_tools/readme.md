# 断言工具集 (assertion_tools)

生成 SVA 断言、形式验证属性和 CDC 检查的工具集。

## Functions
- `generate_sva_assertions(specs)`: 生成 SVA 断言
- `generate_immediate_assertions(specs)`: 生成立即断言
- `generate_concurrent_assertions(specs)`: 生成并发断言
- `generate_formal_properties(specs)`: 生成形式验证属性
- `generate_cdc_assertions(specs)`: 生成 CDC 检查
- `generate_cover_properties(specs)`: 生成覆盖属性
- `generate_assertion_package(specs)`: 生成断言包
- `analyze_assertion_coverage(data)`: 分析断言覆盖率

## Class
- `AssertionTools`: LangChain Agent 使用的工具集类

## Consumed By
- `AssertionEngineer` agent

## Test
```bash
pytest src/tools/assertion_tools/ -v
```
