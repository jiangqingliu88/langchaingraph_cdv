# SignOffAI Web 前端必要性分析

> 日期：2026-08-09  
> 结论：**当前阶段 Web 前端投入严重过度，建议削 Web 强 CLI**

---

## 1. 代码量全景对比

```
总代码量：~42,700 行（src/ 下 .py + .html + .css + .js）

src/web/     10,349 行  ████████████████████████░░░  25%  ← Web 前端
src/tools/   11,055 行  ██████████████████████████░  26%  ← 工具引擎
src/infra/    9,783 行  ███████████████████████░░░░  23%  ← 基础设施
src/core/     9,091 行  █████████████████████░░░░░░  21%  ← 核心框架
src/agents/   2,063 行  █████░░░░░░░░░░░░░░░░░░░░░░   5%  ← Agent 层
src/cli/        699 行  ██░░░░░░░░░░░░░░░░░░░░░░░░░   1.7% ← CLI
```

**核心矛盾：Web 层（25%）≈ 核心框架（21%），CLI 仅 1.7%。**

---

## 2. Web 层拆解

### 2.1 文件清单

| 文件 | 行数 | 职责 |
|------|------|------|
| `src/web/api.py` | 4,233 | 主 API：认证/RBAC、Pipeline SSE 推送、Agent 监控、vPlan 导出、覆盖率 Diff、设计映射、文档编辑器、签核状态机、健康检查、插件系统 |
| `src/web/templates/dashboard.html` | 2,481 | 单文件 SPA：侧边栏导航、Chart.js 图表、暗/亮主题、EventSource SSE 连接 |
| `src/web/templates/login.html` | — | 登录页 |
| `src/web/templates/login_test.html` | — | 测试登录页 |
| `src/web/static/css/dashboard.css` | — | Dashboard 样式 |
| `src/web/static/js/dashboard.js` | — | Dashboard 交互逻辑 |
| `src/web/routes/docs.py` | — | 文档路由（MD 生态 CRUD） |
| `src/web/routes/signoff.py` | — | 签核路由（审批流程） |
| `src/web/routes/pipeline.py` | — | 流水线路由（执行+状态） |
| `src/web/routes/ppa.py` | — | PPA 分析路由（功耗/性能/面积） |
| `src/web/sse.py` | — | SSE 事件推送（Pipeline 实时状态） |

### 2.2 API 端点统计

```
认证类:   POST /api/auth/login, GET /api/auth/me
Pipeline: POST /api/pipeline/run, GET /api/pipeline/{id}/stream
Agent:    GET /api/agents/contracts, GET /api/agents/status, GET /api/agents/status/{role}
设计层:   GET /api/design/mapping, /modules, /trace, POST /upload, PATCH /mapping
文档:     GET /api/editor/{path}, POST /api/editor/{path}
覆盖率:   GET /api/coverage/diff
vPlan:    GET /api/vplan/export
签核:     signoff_router（子路由）
健康:     GET /api/health
页面:     GET /, GET /test-login
```

共计 **25+ 个端点**，撑起了一个完整的企业级 Web 应用。

---

## 3. CLI 现状

`src/cli/commands.py`（699 行）提供的命令：

```bash
vagent init                          # 创建输出目录
vagent dump [session_id]             # 导出签核证据包

# 没有以下命令：
# vagent verify --spec xxx.md        ← 不存在
# vagent signoff --run-id xxx        ← 不存在
# vagent diff --run-a a --run-b b    ← 不存在
# vagent status                      ← 不存在
```

CLI 用的是 `click` + `rich`（表格/Panel/进度条/语法高亮），基础能力都在，但**几乎没有面向核心业务的命令**。

---

## 4. 为什么 Web 前端当前不必要

### 4.1 目标用户不使用浏览器

| 角色 | 日常工作环境 | 核心工具 |
|------|-------------|---------|
| 验证工程师 | Linux 服务器，无 GUI | VCS、Verdi、QuestaSim、Makefile |
| 设计工程师 | Linux 工作站 | VCS、SpyGlass、DC Compiler |
| 签核经理 | 可能用浏览器看报告，但更关注 CI 产出的 PDF/HTML | Jenkins、GitLab CI |

IC 验证工作流是 **终端驱动**的。没有人会在跑仿真的时候打开浏览器点按钮。

### 4.2 引擎还没跑通，Dashboard 展示的是假数据

```
引擎层 (tools/) 真实对接情况：

spec_tools/         → 全部 Mock（返回硬编码 UART 数据）
assertion_tools/    → 全部 Mock（返回 "prop1", "prop2"）
coverage_tools/     → 全部 Mock（返回硬编码 96%/95%/92%）
debug_tools/        → 全部 Mock（返回假 log 分析）
reuse_tools/        → 全部 Mock（返回假 VIP 列表）
doc_tools/          → 真实（SQL 数据库后端）✅
uvm_tools/          → 真实（Jinja2 模板生成 SV 代码）✅
cmodel_tools/       → 真实（调用 g++ 编译 DPI）✅
testcase_tools/     → 真实（YAML→SV 模板生成）✅
```

**8 类工具中 5 类还是假的**。Web 层精心设计了 25+ 个端点来展示这些假数据，这是排列错误的优先级。

### 4.3 CI/CD 集成需要 CLI，不需要 Web

验证流水线的目标运行环境是 CI：

```yaml
# .gitlab-ci.yml 或 Jenkinsfile
verify:
  script:
    - vagent verify --spec specs/uart.md --output output/ --json > result.json
    - vagent signoff --run-id $(cat result.json | jq -r .run_id)
```

