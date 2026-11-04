# src/regression_framework/core/config.py
import os
import sys
import yaml
import re
import json
import copy
from pathlib import Path
from typing import Dict, Any, List, Optional
from jinja2 import Template, StrictUndefined, UndefinedError, TemplateSyntaxError
from jsonschema import validate, ValidationError
from .exceptions import ConfigError
from .logging_config import get_logger
from ..plugins.manager import PluginManager
logger = get_logger(__name__)

# YAML Schema 定义
CONFIG_SCHEMA = {
    "type": "object",
    "properties": {
        # 全局模板变量（原 `global_vars` 已并入这里 —— 两个名字指同一件事，
        # 只会让人猜该用哪个；`global_vars` 的旧配置已迁移）
        "variables": {"type": "object"},
        "config_name": {"type": "string"},
        # 本文件是**后端特定**的生成物（questa/vcs/verilator/icarus）。
        # 保留键校验按它选表；缺省时从 run_cmd 的可执行名识别。
        "simulator": {"type": "string"},
        "env": {"type": "object"},
        "modes": {"type": "object"},
        # ── Reference Finder（溯源定位）──
        # 「哪个提交引入了这个失败」。ExecMan 里这是回归框架自身的能力，配置
        # 就写在 EMC 里；这里对齐同一套契约，让框架（而不是外挂一个工具）
        # 成为它的入口。
        "reference_finder": {
            "type": "object",
            "properties": {
                "good": {"type": "string"},        # 已知通过的提交/ref
                "bad": {"type": "string"},         # 已知失败的提交/ref（默认 HEAD）
                "test": {"type": "string"},        # 要复现的用例名/正则
                "paths": {"type": "array", "items": {"type": "string"}},
                "mode": {"type": "string"},
                "work_root": {"type": "string"},
                # 定位到之后，在边界两个版本上补跑 Debug Run（产出对比素材）
                "debug_at_boundary": {"type": "boolean"},
            },
            "required": ["good", "test"],
        },
        "includes": {"type": "array", "items": {"type": "string"}},
        "include": {},
        "extends": {"type": "string"},
        "settings": {
            "type": "object",
            "properties": {
                "default_build": {"type": "string"},
                "default_count": {"type": "integer", "minimum": 1},
                "simulators": {"type": "object"},
                "hooks": {"type": "object"},
                "lsf_opts": {"type": "object"},
                "build_cache": {"type": "boolean"},
                "retry": {"type": "integer", "minimum": 0}
            }
        },
        "builds": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "simulator": {"type": "string"},
                    "compile_opts": {"type": "array", "items": {"type": "string"}},
                    "files": {"type": "array", "items": {"type": "string"}},
                    "local_vars": {"type": "object"},
                    "variables": {"type": "object"},
                    "hooks": {"type": "object"},
                    # demo.yaml：完整编译命令（支持 Jinja {{ }} 与 shell ${}），
                    # 有它就不走 settings.simulators.<sim>.compile 模板。
                    "run_cmd": {"type": "string"},
                    # ── Reference Finder 的替代命令（ExecMan 的 Alternative
                    # Fields）── 跑**历史/参考版本**时用它替代 run_cmd：老版本的
                    # 编译方式、文件布局常和新版本不同，共用一个命令会编译不过，
                    # 于是把「版本差异」误判成「bug 引入点」。
                    "ref_run_cmd": {"type": "string"},
                    # 调试版命令（带上波形/详细日志）。**本框架尚无 Debug Run
                    # 模式**，这里先只做契约兼容：字段被接受并透传，但要执行
                    # 调试跑法需要另有实现。
                    "debug_run_cmd": {"type": "string"},
                    "ref_debug_run_cmd": {"type": "string"},
                    "top": {"type": "string"},
                    "depends": {"type": "array"},
                    "extends": {"type": "string"}
                },
                "required": ["name"]
            }
        },
        "tests": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "build": {"anyOf": [{"type": "string"}, {"type": "object"}]},
                    "count": {"type": "integer", "minimum": 1},
                    "matrix": {"type": "array"},
                    "local_vars": {"type": "object"},
                    "variables": {"type": "object"},
                    # demo.yaml：完整仿真命令；有它就不走 settings.simulators.<sim>.run
                    "run_cmd": {"type": "string"},
                    # 同上：跑历史/参考版本时替代 run_cmd（见 builds 里的说明）
                    "ref_run_cmd": {"type": "string"},
                    "debug_run_cmd": {"type": "string"},
                    "ref_debug_run_cmd": {"type": "string"},
                    # **测试语义参数**：整组原样透传，后端不解释（`+preload=` /
                    # `+tensor_manifest=` / `+cfg_mode=`）。不是"每个一条用例"。
                    "plusargs": {"type": "array", "items": {"type": "string"}},
                    # 旧语义：每个 plusarg 展开成一条用例（进 local_vars.plusarg）。
                    # 新配置请用 `matrix`；保留这个名字是为了旧 YAML 能平滑迁移。
                    "plusarg_matrix": {"type": "array", "items": {"type": "string"}},
                    # 逃生口：确实要手加后端参数时用；非空时 audit 记 caveat。
                    "backend_args": {"type": "array", "items": {"type": "string"}},
                    # 结构化 test / seeds / modes（后端/框架据此生成方言参数）
                    "test": {"type": "string"},
                    # 每测试模式：只影响这一条用例的 MODE_OPTS（覆盖全局 --enable）
                    "modes": {"type": "array", "items": {"type": "string"}},
                    "seeds": {
                        "type": "object",
                        "properties": {
                            "base": {"type": "integer"},
                            "count": {"type": "integer", "minimum": 1},
                        },
                        "required": ["count"],
                        "additionalProperties": False,
                    },
                    "name_format": {"type": "string"},
                    "desc": {"type": "string"},
                    "run_opts": {"type": "array", "items": {"type": "string"}},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "file_pattern": {"type": "array", "items": {"type": "string"}},
                    "expect": {"type": "object"},
                    "hooks": {"type": "object"}
                },
                "required": ["name"]
            }
        }
    },
    # 必填只有 builds / tests。
    #
    # 原来这里还有一条 `anyOf: [required global_vars, required variables]`，本意是
    # 「至少给一种变量源」。但 `variables` 完全可以为空甚至不写 —— 每 build/test
    # 自带 `run_cmd` 时，变量全在任务级或由 `--set` 注入。于是「一份只用任务级
    # run_cmd 的配置」会被这条规则判不合法，得补个空的 `variables: {}` 才能过，
    # 纯属给人添堵。`global_vars` 已并入 `variables`，这条 anyOf 一并去掉。
    "required": ["builds", "tests"],
}

