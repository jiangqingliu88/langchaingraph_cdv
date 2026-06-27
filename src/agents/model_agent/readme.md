# 参考模型工程师 (model_agent)

根据设计架构生成纯 C++ 参考模型 + 自测验证向量。

## Pipeline Role
- **Phase**: model
- **Task Type**: code_generation
- **Consumes**: spec, design_arch
- **Produces**: model

## Features
- 纯 C++ 参考模型生成（无 SystemC 依赖）
- 自测验证向量生成
- Scoreboard Predictor 桥接
- 基于 `src/tools/uvm_tools/tool_sc_red/` 工具

## Usage
```python
from src.agents.model_agent import ModelAgent
agent = ModelAgent()
await agent.initialize()
result = await agent.execute_task({"input": design_arch})
```

## Test
```bash
pytest src/agents/model_agent/ -v
```
