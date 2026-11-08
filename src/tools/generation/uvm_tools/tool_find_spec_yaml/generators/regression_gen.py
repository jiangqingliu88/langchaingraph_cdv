"""回归产物生成器 —— 从 `find_spec_yaml/main.py` 拆出的 `regression_gen`。

负责：`regression.yaml`、分级 tag、种子展开、测试点回归任务、loopback 用例。
只读输入 + 生成文本；不渲染 Jinja、不碰 env/coverage 产物。
"""
from __future__ import annotations

import builtins
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List


def print(*args, **kwargs):
    kwargs.setdefault("file", sys.stderr)
    builtins.print(*args, **kwargs)


def _load_spec(output_dir: Path):
    """延迟导入主模块的 `_load_spec` —— 避免 main ↔ generators 的循环导入。"""
    from ..main import _load_spec as impl
    return impl(output_dir)


def _is_agent_active(output_dir: Path, agent_name: str) -> bool:
    """检查 agent 是否 active（被动 agent 无 driver，loopback 自闭环无意义）。

    激活模式由 env 级 agents[].is_active 决定（interface 级不再携带）。
    """
    yp = output_dir / "inputs" / "yaml" / "uvm" / "env.yaml"
    if not yp.exists():
        return True
    try:
        data = _yaml.safe_load(yp.read_text(encoding="utf-8", errors="replace")) or {}
        agents = (data.get("environment") or {}).get("agents") or {}
        if isinstance(agents, dict):
            entry = agents.get(agent_name)
        else:
            entry = next((a for a in agents
                          if isinstance(a, dict) and a.get("name") == agent_name), None)
        if isinstance(entry, dict) and entry.get("is_active") is not None:
            return str(entry["is_active"]).strip().lower() in ("true", "1", "yes", "on")
    except Exception:
        return True
    return True


def _dedupe_loopback_tests(test_lines: list, lb_names: set) -> list:
    """重名 test 只保留**最后一次**出现的那条（带独立 loopback build + 正确顶层）。

    为什么必须"留最后一条"而不是"遇到重名就全删"：loopback 用例由**两处**产生 ——
      · case 库里那条：绑在 DUT build 上、顶层是 `<m>_bench_tb_top`（**错**）；
      · 本函数上面刚生成的那条：绑 `build_<m>_<ag>_loopback`、顶层 `<ag>_loopback_tb`（**对**）。
    后者排在后面。原先的写法把**所有**同名的都删了 —— 把对的那条也删掉，只剩绑错
    build 的那条；那目录里是给别的 top 用的脚本，一跑就是 "Error loading design"，
    记成 `unknown`，还会让闭环绕开覆盖率阶段。
    """
    if not lb_names:
        return list(test_lines)
    last: dict = {}
    for i, line in enumerate(test_lines):
        if line.startswith("  - name: "):
            name = line[len("  - name: "):].strip()
            if name in lb_names:
                last[name] = i
    kept: list = []
    skip = False
    for i, line in enumerate(test_lines):
        if line.startswith("  - name: "):
            name = line[len("  - name: "):].strip()
            # 只在**不是最后一次**出现时丢弃（即丢掉重复的早期那条）
            skip = name in lb_names and i != last.get(name)
        if not skip:
            kept.append(line)
    return kept


def _seed_plan(output_dir: Path) -> Dict[str, Dict[str, int]]:
    """`coverage/coverage_plan.yaml` → `{test 名: {base, count, explore}}`。

    计划是 **verify 阶段与 case 模型同批**落盘的（见
    `executors/verify/main.py::_write_coverage_plan`），这里只读不算 ——
    种子是**验证完备性的声明**（这一批要跑够几条），不是回归自己拍的参数。

    读不到就给空 dict（回归按默认 `count: 1` 跑）—— **不编一个种子出来**：
    编出来的种子会让"这一批到底跑够没有"变得无法回答。
    """
    path = output_dir / "coverage" / "coverage_plan.yaml"
    if not path.is_file():
        return {}
    try:
        import yaml as _yaml
        plan = _yaml.safe_load(path.read_text(encoding="utf-8", errors="replace")) or {}
    except Exception:
        return {}
    out: Dict[str, Dict[str, int]] = {}
    for b in (plan.get("batches") or []):
        if not isinstance(b, dict):
            continue
        test, seeds = str(b.get("test") or "").strip(), b.get("seeds") or {}
        if not test:
            continue
        # `dimensions` **两种形状都认**：计划里是列表，env 注入那份是逗号串
        # （注入走 YAML 流式一行，列表要另写缩进）。`str(list)` 会得到
        # `"['D_type']"` —— 那既是噪音又会在 desc 里露出来。
        dims = b.get("dimensions")
        dims = ",".join(str(x) for x in dims) if isinstance(dims, list) else str(dims or "")
        entry: Dict[str, Any] = {"theme": str(b.get("theme") or ""),
                                 "priority": str(b.get("priority") or ""),
                                 "dimensions": dims}
        if isinstance(seeds, dict):
            entry.update({k: int(v) for k, v in seeds.items()
                          if isinstance(v, int)})
        out[test] = entry
    return out


