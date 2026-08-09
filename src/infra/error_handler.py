"""
统一错误处理框架 — 错误码 + 恢复策略 + 异常中间件

涵盖：流程中断、数据库异常、外部工具失败、权限拒绝、数据校验失败
"""
from __future__ import annotations

from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Callable


# ═══════════════════════════════════════════════════════════
# 统一错误码
# ═══════════════════════════════════════════════════════════

class ErrorCode(str, Enum):
    """平台统一错误码 — 模块前缀 + 错误类别"""
    # 通用 1xxx
    INTERNAL_ERROR = "E1000"
    NOT_IMPLEMENTED = "E1001"
    VALIDATION_ERROR = "E1002"

    # 认证/权限 2xxx
    AUTH_INVALID_CREDENTIALS = "E2001"
    AUTH_TOKEN_EXPIRED = "E2002"
    AUTH_PERMISSION_DENIED = "E2003"
    AUTH_RATE_LIMITED = "E2004"

    # 流水线 3xxx
    PIPELINE_NOT_FOUND = "E3001"
    PIPELINE_ALREADY_RUNNING = "E3002"
    PIPELINE_PHASE_FAILED = "E3003"
    PIPELINE_TIMEOUT = "E3004"
    PIPELINE_AGENT_ERROR = "E3005"

    # 签核 4xxx
    SIGNOFF_NOT_FOUND = "E4001"
    SIGNOFF_INVALID_TRANSITION = "E4002"
    SIGNOFF_EVIDENCE_MISSING = "E4003"
    SIGNOFF_CONCURRENT_UPDATE = "E4004"

    # 文档 5xxx
    DOC_NOT_FOUND = "E5001"
    DOC_VERSION_CONFLICT = "E5002"
    DOC_TOO_LARGE = "E5003"

    # 证据 6xxx
    EVIDENCE_NOT_FOUND = "E6001"
    EVIDENCE_HASH_MISMATCH = "E6002"
    EVIDENCE_CHAIN_BROKEN = "E6003"

    # 数据库/存储 7xxx
    DB_CONNECTION_ERROR = "E7001"
    DB_QUERY_ERROR = "E7002"
    DB_MIGRATION_ERROR = "E7003"

    # 外部工具 8xxx
    TOOL_EXECUTION_FAILED = "E8001"
    TOOL_NOT_FOUND = "E8002"
    TOOL_TIMEOUT = "E8003"

    # PPA 9xxx
    PPA_METRIC_NOT_FOUND = "E9001"
    PPA_CONSTRAINT_VIOLATION = "E9002"
    PPA_REPORT_PARSE_ERROR = "E9003"


# ═══════════════════════════════════════════════════════════
# 错误严重级别 + 恢复策略
# ═══════════════════════════════════════════════════════════

class ErrorSeverity(str, Enum):
    CRITICAL = "critical"   # 需立即人工介入
    ERROR = "error"         # 自动重试失败
    WARNING = "warning"     # 可降级继续
    INFO = "info"           # 仅记录


class RecoveryAction(str, Enum):
    RETRY = "retry"             # 自动重试（指数退避）
    FALLBACK = "fallback"       # 降级到备用方案
    SKIP = "skip"               # 跳过继续
    ESCALATE = "escalate"       # 升级到人工处理
    ABORT = "abort"             # 中止流程


# ═══════════════════════════════════════════════════════════
# 错误上下文
# ═══════════════════════════════════════════════════════════

@dataclass
class PlatformError(Exception):
    """平台统一异常"""
    code: ErrorCode
    message: str
    severity: ErrorSeverity = ErrorSeverity.ERROR
    recovery: RecoveryAction = RecoveryAction.ESCALATE
    domain: str = ""            # pipeline / signoff / doc / evidence / ppa
    detail: dict = field(default_factory=dict)
    cause: Optional[Exception] = None
    trace_id: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def __str__(self):
        return f"[{self.code.value}] [{self.domain}] {self.message}"

    def to_dict(self) -> dict:
        return {
            "error_code": self.code.value,
            "message": self.message,
            "severity": self.severity.value,
            "recovery": self.recovery.value,
            "domain": self.domain,
            "detail": self.detail,
            "trace_id": self.trace_id,
            "timestamp": self.timestamp,
        }


# ── 便捷构造 ──

def pipeline_error(code: ErrorCode, message: str,
                   recovery: RecoveryAction = RecoveryAction.ESCALATE, **detail) -> PlatformError:
    return PlatformError(code=code, message=message, domain="pipeline", recovery=recovery, detail=detail)


