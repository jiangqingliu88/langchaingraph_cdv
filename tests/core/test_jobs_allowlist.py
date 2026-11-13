from __future__ import annotations

from pathlib import Path

from src.runtime_plane.core.jobs.allowlist import CommandPolicy, check_command, scan_tool_args


def _policy(mode: str) -> CommandPolicy:
    return CommandPolicy(mode=mode)


def test_allowed_tool(tmp_path):
    ok, why = check_command(["bash", "-lc", "true"], cwd=tmp_path,
                            policy=_policy("enforce"))
    # bash -c 里的字符串不是路径参数（以 '-' 开头），这里应通过
    assert ok is True and why == ""


def test_unknown_tool_is_blocked_in_enforce(tmp_path):
    ok, why = check_command(["curl", "https://example.com"], cwd=tmp_path,
                            policy=_policy("enforce"))
    assert ok is False
    assert "白名单" in why


def test_monitor_records_but_allows(tmp_path):
    ok, why = check_command(["curl", "https://example.com"], cwd=tmp_path,
                            policy=_policy("monitor"))
    assert ok is True
    assert why.startswith("monitor:")


def test_python_inline_code_blocked_in_enforce(tmp_path):
    ok, why = check_command(["python", "-c", "print(1)"], cwd=tmp_path,
                            policy=_policy("enforce"))
    assert ok is False
    assert "python -c" in why


def test_path_escape_blocked(tmp_path):
    ok, why = check_command(["bash", "../../etc/passwd"], cwd=tmp_path,
                            policy=_policy("enforce"))
    assert ok is False
    assert "越出" in why


def test_path_inside_cwd_allowed(tmp_path):
    ok, why = check_command(["bash", "scripts/run.sh"], cwd=tmp_path,
                            policy=_policy("enforce"))
    assert ok is True, why


def test_off_mode_allows_everything():
    ok, why = check_command(["definitely-not-a-tool"], policy=_policy("off"))
    assert ok is True and why == ""


def test_scan_tool_args_finds_command_keys(tmp_path):
    ok, why = scan_tool_args("sim", {"command": "curl http://x"}, cwd=tmp_path,
                             policy=_policy("enforce"))
    assert ok is False
    ok, why = scan_tool_args("sim", {"args": ["-x"]}, cwd=tmp_path,
                             policy=_policy("enforce"))
    assert ok is True and why == ""


def test_from_env_defaults_to_monitor(monkeypatch):
    monkeypatch.delenv("SIGNOFFAI_CMD_ALLOWLIST", raising=False)
    assert CommandPolicy.from_env().mode == "monitor"
    monkeypatch.setenv("SIGNOFFAI_CMD_ALLOWLIST", "enforce")
    assert CommandPolicy.from_env().mode == "enforce"
    monkeypatch.setenv("SIGNOFFAI_CMD_ALLOWLIST", "bogus")
    assert CommandPolicy.from_env().mode == "monitor"