def _as_tag_set(value) -> Optional[set]:
    """把 `'a,b'` / `['a','b']` / `None` 统一成 set 或 None。"""
    if not value:
        return None
    if isinstance(value, str):
        value = value.split(',')
    tags = {str(v).strip() for v in value if str(v).strip()}
    return tags or None


def strip_test_prefix(name: str) -> str:
    """目录名/用例名 → 剥掉**前缀** `test_`（只削一次，不是全局替换）。

    ## 为什么不能用 `name.replace("test_", "")`

    那会把**中间**的 `test_` 也吃掉：

        test_npu_type_test_run_1_seed_2001
          .replace("test_", "")  →  npu_type_run_1_seed_2001   ← 中间那个没了

    而配置里展开出来的名字是 `npu_type_test_run_1` —— 两边对不上，于是这条用例
    **在 tag 筛选那一步被静默丢掉**。

    `npu_basic_test`（`count == 1`）的目录名是 `test_npu_basic_test`，只有前缀一处
    `test_`，所以它**照常跑** —— 表现就是"有些用例跑了、有些没跑"，而报告里
    每一级都 PASS。实测：p0 生成了 218 条用例脚本，只跑了 6 条。

    ## 为什么是"**循环**削前缀"而不是削一次

    配置里的用例名**可能自己就带一个 `test_`**（loopback 那条就叫
    `test_npu_sched_in_loopback`），而生成器还会再加一个前缀，于是目录名是
    `test_test_npu_sched_in_loopback`。削一次得到 `test_npu_sched_in_loopback`，
    而"声明侧"（同样过本函数）得到 `npu_sched_in_loopback` —— **两边对不上，
    这一级被筛成 EMPTY**（实测：修好种子用例之后，loopback 从 PASS 变 EMPTY）。

    所以规则是：**把所有前导 `test_` 都削掉**。种子用例只在前缀处有一个，
    中间的 `test_`（`npu_type_test_run_1`）不受影响。

    这个函数是**唯一**的剥离规则；`infrastructure.py` 与 `regression.py` 都调它。
    """
    s = str(name or "")
    while s.startswith("test_"):
        s = s[len("test_"):]
    return s


