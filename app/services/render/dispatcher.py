import logging
from pathlib import Path

from app.config import settings

from .base import RenderProvider
from .gemini import GeminiProvider
from .openclaw import OpenClawProvider


logger = logging.getLogger(__name__)


_PROVIDER_CLASSES: dict[str, type[RenderProvider]] = {
    "gemini": GeminiProvider,
    "openclaw": OpenClawProvider,
}

_PROVIDERS: dict[str, RenderProvider] = {}


def _get_provider(name: str) -> RenderProvider:
    if name not in _PROVIDERS:
        cls = _PROVIDER_CLASSES.get(name)
        if cls is None:
            raise ValueError(f"unknown render provider: {name!r}")
        _PROVIDERS[name] = cls()
    return _PROVIDERS[name]


async def _dispatch(method: str, *args, **kwargs) -> str:
    primary = settings.render_primary
    fallback = settings.render_fallback or ""

    try:
        provider = _get_provider(primary)
        logger.info("[render] %s via primary=%s", method, primary)
        return await getattr(provider, method)(*args, **kwargs)
    except Exception as primary_exc:
        if not fallback or fallback == primary:
            raise
        logger.warning(
            "[render] primary=%s failed (%s: %s); trying fallback=%s",
            primary, type(primary_exc).__name__, primary_exc, fallback,
        )
        try:
            provider = _get_provider(fallback)
            return await getattr(provider, method)(*args, **kwargs)
        except Exception as fallback_exc:
            raise RuntimeError(
                f"both render providers failed: "
                f"{primary}={primary_exc}; {fallback}={fallback_exc}"
            ) from fallback_exc


async def render(
    source_path: Path,
    upload_path: Path,
    position_hint: dict | None = None,
) -> str:
    return await _dispatch(
        "render", source_path, upload_path, position_hint=position_hint
    )


async def render_composite(composite_path: Path) -> str:
    return await _dispatch("render_composite", composite_path)
