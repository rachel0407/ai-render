import asyncio
import base64
import logging
import time
from pathlib import Path
from urllib.parse import quote

import shortuuid
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.api.deps import verify_admin_token
from app.config import settings
from app.schemas.render import (
    AdminLoginRequest,
    AdminLoginResponse,
    CreateFolderRequest,
    CreateFolderResponse,
    FolderImage,
    FolderInfo,
    FoldersResponse,
    HistoryEntry,
    HistoryResponse,
    RemoveBackgroundRequest,
    RemoveBackgroundResponse,
    RenderJobCreateResponse,
    RenderJobStatusResponse,
    RenderRequest,
    RenderResponse,
    RenderResultItem,
    SetupRequest,
    SetupResponse,
    SetupStatusResponse,
    UploadFolderImageResponse,
)
from app.services import admin_auth, background_service, image_service, setup_service
from app.services.render import dispatcher as render_dispatcher


logger = logging.getLogger(__name__)


limiter = Limiter(key_func=get_remote_address)
router = APIRouter()

_RENDER_JOB_TTL_SECONDS = 30 * 60
_RENDER_JOBS: dict[str, dict] = {}

# 後台上傳的底圖上限。底圖通常是高解析度產品照，給 50 MB 寬鬆。
_SOURCE_IMAGE_MAX_BYTES = 50 * 1024 * 1024


def _public_url(request: Request, path: str) -> str:
    base = str(request.base_url).rstrip("/")
    return f"{base}/{path.lstrip('/')}"


def _cleanup_render_jobs() -> None:
    now = time.time()
    expired = [
        job_id for job_id, job in _RENDER_JOBS.items()
        if now - job.get("created_at", now) > _RENDER_JOB_TTL_SECONDS
    ]
    for job_id in expired:
        _RENDER_JOBS.pop(job_id, None)


async def _prepare_render_upload(body: RenderRequest) -> tuple[Path, Path, str, str | None]:
    folder_path = image_service.resolve_source_folder(body.source_folder)
    if folder_path is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"source folder '{body.source_folder}' not found",
        )

    try:
        upload_path, upload_filename = image_service.save_base64_image(
            body.image_base64, body.source_folder
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    user_filename: str | None = None
    if body.is_composite and body.user_image_base64:
        try:
            _user_path, user_filename = image_service.save_base64_image(
                body.user_image_base64, f"{body.source_folder}_user"
            )
            logger.info("[render composite] 存 user 原圖: %s", user_filename)
        except ValueError as e:
            logger.warning("[render composite] 存 user 原圖失敗: %s", e)

    return folder_path, upload_path, upload_filename, user_filename


async def _render_saved_upload(
    body: RenderRequest,
    folder_path: Path,
    upload_path: Path,
    upload_filename: str,
    user_filename: str | None,
) -> RenderResponse:
    # Composite mode：image_base64 已是 client 合成好的 mockup → 單次 Gemini 呼叫
    if body.is_composite:
        try:
            b64 = await render_dispatcher.render_composite(upload_path)
        except Exception as e:
            logger.warning("composite render failed: %s", e)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"composite render failed: {e}",
            )
        result_filename = image_service.save_result_image(b64, body.source_folder)
        # 寫歷史：composite 模式記 user_filename（user 原圖）作為來源；fallback 是 composite 上傳檔
        image_service.append_history(
            source_folder=body.source_folder,
            result_filename=result_filename,
            user_filename=user_filename or upload_filename,
        )
        return RenderResponse(
            success=True,
            upload_filename=upload_filename,
            results=[RenderResultItem(
                source_filename=f"{body.source_folder}__composite",
                result_filename=result_filename,
                result_base64=b64,
            )],
        )

    # Legacy 雙圖 mode：對 source_folder 每張底圖個別 Gemini call
    source_paths = image_service.list_folder_images(folder_path)
    if not source_paths:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"folder '{body.source_folder}' has no images",
        )

    pos_hint = body.overlay_position.model_dump() if body.overlay_position else None

    async def render_one(src_path: Path) -> RenderResultItem:
        try:
            b64 = await render_dispatcher.render(src_path, upload_path, position_hint=pos_hint)
            result_filename = image_service.save_result_image(b64, src_path.stem)
            image_service.append_history(
                source_folder=body.source_folder,
                result_filename=result_filename,
                user_filename=upload_filename,
            )
            return RenderResultItem(
                source_filename=src_path.name,
                result_filename=result_filename,
                result_base64=b64,
            )
        except Exception as e:
            logger.warning("render %s failed: %s", src_path.name, e)
            return RenderResultItem(source_filename=src_path.name, error=str(e))

    results = await asyncio.gather(*[render_one(p) for p in source_paths])

    if not any(r.result_base64 for r in results):
        msg = "; ".join(r.error or "unknown" for r in results)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"all renders failed: {msg}",
        )

    return RenderResponse(
        success=True,
        upload_filename=upload_filename,
        results=results,
    )


