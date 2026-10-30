"""验证开发智能体 —— UVM环境 + 测试用例 + 断言（真实工具链）"""
from typing import Dict, Any, List, Optional
import json
from pathlib import Path

from src.layers.l2_orchestration.executors.base import BaseExecutor, ExecutorResult
from src.layers.l2_orchestration.executors.registry import register_executor
from src.executors.verify.steps_dag import StepRecorder
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
        #: 7 步的数据依赖记录器（`steps_dag.py`）—— 前置没跑就当场报错，
        #: 不靠注释里的“顺序不能乱”提醒下一个人。
        steps = StepRecorder()

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
            from src.tools.generation.uvm_tools.agent_tools import _uvm_ctx
            _uvm_ctx.set(output_dir=output_dir, agents=[], env_name=f"{module_name}_env")
            # 保存 spec 供 find_spec_yaml 读取
            (output_dir / "spec.json").write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
            # ⚠️ **计划必须早于 `find_spec_yaml`**：回归的 `count`/`SEED` 就在这一步
            # 由它铺开（`_seed_plan` 读 `coverage/coverage_plan.yaml`）。晚一步的话
            # 回归已经生成完了，批次一条都不在里面 —— 而日志看不出任何异常
            # （`env_cov_bins` 是反过来：那个落在 find_spec_yaml 会清空的目录里，
            # 只能晚于它。两件事的方向相反，别一起搬）。
            self._write_coverage_plan(output_dir)
            steps.mark("coverage_plan")
            call_tool("find_spec_yaml", {"spec_text": json.dumps(spec, ensure_ascii=False)})
            steps.mark("find_spec_yaml")
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
            # 第二条通道：`sample: dut` 的字段 → bind 进 DUT 的**覆盖率接口**
            #（也要在 filelist 生成前落盘）。先做它：它解析出来的身份（接口名/
            # bind 实例名/时钟/复位）与 bins 要一起进下面那份契约，而 env 组件与
            # tb_top **都从那一份读** —— 两份各写一次名字就是"改了三个漏一个"。
            dut_channel = self._write_coverage_dut_channel(output_dir)
            steps.mark("dut_channel")
            self._write_env_cov_bins(output_dir, cov_bins_for_render, dut_channel)
            steps.mark("env_cov_bins")
            # 约束模型（`env/cons/*` 的输入）—— 同样落在 find_spec_yaml 之后、
            # jinja_render 之前。落在这里有两个**都必须**成立的理由：
            #   · 早于 find_spec_yaml → 被它清空（同上）；
            #   · 晚于 jinja_render → 这一轮渲染不到，`env/cons/` 不生成。
            # 它还要与 env.yaml **在同一次 `run()` 里**被读到，`default_env`
            # 才回填得上（约束 yaml 自己不写 `env`，见 `gen_uvm.run` 的回填）。
            self._write_constraint_yaml(output_dir)
            steps.mark("constraint_yaml")
            # 三模型关联的断点清单 —— 也落在这一步（它要读刚写下的
            # constraint.yaml，所以必须晚于 `_write_constraint_yaml`）。
            # 落在 `coverage/`：那份报告与覆盖率报告同性质，都是签核材料。
            self._write_association_report(output_dir)
            steps.mark("association_report")
            call_tool("jinja_render", {"output_dir": str(output_dir)})
            steps.mark("jinja_render")
            steps.finish()
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
        # `src/tools/generation/casemodel_tools/`（零 LLM 依赖），Agent 侧的三个包装面在
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
            # **把"用了哪一份"说出来**：人写的模型优先于 front 的草稿，而这件事
            # 从运行结果上看不出来（都是"有一份模型"）。一份手写模型悄悄接管了
            # 整轮回归的测试点，却没有任何一行日志提到它 —— 排查时会很痛苦。
            logger.info(f"case 模型：{case_model}（人写的优先于 front 的草稿）")
            try:
                from src.tools.generation.casemodel_tools.api import run_gaps, run_generate

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

                        # ── 测试点 IR：case 表只是"分解出了什么"，这一份是
                        #    "**每条测试点怎么实现、打哪个仓、跑哪一级**"。
                        #    没有它，下游各自的产物（test / 覆盖 / 回归 / 报告）
                        #    仍然只能靠命名碰巧对齐。
                        tp_files = self._write_testpoints(output_dir, case_model,
                                                          module_name)
                        files.extend(tp_files)
            except Exception as e:
                logger.warning(f"测试点分解失败（casemodel）: {e}")

        # ── 3. SVA 断言：**本轮不再生成**（2026-10-17 撤掉）──
        #
        # 原来这里把 case 模型的 `assertions:` 块 render 成 SVA、包成 module
        # `bind` 进 DUT。撤掉它的理由是**它报的是采样时序产生的 X，不是设计缺陷**：
        #
        #   · DUT 的输入在复位释放后的**第一个时钟沿**仍是 X（驱动器的第一笔写
        #     要等那个沿才生效，而 DUT 在同沿读的是沿前值）——`queue_level`
        #     一旦被锁成 X，`X + 1 = X` **再也回不来**；
        #   · SVA 的语义是"表达式为 X 即失败"，于是它**每一拍**都报（实测
        #     115ns→385ns 共 30 条），把整轮回归判成 fail，而根因是一条驱动时序；
        #   · 同一组规则的**另一个执行点**（env 检查组件）留着，见
        #     `_write_coverage_dut_channel` 那段的 `dut_checker` —— 它把结论收口成
        #     一行 `matched=… mismatched=…`，且**已经把"求值为 X"单列成
        #     `unverified`**（不再把 X 记成命中）。
        #
        # **撤的是"这一半执行点"，不是"这套规则"** —— 规则仍然逐拍求值，只是收口
        # 在 env 那一侧。要恢复 SVA：把这段接回去即可（`generate_sva_assertions` +
        # `assertions/<module>_assertions.sv`），但**先把那条驱动时序修掉**，
        # 否则它会立刻重新变成一片噪音。
        logger.info("断言：本轮不生成 SVA（已撤）—— 规则由 env 检查组件逐拍求值收口")

        tests_data = {
            "module": module_name,
            "env_files": len(files),
            "files": files,
            "status": "generated" if files else "empty",
        }
        score = min(50 + len(files) * 2, 90) if files else 20
        return ExecutorResult(success=bool(files), data={"tests": tests_data, "score": score})

    # ── 功能覆盖率点：case 模型 → env_cov 的 bin ──

    def _write_env_cov_bins(self, output_dir: Path, cov_bins: List[Any],
                            dut: Dict[str, Any] = None) -> None:
        """把 `env_cov_bins.yaml` 落到 `find_spec_yaml` 之后、`jinja_render` 之前。

        四个键：

          · `cov_bins`   —— 策略包的语义 cross（`env_cov.sv.j2` 渲染成 `cross_<name>`）
          · `field_bins` —— **case 模型**的边界 bin（渲染成 `cp_<字段>` 的 bins）
          · `dut_if`     —— **DUT 覆盖率接口的身份**（类型名 / bind 实例名 / 时钟 /
                            复位 / 文件），由 `_write_coverage_dut_channel` 给出
          · `dut_bins`   —— DUT 侧覆盖点的 bins 表（`cg_dut` 的显式仓）

        **`dut_if` 是给两个模板读的同一份身份**：env 组件按它声明
        `virtual <type>`，tb_top 按它写 `config_db::set(..., <dut 实例>.<instance>)`。
        两边都从这一个文件读，所以**不会漂**；没有这个键时两边都不生成任何东西
        —— 而不是一边生成、一边不生成（那样组件拿到的是空句柄，覆盖率永远 0%，
        而编译不报错）。

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
            if dut:
                payload.update(dut)
            (bins_dir / "env_cov_bins.yaml").write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        except Exception as e:                       # noqa: BLE001 旁路，别拦 env 生成
            logger.warning(f"env_cov bin 落盘失败（覆盖率模型将退回自动分箱）: {e}")

    @staticmethod
    def _agent_transaction_fields(output_dir: Path) -> Dict[str, List[str]]:
        """`{agent 名: [事务字段名]}` —— 只收 **master 且 rand** 的字段。

        `realization.kind=stimulus` 的测试点要落到具体 agent 上；字段名对不上
        就是"set 了一个没人读的键"（本仓库刚踩过：61 个属性 test 全是死标签）。
        数据来自 `find_spec_yaml` 写下的 agent yaml（`interfaces.transaction_vars`）。
        """
        import yaml as _yaml

        yaml_dir = output_dir / "inputs" / "yaml" / "uvm"
        env_path = yaml_dir / "env.yaml"
        try:
            env = (_yaml.safe_load(env_path.read_text(encoding="utf-8",
                                                       errors="replace")) or {}
                   ).get("environment") or {}
        except (OSError, ValueError):
            return {}
        out: Dict[str, List[str]] = {}
        for agent in (env.get("agents") or []):
            if not isinstance(agent, dict):
                continue
            name = str(agent.get("name") or "").strip()
            # **passive agent 没有 sequencer**：把它的字段当成激励通道，
            # 生成的约束会挂在一个根本不存在的驱动路径上（`_seq.start(null)`
            # 那一类问题的变体）。`is_active` 缺省当作 active。
            if not name or agent.get("is_master") is False:
                continue
            if agent.get("is_active") is False:
                continue
            try:
                doc = _yaml.safe_load(
                    (yaml_dir / f"{name}.yaml").read_text(
                        encoding="utf-8", errors="replace")) or {}
            except (OSError, ValueError):
                continue
            iface = doc.get("interfaces")
            tvars = (iface.get("transaction_vars") if isinstance(iface, dict)
                     else doc.get("transaction_vars")) or []
            fields = []
            for v in tvars:
                if not isinstance(v, dict) or not v.get("name"):
                    continue
                if str(v.get("isrand", "False")) != "True":
                    continue
                if str(v.get("is_master", "True")) == "False":
                    continue
                fields.append(str(v["name"]))
            if fields:
                out[name] = fields
        return out

    def _write_testpoints(self, output_dir: Path, case_model: Path,
                          module_name: str) -> List[str]:
        """落 `coverage/testpoints.yaml` + `.json` —— 测试点 IR 的唯一落点。

        **为什么落在 `coverage/`**：它与覆盖报告同性质（都是签核材料），而且
        `inputs/yaml/uvm/` 会被 `find_spec_yaml` 清空（见 `layout.casemodel_path`
        的注释）。放在 coverage 下，证据包 `dump` 会连同覆盖率一起收走。
        """
        try:
            from src.tools.generation.casemodel_tools.api import run_testpoints

            # **与 `_casemodel_test_lines` 的 200 条上限同一口径**：那边截断后
            # 不会生成更多属性 test 类，TP 这边若还列着"有 test 名但没类"的
            # 条目，报告就会出现永远 NOT_RUN 的幽灵测试点。
            payload = run_testpoints(
                case_model.read_text(encoding="utf-8", errors="replace"),
                env_name=f"{module_name}_env",
                agents=self._agent_transaction_fields(output_dir) or None,
                module_name=module_name,
                max_tests=200)
            if payload.get("error"):
                logger.warning(f"测试点 IR 生成失败: {payload['error']}")
                return []
            cov_dir = output_dir / "coverage"
            cov_dir.mkdir(parents=True, exist_ok=True)
            # **必须 `newline="\n"`**：Windows 的文本模式会把 `\n` 翻成 `\r\n`，
            # 而 manifest 里的 sha256 算的是 LF 那份 —— 不锁换行符，哈希与实际
            # 落盘文件永远对不上（实测），证据链就成了摆设。
            (cov_dir / "testpoints.yaml").write_text(
                payload["testpoints_yaml"], encoding="utf-8", newline="\n")
            (cov_dir / "testpoints.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            # ── StimulusPlan IR：generated / player 两个后端的公共前置层 ──
            # 当前只落 plan（generated 仍是唯一可执行后端）；player runtime 未实现
            # 时 `ensure_backend_executable` 会显式报错，不静默换后端。
            try:
                from src.tools.generation.casemodel_tools.framework.stimulus_plan import (
                    DEFAULT_BACKEND, build_and_write)

                _plan = build_and_write(
                    payload.get("testpoints") or [], output_dir,
                    backend=DEFAULT_BACKEND, module=module_name)
                logger.info(f"StimulusPlan：{_plan['planned']} 条可激励 / "
                            f"{_plan['unsupported']} 条不适用（backend={_plan['backend']}）")
            except Exception as _e:                    # noqa: BLE001 旁路
                logger.warning(f"StimulusPlan 生成失败: {_e}")
            # **自证**：manifest 说这份 IR 的哈希是 X，落盘字节就得是 X。
            # 哈希对不上时证据链是假的 —— 宁可日志里响一声，也不让它静默过去。
            _want = ((payload.get("methodology") or {}).get("artifacts") or {}) \
                .get("testpoints_yaml", {}).get("sha256", "")
            if _want:
                import hashlib
                _got = hashlib.sha256(
                    (cov_dir / "testpoints.yaml").read_bytes()).hexdigest()
                if _got != _want:
                    logger.warning(
                        f"测试点 IR 哈希与 manifest 不一致：文件 {_got[:12]}… / "
                        f"manifest {_want[:12]}…（落盘编码/换行被改过？）")
            # 框架清单：阶段、计数、输入、IR 哈希 —— 与证据链同一纪律。
            if payload.get("methodology"):
                (cov_dir / "methodology.json").write_text(
                    json.dumps(payload["methodology"], ensure_ascii=False, indent=2),
                    encoding="utf-8")
        except Exception as e:                       # noqa: BLE001 旁路，别拦主流程
            logger.warning(f"测试点 IR 落盘失败: {e}")
            return []
        kinds = "、".join(f"{k}={v}" for k, v in sorted(payload["by_kind"].items()))
        logger.info(f"测试点 IR：{payload['count']} 条（{kinds}；"
                    f"观测型 {payload['observe_only']} 条）→ coverage/testpoints.yaml")
        for note in payload.get("notes") or []:
            logger.info(f"  测试点注意: {note}")
        files = [str(output_dir / "coverage" / "testpoints.yaml"),
                 str(output_dir / "coverage" / "testpoints.json"),
                 str(output_dir / "coverage" / "methodology.json")]
        if (output_dir / "coverage" / "stimulus_plan.json").is_file():
            files.append(str(output_dir / "coverage" / "stimulus_plan.json"))
        return files

    def _write_constraint_yaml(self, output_dir: Path) -> None:
        """`inputs/yaml/uvm/constraint.yaml` —— case 模型 → 约束模型（`env/cons/*` 的输入）。

        ## 这一步补的是"方法学的第三条腿"

            case 模型     说「该测什么」   themes[].method
            覆盖率模型    说「怎么量」     coverpoints / bins
            约束模型      说「怎么驱动」   policies + combinator   ← 这里产出

        在这之前 `build_constraint` **只有 CLI 调**（`vagent case-model constraints`），
        流水线里从来没生成过 —— 于是 `env/cons/*` 在任何真实 run 里都不存在，
        "批次 test 挂策略名" 那条链（`batch_policy` → `create_from_batch`）一直是空转。
        产物丢进同一个 `inputs/yaml/uvm/` 目录即可，`gen_uvm` 按**顶层 `constraint:` 键**
        识别（文件名不参与）。

        ## 端口从 env.yaml 推（不写进 case 模型）

        约束要 `transactions`（agent 名 + seq_item 类型）才能生成协调序列 —— 而
        case 模型是**建模概念**（中文维度名），不该混进实现名。所以从 `find_spec_yaml`
        刚写下的 env.yaml 反读 agents。

        **类型名从 `type` 推，不是从 `name`**：env.yaml 里
        `name: npu_sched_in` / `type: npu_sched_in_master_agent`，而生成的
        seq_item 类是 `npu_sched_in_master_seq_item` —— 照 `name` 拼会得到
        `npu_sched_in_seq_item`，那个类**不存在**（编译期才报）。推导规则与
        `gen_uvm.AgentModel.seq_item_type` 逐字一致（去掉 `_agent` 再加 `_seq_item`）。

        没有 case 模型 / 没有 agent / `build_constraint` 报错 —— 一律**记日志不写**：
        一个空的 `transactions` 渲染出来的协调序列是个空壳（发送循环一次都不进），
        不生成比生成空壳诚实。
        """
        cm_file = _find_case_model(_spec_of(output_dir), output_dir)
        if cm_file is None:
            logger.info("没有 case 模型 —— 跳过约束模型生成（env/cons 不会出现）")
            return
        ports = _constraint_ports(output_dir)
        if not ports:
            logger.info("env.yaml 里没有 agent —— 跳过约束模型生成"
                        "（没有端口就不生成，见 build_constraint）")
            return
        try:
            from src.tools.generation.casemodel_tools.associate import build_constraint

            # `agent_fields` 决定"这个字段该约束哪个 agent" —— 没有它，可驱动
            # 维度只能在一端口时才敢落，多 agent 时全部退化成骨架。
            payload = build_constraint(
                cm_file.read_text(encoding="utf-8"), ports=ports,
                agent_fields=self._agent_transaction_fields(output_dir) or None)
            if payload.get("error"):
                logger.warning(f"约束模型生成不了，跳过: {payload['error']}")
                return
            (output_dir / "inputs" / "yaml" / "uvm" / "constraint.yaml").write_text(
                payload["constraint_yaml"], encoding="utf-8")
            self._write_constraint_status(output_dir, payload)
            # **同一份生效状态也要能被覆盖率计划读到**：签核的人先看
            # `coverage_plan.yaml`，再看 `constraint.yaml` 是两步；把
            # `constraint_backing` 写进计划产物，一步就能回答"哪些策略在约束"。
            self._annotate_coverage_plan(output_dir, payload)
        except Exception as e:                       # noqa: BLE001 旁路，别拦 env 生成
            logger.warning(f"约束模型落盘失败（env/cons 将不生成）: {e}")
            return
        # **日志放在 try 之外**：打日志本身可能失败（Windows 控制台是 GBK，
        # 而 `notes` 里那个 `↔` 不在 GBK 里 —— 实测撞过），而那时文件**已经写成了**。
        # 把它圈在同一个 try 里，except 就会把"日志没打出来"报成"落盘失败"，
        # 让排查的人去找一个并不存在的写入问题。**日志失败不该冒充落盘失败。**
        logger.info(f"约束模型：{payload['policy_count']} 条策略 / "
                    f"default_mode={payload['default_mode']} / "
                    f"{len(ports)} 个端口 → constraint.yaml（渲染出 env/cons/）")
        for note in payload.get("notes") or []:
            logger.warning(f"约束模型: {note}")

    @staticmethod
    def _write_constraint_status(output_dir: Path, payload: Dict[str, Any]) -> None:
        """`coverage/constraint_status.json` —— **约束到底有没有在约束**。

        与 `constraint.yaml` 一起落盘，供覆盖率阶段拼进 `semantic_validations`、
        再由 audit 门禁读（`PASS_WITH_CAVEAT` 就挂在这个字段上）。

        **为什么在生成期判、不去抓仿真日志**：`env_cons_policies.sv.j2` 里策略体
        落到 `default:` 是**运行期**的分支，而那条 `uvm_info` 是 `UVM_HIGH` ——
        默认 verbosity（`UVM_MEDIUM`）下**根本不打**，`sim.sh` 里也没有
        `+UVM_VERBOSITY`。所以"从日志 grep `default:`"那条路是死的（实测）。
        而这件事**生成期就确定**（`build_constraint` 声明 `policies_are_skeletons`），
        不必等仿真、也不必改 verbosity。
        """
        from src.tools.generation.uvm_tools.generation.generators.constraint_gen import (
            write_constraint_status)
        write_constraint_status(output_dir, payload, logger)

    @staticmethod
    def _annotate_coverage_plan(output_dir: Path, payload: Dict[str, Any]) -> None:
        """把 `constraint_backing` 追写进 `coverage/coverage_plan.yaml`。

        为什么是"追写"而不是生成时一起写：计划在 `find_spec_yaml` **之前**
        落盘（回归的种子由它铺开），而约束模型要在 `find_spec_yaml` 之后才
        知道 agent 端口。两件事有先后，但读的人不该被迫读两份文件。
        `constraint_backing` 是**只增字段**，不影响既有读者。

        解析失败只记日志：覆盖计划的权威内容已经落盘，标注是增强项，
        不该因为它把生成流程变成失败。
        """
        from src.tools.generation.uvm_tools.generation.generators.constraint_gen import (
            annotate_coverage_plan)
        annotate_coverage_plan(output_dir, payload, logger)

    def _write_association_report(self, output_dir: Path) -> None:
        """`coverage/association_report.json` —— 三模型关联的**断点清单**。

        `vagent case-model associate` 一直只把断点打到终端上。但关联断点和覆盖率
        报告一样是**签核材料**："声明要测的"与"实际在量的"对不上，签核的人得看得见，
        而且得是机器可读的（audit 门禁要认它，CI 要能拦）。

        ## 覆盖率模型文本从哪来

        流水线里的覆盖率模型是**从 case 模型推出来的对象**
        （`coverage_model()`），没有一份人写的 `coverage.yaml`。而 `associate`
        吃文本 —— 所以用 `coverage_model_to_dict()` 序列化一份（JSON 是合法 YAML）。
        那两个函数在 `coverage.py` 里紧挨着，互为逆。

        **不硬崩**：任何一步出问题只记日志。关联校验是**旁路**，不该因为它
        跑不起来就把 verify 变成失败 —— 该失败的是"关联真断了"，不是"校验没跑成"。
        """
        cm_file = _find_case_model(_spec_of(output_dir), output_dir)
        if cm_file is None:
            return
        cons_path = output_dir / "inputs" / "yaml" / "uvm" / "constraint.yaml"
        try:
            from src.tools.generation.casemodel_tools.associate import associate
            from src.tools.generation.casemodel_tools.coverage import (
                coverage_model, coverage_model_to_dict,
            )
            from src.tools.generation.casemodel_tools.repository import load_models_from_text

            case_text = cm_file.read_text(encoding="utf-8")
            model = load_models_from_text(case_text, source=str(cm_file))[0].resolve()
            module_name = str(_spec_of(output_dir).get("design_name") or "dut")
            cm = coverage_model(model, module_name)
            coverage_text = json.dumps(coverage_model_to_dict(cm), ensure_ascii=False)
            constraint_text = (cons_path.read_text(encoding="utf-8")
                               if cons_path.is_file() else "")

            a = associate(case_text, coverage_text, constraint_text)
            if a.get("error"):
                logger.warning(f"关联校验跑不了，跳过: {a['error']}")
                return
            # **硬边** = ①②（case↔coverage）。断了意味着"声明要测的没落成覆盖仓"，
            # 那是签核必须知道的事 —— audit 据此挂 PASS_WITH_CAVEAT。
            hard = [i for i in (a.get("issues") or [])
                    if i.get("edge") in ("①", "②") and i.get("severity") == "error"]
            report = {
                "hard_edge_broken": len(hard),
                "error_count": a.get("counts", {}).get("error", 0),
                "warning_count": a.get("counts", {}).get("warning", 0),
                "renderable": a.get("renderable", False),
                "summary": a.get("summary", ""),
                "issues": a.get("issues") or [],
                "notes": a.get("notes") or [],
            }
            cov_dir = output_dir / "coverage"
            cov_dir.mkdir(parents=True, exist_ok=True)
            (cov_dir / "association_report.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            logger.info(f"三模型关联：{report['error_count']} 断 / "
                        f"{report['warning_count']} 提示"
                        f"（硬边断 {len(hard)} 条）→ coverage/association_report.json")
        except Exception as e:                       # noqa: BLE001 旁路，别拦 env 生成
            logger.warning(f"关联校验失败（不影响生成）: {e}")

    def _write_coverage_plan(self, output_dir: Path) -> None:
        """`coverage/coverage_plan.yaml` —— 功能覆盖率计划（**与 case 模型同批**）。

        四张表摆在一份文件里：§3 覆盖点 / §5 批次 / §6 种子管理 / §8 需求追溯。

        **为什么要落盘而不是回归那边现算**：回归只关心其中两列（批次 → test →
        种子），而签核关心另外两列（覆盖点 → 需求）。两边各算一遍就会漂 ——
        实测的教训是"声明了 N 个覆盖点、回归里跑 M 条"没人发现得了。一份文件，
        三处读它：回归取种子、覆盖率页取覆盖点、审计取追溯。
        """
        cm_file = _find_case_model(_spec_of(output_dir), output_dir)
        from src.tools.generation.uvm_tools.generation.generators.coverage_gen import (
            write_coverage_plan)
        write_coverage_plan(output_dir, cm_file, logger, module_name="dut")

    def _write_coverage_dut_channel(self, output_dir: Path) -> Dict[str, Any]:
        """`sample: dut` 的字段 → `coverage/<接口>.sv`（bind 进 DUT 的覆盖率接口）。

        **第二条采样通道**。monitor 的事务通道只看得到**激励侧** —— 队列水位、
        依赖类型、发射决策这些内部状态与输出端口，它一个都采不到。而 `bind` 进
        DUT 的接口对输入端口/输出端口/内部寄存器**没有区别**：端口连接表达式在
        目标模块作用域里求值，内部名直接连得过去（实测 vlog/vopt 通过）。

        ## 为什么是"接口 + env 组件"，而不是"自带 covergroup 的探针模块"

        两条都靠 `bind`，都能采到同样的信号。**同时发两份就是同一个信号被两个
        covergroup 各采一遍** —— `vcover` 报表里多一个 covergroup，签核的
        "功能覆盖率"数字被自己搅浑。而探针那份（`render_probe`）在覆盖率管道里
        没有任何东西消费它：真正的报表读的是 ucdb，ucdb 里两个 covergroup 都算。
        所以管道里**只留一条**：接口引信号、env 的 `<env>_coverage` 组件采样 ——
        覆盖率跟 UVM 的报告走（`功能覆盖率[dut]: x%`）。

        探针那条没有废弃：它是**没有 env 也要收覆盖率**时的独立通道
        （`vagent case-model covergroups` 出的 `probe_code`）。

        ## 为什么落在这里

        **它要被编译**：回归的 filelist 在 ops 阶段生成，接口必须先于它存在 ——
        写在覆盖率阶段就永远赶不上这一轮，那就又是一份"看着有、从没编译过"的
        产物（本会话踩过这个坑）。

        返回给调用方的 `{dut_if, dut_bins}` 会并进 `env_cov_bins.yaml`：env 组件
        与 tb_top 都从那一份读身份。**没生成就返回空字典** —— 调用方据此不写
        `dut_if`，于是两个模板一个字都不出（一致地"都没有"，而不是单边有）。
        """
        cm_file = _find_case_model(_spec_of(output_dir), output_dir)
        if cm_file is None:
            return {}
        try:
            from src.tools.generation.casemodel_tools.api import run_covergroups

            payload = run_covergroups(cm_file.read_text(encoding="utf-8"), "dut")
        except Exception as e:                       # noqa: BLE001 旁路
            logger.warning(f"读 case 模型失败（不生成 DUT 覆盖率接口）: {e}")
            return {}
        if not payload.get("probe_ports"):
            return {}                                # 模型里没有 sample: dut 的字段
        code = payload.get("cov_interface_code") or ""
        meta = payload.get("cov_interface") or {}
        if not code or not meta.get("type"):
            # 有 `sample: dut` 的字段却没给 `sampling.dut_module` —— 原因与写法已经
            # 在 `run_covergroups` 的 notes 里写好了，照抄一句，别让人对着"没生成"猜
            for note in payload.get("notes") or []:
                if "dut_module" in note:
                    logger.warning(f"DUT 覆盖率接口生成不了：{note}")
                    break
            else:
                logger.warning("DUT 覆盖率接口生成不了（模型里有 sample: dut 的字段，"
                               "但接口身份算不出来）")
            return {}
        path = output_dir / meta["file"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(code, encoding="utf-8")
        # ── DUT 检查规则：**真 pass 的"比对"那一半** ──
        #
        # 用户口径：真 pass = SCB 报 `mismatched=0` + 断言不报错。断言那半由 SVA
        # 承担（bind 进 DUT），而 `mismatched=0` 需要一个**收口**——env 的检查组件
        # 逐拍求值同一组规则、数出 matched/mismatched 并打印。
        #
        # **同一份规则、两个执行点**：模型里那几条 `assertions` 既渲染成 SVA
        # （设计侧，bind 进 DUT），也翻译成逐拍布尔喂给 env 组件（验证侧，UVM 收口）。
        # 一套规则两处生效，数出来的东西才对得上；各写一份必然漂。
        dut_checker: Dict[str, Any] = {}
        try:
            import yaml as _yaml
            from src.tools.generation.casemodel_tools.coverage import checker_rules
            decls = (_yaml.safe_load(cm_file.read_text(encoding="utf-8",
                                                        errors="replace")) or {})
            got = checker_rules(decls.get("assertions"), meta.get("signals") or [])
            if got["rules"]:
                dut_checker = {"rules": got["rules"], "skipped": got["skipped"],
                               "clock": meta.get("clock", "clk"),
                               "reset": meta.get("reset", "rst_n")}
                logger.info(f"DUT 检查：{len(got['rules'])} 条规则由 env 组件逐拍求值"
                            f"（收口打印 matched/mismatched → 真 pass 的比对半边）")
            for _s in got["skipped"]:
                logger.warning(f"DUT 检查跳过：{_s}")
        except Exception as e:                             # noqa: BLE001 旁路
            logger.warning(f"DUT 检查规则生成失败（本轮没有比对收口）: {e}")
        # 它和这个接口采的是**同一批信号**：两份同时挂在 filelist 里，就是同一个
        # 信号被两个 covergroup 各采一遍 —— `vcover` 报表里多一个 covergroup，
        # 签核的"功能覆盖率"被自己搅浑。删的是本管道自己的产物（名字固定、
        # 随时可重生成），而且**说出来**，不静默动别人的文件。
        stale = path.parent / "dut_probe.sv"
        if stale.exists():
            stale.unlink()
            logger.info(f"清掉上一版的 DUT 探针 {stale.name}：DUT 通道已改走 "
                        f"{path.name} + env 覆盖率组件（两个 covergroup 采同一批"
                        f"信号会重复计量）")
        logger.info(f"功能覆盖率点（DUT 通道）：{len(payload['probe_ports'])} 个信号 "
                    f"→ {path.name}（bind 到 {meta['dut_module']}；由 "
                    f"{meta['type']} 引给 env 覆盖率组件，会被真编译、真采样）")
        return {"dut_if": meta, "dut_bins": payload.get("dut_bins") or {},
                **({"dut_checker": dut_checker} if dut_checker else {})}

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
        cm_file = _find_case_model(_spec_of(output_dir), output_dir)
        if cm_file is None:
            return {}
        try:
            from src.tools.generation.casemodel_tools.api import run_covergroups

            points = run_covergroups(cm_file.read_text(encoding="utf-8"), "dut")
        except Exception as e:                       # noqa: BLE001 旁路，别拦生成
            logger.warning(f"读 case 模型失败（env_cov 退回自动分箱）: {e}")
            return {}
        if points.get("error"):
            logger.warning(f"case 模型构建失败（env_cov 退回自动分箱）: "
                           f"{points['error']}")
            return {}

        out: Dict[str, List[Dict[str, Any]]] = {}
        for cp in points.get("coverpoints") or []:
            # **只收 `sample: stimulus` 的**：`sample: dut` 的那些信号在 env_cov
            # 里根本不可见（那是 DUT 内部状态与输出端口，monitor 采不到），塞进
            # `field_bins` 只会让模板生成一堆引用不到信号的 bin。它们走探针那条路。
            #
            # **只收离散值**：`env_cov.sv.j2` 的 bin 语法只支持 `{v}` 与 `{[a:b]}`，
            # 没有 `illegal_bins` 的位置 —— 区间仓与非法仓都留给探针（DUT 侧那份
            # covergroup 才是完整的）。
            if cp.get("source") != "stimulus":
                continue
            bins = [{"name": b["name"], "value": b["value"]}
                    for b in cp.get("bins") or [] if "value" in b]
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
        from src.tools.checking.coverage_tools.main import generate_gap_directed_seq
        from src.tools.common.lib.env_introspect import (binding_for_agent,
                                                 env_active_agents,
                                                 env_agent_bindings)
        from src.tools.common.lib.filelist import agent_layout

        agents_dir = output_dir / "agents"
        if not agents_dir.exists() or not gaps:
            return

        # 哪些 agent 真的能收激励 —— 问**模型**（`env.yaml` 的 `is_active`）。
        # passive agent 的 sequencer 压根没建出来，注给它就是 `start_item` 当场
        # fatal（详见 `env_active_agents` 的注释）。下面那个"接口里有没有 output"
        # 的文本判据只在模型读不到时兜底用。
        active = env_active_agents(output_dir)
        if not active:
            logger.warning("读不到 env 模型（inputs/yaml/uvm/env.yaml）的 is_active —— "
                           "无法判断哪些 agent 能收激励，本次跳过定向激励注入")

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
            if agent_dir_name in active and not active[agent_dir_name]:
                logger.info(f"{agent_dir_name}: passive agent（env 模型 is_active=false）"
                            f"—— 它没有 sequencer，注激励进去只会 start_item 报错，跳过")
                continue
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
            from src.tools.common.lib.compile import run_compile_check
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
            # ⚠️ **锚点必须在 `main_phase` 里**，不能是"文件里第一个
            # `phase.raise_objection(this);`" —— 生成的测试里 `configure_phase`
            # 和 `main_phase` **各有一句**，`str.replace(..., 1)` 取到的是前者。
            #
            # 后果（实测：端到端 `verify --rtl specs/npu_sched`，p0 挂 1 条）：
            # `configure_phase` 跑在 **run_phase 之前**，而 `start_item/finish_item`
            # 靠 **sequencer 的 run_phase** 递送事务 —— 在 configure_phase 里永远
            # 递不出去，于是激励自己那条 20us 超时先报
            #   `[GAPSEQ] 定向激励超时：20000 ns 内对手方未应答`
            # 紧跟着 `[SEQ] neither the item's sequencer ... to start item`
            # 把整条测试判失败。看起来像"DUT 不应答"，其实是**相位用错了**。
            anchor_at = _main_phase_objection_at(text)
            if anchor_at < 0:
                logger.warning(f"{test_file.name}: 找不到 main_phase 的 "
                               f"raise_objection 锚点，未注入")
                continue
            anchor = "    phase.raise_objection(this);\n"
            text = text[:anchor_at] + anchor + "\n" + inj + text[anchor_at + len(anchor):]
            test_file.write_text(text, encoding="utf-8", errors="replace")


def _main_phase_objection_at(text: str) -> int:
    """`main_phase` 里那句 `phase.raise_objection(this);` 的**下标**（没有则 -1）。

    为什么要专门找它：`configure_phase` 里有一模一样的一句，而那个相位**拿不到
    sequencer 的事务递送**（sequencer 的 run_phase 还没开始）—— 把激励注进那里
    等于注进一个永远等不到应答的地方。见调用处那段注释。
    """
    import re

    m = re.search(r"\btask\s+main_phase\s*\(", text)
    if not m:
        return -1
    return text.find("    phase.raise_objection(this);\n", m.end())


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

    落盘到 `inputs/casemodel.yaml`（`layout.find_case_model` 的**最后一个**来源）
    是**有意的**：这份文件人看得见、改得动。但它是**兜底**那一档 —— 人想长期
    用自己那份，写到 `specs/<模块>/casemodel.yaml` 或 `config/casemodel/<模块>.yaml`
    更合适（那两个来源的优先级高于这里）。

    数据本身不编：功能点/接口/中断都是 spec 里已经有的字段，机械映射成 case 模型
    的结构（几个功能点就几个叶子，几个数据信号就几个维度）。

    spec 里既没功能点也没信号 → 返回 None（不编一份空模型假装做过）。
    """
    try:
        from src.tools.generation.casemodel_tools.spec_bridge import case_model_yaml

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


