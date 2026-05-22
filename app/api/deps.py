from fastapi import Header, HTTPException, status

from app.services import admin_auth


async def verify_admin_token(authorization: str | None = Header(default=None)):
    """admin.html 走 Bearer token；失敗 → 401。"""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
        )
    token = authorization[7:].strip()
    if not admin_auth.verify_token(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or expired token",
        )
