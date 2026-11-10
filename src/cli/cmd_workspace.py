"""CLI 命令组：Workspace zones（main / staging / proposal / gate）。

从 `src/cli/commands.py` 拆出（工作区 + 受控循环域）；导入本模块即把命令
注册到 `cli`。
"""
from __future__ import annotations

import json

import click

from src.app.services import workspace_service as svc
from src.cli.commands import cli


def _print(doc) -> None:
    click.echo(json.dumps(doc, ensure_ascii=False, indent=2))


def _load_hook(spec: str):
    """`module:callable` → 领域检查钩子（与默认检查同样的结构契约）。"""
    import importlib
    module_name, _, attr = spec.partition(":")
    if not module_name or not attr:
        raise click.BadParameter(f"检查钩子必须是 module:callable：{spec}")
    return getattr(importlib.import_module(module_name), attr)


@cli.group("workspace")
def workspace():
    """工作区分区：main（签核）/ staging（沙箱）/ proposal / gate。

    \b
    示例:
      vagent workspace init workspace/demo --from specs/npu_sched/rtl
      vagent workspace loop workspace/demo --task "补一个边界用例"
      vagent workspace gate workspace/demo P-...
      vagent workspace promote workspace/demo P-... --by jiang
    """


@workspace.command("init")
@click.argument("root")
@click.option("--from", "from_dir", default=None,
              help="main 基线目录（会复制一份到 staging）")
@click.option("--project-root", default=None,
              help="只读项目视图根（默认从 --from 向上找 .git/pyproject.toml）")
def workspace_init(root, from_dir, project_root):
    """建出 main/staging/proposals/gate 四区。"""
    _print(svc.init_workspace(root, from_dir, project_root=project_root))


@workspace.command("resources")
@click.argument("root")
@click.option("--kind", type=click.Choice(["", "rtl", "verification", "coverage",
                                           "env", "spec", "model"]),
              default="", help="只看某一类资源")
@click.option("--limit", type=int, default=200, show_default=True)
def workspace_resources(root, kind, limit):
    """只读项目资源清单（RTL/验证/覆盖率/环境/spec/模型）。"""
    _print(svc.list_resources(root, kind, limit))


@workspace.command("status")
@click.argument("root")
def workspace_status(root):
    """主区指纹 / staging 差异 / proposal 列表。"""
    _print(svc.workspace_status(root))


@workspace.command("propose")
@click.argument("root")
@click.option("--task", required=True, help="这次变更要解决什么")
@click.option("--before", required=True, help="变更前的可量化结论")
@click.option("--after", required=True, help="变更后的可量化结论")
@click.option("--reasoning", "reasoning_trace", required=True, help="为什么这么改")
@click.option("--run", "commands", multiple=True,
              help="在 staging 里执行并记录证据的命令（至少一条）")
@click.option("--open-question", "questions", multiple=True, help="待决问题（人工门必看）")
@click.option("--eda-run", default=None, help="附带的 vplan execute 产物目录（EDA 证据）")
@click.option("--target", type=float, default=0.0, help="覆盖率目标（配合 --eda-run）")
def workspace_propose(root, task, before, after, reasoning_trace, commands,
                      questions, eda_run, target):
    """手工造 proposal（不经过 LLM loop；staging 改动 + 真跑命令 + 待决问题）。"""
    _print(svc.create_proposal(root, task, before=before, after=after,
                               reasoning_trace=reasoning_trace,
                               commands=commands, open_questions=questions,
                               eda_run=eda_run, target=target))


@workspace.command("proposals")
@click.argument("root")
def workspace_proposals(root):
    """列出 proposal。"""
    _print(svc.list_proposals(root))


@workspace.command("reset")
@click.argument("root")
def workspace_reset(root):
    """丢弃沙箱：staging 恢复成 main 的副本。"""
    _print(svc.reset_staging(root))


@workspace.command("loop")
@click.argument("root")
@click.option("--task", required=True, help="交给沙箱循环的任务描述")
@click.option("--max-steps", type=int, default=12, show_default=True)
@click.option("--max-rounds", type=int, default=2, show_default=True)
@click.option("--max-tokens", type=int, default=200000, show_default=True)
@click.option("--plan", "plan_first", is_flag=True, help="第一次响应先出 plan")
@click.option("--require-plan-approval", is_flag=True, help="plan 需人工批准")
@click.option("--require-exec-approval", is_flag=True,
              help="命令类工具（run_shell/job）需人工批准")
@click.option("--no-subagent", is_flag=True, help="禁用 spawn_subagent")
@click.option("--session-id", default=None, help="恢复已有会话")
@click.option("--goal", type=click.Choice(["", "coverage"]), default="",
              help="coverage = 证据驱动的覆盖率目标")