def make_tag_matcher(config: dict, tags=None, exclude_tags=None):
    """按 `tests[].tags` 生成「这条 test 该不该跑」的判定函数；不过滤时返回 None。

    `tags` / `exclude_tags` 收 `'a,b'` 或 `['a','b']`，语义与 `--tests` /
    `--exclude-tests` 对齐：include 命中**任一** tag 即保留，exclude 命中任一即
    剔除，且 exclude 优先（同时命中时以 exclude 为准）。

    判定函数吃**生成目录里**的 test 名（`test_` 前缀已剥掉）。它可能是
    `ShellGenerator` 加过 seed 后缀的 `<name>_seed_<seed>`（见 shell.py），
    所以除精确匹配外还要认这条后缀 —— 否则带 `local_vars.SEED` 的用例会被
    整批漏掉。
    """
    include = _as_tag_set(tags)
    exclude = _as_tag_set(exclude_tags)
    if not include and not exclude:
        return None

    # config 传进来的应该是 ConfigBuilder.build() 之后的结果（test 名已展开，
    # tags 已随用例复制），这样 plusargs / count / matrix 派生出来的用例名也对得上。
    allowed = set()
    for test in config.get('tests', []) or []:
        name = test.get('name')
        if not name:
            continue
        test_tags = set(test.get('tags') or [])
        if include and not (test_tags & include):
            continue
        if exclude and (test_tags & exclude):
            continue
        # **两种形态都收**：配置里的 test 名带 `test_` 前缀（`test_apb_loopback`），
        # 而调用方送进来判定的常常是**目录名剥掉前缀**之后的（`apb_loopback` ——
        # 见 `infrastructure.py` 的 `test_dir.replace("test_", "")`）。
        # 只收一种，另一边的 include 明明命中了、名字却对不上 → **整批被静默筛空**
        # （实测：`tags='loopback'` 命中 8 条配置用例，运行时一条都没跑，五级全 total=0）。
        text = str(name)
        allowed.add(text)
        if text.startswith("test_"):
            allowed.add(text[len("test_"):])
    logger.debug(f"Tag filter: {len(allowed)} tests matched (include={include}, exclude={exclude})")

    def _match(dir_test_name: str) -> bool:
        if dir_test_name in allowed:
            return True
        # 种子展开后的目录有两种形态，**都要认**：
        #
        #     <test>_seed_<s>            （老形态）
        #     <test>_run_<i>_seed_<s>    （`count > 1` 展开，**带 _run_ 段**）
        #
        # 原来只认 `_seed_`，于是 `npu_type_test_run_1_seed_2001` **不匹配**
        # `npu_type_test` —— 而 `count == 1` 的 `npu_basic_test` 目录名恰好就是
        # 基名，所以它跑、它不跑，看起来像"有些用例过了"。
        #
        # 实测：p0 的 build 目录里生成了 218 条用例脚本，其中 **194 条是种子展开的
        # 批次用例**，全部被静默筛掉；`total=7 > 0` 又让"零用例"那道闸（EMPTY）
        # 拦不住 —— **分级回归报 PASS，而绝大多数用例一次都没跑**。
        #
        # 这是「假绿」里最难查的一类：报告、日志、退出码全都正常，只有去数
        # `sim_vsim.log` 的个数才发现对不上。
        return any(dir_test_name.startswith(n + '_run_')
                   or dir_test_name.startswith(n + '_seed_')
                   for n in allowed)

    return _match


def expand_modes(modes: dict, variables: dict, names) -> tuple:
    """**纯函数**：`modes` 映射 + 当前 `variables` + 要启用的名字 → 该怎么展开。

    返回 `(applied, opts, warnings, flags)`：

        applied    实际生效的 mode 名（去重、保持给出顺序）
        opts       要拼进聚合变量 `MODE_OPTS` 的值（与 applied 同序）
        warnings   该告警的话（**不在这里打日志** —— 纯函数不碰 logger）
        flags      要设成 `'1'` 的 `<x>_enabled` 键（含组合词的分量）

    抽出来的理由与 `apply_modes` 那次实测事故直接相关：展开逻辑（尤其
    **组合词要同时设它每个分量的 `_enabled`**）曾漏过一次，代价是 DUT 编译少
    `+cover`、覆盖率恒为 0 而命令行看不出问题。这段逻辑要么能被表驱动单测穷举，
    要么下次加模式（`prof` / `upf`）还会再踩一次。副作用（就地改 config、打日志）
    留在 `apply_modes` 里。
    """
    ordered: List[str] = []
    for n in (names or []):
        n = str(n).strip()
        if n and n not in ordered:
            ordered.append(n)

    applied: List[str] = []
    opts: List[str] = []
    warnings: List[str] = []
    for name in ordered:
        if name not in modes:
            # 名字没登记时退回「同名变量」，但只在那个变量确实存在时才认。
            if name in variables:
                var = name
            else:
                warnings.append(
                    f"--enable {name}: modes 里没有登记，且不存在同名变量，忽略"
                    f"（可用的 mode: {', '.join(sorted(modes)) or '无'}）")
                continue
        else:
            var = modes[name]
        value = variables.get(var)
        if value in (None, ''):
            warnings.append(f"--enable {name}: 变量 '{var}' 为空或不存在，忽略")
            continue
        applied.append(name)
        opts.append(str(value))

    flags: Dict[str, str] = {}
    for name in applied:
        # 组合模式（`cov+wave`）**同时是它的每个分量** —— run_cmd 里写
        # `{% if cov_enabled %}+cover{% endif %}` 的分支，不该因为人选的是
        # 组合词就沉默。实测：只设 `cov+wave_enabled` 时 DUT 编译少了 `+cover`，
        # vsim 报 (vsim-8634)「Code was not compiled with coverage options」，
        # 覆盖率**恒为 0** —— 而 MODE_OPTS 是对的，所以从命令行上看不出问题。
        for part in str(name).split('+'):
            part = part.strip()
            if part:
                flags[f'{part}_enabled'] = '1'
        flags[f'{name}_enabled'] = '1'
    return applied, opts, warnings, flags


