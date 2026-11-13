"""Architecture Guard 2.0 —— 单向债务偿还的回归测试。"""
from __future__ import annotations

import json

import pytest
import yaml

from config import architecture_guard as guard


def _tree(root, rel, lines=None, text=None):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if text is None:
        text = "\n".join(f"x{i} = {i}" for i in range(lines)) + "\n"
    path.write_text(text, encoding="utf-8")
    return path


def _budget(path, watched=None, warn=1500, error=2000):
    doc = {"line_budget": {"warn": warn, "error": error},
           "watched": watched or {}}
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return path


def _baseline(path, data):
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path


# ── size budget ─────────────────────────────────────────────────

def test_custom_root_is_scanned(tmp_path):
    _tree(tmp_path, "src/engine_plane/a.py", lines=3)
    counts = guard.line_counts(tmp_path)
    assert "src/engine_plane/a.py" in counts
    assert counts["src/engine_plane/a.py"] == 3


def test_watched_file_shrink_must_tighten(tmp_path):
    _tree(tmp_path, "src/a.py", lines=1400)
    budget = {"warn": 1500, "error": 2000,
              "watched": {"src/a.py": {"registered": 1800, "reason": "r",
                                       "plan": "p"}}}
    issues = guard.line_violations(tmp_path, budget)
    assert any(i["type"] == "budget_not_tightened" for i in issues)


def test_watched_file_growth_fails(tmp_path):
    _tree(tmp_path, "src/a.py", lines=1500)
    budget = {"warn": 1500, "error": 2000,
              "watched": {"src/a.py": {"registered": 1400, "reason": "r",
                                       "plan": "p"}}}
    issues = guard.line_violations(tmp_path, budget)
    assert any(i["type"] == "watched_file_grew" for i in issues)


def test_reduce_debt_lowers_size_budget_and_records_history(tmp_path):
    _tree(tmp_path, "src/a.py", lines=100)
    budget_path = _budget(tmp_path / "budget.yaml",
                          {"src/a.py": {"registered": 200, "reason": "r",
                                        "plan": "p"}})
    baseline_path = _baseline(tmp_path / "baseline.json", {})
    history = tmp_path / "history.jsonl"
    rows = guard.reduce_debt(tmp_path, budget_path, baseline_path, history)
    assert rows and rows[0]["old"] == 200 and rows[0]["new"] == 100
    assert yaml.safe_load(budget_path.read_text(encoding="utf-8"))[
        "watched"]["src/a.py"]["registered"] == 100
    assert history.read_text(encoding="utf-8").strip()


# ── complexity budget ───────────────────────────────────────────

def _func(tmp_path, name="f", body="if x:\n    pass", prefix=""):
    text = f"{prefix}def {name}():\n" + "\n".join(
        "    " + line for line in body.splitlines()) + "\n"
    return text


def test_complexity_growth_and_repayment(tmp_path):
    _tree(tmp_path, "src/a.py", text=_func(
        tmp_path, "f", "\n".join(["if x:", "    pass"] * 30)))
    base = guard.complexity_map(tmp_path)
    key = "src/a.py::f"
    assert base[key] > 20
    grown = guard.complexity_violations(tmp_path, baseline={key: base[key] - 1})
    assert any(i["type"] == "complexity_grew" for i in grown)
    repaid = guard.complexity_violations(tmp_path, baseline={key: base[key] + 5})
    assert any(i["type"] == "debt_repaid" for i in repaid)


def test_complexity_cleared_must_be_removed(tmp_path):
    _tree(tmp_path, "src/a.py", text=_func(tmp_path, "f", "if x:\n    pass"))
    key = "src/a.py::f"
    issues = guard.complexity_violations(tmp_path, baseline={key: 30})
    assert any(i["type"] == "debt_cleared" for i in issues)


def test_new_complexity_debt_requires_approval(tmp_path):
    body = "\n".join(["if x:", "    pass"] * 21)
    _tree(tmp_path, "src/a.py", text=_func(tmp_path, "f", body))
    issues = guard.complexity_violations(tmp_path, baseline={})
    assert any(i["type"] == "complexity_new" for i in issues)


def test_nested_function_is_counted_independently(tmp_path):
    text = (
        "def outer():\n"
        "    if a:\n"
        "        pass\n"
        "    def inner():\n"
        + "".join("        if x:\n            pass\n" for _ in range(4))
    )
    _tree(tmp_path, "src/a.py", text=text)
    m = guard.complexity_map(tmp_path)
    assert m["src/a.py::outer"] == 2
    assert m["src/a.py::outer.inner"] == 5


