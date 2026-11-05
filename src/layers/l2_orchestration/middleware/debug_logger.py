"""Execution tracer - logs every LLM call, tool call, agent action, file write, compile/sim."""
import json, os, time
from datetime import datetime
from pathlib import Path
import structlog

logger = structlog.get_logger()


class ExecutionTracer:
    """Singleton tracer for pipeline execution monitoring.
    Logs to: console (real-time) + JSONL file (post-mortem)."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, '_initialized'):
            return
        self._initialized = True
        self.log_dir = Path("logs/execution")
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._buffer = []
        self._phase_start = {}
        self._indent = 0
        self._enabled = True

    # ── control ──

    def enable(self): self._enabled = True
    def disable(self): self._enabled = False

    # ── pipeline-level ──

    def pipeline_start(self, workflow: str, spec_file: str, phases: list):
        if not self._enabled: return
        print(f"\n{'='*60}")
        print(f"  PIPELINE: {workflow}  |  spec: {spec_file}")
        print(f"  Phases: {' -> '.join(p[:12] for p in phases)}")
        print(f"  Session: {self.session_id}")
        print(f"{'='*60}\n", flush=True)
        self._write_event("pipeline_start", workflow=workflow, spec_file=spec_file, phases=phases)

    def pipeline_end(self, passed: int, total: int, total_time: float, scores: dict = None):
        if not self._enabled: return
        print(f"\n{'='*60}")
        print(f"  RESULT: {passed}/{total} passed  |  {total_time:.1f}s total")
        if scores:
            print(f"  Scores: {scores}")
        print(f"{'='*60}\n", flush=True)
        self._write_event("pipeline_end", passed=passed, total=total, total_time=total_time, scores=scores)
        self.flush()

    def phase_start(self, phase: str, agent_name: str, attempt: int = 0):
        if not self._enabled: return
        label = f"[{phase}] {agent_name}" + (f" (retry {attempt})" if attempt > 0 else "")
        print(f"\n  >>> {label}", flush=True)
        self._phase_start[phase] = time.time()

    def phase_end(self, phase: str, status: str, score: int = 0, elapsed: float = 0):
        if not self._enabled: return
        icon = {"passed": "+", "degraded": "~", "failed": "X", "error": "!"}.get(status, "?")
        print(f"  <<< [{icon}] {phase}: {status} score={score} ({elapsed:.1f}s)\n", flush=True)

    # ── LLM call ──

    def llm_call(self, agent_role: str, prompt: str, response: str = "", tokens: int = 0, elapsed: float = 0, success: bool = True):
        if not self._enabled: return
        plen = len(prompt) if prompt else 0
        rlen = len(response) if response else 0
        tag = agent_role[:18]
        icon = "OK" if success else "FAIL"
        # Show preview of prompt and response
        ppre = prompt[:100].replace('\n', ' ') + ('...' if plen > 100 else '') if prompt else '(empty)'
        rpre = response[:120].replace('\n', ' ') + ('...' if rlen > 120 else '') if response else '(empty)'
        print(f"  [llm] {tag}: prompt({plen}c) \"{ppre}\"", flush=True)
        if response:
            print(f"  [llm] {tag}: resp({rlen}c, {tokens}tk, {elapsed:.1f}s) [{icon}] \"{rpre}\"", flush=True)
        self._write_event("llm_call", agent=agent_role, prompt_len=plen, response_len=rlen,
                          prompt_preview=ppre, response_preview=rpre, tokens=tokens, elapsed=elapsed, success=success)

    # ── tool call ──

    def tool_call(self, agent_role: str, tool_name: str, tool_input: str = "", tool_output: str = "", elapsed: float = 0):
        if not self._enabled: return
        ilen = len(tool_input) if tool_input else 0
        olen = len(tool_output) if tool_output else 0
        print(f"  [tool] {agent_role[:15]}.{tool_name}: in({ilen}c) -> out({olen}c) ({elapsed:.1f}s)", flush=True)
        self._write_event("tool_call", agent=agent_role, tool=tool_name, input_len=ilen, output_len=olen, elapsed=elapsed)

    # ── agent IO ──

    def agent_io(self, agent_role: str, direction: str, summary: str):
        """direction: 'in', 'act', 'out'"""
        if not self._enabled: return
        tag = agent_role[:20]
        icons = {"in": "IN ", "act": "ACT", "out": "OUT"}
        icon = icons.get(direction, "---")
        print(f"  [{tag}] {icon}: {summary[:200]}", flush=True)

    # ── file write ──

    def file_write(self, filepath: str, size: int = 0):
        if not self._enabled: return
        fname = Path(filepath).name
        print(f"  [file] wrote {fname} ({size}b)", flush=True)
        self._write_event("file_write", path=str(filepath), size=size)

    # ── compile / sim ──

    def compile_result(self, agent: str, status: str, errors: int = 0, elapsed: float = 0):
        if not self._enabled: return
        icon = "PASS" if status == "PASS" else "FAIL"
        print(f"  [compile] {agent}: {icon} errors={errors} ({elapsed:.1f}s)", flush=True)

    def sim_result(self, agent: str, status: str, driven: int = 0, matched: int = 0, mismatched: int = 0, score: int = 0, elapsed: float = 0):
        if not self._enabled: return
        icon = "PASS" if status == "PASS" else "FAIL"
        print(f"  [sim] {agent}: {icon} driven={driven} matched={matched} mismatched={mismatched} score={score} ({elapsed:.1f}s)", flush=True)

    # ── internal ──

    def _write_event(self, event_type: str, **kwargs):
        entry = {"timestamp": datetime.now().isoformat(), "session": self.session_id, "event": event_type, **kwargs}
        self._buffer.append(entry)
        if len(self._buffer) >= 5:
            self.flush()

    def flush(self):
        if not self._buffer:
            return
        log_file = self.log_dir / f"exec_{self.session_id}.jsonl"
        with open(log_file, 'a', encoding='utf-8') as f:
            for entry in self._buffer:
                f.write(json.dumps(entry, ensure_ascii=False) + '\n')
        self._buffer = []


# Global singleton
tracer = ExecutionTracer()

# ── Backward-compat wrapper ──

class AgentDebugLogger:
    """Legacy wrapper — delegates to ExecutionTracer."""
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, '_initialized'):
            return
        self._initialized = True

    def log_agent_call(self, agent_role, agent_name, task_input, prompt, output, tools_used, tokens, elapsed, success, error=None):
        tracer.agent_io(agent_role, "in", str(task_input)[:150])
        tracer.agent_io(agent_role, "out", str(output)[:200])

    def log_pipeline_start(self, workflow, spec_file, phases):
        tracer.pipeline_start(workflow, spec_file, [p.get("name", p) for p in phases] if isinstance(phases[0], dict) else phases)

    def log_pipeline_end(self, passed, degraded, total_time):
        tracer.pipeline_end(passed, passed, total_time)

    def get_session_log(self, session_id=None):
        return []

    def list_sessions(self):
        return []


debug_logger = AgentDebugLogger()
