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

## Bypass Mode
解析 spec JSON 生成：
- 函数模块声明
- 寄存器定义
- RTL 层次结构
- Signoff 检查点

## Usage
```python
from src.agents.design_architect import DesignArchitect
agent = DesignArchitect()
await agent.initialize()
result = await agent.execute_task({"input": spec_json, "bypass": True})
```

## Test
```bash
pytest src/agents/design_architect/ -v
```