def test_same_name_methods_have_distinct_identity(tmp_path):
    text = (
        "class A:\n"
        "    def run(self):\n"
        "        if x:\n            pass\n"
        "class B:\n"
        "    def run(self):\n"
        "        if x:\n            pass\n"
        "        if y:\n            pass\n"
    )
    _tree(tmp_path, "src/a.py", text=text)
    m = guard.complexity_map(tmp_path)
    assert m["src/a.py::A.run"] == 2
    assert m["src/a.py::B.run"] == 3


# ── baseline governance ─────────────────────────────────────────

def test_corrupt_baseline_raises(tmp_path):
    path = tmp_path / "baseline.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(guard.GuardConfigError):
        guard.load_baseline(path)


def test_approve_debt_requires_reason_and_approver(tmp_path):
    with pytest.raises(guard.GuardConfigError):
        guard.approve_debt("src/a.py::f", "", "human", root=tmp_path)


def test_approve_debt_allows_new_debt_once(tmp_path):
    body = "\n".join(["if x:", "    pass"] * 21)
    _tree(tmp_path, "src/a.py", text=_func(tmp_path, "f", body))
    baseline = _baseline(tmp_path / "baseline.json", {})
    history = tmp_path / "history.jsonl"
    row = guard.approve_debt("src/a.py::f", "new feature", "alice",
                             root=tmp_path, baseline_path=baseline,
                             history_path=history)
    assert row["approver"] == "alice"
    assert guard.load_baseline(baseline)["src/a.py::f"] > 20
    with pytest.raises(guard.GuardConfigError):
        guard.approve_debt("src/a.py::f", "again", "alice", root=tmp_path,
                           baseline_path=baseline, history_path=history)


def test_reduce_debt_never_raises_baseline(tmp_path):
    body = "\n".join(["if x:", "    pass"] * 25)
    _tree(tmp_path, "src/a.py", text=_func(tmp_path, "f", body))
    actual = guard.complexity_map(tmp_path)["src/a.py::f"]
    baseline = _baseline(tmp_path / "baseline.json", {"src/a.py::f": actual - 5})
    budget = _budget(tmp_path / "budget.yaml")
    guard.reduce_debt(tmp_path, budget, baseline, tmp_path / "h.jsonl")
    assert guard.load_baseline(baseline)["src/a.py::f"] == actual - 5


# ── dependency budget ───────────────────────────────────────────

def test_unregistered_zone_is_reported(tmp_path):
    _tree(tmp_path, "src/rogue/x.py", lines=1)
    issues = guard.zone_violations(tmp_path)
    assert any(i["type"] == "unregistered_zone" and i["path"] == "src/rogue/"
               for i in issues)


def test_engine_must_not_import_agent(tmp_path):
    _tree(tmp_path, "src/agent_plane/specialists/x.py", lines=1)
    _tree(tmp_path, "src/engine_plane/front/x.py",
          text="from src.agent_plane.specialists import x\n")
    issues = guard.import_violations(tmp_path)
    assert any(i["type"] == "import_direction" and i["to"] == "agents"
               for i in issues)


def test_dynamic_import_into_agent_is_checked(tmp_path):
    _tree(tmp_path, "src/agent_plane/specialists/x.py", lines=1)
    _tree(tmp_path, "src/engine_plane/front/x.py", text=(
        "def f():\n"
        "    import importlib\n"
        "    return importlib.import_module('src.agent_plane.specialists.x')\n"))
    issues = guard.import_violations(tmp_path)
    assert any(i["type"] == "lazy_import_direction" and i["to"] == "agents"
               for i in issues)


def test_check_reports_all_budget_dimensions(tmp_path):
    _tree(tmp_path, "src/a.py", lines=1400)
    budget = _budget(tmp_path / "budget.yaml",
                     {"src/a.py": {"registered": 1800, "reason": "r",
                                   "plan": "p"}})
    baseline = _baseline(tmp_path / "baseline.json", {})
    result = guard.check(tmp_path, budget, baseline)
    assert result["ok"] is False
    assert result["line_issues"]
    assert result["debt_issues"]
    assert result["tool_version"] == "2.1"
