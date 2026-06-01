from typing import Literal

from pydantic import BaseModel, Field


class OverlayPosition(BaseModel):
    x_pct: float = Field(..., ge=0, le=1)
    y_pct: float = Field(..., ge=0, le=1)
    w_pct: float = Field(..., gt=0, le=1)
    h_pct: float = Field(..., gt=0, le=1)


class RenderRequest(BaseModel):
    source_folder: str = Field(..., description="底圖資料夾名稱（必須位於 source_image 下）")
    image_base64: str = Field(..., description="要疊加的圖片 base64（可含 data: 前綴）。is_composite=True 時這張已是 client 合成好的 mockup")
    overlay_position: OverlayPosition | None = None
    is_composite: bool = Field(False, description="True = image_base64 已經是 client 合成好的 mockup，跳過 source folder 迭代，直接 Gemini 處理")
    user_image_base64: str | None = Field(None, description="composite 模式可選；附原始上傳的設計圖，方便後台查詢")


class RenderResultItem(BaseModel):
    source_filename: str
    result_filename: str | None = None
    result_base64: str | None = None
    error: str | None = None


class RenderResponse(BaseModel):
    success: bool
    upload_filename: str
    results: list[RenderResultItem]


class RenderJobCreateResponse(BaseModel):
    job_id: str
    status: Literal["pending", "running", "succeeded", "failed"]


class RenderJobStatusResponse(BaseModel):
    job_id: str
    status: Literal["pending", "running", "succeeded", "failed"]
    upload_filename: str | None = None
    results: list[RenderResultItem] | None = None
    error: str | None = None


class RemoveBackgroundRequest(BaseModel):
    image_base64: str


class RemoveBackgroundResponse(BaseModel):
    image_base64: str


# ============ Admin ============

class AdminLoginRequest(BaseModel):
    password: str


class AdminLoginResponse(BaseModel):
    token: str
    expires_at: int


class HistoryEntry(BaseModel):
    id: str
    ts: str                       # ISO 8601
    source_folder: str
    user_filename: str | None = None
    user_url: str | None = None
    result_filename: str
    result_url: str


class HistoryResponse(BaseModel):
    entries: list[HistoryEntry]
    total: int
    page: int
    per_page: int


class FolderImage(BaseModel):
    filename: str
    url: str
    size: int                     # bytes


class FolderInfo(BaseModel):
    name: str
    image_count: int
    images: list[FolderImage]


class FoldersResponse(BaseModel):
    folders: list[FolderInfo]


class CreateFolderRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)


class CreateFolderResponse(BaseModel):
    success: bool
    name: str


class UploadFolderImageResponse(BaseModel):
    success: bool
    folder: str
    filename: str
    url: str
    size: int


# ============ Setup wizard ============

class SetupStatusResponse(BaseModel):
    configured: bool
    needs_gemini_key: bool
    needs_admin_password: bool


class SetupRequest(BaseModel):
    gemini_api_key: str = Field(..., min_length=10, description="Google AI Studio 拿的 Gemini API key")
    admin_password: str = Field(..., min_length=6, description="後台登入密碼（前端輸入；後端 bcrypt hash）")


class SetupResponse(BaseModel):
    success: bool
