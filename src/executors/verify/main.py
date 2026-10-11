"""验证开发智能体 —— UVM环境 + 测试用例 + 断言（真实工具链）"""
from typing import Dict, Any, List, Optional
import json
from pathlib import Path

from src.layers.l2_orchestration.executors.base import BaseExecutor, ExecutorResult
from src.layers.l2_orchestration.executors.registry import register_executor
import structlog

logger = structlog.get_logger()


@register_executor("verify")
class VerifyExecutor(BaseExecutor):
    """验证开发智能体 = uvm + test + assert"""

    task_type = "code_generation"
    consumes = ["spec", "design_arch"]
    produces = "tests"

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(
            role="verify", display_name="验证开发智能体",
            description="UVM环境+测试用例+断言", config=config or {})

    async def _setup(self):
        logger.info(f"{self.display_name} 初始化完成")

    async def _get_prompt_template(self):
        return None

    async def _get_tools(self):
        return []

    async def _execute(self, input_text: str):
        return {"output": ""}

    async def execute_task(self, task: Dict[str, Any]) -> ExecutorResult:
        from src.layers.l1_infrastructure.output_config import make_output_root
        output_dir = Path(make_output_root(task.get("output_dir") or None))
        task["output_dir"] = str(output_dir)

        ctx = task.get("ctx", {})
        spec = ctx.get("spec", {}) if hasattr(ctx, 'get') else {}
        if not isinstance(spec, dict):
            spec = {}

        module_name = spec.get("design_name", "dut") or "dut"
        params = task.get("params", {}) or {}
        supplement = params.get("supplement", False) if isinstance(params, dict) else False
        gaps = params.get("gaps", []) if isinstance(params, dict) else []
        design_style = params.get("design_style", "baseline")
        files = []
        #: 策略包的语义 bin —— 攒着，等 `find_spec_yaml` 跑完再落盘（理由见下面那段）
        cov_bins_for_render: List[Any] = []

        # ── 策略包：按 design-style 加载设计风格验证知识，注入 spec 供测试生成 ──
        try:
            from src.layers.l2_orchestration.governance.policy_pack import get_policy_pack_loader
            pack = get_policy_pack_loader().load(design_style)
            if pack and isinstance(spec, dict):
                spec["_policy_pack"] = {
                    "design_style": pack.design_style,
                    "prompt_hints": pack.prompt_hints,
                    # 带 id 的条目 —— `hint_ids` 落盘的来源（见 `_generate_gap_tests`）
                    "prompt_hint_items": pack.prompt_hint_items(),
                    "test_scenarios": pack.test_scenarios,
                    "coverage_bins": pack.coverage_bins,
                }
                cov_bins_for_render = list(pack.coverage_bins or [])
            else:
                # 不静默：策略包没加载出来 = 语义 cross 不会生成，覆盖率模型会退化成
                # 只有按字段自动分箱的那几个 coverpoint
                logger.warning(f"策略包未加载（design_style={design_style}），"
                               f"本次不会生成语义化 cross")
        except Exception as e:
            logger.warning(f"策略包加载失败（语义化 cross 将缺失）: {e}")

        # ── supplement 模式：只生成 gap 定向激励，不重新生成 env（避免覆盖已放宽的约束）──
        if supplement and gaps:
            try:
                self._generate_gap_tests(output_dir, gaps)
                for p in (output_dir / "agents").rglob("*_gap_seq.sv"):
                    files.append(str(p))
            except Exception as e:
                logger.warning(f"gap 定向激励生成失败: {e}")
            tests_data = {
                "module": module_name,
                "env_files": len(files),
                "files": files,
                "status": "gap_supplement" if files else "empty",
                # **这次注入的验证策略条目** —— 有 id 才谈得上"哪条 hint 有用"
                # （这一轮记的是"用了什么"，结局的关联是下一层统计）
                "hint_ids": list(getattr(self, "_hint_ids", []) or []),
            }
            score = min(50 + len(files) * 2, 90) if files else 20
            return ExecutorResult(success=bool(files), data={"tests": tests_data, "score": score})

        # ── 1. UVM 环境生成（真实工具 uvm_tools）──
        env_gen_ok = False
        try:
            # 经 `call_tool` 调（走 ToolHub 的 schema 校验 + 审计回执）。
            # 这两个工具的 output_dir 来自模块级 `_uvm_ctx`（不是参数），所以
            # 下面那句 set() 仍然必需 —— 它指向的是同一个 ctx 单例。
            from src.layers.l2_orchestration.communication.tool_hub import call_tool
            from src.tools.uvm_tools.agent_tools import _uvm_ctx
            _uvm_ctx.set(output_dir=output_dir, agents=[], env_name=f"{module_name}_env")
            # 保存 spec 供 find_spec_yaml 读取
            (output_dir / "spec.json").write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
            call_tool("find_spec_yaml", {"spec_text": json.dumps(spec, ensure_ascii=False)})
            # ⚠️ **落盘必须在这里，不能更早。**
            #
            # `find_spec_yaml` 第一步就把 `inputs/yaml/uvm/*.yaml` **清空**（那是它的
            # 私有产物目录，见那个函数的注释）。在它之前写进去的东西，等 `jinja_render`
            # 去渲染 env_cov 时已经不在了 —— 实测：这一句原来在策略包那一段（本函数
            # 开头），于是 `cov_bins`（语义 cross）**从来没有进过 env_cov**，而
            # `field_bins`（case 模型的边界 bin）同样会在渲染前被删掉。表现是覆盖率
            # 模型静默退回"值类自动分箱"，命令行与日志看上去一切正常。
            #
            # 顺序必须是：find_spec_yaml（清空 + 重建）→ **写 bins** → jinja_render（读）。
            self._write_env_cov_bins(output_dir, cov_bins_for_render)
            call_tool("jinja_render", {"output_dir": str(output_dir)})
            env_files = [str(p) for p in (output_dir / "agents").rglob("*.sv")] \
                if (output_dir / "agents").exists() else []
            # 失败响亮：env 骨架没生成出来（agents/ 空）→ 记失败，不得靠断言文件蒙混"passed"
            env_gen_ok = len(env_files) > 0
            if env_gen_ok:
                files.extend(env_files)
        except Exception as e:
            logger.warning(f"UVM 生成失败: {e}")
        if not env_gen_ok:
            logger.error(f"UVM 环境生成失败（agents/ 下无 SV 文件），verify 阶段如实失败")
            return ExecutorResult(success=False, data={
                "tests": {"module": module_name, "env_files": 0, "files": [],
                          "status": "env_generation_failed"},
                "score": 0,
                "error": "UVM 环境生成失败：agents/ 下无 SV 文件（检查 find_spec_yaml/jinja_render 日志与 jsonschema 依赖）",
            })

        # ── 2. 测试点分解（**casemodel_tools**）──
        #
        # 这里原来是 `testcase_tools` 的三连：parse_test_points → map_policies_to_tests
        # → build_scenario_yaml，产出 `inputs/yaml/constraint.yaml`。那个包**已经删掉**，
        # 于是这一段每次运行都只留下一句 `No module named 'src.tools.testcase_tools'`
        # 的 warning —— 分解测试点这件事实际上一直是没做的。
        #
        # 现在走 casemodel：它吃一份 **case 模型 YAML**（功能组织树 + P0/P1/P2 专题 +
        # 维度约束组合），吐 case 属性表与 UVM tests 片段。工具本体在
        # `src/tools/casemodel_tools/`（零 LLM 依赖），Agent 侧的三个包装面在
        # `src/executors/verify/casemodel/`。
        #
        # **case 模型从哪来**：闭环里目前**没有** spec → case 模型的桥（设计阶段不产出
        # 它）。所以这一步现在是**有条件生效**的 —— 找到就用，找不到就明确说一句，不
        # 假装做过。要让它真正常态生效，得让设计阶段产出一份，或者由人给一份。
        case_model = _find_case_model(spec, output_dir)
        if case_model is None:
            case_model = _synthesize_case_model(spec, output_dir)
        if case_model is None:
            logger.info("这次运行没有 case 模型 —— 跳过测试点分解（casemodel）")
        else:
            try:
                from src.tools.casemodel_tools.api import run_gaps, run_generate

                yaml_text = case_model.read_text(encoding="utf-8", errors="replace")
                gaps = run_gaps(yaml_text)
                if gaps.get("error"):
                    logger.warning(f"case 模型有问题，跳过分解: {gaps['error']}")
                else:
                    result = run_generate(yaml_text)
                    if result.get("error"):
                        logger.warning(f"case 生成失败: {result['error']}")
                    else:
                        yaml_dir = output_dir / "inputs" / "yaml"
                        yaml_dir.mkdir(parents=True, exist_ok=True)
                        # 产物落在这里（旧 `constraint.yaml` 的位置）：它是"这一步分
                        # 解出了什么"的凭证，人可以在「产物审查」页看它、改它。
                        (yaml_dir / "case_table.json").write_text(
                            json.dumps({"case_model": str(case_model),
                                        "score": gaps.get("score"),
                                        "count": result.get("count"),
                                        "cases": result.get("cases", [])},
                                       ensure_ascii=False, indent=2),
                            encoding="utf-8")
                        files.append(str(yaml_dir / "case_table.json"))
                        logger.info(f"测试点分解完成: {result.get('count')} 条 case"
                                    f"（源：{case_model.name}）")
            except Exception as e:
                logger.warning(f"测试点分解失败（casemodel）: {e}")

        # ── 3. 断言生成（真实工具 assertion_tools）──
        try:
            from src.layers.l2_orchestration.communication.tool_hub import call_tool
            # 参数名是 `specs`（不是 spec_json）—— 以 manifest 的 schema 为准
            sva = call_tool("generate_sva_assertions",
                            {"specs": json.dumps(spec, ensure_ascii=False)})
            asrt_dir = output_dir / "assertions"
            asrt_dir.mkdir(parents=True, exist_ok=True)
            (asrt_dir / f"{module_name}_assertions.sv").write_text(sva, encoding="utf-8")
            files.append(str(asrt_dir / f"{module_name}_assertions.sv"))
        except Exception as e:
            logger.warning(f"断言生成失败: {e}")

        tests_data = {
            "module": module_name,
            "env_files": len(files),
            "files": files,
            "status": "generated" if files else "empty",
        }
        score = min(50 + len(files) * 2, 90) if files else 20
        return ExecutorResult(success=bool(files), data={"tests": tests_data, "score": score})

    # ── 功能覆盖率点：case 模型 → env_cov 的 bin ──

    def _write_env_cov_bins(self, output_dir: Path, cov_bins: List[Any]) -> None:
        """把 `env_cov_bins.yaml` 落到 `find_spec_yaml` 之后、`jinja_render` 之前。

        两个键：

          · `cov_bins`   —— 策略包的语义 cross（`env_cov.sv.j2` 渲染成 `cross_<name>`）
          · `field_bins` —— **case 模型**的边界 bin（渲染成 `cp_<字段>` 的 bins）

        **键名是 `cov_bins`**（不是 `coverage_bins`）：与 schema 的文档类型一致 ——
        用错的名字会让 `UVMGenerator.run()` 的 schema 检查报 error 并 `SystemExit`，
        于是之后任何一次渲染都被它挡住（实测）。消费端两个键名都认，老的运行目录
        不受影响。

        `field_bins` 是「功能覆盖率方法学」真正落地的地方。**为什么不另生成一个
        `coverage/<module>_cg.sv`**：那份文件从来**没有进过编译清单**（全仓库没有
        一处把它加进 filelist），于是它永远不被采样 —— 一个看着像覆盖率模型、
        其实一个 bin 都没测的文件，比没有更坏。真正被编译/采样/统计的是
        `env_cov.sv.j2` 里那几个 `cg_<agent>`（monitor 每笔事务触发
        `write_<agent>` → `sample()`），所以把模型的边界 bin 喂进那条已跑通的通道：
        coverpoint 名就是事务字段名（= spec 的接口信号名）。

        拿不到模型就不写 `field_bins` —— 模板会退回"值类自动分箱"（0/1/其余），
        那是**降级**不是失败，所以只记一条日志。
        """
        try:
            bins_dir = output_dir / "inputs" / "yaml" / "uvm"
            bins_dir.mkdir(parents=True, exist_ok=True)
            payload: Dict[str, Any] = {"cov_bins": list(cov_bins or [])}
            field_bins = self._case_model_field_bins(output_dir)
            if field_bins:
                payload["field_bins"] = field_bins
                logger.info(f"功能覆盖率点（case 模型）：{len(field_bins)} 个字段的边界 "
                            f"bin 已注入 env_cov → 会被真编译、真采样")
            else:
                logger.info("没有可用的 case 模型覆盖点 —— env_cov 退回值类自动分箱")
            (bins_dir / "env_cov_bins.yaml").write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        except Exception as e:                       # noqa: BLE001 旁路，别拦 env 生成
            logger.warning(f"env_cov bin 落盘失败（覆盖率模型将退回自动分箱）: {e}")

    @staticmethod
    def _case_model_field_bins(output_dir: Path) -> Dict[str, List[Dict[str, Any]]]:
        """`inputs/casemodel.yaml` → `{字段名: [{name, value}, …]}`（给 `env_cov` 用）。

        键是**字段名**（`paddr` / `pwdata` / `pwrite`）—— case 模型的字段名就是
        spec 的接口信号名，而 `env_cov` 的 coverpoint 挂在 `agent_item.<字段>` 上，
        两边是同一个命名空间，所以能直接对上。对不上的字段由模板忽略（它按事务字段
        遍历），不会生成引用不到信号的 bin。

        拿不到模型（文件不在 / 解析失败）就返回空 —— 调用方据此退回自动分箱，
        **不静默假装有模型**。
        """
        from src.layers.l1_infrastructure.layout import casemodel_path

        cm_file = casemodel_path(output_dir)
        if not cm_file.is_file():
            return {}
        try:
            from src.tools.casemodel_tools.api import run_covergroups

            points = run_covergroups(cm_file.read_text(encoding="utf-8"),
                                     output_dir.name[:0] or "dut")
        except Exception as e:                       # noqa: BLE001 旁路，别拦生成
            logger.warning(f"读 case 模型失败（env_cov 退回自动分箱）: {e}")
            return {}
        if points.get("error"):
            logger.warning(f"case 模型构建失败（env_cov 退回自动分箱）: "
                           f"{points['error']}")
            return {}

        out: Dict[str, List[Dict[str, Any]]] = {}
        for cp in points.get("coverpoints") or []:
            bins = [{"name": b["name"], "value": b["value"]}
                    for b in cp.get("bins") or []]
            if bins:
                out[cp["signal"]] = bins
        return out

    # ── gap 定向激励生成辅助 ──

    def _generate_gap_tests(self, output_dir: Path, gaps: list):
        """根据 gap 生成定向激励 sequence，注册到 agent package 并注入 random test。

        **文件位置一律问 `agent_layout`，不按平铺名猜。** 生成的 env 用编号子目录
        布局（`1_interface/`、`3_transaction_sequencer/`…），按 `<agent>_interface.sv`
        这种名字找的结果是每个 agent 都被跳过 —— 补测试产出 0 个文件，
        `verify_supplement` 判 FAIL 20，那个动作等于空转（实测）。
        """
        import re
        from src.tools.coverage_tools.main import generate_gap_directed_seq
        from src.tools.lib.env_introspect import (binding_for_agent,
                                                 env_agent_bindings)
        from src.tools.lib.filelist import agent_layout

        agents_dir = output_dir / "agents"
        if not agents_dir.exists() or not gaps:
            return

        # 读 DUT RTL 供 LLM 因果反推（output signal 的缺口需要理解 DUT 逻辑）
        dut_rtl = ""
        rtl_dir = output_dir / "rtl"
        if rtl_dir.exists():
            for sv in sorted(rtl_dir.glob("*.sv")):
                dut_rtl = sv.read_text(encoding="utf-8", errors="replace")
                break

        # **验证策略包的领域知识**：这是 `prompt_hints` 唯一的消费点（见
        # `llm_generate_gap_stimulus`）。没有它，那份"prompt 库"就只是个没人读的字段。
        self._design_hints = ""
        try:
            _pack = (spec.get("_policy_pack") or {}) if isinstance(spec, dict) else {}
            self._design_hints = str(_pack.get("prompt_hints") or "")
            self._hint_ids = [str(it.get("id", "")) for it in
                              (_pack.get("prompt_hint_items") or []) if it.get("id")]
            if self._design_hints:
                logger.info(f"gap 激励将注入验证策略（{len(self._design_hints)} 字符）")
        except Exception:                              # noqa: BLE001
            pass

        # 环境接线（句柄 / 序列器成员 / 事务项类型）—— 从生成出来的 env 里读，
        # 不猜。读不到就如实跳过：编一个名字去生成只会得到编译不过的代码。
        bindings = env_agent_bindings(output_dir)
        if not bindings:
            logger.warning("读不到 env 接线（env_agent_bindings 返回空），跳过定向激励")
            return

        generated = []
        for agent_dir in sorted(agents_dir.iterdir()):
            if not agent_dir.is_dir():
                continue
            agent_dir_name = agent_dir.name
            prefix = agent_dir_name[:-len("_agent")] \
                if agent_dir_name.endswith("_agent") else agent_dir_name
            binding = binding_for_agent(bindings, agent_dir_name)
            if not binding or binding.get("unresolved") or not binding.get("item"):
                logger.info(f"{agent_dir_name}: 接线读不出来"
                            f"（{binding.get('unresolved') if binding else '没有对应句柄'}），"
                            f"跳过定向激励")
                continue
            layout = agent_layout(agent_dir)
            # 只对 input agent（interface 有 output 数据端口，即 TB 驱动 DUT 输入）生成；
            # output agent 的 driver 是空实现，驱动它无意义
            if not layout["interface"]:
                logger.info(f"{agent_dir_name}: 找不到接口文件（见 agent_layout），跳过定向激励")
                continue
            iface_text = "\n".join(
                p.read_text(encoding="utf-8", errors="replace") for p in layout["interface"])
            # 这个 agent 会不会驱动 DUT？（驱动方向写在**时钟块**里）
            # 模板接口是"内部 logic + 时钟块 + modport"那一套：master_cb 里是
            # `output paddr;` —— 没有 `logic` 也没有位宽。原来只认
            # `output logic` / `output [`，于是**每个 agent 都被判成"不驱动 DUT"**
            # 而跳过（实测：补激励产出 0 个文件，verify_supplement FAIL 20）。
            if not re.search(r"^\s*output\s+\w", iface_text, re.M):
                continue
            if not layout["seq_items"]:
                logger.info(f"{agent_dir_name}: 找不到事务项（*_seq_item.sv），跳过定向激励")
                continue
            # 事务项可能拆成多份（base / master / slave）—— 全读，宽度表按变量名合并
            tx_text = "\n".join(
                p.read_text(encoding="utf-8", errors="replace") for p in layout["seq_items"])
            widths = {}
            for m in re.finditer(r"rand\s+bit\s*\[(\d+):0\]\s+(\w+)\s*;", tx_text):
                widths[m.group(2)] = int(m.group(1)) + 1
            # input agent 处理所有 gap：input signal 直接驱动，output signal LLM 反推，generic 随机
            agent_gaps = [g for g in gaps if isinstance(g, dict)]
            if not agent_gaps:
                continue
            seq_code = generate_gap_directed_seq(
                prefix, agent_gaps, widths, dut_rtl, item_class=binding["item"],
                design_hints=self._design_hints)
            seq_path = agent_dir / f"{prefix}_gap_seq.sv"
            seq_path.write_text(seq_code, encoding="utf-8")
            if not layout["package"]:
                logger.warning(f"{agent_dir_name}: 找不到主包，gap sequence 无法注册（不 include）")
                continue
            self._add_include_to_pkg(layout["package"], seq_path.name)
            generated.append({"cls": f"{prefix}_gap_seq",
                              "dir": agent_dir_name,
                              "handle": binding["handle"],
                              "member": binding.get("member", "sequencer"),
                              "extends": f"uvm_sequence #({binding['item']})"})
            logger.info(f"{agent_dir_name}: 定向激励已生成 {seq_path.name}"
                        f"（{len(agent_gaps)} 个 gap；item={binding['item']}，"
                        f"发往 env.{binding['handle']}.{binding.get('member', 'sequencer')}）")

        if generated:
            self._inject_gap_seq_to_test(output_dir / "env" / "tests", generated)
            # 铁律 1：LLM 生成的代码必须经真实 EDA（vlog）编译校验返回 0/1，阻断自说自话
            compiled = self._verify_compilation(output_dir)
            # **记结局**：prompt 库能不能淘汰全看这张表（"有它 vs 没它"）。
            # 这里能确定的结局只有"生成的序列过没过 EDA 编译门禁"；覆盖率增量是
            # 多因素的，算到单条 hint 头上是过度归因（见 l4_memory/hint_stats.py）。
            try:
                from src.layers.l4_memory.hint_stats import record_hint_outcome

                _ids = list(getattr(self, "_hint_ids", []) or [])
                record_hint_outcome(
                    _ids, compiled, run_id=Path(output_dir).name,
                    note=f"生成 {len(generated)} 个定向 seq" if compiled else "编译门禁未过")
            except Exception as _e:                    # noqa: BLE001 旁路
                logger.debug(f"hint 结局记账跳过: {_e}")
            if not compiled:
                logger.warning("gap sequence 编译校验失败，回退为空实现（LLM 代码被 EDA 否决）")
                self._neutralize_gap_seq(output_dir, generated)

    def _verify_compilation(self, output_dir: Path) -> bool:
        """铁律 1：调用真实 EDA（vlog）编译校验，返回 0/1 作为唯一真理。

        不靠 AI 自我判断语法/时序，只认 vlog 的 PASS/FAIL。
        """
        try:
            from src.tools.lib.compile import run_compile_check
            env_name = ""
            for p in sorted((output_dir / "env").glob("*_pkg.sv")):
                env_name = p.name.replace("_pkg.sv", "")
                break
            agents = []
            agents_dir = output_dir / "agents"
            if agents_dir.exists():
                agents = [{"name": d.name} for d in agents_dir.iterdir() if d.is_dir()]
            result = run_compile_check(output_dir, agents, env_name)
            return bool(result.get("passed", False))
        except Exception as e:
            logger.warning(f"编译校验失败: {e}")
            return False

    @staticmethod
    def _neutralize_gap_seq(output_dir: Path, generated: list):
        """把 gap_seq 重写为空实现（LLM 代码未通过 EDA 编译校验后的回退）。

        `generated` 是 `[{cls, handle, member, dir}]`（见 `_generate_gap_tests`）——
        类名与所在目录都在里面，回退时不用再猜一遍；`item` 也带上，免得回退出来的
        类继承一个不存在的基类（原来写死 `{agent}_base_seq`，生成器根本不产它）。
        """
        for item in generated:
            gap_file = output_dir / "agents" / item["dir"] / f"{item['cls']}.sv"
            if not gap_file.exists():
                continue
            extends = item.get("extends") or "uvm_sequence"
            empty = (
                f"// gap_seq 回退为空实现（LLM/Gap 生成的代码未通过 EDA 编译校验）\n"
                f"class {item['cls']} extends {extends};\n"
                f"  `uvm_object_utils({item['cls']})\n"
                f"  function new(string name = \"{item['cls']}\");\n"
                f"    super.new(name);\n"
                f"  endfunction\n"
                f"  virtual task body();\n"
                f"    `uvm_info(\"GAPSEQ\", \"neutralized (generated code rejected by EDA)\", UVM_MEDIUM)\n"
                f"  endtask\n"
                f"endclass : {item['cls']}\n"
            )
            gap_file.write_text(empty, encoding="utf-8", errors="replace")

    @staticmethod
    def _add_include_to_pkg(pkg_file: Path, include_name: str):
        """在 agent package 的 endpackage 前加 include（幂等）。"""
        if not pkg_file.exists():
            return
        text = pkg_file.read_text(encoding="utf-8", errors="replace")
        if include_name in text:
            return
        text = text.replace("endpackage", f'  `include "{include_name}"\nendpackage', 1)
        pkg_file.write_text(text, encoding="utf-8", errors="replace")

    @staticmethod
    def _inject_gap_seq_to_test(tests_dir: Path, generated: list):
        """把 gap sequence 的运行代码注入**随机/生成测试**（不是定向测试）。

        **为什么不能注入定向测试**：`*_direct(ed)_test` 是精确计数的 —— 它按剧本
        发 N 笔事务，scoreboard 就核对那 N 笔。往里多塞几笔"额外激励"，对不上账，
        整个 case 直接挂。实测：注入定向测试之后，第 2 轮回归 **24 个 case 挂 21 个**
        （`pass=3 fail=21`），覆盖率一分没涨还把结果全污染了。

        所以额外激励的落点是**能容忍它的那个测试**（`*_gen_test` / `*_random_test`）。

        **代价要说清楚**：这条路的另一半是"回归得真的去跑那个测试"。实测生成的
        `regression.yaml` 给**每个** case 都写 `+UVM_TESTNAME=<定向测试>`，所以现在
        这份激励生成、注册、编译都过了，但**还没有 case 会执行它** —— 日志里会明说，
        不假装它生效了。要让它生效，得给回归加一个跑生成测试的 case（或在 case
        库里把它挂上）。
        """
        if not tests_dir.exists():
            return
        targets = []
        for pattern in ("*_gen_test.sv", "*_random_test.sv"):
            targets = sorted(tests_dir.glob(pattern))
            if targets:
                break
        if not targets:
            logger.warning("没有可注入 gap sequence 的生成/随机测试（只有定向测试），"
                           "跳过注入 —— 定向测试是精确计数的，塞额外激励会把它挂掉")
            return
        running = _regression_test_name(tests_dir.parent.parent)
        runs_the_stimulus = running and any(
            p in _test_files_defining(tests_dir, running) for p in targets)
        if running and not runs_the_stimulus:
            logger.warning(
                f"gap 激励已注入 {[p.name for p in targets]}，但回归跑的测试是 "
                f"`{running}` —— **没有 case 会执行这段激励**，覆盖率不会因此变化。"
                f"要让它生效，给回归加一个跑生成测试的 case（见 regression.yaml 的 tests）")
        for test_file in targets:
            text = test_file.read_text(encoding="utf-8", errors="replace")
            if "gap_seq" in text:
                continue
            blocks = []
            for item in generated:
                blocks.append(
                    f"    begin\n"
                    f"      {item['cls']} _gseq;\n"
                    f"      _gseq = {item['cls']}::type_id::create(\"_gseq\");\n"
                    f"      _gseq.start(env.{item['handle']}.{item['member']});\n"
                    f"    end"
                )
            inj = "    // Gap-directed stimulation（根据覆盖率 gap 自动生成）\n" + \
                  "\n".join(blocks) + "\n"
            if "    phase.raise_objection(this);\n" not in text:
                logger.warning(f"{test_file.name}: 找不到 raise_objection 锚点，未注入")
                continue
            text = text.replace("    phase.raise_objection(this);\n",
                                "    phase.raise_objection(this);\n\n" + inj, 1)
            test_file.write_text(text, encoding="utf-8", errors="replace")


