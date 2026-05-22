from abc import ABC, abstractmethod
from pathlib import Path


class RenderProvider(ABC):
    """Image-rendering provider. Implementations must support both modes:
    - render: two-image mode (product base + design reference + optional position hint)
    - render_composite: single-image mode (frontend already composited base + design)
    Both return base64-encoded image bytes (PNG/JPEG/WebP)."""

    name: str = "unknown"

    @abstractmethod
    async def render(
        self,
        source_path: Path,
        upload_path: Path,
        position_hint: dict | None = None,
    ) -> str: ...

    @abstractmethod
    async def render_composite(self, composite_path: Path) -> str: ...
