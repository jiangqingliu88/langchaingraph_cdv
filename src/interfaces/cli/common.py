"""CLI 共享底座 —— 退出码 + 无状态 helper。

`commands.py` 只做“入口 + 注册子命令组”；这里放**不依赖 cli/console 全局
状态**的东西，拆出的 `cmd_*` 模块仍可从 `src.interfaces.cli.commands` 取到（后者
re-export），不需要跟着改 import。

放这里的判据：
  · 纯函数（给定输入 → 输出），或只依赖 click/subprocess；
  · 不持有全局单例、不注册命令、不读运行期配置。
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import click

# ═══════════════════════════════════════════════════════════════
# 退出码 —— **一处定义，别处只许引用**
# ═══════════════════════════════════════════════════════════════
# 分工：EXIT_OK/EXIT_FAIL 是通用成败；EXIT_USAGE 与 click 的用法错一致（2，
# 别改）；EXIT_WAITING 是“没失败，在等人”；EXIT_LAYER_VIOLATION 是启动期
# 分层守卫拦下的；EXIT_STRICT 是 --strict-semantic 下 PASS_WITH_CAVEAT。
EXIT_OK = 0
EXIT_FAIL = 1
EXIT_USAGE = 2
EXIT_WAITING = 3
EXIT_LAYER_VIOLATION = 4
EXIT_STRICT = 5


# ═══════════════════════════════════════════════════════════════
# 无状态 helper
# ═══════════════════════════════════════════════════════════════

def _extract_requirements_from_md(text: str) -> list:
    """从 Markdown 提取需求 ID（`**REQ_xxx**`）。"""
    import re

    reqs = []
    for match in re.finditer(r'\*\*(REQ_\w+)\*\*', text):
        reqs.append({"id": match.group(1),
                     "line": text[:match.start()].count("\n") + 1})
    return reqs


def _get_git_info(cwd: Path) -> dict:
    """当前 git 分支 / 短 commit；拿不到就如实标 N/A。"""
    try:
        import subprocess

        branch = subprocess.check_output(
            ["git", "branch", "--show-current"], cwd=str(cwd), text=True).strip()
        commit = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=str(cwd), text=True).strip()
        return {"branch": branch, "commit": commit}
    except Exception:                                   # noqa: BLE001
        return {"branch": "N/A", "commit": "N/A"}


def _output_junit(result: dict) -> None:
    """生成 JUnit XML（CI 消费）。"""
    import xml.etree.ElementTree as ET

    testsuite = ET.Element("testsuite", {
        "name": "SignOffAI",
        "tests": str(result["total"]),
        "failures": str(result["total"] - result["passed"]),
        "errors": "0",
        "time": str(sum(p.get("time", 0) for p in result["phases"])),
        "timestamp": datetime.now().isoformat(),
    })
    for p in result["phases"]:
        testcase = ET.SubElement(testsuite, "testcase", {
            "classname": "SignOffAI.phase",
            "name": p["name"],
            "time": str(p.get("time", 0)),
        })
        if p["status"] in ("failed", "error"):
            ET.SubElement(testcase, "failure", {
                "message": f"Phase {p['name']} {p['status']}",
                "type": p["status"],
            })
    click.echo(ET.tostring(testsuite, encoding="unicode"))


def _output_gitlab_ci(result: dict) -> None:
    """输出 GitLab CI metrics。"""
    passed = result["passed"]
    total = result["total"]
    score = result["overall_score"]

    metrics = [
        f"signoffai_passed {passed}",
        f"signoffai_total {total}",
        f"signoffai_score {score}",
    ]
    for p in result["phases"]:
        name = p["name"].lower()
        metrics.append(f"signoffai_phase_{name}_score {p.get('score', 0)}")

    click.echo("\n".join(metrics))
    click.echo(f"\n# SignOffAI Report: {passed}/{total} passed, Score: {score}/100")


def _sha256_path(path: Path) -> str:
    """文件 sha256；读不到返回空串（调用方按“缺失”处理）。"""
    try:
        import hashlib

        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return ""


def _approver_name() -> str:
    """审批人：git user.name → 环境用户名 → `unknown`（不编一个名字）。"""
    try:
        import subprocess

        out = subprocess.run(["git", "config", "user.name"], capture_output=True,
                             text=True, encoding="utf-8", errors="replace",
                             timeout=5)
        name = (out.stdout or "").strip()
        if name:
            return name
    except Exception:                                   # noqa: BLE001
        pass
    import getpass

    try:
        return getpass.getuser()
    except Exception:                                   # noqa: BLE001
        return "unknown"
