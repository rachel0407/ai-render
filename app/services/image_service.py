import base64
import binascii
import json
import re
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

import shortuuid

from app.config import settings


_MAGIC = [
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpg"),
    (b"GIF87a", "gif"),
    (b"GIF89a", "gif"),
]
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
_PREVIEW_MARKERS = ("(正)", "（正）")
_FRONT_MARKERS = ("(正)", "（正）")
_BACK_MARKERS = ("(背)", "（背）")
_FOLDER_NAME_RE = re.compile(r"^[\w\-]{1,64}$", re.UNICODE)


def _detect_ext(data: bytes) -> str:
    for magic, ext in _MAGIC:
        if data.startswith(magic):
            return ext
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    raise ValueError("unsupported image format (need png/jpg/gif/webp)")


def _strip_data_url(s: str) -> str:
    s = s.strip()
    if s.startswith("data:") and "," in s:
        return s.split(",", 1)[1]
    return s


def _is_safe_name(name: str) -> bool:
    return bool(name) and "/" not in name and "\\" not in name and ".." not in name


def _read_printable_area(folder: Path) -> dict:
    f = folder / "printable_area.json"
    if not f.is_file():
        return {}
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


# ============ Source folders ============

def list_source_folders() -> list[dict]:
    """列出 source_image 下每個 folder（一個 folder = 一個產品/類別）。
    preview = 檔名含 "(正)" 或 "（正）" 的；找不到則 fallback 至第一張。"""
    src = Path(settings.source_dir)
    if not src.exists():
        return []
    folders = []
    for entry in sorted(src.iterdir()):
        if not entry.is_dir():
            continue
        files = sorted(
            f.name for f in entry.iterdir()
            if f.is_file() and f.suffix.lower() in _IMAGE_EXTS
        )
        preview = (
            next((f for f in files if any(m in f for m in _PREVIEW_MARKERS)), files[0])
            if files else None
        )
        front_file = next((f for f in files if any(m in f for m in _FRONT_MARKERS)), None)
        back_file = next((f for f in files if any(m in f for m in _BACK_MARKERS)), None)
        folders.append({
            "name": entry.name,
            "preview": preview,
            "files": files,
            "printable_area": _read_printable_area(entry),
            "front": front_file,
            "back": back_file,
        })
    return folders


def list_folder_files_with_size(folder_name: str) -> list[dict]:
    """列出某 folder 內所有圖檔的 filename + size。folder 不存在或不合法回 []。"""
    if not _is_safe_name(folder_name):
        return []
    folder = Path(settings.source_dir) / folder_name
    if not folder.is_dir():
        return []
    out = []
    for f in sorted(folder.iterdir()):
        if not f.is_file() or f.suffix.lower() not in _IMAGE_EXTS:
            continue
        out.append({"filename": f.name, "size": f.stat().st_size})
    return out


def resolve_source_folder(name: str) -> Path | None:
    if not _is_safe_name(name):
        return None
    p = Path(settings.source_dir) / name
    return p if p.is_dir() else None


def list_folder_images(folder: Path) -> list[Path]:
    return sorted(
        f for f in folder.iterdir()
        if f.is_file() and f.suffix.lower() in _IMAGE_EXTS
    )


def create_source_folder(name: str) -> Path:
    """建立 source_image/{name}/。name 必須只含 word chars + hyphen，1~64 字元。
    folder 已存在會 raise ValueError。"""
    if not _FOLDER_NAME_RE.match(name):
        raise ValueError("folder name must be 1-64 word characters or hyphens")
    folder = Path(settings.source_dir) / name
    if folder.exists():
        raise ValueError(f"folder '{name}' already exists")
    folder.mkdir(parents=True, exist_ok=False)
    return folder


def delete_source_folder(name: str) -> bool:
    """刪除整個 source_image/{name}/ folder（含內部所有檔）。folder 不存在回 False。"""
    if not _is_safe_name(name):
        raise ValueError("invalid folder name")
    folder = Path(settings.source_dir) / name
    if not folder.is_dir():
        return False
    shutil.rmtree(folder)
    return True


def save_source_image(folder_name: str, raw: bytes, original_filename: str) -> tuple[Path, str]:
    """存底圖到 source_image/{folder}/{stem}__{shortuuid8}.{ext}。
    用 magic byte 偵測格式；副檔名一律依偵測結果寫入。"""
    if not _is_safe_name(folder_name):
        raise ValueError("invalid folder name")
    folder = Path(settings.source_dir) / folder_name
    if not folder.is_dir():
        raise ValueError(f"folder '{folder_name}' not found")
    ext = _detect_ext(raw)
    stem = (original_filename or "image").rsplit(".", 1)[0]
    safe_stem = re.sub(r"[^\w\-.()（）]", "_", stem)[:60] or "image"
    name = f"{safe_stem}__{shortuuid.uuid()[:8]}.{ext}"
    path = folder / name
    path.write_bytes(raw)
    return path, name


def delete_source_image(folder_name: str, filename: str) -> bool:
    """刪 source_image/{folder}/{filename}。檔不存在回 False。"""
    if not _is_safe_name(folder_name) or not _is_safe_name(filename):
        raise ValueError("invalid folder or file name")
    path = Path(settings.source_dir) / folder_name / filename
    if not path.is_file():
        return False
    path.unlink()
    return True


# ============ Upload / Result（user 上傳原圖 + AI 合成結果，永久保留） ============

def decode_base64_image(b64: str) -> bytes:
    try:
        return base64.b64decode(_strip_data_url(b64), validate=True)
    except (binascii.Error, ValueError) as e:
        raise ValueError(f"invalid base64: {e}")


def save_base64_image(b64: str, prefix: str) -> tuple[Path, str]:
    raw = decode_base64_image(b64)
    ext = _detect_ext(raw)
    name = f"{prefix}__{shortuuid.uuid()[:8]}.{ext}"
    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
    path = Path(settings.upload_dir) / name
    path.write_bytes(raw)
    return path, name


def save_result_image(b64: str, prefix: str) -> str:
    raw = base64.b64decode(b64)
    ext = _detect_ext(raw)
    name = f"{prefix}__{shortuuid.uuid()[:8]}.{ext}"
    Path(settings.result_dir).mkdir(parents=True, exist_ok=True)
    (Path(settings.result_dir) / name).write_bytes(raw)
    return name


# ============ History（append-only JSONL） ============

def append_history(
    source_folder: str,
    result_filename: str,
    user_filename: str | None = None,
) -> dict:
    """記一筆渲染紀錄到 history.jsonl。回傳寫入的 entry dict。"""
    entry = {
        "id": shortuuid.uuid()[:12],
        "ts": datetime.now(timezone.utc).isoformat(),
        "source_folder": source_folder,
        "user_filename": user_filename,
        "result_filename": result_filename,
    }
    path = Path(settings.history_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def list_history(page: int = 1, per_page: int = 50) -> tuple[list[dict], int]:
    """讀 history.jsonl 反向倒序（最新優先）並分頁。回傳 (entries, total)。"""
    path = Path(settings.history_file)
    if not path.is_file():
        return [], 0
    lines: list[dict] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                lines.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    total = len(lines)
    lines.reverse()
    start = (page - 1) * per_page
    return lines[start:start + per_page], total