def _seed_offset(output_dir: Path) -> int:
    """闭环"扩种"动作留下的**种子偏移**（`coverage/seed_expand.json`）。

    ## 为什么需要这条线

    决策层选 `EXPAND_SEEDS` 时会把 `{"count": N}` 交给 `n_apply_expand_seeds`，
    那边写进 `state.seed` 并记一行"扩种 → seed += N" —— **但那个 state 只被当
    覆盖 agent 的输入用**，回归的 `SEED` 一直是写死的 `12345` + case 模型声明的
    `base`。于是这个动作是个**静默空转**：账上记着"扩了种"，仿真跑的却是同一批
    随机流，覆盖率每轮钉在同一个数（实测六轮 56.2 不动，而每轮 ucdb 的 sha256
    都不一样 —— 数据在采，只是采的是同一批激励）。

    约定：`n_apply_expand_seeds` 每轮把偏移**累加**着写进这个文件（单调递增，
    不覆盖历史），回归生成时把偏移加到每条 test 的基准种子上。
    读不到就是 `0`（没扩过种）—— 不编一个偏移出来。
    """
    path = Path(output_dir) / "coverage" / "seed_expand.json"
    if not path.is_file():
        return 0
    try:
        import json as _json
        return int((_json.loads(path.read_text(encoding="utf-8",
                                                 errors="replace")) or {}).get("offset", 0))
    except Exception:                                      # noqa: BLE001
        return 0


def _seed_lines(name: str, plan: Dict[str, Dict[str, int]],
                offset: int = 0) -> List[str]:
    """这条 test 的 `count` / `SEED` 两行（计划里没有就 `count: 1`）。

    **`count` 展开的种子是"基准 + 逐条递增"**（回归框架 `expand_count`）——
    所以这里只给**基准**，`count` 条各自拿 `base + i - 1`。`{{ SEED }}` 的
    落点是 `run_cmd`（`_sim_run_cmd` 里的 `+ntb_random_seed`）。

    `explore`（探索种子）**并进 count**：它是"防过拟合那几条"，跑法一样、只是
    目的不同；分成两条 test 反而让"这一批一共跑了多少次"说不清。

    `offset` 是闭环"扩种"动作累加出来的偏移（见 `_seed_offset`）—— 加到**基准**
    上，于是整段的随机流换一条（不是把 count 撑大：多跑几条同样的种子没有意义，
    要的是**没跑过的**那些）。
    """
    s = plan.get(name)
    if not s:
        return ["    count: 1"]
    total = int(s.get("count", 0)) + int(s.get("explore", 0))
    if total <= 0:
        return ["    count: 1"]
    return [f"    count: {total}",
            f"    variables: {{SEED: {int(s.get('base', 0)) + int(offset or 0)}}}"]


