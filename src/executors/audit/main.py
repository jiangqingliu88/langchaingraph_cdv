"""审计智能体 —— 质量审查 + 签核证据链"""
from typing import Dict, Any, List
import hashlib
import json
from pathlib import Path

from src.layers.l2_orchestration.executors.base import BaseExecutor, ExecutorResult
from src.layers.l2_orchestration.executors.registry import register_executor
import structlog

logger = structlog.get_logger()


def _read_constraint_status(output_dir: Path) -> Dict[str, Any]:
    """读 verify 写下的 `coverage/constraint_status.json`；读不到给空字典。

    **它比 `semantic_validations` 更可靠**：后者要等覆盖率阶段才拼出来，
    而回归失败时那个阶段会被跳过（见上面关于 caveat 的注释）。
    """
    try:
        doc = json.loads((output_dir / "coverage" / "constraint_status.json")
                         .read_text(encoding="utf-8", errors="replace"))
        return doc if isinstance(doc, dict) else {}
    except (OSError, ValueError):
        return {}


def _read_association_report(output_dir: Path) -> Dict[str, Any]:
    """读 verify 写下的 `coverage/association_report.json`；读不到给空字典。

    **读不到 = 这次没做关联校验**（老 run / verify 那一步失败了），
    于是 `hard_edge_broken` 取不到 → 不挂 caveat。那是"判不了"，不是"断了" ——
    与 `semantic_validations` 的 `None` 同一条纪律（见那里关于三态贬值的注释）。
    """
    try:
        doc = json.loads((output_dir / "coverage" / "association_report.json")
                         .read_text(encoding="utf-8", errors="replace"))
        return doc if isinstance(doc, dict) else {}
    except (OSError, ValueError):
        return {}


def _read_tp_matrix(output_dir: Path) -> Dict[str, Any]:
    """读覆盖率阶段写下的 `coverage/tp_matrix.json`；读不到给空字典。

    它是"每条测试点的覆盖仓有没有命中"的**逐条**结论。没有 = 这一轮没建
    TP IR 或没跑覆盖率 —— **判不了**，不挂 caveat（与上面两条同一纪律）。
    """
    try:
        doc = json.loads((output_dir / "coverage" / "tp_matrix.json")
                         .read_text(encoding="utf-8", errors="replace"))
        return doc if isinstance(doc, dict) else {}
    except (OSError, ValueError):
        return {}


def _sha256_file(path: Path) -> str:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return ""


def _read_json_file(path: Path) -> Dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        return doc if isinstance(doc, dict) else {}
    except (OSError, ValueError):
        return {}


def _rtl_version_hash(output_dir: Path) -> str:
    """RTL 目录内容哈希 —— 与 lineage 同一口径（排序后拼「文件名 + 文件哈希」）。"""
    files = sorted((output_dir / "rtl").glob("*.sv"))
    if not files:
        return ""
    h = hashlib.sha256()
    for f in files:
        h.update(f.name.encode("utf-8"))
        h.update(_sha256_file(f).encode("ascii"))
    return h.hexdigest()


