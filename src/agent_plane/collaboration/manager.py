"""SubagentManager —— 主 Agent 派发、隔离执行、结构化回收。

主 Agent 只拿 `result.json`（摘要 + findings + artifacts + unresolved），
不把子 Agent 的完整聊天/日志塞回自己的上下文。
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from pathlib import Path
from typing import Any, Dict, List

from .context_builder import build_subagent_task
from .contract import SubagentContract, SubagentResult
from .factory import AGENT_TYPES, ROLE_PROMPTS, build_contract
from .isolation import ScopedTools, SubagentWorkspace
from .validator import validate_result

_REPO_ROOT = Path(__file__).resolve().parents[4]


def _kill_process_tree(pid: int) -> None:
    """超时必须清整棵进程树（runner + shell + EDA），不能只杀 Python。"""
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                       capture_output=True)
        return
    try:
        os.killpg(os.getpgid(pid), signal.SIGKILL)
    except OSError:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass


class SubagentManager:
    def __init__(self, parent: Any):
        self.parent = parent
        self.zones = parent.zones
        self._store_lock = threading.Lock()

    def spawn(self, agent_type: str, objective: str, **kwargs: Any) -> Dict[str, Any]:
        contract = build_contract(
            agent_type, objective,
            parent_task_id=str(kwargs.pop("parent_task_id", "")),
            **kwargs)
        return self.run_contract(contract)

    def spawn_many(self, requests: List[Dict[str, Any]],
                   max_workers: int = 3) -> Dict[str, Any]:
        """并行派发多个独立子任务；结果仍逐个结构化回收。"""
        contracts: List[SubagentContract] = []
        for index, req in enumerate(requests or [], 1):
            if not isinstance(req, dict):
                continue
            contracts.append(build_contract(
                str(req.get("agent_type") or ""),
                str(req.get("objective") or req.get("task") or ""),
                parent_task_id=str(req.get("parent_task_id") or ""),
                task_id=str(req.get("task_id") or f"batch_{index}"),
                deliverables=req.get("deliverables"),
                acceptance=req.get("acceptance"),
                constraints=req.get("constraints")))
        if not contracts:
            return {"ok": False, "results": [], "error": "没有可派发的子任务"}
        workers = max(1, min(int(max_workers or 3), len(contracts)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(self.run_contract, c) for c in contracts]
            results = [f.result() for f in futures]
        return {"ok": all(r.get("ok") for r in results),
                "results": results}

    def _fingerprint(self, contract: SubagentContract) -> str:
        """task_id/objective/scope + 工程 revision + 输入文件 hash。"""
        import hashlib
        import json

        project_root = Path(self.zones.project_root())
        revision = ""
        try:
            completed = subprocess.run(
                ["git", "-C", str(project_root), "rev-parse", "HEAD"],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=10)
            if completed.returncode == 0:
                revision = completed.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            revision = ""
        inputs: List[str] = []
        for prefix in (contract.scope or {}).get("read") or []:
            base = project_root / prefix
            files = ([base] if base.is_file() else
                     sorted(p for p in base.rglob("*") if p.is_file())
                     if base.is_dir() else [])
            for path in files[:200]:
                if self.zones.is_blocked(path):
                    continue
                try:
                    if path.stat().st_size > 2_000_000:
                        continue
                    digest = hashlib.sha256(path.read_bytes()).hexdigest()
                except OSError:
                    continue
                inputs.append(f"{path.relative_to(project_root).as_posix()}:{digest}")
        payload = {
            "task_id": contract.task_id,
            "agent_type": contract.agent_type,
            "objective": contract.objective,
            "scope": contract.scope,
            "project_revision": revision,
            "inputs": inputs,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True,
                                         ensure_ascii=False).encode()).hexdigest()

    def run_contract(self, contract: SubagentContract) -> Dict[str, Any]:
        issues = contract.validate()
        if issues:
            return {"ok": False, "task_id": contract.task_id,
                    "status": "FAILED", "error": "; ".join(issues)}
        spec = AGENT_TYPES.get(contract.agent_type)
        if spec is None:
            return {"ok": False, "task_id": contract.task_id,
                    "status": "FAILED",
                    "error": f"未知 agent_type: {contract.agent_type}"}

        workspace = SubagentWorkspace(self.zones, contract.task_id).ensure()
        contract.fingerprint = self._fingerprint(contract)
        store = getattr(self.parent, "task_store", None)
        cached = self._cached_result(contract, workspace)
        if cached is not None:
            return cached
        prompt = self._prepare_workspace(contract, workspace)
        raw, child = self._execute(contract, spec, workspace, prompt)
        workspace.record_event("subagent.finish", status=str(raw.get("status")),
                               summary=str(raw.get("reason") or raw.get("error") or "")[:500])
        return self._finalize(contract, workspace, child, raw, store)

    def _cached_result(self, contract: SubagentContract,
                       workspace: SubagentWorkspace) -> Optional[Dict[str, Any]]:
        old = workspace.read_json("task.json", {})
        same_task = (old.get("objective") == contract.objective
                     and old.get("agent_type") == contract.agent_type)
        if same_task and old.get("fingerprint") == contract.fingerprint:
            cached = self.collect(contract.task_id)
            if cached.get("status") == "COMPLETED":
                return {"ok": bool(cached.get("validated", True)),
                        **cached, "cached": True}
        elif old and old.get("fingerprint") != contract.fingerprint:
            workspace.record_event("subagent.stale",
                                   old_fingerprint=old.get("fingerprint", ""),
                                   new_fingerprint=contract.fingerprint)
        for name in ("result.json", "runner_result.json"):
            try:
                (workspace.root / name).unlink()
            except OSError:
                pass
        return None

    def _prepare_workspace(self, contract: SubagentContract,
                           workspace: SubagentWorkspace) -> str:
        workspace.write_json("task.json", contract.to_dict())
        contract.status = "RUNNING"
        workspace.record_event("subagent.start", agent_type=contract.agent_type,
                               objective=contract.objective)
        project = getattr(self.parent, "project_memory", None)
        project_text = project.load_or_build() if project is not None else ""
        store = getattr(self.parent, "task_store", None)
        task_memory = store.render_memory() if store is not None else ""
        prompt = build_subagent_task(contract, project_context=project_text,
                                     task_memory=task_memory)
        workspace.write_text("prompt.md", prompt)
        return prompt

    def _execute(self, contract: SubagentContract, spec: Any,
                 workspace: SubagentWorkspace, prompt: str) -> tuple:
        use_process = (self.parent.planner is None
                       and os.environ.get("SIGNOFFAI_SUBAGENT_PROCESS", "1") != "0")
        if use_process:
            return self._run_child_process(contract, workspace, prompt), None
        write_roots: list[str] = [str(workspace.workspace_dir)]
        for prefix in (contract.scope or {}).get("write") or []:
            write_roots.append(str(prefix))
        tools = ScopedTools(
            self.parent.sandbox, self.zones,
            allowed_tools=spec.allowed_tools,
            write_roots=write_roots,
            allow_exec=any(t in spec.allowed_tools
                           for t in ("run_shell", "run_verify", "run_stage")),
        )
        from ..runtime.harness import Harness, HarnessConfig
        cfg = HarnessConfig(
            max_steps=max(1, spec.max_steps),
            max_steps_per_subgoal=0,
            max_rounds=1,
            plan_first=False,
            require_plan_approval=False,
            require_exec_approval=False,
            allow_subagent=False,
            emit_proposal=False,
            compaction=self.parent.config.compaction,
            role_prompt=ROLE_PROMPTS.get(contract.agent_type, ""),
            project_root=self.parent.config.project_root
            or str(self.zones.project_root()),
        )
        child = Harness(self.zones, config=cfg, planner=self.parent.planner,
                        tools=tools, stage_runner=self.parent.stage_runner)
        return self._run_child(child, prompt, spec.max_steps,
                               contract.timeout_s), child

    def _finalize(self, contract: SubagentContract,
                  workspace: SubagentWorkspace, child: Any,
                  raw: Dict[str, Any], store: Any) -> Dict[str, Any]:
        result = self._result_of(contract, workspace, child, raw)
        result.validation = validate_result(
            contract, result, workspace,
            project_root=self.zones.project_root())
        result.fingerprint = contract.fingerprint
        result.validated = not result.validation
        workspace.write_json("result.json", result.to_dict())
        if store is not None:
            with self._store_lock:
                store.add_subagent_result(result.to_dict())
        return {"ok": result.status == "COMPLETED" and result.validated,
                **result.to_dict()}

    @staticmethod
    def _run_child(child: Any, prompt: str, max_steps: int,
                   timeout_s: int) -> Dict[str, Any]:
        """在独立线程里跑子 harness；超时返回 TIMEOUT，不拖死主循环。

        注意：线程无法被强杀，超时后子任务可能仍在后台跑；它的 workspace
        会保留，主 Agent 可据此判断“未完成”而不是假 pass。
        """
        if not timeout_s or timeout_s <= 0:
            return child.run(prompt, max_steps=max_steps)
        pool = ThreadPoolExecutor(max_workers=1)
        future = pool.submit(child.run, prompt, max_steps=max_steps)
        try:
            return future.result(timeout=timeout_s)
        except FutureTimeout:
            return {"status": "timeout",
                    "reason": f"子 Agent 超时 {timeout_s}s"}
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

    def _run_child_process(self, contract: SubagentContract,
                           workspace: SubagentWorkspace,
                           prompt: str) -> Dict[str, Any]:
        """用独立 Python 进程跑子 Agent：独立 Harness/session/TaskStore/workspace。"""
        command = [
            sys.executable, "-B", "-m", "src.agent_plane.collaboration.runner",
            "--contract", str(workspace.root / "task.json"),
            "--prompt", str(workspace.root / "prompt.md"),
            "--project-root", str(self.zones.project_root()),
        ]
        env = {k: v for k, v in os.environ.items()
               if not any(x in k.upper() for x in
                          ("SECRET", "TOKEN", "PASSWORD", "PRIVATE_KEY"))}
        # 子进程需要 LLM key；只剔除真正的凭据类变量，不剔除 LLM_API_KEY。
        for key in ("LLM_API_KEY", "LLM_BASE_URL", "LLM_PROVIDER", "LLM_MODEL"):
            if key in os.environ:
                env[key] = os.environ[key]
        kwargs: Dict[str, Any] = {
            "cwd": str(_REPO_ROOT), "env": env,
            "stdout": subprocess.PIPE, "stderr": subprocess.PIPE,
            "text": True, "encoding": "utf-8", "errors": "replace",
        }
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        process = subprocess.Popen(command, **kwargs)
        try:
            stdout, stderr = process.communicate(
                timeout=max(1, int(contract.timeout_s or 600)))
        except subprocess.TimeoutExpired:
            _kill_process_tree(process.pid)
            try:
                stdout, stderr = process.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                stdout, stderr = "", ""
            return {"status": "timeout",
                    "reason": f"子 Agent 进程树超时 {contract.timeout_s}s"}
        doc = None
        for name in ("result.json", "runner_result.json"):
            try:
                doc = workspace.read_json(name, None)
            except Exception:                    # noqa: BLE001
                doc = None
            if isinstance(doc, dict):
                break
        if isinstance(doc, dict):
            return doc
        return {"status": "failed",
                "reason": (stderr or stdout or "")[-1000:]}

    @staticmethod
    def _result_of(contract: SubagentContract, workspace: SubagentWorkspace,
                   child: Any, raw: Dict[str, Any]) -> SubagentResult:
        doc = workspace.read_json("result.json", None)
        if not (isinstance(doc, dict) and doc.get("task_id")):
            doc = workspace.read_json("runner_result.json", None)
        if isinstance(doc, dict) and doc.get("task_id"):
            result = SubagentResult.from_dict(doc)
        elif isinstance(raw, dict) and raw.get("task_id"):
            result = SubagentResult.from_dict(raw)
        else:
            status = str(raw.get("status") or "")
            mapped = {
                "finished_no_proposal": "COMPLETED",
                "proposal": "COMPLETED",
                "done": "COMPLETED",
                "blocked": "BLOCKED",
                "cancelled": "CANCELLED",
                "timeout": "TIMEOUT",
            }.get(status, "FAILED")
            session = getattr(child, "session", None)
            working = getattr(session, "working", {}) or {}
            result = SubagentResult(
                task_id=contract.task_id,
                status=mapped,
                summary=str(raw.get("reason") or raw.get("summary")
                            or raw.get("error")
                            or getattr(session, "last_error", "") or status),
                unresolved=list(working.get("open_questions") or []),
            )
        if not result.findings:
            doc = workspace.read_json("findings.json", None)
            if isinstance(doc, dict):
                result.findings = [f for f in (doc.get("findings") or [])
                                   if isinstance(f, dict)]
            elif isinstance(doc, list):
                result.findings = [f for f in doc if isinstance(f, dict)]
        artifacts = set(result.artifacts) | set(workspace.list_artifacts())
        result.artifacts = sorted(artifacts)
        return result

    def collect(self, task_id: str) -> Dict[str, Any]:
        workspace = SubagentWorkspace(self.zones, task_id)
        for name in ("result.json", "runner_result.json"):
            doc = workspace.read_json(name, None)
            if isinstance(doc, dict):
                return doc
        return {"task_id": task_id, "status": "MISSING"}


__all__ = ["SubagentManager"]
