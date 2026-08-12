# SignOffAI DebugAgent 能力评估与改进方案

> 评估日期：2026-08-11
> 当前状态：**工具全部 mock，能力严重不足，必须重构**

---

## 一、当前能力评估

### 1.1 现有架构

```
DebugAgent
├── execute_task()
│   ├── 1. 收集仿真日志 (keyword grep, 硬编码路径 sim/dut/)
│   ├── 2. _classify_error() — 正则匹配分类 env/rtl/model/spec
│   ├── 3. _cross_check_design_model() — 比较 design vs model 字段计数
│   ├── 4. 合并结果
│   ├── 5. 写入 ctx 黑板书
│   └── 6. LLM 深度分析（可选）
│
└── _get_tools() → DebugTools.get_tools()
    ├── analyze_simulation_log()     ← 返回硬编码 JSON (mock)
    ├── analyze_waveform()           ← 返回硬编码 JSON (mock)
    ├── trace_error_source()         ← 返回硬编码 JSON (mock)
    └── generate_fix_suggestion()    ← 返回硬编码 JSON (mock)
```

### 1.2 能力评分

| 能力维度 | 当前得分 | 说明 |
|----------|---------|------|
| **日志解析** | 2/10 | 仅 keyword grep，"UVM_ERROR" 行提取，无结构化解析，无上下文 |
| **波形分析** | 0/10 | 完全 mock，零真实解析 |
| **根因定位** | 3/10 | 正则分类到 4 大类（env/rtl/model/spec），粒度太粗 |
| **自动修复** | 0/10 | 只"建议"哪个 agent 重跑，不修改代码 |
| **编译错误分析** | 0/10 | 完全不覆盖编译错误 |
| **跨阶段关联** | 3/10 | `_cross_check_design_model` 只比较了字段计数 |
| **增量调试** | 0/10 | 无 bisect、无 delta-debug |
| **历史学习** | 0/10 | 无历史 bug 库，每次从零开始 |
| **迭代验证** | 1/10 | 只有一次 LLM 调用，无假设→验证→排除循环 |

**综合：1.0/10 — 无法独立解决任何真实问题**

---

## 二、差距分析

### 2.1 核心问题：工具全 mock

```python
# debug_tools/main.py — 当前状态
@tool("analyze_simulation_log")
def analyze_simulation_log(log_path: str = "") -> str:
    """分析仿真日志，提取错误和警告"""
    return json.dumps({
        "log_file": log_path or "sim.log",
        "errors": [{"time": "450ns", "severity": "UVM_ERROR",
                     "message": "Scoreboard mismatch: expected 0xABCD1234, got 0xABCE1234"}],
        # ↑ 硬编码的假数据！
    }, indent=2)
```

**4 个工具全部如此。** Agent 调用这些工具得到假数据，LLM 基于假数据做推理，输出完全不可信。

### 2.2 日志解析太浅

当前 `_classify_error()` 只做简单的正则计数：

```python
env_hits = sum(1 for e in errors for p in ENV_PATTERNS if re.search(p, e, re.IGNORECASE))
```

问题：
- 只看包含 `UVM_ERROR`/`UVM_FATAL` 的行，忽略 Warning 和上下文
- 没有解析 UVM 的 `verbosity` 层级报告
- 没有提取时间戳关联多个错误的因果链
- 没有解析 UVM report_summary
- 路径硬编码 `sim/dut/`，不遵循 `regress_dir`

### 2.3 编译错误完全忽略

QuestSim 编译错误格式 `** Error: path/to/file.sv(123): ...` 没有被解析。RegressAgent 编译失败时，DebugAgent 拿不到编译日志。

### 2.4 无自动修复

`generate_fix_suggestion` 只返回文本建议，不会：
- 打开源文件定位具体行
- 生成修复 diff
- 调用 write_file 应用修复
- 重新触发编译验证

### 2.5 无迭代假设验证

设计文档描述的"假设→验证→排除→确认"循环不存在。只有一次 LLM 调用，输出就是最终结果。

---

## 三、改进方案

### 3.1 总目标

