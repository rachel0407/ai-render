import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api.routes import limiter, router
from app.config import settings


logger = logging.getLogger(__name__)


def ensure_storage_dirs() -> None:
    for d in (settings.source_dir, settings.upload_dir, settings.result_dir):
        Path(d).mkdir(parents=True, exist_ok=True)
    Path(settings.history_file).parent.mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_storage_dirs()
    if not settings.is_configured():
        logger.warning(
            "[startup] 系統尚未 configured（缺 gemini_api_key / admin_password_hash / "
            "admin_session_secret）。/ 跟 /admin 會被導到 /setup wizard。"
        )
    yield


app = FastAPI(title="ai-render", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api/v1")
ensure_storage_dirs()
app.mount("/source", StaticFiles(directory=settings.source_dir), name="source")
app.mount("/upload", StaticFiles(directory=settings.upload_dir), name="upload")
app.mount("/result", StaticFiles(directory=settings.result_dir), name="result")


@app.get("/health")
async def health():
    return {"status": "ok", "configured": settings.is_configured()}


@app.get("/", include_in_schema=False)
async def customize_page():
    """User 端入口。沒 configured 先導去 setup wizard。"""
    if not settings.is_configured():
        return RedirectResponse(url="/setup", status_code=303)
    return FileResponse("/app/frontend/customize.html", media_type="text/html")


@app.get("/admin", include_in_schema=False)
async def admin_page():
    if not settings.is_configured():
        return RedirectResponse(url="/setup", status_code=303)
    return FileResponse("/app/frontend/admin.html", media_type="text/html")


@app.get("/setup", include_in_schema=False)
async def setup_page():
    """Setup wizard。已 configured 後仍可開啟（頁面內部會顯示「已設定完成」訊息）。"""
    return FileResponse("/app/frontend/setup.html", media_type="text/html")
