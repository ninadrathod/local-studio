"""
Pillow filter ops used by the JSON preset step runner.
"""

from __future__ import annotations

import math
from functools import lru_cache
from typing import Sequence

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageFont


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


def _dilate(mask: Image.Image, radius: float) -> Image.Image:
    """Binary dilation of an L mask by ~`radius` px (blur + threshold; flat cost, round corners)."""
    # A blurred step edge falls to 8/255 about 1.86 sigma out; threshold there.
    spread = mask.filter(ImageFilter.GaussianBlur(radius=max(0.5, radius / 1.86)))
    return spread.point(lambda v: 255 if v > 8 else 0)


# A usable cutout has a solid body; its soft pixels (hair, fur, motion blur) hug
# that body. A failed one (dark/backlit subjects) is a faint smear spread across
# the frame. So only soft pixels *away from* the solid body count against it.
MIN_SUBJECT_SOLID_FRACTION = 0.003
# Soft pixels within this distance of the body count as its edge: the larger of
# a fraction of the short side and a fraction of the body's equivalent radius
# (so a small, very fluffy subject keeps a proportionally wide fur band).
SUBJECT_EDGE_BAND = 0.04
SUBJECT_EDGE_BAND_BODY = 0.75
MAX_STRAY_SOFT_TO_SOLID = 1.0


def is_reliable_cutout(subject: Image.Image) -> bool:
    """False when the alpha mask is tiny or mostly semi-transparent smear away from the body."""
    if subject.mode != "RGBA":
        return False
    alpha = subject.getchannel("A")
    solid_mask = alpha.point(lambda v: 255 if v >= 128 else 0)
    total = alpha.size[0] * alpha.size[1]
    solid = solid_mask.histogram()[255]
    if total == 0 or solid / total < MIN_SUBJECT_SOLID_FRACTION:
        return False
    soft_mask = alpha.point(lambda v: 255 if 20 < v < 128 else 0)
    body_radius = math.sqrt(solid / math.pi)
    band = max(SUBJECT_EDGE_BAND * min(alpha.size), SUBJECT_EDGE_BAND_BODY * body_radius)
    near_body = _dilate(solid_mask, band)
    stray = ImageChops.subtract(soft_mask, near_body).histogram()[255]
    return stray / solid <= MAX_STRAY_SOFT_TO_SOLID


def extract_subject_layers(
    image: Image.Image, require_clear_subject: bool = False
) -> tuple[Image.Image, Image.Image]:
    """
    Return (subject_rgba, background_rgb).

    Background replaces the subject region with a heavy blur so later filters
    don't double the original subject underneath the cutout. With
    `require_clear_subject`, an unreliable rembg mask (`is_reliable_cutout`
    False) yields a fully transparent subject and the untouched original as
    background, so later steps degrade to "no cutout" instead of drawing a
    smeared shape. Off by default so existing presets keep their behavior.
    """
    from extract_subject import extract_subject as rembg_extract_subject

    original = _as_rgb(image)
    subject = rembg_extract_subject(original)
    if require_clear_subject and not is_reliable_cutout(subject):
        return Image.new("RGBA", original.size, (0, 0, 0, 0)), original
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


def sticker_outline(
    image: Image.Image,
    color: Sequence[int] | None = None,
    rgb: Sequence[int] | None = None,
    width_ratio: float = 0.008,
    softness: float = 0.6,
) -> Image.Image:
    """
    Solid sticker-style outline around an RGBA subject, scaled to the image.

    Width is `width_ratio` × the short side (e.g. 0.008 → ~6 px at 720, ~32 px
    at 4000). Dilation is blur + threshold, so cost stays flat as the width
    grows and corners come out round. `softness` (px) anti-aliases the edge.
    """
    subject = _as_rgba(image)
    tint = _rgb_tint(color, rgb, (255, 255, 255))
    ratio = float(width_ratio)
    if ratio <= 0:
        raise ValueError("width_ratio must be > 0")
    width = max(1.0, ratio * min(subject.size))

    alpha = subject.getchannel("A").point(lambda v: 255 if v >= 128 else 0)
    outline = _dilate(alpha, width)
    if float(softness) > 0:
        outline = outline.filter(ImageFilter.GaussianBlur(radius=float(softness)))

    layer = Image.new("RGBA", subject.size, (*tint, 0))
    layer.putalpha(outline)
    return Image.alpha_composite(layer, subject)


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


