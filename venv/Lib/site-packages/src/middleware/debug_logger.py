"""Agent debug logger - records all agent I/O for debugging"""
import json
import os
from datetime import datetime
from pathlib import Path
import structlog

logger = structlog.get_logger()

class AgentDebugLogger:
    """Agent debug logger - Singleton"""
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not hasattr(self, '_initialized'):
            self._initialized = True
            self.log_dir = Path("logs/agent_debug")
            self.log_dir.mkdir(parents=True, exist_ok=True)
            self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
            self._buffer = []
    
    def log_agent_call(self, agent_role, agent_name, task_input, prompt, output, tools_used, tokens, elapsed, success, error=None):
        """Log a single agent call"""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "session": self.session_id,
            "agent": {
                "role": agent_role,
                "name": agent_name,
            },
            "input": str(task_input)[:2000],
            "prompt": str(prompt)[:3000] if prompt else "",
            "output": str(output)[:3000] if output else "",
            "tools_used": tools_used or [],
            "tokens": tokens or 0,
            "elapsed": f"{elapsed:.2f}s" if elapsed else "0s",
            "success": success,
            "error": str(error)[:500] if error else None,
        }
        self._buffer.append(entry)
        
        # 每10条写入一次
        if len(self._buffer) >= 10:
            self.flush()
    
    def log_pipeline_start(self, workflow, spec_file, phases):
        """Log pipeline start"""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "session": self.session_id,
            "event": "pipeline_start",
            "workflow": workflow,
            "spec_file": spec_file,
            "phases": [p.get("name", p) for p in phases],
        }
        self._buffer.append(entry)
    
    def log_pipeline_end(self, passed, degraded, total_time):
        """Log pipeline end"""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "session": self.session_id,
            "event": "pipeline_end",
            "passed": passed,
            "degraded": degraded,
            "total_time": f"{total_time:.1f}s",
        }
        self._buffer.append(entry)
        self.flush()
    
    def flush(self):
        """Write buffer to file"""
        if not self._buffer:
            return
        log_file = self.log_dir / f"debug_{self.session_id}.jsonl"
        with open(log_file, 'a', encoding='utf-8') as f:
            for entry in self._buffer:
                f.write(json.dumps(entry, ensure_ascii=False) + '\n')
        self._buffer = []
    
    def get_session_log(self, session_id=None):
        """Read session log"""
        sid = session_id or self.session_id
        log_file = self.log_dir / f"debug_{sid}.jsonl"
        if log_file.exists():
            with open(log_file, 'r', encoding='utf-8') as f:
                return [json.loads(line) for line in f if line.strip()]
        return []
    
    def list_sessions(self):
        """List all debug sessions"""
        sessions = []
        for f in sorted(self.log_dir.glob("debug_*.jsonl"), reverse=True):
            sid = f.stem.replace("debug_", "")
            size = f.stat().st_size
            sessions.append({"session": sid, "file": str(f), "size": size})
        return sessions

# Global instance
debug_logger = AgentDebugLogger()
