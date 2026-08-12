# SignOffAI Demo 演示指南

> 面试演示用 — 展示 IC 验证从"手工作坊"到"工程平台"的完整技术方案

---

## 一、项目定位（30秒）

**SignOffAI** = IC 验证的 AI 驱动工程平台。

不是"辅助写代码的 AI 工具"，而是把规格分析→UVM 生成→测试生成→回归→覆盖率→签核变为**可编程、可审计、可治理的工程系统**。

```
核心理念: LLM 不决定结构，LLM 只做"完形填空"
         └── UVM 骨架由 Jinja2 模板渲染
         └── 策略由规则引擎推断
         └── 三层兜底: 确定性校验 → 自动回退 → 人机协作
```

---

## 二、架构总览（1分钟）

```
┌─────────────────────────────────────────────────┐
│              SignOffAI 平台                      │
│                                                 │
│  CLI (vagent)  ←→  Web API (FastAPI)           │
│         │                  │                     │
│         ▼                  ▼                     │
│  ┌─────────────────────────────────────────┐    │
│  │        Pipeline Execution Engine         │    │
│  │  13 phases | gates | feedback loop       │    │
│  │  Harness: snapshots + timeout + retry    │    │
│  │  QualityGuard: 3-layer safety net       │    │
│  └─────────────────────────────────────────┘    │
│         │                  │                     │
│         ▼                  ▼                     │
│  ┌──────────┐    ┌──────────────────┐           │
│  │ 11 Agents│    │   22 Tools       │           │
│  │ 黑板书通信│    │   schema 契约     │           │
│  │ ReAct循环│    │   EDA 深度集成    │           │
│  └──────────┘    └──────────────────┘           │
└─────────────────────────────────────────────────┘
```

---

## 三、演示流程（5分钟）

### 步骤 1: 启动服务

```bash
cd D:/SignOffAI
BOOTSTRAP_ADMIN_PASSWORD=admin123 python -m uvicorn src.web.api:app --host 0.0.0.0 --port 8000
```

打开 `http://localhost:8000` → 登录 `admin / admin123`

### 步骤 2: 展示 CLI 核心能力

```bash
# 安装 CLI
pip install -e .

# 快速验证: 只跑规格分析
vagent verify specs/apb_uart/apb_uart_spec.md --profile spec_only

# 输出:
#   spec: PASS score=85 (32.3s)
#   Passed: 1/1  Score: 85/100
```

### 步骤 3: 展示 Web 前端（边说边点）

| 页面 | 展示什么 | 说明 |
|------|---------|------|
| **流水线** | 12 个 Profile 下拉 | "选择不同场景——Spec变更、RTL更新、覆盖率回归..." |
| | 门禁开关 + 审批模式 | "质量不达标自动阻断" |
| | 输出目录 + 超时 | "完全可配置的执行参数" |
| **治理总览** | 4 个统计卡片 | "每次运行自动生成治理报告" |
| | 质量守护/Token/Harness | "LLM依赖度、回退次数、快照数" |
| **审计 Diff** | 输入两个 Run ID | "字段级精确定位两次签核差异" |
| **覆盖率** | Gap 分析 + 增补建议 | "自动分析空洞并建议补什么 case" |

### 步骤 4: 展示后端能力（API 演示）

```bash
# 13 个核心 API
curl http://localhost:8000/api/pipeline/profiles  # 12 profiles
curl http://localhost:8000/api/dashboard/stats    # 治理数据
curl http://localhost:8000/api/manifest/diff?run_a=..&run_b=..
```

---

## 四、核心技术亮点

### 4.1 13 阶段验证管线

```
spec → design → model → rtl → UVM → test ∥ assert → regress_cov → debug → docs(5路并行) → qa → report → vclose
```

- 并行执行: test+assert 同时跑
- 反馈回路: regress_cov 覆盖率<95% → 自动回退 test 补 case
- 门禁机制: 每个阶段最低分数，不达标即阻断

### 4.2 三层兜底（QualityGuard）

```
Layer 1: 确定性校验
  └── spec: design_name 不能是 "dut/top/block"
  └── uvm: 8 个 SV 文件必须存在
  └── regress_cov: report.json 必须有 pass_rate

Layer 2: 自动回退
  └── spec: 正则提取 → 不调 LLM
  └── test: 矩阵模式生成 → 不调 LLM

Layer 3: 人机协作
  └── 诊断上下文 → [r]etry / [f]allback / [s]kip / [a]bort
```

### 4.3 字段级审计（Manifest Diff）

```json
// 两次签核精确对比
{
  "phase_diffs": {
    "spec": {
      "changed_fields": ["spec.features"],   // 只有这个字段变了
      "unchanged": 6                          // 其余 6 个未变
    }
  }
}
```

### 4.4 双角色设计

| UVM 工程师 | Test 工程师 |
|-----------|-----------|
| regress_dir: uvm_regress | regress_dir: test_regress |
| 编译到 uvm_regress/build/work | 编译到 test_regress/build/work |
| focus: env + P0 case | focus: 场景 + 随机 + 覆盖率 |

### 4.5 22 个 Tool + Schema 契约

```
uvm_tools (10):   find_spec_yaml → jinja_render → check_static/compile/loopback
testcase_tools (7): parse → map → build → coverage_points → generate → check
debug_tools (7):   collect_sim_log → collect_compile_log → auto_fix(20模板) → bisect → rerun
assertion_tools (8): 真实 SVA 生成（非 mock）
```

所有 Tool 有 `schema.yaml` 定义输入/输出/风险等级。

### 4.6 Harness 安全执行

```
snapshot → 超时保护 → 退避重试 → 人工中断标记(.harness_pause) → 恢复
```

---

## 五、演示数据

```bash
# 用项目内置的 APB UART Spec
specs/apb_uart/apb_uart_spec.md  (1380 字符 Markdown)

# 可选的 12 个 Profile:
spec_only | design_only | quick | standard | full
spec_update | rtl_update | uvm_update | model_update
regress_cov | regress_xprop | debug
```

---

## 六、面试话术建议

### 开场（价值观）
"IC 验证最大的问题是：签核靠个人经验，流程不可复现。我们做了一个平台，把整个验证流程变成了可编程、可审计、可治理的工程系统。"

### 架构（差异化）
"和 Copilot/Cursor 不一样——我们不是'辅助写代码'，而是把 LLM 嵌入到 UVM 骨架 + Jinja2 渲染 + 契约校验的工程流程里。LLM 只做填空，不决定结构。"

### 三层兜底（技术深度）
"LLM 的确定性是天花板。我们设计了三层兜底：确定性校验规则、模板回退策略、人机协作升级。每个 Agent 输出都要过这三关。"

### 双角色（业务理解）
"验证团队有两个角色——UVM 工程师管环境，Test 工程师补 case。我们的平台从编译路径到功能按钮都做了角色区分。"

### 结果（数据）
"22 个 Tool，13 阶段管线，12 个 Profile，20 页面 Web 前端，字段级审计 Diff——全部从零搭建，CLI + API 双通道可用。"
