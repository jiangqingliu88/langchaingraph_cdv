# CLI 角色管理 & Pipeline 权限控制

> 日期：2026-08-09

---

## 1. 入口：CLI 登录 & 角色绑定

```bash
# 首次使用 — 通过 git config 绑定身份
vagent login --user jiang
# → 读取 projects/<project>/.signoffai.yaml team 段
# → 匹配 jiang → 角色 fe_design_mgr + dv_mgr
# → 写入 ~/.signoffai/identity

# 查看当前身份
vagent whoami
# → jiang | fe_design_mgr, dv_mgr | project: earlgrey

# 切换项目
vagent project switch earlgrey
# → 重新读取 projects/earlgrey/.signoffai.yaml 的角色

# 列出当前项目的团队成员
vagent team list
# → role          | members
#   fe_design_mgr | xu
#   rtl_eng       | xu, wang
#   dv_mgr        | jiang
#   ...
```

### 身份存储

```yaml
# ~/.signoffai/identity
user: jiang
email: jiang@company.com
current_project: earlgrey
```

---

## 2. 角色 → Pipeline 模式

```yaml
# projects/earlgrey/.signoffai.yaml — pipeline 权限段
pipeline_permissions:
  # ── 前端设计侧 ──
  fe_design_mgr:
    modes:   ["full_soc", "design_frontend", "design_quality", "syn_ppa", "dump", "status"]
    scopes:  ["chip", "ip.*"]                    # 可操作所有 scope

  rtl_lead:
    modes:   ["design_frontend", "design_quality", "dump", "status"]
    scopes:  ["chip", "ip.*"]

  rtl_eng:
    modes:   ["design_frontend", "status"]
    scopes:  ["ip.uart"]                          # 只分配到自己的 IP

  static_lead:
    modes:   ["design_quality", "dump", "status"]
    scopes:  ["chip.cdc", "chip.rdc", "chip.lint", "chip.formal"]

  static_eng:
    modes:   ["design_quality", "status"]
    scopes:  ["chip.cdc", "chip.lint"]

  ppa_lead:
    modes:   ["syn_ppa", "dump", "status"]
    scopes:  ["chip.syn", "chip.ppa"]

  ppa_eng:
    modes:   ["syn_ppa", "status"]
    scopes:  ["chip.syn"]

  # ── DV 侧 ──
  dv_mgr:
    modes:   ["full_soc", "full_verification", "regression_only", "coverage_analysis",
              "debug_analysis", "signoff_gate", "dump", "status"]
    scopes:  ["chip", "ip.*"]

  soc_dv_mgr:
    modes:   ["full_verification", "regression_only", "coverage_analysis",
              "debug_analysis", "signoff_gate", "dump", "status"]
    scopes:  ["chip", "chip.conn"]

  ip_dv_mgr:
    modes:   ["full_verification", "regression_only", "coverage_analysis",
              "debug_analysis", "dump", "status"]
    scopes:  ["ip.uart", "ip.dma", "ip.gpio"]     # 管理的 IP 列表

  dv_eng:
    modes:   ["full_verification", "regression_only", "coverage_analysis", "status"]
    scopes:  ["ip.uart"]                          # 只分配到自己的 IP

  dv_infra:
    modes:   ["full_verification", "dump", "status"]
    scopes:  ["chip", "ip.*"]                      # 基础设施可查看所有

  # ── 全局 ──
  pm:
    modes:   ["dump", "status", "team"]
    scopes:  ["chip"]                             # 只看汇总

  viewer:
    modes:   ["status", "dump"]
    scopes:  ["chip"]                             # 只读
```

---

## 3. Pipeline 模式定义

