# SignOffAI 团队角色管理设计

> 日期：2026-08-09  
> 参考：芯片公司设计+验证双线组织结构

---

## 1. 芯片公司标准组织架构

```
                              ┌─────────────────────┐
                              │   Project Manager    │
                              │  (进度/资源/里程碑)    │
                              └──────────┬──────────┘
                                         │
                   ┌─────────────────────┴─────────────────────┐
                   │                                           │
     ┌─────────────┴─────────────┐           ┌─────────────────┴─────────────┐
     │  Front-End Design Manager │           │  DV Manager                   │
     │  (前端设计经理)             │           │  (DV验证经理)                   │
     │                           │           │                               │
     │  负责: RTL → Syn → 静态签核 │           │  负责: 动态仿真 → 功能签核        │
     │  交付: gate-level netlist  │           │  交付: signoff report          │
     └─────────────┬─────────────┘           └─────────────────┬─────────────┘
                   │                                           │
    ┌──────────────┼──────────────┐              ┌─────────────┼─────────────┐
    │              │              │              │             │             │
┌───┴───────┐ ┌───┴───────┐ ┌───┴───────┐ ┌────┴────┐ ┌────┴────┐ ┌────┴────┐
│RTL Design │ │Static Verif│ │PPA Lead  │ │SoC DV   │ │IP DV   │ │DV Infra │
│Lead       │ │Lead        │ │          │ │Lead     │ │Lead    │ │         │
│           │ │            │ │          │ │         │ │        │ │         │
│UART RTL   │ │Lint        │ │Synthesis │ │Chip TB  │ │UART DV │ │EDA工具链  │
│DMA RTL    │ │CDC         │ │PPA(noSDF)│ │seq_lib  │ │DMA DV  │ │CI/CD    │
│GPIO RTL   │ │RDC         │ │STA Setup │ │Cross-IP │ │GPIO DV │ │VIP库     │
│SoC Top    │ │Formal      │ │          │ │         │ │        │ │         │
└───────────┘ └────────────┘ └──────────┘ └─────────┘ └────────┘ └─────────┘
```

---

## 2. 两大阵营职责边界

```
┌──────────────────────────────────────────────────────────────────┐
│                      DESIGN 侧（静态）                              │
│                                                                  │
│  RTL Design   →  写 Verilog/VHDL                                  │
│  Lint         →  静态代码规则检查（Verilator/SpyGlass）             │
│  CDC          →  静态时钟域 crossing 检查（无仿真）                  │
│  RDC          →  静态复位域 crossing 检查（无仿真）                  │
│  Formal       →  静态形式验证（JasperGold/VC-Formal）               │
│  Synthesis    →  逻辑综合（DC/Genus）                               │
│  PPA (no SDF) →  综合后 PPA 收敛（功耗/性能/面积）                   │
│                  - 无 SDF 反标（pre-layout）                       │
│                  - 基于 wire-load model 或 zero-wire-load          │
│                  - 目标: timing slack ≥ 0, power ≤ target,         │
│                    area ≤ budget                                  │
├──────────────────────────────────────────────────────────────────┤
│                      DV 侧（动态）                                  │
│                                                                  │
│  UVM Env      →  搭建验证环境                                      │
│  Testcase     →  编写测试用例                                      │
│  Assertion    →  SVA 动态断言                                      │
│  Regression   →  仿真回归（VCS/Xcelium）                            │
│  Coverage     →  代码 + 功能覆盖率                                  │
│  Debug        →  失败定位 + 根因分析                                │
│  Signoff      →  功能签核                                          │
└──────────────────────────────────────────────────────────────────┘
```

---

## 3. 角色定义（10 个角色）

### 3.1 Design 侧

| 角色 | 代号 | 职责 | 审批权限 |
|------|:---:|------|:---:|
| **Front-End Design Manager** | `fe_design_mgr` | RTL 交付 + 静态签核总负责 | 所有前端设计侧签核 |
| **RTL Design Lead** | `rtl_lead` | 管理 RTL 编码团队（按 IP 分配） | IP 级 RTL 代码 review |
| **RTL Design Engineer** | `rtl_eng` | 写 RTL 代码、修复设计 bug | 无 |
| **Static Verification Lead** | `static_lead` | 管理 Lint/CDC/RDC/Formal 团队 | 静态检查结论审批 |
| **Static Verification Eng** | `static_eng` | Lint / CDC / RDC / Formal 执行 | 无 |
| **PPA Lead** | `ppa_lead` | 管理 Synthesis/STA/PPA 收敛 | PPA signoff |
| **PPA Engineer** | `ppa_eng` | 综合 / STA setup / PPA 分析（无 SDF） | 无 |

