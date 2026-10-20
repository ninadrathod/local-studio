"""Unit tests for `app.services.image_io` (service functions only)."""

from __future__ import annotations

import asyncio
from io import BytesIO

import pytest
from PIL import Image

from app.services.image_io import (
    MAX_IMAGE_PIXELS,
    MAX_IMAGE_SIDE,
    MAX_UPLOAD_BYTES,
    ImageTooLargeError,
    ensure_image_limits,
    fit_image_limits,
    fit_size,
    load_image,
    read_upload_capped,
    save_png_bytes,
)


def _png_bytes(size: tuple[int, int] = (10, 10), color=(1, 2, 3)) -> bytes:
    image = Image.new("RGB", size, color=color)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


class _FakeUpload:
    def __init__(self, data: bytes, chunk_size: int = 64 * 1024) -> None:
        self._buf = BytesIO(data)
        self._chunk_size = chunk_size

    async def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            size = self._chunk_size
        return self._buf.read(size)


def test_load_image_decodes_png_bytes() -> None:
    raw = _png_bytes((12, 8), color=(40, 50, 60))
    image = load_image(raw)
    assert image.size == (12, 8)
    assert image.getpixel((0, 0)) == (40, 50, 60)


def test_load_image_rejects_invalid_bytes() -> None:
    with pytest.raises(Exception):
        load_image(b"not-an-image")


def test_load_image_rejects_oversized_dimensions() -> None:
    image = Image.new("RGB", (16, 16), color=(1, 2, 3))
    with pytest.raises(ImageTooLargeError):
        ensure_image_limits(image, max_side=8)


def test_ensure_image_limits_rejects_pixel_count() -> None:
    image = Image.new("RGB", (10, 10), color=(1, 2, 3))
    with pytest.raises(ImageTooLargeError):
        ensure_image_limits(image, max_side=MAX_IMAGE_SIDE, max_pixels=50)


def test_read_upload_capped_returns_bytes() -> None:
    raw = b"abc123"

    async def _run() -> bytes:
        return await read_upload_capped(_FakeUpload(raw), max_bytes=100)

    assert asyncio.run(_run()) == raw


def test_read_upload_capped_rejects_oversize() -> None:
    raw = b"x" * 100

    async def _run() -> bytes:
        return await read_upload_capped(_FakeUpload(raw, chunk_size=16), max_bytes=50)

    with pytest.raises(ImageTooLargeError):
        asyncio.run(_run())


def test_max_upload_constant_is_positive() -> None:
    assert MAX_UPLOAD_BYTES >= 1_000_000


def test_save_png_bytes_writes_png_signature() -> None:
    image = Image.new("RGB", (4, 4), color=(9, 8, 7))
    raw = save_png_bytes(image)
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"


def test_save_png_bytes_round_trips_with_load_image() -> None:
    original = Image.new("RGB", (6, 5), color=(100, 110, 120))
    encoded = save_png_bytes(original)
    reloaded = load_image(encoded)
    assert reloaded.size == original.size
    assert reloaded.getpixel((0, 0)) == (100, 110, 120)


def _jpeg_bytes(size: tuple[int, int], color=(120, 80, 40)) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", size, color=color).save(buffer, format="JPEG", quality=80)
    return buffer.getvalue()


def test_fit_size_keeps_small_and_shrinks_large_within_caps() -> None:
    assert fit_size((4000, 3000)) == (4000, 3000)
    w, h = fit_size((6376, 4254))  # 27.1 MP camera photo
    assert w * h <= MAX_IMAGE_PIXELS
    assert abs(w / h - 6376 / 4254) < 0.01
    w, h = fit_size((12000, 2000))  # panorama over the side cap
    assert w <= MAX_IMAGE_SIDE and abs(w / h - 6) < 0.01


def test_load_image_downscales_over_pixel_cap_instead_of_rejecting() -> None:
    image = load_image(_jpeg_bytes((120, 90)), max_pixels=2_700)
    assert image.size[0] * image.size[1] <= 2_700
    assert abs(image.size[0] / image.size[1] - 120 / 90) < 0.05
    png = load_image(_png_bytes((100, 20)), max_side=50)
    assert png.size == (50, 10)
    assert png.getpixel((0, 0)) == (1, 2, 3)


def test_load_image_uses_jpeg_draft_for_large_photos() -> None:
    # The decoder runs at reduced scale, then LANCZOS lands exactly on target.
    image = load_image(_jpeg_bytes((800, 600)), max_pixels=30_000)
    assert image.size == fit_size((800, 600), max_pixels=30_000)


def test_load_image_rejects_above_decode_ceiling_before_decoding() -> None:
    with pytest.raises(ImageTooLargeError):
        load_image(_png_bytes((100, 100)), max_decode_pixels=5_000)