def _spec_of(output_dir: Path) -> Dict[str, Any]:
    """这次运行的 spec —— 从 `<run>/spec.json` 读（verify 自己在 UVM 生成前落的那份）。

    写盘器（field_bins / DUT 探针）拿不到调用栈里的 `spec` 变量，而
    `_find_case_model` 需要它来认 `specs/<模块>/casemodel.yaml` 这类候选。
    `spec.json` 就是"这次运行的 spec"的落点，读它比把 spec 一路透传干净。
    """
    try:
        return json.loads((output_dir / "spec.json").read_text(encoding="utf-8")) or {}
    except (OSError, ValueError):
        return {}


def _find_case_model(spec: Any, output_dir: Path) -> Optional[Path]:
    """转发到 `layout.find_case_model` —— **"用哪份模型"的判据只有那一处**。

    原来这里自己实现了一份（认识 `config/`），而**覆盖率侧**读的是
    `casemodel_path()`（只认 `inputs/`）。同一个 run 里于是：

        verify   拿 `config/casemodel/<模块>.yaml` 分解测试点
        coverage 拿 front 的草稿 `inputs/casemodel.yaml` 生成覆盖点

    两份模型的覆盖点不一样，而两边都觉得自己对。收成一处之后只有一个答案；
    `specs/<模块>/casemodel.yaml`（手写模型最自然的位置）也一并被认了。
    """
    from src.layers.l1_infrastructure.layout import find_case_model

    return find_case_model(spec, output_dir)


