"""运维调度智能体 —— 编译 + 仿真 + 回归（真实 EDA 工具链）"""
from typing import Dict, Any
import json
from pathlib import Path

from src.layers.l2_orchestration.executors.base import BaseExecutor, ExecutorResult
from src.layers.l2_orchestration.executors.registry import register_executor
import structlog

logger = structlog.get_logger()


def _worklist_filter(output_dir: Path, params: Dict[str, Any]) -> str:
    """M4 义务 worklist（**opt-in**）：只重跑未清偿义务对应的回归 test。

    开关：`params.worklist is True` 或 `SIGNOFFAI_WORKLIST=1`。默认关闭 ——
    默认仍是全量回归（nightly 需要它），worklist 用于"补一条证据"的重跑。
    算不出来（没有契约 / 没有回归清单）就返回空串，回落全量，不静默缩小范围。
    """
    import os

    enabled = (isinstance(params, dict) and params.get("worklist") is True) or \
        str(os.environ.get("SIGNOFFAI_WORKLIST", "")).lower() in ("1", "true", "on")
    if not enabled:
        return ""
    try:
        from src.tools.checking.verification_os.worklist import write_worklist

        data = write_worklist(output_dir)
    except Exception as e:                          # noqa: BLE001 旁路
        logger.warning(f"worklist 生成失败（回落全量）: {e}")
        return ""
    if not data.get("available") or not data.get("regex"):
        logger.info("worklist：没有未清偿义务或清单不可用 → 跑全量")
        return ""
    logger.info(f"worklist：{data['open']}/{data['obligations']} 条义务未清偿 "
                f"→ 只跑 {data['count']} 条 test")
    return str(data["regex"])


def _regression_filter(output_dir: Path, params: Dict[str, Any]) -> str:
    """回归 test 过滤：worklist（义务驱动）优先，其次增量基线，否则全量。"""
    return _worklist_filter(output_dir, params) or OpsExecutor._incremental_filter(output_dir)


def _eda_guard(design_style: str):
    """EDA 可用性前置检查：没有 vlog/vsim 就响亮失败，不假装跑回归。

    确定性检测 PATH；缺失 → `eda_missing`（score 0，success=False），由执行引擎
    终止闭环（BLOCKED_EDA_MISSING），而不是误判为功能失败去循环重构。
    """
    import shutil

    eda_found = [t for t in ("vlog", "vsim") if shutil.which(t)]
    if eda_found:
        return None
    return ExecutorResult(success=False, data={
        "regression": {
            "status": "FAIL", "passed": 0, "failed": 1, "total": 1,
            "eda_missing": True,
            "error": "未检测到 EDA 工具（vlog/vsim）。请安装 QuestaSim 并加入 PATH 后重试。",
            "eda_tools_found": eda_found,
            "design_style": design_style,
        },
        "score": 0,
    })


def _contract_gate(output_dir: Path, params: Dict[str, Any]):
    """M1 契约门禁：**没有（或损坏的）契约，ops 拒绝开跑**。

    放宽条件只有两条，都写在这里：
      · 环境变量 `SIGNOFFAI_CONTRACT_GATE=off`（手工/迁移期）；
      · `params.contract_gate is False`（调用方显式关掉）。
    没有 `coverage/testpoints.yaml` 的 run 不是 verify 产出的（历史/手工目录），
    契约无从谈起 —— 放行，不退化成"所有老 run 都不能跑回归"。
    """
    import os

    if str(os.environ.get("SIGNOFFAI_CONTRACT_GATE", "")).lower() in ("off", "0", "false"):
        return None
    if isinstance(params, dict) and params.get("contract_gate") is False:
        return None
    if not (Path(output_dir) / "coverage" / "testpoints.yaml").is_file():
        return None

    from src.tools.checking.verification_os import check_contract

    result = check_contract(output_dir)
    if result.get("ok"):
        return None
    logger.warning(f"契约门禁拦截：{result.get('reason')}（{output_dir}）")
    return ExecutorResult(success=False, data={
        "regression": {
            "status": "FAIL", "passed": 0, "failed": 1, "total": 1,
            "contract_missing": True, "contract": result,
            "error": f"契约不可用（{result.get('reason')}）—— 先跑 verify，"
                     f"或用 `vagent contract build --run {output_dir}` 生成",
        },
        "score": 0,
    }, error=f"契约门禁拦截：{result.get('reason')}")


