"""Compatibility wrapper for the existing Mental IR source and validator."""

from pathlib import Path

from src.agent_plane.specialists.mental_model.main import generate_mental_ir as _generate_mental_ir
from src.mental_ir_plane import MentalIR


def generate_mental_ir(spec_text: str, *, module: str, spec_path: str = "", output_dir: Path | None = None) -> MentalIR:
    """原文、module 与校验逻辑沿用旧生成器；不把新循环冒充完整设计理解。"""
    return _generate_mental_ir(spec_text, module=module, spec_path=spec_path, output_dir=output_dir)


__all__ = ["generate_mental_ir"]
