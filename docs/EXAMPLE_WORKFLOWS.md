# SignOffAI 业务流程示例

> 基于 UART IP 的完整签核流程演示  
> Version 2.0 | 2026-08-09

---

## 目录

1. [场景一：UART TX 模块从规格到签核](#场景一uart-tx-模块从规格到签核)
2. [场景二：PPA 签核——功耗/性能/面积达标判定](#场景二ppa-签核功耗性能面积达标判定)
3. [场景三：多人审批链——双人审核 + 追问退回](#场景三多人审批链双人审核--追问退回)
4. [场景四：文档变更触发签核审查](#场景四文档变更触发签核审查)
5. [场景五：回归失败 → 聚类诊断 → 知识沉淀](#场景五回归失败--聚类诊断--知识沉淀)
6. [场景六：多项目运营仪表盘](#场景六多项目运营仪表盘)
7. [场景七：审计追溯与证据链完整性验证](#场景七审计追溯与证据链完整性验证)

---

## 场景一：UART TX 模块从规格到签核

### 角色
- **张三** (senior_engineer) — 验证工程师
- **李经理** (verification_manager) — SignOff 经理

### 流程

```
1. 张三编写规格
2. 张三运行验证流水线
3. 系统生成所有产物
4. 张三创建签核
5. 李经理审批签核
6. 证据链锁定
```

### 步骤

**Step 1: 张三编写规格文档**

张三在规格文档库新建 `uart/uart_tx_spec.md`：

```markdown
# UART TX 模块规格

## 1. 概述
UART 发送模块负责将并行数据转换为串行数据输出。

## 2. 功能需求

### 帧组装
**REQ_UART_TX_001**：按配置组装起始位+数据位+校验位+停止位
**级别**：P0
**验收标准**：所有帧格式组合正确

### 移位寄存器
**REQ_UART_TX_002**：并行数据加载到移位寄存器，按波特率逐位输出
**级别**：P0

### TX FIFO
**REQ_UART_TX_003**：FIFO 读写指针管理和空标志
**级别**：P1

### 发送状态机
**REQ_UART_TX_004**：IDLE → START → DATA → PARITY → STOP
**级别**：P0

### 中断生成
**REQ_UART_TX_005**：TX FIFO empty 时产生中断
**级别**：P1
```

保存后系统自动提取 5 条需求（REQ_UART_TX_001 ~ 005）。

**Step 2: 张三运行验证流水线**

```
页面：流水线 → 粘贴规格 → 工作流: full_verification → 点击运行
```

系统执行 8 个阶段：

```
Phase 1: spec_analysis     ✅ 评分 95  耗时 2.3s
Phase 2: design_arch       ✅ 评分 88  耗时 5.1s
Phase 3: uvm_env_gen       ✅ 评分 92  耗时 12.4s
Phase 4: test_gen          ✅ 评分 85  耗时 8.7s
Phase 5: regression        ✅ 通过 15/15  耗时 45.2s
Phase 6: coverage          ✅ 行 96.2% 分支 91.5%
Phase 7: quality_assurance ✅ 评分 90  耗时 3.2s
Phase 8: report            ✅ 生成签核报告
```

生成产物：
```
output/run_20260809_143022_a3f2b1/
├── docs/manifest.json           ← SHA256: a1b2c3...
├── docs/evidence_chain.json
├── reports/regression/pass_rate_100%.html
├── reports/coverage/line_96.2_branch_91.5.json
├── testcases/uart_tx/
├── rtl/uart_tx.v
├── uvm/uart_tx_env_pkg.sv
└── logs/compile/uart_tx_compile.log
```

**Step 3: 张三创建签核**

```
页面：签核证据链 → 新建普通签核
标题: UART TX 模块 Tape-out 签核
类型: tapeout
```

系统自动绑定：
- manifest_hash → `a1b2c3...`
- run_id → `run_20260809_143022_a3f2b1`
- 关联的 8 个阶段产物

**Step 4: 李经理审批**

李经理登录 → 签核证据链页面 → 看到待审批的签核

```
展开证据详情:
  ✅ Manifest 完整性: 通过
  ✅ 覆盖率: line 96.2% (≥95% 门限)
  ✅ 回归通过率: 100% (≥95% 门限)
  ✅ 需求覆盖率: 5/5 (100%)
  ✅ 产物文件: 完整, 无缺失

点击 → 批准
```

系统操作：
- 签核状态: pending → approved
- 证据链锁定: manifest_hash 写入 signoff.evidence_package_hash
- SignoffEvent 记录: before=pending, after=approved
- 审计日志: signoff_approve
- 工作流触发: 自动生成报告、发送通知

---

## 场景二：PPA 签核——功耗/性能/面积达标判定

### 角色
- **王工** (senior_engineer) — 负责 PPA 分析
- **李经理** (verification_manager) — 审批

### 流程

```
1. 王工从 PrimeTime/DC 导出 PPA 报告
2. 创建 PPA 签核并导入数据
3. 系统自动对比门限
4. 李经理审批 PPA 签核
5. PPA 签核关联到 tapeout 聚合签核
```

### 步骤

**Step 1: 配置 PPA 门限规则**

李经理预先配置：
```json
POST /api/ppa/constraints
[
  {"category": "power", "metric_name": "total_power",
   "threshold_value": 100, "unit": "mw", "constraint_type": "max",
   "margin_required_pct": 10, "severity": "P0"},
  {"category": "performance", "metric_name": "fmax",
   "threshold_value": 800, "unit": "mhz", "constraint_type": "min",
   "margin_required_pct": 15, "severity": "P0"},
  {"category": "area", "metric_name": "cell_area",
   "threshold_value": 3.0, "unit": "mm2", "constraint_type": "max",
   "margin_required_pct": 20, "severity": "P1"}
]
```

**Step 2: 王工导入 PPA 数据**

```
页面：签核证据链 → PPA 签核面板 → 新建 PPA 签核
类型: ppa_full
标题: UART IP PPA 全维度签核
```

手动录入或导入 EDA 报告：

```json
POST /api/ppa/report/parse
{
  "report_text": "PrimeTime Power Report\nTotal Power = 85.3 mW\n...",
  "report_type": "pt_power",
  "signoff_id": 2
}
```

系统自动解析并存储：
```
PPA 指标 (signoff_id=2):
  power/total_power:    85.3 mW  (target ≤100, margin +14.7%) ✅
  power/dynamic_power:  52.1 mW                              
  power/leakage_power:  33.2 mW                              
  perf/fmax:            1200 MHz  (target ≥800, margin +50%)  ✅
  perf/setup_worst:     0.15 ns   (target ≥0)                ✅
  area/cell_area:       2.3 mm²   (target ≤3.0, margin +23%) ✅
  area/gate_count:      85,320    (target ≤100k)             ✅
```

多个 PVT Corner 对比：
```
Corner            | 功耗(mW) | Fmax(MHz) | 面积(mm²)
ss_0p99v_125c     |   72.1   |    980    |   2.31
tt_1p1v_25c       |   85.3   |   1200    |   2.30
ff_1p21v_m40c     |  105.2   |   1450    |   2.28
```

**Step 3: 门限自动检查**

点击 "对比门限规则"：
```
✅ total_power: 85.3 ≤ 100, margin +14.7% (≥10%) → pass
✅ fmax: 1200 ≥ 800, margin +50% (≥15%) → pass
✅ cell_area: 2.3 ≤ 3.0, margin +23% (≥20%) → pass

结论：所有 P0 门限通过，可以签核
```

**Step 4: 聚合 Tape-out 签核**

创建聚合签核，关联功能签核和 PPA 签核：
```
Tape-out Signoff #3
├── Functional: ✅ Signoff #1 (coverage 96.2%, pass_rate 100%)
├── PPA Power:  ✅ Signoff #2 (total_power 85.3mW, margin 14.7%)
├── PPA Perf:   ✅ Signoff #2 (fmax 1200MHz, margin 50%)
└── PPA Area:   ✅ Signoff #2 (area 2.3mm², margin 23%)
```

---

## 场景三：多人审批链——双人审核 + 追问退回

### 角色
- **张三** (engineer) — 提交者
- **王工** (senior_engineer) — 初审
- **李经理** (verification_manager) — 终审

### 流程

```
张三提交 → 王工初审(追问) → 张三回复 → 王工通过 → 李经理终审(退回) → 张三修改 → 李经理批准
```

### 步骤

**Step 1: 张三提交签核**

```
POST /api/approval/signoff/1/submit
{"comment": "UART TX 模块验证完成，申请流片审批"}
→ 状态: draft → submitted
```

**Step 2: 王工初审 —— 追问**

王工查看证据详情，发现覆盖率报告中某个 corner case 缺失:

```
POST /api/approval/signoff/1/ask-back
{"question": "BR_115200 波特率下的帧格式覆盖率为 78%，请补充定向测试"}
→ 状态: under_review → asked_back
```

张三收到通知，补充测试后回复:

```
POST /api/approval/signoff/1/resubmit
{"comment": "已补充 BR_115200 帧格式定向测试，覆盖率提升至 96.2%"}
→ 状态: asked_back → under_review
```

**Step 3: 王工初审通过**

```
POST /api/approval/signoff/1/approve
{"comment": "覆盖率达标，通过初审"}
→ 状态: under_review → approved (当前步骤)
→ 自动推进到下一步: verification_manager 终审
```

**Step 4: 李经理终审 —— 退回修改**

李经理发现 manifest hash 与最新版本不一致:

```
POST /api/approval/signoff/1/return-for-revision
{"notes": "证据包 manifest hash 不是最新版本，请重新运行流水线并更新证据链"}
→ 状态: under_review → returned
```

张三重新运行流水线，更新证据链后重新提交:

```
POST /api/approval/signoff/1/resubmit
{"comment": "已重跑流水线 run_20260809_180530_b7e2f1，更新了证据链"}
→ 状态: returned → under_review
```

**Step 5: 李经理终审通过**

```
POST /api/approval/signoff/1/approve
{"comment": "证据链完整，批准流片"}
→ 状态: under_review → approved
→ 签核锁定，证据链固化
```

**审批时间线：**

```
09:30  张三提交审批
09:45  王工追问 (baud rate 覆盖率)
10:20  张三回复并补充测试
10:35  王工初审通过
11:00  李经理退回 (manifest 版本不一致)
11:30  张三重跑流水线并更新证据
11:50  李经理终审通过 ✅
─────────────────────────
总耗时: 2h20min (含2次来回)
```

---

## 场景四：文档变更触发签核审查

### 流程

```
张三修改规格文档 → 系统检测到关联签核已批准 → 自动标记需要重新审查 → 李经理收到通知
```

### 步骤

**Step 1: 张三修改规格**

张三在 `uart_tx_spec.md` 中新增一条需求：

```markdown
### 奇偶校验配置
**REQ_UART_TX_006**：支持奇校验、偶校验、无校验三种模式
**级别**：P1
```

保存后系统自动：
- 创建新版本 (v2.0)
- 记录审计日志: `doc_update`
- 触发 `DocSignoffBinding.on_doc_updated()`

**Step 2: 系统自动检测**

`on_doc_updated()` 检测到：
```
文档 doc/12 (uart_tx_spec.md) 已更新
关联签核 #1 状态: approved
→ 标记 signoff #1 需要重新审查
→ 审计日志: doc_change_requires_review
```

**Step 3: 李经理收到提示**

签核列表显示：
```
┌─────────────────────────────────────────────────────────┐
│ UART TX Tape-out 签核  [approved] ⚠️ 需重新审查        │
│ 关联文档 uart_tx_spec.md 于 2026-08-09 10:00 更新     │
│ 新增需求: REQ_UART_TX_006                              │
└─────────────────────────────────────────────────────────┘
```

**Step 4: 完整追踪链**

```
GET /api/v2/docs/12  (文档追踪)
→ 版本历史: v1.0 → v2.0 (新增 REQ_UART_TX_006)
→ 关联签核: #1 (needs review)
→ 关联测试: TEST_TX_001 ~ TEST_TX_005 (可能需要新增 TEST_TX_006)
```

---

## 场景五：回归失败 → 聚类诊断 → 知识沉淀

### 流程

```
回归发现5个失败 → 失败聚类引擎分析 → 自动分类2类 → 提取修复知识 → 自动存储
```

### 步骤

**Step 1: 批量失败分析**

```json
POST /api/ops/failure-cluster
{
  "failed_logs": [
    {"run_id":"r1","phase":"regression","error_log":"UVM_ERROR: scoreboard mismatch at cycle 42",...},
    {"run_id":"r2","phase":"regression","error_log":"UVM_ERROR: scoreboard mismatch at cycle 87",...},
    {"run_id":"r3","phase":"regression","error_log":"Simulation timeout after 3600s",...},
    {"run_id":"r4","phase":"simulation","error_log":"FIFO overflow detected in uart_fifo.v:129",...},
    {"run_id":"r5","phase":"compilation","error_log":"Error: undefined identifier 'uart_ctrl_new'",...}
  ]
}
```

**Step 2: 聚类结果**

```
5 个失败 → 3 个聚类:

Cluster #001: scoreboard_mismatch (2次, 40%)
  样本: r1, r2
  建议: 比对参考模型和 DUT 输出，定位第一个不一致 cycle

Cluster #002: compile_error (1次, 20%)
  样本: r5
  建议: 检查 include 路径和模块声明

Cluster #003: timeout (1次, 20%)
  样本: r3
  建议: 增大 timeout 值或检查死锁

Cluster #004: fifo_overflow (1次, 20%)
  样本: r4
  自动修复: ✅ 可自动
  建议: 检查 FIFO 深度设置和读写速率匹配
```

**Step 3: 知识自动沉淀**

系统调用 `KnowledgeExtractor.auto_store()`：
```
自动创建知识条目:
  "修复方案: scoreboard_mismatch" (来源: r1, r2)
  分类: bug_case | 标签: auto,fix
  内容: 比对参考模型和 DUT 输出，定位第一个不一致 cycle

  "修复方案: fifo_overflow" (来源: r4)
  分类: bug_case | 标签: auto,fix
  内容: 检查 FIFO 深度设置和读写速率匹配
```

---

## 场景六：多项目运营仪表盘

### 场景

SignOff 经理登录后查看模块总览，了解全局状态。

### 仪表盘数据

```
GET /api/ops/dashboard
```

```
┌────────────────────────────────────────────────────────────┐
│ 系统运行时间: 72.5h                                        │
│ 流水线总数: 189 | 签核总数: 12 | API 调用: 3456           │
├────────────────────────────────────────────────────────────┤
│ 流水线统计                                                  │
│   平均耗时: 45.3s                                          │
│   通过率(近20次): 85%                                      │
├────────────────────────────────────────────────────────────┤
│ 签核统计                                                    │
│   平均周期: 2.5h                                           │
│   已批准: 8 | 待审批: 3 | 已驳回: 1                        │
├────────────────────────────────────────────────────────────┤
│ 性能: 慢 API                                                │
│   /api/pipeline/run: avg 320ms, p99 1500ms                │
│   /api/manifest/verify: avg 280ms, p99 890ms              │
├────────────────────────────────────────────────────────────┤
│ 用户活跃度 Top3                                             │
│   zhangsan: 156 actions (pipeline_run: 45)                 │
│   wanggong: 89 actions (signoff_create: 12)                │
│   limanager: 67 actions (signoff_approve: 8)               │
├────────────────────────────────────────────────────────────┤
│ 模块失败率                                                  │
│   uart_rx: 0.12 | uart_fifo: 0.08 | alu_logic: 0.03      │
└────────────────────────────────────────────────────────────┘
```

### 健康检查

```
GET /api/admin/health-check
```

```
健康状态: ⚠️ 2 issues
  ⚠️ 12 个已批准签核未归档 — 建议批量归档
  ℹ️ 表 audit_logs 建议在 created_at 上建索引
```

---

## 场景七：审计追溯与证据链完整性验证

### 场景

外部审计要求验证签核 #1 的证据链是否完整、未被篡改。

### 步骤

**Step 1: 证据完整性校验**

```
GET /api/manifest/run_20260809_143022_a3f2b1/verify
```

```json
{
  "session_id": "run_20260809_143022_a3f2b1",
  "valid": true,
  "manifest_hash_ok": true,
  "phases_complete": true,
  "phases_completed": 8,
  "total_phases": 8,
  "file_count": 45,
  "missing_files": [],
  "hash_mismatches": [],
  "conclusion": "🟢 证据链完整，未被篡改"
}
```

**Step 2: 审计哈希链验证**

```
GET /api/audit/chain/verify
```

```json
{
  "valid": true,
  "total_records": 234,
  "issues": [],
  "latest_hash": "f8e7d6c5b4a3...",
  "message": "审计链完整"
}
```

**Step 3: 签核完整追溯链**

```
GET /api/signoffs/1/evidence
```

```json
{
  "signoff_id": 1,
  "status": "approved",
  "run_id": "run_20260809_143022_a3f2b1",
  "manifest_hash": "a1b2c3d4e5f6...",
  "integrity": {
    "manifest_hash_ok": true,
    "phases_complete": true,
    "phases_passed": 8,
    "valid": true,
    "conclusion": "🟢 证据链完整"
  },
  "manifest": {
    "phases": [
      {"phase_name": "spec", "status": "passed", "output_hash": "..."},
      {"phase_name": "design", "status": "passed", "output_hash": "..."},
      ...
    ]
  }
}
```

**Step 4: 审计轨迹**

```
GET /api/signoffs/1/timeline
```

```
📝 10:30 签核创建
▶️ 10:30 流水线 run_20260809_143022 完成
📦 10:31 证据包绑定 (manifest a1b2c3...)
📝 10:35 张三提交审批
⚠️ 10:45 王工追问 (baud rate 覆盖率)
📝 11:05 张三回复并补充测试
✅ 11:20 王工初审通过
⚠️ 11:30 李经理退回 (manifest 版本不一致)
📝 11:45 张三重跑流水线并更新证据链
✅ 12:00 李经理终审通过
🔒 12:00 证据链锁定 (hash: f8e7d6...)
```

---

## 总结

| 场景 | 核心能力 | 涉及模块 |
|------|---------|---------|
| 规格→签核 | AI 流水线 + 签核审批 | pipeline, signoff, manifest |
| PPA 签核 | 多维度量化 + 门限对比 | ppa, constraints, policy engine |
| 多人审批 | 追问/退回/重新提交 | approval_workflow, multi_approval |
| 文档联动 | 变更触发审查 + 追踪链 | doc_signoff_binding, doc_versions |
| 失败聚类 | 自动分类 + 知识沉淀 | failure_cluster, knowledge_extractor |
| 运营仪表盘 | 全局指标 + 健康检查 | observability, health_monitor |
| 审计追溯 | 证据完整性 + 哈希链 | manifest, audit_chain, timeline |

> API 详细文档: http://localhost:8000/docs
