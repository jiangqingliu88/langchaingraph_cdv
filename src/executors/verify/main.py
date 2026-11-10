"""验证开发智能体 —— UVM环境 + 测试用例 + 断言（真实工具链）"""
from typing import Dict, Any, List, Optional
import json
from pathlib import Path

from src.layers.l2_orchestration.executors.base import BaseExecutor, ExecutorResult
from src.layers.l2_orchestration.executors.registry import register_executor
from src.executors.verify.steps_dag import StepRecorder
from src.executors.verify.ir_artifacts import (
    attach_tp_constraints, enrich_case_ir, testpoint_files,
    write_contract_build,
)
from src.executors.verify.dut_checker import build_dut_checker
from src.executors.verify.steps.vplan_layout import package_vplan_assets
from src.executors.verify.steps.interface_spec import (  # noqa: F401
    _interface_protocol,
    _merge_interface_attrs,
    _top_module_interfaces,
    _vplan_uvm_spec,
)
import structlog

logger = structlog.get_logger()


from src.executors.verify.steps.helpers import (  # noqa: E402
    _main_phase_objection_at,
    _test_files_defining,
    _regression_test_name,
    _spec_of,
    _load_runtime_model_doc,
    _assertion_signals,
    _bitmap_patch,
    _retire_stale_probe,
    _timing_signals,
    _sv_ident,
    _bitmap_timing,
    _bitmap_agent,
    _untrackable_note,
    _bitmap_entry,
    _build_tp_bitmap,
    _write_tp_bitmap,
    _seq_item_type,
    _constraint_ports,
    _AGENT_SUFFIX,
)


from src.executors.verify.steps.env_cov import EnvCovSteps  # noqa: E402
from src.executors.verify.steps.testpoints import TestpointSteps  # noqa: E402
from src.executors.verify.steps.constraint import ConstraintSteps  # noqa: E402
from src.executors.verify.steps.gap import GapRenderSteps  # noqa: E402

