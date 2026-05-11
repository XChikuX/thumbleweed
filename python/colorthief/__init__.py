"""
colorthief
==========
Dominant colour and palette extraction for Python, backed by a Rust extension.

This is a compatibility shim — everything is also available via
``import thumbleweed``.

Quick-start
-----------
>>> import colorthief
>>> # From raw image bytes (PNG, JPEG, WebP, …)
>>> dominant = colorthief.get_color(image_bytes)
>>> palette = colorthief.get_palette(image_bytes, color_count=5)

>>> # From a file path
>>> dominant = colorthief.get_color("photo.jpg")
>>> palette = colorthief.get_palette("photo.jpg", color_count=5)

>>> # From a BytesIO object or Pillow Image
>>> import io
>>> buf = io.BytesIO(open("photo.jpg", "rb").read())
>>> dominant = colorthief.get_color(buf)
>>> palette = colorthief.get_palette(buf, color_count=5)
"""

from __future__ import annotations

__all__ = [
    "get_color",
    "get_palette",
    "ColorThief",
    "__version__",
]

from thumbleweed._core import (  # type: ignore[import]
    __version__,
)
from thumbleweed._core import (
    colorthief_get_color_bytes as _get_color_bytes,
)
from thumbleweed._core import (
    colorthief_get_palette_bytes as _get_palette_bytes,
)

# ── Internal helpers ─────────────────────────────────────────────────────────


def _to_image_bytes(source: object) -> bytes:
    """Normalise *source* to raw encoded image bytes (PNG / JPEG / …)."""
    import pathlib

    if isinstance(source, (bytes, bytearray, memoryview)):
        return bytes(source)

    if isinstance(source, (str, pathlib.Path)):
        try:
            with open(source, "rb") as fh:
                return fh.read()
        except FileNotFoundError as exc:
            raise ValueError(f"Image file not found: {source}") from exc

    if hasattr(source, "read"):
        pos = source.tell() if hasattr(source, "tell") else None
        try:
            data = source.read()
        finally:
            if pos is not None and hasattr(source, "seek"):
                source.seek(pos)
        return bytes(data)

    try:
        from PIL import Image  # noqa: PLC0415

        if isinstance(source, Image.Image):
            import io

            buf = io.BytesIO()
            source.convert("RGB").save(buf, format="PNG")
            return buf.getvalue()
    except ImportError:
        pass

    raise TypeError(
        f"colorthief: unsupported input type {type(source).__name__!r}. "
        "Pass bytes, bytearray, BytesIO, a file path, or a Pillow Image."
    )


# ── Public API ───────────────────────────────────────────────────────────────


def get_color(image: object, quality: int = 10) -> tuple[int, int, int]:
    """Extract the dominant colour from any supported image input."""
    return _get_color_bytes(_to_image_bytes(image), quality)


def get_palette(
    image: object,
    color_count: int = 10,
    quality: int = 10,
) -> list[tuple[int, int, int]]:
    """Extract a colour palette from any supported image input."""
    return _get_palette_bytes(_to_image_bytes(image), color_count, quality)


class ColorThief:
    """Extract dominant colours and palettes from an image."""

    def __init__(self, image: object) -> None:
        self._image = _to_image_bytes(image)

    def get_color(self, quality: int = 10) -> tuple[int, int, int]:
        return _get_color_bytes(self._image, quality)

    def get_palette(
        self, color_count: int = 10, quality: int = 10
    ) -> list[tuple[int, int, int]]:
        return _get_palette_bytes(self._image, color_count, quality)