def test_fit_image_limits_expands_palette_before_resize() -> None:
    palette = Image.new("RGB", (40, 40), (200, 10, 10)).convert("P")
    out = fit_image_limits(palette, max_side=20)
    assert out.size == (20, 20) and out.mode == "RGB"
    same = Image.new("RGB", (10, 10))
    assert fit_image_limits(same) is same


def test_load_image_applies_exif_orientation() -> None:
    # Cameras store portrait shots landscape plus an orientation tag (6 = rotate 90° CW).
    image = Image.new("RGB", (40, 20), (10, 20, 30))
    exif = Image.Exif()
    exif[0x0112] = 6
    buffer = BytesIO()
    image.save(buffer, format="JPEG", exif=exif.tobytes())
    assert load_image(buffer.getvalue()).size == (20, 40)


def test_load_image_converts_embedded_profile_to_srgb() -> None:
    from PIL import ImageCms

    # A LAB-profiled red differs from sRGB red; conversion must change the pixels.
    lab = ImageCms.ImageCmsProfile(ImageCms.createProfile("LAB"))
    srgb = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB"))
    red = Image.new("RGB", (8, 8), (200, 40, 40))
    buffer = BytesIO()
    red.save(buffer, format="PNG", icc_profile=srgb.tobytes())
    same = load_image(buffer.getvalue())
    assert same.mode == "RGB" and "icc_profile" not in same.info
    assert all(abs(a - b) <= 2 for a, b in zip(same.getpixel((0, 0)), (200, 40, 40)))
    # A broken profile falls back to a plain mode conversion instead of failing.
    buffer = BytesIO()
    red.save(buffer, format="PNG", icc_profile=b"not-a-profile")
    assert load_image(buffer.getvalue()).getpixel((0, 0)) == (200, 40, 40)
    del lab


def test_to_working_mode_normalises_16bit_cmyk_and_grey() -> None:
    from app.services.image_io import to_working_mode

    deep = Image.new("I;16", (4, 4), 65535)
    out = to_working_mode(deep)
    assert out.mode == "RGB" and out.getpixel((0, 0)) == (255, 255, 255)
    mid = to_working_mode(Image.new("I;16", (4, 4), 32896))
    assert abs(mid.getpixel((0, 0))[0] - 128) <= 1  # scaled, not clipped to white
    assert to_working_mode(Image.new("CMYK", (4, 4), (0, 0, 0, 0))).mode == "RGB"
    assert to_working_mode(Image.new("LA", (4, 4), (90, 128))).mode == "RGBA"
    assert to_working_mode(Image.new("L", (4, 4), 90)).mode == "RGB"
    rgba = Image.new("RGBA", (4, 4))
    assert to_working_mode(rgba) is rgba


def test_encode_result_matches_upload_format() -> None:
    from app.services.image_io import encode_result

    photo = Image.new("RGB", (16, 16), (120, 80, 40))
    body, media_type = encode_result(photo, "JPEG")
    assert media_type == "image/jpeg" and body[:2] == b"\xff\xd8"
    reloaded = Image.open(BytesIO(body))
    assert reloaded.info.get("icc_profile")  # tagged sRGB
    body, media_type = encode_result(photo, "PNG")
    assert media_type == "image/png" and body[:8] == b"\x89PNG\r\n\x1a\n"
    # Transparency can't survive JPEG, so a cut-out result stays PNG.
    cutout = Image.new("RGBA", (16, 16), (120, 80, 40, 0))
    assert encode_result(cutout, "JPEG")[1] == "image/png"
    opaque_rgba = Image.new("RGBA", (16, 16), (120, 80, 40, 255))
    assert encode_result(opaque_rgba, "JPEG")[1] == "image/jpeg"
    assert encode_result(photo, None)[1] == "image/png"


def _exif_bytes() -> bytes:
    exif = Image.Exif()
    exif.get_ifd(0x8769)[0x9003] = "2019:07:04 18:30:00"  # DateTimeOriginal
    exif[0x0110] = "TestCam"  # camera model, standing in for private metadata
    return exif.tobytes()


def test_load_image_keeps_exif_through_profile_conversion() -> None:
    from PIL import ImageCms

    srgb = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB"))
    buffer = BytesIO()
    Image.new("RGB", (8, 8), (200, 40, 40)).save(
        buffer, format="JPEG", icc_profile=srgb.tobytes(), exif=_exif_bytes()
    )
    loaded = load_image(buffer.getvalue())
    assert "icc_profile" not in loaded.info  # the conversion ran
    assert loaded.getexif().get_ifd(0x8769)[0x9003] == "2019:07:04 18:30:00"


def test_encoders_never_write_upload_exif() -> None:
    from app.services.image_io import encode_result

    photo = Image.new("RGB", (16, 16), (120, 80, 40))
    photo.info["exif"] = _exif_bytes()
    for source_format in ("JPEG", "PNG"):
        body, _ = encode_result(photo, source_format)
        assert not Image.open(BytesIO(body)).getexif()
    assert not Image.open(BytesIO(save_png_bytes(photo))).getexif()