def _build_signoff_evidence(output_dir: Path, signoff: Dict[str, Any],
                            tp: Dict[str, Any], sem: Dict[str, Any],
                            caveats: List[str]) -> Dict[str, Any]:
    """**可对外交换的签核证据包**（`signoff_evidence_v1`）。

    把散在各处的证据收成一份带 schema 的 JSON：任何工具都能读、能验、能 diff。
    这是"可复现 · 可审计 · 可治理"从内部自洽走向**可移植资产**的那一步。

    说清楚的边界：
      · `seed_diversity` 目前是 `None` —— 种子有没有真的改变激励分布**还没验**，
        `None` ≠ "已验证"，也 ≠ "没通过"；
      · `unreachable_justifications` 现在只列 `SUSPECT`（计划覆盖率里 0 命中），
        **不是**"已证明不可达"；模型声明不可达后才会升为 `JUSTIFIED`。
    """
    methodology = _read_json_file(output_dir / "coverage" / "methodology.json")
    plan = _read_json_file(output_dir / "sim" / "coverage" / "coverage_result.json")
    plan_cov = plan.get("plan_coverage") or {}
    rows = tp.get("rows") or []
    merged_stores = int(plan_cov.get("stores") or 0)

    # 观测型维度里 0 命中的仓 —— 证据是"跨 N 条合并用例库 0 命中"。
    # 这是**嫌疑**不是判决：没有模型声明的不可达理由，就不能把它从分母里拿掉。
    unreachable = []
    for row in rows:
        if not isinstance(row, dict) or row.get("status") != "UNOBSERVED":
            continue
        unreachable.append({
            "tp_id": row.get("tp_id"),
            "bin": f"{row.get('coverpoint')}.{row.get('bin')}",
            "kind": row.get("kind") or "observe",
            "status": "SUSPECT",
            "evidence": f"0 hits across {merged_stores} merged regression test stores"
                        if merged_stores else "no merged plan coverage",
            "note": "需要模型声明 `unreachable` 才能从覆盖率分母里剔除",
        })

    # caveat → 建议动作（**只给建议，不自动执行危险动作**）
    actions = []
    cpa = sem.get("constraint_policy_applied")
    if cpa is None:
        # 覆盖率阶段没跑 / 老 run：读 verify 直接写下的那份（与 audit 门禁同源）
        cpa = _read_constraint_status(output_dir).get("constraint_policy_applied")
    if cpa is False:
        actions.append({"action": "BACKFILL_CONSTRAINTS", "auto": False,
                        "reason": "部分策略仍是骨架：补 sequence realization / 协议参数"})
    if tp.get("missed"):
        actions.append({"action": "GENERATE_DIRECTED_TEST", "auto": False,
                        "reason": f"{len(tp.get('missed') or [])} 条测试点未命中："
                                  f"从 tp_matrix.missed[] 生成定向约束/用例"})
    if tp.get("unmapped"):
        actions.append({"action": "REGENERATE_COVERAGE_MODEL", "auto": True,
                        "reason": "测试点的覆盖仓在报告里找不到：模型与覆盖率模型漂了"})
    if sem.get("cg_dut_hit_gt_zero") is False:
        actions.append({"action": "CHECK_BIND_PROBE", "auto": False,
                        "reason": "cg_dut 零命中：检查 bind 探针 / config_db 句柄"})
    if sem.get("ucdb_nonzero_bins") is False:
        actions.append({"action": "RERUN_COVERAGE", "auto": True,
                        "reason": "ucdb 落了库但 bin 零命中"})

    llm_log = output_dir / "docs" / "llm_audit.jsonl"
    return {
        "schema": "signoff_evidence_v1",
        "run": output_dir.name,
        "rtl_version_hash": _rtl_version_hash(output_dir),
        "testpoint_ir_sha256": ((methodology.get("artifacts") or {})
                                .get("testpoints_yaml") or {}).get("sha256", ""),
        "framework": {"name": methodology.get("framework", ""),
                      "version": methodology.get("version", "")},
        "coverage": {
            "plan_pct": plan_cov.get("functional_pct"),
            "single_test_pct": plan_cov.get("single_test_pct"),
            "gate_pct": signoff.get("coverage"),
            "gate_passed": (signoff.get("gates") or {}).get("coverage_ok"),
            "merged_stores": merged_stores,
            "merged_ucdb": plan_cov.get("ucdb", ""),
        },
        "tp_matrix": {
            "counts": tp.get("counts") or {},
            "total": tp.get("total", 0),
            "drivable_pct": tp.get("drivable_pct", 0.0),
            "backdoor_pct": tp.get("backdoor_pct", 0.0),
            "missed_tp_ids": [r.get("tp_id") for r in (tp.get("missed") or [])
                              if isinstance(r, dict)],
        },
        # **未验证就写 null** —— 不冒充"已验证"。
        "seed_diversity": None,
        "no_test_success": "seed_diversity 尚未实现（种子是否改变激励分布未逐 bin 验证）",
        "semantic_validations": sem,
        "caveats": list(caveats),
        "caveat_actions": actions,
        "unreachable_justifications": unreachable,
        "llm_audit_digest": _sha256_file(llm_log),
        "verdict": signoff.get("verdict"),
        "signoff_status": signoff.get("signoff_status"),
    }


