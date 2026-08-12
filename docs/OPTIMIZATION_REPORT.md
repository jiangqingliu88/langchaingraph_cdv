# SignOffAI 全面优化报告

> 优化日期：2026-08-12
> 目标：CLI 体验 / Agent 管道 / Tool 集成 三项从 5.7/10 → 7/10

---

## 一、CLI 体验优化

### 1.1 UTF-8 中文乱码修复

**问题**：Windows 终端默认 GBK 编码，structlog 中文日志全部乱码。

**修复**：CLI 入口强制 UTF-8 编码
```python
# src/cli/commands.py (新增)
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
```

### 1.2 vagent 安装支持

```bash
pip install -e .
vagent --help
vagent verify spec.md --compile
vagent signoff <run_id>
vagent dump <run_id>
```

`pyproject.toml` 已配置：
```toml
[project.scripts]
vagent = "src.cli.commands:cli"
```

### 1.3 CLI 命令矩阵

| 命令 | 功能 | 状态 |
|------|------|------|
| `vagent verify` | 完整验证管线 (--gate/--no-gate/--approval) | ✅ |
| `vagent init` | 初始化输出目录 | ✅ |
| `vagent signoff generate/export/verify` | 签核报告生成/导出/校验 | ✅ |
| `vagent dump` | 复现 + 导出签核证据包 | ✅ |
| `vagent status` | 查询运行状态 | ✅ |
| `vagent pipeline list/graph` | 管线查看 | ✅ |
| `vagent coverage report/gaps/trend/merge` | 覆盖率管理 | ✅ |
| `vagent diff coverage` | 覆盖率对比 | ✅ |
| `vagent tool call` | 直接调用 Tool | ✅ |

---

## 二、Agent 管道优化

### 2.1 门禁机制

每个阶段有最低质量分数，低于门槛管线 HALT：

| 阶段 | 门槛 | 类型 |
|------|------|------|
| spec | 55 | 🟡 中等 |
| UVM | 70 | 🔴 严格 |
| regress_cov | 50 | 🔴 严格 |
| qa | 50 | 🟡 中等 |
| docs/vclose | 0 | ⚪ 不卡 |

默认关闭，`--gate` 开启：
```bash
vagent verify spec.md --gate              # 开启门禁
vagent verify spec.md                     # 无门禁（调试用）
```

### 2.2 反馈回路

regress_cov 覆盖率 < 95% 时自动回退 test 补 case：

```
regress_cov → coverage < 95% → 注入 gap 建议 → test → regress_cov (max 2轮)
```

### 2.3 审批门控

高风险阶段（UVM、regress_cov、qa）支持人工审批：

```bash
vagent verify spec.md --approval interactive  # 每阶段询问 y/n
vagent verify spec.md --approval auto         # 全自动（默认）
vagent verify spec.md --approval threshold    # 风险 > high 才审批
```

### 2.4 Token 预算追踪

每个 pipeline run 自动追踪 LLM token 用量：

```json
{
  "governance": {
    "token_budget": {
      "total_tokens": 45000,
      "llm_calls": 23,
      "limit": 200000
    }
  }
}
```

### 2.5 审计 Hash 链

每个阶段记录输入数据 hash：

```json
{
  "name": "regress_cov",
  "score": 50,
  "input_hash": "a3f8b2c1"   // ← 输入数据的版本指纹
}
```

---

## 三、Tool 集成优化

### 3.1 Schema 契约

| 工具集 | schema.yaml | Tool 数量 |
|--------|:---:|------|
| uvm_tools | ✅ 已有 | 10 |
| testcase_tools | ✅ **新增** | 7 |
| debug_tools | ✅ **新增** | 7 |

每个 tool 的 schema 包含：
- `input` — 参数定义（类型、是否必填、描述）
- `output` — 输出格式 + JSON Schema
- `risk_level` — safe / medium / high
- `side_effects` — 副作用说明（如写文件、修改源码）

### 3.2 QuestaSim 路径自动检测

优先级：
1. 环境变量 `QUESTA_HOME`
2. 8 个常见安装路径
3. `PATH` 中搜索 `vlog.exe`
4. 回退默认值