def apply_modes(config: dict, enabled_modes) -> list:
    """把 `--enable wave,cov` 落到变量上；返回实际生效的 mode 名列表。

    `modes:` 块是「mode 名 → 变量名」的映射（见 common_base.yaml：
    `wave: wave_opt`）。启用某个 mode 时把那个变量的值追加进聚合变量
    `MODE_OPTS`，命令里写 `{{ MODE_OPTS }}` 就能拿到一串拼好的选项。

    顺带设 `<mode>_enabled: '1'`，方便 run_cmd 里按 mode 分支
    （`{% if wave_enabled %}...{% endif %}`）。

    只认 `modes:` 里登记过的名字：没登记的直接告警忽略 —— 打错字时宁可少注入
    一个选项，也不要静默地在命令里塞进一个不存在的变量。

    **决策逻辑在 `expand_modes`（纯函数，可表驱动单测）**；这里只负责副作用：
    打日志、写 `variables`。
    """
    names = sorted(_as_tag_set(enabled_modes) or ())
    if not names:
        return []
    variables = config.setdefault('variables', {})
    applied, opts, warnings, flags = expand_modes(
        config.get('modes') or {}, variables, names)
    for msg in warnings:
        logger.warning(msg)
    if opts:
        variables['MODE_OPTS'] = ' '.join(opts)
    variables.update(flags)
    logger.info(f"Enabled modes: {', '.join(applied)}" if applied else "Enabled modes: (none)")
    return applied


def render_str(text: str, context: dict, where: str = '') -> str:
    """渲染一个 `{{ }}` 模板，**引用不存在的变量直接报错**。

    Jinja 默认的 `Undefined` 会把找不到的变量渲染成**空字符串**：
    `{{ plusarg }}` 没定义就变成 `+UVM_VERBOSITY=LOW  +TOP=...`（多一个空格），
    命令照跑、结果全错，而且没有任何报错 —— 这是最难查的一类问题。
    这里换成 `StrictUndefined`：找不到就炸，并且指出是哪个字段。

    `ShellGenerator._substitute` 也走这个函数 —— 两个渲染点必须同样严格，
    一处严格一处静默等于没管住。

    确实允许缺省的变量，用 Jinja 自己的写法显式声明，别指望默认空串：
    `{{ var | default('') }}`、`{{ var | default('-') }}` 或
    `{% if var is defined %}...{% endif %}`。
    """
    try:
        return Template(text, undefined=StrictUndefined).render(**context)
    except UndefinedError as e:
        raise ConfigError(
            f"变量引用未定义({where or '未知位置'}): {e} —— "
            f"如果它本来就允许缺省，写成 {{{{ var | default('') }}}}") from e
    except TemplateSyntaxError as e:
        raise ConfigError(f"模板语法错误({where or '未知位置'}): {e}") from e


def normalize_build_name(name: str) -> str:
    """把 yaml 里的 build 名规整成**生成目录**里的任务名。

    yaml 写 `build_base1`，生成目录是 `build_build_base1`，调度器取到的任务名是
    去掉一层 `build_` 前缀的 `base1`。依赖表两边都要按同一套规整，否则
    `depends: [build_base1]` 永远匹配不上任务 `base1`。
    """
    name = str(name)
    return name[len('build_'):] if name.startswith('build_') else name


def build_dependency_map(config: dict) -> Dict[str, List[str]]:
    """`{build 任务名: [它依赖的 build 任务名...]}` —— 供调度器建依赖图。

    名字都过一遍 `normalize_build_name`，跟 `TaskFactory` 建出来的任务名对齐。
    返回值只含**确实声明了 depends 的** build，没依赖的不占键。
    """
    deps: Dict[str, List[str]] = {}
    for build in config.get('builds', []) or []:
        if not isinstance(build, dict):
            continue
        name, depends = build.get('name'), build.get('depends')
        if name and depends:
            deps[normalize_build_name(name)] = [normalize_build_name(d) for d in depends]
    return deps


