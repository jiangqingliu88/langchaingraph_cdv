# 断言工程师 (assertion_engineer)

生成 SVA 断言、形式验证属性和 CDC 检查。

## Pipeline Role
- **Phase**: assert
- **Task Type**: assertion_generation
- **Consumes**: (none)
- **Produces**: (text chain only)

## Features
- SVA (SystemVerilog Assertions) 生成
- 形式验证属性生成
- CDC (Clock Domain Crossing) 检查
- 协议检查器

## Usage
```python
from src.agents.assertion_engineer import AssertionEngineer
agent = AssertionEngineer()
await agent.initialize()
result = await agent.execute_task({"input": design_info, "bypass": True})
```

## Test
```bash
pytest src/agents/assertion_engineer/ -v
```
