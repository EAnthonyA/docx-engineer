import os

import bcrypt
from fastapi import Cookie, HTTPException, Response
from itsdangerous import BadSignature, SignatureExpired, TimestampSigner

SESSION_COOKIE = "session"
_SESSION_MAX_AGE = 60 * 60 * 24 * 30  # 30 days


def _signer() -> TimestampSigner:
    secret = os.environ.get("SESSION_SECRET", "dev-secret-change-me-in-production")
    return TimestampSigner(secret)


def create_session(response: Response) -> None:
    token = _signer().sign("admin").decode()
    secure = os.environ.get("SECURE_COOKIES", "false").lower() == "true"
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=_SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=secure,
    )


def clear_session(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE)


def verify_session(session: str | None = Cookie(default=None, alias=SESSION_COOKIE)) -> bool:
    if not session:
        raise HTTPException(401, "Not authenticated")
    try:
        _signer().unsign(session, max_age=_SESSION_MAX_AGE)
        return True
    except (BadSignature, SignatureExpired):
        raise HTTPException(401, "Session expired or invalid")


def verify_password(plain: str) -> bool:
    hashed = os.environ.get("ADMIN_PASSWORD_HASH", "")
    if hashed:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    # Dev fallback: plaintext password via ADMIN_PASSWORD env var
    dev_password = os.environ.get("ADMIN_PASSWORD", "admin")
    return plain == dev_password
