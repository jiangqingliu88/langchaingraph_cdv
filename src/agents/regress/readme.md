# 回归管理器 (regression_manager)

管理回归测试执行和结果分析。

## Pipeline Role
- **Phase**: regress
- **Task Type**: regression_management
- **Consumes**: env, tests
- **Produces**: regression

## Features
- 回归测试执行管理
- QuestaSim / VCS 仿真调度
- 并行回归支持
- 结果收集与分析
- Pass/Fail 报告

## Usage
```python
from src.agents.regression_manager import RegressionManager
agent = RegressionManager()
await agent.initialize()
result = await agent.execute_task({"input": regression_config})
```

## Test
```bash
pytest src/agents/regression_manager/ -v
```
