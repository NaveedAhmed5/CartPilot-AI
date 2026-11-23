"""Minimal, dependency-free auth for the website: PBKDF2 password hashes and
HMAC-signed bearer tokens (customer and admin roles)."""

import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
from typing import Any, Dict, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import settings

log = logging.getLogger("cartpilot.auth")

_SECRET = settings.secret_key or secrets.token_urlsafe(32)
if not settings.secret_key:
    log.warning("SECRET_KEY not set: using a random key (website logins reset on restart).")

DEFAULT_ADMIN_PASSWORD = "cartpilot-admin"
ADMIN_PASSWORD = settings.admin_password or DEFAULT_ADMIN_PASSWORD
if not settings.admin_password:
    log.warning("ADMIN_PASSWORD not set: using the default admin password. Set ADMIN_PASSWORD in production.")

TOKEN_TTL_S = 7 * 24 * 3600
_ITERATIONS = 200_000
_bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _ITERATIONS)
    return f"pbkdf2${_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iters, salt_hex, digest_hex = stored.split("$")
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), int(iters))
        return hmac.compare_digest(digest.hex(), digest_hex)
    except Exception:
        return False


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def make_token(sub: str, role: str) -> str:
    payload = _b64(json.dumps({"sub": sub, "role": role, "exp": int(time.time()) + TOKEN_TTL_S}).encode())
    sig = _b64(hmac.new(_SECRET.encode(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{sig}"


def read_token(token: str) -> Optional[Dict[str, Any]]:
    try:
        payload, sig = token.split(".")
        expected = _b64(hmac.new(_SECRET.encode(), payload.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected):
            return None
        data = json.loads(_unb64(payload))
        if int(data.get("exp", 0)) < time.time():
            return None
        return data
    except Exception:
        return None


def _claims(creds: Optional[HTTPAuthorizationCredentials]) -> Dict[str, Any]:
    if not creds or not creds.credentials:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Login required")
    data = read_token(creds.credentials)
    if not data:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired, please log in again")
    return data


def current_user(creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer)) -> str:
    data = _claims(creds)
    if data.get("role") != "user":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Customer login required")
    return str(data["sub"])


def require_admin(creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer)) -> str:
    data = _claims(creds)
    if data.get("role") != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin login required")
    return "admin"


def check_admin_password(password: str) -> bool:
    return hmac.compare_digest(password.encode(), ADMIN_PASSWORD.encode())
