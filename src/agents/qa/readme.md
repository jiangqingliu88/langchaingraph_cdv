# 质量保证 (quality_assurance)

代码审查和验证质量评估。

## Pipeline Role
- **Phase**: qa
- **Task Type**: quality_review
- **Consumes**: (none)
- **Produces**: (text chain only)

## Features
- 验证环境代码审查
- 测试用例质量评估
- 验证完整性检查
- 问题清单生成

## Usage
```python
from src.agents.quality_assurance import QualityAssurance
agent = QualityAssurance()
await agent.initialize()
result = await agent.execute_task({"input": verification_data})
```

## Test
```bash
pytest src/agents/quality_assurance/ -v
```
