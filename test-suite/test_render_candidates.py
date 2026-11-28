"""Tests for create-preset candidate HTML helpers (crop + draw_text previews)."""

from __future__ import annotations

import io

import sys
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / ".cursor" / "skills" / "create-preset" / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from render_candidates import (  # noqa: E402
    _render_font_sample,
    crop_square,
    downscale_square,
    normalize_crop_align,
)


def _wide_red_blue() -> Image.Image:
    image = Image.new("RGB", (8, 4), (0, 0, 255))
    for x in range(4):
        for y in range(4):
            image.putpixel((x, y), (255, 0, 0))
    return image


def _tall_red_blue() -> Image.Image:
    image = Image.new("RGB", (4, 8), (0, 0, 255))
    for x in range(4):
        for y in range(4):
            image.putpixel((x, y), (255, 0, 0))
    return image


def test_normalize_crop_align_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="crop align"):
        normalize_crop_align("diagonal")


def test_crop_square_wide_keeps_named_side() -> None:
    image = _wide_red_blue()
    left = crop_square(image, "left")
    right = crop_square(image, "right")
    center = crop_square(image, "center")
    assert left.size == (4, 4)
    assert right.size == (4, 4)
    assert center.size == (4, 4)
    assert left.getpixel((1, 1)) == (255, 0, 0)
    assert right.getpixel((1, 1)) == (0, 0, 255)
    assert center.getpixel((0, 1)) == (255, 0, 0)
    assert center.getpixel((3, 1)) == (0, 0, 255)


def test_crop_square_tall_keeps_named_edge() -> None:
    image = _tall_red_blue()
    top = crop_square(image, "top")
    bottom = crop_square(image, "bottom")
    assert top.getpixel((1, 1)) == (255, 0, 0)
    assert bottom.getpixel((1, 1)) == (0, 0, 255)


def test_downscale_square_uses_crop_align() -> None:
    image = _wide_red_blue()
    out = downscale_square(image, size=4, align="left")
    assert out.size == (4, 4)
    assert out.getpixel((1, 1)) == (255, 0, 0)


def test_downscale_square_applies_exif_orientation() -> None:
    # Stored 4×2 (red left, blue right) with orientation 6 → displayed 2×4, red on top.
    image = _wide_red_blue()
    exif = Image.Exif()
    exif[0x0112] = 6
    buf = io.BytesIO()
    image.save(buf, format="JPEG", exif=exif.tobytes(), quality=100)
    buf.seek(0)
    with Image.open(buf) as tagged:
        tagged.load()
        out = downscale_square(tagged, size=2, align="top")
    r, g, b = out.getpixel((1, 0))
    assert r > 150 and b < 100


def test_font_path_preview_matches_draw_text() -> None:
    import filters as F

    font_path = None
    for path in F._SANS_FONT_CANDIDATES:
        if Path(path).is_file():
            font_path = path
            break
    if font_path is None:
        from PIL import ImageFont

        try:
            ImageFont.truetype("DejaVuSans.ttf", 12)
            font_path = "DejaVuSans.ttf"
        except OSError:
            pytest.skip("No TrueType font available")

    backdrop = Image.new("RGB", (120, 80), (240, 230, 220))
    kwargs = {
        "text": "Hi",
        "font_size": 24,
        "color": (20, 10, 5),
        "align": "bottom",
        "font_path": font_path,
    }
    via_preview = _render_font_sample(
        text=kwargs["text"],
        font_style=None,
        font_path=font_path,
        backdrop=backdrop.copy(),
        font_size=kwargs["font_size"],
        color=kwargs["color"],
        align=kwargs["align"],
    )
    via_filter = F.draw_text(backdrop.copy(), **kwargs)
    assert via_preview.tobytes() == via_filter.tobytes()
