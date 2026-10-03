"""Single-user login: one password (APP_PASSWORD), then a signed cookie valid for 60 days."""
import hmac
import time

from fastapi import HTTPException, Request, Response
from itsdangerous import BadSignature, SignatureExpired, TimestampSigner

from .config import get_settings

COOKIE = "upajna_session"
MAX_AGE = 60 * 24 * 3600
_attempts: dict[str, tuple[int, float]] = {}


def _signer() -> TimestampSigner:
    return TimestampSigner(get_settings().session_secret or "dev-only-secret")


def login(request: Request, response: Response, password: str) -> None:
    ip = request.client.host if request.client else "x"
    count, until = _attempts.get(ip, (0, 0.0))
    if until > time.time():
        raise HTTPException(429, "Too many tries. Wait a few minutes and try again.")
    expected = get_settings().app_password
    if not expected or not hmac.compare_digest(password.encode(), expected.encode()):
        count += 1
        _attempts[ip] = (0, time.time() + 300) if count >= 5 else (count, 0.0)
        raise HTTPException(401, "That password isn't right.")
    _attempts.pop(ip, None)
    secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    response.set_cookie(COOKIE, _signer().sign("ok").decode(), max_age=MAX_AGE, httponly=True, samesite="lax", secure=secure)


def logout(response: Response) -> None:
    response.delete_cookie(COOKIE)


def require_auth(request: Request) -> None:
    token = request.cookies.get(COOKIE)
    try:
        if token and _signer().unsign(token, max_age=MAX_AGE) == b"ok":
            return
    except (BadSignature, SignatureExpired):
        pass
    raise HTTPException(401, "Please sign in.")
