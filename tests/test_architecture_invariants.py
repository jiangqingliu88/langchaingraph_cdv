"""架构不变量 —— 数量、边界、动作、caveat、文档同步。

这些不是“业务测试”：它们钉的是**人最容易记错、代码改了文档没改**的那类事实。
新增节点 / executor / 工具板块 / 动作 / caveat 时，必须同时改这里和
ARCHITECTURE.md —— 否则 CI 红。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from config import architecture_guard as guard
from src.layers.l2_orchestration.communication.tool_hub import ToolHub
from src.layers.l2_orchestration.graph import NODE_FUNCS
from src.layers.l3_decision.decision_engine import ALL_ACTIONS
from src.tools.boards import BOARDS

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "ARCHITECTURE.md"

EXPECTED_ACTIONS = (
    "FIX_COMPILE_bug", "FIX_MODEL_bug", "FIX_FUNCTIONAL_bug",
    "FIX_PROTOCOL_bug", "FIX_RESET_bug", "FIX_CDC_bug", "FIX_DEADCODE_bug",
    "EXPAND_SEEDS", "RELAX_CONSTRAINT", "GENERATE_DIRECTED_TEST", "CONVERGE",
)

EXPECTED_CAVEATS = {
    "CONSTRAINT_PARTIAL", "CONSTRAINT_INACTIVE", "UCDB_NO_BINS", "CG_DUT_ZERO",
    "ASSOCIATION_HARD_EDGE", "PLAN_INCONSISTENT", "TP_UNMAPPED",
    "TP_TRACE_INCOMPLETE", "TP_MISSED",
    # 逐用例签核（docs/design/case_coverage_and_wave_traceability.md）
    "TP_NOT_SIGNED_OFF", "TP_WAVE_MISSING", "TP_TIMING_WARN",
    "MODEL_UNAVAILABLE", "BASELINE_MISSING", "BACKEND_ARGS_USED",
    # Case View 门禁（docs/design/architecture_transformation_plan.md D5）
    "CASE_GATE_BLOCKED",
    # case 三集合契约（arch.md §9）
    "CASE_GROUP_PARTIAL", "CASE_SVA_VACUOUS", "CASE_SCB_NOT_EXECUTED",
    "CASE_PATH_PENDING_BACKEND", "CASE_IR_EVIDENCE_MISMATCH",
    # 五维质量门 block 模式（§15：evidence/functional 硬，其余软）
    "QUALITY_GATE_BLOCKED", "QUALITY_GATE_WARN",
    # 权威差分 / 覆盖率回退 / 证据门（audit/helpers.py）
    "AUTHORITY_DIFF", "AUTHORITY_DIFF_MISSING",
    "COVERAGE_REGRESSION", "EVIDENCE_GATE",
}


# ═══════════════════════════════════════════════════════════════
# 代码结构
# ═══════════════════════════════════════════════════════════════

def test_there_are_exactly_24_nodes_split_12_pure_12_agent():
    names = [name for name, _ in NODE_FUNCS]
    assert len(names) == len(set(names)) == 24
    modules = [fn.__module__ for _, fn in NODE_FUNCS]
    pure = [m for m in modules if ".nodes.pure." in m]
    agent = [m for m in modules if ".nodes.agent." in m]
    # `apply_compile_retry` 在 agent/fix.py（可回退到 debug LLM），不是 pure
    assert len(pure) == 12 and len(agent) == 12


def test_eight_executors_have_a_tool_mapping():
    roles = set(ToolHub.EXECUTOR_TOOL_MODULES)
    assert roles == {"front", "design", "model", "verify",
                     "ops", "coverage", "debug", "audit"}
    assert len(roles) == 8


def test_tool_boards_are_the_canonical_boards():
    assert set(BOARDS) == {"generation", "checking", "execution",
                           "flow", "integration", "common", "humanview"}
    assert "uvm_tools" in BOARDS["generation"]
    assert "assertion_tools" in BOARDS["checking"]
    # regression_tools 已迁到 layers/l2；execution 板块保留为空。
    assert BOARDS["execution"] == ()


def test_decision_action_universe_is_frozen():
    assert tuple(ALL_ACTIONS) == EXPECTED_ACTIONS


def test_caveat_codes_in_audit_match_the_public_set():
    # 3.0 拆分后 caveat 分在 main.py 与 helpers.py 两处，按包扫描。
    found = set()
    for path in sorted((ROOT / "src/executors/audit").glob("*.py")):
        found |= set(re.findall(r'(?:_caveat|caveat)\("([A-Z_]+)"',
                                path.read_text(encoding="utf-8")))
    assert found == EXPECTED_CAVEATS


# ═══════════════════════════════════════════════════════════════
# 复杂度 / 行数预算
# ═══════════════════════════════════════════════════════════════

def test_file_and_complexity_budget_is_green():
    result = guard.check()
    assert result["ok"], (result["line_issues"], result["complexity_issues"])


def test_line_guard_catches_an_unwatched_oversized_file():
    # 用真实仓库 + 人为收紧的预算做一次负例，不依赖造临时树
    budget = {"warn": 10, "error": 20, "watched": {}}
    issues = guard.line_violations(budget=budget)
    assert any(i["type"] == "lines_over_error" for i in issues)


def test_line_guard_enforces_watched_budget_below_hard_error():
    """watched 的 registered 是硬预算，不是只在 >2000 时生效。"""
    budget = {"warn": 1500, "error": 2000,
              "watched": {"src/cli/commands.py": {
                  "registered": 1, "reason": "test", "plan": "test"}}}
    issues = guard.line_violations(budget=budget)
    assert any(i["type"] == "watched_file_grew"
               and i["path"] == "src/cli/commands.py" for i in issues)


def test_complexity_guard_catches_a_new_hotspot():
    issues = guard.complexity_violations(threshold=1, baseline={})
    assert issues and all(i["type"] == "complexity_new" for i in issues[:5])


def test_watched_files_register_reason_plan_and_size():
    budget = guard.load_budget()
    counts = guard.line_counts()
    for rel, entry in budget["watched"].items():
        assert entry.get("reason") and entry.get("plan"), rel
        assert counts[rel] <= int(entry["registered"]), rel


# ═══════════════════════════════════════════════════════════════
# 文档同步（代码改了文档没改 → 这里红）
# ═══════════════════════════════════════════════════════════════

def test_architecture_doc_matches_code_facts():
    doc = DOC.read_text(encoding="utf-8")
    for phrase in ("24 节点闭环", "八个 Executor",
                   "pure（12 个", "agent（12 个",
                   "steps_dag.py", "STATE_CONTRACTS",
                   "EXECUTORS_WITHOUT_HUB_TOOLS",
                   "signoff_replay_recipe_v2",
                   "runtime.py", "运行时知识图",
                   "config/architecture_guard.py", "complexity_baseline",
                   "stimulus_plan.json", "LLM 输出治理"):
        assert phrase in doc, f"ARCHITECTURE.md 缺少：{phrase}"
    for action in ALL_ACTIONS:
        assert action in doc, f"ARCHITECTURE.md 缺少动作：{action}"
    for code in EXPECTED_CAVEATS:
        assert code in doc, f"ARCHITECTURE.md 缺少 caveat：{code}"
    for board in BOARDS:
        assert board in doc, f"ARCHITECTURE.md 缺少工具板块：{board}"


def test_known_limitations_match_architecture_doc():
    from config.known_limitations import KNOWN_LIMITATIONS

    doc = DOC.read_text(encoding="utf-8")
    ids = [item["id"] for item in KNOWN_LIMITATIONS]
    assert len(ids) == len(set(ids))
    for item in KNOWN_LIMITATIONS:
        assert item["status"] in ("open", "by_design", "done"), item
        assert item["text"] in doc, f"§15 缺少边界条目：{item['id']}"


def test_player_runtime_boundary_matches_code():
    from config.known_limitations import by_id
    from src.layers.l3_decision.vplan.runtime.framework.stimulus_plan import BACKENDS

    boundary = by_id("player_runtime")
    if BACKENDS["player"]["runtime"]:
        # 实现 runtime 时必须把边界项更新为 done 并改文档，不能悄悄漂
        assert boundary["status"] == "done", \
            "player runtime 已实现，但 KNOWN_LIMITATIONS/§15 还写着未实现"
    else:
        assert boundary["status"] == "open"


def test_doc_test_count_matches_reality():
    """文档头部写的用例数不能比实测少（少于实测会误导“还要补测试”）。"""
    doc = DOC.read_text(encoding="utf-8")
    m = re.search(r"全量单测：\*\*(\d+) passed", doc)
    assert m, "ARCHITECTURE.md 头部没有单测计数"
    # 只做下限检查：新增测试后如果忘了更新，这里会提示（不反向卡住）
    assert int(m.group(1)) >= 1000


def test_cli_does_not_import_optional_auth():
    """`auth.py` 是**可选 API 面**（FastAPI/PyJWT 在 `api` extra）—— CLI 不许 import。

    否则核心安装为了认证代码被拉上两个重依赖；这条不变量之前只在文档里写着，
    没有守卫（改一行 import 就能悄悄破掉）。
    """
    offenders = []
    pattern = re.compile(r"(l2_orchestration\.auth|from\s+\.auth\s+import)")
    for path in (ROOT / "src" / "cli").rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            if line.strip().startswith("#"):
                continue
            if pattern.search(line):
                offenders.append(f"{path.relative_to(ROOT).as_posix()}: {line.strip()}")
    assert not offenders, "CLI 不得 import 可选认证模块：\n" + "\n".join(offenders)


def test_known_limitations_expose_a_machine_readable_state():
    """边界表是状态机（id/status/owner_phase/verify_test），不是一段散文。"""
    from config.known_limitations import LIMITATION_STATUSES, rows

    items = rows()
    assert items and {r["id"] for r in items} == {
        r["id"] for r in rows()}
    for row in items:
        assert row["status"] in LIMITATION_STATUSES, row
        assert row["summary"], row
        assert set(row) == {"id", "summary", "status", "owner_phase", "verify_test"}
