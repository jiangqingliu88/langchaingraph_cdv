# SignOffAI 架构更新方案 — 三层映射模型

> 设计架构师 → 需求数据库 → 测试点 三层强映射

---

## 一、当前架构 vs 目标架构

### 当前数据流（两层）

```
MD 规格 ──→ SpecPlanner ──→ 需求列表 (vPlan)
                ↓
         DesignArchitect ──→ RTL + 设计文档 (松散,无结构化存储)
                ↓
         VerificationArchitect ──→ UVM 环境
                ↓
         TestEngineer ──→ 测试用例

问题: 设计层的"模块/接口/功能点"没有结构化存储和追溯
```

### 目标架构（三层映射）

```
需求层                  设计层                    验证层
(Requirements)     (Modules + Features)     (Testpoints + Cases)
─────────────────────────────────────────────────────────────
REQ-001: 数据通路  ──→  Module: noc_router  ──→  TP-001: 正向通路 (P0)
                         ├─ Port: data_in      TP-002: 输入检测 (P1)
                         ├─ Port: data_out     TP-003: 输出检测 (P1)
                         └─ Feature: 数据转发

REQ-002: 背压处理  ──→  Module: noc_router  ──→  TP-005: buffer满 (P1)
                         └─ Feature: 背压控制   TP-006: 反压恢复 (P1)

每一层都可追溯,每一步都有 hash,每一个映射都有 confidence score
```

---

## 二、数据库扩展

### 2.1 新增表（复用现有 models.py 模式）

```sql
-- 模块表 (对应 DesignArchitect 输出)
CREATE TABLE design_modules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER REFERENCES projects(id),
    name VARCHAR(255) NOT NULL,       -- noc_router
    parent_id INTEGER,                 -- 层次化: soc_top → noc_router
    description TEXT,
    interfaces JSON,                   -- [{name, direction, width, protocol}]
    signals JSON,                      -- [{name, type, description}]
    rtl_file VARCHAR(500),            -- 生成的 RTL 文件路径
    rtl_hash VARCHAR(64),             -- RTL 代码 hash (可追溯)
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 功能点表 (映射到 spec features)
CREATE TABLE design_features (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    module_id INTEGER REFERENCES design_modules(id),
    name VARCHAR(255) NOT NULL,        -- 数据转发
    level VARCHAR(10) DEFAULT 'P0',   -- P0/P1/P2/P3
    description TEXT,
    keywords TEXT,                     -- 逗号分隔,用于匹配需求
    spec_feature_ref VARCHAR(100),    -- 对应 spec 中的 feature name
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 需求→功能点 映射表 (核心: 可追溯)
CREATE TABLE req_feature_map (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    req_id VARCHAR(50) NOT NULL,       -- REQ-001
    feature_id INTEGER REFERENCES design_features(id),
    mapping_type VARCHAR(20) DEFAULT 'DIRECT',  -- DIRECT/INFERRED/MANUAL
    confidence REAL DEFAULT 1.0,       -- 映射置信度
    mapped_by VARCHAR(50),            -- auto/manual/用户名
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 功能点→测试点 映射表
CREATE TABLE feature_testpoint_map (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    feature_id INTEGER REFERENCES design_features(id),
    testpoint_id VARCHAR(50) NOT NULL,  -- TP-001
    mapping_type VARCHAR(20) DEFAULT 'DIRECT',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### 2.2 现有表改动 (最小化)

无需修改现有表。新表通过 `project_id` 和 `req_id` 与现有 `projects`、`vplan` 联表。

---

## 三、DesignArchitect Agent 改造

### 3.1 consumes/produces 契约更新

```python
# src/agents/design_architect/main.py

class DesignArchitect(BaseAgent):
    task_type = "design_architecture"
    
    # 旧: consumes = {"spec": [...]}
    # 新: 增加 produces 为结构化设计数据
    consumes = {"spec": ["features", "interfaces", "registers", "design_name"]}
    produces = "design_arch"  # 保持不变,但内容增强
    
    # 新增: 产出结构化模块数据
    structured_produces = {
        "modules": "design_modules",      # → 写入 design_modules 表
        "features": "design_features",    # → 写入 design_features 表
        "mapping": "req_feature_map",     # → 写入 req_feature_map 表
    }
```

### 3.2 输出格式增强

```json
// 旧输出 (仅文本)
{"design_arch": {"module_name": "alu", "function_count": 12, ...}}