def _tp_regression_lines(output_dir: Path, module_name: str, env_name: str,
                         dut_top: str, seed_offset: int = 0,
                         run_cmd_fn=None) -> List[str]:
    """**可激励测试点 → 回归任务**（一条 TP 一条 test）。

    ## 补的是哪一半

    属性 test 类一直是**生成了、但没有任何回归任务执行它** —— 测试点在模型里
    说得再清楚，跑不到就等于没有。批次测试覆盖的是"随机打一片"，而每条属性
    测试点覆盖的是"这个取值**确定**被驱动过"；两者不能互相替代。

    收两类：
      · `stimulus` —— 属性 test 真驱动事务字段；
      · `backdoor` —— 属性 test 用 `uvm_hdl_force` 把内部状态摆到目标值
        （**需要 `-voptargs=+acc`**，否则信号被优化掉、force 失败）。
    `observe` 没有激励差异、`sequence` 还没有场景生成器，都不占回归槽。

    分级取 TP IR 的 `execution.stage`（由专题优先级派生）—— **不再靠目录名
    或 tag 手写**："这一条该在哪一级跑"是模型说的。
    """
    from src.layers.l3_decision.vplan import engine

    project = engine.project_for(_load_spec(output_dir) or {}, output_dir)
    if project is None:
        return []
    try:
        payload = engine.run_testpoints(
            project, env_name=env_name, module_name=module_name,
            max_tests=200)
    except Exception as e:                             # noqa: BLE001 旁路，别拦回归生成
        print(f"  [find_yaml] 测试点回归未生成: {e}", flush=True)
        return []
    if payload.get("error"):
        print(f"  [find_yaml] 测试点回归未生成: {payload['error']}", flush=True)
        return []

    if run_cmd_fn is None:
        return []

    lines: List[str] = []
    for tp in payload.get("testpoints") or []:
        realization = tp.get("realization") or {}
        execution = tp.get("execution") or {}
        kind = str(realization.get("kind") or "")
        if kind not in ("stimulus", "backdoor", "sequence"):
            continue
        # **没有逐笔取值的 sequence 不占回归槽**：它生成不了确定差异，
        # 跑一条"看起来是场景、其实只是随机"的用例比不跑更糟。
        if kind == "sequence" and not (realization.get("values") or []):
            continue
        test = str(execution.get("test") or "").strip()
        if not test:
            continue
        seeds = execution.get("seeds") or []
        seed = (int(seeds[0]) if seeds else 12345) + int(seed_offset or 0)
        slug = re.sub(r"[^a-z0-9]+", "_",
                      str(tp.get("tp_id") or "tp").lower()).strip("_")
        if slug.startswith("tp_"):
            slug = slug[len("tp_"):]
        name = f"tp_{slug}"
        lines.append(f"  - name: {name}")
        lines.append(f"    build: build_{module_name}_dut")
        # **仍然走 `_seed_lines`**：测试点是一条定向用例（不是种子批次），
        # 计划里没有它 → 退回单条 count。但不在这里写死第二个字面量 ——
        # 那条"所有 test 都过 _seed_lines"的契约测试会抓到（实测）。
        # 种子偏移必须一路传到这里：漏了就是"扩种只对批次生效，定向 TP 永远跑老种子"
        lines.extend(_seed_lines(name, {}, seed_offset))
        lines.append(f"    variables: {{SEED: {seed}}}")
        # `run_cmd` 的成败判据与其它 test **同一份实现**（`_sim_run_cmd` 是
        # `_generate_regression_yaml` 的嵌套函数）—— 不在这里复制一段，
        # 否则"真 pass 要 mismatched=0"这条判据就出现了第二个版本。
        if kind == "backdoor":
            lines.append(f"    run_cmd: '{run_cmd_fn(dut_top, test, '-voptargs=+acc')}'")
        else:
            lines.append(f"    run_cmd: '{run_cmd_fn(dut_top, test)}'")
        tags = [f'"{execution.get("stage") or "p3"}"', '"tp"']
        if kind == "backdoor":
            tags.append('"backdoor"')
        if kind == "sequence":
            tags.append('"sequence"')
        tags.append(f'"{tp.get("tp_id")}"')
        lines.append(f"    tags: [{', '.join(tags)}]")
        suffix = {"backdoor": " · 后门到达", "sequence": " · 场景序列"}.get(kind, "")
        lines.append(f'    desc: "{tp.get("tp_id")}：{tp.get("dimension")}='
                     f'{tp.get("value")}（{tp.get("requirement") or ""}）'
                     f'{suffix}"')
        lines.append("")
    return lines


