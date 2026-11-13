# 设计架构师 (design_architect)

模块 Spec → function hierarchy + register map + RTL hierarchy 代码生成。

## Pipeline Role
- **Phase**: design
- **Task Type**: code_generation
- **Consumes**: spec
- **Produces**: design_arch

## Features
- 模块名提取
- 功能层次结构生成 (function hierarchy)
- 寄存器 Map 生成
- RTL 例化层次生成
- Signoff checklist 生成
- 代码渲染 (SystemVerilog)

## Usage
```python
from src.engine.agents.design_architect import DesignArchitect
agent = DesignArchitect()
await agent.initialize()
result = await agent.execute_task({"input": spec_json})
```

## Test
```bash
pytest src/engine_plane/agents/design_architect/ -v
```
