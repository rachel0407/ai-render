import asyncio
import base64
import logging
from pathlib import Path

import httpx

from app.config import settings

from .base import RenderProvider


logger = logging.getLogger(__name__)


class OpenClawProvider(RenderProvider):
    """Routes image-edit calls through the host-side openclaw-bridge HTTP service,
    which wraps `openclaw infer image edit` and uses OpenClaw's configured OAuth
    profile (e.g. ChatGPT/Codex subscription) instead of a per-token API key."""

    name = "openclaw"

    def __init__(self) -> None:
        self._semaphore = asyncio.Semaphore(settings.max_openclaw_concurrency)
        self._http_timeout = max(settings.openclaw_timeout_ms / 1000.0 + 10.0, 30.0)

    async def _call_bridge(self, prompt: str, image_paths: list[Path]) -> str:
        images_b64 = [
            base64.b64encode(p.read_bytes()).decode("ascii") for p in image_paths
        ]
        headers: dict[str, str] = {}
        if settings.openclaw_bridge_token:
            headers["Authorization"] = f"Bearer {settings.openclaw_bridge_token}"
        payload = {
            "prompt": prompt,
            "images_base64": images_b64,
            "model": settings.openclaw_model,
            "output_format": "png",
            "timeout_ms": settings.openclaw_timeout_ms,
        }

        async with self._semaphore:
            async with httpx.AsyncClient(timeout=self._http_timeout) as client:
                resp = await client.post(
                    f"{settings.openclaw_bridge_url.rstrip('/')}/edit",
                    headers=headers,
                    json=payload,
                )

        if resp.status_code != 200:
            raise RuntimeError(
                f"openclaw-bridge returned {resp.status_code}: {resp.text[:400]}"
            )
        data = resp.json()
        if not data.get("success") or not data.get("image_base64"):
            raise RuntimeError(
                f"openclaw-bridge did not return image: "
                f"{(data.get('error') or data)!r}"
            )
        return data["image_base64"]

    def _build_prompt(self, position_hint: dict | None) -> str:
        prompt = settings.render_prompt
        if position_hint:
            x = round(position_hint["x_pct"] * 100)
            y = round(position_hint["y_pct"] * 100)
            w = round(position_hint["w_pct"] * 100)
            h = round(position_hint["h_pct"] * 100)
            prompt += (
                f"\n\nDesign placement on base image: top-left at "
                f"({x}%, {y}%), size {w}% wide × {h}% tall."
            )
        return prompt

    async def render(
        self,
        source_path: Path,
        upload_path: Path,
        position_hint: dict | None = None,
    ) -> str:
        return await self._call_bridge(
            self._build_prompt(position_hint),
            [source_path, upload_path],
        )

    async def render_composite(self, composite_path: Path) -> str:
        return await self._call_bridge(
            settings.render_composite_prompt,
            [composite_path],
        )
