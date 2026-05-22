import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api.routes import limiter, router
from app.config import settings


logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    for d in (settings.source_dir, settings.upload_dir, settings.result_dir):
        Path(d).mkdir(parents=True, exist_ok=True)
    Path(settings.history_file).parent.mkdir(parents=True, exist_ok=True)
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
app.mount("/source", StaticFiles(directory=settings.source_dir), name="source")
app.mount("/upload", StaticFiles(directory=settings.upload_dir), name="upload")
app.mount("/result", StaticFiles(directory=settings.result_dir), name="result")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
async def customize_page():
    """User 端入口 — 匿名上傳 → 去背 → 渲染。"""
    return FileResponse("/app/customize.html", media_type="text/html")


@app.get("/admin", include_in_schema=False)
async def admin_page():
    """後台 HTML（auth 在前端登入後 POST /api/v1/admin/login 拿 token）。"""
    return FileResponse("/app/admin.html", media_type="text/html")
