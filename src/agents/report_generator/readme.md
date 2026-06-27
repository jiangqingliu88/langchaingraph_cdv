# 报告生成器 (report_generator)

生成最终验证报告和签核文档。

## Pipeline Role
- **Phase**: report
- **Task Type**: report_generation
- **Consumes**: (none)
- **Produces**: (text chain only)

## Features
- 验证报告自动生成
- 签核文档生成
- 多格式输出支持

## Usage
```python
from src.agents.report_generator import ReportGenerator
agent = ReportGenerator()
await agent.initialize()
result = await agent.execute_task({"input": all_results})
```

## Test
```bash
pytest src/agents/report_generator/ -v
```
