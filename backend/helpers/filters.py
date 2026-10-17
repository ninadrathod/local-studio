"""
Pillow filter ops used by the JSON preset step runner.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Sequence

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont


def _as_rgba(image: Image.Image) -> Image.Image:
    return image.convert("RGBA")


def _as_rgb(image: Image.Image) -> Image.Image:
    return image.convert("RGB")


def _rgb_tint(
    color: Sequence[int] | None = None,
    rgb: Sequence[int] | None = None,
    default: Sequence[int] = (255, 255, 255),
) -> tuple[int, int, int]:
    tint = color if color is not None else rgb
    if tint is None:
        tint = default
    return tuple(int(c) for c in tint)


_SANS_FONT_CANDIDATES = (
    "DejaVuSans.ttf",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
)

_FLOW_FONT_CANDIDATES = (
    "/System/Library/Fonts/Supplemental/Brush Script.ttf",
    "/System/Library/Fonts/Supplemental/Apple Chancery.ttf",
    "/System/Library/Fonts/Supplemental/Bradley Hand Bold.ttf",
    "/usr/share/fonts/truetype/msttcorefonts/Brush_Script_MT_Italic.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSerif-Italic.ttf",
    "DejaVuSans.ttf",
)


def _font_candidates(style: str) -> tuple[str, ...]:
    text = (style or "sans").strip().lower()
    if text in {"flow", "script", "hand", "cursive"}:
        return _FLOW_FONT_CANDIDATES
    return _SANS_FONT_CANDIDATES


def _truetype(path: str, size: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.truetype(path, size, index=0)


@lru_cache(maxsize=32)
def _load_font(
    size: int,
    style: str = "sans",
    font_path: str | None = None,
) -> ImageFont.ImageFont:
    if font_path:
        try:
            return _truetype(font_path, size)
        except OSError as exc:
            raise ValueError(f"Could not load font: {font_path}") from exc
    for path in _font_candidates(style):
        try:
            return _truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def extract_subject_layers(image: Image.Image) -> tuple[Image.Image, Image.Image]:
    """
    Return (subject_rgba, background_rgb).

    Background replaces the subject region with a heavy blur so later filters
    don't double the original subject underneath the cutout.
    """
    from extract_subject import extract_subject as rembg_extract_subject

    original = _as_rgb(image)
    subject = rembg_extract_subject(original)
    mask = subject.getchannel("A")
    blurred = original.filter(ImageFilter.GaussianBlur(radius=40))
    background = Image.composite(blurred, original, mask)
    return subject, background


def brightness(image: Image.Image, amount: float = 1.0) -> Image.Image:
    base = _as_rgb(image)
    out = ImageEnhance.Brightness(base).enhance(float(amount))
    if image.mode == "RGBA":
        out = out.convert("RGBA")
        out.putalpha(image.getchannel("A"))
    return out


def color(image: Image.Image, amount: float = 1.0) -> Image.Image:
    base = _as_rgb(image)
    out = ImageEnhance.Color(base).enhance(float(amount))
    if image.mode == "RGBA":
        out = out.convert("RGBA")
        out.putalpha(image.getchannel("A"))
    return out


def contrast(image: Image.Image, amount: float = 1.0) -> Image.Image:
    base = _as_rgb(image)
    out = ImageEnhance.Contrast(base).enhance(float(amount))
    if image.mode == "RGBA":
        out = out.convert("RGBA")
        out.putalpha(image.getchannel("A"))
    return out


def overlay(
    image: Image.Image,
    rgb: Sequence[int] = (255, 200, 110),
    alpha: float = 0.2,
    color: Sequence[int] | None = None,
) -> Image.Image:
    base = _as_rgb(image)
    tint = _rgb_tint(color, rgb, (255, 200, 110))
    color_layer = Image.new("RGB", base.size, tint)
    out = Image.blend(base, color_layer, alpha=float(alpha))
    if image.mode == "RGBA":
        out = out.convert("RGBA")
        out.putalpha(image.getchannel("A"))
    return out


def grayscale(image: Image.Image) -> Image.Image:
    gray = _as_rgb(image).convert("L").convert("RGB")
    if image.mode == "RGBA":
        gray = gray.convert("RGBA")
        gray.putalpha(image.getchannel("A"))
    return gray


def glow_border(
    image: Image.Image,
    rgb: Sequence[int] = (0, 255, 200),
    width: int = 8,
    blur: float = 12.0,
    color: Sequence[int] | None = None,
) -> Image.Image:
    """Add a soft colored glow around an RGBA subject's alpha edge."""
    subject = _as_rgba(image)
    alpha = subject.getchannel("A")
    tint = _rgb_tint(color, rgb, (0, 255, 200))

    # MaxFilter size must be odd
    dilate = max(3, int(width) * 2 + 1)
    if dilate % 2 == 0:
        dilate += 1
    glow_mask = alpha.filter(ImageFilter.MaxFilter(size=dilate))
    glow_mask = glow_mask.filter(ImageFilter.GaussianBlur(radius=float(blur)))

    glow = Image.new("RGBA", subject.size, (*tint, 0))
    glow.putalpha(glow_mask)
    return Image.alpha_composite(glow, subject)