def _case_library():
    """回归结果回写目标（L4 `TestcaseRegistry`）。

    `InfrastructureManager` 在 L1，**不能**自己 import L4，所以库对象是注入的。
    L2 的 `hydrate_runtime` 会注入 `rt.infra`，但 ops 执行器自己另起一个
    `InfrastructureManager` 跑分级回归 —— 不在这儿补上，回归结果就永远不落库
    （每次跑都出一条「没有注入 case 库」warning）。拿不到就返回 None，L1 会
    自己出声，不静默。
    """
    try:
        from src.layers.l4_memory.testcase_registry import TestcaseRegistry
        return TestcaseRegistry()
    except Exception as e:                      # noqa: BLE001 旁路
        logger.warning(f"case 库不可用，回归结果不会回写用例状态: {e}")
        return None


def _write_wave_index(output_dir: Path) -> None:
    """回归收尾写 `waves/manifest.json` —— 波形 ↔ 用例 ↔ 测试点。

    波形按用例落（`test_*/waves/<task>.db`），但此前**没有任何文件**把
    "这份波形对应哪条用例、证明哪些测试点"写下来 —— 打开波形只看到模块名。
    这里统一落一份索引（唯一真源，供 audit 反查、`vagent wave show` 展示）。

    **失败不拦回归**：索引是旁路证据，落不下去时日志喊一声，别把一次真实
    跑完的回归报成失败。波形文件本身仍在用例目录里。
    """
    try:
        from src.layers.l1_infrastructure.layout import test_dirs
        from src.tools.common.lib.case_meta import write_wave_manifest
        manifest = write_wave_manifest(output_dir, test_dirs(output_dir))
        logger.info(f"波形索引：{manifest.get('with_wave', 0)}/"
                    f"{manifest.get('count', 0)} 条用例有波形 → waves/manifest.json")
    except Exception as e:                      # noqa: BLE001 旁路证据
        logger.warning(f"波形索引生成失败（回归结果不受影响）: {e}")


