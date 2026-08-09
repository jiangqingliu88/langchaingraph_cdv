# SignOffAI 用户手册

> IC 功能设计验证签核平台 — 可复现 · 可审计 · 可治理 · 可交付  
> Version 2.0 | 2026-08-09

---

## 目录

1. [系统概述](#1-系统概述)
2. [快速开始](#2-快速开始)
3. [核心概念](#3-核心概念)
4. [Web 平台操作指南](#4-web-平台操作指南)
5. [验证流水线](#5-验证流水线)
6. [签核审批](#6-签核审批)
7. [PPA 签核](#7-ppa-签核)
8. [规格文档管理](#8-规格文档管理)
9. [证据链与审计](#9-证据链与审计)
10. [角色与权限](#10-角色与权限)
11. [配置参考](#11-配置参考)
12. [运维指南](#12-运维指南)
13. [常见问题](#13-常见问题)

---

## 1. 系统概述

SignOffAI 是一个面向 IC 数字设计的**AI 驱动验证签核平台**。它将传统的手工验证流程自动化，并提供企业级的审批、证据链和审计能力。

### 核心能力

| 能力 | 说明 |
|------|------|
| AI 验证流水线 | 从 Markdown 规格自动生成 RTL、UVM 环境、测试用例、覆盖率报告 |
| 签核审批 | 多级审批链，支持批准/驳回/追问/退回/重新提交 |
| 证据链 | Manifest 哈希自校验，产物完整性验证，审计哈希链防篡改 |
| PPA 签核 | Power / Performance / Area 多维度量化签核，门限自动检查 |
| 文档生态 | 规格文档版本管理、需求提取、文档-签核联动 |
| 平台治理 | 多租户隔离、权限矩阵、健康监控、备份恢复 |

### 技术栈

- **后端**: Python 3.10+ / FastAPI / SQLAlchemy / SQLite (可扩展 PostgreSQL)
- **前端**: Vanilla JS + Chart.js + Bootstrap Icons
- **AI**: DeepSeek / OpenAI 兼容 LLM
- **EDA**: QuestaSim / VCS / Xcelium (适配器架构)

---

## 2. 快速开始

### 2.1 环境要求

- Python 3.10+
- pip
- (可选) QuestaSim 或其他 EDA 仿真器
- (可选) DeepSeek API Key

### 2.2 安装

```bash
git clone <repository>
cd SignOffAI
pip install -e .
```

### 2.3 创建管理员账号

**方式一：启动时自动创建**
```bash
# Linux / macOS
export BOOTSTRAP_ADMIN_PASSWORD=你的密码
python -m uvicorn src.web.api:app --host 0.0.0.0 --port 8000

# Windows PowerShell
$env:BOOTSTRAP_ADMIN_PASSWORD="你的密码"
python -m uvicorn src.web.api:app --host 0.0.0.0 --port 8000
```

**方式二：手动创建**
```bash
python -c "
import asyncio
from src.database.repository import create_user
from src.core.auth import hash_password
async def main():
    await create_user('admin', hash_password('你的密码'), '管理员', 'admin@signoffai.dev', 'admin')
    print('done')
asyncio.run(main())
"
```

### 2.4 启动平台

```bash
# 开发模式（默认，demo 数据关闭）
python -m uvicorn src.web.api:app --host 0.0.0.0 --port 8000

# 演示模式（加载示例数据）
$env:DEMO_ENABLED="1"
$env:APP_MODE="demo"
python -m uvicorn src.web.api:app --host 0.0.0.0 --port 8000
```

浏览器访问 **http://localhost:8000** 登录。

### 2.5 命令行工具

```bash
# 查看所有可用命令
vagent --help

# 从规格文件运行验证
vagent verify specs/uart/uart_tx_spec.md

# 导出证据包
vagent dump <session_id>
```

---

## 3. 核心概念

### 3.1 领域对象

```
项目 (Project)
  ├── 规格文档 (DocDocument)
  │     ├── 文档版本 (DocVersion)
  │     └── 需求条目 (DocRequirement)
  ├── 验证流水线 (PipelineRun)
  │     └── 阶段产物 (Artifact)
  ├── 签核记录 (Signoff)
  │     ├── 审批事件 (SignoffEvent)
  │     ├── PPA 指标 (PPAMetric)
  │     └── PPA Corner (PPACorner)
  └── 审计日志 (AuditLog)
```

### 3.2 状态机

**签核状态流:**
```
draft → pending → approved  (终态)
              → rejected  → draft / pending (重新打开)
draft → deleted (软删除)
```

**文档状态流:**
```
draft → review → approved → deprecated
```

**流水线状态流:**
```
running → completed / completed_with_errors / cancelled
```

所有非法状态转移在 API 层被强制拦截。

### 3.3 证据链模型

```
Signoff
  ├── manifest_hash ──→ manifest.json (SHA256 自校验)
  ├── run_id ──→ PipelineRun ──→ phases[] ──→ Artifact[]
  ├── evidence_package_hash
  └── EvidenceLink[] ──→ object_type + object_id + relation_type
```

---

## 4. Web 平台操作指南

### 4.1 界面布局

```
┌─ 侧边栏 ───────────────────────────────────┐
│ 仪表盘 / 模块总览 / 规格文档 / 流水线       │
│ 需求追踪 / 三层追溯 / 覆盖率 / 回归管理     │
│ 签核证据链 / 智能调试 / 知识库 / 工具治理   │
└────────────────────────────────────────────┘

┌─ 顶部栏 ───────────────────────────────────┐
│ 路径面包屑 / 角色切换 / 主题切换 / 登出     │
└────────────────────────────────────────────┘

┌─ 主内容区 ─────────────────────────────────┐
│                                            │
│  当前选中页面的内容                         │
│                                            │
└────────────────────────────────────────────┘
```

### 4.2 角色切换

点击顶部 "SignOff 经理" / "SignOff 工程师" 按钮切换视图：

- **经理视图**: 模块总览、审批操作、审计日志、管理员设置
- **工程师视图**: 我的模块、流水线执行、文档编辑

### 4.3 主题切换

点击顶部 🌙/☀️ 图标切换暗色/亮色主题。

---

## 5. 验证流水线

### 5.1 运行验证

1. 进入 **流水线** 页面
2. 粘贴或上传 Markdown 规格文档
3. 选择工作流:
   - `full_verification` — 完整验证（规格→设计→UVM→测试→回归→覆盖率→报告）
   - `quick_check` — 快速检查（仅规格分析 + 设计检查）
   - `regression_only` — 仅回归（编译 + 仿真 + 覆盖率）
   - `ppa_analysis` — PPA 分析
4. 选择执行类型: `traditional`（传统AI执行）/ `ai_exploration`（AI 探索）
5. 点击 **运行流水线**

### 5.2 实时监控

运行过程中可实时查看:
- 每个阶段的执行状态（运行中/通过/失败/跳过）
- 阶段评分和耗时
- 产物哈希和工具调用次数

### 5.3 工作流模板

| 模板 | 步骤数 | 说明 |
|------|--------|------|
| full_verification | 8 | spec→design→uvm→tests→regression→coverage→qa→report |
| quick_check | 3 | spec→design→qa |
| regression_only | 3 | regression→coverage→report |
| ppa_analysis | 4 | power→timing→area→ppa_report |

可通过 API 创建自定义工作流模板。

---

## 6. 签核审批

### 6.1 创建签核

1. 进入 **签核证据链** 页面
2. 点击 **新建普通签核**
3. 输入标题和类型:
   - `tapeout` — 流片签核
   - `milestone` — 里程碑签核
   - `coverage` — 覆盖率签核
4. 系统自动绑定最新 Manifest 和证据链

### 6.2 审批流程

**基础审批（单级）:**
```
工程师提交 → 经理批准/驳回
```

**双人审批:**
```
工程师提交 → 高级工程师初审 → 经理终审
```

**流片审批（三级）:**
```
工程师提交 → 高级工程师 → 验证经理 → 管理员
```

### 6.3 审批操作

| 操作 | 可用角色 | 说明 |
|------|---------|------|
| 提交 | 工程师+ | 签核进入待审批状态 |
| 批准 | 经理/管理员 | 锁定证据链，签发 |
| 驳回 | 经理/管理员 | 退回修改，需填写理由 |
| 追问 | 审批人 | 提出问题，等待回复 |
| 退回修改 | 审批人 | 退回给提交者修改 |
| 重新提交 | 提交者 | 修改后重新进入审批 |

### 6.4 证据详情

签核详情页面展示:
- **证据链追溯表**: 每个阶段的输入/输出/哈希/工具调用
- **完整性校验**: Manifest hash 自检 + 文件缺失检测 + 哈希篡改检测
- **签核时间线**: 创建→关联证据→审批→锁定 全过程
- **证据包导出**: 一键下载 ZIP 证据包

---

## 7. PPA 签核

### 7.1 创建 PPA 签核

1. 进入 **签核证据链** 页面
2. 在 **PPA 签核** 面板点击 **新建 PPA 签核**
3. 选择类型:
   - `ppa_power` — 功耗签核
   - `ppa_performance` — 性能签核
   - `ppa_area` — 面积签核
   - `ppa_full` — 全维度综合签核

### 7.2 导入 PPA 指标

**手动录入**: 点击创建后跟随引导填写或直接在面板录入

**EDA 报告解析**: 
```bash
POST /api/ppa/report/parse
{
  "report_text": "<PrimeTime 功耗报告内容>",
  "report_type": "pt_power",
  "signoff_id": 1
}
```

支持解析:
- PrimeTime 功耗/时序报告
- Design Compiler 面积报告
- Innovus 面积报告
- Voltus 功耗报告
- Tempus 时序报告

### 7.3 门限检查

点击 **对比门限规则** 自动检查所有指标:
- ✅ pass — 达标且裕量充足
- ⚠️ marginal — 达标但裕量不足
- ❌ fail — 不满足门限

### 7.4 PVT Corner 对比

PPA 面板的 **PVT Corners** Tab 展示多工艺角对比表:
- ss_0p99v_125c (最差功耗)
- tt_1p1v_25c (典型)
- ff_1p21v_m40c (最佳性能)

---

## 8. 规格文档管理

### 8.1 文档列表

**规格文档库** 页面展示所有模块的 Markdown 规格文档，包括:
- 文档标题、路径、大小
- 关联需求数量
- 文档状态（draft/review/approved/deprecated）

### 8.2 创建文档

1. 点击 **+ 新建**
2. 填写标题和内容
3. 选择级别: chip / subsystem / module / unit
4. 保存后自动解析需求条目（REQ_* 标记）

### 8.3 版本管理

- 每次保存文档自动创建新版本
- 版本历史可查看、对比
- 支持回退到历史版本
- 回退操作被审计记录

### 8.4 文档审批

```
draft → 提交审批 → review → 批准 → approved
                              → 废弃 → deprecated
```

### 8.5 文档-签核联动

- 文档变更时自动检查关联签核是否需要重新审查
- 文档批准后自动绑定到相关签核的证据链
- `get_doc_trace()` 可获取文档的完整追踪链

---

## 9. 证据链与审计

### 9.1 证据链结构

每次验证执行生成完整的证据包:
```
output/<run_id>/
  docs/
    manifest.json       ← SHA256 自校验
    evidence_chain.json ← 5 层证据
  reports/
    regression/         ← 回归报告
    coverage/           ← 覆盖率报告
    ppa/                ← PPA 报告
  testcases/            ← 生成的测试用例
  rtl/                  ← 生成的 RTL
  uvm/                  ← UVM 环境
  logs/                 ← 编译/仿真日志
  snapshots/            ← 上下文快照
```

### 9.2 完整性校验

**自动校验**:
- Manifest hash 自校验（存储 vs 计算）
- 阶段完整性检查
- 产物文件缺失检测
- Hash 篡改检测

**手动校验**: 签核页面 → 点击 **校验完整性**

### 9.3 审计哈希链

所有审计日志通过 SHA256 哈希链链接:
```
Log[0] → chain_hash[0]
Log[1] → prev_hash=chain_hash[0] → chain_hash[1]
Log[2] → prev_hash=chain_hash[1] → chain_hash[2]
...
```

**审计链验证 API**: `GET /api/audit/chain/verify` — 检测缺失/篡改记录

### 9.4 证据包导出

```bash
# Web: 签核页面 → 导出证据包
# CLI:
vagent dump <session_id>

# API:
GET /api/manifest/{session_id}/export
```

---

## 10. 角色与权限

### 10.1 角色定义

| 角色 | 权限范围 |
|------|---------|
| **admin** | 所有权限，包括用户管理、系统配置、备份恢复 |
| **verification_manager** | 签核审批、文档编辑、流水线管理、PPA 门限配置 |
| **senior_engineer** | 签核提交、文档编辑、流水线执行、PPA 数据管理 |
| **engineer** | 查看签核/文档/流水线、运行流水线 |
| **viewer** | 只读查看 |

### 10.2 权限码（部分）

| 权限码 | 说明 |
|--------|------|
| signoff.approve | 批准签核 |
| signoff.create | 创建签核 |
| doc.edit | 编辑文档 |
| evidence.export | 导出证据包 |
| pipeline.run | 运行流水线 |
| ppa.constraint.manage | 管理 PPA 门限 |
| user.manage | 管理用户 |
| audit.read | 查看审计日志 |

完整 22 个权限码列表: `GET /api/admin/permissions`

### 10.3 权限检查

API 层使用 `require_permission("signoff.approve")` 进行动作级权限检查，替代简单的角色字符串匹配。

---

## 11. 配置参考

### 11.1 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `PLATFORM_ENV` | 环境: development / test / production | production |
| `JWT_SECRET` | JWT 签名密钥（生产必设） | 自动生成并持久化到 `.jwt_secret` |
| `BOOTSTRAP_ADMIN_PASSWORD` | 首次启动创建管理员密码 | - |
| `DEMO_ENABLED` | 启用演示数据 | 0 |
| `APP_MODE` | 应用模式: demo / production | production |
| `LLM_API_KEY` | LLM API 密钥 | - |
| `DB_URL` | 数据库连接字符串 | sqlite+aiosqlite:///ic_verification.db |
| `PLATFORM_AUDIT_RETENTION_DAYS` | 审计日志保留天数 | 90 |

### 11.2 分环境配置

```bash
# 开发环境
export PLATFORM_ENV=development
export DEMO_ENABLED=1

# 测试环境
export PLATFORM_ENV=test
export DB_URL=sqlite+aiosqlite:///test.db

# 生产环境
export PLATFORM_ENV=production
export JWT_SECRET=<强随机密钥>
export LLM_API_KEY=<你的API Key>
export DB_URL=postgresql+asyncpg://user:pass@host/db
```

### 11.3 配置文件

| 文件 | 说明 |
|------|------|
| `config/settings.py` | Pydantic Settings 主配置 |
| `.env` | 生产环境变量 |
| `.env.development` | 开发环境变量 |
| `.jwt_secret` | JWT 密钥文件（自动生成） |
| `config/evidence_schema.yaml` | 证据链 Schema 定义 |
| `config/agent_config.yaml` | Agent 配置 |

---

## 12. 运维指南

### 12.1 数据库管理

**备份:**
```bash
# API
POST /api/admin/backup
# Python
python -m src.database.backup
```

**迁移:**
```bash
# 查看状态
GET /api/admin/migrations
# 执行迁移
POST /api/admin/migrations/run
# Python
python -m src.database.migrations
```

### 12.2 健康检查

**快速检查:**
```bash
GET /api/health
GET /api/health/quick
```

**全面检查:**
```bash
GET /api/admin/health-check
```

检查项目:
- 过期规则检测
- 未归档签核数量
- 无证据的已批准签核
- 数据库大小
- 卡住的流水线
- 索引完整性

### 12.3 运营仪表盘

```bash
# 运营总览
GET /api/ops/dashboard

# 最慢流程
GET /api/ops/slow-flows

# 错误统计
GET /api/ops/errors

# 用户行为分析
GET /api/ops/behavior-analysis?days=30
```

### 12.4 审计日志管理

**查看审计日志:**
```bash
GET /api/audit/enhanced?limit=50&action=signoff_approve&access_result=success
```

**审计链验证:**
```bash
GET /api/audit/chain/verify
```

**清理过期日志:**
```bash
python -m src.database.backup --retention 90
```

### 12.5 资源监控

```bash
# 资源池状态
GET /api/admin/resources

# Agent 并发数、License 使用情况、等待队列
```

---

## 13. 常见问题

### Q: 重启后登录失效？
A: v2.0 已修复。JWT 密钥自动持久化到 `.jwt_secret` 文件。生产环境建议设置 `JWT_SECRET` 环境变量。

### Q: 如何恢复误删的签核？
A: 签核使用软删除，数据库记录不会物理删除。联系管理员通过 API 恢复。

### Q: 证据链校验失败怎么办？
A: 检查 `output/` 目录下的文件是否被手动修改或删除。重新运行验证流水线生成新的证据包。

### Q: 如何添加新的审批链？
A: 在 `approval_workflow.py` 中注册新的 `ApprovalChain`，或通过 API 动态创建。

### Q: PPA 门限规则如何配置？
A: 
```bash
POST /api/ppa/constraints
{
  "category": "power",
  "metric_name": "total_power",
  "threshold_value": 100,
  "unit": "mw",
  "constraint_type": "max",
  "margin_required_pct": 10,
  "severity": "P0"
}
```

### Q: 支持哪些 EDA 工具？
A: 当前适配器支持 QuestaSim，插件架构支持扩展: VCS / Xcelium / Riviera / Design Compiler / Innovus / PrimeTime / Voltus / Tempus。

### Q: 如何接入企业微信/钉钉通知？
A: 实现 `NotificationAdapter` 接口并注册到插件系统:
```python
class WeChatNotifier(NotificationAdapter):
    async def send(self, recipients, title, content, level="info"):
        # 调用企业微信 API
        ...
```

---

> 更多信息请参考项目 README 和 API 文档 (http://localhost:8000/docs)