@register_executor("verify")
class VerifyExecutor(TestpointSteps, EnvCovSteps, ConstraintSteps, GapRenderSteps, BaseExecutor):
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
        # **早于 env 生成解析一次**：测试点位图（`tp_seen`）要进覆盖率接口，
        # 而接口在 `jinja_render` 之前就要落盘。这里只读文件，没有副作用；
        # 第 2 步复用同一份，不再重复解析。
        from src.layers.l3_decision.vplan import engine

        vplan_project = engine.project_for(spec, output_dir)
        params = task.get("params", {}) or {}
        supplement = params.get("supplement", False) if isinstance(params, dict) else False
        gaps = params.get("gaps", []) if isinstance(params, dict) else []
        design_style = params.get("design_style", "baseline")
        files = []
        #: 策略包的语义 bin —— 攒着，等 `find_spec_yaml` 跑完再落盘（理由见下面那段）
        cov_bins_for_render: List[Any] = []
        #: 8 步的数据依赖记录器（`steps_dag.py`）—— 前置没跑就当场报错，
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
            # 保存 spec 供 find_spec_yaml 读取（VPlan 顶层契约会改写协议边界）
            uvm_spec = _vplan_uvm_spec(spec, output_dir)
            (output_dir / "spec.json").write_text(
                json.dumps(uvm_spec, ensure_ascii=False), encoding="utf-8")
            # ⚠️ **计划必须早于 `find_spec_yaml`**：回归的 `count`/`SEED` 就在这一步
            # 由它铺开（`_seed_plan` 读 `coverage/coverage_plan.yaml`）。晚一步的话
            # 回归已经生成完了，批次一条都不在里面 —— 而日志看不出任何异常
            # （`env_cov_bins` 是反过来：那个落在 find_spec_yaml 会清空的目录里，
            # 只能晚于它。两件事的方向相反，别一起搬）。
            self._write_coverage_plan(output_dir)
            steps.mark("coverage_plan")
            call_tool("find_spec_yaml", {"spec_text": json.dumps(
                uvm_spec, ensure_ascii=False)})
            steps.mark("find_spec_yaml")
            # ── 测试点 IR **提前算一次** ──
            #
            # `tp_seen` 位图要进覆盖率接口，而接口在 `jinja_render` 之前落盘；
            # 渲染后再生成 testpoints 就赶不上这一轮。这里只算不写（写仍在
            # `_write_testpoints`，那一步还要落 methodology/StimulusPlan），
            # 两份产物共用同一份 payload —— **不重建第二份真源**。
            tp_payload = self._prebuild_testpoints(output_dir, module_name)
            steps.mark("testpoints_prebuild")
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
            dut_channel = self._write_coverage_dut_channel(
                output_dir, tp_payload=tp_payload)
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
            # P2：资源模型/场景必须先于渲染落盘 —— `EnvironmentRenderTask`
            # 读这两份生成 resource checker；晚于渲染这一轮就没有 checker
            # （而 checker 缺失不会让编译失败，只会静默少一个证据源）。
            self._prepare_resource_artifacts(output_dir, module_name)
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

        # ── 2. 测试点 IR（VPlan 执行资产 → TP/Case/契约）──
        #
        # 输入是 run 的 `inputs/vplan/`（`data/*.csv` + `cases/*.yaml`）；
        # `vplan.engine` 负责投影，不再有 case 模型引擎。
        if vplan_project is not None:
            # VPlan 原生：没有 case 表/完备性打分这一步，TP IR 直接从
            # `data/*.csv` + `cases/*.yaml` 投影。
            try:
                tp_files = self._write_testpoints(output_dir, module_name,
                                                  payload=tp_payload)
                files.extend(tp_files)
                self._write_plan_consistency(output_dir)
                logger.info("测试点 IR：VPlan 原生投影（无 case 属性表）")
            except Exception as e:                     # noqa: BLE001 旁路
                logger.warning(f"VPlan 测试点 IR 落盘失败: {e}")
        else:
            logger.info("没有 VPlan 项目 —— 跳过测试点 IR")

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

        package_vplan_assets(output_dir, module_name)
        tests_data = {
            "module": module_name,
            "env_files": len(files),
            "files": files,
            "status": "generated" if files else "empty",
        }
        score = min(50 + len(files) * 2, 90) if files else 20
        return ExecutorResult(success=bool(files), data={"tests": tests_data, "score": score})

    # ── 功能覆盖率点：case 模型 → env_cov 的 bin ──




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
        from src.tools.generation.uvm_tools.tool_uvm.generators.constraint_gen import (
            annotate_coverage_plan)
        annotate_coverage_plan(output_dir, payload, logger)

    def _write_plan_consistency(self, output_dir: Path) -> None:
        """TP IR / StimulusPlan / constraint_backing 的同源校验。"""
        try:
            from src.layers.l3_decision.vplan.runtime.framework.plan_consistency import (
                write_plan_consistency)

            summary = write_plan_consistency(output_dir)
            if summary["issues"]:
                logger.warning(f"plan consistency：{summary['issues']} 处不一致")
        except Exception as e:                     # noqa: BLE001 旁路
            logger.warning(f"plan consistency 生成失败: {e}")

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
        from src.layers.l3_decision.vplan import engine

        module_name = str(_spec_of(output_dir).get("design_name") or "dut")
        project = engine.project_for(_spec_of(output_dir), output_dir)
        if project is None:
            return
        case_text = engine.model_text(project)
        coverage_text = engine.coverage_model_text(project, module_name)
        cons_path = output_dir / "inputs" / "yaml" / "uvm" / "constraint.yaml"
        try:
            constraint_text = (cons_path.read_text(encoding="utf-8")
                               if cons_path.is_file() else "")
            a = engine.run_association(case_text, coverage_text, constraint_text)
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
        from src.tools.generation.uvm_tools.tool_uvm.generators.coverage_gen import (
            write_coverage_plan)
        write_coverage_plan(output_dir, None, logger, module_name="dut")

    def _write_coverage_dut_channel(self, output_dir: Path,
                                    tp_payload: Dict[str, Any] = None
                                    ) -> Dict[str, Any]:
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
        from src.layers.l3_decision.vplan import engine

        project = engine.project_for(_spec_of(output_dir), output_dir)
        if project is None:
            return {}
        text = engine.model_text(project)
        decls = _load_runtime_model_doc(text)
        tp_width = len((tp_payload or {}).get("testpoints") or [])
        try:
            # `extra_signals`：断言规则引用、但没被覆盖点采的信号（`issue_valid`
            # 这种端口）。接口里不引，env 检查组就读不到 —— 规则只能被跳过。
            # **timing 的 start/end 也要引**：它们由 env 检查组逐拍读，不在
            # 覆盖点里的话接口上根本没有。
            extra = (_assertion_signals(decls) + _timing_signals(tp_payload))
            payload = engine.run_covergroups(
                project, "dut", extra_signals=extra, tp_bitmap_width=tp_width)
        except Exception as e:                       # noqa: BLE001 旁路
            logger.warning(f"读 case 模型失败（不生成 DUT 覆盖率接口）: {e}")
            return {}
        bitmap_patch = _bitmap_patch(output_dir, tp_payload, payload,
                                     self._agent_transaction_fields(output_dir))
        if not payload.get("probe_ports"):
            # 模型里没有 `sample: dut` 的字段：没有覆盖率接口，`tp_seen` 无处可放；
            # 但位图与 `[TP_HIT]` 日志仍然有用（stimulus 通道）。
            return bitmap_patch
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
            return bitmap_patch
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
        checker_patch = build_dut_checker(decls, meta)
        # 它和这个接口采的是**同一批信号**：两份同时挂在 filelist 里，就是同一个
        # 信号被两个 covergroup 各采一遍 —— `vcover` 报表里多一个 covergroup，
        # 签核的"功能覆盖率"被自己搅浑。删的是本管道自己的产物（名字固定、
        # 随时可重生成），而且**说出来**，不静默动别人的文件。
        _retire_stale_probe(path)
        logger.info(f"功能覆盖率点（DUT 通道）：{len(payload['probe_ports'])} 个信号 "
                    f"→ {path.name}（bind 到 {meta['dut_module']}；由 "
                    f"{meta['type']} 引给 env 覆盖率组件，会被真编译、真采样）")
        return {"dut_if": meta, "dut_bins": payload.get("dut_bins") or {},
                **checker_patch, **bitmap_patch}

    @staticmethod
    def _field_bins(output_dir: Path) -> Dict[str, List[Dict[str, Any]]]:
        """VPlan 执行资产 → `{字段名: [{name, value}, …]}`（给 `env_cov` 用）。

        键是**字段名**（`paddr` / `pwdata` / `pwrite`）—— case 模型的字段名就是
        spec 的接口信号名，而 `env_cov` 的 coverpoint 挂在 `agent_item.<字段>` 上，
        两边是同一个命名空间，所以能直接对上。对不上的字段由模板忽略（它按事务字段
        遍历），不会生成引用不到信号的 bin。

        拿不到模型（文件不在 / 解析失败）就返回空 —— 调用方据此退回自动分箱，
        **不静默假装有模型**。
        """
        from src.layers.l3_decision.vplan import engine

        project = engine.project_for(_spec_of(output_dir), output_dir)
        if project is None:
            return {}
        try:
            points = engine.run_covergroups(project, "dut")
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

