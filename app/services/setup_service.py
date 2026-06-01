"""Setup wizard service：首次啟動沒有 Gemini key / admin 密碼時，從瀏覽器收資料、
寫到 storage/config.json、in-memory 更新 settings。

config.json 路徑 = config._CONFIG_FILE = /app/storage/config.json（mount 在 host 的 ./storage）。
"""

import json
import logging
import secrets

import bcrypt

from app.config import _CONFIG_FILE, settings


logger = logging.getLogger(__name__)


def write_config(gemini_api_key: str, admin_password: str) -> None:
    """把使用者填的資料寫到 storage/config.json，並 in-memory 同步到 settings。
    admin_password 會被 bcrypt hash（cost 12）；session_secret 自動產 32 字元 urlsafe。"""
    if not gemini_api_key or not admin_password:
        raise ValueError("gemini_api_key 與 admin_password 都必填")

    # 讀現有檔（避免覆蓋其他人之前寫入的欄位；目前只有這三欄但保留 forward-compat）
    existing: dict = {}
    if _CONFIG_FILE.is_file():
        try:
            existing = json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            existing = {}

    # bcrypt hash 密碼
    pw_hash = bcrypt.hashpw(admin_password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("ascii")

    # session_secret：保留舊的（若有），否則隨機產一個
    session_secret = existing.get("admin_session_secret") or secrets.token_urlsafe(32)

    new_cfg = {
        **existing,
        "gemini_api_key": gemini_api_key,
        "admin_password_hash": pw_hash,
        "admin_session_secret": session_secret,
    }

    # Atomic write：先寫 tmp 再 rename
    _CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _CONFIG_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(new_cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(_CONFIG_FILE)
    logger.info("[setup] config 已寫入 %s", _CONFIG_FILE)

    # In-memory 更新（不用重啟 container 就生效）
    settings.gemini_api_key = gemini_api_key
    settings.admin_password_hash = pw_hash
    settings.admin_session_secret = session_secret
