"""
Load and encode images with Pillow.
"""

from __future__ import annotations

import math
import os
from io import BytesIO
from typing import Any

from PIL import Image, ImageCms, ImageOps

# Caps for untrusted HTTP uploads (apply-preset / blur).
MAX_UPLOAD_BYTES = 100 * 1024 * 1024  # 100 MiB — full-quality DSLR JPEGs / TIFFs
# Working size: larger uploads are downscaled to fit, not rejected. 64 MP keeps
# full-frame DSLR files (45–61 MP) at native resolution; the heaviest presets
# peak at ~3.7 GiB there.
MAX_IMAGE_SIDE = 12_000
# LIGHTWEIGHT=1 (low-RAM machines, e.g. a 1 GB Raspberry Pi): downscale every
# input to ≤ 2 MP before any filter runs.
LIGHTWEIGHT = os.environ.get("LIGHTWEIGHT", "0").strip() == "1"
MAX_IMAGE_PIXELS = 2_000_000 if LIGHTWEIGHT else 64_000_000  # 64 MP e.g. 9504×6336 (61 MP)
# Hard ceiling, checked from the header before decoding; above this the upload
# is rejected outright (decompression-bomb guard).
MAX_DECODE_PIXELS = 120_000_000  # e.g. a 102 MP medium-format file
# JPEG uploads come back as JPEG at this quality with full-resolution chroma
# (4:4:4); everything else (or a result with transparency) comes back as PNG.
JPEG_OUTPUT_QUALITY = 95

_SRGB = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB"))
_SRGB_BYTES = _SRGB.tobytes()

# Apply once so decode rejects bombs without per-request global mutation
# (Pillow errors at 2× this; `load_image` checks the header against it first).
Image.MAX_IMAGE_PIXELS = MAX_DECODE_PIXELS


class ImageTooLargeError(ValueError):
    """Raised when upload bytes or decoded dimensions exceed configured limits."""