@register_executor("ops")
class OpsExecutor(BaseExecutor):
    """运维调度智能体 = 编译 + 仿真（RegressionRunner）"""

    task_type = "regression_management"
    consumes = ["env", "tests"]
    produces = "regression"

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(
            role="ops", display_name="运维调度智能体",
            description="编译+仿真+回归", config=config or {})

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

        params = task.get("params", {}) or {}
        design_style = params.get("design_style", "baseline") if isinstance(params, dict) else "baseline"

        # **无契约不执行**（v3 M1）：verify 已经编译过 contract/，ops 只校验它。
        # 只有"本该有契约却缺失/损坏"才算拦截 —— 没有 TP IR 的手工/历史 run 放行。
        blocked = _contract_gate(output_dir, params)
        if blocked is not None:
            return blocked
        # 这一轮要开的**仿真业务**（cov / wave / debug_all …，见 sim_modes.py）。
        # None = 交给默认（`_normalize_sim_modes` 给 `cov+wave`），不是"什么都不开"。
        sim_modes = params.get("sim_modes") if isinstance(params, dict) else None

        # ── EDA 可用性前置检查（失败响亮：没有 EDA 就不假装跑回归）──
        blocked = _eda_guard(design_style)
        if blocked is not None:
            return blocked

        # ── 回归执行：直接走 L1 InfrastructureManager（真实回归框架）──
        # 不走 MCP 子进程工具（regression.run）：tool_worker 引用的 regression_tool 模块
        # 已不存在（断链），且子进程隔离会丢失 EDA 失败细节。L1 是同一回归框架的统一封装。
        #
        # **走分级门控那一条**（loopback → p0 → p1 → p2 → p3）：agent loopback 不过
        # 就不进 P0 —— 环境自身都没自洽（SCB 不 match）时，后面几级的失败会全是
        # 同一个环境问题刷屏，把真正的 DUT 缺陷埋掉。`blocked_at` 说明卡在哪一级。
        try:
            from src.layers.l1_infrastructure.infrastructure import InfrastructureManager
            infra = InfrastructureManager(output_dir, case_library=_case_library())
            # 人工节点开关（工具栏「人工节点」，`RunRequest.manual_gate`）：
            # **关掉 = auto_approve**，loopback 全过也直接往下跑，不停车等人。
            # 缺省（没传）按**开**处理 —— 门是默认该在的。
            manual_gate = (params.get("manual_gate", True)
                           if isinstance(params, dict) else True)
            reg_data = infra.run_regression_staged(
                mode="local", enabled_modes=sim_modes,
                auto_approve=not manual_gate,
                tests=_regression_filter(output_dir, params))
            if not isinstance(reg_data, dict):
                reg_data = {}
        except Exception as e:
            logger.warning(f"回归执行失败: {e}")
            reg_data = {"status": "FAIL", "passed": 0, "failed": 1, "total": 1,
                        "error": str(e)[:300], "design_style": design_style}

        # 分级门控：把"卡在哪一级"摊到顶层，好让 debug / decision 一眼看到
        if isinstance(reg_data, dict) and reg_data.get("blocked_at"):
            logger.warning(f"分级回归卡在 {reg_data['blocked_at']}："
                           f"{reg_data.get('blocked_reason', '')}")

        # 人工节点：**既不是失败，也不是可以往下走** —— 回归停在 loopback 之后等人
        # 放行。必须和 PASS / FAIL 分开：按下面 `failed == 0 and passed > 0` 的口径，
        # 它会**被判成成功**，流程就带着一个没放行的门继续往下跑了。
        awaiting = (isinstance(reg_data, dict)
                    and reg_data.get("status") == "WAITING_APPROVAL")
        if awaiting:
            aw = reg_data.get("awaiting") or {}
            logger.warning(
                f"分级回归停在人工节点：{aw.get('after')} 已全过，"
                f"进 {aw.get('next')} 前需人工放行（{aw.get('hint', '')}）")

        if not reg_data.get("status"):
            # 工具失败 → 兜底 FAIL（含错误信息，供 debug/decision 分析）
            err = str(reg_data.get("error", ""))
            reg_data = {
                "status": "FAIL", "passed": 0, "failed": 1, "total": 1,
                "error": err, "design_style": design_style,
                "eda_missing": self._is_eda_missing(err),
            }
        else:
            reg_data.setdefault("design_style", design_style)
            # 记下这一轮开的仿真业务 —— 审计/复现要能回答"这份波形/覆盖率
            # 是哪几门业务跑出来的"，而不是回头去猜当时的界面状态。
            reg_data.setdefault("sim_modes", list(sim_modes or []))
            # 记下这一轮人工节点开没开 —— 和 sim_modes 同理：跑完要能回答
            # "这一轮为什么没停在 loopback"，而不是回头去猜当时的开关状态。
            reg_data.setdefault("manual_gate", manual_gate)
            # 即使回归跑起来了，内部报 EDA 缺失（如 stderr 含 vlog/vsim 找不到）也要标记
            _err = str(reg_data.get("error", "") or reg_data.get("stderr", ""))
            if not reg_data.get("eda_missing"):
                reg_data["eda_missing"] = self._is_eda_missing(_err)

        _write_wave_index(output_dir)

        passed = reg_data.get("passed", 0)
        failed = reg_data.get("failed", 0)
        # 等人放行时 `failed == 0 and passed > 0` 也成立 —— 显式排除，别让它算成功
        success = (not awaiting
                   and (reg_data.get("status") == "PASS"
                        or (failed == 0 and passed > 0)))
        score = 60 if success else 20
        data = {"regression": reg_data, "score": score}
        if awaiting:
            # 让上层（人 / 报告 / 决策）能把"停下来等放行"和"跑挂了"分开
            data["awaiting_approval"] = reg_data.get("awaiting") or {}
        return ExecutorResult(
            success=success,
            data=data,
            error=(reg_data.get("blocked_reason") or None) if awaiting else None,
            metadata={"awaiting_approval": True} if awaiting else {},
        )

    # ── 文件系统发现辅助 ──

    @staticmethod
    def _incremental_filter(output_dir: Path) -> str:
        """按 `SIGNOFFAI_INCREMENTAL_BASELINE` 生成回归 test 正则过滤。

        没有基线 / 没有依赖映射 → 返回空串（全量）。**绝不因为"算不出来"
        就静默缩小范围**：`confidence != mapped` 时明确跑全量。
        """
        import os
        import re

        baseline = os.environ.get("SIGNOFFAI_INCREMENTAL_BASELINE", "").strip()
        if not baseline or not Path(baseline).is_dir():
            return ""
        try:
            from src.core.incremental.plan import write_plan
            plan = write_plan(baseline, output_dir)
        except Exception as e:                         # noqa: BLE001 增量是增强
            logger.warning(f"增量计划生成失败（按全量跑）: {e}")
            return ""
        selected = plan.get("selected_tests") or []
        if plan.get("confidence") != "mapped" or not selected:
            logger.info(f"增量计划不缩小范围（confidence={plan.get('confidence')}）")
            return ""
        logger.info(f"增量回归：{len(selected)}/{plan.get('all_tests')} 条 "
                    f"（基线 {plan.get('baseline_run')}）")
        return "^(?:" + "|".join(re.escape(t) for t in selected) + ")$"

    @staticmethod
    def _is_eda_missing(err_text: str) -> bool:
        """识别"EDA 工具缺失"类错误（vlog/vsim 找不到），区别于编译/仿真失败。

        这是"失败响亮"的关键：EDA 缺失是环境问题，不是代码问题，
        决策层必须据此终止闭环并提示安装，而不是误判为功能错误去重构 RTL。
        """
        if not err_text:
            return False
        t = err_text.lower()
        markers = (
            "'vlog' 不是内部或外部命令", "'vsim' 不是内部或外部命令",
            "not recognized as", "no such file or directory", "not found",
            "cannot find", "找不到", "无法识别", "不是内部或外部命令",
            "vlog.exe", "vsim.exe", "questa", "questa sim",
        )
        # 只在这些词同时出现时才判 EDA 缺失，避免把编译错误误判
        return any(m in t for m in markers)

    @staticmethod
    def _discover_env_name(output_dir: Path) -> str:
        """从 env/*_pkg.sv 发现环境名（如 dut_env）。"""
        try:
            for p in sorted((output_dir / "env").glob("*_pkg.sv")):
                return p.name.replace("_pkg.sv", "")
        except Exception:
            pass
        return "dut_env"

    @staticmethod
    def _discover_agent_names(output_dir: Path) -> list:
        """从 agents/ 子目录发现 agent 名（如 dut_in, dut_out）。"""
        try:
            agents_dir = output_dir / "agents"
            if agents_dir.exists():
                return sorted(d.name for d in agents_dir.iterdir() if d.is_dir())
        except Exception:
            pass
        return []

    @staticmethod
    def _discover_top_module(output_dir: Path) -> str:
        """从 bench/*_tb_top.sv 发现 testbench 顶层模块名。"""
        try:
            for p in sorted((output_dir / "bench").glob("*_tb_top.sv")):
                return p.stem
        except Exception:
            pass
        return ""