def _test_files_defining(tests_dir: Path, class_name: str) -> list:
    """在 `env/tests/` 里找出**定义了 `class <class_name>`** 的文件。

    **不能按文件名找**：文件名和类名不是一回事（实测：文件是
    `apb_uart_env_direct_test.sv`，里面的类叫 `apb_uart_env_directed_test`）——
    按 `<类名>.sv` 去找会找不到，然后退回"猜一个测试文件"，注入到永远不跑的那个。
    """
    import re

    pattern = re.compile(rf"\bclass\s+{re.escape(class_name)}\b")
    found = []
    for sv in sorted(tests_dir.glob("*.sv")):
        try:
            if pattern.search(sv.read_text(encoding="utf-8", errors="replace")):
                found.append(sv)
        except OSError:
            continue
    return found


def _regression_test_name(output_root: Path) -> str:
    """回归配置里 `<build>/<test>` 实际跑的 UVM 测试名（`+UVM_TESTNAME=...`）。

    读 `<运行目录>/inputs/yaml/regression.yaml`。读不到返回空串 —— 调用方会退回
    "按名字猜测试文件"，但那只是权宜：**猜错了定向激励就等于没补**。
    """
    import re

    cfg = Path(output_root) / "inputs" / "yaml" / "regression.yaml"
    if not cfg.exists():
        return ""
    try:
        m = re.search(r"\+UVM_TESTNAME=(\w+)",
                      cfg.read_text(encoding="utf-8", errors="replace"))
        return m.group(1) if m else ""
    except OSError:
        return ""