### 3.2 DV 侧

| 角色 | 代号 | 职责 | 审批权限 |
|------|:---:|------|:---:|
| **DV Manager** | `dv_mgr` | 全芯片验证策略 + 功能签核 | 所有 DV 侧签核 |
| **SoC DV Lead** | `soc_dv_mgr` | 芯片级验证（CHIP/ST） | chip 级功能签核 |
| **IP DV Lead** | `ip_dv_mgr` | 模块级验证（BT/UT） | IP 级功能签核 |
| **DV Engineer** | `dv_eng` | 日常验证开发 | 无 |
| **DV Infrastructure Eng** | `dv_infra` | EDA 工具/CI/CD/VIP 库 | 无 |

### 3.3 全局

| 角色 | 代号 | 职责 | 审批权限 |
|------|:---:|------|:---:|
| **Project Manager** | `pm` | 进度/资源/里程碑/外部协调 | 项目创建/归档 |
| **Viewer** | `viewer` | 只读（管理层/外部审计） | 无 |

---

## 4. 权限矩阵（核心截取）

```
                      fe_design rtl   static static ppa   ppa   dv_   soc_dv ip_dv dv_  dv_    pm   viewer
                      _mgr      lead  _lead  _eng   lead  _eng  mgr   _mgr   _mgr  eng  infra
                        _lead   _eng  _eng    _eng   lead  _lead  _lead _eng infra
────────────────────────────────────────────────────────────────────────────────────────────
Design 侧
  RTL 代码提交           ✅      ✅    -       -      -     -      -     -    -      -    -
  Lint 执行 & 审批        ✅      -     ✅      -      -     -      -     -    -      -    -
  CDC 执行 & 审批         ✅      -     ✅      -      -     -      -     -    -      -    -
  RDC 执行 & 审批         ✅      -     ✅      -      -     -      -     -    -      -    -
  Formal 执行 & 审批      ✅      -     ✅      -      -     -      -     -    -      -    -
  Synthesis 执行          ✅      -     -       ✅     -     -      -     -    -      -    -
  PPA Signoff (no SDF)    ✅      -     -       ✅     -     -      -     -    -      -    -

DV 侧
  Spec 编辑              ✅      ✅    -       -      ✅    ✅     ✅    ✅(own) -    -    -
  Testplan 编辑          -       -     -       -      ✅    ✅     ✅    ✅(own) -    -    -
  UVM Env 生成           -       -     -       -      ✅    ✅     ✅    ✅(own) -    -    -
  Testcase 编写          -       -     -       -      ✅    ✅     ✅    ✅(own) -    -    -
  Regression 启动        -       -     -       -      ✅    ✅     ✅    ✅(own) -    -    -
  Coverage 分析          -       ✅    -       -      ✅    ✅     ✅    ✅(own) -    ✅   ✅
  Debug 分析             -       ✅    -       -      ✅    ✅     ✅    ✅(own) -    -    -
  DV Signoff             -       -     -       -      ✅    ✅     ✅    -    -      -    -

全局
  最终 Tapeout Signoff    ✅      -     -       -      ✅    -      -     -    -      ✅   -
```

---

## 5. 两阶段签核链

```
                            Design Signoff                    DV Signoff
                           (静态, 由 fe_design_mgr)            (动态, 由 dv_mgr)
                           ════════════════                 ══════════════

D1 (设计启动)              RTL 代码完成
                           Lint clean               ←→     Spec 完成
                                                           Testplan draft

D2 (设计冻结)              CDC clean                        V1 (冒烟通过)
                           RDC clean                        Smoke test PASS
                           Formal pass                      基础 UVM env ready

D3 (设计签核)              Synthesis pass                   V2 (功能验证)
                           PPA converge (no SDF)            全部 tests PASS
                           STA setup ready                  代码覆盖率 ≥95%
                                                           功能覆盖率 ≥100%

                                                           V3 (签核收敛)
                                                           无未关闭 P0/P1 bug
                                                           Checklist 全部 Done

═══════════════════════════════════════════════════════════════════════════
                        TAPEOUT (pm + fe_design_mgr + dv_mgr 三方签字)
```

---

## 6. 静态检查 → 工具映射

| 检查项 | 工具 | 输入 | 产出 | 角色 |
|--------|------|------|------|:---:|
| **Lint** | Verilator / SpyGlass | RTL `.sv` | `chip_lint_cfg.hjson` + waiver | `static_eng` |
| **CDC** | SpyGlass CDC / Meridian CDC | RTL + clock domains | `chip_cdc_cfg.hjson` + waiver | `static_eng` |
| **RDC** | Meridian RDC | RTL + reset domains | `chip_rdc_cfg.hjson` + waiver | `static_eng` |
| **Formal** | JasperGold / VC-Formal | RTL + properties | `chip_formal_cfg.hjson` | `static_eng` |
| **Synthesis** | DC / Genus / Yosys | RTL + SDC + lib | `chip_syn_cfg.hjson` + netlist | `ppa_eng` |
| **PPA (no SDF)** | PrimeTime / Tempus | netlist + SDC (无 SDF) | PPA report (timing/power/area) | `ppa_eng` |

