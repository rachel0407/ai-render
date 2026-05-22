from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")

    gemini_api_key: str
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

    # Render provider routing: primary first, on any exception fall back to secondary.
    # Valid names: "gemini", "openclaw". Set fallback to empty string to disable fallback.
    render_primary: str = "gemini"
    render_fallback: str = ""

    # OpenClaw bridge (optional fallback provider). Disabled by default.
    openclaw_bridge_url: str = "http://host.docker.internal:18790"
    openclaw_bridge_token: str = ""
    openclaw_model: str = "openai/gpt-image-2"
    openclaw_timeout_ms: int = 120000
    max_openclaw_concurrency: int = 1

    # Admin 後台登入：bcrypt hash 的密碼 + HMAC session secret
    admin_password_hash: str = ""           # bcrypt 產生，例 $2b$12$...
    admin_session_secret: str = ""          # 隨機 32+ 字元，HMAC 簽 session token 用
    admin_session_hours: int = 8


settings = Settings()