```yaml
# projects/earlgrey/.signoffai.yaml — pipeline 模式段
pipelines:
  # ── 前端设计 Pipeline ──
  design_frontend:
    description: "RTL 设计生成（spec → design_arch → model）"
    phases: [spec, design, model]
    roles: [fe_design_mgr, rtl_lead, rtl_eng]

  design_quality:
    description: "静态检查（Lint → CDC → RDC → Formal）"
    phases: [lint, cdc, rdc, formal]
    roles: [fe_design_mgr, rtl_lead, static_lead, static_eng]

  syn_ppa:
    description: "综合 + PPA 收敛（Syn → PPA report）"
    phases: [syn, ppa]
    roles: [fe_design_mgr, ppa_lead, ppa_eng]

  # ── DV Pipeline ──
  full_verification:
    description: "完整验证流程（vplan → UVM → test → regress → cover → debug → signoff）"
    phases: [vplan, tpoint, rtm, UVM, test, assert, regress, cover, debug, qa, report, signoff]
    roles: [dv_mgr, soc_dv_mgr, ip_dv_mgr, dv_eng]

  regression_only:
    description: "只跑回归 + 覆盖率"
    phases: [regress, cover]
    roles: [dv_mgr, soc_dv_mgr, ip_dv_mgr, dv_eng]

  coverage_analysis:
    description: "覆盖率分析 + 缺口建议"
    phases: [cover, debug]
    roles: [dv_mgr, soc_dv_mgr, ip_dv_mgr, dv_eng]

  debug_analysis:
    description: "失败分析 + 根因定位"
    phases: [debug]
    roles: [dv_mgr, soc_dv_mgr, ip_dv_mgr]

  # ── 签核 Pipeline ──
  signoff_gate:
    description: "签核门（qa → report → signoff）"
    phases: [qa, report, signoff]
    roles: [dv_mgr, soc_dv_mgr]

  # ── SoC 全流程 ──
  full_soc:
    description: "SoC 全流程（设计 + 静态检查 + DV + 签核）"
    phases: [spec, design, model, lint, cdc, rdc, syn, vplan, tpoint, rtm,
             UVM, test, assert, regress, cover, debug, formal, qa, report, signoff]
    roles: [fe_design_mgr, dv_mgr]     # 只有经理级可跑全流程
```

---

## 4. CLI 执行流

```bash
# 进入 CLI 时必须已登录
$ vagent status
→ 未登录。请先执行: vagent login --user <username>

# 登录后，每次命令自动检查角色权限
$ vagent verify --pipeline full_soc
→ 用户 jiang 角色 [fe_design_mgr, dv_mgr] → 允许

$ vagent verify --pipeline full_soc
→ 用户 wang 角色 [rtl_eng] → 拒绝: rtl_eng 无权运行 full_soc
→ 可用模式: design_frontend, status

# scope 检查
$ vagent verify --pipeline full_verification --scope ip.dma
→ 用户 zhang 角色 [dv_eng, scope=ip.uart] → 拒绝: zhang 无权操作 ip.dma
→ 可用 scope: ip.uart

# 分步执行
$ vagent run lint --scope ip.uart       # static_eng: ✅
$ vagent run regress --scope ip.uart    # dv_eng: ✅
$ vagent run signoff --scope chip       # dv_eng: ❌ 只有 dv_mgr/soc_dv_mgr 可签核 chip
```

---

## 5. 实现：`src/cli/auth.py`（新增）

