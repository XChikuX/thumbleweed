"""
blurhash
========
BlurHash encode/decode for Python, backed by a Rust extension.

This is a compatibility shim — everything is also available via
``import thumbleweed``.

Quick-start
-----------
>>> import blurhash
>>> # From raw RGBA bytes
>>> hash_str = blurhash.encode(rgba_bytes, 4, 3, w, h)
>>> rgba = blurhash.decode(hash_str, 64, 64)

>>> # From / to a Pillow Image (requires  pip install thumbleweed[pillow])
>>> from PIL import Image
>>> img = Image.open("photo.jpg")
>>> hash_str = blurhash.encode_image(img, 4, 3)
>>> placeholder = blurhash.decode_image(hash_str, 64, 64)

>>> # From a BytesIO / bytes / file path — no Pillow required
>>> import io
>>> with open("photo.jpg", "rb") as f:
...     hash_str = blurhash.encode_image(f.read())
>>> buf = io.BytesIO(open("photo.jpg", "rb").read())
>>> hash_str = blurhash.encode_image(buf)
"""

from __future__ import annotations

__all__ = [
    "encode",
    "decode",
    "encode_image",
    "decode_image",
    "__version__",
]

from thumbleweed._core import (  # type: ignore[import]
    __version__,
)
from thumbleweed._core import (
    blurhash_decode as decode,
)
from thumbleweed._core import (
    blurhash_encode as encode,
)
from thumbleweed._core import (
    blurhash_encode_image_bytes as _encode_image_bytes,
)

# ── Internal helpers ─────────────────────────────────────────────────────────


def _read_bytes(source: object) -> bytes:
    """Normalise *source* to raw file bytes (not decoded pixels).

    Accepts bytes / bytearray / memoryview, file-likes, str / Path.
    """
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
    raise TypeError(
        f"encode_image() does not know how to handle {type(source).__name__!r}. "
        "Pass a Pillow Image, bytes, bytearray, BytesIO, or a file path."
    )


# ── Optional Pillow helpers ──────────────────────────────────────────────────


def encode_image(
    image: object,
    cx: int = 4,
    cy: int = 3,
) -> str:
    """Encode an image to a BlurHash string.

    Accepts a wide range of input types:

    - :class:`PIL.Image.Image` — converted to ``RGBA`` directly (requires
      Pillow because the caller supplied a Pillow object).
    - :class:`bytes` / :class:`bytearray` / :class:`memoryview` — treated as
      raw encoded image data (PNG, JPEG, WebP, GIF, BMP, etc.) and decoded in
      Rust. No Pillow required.
    - :class:`io.BytesIO` or any file-like with ``.read()`` — read then
      decoded as above. No Pillow required.
    - :class:`str` / :class:`pathlib.Path` — opened and decoded as above. No
      Pillow required.

    Parameters
    ----------
    image:
        Image source (see above).
    cx:
        Number of horizontal components (1-9). Default 4.
    cy:
        Number of vertical components (1-9). Default 3.

    Returns
    -------
    str
        BlurHash string.

    Raises
    ------
    ImportError
        If Pillow is not installed and ``image`` is a Pillow Image object.
    TypeError
        If the input type is unsupported.
    """
    import pathlib

    # Fast path for encoded image data: decode in Rust, no Pillow required.
    if (
        isinstance(image, (bytes, bytearray, memoryview))
        or isinstance(image, (str, pathlib.Path))
        or hasattr(image, "read")
    ):
        return _encode_image_bytes(_read_bytes(image), cx, cy)

    # Pillow Image support is optional and only needed for actual PIL objects.
    try:
        from PIL import Image  # noqa: PLC0415
    except ImportError as exc:
        raise TypeError(
            f"encode_image() does not know how to handle {type(image).__name__!r}. "
            "Pass a Pillow Image, bytes, bytearray, BytesIO, or a file path."
        ) from exc

    if isinstance(image, Image.Image):
        pil_img: Image.Image = image.convert("RGBA")
        w, h = pil_img.size
        rgba_bytes: bytes = pil_img.tobytes()
        return encode(rgba_bytes, cx, cy, w, h)

    raise TypeError(
        f"encode_image() does not know how to handle {type(image).__name__!r}. "
        "Pass a Pillow Image, bytes, bytearray, BytesIO, or a file path."
    )


def decode_image(
    blur_hash: str,
    width: int = 64,
    height: int = 64,
) -> "Image.Image":  # noqa: F821
    """Decode a BlurHash string to a Pillow :class:`~PIL.Image.Image`.

    Parameters
    ----------
    blur_hash:
        BlurHash string.
    width:
        Output width in pixels. Default 64.
    height:
        Output height in pixels. Default 64.

    Returns
    -------
    PIL.Image.Image
        An ``RGBA`` placeholder image.

    Raises
    ------
    ImportError
        If Pillow is not installed.
    ValueError
        If ``blur_hash`` is invalid.
    """
    _require_pillow()
    from PIL import Image  # noqa: PLC0415

    rgba_bytes = decode(blur_hash, width, height)
    return Image.frombytes("RGBA", (width, height), rgba_bytes)


def _require_pillow() -> None:
    try:
        import PIL  # noqa: F401
    except ImportError as exc:
        raise ImportError(
            "Pillow is required for image helpers. "
            "Install it with:  pip install thumbleweed[pillow]"
        ) from exc
