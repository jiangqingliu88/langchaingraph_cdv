# src/regression_framework/generators/shell.py
import os
import re
import zlib
import shutil
from jinja2 import Template
from ..core.config import render_str, expand_modes
from ..core.exceptions import ConfigError
from ...backend_profiles import join_args
from ..core.logging_config import get_logger
from ..models.scheduler import ERROR_PATTERN

logger = get_logger(__name__)


def _testpoint_test_map(run_root) -> dict:
    """TP IR 的 `execution.test` → `[tp_id…]`。

    一条用例（UVM test 类）可能挂多条测试点，签核要把它们都记下来 ——
    否则"这条波形在证明哪个测试点"又要靠人去翻 testpoints.yaml。

    读不到 / 解析失败返回 `{}`：这是**旁路索引**，不该拦住回归生成。缺失时
    `task_meta.json` 仍会带上标签里显式的 `TP-*`。
    """
    if not run_root:
        return {}
    path = os.path.join(str(run_root), "coverage", "testpoints.yaml")
    try:
        import yaml as _yaml
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            doc = _yaml.safe_load(fh) or {}
    except (OSError, ValueError):
        return {}
    tps = doc.get("testpoints") if isinstance(doc, dict) else None
    out = {}
    for tp in tps or []:
        if not isinstance(tp, dict):
            continue
        tp_id = str(tp.get("tp_id") or "").strip()
        test = str((tp.get("execution") or {}).get("test") or "").strip()
        if tp_id and test:
            out.setdefault(test, []).append(tp_id)
    return out


def _testpoint_case_map(run_root) -> dict:
    """TP IR 的 `execution.test` → `case_id`（Case IR 在生成期已注入）。

    同一测试类下的多条 TP 共用同一条 CASE（声明式）；合成式则可能一条 test
    对应多条 CASE —— 取第一个，并**不掩盖**（`case_ids` 全量也写进 meta）。
    """
    m = _testpoint_case_map_detail(run_root)
    return {test: ids[0] for test, ids in m.items() if ids}


def _testpoint_case_map_detail(run_root) -> dict:
    """`{test: [case_id…]}` —— 全量（去重保序）。"""
    if not run_root:
        return {}
    path = os.path.join(str(run_root), "coverage", "testpoints.yaml")
    try:
        import yaml as _yaml
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            doc = _yaml.safe_load(fh) or {}
    except (OSError, ValueError):
        return {}
    out = {}
    for tp in (doc.get("testpoints") if isinstance(doc, dict) else None) or []:
        if not isinstance(tp, dict):
            continue
        test = str((tp.get("execution") or {}).get("test") or "").strip()
        # 一条 TP 可被多条 CASE 共享（`case_ids` 全量）；旧 IR 只有 `case_id`
        ids = [str(c).strip() for c in (tp.get("case_ids") or []) if str(c).strip()]
        if not ids and str(tp.get("case_id") or "").strip():
            ids = [str(tp["case_id"]).strip()]
        for case_id in ids:
            if test and case_id not in out.get(test, []):
                out.setdefault(test, []).append(case_id)
    return out


def _testpoint_contract_map(run_root) -> dict:
    """TP IR 的 `execution.test` → 三集合指纹 `{groups, sva, scb}`。

    与 `_testpoint_test_map` 同源同口径：**只读** `coverage/testpoints.yaml`。
    缺字段就是空列表 —— 不在这里编 ID（契约由 verify 生成）。
    """
    if not run_root:
        return {}
    path = os.path.join(str(run_root), "coverage", "testpoints.yaml")
    try:
        import yaml as _yaml
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            doc = _yaml.safe_load(fh) or {}
    except (OSError, ValueError):
        return {}
    out = {}
    for tp in (doc.get("testpoints") if isinstance(doc, dict) else None) or []:
        if not isinstance(tp, dict):
            continue
        test = str((tp.get("execution") or {}).get("test") or "").strip()
        if not test:
            continue
        slot = out.setdefault(test, {"groups": [], "sva": [], "scb": []})
        for key in ("groups", "sva", "scb"):
            for item in tp.get(key) or []:
                if str(item) and str(item) not in slot[key]:
                    slot[key].append(str(item))
    return out


def _case_constraint_map(run_root) -> dict:
    """`case_ir.json` → `{case_id: [constraint ids]}`（第四集合，旁路索引）。

    约束归属由 verify 按 coverage plan 的维度交集算好；这里**只读**。
    缺文件/缺字段就是空 —— 不按测试名猜约束。
    """
    if not run_root:
        return {}
    path = os.path.join(str(run_root), "coverage", "case_ir.json")
    try:
        import json as _json
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            doc = _json.load(fh) or {}
    except (OSError, ValueError):
        return {}
    out = {}
    for case in (doc.get("cases") if isinstance(doc, dict) else None) or []:
        if not isinstance(case, dict) or not case.get("id"):
            continue
        ids = [str(c) for c in case.get("constraints") or [] if str(c)]
        if ids:
            out[str(case["id"])] = ids
    return out