def _synthesize_case_model(spec: Any, output_dir: Path) -> Optional[Path]:
    """没有现成 case 模型时，**从 spec 合成一份**并落盘（`casemodel_tools.spec_bridge`）。

    这是原来缺的那座桥：闭环里没有任何一步产 case 模型，于是测试点分解常年
    「跳过」—— 覆盖率的收敛只能靠随机激励。

    落盘到 `inputs/casemodel.yaml`（`_find_case_model` 的来源 2）是**有意的**：
    这份文件人看得见、改得动，改完下次运行用的就是**人给的那一份**（来源 2 的
    优先级高于合成）。数据本身不编：功能点/接口/中断都是 spec 里已经有的字段，
    机械映射成 case 模型的结构（几个功能点就几个叶子，几个数据信号就几个维度）。

    spec 里既没功能点也没信号 → 返回 None（不编一份空模型假装做过）。
    """
    try:
        from src.tools.casemodel_tools.spec_bridge import case_model_yaml

        yaml_text = case_model_yaml(spec if isinstance(spec, dict) else {})
        if not yaml_text:
            return None
        from src.layers.l1_infrastructure.layout import casemodel_path
        path = casemodel_path(output_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        # 已经有一份就不覆盖 —— 优先级：**人放的 / front 从 spec 出的** > 这里合成的。
        # front 比本步更早跑，所以这一步在正常情况下就是"不覆盖"。
        if not path.exists():
            path.write_text(yaml_text, encoding="utf-8")
        logger.info(f"case 模型由 spec 合成并落盘（{path.name}）—— "
                    f"想换一份就改这个文件，下次运行优先用它")
        return path
    except Exception as e:
        logger.warning(f"从 spec 合成 case 模型失败: {e}")
        return None


def _find_case_model(spec: Any, output_dir: Path) -> Optional[Path]:
    """找这次运行要用的 **case 模型**（casemodel 的输入）。找不到返回 None。

    **找不到就不编一份出来。** 分解测试点这件事没做，就要在日志里说没做 ——
    编一份空模型让它"看起来做了"比不做更糟。

    三个来源，按「离这次运行由近到远」排：

      1. `spec["case_model"]` —— 设计阶段若产出了就把路径写在这儿，优先它；
      2. `<运行目录>/inputs/casemodel.yaml` —— **人手工放一份**（模型还没写完时
         这是最现实的用法）；
      3. `config/casemodel/<模块名>.yaml` —— 项目级常备的那一份。

    闭环里目前**没有** spec → case 模型的桥（设计阶段不产出它），所以第 1 条现在
    通常不会命中；这条线是"有条件生效"的，等设计阶段补上就自然通。
    """
    candidates = []
    if isinstance(spec, dict):
        declared = spec.get("case_model")
        if isinstance(declared, str) and declared.strip():
            candidates.append(Path(declared))
        module = str(spec.get("design_name") or "").strip()
        if module:
            candidates.append(Path("config") / "casemodel" / f"{module}.yaml")
    from src.layers.l1_infrastructure.layout import casemodel_path
    candidates.append(casemodel_path(output_dir))

    for path in candidates:
        try:
            if path.is_file():
                return path
        except OSError:
            continue
    return None