def glow_line_border(
    image: Image.Image,
    color: Sequence[int] | None = None,
    rgb: Sequence[int] | None = None,
    width: int = 4,
    blur: float = 1.5,
) -> Image.Image:
    """
    Draw a glowing outline around the subject only (ring), without filling the body.

    Accepts `color` or `rgb` as [R, G, B].
    """
    from PIL import ImageChops

    subject = _as_rgba(image)
    tint_rgb = _rgb_tint(color, rgb, (0, 255, 200))

    alpha = subject.getchannel("A")
    dilate = max(3, int(width) * 2 + 1)
    if dilate % 2 == 0:
        dilate += 1

    # Outer silhouette minus subject fill → border ring only
    outer = alpha.filter(ImageFilter.MaxFilter(size=dilate))
    ring = ImageChops.subtract(outer, alpha)
    if float(blur) > 0:
        ring = ring.filter(ImageFilter.GaussianBlur(radius=float(blur)))

    line = Image.new("RGBA", subject.size, (*tint_rgb, 0))
    line.putalpha(ring)
    # Subject stays on top so its pixels are not tinted by the glow
    return Image.alpha_composite(line, subject)


_RESAMPLE = {
    "lanczos": Image.Resampling.LANCZOS,
    "bicubic": Image.Resampling.BICUBIC,
    "bilinear": Image.Resampling.BILINEAR,
}


def upscale(
    image: Image.Image,
    long_edge: int = 1920,
    max_scale: float = 4.0,
    resample: str = "lanczos",
) -> Image.Image:
    """
    Enlarge so the longer side reaches `long_edge` px (aspect ratio kept).

    Never shrinks: images already at/above `long_edge` are returned unchanged.
    The enlargement factor is capped at `max_scale`.
    """
    target = int(long_edge)
    if target < 1:
        raise ValueError("long_edge must be >= 1")
    cap = float(max_scale)
    if cap < 1.0:
        raise ValueError("max_scale must be >= 1.0")
    mode = (resample or "lanczos").strip().lower()
    if mode not in _RESAMPLE:
        raise ValueError(f"resample must be one of {sorted(_RESAMPLE)}")

    width, height = image.size
    factor = min(target / max(width, height), cap)
    if factor <= 1.0:
        return image.copy()
    size = (max(1, int(round(width * factor))), max(1, int(round(height * factor))))
    return image.resize(size, _RESAMPLE[mode])


def sharpen(
    image: Image.Image,
    radius: float = 2.0,
    percent: int = 120,
    threshold: int = 3,
) -> Image.Image:
    """Unsharp-mask sharpening (alpha preserved)."""
    base = _as_rgb(image)
    out = base.filter(
        ImageFilter.UnsharpMask(radius=float(radius), percent=int(percent), threshold=int(threshold))
    )
    if image.mode == "RGBA":
        out = out.convert("RGBA")
        out.putalpha(image.getchannel("A"))
    return out


