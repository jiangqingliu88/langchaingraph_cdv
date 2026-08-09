"""
安全与合规 — 审计不可篡改 + 最小权限 + 速率限制 + 输入净化

四层防护:
  1. AuditChain — 审计日志哈希链，确保不可篡改
  2. PrincipleOfLeastPrivilege — 最小权限强制执行器
  3. RateLimiter — API 速率限制（令牌桶算法）
  4. InputSanitizer — 输入净化和注入防护

用法:
  from src.infra.security import (
      AuditChain, RateLimiter, InputSanitizer, get_rate_limiter
  )

  # 审计链：每条记录包含前一条的 hash
  chain = AuditChain()
  chain.append({"action": "signoff_approve", "user": "admin"})
  chain.verify()  # → True（未被篡改）

  # 速率限制：每分钟 60 次
  limiter = get_rate_limiter()
  limiter.check("api:/pipeline/run", max_calls=60, window_s=60)

  # 输入净化
  sanitized = InputSanitizer.sanitize_html(user_input)
"""

from __future__ import annotations
import hashlib
import hmac
import json
import os
import re
import time
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


# ═══════════════════════════════════════════════════════════
# 1. 审计链 — 哈希链表确保不可篡改
# ═══════════════════════════════════════════════════════════

@dataclass
class AuditChainEntry:
    """审计链条目 — 包含前一条的 hash"""
    index: int
    timestamp: str
    data: Dict[str, Any]
    prev_hash: str
    hash: str


