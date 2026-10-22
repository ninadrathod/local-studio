"""
Pillow filter ops used by the JSON preset step runner.
"""

from __future__ import annotations

import math
import os
from functools import lru_cache
from pathlib import Path
from typing import Sequence

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageStat


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

# Film-camera date imprint: bold typewriter mono, falling back to other bold monos.
_STAMP_FONT_CANDIDATES = (
    "/System/Library/Fonts/Supplemental/Courier New Bold.ttf",
    "/Library/Fonts/Courier New Bold.ttf",
    "/usr/share/fonts/truetype/msttcorefonts/Courier_New_Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf",
    "DejaVuSansMono-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
    "DejaVuSans.ttf",
)


# Open-licensed display fonts shipped with the repo (OFL / Apache; licences sit next to them).
_FONTS_DIR = Path(__file__).resolve().parents[1] / "fonts"


def _bundled(name: str) -> str:
    return str(_FONTS_DIR / name)


# Poster-title display styles. `poster` and `brush` prefer the system Impact /
# Brush Script (macOS, Windows) and fall back to bundled open lookalikes.
_DISPLAY_FONT_CANDIDATES: dict[str, tuple[str, ...]] = {
    "poster": (
        "/System/Library/Fonts/Supplemental/Impact.ttf",
        "/Library/Fonts/Impact.ttf",
        "C:/Windows/Fonts/impact.ttf",
        "/usr/share/fonts/truetype/msttcorefonts/Impact.ttf",
        _bundled("Anton-Regular.ttf"),
    ),
    "brush": (
        "/System/Library/Fonts/Supplemental/Brush Script.ttf",
        "C:/Windows/Fonts/BRUSHSCI.TTF",
        _bundled("Yellowtail-Regular.ttf"),
    ),
    "slab": (_bundled("AlfaSlabOne-Regular.ttf"),),
    "signature": (_bundled("MrDafoe-Regular.ttf"),),
    "bold_display": (_bundled("PassionOne-Bold.ttf"),),
    "stencil": (_bundled("BlackOpsOne-Regular.ttf"),),
    # Monoton and Bungee only have capitals: lowercase input renders as caps.
    "neon_lines": (_bundled("Monoton-Regular.ttf"),),
    "marquee": (_bundled("Bungee-Regular.ttf"),),
}


def _font_candidates(style: str) -> tuple[str, ...]:
    text = (style or "sans").strip().lower()
    if text in {"flow", "script", "hand", "cursive"}:
        return _FLOW_FONT_CANDIDATES
    if text in {"stamp", "mono", "typewriter"}:
        return _STAMP_FONT_CANDIDATES
    if text in _DISPLAY_FONT_CANDIDATES:
        # Plain sans as a last resort if the bundled file is missing.
        return _DISPLAY_FONT_CANDIDATES[text] + _SANS_FONT_CANDIDATES
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


# rembg can return several solid islands (a person *and* a framed picture on the
# wall). Single-subject presets keep every island that touches the bottom edge
# and is at least this fraction of the largest island (people in a portrait are
# cropped by the bottom; frames and signs on the wall aren't), else just the
# largest — with pieces within a small gap of them and the soft edges hugging them.
MAIN_SUBJECT_GROUNDED_MIN = 0.25
# Working mask: short side ≤ 256 px and long side ≤ 1024 px, so labelling cost
# stays bounded for panoramas.
MAIN_SUBJECT_WORK_SIDE = 256
MAIN_SUBJECT_WORK_LONG_SIDE = 1024
MAIN_SUBJECT_MERGE_GAP = 0.015
MAIN_SUBJECT_EDGE_BAND = 0.03
_MAIN_SUBJECT_MAX_LABELS = 253


def keep_main_subject(alpha: Image.Image) -> Image.Image:
    """Return `alpha` with every solid island except the main one(s) (and near neighbours) cleared."""
    width, height = alpha.size
    scale = min(
        1.0,
        MAIN_SUBJECT_WORK_SIDE / max(1, min(width, height)),
        MAIN_SUBJECT_WORK_LONG_SIDE / max(1, width, height),
    )
    small_size = (max(1, round(width * scale)), max(1, round(height * scale)))
    solid = alpha.point(lambda v: 255 if v >= 128 else 0)
    small = solid.resize(small_size, Image.Resampling.BOX).point(lambda v: 255 if v >= 128 else 0)
    if not small.getbbox():
        return alpha.copy()
    gap = MAIN_SUBJECT_MERGE_GAP * min(small_size)
    labels = _dilate(small, gap) if gap >= 1 else small

    # Label islands 1..253 by flood fill, seeding each from the first unlabelled
    # pixel (found with C-speed getbbox). A mask with more islands than that is
    # noise we can't rank safely, so it is returned unchanged.
    islands: list[int] = []
    for value in range(1, _MAIN_SUBJECT_MAX_LABELS + 2):
        remaining = labels.point(lambda v: 255 if v == 255 else 0).getbbox()
        if not remaining:
            break
        if value > _MAIN_SUBJECT_MAX_LABELS:
            return alpha.copy()
        x0, y0, x1, _ = remaining
        row = labels.crop((x0, y0, x1, y0 + 1)).tobytes()
        ImageDraw.floodfill(labels, (x0 + row.index(255), y0), value)
        islands.append(value)
    if len(islands) < 2:
        return alpha.copy()
    hist = labels.histogram()
    largest = max(islands, key=lambda v: hist[v])
    bottom_row = set(labels.crop((0, small_size[1] - 1, small_size[0], small_size[1])).getdata())
    chosen = {
        v for v in islands
        if v in bottom_row and hist[v] >= MAIN_SUBJECT_GROUNDED_MIN * hist[largest]
    } or {largest}

    keep = labels.point(lambda v: 255 if v in chosen else 0)
    keep = keep.resize(alpha.size, Image.Resampling.BILINEAR).point(lambda v: 255 if v > 0 else 0)
    # Soft edges (hair) may sit further out than the merge gap; keep a wider
    # band around the body, minus the solid pixels of the dropped islands.
    near = _dilate(keep, MAIN_SUBJECT_EDGE_BAND * min(width, height))
    others = ImageChops.subtract(solid, keep)
    return ImageChops.multiply(alpha, ImageChops.subtract(near, others))


def extract_subject_layers(
    image: Image.Image,
    require_clear_subject: bool = False,
    single_subject: bool = False,
) -> tuple[Image.Image, Image.Image]:
    """
    Return (subject_rgba, background_rgb).

    Background replaces the subject region with a heavy blur so later filters
    don't double the original subject underneath the cutout. With
    `require_clear_subject`, an unreliable rembg mask (`is_reliable_cutout`
    False) yields a fully transparent subject and the untouched original as
    background, so later steps degrade to "no cutout" instead of drawing a
    smeared shape. With `single_subject`, only the main solid island is kept
    (`keep_main_subject`), so a second salient object such as a wall frame is
    left in the background. Both off by default so existing presets keep their
    behavior.
    """
    from extract_subject import extract_subject as rembg_extract_subject

    original = _as_rgb(image)
    subject = rembg_extract_subject(original)
    if require_clear_subject and not is_reliable_cutout(subject):
        return Image.new("RGBA", original.size, (0, 0, 0, 0)), original
    if single_subject:
        subject.putalpha(keep_main_subject(subject.getchannel("A")))
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


def _ratio_px(ratio: float | None, size: tuple[int, int], fallback: float, minimum: float = 0.0) -> float:
    """`ratio` × the short side when given (scales with resolution), else the fixed `fallback` px."""
    if ratio is None:
        return float(fallback)
    value = float(ratio)
    if value < 0:
        raise ValueError("ratio params must be >= 0")
    return max(minimum, value * min(size))


def _grow_alpha(alpha: Image.Image, width: float, scaled: bool) -> Image.Image:
    """
    Grow an alpha mask outward by ~`width` px. Fixed-px params keep the original
    MaxFilter (soft edges preserved); ratio params use the flat-cost blur+threshold
    dilation, since a MaxFilter's cost grows with width² and a DSLR-scale width
    would take minutes.
    """
    if scaled:
        return _dilate(alpha, width)
    size = max(3, int(width) * 2 + 1)  # MaxFilter size must be odd
    if size % 2 == 0:
        size += 1
    return alpha.filter(ImageFilter.MaxFilter(size=size))


