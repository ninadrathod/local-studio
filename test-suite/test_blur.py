"""Unit tests for `app.services.blur` (service functions only)."""

from __future__ import annotations

from PIL import Image

from app.services.blur import (
    DEFAULT_BLUR_RADIUS,
    apply_blur,
    is_allowed_image,
)


def test_is_allowed_image_accepts_known_content_type() -> None:
    assert is_allowed_image("image/png", None) is True
    assert is_allowed_image("IMAGE/JPEG", "notes.txt") is True


def test_is_allowed_image_accepts_known_extension() -> None:
    assert is_allowed_image(None, "photo.JPG") is True
    assert is_allowed_image("application/octet-stream", "shot.webp") is True


def test_is_allowed_image_accepts_heic() -> None:
    assert is_allowed_image("image/heic", None) is True
    assert is_allowed_image("image/HEIF", None) is True
    assert is_allowed_image("application/octet-stream", "IMG_0001.HEIC") is True
    assert is_allowed_image("", "burst.heif") is True


def test_is_allowed_image_rejects_non_image() -> None:
    assert is_allowed_image(None, None) is False
    assert is_allowed_image("text/plain", "readme.txt") is False
    assert is_allowed_image("application/pdf", "doc.pdf") is False


def test_apply_blur_preserves_size_and_changes_pixels() -> None:
    source = Image.new("RGB", (32, 24), color=(255, 0, 0))
    # Distinct corner so blur has something to average
    source.putpixel((0, 0), (0, 255, 0))

    blurred = apply_blur(source, radius=DEFAULT_BLUR_RADIUS)

    assert blurred.size == source.size
    assert list(blurred.get_flattened_data()) != list(source.get_flattened_data())


def test_apply_blur_converts_non_rgb_modes_to_rgba() -> None:
    source = Image.new("L", (16, 16), color=128)
    blurred = apply_blur(source, radius=2)
    assert blurred.mode == "RGBA"


def test_apply_blur_zero_radius_is_identity_for_rgb() -> None:
    source = Image.new("RGB", (8, 8), color=(10, 20, 30))
    blurred = apply_blur(source, radius=0)
    assert list(blurred.get_flattened_data()) == list(source.get_flattened_data())