_DOODLE_ANCHORS = {
    "top_left": (0.18, 0.18),
    "top_right": (0.82, 0.18),
    "bottom_left": (0.18, 0.82),
    "bottom_right": (0.82, 0.82),
    "top": (0.5, 0.15),
    "bottom": (0.5, 0.85),
    "left": (0.15, 0.5),
    "right": (0.85, 0.5),
    "center": (0.5, 0.5),
}
_DOODLE_SUPERSAMPLE = 2
# Above this many region pixels, draw at 1× — strokes are thick enough that
# supersampling adds little and 2× would quadruple memory.
_DOODLE_SUPERSAMPLE_MAX_PIXELS = 4_000_000
DOODLE_MAX_COUNT = 12


def _doodle_center(
    size: tuple[int, int],
    anchor: str,
    x: float | None,
    y: float | None,
    around: Image.Image | None,
) -> tuple[float, float]:
    width, height = size
    if x is not None and y is not None:
        return float(x) * width, float(y) * height
    mode = (anchor or "center").strip().lower()
    if mode == "subject":
        bbox = around.getchannel("A").getbbox() if around is not None and around.mode == "RGBA" else None
        if bbox:
            return (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
        mode = "center"
    if mode not in _DOODLE_ANCHORS:
        raise ValueError(f"anchor must be 'subject' or one of {sorted(_DOODLE_ANCHORS)}")
    fx, fy = _DOODLE_ANCHORS[mode]
    return fx * width, fy * height


def _stroke(
    draw: ImageDraw.ImageDraw,
    points: list[tuple[float, float]],
    width: int,
    fill: tuple[int, int, int, int],
) -> None:
    """Polyline with round joints and caps (marker look)."""
    if len(points) > 1:
        draw.line(points, fill=fill, width=width, joint="curve")
    r = width / 2
    for px, py in (points[0], points[-1]):
        draw.ellipse((px - r, py - r, px + r, py + r), fill=fill)


def _wobble_line(
    rng, start: tuple[float, float], end: tuple[float, float], jitter: float, steps: int = 12
) -> list[tuple[float, float]]:
    (x0, y0), (x1, y1) = start, end
    pts = []
    for i in range(steps + 1):
        t = i / steps
        edge = 0.0 if i in (0, steps) else 1.0
        pts.append(
            (x0 + (x1 - x0) * t + rng.uniform(-jitter, jitter) * edge,
             y0 + (y1 - y0) * t + rng.uniform(-jitter, jitter) * edge)
        )
    return pts


def _wobble_circle(rng, cx: float, cy: float, radius: float, jitter: float) -> list[tuple[float, float]]:
    import math

    steps = max(48, int(radius / 3))
    phase = rng.uniform(0, 2 * math.pi)
    # Two low-frequency bumps read as hand-drawn without looking noisy.
    a1, a2 = rng.uniform(-jitter, jitter), rng.uniform(-jitter, jitter)
    pts = []
    for i in range(steps + 1):
        t = 2 * math.pi * i / steps
        r = radius + a1 * math.sin(2 * t + phase) + a2 * math.sin(3 * t - phase)
        pts.append((cx + r * math.cos(t + phase), cy + r * math.sin(t + phase)))
    return pts


def doodle(
    image: Image.Image,
    style: str = "xo",
    color: Sequence[int] | None = None,
    rgb: Sequence[int] | None = None,
    anchor: str = "top_right",
    x: float | None = None,
    y: float | None = None,
    size: float = 0.25,
    stroke: float = 0.008,
    count: int = 3,
    angle: float = 0.0,
    opacity: float = 1.0,
    jitter: float = 0.12,
    seed: int = 7,
    around: Image.Image | None = None,
) -> Image.Image:
    """
    Draw one hand-drawn doodle onto `image`.

    `style`: `xo` (3×3 tic-tac-toe of X/O), `rings` (`count` concentric circles),
    `wiggles` (`count` parallel wavy lines, rotated by `angle` degrees),
    `stars` (`count` four-point sparkles).
    Placement: `anchor` (corner/edge name, `center`, or `subject` = centre of the
    `around` layer's alpha bbox) or explicit `x` / `y` fractions (0–1).
    `size` and `stroke` are fractions of the image's short side, so the look
    scales with resolution. `jitter` (fraction of stroke spacing) controls wobble.
    """
    import math
    import random

    mode = (style or "xo").strip().lower()
    if mode not in {"xo", "rings", "wiggles", "stars"}:
        raise ValueError("style must be one of xo, rings, wiggles, stars")
    n = int(count)
    if not 1 <= n <= DOODLE_MAX_COUNT:
        raise ValueError(f"count must be between 1 and {DOODLE_MAX_COUNT}")

    base = _as_rgba(image)
    w, h = base.size
    span_px = max(4.0, float(size) * min(w, h))
    stroke_px = max(1.0, float(stroke) * min(w, h))
    center_x, center_y = _doodle_center(base.size, anchor, x, y, around)

    # Draw only the doodle's neighbourhood (generous pad covers wobble, wiggle
    # amplitude/offsets and star arms), not a full-frame layer.
    half = span_px * 0.7 + stroke_px * (4 + 2 * n)
    rx0, ry0 = max(0, int(center_x - half)), max(0, int(center_y - half))
    rx1, ry1 = min(w, int(math.ceil(center_x + half))), min(h, int(math.ceil(center_y + half)))
    if rx1 <= rx0 or ry1 <= ry0:
        return image.copy()
    rw, rh = rx1 - rx0, ry1 - ry0
    ss = _DOODLE_SUPERSAMPLE if rw * rh <= _DOODLE_SUPERSAMPLE_MAX_PIXELS else 1

    span = span_px * ss
    line_w = max(2, int(round(stroke_px * ss)))
    alpha = int(round(255 * max(0.0, min(1.0, float(opacity)))))
    fill = (*_rgb_tint(color, rgb, (255, 255, 255)), alpha)
    cx, cy = (center_x - rx0) * ss, (center_y - ry0) * ss
    rng = random.Random(int(seed))
    wob = float(jitter)

    layer = Image.new("RGBA", (rw * ss, rh * ss), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)

    if mode == "xo":
        cell = span / 3
        left, top = cx - span / 2, cy - span / 2
        j = cell * wob * 0.4
        for i in (1, 2):
            _stroke(draw, _wobble_line(rng, (left + i * cell, top), (left + i * cell, top + span), j), line_w, fill)
            _stroke(draw, _wobble_line(rng, (left, top + i * cell), (left + span, top + i * cell), j), line_w, fill)
        marks = ["x", "o", "x", "", "x", "o", "o", "", "x"]
        rng.shuffle(marks)
        inset = cell * 0.24
        for idx, mark in enumerate(marks):
            gx, gy = left + (idx % 3) * cell, top + (idx // 3) * cell
            if mark == "x":
                _stroke(draw, _wobble_line(rng, (gx + inset, gy + inset), (gx + cell - inset, gy + cell - inset), j, 6), line_w, fill)
                _stroke(draw, _wobble_line(rng, (gx + cell - inset, gy + inset), (gx + inset, gy + cell - inset), j, 6), line_w, fill)
            elif mark == "o":
                _stroke(draw, _wobble_circle(rng, gx + cell / 2, gy + cell / 2, cell / 2 - inset, j), line_w, fill)
    elif mode == "rings":
        outer = span / 2
        gap = outer / (n + 0.5)
        for i in range(n):
            radius = outer - i * gap
            _stroke(draw, _wobble_circle(rng, cx, cy, radius, gap * wob), line_w, fill)
    elif mode == "wiggles":
        theta = math.radians(float(angle))
        cos_t, sin_t = math.cos(theta), math.sin(theta)
        gap = line_w * 3.2
        amp = line_w * 1.6
        waves = 4.5
        steps = 64
        for i in range(n):
            offset = (i - (n - 1) / 2) * gap
            pts = []
            for k in range(steps + 1):
                t = k / steps
                u = (t - 0.5) * span
                v = offset + amp * math.sin(2 * math.pi * waves * t + i * 0.6)
                pts.append((cx + u * cos_t - v * sin_t, cy + u * sin_t + v * cos_t))
            _stroke(draw, pts, line_w, fill)
    else:
        for i in range(n):
            ang = rng.uniform(0, 2 * math.pi)
            dist = span / 2 * (0.25 + 0.75 * (i / max(1, n - 1))) if n > 1 else 0.0
            sx, sy = cx + dist * math.cos(ang), cy + dist * math.sin(ang)
            arm = span * rng.uniform(0.09, 0.14)
            pinch = arm * 0.18
            star = []
            for k in range(8):
                t = math.pi / 4 * k - math.pi / 2
                r = arm if k % 2 == 0 else pinch
                star.append((sx + r * math.cos(t), sy + r * math.sin(t)))
            draw.polygon(star, fill=fill)

    if ss > 1:
        layer = layer.resize((rw, rh), Image.Resampling.LANCZOS)
    out = base.copy()
    out.alpha_composite(layer, (rx0, ry0))
    if image.mode != "RGBA":
        out = out.convert(image.mode if image.mode in {"RGB", "L"} else "RGB")
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