```python
"""CLI 身份认证 & 角色权限检查"""
import os
import yaml
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional

IDENTITY_FILE = Path.home() / ".signoffai" / "identity"

@dataclass
class UserIdentity:
    username: str
    email: str = ""
    current_project: str = ""

    @classmethod
    def load(cls) -> Optional["UserIdentity"]:
        if not IDENTITY_FILE.exists():
            return None
        data = yaml.safe_load(IDENTITY_FILE.read_text())
        return cls(**data)

    def save(self):
        IDENTITY_FILE.parent.mkdir(parents=True, exist_ok=True)
        IDENTITY_FILE.write_text(yaml.dump({
            "username": self.username,
            "email": self.email,
            "current_project": self.current_project,
        }))


class RoleGuard:
    """每次 CLI 命令执行前检查角色权限"""

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.identity = UserIdentity.load()
        self._config = self._load_project_config()

    def _load_project_config(self) -> dict:
        cfg_path = self.project_root / ".signoffai.yaml"
        if not cfg_path.exists():
            return {}
        return yaml.safe_load(cfg_path.read_text())

    @property
    def roles(self) -> List[str]:
        """当前用户的角色列表"""
        if not self.identity:
            return []
        team = self._config.get("team", {})
        roles = []
        for category in ["fe_design", "dv"]:
            cat = team.get(category, {})
            for role_name, members in cat.items():
                if isinstance(members, dict):
                    # ip_dv_leads: {uart: [wang], dma: [zhang]}
                    for ip, member_list in members.items():
                        if self.identity.username in member_list:
                            roles.append(f"{role_name}.{ip}")
                elif isinstance(members, list):
                    if self.identity.username in members:
                        roles.append(role_name)
        return roles

    def can_run_pipeline(self, pipeline_name: str) -> tuple[bool, str]:
        """检查是否能运行指定 pipeline"""
        if not self.identity:
            return False, "未登录。请先执行: vagent login --user <username>"

        pipelines = self._config.get("pipelines", {})
        if pipeline_name not in pipelines:
            return False, f"未知 pipeline: {pipeline_name}"

        allowed_roles = pipelines[pipeline_name].get("roles", [])
        user_roles = self.roles
        if not any(r in allowed_roles for r in user_roles):
            return False, (
                f"角色 {user_roles} 无权运行 {pipeline_name}。\n"
                f"允许角色: {allowed_roles}\n"
                f"可用 pipeline: {self._available_pipelines()}"
            )
        return True, ""

    def can_access_scope(self, scope: str) -> tuple[bool, str]:
        """检查是否能操作指定 scope"""
        permissions = self._config.get("pipeline_permissions", {})
        for role in self.roles:
            role_perm = permissions.get(role, {})
            scopes = role_perm.get("scopes", [])
            for s in scopes:
                if _scope_matches(scope, s):
                    return True, ""
        return False, f"角色 {self.roles} 无权操作 scope {scope}"

    def _available_pipelines(self) -> List[str]:
        permissions = self._config.get("pipeline_permissions", {})
        available = []
        for role in self.roles:
            available.extend(permissions.get(role, {}).get("modes", []))
        return list(set(available))


def _scope_matches(requested: str, allowed: str) -> bool:
    """scope 通配匹配: ip.uart 匹配 ip.* 和 ip.uart"""
    import fnmatch
    return fnmatch.fnmatch(requested, allowed)
```

---

## 6. CLI 命令扩展

```bash
# 身份
vagent login --user <username>           # 首次登录
vagent whoami                            # 查看当前身份
vagent logout                            # 退出

# 项目
vagent project switch <name>             # 切换项目（重新加载角色）
vagent project init <name>               # 创建项目 → 自动成为 fe_design_mgr + dv_mgr

# 团队
vagent team list                         # 列出团队成员
vagent team add --user wang --role dv_eng --scope ip.uart
vagent team add --user chen --role static_lead
vagent team remove --user wang
vagent team show --user wang             # 查看某成员的权限

# 运行（自动检查权限）
vagent verify --pipeline full_soc                  # 自动检查角色
vagent verify --pipeline design_quality --scope chip.cdc
vagent run lint --scope ip.uart

# 查看可用的 pipeline
vagent pipeline list                     # 列出当前角色可用的所有 pipeline
```

---

## 7. `.signoffai.yaml` 完整结构（含角色 + pipeline）

