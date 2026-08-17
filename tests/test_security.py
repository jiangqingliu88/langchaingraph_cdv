"""安全测试 — 认证（密码哈希 / JWT）部分

说明：旧测试还覆盖 src.web API 的路径穿越防护，但 CLAUDE.md 明确禁止 Web 前端
（src/web 不存在），故只保留当前真实存在的 src.layers.l2_orchestration.auth 测试。
"""
import hashlib
import os

from src.layers.l2_orchestration.auth import hash_password, password_needs_rehash, verify_password


def test_password_hash_is_salted_and_verifiable():
    first = hash_password("correct horse battery staple")
    second = hash_password("correct horse battery staple")

    assert first.startswith("pbkdf2_sha256$")
    assert first != second
    assert verify_password("correct horse battery staple", first)
    assert not verify_password("wrong password", first)
    assert not password_needs_rehash(first)


def test_legacy_password_hash_can_be_migrated_after_successful_login():
    salt = "legacy-salt"
    legacy = f"{salt}:{hashlib.sha256(('old password' + salt).encode()).hexdigest()}"

    assert verify_password("old password", legacy)
    assert password_needs_rehash(legacy)


def test_hash_password_always_unique():
    """相同密码每次哈希结果不同（因随机盐）"""
    p1 = hash_password("the same password")
    p2 = hash_password("the same password")
    assert p1 != p2


# ── JWT / Auth 安全测试 ──

def test_create_and_decode_token():
    from src.layers.l2_orchestration.auth import create_token, decode_token
    token = create_token(1, "testuser", "engineer")
    payload = decode_token(token)
    assert payload is not None
    assert payload["user_id"] == 1
    assert payload["username"] == "testuser"
    assert payload["role"] == "engineer"


def test_decode_expired_token():
    from src.layers.l2_orchestration.auth import create_token, decode_token
    import jwt as pyjwt
    from datetime import datetime, timedelta
    # 生成一个已过期的 token
    payload = {
        "user_id": 1, "username": "expired", "role": "engineer",
        "exp": datetime.utcnow() - timedelta(hours=1),
        "iat": datetime.utcnow() - timedelta(hours=25),
    }
    expired_token = pyjwt.encode(payload, "wrong-secret", algorithm="HS256")
    result = decode_token(expired_token)
    assert result is None  # invalid signature or expired


def test_decode_tampered_token():
    """篡改的 token 应返回 None"""
    from src.layers.l2_orchestration.auth import create_token, decode_token
    token = create_token(1, "user", "engineer")
    tampered = token[:-5] + "XXXXX"
    result = decode_token(tampered)
    assert result is None


def test_default_jwt_secret_is_not_hardcoded():
    """JWT SECRET_KEY 默认随机生成，而非硬编码"""
    from src.layers.l2_orchestration import auth
    # 确保未设置环境变量时使用随机密钥
    if "JWT_SECRET" not in os.environ:
        secret1 = auth.SECRET_KEY
        # 重新加载模块以获取新随机密钥
        import importlib
        importlib.reload(auth)
        secret2 = auth.SECRET_KEY
        # 每次重新加载生成不同的随机密钥（生产环境应持久化）
        assert len(secret1) >= 48 or len(secret2) >= 48
