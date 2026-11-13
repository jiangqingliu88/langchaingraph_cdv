"""tool_sc_red entry point.

Usage: python -m src.generation.uvm_tools.tool_sc_red.main
"""
import sys
from .generate import main as gen_main


if __name__ == "__main__":
    sys.exit(gen_main() or 0)