async def read_upload_capped(
    file: Any,
    *,
    max_bytes: int = MAX_UPLOAD_BYTES,
) -> bytes:
    """Read an upload in chunks; reject once size exceeds `max_bytes`."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(64 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise ImageTooLargeError(
                f"Upload exceeds maximum size of {max_bytes} bytes."
            )
        chunks.append(chunk)
    return b"".join(chunks)


def ensure_image_limits(
    image: Image.Image,
    *,
    max_side: int = MAX_IMAGE_SIDE,
    max_pixels: int = MAX_IMAGE_PIXELS,
) -> Image.Image:
    """Reject images that are too wide/tall or have too many pixels."""
    width, height = image.size
    if width > max_side or height > max_side:
        raise ImageTooLargeError(
            f"Image dimensions {width}×{height} exceed maximum side length {max_side}."
        )
    if width * height > max_pixels:
        raise ImageTooLargeError(
            f"Image has {width * height} pixels; maximum is {max_pixels}."
        )
    return image


def fit_size(
    size: tuple[int, int],
    *,
    max_side: int = MAX_IMAGE_SIDE,
    max_pixels: int = MAX_IMAGE_PIXELS,
) -> tuple[int, int]:
    """Largest same-aspect size within `max_side` and `max_pixels` (unchanged if it already fits)."""
    width, height = size
    scale = min(1.0, max_side / max(width, height), math.sqrt(max_pixels / (width * height)))
    if scale >= 1.0:
        return width, height
    # Floor so rounding never lands a pixel over the cap.
    return max(1, int(width * scale)), max(1, int(height * scale))


def fit_image_limits(
    image: Image.Image,
    *,
    max_side: int = MAX_IMAGE_SIDE,
    max_pixels: int = MAX_IMAGE_PIXELS,
) -> Image.Image:
    """Downscale (LANCZOS, aspect kept) an image that exceeds the working size."""
    target = fit_size(image.size, max_side=max_side, max_pixels=max_pixels)
    if target == image.size:
        return image
    if image.mode in ("P", "1"):
        # Palette/bilevel resize is nearest-only in Pillow; expand first for a smooth result.
        image = image.convert("RGBA" if "transparency" in image.info else "RGB")
    return image.resize(target, Image.Resampling.LANCZOS)


def to_working_mode(image: Image.Image) -> Image.Image:
    """
    Normalise any decoded image to 8-bit sRGB `RGB` / `RGBA`.

    16-bit and 32-bit greyscale (TIFF / PNG `I;16`, `I`, `F`) are scaled down
    rather than clipped; an embedded ICC profile (Adobe RGB, ProPhoto, CMYK) is
    converted to sRGB so colours don't shift once the profile is dropped.
    """
    if image.mode.startswith("I;16"):
        image = image.convert("I")
    if image.mode == "I":
        peak = image.getextrema()[1]
        # 16-bit data tops out at 65535; anything at or below 255 is already 8-bit.
        image = image.point(lambda v: v / 257) if peak > 255 else image
        image = image.convert("L")
    elif image.mode == "F":
        # Float data is either 0–1 (scale up) or already 0–255.
        gain = 255.0 if image.getextrema()[1] <= 1.0 else 1.0
        image = image.point(lambda v: v * gain).convert("L")

    icc = image.info.get("icc_profile")
    if icc and image.mode in ("RGB", "RGBA", "CMYK", "L", "LA"):
        alpha = image.getchannel("A") if image.mode in ("RGBA", "LA") else None
        base = image.convert("L") if image.mode == "LA" else image
        base = base.convert("RGB") if base.mode == "RGBA" else base
        try:
            source = ImageCms.ImageCmsProfile(BytesIO(icc))
            converted = ImageCms.profileToProfile(base, source, _SRGB, outputMode="RGB")
        except (ImageCms.PyCMSError, OSError, ValueError):
            converted = None  # broken profile: fall back to a plain mode convert
        if converted is not None:
            image = converted
            if alpha is not None:
                image = image.convert("RGBA")
                image.putalpha(alpha)
        image.info.pop("icc_profile", None)

    if image.mode in ("RGB", "RGBA"):
        return image
    has_alpha = image.mode in ("LA", "PA", "RGBa", "La") or "transparency" in image.info
    return image.convert("RGBA" if has_alpha else "RGB")


def load_image_with_format(
    raw: bytes,
    *,
    max_side: int = MAX_IMAGE_SIDE,
    max_pixels: int = MAX_IMAGE_PIXELS,
    max_decode_pixels: int = MAX_DECODE_PIXELS,
) -> tuple[Image.Image, str | None]:
    """
    Decode image bytes into an 8-bit sRGB `RGB`/`RGBA` image, plus the source
    format (`"JPEG"`, `"PNG"`, …) so the result can be encoded to match.

    Images over `max_decode_pixels` are rejected from the header, before
    decoding. EXIF orientation is applied (camera portrait shots are stored
    sideways). Images over the working size (`max_side` / `max_pixels`) are
    downscaled to fit; JPEGs decode at a reduced scale first (`draft`) so the
    full-size bitmap is never held in memory.
    """
    image = Image.open(BytesIO(raw))
    source_format = image.format
    width, height = image.size
    if width * height > max_decode_pixels:
        raise ImageTooLargeError(
            f"Image has {width * height} pixels; maximum is {max_decode_pixels}."
        )
    # fit_size is symmetric in width/height, so the target holds after rotation.
    target = fit_size(image.size, max_side=max_side, max_pixels=max_pixels)
    if target != image.size and source_format == "JPEG":
        # Picks the smallest DCT scale (1/2, 1/4, 1/8) that is still >= target.
        image.draft(image.mode, target)
    image.load()
    image = ImageOps.exif_transpose(image) or image
    # Colour conversion can drop metadata; keep EXIF so presets can read the
    # capture date. Encoders here never write `info["exif"]`, so it isn't re-emitted.
    exif = image.info.get("exif")
    image = to_working_mode(image)
    image = fit_image_limits(image, max_side=max_side, max_pixels=max_pixels)
    if exif and "exif" not in image.info:
        image.info["exif"] = exif
    return image, source_format


def load_image(
    raw: bytes,
    *,
    max_side: int = MAX_IMAGE_SIDE,
    max_pixels: int = MAX_IMAGE_PIXELS,
    max_decode_pixels: int = MAX_DECODE_PIXELS,
) -> Image.Image:
    """Decode image bytes (see `load_image_with_format`) and return just the image."""
    image, _ = load_image_with_format(
        raw, max_side=max_side, max_pixels=max_pixels, max_decode_pixels=max_decode_pixels
    )
    return image


def save_png_bytes(image: Image.Image) -> bytes:
    """Encode an image as PNG bytes."""
    buffer = BytesIO()
    image.save(buffer, format="PNG", exif=b"")  # never re-emit upload EXIF
    return buffer.getvalue()


def _is_opaque(image: Image.Image) -> bool:
    if image.mode not in ("RGBA", "LA", "PA") and "transparency" not in image.info:
        return True
    return image.convert("RGBA").getchannel("A").getextrema()[0] == 255


def encode_result(image: Image.Image, source_format: str | None) -> tuple[bytes, str]:
    """
    Encode a result to match its upload: JPEG in → high-quality sRGB JPEG out
    (a fraction of a PNG's size and encode time at DSLR resolution); any other
    input, or a result with transparency, → PNG. Returns (bytes, media type).
    Camera EXIF (GPS, serial numbers) is not carried over.
    """
    buffer = BytesIO()
    if source_format == "JPEG" and _is_opaque(image):
        image.convert("RGB").save(
            buffer,
            format="JPEG",
            quality=JPEG_OUTPUT_QUALITY,
            subsampling=0,
            icc_profile=_SRGB_BYTES,
            exif=b"",
        )
        return buffer.getvalue(), "image/jpeg"
    image.save(buffer, format="PNG", icc_profile=_SRGB_BYTES, exif=b"")
    return buffer.getvalue(), "image/png"
