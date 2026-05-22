import asyncio
import base64
import logging
import mimetypes
from pathlib import Path

from google import genai
from google.genai import types

from app.config import settings

from .base import RenderProvider


logger = logging.getLogger(__name__)


def _mime_for(path: Path) -> str:
    mime, _ = mimetypes.guess_type(str(path))
    return mime or "application/octet-stream"


def _extract(resp) -> tuple[str | None, str]:
    img_b64, texts = None, []
    if resp.candidates:
        for part in resp.candidates[0].content.parts or []:
            if part.inline_data and part.inline_data.data:
                img_b64 = base64.b64encode(part.inline_data.data).decode("ascii")
            elif part.text:
                texts.append(part.text)
    return img_b64, " ".join(texts).strip()


class GeminiProvider(RenderProvider):
    name = "gemini"

    def __init__(self) -> None:
        self._client = genai.Client(api_key=settings.gemini_api_key)
        self._semaphore = asyncio.Semaphore(settings.max_gemini_concurrency)

    def _build_prompt(self, position_hint: dict | None) -> str:
        prompt = settings.render_prompt
        if position_hint:
            x = round(position_hint["x_pct"] * 100)
            y = round(position_hint["y_pct"] * 100)
            w = round(position_hint["w_pct"] * 100)
            h = round(position_hint["h_pct"] * 100)
            prompt += (
                f"\n\n[User-specified position and size (percentage; origin top-left, X right, Y down)]"
                f"\nDesign top-left: ({x}%, {y}%); design size: {w}% wide × {h}% tall."
                f"\nApply at this proportion and position with ±5% tolerance; "
                f"apply corresponding perspective transformation when not viewed head-on."
            )
        return prompt

    async def render(
        self,
        source_path: Path,
        upload_path: Path,
        position_hint: dict | None = None,
    ) -> str:
        contents = [
            self._build_prompt(position_hint),
            types.Part.from_bytes(
                data=source_path.read_bytes(), mime_type=_mime_for(source_path)
            ),
            types.Part.from_bytes(
                data=upload_path.read_bytes(), mime_type=_mime_for(upload_path)
            ),
        ]
        config = types.GenerateContentConfig(response_modalities=["IMAGE", "TEXT"])

        last_text = ""
        async with self._semaphore:
            for attempt in range(2):
                resp = await self._client.aio.models.generate_content(
                    model=settings.gemini_model,
                    contents=contents,
                    config=config,
                )
                img_b64, last_text = _extract(resp)
                if img_b64:
                    return img_b64
                logger.warning(
                    "Gemini text-only response (attempt %d): %s",
                    attempt + 1,
                    last_text[:300],
                )

        raise RuntimeError(
            f"Gemini returned no image (possibly safety-filtered or text-only). "
            f"Model said: {last_text[:200] or '(empty)'}"
        )

    async def render_composite(self, composite_path: Path) -> str:
        contents = [
            settings.render_composite_prompt,
            types.Part.from_bytes(
                data=composite_path.read_bytes(), mime_type=_mime_for(composite_path)
            ),
        ]
        config = types.GenerateContentConfig(response_modalities=["IMAGE", "TEXT"])

        last_text = ""
        async with self._semaphore:
            for attempt in range(2):
                resp = await self._client.aio.models.generate_content(
                    model=settings.gemini_model,
                    contents=contents,
                    config=config,
                )
                img_b64, last_text = _extract(resp)
                if img_b64:
                    return img_b64
                logger.warning(
                    "Gemini text-only response (composite attempt %d): %s",
                    attempt + 1,
                    last_text[:300],
                )

        raise RuntimeError(
            f"Gemini returned no image (composite mode). "
            f"Model said: {last_text[:200] or '(empty)'}"
        )