### PPA 收敛目标（无 SDF，pre-layout）

```yaml
ppa_targets:
  timing:
    clock_period_ns: 10          # 100 MHz
    wns_target_ns: 0             # Worst Negative Slack ≥ 0
    tns_target_ns: 0             # Total Negative Slack = 0
    setup_margin_pct: 10         # 10% setup margin for post-layout degradation
  power:
    total_power_mw: 50           # < 50 mW
    leakage_power_mw: 5          # < 5 mW
  area:
    total_area_um2: 500000       # < 500,000 μm²
    utilization_pct: 70           # < 70%
```

---

## 7. `.signoffai.yaml` 扩展

```yaml
team:
  # ── 前端设计侧 ──
  fe_design:
    fe_design_mgr:  ["xu"]              # 前端设计经理
    rtl_lead:       ["xu"]              # RTL 设计 Leader（可兼任）
    rtl_engs:       ["xu", "wang"]
    static_lead:    ["chen"]            # 静态验证 Leader
    static_engs:    ["chen"]
    ppa_lead:       ["liu"]             # PPA Leader
    ppa_engs:       ["liu"]

  # ── DV 侧 ──
  dv:
    dv_mgr:      ["jiang"]
    soc_dv_mgr:  ["li"]
    ip_dv_mgrs:
      uart:  ["wang"]
      dma:   ["zhang"]
      gpio:  ["wang"]
    dv_engs:
      uart:  ["wang", "zhao"]
      dma:   ["zhang"]
      gpio:  ["wang"]
    dv_infra:     ["jiang"]              # CI/工具链/VIP库

  # ── 全局 ──
  pm:            ["jiang"]
  viewers:       ["boss@company.com"]

# ── 签核门控 ──
signoff_gates:
  D1:
    requires: ["LINT_CLEAN"]
    approver: "fe_design_mgr"
  D2:
    requires: ["CDC_CLEAN", "RDC_CLEAN", "FORMAL_PASS"]
    approver: "fe_design_mgr"
  D3:
    requires: ["SYNTHESIS_PASS", "PPA_CONVERGED"]
    approver: "fe_design_mgr"
  V1:
    requires: ["SMOKE_TEST_PASSING", "TESTPLAN_COMPLETED"]
    approver: "ip_dv_mgr"
  V2:
    requires: ["ALL_TESTS_PASSING", "CODE_COVERAGE_90", "FUNCTIONAL_COVERAGE_100"]
    approver: "soc_dv_mgr"
  V3:
    requires: ["CODE_COVERAGE_95", "NO_P0_P1_BUGS", "CHECKLIST_DONE"]
    approver: "dv_mgr"
  TAPEOUT:
    requires: ["D3", "V3"]
    approvers: ["fe_design_mgr", "dv_mgr", "pm"]
    min_approvals: 3
```

---

## 8. 与 OpenTitan 的 Checklist 对齐

OpenTitan 的 `checklist.md` 按 D1/D2/D3/V1/V2/V3 组织，天然对应双线签核：

```
checklist.md section      →   负责角色          →   签核门
─────────────────────────────────────────────────────────
D1 (Design)               →   fe_design_mgr       →   D1 gate
D2 (Design Freeze)        →   fe_design_mgr       →   D2 gate
D3 (Design Signoff)       →   fe_design_mgr       →   D3 gate
V1 (Smoke)                →   ip_dv_mgr        →   V1 gate
V2 (Functional)           →   soc_dv_mgr       →   V2 gate
V2S (Security)            →   dv_mgr           →   (安全特例)
V3 (Closure)              →   dv_mgr           →   V3 gate
```

---

## 9. 代码量影响

| 文件 | 改动 | 说明 |
|------|:---:|------|
| `src/core/auth.py` | +60 行 | 增加 fe_design_mgr / rtl_lead / static_lead / ppa_lead / ... |
| `src/infra/rbac.py` | +30 行 | 增加静态检查 + PPA 权限 |
| `src/infra/approval_workflow.py` | +80 行 | D1→D3 设计侧审批链 |
| `.signoffai.yaml` | 已有 | team 段扩展 |
| `projects/earlgrey/hw/ip/*/doc/checklist.md` | 已有 | 对齐 OpenTitan |
