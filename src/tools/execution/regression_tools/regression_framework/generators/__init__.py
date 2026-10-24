# src/regression_framework/generators/__init__.py
from .shell import ShellGenerator
from .makefile import MakefileGenerator

__all__ = ['ShellGenerator', 'MakefileGenerator']