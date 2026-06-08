# 覆盖率管理器 (coverage_manager)

收集和分析代码及功能覆盖率。

## Pipeline Role
- **Phase**: cover
- **Task Type**: coverage_analysis
- **Consumes**: spec, regression
- **Produces**: coverage

## Features
- 代码覆盖率收集
- 功能覆盖率分析
- 覆盖率报告生成
- 覆盖率缺口识别

## Usage
```python
from src.agents.coverage_manager import CoverageManager
agent = CoverageManager()
await agent.initialize()
result = await agent.execute_task({"input": coverage_data, "bypass": True})
```

## Test
```bash
pytest src/agents/coverage_manager/ -v
```
