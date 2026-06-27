# 测试工程师 (test_engineer)

约束策略→场景映射→SV测试代码→仿真参数一站式生成。

原 `sequence_engineer` + `testcase_engineer` 合并。

## Pipeline Role
- **Phase**: test
- **Task Type**: code_generation
- **Consumes**: spec, env
- **Produces**: tests

## Features
- 约束策略定义 (constraint policies)
- 策略到测试场景映射
- SystemVerilog 测试代码生成
- 仿真参数 (simargs) 生成
- 测试覆盖率检查

## Usage
```python
from src.agents.test_engineer import TestEngineer
agent = TestEngineer()
await agent.initialize()
result = await agent.execute_task({"input": context})
```

## Test
```bash
pytest src/agents/test_engineer/ -v
```
