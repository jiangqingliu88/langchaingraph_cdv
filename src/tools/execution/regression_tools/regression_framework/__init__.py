# src/regression_framework/__init__.py
from .core.config import ConfigBuilder
from .models.scheduler import Scheduler
from .execution.strategy import MockStrategy, LocalStrategy, LsfStrategy
from .generators.shell import ShellGenerator
from .reporters.html import HtmlReporter
from .reporters.json import JsonReporter
from .reporters.trend_db import TrendDatabase

__all__ = [
    'ConfigBuilder',
    'Scheduler',
    'MockStrategy', 'LocalStrategy', 'LsfStrategy',
    'ShellGenerator',
    'HtmlReporter', 'JsonReporter', 'TrendDatabase'
]