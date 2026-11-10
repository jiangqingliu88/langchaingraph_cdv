# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [2.0.0] - 2026-11-10

### Changed

- VPlan spec-first planning layer: `docs/specs/*.csv` + `data/contract_matrix/*.csv`
  + `cases/*.yaml`, human review gate, `PLAN_ONLY` build, execution bridge and
  evidence-driven `vplan gate`.
- UVM assets now use the `<run>/sv/` layout (legacy top-level layout is opt-in).
- ISA stimulus path replaced the declarative random generator with
  `isa_ir_tools` (IR → tensors → seq.ir → commands) and a standalone TB player.
- Tool boards / docs / tests reconciled with the current directory layout.

### Fixed

- Architecture guard now enforces watched-file registered budgets.
- VPlan gate selects the latest linked run and reports active drift.
- Contract matrix schema validates the 13 columns and status enum; writes are atomic.
- VPlan TP can bind explicit stimulus fields; `uvm_arch` scoreboards map via
  `check_artifact`/`object` where declared.
- Secret scan (`scripts/check_secrets.py`) and cleaned `TODO.md`.
- Main suite 1176 passed / 4 skipped; workbench 692 passed.

## [1.0.0] - 2026-11-05

Initial public release.

### Added

- **LangGraph closed-loop orchestration** — 24-node verification graph built on a
  five-layer engine (L1 infrastructure, L2 orchestration, L3 decision,
  L4 memory, L5 evolution).
- **Eight stage executors** covering spec intake, design, reference models,
  verification, operations, coverage, debug, and audit/sign-off.
- **Test-point IR methodology** — case models decomposed into a stable
  `tp_id` axis that drives stimulus, constraints, coverage, regression, and
  sign-off.
- **UVM generation pipeline** — interface, loopback environments, drivers,
  monitors, sequencers, scoreboards, and tests generated from templates.
- **Regression framework** — Questa-based staged regression (p0–p3), coverage
  merging/archiving, and human approval gates.
- **Evidence chain v2** — contract-level sign-off evidence with manifests,
  hashes, and an auditable governance loop.
- **NPU ISA stimulus generator** — scenario DSL → ISA transaction IR → binary
  encoding and tensor data.
- **PySide6 workbench** (optional) for regression waveforms, coverage, test
  points, and sign-off review.
- Open-source project scaffolding: Apache-2.0 license, contribution guide,
  code of conduct, security policy, issue/PR templates, and CI.

[Unreleased]: https://github.com/jiangqingliu88/langchaingraph_cdv/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/jiangqingliu88/langchaingraph_cdv/releases/tag/v1.0.0