class AuditChain:
    """审计哈希链 — 每条记录链接到前一条，确保不可篡改

    原理: hash_n = SHA256(data_n + hash_{n-1})
    验证: 逐条重新计算 hash，任何修改都会导致链断裂
    """

    def __init__(self, chain_name: str = "default"):
        self.chain_name = chain_name
        self._entries: List[AuditChainEntry] = []
        self._secret = os.environ.get("AUDIT_CHAIN_SECRET", "signoffai-chain-secret")
        self._lock = threading.Lock()

    def _compute_hash(self, data: dict, prev_hash: str, index: int, timestamp: str) -> str:
        """计算审计链 hash — HMAC-SHA256"""
        payload = json.dumps({
            "index": index, "timestamp": timestamp,
            "data": data, "prev_hash": prev_hash,
        }, sort_keys=True, ensure_ascii=False)
        return hmac.new(
            self._secret.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def append(self, data: dict) -> AuditChainEntry:
        """追加一条审计记录"""
        with self._lock:
            index = len(self._entries)
            prev_hash = self._entries[-1].hash if self._entries else "0" * 64
            timestamp = datetime.now().isoformat()

            entry_hash = self._compute_hash(data, prev_hash, index, timestamp)
            entry = AuditChainEntry(
                index=index, timestamp=timestamp,
                data=data, prev_hash=prev_hash, hash=entry_hash,
            )
            self._entries.append(entry)
            return entry

    def verify(self) -> Tuple[bool, str]:
        """验证审计链完整性 — 从头到尾逐条重算"""
        with self._lock:
            if not self._entries:
                return True, "空链"

            prev_hash = "0" * 64
            for i, entry in enumerate(self._entries):
                # 检查 index 连续性
                if entry.index != i:
                    return False, f"索引断裂: 预期 {i}, 实际 {entry.index}"

                # 检查前驱 hash
                if entry.prev_hash != prev_hash:
                    return False, f"哈希链断裂于条目 {i}: 前驱 hash 不匹配"

                # 重算 hash
                expected = self._compute_hash(entry.data, entry.prev_hash, entry.index, entry.timestamp)
                if entry.hash != expected:
                    return False, f"条目 {i} 被篡改: hash 不匹配"

                prev_hash = entry.hash

            return True, f"链完整: {len(self._entries)} 条记录"

    def get_chain_info(self) -> dict:
        with self._lock:
            return {
                "chain_name": self.chain_name,
                "total_entries": len(self._entries),
                "first_entry": self._entries[0].timestamp if self._entries else "",
                "last_entry": self._entries[-1].timestamp if self._entries else "",
                "last_hash": self._entries[-1].hash if self._entries else "",
                "verified": self.verify()[0],
            }

    def export_chain(self) -> List[dict]:
        with self._lock:
            return [{
                "index": e.index, "timestamp": e.timestamp,
                "data": e.data, "prev_hash": e.prev_hash[-16:],
                "hash": e.hash[-16:],
            } for e in self._entries]


# ═══════════════════════════════════════════════════════════
# 2. 最小权限强制执行器
# ═══════════════════════════════════════════════════════════

class PrincipleOfLeastPrivilege:
    """最小权限原则 — 强制执行器

    检查项:
      - 管理员操作必须显式声明
      - 批量操作需要二次确认
      - 敏感数据访问需要审批
      - 不允许跨项目越权访问
    """

    # 敏感操作列表 — 必须由管理员或经理执行
    SENSITIVE_ACTIONS = {
        "signoff_approve", "signoff_reject", "user_create", "user_delete",
        "project_delete", "evidence_delete", "system_config_change",
    }

    # 批量操作阈值 — 超过此数量需要二次确认
    BATCH_THRESHOLD = 50

    @staticmethod
    def is_sensitive_action(action: str) -> bool:
        return action in PrincipleOfLeastPrivilege.SENSITIVE_ACTIONS

    @staticmethod
    def requires_elevated_role(action: str) -> Tuple[bool, str]:
        """返回 (是否需要提权, 最低角色要求)"""
        if action in ("signoff_approve", "signoff_reject", "user_create",
                       "project_delete", "evidence_delete", "system_config_change"):
            return True, "verification_manager"
        if action in ("user_delete",):
            return True, "admin"
        return False, "engineer"

    @staticmethod
    def validate_batch_operation(count: int, action: str) -> Tuple[bool, str]:
        """批量操作校验"""
        if count > PrincipleOfLeastPrivilege.BATCH_THRESHOLD:
            return False, f"批量操作超过阈值 ({count} > {PrincipleOfLeastPrivilege.BATCH_THRESHOLD})，需要分批执行"
        if count > PrincipleOfLeastPrivilege.BATCH_THRESHOLD // 2:
            return True, f"批量操作 {count} 条，需要二次确认"
        return True, ""

    @staticmethod
    def check_cross_project_access(user_projects: List[int], target_project: int) -> bool:
        """检查跨项目访问"""
        return target_project in user_projects or target_project == 0


# ═══════════════════════════════════════════════════════════
# 3. 速率限制器 — 令牌桶算法
# ═══════════════════════════════════════════════════════════

@dataclass
class RateLimitResult:
    allowed: bool
    remaining: int
    reset_after_s: float
    retry_after_s: float = 0.0


class RateLimiter:
    """令牌桶速率限制器 — 按 key (用户/IP/endpoint) 分别限制"""

    def __init__(self):
        self._buckets: Dict[str, dict] = {}
        self._lock = threading.Lock()

    def check(self, key: str, max_calls: int = 60, window_s: float = 60.0) -> RateLimitResult:
        """检查是否允许请求

        Args:
            key: 限制键 (如 "user:admin" 或 "ip:192.168.1.1" 或 "api:/pipeline/run")
            max_calls: 时间窗口内最大调用次数
            window_s: 时间窗口（秒）
        """
        now = time.time()
        with self._lock:
            bucket = self._buckets.get(key)

            if bucket is None or (now - bucket["window_start"]) > window_s:
                # 新窗口
                self._buckets[key] = {
                    "tokens": max_calls - 1,
                    "window_start": now,
                    "max_calls": max_calls,
                    "window_s": window_s,
                }
                return RateLimitResult(allowed=True, remaining=max_calls - 1,
                                       reset_after_s=window_s)

            if bucket["tokens"] > 0:
                bucket["tokens"] -= 1
                reset_after = window_s - (now - bucket["window_start"])
                return RateLimitResult(allowed=True, remaining=bucket["tokens"],
                                       reset_after_s=round(reset_after, 1))

            # 限流
            reset_after = window_s - (now - bucket["window_start"])
            return RateLimitResult(allowed=False, remaining=0,
                                   reset_after_s=round(reset_after, 1),
                                   retry_after_s=round(reset_after + 0.5, 1))

    def reset(self, key: str = None):
        """重置限制器"""
        with self._lock:
            if key:
                self._buckets.pop(key, None)
            else:
                self._buckets.clear()

    def get_status(self, key: str = None) -> dict:
        """获取限制器状态"""
        with self._lock:
            if key:
                bucket = self._buckets.get(key)
                if not bucket:
                    return {"key": key, "status": "no_limit"}
                return {
                    "key": key,
                    "remaining": bucket["tokens"],
                    "max_calls": bucket["max_calls"],
                    "window_s": bucket["window_s"],
                    "reset_after_s": round(bucket["window_s"] - (time.time() - bucket["window_start"]), 1),
                }
            return {
                "total_buckets": len(self._buckets),
                "buckets": {
                    k: {"remaining": v["tokens"], "max": v["max_calls"]}
                    for k, v in list(self._buckets.items())[:20]
                },
            }


# 预定义速率限制配置
RATE_LIMITS = {
    "login": {"max_calls": 10, "window_s": 60},        # 登录：10次/分钟
    "api_default": {"max_calls": 300, "window_s": 60},  # 通用API：300次/分钟
    "pipeline_run": {"max_calls": 10, "window_s": 60},  # 流水线启动：10次/分钟
    "evidence_export": {"max_calls": 5, "window_s": 60},# 证据导出：5次/分钟
    "signoff_approve": {"max_calls": 20, "window_s": 60},# 签核审批：20次/分钟
}


# ═══════════════════════════════════════════════════════════
# 4. 输入净化器
# ═══════════════════════════════════════════════════════════

class InputSanitizer:
    """输入净化 — 防 XSS、SQL 注入、路径遍历"""

    # 危险模式
    _XSS_PATTERNS = [
        (re.compile(r'<script[^>]*>.*?</script>', re.IGNORECASE | re.DOTALL), '[script blocked]'),
        (re.compile(r'javascript\s*:', re.IGNORECASE), '[js blocked]'),
        (re.compile(r'on\w+\s*=\s*"[^"]*"', re.IGNORECASE), '[event blocked]'),
        (re.compile(r'on\w+\s*=\s*\'[^\']*\'', re.IGNORECASE), '[event blocked]'),
        (re.compile(r'<iframe[^>]*>', re.IGNORECASE), '[iframe blocked]'),
    ]

    _SQL_INJECTION_PATTERNS = [
        re.compile(r"(\bUNION\b.*\bSELECT\b|\bSELECT\b.*\bFROM\b.*\bWHERE\b)", re.IGNORECASE),
        re.compile(r"(--\s*$|#\s Use\b)", re.IGNORECASE),
        re.compile(r"(\bDROP\s+TABLE\b|\bALTER\s+TABLE\b|\bDELETE\s+FROM\b)", re.IGNORECASE),
    ]

    _PATH_TRAVERSAL_PATTERNS = [
        re.compile(r'\.\./'),
        re.compile(r'\.\.\\'),
        re.compile(r'~'),
    ]

    @staticmethod
    def sanitize_html(text: str) -> str:
        """净化 HTML/XSS 攻击"""
        for pattern, replacement in InputSanitizer._XSS_PATTERNS:
            text = pattern.sub(replacement, text)
        return text

    @staticmethod
    def sanitize_sql(text: str) -> str:
        """检测 SQL 注入模式（不修改，返回是否安全）"""
        for pattern in InputSanitizer._SQL_INJECTION_PATTERNS:
            if pattern.search(text):
                return False
        return True

    @staticmethod
    def sanitize_path(path: str) -> str:
        """净化文件路径 — 移除路径遍历"""
        for pattern in InputSanitizer._PATH_TRAVERSAL_PATTERNS:
            path = pattern.sub('', path)
        # 移除多余的 /
        path = re.sub(r'/+', '/', path)
        # 移除开头的 /
        path = path.lstrip('/')
        return path

    @staticmethod
    def sanitize_all(user_input: str) -> Tuple[str, List[str]]:
        """综合净化 — 返回 (净化后文本, 告警列表)"""
        warnings = []
        original = user_input

        # XSS 检查
        cleaned = InputSanitizer.sanitize_html(user_input)
        if cleaned != original:
            warnings.append("XSS 内容已移除")

        # SQL 注入检查
        if not InputSanitizer.sanitize_sql(user_input):
            warnings.append("检测到可疑 SQL 模式")

        # 路径遍历检查
        path_cleaned = InputSanitizer.sanitize_path(user_input)
        if path_cleaned != user_input:
            warnings.append("路径遍历字符已移除")
            cleaned = path_cleaned

        return cleaned, warnings

    @staticmethod
    def validate_email(email: str) -> bool:
        return bool(re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email))

    @staticmethod
    def validate_username(username: str) -> bool:
        return bool(re.match(r'^[a-zA-Z0-9_]{3,30}$', username))