@click.option("--target", type=float, default=0.0, help="覆盖率目标（--goal coverage）")
@click.option("--project", default="", help="vplan 项目路径（默认 staging）")
@click.option("--project-root", default="", help="只读项目视图根")
@click.option("--evidence", default="", help="已有 run 目录（用于自动拆缺口）")
@click.option("--max-subgoals", type=int, default=6, show_default=True)
@click.option("--require-review", is_flag=True,
              help="run_verify 时强制人工审阅（默认沙箱允许 --allow-unreviewed）")
@click.option("--export", "auto_export", is_flag=True,
              help="run_verify 后自动导出证据 zip（落 staging）")
@click.option("--export-out", default="", help="证据 zip 输出路径（staging 内相对路径）")
def workspace_loop(root, task, max_steps, max_rounds, max_tokens, plan_first,
                   require_plan_approval, require_exec_approval, no_subagent,
                   session_id, goal, target, project, project_root, evidence,
                   max_subgoals, require_review, auto_export, export_out):
    """通用 harness：状态机 + 回填 + 压缩；只写 staging，出口是 proposal/如实阻塞。"""
    _print(svc.run_sandbox(
        root, task, max_steps=max_steps, session_id=session_id,
        max_rounds=max_rounds, max_tokens=max_tokens,
        plan_first=plan_first, require_plan_approval=require_plan_approval,
        require_exec_approval=require_exec_approval,
        allow_subagent=not no_subagent,
        goal=goal, coverage_target=target, project=project,
        project_root=project_root, evidence=evidence,
        max_subgoals=max_subgoals,
        allow_unreviewed=not require_review,
        auto_export=auto_export, export_out=export_out))


@workspace.command("export")
@click.argument("root")
@click.option("--run", "run_dir", required=True, help="run 目录（优先导出 signoff_evidence/）")
@click.option("--output", "-o", default=None, help="zip 输出路径（默认 <run>/export/）")
def workspace_export(root, run_dir, output):
    """把 run 的证据导出成可交换 zip（v2 签核包优先，否则结构化证据）。"""
    if not svc.workspace_status(root).get("ok"):
        _print({"error": f"workspace 不存在：{root}"})
        return
    _print(svc.export_evidence(run_dir, output))


@workspace.command("sessions")
@click.argument("root")
def workspace_sessions(root):
    """列出 harness 会话（状态 / 轮次 / 步数 / proposal）。"""
    _print(svc.list_sessions(root))


@workspace.command("resume")
@click.argument("root")
@click.argument("session_id")
@click.option("--approve/--deny", "approve", default=None,
              help="批准/拒绝 plan 或待执行的命令")
@click.option("--answer", default="", help="ask_user 的回答")
@click.option("--plan", default="", help="批准时替换 plan 文本")
def workspace_resume(root, session_id, approve, answer, plan):
    """恢复暂停的会话（plan 审批 / 命令审批 / ask_user）。"""
    _print(svc.resume_sandbox(root, session_id, approve=approve,
                              answer=answer, plan=plan))


@workspace.command("gate")
@click.argument("root")
@click.argument("proposal_id")
@click.option("--check", "checks", multiple=True,
              help="领域校验钩子 module:callable（可重复；契约/回归/覆盖率阈值）")
@click.option("--profile", type=click.Choice(["default", "eda"]), default="default",
              show_default=True, help="eda = 追加 EDA 证据裁决")
def workspace_gate(root, proposal_id, checks, profile):
    """跑确定性 Gate 检查（默认检查 + 注入的领域钩子）。"""
    hooks = [_load_hook(spec) for spec in checks]
    _print(svc.run_gate(root, proposal_id, extra_checks=hooks, profile=profile))


@workspace.command("approve")
@click.argument("root")
@click.argument("proposal_id")
@click.option("--by", required=True, help="批准人")
@click.option("--comment", default="", help="批准意见")
def workspace_approve(root, proposal_id, by, comment):
    """人工批准（open_questions/warn 的人工门）。"""
    _print(svc.approve_gate(root, proposal_id, by=by, comment=comment))


@workspace.command("promote")
@click.argument("root")
@click.argument("proposal_id")
@click.option("--by", default="", help="执行 promote 的人（写入账本）")
@click.option("--force", is_flag=True, help="跳过人工门/基线检查（仅开发调试）")
def workspace_promote(root, proposal_id, by, force):
    """过 Gate 后把 staging 变更提升进 main（唯一写 main 的入口）。"""
    _print(svc.promote(root, proposal_id, by=by, force=force))
