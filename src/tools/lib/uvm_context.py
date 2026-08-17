"""
共享上下文 —— 供所有 UVM 工具使用的线程安全单例

用法:
    from src.tools.lib.uvm_context import ctx
    ctx.set(output_dir=Path("output"), agents=[], env_name="dut_env")
    print(ctx.output_dir)
"""
import threading
from pathlib import Path
from typing import List, Optional


class UvmToolContext:
    """UVM 工具共享运行时上下文（线程安全单例）。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._output_dir: Optional[str] = None
        self._agents: List = []
        self._env_name: str = "dut"

    def set(self, *, output_dir, agents, env_name):
        with self._lock:
            self._output_dir = str(output_dir)
            self._agents = list(agents) if agents else []
            self._env_name = env_name or "dut"

    def update_agents(self, agents: List):
        with self._lock:
            self._agents = list(agents)

    def update_env_name(self, env_name: str):
        with self._lock:
            self._env_name = env_name

    @property
    def output_dir(self) -> str:
        if self._output_dir:
            return self._output_dir
        from src.layers.l1_infrastructure.output_config import make_output_root
        return str(Path(make_output_root()).resolve())

    @property
    def agents(self) -> List:
        return self._agents

    @property
    def env_name(self) -> str:
        return self._env_name or "dut"

    def reset(self):
        with self._lock:
            self._output_dir = None
            self._agents = []
            self._env_name = "dut"


ctx = UvmToolContext()
