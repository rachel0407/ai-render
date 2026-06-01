"""Render dispatcher — 目前只有 Gemini 一個 provider。
保留 dispatcher 這層抽象，之後要加新 provider 時改一行 _PROVIDER_CLASSES 就好。"""
import logging
from pathlib import Path

from .base import RenderProvider
from .gemini import GeminiProvider


logger = logging.getLogger(__name__)


_PROVIDER_CLASSES: dict[str, type[RenderProvider]] = {
    "gemini": GeminiProvider,
}

_PROVIDERS: dict[str, RenderProvider] = {}


def _get_provider(name: str) -> RenderProvider:
    if name not in _PROVIDERS:
        cls = _PROVIDER_CLASSES.get(name)
        if cls is None:
            raise ValueError(f"unknown render provider: {name!r}")
        _PROVIDERS[name] = cls()
    return _PROVIDERS[name]


async def render(
    source_path: Path,
    upload_path: Path,
    position_hint: dict | None = None,
) -> str:
    provider = _get_provider("gemini")
    return await provider.render(source_path, upload_path, position_hint=position_hint)


async def render_composite(composite_path: Path) -> str:
    provider = _get_provider("gemini")
    return await provider.render_composite(composite_path)
