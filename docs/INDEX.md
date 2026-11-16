# SignOffAI 文档入口与同步范围

本页是文档导航，不替代各文档的原始内容、证据或 SourceAnchor。阅读时请先区分**当前实现说明、学习笔记与历史验收/迁移记录**。

## 1. 当前实现与入口

| 主题 | 文档 | 适用点 |
|---|---|---|
| 项目总览 | [README](../README.md) | 架构、安装、GUI/CLI 与验证边界 |
| 总体架构 | [ARCHITECTURE_4.0](../ARCHITECTURE_4.0.md) | 八职责平面 + Workbench；不新增 Domain Plane |
| 十个 Agent / 五个 Domain | [Agent Domain 与 ReAct 布局](architecture/AGENT_DOMAIN_LAYOUT.md) | 独立 SDK Agent、工具适配、能力与缺口 |
| 兼容专家目录 | [Specialists](architecture/SPECIALIST_AGENTS.md) | 原 CLI/GUI/阶段和生成器兼容入口 |
| 对话与模式 | [Interaction Modes](architecture/INTERACTION_MODES.md) | `chat` / `plan` / `verify`、既有模式映射 |
| 接口时序验证 | [Interface Timing Slice](architecture/INTERFACE_TIMING_SLICE.md) | 有界 AXI4-Stream 证据与后端缺席行为 |
| ChipStack 风格工作区 | [Artifact Workspace](architecture/CHIPSTACK_ARTIFACT_WORKSPACE.md) | 产物索引和 `Archived/<run_id>`真实来源；非 Cadence 数据库适配 |
| Specification Compiler | [Specification Compiler](architecture/SPECIFICATION_COMPILER.md) | 有界规格/IR 编译与绑定证据 |
| Mental IR | [Mental IR](architecture/MENTAL_IR.md) | SourceAnchor 与候选设计理解 |

十个 SDK Agent 的物理入口是 [`reaction/registry.py`](../src/agent_plane/reaction/registry.py)。它们是 Agent Plane 内部独立角色；原 `specialists/`、supervisor 以及联合作业契约并未被整体迁移或重写。

## 2. 依赖、环境与安装

1. [根 requirements](../requirements.txt)：基础依赖与 Agent Stack 的合并文件，供 pip 使用。
2. [分组 Agent 清单](../requirements/agent-stack.txt)：用户原始分类、兼容替代说明与隔离安装方式。
3. [固定版本 Agent 清单](../requirements/agent-stack-resolved.txt)：从当前项目环境核对的直接依赖版本。
4. [原始 `pyproject.toml`](../pyproject.toml)：项目自身核心依赖和版本约束。

当前核验重点：`openai-agents==0.24.0`、`openai==3.51.0`、`langchain==1.4.3`、`langchain-core==1.6.6`。`litellm==1.109.1`、`grpcio==1.76.0`、`tree-sitter==0.20.4` 是与当前环境、Agents SDK、weaviate 客户端和 native language binding 相容的选定版本。

**`requirements.txt` 已是合并文件**。运行 `python scripts/sync_requirements.py` 会按基础 manifest 重建；除非同时保留 Agent 扩展和兼容版本，不应覆盖合并段。

推荐在项目根目录执行：

```powershell
& .\venv\Scripts\python.exe -I -m pip install -r .\requirements.txt
```

`-I` 是隔离外部 Python 搜索路径的调用方式，不会改写全局配置。安装包不自动获得 LLM 密钥、数据库服务器、EDA 工具或 OTel 上报端点。

## 3. 架构治理与阶段记录

- [Architecture Guard 原则](architecture/ARCHITECTURE_GUARD_PRINCIPLES.md)：模块边界、依赖与债务机制。
- [Stage Dependency Matrix](architecture/STAGE_DEPENDENCY_MATRIX.md)：旧阶段测试与依赖视图。
- [Stage Ownership](architecture/STAGE_OWNERSHIP.md)：原职责所有者的迁移分工，不等于新 SDK Agent 目录。
- [Stage Migration Plan](architecture/STAGE_MIGRATION_PLAN.md)：历史迁移步骤与兼容背景。
- [原架构讨论](architecture/arch.md)：早期讨论稿，提供背景，不作为当前所有接口的权威定义。

这些文档描述既有 supervisor/执行器分权与历史迁移；它们不被静默重写成“十个新 Agent 都有对应后端”。

## 4. 学习笔记（示意，不是运行证据）

- [Agents SDK 与类型识别](package_learn/learn_ai_package.md)。
- [LangChain 与 Agents SDK 的原子性区别](package_learn/lanchain_vs_opai-agent.md)。
- [AI 包学习路径](package_learn/agent_learn.md)。
- [本项目组合框架的对应关系与模型限制](package_learn/arch.md)。

以上笔记按当前仓库版本补充实际边界。它们用于学习 Agent、模型、工具和可选存储的组合方式，**不表示自动完成了外部模型连接、Weaviate/MongoDB 连接、自动 telemetry 上报或完整 agent 行为测试**。其中出现的第三方候选框架不代表已加入项目安装清单。

## 5. 历史记录与验收（保留原文语义）

- [M1A Resource IR 验收（2026-11-13）](architecture/M1A_RESOURCE_IR_ACCEPTANCE_2026-11-13.md)。
- [Architecture 4.0 设计评审（2026-11-13）](architecture/ARCHITECTURE_4.0_REVIEW_2026-11-13.md)。
- [历史记录](history/history_record.md)、[H1](history/h1.md)、[H2](history/h2.md)。

历史文件用于追溯当时的讨论、快照和验证，不按今天的目录和版本逐字改写。其通过数量、引擎执行状态或 API 示例**不得自动扩展为当前新角色的完整验收**。

## 6. 本次同步声明

已统一：根 README、当前 Agent/兼容目录说明、SDK 学习笔记、依赖安装说明及此文档导航。历史验收、旧迁移计划与原始规格未擅自改变。

本阶段命中的核查是结构、目录、SDK 构造、依赖/导入和 Architecture Guard 等；不对未实际执行的 Provider 网络调用、全量测试、EDA、PPA、SuperLint 或 formal proof 作完成承诺。