def _case_ir_sha(run_root) -> str:
    """`case_ir_sha256` —— 证据对的是哪一版契约。

    **从 `methodology.json` 读**（verify 生成期算的规范哈希），不在回归侧
    另算一份：两处各算一次，字节/换行/键序稍有不同就会得到一个永远对不上的
    指纹 —— 那正是哈希链最该避免的事。读不到就回退到文件的 sha256。
    """
    if not run_root:
        return ""
    try:
        import json as _json
        with open(os.path.join(str(run_root), "coverage", "methodology.json"),
                  "r", encoding="utf-8", errors="replace") as fh:
            doc = _json.load(fh) or {}
        sha = str((doc or {}).get("case_ir_sha256") or "").strip()
        if sha:
            return sha
    except (OSError, ValueError):
        pass
    try:
        import hashlib
        with open(os.path.join(str(run_root), "coverage", "case_ir.json"), "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()
    except OSError:
        return ""


def _tst_id(test: str, seed) -> str:
    """`TST-<test>@<seed>` —— 与 `humanview.case_ir.tst_id_of` 同一口径。"""
    try:
        from src.layers.l3_decision.case_ir import tst_id_of
        return tst_id_of(test, seed)
    except Exception:                            # noqa: BLE001 身份层不可用不挡生成
        return f"TST-{test}@{seed}" if test else ""


def _tp_ids_from_tags(tags) -> list:
    """`TP-…` 形式的 tag → tp_id（与 `collect_real_coverage` 反查同一口径）。"""
    out = []
    for t in tags or []:
        s = str(t).strip()
        if s.upper().startswith("TP-"):
            out.append(s)
    return list(dict.fromkeys(out))


def _stage_from_tags(tags) -> str:
    for t in tags or []:
        s = str(t).strip().lower()
        if s in ("loopback", "p0", "p1", "p2", "p3"):
            return s
    return ""


def _uvm_test_from_command(sim_cmd: str, fallback: str) -> str:
    """从渲染后的仿真命令里取 `+UVM_TESTNAME=`（真正的 UVM 类名）。"""
    m = re.search(r"\+UVM_TESTNAME\s*[= ]\s*([^\s;'\"]+)", sim_cmd or "")
    return m.group(1) if m else fallback


def _contract_hash(run_root) -> str:
    """`contract/contract_manifest.json` 的 `contract_hash`（M1 构建物）。

    读不到就空串：**不拿 case_ir 的哈希冒充契约哈希** —— 两者语义不同，
    混用会让"证据对的是哪一版契约"这件事从此说不清。
    """
    if not run_root:
        return ""
    try:
        import json as _json
        with open(os.path.join(str(run_root), "contract", "contract_manifest.json"),
                  "r", encoding="utf-8", errors="replace") as fh:
            return str((_json.load(fh) or {}).get("contract_hash") or "")
    except (OSError, ValueError):
        return ""


def _contract_meta(test_class: str, contract_map, case_ir_sha: str,
                   contract_hash: str = "") -> dict:
    """`task_meta` 的三集合指纹段（group/sva/scb + 契约哈希）。"""
    slot = (contract_map or {}).get(test_class) or {}
    return {
        "group_ids": list(slot.get("groups") or []),
        "sva_ids": list(slot.get("sva") or []),
        "scb_ids": list(slot.get("scb") or []),
        "case_ir_sha": case_ir_sha,
        # M1：证据对的是**这一版契约**（构建物），不是 case_ir 文件
        "contract_hash": contract_hash,
    }


def _write_task_identity(test_dir, testcase, test_name, sim_cmd, t_context,
                         seed, build_name, test, tp_map, case_map=None,
                         contract_map=None, case_ir_sha="",
                         contract_hash="", constraint_map=None) -> None:
    """落 `task_meta.json` —— 用例 → 测试点 → 波形那条链的起点。

    归属优先级：显式 `tp_ids` > tag 里的 `TP-*` > `execution.test` 反查
    （`tp_map` 来自 `<run>/coverage/testpoints.yaml`）。失败只告警：这是
    旁路索引，不该拦住回归目录生成。
    """
    test_class = _uvm_test_from_command(
        sim_cmd, str(t_context.get('TEST') or test_name))
    tp_ids = list(_tp_ids_from_tags(test.get('tags') or []))
    for tid in tp_map.get(test_class, []):
        if tid not in tp_ids:
            tp_ids.append(tid)
    try:
        from src.tools.common.lib.case_meta import write_task_meta
        # 第四集合：这条执行依赖的约束（来自 case_ir，按 case_id 展开）
        constraint_ids = []
        for cid in (case_map or {}).get(test_class) or []:
            for c in (constraint_map or {}).get(cid) or []:
                if c not in constraint_ids:
                    constraint_ids.append(c)
        write_task_meta(test_dir, {
            "task": testcase,
            "test_name": test_name,
            "test": test_class,
            "seed": seed,
            "build": build_name,
            "stage": _stage_from_tags(test.get('tags') or []),
            "tags": list(test.get('tags') or []),
            "tp_ids": tp_ids,
            # ── 身份脊梁（v2）：CASE 来自 Case IR，TST 由 test+seed 派生 ──
            "case_ids": list((case_map or {}).get(test_class) or []),
            "case_id": ((case_map or {}).get(test_class) or [""])[0],
            "tst_id": _tst_id(test_class, seed),
            # 三集合指纹 + 契约哈希：这条任务自证"跑的是哪一版契约"
            **_contract_meta(test_class, contract_map, case_ir_sha, contract_hash),
            "constraint_ids": constraint_ids,
            "desc": str(test.get('desc') or ""),
        })
    except Exception as e:                      # noqa: BLE001 旁路索引
        logger.warning(f"{test_name}: task_meta 落盘失败: {e}")


class ShellGenerator:
    def __init__(self):
        self.context = {}
        self.settings = {}
        self.simulators = {}
        self.default_sim = 'vcs'
        self.default_build = 'build_base'
        self.hooks_global = {}
        self.cfg_env = {}
        self.root_dir = ''
        self.config_name = ''
        self.session_name = ''
        self.error_pattern = ERROR_PATTERN
        self.reference_mode = False
        self.debug_mode = False
        #: 分级裁剪判定（吃用例名 → 是否生成本级目录）；None = 生成全量。
        self.test_filter = None
        #: `execution.test → [tp_id]`（来自 <run>/coverage/testpoints.yaml）。
        self.tp_map = {}

    def generate(self, config: dict, root_dir: str, mode: str,
                 reference_mode: bool = False, debug_mode: bool = False,
                 test_filter=None, run_root=None):
        """生成 build/test 目录与脚本。

        `test_filter` 是**可选的用例裁剪判定**（吃一调用例名，返回 bool）。
        分级回归传 `make_tag_matcher(...)`，于是每一级的 build 目录里只出现
        **本级 tag** 的用例目录 —— 不再铺全量。

        不传 = 与从前逐字节一致（生成全部 test 目录，之后可用不同 `--tags`
        复跑同一棵树）。这是有意的：全量树便于人工反复筛选，而分级目录的
        意义是"这一级的证据"，两者不该互相绑架。
        """
        # 与 ConfigBuilder 保持一致：variables 是唯一的全局模板变量源
        self.context = {}
        self.context.update(config.get('variables', {}) or {})
        self.context.update(os.environ)
        # Eman 那套运行时变量（EMAN_*）的来源，见 `_eman_env`
        self.root_dir = os.path.abspath(root_dir)
        self.config_name = str(config.get('config_name') or os.path.basename(self.root_dir))
        # 会话名与 regression.py 落盘的 .regression_session.json 的 session_id 保持一致
        self.session_name = os.path.basename(self.root_dir)
        self.error_pattern = ERROR_PATTERN
        # **`env:` 才是环境变量，导进脚本；`variables:` 不是。**
        # `variables` 是**模板变量** —— 它们的用途是在生成脚本时被 `{{ }}`
        # 替换进命令正文（走上一步的 `self.context`），不是塞进进程环境。
        # 把 variables 也 export 出去，等于把 TB_TOP / debug_args 这类模板中间量
        # 污染成环境变量，还会让人误以为命令里可以写 `$TB_TOP`。
        # 要跨进程传给 EDA 工具的东西，写进 `env:`。
        self.cfg_env = config.get('env', {}) or {}
        # Reference Finder 跑**历史/参考版本**时置 True：有 `ref_run_cmd` 就改用它
        # （老版本的编译/仿真方式常和新版本不同，沿用 run_cmd 会编译不过，于是把
        # 「版本差异」误判成「bug 引入点」）。
        self.reference_mode = bool(reference_mode)
        # debug 模式：用 debug_run_cmd / ref_debug_run_cmd（开波形、放详细日志）
        self.debug_mode = bool(debug_mode)
        # 分级裁剪：吃用例名、返回是否生成本级目录（见 `_generate_build`）
        self.test_filter = test_filter
        # 测试点归属（用例 → tp_id）：从运行根下的 TP IR 反查。
        # `root_dir` 可能是 `<run>/regression_run/<stage>`，不能从它往上猜；
        # 调用方给 `run_root` 才是**唯一**说得清的那个落点。
        self.tp_map = _testpoint_test_map(run_root)
        # 用例身份（`test → case_id`）：和 tp_map 同源（TP IR），同样只做旁路。
        self.case_map = _testpoint_case_map_detail(run_root)
        # 三集合指纹 + 契约哈希（同样只读 TP IR / methodology）
        self.contract_map = _testpoint_contract_map(run_root)
        # 第四集合：约束归属（只读 case_ir）
        self.constraint_map = _case_constraint_map(run_root)
        self.case_ir_sha = _case_ir_sha(run_root)
        # M1：契约构建物的哈希（没有时为空串，task_meta 如实留空）
        self.contract_hash = _contract_hash(run_root)
        self.settings = config.get('settings', {})
        self.simulators = self.settings.get('simulators', {})
        self.default_sim = self.settings.get('default_simulator', 'vcs')
        self.default_build = self.settings.get('default_build', 'build_base')
        self.hooks_global = self.settings.get('hooks', {})

        os.makedirs(root_dir, exist_ok=True)
        logger.info(f"Creating shell scripts in {root_dir} (mode={mode})")

        builds = self._collect_builds(config)
        for build_name, build_conf in builds.items():
            self._generate_build(build_name, build_conf, root_dir, mode, config)

        if mode in ('mock', 'local'):
            self._generate_run_all(root_dir, mode, builds)

    def _collect_builds(self, config):
        builds = {}
        for test in config.get('tests', []):
            build = test.get('build')
            if isinstance(build, dict):
                build_name = build.get('name', 'inline_' + test['name'])
                builds[build_name] = build
                test['build'] = build_name
            elif isinstance(build, str):
                if build not in builds:
                    builds[build] = {}
            else:
                test['build'] = self.default_build
                if self.default_build not in builds:
                    builds[self.default_build] = {}
        for b in config.get('builds', []):
            name = b.get('name')
            if not name:
                continue
            if name not in builds or not builds[name]:
                # 覆盖空占位符或新增
                builds[name] = b
            else:
                # 合并：已有的 inline build 可能只有部分字段
                existing = builds[name]
                if isinstance(existing, dict):
                    merged = b.copy()
                    merged.update(existing)
                    builds[name] = merged
        return builds

    def _generate_build(self, build_name, build_conf, root_dir, mode, config):
        build_dir = os.path.join(root_dir, f"build_{build_name}")
        os.makedirs(build_dir, exist_ok=True)
        b_context = self.context.copy()
        b_context.update(build_conf.get('variables', {}))
        b_context.update(build_conf.get('local_vars', {}))
        # build 声明的 `top` 进上下文，run_cmd 里可以写 `{{ top }}`
        if build_conf.get('top'):
            b_context.setdefault('top', build_conf['top'])
        # EMAN_* 同一份既进 jinja 上下文（`{{ EMAN_RUN_DIR }}`）也进 export
        # （`${EMAN_RUN_DIR}`）—— 两种写法指同一个值，就不会出现"明明有这个名字
        # 却报未定义"。严格渲染下这一点更要紧。
        eman_build = self._eman_env(build_name, build_dir)
        b_context.update(eman_build)
        # ── 每个 build 用**自己的 work 库** ──
        # 共用一个库会把**别的 build 的类**带进来：DUT build 编的是全部 agent
        # （apb+uart+intr），loopback build 只该有 apb —— 但共用库时 loopback 的 tb
        # 加载会撞上 uart 的类，于是被迫解析 `virtual uart_if` 而报
        #   (vsim-8451) uart_port_monitor.sv: 'virtual uart_if' cannot find a matching instance
        #   → Error loading design（实测 apb_loopback 就是这么挂的）。
        # Questa 在 load 阶段解析设计里出现过的**每个** virtual interface 类型，
        # 跟"有没有例化"无关 —— 所以根治办法是别让不属于本 build 的类进这个库。
        # 编译与仿真必须用**同一个** WORK，故这里连同 test 上下文一起覆盖（见下）。
        b_context['WORK'] = f"{eman_build['EMAN_COMPILE_DIR']}/work"
        # 只导 `env:` 和框架的 EMAN_*；variables / local_vars 走 jinja 上下文
        build_exports = self._export_lines(self.cfg_env, eman_build)

        pre_cmd = build_conf.get('hooks', {}).get('pre_build') or self.hooks_global.get('pre_build')
        if pre_cmd:
            pre_cmd = self._substitute(pre_cmd, b_context, f"builds[{build_name}].hooks.pre_build")
            self._write_script(os.path.join(build_dir, 'pre_build.sh'), pre_cmd, "pre_build",
                               mode, exports=build_exports)

        sim = build_conf.get('simulator', self.default_sim)
        # **build 自带 `run_cmd` 时直接用**（demo.yaml 的写法）：一条完整编译命令，
        # 想写什么写什么 —— 不用再去迁就 `settings.simulators.<sim>.compile` 模板
        # 里那两个占位符（`{opts}` / `{files}`）。没有才回退到模板。
        _cmd = self._pick_run_cmd(build_conf)
        if _cmd:
            compile_cmd = self._substitute(_cmd, b_context, f"builds[{build_name}].run_cmd")
        else:
            opts = build_conf.get('compile_opts', [])
            files = build_conf.get('files', [])
            opts_str = ' '.join([self._substitute(opt, b_context, f"builds[{build_name}].compile_opts") for opt in opts])
            files_str = ' '.join(files)
            compile_tmpl = self.simulators.get(sim, {}).get('compile', 'vcs -full64 -sverilog {opts} {files}')
            compile_cmd = compile_tmpl.format(opts=opts_str, files=files_str)

        post_build_cmd = build_conf.get('hooks', {}).get('post_build') or self.hooks_global.get('post_build')
        if post_build_cmd:
            post_build_cmd = self._substitute(post_build_cmd, b_context, f"builds[{build_name}].hooks.post_build")

        self._write_build_script(build_dir, build_name, compile_cmd, build_exports, mode)

        # post_build 只在这里落一份 post_build.sh，**不再往 build.sh 里也拼一遍** ——
        # BuildTask 是「build.sh 跑完再跑 post_build.sh」，拼两处就执行两遍。
        if post_build_cmd:
            self._write_script(os.path.join(build_dir, 'post_build.sh'), post_build_cmd, "post_build",
                               mode, exports=build_exports)

        build_tests = [
            t for t in config.get('tests', [])
            if t.get('build') == build_name
            and (self.test_filter is None or self.test_filter(t.get('name', '')))
        ]
        for test in build_tests:
            test_name = test['name']
            seed = test.get('local_vars', {}).get('SEED', None)
            testcase = f"{test_name}_seed_{seed}" if seed is not None else test_name
            subdir = f"test_{testcase}"
            test_dir = os.path.join(build_dir, subdir)
            os.makedirs(test_dir, exist_ok=True)
            t_context = self.context.copy()
            t_context.update(test.get('variables', {}))
            t_context.update(test.get('local_vars', {}))
            # 结构化 test 名（给后端模板用；run_cmd 里可写 {{ TEST }}）
            t_context.setdefault('TEST', test.get('test') or test_name)
            # **每测试模式**：`modes: [cov, wave]` 只影响这一条用例的 MODE_OPTS。
            # 全局 `--enable` 仍然通过 config.variables 生效；这里是更细的一层。
            if test.get('modes'):
                _applied, _opts, _warn, _flags = expand_modes(
                    config.get('modes') or {}, t_context, test.get('modes'))
                for _w in _warn:
                    logger.warning(f"{test_name}: {_w}")
                if _opts:
                    t_context['MODE_OPTS'] = ' '.join(_opts)
                t_context.update(_flags)
            # 用户 plusargs / 逃生口：**统一在模板的 {{ PLUSARGS }} 处注入**。
            # 不能直接追加到整条命令末尾 —— 那是判据链 `;` 的后面，不是 vsim 的参数。
            _plusargs = list(test.get('plusargs') or [])
            _backend_args = list(test.get('backend_args') or [])
            t_context['PLUSARGS'] = join_args(_plusargs + _backend_args)
            if _backend_args:
                logger.warning(
                    f"{test_name}: 使用了 backend_args（后端逃生口）—— "
                    f"签核证据会记 caveat: {_backend_args}")
            # build 的 `top` 也进 test 的上下文：vsim 的设计单元是位置参数，
            # 模板里写 `{{ top }}` 比在每个 test 的 run_cmd 里重抄一遍省事。
            if build_conf.get('top'):
                t_context.setdefault('top', build_conf['top'])
            eman_test = self._eman_env(build_name, build_dir, test_name=test_name,
                                       test_dir=test_dir, seed=seed, testcase=testcase)
            t_context.update(eman_test)
            # 仿真必须加载**本 build 编出来的那个库** —— 上面把 WORK 覆盖成了
            # 每 build 独立，这里不跟着覆盖，vsim 就会去加载全局那个（含别的
            # build 的类）→ 又回到 8451。两边必须同一个值。
            t_context['WORK'] = b_context['WORK']
            test_exports = self._export_lines(self.cfg_env, eman_test)

            pre_sim_cmd = test.get('hooks', {}).get('pre_sim') or self.hooks_global.get('pre_sim')
            if pre_sim_cmd:
                pre_sim_cmd = self._substitute(pre_sim_cmd, t_context, f"tests[{testcase}].hooks.pre_sim")
                self._write_script(os.path.join(test_dir, 'pre_sim.sh'), pre_sim_cmd, "pre_sim",
                                   mode, exports=test_exports)

            # **test 自带 `run_cmd` 时直接用**（demo.yaml 的写法）：完整仿真命令。
            # 这条比模板强的地方很实在：模板只有 `{run_opts}` 一个占位符，
            # 顶层模块名、`-l <日志>`、跑完之后的成败判定都得挤进 run_opts 里；
            # 写成 run_cmd 就能正常表达，也不必再管"框架会在命令尾巴上加
            # `> sim.log 2>&1`"这件事。
            _tcmd = self._pick_run_cmd(test)
            _has_user_args = bool(_plusargs or _backend_args)
            if _tcmd:
                # 有用户参数却没有注入点 = 参数会被**静默丢掉**（或落到判据链后面）。
                # 生成期报错，让人去模板里加 `{{ PLUSARGS }}`。
                if _has_user_args and '{{ PLUSARGS' not in _tcmd:
                    raise ConfigError(
                        f"{test_name}: 声明了 plusargs/backend_args，但 run_cmd 里"
                        f"没有 `{{{{ PLUSARGS }}}}` 注入点 —— 参数会被丢掉。"
                        f"把注入点放在仿真命令之后、判据链 `;` 之前")
                sim_cmd = self._substitute(_tcmd, t_context, f"tests[{testcase}].run_cmd")
            else:
                run_opts_raw = test.get('run_opts', [])
                _opts = [self._substitute(opt, t_context, f"tests[{testcase}].run_opts")
                         for opt in run_opts_raw]
                if t_context.get('PLUSARGS'):
                    # 无 run_cmd 时模板只有 `{run_opts}`：用户参数追加在它后面，
                    # 顺序仍是「后端/框架选项 → 用户 plusargs → backend_args」。
                    _opts.append(t_context['PLUSARGS'])
                run_opts = ' '.join(_opts)
                sim_tmpl = self.simulators.get(sim, {}).get('run', './simv {run_opts}')
                sim_cmd = sim_tmpl.format(run_opts=run_opts)
            self._write_sim_script(test_dir, test_name, seed, sim_cmd, mode, exports=test_exports)

            # 用例身份（用例 → 测试点 → 波形那条链的起点）。写在**脚本落盘
            # 之后**：`+UVM_TESTNAME` 是渲染后的真名，原始配置里读不到。
            _write_task_identity(test_dir, testcase, test_name, sim_cmd,
                                 t_context, seed, build_name, test, self.tp_map,
                                 self.case_map, self.contract_map,
                                 self.case_ir_sha, self.contract_hash,
                                 self.constraint_map)

            post_sim_cmd = test.get('hooks', {}).get('post_sim') or self.hooks_global.get('post_sim')
            if post_sim_cmd:
                post_sim_cmd = self._substitute(post_sim_cmd, t_context, f"tests[{testcase}].hooks.post_sim")
                self._write_script(os.path.join(test_dir, 'post_sim.sh'), post_sim_cmd, "post_sim", mode)

    def _pick_run_cmd(self, conf: dict) -> str:
        """挑这条 build/test 该用哪条命令 —— ExecMan 的「备用命令字段」矩阵。

        两个正交的维度决定用哪条：

                普通版本            历史/参考版本
        normal  run_cmd             ref_run_cmd
        debug   debug_run_cmd       ref_debug_run_cmd

        · **参考版本**（Reference Finder 跑历史提交）为什么要换命令：老版本的
          编译/仿真方式常和新版本不同，沿用 `run_cmd` 会编译不过，于是「版本差异」
          被误读成「bug 引入点」—— 这是溯源结论最容易被污染的地方。
        · **debug 模式**为什么要换命令：调试跑法要开波形、放大日志，比普通跑慢得多，
          只在需要给调试分析提供素材时才用。

        逐级回退：精确命中的没有，就退到同一维度下更通用的那条，最后才用 `run_cmd`。
        全部缺失时返回空串（调用方会回落到模板路径）。
        """
        if self.debug_mode:
            if self.reference_mode and conf.get('ref_debug_run_cmd'):
                return conf['ref_debug_run_cmd']
            if conf.get('debug_run_cmd'):
                return conf['debug_run_cmd']
        if self.reference_mode and conf.get('ref_run_cmd'):
            return conf['ref_run_cmd']
        return conf.get('run_cmd') or conf.get('ref_run_cmd') or ''

    def _substitute(self, text, context, where=''):
        """渲染 `{{ }}`。与 `ConfigBuilder` 走**同一个**严格渲染器 —— 两个渲染点
        必须同样地「引用不存在的变量就报错」，否则一处严格一处静默，等于没管。
        """
        return render_str(text, context, where)

    def _eman_env(self, build_name, build_dir, test_name=None, test_dir=None,
                  seed=None, testcase=None) -> dict:
        """按 Eman 的变量表算出这一层上下文该有的 `EMAN_*`，全部是导出用的标量。

        本框架没有 build group / test group 这两层概念，所以 `BUILD_PATH` /
        `TEST_PATH` / `TEST_GROUP_PATH` 用「相对运行根的路径」和「用例名」顶上
        （见下面的布局）。目录布局是本框架既有的，只是把名字对到表上：

            <root>/                                  EMAN_TOP_RUN_DIR
            <root>/build_<name>/                     EMAN_COMPILE_DIR / EMAN_BUILD_PATH
            <root>/build_<name>/simv                 EMAN_SIMV
            <root>/build_<name>/simv_debug           EMAN_DEBUG_SIMV
            <root>/build_<name>/build.log            EMAN_LOG_FILE   (build 上下文)
            <root>/build_<name>/test_<tc>/           EMAN_RUN_DIR    (test 上下文)
            <root>/build_<name>/test_<tc>/sim.log    EMAN_LOG_FILE   (test 上下文)
            <root>/build_<name>/test_<tc>/cov/       EMAN_CM_DIR     (test 上下文)

        传了 `test_*` 就是 test 上下文：`EMAN_RUN_DIR` / `EMAN_CM_DIR` /
        `EMAN_LOG_FILE` 指向用例那一层，`EMAN_BUILD_*` 仍然指向它所属的 build；
        不传就是 build 上下文，`EMAN_TEST_*` 留空。

        `EMAN_BASE_STATUS` / `EMAN_CUSTOM_STATUS` **不在这里**：它们是跑完才有的
        结果，脚本执行时无从知晓，由调度器判完写进 `<run_dir>/status.env`。
        """
        root = self.root_dir
        rel_build = os.path.relpath(build_dir, root).replace(os.sep, '/')

        # 运行目录：test 上下文=用例目录，build 上下文=build 目录
        run_dir = test_dir or build_dir
        rel_run = os.path.relpath(run_dir, root).replace(os.sep, '/')

        env = {
            # ── 运行根 / 会话 ──
            'EMAN_TOP_RUN_DIR': self._posix(root),
            'EMAN_CONFIG_NAME': self.config_name,
            # 会话名 = 运行根目录名，与跑完落盘的 .regression_session.json 的
            # session_id 是同一个值（见 regression.py 的会话段）。
            'EMAN_SESSION_NAME': self.session_name,

            # ── 构建上下文 ──
            'EMAN_BUILD_NAME': build_name,
            'EMAN_BUILD_PATH': rel_build,
            'EMAN_COMPILE_DIR': self._posix(build_dir),
            'EMAN_SIMV': self._posix(os.path.join(build_dir, 'simv')),
            'EMAN_DEBUG_SIMV': self._posix(os.path.join(build_dir, 'simv_debug')),

            # ── 运行目录 / 覆盖率 / 日志（随上下文切换）──
            'EMAN_RUN_DIR': self._posix(run_dir),
            'EMAN_CM_DIR': self._posix(os.path.join(run_dir, 'cov')),

            # ── 判定规则（与调度器判定共用同一个常量）──
            'EMAN_ERROR_PATTERN': self.error_pattern,
        }

        if test_name is not None:
            tc = testcase or test_name
            env.update({
                'EMAN_TEST_NAME': test_name,        # 配置里的基础名，不带随机种子
                'EMAN_TESTCASE': tc,                # 带 seed 的用例全名
                'EMAN_RUN_DIR': self._posix(run_dir),
                'EMAN_CM_DIR': self._posix(os.path.join(run_dir, 'cov')),
                'EMAN_CM_NAME': tc,
                'EMAN_LOG_FILE': self._posix(os.path.join(run_dir, 'sim.log')),
                'EMAN_DEBUG_LOG_FILE': self._posix(os.path.join(run_dir, 'sim_debug.log')),
                # `<build>/<test>`：rel_run 本身就是 `build_<name>/test_<tc>`，
                # 不要再拼一次 rel_build（会把 build 目录拼成两层）。
                'EMAN_TEST_PATH': rel_run,
                # 没有 test group 这一层，组路径就是用例名本身
                'EMAN_TEST_GROUP_PATH': tc,
                'EMAN_RANDOM': self._random_seed(tc, seed),
            })
        else:
            env.update({
                'EMAN_TEST_NAME': '',
                'EMAN_TESTCASE': '',
                'EMAN_CM_NAME': '',
                'EMAN_LOG_FILE': self._posix(os.path.join(build_dir, 'build.log')),
                'EMAN_DEBUG_LOG_FILE': self._posix(os.path.join(build_dir, 'build_debug.log')),
                'EMAN_TEST_PATH': rel_build,
                'EMAN_TEST_GROUP_PATH': '',
                'EMAN_RANDOM': '',
            })
        return env

    @staticmethod
    def _posix(path: str) -> str:
        """导出路径统一成正斜杠。

        脚本是给 bash 跑的（LocalStrategy 就是 `bash <script>`），`D:\\a\\b` 在
        bash 里不是合法路径 —— 反斜杠会被当转义符吃掉，路径直接找不着。
        """
        return os.path.abspath(path).replace('\\', '/')

    @staticmethod
    def _random_seed(testcase: str, seed) -> str:
        """`EMAN_RANDOM`：有 seed 就用它；没有则从用例名派生一个**稳定**的数。

        特意用 `zlib.crc32` 而不是 Python 内建 `hash()`：后者对 str 每个进程都
        加随机盐（PYTHONHASHSEED），同一条用例两次生成会得到不同的种子，回归就
        不可复现了 —— 而这个框架的 `--rerun-failed` 和趋势库正是靠可复现。
        """
        if seed is not None:
            return str(seed)
        if not testcase:
            return ''
        return str(zlib.crc32(testcase.encode('utf-8')) & 0x7FFFFFFF)

    @staticmethod
    def _export_lines(*mappings) -> list:
        """把变量导成 shell 的 `export K='V'`，按传入顺序（靠后的覆盖靠前的）。

        只导标量、且只导合法标识符名：dict/list 塞进环境变量没有意义，名字不合法的
        （如 `rtl/`）会直接让 bash 报 `not a valid identifier` 打断脚本。
        """
        merged = {}
        for mapping in mappings:
            if isinstance(mapping, dict):
                merged.update(mapping)
        lines = []
        for key, value in merged.items():
            if not isinstance(key, str) or not re.match(r'^[A-Za-z_][A-Za-z0-9_]*$', key):
                continue
            if isinstance(value, bool):
                continue
            if not isinstance(value, str):
                if isinstance(value, (int, float)):
                    value = str(value)
                else:
                    continue
            # 值里可能有单引号：按 shell 的规矩 `'` → `'\''`（断开-转义-续上）
            safe = value.replace("'", "'\\''")
            lines.append(f"export {key}='{safe}'")
        return lines

    def _write_script(self, path, cmd, label, mode, exports=None):
        with open(path, 'w', encoding='utf-8') as f:
            f.write("#!/bin/bash\n")
            for line in exports or []:
                f.write(f"{line}\n")
            if mode == 'mock':
                f.write(f"echo \"[MOCK] {label}: {cmd}\"\n")
            else:
                f.write(f"{cmd}\n")
        os.chmod(path, 0o755)

    def _write_build_script(self, build_dir, build_name, compile_cmd, exports, mode):
        """build.sh 只放编译命令。

        post_build **不再拼进来**：`post_build.sh` 已经单独落了一份，而
        `BuildTask.execute` 是「跑 build.sh → 跑 post_build.sh」，拼两处就等于
        post_build 执行两遍。
        """
        with open(os.path.join(build_dir, 'build.sh'), 'w', encoding='utf-8') as f:
            f.write("#!/bin/bash\n")
            for line in exports or []:
                f.write(f"{line}\n")
            if mode == 'mock':
                f.write(f"echo \"[MOCK] Build {build_name}\"\n")
                f.write(f"echo \"  {compile_cmd}\"\n")
            else:
                f.write(f"{compile_cmd}\n")
        os.chmod(os.path.join(build_dir, 'build.sh'), 0o755)

    def _write_sim_script(self, test_dir, test_name, seed, sim_cmd, mode, exports=None):
        """生成 sim.sh，包含波形索引和性能计时"""
        with open(os.path.join(test_dir, 'sim.sh'), 'w', encoding='utf-8') as f:
            f.write("#!/bin/bash\n")
            for line in exports or []:
                f.write(f"{line}\n")
            if mode == 'mock':
                f.write(f"echo \"[MOCK] Test: {test_name} (seed={seed})\"\n")
                f.write(f"echo \"  {sim_cmd}\"\n")
            else:
                # 定义波形目录和文件路径。
                # **必须是绝对 POSIX 路径**，两个坑叠在一起：
                #   1. 直接写 `os.path.join` 在 Windows 上产出 `a\b\c`，bash 把
                #      反斜杠当转义符吃掉，`mkdir -p a\b\c` 变成一个叫 `abc` 的目录；
                #   2. 脚本执行时 cwd 是**用例自己的目录**（LocalStrategy 的
                #      `cwd=test_dir`），写相对运行根的路径会在这层目录里再套一份
                #      完整树。
                # 用绝对路径两个问题一起没了，也和 `EMAN_RUN_DIR` 保持一致。
                wave_dir = self._posix(os.path.join(test_dir, 'waves'))
                # Questa 波形库是 qwave.db（`vsim -qwavedb=…+wavefile=`），不是 fsdb；
                # 打开走 `visualizer -wavefile <这份 .db>`（见 ops.cov_actions.open_wave）。
                wave_file = f"{wave_dir}/{test_name}.db"
                f.write(f"mkdir -p {wave_dir}\n")
                # 计时并运行仿真。
                # **用秒级整数 + bash 内置算术**，不用 `date +%s.%N` + `bc`：
                # `bc` 不是到处都有（Windows/MSYS 上就没有），缺了它这两行会报
                # "bc: command not found"、`sim_time` 恒为空。整数秒对"哪条 case 慢"
                # 够用（`sim_time.log` 就是给 `_parse_task_result` 读的）。
                f.write(f"start_time=$(date +%s)\n")
                f.write(f"{sim_cmd} > sim.log 2>&1\n")
                f.write(f"ret=$?\n")
                f.write(f"end_time=$(date +%s)\n")
                # 计算仿真耗时（整数秒）
                f.write(f"sim_time=$((end_time - start_time))\n")
                f.write(f"echo \"SIM_TIME=$sim_time\" > sim_time.log\n")
                # 记录波形路径 —— **不看成败**：通过用例的波形同样要看
                # （界面「波形」列/点击读取的就是这份 wave.log）。
                f.write(f"if [ -f {wave_file} ]; then\n")
                f.write(f"    echo \"WAVE_PATH={wave_file}\" > wave.log\n")
                f.write(f"else\n")
                f.write(f"    echo \"WAVE_PATH=NOT_FOUND\" > wave.log\n")
                f.write(f"fi\n")
                f.write(f"exit $ret\n")
        os.chmod(os.path.join(test_dir, 'sim.sh'), 0o755)

    def _generate_run_all(self, root_dir, mode, builds):
        fname = 'run_all_mock.sh' if mode == 'mock' else 'run_all_local.sh'
        path = os.path.join(root_dir, fname)
        with open(path, 'w', encoding='utf-8') as f:
            f.write("#!/bin/bash\n")
            f.write(f"echo \"Running regression in {root_dir} (mode={mode})\"\n")
            if mode == 'local':
                f.write("set -e\n")
            for build_name in builds.keys():
                f.write(f"echo \"--- Build {build_name} ---\"\n")
                f.write(f"cd build_{build_name} && ./build.sh && cd ..\n")
                f.write(f"for testdir in build_{build_name}/test_*; do\n")
                f.write(f"  if [ -d \"$testdir\" ]; then\n")
                f.write(f"    cd $testdir && ./sim.sh && cd ../..\n")
                f.write(f"  fi\n")
                f.write(f"done\n")
        os.chmod(path, 0o755)