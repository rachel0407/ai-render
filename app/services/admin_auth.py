"""Admin auth：bcrypt 驗密碼 + HMAC 簽 session token。
Token 格式：base64url(payload).hex(hmac_sha256(secret, payload))
payload 內含 iat, exp。"""

import base64
import hashlib
import hmac
import json
import logging
import secrets
import time

import bcrypt

from app.config import settings


logger = logging.getLogger(__name__)


def verify_password(password: str) -> bool:
    """比對使用者輸入的明文密碼與 .env 內的 bcrypt hash。"""
    if not settings.admin_password_hash:
        logger.error("[admin_auth] ADMIN_PASSWORD_HASH 未設定")
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), settings.admin_password_hash.encode("utf-8"))
    except (ValueError, TypeError) as e:
        logger.warning("[admin_auth] bcrypt verify 失敗: %s", e)
        return False


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _sign(payload: bytes) -> str:
    if not settings.admin_session_secret:
        raise RuntimeError("ADMIN_SESSION_SECRET 未設定")
    mac = hmac.new(
        settings.admin_session_secret.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).digest()
    return mac.hex()


def issue_token() -> tuple[str, int]:
    """產生新 session token。回傳 (token, exp_unix_ts)。"""
    now = int(time.time())
    exp = now + settings.admin_session_hours * 3600
    payload = json.dumps(
        {"iat": now, "exp": exp, "n": secrets.token_hex(8)},
        separators=(",", ":"),
    ).encode("utf-8")
    payload_b64 = _b64url_encode(payload)
    sig = _sign(payload_b64.encode("ascii"))
    return f"{payload_b64}.{sig}", exp


def verify_token(token: str) -> bool:
    """驗 token 簽章 + 過期時間。回傳 True/False。"""
    if not token or "." not in token:
        return False
    payload_b64, sig = token.split(".", 1)
    try:
        expected_sig = _sign(payload_b64.encode("ascii"))
    except RuntimeError:
        return False
    if not hmac.compare_digest(expected_sig, sig):
        return False
    try:
        payload = json.loads(_b64url_decode(payload_b64))
    except (ValueError, json.JSONDecodeError):
        return False
    exp = payload.get("exp", 0)
    return isinstance(exp, int) and time.time() < exp