@register_executor("audit")
class AuditExecutor(BaseExecutor):
    """审计智能体 = 质量审查 + 签核报告"""

    task_type = "quality_review"
    consumes = ["regression", "coverage"]
    produces = None

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(
            role="audit", display_name="审计智能体",
            description="质量审查+签核证据链", config=config or {})

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
        regression = ctx.get("regression", {}) if hasattr(ctx, 'get') else {}
        coverage = ctx.get("coverage", {}) if hasattr(ctx, 'get') else {}
        if not isinstance(regression, dict):
            regression = {}
        if not isinstance(coverage, dict):
            coverage = {}

        # ── 质量审查（真实逻辑）──
        passed = regression.get("passed", 0)
        failed = regression.get("failed", 0)
        total = regression.get("total", 0)
        # **按口径取**（与闭环同一个来源）—— 门槛挂在哪个数上，必须与闭环盯的那个
        # 数一致；否则会出现"闭环在追功能覆盖率、审计在判代码覆盖率"这种错位。
        from src.layers.l2_orchestration.planning import pick_coverage_value
        _pick = pick_coverage_value(coverage)
        overall = _pick["value"]

        # ── 签核前置门禁（历史 bug：audit 永远 success=True，0% 覆盖率也"通过"）──
        # 任一门禁不满足 → NEEDS_FIX 且 success=False（失败响亮，禁止粉饰）
        gates = {}
        # G1: RTL 真实存在且通过 vlog 编译（无 RTL = 无签核对象）
        try:
            rtl_dir = output_dir / "rtl"
            rtl_files = sorted(rtl_dir.glob("*.sv")) if rtl_dir.exists() else []
            gates["rtl_present"] = len(rtl_files) > 0
            gates["rtl_files"] = [f.name for f in rtl_files][:20]
        except Exception:
            gates["rtl_present"] = False
            gates["rtl_files"] = []
        # G1b: RTL 顶层不是占位骨架（LLM 连线失败回退的确定性骨架无真实互连逻辑）
        try:
            _arch = ctx.get("design_arch", {}) if hasattr(ctx, "get") else {}
            gates["rtl_real"] = bool(gates["rtl_present"]) and not bool(
                (_arch if isinstance(_arch, dict) else {}).get("rtl_placeholder", False))
        except Exception:
            gates["rtl_real"] = bool(gates["rtl_present"])
        # G2: 回归真实执行且全过（total>0 且 failed==0）
        gates["regression_passed"] = failed == 0 and total > 0
        # G3: 覆盖率来自真实收集（>0 才算收集过；0 或缺失 = 没跑覆盖率）
        gates["coverage_collected"] = isinstance(overall, (int, float)) and overall > 0
        # G4: 参考模型是真实模型（禁止 a+b 模板占位模型通过签核）
        # ctx["model"] 已是 model_data（execution.py 的 ctx.update(data) 直接展开），
        # 历史读取层级错误（_model["model"]）导致占位模型被误判为真实。
        try:
            _model = ctx.get("model", {}) if hasattr(ctx, "get") else {}
            _model_data = _model if isinstance(_model, dict) else {}
            gates["model_real"] = not bool(_model_data.get("placeholder", False))
            gates["model_placeholder_reason"] = str(_model_data.get("placeholder_reason", ""))[:200]
        except Exception:
            gates["model_real"] = False
            gates["model_placeholder_reason"] = "无法读取模型状态"

        # 判定
        #
        # 门槛用**本次 run 的目标**（`ctx["target"]`，来自 `--target` / 配置），
        # 不是写死的 95。写死 95 的后果实测过：目标 80 的项目跑出 32.5%，
        # 判定当然还是 NEEDS_FIX —— 数字看着"有门槛"，其实门槛与实际目标无关，
        # 而闭环拿它当"动作失败"计数（见 runtime.py 的熔断那一段）。
        pass_rate_ok = gates["regression_passed"]
        try:
            _target = float(ctx.get("target") or 0) if hasattr(ctx, "get") else 0.0
        except (TypeError, ValueError):
            _target = 0.0
        # 目标没给（0/缺失）就不假装有门槛：如实说"判不了"，不让它静默通过
        coverage_ok = (isinstance(overall, (int, float)) and _target > 0
                       and overall >= _target)
        gates["target"] = _target
        gates["coverage_ok"] = bool(coverage_ok)
        hard_ok = bool(pass_rate_ok and coverage_ok and gates.get("rtl_real", False)
                       and gates["model_real"])

        # ── 软缺口（caveats）：硬门禁过了，但"绿得不够实在" ──
        #
        # 这一层回答的是「数字好看**不等于**量到了该量的东西」。此前这类中间态
        # 只散在日志与人的记忆里：约束生成了而策略体是空壳、ucdb 落库而 bin
        # 一个没命中、关联硬边断了 —— audit 全当没看见，`READY` 照发。
        #
        # **三态而不是两态**：`PASS_WITH_CAVEAT` 与 `NEEDS_FIX` 的处置完全不同 ——
        # 前者可以签、但要写清保留了哪些缺口；后者根本不能签。
        sem = ctx.get("semantic_validations", {}) if hasattr(ctx, "get") else {}
        if not isinstance(sem, dict):
            sem = {}
        #
        # **只有显式的 `False` 才算缺口**。`None` 是"判不了"（没跑覆盖率 /
        # 没生成约束模型），而"判不了"到处都是 —— 把它也算进来的话几乎每个 run
        # 都会挂上 caveat，三态就贬值成"反正总有一条"，没人再去看那几行。
        # 同一条纪律见 `_artifact_manifest`：读不到就什么都不放。
        caveats: List[str] = []
        # 约束有没有真在约束 —— **优先读 verify 直接写下的那份**，`semantic_validations`
        # 里那份当补充。
        #
        # 为什么不能只靠 `semantic_validations`：它是**覆盖率阶段**拼进
        # `coverage_result.json` 的，而回归失败时闭环会**跳过 coverage**
        # （"功能回归 N 失败 → 跳过 coverage，进入 debug 修复"）。那种 run 里
        # `semantic_validations` 恒为 `{}`，于是"`env/cons/` 生成了但 11 条策略
        # 全是空壳"这件事在签核报告里**一个字都没有** —— 实测跑出来的就是这个。
        # 而 `constraint_status.json` 是 verify 写的，无论跑没跑覆盖率都在。
        _cpa = sem.get("constraint_policy_applied")
        if _cpa is None:
            _st = _read_constraint_status(output_dir)
            if _st.get("constraint_generated") is True:
                _cpa = _st.get("constraint_policy_applied")
        if _cpa is False:
            _st = _read_constraint_status(output_dir)
            _backed = _st.get("backed_policy_count")
            _total = _st.get("policy_count")
            if isinstance(_backed, int) and isinstance(_total, int) and _total > 0:
                caveats.append(
                    f"约束只部分生效：{_backed}/{_total} 条策略由模型编译出真实赋值，"
                    f"其余 {_st.get('unbacked_policy_count', _total - _backed)} 条仍是"
                    f"空骨架（维度不可驱动，没有 `stimulus.field`）—— "
                    f"见 coverage/constraint_status.json")
            else:
                caveats.append(
                    "约束未激活：策略体的 apply() 落在 `default:` 分支、不做任何事"
                    "（`env/cons/` 生成了但约束不约束东西）")
        if sem.get("ucdb_nonzero_bins") is False:
            caveats.append("覆盖率库落了但**一个 bin 都没命中** —— 覆盖率的数字没有意义")
        if sem.get("cg_dut_hit_gt_zero") is False:
            caveats.append("`cg_dut` 零命中 —— DUT 探针可能没挂上，内部状态/输出端口没采到")
        # 关联硬边断（`associate` 的 ① ②）—— 覆盖率与 case 模型对不上，
        # 那意味着"声明要测的"与"实际在量的"是两回事。
        #
        # **读文件而不是读 ctx**：那份报告由 verify 写在
        # `<run>/coverage/association_report.json`，而审计拿得到 run 目录 ——
        # 为一个旁路产物专门加一条穿过 24 个节点的 ctx 键，不划算。
        assoc = _read_association_report(output_dir)
        if assoc.get("hard_edge_broken"):
            caveats.append(
                f"三模型关联硬边断了 {assoc['hard_edge_broken']} 条"
                f"（声明的测试点没落成覆盖仓）—— 见 coverage/association_report.json")

        # ── 测试点矩阵：**签核按测试点说话，不按百分比说话** ──
        #
        # 功能覆盖率 70% 只说明"有 30% 的仓没中"，但它不说"缺的是哪一条、
        # 属于谁、是不是根本不可激励"。矩阵把缺口归因到 `tp_id` 与需求编号。
        tp = _read_tp_matrix(output_dir)
        tp_summary: Dict[str, Any] = {}
        if tp:
            tp_summary = {
                "total": tp.get("total", 0),
                "drivable": tp.get("drivable", 0),
                "drivable_hit": tp.get("drivable_hit", 0),
                "drivable_pct": tp.get("drivable_pct", 0.0),
                # **后门到达单独一栏**：force 内部状态采到的覆盖，不算激励覆盖。
                "backdoor": tp.get("backdoor", 0),
                "backdoor_hit": tp.get("backdoor_hit", 0),
                "backdoor_pct": tp.get("backdoor_pct", 0.0),
                # **观测型不是缺口**：它们没有输入引脚，命中与否是"状态到没到"，
                # 单独一栏，不混进可激励覆盖率。
                "observe_only": tp.get("observe_only", 0),
                "observed": tp.get("observed", 0),
                "missed": len(tp.get("missed") or []),
                "unmapped": len(tp.get("unmapped") or []),
            }
            if tp_summary["unmapped"]:
                caveats.append(
                    f"{tp_summary['unmapped']} 条测试点的覆盖仓在报告里找不到"
                    f"（模型与生成的覆盖率模型漂了）—— 见 coverage/tp_matrix.json")
            if sem.get("testpoints_traced") is False and not tp_summary["unmapped"]:
                caveats.append(
                    "测试点与覆盖仓的对应关系不完整 —— 见 coverage/tp_matrix.json")
            if tp_summary["missed"]:
                caveats.append(
                    f"{tp_summary['missed']} 条测试点的仓未命中"
                    f"（可激励 {tp_summary['drivable_hit']}/{tp_summary['drivable']}，"
                    f"{tp_summary['drivable_pct']}%；后门 "
                    f"{tp_summary.get('backdoor_hit', 0)}/{tp_summary.get('backdoor', 0)}；"
                    f"观测型 {tp_summary['observed']}/{tp_summary['observe_only']}）"
                    f"—— 逐条见 coverage/tp_matrix.json")

        if not hard_ok:
            verdict = "NEEDS_FIX"
        elif caveats:
            verdict = "PASS_WITH_CAVEAT"
        else:
            verdict = "READY"

        # ── 签核报告（证据链）──
        #
        # **两个覆盖率都写进去，并标出哪个是本次判定的口径**。只留一个数的话，
        # 读报告的人分不清"32.5%"是代码覆盖率还是功能覆盖率 —— 而这两个数在
        # 同一份 run 里可以差一倍（32.5% vs 64.81%），"差在哪"正是要回答的问题。
        signoff = {
            "verdict": verdict,
            "pass_rate": f"{passed}/{total}",
            "coverage": overall,
            "coverage_metric": _pick["metric"],
            "coverage_detail": {
                "metric": _pick["metric"],
                "target": gates.get("target"),
                "functional_pct": coverage.get("functional_pct"),
                "code_overall_pct": coverage.get("overall_pct"),
                "code_metrics_present": coverage.get("metrics_present"),
                "code_metrics_absent": coverage.get("metrics_absent"),
            },
            "gates": gates,
            # **软缺口**：硬门禁全过、但"绿得不够实在"的地方。空列表 = 没有。
            # 与 `gates` 分开：门禁是"能不能签"，这是"签的时候要写清什么"。
            "caveats": caveats,
            "semantic_validations": sem,
            # 测试点维度的签核口径：**可激励 / 已命中 / 只能观测** 三栏分开。
            # 空字典 = 这一轮没有 TP IR（老 run / 没建模），不是"测试点全过"。
            "testpoints": tp_summary,
            "summary": {
                "total_tests": total, "passed": passed, "failed": failed,
                "overall_coverage": overall,
                "coverage_metric": _pick["metric"],
                "functional_coverage": coverage.get("functional_pct"),
                "code_coverage": coverage.get("overall_pct"),
                "rtl_present": gates["rtl_present"],
                "coverage_collected": gates["coverage_collected"],
                "caveat_count": len(caveats),
                "testpoint_count": tp_summary.get("total", 0),
                "testpoint_missed": tp_summary.get("missed", 0),
            },
            # 三态 → 签核状态。**`NEEDS_FIX` 原来是 CONDITIONAL，这是错的** ——
            # "有条件通过"读起来像"可以签了、带着条件"，而 NEEDS_FIX 是
            # "根本不能签"。把两件事标成同一个词，报告读起来会误导。
            "signoff_status": {"READY": "APPROVED",
                               "PASS_WITH_CAVEAT": "CONDITIONAL",
                               "NEEDS_FIX": "REJECTED"}[verdict],
        }

        # ── 可交换签核证据包（signoff_evidence_v1）──
        #
        # 与 report.json 并存：report 是人读的签核报告；evidence 是**带 schema、
        # 可被任何工具读取/校验/diff** 的证据包。`dump` 会把它一起打包。
        output_dir.mkdir(parents=True, exist_ok=True)
        try:
            evidence = _build_signoff_evidence(output_dir, signoff, tp, sem, caveats)
            ev_path = output_dir / "signoff_evidence.json"
            ev_path.write_text(json.dumps(evidence, indent=2, ensure_ascii=False),
                               encoding="utf-8")
            signoff["signoff_evidence"] = {
                "schema": evidence["schema"],
                "path": str(ev_path),
                "sha256": _sha256_file(ev_path),
            }
        except Exception as e:                         # noqa: BLE001 证据包别拦签核
            logger.warning(f"签核证据包写入失败: {e}")

        # 写签核报告
        report_path = output_dir / "report.json"
        try:
            report_path.write_text(json.dumps(signoff, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            logger.warning(f"签核报告写入失败: {e}")

        score = 80 if verdict == "READY" else 40
        # 说真话：门禁不满足 → 如实失败（success=False），不再无条件"通过"
        return ExecutorResult(success=(verdict == "READY"), data={"report": signoff, "score": score})