> DebugAgent 4.0：从 "建议重跑某个 agent" 升级为 **自动诊断→定位→修复→验证** 闭环。

### 3.2 新架构

```
DebugAgent 4.0
│
├── Phase 1: 收集 (Collect)
│   ├── collect_compile_log()       ← 解析 vlog 编译错误
│   ├── collect_sim_log()           ← 解析 vsim 仿真日志
│   ├── collect_waveform()          ← 解析 WLF/VCD 关键信号
│   └── collect_coverage_data()     ← 对比预期 vs 实际覆盖率
│
├── Phase 2: 分类 (Classify)
│   ├── classify_error()            ← 增强版：多级分类 + 置信度
│   ├── fingerprint_error()         ← 错误指纹（去重相似错误）
│   └── rank_by_impact()            ← 按影响排序修复优先级
│
├── Phase 3: 定位 (Locate)
│   ├── bisect_test()               ← 二分法定位哪个 test 引入失败
│   ├── bisect_code()               ← git bisect 定位哪个 commit
│   ├── trace_signal()              ← 信号反向追踪（fan-in cone）
│   └── cross_check_design_model()  ← 增强：字段级 diff
│
├── Phase 4: 修复 (Fix)
│   ├── auto_fix_compile()          ← 自动修复常见编译错误
│   ├── auto_fix_timing()           ← 自动修复 setup/hold violation
│   ├── auto_fix_uvm()              ← 自动修复 UVM config_db/phase 问题
│   └── generate_fix_diff()         ← 生成修复 patch
│
├── Phase 5: 验证 (Verify)
│   ├── recompile_check()           ← 重新编译确认修复
│   ├── rerun_failed_test()         ← 重跑失败 case
│   └── regression_smoke()          ← 快速回归确认无回归
│
└── Phase 6: 学习 (Learn)
    ├── record_bug_pattern()        ← 记录 bug 指纹到知识库
    └── suggest_pre_check()         ← 建议新增静态检查规则
```

### 3.3 工具改造明细

#### tool: `analyze_simulation_log` → `collect_sim_log`

```python
@tool("collect_sim_log")
def collect_sim_log(output_dir: str) -> str:
    """解析仿真日志，返回结构化错误树。

    真实解析:
    1. glob: output_dir/<regress_dir>/sim/dut/sim_*.log
    2. 提取 UVM report_summary 段落
    3. 按 UVM_ERROR / UVM_FATAL / UVM_WARNING 分组
    4. 提取每个错误的:
       - 时间戳 → 关联到具体 test phase
       - 文件:行号 → 关联到源码位置
       - 错误消息 + 上下文 (±5 行)
    5. 构建错误因果链 (同一时间窗口的错误关联)
    """
    # 真实实现...
```

#### tool: `analyze_waveform` → `collect_waveform`

```python
@tool("collect_waveform")
def collect_waveform(output_dir: str, signals: list = None) -> str:
    """解析波形文件 (WLF)，提取关键信号值。

    真实解析:
    1. 找到 output_dir/<regress_dir>/sim/dut/wave_*.wlf
    2. 使用 vsim -view 或 wlf2vcd 转换
    3. 对指定信号提取:
       - 最后 100ns 的值变化
       - X/Z 出现的时间点
       - 与期望值的差异时间点
    4. 返回时间线数据
    """
```

#### tool: `trace_error_source` → `bisect_test`

```python
@tool("bisect_test")
def bisect_test(output_dir: str, failed_tests: str) -> str:
    """二分法定位失败测试的最小集合。

    策略:
    1. 全部 N 个 test，先跑一半
    2. 如果失败 → 缩小范围到这一半
    3. 如果通过 → 扩大范围到另一半
    4. 迭代直到定位到最小失败集合
    5. 返回: {failing_tests, minimal_repro, estimated_root_cause}
    """
```

#### tool: `generate_fix_suggestion` → `auto_fix`

