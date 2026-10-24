"""后端档案 —— **数据驱动的 EDA 方言描述**（不是类层次）。

## 为什么不建 `Backend` 类

本仓库的回归产物本来就是**后端特定的 YAML**：`run_cmd` 是完整命令 + 判据链
（`vsim ... ; [ -s sim_vsim.log ] && ...`），不是 argv。为它引入
`render_argv()` 抽象，得先把"命令"和"跑完怎么判"拆开，收益低、风险高。

所以这里只收三样**数据**：

    reserved      后端自己生成的参数键（用户 plusargs 不许手写）
    run_cmd_template  本后端的仿真命令模板（`%(top)s` 等 Python 占位符）
    detect_tokens 从 run_cmd 里识别的可执行名

再加两个纯函数：`detect_simulator()` / `validate_plusargs()`。
**新增后端 = 加一个字典条目**，不改任何类或生成器分支。

## 与 plusargs 设计的关系

`plusargs` 只装**测试语义参数**（`+preload=` / `+cfg_mode=`），由框架原样
透传到模板里的 `{{ PLUSARGS }}`；后端方言参数（`+ntb_random_seed`、
`+UVM_TESTNAME`、`-cm`…）由模板/结构化字段生成，用户手写即报错。
"""
from __future__ import annotations

import shlex
from typing import Any, Dict, Iterable, List, Optional, Tuple

#: Questa 的判据链（与 `tool_find_spec_yaml._sim_run_cmd` 逐字一致）。
#: `%(top)s` / `%(test)s` / `%(extra_opts)s` 是 Python 占位符；
#: `{{ SEED }}` / `{{ MODE_OPTS }}` / `{{ PLUSARGS }}` 留给回归框架的 Jinja。
QUESTA_TEMPLATE = (
    "vsim -c -sv_lib {{ UVM_DPI }} -onfinish stop -work {{ WORK }} "
    "%(top)s +UVM_TESTNAME=%(test)s +ntb_random_seed={{ SEED }} "
    "-l sim_vsim.log %(extra_opts)s "
    '-do "log -r /*; run -all; quit -f" {{ MODE_OPTS | default("") }} '
    "{{ PLUSARGS }} ; "
    "[ -s sim_vsim.log ] && "
    '! grep -qE "UVM_ERROR : *[1-9]|UVM_FATAL : *[1-9]|FATAL ERROR|Errors: *[1-9]"'
    ' sim_vsim.log && { '
    'grep -qE "mismatched=0" sim_vsim.log '
    '|| { echo "NO_CHECKER_EVIDENCE: 没有比对结论（真 pass 要求 SCB 报 mismatched=0）"; '
    'exit 1; }; }'
)

BACKENDS: Dict[str, Dict[str, Any]] = {
    "questa": {
        "display": "QuestaSim / ModelSim",
        "detect_tokens": ("vsim", "vlog", "vopt"),
        "reserved": {
            "+uvm_testname", "+ntb_random_seed", "+uvm_timeout",
            "+cover", "+wave", "+glitch", "+delta",
            "-coverage", "-coverstore", "-testname", "-qwavedb", "-voptargs",
            "-sv_lib", "-work", "-l", "-do", "-onfinish",
        },
        "run_cmd_template": QUESTA_TEMPLATE,
        "seed_flag": "+ntb_random_seed={{ SEED }}",
    },
    "vcs": {
        "display": "Synopsys VCS",
        "detect_tokens": ("vcs", "simv"),
        "reserved": {
            "+uvm_testname", "+ntb_random_seed", "+ntb_random_seed_automatic",
            "-cm", "-cm_dir", "-cm_name", "-lca", "-kdb", "-l",
            "+fsdb", "-debug_access", "-debug_region", "-ucli",
        },
        # 未实现：模板留空，`render_sim_command` 会明确报错，不悄悄退回 Questa。
        "run_cmd_template": "",
        "seed_flag": "+ntb_random_seed={{ SEED }}",
    },
    "verilator": {
        "display": "Verilator",
        "detect_tokens": ("verilator", "Vtb"),
        "reserved": {"--trace", "--trace-fst", "--seed", "--top-module",
                     "-Mdir", "-o", "--binary"},
        "run_cmd_template": "",
        "seed_flag": "--seed %(seed)s",
    },
    "icarus": {
        "display": "Icarus Verilog",
        "detect_tokens": ("iverilog", "vvp"),
        "reserved": {"-s", "-o", "-l", "-plusarg"},
        "run_cmd_template": "",
        "seed_flag": "",
    },
}