def denoise(image: Image.Image, size: int = 3) -> Image.Image:
    """Median filter to soften noise / JPEG blocking (`size` odd, >= 3)."""
    window = int(size)
    if window < 3 or window % 2 == 0:
        raise ValueError("size must be an odd integer >= 3")
    base = _as_rgb(image)
    out = base.filter(ImageFilter.MedianFilter(size=window))
    if image.mode == "RGBA":
        out = out.convert("RGBA")
        out.putalpha(image.getchannel("A"))
    return out


def ai_upscale(
    image: Image.Image,
    long_edge: int = 1920,
    max_scale: float = 4.0,
    denoise: float = 0.5,
    max_input_pixels: int = 1_000_000,
    tile: int = 256,
) -> Image.Image:
    """
    Real-ESRGAN 4× super-resolution (local ONNX), then Lanczos to the target size.

    Longer side reaches `long_edge` px (factor capped at `max_scale`; never shrinks).
    Inputs above `max_input_pixels` are reduced before the model so the 4× pass
    stays bounded. `denoise` is 0.0 (keep grain) – 1.0 (smoothest). Alpha is
    resized with Lanczos.
    """
    import numpy as np

    from upscale_model import super_resolve

    target = int(long_edge)
    if target < 1:
        raise ValueError("long_edge must be >= 1")
    cap = float(max_scale)
    if cap < 1.0:
        raise ValueError("max_scale must be >= 1.0")
    budget = int(max_input_pixels)
    if budget < 1:
        raise ValueError("max_input_pixels must be >= 1")

    width, height = image.size
    factor = min(target / max(width, height), cap)
    if factor <= 1.0:
        return image.copy()
    size = (max(1, int(round(width * factor))), max(1, int(round(height * factor))))

    src = _as_rgb(image)
    if width * height > budget:
        shrink = (budget / (width * height)) ** 0.5
        src = src.resize(
            (max(1, int(width * shrink)), max(1, int(height * shrink))), Image.Resampling.LANCZOS
        )
    hires = Image.fromarray(super_resolve(np.asarray(src), denoise=denoise, tile=tile))
    out = hires.resize(size, Image.Resampling.LANCZOS)
    if image.mode == "RGBA":
        out = out.convert("RGBA")
        out.putalpha(image.getchannel("A").resize(size, Image.Resampling.LANCZOS))
    return out


def composite(base: Image.Image, overlay: Image.Image) -> Image.Image:
    """Paste overlay (with alpha) on top of base."""
    bottom = _as_rgba(base)
    top = _as_rgba(overlay)
    if top.size != bottom.size:
        top = top.resize(bottom.size, Image.Resampling.LANCZOS)
    return Image.alpha_composite(bottom, top)