async def _run_render_job(
    job_id: str,
    body: RenderRequest,
    folder_path: Path,
    upload_path: Path,
    upload_filename: str,
    user_filename: str | None,
) -> None:
    job = _RENDER_JOBS.get(job_id)
    if not job:
        return
    job["status"] = "running"
    try:
        response = await _render_saved_upload(
            body, folder_path, upload_path, upload_filename, user_filename
        )
        job["status"] = "succeeded"
        job["upload_filename"] = response.upload_filename
        job["results"] = [r.model_dump() for r in response.results]
    except HTTPException as e:
        job["status"] = "failed"
        job["error"] = str(e.detail)
        logger.warning("[render-job %s] failed: %s", job_id, e.detail)
    except Exception as e:
        job["status"] = "failed"
        job["error"] = str(e)
        logger.exception("[render-job %s] unexpected failure", job_id)


# ============ Setup wizard（未 configured 才開放） ============

@router.get("/setup/status", response_model=SetupStatusResponse)
async def setup_status():
    return SetupStatusResponse(
        configured=settings.is_configured(),
        needs_gemini_key=not bool(settings.gemini_api_key),
        needs_admin_password=not bool(settings.admin_password_hash),
    )


@router.post("/setup", response_model=SetupResponse)
@limiter.limit("5/minute")
async def setup_submit(request: Request, body: SetupRequest):
    """初始化設定。已 configured 後拒絕（避免攻擊者重設密碼）。
    想重置：刪 storage/config.json 並 restart container。"""
    if settings.is_configured():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="system already configured; 想重設請刪 storage/config.json 並重啟",
        )
    try:
        setup_service.write_config(body.gemini_api_key, body.admin_password)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    logger.info("[setup] first-run setup completed")
    return SetupResponse(success=True)


# ============ 公開 endpoints（user 端用，匿名 + IP rate-limit） ============

@router.get("/sources")
async def list_sources():
    """列出 source_image 下每個 folder（一個 folder = 一個產品）。"""
    return {"folders": image_service.list_source_folders()}


@router.post("/remove-background", response_model=RemoveBackgroundResponse)
@limiter.limit(f"{settings.rate_limit_per_min}/minute")
async def remove_background(request: Request, body: RemoveBackgroundRequest):
    """rembg/u2net 去背。回傳透明 PNG base64。"""
    try:
        raw = image_service.decode_base64_image(body.image_base64)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    try:
        out = await background_service.remove_background(raw)
    except Exception as e:
        logger.exception("[remove-bg] failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"background removal failed: {e}",
        )
    return RemoveBackgroundResponse(image_base64=base64.b64encode(out).decode())


@router.post("/render", response_model=RenderResponse)
@limiter.limit(f"{settings.rate_limit_per_min}/minute")
async def render(request: Request, body: RenderRequest):
    folder_path, upload_path, upload_filename, user_filename = await _prepare_render_upload(body)
    return await _render_saved_upload(body, folder_path, upload_path, upload_filename, user_filename)


@router.post("/render-jobs", response_model=RenderJobCreateResponse)
@limiter.limit(f"{settings.rate_limit_per_min}/minute")
async def create_render_job(request: Request, body: RenderRequest):
    _cleanup_render_jobs()
    folder_path, upload_path, upload_filename, user_filename = await _prepare_render_upload(body)
    job_id = shortuuid.uuid()
    _RENDER_JOBS[job_id] = {
        "job_id": job_id,
        "status": "pending",
        "created_at": time.time(),
        "source_folder": body.source_folder,
        "upload_filename": upload_filename,
        "results": None,
        "error": None,
    }
    asyncio.create_task(
        _run_render_job(job_id, body, folder_path, upload_path, upload_filename, user_filename)
    )
    return RenderJobCreateResponse(job_id=job_id, status="pending")