// 新输出 (结构化 + 可追溯)
{
  "design_arch": {
    "module_name": "noc_router",
    "function_count": 3,
    "modules": [
      {
        "name": "noc_router",
        "parent": "soc_top",
        "interfaces": [
          {"name": "data_in", "direction": "INPUT", "width": 32, "protocol": "AXI-Stream"},
          {"name": "data_out", "direction": "OUTPUT", "width": 32, "protocol": "AXI-Stream"}
        ],
        "features": [
          {
            "name": "数据转发",
            "level": "P0",
            "keywords": ["data", "forward", "packet", "数据", "转发"],
            "spec_ref": "REQ-001",
            "testpoints": ["TP-001", "TP-002"]
          }
        ],
        "rtl_file": "rtl/noc_router.v",
        "rtl_hash": "a1b2c3..."
      }
    ],
    "mapping_summary": {
      "total_requirements": 8,
      "mapped_to_modules": 8,
      "mapped_to_features": 8,
      "unmapped": 0
    }
  }
}
```

---

## 四、新增核心模块: DesignArchitectMapper

### 4.1 位置

```
src/core/design_mapper.py
```

### 4.2 职责

| 方法 | 说明 |
|---|---|
| `parse_md_modules(md_text)` | 从 Markdown 解析模块/接口/功能点 |
| `match_req_to_features(reqs, modules)` | 需求→功能点 关键词匹配 |
| `store_modules(project_id, modules)` | 写入 design_modules 表 |
| `store_features(project_id, features)` | 写入 design_features 表 |
| `store_mapping(req_feature_pairs)` | 写入 req_feature_map 表 |
| `generate_mapping_report(project_id)` | 生成三层映射报告 |

### 4.3 关键词匹配逻辑

```python
# 从 spec features 到 design features 的自动匹配
FEATURE_KEYWORDS = {
    "data_path":    ["data", "数据", "通路", "path", "packet", "包"],
    "backpressure": ["backpressure", "背压", "buffer", "full", "满"],
    "arbitration":  ["arbit", "仲裁", "grant", "priority"],
    "error":        ["error", "错误", "fault", "inject", "注入"],
    "interrupt":    ["interrupt", "中断", "irq"],
    "register":     ["register", "寄存器", "cfg", "config"],
}
```

---

## 五、API 新增

### 5.1 端点列表

| 端点 | 方法 | 说明 | 权限 |
|---|---|---|---|
| `/api/design/mapping/{project_id}` | GET | 三层映射矩阵 | 项目成员 |
| `/api/design/modules/{project_id}` | GET | 模块列表 + 功能点 | 项目成员 |
| `/api/design/modules/{project_id}` | POST | 上传/更新模块划分 MD | 管理员/经理 |
| `/api/design/mapping/{project_id}` | PATCH | 手动调整映射关系 | 管理员/经理 |
| `/api/design/trace/{req_id}` | GET | 单需求完整追溯链 | 项目成员 |

### 5.2 示例响应

```json
// GET /api/design/mapping/1
{
  "project_id": 1,
  "mapping_matrix": [
    {
      "req_id": "REQ-001",
      "req_description": "数据通路正确性",
      "module": "noc_router",
      "feature": "数据转发",
      "feature_level": "P0",
      "testpoints": ["TP-001", "TP-002"],
      "mapping_type": "DIRECT",
      "confidence": 0.95
    }
  ],
  "stats": {
    "total_reqs": 8,
    "mapped_reqs": 8,
    "total_modules": 3,
    "total_features": 12,
    "unmapped_reqs": 0
  }
}
```

---

## 六、前端展示 (在三层映射视角下)

### 6.1 模块卡片增强

每个模块卡片显示三层映射状态：

```
┌──────────────────────────────────┐
│ noc_router                       │
│ 8 需求 → 3 模块 → 12 功能点      │
│ ████████████████████ 100% 映射   │
│                                  │
│ 🔗 追溯: REQ-001 → 数据转发 → TP-001 │
│ 🔗 追溯: REQ-002 → 背压控制 → TP-005 │
└──────────────────────────────────┘
```

### 6.2 需求追溯视图 (新增页面)

点击任一需求 → 展开完整追溯链:
```
REQ-001: 数据通路正确性
  ├── Module: noc_router (RTL hash: a1b2c3...)
  │   ├── Feature: 数据转发 (P0) ✅
  │   │   ├── TP-001: 正向数据通路 (P0) ✅ PASS
  │   │   └── TP-002: 数据输入检测 (P1) ⚠ FAIL
  │   └── Feature: 错误注入 (P2) ✅
  │       └── TP-007: FCS 错误注入 (P2) ✅ PASS
  └── Coverage: line=92% branch=85% toggle=78%
```

---

## 七、证据链增强

### 7.1 evidence.py 新增 DesignLayer 检查

```python
# 在 _collect_design_layer 中增加:
"req_module_mapping": {
    "total_requirements": 8,
    "mapped_to_modules": 8,
    "mapped_to_features": 8,
    "unmapped": 0,
    "mapping_coverage": 100.0  # % of reqs with module mapping
}
```

### 7.2 证据链 CLI 输出

```
=== Evidence Chain ===
  [██████████] 需求→模块映射: 8/8 (100%)
  [████████░░] 模块→功能点: 12/15 (80%)
  [██████░░░░] 功能点→测试点: 9/12 (75%)
```

---

## 八、实施优先级

| 优先级 | 任务 | 工作量 | 依赖 |
|---|---|---|---|
| **P0** | `design_modules` + `design_features` 表 | 30min | 无 |
| **P0** | `req_feature_map` + `feature_testpoint_map` 表 | 20min | P0 表 |
| **P0** | `DesignArchitectMapper` 核心类 | 2h | P0 表 |
| **P1** | DesignArchitect Agent 输出增强 | 1h | Mapper |
| **P1** | `/api/design/mapping` API | 1h | Mapper |
| **P1** | 前端需求追溯视图 | 2h | API |
| **P2** | evidence.py DesignLayer 增强 | 1h | Mapper |

---

## 九、文件变更清单

| 操作 | 文件 |
|---|---|
| 新增 | `src/core/design_mapper.py` |
| 新增 | `src/database/models.py` (3 个新表) |
| 修改 | `src/agents/design_architect/main.py` (输出增强) |
| 修改 | `src/web/api.py` (5 个新端点) |
| 修改 | `src/core/evidence.py` (DesignLayer 增强) |
| 新增 | `src/web/templates/dashboard.html` (追溯视图) |

---

*此文档是 SignOffAI 从"两层"升级到"三层强映射"的架构方案。实施后,可追溯能力从"需求→测试"变为"需求→模块→功能点→测试点"的完整链路。*