```python
@tool("auto_fix")
def auto_fix(error_info: str, output_dir: str) -> str:
    """自动修复常见问题并应用 patch。

    修复模板库:
    - "virtual interface not set"  → 在 build_phase 注入 config_db::set
    - "Module not defined"         → 检查 filelist 是否遗漏 .sv 文件
    - "X/Z detected"               → 在 reset 阶段加初始化
    - "setup timing violation"     → 调整 clock constraint 或加 pipeline
    - "scoreboard mismatch LSB"    → 检查 bit-width/padding

    流程:
    1. 匹配修复模板
    2. 定位源文件:行号
    3. 生成 diff
    4. write_file 应用
    5. 返回 {file, line, old, new, applied}
    """
```

### 3.4 新增工具清单

| 工具 | 真实能力 | 优先级 |
|------|---------|--------|
| `collect_compile_log` | 解析 vlog 编译错误，提取文件:行号:消息 | **P0** |
| `collect_sim_log` | 解析 vsim 仿真日志，结构化错误树 | **P0** |
| `collect_waveform` | 解析 WLF/VCD 提取关键信号时间线 | P1 |
| `bisect_test` | 二分法定位失败测试 | P1 |
| `bisect_code` | git bisect 定位引入 bug 的 commit | P2 |
| `auto_fix` | 模板匹配 + 自动生成修复 patch + 应用 | **P0** |
| `fingerprint_error` | 错误去重指纹（相同 bug 合并） | P1 |
| `rerun_failed_test` | 重跑失败 test 并对比结果 | P1 |
| `record_bug_pattern` | 记录 bug 指纹到 knowledge base | P2 |
| `signal_trace` | 信号 fan-in cone 反向追踪 | P2 |

### 3.5 分类粒度增强

当前 4 大类 → 细化为 12 类：

```python
ERROR_CATEGORIES = {
    # UVM 环境
    "uvm_config":     ["config_db", "set", "get", "virtual interface"],
    "uvm_phase":      ["phase", "objection", "timeout", "drain_time"],
    "uvm_factory":    ["factory", "type_id", "create", "override"],
    "uvm_sequencer":  ["sequencer", "sequence", "start_item", "finish_item"],
    "uvm_tlm":        ["TLM", "port", "export", "imp", "analysis"],

    # RTL 设计
    "rtl_xz":         ["X", "Z", "unknown", "high-impedance"],
    "rtl_timing":     ["setup", "hold", "violation", "slack"],
    "rtl_width":      ["width mismatch", "truncated", "extended"],
    "rtl_syntax":     ["already declared", "not defined", "syntax error"],

    # 编译
    "compile_syntax":  ["vlog-", "Error:", "near"],
    "compile_elab":    ["vopt-", "elaboration", "unresolved"],

    # 模型
    "model_mismatch":  ["predictor", "golden", "expected", "actual"],
}
```

---

## 四、迭代假设验证引擎

### 4.1 当前：单次 LLM 调用

```
输入 → LLM → 输出（无验证）
```

### 4.2 改进：多轮假设驱动

```python
async def _hypothesis_loop(self, errors, max_rounds=5):
    """
    1. Form hypothesis: "Root cause is X because Y"
    2. Verify:       run specific check against hypothesis
    3. Eliminate:    if falsified, discard and form new hypothesis
    4. Confirm:      if verified, produce fix
    5. Iterate:      repeat until root cause found or max rounds
    """
    hypotheses = []
    for round in range(max_rounds):
        # LLM 基于当前证据提出假设
        hypo = await self._form_hypothesis(errors, hypotheses, round)
        if not hypo:
            break

        # 验证假设（执行具体检查）
        verify_result = await self._verify_hypothesis(hypo)

        if verify_result["confirmed"]:
            # 生成修复
            fix = await self._generate_fix(hypo, verify_result)
            # 应用并验证
            apply_result = await self._apply_and_verify(fix)
            if apply_result["fixed"]:
                return {"root_cause": hypo, "fix": fix, "verified": True, "rounds": round+1}

        hypotheses.append({"hypothesis": hypo, "result": verify_result, "round": round})

    return {"root_cause": None, "hypotheses": hypotheses, "verified": False}
```

---

## 五、修复模板库

### 5.1 常见编译错误自动修复

