# Contributing to SignOffAI

[简体中文](#贡献指南)

Thanks for your interest in SignOffAI. This document describes the development
workflow, coding conventions, and review process. By participating, you agree to
follow our [Code of Conduct](CODE_OF_CONDUCT.md).

## Ways to contribute

- Report bugs and propose features through GitHub Issues (use the templates).
- Improve documentation, examples, and test coverage.
- Submit pull requests for bug fixes or well-scoped features.
- Report security vulnerabilities privately — see [SECURITY.md](SECURITY.md).

## Development setup

```bash
# Python 3.10–3.12
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -e ".[dev]"           # add ",gui" for the PySide6 workbench

cp .env.example .env              # then fill in your own API key
```

`QuestaSim` is optional. Unit tests run without EDA tools; end-to-end simulation
and coverage tests require a local Questa installation and are skipped otherwise.

## Before opening a pull request

```bash
ruff check src/ tests/            # lint
ruff format --check src/ tests/   # formatting
pytest tests/ -q                  # core suite
pytest src/tools/checking src/tools/humanview \
       src/layers/l3_decision/contract/tests \
       tests/test_vplan_integration.py tests/test_vplan_bootstrap.py -q
python -m config.architecture_guard   # layer-direction invariants
```

For GUI changes, also run `pytest src/workbench/tests -q` with
`QT_QPA_PLATFORM=offscreen` on headless machines.

## Coding conventions

- Follow the existing style: type hints where practical, concise docstrings, and
  Chinese comments only where the surrounding module already uses them.
- Keep the five-layer dependency direction intact. Run the architecture guard;
  do not silence it by moving imports inside functions.
- New behavior needs a test. A bug fix needs a regression test that fails before
  the fix.
- Do not commit generated artifacts (`output*/`, `work/`, `*.ucdb`, `*.qpg`,
  `*.log`) or secrets (`.env`, `.jwt_secret`). The `.gitignore` covers these.

## Commit messages

Use [Conventional Commits](https://www.conventionalcommits.org/):

```
feat(scope): add a capability
fix(scope): correct a defect
docs: update documentation
refactor(scope): restructure without behavior change
test(scope): add or fix tests
chore: maintenance
```

All commits must be signed off under the
[Developer Certificate of Origin 1.1](https://developercertificate.org/):

```bash
git commit -s -m "feat(verify): ..."
```

## Pull request process

1. Fork the repository and create a topic branch from `main`.
2. Keep the change focused; split unrelated work into separate PRs.
3. Fill in the PR template, link related issues, and describe how you tested it.
4. CI must pass (lint, unit, package, workbench, integration jobs).
5. A maintainer reviews and merges. Do not force-push after review starts.

## License

By contributing, you agree that your contributions are licensed under the
Apache License 2.0, as described in [LICENSE](LICENSE).

---

## 贡献指南

感谢你对 SignOffAI 的关注。参与本项目即表示你同意遵守
[行为准则](CODE_OF_CONDUCT.md)。

### 开发环境

```bash
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -e ".[dev]"           # 需要桌面工作台再加 ",gui"
cp .env.example .env              # 填入你自己的 API Key
```

QuestaSim 可选：单元测试不需要 EDA 工具；端到端仿真与覆盖率测试需要本地
Questa，否则会跳过。

### 提交前自检

```bash
ruff check src/ tests/
ruff format --check src/ tests/
pytest tests/ -q
python -m config.architecture_guard
```

### 约定

- 保持五层依赖方向不变，架构守卫必须通过；不要用函数内延迟 import 绕过。
- 新增行为要有测试；修复 bug 要有能复现该 bug 的回归测试。
- 不要提交生成产物（`output*/`、`work/`、`*.ucdb`、`*.qpg`、`*.log`）或密钥
  （`.env`、`.jwt_secret`）。
- 提交信息遵循 Conventional Commits，并使用 `git commit -s` 签署 DCO。
- 提交 PR 前请先同步 `main`，保持改动聚焦，填写 PR 模板并说明测试方式。
