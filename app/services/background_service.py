"""rembg/birefnet-general 去背服務。

rembg.remove 是同步 + CPU bound，直接在 event loop 跑會卡死整個 worker
（render-jobs 也會被卡）。所以走獨立 ThreadPoolExecutor。

模型：birefnet-general（~880MB）— 比 u2net / isnet 在 logo / 文字 / 細邊緣的
品質都好上一截；代價是 image 變大 + 每張多 1-2 秒。
"""
import asyncio
import io
import logging
from concurrent.futures import ThreadPoolExecutor

from PIL import Image
from rembg import new_session, remove

logger = logging.getLogger(__name__)

_MODEL_NAME = "birefnet-general"

# max_workers=2：兩張同時跑就會把單核打滿，再多只是排隊吃 RAM。
# birefnet 比 u2net 吃更多 RAM（單張可能 ~1.5GB），維持 2 避免 OOM。
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="rembg")

# Lazy init — Dockerfile 已把模型 bake 進 image，這裡只是 read from disk + 建 onnx session。
# 第一次呼叫的 worker 會建 session；rembg 內部對 onnx session 是 thread-safe，
# 兩個 worker 同時搶到 None 最多就是建兩次（罕見、無害）。
_session = None

# 使用者上傳的圖可能很大（手機原圖 4000px+），先 downscale 到長邊 1600px。
# 紙袋 / logo 設計這個解析度綽綽有餘，再大只是讓 onnxruntime 多吃 CPU 跟 RAM。
_MAX_DIM = 1600


def _get_session():
    global _session
    if _session is None:
        _session = new_session(_MODEL_NAME)
        logger.info("[bg-removal] %s session initialized", _MODEL_NAME)
    return _session


def _remove_sync(raw: bytes) -> bytes:
    img = Image.open(io.BytesIO(raw))
    if max(img.size) > _MAX_DIM:
        img.thumbnail((_MAX_DIM, _MAX_DIM), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        raw = buf.getvalue()
    return remove(raw, session=_get_session())


async def remove_background(raw: bytes) -> bytes:
    """回傳透明 PNG bytes。失敗讓 exception 往外拋，由 route 轉成 5xx。"""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, _remove_sync, raw)
