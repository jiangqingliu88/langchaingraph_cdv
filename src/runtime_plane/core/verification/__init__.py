"""验证质量门 —— 五个相互独立维度，回答「这次绿得实在吗」。"""
from src.runtime_plane.core.verification.quality import (
    DIMENSIONS, QUALITY_SCHEMA, evaluate, write,
)

__all__ = ["DIMENSIONS", "QUALITY_SCHEMA", "evaluate", "write"]
