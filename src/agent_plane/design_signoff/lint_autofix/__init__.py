"""No-op/lint_autofix: functional ReAct adapter, not an architecture plane."""

from .agent import LintAutoFixAgent, create_agent

__all__ = ["LintAutoFixAgent", "create_agent"]