def glow_border(
    image: Image.Image,
    rgb: Sequence[int] = (0, 255, 200),
    width: int = 8,
    blur: float = 12.0,
    color: Sequence[int] | None = None,
    width_ratio: float | None = None,
    blur_ratio: float | None = None,
) -> Image.Image:
    """
    Add a soft colored glow around an RGBA subject's alpha edge.

    `width` / `blur` are px; `width_ratio` / `blur_ratio` (fractions of the short
    side) override them so the glow looks the same from phone to DSLR size.
    """
    subject = _as_rgba(image)
    alpha = subject.getchannel("A")
    tint = _rgb_tint(color, rgb, (0, 255, 200))

    grow = _ratio_px(width_ratio, subject.size, width, 1.0)
    glow_mask = _grow_alpha(alpha, grow, width_ratio is not None)
    glow_mask = glow_mask.filter(
        ImageFilter.GaussianBlur(radius=_ratio_px(blur_ratio, subject.size, blur))
    )

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
    width_ratio: float | None = None,
    blur_ratio: float | None = None,
) -> Image.Image:
    """
    Draw a glowing outline around the subject only (ring), without filling the body.

    Accepts `color` or `rgb` as [R, G, B]. `width` / `blur` are px;
    `width_ratio` / `blur_ratio` (fractions of the short side) override them so
    the line looks the same from phone to DSLR size.
    """
    subject = _as_rgba(image)
    tint_rgb = _rgb_tint(color, rgb, (0, 255, 200))

    alpha = subject.getchannel("A")
    grow = _ratio_px(width_ratio, subject.size, width, 1.0)

    # Outer silhouette minus subject fill → border ring only
    outer = _grow_alpha(alpha, grow, width_ratio is not None)
    ring = ImageChops.subtract(outer, alpha)
    blur_px = _ratio_px(blur_ratio, subject.size, blur)
    if blur_px > 0:
        ring = ring.filter(ImageFilter.GaussianBlur(radius=blur_px))

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
    resized with Lanczos. With LIGHTWEIGHT=1 the model is skipped and the image
    is just Lanczos-resized to the same target (`upscale`), much cheaper.
    """
    if os.environ.get("LIGHTWEIGHT", "0").strip() == "1":
        return upscale(image, long_edge=long_edge, max_scale=max_scale)

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
# `color: "auto"` inks dark on light backgrounds (mean luma above the threshold),
# white otherwise, so a white marker never vanishes on a pale wall.
DOODLE_AUTO_LUMA_THRESHOLD = 150
DOODLE_DARK_INK = (34, 34, 34)
# `avoid_subject` moves a corner/edge doodle when the `around` layer covers more
# than this fraction of its box, trying the mirrored anchors in order.
DOODLE_AVOID_MAX_OVERLAP = 0.08
# `avoid_busy` also moves it off cluttered background (a framed picture, a
# sign). Busyness = mean edge strength on a blurred ≤128 px copy, so fine
# texture (stucco, grain) washes out and only structure counts; plain wall
# scores ~2, a gilded frame ~13.
DOODLE_BUSY_WORK_SIDE = 128
DOODLE_BUSY_MAX_EDGE = 8.0


def _mirror_anchors(anchor: str) -> list[str]:
    swap_x = {"left": "right", "right": "left"}
    swap_y = {"top": "bottom", "bottom": "top"}
    parts = anchor.split("_")
    flip_x = "_".join(swap_x.get(p, p) for p in parts)
    flip_y = "_".join(swap_y.get(p, p) for p in parts)
    flip_xy = "_".join(swap_y.get(swap_x.get(p, p), swap_x.get(p, p)) for p in parts)
    out: list[str] = []
    for name in (anchor, flip_x, flip_y, flip_xy):
        if name not in out:
            out.append(name)
    return out


def _clear_anchor(
    base: Image.Image,
    anchor: str,
    half: float,
    around: Image.Image | None,
    avoid_busy: bool,
) -> str:
    """
    Pick the first of `anchor` and its mirrors whose doodle box the subject
    barely covers (and, with `avoid_busy`, whose background is calm); if none
    qualifies, the one with the lowest combined score.
    """
    width, height = base.size
    alpha = around.getchannel("A") if around is not None else None
    edges = None
    scale = 1.0
    if avoid_busy:
        scale = min(1.0, DOODLE_BUSY_WORK_SIDE / max(1, min(width, height)))
        small = base.convert("L").resize(
            (max(1, round(width * scale)), max(1, round(height * scale))), Image.Resampling.BOX
        )
        edges = small.filter(ImageFilter.GaussianBlur(1)).filter(ImageFilter.FIND_EDGES)
    best, best_score = anchor, float("inf")
    for name in _mirror_anchors(anchor):
        fx, fy = _DOODLE_ANCHORS[name]
        cx, cy = fx * width, fy * height
        box = (max(0, int(cx - half)), max(0, int(cy - half)),
               min(width, int(cx + half)), min(height, int(cy + half)))
        if box[2] <= box[0] or box[3] <= box[1]:
            continue
        overlap = ImageStat.Stat(alpha.crop(box)).mean[0] / 255 if alpha is not None else 0.0
        busy = 0.0
        if edges is not None:
            small_box = tuple(int(round(v * scale)) for v in box)
            if small_box[2] > small_box[0] and small_box[3] > small_box[1]:
                busy = ImageStat.Stat(edges.crop(small_box)).mean[0]
        if overlap <= DOODLE_AVOID_MAX_OVERLAP and busy <= DOODLE_BUSY_MAX_EDGE:
            return name
        score = overlap / DOODLE_AVOID_MAX_OVERLAP + busy / DOODLE_BUSY_MAX_EDGE
        if score < best_score:
            best, best_score = name, score
    return best


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
    color: Sequence[int] | str | None = None,
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
    avoid_subject: bool = False,
    avoid_busy: bool = False,
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
    `color: "auto"` picks dark ink on light backgrounds and white on dark ones.
    `avoid_subject` (with `around`) moves a corner/edge anchor to its first
    mirror the subject doesn't cover, so the doodle isn't hidden behind it.
    `avoid_busy` also skips mirrors over cluttered background (frames, signs).
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
    # Draw only the doodle's neighbourhood (generous pad covers wobble, wiggle
    # amplitude/offsets and star arms), not a full-frame layer.
    half = span_px * 0.7 + stroke_px * (4 + 2 * n)
    mode_anchor = (anchor or "center").strip().lower()
    avoid_around = avoid_subject and around is not None and around.mode == "RGBA"
    if (
        (avoid_around or avoid_busy)
        and (x is None or y is None)
        and mode_anchor in _DOODLE_ANCHORS
        and mode_anchor != "center"
    ):
        anchor = _clear_anchor(
            base, mode_anchor, span_px / 2, around if avoid_around else None, bool(avoid_busy)
        )
    center_x, center_y = _doodle_center(base.size, anchor, x, y, around)
    rx0, ry0 = max(0, int(center_x - half)), max(0, int(center_y - half))
    rx1, ry1 = min(w, int(math.ceil(center_x + half))), min(h, int(math.ceil(center_y + half)))
    if rx1 <= rx0 or ry1 <= ry0:
        return image.copy()
    rw, rh = rx1 - rx0, ry1 - ry0
    ss = _DOODLE_SUPERSAMPLE if rw * rh <= _DOODLE_SUPERSAMPLE_MAX_PIXELS else 1

    span = span_px * ss
    line_w = max(2, int(round(stroke_px * ss)))
    alpha = int(round(255 * max(0.0, min(1.0, float(opacity)))))
    if isinstance(color, str):
        if color.strip().lower() != "auto":
            raise ValueError("color must be an [r, g, b] list or 'auto'")
        luma = ImageStat.Stat(base.convert("L").crop((rx0, ry0, rx1, ry1))).mean[0]
        ink = DOODLE_DARK_INK if luma > DOODLE_AUTO_LUMA_THRESHOLD else (255, 255, 255)
    else:
        ink = _rgb_tint(color, rgb, (255, 255, 255))
    fill = (*ink, alpha)
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


def _keep_alpha(out: Image.Image, image: Image.Image) -> Image.Image:
    """Return `out` as RGB, or RGBA carrying `image`'s alpha when it had one."""
    if image.mode == "RGBA":
        out = out.convert("RGBA")
        out.putalpha(image.getchannel("A"))
        return out
    return out if out.mode == "RGB" else out.convert("RGB")


def _flatten(image: Image.Image, background: Sequence[int] = (255, 255, 255)) -> Image.Image:
    """RGB copy of `image`; RGBA is composited onto `background` first so hidden
    pixels under transparency can't leak into tone/edge detection."""
    if image.mode != "RGBA":
        return _as_rgb(image)
    flat = Image.new("RGB", image.size, tuple(background))
    flat.paste(image.convert("RGB"), (0, 0), image.getchannel("A"))
    return flat


def _band_lut(fn) -> list[int]:
    """768-entry RGB point table from `fn(value, band_index)`."""
    return [max(0, min(255, round(fn(v, band)))) for band in range(3) for v in range(256)]


def posterize(image: Image.Image, levels: int = 5, smooth: int = 3) -> Image.Image:
    """
    Flatten each RGB channel to `levels` evenly spaced values (comic-style colour
    bands). `smooth` (odd, 0 to skip) median-filters first so bands stay clean.
    """
    steps = int(levels)
    if not 2 <= steps <= 32:
        raise ValueError("levels must be between 2 and 32")
    base = _as_rgb(image)
    window = int(smooth)
    if window:
        if window < 3 or window % 2 == 0:
            raise ValueError("smooth must be 0 or an odd integer >= 3")
        base = base.filter(ImageFilter.MedianFilter(size=window))
    lut = [round(round(v / 255 * (steps - 1)) * 255 / (steps - 1)) for v in range(256)]
    return _keep_alpha(base.point(lut * 3), image)


def ink_edges(
    image: Image.Image,
    detail: float = 0.0025,
    threshold: int = 6,
    thickness: float = 0.0015,
    color: Sequence[int] | None = None,
    rgb: Sequence[int] | None = None,
    opacity: float = 1.0,
) -> Image.Image:
    """
    Draw comic-style ink outlines (difference of Gaussians on luminance).

    `detail` is the edge blur radius and `thickness` the line growth, both as
    fractions of the short side so the look scales with resolution. Lower
    `threshold` → more lines.
    """
    base = _flatten(image)
    short = min(base.size)
    gray = base.convert("L")
    r1 = max(0.5, float(detail) * short)
    fine = gray.filter(ImageFilter.GaussianBlur(radius=r1))
    coarse = gray.filter(ImageFilter.GaussianBlur(radius=r1 * 1.6))
    del gray
    # Pixels darker than their surroundings → the dark side of an edge.
    dog = ImageChops.subtract(coarse, fine)
    del fine, coarse
    cut = int(threshold)
    lines = dog.point(lambda v: 255 if v > cut else 0)
    del dog
    grow = float(thickness) * short
    if grow >= 1.0:
        lines = _dilate(lines, grow)
    lines = lines.filter(ImageFilter.GaussianBlur(radius=0.6))
    strength = max(0.0, min(1.0, float(opacity)))
    if strength < 1.0:
        lines = lines.point(lambda v: int(v * strength))
    # Paint ink through the line mask in place (no full-size ink layer).
    base.paste(_rgb_tint(color, rgb, (20, 18, 16)), (0, 0, *base.size), lines)
    return _keep_alpha(base, image)


# Process halftone at most this long edge, then resize back, so dot drawing and
# the rotated screens stay bounded on very large uploads.
_HALFTONE_MAX_EDGE = 2400
# Dots are drawn one by one; if a screen would need more than this many cells
# (tiny `cell`, extreme aspect ratios), the pitch is enlarged to fit.
_HALFTONE_MAX_DOTS = 160_000
_CMYK_ANGLES = (15.0, 75.0, 0.0, 45.0)
_CMYK_INKS = ((0, 160, 225), (230, 0, 125), (255, 230, 0), (25, 22, 20))


def _separate_cmyk(image: Image.Image, gcr: float = 0.6) -> tuple[Image.Image, ...]:
    """
    Split RGB into C, M, Y, K ink channels with grey-component replacement.

    Pillow's own RGB→CMYK leaves K at 0, so shadows would print as muddy
    overlapping C+M+Y dots. Here `gcr` (0–1) of the shared grey moves to the
    black plate: 1 = cleanest blacks, lower keeps more colour in the darks.
    """
    r, g, b = _as_rgb(image).split()
    c, m, y = ImageChops.invert(r), ImageChops.invert(g), ImageChops.invert(b)
    amount = max(0.0, min(1.0, float(gcr)))
    k = ImageChops.darker(ImageChops.darker(c, m), y).point(lambda v: int(v * amount))
    return ImageChops.subtract(c, k), ImageChops.subtract(m, k), ImageChops.subtract(y, k), k