def place_on_canvas(
    image: Image.Image,
    scale: float = 1.4,
    fill: Sequence[int] | None = None,
    color: Sequence[int] | None = None,
    rgb: Sequence[int] | None = None,
    layout: str = "polaroid",
) -> Image.Image:
    """
    Place `image` on a larger solid canvas.

    `scale` multiplies width and height (e.g. 1.4 → 40% larger).
    `layout`:
      - `center` — equal margins all sides
      - `polaroid` — side margins equal; photo shifted up so the bottom band is larger
    """
    photo = _as_rgba(image)
    factor = float(scale)
    if factor < 1.0:
        raise ValueError("scale must be >= 1.0")

    canvas_w = max(1, int(round(photo.size[0] * factor)))
    canvas_h = max(1, int(round(photo.size[1] * factor)))
    tint = _rgb_tint(color if color is not None else fill, rgb, (255, 255, 255))
    canvas = Image.new("RGBA", (canvas_w, canvas_h), (*tint, 255))

    side = max(0, (canvas_w - photo.size[0]) // 2)
    leftover_y = max(0, canvas_h - photo.size[1])
    mode = (layout or "polaroid").strip().lower()
    if mode == "center":
        top = leftover_y // 2
    else:
        # Match side margin on top when possible; remainder becomes the caption band.
        top = min(side, leftover_y)
    canvas.paste(photo, (side, top), photo)
    return canvas


def draw_text(
    image: Image.Image,
    text: str = "",
    font_size: int = 48,
    color: Sequence[int] | None = None,
    rgb: Sequence[int] | None = None,
    x: int | None = None,
    y: int | None = None,
    align: str = "center",
    font_style: str = "sans",
    font_path: str | None = None,
    stroke_width: int = 0,
    stroke_color: Sequence[int] | None = None,
    margin: int = 16,
) -> Image.Image:
    """
    Draw `text` onto an image.

    `align`: `center`, `top`, `bottom`, `top_right`, `top_left`, `bottom_center`
    (ignored when both `x` and `y` are set — then those are top-left).
    `font_style`: `sans` (default) or `flow` / `script` for handwriting look.
    `font_path`: optional `.ttf` / `.otf` / `.ttc` file; when set, it is used
    instead of `font_style`.
    """
    value = "" if text is None else str(text)
    if not value:
        return image

    canvas = _as_rgba(image)
    tint = _rgb_tint(color, rgb, (255, 255, 255))
    fill_rgba = (*tint, 255)
    stroke = int(stroke_width)
    stroke_fill = None
    if stroke > 0:
        stroke_rgb = _rgb_tint(stroke_color, None, (0, 0, 0))
        stroke_fill = (*stroke_rgb, 255)

    size = max(8, int(font_size))
    style = (font_style or "sans").strip().lower()
    path = str(font_path).strip() if font_path else None
    font = _load_font(size, style, path or None)
    draw = ImageDraw.Draw(canvas)
    max_width = int(canvas.size[0] * 0.9)
    for _ in range(12):
        bbox = draw.textbbox((0, 0), value, font=font, stroke_width=stroke)
        text_w = bbox[2] - bbox[0]
        if text_w <= max_width or size <= 8:
            break
        size = max(8, size - 4)
        font = _load_font(size, style, path or None)

    draw_kwargs: dict = {
        "font": font,
        "fill": fill_rgba,
        "stroke_width": stroke,
    }
    if stroke_fill is not None:
        draw_kwargs["stroke_fill"] = stroke_fill

    if x is not None and y is not None:
        draw.text((int(x), int(y)), value, **draw_kwargs)
        return canvas

    pad = max(0, int(margin))
    mode = (align or "center").strip().lower()
    bbox = draw.textbbox((0, 0), value, font=font, stroke_width=stroke)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    def _draw_at(px: float, py: float, anchor: str) -> None:
        try:
            draw.text((px, py), value, anchor=anchor, **draw_kwargs)
        except (TypeError, ValueError):
            # Fallback when anchors aren't supported.
            if anchor.endswith("m") and anchor.startswith("m"):
                draw.text((int(px - text_w / 2), int(py - text_h / 2)), value, **draw_kwargs)
            elif anchor.startswith("r"):
                draw.text((int(px - text_w), int(py)), value, **draw_kwargs)
            elif anchor.startswith("l"):
                draw.text((int(px), int(py)), value, **draw_kwargs)
            else:
                draw.text((int(px - text_w / 2), int(py)), value, **draw_kwargs)

    if mode in {"top_right", "right_top"}:
        _draw_at(canvas.size[0] - pad, pad, "rt")
    elif mode in {"top_left", "left_top"}:
        _draw_at(pad, pad, "lt")
    elif mode in {"bottom", "bottom_center"}:
        _draw_at(canvas.size[0] / 2, canvas.size[1] - pad, "mb")
    elif mode == "top":
        _draw_at(canvas.size[0] / 2, pad, "mt")
    else:
        _draw_at(canvas.size[0] / 2, canvas.size[1] / 2, "mm")
    return canvas