```yaml
project:
  name: "earlgrey"
  type: "soc"

team:
  fe_design:
    fe_design_mgr:  ["xu"]
    rtl_lead:       ["xu"]
    rtl_engs:       ["xu", "wang"]
    static_lead:    ["chen"]
    static_engs:    ["chen"]
    ppa_lead:       ["liu"]
    ppa_engs:       ["liu"]

  dv:
    dv_mgr:         ["jiang"]
    soc_dv_mgr:     ["li"]
    ip_dv_mgrs:
      uart: ["wang"]
      dma:  ["zhang"]
      gpio: ["wang"]
    dv_engs:
      uart: ["wang", "zhao"]
      dma:  ["zhang"]
      gpio: ["wang"]
    dv_infra:       ["jiang"]

  pm:              ["jiang"]
  viewers:         ["boss@company.com"]

pipeline_permissions:
  fe_design_mgr:  {modes: [full_soc, design_frontend, design_quality, syn_ppa, dump, status], scopes: [chip, ip.*]}
  rtl_lead:       {modes: [design_frontend, design_quality, dump, status],             scopes: [chip, ip.*]}
  rtl_eng:        {modes: [design_frontend, status],                                   scopes: [ip.uart]}
  static_lead:    {modes: [design_quality, dump, status],                              scopes: [chip.cdc, chip.rdc, chip.lint, chip.formal]}
  static_eng:     {modes: [design_quality, status],                                    scopes: [chip.cdc, chip.lint]}
  ppa_lead:       {modes: [syn_ppa, dump, status],                                     scopes: [chip.syn, chip.ppa]}
  ppa_eng:        {modes: [syn_ppa, status],                                           scopes: [chip.syn]}
  dv_mgr:         {modes: [full_soc, full_verification, regression_only, coverage_analysis, debug_analysis, signoff_gate, dump, status], scopes: [chip, ip.*]}
  soc_dv_mgr:     {modes: [full_verification, regression_only, coverage_analysis, debug_analysis, signoff_gate, dump, status], scopes: [chip, chip.conn]}
  ip_dv_mgr:      {modes: [full_verification, regression_only, coverage_analysis, debug_analysis, dump, status], scopes: [ip.uart, ip.dma, ip.gpio]}
  dv_eng:         {modes: [full_verification, regression_only, coverage_analysis, status], scopes: [ip.uart]}
  dv_infra:       {modes: [full_verification, dump, status],                           scopes: [chip, ip.*]}
  pm:             {modes: [dump, status, team],                                         scopes: [chip]}
  viewer:         {modes: [status, dump],                                              scopes: [chip]}

pipelines:
  design_frontend:    {phases: [spec, design, model],                       roles: [fe_design_mgr, rtl_lead, rtl_eng]}
  design_quality:     {phases: [lint, cdc, rdc, formal],                   roles: [fe_design_mgr, rtl_lead, static_lead, static_eng]}
  syn_ppa:            {phases: [syn, ppa],                                 roles: [fe_design_mgr, ppa_lead, ppa_eng]}
  full_verification:  {phases: [vplan, tpoint, rtm, UVM, test, assert, regress, cover, debug, qa, report, signoff], roles: [dv_mgr, soc_dv_mgr, ip_dv_mgr, dv_eng]}
  regression_only:    {phases: [regress, cover],                           roles: [dv_mgr, soc_dv_mgr, ip_dv_mgr, dv_eng]}
  coverage_analysis:  {phases: [cover, debug],                             roles: [dv_mgr, soc_dv_mgr, ip_dv_mgr, dv_eng]}
  debug_analysis:     {phases: [debug],                                    roles: [dv_mgr, soc_dv_mgr, ip_dv_mgr]}
  signoff_gate:       {phases: [qa, report, signoff],                      roles: [dv_mgr, soc_dv_mgr]}
  full_soc:           {phases: [spec, design, model, lint, cdc, rdc, syn, vplan, tpoint, rtm, UVM, test, assert, regress, cover, debug, formal, qa, report, signoff], roles: [fe_design_mgr, dv_mgr]}
```

---

## 8. Scope → 目录绑定

### 8.1 设计原则

```
不搞文件系统 ACL（太重），用两层控制：
  1. CLI 命令 → scope 检查 → 拒绝越权操作
  2. Git CODEOWNERS → PR review 门控 → 越权代码合并不了
```

### 8.2 `.signoffai.yaml` 目录映射

```yaml
# scope → 目录的读写权限映射
scope_directories:
  # ── IP 模块 ──
  ip.uart:
    read:  ["hw/ip/uart/**"]
    write: ["hw/ip/uart/**", "hw/top_earlgrey/data/ip/chip_uart*"]
  ip.dma:
    read:  ["hw/ip/dma/**"]
    write: ["hw/ip/dma/**", "hw/top_earlgrey/data/ip/chip_dma*"]
  ip.gpio:
    read:  ["hw/ip/gpio/**"]
    write: ["hw/ip/gpio/**", "hw/top_earlgrey/data/ip/chip_gpio*"]

  # ── 芯片级 ──
  chip:
    read:  ["hw/top_earlgrey/**", "hw/ip/*/rtl/**"]
    write: ["hw/top_earlgrey/dv/**", "hw/top_earlgrey/data/**"]
  chip.conn:
    read:  ["hw/top_earlgrey/data/chip_conn*"]
    write: ["hw/top_earlgrey/data/chip_conn*"]

  # ── 静态检查 ──
  chip.cdc:
    read:  ["hw/ip/*/rtl/**", "hw/top_earlgrey/rtl/**"]
    write: ["hw/cdc/**"]
  chip.rdc:
    read:  ["hw/ip/*/rtl/**", "hw/top_earlgrey/rtl/**"]
    write: ["hw/rdc/**"]
  chip.lint:
    read:  ["hw/ip/*/rtl/**", "hw/top_earlgrey/rtl/**"]
    write: ["hw/lint/**"]
  chip.formal:
    read:  ["hw/ip/*/rtl/**", "hw/top_earlgrey/rtl/**"]
    write: ["hw/formal/**"]

  # ── 综合 + PPA ──
  chip.syn:
    read:  ["hw/top_earlgrey/rtl/**"]
    write: ["hw/syn/**"]
  chip.ppa:
    read:  ["hw/syn/**"]
    write: ["hw/syn/**"]
```