Web SSE 推送、Dashboard 图表对 CI 系统毫无意义。CI 需要的是：
- 结构化输出（JSON）
- 明确的退出码（0=通过, 非0=失败）
- 可归档的产物（证据包 zip）

### 4.4 维护成本被低估

Web 层不是"一个页面加几个 API"，它引入了一整套企业级基础设施：

```
JWT 认证        → src/core/auth.py, api.py 中的 Depends(require_auth)
RBAC 角色控制   → src/infra/rbac.py, rbac_web.py
速率限制        → src/infra/security.py (RateLimiter)
审计日志        → src/database/models.py (AuditLog)
SSE 实时推送    → src/web/sse.py
插件系统        → src/infra/plugin_system.py
错误处理        → src/infra/error_handler.py
事件总线        → src/infra/event_bus.py
可观测性        → src/infra/observability.py
```

这些设施本身没有问题，但它们应该在**引擎成熟后再接入**，而不是在引擎还没跑通时就全部搭好。

### 4.5 投入产出比严重失衡

```
Web 层:   10,349 行  →  产出：一个展示假数据的 Dashboard
CLI 层:      699 行  →  产出：两个半命令

Web/CLI 行数比 = 14.8 : 1
```

合理的比例应该反过来，CLI 应该是 Web 的 3-5 倍。因为核心价值在**执行验证**，不在**展示结果**。

---

## 5. 判断矩阵

| 维度 | Web Dashboard | CLI 工具 |
|------|:---:|:---:|
| 目标用户匹配度 | ❌ 低 | ✅ 高 |
| CI/CD 集成 | ❌ 不支持 | ✅ 原生支持 |
| 当前数据真实性 | ❌ 80% Mock | — |
| 开发维护成本 | ❌ 高（10K+ 行） | ✅ 低 |
| 对核心价值的贡献 | ⚠️ 间接（展示） | ✅ 直接（执行） |
| 非工程师可访问性 | ✅ 好 | ❌ 需要终端技能 |
| 未来需要吗 | ✅ 签核经理需要 | ✅ 始终需要 |

**结论：CLI 是刚需，Web 是锦上添花。先有花再添锦，顺序不能反。**

---

## 6. 建议方案

### 阶段一：削 Web，强 CLI（立即执行）

| 行动 | 说明 |
|------|------|
| **砍掉 Dashboard HTML** | 删除 `dashboard.html` (2,481 行)，删除 `static/` |
| **砍掉 SSE** | 删除 `src/web/sse.py`，Pipeline 结果通过 JSON API + 轮询获取 |
| **砍掉 Auth/RBAC** | 删除 JWT 认证链，API 仅保留 `--api-key` header 或内网裸奔 |
| **砍掉 login 页面** | 删除 `login.html`、`login_test.html` |
| **砍掉审计日志** | 删除 AuditLog 写入代码，调 API 不需要登录自然不需要审计 |
| **砍掉子路由** | 合并 `routes/` 中的 signoff/ppa/docs/pipeline 回 api.py，减少文件数 |
| **保留最小 API** | 仅保留：`POST /api/pipeline/run`、`GET /api/pipeline/{id}/status`、`GET /api/health` |

**预期效果：Web 层从 10K 行缩减到 ~800 行，减掉 90%。**

### 阶段二：CLI 对标投入

```bash
# 核心验证命令
vagent verify --spec <path>          # 运行完整验证流水线
vagent verify --spec <path> --step coverage  # 单步执行

# 签核
vagent signoff --run-id <id>         # 生成签核报告
vagent signoff --run-id <id> --export evidence.zip  # 导出证据包

# 差异分析
vagent diff --run-a <id1> --run-b <id2>  # 两次回归覆盖率对比
vagent diff --spec <v1> --spec <v2>       # 规格变更影响分析

# 状态
vagent status                        # 查看所有 Agent 状态
vagent status --run-id <id>          # 查看某次运行状态

# 工具
vagent tool list                     # 列出所有可用工具
vagent tool call <name> --args '{}'  # 直接调用工具

# 输出格式
--json                               # JSON 输出（给 CI）
--plain                              # 纯文本输出（给人）
--rich                               # 富文本输出（默认，交互终端）
```

### 阶段三：引擎成熟后重建 Web（未来）

当以下条件满足时，再考虑重建 Web Dashboard：
- 8 类工具全部对接真实 EDA 后端，Mock 率 = 0
- CLI 命令稳定，至少 20+ 个项目在 CI 中使用
- 签核经理明确反馈需要 Web 界面查看趋势

---

## 7. 对比参考

| 工具 | 交互方式 | 有 Web UI 吗 |
|------|---------|:---:|
| VCS (Synopsys) | CLI | 有 Verdi（波形查看，不是 Web） |
| QuestaSim (Siemens) | CLI + Tcl | 有 GUI（桌面应用，不是 Web） |
| Verilator | CLI | ❌ 无 |
| cocotb | CLI + Python API | ❌ 无 |
| Jenkins | Web | ✅（CI 调度器，天然 Web） |
| pytest | CLI | ❌ 无 |

**IC 验证工具链的行业惯例是 CLI 优先，GUI 是可选的调试辅助。SignOffAI 应该遵循这个惯例。**

---

## 8. 一句话总结

> **Web 前端不是不需要，而是还没到需要的时候。当前 10K 行 Web 代码中有 9K 行是在给假数据搭舞台。正确顺序是：引擎先跑通 → CLI 先做扎实 → CI 先跑起来 → 最后再上 Web Dashboard。**