def collect_tags(config: dict) -> Dict[str, List[str]]:
    """`{tag: [test 名, ...]}` —— 供 `--show-tags` / `--show-tests` 用。

    只统计 `tests[].tags`，没有 tag 的用例归到 '(untagged)' 这个桶里，
    这样 `--show-tests` 能列出全部用例而不是漏掉无标签的那批。
    """
    result: Dict[str, List[str]] = {}
    for test in config.get('tests', []) or []:
        name = test.get('name')
        if not name:
            continue
        tags = [str(t) for t in (test.get('tags') or [])] or ['(untagged)']
        for tag in tags:
            result.setdefault(tag, []).append(str(name))
    return result


class ConfigBuilder:
    """配置构建器 - 支持 include, extends, 变量替换, matrix展开, 命令行覆盖"""
    
    def __init__(self, yaml_file: str, cli_overrides: Optional[List[str]] = None):
        self.yaml_file = yaml_file
        self.cli_overrides = cli_overrides or []
        self.context = {}
        self.plugin_dir = "plugins"
        self._raw_data = {}
        self.plugin_manager = PluginManager()
        self.plugin_manager.discover_plugins()  # 自动发现插件
    def load_yaml_with_includes(self, filepath: str, base_dir: str = None) -> dict:
        if base_dir is None:
            base_dir = os.path.dirname(filepath) or '.'
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
        except Exception as e:
            logger.error(f"Failed to load YAML {filepath}: {e}")
            raise ConfigError(f"YAML load error: {e}")
        
        if data is None:
            data = {}
            
        # `includes`（复数是本框架的老写法）/ `include`（demo.yaml 用的是单数，
        # 值可以是字符串或列表）—— 两种都收，否则 demo.yaml 的 base 不会被合并。
        _inc = data.get('includes')
        if _inc is None:
            _inc = data.get('include')
        if isinstance(_inc, str):
            _inc = [_inc]
        if _inc:
            for inc in _inc:
                inc_path = os.path.join(base_dir, inc)
                if not os.path.exists(inc_path):
                    logger.warning(f"Include file '{inc_path}' not found, skipping.")
                    continue
                inc_data = self.load_yaml_with_includes(inc_path, base_dir)
                data = self._merge_config(inc_data, data)
        return data
    
    def _merge_config(self, base: dict, override: dict) -> dict:
        if not isinstance(base, dict) or not isinstance(override, dict):
            return copy.deepcopy(override)
        result = copy.deepcopy(base)
        for key, val in override.items():
            if key in result:
                if isinstance(result[key], dict) and isinstance(val, dict):
                    result[key] = self._merge_config(result[key], val)
                elif key == 'tests' and isinstance(result[key], list) and isinstance(val, list):
                    # 按 name 去重合并
                    names = {t.get('name') for t in result[key] if t.get('name')}
                    for item in val:
                        if item.get('name') in names:
                            for idx, old in enumerate(result[key]):
                                if old.get('name') == item.get('name'):
                                    result[key][idx] = self._merge_config(old, item)
                                    break
                        else:
                            result[key].append(item)
                elif key == 'builds' and isinstance(result[key], list) and isinstance(val, list):
                    existing = {b['name'] for b in result[key] if b.get('name')}
                    for item in val:
                        if item.get('name') in existing:
                            for idx, old in enumerate(result[key]):
                                if old.get('name') == item.get('name'):
                                    result[key][idx] = self._merge_config(old, item)
                                    break
                        else:
                            result[key].append(item)
                else:
                    result[key] = copy.deepcopy(val)
            else:
                result[key] = copy.deepcopy(val)
        return result
    
    def substitute_vars(self, obj, context: dict, _skip_keys: tuple = (), _path: str = ''):
        """递归渲染 `{{ }}`；`_skip_keys` 里的键整个跳过（原样留着）。

        跳过是给 `run_cmd` 用的：它要留到 ShellGenerator 那里、按**每个
        build/test 自己的上下文**渲染 —— 那个上下文里才有 `local_vars`
        （`{{ plusarg }}`、每条 count 展开出来的 `{{ SEED }}`）。这里是全局
        上下文，先渲染一遍的话，Jinja 会把未定义的 `{{ plusarg }}` 渲染成空串，
        原文就没了，后面再渲染也救不回来。

        `_path` 只用来在报错时指出是**哪个字段**引用了不存在的变量。
        """
        if isinstance(obj, str):
            return render_str(obj, context, _path)
        elif isinstance(obj, list):
            return [self.substitute_vars(item, context, _skip_keys, f"{_path}[{i}]")
                    for i, item in enumerate(obj)]
        elif isinstance(obj, dict):
            return {k: (v if k in _skip_keys
                        else self.substitute_vars(v, context, _skip_keys,
                                                  f"{_path}.{k}" if _path else str(k)))
                    for k, v in obj.items()}
        else:
            return obj
    
    def expand_matrix(self, tests: list) -> list:
        expanded = []
        for test in tests:
            if 'matrix' not in test:
                expanded.append(test)
                continue
            matrix_items = test.pop('matrix')
            all_params = {}
            for item in matrix_items:
                # 检查是否为插件调用
                if 'plugin' in item:
                    plugin_name = item.pop('plugin')
                    plugin = self.plugin_manager.get_matrix_plugin(plugin_name)
                    if plugin:
                        plugin.initialize(item.get('config', {}))
                        result = plugin.generate(**item.get('args', {}))
                        for k, v in result.items():
                            all_params.setdefault(k, []).extend(v)
                    else:
                        logger.warning(f"Matrix plugin '{plugin_name}' not found")
                else:
                    # 原有静态逻辑
                    for k, v in item.items():
                        if not isinstance(v, list):
                            v = [v]
                        all_params.setdefault(k, []).extend(v)
            
            name_format = test.pop('name_format', None)
            keys = list(all_params.keys())
            values = [all_params[k] for k in keys]
            idx = 0
            for combo in __import__('itertools').product(*values):
                new_test = copy.deepcopy(test)
                param_dict = dict(zip(keys, combo))
                if name_format:
                    ctx = param_dict.copy()
                    ctx['idx'] = idx
                    name = name_format.format(**ctx)
                else:
                    suffix = '_'.join([str(v) for v in param_dict.values()])
                    name = f"{test['name']}_{suffix}"
                new_test['name'] = name
                if 'local_vars' not in new_test:
                    new_test['local_vars'] = {}
                for k, v in param_dict.items():
                    new_test['local_vars'][k] = v
                expanded.append(new_test)
                idx += 1
        return expanded
    
    def expand_plusarg_matrix(self, tests: list) -> list:
        """`plusarg_matrix: ["+pb=1", "+pb=2"]` → 每个 plusarg 一条用例。

        **这是旧 `plusargs` 的语义**，现在改名保留：`plusargs` 只负责"整组
        透传给同一条用例"，不再展开。旧配置把字段名改成 `plusarg_matrix`
        即可保持原行为。

        展开后的用例带 `local_vars.plusarg`，命令里用 `{{ plusarg }}` 取。
        名字后缀取 plusarg 去掉 `+` 并把 `=` 换成 `_`，便于在报告里一眼看出。
        """
        expanded = []
        for test in tests:
            matrix = test.pop('plusarg_matrix', None)
            # **兼容旧配置**：旧语义的 `plusargs` 一定配合 `{{ plusarg }}`
            # （单数）使用。看到这个模板就按旧语义展开并告警；新语义的
            # `{{ PLUSARGS }}`（复数/大写）不受影响。
            if matrix is None and re.search(r"{{\s*plusarg\s*}}",
                                             str(test.get('run_cmd') or '')):
                matrix = test.pop('plusargs', None)
                if matrix:
                    logger.warning(
                        f"{test.get('name', '?')}: 旧 `plusargs` 语义已更名为 "
                        f"`plusarg_matrix`（每个 plusarg 一条用例）；新 `plusargs` "
                        f"是整组透传，请配合 `{{{{ PLUSARGS }}}}` 使用")
            if not matrix:
                expanded.append(test)
                continue
            for pa in matrix:
                new_test = copy.deepcopy(test)
                suffix = str(pa).strip('+').replace('=', '_')
                new_test['name'] = f"{test['name']}_{suffix}"
                new_test.setdefault('local_vars', {})['plusarg'] = pa
                expanded.append(new_test)
        return expanded

    def expand_plusargs(self, tests: list) -> list:
        """**已废止的旧入口** —— 等价于 `expand_plusarg_matrix`。

        保留它只是为了让外部脚本/旧测试不突然 ImportError；新代码请直接调
        `expand_plusarg_matrix`，语义更明确。
        """
        return self.expand_plusarg_matrix(tests)

    @staticmethod
    def _seed_base(test: dict):
        """`count` 展开时的种子基准：`local_vars.SEED` 优先，其次 `test.variables.SEED`。

        demo.yaml 把 SEED 写在 `variables` 里（`SEED: "{{ SEED }}"`），只认
        local_vars 的话 `count: 3` 会展开成三条**种子完全相同**的用例——名字变了、
        跑的东西没变。取不到整数就返回 None（此时只改名字、不动种子）。
        """
        raw = test.get('local_vars', {}).get('SEED')
        if raw is None:
            raw = test.get('variables', {}).get('SEED')
        if raw is None:
            return None
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None

    def expand_count(self, tests: list, default_count: int) -> list:
        """`count` / `seeds` → N 条用例，种子连续。

        `seeds: {base, count}` 是结构化写法（推荐）：种子**只有一个出处**，
        后端据此生成 `+ntb_random_seed`。旧的 `count` + `local_vars.SEED`
        继续支持；两者同时出现时 `seeds` 优先。
        """
        expanded = []
        for test in tests:
            seeds_decl = test.pop('seeds', None)
            if isinstance(seeds_decl, dict):
                try:
                    count = int(seeds_decl.get('count', default_count))
                except (TypeError, ValueError):
                    count = default_count
                raw_base = seeds_decl.get('base', self._seed_base(test))
                try:
                    base_seed = int(raw_base) if raw_base is not None else 0
                except (TypeError, ValueError):
                    base_seed = 0
            else:
                count = test.pop('count', default_count)
                base_seed = self._seed_base(test)
            for i in range(1, count + 1):
                new_test = copy.deepcopy(test)
                if count > 1:
                    new_test['name'] = f"{test['name']}_run_{i}"
                # 显式 `seeds` 即使 count=1 也要落 SEED —— 否则声明了基准，
                # 实际仍用全局默认种子（"声明了却没生效"）。
                if base_seed is not None:
                    new_test.setdefault('local_vars', {})['SEED'] = base_seed + i - 1
                expanded.append(new_test)
        return expanded
    
    def apply_cli_overrides(self, data: dict) -> dict:
        """应用命令行覆盖，如 --set variables.SEED=9999"""
        for override in self.cli_overrides:
            if '=' not in override:
                logger.warning(f"Ignoring invalid override: {override}")
                continue
            path_str, value_str = override.split('=', 1)
            path = path_str.split('.')
            
            # 解析值类型
            try:
                if value_str.lower() == 'true':
                    value = True
                elif value_str.lower() == 'false':
                    value = False
                elif value_str.isdigit():
                    value = int(value_str)
                elif re.match(r'^-?\d+\.\d+$', value_str):
                    value = float(value_str)
                else:
                    value = value_str
            except:
                value = value_str
            
            # 遍历路径
            current = data
            for key in path[:-1]:
                if key not in current:
                    logger.warning(f"Path {path_str} not found, creating")
                    current[key] = {}
                current = current[key]
            current[path[-1]] = value
            logger.info(f"Applied override: {path_str} = {value}")
        return data
    
    def validate_config(self, data: dict):
        """使用 jsonschema 校验配置"""
        try:
            validate(instance=data, schema=CONFIG_SCHEMA)
        except ValidationError as e:
            raise ConfigError(f"Config validation error: {e.message} at {e.path}")
    
    def build(self, incremental=False, repo_path='.', enabled_modes=None) -> dict:
        raw = self.load_yaml_with_includes(self.yaml_file)
        raw = self._resolve_extends(raw)
        raw = self._resolve_build_extends(raw)
        raw = self.apply_cli_overrides(raw)
        self.validate_config(raw)

        # `--enable` 要在渲染之前落地：它写的是 variables，而 variables 是渲染上下文
        # 的一部分，晚一步 `{{ MODE_OPTS }}` 就已经被渲染成空串了。
        if enabled_modes:
            apply_modes(raw, enabled_modes)

        # 渲染上下文 = variables，再叠 shell 环境变量
        # （`${VAR}` 走 shell，这里补的是 `{{ VAR }}` 那条路）。
        self.context = {}
        self.context.update(raw.get('variables', {}) or {})
        self.context.update(os.environ)

        # 命令类字段一律**不在全局渲染**，交给 generators/shell.py 按每个
        # build/test 自己的上下文渲染：
        #   · `run_cmd` 要看到 `{{ plusarg }}`（plusargs 展开后才存在），
        #     这里先渲染会被 Jinja 当成未定义、渲染成空串，整条参数丢掉；
        #   · `ref_run_cmd` / `debug_run_cmd` 要看到只在**溯源模式**下才注入的
        #     `RF_WORKTREE` 等变量。普通回归里它们根本不会被用到，就更不该
        #     在这里渲染 —— 否则一份「带了 ref_run_cmd 的配置」连普通回归都跑不了。
        substituted = self.substitute_vars(
            raw, self.context,
            # 用户参数**原样保留**：`{{ SEED }}` 必须能被后面的守卫看见并拒绝；
            # 提前渲染会把违规值洗成合法字面量（实测：此前的测试因此没报错）。
            _skip_keys=('run_cmd', 'ref_run_cmd', 'debug_run_cmd',
                        'ref_debug_run_cmd', 'plusargs', 'backend_args',
                        'plusarg_matrix'))

        settings = substituted.get('settings', {})
        default_count = settings.get('default_count', 1)
        tests = substituted.get('tests', [])
        tests = self.expand_matrix(tests)
        tests = self.expand_plusarg_matrix(tests)
        tests = self.expand_count(tests, default_count)

        if incremental:
            from ..utils.git_utils import filter_by_git_changes
            tests = filter_by_git_changes(tests, repo_path)

        substituted['tests'] = tests
        self._validate_plusargs(substituted)
        return substituted

    @staticmethod
    def _validate_plusargs(data: dict) -> None:
        """**生成期**守住 plusargs 的两条纪律（见 `backend_profiles`）。

        为什么必须在这里、而不是等运行期：`+ntb_random_seed` 与 `seeds` 同时
        出现时，UVM 只会安静地采用其中一个 —— 表现为"声明 18 条种子、实际
        只跑一条，回归全绿"。这种坑运行期看不出来，只能在生成期拦。
        """
        from src.layers.l2_orchestration.regression_tools import backend_profiles

        sim = backend_profiles.detect_simulator(data)
        if not sim:
            logger.warning("无法识别回归后端，跳过 plusargs 保留键校验"
                           "（请在 YAML 顶层写 `simulator:`）")
            return
        for test in data.get('tests') or []:
            if not isinstance(test, dict):
                continue
            plusargs = test.get('plusargs') or []
            if not plusargs:
                continue
            errors, warnings = backend_profiles.validate_plusargs(plusargs, sim)
            name = test.get('name', '?')
            for msg in warnings:
                logger.warning(f"{name}: {msg}")
            if errors:
                raise ConfigError(
                    f"{name}: " + "；".join(errors)
                    + f"（后端 {sim}；plusargs 只装测试语义参数，"
                      f"后端方言由 test/seeds/modes 生成）")

    def load_reference_finder(self) -> dict:
        """只读配置里的 `reference_finder:` 块，**不做完整渲染**。

        溯源入口只需要这个块。不能顺手把整份配置渲染出来，因为 `run_cmd` /
        `ref_run_cmd` 里会引用**只在跑某个具体版本时**才存在的变量
        （`RF_WORKTREE` / `RF_RUN_DIR`，由 Reference Finder 逐版本注入）——
        在这里完整渲染会立刻报「变量引用未定义」。

        走的仍然是 `build()` 那套加载链（include → extends → build 级 extends →
        `--set` 覆盖 → schema 校验），只是到渲染之前停住。
        """
        raw = self.load_yaml_with_includes(self.yaml_file)
        raw = self._resolve_extends(raw)
        raw = self._resolve_build_extends(raw)
        raw = self.apply_cli_overrides(raw)
        self.validate_config(raw)
        return raw.get('reference_finder') or {}

    def _resolve_build_extends(self, data: dict) -> dict:
        """build 级 `extends`：子 build 继承父 build 的字段，自己的覆盖父的。

        common_base.yaml 那套「子 build 只 override `variables.BUILD_OPTS`、
        编译命令从父 build 继承」靠的就是它。此前只有**顶层** `extends` 被处理，
        build 级的 `extends` 是 schema 收下、没人执行的死配置：子 build 拿不到
        run_cmd，会掉回 `settings.simulators` 模板生成一条空命令。

        父先定义的按顺序就地展开，所以支持链式继承（a → b → c）。
        """
        builds = data.get('builds')
        if not isinstance(builds, list):
            return data
        by_name = {b.get('name'): b for b in builds
                   if isinstance(b, dict) and b.get('name')}
        for build in builds:
            if not isinstance(build, dict):
                continue
            parent_name = build.pop('extends', None)
            if not parent_name:
                continue
            parent = by_name.get(parent_name)
            if parent is None:
                logger.warning(f"build '{build.get('name')}' extends 的 '{parent_name}' 不存在，忽略")
                continue
            if parent is build:
                logger.warning(f"build '{build.get('name')}' extends 了自己，忽略")
                continue
            merged = self._merge_config(parent, build)
            merged['name'] = build.get('name')
            build.clear()
            build.update(merged)   # 就地更新，保持 by_name 里的引用有效
        return data
    
    def _resolve_extends(self, data: dict) -> dict:
        if 'extends' in data:
            base_path = data.pop('extends')
            base_dir = os.path.dirname(self.yaml_file) or '.'
            base_full = os.path.join(base_dir, base_path)
            if not os.path.exists(base_full):
                logger.warning(f"Base config '{base_full}' not found, skipping extends.")
                return data
            base_data = self.load_yaml_with_includes(base_full, base_dir)
            return self._merge_config(base_data, data)
        return data