def _dot_screen(ink: Image.Image, cell: float, angle: float) -> Image.Image:
    """
    Halftone one ink channel (L, 255 = full ink) into a dot mask of the same size.

    The channel is rotated to the screen angle, averaged per cell, a dot sized by
    coverage is drawn at each cell centre, then the screen is rotated back.
    """
    import math

    w, h = ink.size
    rotated = ink.rotate(angle, resample=Image.Resampling.BILINEAR, expand=True, fillcolor=0)
    rw, rh = rotated.size
    cols, rows = max(1, math.ceil(rw / cell)), max(1, math.ceil(rh / cell))
    means = rotated.resize((cols, rows), Image.Resampling.BOX)
    ss = 2 if cell < 12 else 1
    screen = Image.new("L", (int(cols * cell * ss), int(rows * cell * ss)), 0)
    draw = ImageDraw.Draw(screen)
    px = means.load()
    unit = cell * ss
    # Dot area ≈ ink coverage (r = sqrt(c/π)), with mild print "dot gain" that
    # grows to 0.71 × cell at full ink so solid areas close up.
    for row in range(rows):
        cy = (row + 0.5) * unit
        for col in range(cols):
            value = px[col, row]
            if value < 6:
                continue
            coverage = value / 255
            radius = unit * math.sqrt(coverage / math.pi) * (1 + 0.26 * coverage)
            cx = (col + 0.5) * unit
            draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=255)
    if ss > 1:
        screen = screen.resize((int(cols * cell), int(rows * cell)), Image.Resampling.LANCZOS)
    screen = screen.crop((0, 0, rw, rh)).rotate(-angle, resample=Image.Resampling.BILINEAR, expand=True)
    sw, sh = screen.size
    left, top = (sw - w) // 2, (sh - h) // 2
    return screen.crop((left, top, left + w, top + h))


def halftone(
    image: Image.Image,
    mode: str = "mono",
    cell: float = 0.012,
    angle: float = 45.0,
    paper: Sequence[int] | None = None,
    ink: Sequence[int] | None = None,
    mix: float = 1.0,
    gcr: float = 0.6,
) -> Image.Image:
    """
    Printed halftone dot screen.

    `mode`: `mono` (one `ink` colour at `angle`) or `cmyk` (four process inks at
    15/75/0/45°; `gcr` sets how much shared grey prints on the black plate).
    `cell` is the dot pitch as a fraction of the short side.
    Dots print on `paper`; `mix` < 1 blends the print back over the original.
    """
    kind = (mode or "mono").strip().lower()
    if kind not in {"mono", "cmyk"}:
        raise ValueError("mode must be 'mono' or 'cmyk'")
    pitch = float(cell)
    if not 0.002 <= pitch <= 0.1:
        raise ValueError("cell must be between 0.002 and 0.1")
    paper_rgb = _rgb_tint(paper, None, (255, 255, 255))
    base = _flatten(image, paper_rgb)
    w, h = base.size
    scale = min(1.0, _HALFTONE_MAX_EDGE / max(w, h))
    work = base if scale == 1.0 else base.resize(
        (max(1, round(w * scale)), max(1, round(h * scale))), Image.Resampling.LANCZOS
    )
    cell_px = max(3.0, pitch * min(work.size))
    # Worst case (45°) rotated screen area / cell area ≈ dots per channel.
    screen_area = (work.size[0] + work.size[1]) ** 2 / 2
    if screen_area / cell_px**2 > _HALFTONE_MAX_DOTS:
        cell_px = math.sqrt(screen_area / _HALFTONE_MAX_DOTS)
    printed = Image.new("RGB", work.size, paper_rgb)

    if kind == "mono":
        darkness = ImageChops.invert(work.convert("L"))
        dots = _dot_screen(darkness, cell_px, float(angle))
        layer = Image.new("RGB", work.size, _rgb_tint(ink, None, (25, 22, 20)))
        printed = Image.composite(layer, printed, dots)
    else:
        for channel, ang, ink_rgb in zip(_separate_cmyk(work, gcr), _CMYK_ANGLES, _CMYK_INKS):
            dots = _dot_screen(channel, cell_px, ang)
            inked = Image.composite(Image.new("RGB", work.size, ink_rgb), Image.new("RGB", work.size, (255, 255, 255)), dots)
            printed = ImageChops.multiply(printed, inked)

    del work
    if printed.size != base.size:
        printed = printed.resize(base.size, Image.Resampling.LANCZOS)
    amount = max(0.0, min(1.0, float(mix)))
    if amount < 1.0:
        printed = Image.blend(base, printed, amount)
    del base
    return _keep_alpha(printed, image)


