"""Settings 載入優先級：環境變數 > .env > storage/config.json（setup wizard 寫入）> default。

讓首次啟動者可以走 setup wizard 在瀏覽器填 Gemini key + admin 密碼，後端寫進
storage/config.json。已經用 .env 配好的人完全不受影響（環境變數仍優先）。"""

import json
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


_CONFIG_FILE = Path("/app/storage/config.json")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")

    # 必要設定（沒設 = 走 setup wizard）。Default 為空字串而非 None，方便 truthy check。
    gemini_api_key: str = ""
    admin_password_hash: str = ""
    admin_session_secret: str = ""

    gemini_model: str = "gemini-2.5-flash-image"
    render_prompt: str = (
        "請將第二張圖片自然地渲染與合成到第一張圖片上，保留第一張底圖的光影、"
        "透視與整體構圖，融合自然，不要破壞底圖原有的元素。"
    )
    render_composite_prompt: str = (
        "The input image is a product mockup: the user has already placed their design onto "
        "the target print area on the product surface. Your sole task is to transform the design "
        "region from a 'stuck-on / hard-printed' appearance into a 'naturally printed' appearance."
        "\n\n[ABSOLUTELY DO NOT CHANGE] "
        "Preserve the entire composition exactly: no geometric transformation, perspective shift, "
        "rotation, translation, scaling, distortion, warping, cropping, or relayout. "
        "Preserve the design's position, size, aspect ratio, angle, shape, outline, text content, "
        "graphics, and colors. Preserve the product's shape, color, structure, and viewing angle. "
        "Preserve the overall image dimensions and proportions. Do not add or remove any elements."
        "\n\n[WHAT YOU MUST DO] Only change the surface visual quality of the design: "
        "(1) The design surface should inherit the original lighting, shadows, reflections, and "
        "color temperature of that area in the base image. "
        "(2) Blend the design into the surface texture (paper grain, fabric weave, fiber details, "
        "dark areas). "
        "(3) Edges should not be sharp or glossy — it should look genuinely printed onto the "
        "material, not a sticker pasted on top."
        "\n\nTo repeat: the geometry (position, size, angle, shape) must be pixel-level identical "
        "to the input. You are only responsible for material and lighting integration."
    )

    source_dir: str = "/app/storage/source_image"
    upload_dir: str = "/app/storage/upload_image"
    result_dir: str = "/app/storage/result_image"
    history_file: str = "/app/storage/history.jsonl"

    max_gemini_concurrency: int = 2
    rate_limit_per_min: int = 20

    admin_session_hours: int = 8

    def is_configured(self) -> bool:
        return bool(self.gemini_api_key and self.admin_password_hash and self.admin_session_secret)


def _load_config_file() -> dict:
    if not _CONFIG_FILE.is_file():
        return {}
    try:
        return json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _build_settings() -> Settings:
    """env / .env 先載入；沒設的欄位用 storage/config.json 補（setup wizard 用）。"""
    s = Settings()
    file_cfg = _load_config_file()
    if not s.gemini_api_key and file_cfg.get("gemini_api_key"):
        s.gemini_api_key = file_cfg["gemini_api_key"]
    if not s.admin_password_hash and file_cfg.get("admin_password_hash"):
        s.admin_password_hash = file_cfg["admin_password_hash"]
    if not s.admin_session_secret and file_cfg.get("admin_session_secret"):
        s.admin_session_secret = file_cfg["admin_session_secret"]
    return s


settings = _build_settings()
