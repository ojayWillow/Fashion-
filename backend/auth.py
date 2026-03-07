"""Simple password authentication with session cookies.

The admin password is read from the ADMIN_PASSWORD environment variable.
Sessions use signed cookies via itsdangerous (no database needed).
"""
import os
import time
import hashlib
import secrets
from functools import wraps
from fastapi import Request, Response, HTTPException
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

# Password from env (default for development only)
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "changeme")

# Secret key for signing cookies — generated once per server start
# In production, set SECRET_KEY env var for persistence across restarts
SECRET_KEY = os.environ.get("SECRET_KEY", secrets.token_hex(32))

SESSION_MAX_AGE = 60 * 60 * 24  # 24 hours
COOKIE_NAME = "fashion_session"

serializer = URLSafeTimedSerializer(SECRET_KEY)


def create_session_token() -> str:
    """Create a signed session token."""
    return serializer.dumps({"admin": True, "t": time.time()})


def verify_session_token(token: str) -> bool:
    """Verify a session token is valid and not expired."""
    try:
        data = serializer.loads(token, max_age=SESSION_MAX_AGE)
        return data.get("admin") is True
    except (BadSignature, SignatureExpired):
        return False


def check_password(password: str) -> bool:
    """Check if the provided password matches.

    Uses constant-time comparison to prevent timing attacks.
    """
    return secrets.compare_digest(password, ADMIN_PASSWORD)


def is_authenticated(request: Request) -> bool:
    """Check if the request has a valid session cookie."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return False
    return verify_session_token(token)


def require_auth(request: Request):
    """Raise 401 if the request is not authenticated."""
    if not is_authenticated(request):
        raise HTTPException(status_code=401, detail="Authentication required")