_ALIASES = {
    "modelsim": "questa",
    "questasim": "questa",
    "questa": "questa",
    "vsim": "questa",
    "synopsys": "vcs",
    "vcs": "vcs",
    "verilator": "verilator",
    "iverilog": "icarus",
    "icarus": "icarus",
}


def normalize_backend(name: str) -> str:
    return _ALIASES.get(str(name or "").strip().lower(), "")


def detect_simulator(data: Dict[str, Any]) -> str:
    """从配置里识别后端：显式 `simulator` → settings → run_cmd 里的可执行名。

    识别不出返回空串（**不猜**）—— 调用方据此跳过保留键校验，并在日志里说清。
    """
    explicit = str((data or {}).get("simulator") or "").strip()
    if explicit:
        return normalize_backend(explicit) or explicit.lower()
    settings = (data or {}).get("settings") or {}
    default = str(settings.get("default_simulator") or "").strip()
    if default:
        return normalize_backend(default) or default.lower()
    for test in (data or {}).get("tests") or []:
        if not isinstance(test, dict):
            continue
        cmd = str(test.get("run_cmd") or test.get("ref_run_cmd") or "")
        for name, profile in BACKENDS.items():
            if any(tok in cmd for tok in profile["detect_tokens"]):
                return name
    return ""


def reserved_keys(backend: str) -> set:
    profile = BACKENDS.get(normalize_backend(backend) or backend, {})
    return set(profile.get("reserved") or ())


def _key_of(arg: str) -> str:
    """`+foo=1` → `+foo`；大小写/空白归一。"""
    return str(arg).strip().split("=", 1)[0].strip().lower()


def validate_plusargs(plusargs: Iterable[str],
                      backend: str) -> Tuple[List[str], List[str]]:
    """返回 `(errors, warnings)`。

    规则：
      1. 后端保留键不能手写（`+ntb_random_seed` / `+UVM_TESTNAME` / `-cm`…）；
      2. `{{ SEED }}` 不允许出现在 plusargs —— 种子只有 `seeds` 一个出处；
      3. 重复键告警（UVM 后者覆盖前者，静默接受会让人以为两条都生效）。

    **不校验 `backend_args`**：那是显式逃生口，由 audit 记 caveat。
    """
    errors: List[str] = []
    warnings: List[str] = []
    reserved = reserved_keys(backend)
    seen: Dict[str, int] = {}
    for raw in plusargs or []:
        p = str(raw).strip()
        if not p:
            continue
        key = _key_of(p)
        if "{{" in p and "SEED" in p.upper():
            errors.append(
                f"plusargs 里不能写 {p!r}：种子由 `seeds` 字段生成，"
                f"不允许把回归调度语义漏进 test 参数")
        if key in reserved:
            errors.append(
                f"plusarg {key} 是 {backend or '后端'} 自己生成的，不能手写；"
                f"请用结构化字段（test / seeds / modes）表达")
        seen[key] = seen.get(key, 0) + 1
    for key, n in seen.items():
        if n > 1:
            warnings.append(
                f"plusargs 里 {key} 出现了 {n} 次 —— UVM 后者覆盖前者，"
                f"前一条不会生效")
    return errors, warnings


def render_sim_command(backend: str, top: str, test: str,
                       extra_opts: str = "") -> str:
    """按后端模板渲染仿真命令。**未实现的后端明确报错**，不退回 Questa。"""
    name = normalize_backend(backend) or str(backend or "").strip().lower()
    profile = BACKENDS.get(name)
    if not profile:
        raise ValueError(f"未知后端 {backend!r}（已知：{'、'.join(BACKENDS)}）")
    tmpl = profile.get("run_cmd_template") or ""
    if not tmpl:
        raise ValueError(
            f"后端 {name} 还没有 run_cmd 模板 —— 不同后端应生成不同的 YAML；"
            f"在 backend_profiles.py 里补 `run_cmd_template` 即可")
    return tmpl % {"top": top, "test": test, "extra_opts": extra_opts}


def quote_arg(arg: str) -> str:
    """用户参数 → shell 片段。

    只在**含空白**时加引号；`${EMAN_...}` 这类 shell 变量要保持可展开，
    所以不无差别 `shlex.quote`（那会把它变成字面量）。
    """
    s = str(arg)
    if any(ch.isspace() for ch in s) and not (s.startswith("'") or s.startswith('"')):
        return shlex.quote(s)
    return s


def join_args(args: Iterable[str]) -> str:
    return " ".join(quote_arg(a) for a in (args or []) if str(a).strip())
