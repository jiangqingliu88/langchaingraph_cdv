"""Lint AutoFix Agent（惰性导出，避免 import 包即拉 SDK）。"""

from src.agent_plane._lazy import make_getattr

__all__ = ['LintAutoFixAgent', 'create_agent']

_LAZY = {
    'LintAutoFixAgent': (f"{__name__}.agent", 'LintAutoFixAgent'),
    'create_agent': (f"{__name__}.agent", 'create_agent'),
}

__getattr__ = make_getattr(globals(), _LAZY, __name__)