### 8.3 自动生成 Git CODEOWNERS

```python
# src/cli/codeowners_gen.py
def generate_codeowners(project_root: Path):
    """从 .signoffai.yaml → 生成 .github/CODEOWNERS"""
    config = yaml.safe_load((project_root / ".signoffai.yaml").read_text())
    team = config["team"]
    scope_dirs = config["scope_directories"]

    lines = ["# Auto-generated by SignOffAI — do not edit manually", ""]

    # dv_engs.uart → wang, zhao
    ip_dv_mgrs = team.get("dv", {}).get("ip_dv_mgrs", {})
    dv_engs = team.get("dv", {}).get("dv_engs", {})

    for ip_name, members in dv_engs.items():
        owners = " ".join(f"@{m}" for m in members)
        lead = ip_dv_mgrs.get(ip_name, [])
        if lead:
            owners += " " + " ".join(f"@{m}" for m in lead)
        lines.append(f"# IP: {ip_name}")
        lines.append(f"hw/ip/{ip_name}/   {owners}")
        lines.append("")

    # static_eng → chen
    static_engs = team.get("fe_design", {}).get("static_engs", [])
    if static_engs:
        owners = " ".join(f"@{m}" for m in static_engs)
        lines.append(f"# Static verification")
        lines.append(f"hw/cdc/   {owners}")
        lines.append(f"hw/rdc/   {owners}")
        lines.append(f"hw/lint/  {owners}")
        lines.append(f"hw/formal/ {owners}")
        lines.append("")

    # ppa
    ppa_engs = team.get("fe_design", {}).get("ppa_engs", [])
    if ppa_engs:
        owners = " ".join(f"@{m}" for m in ppa_engs)
        lines.append(f"# PPA / Synthesis")
        lines.append(f"hw/syn/   {owners}")
        lines.append("")

    # dv_mgr + soc_dv_mgr → chip level
    dv_mgr = team.get("dv", {}).get("dv_mgr", [])
    soc_mgr = team.get("dv", {}).get("soc_dv_mgr", [])
    chip_owners = dv_mgr + soc_mgr
    if chip_owners:
        owners = " ".join(f"@{m}" for m in chip_owners)
        lines.append(f"# Chip level")
        lines.append(f"hw/top_earlgrey/   {owners}")
        lines.append("")

    (project_root / ".github" / "CODEOWNERS").parent.mkdir(parents=True, exist_ok=True)
    (project_root / ".github" / "CODEOWNERS").write_text("\n".join(lines))

# 每次 vagent team add/remove 后自动重新生成
```

### 8.4 CLI 行为

```bash
# 登录时自动绑定
$ vagent login --user wang
→ 身份: wang | 角色: dv_eng | scope: ip.uart
→ 绑定目录:
    read:  hw/ip/uart/**
    write: hw/ip/uart/**, hw/top_earlgrey/data/ip/chip_uart*
→ Git: 你的修改只接受 hw/ip/uart/ 目录下的

# 查看自己的权限
$ vagent whoami --verbose
→ 用户:   wang
  角色:   dv_eng
  Scope:  ip.uart
  可读:   hw/ip/uart/**
  可写:   hw/ip/uart/**, hw/top_earlgrey/data/ip/chip_uart*
  Pipeline: full_verification, regression_only, coverage_analysis, status
```

---

## 9. Fusesoc Filelist 管理

