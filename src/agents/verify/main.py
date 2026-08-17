"""验证开发智能体 —— UVM环境 + 测试用例 + 断言（真实工具链）"""
from typing import Dict, Any
import json
from pathlib import Path

from src.layers.l2_orchestration.agents.base import BaseAgent, AgentResult
from src.layers.l2_orchestration.agents.registry import register_agent
import structlog

logger = structlog.get_logger()


@register_agent("verify")
class VerifyAgent(BaseAgent):
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

    async def execute_task(self, task: Dict[str, Any]) -> AgentResult:
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

        # ── 策略包：按 design-style 加载设计风格验证知识，注入 spec 供测试生成 ──
        try:
            from src.layers.l2_orchestration.governance.policy_pack import get_policy_pack_loader
            pack = get_policy_pack_loader().load(design_style)
            if pack and isinstance(spec, dict):
                spec["_policy_pack"] = {
                    "design_style": pack.design_style,
                    "prompt_hints": pack.prompt_hints,
                    "test_scenarios": pack.test_scenarios,
                    "coverage_bins": pack.coverage_bins,
                }
                # 把 coverage_bins 落盘，供 gen_uvm 渲染 env_cov 时生成语义化 cross
                _bins_dir = output_dir / "inputs" / "yaml" / "uvm"
                _bins_dir.mkdir(parents=True, exist_ok=True)
                _bins_path = _bins_dir / "env_cov_bins.yaml"
                _bins_path.write_text(
                    json.dumps({"coverage_bins": pack.coverage_bins}, ensure_ascii=False),
                    encoding="utf-8")
        except Exception:
            pass

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
            }
            score = min(50 + len(files) * 2, 90) if files else 20
            return AgentResult(success=bool(files), data={"tests": tests_data, "score": score})

        # ── 1. UVM 环境生成（真实工具 uvm_tools）──
        env_gen_ok = False
        try:
            from src.tools.uvm_tools.tool_find_spec_yaml.main import run as find_spec_yaml
            from src.tools.uvm_tools.tool_jinja_render.main import run as jinja_render
            from src.tools.uvm_tools.agent_tools import _uvm_ctx
            _uvm_ctx.set(output_dir=output_dir, agents=[], env_name=f"{module_name}_env")
            # 保存 spec 供 find_spec_yaml 读取
            (output_dir / "spec.json").write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
            find_spec_yaml(json.dumps(spec, ensure_ascii=False))
            jinja_render(str(output_dir))
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
            return AgentResult(success=False, data={
                "tests": {"module": module_name, "env_files": 0, "files": [],
                          "status": "env_generation_failed"},
                "score": 0,
                "error": "UVM 环境生成失败：agents/ 下无 SV 文件（检查 find_spec_yaml/jinja_render 日志与 jsonschema 依赖）",
            })

        # ── 2. 测试用例生成（真实工具 testcase_tools，用 .invoke 绕开 LangChain tool 包装）──
        try:
            from src.tools.testcase_tools.tools import parse_test_points, map_policies_to_tests, build_scenario_yaml
            spec_json = json.dumps(spec, ensure_ascii=False)
            tp = json.loads(parse_test_points.invoke(spec_json))
            tp["features"] = spec.get("features", [])
            tp["interfaces"] = spec.get("interfaces", [])
            mapped = json.loads(map_policies_to_tests.invoke(json.dumps(tp, ensure_ascii=False)))
            mapped["env_name"] = f"{module_name}_env"
            mapped["project_name"] = module_name
            mapped["features"] = spec.get("features", [])
            mapped["interfaces"] = spec.get("interfaces", [])
            yaml_str = build_scenario_yaml.invoke(json.dumps(mapped, ensure_ascii=False))
            yaml_dir = output_dir / "inputs" / "yaml"
            yaml_dir.mkdir(parents=True, exist_ok=True)
            (yaml_dir / "constraint.yaml").write_text(yaml_str, encoding="utf-8")
        except Exception as e:
            logger.warning(f"测试用例生成失败: {e}")

        # ── 3. 断言生成（真实工具 assertion_tools）──
        try:
            from src.tools.assertion_tools.main import generate_sva_assertions
            sva = generate_sva_assertions(json.dumps(spec, ensure_ascii=False))
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
        return AgentResult(success=bool(files), data={"tests": tests_data, "score": score})

    # ── gap 定向激励生成辅助 ──

    def _generate_gap_tests(self, output_dir: Path, gaps: list):
        """根据 gap 生成定向激励 sequence，注册到 agent package 并注入 random test。"""
        import re
        from src.tools.coverage_tools.main import generate_gap_directed_seq

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

        generated = []
        for agent_dir in sorted(agents_dir.iterdir()):
            if not agent_dir.is_dir():
                continue
            agent_name = agent_dir.name
            # 只对 input agent（interface 有 output 数据端口，即 TB 驱动 DUT 输入）生成；
            # output agent 的 driver 是空实现，驱动它无意义
            iface_file = agent_dir / f"{agent_name}_interface.sv"
            if not iface_file.exists():
                continue
            iface_text = iface_file.read_text(encoding="utf-8", errors="replace")
            if not re.search(r"output\s+(?:logic|\[)", iface_text):
                continue
            tx_file = agent_dir / f"{agent_name}_transaction.sv"
            if not tx_file.exists():
                continue
            tx_text = tx_file.read_text(encoding="utf-8", errors="replace")
            widths = {}
            for m in re.finditer(r"rand\s+bit\s*\[(\d+):0\]\s+(\w+)\s*;", tx_text):
                widths[m.group(2)] = int(m.group(1)) + 1
            # input agent 处理所有 gap：input signal 直接驱动，output signal LLM 反推，generic 随机
            agent_gaps = [g for g in gaps if isinstance(g, dict)]
            if not agent_gaps:
                continue
            seq_code = generate_gap_directed_seq(agent_name, agent_gaps, widths, dut_rtl)
            (agent_dir / f"{agent_name}_gap_seq.sv").write_text(seq_code, encoding="utf-8")
            self._add_include_to_pkg(agent_dir / f"{agent_name}_pkg.sv",
                                     f"{agent_name}_gap_seq.sv")
            generated.append(agent_name)

        if generated:
            self._inject_gap_seq_to_test(output_dir / "env" / "tests", generated)
            # 铁律 1：LLM 生成的代码必须经真实 EDA（vlog）编译校验返回 0/1，阻断自说自话
            if not self._verify_compilation(output_dir):
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
    def _neutralize_gap_seq(output_dir: Path, agent_names: list):
        """把 gap_seq 重写为空实现（LLM 代码未通过 EDA 编译校验后的回退）。"""
        for an in agent_names:
            gap_file = output_dir / "agents" / an / f"{an}_gap_seq.sv"
            if not gap_file.exists():
                continue
            empty = (
                f"// gap_seq 回退为空实现（LLM 代码未通过 EDA 编译校验）\n"
                f"class {an}_gap_seq extends {an}_base_seq;\n"
                f"  `uvm_object_utils({an}_gap_seq)\n"
                f"  function new(string name = \"{an}_gap_seq\");\n"
                f"    super.new(name);\n"
                f"  endfunction\n"
                f"  virtual task body();\n"
                f"    `uvm_info(\"GAPSEQ\", \"neutralized (LLM code rejected by EDA)\", UVM_MEDIUM)\n"
                f"  endtask\n"
                f"endclass : {an}_gap_seq\n"
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
    def _inject_gap_seq_to_test(tests_dir: Path, agent_names: list):
        """在 random test 的 run_phase 开头注入 gap sequence 运行。"""
        if not tests_dir.exists():
            return
        for test_file in sorted(tests_dir.glob("*_random_test.sv")):
            text = test_file.read_text(encoding="utf-8", errors="replace")
            if "gap_seq" in text:
                continue
            blocks = []
            for an in agent_names:
                blocks.append(
                    f"    begin\n"
                    f"      {an}_gap_seq _gseq;\n"
                    f"      _gseq = {an}_gap_seq::type_id::create(\"_gseq\");\n"
                    f"      _gseq.start(env.{an}_agent_h.sqr);\n"
                    f"    end"
                )
            inj = "    // Gap-directed stimulation（根据覆盖率 gap 自动生成）\n" + \
                  "\n".join(blocks) + "\n"
            text = text.replace("    phase.raise_objection(this);\n",
                                "    phase.raise_objection(this);\n\n" + inj, 1)
            test_file.write_text(text, encoding="utf-8", errors="replace")
