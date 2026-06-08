# 调试工程师 (debug_engineer)

分析失败测试，定位问题根因。

## Pipeline Role
- **Phase**: debug
- **Task Type**: debug_analysis
- **Consumes**: (none)
- **Produces**: (text chain only)

## Features
- 仿真日志分析
- 波形定位
- 失败根因分析
- 修复建议生成

## Usage
```python
from src.agents.debug_engineer import DebugEngineer
agent = DebugEngineer()
await agent.initialize()
result = await agent.execute_task({"input": log_data, "bypass": True})
```

## Test
```bash
pytest src/agents/debug_engineer/ -v
```
