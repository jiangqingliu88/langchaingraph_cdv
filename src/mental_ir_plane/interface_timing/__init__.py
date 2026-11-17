"""接口时序 IR 功能块，仍属于 Architecture 4.0 的 IR Plane。"""

from .bridge import to_specification_document
from .model import (
    SCHEMA,
    ClockSpec,
    InterfaceTimingIR,
    SignalBinding,
    SourceAnchor,
    TimingContractError,
    TimingRule,
    source_hash,
    temporal_from_dict,
)

__all__ = [
    "SCHEMA",
    "ClockSpec",
    "InterfaceTimingIR",
    "SignalBinding",
    "SourceAnchor",
    "TimingContractError",
    "TimingRule",
    "source_hash",
    "temporal_from_dict",
    "to_specification_document",
]
