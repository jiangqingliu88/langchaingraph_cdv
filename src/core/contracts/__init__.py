"""数据契约 —— schema 版本、JSONL 读写、事件注册、证据 envelope。

只用标准库；不 import `src.layers`。CLI / Workbench / Executor 都从这里拿
「版本号与序列化规则」，避免同一类文件在多处各写一份 schema 字符串。

它是**契约层**，不是执行层：不做业务判定，只回答「这份数据的形状和版本」。
"""
from src.core.contracts import versions
from src.core.contracts.events import (
    EVENT_TYPES, PRODUCERS, event_producer, register_producer, validate_event_type,
)
from src.core.contracts.evidence import (
    EVIDENCE_PROFILES, build_envelope, validate_envelope,
)
from src.core.contracts.jsonl import (
    append_jsonl, canonical_json, read_jsonl, sha256_json, write_jsonl,
)
from src.core.contracts.quality import (
    DIMENSIONS, ENFORCEMENT_MODES, STATUSES, overall_status,
)

__all__ = [
    "versions",
    "append_jsonl", "canonical_json", "read_jsonl", "sha256_json", "write_jsonl",
    "EVENT_TYPES", "PRODUCERS", "event_producer", "register_producer",
    "validate_event_type",
    "EVIDENCE_PROFILES", "build_envelope", "validate_envelope",
    "DIMENSIONS", "ENFORCEMENT_MODES", "STATUSES", "overall_status",
]
