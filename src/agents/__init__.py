"""
Agents包 — Phase = Agent 命名
"""
from src.agents.spec import SpecAgent
from src.agents.design import DesignAgent
from src.agents.uvm import UvmAgent
from src.agents.model import ModelAgent
from src.agents.rtl import RtlAgent
from src.agents.test import TestAgent
from src.agents.asserts import AssertsAgent
from src.agents.cover import CoverAgent
from src.agents.regress import RegressAgent
from src.agents.debug import DebugAgent
from src.agents.qa import QaAgent
from src.agents.report import ReportAgent

__all__ = [
    "SpecAgent", "DesignAgent", "UvmAgent", "ModelAgent",
    "RtlAgent", "TestAgent", "AssertsAgent", "CoverAgent",
    "RegressAgent", "DebugAgent", "QaAgent", "ReportAgent",
]
