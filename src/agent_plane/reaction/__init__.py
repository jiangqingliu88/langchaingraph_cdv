"""Independent agents built on openai-agents; domain grouping stays in Agent Plane."""

from .core import ReActAgent, RoleSpec
from .registry import canonical_role, create_agent, role_metadata

__all__ = ["ReActAgent", "RoleSpec", "canonical_role", "create_agent", "role_metadata"]