```bash
# 设置环境变量
export QUESTA_HOME=/opt/mentor/questasim/bin
```

### 3.3 Debug Tools：全真实实现

| 工具 | 能力 | 状态 |
|------|------|------|
| `collect_sim_log` | 解析 vsim 日志 → 结构化错误树 | ✅ 真实 |
| `collect_compile_log` | 解析 vlog 编译错误 | ✅ 真实 |
| `collect_waveform` | WLF/VCD 信号提取 | ✅ 真实 |
| `fingerprint_error` | 错误 MD5 指纹去重 | ✅ 真实 |
| `bisect_test` | 二分定位失败 case | ✅ 真实 |
| `auto_fix` | 8 个修复模板 → 自动修 | ✅ 真实 |
| `rerun_failed_test` | 重跑验证修复 | ✅ 真实 |

### 3.4 Testcase Tools：覆盖率点生成

```bash
# 7 个 tool 完整链路
parse_test_points → map_policies_to_tests → build_scenario_yaml
  → generate_coverage_points  ← 新增：spec → covergroup SV
  → generate_test_cases
  → check_test_coverage
```

---

## 四、优化前后对比

| 维度 | 优化前 | 优化后 | 改善 |
|------|--------|--------|------|
| CLI 体验 | 6/10 | **7/10** | UTF-8、vagent 可安装 |
| Agent 管道 | 5/10 | **7/10** | 门禁、审批、Token、Hash |
| Tool 集成 | 6/10 | **7/10** | 2 个 schema.yaml、QuestaSim 检测 |
| 可复现 | 5/10 | **6/10** | vagent dump + hash 链 |
| 可审计 | 4/10 | **7/10** | 阶段 hash + 字段级 snapshot + cross-run diff |
| 可治理 | 1/10 | **5/10** | 审批接真 + Token + 门禁 |
| 可交付 | 5/10 | **6/10** | docs 移到 regress_cov 后 |
| **综合** | **5.7/10** | **6.7/10** | |

---

## 五、三层兜底机制（7→8+）

### 架构

```
Agent 执行完毕
    │
    ▼
Layer 1: 确定性校验
    │  ├── spec: design_name 不是占位符? interfaces 有信号?
    │  ├── design: function_hier 存在? registers 非空?
    │  ├── uvm: quality_report.json PASS? 8 个文件存在?
    │  ├── test: constraint.yaml 可解析? scenarios 非空?
    │  └── regress_cov: report.json 存在? pass_rate > 0?
    │
    ├── PASS → 继续
    │
    ├── FAIL → Layer 2: 自动回退
    │           ├── spec: 正则提取模块名/特性/接口/测试点
    │           └── test: 矩阵模式生成
    │           → 回退通过但降分 (score=50)
    │
    └── FAIL → Layer 3: 人机协作
                ├── 展示诊断上下文
                ├── [r] 重试 LLM / [f] 接受回退 / [s] 跳过 / [a] 终止
                └── CI 模式自动 fallback (不打扰)
```

### QualityGuard 统计

管线结束输出：
```json
{
  "governance": {
    "quality_guard": {
      "total_validated": 8,
      "passed_directly": 5,       // 5 个阶段 LLM 输出直接合格
      "fallback_used": 2,         // 2 个阶段走了规则回退
      "escalated_to_human": 1,    // 1 个阶段升级人工决策
      "llm_dependency_pct": 62.5  // LLM 依赖度 62.5%
    }
  }
}
```

### 使用方式

```bash
# 交互模式：失败时询问
vagent verify spec.md --approval interactive

# CI 模式：失败时自动 fallback
vagent verify spec.md --approval auto --json
```

## 六、下一步达到 8/10

| 优先级 | 改动 | 预期收益 |
|--------|------|---------|
| P0 | UVM 阶段编译通过率提升（修复 DEGRADED 根因） | 管道稳定性 +1 |
| P1 | auto_fix 模板从 8→20 个 | 调试自动化 +1 |
| P1 | regress_cov 反馈回路实测验证 | 覆盖率收敛 +1 |
| P2 | `vagent dump` 端到端验证 | 可复现 +1 |
| P2 | 错误信息友好化（替换 traceback 为中文提示） | CLI 体验 +1 |
