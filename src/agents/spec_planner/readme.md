# 规格与测试规划师 (spec_and_test_planner)

分析设计规格文档，生成验证测试计划。

## Pipeline Role
- **Phase**: spec
- **Task Type**: spec_analysis
- **Consumes**: (none)
- **Produces**: spec

## Features
- 规格文档解析与特征提取
- 接口信号识别与分类
- 寄存器 Map 生成
- 测试计划自动生成 (ST/IT/BT 三级)

## Usage
```python
from src.agents.spec_planner import SpecAndTestPlanner
agent = SpecAndTestPlanner()
await agent.initialize()
result = await agent.execute_task({"input": "UART design spec"})
```

## Test
```bash
pytest src/agents/spec_planner/ -v
```
