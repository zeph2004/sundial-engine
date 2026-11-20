from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any, Dict, Optional

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

TOKEN_EXPIRY_SECONDS: int = 24 * 60 * 60  # 24 hours
bearer_scheme = HTTPBearer(auto_error=False)


def get_admin_user() -> str:
    return os.environ.get("SUNDIAL_ADMIN_USER", "admin")


def get_admin_pass() -> str:
    return os.environ.get("SUNDIAL_ADMIN_PASS", "sundial-admin")


def get_secret_key() -> bytes:
    raw = os.environ.get("SUNDIAL_SECRET_KEY", "sundial-dev-secret-key-change-in-production")
    return raw.encode("utf-8")


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(token_part: str) -> bytes:
    padding = "=" * (-len(token_part) % 4)
    return base64.urlsafe_b64decode((token_part + padding).encode("ascii"))


def verify_admin_credentials(username: str, password: str) -> bool:
    """Constant-time verification of single-admin username and password."""
    expected_user = get_admin_user()
    expected_pass = get_admin_pass()
    user_ok = hmac.compare_digest(username.encode("utf-8"), expected_user.encode("utf-8"))
    pass_ok = hmac.compare_digest(password.encode("utf-8"), expected_pass.encode("utf-8"))
    return user_ok and pass_ok


def create_access_token(
    username: Optional[str] = None,
    expires_in: int = TOKEN_EXPIRY_SECONDS,
) -> str:
    """
    Creates a stateless HMAC-SHA256 signed bearer token using Python's standard library
    (`hmac`, `hashlib`, `base64`, `json`, `time`) with a 24-hour default expiry.
    Format: `<base64url(payload_json)>.<base64url(hmac_sha256_signature)>`.
    """
    now = int(time.time())
    payload = {
        "sub": username or get_admin_user(),
        "role": "admin",
        "iat": now,
        "exp": now + int(expires_in),
    }
    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload_b64 = _b64url_encode(payload_bytes)
    sig = hmac.new(get_secret_key(), payload_b64.encode("ascii"), hashlib.sha256).digest()
    sig_b64 = _b64url_encode(sig)
    return f"{payload_b64}.{sig_b64}"


def verify_access_token(token: str) -> Dict[str, Any]:
    """
    Validates an HMAC-SHA256 bearer token and returns its decoded payload dict.
    Raises `HTTPException(401)` if malformed, signature-mismatched, or expired.
    """
    if not token or "." not in token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token format.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    parts = token.split(".")
    if len(parts) != 2:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed authentication token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload_b64, sig_b64 = parts
    expected_sig = hmac.new(
        get_secret_key(), payload_b64.encode("ascii"), hashlib.sha256
    ).digest()
    expected_sig_b64 = _b64url_encode(expected_sig)

    if not hmac.compare_digest(sig_b64.encode("ascii"), expected_sig_b64.encode("ascii")):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token signature.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload_bytes = _b64url_decode(payload_b64)
        payload = json.loads(payload_bytes.decode("utf-8"))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unable to decode token payload.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    exp = payload.get("exp")
    if not isinstance(exp, (int, float)) or time.time() > exp:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication token has expired.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return payload


def require_admin(
    authorization: Optional[str] = Header(default=None, include_in_schema=False),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> Dict[str, Any]:
    """
    FastAPI dependency that validates the `Authorization: Bearer <token>` header
    (compatible both with direct Header injection and Swagger UI's "Authorize" button)
    and raises `HTTPException(401)` if missing, invalid, or expired.
    """
    if credentials is not None and credentials.credentials:
        if credentials.scheme.lower() != "bearer":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authorization header must use 'Bearer <token>' format.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return verify_access_token(credentials.credentials.strip())

    if not authorization or not isinstance(authorization, str):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    scheme, _, token = authorization.strip().partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header must use 'Bearer <token>' format.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return verify_access_token(token.strip())
