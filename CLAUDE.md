# SignOffAI — contributor and AI-assistant guide

This is a short orientation for contributors and coding assistants.
[`ARCHITECTURE.md`](ARCHITECTURE.md) is the authoritative description of the
current code architecture; keep it in sync when layer boundaries or graph nodes
change. [`README.md`](README.md) covers usage; [`CONTRIBUTING.md`](CONTRIBUTING.md)
covers the development workflow.

## Ground rules

1. **EDA is the source of truth.** Never report a compile/simulation/coverage
   stage as passed without tool evidence. "No log" is not "no error"; missing
   EDA tools must surface as `BLOCKED_EDA_MISSING` or `EDA_MISSING`.
2. **Keep the five-layer dependency direction.** Run
   `python -m config.architecture_guard` after structural changes. Do not hide
   violations behind function-local imports.
3. **LLMs are called at specific points, not as the orchestrator.** All model
   calls go through `src/tools/common/lib/llm_call.py:call_llm`; process control,
   routing, and pass/fail decisions stay deterministic.
4. **Behavior changes need tests.** A bug fix needs a regression test that fails
   before the fix.
5. **Never commit secrets or generated artifacts.** `.env`, `.jwt_secret`,
   `output*/`, `work/`, `*.ucdb`, `*.qpg`, and `*.log` are ignored.
6. **VPlan statuses are evidence-driven.** `planned` ≠ `covered` and
   `assume` ≠ `active`. A `vplan` build is `PLAN_ONLY`: it writes TP/Case/contract
   IR but no EDA evidence, so it is not signable. Never promote a contract by
   editing CSV status alone.
7. **LLM-extracted VPlan tables need human review before execution.**
   `docs/specs/*`, `data/*`, and `cases/*` are bootstrapped by an LLM; a wrong
   module/interface table poisons RTL, UVM, regression, and coverage. Record a
   review with `vplan review <project> --by <name>` (binds file hashes).
   `vplan execute` and `vplan gate --apply` refuse unreviewed or stale projects;
   `--allow-unreviewed` is a logged dev-only escape hatch.

## Common commands

```bash
pip install -e ".[dev]"          # add ",gui" for the PySide6 workbench
pytest tests/ -q
pytest src/tools/checking src/tools/humanview \
       src/layers/l3_decision/contract/tests \
       src/layers/l3_decision/vplan -q
python -m config.architecture_guard
ruff check src/ tests/ && ruff format --check src/ tests/
python -m src.cli.commands --help

# VPlan planning layer (spec-first project, no case-model YAML)
python -m src.cli.commands vplan status specs/npu_sched
python -m src.cli.commands vplan review specs/npu_sched --by <name>   # 人工审阅门：绑定 docs/specs/data/cases 哈希
python -m src.cli.commands vplan review specs/npu_sched --check       # 未审阅/过期时退出码 1（CI）
python -m src.cli.commands vplan build  specs/npu_sched -o output_vplan_npu_sched
python -m src.cli.commands verify       specs/npu_sched -o output_vplan_npu_sched
#   A bare project (only `cmdsched.md` at the root) is bootstrapped by front:
#   spec -> dplan contract + six VPlan tables -> docs/specs/*.csv + data/*.csv
#   + cases/*.yaml, then format/reference validation. `--rebootstrap` overwrites
#   those draft tables; it never marks them active.

# VPlan execution layer: project -> inputs/vplan/ -> verify kernel (EDA required)
# UVM assets: <run>/sv/ is the only layout; top-level agents/env/bench are removed
python -m src.cli.commands vplan execute specs/npu_sched --dry-run
python -m src.cli.commands vplan execute specs/npu_sched -o output_vplan_npu_sched --max-rounds 1 --sim-mode cov
#   默认拒绝未审阅/已过期的项目；开发调试可显式 `--allow-unreviewed`（记 warning）
#   sv/ is produced during verify (default); SIGNOFFAI_UVM_LAYOUT=legacy disables it
python -m src.cli.commands vplan package-assets <run>   # re-materialise sv/ for existing runs
python -m src.cli.commands vplan execute ... --keep-legacy   # keep top-level dirs (default: removed)
python -m src.cli.commands vplan scan-assets <run> --check
python -m src.cli.commands vplan link specs/npu_sched <run>
python -m src.cli.commands vplan gate specs/npu_sched [--apply]
```

## Layout reminders

- `src/executors/` — eight stage executors; only `design` and `debug` call an LLM directly.
- `src/layers/l1_infrastructure/` — deterministic, zero-AI layer; must not import upward.
- `src/layers/l2_orchestration/` — LangGraph graph, routers, nodes, governance, evidence;
  `supervisor/` is the default Supervisor main graph + design/execution subgraphs,
  `graph.py` keeps the legacy 24-node single graph for rollback
  (`SIGNOFFAI_SUPERVISOR=off`).
- `src/layers/l3_decision/` — coverage-driven decisions, case models, test-point IR;
  `l3_decision/vplan/` loads `specs/<module>/docs/specs/*.csv` + `data/contract_matrix`
  and projects them into the kernel (planning/contract layer only).
  `l3_decision/dplan.py` aligns the design/model contract (dplan) with VPlan;
  run 输入落在 `<run>/inputs/dplan/`（CSV/HTML/MD 为主，JSON 只作机器 sidecar）。
- `src/layers/l4_memory/` — persistence and IP/case/debug knowledge bases.
- `src/layers/l5_evolution/` — experience distillation and policy weights.
- `src/tools/` — domain tools grouped by generation / checking / humanview / common
  (regression lives in `src/layers/l2_orchestration/regression_tools/`).
- `src/cli/` — the `vagent` entry point; `src/workbench/` — optional desktop UI.

## Environment

Start from [`.env.example`](.env.example). Without an LLM key, deterministic
paths still run and LLM steps fail honestly. QuestaSim is optional for unit
tests; end-to-end coverage flows require it.
