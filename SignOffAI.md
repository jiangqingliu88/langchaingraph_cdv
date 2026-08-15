# SignOffAI 项目记忆

> 类似 CLAUDE.md，自动加载到每个 Agent 的上下文。

## 项目约定

- 个人级 CLI 工具，禁止 Web 前端开发
- 所有功能通过 `python -m src.cli.commands` 交付
- LLM 只做"完形填空"，不决定整体结构
- 确定性优先：规则/模板先行，LLM 兜底

## 架构约定

- 七 Agent：design / model / verify / ops / coverage / debug / audit
- 决策层 L3 驱动闭环（覆盖率 + 编译失败 + 比对失败）
- 统一通信：A2A 风格 JSON-RPC
- 统一证据链：git diff + 修改理由 + hash

## 编译命令

```bash
# 运行完整闭环
python -m src.cli.commands verify spec.md

# 只跑单个 Agent
python -m src.cli.commands verify spec.md --step design

# 编译仿真
python -m src.cli.commands verify spec.md --compile
```

## 编码规范

- SystemVerilog 用 always_ff，不用 always（时序逻辑）
- 参考模型接口统一 predict(input_txn, state) → output_txn
- 每个 Agent 输出必须通过 schema 校验

## 领域约定

- UVM 环境 8 个文件必须齐全（静态检查硬指标）
- 覆盖率目标：代码 ≥95%，功能 ≥100%
- 编译失败优先级高于覆盖率不达标
