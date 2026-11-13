"""
Pipeline 执行服务 —— CLI 和 Web API 共享的验证流水线引擎

单例模式，管理 Agent 生命周期 + 流水线执行 + 运行状态追踪。
"""
from __future__ import annotations
import time, json, uuid, asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime
import structlog

from src.runtime_plane.infrastructure.output_config import make_output_root
from src.orchestration_plane.l2.regression_tools import sim_modes as _sim_modes

from src.orchestration_plane.l2.executors.registry import ExecutorRegistry
from config.settings import Settings


from .execution_loop import ClosedLoopSteps
from .execution_lifecycle import RunLifecycleSteps


class PipelineExecutionService(ClosedLoopSteps, RunLifecycleSteps):
    """流水线执行服务（单例）"""

    _instance: Optional[PipelineExecutionService] = None

    def __init__(self):
        self.settings = Settings.get_instance()
        self.registry = ExecutorRegistry.get_instance()
        self._initialized = False
        self._runs: Dict[str, dict] = {}  # run_id → {state, phases, results, ctx}

    @classmethod
    def get_instance(cls) -> PipelineExecutionService:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