def _generate_regression_yaml(output_dir: Path, yaml_dir: Path,
                               module_name: str, env_name: str,
                               top_module: str,
                               agents: list, filelist_name: str = "filelist.f") -> Path:
    """生成回归框架可用的 regression.yaml（builds + tests）。

    从 spec.json 提取 test_points 作为测试用例列表。
    """
    reg_dir = output_dir / "inputs" / "yaml"
    reg_dir.mkdir(parents=True, exist_ok=True)
    reg_path = reg_dir / "regression.yaml"

    # filelist 引用固定路径（filelist.f 的实际生成在回归执行时由 L1.run_regression 完成，
    # 因为 find_spec_yaml 运行于 jinja_render 之前，agents/env/bench 尚未生成）
    fl_dir = output_dir / "inputs" / "filelists"
    fl_path = fl_dir / filelist_name
    filelist_ref = str(fl_path.resolve()).replace("\\", "/")

    # 种子管理：从**与 case 模型同批落盘**的功能覆盖率计划里读（只读不算）
    seed_plan = _seed_plan(output_dir)
    # 闭环"扩种"动作的偏移（`coverage/seed_expand.json`，由 apply 阶段写入）。
    # **不加这一条，扩种就是个静默空转**：决策记着"seed += N"，回归照旧跑
    # 写死的 12345 + 计划的 base，每轮同一批随机流（实测覆盖率六轮不动）。
    seed_offset = _seed_offset(output_dir)
    if seed_offset:
        print(f"  [find_yaml] 扩种偏移 +{seed_offset}：每条 test 的基准种子已顺移"
              f"（闭环扩种动作的落点）", flush=True)

    # 从 spec.json 提取测试点
    test_points = []
    spec_path = output_dir / "spec.json"
    if spec_path.exists():
        try:
            spec_data = json.loads(spec_path.read_text(encoding="utf-8"))
            test_points = spec_data.get("test_points", []) or []
        except Exception:
            pass

    # 从 case 库（testcase_registry）读用例 —— case 库是"用例真相源"，regression.yaml 与它对齐
    # 注意：case 库是跨 run 共享的，在项目根 .signoffai/（而非 run 目录 .signoffai/）
    cases = []
    try:
        from src.layers.l4_memory.testcase_registry import TestcaseRegistry
        case_reg = TestcaseRegistry()
        # **按模块筛**：这个库是项目级的，躺着所有跑过的模块 —— 不筛就会把
        # 别的项目的用例写进本项目的 regression.yaml（实测：NPU 的 p0 里跑了
        # 14 条 apb_uart 的名字，全用本地 test 兜底执行，同一个仿真数了十几遍）。
        cases = case_reg.get_priority_order(stage=0, limit=50, module=module_name)
        # 回归模式开关：增量（默认，只跑未 passed）/ 全量（跑所有用例）
        try:
            from config.settings import Settings
            incremental = Settings.get_instance().verification.incremental_regression
        except Exception:
            incremental = True
        if incremental:
            cases = [c for c in cases if c.get("status") in ("planned", "generated")]
        case_reg.close()
    except Exception:
        cases = []

    dut_build = f"build_{module_name}_dut"
    dut_top = f"{top_module}_bench_tb_top"

    def _sim_run_cmd(top: str, uvm_test: str, extra_opts: str = "") -> str:
        """一条完整的仿真命令（demo.yaml 的 `run_cmd` 写法）。

        比旧的 `run_opts` + 全局 `settings.simulators.<sim>.run` 模板强在：
        顶层模块名、日志文件、**跑完怎么判成败**都能直接写进来，不必挤占
        `run_opts`，也不必再管"框架会在命令尾巴追加 `> sim.log 2>&1`"。

        末尾那句 `! grep ...` 是**唯一的失败判据**：回归框架只看退出码，而 vsim
        无论跑出多少 UVM_ERROR / UVM_FATAL，只要最后 `quit -f` 了就是 exit 0 ——
        实测 `+UVM_TESTNAME=不存在的测试` 这种 UVM_FATAL(INVTST) 也是 0，
        于是"一条都没跑"被记成 PASS。**只匹配计数非 0 的那行**
        （`UVM_ERROR :    3`）；匹配裸 `UVM_ERROR :` 会连 `UVM_ERROR :    0` 一起命中。
        日志走 `-l sim_vsim.log`，避免和框架那句收尾重定向抢同一个文件。

        **为什么还要匹配 `FATAL ERROR` / `Errors: *[1-9]`**：UVM 那两条计数管不到
        "仿真根本没起来"——实测 8 条用例挂在 `vsim-3772 Failed to load DPI auto
        compile shared library`，vsim 直接 `FATAL ERROR while loading design` 退出，
        日志里一条 `UVM_ERROR :` 都没有，于是**全部记成 PASS**（波形、覆盖率自然
        也没有）。末尾那行 `# Errors: 2, Warnings: 0` 是 vsim 自己的结算，按它判
        才盖得住这一类。

        `{{ MODE_OPTS }}` 是**仿真业务的落点**（波形 / 覆盖率 / 调试…）：里面装的是
        本次启用的那几门业务的选项串，由回归框架的 `apply_modes()` 按 `modes:` 表
        拼好（表见 `src/layers/l2_orchestration/regression_tools/common_base.yaml`，取值见 `sim_modes.py`）。
        没启用任何业务时它是未定义的，所以必须 `| default("")` —— 渲染走的是
        `StrictUndefined`，裸 `{{ MODE_OPTS }}` 会在"什么都不开"的那次直接报错。
        """
        # `[ -s sim_vsim.log ] &&` **不能省**：日志**不存在或为空**时，`grep` 自己
        # 报错退出（非零），而 `!` 一取反就成了**通过** —— 于是"vsim 压根没起来"
        # 被记成 pass。实测踩过：环境里 vsim 崩了（连 `sim_vsim.log` 都没生成），
        # 一整轮回归全绿、覆盖率 0%，而各用例的 status.env 都是 pass。
        # 先要求日志非空，再谈里面有没有错。
        #
        # ── 第三段：**"没报错"不等于"验过了"** ──
        #
        # 用户定的口径：**真 pass = SCB 报 `mismatched=0`（真有比对） + 断言不报错**。
        # 前两段只查了"没有错"，那对一条**压根没有判据**的用例同样成立 —— 实测：
        # p0/p1 的 env 测试既没例化 scoreboard、也没断言，20 条照样全绿，而
        # `test_npu_basic_test` 覆盖率 0.0%/0.0% 也是 pass。
        #
        # 所以再要求一条**比对结论**：日志里得有 `mismatched=0`（SCB 的结算行）。
        # 没有 → 判失败并**写明原因**（`NO_CHECKER_EVIDENCE`），而不是冒充通过。
        # 断言那半不需要额外条件：断言违规走 `$error` → Questa 打 `** Error:` →
        # 第二段的 `Errors: *[1-9]` 已经拦住（实测：把 RTL 的 RAW 守卫删掉，
        # 断言立刻报错、退出码非零）。
        # 命令模板按**后端档案**取（`backend_profiles.py`）。Questa 一份；
        # 其它后端要在同一张数据表里补 `run_cmd_template`，不在这里写 if/elif。
        #
        # `{{ PLUSARGS }}` 是**用户 plusargs 的唯一注入点**，位置在 `;` 之前 ——
        # 直接往整条命令尾巴追加会把参数放到判据链后面（那不是给 vsim 的）。
        from src.layers.l2_orchestration.regression_tools.backend_profiles import render_sim_command

        return render_sim_command("questa", top, uvm_test, extra_opts)

    # 构建测试列表
    test_lines = []
    if cases:
        # case 库对齐：每个 case 一个 test（run_opts 用 random_test，case 名用于追踪 + 回写状态）
        for c in cases:
            cname = c.get("name", "case")
            priority = c.get("priority", "P1")
            scenario = c.get("scenario", "")
            test_lines.append(f"  - name: {cname}")
            test_lines.append(f"    build: build_{module_name}_dut")
            test_lines.extend(_seed_lines(cname, seed_plan, seed_offset))
            # 完整仿真命令（demo.yaml 的 `run_cmd` 写法）：顶层模块名、日志路径、
            # 跑完的成败判定都写在这一条里，不再往 `run_opts` 里挤。
            _run_cmd = _sim_run_cmd(dut_top, f"{env_name}_directed_test")
            test_lines.append(f"    run_cmd: '{_run_cmd}'")
            test_lines.append(f"    tags: [\"{priority.lower()}\", \"{scenario}\"]")
            test_lines.append("")
    elif test_points:
        for i, tp in enumerate(test_points):
            tid = tp.get("id", f"test_{i}")
            tname = tid.lower().replace("-", "_")
            desc = tp.get("description", tp.get("feature", ""))
            priority = tp.get("priority", "P1")
            test_lines.append(f"  - name: {tname}")
            test_lines.append(f"    build: build_{module_name}_dut")
            test_lines.extend(_seed_lines(tname, seed_plan, seed_offset))
            # 完整仿真命令（demo.yaml 的 `run_cmd` 写法）：顶层模块名、日志路径、
            # 跑完的成败判定都写在这一条里，不再往 `run_opts` 里挤。
            _run_cmd = _sim_run_cmd(dut_top, f"{env_name}_base_test")
            test_lines.append(f"    run_cmd: '{_run_cmd}'")
            test_lines.append(f"    tags: [\"{priority.lower()}\", \"{tid}\"]")
            if desc:
                test_lines.append(f"    desc: \"{desc[:80]}\"")
            test_lines.append("")
    else:
        # 回退：环境级测试（base/directed/random）—— env/tests 里真正生成的 test 类
        # 同上：这三个都真实存在（`_random_test` 不在其列，删掉）。
        for _tname in (f"{env_name}_base_test", f"{env_name}_directed_test"):
            test_lines.append(f"  - name: test_{_tname}")
            test_lines.append(f"    build: build_{module_name}_dut")
            test_lines.extend(_seed_lines(f"test_{_tname}", seed_plan, seed_offset))
            # 完整仿真命令（demo.yaml 的 `run_cmd` 写法）：顶层模块名、日志路径、
            # 跑完的成败判定都写在这一条里，不再往 `run_opts` 里挤。
            _run_cmd = _sim_run_cmd(dut_top, _tname)
            test_lines.append(f"    run_cmd: '{_run_cmd}'")
            test_lines.append(f"    tags: [\"smoke\"]")
            test_lines.append("")

    # ── 生成测试（随机 + 覆盖率缺口定向激励）──
    #
    # 上面每条 case 跑的都是**定向测试**。定向测试按剧本发固定几笔事务，多一笔
    # scoreboard 就对不上账（实测：往定向测试里注入额外激励，24 个 case 挂 21 个）。
    # 而覆盖率缺口补出来的定向激励**正是额外激励** —— 它只该落在能容忍它的
    # `*_gen_test` 上。
    #
    # 没有这条 case 会怎样：补出来的序列生成、注册、编译全过，但**没有任何 case
    # 执行它** —— 表现为"补了测试但覆盖率一动不动"（实测 5 轮 88.0%，一分没涨）。
    # 这条 case 就是让那段激励真正跑起来的地方（顺带每次回归都多一份随机激励，
    # 那本来就是随机测试该干的事）。
    #
    # 名字不取自 case 库（它是环境自带的测试，不是某个验证用例）：case 库回写
    # 状态时对不在册的名字会直接跳过（`TestcaseRegistry.update_status` 查不到就 return），
    # 不会污染用例库。
    test_lines.append(f"  - name: {module_name}_gen_stimulus")
    test_lines.append(f"    build: build_{module_name}_dut")
    test_lines.extend(_seed_lines(f"{module_name}_gen_stimulus", seed_plan, seed_offset))
    test_lines.append(f"    run_cmd: '{_sim_run_cmd(dut_top, f'{env_name}_gen_test')}'")
    # `p3` = 错误 + 随机。原先只有 `smoke/random/gap` —— **没有任何 pN tag**，
    # 于是这条随机用例哪个分级都进不去（分级回归按 p0..p3 筛，见 REGRESSION_STAGES）。
    test_lines.append('    tags: ["p3", "smoke", "random", "gap"]')
    test_lines.append("")

    # ── 批次测试（**一条 = 一个 UVM_TEST = 一个批次/专题**）──
    #
    # 与用例库那一批**并存**：那边一条一个属性取值（粒度细，追状态与用例库），
    # 这边一条一个批次（粒度粗，挂**种子管理**）。两侧的名字不同、用途不同，
    # 合并不了 —— 合并了"这一批一共跑了多少次"就又说不清了。
    #
    # `+UVM_TESTNAME` 用**批次名**，对应 `test_batch.sv.j2` 生成的类
    # （`environment.batches` → `{env}_batch_test.sv`）。类不存在的话 UVM 报
    # INVTST 而 vsim 仍然 exit 0 —— **跑不起来反而看不出来**。
    if seed_plan:
        for bname, meta in seed_plan.items():
            test_lines.append(f"  - name: {bname}")
            test_lines.append(f"    build: build_{module_name}_dut")
            test_lines.extend(_seed_lines(bname, seed_plan, seed_offset))
            test_lines.append(f"    run_cmd: '{_sim_run_cmd(dut_top, bname)}'")
            prio = (meta.get("priority") or "P1").lower()
            theme = meta.get("theme") or ""
            # tag 用**分级回归那四级**（p0..p3）—— 分级就是按它筛的
            test_lines.append(f'    tags: ["{prio}", "batch", "{theme}"]')
            if meta.get("dimensions"):
                test_lines.append(f'    desc: "批次 {theme}：打 {meta["dimensions"]}"')
            test_lines.append("")

    # ── 测试点回归（**可激励 TP 一条一个任务**）──
    #
    # 属性 test 以前生成了却从没被任何回归任务执行 —— 这是"死标签"的第二半。
    # 分级由 TP IR 的 `execution.stage` 决定（专题优先级派生），不再手写 tag。
    test_lines.extend(_tp_regression_lines(output_dir, module_name, env_name,
                                           dut_top, seed_offset, _sim_run_cmd))

    # ── loopback 测试（每个 active agent 一个，独立 build + 独立顶层 {ag}_loopback_tb）──
    # 同时把 loopback 用例注册进 case 库（用例真相源），跨 run 沉淀。
    for ag in agents:
        if not _is_agent_active(output_dir, ag):
            continue
        try:
            from src.layers.l4_memory.testcase_registry import TestcaseRegistry
            _cr = TestcaseRegistry()
            _cr.register(f"test_{ag}_loopback", purpose="smoke",
                         scenario="loopback", priority="P0")
            _cr.close()
        except Exception:
            pass
        test_lines.append(f"  - name: test_{ag}_loopback")
        test_lines.append(f"    build: build_{module_name}_{ag}_loopback")
        test_lines.extend(_seed_lines(f"test_{ag}_loopback", seed_plan, seed_offset))
        # 完整仿真命令（demo.yaml 的 `run_cmd` 写法）：顶层模块名、日志路径、
        # 跑完的成败判定都写在这一条里，不再往 `run_opts` 里挤。
        _run_cmd = _sim_run_cmd(f"{ag}_loopback_tb", f"{ag}_loopback_test")
        test_lines.append(f"    run_cmd: '{_run_cmd}'")
        test_lines.append(f"    tags: [\"smoke\", \"loopback\"]")
        test_lines.append("")

    # ── 去掉重名 test ──
    #
    # case 库里也有叫 `apb_loopback` / `uart_loopback` 的用例，而上面 loopback 那一轮
    # 又会注册 `test_<ag>_loopback` —— 两条同名 test 会让 ShellGenerator 生成**同名
    # 目录**（`test_test_apb_loopback`），其中一个被排到另一个的 build 上跑：
    # 那目录里是给别的 top 用的脚本，一跑就是 "Error loading design"，记成 `unknown`，
    # 而且 `is_elab_failure_line` 会据此把每一格 sim 日志都读一遍 → 闭环绕开覆盖率阶段。
    # 保留后面那条（带独立 loopback build 和正确的 top），前面的整块删掉。
    _lb_names = {f"test_{ag}_loopback" for ag in agents if _is_agent_active(output_dir, ag)}
    test_lines = _dedupe_loopback_tests(test_lines, _lb_names)

    tests_section = "\n".join(test_lines)

    # ── builds 段：每个 build 一条**完整编译命令**（run_cmd）──
    #
    # 与 demo.yaml 同一套契约：`run_cmd` 里可以用 `{{ VAR }}` 取 `variables`，
    # 也可以直接写 shell 的 `${VAR}`。比旧的 `compile_opts` + `files` 表达力强，
    # 也不必再迁就 `settings.simulators.<sim>.compile` 模板的 `{opts}` / `{files}`。
    #
    # filelist 名是 `filelist_<agent 目录名>_lb.f`（`build_loopback_filelist` 由
    # L1.run_regression 拿 `agents/` 下的**目录名**生成，即 `{ag}_agent`）——
    # 写成协议名会 "Failed to open -f file .../filelist_uart_lb.f"。
    # 覆盖率是**编译期**使能的（vlog +cover），仿真期那句 `-coverage` 只是"允许保留
    # 已使能的统计"。所以"默认开覆盖率"这件事必须落在**编译命令**上，否则 vsim 那边
    # 挂了一串覆盖率开关，却没有任何被插桩的代码可采。
    #
    # 用 `cov_enabled`（`apply_modes` 给启用中的 mode 设的标记）而不是每次编译都加：
    # 不选覆盖率业务时命令与从前**逐字节一致**，不去动已经跑通的那条路。
    # `| default(false)` 不能省 —— 渲染走 StrictUndefined，裸 `{% if cov_enabled %}`
    # 在"没启用"的那次直接抛 UndefinedError。
    _cov_build_flag = " {% if cov_enabled | default(false) %}+cover{% endif %}"

    builds_lines = [
        f"  - name: build_{module_name}_dut",
        f"    top: {top_module}_bench_tb_top",
        f"    run_cmd: 'vlog -work {{{{ WORK }}}} -sv -mfcu +incdir+{{{{ UVM_SRC }}}}"
        f" {{{{ UVM_SRC }}}}/uvm_pkg.sv -f {filelist_ref}{_cov_build_flag}'",
    ]
    for ag in agents:
        if not _is_agent_active(output_dir, ag):
            continue
        lb_ref = str((fl_dir / f"filelist_{ag}_agent_lb.f").resolve()).replace("\\", "/")
        builds_lines.append(f"  - name: build_{module_name}_{ag}_loopback")
        builds_lines.append(f"    top: {ag}_loopback_tb")
        builds_lines.append(
            f"    run_cmd: 'vlog -work {{{{ WORK }}}} -sv -mfcu +incdir+{{{{ UVM_SRC }}}}"
            f" {{{{ UVM_SRC }}}}/uvm_pkg.sv -f {lb_ref}{_cov_build_flag}'")
    builds_section = "\n".join(builds_lines)

    from config.settings import questa_home
    _questa_root = questa_home().replace("\\", "/")

    # ── 仿真业务模式：include common_base.yaml（`modes:` 表的来源）+ 本后端取值 ──
    #
    # `include:` 把 `common_base.yaml` 当**基底**合并（框架 `_merge_config`：本地优先）。
    # 要的是它那张 `modes:` 表 —— 业务词条（wave/cov/upf…）→ 选项变量 的映射是**一份
    # 语义来源**，另起一套名字迟早两边对不上。
    #
    # **但它的值是 VCS 语义**（`-cm line+cond+…`、`+DUMP_FILE=…fsdb`），而本文件的
    # builds/tests 是 Questa（vlog/vsim）：把 VCS 参数原样拼进 vsim，vsim 判"未知选项"、
    # 整轮回归全崩。所以下面把同名变量**就地覆盖**成 Questa 取值（见 `sim_modes.py`，
    # 每条都在本机 `vsim -help` 里核过）。合并规则是本地优先，覆盖是有效的。
    #
    # 另一处要注意的：common_base 自己的 4 个 build（multi_step_build 等）会一起被
    # 合并进来，它们跑的是 `VCS …`。它们**没有任何 test 挂在上面**，而 L1 调度只跑
    # "yaml 里声明给该 build 的 test"（见 InfrastructureManager.run_regression 的
    # `tests_by_build`），所以永远不会被排进去。这条不变量有测试钉着
    # （tests/test_sim_modes.py::test_common_base_builds_are_never_scheduled）。
    from src.layers.l2_orchestration.regression_tools.sim_modes import (common_base_path,
                                                     yaml_variables)
    _mode_vars = "\n".join(f"  {k}: '{v}'" for k, v in yaml_variables().items())
    _common_base = common_base_path().as_posix()

    yaml_content = f"""# 回归测试配置 — 由 find_spec_yaml 自动生成
# 用法: python regression.py --config {reg_path.as_posix()} --action all --mode local
#
# ── 用的是 demo.yaml 那套契约（variables + 每 build/test 自带 run_cmd）──
# 旧写法（`global_vars` + `settings.simulators.<sim>.compile/run` 模板）留给
# 回归框架的模板只有 `{{files}}` / `{{run_opts}}` 两个占位符，想表达"顶层模块名"
# "日志路径""跑完怎么判成败"都只能往 run_opts 里硬塞，还得记住框架会在命令尾巴上
# 追加 `> sim.log 2>&1`。写成完整 `run_cmd` 就都不用绕了。
#
# ── 仿真业务模式（波形 / 覆盖率 / 调试…）──
# `modes:` 表与聚合变量机制来自 include 的 common_base.yaml；下面同名变量按本后端
# （Questa）**覆盖**了它的 VCS 取值。启用哪几门业务由上层给（CLI `--enable` /
# 工作台工具栏下拉，默认 cov+wave），框架的 apply_modes() 把它们拼进 MODE_OPTS，
# 仿真命令里写 `{{{{ MODE_OPTS | default("") }}}}` 取用。
# 值给空串的那些（xprop/tprop/upf）是本后端**没有对应开关**的：选中会被告警忽略，
# 不会把一个不存在的参数塞进命令行。

# 本文件是**后端特定**的生成物（当前 Questa）。保留键校验按这个字段选表；
# 换后端 = 换一份 YAML 模板 + 这里换名字，不改框架代码。
simulator: questa

include:
  - {_common_base}

variables:
  # 闭环"扩种"动作的偏移加在基准上（见 `_seed_offset`）—— 加到**每一条**上，
  # 否则没有批次计划的那些 test（loopback / 手写用例）永远跑同一批随机流。
  SEED: {12345 + int(seed_offset or 0)}
  QUESTA: {_questa_root}
  UVM_SRC: {_questa_root}/verilog_src/uvm-1.2/src
  UVM_DPI: {_questa_root}/uvm-1.2/win64/uvm_dpi
  WORK: {str((output_dir / 'build' / 'work').resolve()).replace(chr(92), '/')}
  BENCH_TOP: {top_module}_bench_tb_top
{_mode_vars}

builds:
{builds_section}

tests:
{tests_section}
"""
    reg_path.write_text(yaml_content, encoding="utf-8", errors="replace")
    return reg_path