def signoff_error(code: ErrorCode, message: str,
                  recovery: RecoveryAction = RecoveryAction.ESCALATE, **detail) -> PlatformError:
    return PlatformError(code=code, message=message, domain="signoff", recovery=recovery, detail=detail)


def doc_error(code: ErrorCode, message: str,
              recovery: RecoveryAction = RecoveryAction.ESCALATE, **detail) -> PlatformError:
    return PlatformError(code=code, message=message, domain="doc", recovery=recovery, detail=detail)


def db_error(code: ErrorCode, message: str, cause: Exception = None) -> PlatformError:
    return PlatformError(code=code, message=message, domain="database",
                         severity=ErrorSeverity.CRITICAL, recovery=RecoveryAction.RETRY,
                         cause=cause)


# ═══════════════════════════════════════════════════════════
# 错误恢复策略注册表
# ═══════════════════════════════════════════════════════════

@dataclass
class RecoveryRule:
    code: ErrorCode
    max_retries: int = 3
    backoff_seconds: float = 1.0
    fallback_action: Optional[Callable] = None


class ErrorRecoveryRegistry:
    """错误恢复策略注册表 — 每种错误码匹配一个恢复规则"""

    def __init__(self):
        self._rules: dict[ErrorCode, RecoveryRule] = {
            ErrorCode.DB_CONNECTION_ERROR: RecoveryRule(ErrorCode.DB_CONNECTION_ERROR, max_retries=3, backoff_seconds=2.0),
            ErrorCode.DB_QUERY_ERROR: RecoveryRule(ErrorCode.DB_QUERY_ERROR, max_retries=2, backoff_seconds=1.0),
            ErrorCode.TOOL_EXECUTION_FAILED: RecoveryRule(ErrorCode.TOOL_EXECUTION_FAILED, max_retries=1, backoff_seconds=5.0),
            ErrorCode.TOOL_TIMEOUT: RecoveryRule(ErrorCode.TOOL_TIMEOUT, max_retries=2, backoff_seconds=10.0),
            ErrorCode.PIPELINE_PHASE_FAILED: RecoveryRule(ErrorCode.PIPELINE_PHASE_FAILED, max_retries=1, backoff_seconds=0.0),
            ErrorCode.SIGNOFF_CONCURRENT_UPDATE: RecoveryRule(ErrorCode.SIGNOFF_CONCURRENT_UPDATE, max_retries=3, backoff_seconds=0.5),
            ErrorCode.AUTH_RATE_LIMITED: RecoveryRule(ErrorCode.AUTH_RATE_LIMITED, max_retries=0, backoff_seconds=30.0),
        }

    def get_rule(self, code: ErrorCode) -> Optional[RecoveryRule]:
        return self._rules.get(code)

    def register(self, code: ErrorCode, rule: RecoveryRule):
        self._rules[code] = rule


# ── 全局实例 ──
_recovery_registry: Optional[ErrorRecoveryRegistry] = None


def get_recovery_registry() -> ErrorRecoveryRegistry:
    global _recovery_registry
    if _recovery_registry is None:
        _recovery_registry = ErrorRecoveryRegistry()
    return _recovery_registry


# ═══════════════════════════════════════════════════════════
# FastAPI 异常处理钩子
# ═══════════════════════════════════════════════════════════

def register_error_handlers(app):
    """向 FastAPI app 注册统一错误处理"""

    from fastapi import Request
    from fastapi.responses import JSONResponse

    @app.exception_handler(PlatformError)
    async def platform_error_handler(request: Request, exc: PlatformError):
        return JSONResponse(
            status_code=_http_status(exc.code),
            content=exc.to_dict(),
        )

    @app.exception_handler(Exception)
    async def fallback_handler(request: Request, exc: Exception):
        # 未知异常包装为 PlatformError
        pe = PlatformError(
            code=ErrorCode.INTERNAL_ERROR,
            message=str(exc)[:200],
            severity=ErrorSeverity.CRITICAL,
            recovery=RecoveryAction.ESCALATE,
            domain="system",
            cause=exc,
        )
        return JSONResponse(
            status_code=500,
            content=pe.to_dict(),
        )


def _http_status(code: ErrorCode) -> int:
    """错误码 → HTTP 状态码"""
    prefix = code.value[1]  # 第一个数字
    status_map = {
        "1": 500,  # 内部错误
        "2": 401,  # 认证
        "3": 500,  # 流水线
        "4": 400,  # 签核
        "5": 404,  # 文档
        "6": 404,  # 证据
        "7": 503,  # 数据库
        "8": 502,  # 外部工具
        "9": 400,  # PPA
    }
    return status_map.get(prefix, 500)