def paper_texture(
    image: Image.Image,
    color: Sequence[int] | None = None,
    rgb: Sequence[int] | None = None,
    tint: float = 0.35,
    grain: float = 0.08,
    stains: float = 0.12,
    fade: float = 0.0,
    seed: int = 11,
) -> Image.Image:
    """
    Age a print onto paper: multiply-tint toward `color` by `tint`, add fine
    `grain` speckle and low-frequency `stains` (blotchy yellowing), then `fade`
    (lift blacks toward the paper). All randomness is seeded; grain size scales
    with resolution.
    """
    import random

    out = _as_rgb(image)
    w, h = out.size
    paper_rgb = _rgb_tint(color, rgb, (236, 222, 190))
    rng = random.Random(int(seed))

    # Tint, stain darkening and fade are per-channel tone curves, so they run as
    # point tables instead of allocating full-size solid/blend layers.
    t = max(0.0, min(1.0, float(tint)))
    if t > 0:
        out = out.point(_band_lut(lambda v, b: v * (1 - t + t * paper_rgb[b] / 255)))

    g = max(0.0, min(1.0, float(grain)))
    if g > 0:
        tile_side = 256
        tile = Image.frombytes("L", (tile_side, tile_side), rng.randbytes(tile_side * tile_side))
        grain_px = max(1.0, min(w, h) / 720)
        if grain_px > 1.0:
            tile = tile.resize((round(tile_side * grain_px),) * 2, Image.Resampling.BILINEAR)
        low = round(255 * (1 - g))
        tile = tile.point(lambda v: low + (v * (255 - low)) // 255)
        tile_rgb = Image.merge("RGB", (tile, tile, tile))
        tw, th = tile_rgb.size
        # Multiply grain tile by tile in place (no full-size noise layer).
        for ty in range(0, h, th):
            for tx in range(0, w, tw):
                box = (tx, ty, min(w, tx + tw), min(h, ty + th))
                region = out.crop(box)
                out.paste(ImageChops.multiply(region, tile_rgb.crop((0, 0, *region.size))), box[:2])

    st = max(0.0, min(1.0, float(stains)))
    if st > 0:
        short = min(w, h)
        # Blot grid follows the aspect ratio so stains stay round on panoramas.
        cols = max(2, min(240, round(12 * w / short)))
        rows = max(2, min(240, round(12 * h / short)))
        blot = Image.frombytes("L", (cols, rows), rng.randbytes(cols * rows)).resize(
            (w, h), Image.Resampling.BICUBIC
        )
        blot = blot.filter(ImageFilter.GaussianBlur(radius=short / 30))
        mask = blot.point(lambda v: int(max(0, v - 110) / 145 * 255 * st))
        del blot
        stained = out.point(_band_lut(lambda v, b: v * paper_rgb[b] * 0.82 / 255))
        out.paste(stained, (0, 0), mask)
        del stained, mask

    f = max(0.0, min(1.0, float(fade)))
    if f > 0:
        out = out.point(_band_lut(lambda v, b: v + f * max(0, paper_rgb[b] - v)))
    return _keep_alpha(out, image)


# Per-pixel grading (split tone, vibrance, shadows / highlights) runs in horizontal
# strips so a frame never needs more than one strip of float32 working memory. Each
# strip holds ~a dozen float temporaries (~100 B/pixel), so 1 MP keeps a pass near
# 100 MB — small enough for a 1 GB LIGHTWEIGHT host next to the rembg model.
_GRADE_STRIP_PIXELS = 1_000_000
# Rec. 709 luma weights.
_LUMA = (0.2126, 0.7152, 0.0722)


def _grade_curve(
    v: float,
    exposure_gain: float,
    contrast: float,
    pivot: float,
    black_lift: float,
    white_rolloff: float,
) -> float:
    """One channel value 0–1 through exposure → contrast curve → highlight shoulder → matte lift."""
    x = min(1.0, max(0.0, v * exposure_gain))
    if contrast > 0:
        # Blend toward an S-curve pivoted at `pivot`: deeper shadows, brighter highlights.
        if x < pivot:
            s_curve = pivot * (x / pivot) ** 1.6
        else:
            s_curve = pivot + (1 - pivot) * (1 - (1 - (x - pivot) / (1 - pivot)) ** 1.6)
        x += contrast * (s_curve - x)
    elif contrast < 0:
        # Flatten toward the pivot (soft, low-contrast look).
        x += -contrast * 0.6 * (pivot - x)
    if white_rolloff > 0:
        # Shoulder above the knee: slope 1 at the knee easing to 1 − rolloff at white,
        # so highlights compress smoothly instead of clipping.
        knee = 1 - 0.5 * white_rolloff
        if x > knee:
            span = 1 - knee
            u = (x - knee) / span
            x = knee + span * (u - 0.5 * white_rolloff * u * u)
    return black_lift + x * (1 - black_lift)


def color_grade(
    image: Image.Image,
    temperature: float = 0.0,
    tint: float = 0.0,
    exposure: float = 0.0,
    contrast: float = 0.0,
    pivot: float = 0.45,
    black_lift: float = 0.0,
    white_rolloff: float = 0.0,
    saturation: float = 1.0,
    vibrance: float = 0.0,
    shadows: Sequence[int] | None = None,
    highlights: Sequence[int] | None = None,
    split: float = 0.0,
    balance: float = 0.0,
) -> Image.Image:
    """
    Photographic colour grade in one pass.

    - `temperature` (−1 cool … 1 warm) and `tint` (−1 green … 1 magenta): white balance.
    - `exposure` (stops), `contrast` (−1 flat … 1 punchy S-curve around `pivot`),
      `black_lift` (0–0.3 matte / faded blacks), `white_rolloff` (0–1 soft highlight
      shoulder instead of clipping). These fold into per-channel point tables, so
      they cost the same at any resolution.
    - `shadows` / `highlights` ([r, g, b]) with `split` (0–1) split-tone the image:
      each tint shifts hue in its tonal range while keeping luminance; `balance`
      (−1 … 1) moves the crossover toward shadows (−) or highlights (+).
    - `saturation` (1 = unchanged) and `vibrance` (0–1, boosts muted colours more
      than already-saturated ones, so skin doesn't go orange).
    """
    import numpy as np

    out = _as_rgb(image)
    temp, tnt = float(temperature), float(tint)
    gains = (1 + 0.10 * temp, 1 - 0.06 * tnt, 1 - 0.10 * temp)
    exposure_gain = 2.0 ** float(exposure)
    c = max(-1.0, min(1.0, float(contrast)))
    pv = max(0.05, min(0.95, float(pivot)))
    lift = max(0.0, min(0.3, float(black_lift)))
    roll = max(0.0, min(1.0, float(white_rolloff)))
    out = out.point(
        _band_lut(lambda v, b: 255 * _grade_curve(v * gains[b] / 255, exposure_gain, c, pv, lift, roll))
    )

    amount = max(0.0, min(1.0, float(split)))
    vib = max(0.0, min(1.0, float(vibrance)))
    sat = max(0.0, float(saturation))
    if amount == 0 and vib == 0 and sat == 1.0:
        return _keep_alpha(out, image)

    luma = np.array(_LUMA, dtype=np.float32)

    def _hue_shift(rgb: Sequence[int] | None) -> "np.ndarray":
        # Tint minus its own luma: pure hue offset, zero brightness change.
        if rgb is None:
            return np.zeros(3, dtype=np.float32)
        t = np.array([float(v) for v in rgb], dtype=np.float32) / 255
        return t - float(t @ luma)

    shadow_shift, highlight_shift = _hue_shift(shadows), _hue_shift(highlights)
    crossover = 0.5 + 0.35 * max(-1.0, min(1.0, float(balance)))

    w, h = out.size
    rows = max(1, _GRADE_STRIP_PIXELS // max(1, w))
    graded = Image.new("RGB", out.size)
    for top in range(0, h, rows):
        box = (0, top, w, min(h, top + rows))
        px = np.asarray(out.crop(box), dtype=np.float32) / 255
        y = px @ luma
        if amount > 0:
            # Smooth weights: shadows fade out by the crossover, highlights fade in from it.
            ws = np.clip(1 - y / crossover, 0, 1) ** 1.5
            wh = np.clip((y - crossover) / (1 - crossover), 0, 1) ** 1.5
            px += amount * (ws[..., None] * shadow_shift + wh[..., None] * highlight_shift)
        if sat != 1.0 or vib > 0:
            yy = (px @ luma)[..., None]
            chroma = px - yy
            factor = sat
            if vib > 0:
                current = np.max(np.abs(chroma), axis=-1, keepdims=True)
                factor = factor * (1 + vib * np.clip(1 - current * 3, 0, 1))
            px = yy + chroma * factor
        px = _fit_gamut(px, luma)
        graded.paste(Image.fromarray(np.clip(px * 255 + 0.5, 0, 255).astype(np.uint8), "RGB"), box[:2])
    return _keep_alpha(graded, image)


def _fit_gamut(px: "np.ndarray", luma: "np.ndarray") -> "np.ndarray":
    """
    Bring out-of-range pixels (float RGB 0–1) back by shrinking chroma toward their
    own luma (hue and brightness kept) instead of clipping channels one by one,
    which would shift hue and dull bright highlights.
    """
    import numpy as np

    y = np.clip(px @ luma, 0, 1)[..., None]
    chroma = px - y
    over = np.max(chroma, axis=-1, keepdims=True)
    under = np.min(chroma, axis=-1, keepdims=True)
    with np.errstate(divide="ignore", invalid="ignore"):
        fit_hi = np.where(over > 0, (1 - y) / over, 1.0)
        fit_lo = np.where(under < 0, -y / under, 1.0)
    return y + chroma * np.clip(np.minimum(fit_hi, fit_lo), 0, 1)


def _curve_table(points: Sequence[Sequence[float]] | None) -> list[float]:
    """
    256-entry curve (values 0–255) through `points` ([[x, y], …], 0–255) using
    monotone cubic (Fritsch–Carlson) interpolation, so the curve never overshoots
    between points. Flat beyond the first / last point; identity when `points` is empty.
    """
    if not points:
        return [float(v) for v in range(256)]
    pts = sorted((max(0.0, min(255.0, float(x))), max(0.0, min(255.0, float(y)))) for x, y in points)
    xs, ys = [pts[0][0]], [pts[0][1]]
    for x, y in pts[1:]:
        if x > xs[-1]:
            xs.append(x)
            ys.append(y)
    if len(xs) == 1:
        return [ys[0]] * 256
    n = len(xs)
    slopes = [(ys[i + 1] - ys[i]) / (xs[i + 1] - xs[i]) for i in range(n - 1)]
    tangents = [slopes[0]] + [
        0.0 if slopes[i - 1] * slopes[i] <= 0 else (slopes[i - 1] + slopes[i]) / 2 for i in range(1, n - 1)
    ] + [slopes[-1]]
    for i, m in enumerate(slopes):
        if m == 0:
            tangents[i] = tangents[i + 1] = 0.0
            continue
        a, b = tangents[i] / m, tangents[i + 1] / m
        if a * a + b * b > 9:
            k = 3 / math.hypot(a, b)
            tangents[i], tangents[i + 1] = k * a * m, k * b * m
    table = []
    seg = 0
    for v in range(256):
        if v <= xs[0]:
            table.append(ys[0])
            continue
        if v >= xs[-1]:
            table.append(ys[-1])
            continue
        while xs[seg + 1] < v:
            seg += 1
        h = xs[seg + 1] - xs[seg]
        t = (v - xs[seg]) / h
        t2, t3 = t * t, t * t * t
        table.append(
            (2 * t3 - 3 * t2 + 1) * ys[seg]
            + (t3 - 2 * t2 + t) * h * tangents[seg]
            + (-2 * t3 + 3 * t2) * ys[seg + 1]
            + (t3 - t2) * h * tangents[seg + 1]
        )
    return [max(0.0, min(255.0, y)) for y in table]


def tone_curve(
    image: Image.Image,
    master: Sequence[Sequence[float]] | None = None,
    red: Sequence[Sequence[float]] | None = None,
    green: Sequence[Sequence[float]] | None = None,
    blue: Sequence[Sequence[float]] | None = None,
) -> Image.Image:
    """
    Photoshop / Lightroom style point curves. Each curve is a list of [input, output]
    control points on 0–255 joined by a smooth monotone spline: `master` runs on all
    three channels first, then `red` / `green` / `blue` per channel (e.g. lift the
    blue curve's black point for blue shadows). Folded into one point table, so cost
    is flat at any resolution; an omitted curve is the identity.
    """
    base = _curve_table(master)
    channel = [_curve_table(c) for c in (red, green, blue)]

    def through(v: int, band: int) -> float:
        x = base[v]
        lo = int(x)
        hi = min(255, lo + 1)
        return channel[band][lo] + (x - lo) * (channel[band][hi] - channel[band][lo])

    return _keep_alpha(_as_rgb(image).point(_band_lut(through)), image)


# Guided-filter edge threshold (variance on 0–1 luma): local contrast well above this
# is kept as an edge, texture below it is smoothed.
_GUIDED_EPS = 0.01


def _box_mean(a: "np.ndarray", radius: int) -> "np.ndarray":
    """Mean over a (2r+1)² window, shrinking at the borders (summed-area table)."""
    import numpy as np

    h, w = a.shape
    sat = np.zeros((h + 1, w + 1), dtype=np.float64)
    sat[1:, 1:] = a.cumsum(0).cumsum(1)
    y0 = np.clip(np.arange(h) - radius, 0, h)
    y1 = np.clip(np.arange(h) + radius + 1, 0, h)
    x0 = np.clip(np.arange(w) - radius, 0, w)
    x1 = np.clip(np.arange(w) + radius + 1, 0, w)
    total = sat[y1][:, x1] - sat[y0][:, x1] - sat[y1][:, x0] + sat[y0][:, x0]
    count = (y1 - y0)[:, None] * (x1 - x0)[None, :]
    return (total / count).astype(np.float32)


def _guided_coefficients(guide: "np.ndarray", radius: int, eps: float) -> tuple["np.ndarray", "np.ndarray"]:
    """
    Self-guided filter (He et al.) coefficients: smoothed = a · guide + b. Returning
    the box-averaged a / b (not the result) lets the caller upscale them and apply
    them to full-resolution luma — the "fast guided filter" — so edges stay crisp.
    """
    mean = _box_mean(guide, radius)
    var = _box_mean(guide * guide, radius) - mean * mean
    a = var / (var + eps)
    b = mean - a * mean
    return _box_mean(a, radius), _box_mean(b, radius)


def shadows_highlights(
    image: Image.Image,
    shadows: float = 0.0,
    highlights: float = 0.0,
    radius_ratio: float = 0.02,
    local: float = 0.6,
) -> Image.Image:
    """
    Local shadow / highlight recovery (Lightroom Shadows & Highlights sliders).

    `shadows` (−1 deepen … 1 open up) and `highlights` (−1 recover … 1 brighten) bend
    brightness with a gamma whose strength follows a tone mask: dark regions get the
    shadow move, bright regions the highlight move, mid-tones little of either, and
    pure black / white stay put. The mask mixes each pixel's luma with an edge-aware
    smoothing of it (`radius_ratio` × short side, `local` 0–1 share of the smoothed
    luma), so a dark face in a bright frame lifts as a region rather than by pixel,
    while a hard edge (building against sky) keeps its own side's move instead of
    bleeding into a halo. The smoothing is a fast guided filter: coefficients are fitted
    at ≤ 1024 px and applied against full-resolution luma, so cost is flat and the mask
    stays sharp at edges. Colour scales with brightness (hue kept), and pixels that
    would leave the gamut lose chroma instead of clipping.
    """
    import numpy as np

    sh = max(-1.0, min(1.0, float(shadows)))
    hi = max(-1.0, min(1.0, float(highlights)))
    out = _as_rgb(image)
    if sh == 0 and hi == 0:
        return _keep_alpha(out, image)
    mix = max(0.0, min(1.0, float(local)))
    w, h = out.size
    luma = np.array(_LUMA, dtype=np.float32)
    small = np.asarray(_small_copy(out), dtype=np.float32) / 255 @ luma
    # Box radius ≈ 2σ of the Gaussian this replaces, so the mask reaches as far.
    radius = max(1, round(2 * float(radius_ratio) * min(small.shape)))
    coef_a, coef_b = _guided_coefficients(small, radius, _GUIDED_EPS)
    coef_a = Image.fromarray(coef_a, "F").resize((w, h), Image.Resampling.BILINEAR)
    coef_b = Image.fromarray(coef_b, "F").resize((w, h), Image.Resampling.BILINEAR)
    rows = max(1, _GRADE_STRIP_PIXELS // max(1, w))
    result = Image.new("RGB", out.size)
    for top in range(0, h, rows):
        box = (0, top, w, min(h, top + rows))
        px = np.asarray(out.crop(box), dtype=np.float32) / 255
        y = np.clip(px @ luma, 0, 1)
        smooth = np.asarray(coef_a.crop(box), dtype=np.float32) * y + np.asarray(coef_b.crop(box), dtype=np.float32)
        m = (1 - mix) * y + mix * np.clip(smooth, 0, 1)
        ws = np.clip(1 - m / 0.55, 0, 1) ** 1.6
        wh = np.clip((m - 0.45) / 0.55, 0, 1) ** 1.6
        # Positive moves brighten (gamma < 1); 0 and 1 are fixed points of any gamma.
        gamma = 2.0 ** (-(1.3 * sh * ws + 1.1 * hi * wh))
        target = np.power(y, gamma)
        with np.errstate(divide="ignore", invalid="ignore"):
            ratio = np.where(y > 1e-4, target / y, 1.0)
        px = px * ratio[..., None] + np.where(y > 1e-4, 0.0, target)[..., None]
        px = _fit_gamut(px, luma)
        result.paste(Image.fromarray(np.clip(px * 255 + 0.5, 0, 255).astype(np.uint8), "RGB"), box[:2])
    return _keep_alpha(result, image)


# Named hue centres (degrees on the HSV wheel) for `selective_color`.
_HUE_NAMES = {
    "red": 0.0,
    "orange": 30.0,
    "yellow": 48.0,
    "green": 120.0,
    "cyan": 180.0,
    "teal": 175.0,
    "blue": 220.0,
    "purple": 275.0,
    "magenta": 300.0,
    "pink": 330.0,
}


def _hue_degrees(hue: float | str | Sequence[int]) -> float:
    """Hue centre from degrees, a name in `_HUE_NAMES`, or an [r, g, b] colour."""
    if isinstance(hue, str):
        key = hue.strip().lower()
        if key not in _HUE_NAMES:
            raise ValueError(f"Unknown hue '{hue}'. Use degrees, [r, g, b], or one of: {', '.join(_HUE_NAMES)}")
        return _HUE_NAMES[key]
    if isinstance(hue, (int, float)):
        return float(hue) % 360
    import colorsys

    r, g, b = (max(0, min(255, int(c))) / 255 for c in hue)
    return colorsys.rgb_to_hsv(r, g, b)[0] * 360


def selective_color(
    image: Image.Image,
    hue: float | str | Sequence[int] = "yellow",
    width: float = 35.0,
    saturation: float = 1.6,
    lightness: float = 0.1,
    others: float = 1.0,
    pull: float = 0.0,
) -> Image.Image:
    """
    Push one colour family and (optionally) mute the rest.

    - `hue`: target as degrees (0–360), a name (`red`, `orange`, `yellow`, `green`,
      `cyan`, `teal`, `blue`, `purple`, `magenta`, `pink`) or an [r, g, b] colour.
    - `width`: half-width of the hue band in degrees; weight eases to 0 at the edge.
    - `saturation`: saturation multiplier inside the band (1 = unchanged).
    - `lightness`: brightness lift inside the band (0–1, fraction of value).
    - `others`: saturation multiplier outside the band (1 = unchanged, 0 = grey).
    - `pull`: 0–1, rotate in-band hues toward the target (tighter, purer colour).

    Near-grey pixels get little weight, so white walls and skies don't pick up the colour.
    Runs in strips (flat memory at any resolution); keeps alpha.
    """
    import numpy as np

    out = _as_rgb(image)
    centre = _hue_degrees(hue) / 360
    band = max(1.0, min(180.0, float(width))) / 360
    sat_in = max(0.0, float(saturation))
    sat_out = max(0.0, float(others))
    lift = max(0.0, min(1.0, float(lightness)))
    rotate = max(0.0, min(1.0, float(pull)))

    w, h = out.size
    rows = max(1, _GRADE_STRIP_PIXELS // max(1, w))
    result = Image.new("RGB", out.size)
    for top in range(0, h, rows):
        box = (0, top, w, min(h, top + rows))
        rgb = np.asarray(out.crop(box), dtype=np.float32) / 255
        r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
        v = rgb.max(axis=-1)
        c = v - rgb.min(axis=-1)
        s = np.where(v > 0, c / np.maximum(v, 1e-6), 0)
        safe = np.maximum(c, 1e-6)
        hh = np.where(
            v == r,
            ((g - b) / safe) % 6,
            np.where(v == g, (b - r) / safe + 2, (r - g) / safe + 4),
        ) / 6
        hh = np.where(c > 0, hh, 0)

        # Signed circular distance to the target, in turns (−0.5 … 0.5).
        diff = (centre - hh + 0.5) % 1 - 0.5
        t = np.clip(1 - np.abs(diff) / band, 0, 1)
        weight = t * t * (3 - 2 * t) * np.clip(c / 0.06, 0, 1)

        hh = (hh + rotate * weight * diff) % 1
        s = np.clip(s * (sat_out + (sat_in - sat_out) * weight), 0, 1)
        v = np.clip(v * (1 + lift * weight), 0, 1)

        # HSV → RGB.
        i = np.floor(hh * 6).astype(np.int32) % 6
        f = hh * 6 - np.floor(hh * 6)
        p, q, tt = v * (1 - s), v * (1 - s * f), v * (1 - s * (1 - f))
        choices = [
            np.stack(x, axis=-1)
            for x in ((v, tt, p), (q, v, p), (p, v, tt), (p, q, v), (tt, p, v), (v, p, q))
        ]
        px = np.choose(i[..., None], choices)
        result.paste(Image.fromarray(np.clip(px * 255 + 0.5, 0, 255).astype(np.uint8), "RGB"), box[:2])
    return _keep_alpha(result, image)


def vignette(
    image: Image.Image,
    amount: float = 0.25,
    midpoint: float = 0.55,
    feather: float = 0.6,
    roundness: float = 0.0,
    color: Sequence[int] | None = None,
    rgb: Sequence[int] | None = None,
) -> Image.Image:
    """
    Darken (or tint toward `color`) the frame edges.

    `amount` 0–1 strength, `midpoint` 0–1 how far from the centre the falloff
    starts, `feather` 0–1 how gradual it is, `roundness` 0 follows the frame's
    aspect ratio … 1 perfect circle. The mask is computed at ≤ 256 px and
    smoothly scaled up, so cost is flat at any resolution.
    """
    import math

    out = _as_rgb(image)
    w, h = out.size
    strength = max(0.0, min(1.0, float(amount)))
    if strength == 0:
        return _keep_alpha(out, image)
    scale = min(1.0, 256 / max(w, h))
    sw, sh = max(2, round(w * scale)), max(2, round(h * scale))
    rnd = max(0.0, min(1.0, float(roundness)))
    # Axis weights: 1/1 follows the frame (corners = 1, edge midpoints ≈ 0.71);
    # true pixel aspect at roundness 1 gives a circle.
    kx = 1 + rnd * (max(1.0, w / h) - 1)
    ky = 1 + rnd * (max(1.0, h / w) - 1)
    norm = math.hypot(kx, ky)
    start = max(0.0, min(1.0, float(midpoint)))
    soft = max(0.05, float(feather))
    values = []
    for yy in range(sh):
        ny = ((yy + 0.5) / sh * 2 - 1) * ky
        for xx in range(sw):
            nx = ((xx + 0.5) / sw * 2 - 1) * kx
            t = min(1.0, max(0.0, (math.hypot(nx, ny) / norm - start) / soft))
            values.append(round(255 * strength * t * t * (3 - 2 * t)))
    mask = Image.new("L", (sw, sh))
    mask.putdata(values)
    mask = mask.resize((w, h), Image.Resampling.BICUBIC)
    edge = Image.new("RGB", out.size, _rgb_tint(color, rgb, (0, 0, 0)))
    out = Image.composite(edge, out, mask)
    return _keep_alpha(out, image)


_GLOW_WORK_EDGE = 1024


def _small_copy(image: Image.Image, long_edge: int = _GLOW_WORK_EDGE) -> Image.Image:
    """RGB copy shrunk so its long side is at most `long_edge` (never enlarged)."""
    rgb = _as_rgb(image)
    w, h = rgb.size
    scale = min(1.0, long_edge / max(w, h))
    if scale >= 1.0:
        return rgb.copy()
    return rgb.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.Resampling.BILINEAR)


def _highlight_mask(small: Image.Image, threshold: float) -> Image.Image:
    """L mask of pixels brighter than `threshold` (0–1), with a soft knee."""
    t = max(0.0, min(0.99, float(threshold)))
    lut = [round(255 * max(0.0, min(1.0, (v / 255 - t) / (1 - t))) ** 1.5) for v in range(256)]
    return small.convert("L").point(lut)


def _screen_blend(base: Image.Image, light: Image.Image, amount: float) -> Image.Image:
    """Screen `light` (RGB, any size) over `base` (RGB) at `amount` 0–1."""
    if light.size != base.size:
        light = light.resize(base.size, Image.Resampling.BICUBIC)
    if amount >= 1.0:
        return ImageChops.screen(base, light)
    lut = [round(v * max(0.0, float(amount))) for v in range(256)] * 3
    return ImageChops.screen(base, light.point(lut))


def bloom(
    image: Image.Image,
    threshold: float = 0.65,
    radius_ratio: float = 0.03,
    amount: float = 0.5,
    color: Sequence[int] | None = None,
    rgb: Sequence[int] | None = None,
) -> Image.Image:
    """
    Soft diffusion glow (Pro-Mist / dreamy filter): highlights above `threshold`
    are blurred by `radius_ratio` × the short side and screened back at `amount`.
    Optional `color` multiplies the glow (e.g. warm cream). Worked at ≤ 1024 px,
    so cost is flat at any resolution.
    """
    out = _as_rgb(image)
    small = _small_copy(out)
    glow = ImageChops.multiply(small, _highlight_mask(small, threshold).convert("RGB"))
    if color is not None or rgb is not None:
        glow = ImageChops.multiply(glow, Image.new("RGB", glow.size, _rgb_tint(color, rgb, (255, 255, 255))))
    radius = max(0.5, float(radius_ratio) * min(small.size))
    glow = glow.filter(ImageFilter.GaussianBlur(radius))
    return _keep_alpha(_screen_blend(out, glow, amount), image)


_HALATION_GAIN = 10 / 3


def halation(
    image: Image.Image,
    threshold: float = 0.75,
    radius_ratio: float = 0.012,
    amount: float = 0.6,
    color: Sequence[int] | None = None,
    rgb: Sequence[int] | None = None,
) -> Image.Image:
    """
    Film halation: a red-orange (`color`) halo bleeding out of bright highlights,
    as light reflects off the film base. Like `bloom`, but the glow is tinted
    luminance rather than the highlight colour, and the halo sits around (not on)
    the source.
    """
    out = _as_rgb(image)
    small = _small_copy(out)
    mask = _highlight_mask(small, threshold)
    radius = max(0.5, float(radius_ratio) * min(small.size))
    # Keep only the spill *outside* the source (blurred minus original), boosted
    # so a faint spill still reads as a halo.
    halo = ImageChops.subtract(mask.filter(ImageFilter.GaussianBlur(radius)), mask)
    halo = halo.point(lambda v: min(255, round(v * _HALATION_GAIN)))
    tint = Image.new("RGB", small.size, _rgb_tint(color, rgb, (255, 70, 30)))
    glow = ImageChops.multiply(tint, halo.convert("RGB"))
    return _keep_alpha(_screen_blend(out, glow, amount), image)


_LEAK_ANCHORS = {
    "top_left": (-0.1, -0.1),
    "top_right": (1.1, -0.1),
    "bottom_left": (-0.1, 1.1),
    "bottom_right": (1.1, 1.1),
    "left": (-0.15, 0.45),
    "right": (1.15, 0.45),
    "top": (0.55, -0.15),
    "bottom": (0.45, 1.15),
}


def light_leak(
    image: Image.Image,
    anchor: str = "top_right",
    size: float = 0.7,
    amount: float = 0.6,
    color: Sequence[int] | None = None,
    rgb: Sequence[int] | None = None,
    core: Sequence[int] | None = None,
    streak: float = 0.35,
) -> Image.Image:
    """
    Analog light leak / "sun puddle": a warm `color` glow bleeding in from an
    edge or corner `anchor`, with a brighter `core` near the edge and a soft
    `streak` (0–1) stretched along the nearest frame edge. `size` is the reach
    as a fraction of the frame diagonal. Built at ≤ 256 px and screened in.
    """
    import numpy as np

    out = _as_rgb(image)
    w, h = out.size
    scale = min(1.0, 256 / max(w, h))
    sw, sh = max(2, round(w * scale)), max(2, round(h * scale))
    ax, ay = _LEAK_ANCHORS.get(anchor, _LEAK_ANCHORS["top_right"])
    yy, xx = np.mgrid[0:sh, 0:sw].astype(np.float32)
    nx, ny = (xx + 0.5) / sw, (yy + 0.5) / sh
    aspect = w / h
    dx, dy = (nx - ax) * aspect, ny - ay
    diag = float(np.hypot(aspect, 1.0))
    reach = max(0.05, float(size)) * diag
    s = max(0.0, min(1.0, float(streak)))
    # Stretch the falloff along the edge the anchor sits on (vertical edges → tall streak).
    if ax < 0 or ax > 1:
        dy = dy * (1 - 0.7 * s)
    else:
        dx = dx * (1 - 0.7 * s)
    d = np.hypot(dx, dy) / reach
    outer = np.clip(1 - d, 0, 1) ** 2
    inner = np.clip(1 - d * 2.2, 0, 1) ** 2
    tint = np.array(_rgb_tint(color, rgb, (255, 110, 40)), dtype=np.float32)
    hot = np.array(core if core is not None else (255, 220, 150), dtype=np.float32)
    layer = outer[..., None] * tint + inner[..., None] * (hot - tint)
    leak = Image.fromarray(np.clip(layer, 0, 255).astype(np.uint8), "RGB")
    leak = leak.resize((w, h), Image.Resampling.BICUBIC)
    return _keep_alpha(_screen_blend(out, leak, amount), image)


def film_dust(
    image: Image.Image,
    amount: float = 0.5,
    hairs: int = 3,
    scratches: int = 2,
    opacity: float = 0.75,
    seed: int = 11,
) -> Image.Image:
    """
    Scanned-film dust: seeded white specks (and a few dark ones), curly hairs and
    faint vertical scratches. Speck count follows `amount` (0–1), sizes are
    fractions of the short side, so the frame looks the same at any resolution.
    """
    import math
    import random

    out = _as_rgb(image)
    w, h = out.size
    short = min(w, h)
    rng = random.Random(int(seed))
    light = Image.new("L", out.size, 0)
    dark = Image.new("L", out.size, 0)
    draw_l, draw_d = ImageDraw.Draw(light), ImageDraw.Draw(dark)
    specks = round(max(0.0, min(1.0, float(amount))) * 160)
    for _ in range(specks):
        r = short * rng.uniform(0.0006, 0.0028) * (2.2 if rng.random() < 0.08 else 1.0)
        x, y = rng.uniform(0, w), rng.uniform(0, h)
        rx, ry = r * rng.uniform(0.6, 1.4), r * rng.uniform(0.6, 1.4)
        target = draw_d if rng.random() < 0.2 else draw_l
        target.ellipse((x - rx, y - ry, x + rx, y + ry), fill=rng.randint(150, 255))
    line_w = max(1, round(short * 0.0009))
    for _ in range(max(0, int(hairs))):
        x, y = rng.uniform(0.05, 0.95) * w, rng.uniform(0.05, 0.95) * h
        angle = rng.uniform(0, 2 * math.pi)
        step = short * 0.004
        pts = [(x, y)]
        for _ in range(rng.randint(10, 22)):
            angle += rng.uniform(-0.6, 0.6)
            x, y = x + math.cos(angle) * step, y + math.sin(angle) * step
            pts.append((x, y))
        draw_l.line(pts, fill=rng.randint(170, 230), width=line_w, joint="curve")
    for _ in range(max(0, int(scratches))):
        x = rng.uniform(0.1, 0.9) * w
        y0, y1 = sorted((rng.uniform(0, h), rng.uniform(0, h)))
        drift = rng.uniform(-0.01, 0.01) * w
        draw_l.line([(x, y0), (x + drift, y1)], fill=rng.randint(60, 110), width=line_w)
    soft = max(0.4, short * 0.0004)
    k = max(0.0, min(1.0, float(opacity)))
    light = light.filter(ImageFilter.GaussianBlur(soft)).point(lambda v: round(v * k))
    dark = dark.filter(ImageFilter.GaussianBlur(soft)).point(lambda v: round(v * k))
    out = Image.composite(Image.new("RGB", out.size, (245, 242, 232)), out, light)
    out = Image.composite(Image.new("RGB", out.size, (18, 16, 14)), out, dark)
    return _keep_alpha(out, image)


def chromatic_aberration(
    image: Image.Image,
    amount: float = 0.004,
) -> Image.Image:
    """
    Lens colour fringing: red is scaled out and blue in around the centre by
    `amount` (fraction of size), so colour edges split more toward the corners.
    """
    out = _as_rgb(image)
    w, h = out.size
    a = max(0.0, min(0.05, float(amount)))
    if a == 0:
        return _keep_alpha(out, image)
    r, g, b = out.split()

    def zoom(channel: Image.Image, k: float) -> Image.Image:
        zw, zh = max(w, round(w * k)), max(h, round(h * k))
        if (zw, zh) == (w, h):
            return channel
        big = channel.resize((zw, zh), Image.Resampling.BICUBIC)
        left, top = (zw - w) // 2, (zh - h) // 2
        return big.crop((left, top, left + w, top + h))

    # Scale every channel ≥ 1 so none leaves a border: R most, G half, B none.
    merged = Image.merge("RGB", (zoom(r, 1 + 2 * a), zoom(g, 1 + a), b))
    return _keep_alpha(merged, image)


def _weighted_blur(rgb: Image.Image, weight: Image.Image, radius: float) -> tuple[Image.Image, Image.Image]:
    """
    Normalised Gaussian blur: each output pixel averages only neighbours with
    `weight` (L, 0–255), so zero-weight pixels (a cut-out hole, transparent
    areas) don't bleed their colour. Returns (rgb, blurred weight). Where almost
    nothing nearby has weight, falls back to the plain blur.
    """
    import numpy as np

    gauss = ImageFilter.GaussianBlur(radius)
    num = ImageChops.multiply(rgb, Image.merge("RGB", (weight, weight, weight))).filter(gauss)
    den = weight.filter(gauss)
    plain = rgb.filter(gauss)
    w, h = rgb.size
    rows = max(1, _GRADE_STRIP_PIXELS // max(1, w))
    out = Image.new("RGB", rgb.size)
    for top in range(0, h, rows):
        box = (0, top, w, min(h, top + rows))
        n = np.asarray(num.crop(box), dtype=np.float32)
        d = np.asarray(den.crop(box), dtype=np.float32)[..., None]
        p = np.asarray(plain.crop(box), dtype=np.float32)
        norm = n * 255.0 / np.maximum(d, 1.0)
        # 8-bit premultiplied values get noisy at tiny weights: ease into the plain blur there.
        t = np.clip(d / 16.0, 0.0, 1.0)
        mixed = np.clip(norm * t + p * (1 - t) + 0.5, 0, 255).astype(np.uint8)
        out.paste(Image.fromarray(mixed, "RGB"), box[:2])
    return out, den


def blur(
    image: Image.Image,
    radius_ratio: float = 0.01,
    exclude: Image.Image | None = None,
    exclude_grow: float = 0.004,
) -> Image.Image:
    """
    Gaussian blur by `radius_ratio` × the short side (lens / background blur).
    Large radii are computed on a shrunken copy and scaled back, so cost stays
    flat. RGBA is blurred with premultiplied alpha, so transparent pixels don't
    darken the edges. `exclude` (an RGBA layer, e.g. the subject cutout) gives
    zero weight to the pixels under its alpha, grown by `exclude_grow` × the
    short side, so a hole filled with the subject's colours doesn't bleed into
    the blurred background as a dark rim.
    """
    has_alpha = image.mode == "RGBA"
    rgb = _as_rgb(image)
    w, h = rgb.size
    radius = max(0.0, float(radius_ratio)) * min(w, h)
    if radius < 0.3:
        return _keep_alpha(rgb, image)
    weight = image.getchannel("A") if has_alpha else None
    if exclude is not None:
        hole = _as_rgba(exclude).getchannel("A")
        if hole.size != rgb.size:
            hole = hole.resize(rgb.size, Image.Resampling.BILINEAR)
        grow = max(0.0, float(exclude_grow)) * min(w, h)
        if grow >= 0.5:
            hole = _dilate(hole, grow)
        keep = ImageChops.invert(hole)
        weight = keep if weight is None else ImageChops.multiply(weight, keep)
    shrink = min(1.0, 6.0 / radius) if radius > 6 else 1.0
    size = (max(1, round(w * shrink)), max(1, round(h * shrink)))
    work = rgb.resize(size, Image.Resampling.BILINEAR) if shrink < 1.0 else rgb
    if weight is None:
        out = work.filter(ImageFilter.GaussianBlur(radius * shrink))
        alpha = None
    else:
        work_w = weight.resize(size, Image.Resampling.BILINEAR) if shrink < 1.0 else weight
        out, alpha = _weighted_blur(work, work_w, radius * shrink)
    if shrink < 1.0:
        out = out.resize((w, h), Image.Resampling.BICUBIC)
        alpha = alpha.resize((w, h), Image.Resampling.BICUBIC) if alpha is not None else None
    if not has_alpha:
        return out
    if exclude is not None:
        # An `exclude` hole only steers the colour average; the layer keeps its
        # own transparency, blurred like the colour.
        alpha = blur(image.getchannel("A").convert("RGB"), radius_ratio).convert("L")
    out = out.convert("RGBA")
    out.putalpha(alpha)
    return out

# Long edge for the motion-blur work copy: streaks hide fine detail, so a larger
# frame is blurred at this size and scaled back up (flat cost at any resolution).
# LIGHTWEIGHT=1 hosts (≤ 2 MP inputs, ~1 GB RAM shared with the rembg model) use the
# smaller edge so the multi-channel work buffers stay under ~80 MB.
_MOTION_WORK_EDGE = 1600
_MOTION_WORK_EDGE_LIGHT = 1024


def motion_blur(
    image: Image.Image,
    length_ratio: float = 0.06,
    angle: float = 0.0,
    trail: float = 0.0,
    fade: float = 0.0,
    freeze: float = 0.0,
    exclude: Image.Image | None = None,
    exclude_grow: float = 0.004,
) -> Image.Image:
    """
    Directional (shutter) motion blur.

    `length_ratio` is the streak length as a fraction of the short side (≤ 0.5); `angle` is
    the direction of motion in degrees (0 → right, 90 → up). `trail` 0 smears both
    ways (camera pan / shake), 1 only behind the motion (object streaking past);
    `fade` 0–1 thins the streak toward its tail. `freeze` 0–1 mixes the sharp frame
    back in (rear-curtain flash: a crisp subject riding its own blur). Frame edges
    are extended, not filled with black (worked at ≤ 1600 px long edge, ≤ 1024 with
    LIGHTWEIGHT=1, then scaled back); RGBA blurs with premultiplied alpha, so a
    cut-out subject streaks into transparency without dark fringes. `exclude` (an
    RGBA layer, e.g. the subject cutout; RGB images only) gives zero weight to the
    pixels under its alpha, grown by `exclude_grow` × the short side, so a hole filled
    with the subject's colours isn't smeared past the subject's outline (panning).
    """
    import numpy as np

    # Capped at half the short side: the padded work copy grows with the streak.
    length = max(0.0, min(0.5, float(length_ratio)))
    keep = max(0.0, min(1.0, float(freeze)))
    has_alpha = image.mode == "RGBA"
    src = _as_rgba(image) if has_alpha else _as_rgb(image)
    w, h = src.size
    light = os.environ.get("LIGHTWEIGHT", "0").strip() == "1"
    work_edge = _MOTION_WORK_EDGE_LIGHT if light else _MOTION_WORK_EDGE
    scale = min(1.0, work_edge / max(w, h))
    work = src if scale >= 1.0 else src.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.Resampling.BILINEAR)
    px = np.asarray(work, dtype=np.float32) / 255
    if has_alpha:
        if exclude is not None:
            raise ValueError("motion_blur: exclude works on RGB layers only")
        px[..., :3] *= px[..., 3:4]
    elif exclude is not None:
        hole = _as_rgba(exclude).getchannel("A")
        if hole.size != work.size:
            hole = hole.resize(work.size, Image.Resampling.BILINEAR)
        grow = max(0.0, float(exclude_grow)) * min(work.size)
        if grow >= 0.5:
            hole = _dilate(hole, grow)
        keep_w = 1 - np.asarray(hole, dtype=np.float32)[..., None] / 255
        # Channels: weighted colour, weight, plain colour (fallback deep inside the hole).
        px = np.concatenate([px * keep_w, keep_w, px], axis=-1)
    streak = length * min(work.size)
    if streak < 1 or keep >= 1.0:
        return src.copy()

    rad = math.radians(float(angle))
    # Image y points down, so "up" (90°) is −y. A pixel at p takes source colour from
    # p + d·dir with d ≥ 0, so the streak lands behind the moving object.
    dx, dy = math.cos(rad), -math.sin(rad)
    tr = max(0.0, min(1.0, float(trail)))
    fd = max(0.0, min(1.0, float(fade)))
    samples = max(2, min(96, math.ceil(streak)))
    pad = math.ceil(streak) + 1
    padded = np.pad(px, ((pad, pad), (pad, pad), (0, 0)), mode="edge")
    sh, sw = px.shape[:2]
    # Reuse the source buffer as the accumulator and one scratch buffer for the
    # weighted copy, so the loop allocates nothing per sample.
    acc = px
    acc.fill(0)
    scratch = np.empty_like(acc)
    total = 0.0
    for i in range(samples):
        s = i / (samples - 1)
        d = streak * (s - 0.5 * (1 - tr))
        weight = 1 - fd * s
        ox, oy = round(d * dx), round(d * dy)
        np.multiply(padded[pad + oy : pad + oy + sh, pad + ox : pad + ox + sw], weight, out=scratch)
        acc += scratch
        total += weight
    del padded, scratch
    acc /= total
    if exclude is not None and not has_alpha:
        weight = acc[..., 3:4]
        # Ease into the plain streak where almost nothing outside the hole was sampled.
        t = np.clip(weight / 0.06, 0, 1)
        acc = acc[..., :3] / np.maximum(weight, 1e-4) * t + acc[..., 4:7] * (1 - t)
    if has_alpha:
        alpha = acc[..., 3:4]
        acc[..., :3] = np.where(alpha > 1e-4, acc[..., :3] / np.maximum(alpha, 1e-4), 0)
    mode = "RGBA" if has_alpha else "RGB"
    out = Image.fromarray(np.clip(acc * 255 + 0.5, 0, 255).astype(np.uint8), mode)
    if out.size != (w, h):
        out = out.resize((w, h), Image.Resampling.BICUBIC)
    if keep > 0:
        if has_alpha:
            # Sharp copy over its own streak, so the frozen subject stays crisp.
            sharp = src.copy()
            sharp.putalpha(src.getchannel("A").point(lambda v: round(v * keep)))
            out = Image.alpha_composite(out, sharp)
        else:
            out = Image.blend(out, src, keep)
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


_BOX_STYLES = {"none", "frame", "double", "corners", "label"}
# Neon title halo: brightness is fixed (part of the look, not a preset knob) and
# the radius is capped so a preset can't ask for a frame-sized glow layer.
_TEXT_GLOW_STRENGTH = 1.9
_MAX_TEXT_GLOW_RATIO = 0.05


def _frame_text_layer(
    layer: Image.Image,
    style: str,
    line: int,
    padding: int,
    color: tuple[int, int, int],
    fill: tuple[int, ...] | None,
    radius: int,
) -> Image.Image:
    """Grow a text layer by `padding` + `line` and draw a thin box behind / around the text.

    `frame`: one outline; `double`: outline plus an inner hairline; `corners`:
    viewfinder brackets only; `label`: solid `fill` (default `color`) plate.
    """
    inset = padding + line
    w, h = layer.width + 2 * inset, layer.height + 2 * inset
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(out)
    outer = (line // 2, line // 2, w - 1 - line // 2, h - 1 - line // 2)
    ink = (*color, 255)
    if style == "label" or fill is not None:
        plate = tuple(fill) if fill is not None else ink
        if len(plate) == 3:
            plate = (*plate, 255)
        draw.rounded_rectangle((0, 0, w - 1, h - 1), radius=radius, fill=plate)
    if style in {"frame", "double"}:
        draw.rounded_rectangle(outer, radius=radius, outline=ink, width=line)
    if style == "double":
        gap = max(2, line * 3)
        thin = max(1, line // 2)
        draw.rounded_rectangle(
            (outer[0] + gap, outer[1] + gap, outer[2] - gap, outer[3] - gap),
            radius=max(0, radius - gap),
            outline=ink,
            width=thin,
        )
    if style == "corners":
        arm = max(line * 4, int(min(w, h) * 0.28))
        x0, y0, x1, y1 = outer
        for cx, cy, dx, dy in ((x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)):
            draw.line([(cx, cy + dy * arm), (cx, cy), (cx + dx * arm, cy)], fill=ink, width=line, joint="curve")
    out.alpha_composite(layer, (inset, inset))
    return out


def _paste_text_block(
    canvas: Image.Image,
    value: str,
    draw_kwargs: dict,
    bbox: tuple[int, int, int, int],
    stretch: float,
    angle: float,
    glow: float,
    glow_rgb: tuple[int, int, int],
    mode: str,
    pad: int,
    box: dict | None = None,
    xy: tuple[int, int] | None = None,
) -> Image.Image:
    """Render text on its own layer, stretch it, frame it, tilt it, add a neon glow, and paste it.

    Placement follows `align`, or `xy` (top-left of the text / box) when given.
    """
    cw, ch = canvas.size
    text_w, text_h = max(1, bbox[2] - bbox[0]), max(1, bbox[3] - bbox[1])
    layer = Image.new("RGBA", (text_w, text_h), (0, 0, 0, 0))
    ImageDraw.Draw(layer).text((-bbox[0], -bbox[1]), value, **draw_kwargs)
    out_h = max(1, min(int(round(text_h * stretch)), int(ch * 0.95)))
    if out_h != text_h:
        layer = layer.resize((text_w, out_h), Image.Resampling.LANCZOS)
    if box:
        # Font bboxes carry ascender/descender room; crop to the inked glyphs so padding is even.
        inked = layer.getchannel("A").getbbox()
        if inked:
            layer = layer.crop(inked)
        layer = _frame_text_layer(layer, **box)
        if layer.height > ch:
            layer = layer.resize((layer.width, int(ch * 0.95)), Image.Resampling.LANCZOS)
    if angle:
        layer = layer.rotate(float(angle), resample=Image.Resampling.BICUBIC, expand=True)
    # Room for the glow to fade out inside the layer instead of being cut at its edge.
    spread = int(math.ceil(glow * 3)) if glow > 0 else 0
    if spread:
        padded = Image.new("RGBA", (layer.width + 2 * spread, layer.height + 2 * spread), (0, 0, 0, 0))
        padded.paste(layer, (spread, spread))
        layer = padded
    lw, lh = layer.size

    if xy is not None:
        left, top = xy[0] - spread, xy[1] - spread
    else:
        if mode in {"top_left", "left_top", "bottom_left", "left_bottom"}:
            left = pad - spread
        elif mode in {"top_right", "right_top", "bottom_right", "right_bottom"}:
            left = cw - pad - lw + spread
        else:
            left = (cw - lw) / 2
        if mode in {"top", "top_left", "left_top", "top_right", "right_top"}:
            top = pad - spread
        elif mode in {"bottom", "bottom_center", "bottom_left", "left_bottom", "bottom_right", "right_bottom"}:
            top = ch - pad - lh + spread
        else:
            top = (ch - lh) / 2
    pos = (int(round(left)), int(round(top)))

    if spread:
        # Neon halo: blurred alpha in `glow_rgb`, screened onto the canvas twice
        # (wide soft bloom + tighter hot ring) before the crisp text goes on top.
        alpha = layer.getchannel("A")
        halo = Image.new("L", canvas.size, 0)
        for radius, gain in ((glow, _TEXT_GLOW_STRENGTH), (glow * 0.35, _TEXT_GLOW_STRENGTH * 0.8)):
            soft = alpha.filter(ImageFilter.GaussianBlur(max(0.5, radius)))
            soft = soft.point(lambda v, g=gain: min(255, int(v * g)))
            halo.paste(ImageChops.lighter(halo.crop((*pos, pos[0] + lw, pos[1] + lh)), soft), pos)
        tint = Image.new("RGB", canvas.size, glow_rgb)
        lit = ImageChops.screen(canvas.convert("RGB"), ImageChops.multiply(tint, Image.merge("RGB", (halo,) * 3)))
        canvas = Image.merge("RGBA", (*lit.split(), canvas.getchannel("A")))
    canvas.alpha_composite(layer, (max(0, pos[0]), max(0, pos[1])), (max(0, -pos[0]), max(0, -pos[1])))
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
    font_size_ratio: float | None = None,
    stroke_ratio: float | None = None,
    margin_ratio: float | None = None,
    scale_y: float = 1.0,
    angle: float = 0.0,
    glow_ratio: float = 0.0,
    glow_color: Sequence[int] | None = None,
    box: str = "none",
    box_color: Sequence[int] | None = None,
    box_fill: Sequence[int] | None = None,
    box_ratio: float = 0.003,
    box_pad_ratio: float = 0.025,
    box_radius_ratio: float = 0.0,
) -> Image.Image:
    """
    Draw `text` onto an image.

    `font_size` / `stroke_width` / `margin` are px; the matching `*_ratio`
    params (fractions of the short side) override them so text keeps its
    proportions from phone to DSLR size.

    `scale_y` stretches the glyphs vertically (e.g. 1.8 for tall poster
    lettering; capped so the text fits 95% of the height). `angle` tilts the
    text (degrees, counter-clockwise). `glow_ratio` (fraction of the short side,
    capped at 0.05) adds a fixed-brightness neon halo in `glow_color` (default:
    the stroke colour, else the fill) screened under the text.

    `box` puts the text in a thin box: `frame`, `double`, `corners` (viewfinder
    brackets) or `label` (solid plate in `box_fill`, default `box_color`).
    `box_color` defaults to the text colour; `box_ratio` (line), `box_pad_ratio`
    (gap to the text) and `box_radius_ratio` (rounded corners) are fractions of
    the short side. The box stretches, tilts and glows with the text.

    `align`: `center`, `top`, `bottom`, `top_right`, `top_left`, `bottom_right`, `bottom_left`, `bottom_center`
    (ignored when both `x` and `y` are set — then those are top-left).
    `font_style`: `sans` (default), `flow` / `script` for handwriting look, or `stamp` for a bold mono film-camera date imprint.
    Poster-title styles: `poster` (Impact → bundled Anton), `brush` (Brush Script →
    bundled Yellowtail), `slab`, `signature`, `bold_display`, `stencil`, and the
    caps-only `neon_lines` / `marquee` (bundled under `backend/fonts/`).
    `font_path`: optional `.ttf` / `.otf` / `.ttc` file; when set, it is used
    instead of `font_style`.
    """
    value = "" if text is None else str(text)
    if not value:
        return image

    canvas = _as_rgba(image)
    tint = _rgb_tint(color, rgb, (255, 255, 255))
    fill_rgba = (*tint, 255)
    stroke = int(round(_ratio_px(stroke_ratio, canvas.size, stroke_width, 1.0 if stroke_ratio else 0.0)))
    stroke_fill = None
    if stroke > 0:
        stroke_rgb = _rgb_tint(stroke_color, None, (0, 0, 0))
        stroke_fill = (*stroke_rgb, 255)

    size = max(8, int(round(_ratio_px(font_size_ratio, canvas.size, font_size))))
    style = (font_style or "sans").strip().lower()
    path = str(font_path).strip() if font_path else None
    font = _load_font(size, style, path or None)
    draw = ImageDraw.Draw(canvas)
    max_width = int(canvas.size[0] * 0.9)
    frame = None
    box_style = (box or "none").strip().lower()
    if box_style not in _BOX_STYLES:
        raise ValueError(f"Unknown box '{box}'. Use one of: {', '.join(sorted(_BOX_STYLES))}")
    if box_style != "none":
        line = max(1, int(round(_ratio_px(box_ratio, canvas.size, 3))))
        padding = max(0, int(round(_ratio_px(box_pad_ratio, canvas.size, 16))))
        frame = {
            "style": box_style,
            "line": line,
            "padding": padding,
            "color": _rgb_tint(box_color, None, tint),
            "fill": tuple(int(c) for c in box_fill) if box_fill is not None else None,
            "radius": int(round(_ratio_px(box_radius_ratio, canvas.size, 0))),
        }
        # The box needs its padding + line on both sides inside the 90% width.
        max_width = max(8, max_width - 2 * (padding + line))
    for _ in range(12):
        bbox = draw.textbbox((0, 0), value, font=font, stroke_width=stroke)
        text_w = bbox[2] - bbox[0]
        if text_w <= max_width or size <= 8:
            break
        # Jump to the size that should fit (text width ~ font size), so a
        # DSLR-scale font converges in a step or two; -1 guarantees progress.
        size = max(8, min(size - 1, int(size * max_width / max(1, text_w))))
        font = _load_font(size, style, path or None)

    draw_kwargs: dict = {
        "font": font,
        "fill": fill_rgba,
        "stroke_width": stroke,
    }
    if stroke_fill is not None:
        draw_kwargs["stroke_fill"] = stroke_fill

    stretch = max(0.1, float(scale_y))
    glow = _ratio_px(min(float(glow_ratio), _MAX_TEXT_GLOW_RATIO), canvas.size, 0.0) if glow_ratio else 0.0
    layered = stretch != 1.0 or bool(angle) or glow > 0 or frame is not None
    xy = (int(x), int(y)) if x is not None and y is not None else None

    if xy is not None and not layered:
        draw.text(xy, value, **draw_kwargs)
        return canvas

    pad = max(0, int(round(_ratio_px(margin_ratio, canvas.size, margin))))
    mode = (align or "center").strip().lower()
    bbox = draw.textbbox((0, 0), value, font=font, stroke_width=stroke)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    if layered:
        glow_rgb = _rgb_tint(glow_color, None, stroke_fill[:3] if stroke_fill else tint)
        return _paste_text_block(
            canvas, value, draw_kwargs, bbox, stretch, float(angle or 0), glow, glow_rgb,
            mode, pad, frame, xy,
        )

    def _draw_at(px: float, py: float, anchor: str) -> None:
        try:
            draw.text((px, py), value, anchor=anchor, **draw_kwargs)
        except (TypeError, ValueError):
            # Fallback when anchors aren't supported: first letter is horizontal
            # (l/m/r), second vertical (t/m/b), offsetting from the top-left origin.
            dx = {"l": 0.0, "m": -text_w / 2, "r": -text_w}.get(anchor[0], -text_w / 2)
            dy = {"t": 0.0, "m": -text_h / 2, "b": -text_h}.get(anchor[1:2], 0.0)
            draw.text((int(px + dx), int(py + dy)), value, **draw_kwargs)

    if mode in {"top_right", "right_top"}:
        _draw_at(canvas.size[0] - pad, pad, "rt")
    elif mode in {"top_left", "left_top"}:
        _draw_at(pad, pad, "lt")
    elif mode in {"bottom_right", "right_bottom"}:
        _draw_at(canvas.size[0] - pad, canvas.size[1] - pad, "rb")
    elif mode in {"bottom_left", "left_bottom"}:
        _draw_at(pad, canvas.size[1] - pad, "lb")
    elif mode in {"bottom", "bottom_center"}:
        _draw_at(canvas.size[0] / 2, canvas.size[1] - pad, "mb")
    elif mode == "top":
        _draw_at(canvas.size[0] / 2, pad, "mt")
    else:
        _draw_at(canvas.size[0] / 2, canvas.size[1] / 2, "mm")
    return canvas