@router.get("/render-jobs/{job_id}", response_model=RenderJobStatusResponse)
async def get_render_job(job_id: str):
    _cleanup_render_jobs()
    job = _RENDER_JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="render job not found")
    return RenderJobStatusResponse(
        job_id=job_id,
        status=job["status"],
        upload_filename=job.get("upload_filename"),
        results=job.get("results"),
        error=job.get("error"),
    )


# ============ Admin endpoints（後台用） ============

@router.post("/admin/login", response_model=AdminLoginResponse)
@limiter.limit("10/minute")
async def admin_login(request: Request, body: AdminLoginRequest):
    if not admin_auth.verify_password(body.password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="密碼錯誤")
    token, exp = admin_auth.issue_token()
    return AdminLoginResponse(token=token, expires_at=exp)


@router.get("/admin/me", dependencies=[Depends(verify_admin_token)])
async def admin_me():
    return {"ok": True}


@router.get(
    "/admin/history",
    response_model=HistoryResponse,
    dependencies=[Depends(verify_admin_token)],
)
async def admin_history(request: Request, page: int = 1, per_page: int = 50):
    page = max(1, page)
    per_page = max(1, min(per_page, 200))
    entries, total = image_service.list_history(page=page, per_page=per_page)
    out = []
    for e in entries:
        user_filename = e.get("user_filename")
        out.append(HistoryEntry(
            id=e.get("id") or "",
            ts=e.get("ts") or "",
            source_folder=e.get("source_folder") or "",
            user_filename=user_filename,
            user_url=_public_url(request, f"upload/{quote(user_filename)}") if user_filename else None,
            result_filename=e.get("result_filename") or "",
            result_url=_public_url(request, f"result/{quote(e.get('result_filename') or '')}"),
        ))
    return HistoryResponse(entries=out, total=total, page=page, per_page=per_page)


@router.get(
    "/admin/folders",
    response_model=FoldersResponse,
    dependencies=[Depends(verify_admin_token)],
)
async def admin_list_folders(request: Request):
    folders = image_service.list_source_folders()
    out = []
    for f in folders:
        images = [
            FolderImage(
                filename=img["filename"],
                url=_public_url(request, f"source/{quote(f['name'])}/{quote(img['filename'])}"),
                size=img["size"],
            )
            for img in image_service.list_folder_files_with_size(f["name"])
        ]
        out.append(FolderInfo(name=f["name"], image_count=len(images), images=images))
    return FoldersResponse(folders=out)


@router.post(
    "/admin/folders",
    response_model=CreateFolderResponse,
    dependencies=[Depends(verify_admin_token)],
)
async def admin_create_folder(body: CreateFolderRequest):
    try:
        image_service.create_source_folder(body.name)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    logger.info("[admin] create folder %s", body.name)
    return CreateFolderResponse(success=True, name=body.name)


@router.delete("/admin/folders/{folder}", dependencies=[Depends(verify_admin_token)])
async def admin_delete_folder(folder: str):
    try:
        ok = image_service.delete_source_folder(folder)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="folder not found")
    logger.info("[admin] delete folder %s", folder)
    return {"success": True, "name": folder}


@router.post(
    "/admin/folders/{folder}/images",
    response_model=UploadFolderImageResponse,
    dependencies=[Depends(verify_admin_token)],
)
async def admin_upload_folder_image(request: Request, folder: str, file: UploadFile = File(...)):
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="empty file")
    if len(raw) > _SOURCE_IMAGE_MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"file too large (max {_SOURCE_IMAGE_MAX_BYTES // (1024 * 1024)} MB)",
        )
    try:
        _, name = image_service.save_source_image(folder, raw, file.filename or "image")
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    url = _public_url(request, f"source/{quote(folder)}/{quote(name)}")
    logger.info("[admin] upload image folder=%s file=%s size=%d KB → %s",
                folder, file.filename, len(raw) // 1024, name)
    return UploadFolderImageResponse(
        success=True, folder=folder, filename=name, url=url, size=len(raw)
    )


@router.delete(
    "/admin/folders/{folder}/images/{filename}",
    dependencies=[Depends(verify_admin_token)],
)
async def admin_delete_folder_image(folder: str, filename: str):
    try:
        ok = image_service.delete_source_image(folder, filename)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="image not found")
    logger.info("[admin] delete image %s/%s", folder, filename)
    return {"success": True}