# ═══════════════════════════════════════════════════════════
# 5. 密钥管理器
# ═══════════════════════════════════════════════════════════

class KeyManager:
    """密钥管理器 — 环境变量 + 文件 + 轮转"""

    @staticmethod
    def get_secret(key: str, default: str = None) -> Optional[str]:
        """获取密钥 — 优先级: 环境变量 > secrets 文件 > default"""
        # 1. 环境变量
        value = os.environ.get(key)
        if value:
            return value

        # 2. secrets 文件
        secrets_dir = os.environ.get("SECRETS_DIR", ".secrets")
        secrets_file = os.path.join(secrets_dir, key.lower())
        if os.path.exists(secrets_file):
            try:
                with open(secrets_file, "r") as f:
                    return f.read().strip()
            except Exception:
                pass

        # 3. 默认值（仅开发环境）
        if os.environ.get("APP_ENV", "development") == "development":
            return default

        return None

    @staticmethod
    def rotate_secret(key: str, new_value: str):
        """轮转密钥"""
        secrets_dir = os.environ.get("SECRETS_DIR", ".secrets")
        os.makedirs(secrets_dir, exist_ok=True)
        secrets_file = os.path.join(secrets_dir, key.lower())
        # 备份旧密钥
        if os.path.exists(secrets_file):
            backup = f"{secrets_file}.bak.{int(time.time())}"
            os.rename(secrets_file, backup)
        with open(secrets_file, "w") as f:
            f.write(new_value)
        os.chmod(secrets_file, 0o600)

    @staticmethod
    def list_keys() -> List[str]:
        secrets_dir = os.environ.get("SECRETS_DIR", ".secrets")
        if not os.path.isdir(secrets_dir):
            return []
        return [f for f in os.listdir(secrets_dir) if not f.endswith('.bak')]


# ═══════════════════════════════════════════════════════════
# 全局实例
# ═══════════════════════════════════════════════════════════

_audit_chain: Optional[AuditChain] = None
_rate_limiter: Optional[RateLimiter] = None


def get_audit_chain() -> AuditChain:
    global _audit_chain
    if _audit_chain is None:
        _audit_chain = AuditChain()
    return _audit_chain


def get_rate_limiter() -> RateLimiter:
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = RateLimiter()
    return _rate_limiter