| 错误模式 | 自动修复 |
|----------|---------|
| `Module "X" not defined` | 检查 filelist 遗漏 → 追加 `+incdir+` 或 `.sv` 文件 |
| `already declared in this scope` | 删除重复 import/include |
| `could not find package "X"` | 追加 `-y` 或 `+libext+` 到 vlog 命令 |
| `virtual interface not set` | 在 test.build_phase 注入 `uvm_config_db::set("*.env.*", "vif", vif)` |
| `Port "X" not found in module "Y"` | 检查 interface 端口名是否与 RTL 一致 |

### 5.2 常见仿真错误自动修复

| 错误模式 | 自动修复 |
|----------|---------|
| `UVM_FATAL @ 0ns: NOVIF` | 在 top_tb 中加入 `uvm_config_db::set(..., "*", "vif", intf)` |
| `Scoreboard mismatch (LSB)` | 检查位宽对齐 → 加 `$size()` 检查 + auto-pad |
| `Sequence timeout` | 增加 `drain_time` 或检查 `raise_objection`/`drop_objection` |
| `UVM_ERROR: driver got X on pin` | 检查 reset 释放时序 → 在 reset 期间 drive 确定值 |

---

## 六、与其他 Agent 的协作改进

### 6.1 与 regress_cov 协作

```
regress_cov: compile → sim → 收集失败 test list
    │
    ▼
debug:    接收失败列表 → 分类 → 定位根因 → 修复
    │
    ├── 修复成功 → 通知 regress_cov 重跑
    └── 无法修复 → 通知 qa 标记 waive/known issue
```

### 6.2 与 assert 协作

```
assert 生成 SVA → regress_cov 仿真触发 assertion fail
    │
    ▼
debug:    读取 assertion fail 消息
    │       提取: 时间戳、信号名、期望值 vs 实际值
    │
    ▼
    溯源定位 → 是 RTL bug 还是 assertion 写错了
```

### 6.3 与 test 协作

```
test 生成 case → regress_cov 仿真
    │
    ├── case PASS → 正常
    └── case FAIL → debug 分析
                      ├── case 本身 bug → 反馈给 test 修正
                      └── RTL/env bug → debug 自动修复
```

---

## 七、实施优先级

| 优先级 | 改动 | 预期收益 | 工作量 |
|--------|------|---------|--------|
| **P0** | `collect_sim_log` — 真实日志解析 | DebugAgent 有真实输入 | 2天 |
| **P0** | `collect_compile_log` — 编译错误解析 | 覆盖编译失败场景 | 1天 |
| **P0** | `auto_fix` — 自动修复模板库 (Top 10) | 80% 常见问题自动修复 | 3天 |
| **P0** | 分类粒度 4→12 类 | 准确路由到正确的 agent | 0.5天 |
| P1 | `bisect_test` — 测试二分定位 | 快速缩小失败范围 | 1天 |
| P1 | 迭代假设验证引擎 | 从 "猜一次" 到 "验证后确认" | 2天 |
| P1 | `rerun_failed_test` — 修复后验证 | 确保修复有效 | 0.5天 |
| P1 | `fingerprint_error` — 错误去重 | 相同 bug 不重复分析 | 1天 |
| P2 | `collect_waveform` — 真实波形解析 | 定位时序问题 | 3天 |
| P2 | `bisect_code` — git bisect | 定位引入 bug 的 commit | 1天 |
| P2 | `record_bug_pattern` — 知识库 | 历史学习，预防复发 | 2天 |
| P3 | `signal_trace` — fan-in cone | 复杂 RTL bug 定位 | 3天 |

---

## 八、结论

**当前 DebugAgent 评分：1.0/10**，核心问题：
1. 4 个工具全 mock，返回假数据
2. 日志解析只有 keyword grep
3. 无自动修复能力
4. 无迭代验证循环

**升级到 DebugAgent 4.0 后预期评分：7.5/10**：
- P0 完成后 → 4.0/10（有真实输入+基础自动修复）
- P1 完成后 → 6.5/10（有迭代验证+二分定位）
- P2+P3 完成后 → 7.5/10（波形分析+历史学习）

**P0 投入 6.5 天，即可覆盖 80% 的常见调试场景。**
