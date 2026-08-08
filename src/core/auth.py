"""
JWT 认证模块 —— 用户登录 / Token 签发 / 权限中间件
"""
import hashlib, hmac, os, secrets, jwt
from datetime import datetime, timedelta
from typing import Optional
from fastapi import HTTPException, Request, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

SECRET_KEY = os.environ.get("JWT_SECRET") or secrets.token_urlsafe(48)
ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 24

security = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    """Hash passwords with a salted, work-factor protected KDF."""
    salt = os.urandom(16)
    iterations = 600_000
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, raw_iterations, raw_salt, expected = stored.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(raw_salt), int(raw_iterations)
        ).hex()
        return hmac.compare_digest(digest, expected)
    except (TypeError, ValueError):
        # Compatibility for accounts created before the PBKDF2 migration.  The
        # caller upgrades a successfully authenticated legacy hash immediately.
        try:
            salt, expected = stored.split(":", 1)
            actual = hashlib.sha256((password + salt).encode("utf-8")).hexdigest()
            return hmac.compare_digest(actual, expected)
        except (AttributeError, ValueError):
            return False


def password_needs_rehash(stored: str) -> bool:
    return not stored.startswith("pbkdf2_sha256$")


def create_token(user_id: int, username: str, role: str) -> str:
    payload = {
        "user_id": user_id,
        "username": username,
        "role": role,
        "exp": datetime.utcnow() + timedelta(hours=TOKEN_EXPIRE_HOURS),
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Optional[dict]:
    """从请求中提取当前用户（可选认证）"""
    token = None
    if credentials:
        token = credentials.credentials
    if not token:
        token = request.cookies.get("access_token")
    if not token:
        return None
    if token.startswith("Bearer "):
        token = token[7:]
    payload = decode_token(token)
    return payload


async def require_auth(user: Optional[dict] = Depends(get_current_user)) -> dict:
    """强制认证 —— 未登录返回 401"""
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")
    return user


async def require_admin(user: dict = Depends(require_auth)) -> dict:
    """管理员权限"""
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


async def require_engineer(user: dict = Depends(require_auth)) -> dict:
    """工程师及以上"""
    if user.get("role") not in ("admin", "verification_manager", "senior_engineer", "engineer"):
        raise HTTPException(status_code=403, detail="需要工程师及以上权限")
    return user
