# 验证架构师 (verification_architect)

设计 UVM 验证环境架构、生成所有组件代码、进行质量自检。

## Pipeline Role
- **Phase**: arch
- **Task Type**: code_generation
- **Consumes**: spec
- **Produces**: env

## Features
- UVM 环境代码生成 (driver, monitor, agent, env, scoreboard...)
- 7 工具质量自检流水线：
  1. generate_env_code — 生成环境代码
  2. check_static — 静态检查
  3. check_compile — 编译检查
  4. check_loopback — 回环验证
  5. check_health — 健康检查
  6. generate_quality_report — 质量报告
  7. fix_issues — 修复问题
- 质量评分 ≥80/100 才交付

## Usage
```python
from src.agents.verify_architect import VerificationArchitect
agent = VerificationArchitect()
await agent.initialize()
result = await agent.execute_task({"input": spec_text})
```

## Test
```bash
pytest src/agents/verify_architect/ -v
```