#: agent 类名的后缀 —— 去掉它再加 `_seq_item` 就是事务类型名。
_AGENT_SUFFIX = "_agent"


def _seq_item_type(agent: Dict[str, Any]) -> str:
    """env.yaml 的一个 agent → 它的 seq_item 类型名。

    **从 `type` 推，不是从 `name`**：env.yaml 里 `name: npu_sched_in` 而
    `type: npu_sched_in_master_agent`，生成的事务类是
    `npu_sched_in_master_seq_item` —— 照 `name` 拼出来的
    `npu_sched_in_seq_item` **不存在**（而那个错只会在 vlog 编译时才冒出来）。

    规则与 `gen_uvm.AgentModel.seq_item_type` 逐字一致（那边也是去 `_agent`
    再加 `_seq_item`）；`master` / `slave` 的区别已经编码在 `type` 里，不用再判
    `is_master`。
    """
    typ = str(agent.get("type") or "").strip()
    base = typ[:-len(_AGENT_SUFFIX)] if typ.endswith(_AGENT_SUFFIX) else typ
    return f"{base}_seq_item" if base else ""


def _constraint_ports(output_dir: Path) -> List[Dict[str, str]]:
    """`find_spec_yaml` 写下的 env.yaml → `build_constraint` 要的 ports。

    端口**从 env.yaml 推**，不写进 case 模型：case 模型说的是建模概念
    （中文维度名），端口名/事务类型是**实现名** —— 两边的对应没有建模，
    混在一起只会让"改名"变成两处都要改。
    """
    import yaml as _yaml

    path = output_dir / "inputs" / "yaml" / "uvm" / "env.yaml"
    try:
        doc = _yaml.safe_load(path.read_text(encoding="utf-8", errors="replace")) or {}
    except (OSError, ValueError):
        return []
    env = (doc or {}).get("environment") or {}
    ports: List[Dict[str, str]] = []
    seen: set = set()
    for agent in (env.get("agents") or []):
        if not isinstance(agent, dict):
            continue
        name = str(agent.get("name") or "").strip()
        item = _seq_item_type(agent)
        if not name or not item or name in seen:
            continue
        seen.add(name)
        ports.append({"name": name, "type": item})
    return ports
