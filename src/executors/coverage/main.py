"""覆盖率智能体 —— 收集 + 分析覆盖率数据（真实工具）"""
from typing import Dict, Any
import json
from pathlib import Path

from src.layers.l2_orchestration.executors.base import BaseExecutor, ExecutorResult
from src.layers.l2_orchestration.executors.registry import register_executor
import structlog

logger = structlog.get_logger()


@register_executor("coverage")
class CoverageExecutor(BaseExecutor):
    """覆盖率智能体 = 覆盖率收集 + gap 分析"""

    task_type = "coverage_analysis"
    consumes = ["spec", "regression"]
    produces = "coverage"

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(
            role="coverage", display_name="覆盖率智能体",
            description="收集+分析覆盖率", config=config or {})

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

        # 扩种闭环：params.seed 控制随机种子（EXPAND_SEEDS 时递增）
        params = task.get("params", {}) or {}
        seed = params.get("seed", 0) if isinstance(params, dict) else 0
        round_num = params.get("round_num", 0) if isinstance(params, dict) else 0

        # ── 功能覆盖率点生成 ──
        #
        # **优先从 VPlan 执行资产来**（`inputs/vplan/data/*.csv`）：维度、
        # 取值点、维度之间要不要一起组合，都在里面。它与 `run_uvm_tests`
        # 是**同一份分母的两面**：激励撒的取值 = 覆盖率收的 bin。
        #
        # 没有 VPlan 项目时才退回 spec 骨架生成器
        # （`FunctionalCoveragePointGenerator`，只给 opcode 枚举 bin）。
        ctx = task.get("ctx", {})
        spec = ctx.get("spec", {}) if hasattr(ctx, "get") else {}
        if not isinstance(spec, dict):
            spec = {}
        module_name = spec.get("design_name", "dut") or "dut"

        func_cov: Dict[str, Any] = {}
        try:
            func_cov = self._build_functional_coverage(output_dir, module_name, spec)
        except Exception as e:
            logger.warning(f"功能覆盖率点生成失败: {e}")
            func_cov = {}

        # ── EDA 可用性前置检查（失败响亮：没有 vsim 就不假装收集覆盖率）──
        import shutil
        if not shutil.which("vsim"):
            return ExecutorResult(success=False, data={
                "coverage": {"overall_pct": 0, "status": "EDA_MISSING"},
                "gaps": [],
                "score": 0,
                "error": "未检测到 vsim，无法收集覆盖率。请安装 QuestaSim 并加入 PATH 后重试。",
            })

        # ── 收集真实覆盖率（vsim -coverage → ucdb → 报告），走 L1 统一入口 ──
        # 不走 MCP 子进程工具（coverage.collect）：tool_worker 引用的 regression_tool
        # 模块已不存在（断链）。L1 InfrastructureManager.collect_coverage 是同一后端
        # 的统一封装（含 ucdb 归档 + SHA256 固化），返回 {coverage, simulation, ...}。
        coverage_data = {}
        collection_error = ""
        try:
            from src.layers.l1_infrastructure.infrastructure import InfrastructureManager
            infra = InfrastructureManager(output_dir)
            coverage_data = infra.collect_coverage(round_num=round_num, seed=seed)
            if not isinstance(coverage_data, dict):
                coverage_data = {}
        except Exception as e:
            logger.warning(f"覆盖率收集失败: {e}")
            collection_error = str(e)[:300]

        # collect_real_coverage 返回 {compile, simulation, coverage:{...}, status}
        # 真正的覆盖率指标在 result["coverage"] 里
        nested_cov = coverage_data.get("coverage", {}) if isinstance(coverage_data, dict) else {}
        if not isinstance(nested_cov, dict):
            nested_cov = {}

        # ── 收集失败 ≠ 覆盖率是 0 ──
        # 这两个在报告里长得一样（都是 0%），但一个是"工具/环境没跑起来"，
        # 一个是"跑了确实没覆盖"。原来这里把前者的原因直接丢掉，界面上只剩一个
        # 0.0%，排查时得手工去翻运行目录的日志才知道是编译挂了（实测踩过：
        # 覆盖率编译的 filelist 漏了 UVM 库，报 9 个错，最后呈现的就是"覆盖率 0%"）。
        # 所以：**原因留进结果与日志**，哪怕结论仍然是 0%。
        if not collection_error and coverage_data.get("status") not in (None, "PASS"):
            _compile = coverage_data.get("compile") or {}
            _sim = coverage_data.get("simulation") or {}
            collection_error = str(
                coverage_data.get("error")
                or (isinstance(_compile, dict) and _compile.get("stderr", ""))
                or (isinstance(_sim, dict) and _sim.get("error", ""))
                or "coverage collection not PASS"
            )[:300]
        if collection_error:
            logger.error(f"覆盖率收集未成功（结果按 0% 记，原因如下，不是「确实没覆盖」）: "
                         f"{collection_error[:200]}")
        # 原始证据（仿真 log + VCD 波形），供证据链归档 + 人工检查
        _simulation = coverage_data.get("simulation", {}) if isinstance(coverage_data, dict) else {}
        log_path = _simulation.get("log_path", "") if isinstance(_simulation, dict) else ""
        vcd_path = _simulation.get("vcd_path", "") if isinstance(_simulation, dict) else ""

        # ── 语义层降维：真实 gap 归因（constraint / unstimulated / unreachable）──
        toggle_details = []
        try:
            from src.layers.l3_decision.evidence.main import build_coverage_gaps
            from src.layers.l1_infrastructure.coverage_backend import get_coverage_backend
            constraints = self._extract_constraints(output_dir)
            toggle_details = get_coverage_backend().parse_toggle_details(output_dir)
            gaps = build_coverage_gaps(nested_cov, constraints, toggle_details)
        except Exception as e:
            logger.warning(f"gap 归因失败: {e}")
            gaps = []

        # ── 覆盖地图：bin 级精确定位（对应自动驾驶的"定位层"）──
        coverage_map = {}
        try:
            from src.layers.l2_orchestration.coverage_map import CoverageMap
            functional_detail = nested_cov.get("functional_detail", {})
            coverage_map = CoverageMap().build(nested_cov, toggle_details, functional_detail)
        except Exception as e:
            logger.warning(f"覆盖地图生成失败: {e}")

        # ── V2 Knowledge Graph：覆盖率 bin 命中状态落库（跨 run 跟踪进度）──
        try:
            from src.layers.l3_decision.knowledge.persistence import record_coverage_bins
            _bins = coverage_map.get("bins", []) if isinstance(coverage_map, dict) else []
            if _bins:
                _run_id = Path(output_dir).name
                await record_coverage_bins(_bins, run_id=_run_id)
                logger.info(f"覆盖率 bin 落库: {len(_bins)} 个")
        except Exception as e:
            logger.warning(f"覆盖率 bin 落库失败: {e}")

        # ── Event Bus：发布 COVERAGE_UPDATED（异步通知订阅者：KG / 决策 / 其它 Agent）──
        try:
            from src.layers.l2_orchestration.communication.verification_events import publish_coverage_updated
            _module = (ctx.get("spec", {}).get("design_name", "dut")
                       if isinstance(ctx, dict) else "dut")
            _ov = nested_cov.get("overall_pct", nested_cov.get("coverage_pct", 0))
            try:
                _ov = float(_ov) if _ov else 0.0
            except (TypeError, ValueError):
                _ov = 0.0
            _gap = ";".join(g.get("dimension", "") for g in gaps if isinstance(g, dict))[:200]
            await publish_coverage_updated(module=_module, coverage=_ov, gap=_gap)
        except Exception as e:
            logger.warning(f"发布 COVERAGE_UPDATED 失败: {e}")

        if nested_cov:
            # 直接返回扁平覆盖率指标，避免外层再包一层 coverage → 双重嵌套
            overall = nested_cov.get("overall_pct", nested_cov.get("coverage_pct", 0))
            if isinstance(overall, str):
                try:
                    overall = float(overall)
                except ValueError:
                    overall = 0
            score = min(50 + int(overall * 0.45), 95) if overall else 20
        else:
            nested_cov = {"overall_pct": 0}
            gaps = []
            score = 10

        # ── 归因校准: 用历史反馈过滤 unreachable 黑名单 + 标注 reason 置信度 ──
        calibration = {}
        try:
            from src.layers.l4_memory.coverage_experience import get_coverage_experience_store
            cov_store = get_coverage_experience_store()
            blacklist = set(cov_store.get_blacklist())
            acc = cov_store.reason_accuracy()
            filtered = []
            dropped = 0
            blacklisted_gaps = []  # 被黑名单过滤的结构性死代码点（供 Exclude 自动发现提议放弃）
            for g in gaps:
                if isinstance(g, dict):
                    if g.get("reason") == "unreachable" and g.get("dimension") in blacklist:
                        dropped += 1
                        blacklisted_gaps.append({
                            "dimension": g.get("dimension"),
                            "location": g.get("location") or g.get("signal") or g.get("dimension"),
                        })
                        continue
                    g["reason_confidence"] = acc.get(g.get("reason"), {}).get("confidence", 1.0)
                filtered.append(g)
            gaps = filtered
            calibration = {"blacklist": sorted(blacklist), "dropped_unreachable": dropped,
                           "blacklisted_gaps": blacklisted_gaps, "reason_accuracy": acc}
        except Exception as _e:
            logger.warning(f"归因校准过滤失败: {_e}")

        # ── 铁律 2 + 3：覆盖率数据库版本固化 + 降采样 ──
        # ucdb 哈希（版本固化，复现时可回滚比对）；LLM 空洞分析只读 text 汇总，绝不读 ucdb
        from src.layers.l1_infrastructure.infrastructure import sha256_file
        ucdb_path = nested_cov.get("ucdb_path", "")
        ucdb_hash = ""
        if ucdb_path:
            try:
                # 分块哈希：ucdb 可能几十 GB，整文件 read_bytes() 会打爆内存。
                # 与铁律二的归档实现（InfrastructureManager.archive_coverage）共用
                # 同一份 sha256_file()，避免出现两份行为不同的哈希。
                ucdb_hash = sha256_file(ucdb_path)
            except Exception:
                pass
        # 铁律三：指向 <1KB 语义降采样（而非完整 vcover 报告）——LLM 只看这一份。
        # 完整报告仍留在 coverage_summary.txt，供人工与解析使用。
        summary_path = str(Path(nested_cov.get("report_dir", "")) / "coverage_summary_llm.txt") \
            if nested_cov.get("report_dir") else ""

        return ExecutorResult(success=True, data={
            "coverage": nested_cov,
            # **语义自述**：`{ucdb_nonzero_bins, cg_dut_hit_gt_zero,
            # constraint_policy_applied, seed_diversity_verified, notes}` ——
            # 由 `collect_real_coverage.run()` 算出（见那个函数的 docstring）。
            # 走顶层键（不是塞进 `coverage`）：audit 的门禁直接读它判
            # `PASS_WITH_CAVEAT`，与具体的覆盖率数字解耦。
            "semantic_validations": coverage_data.get("semantic_validations") or {},
            # 测试点 × 覆盖仓矩阵（含未命中/不可映射的 tp_id）—— 闭环决策与
            # 签核都读它；没有 TP IR 时是空字典（不是"全过了"）。
            "tp_matrix": coverage_data.get("tp_matrix") or {},
            "gaps": gaps,
            "score": score,
            "coverage_db": {"ucdb_path": ucdb_path, "sha256": ucdb_hash},
            "coverage_summary": summary_path,
            "log_path": log_path,
            "vcd_path": vcd_path,
            "collection_error": collection_error,
            "calibration": calibration,
            "functional_coverage": func_cov,
            "coverage_map": coverage_map,
        })

    # ── 功能覆盖率点：case 模型优先，spec 骨架兜底 ──

    @staticmethod
    def _build_functional_coverage(output_dir: Path, module_name: str,
                                   spec: Dict[str, Any]) -> Dict[str, Any]:
        """产出 `coverage/coverage_points.json` —— 功能覆盖点的**声明**。

        ## 这里**不写** `coverage/<module>_cg.sv`（与从前不一样）

        那份文件从来**没有进过编译清单**（全仓库没有一处把它加进 filelist），
        所以它永远不被编译、不被采样、不被 `vcover` 统计 —— 一个看着像功能覆盖率
        模型、其实一个 bin 都没测的文件。**那比没有更坏**：人对着它调覆盖率，
        调的是个死物。

        真正被测量的是 `env_cov.sv.j2` 里那几个 `cg_<agent>`（monitor 每笔事务
        触发 `write_<agent>` → `sample()`）。模型的边界 bin 由 **verify 阶段**
        经 `inputs/yaml/uvm/env_cov_bins.yaml` 的 `field_bins` 注入那条通道
        （见 `src/executors/verify/main.py::_field_bins`），那里才是
        "模型声明的扫描点"真正变成 bin 的地方。

        本函数只落**声明**（`coverage_points.json`），供 workbench 那页与审计读；
        要一段独立可编译的 covergroup 文本走 `vplan` 执行资产。
        """
        # **统一判据**：与 verify 分解测试点用的是同一处解析 —— 两个读法会在
        # 同一个 run 里各拿一份模型（verify 认 config/、coverage 只认 inputs/），
        # 于是"分解出来的测试点"和"生成的覆盖点"来自两份不同的模型。
        from src.layers.l3_decision.vplan import engine

        project = engine.project_for(spec, output_dir)
        cov_dir = output_dir / "coverage"
        cov_dir.mkdir(parents=True, exist_ok=True)
        points: Dict[str, Any] = {}
        if project is not None:
            points = engine.run_covergroups(project, module_name)
        source = "vplan"

        if not points:
            # 退回 spec 骨架 —— 明说一句，别让人以为模型生效了。
            from src.executors.coverage.functional_coverage import (
                FunctionalCoveragePointGenerator)

            gen = FunctionalCoveragePointGenerator()
            legacy = gen.generate(spec, module_name)
            logger.info("没有可用的 VPlan 项目 —— 功能覆盖率退回 spec 骨架")
            return {**legacy, "source": "spec_fallback",
                    "notes": ["没读到 VPlan 执行资产 —— 覆盖点从 spec 骨架出，"
                              f"只含 feature 枚举 bin"]}

        # 声明落盘（workbench 那页与审计读这一份，不重算）。
        # **每次覆盖**：它是机器读的声明，不是给人改的产物 —— 留旧的反而对不上现场。
        (cov_dir / "coverage_points.json").write_text(
            json.dumps({**points, "module": module_name, "source": source},
                       ensure_ascii=False, indent=2),
            encoding="utf-8")
        logger.info(
            f"功能覆盖率点（来自 {source}）：{points.get('coverpoint_count')} 覆盖点 / "
            f"{points.get('bin_count')} bin / {points.get('cross_count')} cross → "
            f"coverage_points.json（bin 由 env_cov 承采，见 verify 的 field_bins）")
        return {**points, "source": source}

    @staticmethod
    def _extract_constraints(output_dir: Path) -> list:
        """从生成的 transaction 文件提取"限制性约束"（约束范围 < 信号全范围）。

        扫描 agents/*/*_transaction.sv：
          - rand bit [W-1:0] sig;             → 信号宽度
          - constraint ... {sig inside {[0:MAX]};} → 约束范围

        只有 MAX < 2^W - 1（约束真正限制了取值范围）才算限制性约束，
        这种约束会让高位 bit 的 toggle 必然未覆盖。
        """
        import re
        constraints = []
        try:
            agents_dir = output_dir / "agents"
            if not agents_dir.is_dir():
                agents_dir = output_dir / "sv" / "agents"
            if not agents_dir.exists():
                return constraints
            for tx_file in agents_dir.rglob("*_transaction.sv"):
                text = tx_file.read_text(encoding="utf-8", errors="replace")
                widths = {}
                for m in re.finditer(r"rand\s+bit\s*\[(\d+):0\]\s+(\w+)\s*;", text):
                    widths[m.group(2)] = int(m.group(1)) + 1
                for m in re.finditer(r"(\w+)\s+inside\s*\{\s*\[0:(\d+)\]", text):
                    sig, maxv = m.group(1), int(m.group(2))
                    w = widths.get(sig, 32)
                    if maxv < (1 << w) - 1:
                        constraints.append({"signal": sig, "width": w, "max": maxv})
        except Exception:
            pass
        return constraints