### 9.1 fusesoc 在 dvsim 中的角色

```
dvsim → fusesoc → filelist.f → VCS/Xcelium 编译
         ↑
    .core 文件描述源文件 + 依赖关系
```

每个 IP 和 SoC 顶层都有自己的 `.core` 文件：

```
hw/ip/uart/uart.core                    ← RTL core（描述 RTL 源文件）
hw/ip/uart/dv/uart_sim.core             ← 仿真 core（RTL + DV env + TB）
hw/top_earlgrey/chip_earlgrey_asic.core ← SoC 顶层 core（所有 IP + 连线）
```

### 9.2 SignOffAI 的职责（不替换 fusesoc，只管理 .core 文件）

```
SignOffAI UVM Agent 生成新代码
    │
    ├── hw/ip/uart/dv/env/uart_env.sv       ← 新文件
    ├── hw/ip/uart/dv/tb/tb.sv              ← 新文件
    └── hw/ip/uart/dv/tests/uart_base_test.sv ← 新文件
    │
    ▼
FusesocUpdater 自动更新 uart_sim.core
    │
    ├── 追加 dv fileset 中的文件列表
    ├── 追加 tb_top fileset
    └── 保持 targets.sim 正确
    │
    ▼
dvsim → fusesoc → filelist.f ✅ 包含新文件
```

### 9.3 `.core` 文件结构（标准 fusesoc 格式）

```ini
# hw/ip/uart/dv/uart_sim.core
CAPI=2:
name: lowrisc:dv:uart_sim:0.1
description: "UART block-level simulation"

filesets:
  # RTL — 引用 IP 的 core，不用重复列出
  rtl:
    depend:
      - lowrisc:ip:uart

  # DV 环境
  dv_env:
    files:
      - dv/env/uart_env_pkg.sv
      - dv/env/uart_env.sv
      - dv/env/uart_env_cfg.sv
      - dv/env/uart_env_cov.sv
      - dv/env/uart_scoreboard.sv
      - dv/env/uart_virtual_sequencer.sv
      - dv/env/uart_if.sv
      - dv/env/uart_seq_item.sv
    file_type: systemVerilogSource

  # Sequences
  dv_seqs:
    files:
      - dv/env/seq_lib/uart_base_vseq.sv
      - dv/env/seq_lib/uart_smoke_vseq.sv
      - dv/env/seq_lib/uart_tx_rx_vseq.sv
      - dv/env/seq_lib/uart_vseq_list.sv
    file_type: systemVerilogSource

  # Testbench top
  tb_top:
    files:
      - dv/tb/tb.sv
    file_type: systemVerilogSource

  # Tests
  dv_tests:
    files:
      - dv/tests/uart_base_test.sv
      - dv/tests/uart_test_pkg.sv
    file_type: systemVerilogSource

  # SVA bindings
  sva:
    files:
      - dv/sva/uart_bind.sv
    file_type: systemVerilogSource

targets:
  sim:
    filesets:
      - rtl
      - dv_env
      - dv_seqs
      - tb_top
      - dv_tests
      - sva
```

### 9.4 FusesocUpdater 实现

