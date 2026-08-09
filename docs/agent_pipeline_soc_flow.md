# SignOffAI SoC 级 Agent 流水线

> 日期：2026-08-09
> 流水线对标 OpenTitan `top_earlgrey` SoC 全流程

---

## 1. 完整流水线（20 阶段）

```
┌──────────────────────────────────────────────────────────────────────────┐
│  Phase  阶段              Agent/Engine        产出                        │
├──────────────────────────────────────────────────────────────────────────┤
│                            === 前端: AI 生成 ===                          │
│                                                                          │
│   1    spec              spec_planner         chip.spec + ip.*.spec       │
│   2    design_arch       design_architect     chip.design_arch            │
│   3    model             model_agent          ip.*.model                  │
│                                                                          │
│                            === 设计质量: 工具链 ===                        │
│                                                                          │
│   4    lint              lint_engineer        chip.lint_report            │
│   5    cdc               cdc_engineer         chip.cdc_report             │
│   6    rdc               rdc_engineer         chip.rdc_report             │
│   7    syn               syn_engineer         chip.syn_report             │
│                                                                          │
│                            === 验证: AI + dvsim ===                       │
│                                                                          │
│   8    vplan             vplan_generator      chip.testplan + ip.*.testplan│
│   9    tpoint            testpoint_decomp     chip.tpoints + ip.*.tpoints │
│  10    rtm               trace_matrix         chip.rtm                    │
│  11    UVM               verification_arch    ip.*.env                    │
│  12    test              test_engineer        ip.*.tests                  │
│  13    assert            assertion_engineer   ip.*.sva                    │
│  14    regress           regression_manager   ip.*.regression + chip.regression │
│  15    cover             coverage_manager     ip.*.coverage + chip.coverage │
│  16    debug             debug_engineer       ip.*.debug + chip.debug     │
│                                                                          │
│                            === 签核: AI + 人工 ===                        │
│                                                                          │
│  17    formal            formal_engineer      chip.formal_report          │
│  18    qa                quality_assurance    chip.qa_report              │
│  19    report            report_generator     chip.signoff_report         │
│  20    signoff           signoff_service      chip.signoff + evidence.zip │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Agent I/O 契约（SoC 层级）

```python
FULL_SOC_PHASES = [
    # ── 前端: AI 生成 ──
    ("spec",       "spec_planner",          None,  False,  ["chip.spec"]),
    ("design",     "design_architect",      None,  False,  ["chip.spec"]),
    ("model",      "model_agent",           None,  False,  ["ip.*.spec", "ip.*.design_arch"]),

    # ── 设计质量: 工具链 ──
    ("lint",       "lint_engineer",         None,  False,  ["chip.design_arch", "ip.*.rtl"]),
    ("cdc",        "cdc_engineer",          None,  False,  ["chip.design_arch"]),
    ("rdc",        "rdc_engineer",          None,  False,  ["chip.design_arch"]),
    ("syn",        "syn_engineer",          None,  False,  ["chip.design_arch"]),

    # ── 验证: AI + dvsim ──
    ("vplan",      "vplan_generator",       None,  False,  ["ip.*.spec"]),
    ("tpoint",     "testpoint_decomp",      None,  False,  ["chip.testplan"]),
    ("rtm",        "trace_matrix",          None,  False,  ["chip.testplan", "ip.*.testplan"]),
    ("UVM",        "verification_architect",None,  False,  ["ip.*.spec", "ip.*.design_arch"]),
    ("test",       "test_engineer",         None,  False,  ["ip.*.env", "ip.*.testplan"]),
    ("assert",     "assertion_engineer",    None,  False,  ["ip.*.spec", "ip.*.env"]),
    ("regress",    "regression_manager",    None,  False,  ["ip.*.env", "ip.*.tests", "ip.*.sim_cfg"]),
    ("cover",      "coverage_manager",      None,  False,  ["ip.*.regression"]),
    ("debug",      "debug_engineer",        None,  False,  ["ip.*.regression", "ip.*.coverage"]),

    # ── 签核: AI + 人工 ──
    ("formal",     "formal_engineer",       None,  False,  ["chip.design_arch"]),
    ("qa",         "quality_assurance",     None,  False,  ["ip.*.coverage", "chip.coverage",
                                                            "chip.lint_report", "chip.cdc_report"]),
    ("report",     "report_generator",      None,  False,  ["chip.qa_report", "chip.coverage"]),
    ("signoff",    "signoff_service",       None,  False,  ["chip.report", "chip.qa_report"]),
]
```

---

## 3. 新增 Agent（5 个）

| Agent | consumes | produces | 工具 |
|-------|----------|----------|------|
| `lint_engineer` | `chip.design_arch`, `ip.*.rtl` | `chip.lint_report` | Verilator / AscentLint |
| `cdc_engineer` | `chip.design_arch` | `chip.cdc_report` | SpyGlass CDC / Meridian CDC |
| `rdc_engineer` | `chip.design_arch` | `chip.rdc_report` | Meridian RDC |
| `syn_engineer` | `chip.design_arch` | `chip.syn_report` | Design Compiler / Yosys |
| `formal_engineer` | `chip.design_arch` | `chip.formal_report` | JasperGold / VC-Formal |

---

## 4. 执行模式

```bash
# 全流程（AI 生成 → 工具检查 → dvsim 回归 → 签核）
vagent verify --workflow full_soc --spec specs/earlgrey_spec.md

# 只跑设计质量检查（lint + cdc + rdc）
vagent verify --workflow design_quality

# 只跑验证（UVM → test → regress → cover）
vagent verify --workflow verification --backend dvsim

# 只跑签核（formal + syn + qa + report + signoff）
vagent verify --workflow signoff_gate

# 增量：只重跑失败的 IP
vagent verify --workflow verification --retry-failed --scope ip.uart
```

---

## 5. 新增的 ContextStore keys

```
chip.lint_report          ← Lint 检查结果
chip.cdc_report           ← CDC 检查结果
chip.rdc_report           ← RDC 检查结果
chip.syn_report           ← 综合结果（时序/面积/功耗）
chip.formal_report        ← 形式验证结果
chip.qa_report            ← 质量审查结论
```

---

## 6. 目录 → Agent 映射

```
hw/top_earlgrey/lint/     →  lint_engineer      (读取 chip_lint_cfg.hjson)
hw/top_earlgrey/cdc/      →  cdc_engineer       (读取 chip_cdc_cfg.hjson)
hw/top_earlgrey/rdc/      →  rdc_engineer       (读取 chip_rdc_cfg.hjson)
hw/top_earlgrey/syn/      →  syn_engineer       (读取 chip_syn_cfg.hjson)
hw/top_earlgrey/formal/   →  formal_engineer    (读取 chip_formal_cfg.hjson)
hw/top_earlgrey/dv/       →  regression_manager (读取 chip_sim_cfg.hjson)
hw/ip/*/dv/               →  regression_manager (读取 ip.*.sim_cfg)
```