```python
# src/tools/dvsim_adapter/fusesoc_updater.py
import re
from pathlib import Path
from typing import List

class FusesocUpdater:
    """UVM Agent 生成代码后，自动更新 .core 文件"""

    def __init__(self, project_root: Path, scope: str):
        self.project_root = project_root
        self.scope = scope                  # "ip.uart"
        self.ip_name = scope.split(".")[-1]  # "uart"
        self.core_path = self._resolve_core_path()

    def _resolve_core_path(self) -> Path:
        # scope 检查：只有该 IP 的 DV eng 可写
        return self.project_root / "hw" / "ip" / self.ip_name / "dv" / f"{self.ip_name}_sim.core"

    def add_files_to_fileset(self, fileset: str, new_files: List[str]):
        """往 fileset 追加文件（去重）"""
        content = self.core_path.read_text()
        section = self._find_fileset(content, fileset)
        if not section:
            raise ValueError(f"Fileset '{fileset}' not found in {self.core_path}")

        for f in new_files:
            rel_path = f"      - {f}"
            if rel_path not in section:
                section += f"\n{rel_path}"

        updated = content.replace(self._find_fileset(content, fileset), section)
        self.core_path.write_text(updated)

    def add_sequence(self, seq_file: str):
        """UVM Agent 新增 sequence 后自动注册"""
        self.add_files_to_fileset("dv_seqs", [
            f"dv/env/seq_lib/{Path(seq_file).name}",
        ])
        # 同时更新 vseq_list.sv
        self._update_vseq_list(seq_file)

    def _update_vseq_list(self, seq_file: str):
        """更新 *_vseq_list.sv 注册新 sequence"""
        list_path = self.core_path.parent / "env" / "seq_lib" / f"{self.ip_name}_vseq_list.sv"
        if not list_path.exists():
            return
        content = list_path.read_text()
        seq_name = Path(seq_file).stem
        include_line = f'`include "{seq_name}.sv"'
        if include_line not in content:
            # 在最后一个 `include 之后追加
            last_include = max(i for i, line in enumerate(content.split("\n")) if "`include" in line)
            lines = content.split("\n")
            lines.insert(last_include + 1, include_line)
            list_path.write_text("\n".join(lines))

    def _find_fileset(self, content: str, name: str) -> str:
        """从 .core 中提取指定 fileset 的文本块"""
        pattern = rf"  {name}:\s*\n((?:    .*\n?)*)"
        m = re.search(pattern, content)
        return m.group(0) if m else ""
```

### 9.5 CLI 集成

```bash
# UVM Agent 生成环境后自动调用
$ vagent run verification --scope ip.uart
→ verification_architect 生成:
    dv/env/uart_env.sv
    dv/env/uart_env_pkg.sv
    dv/tb/tb.sv
    ...
→ FusesocUpdater: 更新 hw/ip/uart/dv/uart_sim.core ✅
→ FusesocUpdater: 更新 hw/ip/uart/dv/env/seq_lib/uart_vseq_list.sv ✅

# 手动触发更新（已有代码但没注册到 .core）
$ vagent fusesoc update --scope ip.uart
→ 扫描 hw/ip/uart/dv/ 下所有 .sv 文件
→ 对比 uart_sim.core 中已注册的文件
→ 新增 3 个未注册文件 → 追加到 dv_env fileset

# 验证 filelist 生成
$ vagent fusesoc generate --scope ip.uart
→ fusesoc run --target=sim lowrisc:dv:uart_sim:0.1
→ 输出: filelist.f ✅
```

### 9.6 目录结构总结

```
hw/ip/uart/
├── uart.core                  ← RTL core（手写或 regtool 生成）
└── dv/
    ├── uart_sim.core          ← 仿真 core（UVM Agent 生成 + FusesocUpdater 维护）
    ├── uart_sim_cfg.hjson     ← dvsim 配置（vplan_generator 生成）
    ├── env/                   ← UVM 环境（verification_architect 生成）
    ├── tb/tb.sv              ← Testbench top
    ├── tests/                ← UVM tests（test_engineer 生成）
    └── env/seq_lib/          ← Sequences + vseq_list.sv（FusesocUpdater 维护）
```

---

## 10. 实施路线

| 步骤 | 文件 | 说明 |
|:---:|------|------|
| 1 | `src/cli/auth.py` | 新增 RoleGuard + UserIdentity + scope→dir 检查 |
| 2 | `src/cli/commands.py` | 每个命令入口加 `guard.can_run_pipeline()` + `guard.can_access_dir()` |
| 3 | `src/cli/codeowners_gen.py` | 从 `.signoffai.yaml` 自动生成 `.github/CODEOWNERS` |
| 4 | `src/tools/dvsim_adapter/fusesoc_updater.py` | UVM 代码生成后自动维护 .core 文件 |
| 5 | `projects/earlgrey/.signoffai.yaml` | 合并 pipeline_permissions + pipelines + scope_directories |
| 6 | `vagent login/logout/whoami` | 新增身份命令，`--verbose` 显示绑定目录 |
| 7 | `vagent team list/add/remove` | 新增团队管理命令，自动触发 CODEOWNERS 重生成 |
| 8 | `vagent pipeline list` | 新增 pipeline 发现命令 |
| 9 | `vagent fusesoc update/generate` | 新增 fusesoc 文件管理命令 |
