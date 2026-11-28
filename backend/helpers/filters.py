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
    # Street graffiti (all OFL, licences next to the files): wildstyle-ish
    # piece lettering, dripping wet paint, and grainy spray-can type.
    "graffiti": (_bundled("SedgwickAveDisplay-Regular.ttf"),),
    "wet_paint": (_bundled("RubikWetPaint-Regular.ttf"),),
    "spray": (_bundled("RubikSprayPaint-Regular.ttf"),),
    # Loose felt-pen handwriting (Nanum Pen Script, OFL) for scribbled notes.
    "scribble": (_bundled("NanumPenScript-Regular.ttf"),),
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
DOODLE_STYLES = (
    "xo", "rings", "wiggles", "stars", "hearts", "arrow", "sun",
    "cloud", "zigzag", "dots", "flower", "spiral", "bolt", "crown",
)
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


def _heart_points(cx: float, cy: float, size: float, tilt: float = 0.0) -> list[tuple[float, float]]:
    import math

    pts = []
    for i in range(65):
        t = 2 * math.pi * i / 64
        x = 16 * math.sin(t) ** 3
        y = -(13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t))
        x, y = x / 17 * size, y / 17 * size
        pts.append((cx + x * math.cos(tilt) - y * math.sin(tilt), cy + x * math.sin(tilt) + y * math.cos(tilt)))
    return pts


def _draw_extra_doodle(draw, mode, rng, cx, cy, span, line_w, fill, n, angle, wob) -> None:
    """Simple marker doodles for `doodle` styles beyond xo/rings/wiggles/stars/hearts/dots."""
    import math

    theta = math.radians(angle)
    cos_t, sin_t = math.cos(theta), math.sin(theta)

    def rot(u: float, v: float) -> tuple[float, float]:
        return cx + u * cos_t - v * sin_t, cy + u * sin_t + v * cos_t

    j = line_w * wob * 2
    if mode == "arrow":
        # Gently curved shaft along `angle`, head at the far end.
        shaft = [rot((t - 0.5) * span, -span * 0.12 * math.sin(math.pi * t)) for t in (k / 24 for k in range(25))]
        _stroke(draw, shaft, line_w, fill)
        tip = shaft[-1]
        back = math.atan2(tip[1] - shaft[-4][1], tip[0] - shaft[-4][0]) + math.pi
        head = span * 0.16
        for side in (-0.5, 0.5):
            end = (tip[0] + head * math.cos(back + side), tip[1] + head * math.sin(back + side))
            _stroke(draw, _wobble_line(rng, tip, end, j, 4), line_w, fill)
    elif mode == "sun":
        core = span * 0.2
        _stroke(draw, _wobble_circle(rng, cx, cy, core, j), line_w, fill)
        rays = max(8, n)
        for k in range(rays):
            a = 2 * math.pi * k / rays + rng.uniform(-0.08, 0.08)
            r0, r1 = core * 1.45, core * rng.uniform(2.1, 2.5)
            _stroke(draw, _wobble_line(rng, (cx + r0 * math.cos(a), cy + r0 * math.sin(a)),
                                       (cx + r1 * math.cos(a), cy + r1 * math.sin(a)), j, 4), line_w, fill)
    elif mode == "cloud":
        # Outer outline of three overlapping puffs above a flat base.
        u = span / 2
        puffs = [(-0.42 * u, 0.05 * u, 0.36 * u), (0.0, -0.18 * u, 0.48 * u), (0.42 * u, 0.02 * u, 0.38 * u)]
        base_y = cy + 0.3 * u

        def covered(px: float, py: float, skip: int) -> bool:
            return any(
                k != skip and (px - cx - ox) ** 2 + (py - cy - oy) ** 2 < r * r * 0.995
                for k, (ox, oy, r) in enumerate(puffs)
            )

        for k, (ox, oy, r) in enumerate(puffs):
            arc: list[tuple[float, float]] = []
            for i in range(121):
                t = 2 * math.pi * i / 120
                px, py = cx + ox + r * math.cos(t), cy + oy + r * math.sin(t)
                if py <= base_y and not covered(px, py, k):
                    arc.append((px, py))
                elif len(arc) > 1:
                    _stroke(draw, arc, line_w, fill)
                    arc = []
                else:
                    arc = []
            if len(arc) > 1:
                _stroke(draw, arc, line_w, fill)
        half_base = math.sqrt(max(0.0, puffs[0][2] ** 2 - (base_y - cy - puffs[0][1]) ** 2))
        left = cx + puffs[0][0] - half_base
        half_base = math.sqrt(max(0.0, puffs[2][2] ** 2 - (base_y - cy - puffs[2][1]) ** 2))
        right = cx + puffs[2][0] + half_base
        _stroke(draw, _wobble_line(rng, (left, base_y), (right, base_y), j, 8), line_w, fill)
    elif mode == "zigzag":
        gap = line_w * 3.4
        teeth = 7
        for i in range(n):
            offset = (i - (n - 1) / 2) * gap
            pts = [rot((k / (2 * teeth) - 0.5) * span, offset + (line_w * 1.6 if k % 2 else -line_w * 1.6)) for k in range(2 * teeth + 1)]
            _stroke(draw, pts, line_w, fill)
    elif mode == "flower":
        petals = max(5, n)
        center = span * 0.1
        petal = span * 0.17
        for k in range(petals):
            a = 2 * math.pi * k / petals
            px, py = cx + (center + petal) * math.cos(a), cy + (center + petal) * math.sin(a)
            pts = []
            for i in range(33):
                t = 2 * math.pi * i / 32
                u, v = petal * math.cos(t), petal * 0.55 * math.sin(t)
                pts.append((px + u * math.cos(a) - v * math.sin(a), py + u * math.sin(a) + v * math.cos(a)))
            _stroke(draw, pts, line_w, fill)
        _stroke(draw, _wobble_circle(rng, cx, cy, center, j), line_w, fill)
    elif mode == "spiral":
        turns = 2.6
        pts = []
        for i in range(161):
            t = i / 160
            r = span * 0.5 * t
            a = 2 * math.pi * turns * t + theta
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
        _stroke(draw, pts, line_w, fill)
    elif mode == "bolt":
        u = span / 2
        shape = [(0.15, -1.0), (-0.45, 0.1), (-0.02, 0.1), (-0.25, 1.0), (0.5, -0.2), (0.05, -0.2), (0.15, -1.0)]
        _stroke(draw, [rot(x * u * 0.95, y * u) for x, y in shape], line_w, fill)
    elif mode == "crown":
        # Street-art crown: three spiked points with a ball on each tip.
        u = span / 2
        shape = [(-1.0, 0.55), (-1.0, -0.45), (-0.5, 0.05), (0.0, -0.8), (0.5, 0.05), (1.0, -0.45), (1.0, 0.55), (-1.0, 0.55)]
        _stroke(draw, [rot(x * u, y * u * 0.85) for x, y in shape], line_w, fill)
        for tip_x, tip_y in ((-1.0, -0.45), (0.0, -0.8), (1.0, -0.45)):
            px, py = rot(tip_x * u, (tip_y - 0.18) * u * 0.85)
            r = line_w * 1.3
            draw.ellipse((px - r, py - r, px + r, py + r), fill=fill)


DOODLE_FRAME_STYLES = ("line", "double", "dashes", "dots", "zigzag", "waves", "corners")


def doodle_frame(
    image: Image.Image,
    style: str = "line",
    color: Sequence[int] | str | None = None,
    rgb: Sequence[int] | None = None,
    inset: float = 0.035,
    stroke: float = 0.006,
    jitter: float = 0.12,
    opacity: float = 1.0,
    seed: int = 7,
) -> Image.Image:
    """
    Hand-drawn border just inside the image edges.

    `style`: `line` (wobbly rectangle, corners overshoot like a marker), `double`,
    `dashes`, `dots`, `zigzag`, `waves`, or `corners` (bracket marks only).
    `inset` and `stroke` are fractions of the short side. `color: "auto"` inks dark
    on light borders and white on dark ones. The frame is drawn into a one-channel
    mask (2× and downsampled up to 4 MP for marker-smooth edges, 1× above) and the
    ink is painted through it onto a single copy, so a 61 MP frame costs one image
    copy plus a 1-byte mask rather than several RGBA layers.
    """
    import math
    import random

    mode = (style or "line").strip().lower()
    if mode not in DOODLE_FRAME_STYLES:
        raise ValueError(f"style must be one of {', '.join(DOODLE_FRAME_STYLES)}")
    w, h = image.size
    short = min(w, h)
    pad = max(2.0, float(inset) * short)
    stroke_px = max(1.0, float(stroke) * short)
    ss = _DOODLE_SUPERSAMPLE if w * h <= _DOODLE_SUPERSAMPLE_MAX_PIXELS else 1
    line_w = max(2, int(round(stroke_px * ss)))
    alpha = int(round(255 * max(0.0, min(1.0, float(opacity)))))
    if isinstance(color, str):
        if color.strip().lower() != "auto":
            raise ValueError("color must be an [r, g, b] list or 'auto'")
        band = max(1, int(pad * 2))
        strips = [image.crop((0, 0, w, band)).convert("L"), image.crop((0, h - band, w, h)).convert("L")]
        luma = sum(ImageStat.Stat(s_).mean[0] for s_ in strips) / len(strips)
        ink = DOODLE_DARK_INK if luma > DOODLE_AUTO_LUMA_THRESHOLD else (255, 255, 255)
    else:
        ink = _rgb_tint(color, rgb, (255, 255, 255))
    fill = alpha  # coverage in the one-channel mask; the ink colour is applied at paste time
    rng = random.Random(int(seed))
    j = line_w * float(jitter) * 3

    layer = Image.new("L", (w * ss, h * ss), 0)
    draw = ImageDraw.Draw(layer)
    x0, y0, x1, y1 = pad * ss, pad * ss, (w - pad) * ss, (h - pad) * ss
    sides = [((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))]

    def along(a, b, t):
        return a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t

    for a, b in sides:
        length = math.hypot(b[0] - a[0], b[1] - a[1])
        nx, ny = (b[1] - a[1]) / length, -(b[0] - a[0]) / length  # outward-ish normal
        if mode in {"line", "double"}:
            over = line_w * 2.5
            ux, uy = (b[0] - a[0]) / length, (b[1] - a[1]) / length
            start, end = (a[0] - ux * over, a[1] - uy * over), (b[0] + ux * over * 0.4, b[1] + uy * over * 0.4)
            _stroke(draw, _wobble_line(rng, start, end, j, 16), line_w, fill)
            if mode == "double":
                gap = line_w * 2.6
                s2 = (start[0] - nx * gap, start[1] - ny * gap)
                e2 = (end[0] - nx * gap, end[1] - ny * gap)
                _stroke(draw, _wobble_line(rng, s2, e2, j, 16), max(1, line_w // 2), fill)
        elif mode == "dashes":
            dash, gap = line_w * 6, line_w * 4
            t = 0.0
            while t < length:
                t1 = min(length, t + dash)
                _stroke(draw, _wobble_line(rng, along(a, b, t / length), along(a, b, t1 / length), j * 0.5, 3), line_w, fill)
                t = t1 + gap
        elif mode == "dots":
            step = line_w * 4
            for k in range(int(length // step) + 1):
                px, py = along(a, b, min(1.0, k * step / length))
                r = line_w * 0.75
                draw.ellipse((px - r, py - r, px + r, py + r), fill=fill)
        elif mode in {"zigzag", "waves"}:
            period = line_w * 8
            amp = line_w * 1.8
            count = max(2, int(length / period))
            pts = []
            for k in range(count * 8 + 1):
                t = k / (count * 8)
                px, py = along(a, b, t)
                phase = 2 * math.pi * count * t
                off = amp * (math.sin(phase) if mode == "waves" else (2 / math.pi) * math.asin(math.sin(phase)))
                pts.append((px + nx * off, py + ny * off))
            _stroke(draw, pts, line_w, fill)
    if mode == "corners":
        arm = short * ss * 0.12
        for cx_, cy_, dx, dy in ((x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)):
            _stroke(draw, _wobble_line(rng, (cx_, cy_ + dy * arm), (cx_, cy_), j, 6), line_w, fill)
            _stroke(draw, _wobble_line(rng, (cx_, cy_), (cx_ + dx * arm, cy_), j, 6), line_w, fill)

    if ss > 1:
        layer = layer.resize((w, h), Image.Resampling.LANCZOS)
    out = image.copy() if image.mode in {"RGB", "RGBA"} else image.convert("RGB")
    out.paste((*ink, 255) if out.mode == "RGBA" else ink, (0, 0, w, h), layer)
    return out


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
    `stars` (`count` four-point sparkles), `hearts` (`count` outlined hearts),
    `arrow` (one curved arrow pointing along `angle`), `sun` (circle + rays; `count`
    rays, at least 8), `cloud` (one puffy outline), `zigzag` (`count` parallel
    zigzags along `angle`), `dots` (`count` scattered filled dots), `flower`
    (petals, at least 5), `spiral` (one loose spiral), `bolt` (lightning outline).
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
    if mode not in DOODLE_STYLES:
        raise ValueError(f"style must be one of {', '.join(DOODLE_STYLES)}")
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
    elif mode in {"stars", "hearts", "dots"}:
        for i in range(n):
            ang = rng.uniform(0, 2 * math.pi)
            dist = span / 2 * (0.25 + 0.75 * (i / max(1, n - 1))) if n > 1 else 0.0
            sx, sy = cx + dist * math.cos(ang), cy + dist * math.sin(ang)
            if mode == "hearts":
                _stroke(draw, _heart_points(sx, sy, span * rng.uniform(0.09, 0.14), rng.uniform(-0.3, 0.3)), line_w, fill)
                continue
            if mode == "dots":
                r = span * rng.uniform(0.025, 0.05) + line_w / 2
                draw.ellipse((sx - r, sy - r, sx + r, sy + r), fill=fill)
                continue
            arm = span * rng.uniform(0.09, 0.14)
            pinch = arm * 0.18
            star = []
            for k in range(8):
                t = math.pi / 4 * k - math.pi / 2
                r = arm if k % 2 == 0 else pinch
                star.append((sx + r * math.cos(t), sy + r * math.sin(t)))
            draw.polygon(star, fill=fill)
    else:
        _draw_extra_doodle(draw, mode, rng, cx, cy, span, line_w, fill, n, float(angle), wob)

    if ss > 1:
        layer = layer.resize((rw, rh), Image.Resampling.LANCZOS)
    out = base.copy()
    out.alpha_composite(layer, (rx0, ry0))
    if image.mode != "RGBA":
        out = out.convert(image.mode if image.mode in {"RGB", "L"} else "RGB")
    return out



# --- Codex (Leonardo-style notebook) doodles --------------------------------

CODEX_KINDS = (
    "notes", "geometry", "vitruvian", "gears", "wing", "vortex", "proportion",
    "aerial_screw", "parachute", "pulley", "optics",
    "bird_wing", "bat_wing",
)
CODEX_SEPIA = (88, 54, 28)
# Largest element: at most this × the short side (bounds the drawing buffer).
CODEX_MAX_SPAN = 1.2
# Drawing buffer cap: bigger elements are drawn at reduced scale, then enlarged.
_CODEX_MAX_BUFFER_PIXELS = 16_000_000
# Image.info key where each codex element records the box it drew, so later
# `avoid_subject` elements can steer clear of earlier ones.
CODEX_BOXES_KEY = "codex_boxes"
_CODEX_EDGE_ANCHORS = ("left", "right", "top", "bottom")
_CODEX_MAX_TAKEN_OVERLAP = 0.3


def _known_font_style(style: str) -> bool:
    text = (style or "").strip().lower()
    return text in {"sans", "flow", "script", "hand", "cursive", "stamp", "mono", "typewriter"} or text in _DISPLAY_FONT_CANDIDATES


def _box_overlap(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    """Fraction of box `a` covered by box `b`."""
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    area = max(1e-6, (a[2] - a[0]) * (a[3] - a[1]))
    return ix * iy / area


def _codex_pick_anchor(
    base: Image.Image,
    anchor: str,
    half: float,
    around: Image.Image,
    taken: Sequence[Sequence[float]],
) -> str:
    """
    Like `_clear_anchor`, but also avoids boxes earlier codex elements drew
    (`taken`) and, when every mirror corner is blocked, tries the edge centres.
    First candidate clear of both wins; otherwise the lowest combined score.
    """
    width, height = base.size
    alpha = around.getchannel("A")
    candidates = [a for a in _mirror_anchors(anchor) + list(_CODEX_EDGE_ANCHORS) if a != "center"]
    seen: list[str] = []
    best, best_score = anchor, float("inf")
    for name in candidates:
        if name in seen:
            continue
        seen.append(name)
        fx, fy = _DOODLE_ANCHORS[name]
        cx, cy = fx * width, fy * height
        box = (max(0, int(cx - half)), max(0, int(cy - half)), min(width, int(cx + half)), min(height, int(cy + half)))
        if box[2] <= box[0] or box[3] <= box[1]:
            continue
        subject = ImageStat.Stat(alpha.crop(box)).mean[0] / 255
        clash = max((_box_overlap(box, tuple(t)) for t in taken), default=0.0)
        if subject <= DOODLE_AVOID_MAX_OVERLAP and clash <= _CODEX_MAX_TAKEN_OVERLAP:
            return name
        score = subject / DOODLE_AVOID_MAX_OVERLAP + clash / _CODEX_MAX_TAKEN_OVERLAP
        if score < best_score:
            best, best_score = name, score
    return best
# Italian-flavoured filler for the mirror-written notes (generic words, no quotation).
_CODEX_WORDS = (
    "il", "la", "del", "della", "che", "per", "moto", "acqua", "aria", "peso", "forza",
    "ala", "uccello", "ruota", "linea", "punto", "corpo", "lume", "ombra", "occhio",
    "misura", "braccio", "testa", "piede", "centro", "cerchio", "quadro", "vento",
    "onda", "vite", "leva", "polo", "moto", "tempo", "sole", "terra", "sopra", "sotto",
    "come", "quanto", "sia", "dove", "ogni", "parte", "grado", "angolo", "natura",
)


def _codex_notes(layer, rng, cx, cy, span, ink, lines, font_px, mirror, font_style):
    """A paragraph of pseudo-handwriting (optionally mirror-written) centred at (cx, cy)."""
    width = span
    line_h = font_px * 1.25
    total = line_h * lines
    font = _load_font(max(6, int(font_px)), font_style)
    block = Image.new("L", (int(width) + 4, int(total + font_px) + 4), 0)
    bdraw = ImageDraw.Draw(block)
    for i in range(lines):
        # Ragged right edge; the last line is short, like the end of a paragraph.
        limit = width * (rng.uniform(0.35, 0.6) if i == lines - 1 else rng.uniform(0.82, 1.0))
        words: list[str] = []
        while True:
            cand = " ".join(words + [rng.choice(_CODEX_WORDS)])
            if bdraw.textlength(cand, font=font) > limit and words:
                break
            words = cand.split(" ")
            if len(words) > 40:
                break
        bdraw.text((rng.uniform(0, font_px * 0.3), i * line_h), " ".join(words), fill=255, font=font)
    if mirror:
        block = block.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    x0, y0 = int(cx - block.width / 2), int(cy - total / 2)
    color_layer = Image.new("RGBA", block.size, ink)
    color_layer.putalpha(ImageChops.multiply(block, Image.new("L", block.size, ink[3])))
    layer.alpha_composite(color_layer, (max(0, x0), max(0, y0)), (max(0, -x0), max(0, -y0)))


def _codex_label(draw, rng, x, y, text, size, fill, font_style):
    font = _load_font(max(6, int(size)), font_style)
    draw.text((x, y), text, fill=fill, font=font, anchor="mm")


def _quad(a, m, b, n=12):
    """Quadratic Bézier a→b through control m, as n+1 points."""
    return [((1 - t) ** 2 * a[0] + 2 * (1 - t) * t * m[0] + t * t * b[0],
             (1 - t) ** 2 * a[1] + 2 * (1 - t) * t * m[1] + t * t * b[1])
            for t in (i / n for i in range(n + 1))]


def _codex_feather(draw, base, ang, length, width, line_w, fill, paper, barbs=3):
    """
    One flight feather as a closed shape: asymmetric vanes (wider trailing
    side), filled with `paper` (so later feathers overlap earlier ones like
    shingles) and outlined in ink, plus a shaft and a few barb strokes.
    """
    import math

    ux, uy = math.cos(ang), math.sin(ang)
    nx, ny = -uy, ux
    tip = (base[0] + ux * length, base[1] + uy * length)
    thin = max(1, line_w // 2)
    sides = []
    for side, wscale in ((1, 1.0), (-1, 0.5)):
        ctrl = (base[0] + ux * length * 0.62 + nx * width * wscale * side * 1.6,
                base[1] + uy * length * 0.62 + ny * width * wscale * side * 1.6)
        sides.append(_quad(base, ctrl, tip, 14))
    outline = sides[0] + sides[1][::-1]
    if paper is not None:
        draw.polygon(outline, fill=paper)
    _stroke(draw, outline + [outline[0]], max(1, line_w * 2 // 3), fill)
    _stroke(draw, [base, (base[0] + ux * length * 0.9, base[1] + uy * length * 0.9)], thin, fill)
    for k in range(barbs):
        t = 0.28 + 0.52 * k / max(1, barbs - 1)
        on = (base[0] + ux * length * t, base[1] + uy * length * t)
        out = (on[0] + (nx * 0.8 + ux * 0.45) * width * 0.9, on[1] + (ny * 0.8 + uy * 0.45) * width * 0.9)
        _stroke(draw, [on, out], thin, fill)


def _codex_bird_wing(draw, rng, cx, cy, span, line_w, fill, paper):
    import math

    root = (cx - span * 0.44, cy + span * 0.06)
    wrist = (cx + span * 0.1, cy - span * 0.27)
    arm = _quad(root, (cx - span * 0.2, cy - span * 0.3), wrist, 24)
    # Primaries fanned from the wrist: inner (pointing down) first, outer on top.
    for k in range(9, -1, -1):
        ang = math.radians(-14 + k * 9.5)
        length = span * (0.47 - 0.017 * k)
        base = (wrist[0] - span * 0.012 * k, wrist[1] + span * 0.012 * k)
        _codex_feather(draw, base, ang, length, span * 0.042, line_w, fill, paper, 3)
    # Secondaries hanging from the arm, root side first.
    for k in range(9):
        base = arm[1 + k * 2]
        ang = math.radians(98 - k * 2.2)
        _codex_feather(draw, base, ang, span * (0.27 + 0.006 * k), span * 0.038, line_w, fill, paper, 2)
    # Two rows of short covert feathers over the secondaries' bases.
    for row, (length, width) in enumerate(((0.15, 0.034), (0.08, 0.028))):
        for k in range(10):
            base = arm[k * 2 + row]
            ang = math.radians(100 - k * 3.5)
            _codex_feather(draw, base, ang, span * length, span * width, line_w, fill, paper, 1)
    # Leading-edge bone drawn last, over every feather base.
    _stroke(draw, arm, line_w + max(1, line_w // 2), fill)
    r = line_w * 2.2
    draw.ellipse((wrist[0] - r, wrist[1] - r, wrist[0] + r, wrist[1] + r), fill=fill)


def _codex_bat_wing(draw, rng, cx, cy, span, line_w, fill, wob):
    import math

    root = (cx - span * 0.44, cy + span * 0.04)
    elbow = (cx - span * 0.12, cy - span * 0.2)
    wrist = (cx + span * 0.08, cy - span * 0.28)
    bone_w = line_w + max(1, line_w // 2)
    thin = max(1, line_w // 2)
    _stroke(draw, _wobble_line(rng, root, elbow, wob * 0.4, 8), bone_w, fill)
    _stroke(draw, _wobble_line(rng, elbow, wrist, wob * 0.4, 8), bone_w, fill)
    # Jointed finger spars fanning from the wrist (each with a knuckle).
    tips = []
    for k, (ang, length) in enumerate(((-18, 0.44), (8, 0.46), (34, 0.42), (62, 0.36))):
        a = math.radians(ang)
        knuckle = (wrist[0] + math.cos(a) * span * length * 0.45, wrist[1] + math.sin(a) * span * length * 0.45)
        bend = a + math.radians(10)
        tipp = (knuckle[0] + math.cos(bend) * span * length * 0.55, knuckle[1] + math.sin(bend) * span * length * 0.55)
        _stroke(draw, _wobble_line(rng, wrist, knuckle, wob * 0.3, 6), line_w, fill)
        _stroke(draw, _wobble_line(rng, knuckle, tipp, wob * 0.3, 6), line_w, fill)
        for pt in (knuckle,):
            rr = line_w * 1.8
            _stroke(draw, _wobble_circle(rng, pt[0], pt[1], rr, 0.0), thin, fill)
        tips.append(tipp)
    # Thumb claw at the wrist.
    _stroke(draw, _quad(wrist, (wrist[0] - span * 0.02, wrist[1] - span * 0.08), (wrist[0] - span * 0.06, wrist[1] - span * 0.1), 6), line_w, fill)
    for pt in (elbow, wrist):
        rr = line_w * 2.4
        draw.ellipse((pt[0] - rr, pt[1] - rr, pt[0] + rr, pt[1] + rr), fill=fill)
    # Scalloped membrane edge: finger tip → finger tip, then back to the body.
    chain = tips + [(root[0] + span * 0.06, root[1] + span * 0.12)]
    for a, b in zip(chain, chain[1:]):
        mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
        # Bow the edge inward toward the wrist.
        dx, dy = wrist[0] - mx, wrist[1] - my
        d = math.hypot(dx, dy) or 1.0
        ctrl = (mx + dx / d * span * 0.07, my + dy / d * span * 0.07)
        _stroke(draw, _quad(a, ctrl, b, 14), line_w, fill)
    # Light shading: short parallel strokes along each membrane panel near the edge.
    for a, b in zip(chain, chain[1:]):
        for t in (0.25, 0.4, 0.55, 0.7):
            px_, py_ = a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
            dx, dy = wrist[0] - px_, wrist[1] - py_
            d = math.hypot(dx, dy) or 1.0
            _stroke(draw, [(px_ + dx / d * span * 0.04, py_ + dy / d * span * 0.04),
                           (px_ + dx / d * span * 0.1, py_ + dy / d * span * 0.1)], thin, fill)


def _codex_gear(draw, rng, cx, cy, radius, teeth, line_w, fill, wob):
    import math

    pts = []
    tooth = radius * 0.16
    phase = rng.uniform(0, 2 * math.pi)
    for k in range(teeth * 4 + 1):
        t = phase + 2 * math.pi * k / (teeth * 4)
        r = radius + (tooth if k % 4 in (1, 2) else 0) + rng.uniform(-wob, wob)
        pts.append((cx + r * math.cos(t), cy + r * math.sin(t)))
    _stroke(draw, pts, line_w, fill)
    _stroke(draw, _wobble_circle(rng, cx, cy, radius * 0.22, wob), line_w, fill)
    spokes = rng.choice((4, 5, 6))
    for k in range(spokes):
        t = phase + 2 * math.pi * k / spokes
        a = (cx + radius * 0.22 * math.cos(t), cy + radius * 0.22 * math.sin(t))
        b = (cx + radius * 0.82 * math.cos(t), cy + radius * 0.82 * math.sin(t))
        _stroke(draw, _wobble_line(rng, a, b, wob, 6), max(1, line_w * 2 // 3), fill)
    _stroke(draw, _wobble_circle(rng, cx, cy, radius * 0.82, wob), max(1, line_w * 2 // 3), fill)


def codex_doodle(
    image: Image.Image,
    kind: str = "notes",
    color: Sequence[int] | None = None,
    rgb: Sequence[int] | None = None,
    anchor: str = "top_left",
    x: float | None = None,
    y: float | None = None,
    size: float = 0.3,
    stroke: float = 0.003,
    angle: float = 0.0,
    opacity: float = 0.85,
    lines: int = 6,
    mirror: bool = True,
    font_style: str = "scribble",
    labels: bool = True,
    subject_fit: float | None = None,
    max_size: float | None = None,
    subject_y: float | None = None,
    paper: Sequence[int] | None = None,
    flip: bool = False,
    offset_x: float = 0.0,
    offset_y: float = 0.0,
    jitter: float = 0.35,
    seed: int = 5,
    around: Image.Image | None = None,
    avoid_subject: bool = False,
) -> Image.Image:
    """
    Draw one Leonardo-notebook element in thin ink (sepia by default).

    `kind`: `notes` (a paragraph of `lines` rough handwritten lines of
    Italian-flavoured filler, `size` wide, mirror-written when `mirror`), `geometry` (circle
    with inscribed square + triangle, diagonals, lettered points), `vitruvian`
    (circle + square, centred on the subject with `anchor: subject`), `gears`
    (two meshing toothed wheels), `wing` (bat-like flying-machine wing with ribs),
    `vortex` (water-eddy spiral studies), `proportion` (a measuring scale with
    ticks and numbers), `aerial_screw` (helical flying machine on a platform),
    `parachute` (pyramid canopy with cords and a hanging figure), `pulley`
    (pulley block with ropes and a hanging weight), `optics` (an eye with
    converging light rays and a lens).
    `max_size` (fraction of the short side) caps the size from `subject_fit`,
    so a full-frame subject doesn't push the element off the frame.
    `subject_y` (with `anchor: subject`, 0 = top … 1 = bottom of the subject
    bbox) sets the centre's height within the subject, e.g. 0.2 ≈ shoulders.
    `bird_wing` (feather study: fanned primaries from the wrist, secondaries
    along the arm, scalloped covert rows) and `bat_wing` (ornithopter frame:
    jointed finger spars from the wrist with a scalloped, lightly shaded
    membrane) both grow rightwards from a root at the element's left; flip
    the second of a pair. `paper` ([r, g, b], `bird_wing`) fills each feather
    so later feathers overlap earlier ones; without it they are outlines only.
    `flip` mirrors the element left↔right (e.g. a pair of wings);
    `offset_x` / `offset_y` shift its centre by that fraction of its size. Placement, `avoid_subject`, `size` / `stroke` (fractions
    of the short side) work like `doodle`; `angle` rotates the element.
    `subject_fit` (with `anchor: subject`) sets `size` to that multiple of the
    subject bbox's long side. `labels` adds small handwritten letters/numbers.
    `font_style` must be a known style (default `scribble`). Each element is
    capped at `CODEX_MAX_SPAN` × the short side and records the box it drew in
    `image.info["codex_boxes"]`; a later `avoid_subject` element avoids both
    the subject and those boxes (trying mirror corners, then edge centres).
    All randomness is seeded; drawn only in the element's region (2×
    supersampled up to 4 MP, 1× up to 16 MP, reduced scale beyond).
    """
    import math
    import random

    mode = (kind or "notes").strip().lower()
    if mode not in CODEX_KINDS:
        raise ValueError(f"kind must be one of {', '.join(CODEX_KINDS)}")
    n_lines = int(lines)
    if not 1 <= n_lines <= 20:
        raise ValueError("lines must be between 1 and 20")
    for name, value in (("size", size), ("stroke", stroke), ("angle", angle), ("opacity", opacity), ("jitter", jitter)):
        if not math.isfinite(float(value)):
            raise ValueError(f"{name} must be a finite number")
    if float(size) <= 0:
        raise ValueError("size must be > 0")
    if not _known_font_style(font_style):
        raise ValueError(f"unknown font_style: {font_style!r}")

    base = _as_rgba(image)
    w, h = base.size
    short = min(w, h)
    span_px = float(size) * short
    mode_anchor = (anchor or "center").strip().lower()
    bbox = around.getchannel("A").getbbox() if around is not None and around.mode == "RGBA" else None
    if subject_fit is not None and mode_anchor == "subject":
        if bbox is None:
            return image.copy()
        span_px = float(subject_fit) * max(bbox[2] - bbox[0], bbox[3] - bbox[1])
    if max_size is not None:
        if not math.isfinite(float(max_size)) or float(max_size) <= 0:
            raise ValueError("max_size must be > 0")
        span_px = min(span_px, float(max_size) * short)
    span_px = max(8.0, min(span_px, CODEX_MAX_SPAN * short))
    stroke_px = max(1.0, float(stroke) * short)
    taken = list(image.info.get(CODEX_BOXES_KEY, ()))
    if (
        avoid_subject and around is not None and around.mode == "RGBA" and (x is None or y is None)
        and mode_anchor in _DOODLE_ANCHORS and mode_anchor != "center"
    ):
        anchor = _codex_pick_anchor(base, mode_anchor, span_px / 2, around, taken)
    center_x, center_y = _doodle_center(base.size, anchor, x, y, around)
    if subject_y is not None and mode_anchor == "subject" and bbox is not None:
        if not math.isfinite(float(subject_y)):
            raise ValueError("subject_y must be a finite number")
        center_y = bbox[1] + float(subject_y) * (bbox[3] - bbox[1])
    for name, value in (("offset_x", offset_x), ("offset_y", offset_y)):
        if not math.isfinite(float(value)):
            raise ValueError(f"{name} must be a finite number")
    center_x += float(offset_x) * span_px
    center_y += float(offset_y) * span_px

    half = span_px * 0.75 + stroke_px * 6
    # Draw on a square canvas around the centre so rotation keeps the element whole.
    side = int(math.ceil(2 * half))
    if side * side <= _DOODLE_SUPERSAMPLE_MAX_PIXELS:
        ss = float(_DOODLE_SUPERSAMPLE)
    elif side * side <= _CODEX_MAX_BUFFER_PIXELS:
        ss = 1.0
    else:  # huge element on a huge photo: draw smaller, enlarge after
        ss = math.sqrt(_CODEX_MAX_BUFFER_PIXELS / (side * side))
    ink = _rgb_tint(color, rgb, CODEX_SEPIA)
    alpha = int(round(255 * max(0.0, min(1.0, float(opacity)))))
    fill = (*ink, alpha)
    rng = random.Random(int(seed))
    span = span_px * ss
    line_w = max(1, int(round(stroke_px * ss)))
    wob = float(jitter) * line_w * 2
    work_side = max(1, int(round(side * ss)))
    layer = Image.new("RGBA", (work_side, work_side), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    cx = cy = work_side / 2
    label_px = span * 0.07
    style = font_style or "scribble"

    if mode == "notes":
        # Letter size follows the block width (~22 characters a line); many
        # lines are squeezed so the block stays within ~1.1 × its width.
        font_px = min(span * 0.075, span * 1.1 / n_lines / 1.25)
        _codex_notes(layer, rng, cx, cy, span, fill, n_lines, font_px, bool(mirror), style)
    elif mode in ("geometry", "vitruvian"):
        r = span / 2
        _stroke(draw, _wobble_circle(rng, cx, cy, r, wob), line_w, fill)
        if mode == "vitruvian":
            # Leonardo's square sits lower than the circle: base on the circle's bottom.
            sq = r * 1.64
            top, bottom = cy + r - sq, cy + r
            corners = [(cx - sq / 2, top), (cx + sq / 2, top), (cx + sq / 2, bottom), (cx - sq / 2, bottom)]
            for a, b in zip(corners, corners[1:] + corners[:1]):
                _stroke(draw, _wobble_line(rng, a, b, wob), line_w, fill)
            # Construction: centre lines + diagonals of the square, faint.
            thin = max(1, line_w // 2)
            _stroke(draw, _wobble_line(rng, (cx, cy - r), (cx, cy + r), wob), thin, fill)
            _stroke(draw, _wobble_line(rng, (cx - r, cy), (cx + r, cy), wob), thin, fill)
            _stroke(draw, _wobble_line(rng, corners[0], corners[2], wob), thin, fill)
            _stroke(draw, _wobble_line(rng, corners[1], corners[3], wob), thin, fill)
            for k in range(1, 8):  # tick marks along the square's base
                tx = corners[3][0] + sq * k / 8
                _stroke(draw, [(tx, bottom - line_w * 3), (tx, bottom + line_w * 3)], thin, fill)
        else:
            tri = [(cx + r * math.cos(t), cy + r * math.sin(t))
                   for t in (-math.pi / 2, math.pi / 6, 5 * math.pi / 6)]
            sqr = [(cx + r * math.cos(t), cy + r * math.sin(t))
                   for t in (math.pi / 4, 3 * math.pi / 4, 5 * math.pi / 4, 7 * math.pi / 4)]
            for poly in (tri, sqr):
                for a, b in zip(poly, poly[1:] + poly[:1]):
                    _stroke(draw, _wobble_line(rng, a, b, wob), line_w, fill)
            thin = max(1, line_w // 2)
            _stroke(draw, _wobble_line(rng, sqr[0], sqr[2], wob), thin, fill)
            _stroke(draw, _wobble_line(rng, sqr[1], sqr[3], wob), thin, fill)
            _stroke(draw, _wobble_line(rng, (cx - r * 1.25, cy), (cx + r * 1.25, cy), wob), thin, fill)
            dot = line_w * 1.6
            for px_, py_ in tri + sqr:
                draw.ellipse((px_ - dot, py_ - dot, px_ + dot, py_ + dot), fill=fill)
            if labels:
                for letter, (px_, py_) in zip("abcdefg", tri + sqr):
                    ox, oy = (px_ - cx) * 0.16, (py_ - cy) * 0.16
                    _codex_label(draw, rng, px_ + ox, py_ + oy, letter, label_px * 1.4, fill, style)
    elif mode == "gears":
        r1 = span * 0.28
        teeth1 = rng.randint(12, 16)
        g1 = (cx - span * 0.14, cy - span * 0.06)
        _codex_gear(draw, rng, *g1, r1, teeth1, line_w, fill, wob)
        r2 = r1 * 0.58
        t = rng.uniform(-0.6, 0.4)
        d = (r1 + r2) * 1.12
        g2 = (g1[0] + d * math.cos(t), g1[1] + d * math.sin(t) * -1)
        _codex_gear(draw, rng, *g2, r2, max(7, int(teeth1 * 0.58)), line_w, fill, wob)
        if labels:
            _codex_label(draw, rng, g1[0], g1[1] + r1 * 1.45, "a", label_px * 1.4, fill, style)
            _codex_label(draw, rng, g2[0], g2[1] + r2 * 1.6, "b", label_px * 1.4, fill, style)
    elif mode == "wing":
        root = (cx - span * 0.45, cy + span * 0.05)
        tip = (cx + span * 0.48, cy - span * 0.12)
        peak = (cx - span * 0.05, cy - span * 0.42)
        spar = [((1 - t) ** 2 * root[0] + 2 * (1 - t) * t * peak[0] + t * t * tip[0],
                 (1 - t) ** 2 * root[1] + 2 * (1 - t) * t * peak[1] + t * t * tip[1])
                for t in (k / 40 for k in range(41))]
        _stroke(draw, spar, line_w, fill)
        ribs = 6
        trail = []
        for k in range(1, ribs + 1):
            sp = spar[int(k / (ribs + 1) * 40)]
            end = (sp[0] + span * 0.08 * (k - ribs / 2) / ribs, sp[1] + span * (0.42 - 0.04 * k))
            _stroke(draw, _wobble_line(rng, sp, end, wob, 8), max(1, line_w * 2 // 3), fill)
            trail.append(end)
        # Scalloped trailing edge between rib ends (membrane).
        edge_pts = [root] + trail + [tip]
        for a, b in zip(edge_pts, edge_pts[1:]):
            mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2 - span * 0.035)
            arc = [((1 - t) ** 2 * a[0] + 2 * (1 - t) * t * mid[0] + t * t * b[0],
                    (1 - t) ** 2 * a[1] + 2 * (1 - t) * t * mid[1] + t * t * b[1])
                   for t in (k / 10 for k in range(11))]
            _stroke(draw, arc, max(1, line_w * 2 // 3), fill)
        # Pivot + pull cord.
        dot = line_w * 2.2
        draw.ellipse((root[0] - dot, root[1] - dot, root[0] + dot, root[1] + dot), fill=fill)
        _stroke(draw, _wobble_line(rng, root, (root[0] + span * 0.1, root[1] + span * 0.35), wob), max(1, line_w // 2), fill)
    elif mode == "bird_wing":
        paper_fill = None if paper is None else (*_rgb_tint(paper, None, (236, 222, 190)), alpha)
        _codex_bird_wing(draw, rng, cx, cy, span, line_w, fill, paper_fill)
    elif mode == "bat_wing":
        _codex_bat_wing(draw, rng, cx, cy, span, line_w, fill, wob)
    elif mode == "vortex":
        for k in range(3):
            ex = cx + rng.uniform(-0.25, 0.25) * span
            ey = cy + rng.uniform(-0.2, 0.2) * span
            rad = span * rng.uniform(0.12, 0.24)
            turns = rng.uniform(2.2, 3.2)
            spin = rng.choice((-1, 1))
            pts = []
            steps = 90
            for i in range(steps + 1):
                t = i / steps
                th = spin * 2 * math.pi * turns * t
                rr = rad * (1 - t * 0.92) + rng.uniform(-wob, wob) * 0.3
                pts.append((ex + rr * math.cos(th), ey + rr * math.sin(th) * 0.8))
            _stroke(draw, pts, line_w, fill)
        for k in range(5):  # flowing current lines
            oy = cy + (k - 2) * span * 0.11
            pts = [(cx - span * 0.48 + span * 0.96 * t,
                    oy + span * 0.04 * math.sin(2 * math.pi * (t * 1.6 + k * 0.3)))
                   for t in (i / 30 for i in range(31))]
            _stroke(draw, pts, max(1, line_w // 2), fill)
    elif mode == "aerial_screw":
        # Helical sail: a squashed spiral (ellipses rising), mast, platform.
        mast_top, mast_bot = (cx, cy - span * 0.42), (cx, cy + span * 0.3)
        _stroke(draw, _wobble_line(rng, mast_top, mast_bot, wob), line_w, fill)
        turns, steps = 2.6, 160
        pts = []
        for i in range(steps + 1):
            t = i / steps
            th = 2 * math.pi * turns * t
            rr = span * (0.42 - 0.12 * t)
            pts.append((cx + rr * math.cos(th), cy - span * 0.05 - span * 0.34 * t + rr * 0.22 * math.sin(th)))
        _stroke(draw, pts, line_w, fill)
        thin = max(1, line_w * 2 // 3)
        for k in range(6):  # spokes from mast to the sail rim
            t = (k + 0.5) / 6
            idx = int(t * steps)
            _stroke(draw, _wobble_line(rng, (cx, pts[idx][1]), pts[idx], wob, 6), thin, fill)
        base_y = cy + span * 0.3
        plat = [(cx - span * 0.3, base_y), (cx + span * 0.3, base_y),
                (cx + span * 0.22, base_y + span * 0.08), (cx - span * 0.22, base_y + span * 0.08)]
        for a, b in zip(plat, plat[1:] + plat[:1]):
            _stroke(draw, _wobble_line(rng, a, b, wob), line_w, fill)
        for sx_ in (-0.2, 0.2):  # crank handles
            _stroke(draw, _wobble_line(rng, (cx, base_y - span * 0.06), (cx + span * sx_, base_y - span * 0.02), wob), thin, fill)
    elif mode == "parachute":
        apex = (cx, cy - span * 0.46)
        bl, br = (cx - span * 0.36, cy - span * 0.04), (cx + span * 0.36, cy - span * 0.04)
        back = (cx + span * 0.1, cy - span * 0.1)
        for a, b in ((apex, bl), (apex, br), (bl, br), (apex, back)):
            _stroke(draw, _wobble_line(rng, a, b, wob), line_w, fill)
        _stroke(draw, _wobble_line(rng, bl, back, wob), max(1, line_w // 2), fill)
        _stroke(draw, _wobble_line(rng, back, br, wob), max(1, line_w // 2), fill)
        # Cords to a small stick figure.
        hx, hy = cx, cy + span * 0.24
        thin = max(1, line_w // 2)
        for corner in (bl, br, back):
            _stroke(draw, _wobble_line(rng, corner, (hx, hy), wob), thin, fill)
        head = span * 0.035
        _stroke(draw, _wobble_circle(rng, hx, hy - head, head, wob * 0.3), thin, fill)
        body_bot = (hx, hy + span * 0.13)
        _stroke(draw, _wobble_line(rng, (hx, hy), body_bot, wob), line_w, fill)
        for dx_ in (-1, 1):
            _stroke(draw, [(hx, hy + span * 0.03), (hx + dx_ * span * 0.07, hy - span * 0.03)], thin, fill)
            _stroke(draw, [body_bot, (hx + dx_ * span * 0.05, body_bot[1] + span * 0.09)], thin, fill)
    elif mode == "pulley":
        beam_y = cy - span * 0.44
        _stroke(draw, _wobble_line(rng, (cx - span * 0.4, beam_y), (cx + span * 0.4, beam_y), wob), line_w, fill)
        for k in range(7):  # hatching on the beam
            bx = cx - span * 0.38 + k * span * 0.12
            _stroke(draw, [(bx, beam_y), (bx - span * 0.05, beam_y - span * 0.05)], max(1, line_w // 2), fill)
        r1, r2 = span * 0.12, span * 0.09
        p1 = (cx - span * 0.08, beam_y + span * 0.2)
        p2 = (cx + span * 0.1, cy + span * 0.06)
        _stroke(draw, _wobble_line(rng, (p1[0], beam_y), p1, wob), line_w, fill)
        for (px_, py_), r in ((p1, r1), (p2, r2)):
            _stroke(draw, _wobble_circle(rng, px_, py_, r, wob * 0.5), line_w, fill)
            dot = line_w * 1.8
            draw.ellipse((px_ - dot, py_ - dot, px_ + dot, py_ + dot), fill=fill)
        thin = max(1, line_w * 2 // 3)
        # Rope: down the left of p1 to the pull, over to p2, up to the beam.
        _stroke(draw, _wobble_line(rng, (p1[0] - r1, p1[1]), (p1[0] - r1, cy + span * 0.42), wob), thin, fill)
        _stroke(draw, _wobble_line(rng, (p1[0] + r1, p1[1]), (p2[0] - r2, p2[1]), wob), thin, fill)
        _stroke(draw, _wobble_line(rng, (p2[0] + r2, p2[1]), (p2[0] + r2, beam_y), wob), thin, fill)
        # Weight hanging from the lower pulley.
        wy = p2[1] + r2 + span * 0.08
        _stroke(draw, _wobble_line(rng, (p2[0], p2[1] + r2), (p2[0], wy), wob), thin, fill)
        box = [(p2[0] - span * 0.08, wy), (p2[0] + span * 0.08, wy),
               (p2[0] + span * 0.1, wy + span * 0.15), (p2[0] - span * 0.1, wy + span * 0.15)]
        for a, b in zip(box, box[1:] + box[:1]):
            _stroke(draw, _wobble_line(rng, a, b, wob), line_w, fill)
        if labels:
            _codex_label(draw, rng, p2[0], wy + span * 0.075, "p", label_px * 1.3, fill, style)
    elif mode == "optics":
        ex, ey = cx + span * 0.22, cy
        # Eye: almond outline + iris + pupil.
        top = [(ex - span * 0.2 + span * 0.4 * t, ey - span * 0.12 * math.sin(math.pi * t)) for t in (k / 24 for k in range(25))]
        bot = [(ex - span * 0.2 + span * 0.4 * t, ey + span * 0.1 * math.sin(math.pi * t)) for t in (k / 24 for k in range(25))]
        _stroke(draw, top, line_w, fill)
        _stroke(draw, bot, line_w, fill)
        _stroke(draw, _wobble_circle(rng, ex - span * 0.03, ey, span * 0.075, wob * 0.3), line_w, fill)
        pr = span * 0.03
        draw.ellipse((ex - span * 0.03 - pr, ey - pr, ex - span * 0.03 + pr, ey + pr), fill=fill)
        # Lens + rays from an object converging through it to the eye.
        lx = cx - span * 0.12
        lens = [(lx + span * 0.03 * math.sin(math.pi * t), cy - span * 0.2 + span * 0.4 * t) for t in (k / 20 for k in range(21))]
        lens2 = [(lx - span * 0.03 * math.sin(math.pi * t), cy - span * 0.2 + span * 0.4 * t) for t in (k / 20 for k in range(21))]
        _stroke(draw, lens, line_w, fill)
        _stroke(draw, lens2, line_w, fill)
        thin = max(1, line_w // 2)
        ox_ = cx - span * 0.46
        for k in range(5):
            oy_ = cy + (k - 2) * span * 0.09
            mid = (lx, cy + (k - 2) * span * 0.07)
            _stroke(draw, _wobble_line(rng, (ox_, oy_), mid, wob, 6), thin, fill)
            _stroke(draw, _wobble_line(rng, mid, (ex - span * 0.1, ey), wob, 6), thin, fill)
        # The object: a small arrow standing on the axis.
        _stroke(draw, [(ox_, cy + span * 0.18), (ox_, cy - span * 0.18)], line_w, fill)
        _stroke(draw, [(ox_ - span * 0.03, cy - span * 0.13), (ox_, cy - span * 0.18), (ox_ + span * 0.03, cy - span * 0.13)], line_w, fill)
    else:  # proportion
        top, bottom = cy - span / 2, cy + span / 2
        _stroke(draw, _wobble_line(rng, (cx, top), (cx, bottom), wob), line_w, fill)
        ticks = 8
        for k in range(ticks + 1):
            ty = top + span * k / ticks
            length = span * (0.07 if k % 2 == 0 else 0.04)
            _stroke(draw, [(cx - length, ty), (cx + length, ty)], max(1, line_w * 2 // 3), fill)
            if labels and k % 2 == 0:
                _codex_label(draw, rng, cx + span * 0.13, ty, str(k // 2 + 1), label_px * 1.2, fill, style)
        for end in (top, bottom):  # arrow heads
            sgn = 1 if end == top else -1
            _stroke(draw, [(cx - span * 0.035, end + sgn * span * 0.05), (cx, end), (cx + span * 0.035, end + sgn * span * 0.05)], line_w, fill)

    if flip:
        layer = layer.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    if float(angle) % 360:
        layer = layer.rotate(float(angle), resample=Image.Resampling.BICUBIC)
    if layer.size != (side, side):
        down = layer.width > side
        layer = layer.resize((side, side), Image.Resampling.LANCZOS if down else Image.Resampling.BICUBIC)
    ox, oy = int(round(center_x - side / 2)), int(round(center_y - side / 2))
    out = base.copy()
    sx0, sy0 = max(0, -ox), max(0, -oy)
    sx1, sy1 = min(side, w - ox), min(side, h - oy)
    if sx1 > sx0 and sy1 > sy0:
        out.alpha_composite(layer.crop((sx0, sy0, sx1, sy1)), (ox + sx0, oy + sy0))
    if image.mode != "RGBA":
        out = out.convert(image.mode if image.mode in {"RGB", "L"} else "RGB")
    # Record where this element sits so later `avoid_subject` elements avoid it.
    reach = span_px * 0.55
    drawn = (max(0.0, center_x - reach), max(0.0, center_y - reach), min(float(w), center_x + reach), min(float(h), center_y + reach))
    out.info[CODEX_BOXES_KEY] = taken + [drawn]
    return out


def circle_backdrop(
    image: Image.Image,
    color: Sequence[int] | None = None,
    rgb: Sequence[int] | None = None,
    opacity: float = 0.5,
    size: float = 0.8,
    anchor: str = "subject",
    x: float | None = None,
    y: float | None = None,
    offset_y: float = 0.0,
    softness: float = 0.0,
    subject_fit: float | None = None,
    around: Image.Image | None = None,
) -> Image.Image:
    """
    Paint one filled, semi-transparent disc onto `image` (e.g. behind a cut-out).

    `size` is the diameter and `offset_y` / `softness` (edge feather) are
    fractions of the short side, so the look scales with resolution. Placement
    follows `doodle`: `anchor` (`subject` = centre of the `around` layer's alpha
    bbox, or a corner/edge name / `center`) or explicit `x` / `y` (0–1);
    `offset_y` then nudges the centre (negative = up). `subject_fit` caps the
    diameter at that multiple of the subject bbox's long side, so a small or
    distant subject isn't dwarfed. With `anchor: subject` and an `around` layer
    that has no visible pixels (no subject found), the image is returned as-is.
    Only the disc's region is drawn (2× supersampled up to 4 MP), so cost
    follows the disc, not the frame.
    """
    params = {"size": size, "opacity": opacity, "offset_y": offset_y, "softness": softness}
    if subject_fit is not None:
        params["subject_fit"] = subject_fit
    for name, value in params.items():
        if not math.isfinite(float(value)):
            raise ValueError(f"{name} must be a finite number")
    if float(size) <= 0:
        raise ValueError("size must be > 0")
    if subject_fit is not None and float(subject_fit) <= 0:
        raise ValueError("subject_fit must be > 0")

    base = _as_rgba(image)
    w, h = base.size
    short = min(w, h)
    bbox = around.getchannel("A").getbbox() if around is not None and around.mode == "RGBA" else None
    if (anchor or "").strip().lower() == "subject" and around is not None and bbox is None:
        return image.copy()
    diameter = float(size) * short
    if subject_fit is not None and bbox is not None:
        subject_long = max(bbox[2] - bbox[0], bbox[3] - bbox[1])
        diameter = min(diameter, float(subject_fit) * subject_long)
    feather = max(0.0, float(softness)) * short
    center_x, center_y = _doodle_center(base.size, anchor, x, y, around)
    center_y += float(offset_y) * short

    radius = diameter / 2
    half = radius + feather * 3 + 2
    rx0, ry0 = max(0, int(center_x - half)), max(0, int(center_y - half))
    rx1, ry1 = min(w, int(math.ceil(center_x + half))), min(h, int(math.ceil(center_y + half)))
    if rx1 <= rx0 or ry1 <= ry0:
        return image.copy()
    rw, rh = rx1 - rx0, ry1 - ry0
    ss = _DOODLE_SUPERSAMPLE if rw * rh <= _DOODLE_SUPERSAMPLE_MAX_PIXELS else 1

    alpha = int(round(255 * max(0.0, min(1.0, float(opacity)))))
    mask = Image.new("L", (rw * ss, rh * ss), 0)
    cx, cy = (center_x - rx0) * ss, (center_y - ry0) * ss
    r = radius * ss
    ImageDraw.Draw(mask).ellipse((cx - r, cy - r, cx + r, cy + r), fill=alpha)
    if ss > 1:
        mask = mask.resize((rw, rh), Image.Resampling.LANCZOS)
    if feather > 0:
        mask = mask.filter(ImageFilter.GaussianBlur(radius=feather))

    layer = Image.new("RGBA", (rw, rh), (*_rgb_tint(color, rgb, (220, 30, 30)), 0))
    layer.putalpha(mask)
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


def _image_seed(image: Image.Image) -> int:
    """Stable per-photo seed: CRC32 of a 16×16 greyscale thumbnail (same photo → same seed)."""
    import zlib

    thumb = image.convert("L").resize((16, 16), Image.Resampling.BILINEAR)
    return zlib.crc32(thumb.tobytes())


def paper_texture(
    image: Image.Image,
    color: Sequence[int] | None = None,
    rgb: Sequence[int] | None = None,
    tint: float = 0.35,
    grain: float = 0.08,
    stains: float = 0.12,
    fade: float = 0.0,
    seed: int | str = 11,
) -> Image.Image:
    """
    Age a print onto paper: multiply-tint toward `color` by `tint`, add fine
    `grain` speckle and low-frequency `stains` (blotchy yellowing), then `fade`
    (lift blacks toward the paper). All randomness is seeded; grain size scales
    with resolution. `seed: "auto"` derives the seed from the photo itself, so
    each picture gets its own stain / grain layout while the same photo always
    renders the same way.
    """
    import random

    out = _as_rgb(image)
    w, h = out.size
    paper_rgb = _rgb_tint(color, rgb, (236, 222, 190))
    rng = random.Random(_image_seed(out) if seed == "auto" else int(seed))

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


def _smooth_noise_1d(rng, n: int = 8):
    """Seeded smooth 1-D noise on [0, 1] → [0, 1] (cosine-interpolated knots)."""
    import numpy as np

    knots = np.asarray([rng.random() for _ in range(n + 1)], dtype=np.float32)

    def sample(t):
        pos = np.clip(t, 0.0, 1.0) * n
        i = np.minimum(pos.astype(np.int32), n - 1)
        f = pos - i
        f = (1 - np.cos(f * np.pi)) / 2
        return knots[i] * (1 - f) + knots[i + 1] * f

    return sample


_MAX_FOLDS = 12


def fold_marks(
    image: Image.Image,
    cols: int = 2,
    rows: int = 2,
    extra: int = 1,
    extra_style: str = "corner",
    extra_length: Sequence[float] = (0.16, 0.4),
    strength: float = 0.5,
    wear: float = 0.6,
    grime: float = 0.4,
    panels: float = 0.04,
    width_ratio: float = 0.004,
    jitter: float = 0.04,
    tilt: float = 1.0,
    paper: Sequence[int] | None = None,
    seed: int | str = "auto",
) -> Image.Image:
    """
    Worn creases from a poster that was folded for years and opened again.

    `cols` / `rows` are the folded panels (2 × 2 → one vertical + one horizontal
    crease); each crease is nudged off the grid by up to `jitter` (fraction of the
    side), tilted by up to `tilt` degrees and wanders slightly along its length.
    `extra` adds short random creases: `extra_style` `corner` (diagonal bends
    near the corners) or `scatter` (short straight creases anywhere, along the
    grid directions); `extra_length` is their [min, max] length as a fraction
    of the short side. `cols` / `rows` of 1 mean no full-length crease, so only
    the short ones show. Along every crease:
      - `wear` (0–1): ink cracked off in broken patches, showing `paper`;
      - `grime` (0–1): a soft brownish dirt band;
      - `strength` (0–1): the fold's ridge, lit on one side and shaded on the other.
    `cols` / `rows` are capped at 12. `panels` (0–0.2) shades each folded panel slightly differently, as a sheet
    that never lies quite flat again. `width_ratio` is the crease width as a
    fraction of the short side. `seed: "auto"` gives each photo its own layout.
    """
    import random

    import numpy as np

    out = _as_rgb(image)
    w, h = out.size
    short = min(w, h)
    base_seed = _image_seed(out) if seed == "auto" else int(seed)
    rng = random.Random(base_seed)
    clamp = lambda v, hi=1.0: max(0.0, min(hi, float(v)))
    s, wr, gr, pn = clamp(strength), clamp(wear), clamp(grime), clamp(panels, 0.2)
    jit, tilt_max = clamp(jitter, 0.2), clamp(tilt, 10.0)
    cw = max(1.0, _ratio_px(width_ratio, out.size, 3.0))
    paper_rgb = np.asarray(_rgb_tint(paper, None, (238, 230, 210)), dtype=np.float32)
    # Capped: every crease is evaluated per strip, so a typo like `cols: 500` can't stall a render.
    n_cols, n_rows = max(1, min(_MAX_FOLDS, int(cols))), max(1, min(_MAX_FOLDS, int(rows)))
    extra_style = (extra_style or "corner").strip().lower()
    if extra_style not in {"corner", "scatter"}:
        raise ValueError("extra_style must be 'corner' or 'scatter'")
    if len(extra_length) != 2:
        raise ValueError("extra_length must be [min, max]")

    creases = []

    def add(px, py, angle_deg, half_len, gain):
        a = math.radians(angle_deg)
        creases.append(
            dict(
                px=px, py=py, dx=math.cos(a), dy=math.sin(a), half=half_len,
                lit=rng.choice((-1, 1)), gain=gain,
                env=_smooth_noise_1d(rng, 6), wobble=_smooth_noise_1d(rng, 24),
                cracks=_smooth_noise_1d(rng, 160), grit=_smooth_noise_1d(rng, 12),
            )
        )

    xs_cut = [0.0]
    for i in range(1, n_cols):
        x = (i / n_cols + rng.uniform(-jit, jit)) * w
        xs_cut.append(x)
        add(x, h / 2, 90 + rng.uniform(-tilt_max, tilt_max), math.inf, rng.uniform(0.75, 1.0))
    ys_cut = [0.0]
    for i in range(1, n_rows):
        y = (i / n_rows + rng.uniform(-jit, jit)) * h
        ys_cut.append(y)
        add(w / 2, y, rng.uniform(-tilt_max, tilt_max), math.inf, rng.uniform(0.75, 1.0))
    lo, hi = sorted((clamp(extra_length[0]), clamp(extra_length[1])))
    for _ in range(max(0, min(8, int(extra)))):
        if extra_style == "corner":
            cx = rng.choice((rng.uniform(0.02, 0.2), rng.uniform(0.8, 0.98))) * w
            cy = rng.choice((rng.uniform(0.02, 0.2), rng.uniform(0.8, 0.98))) * h
            angle = rng.choice((45, 135)) + rng.uniform(-20, 20)
        else:
            # A short crease anywhere, running roughly along the fold grid.
            cx, cy = rng.uniform(0.12, 0.88) * w, rng.uniform(0.12, 0.88) * h
            angle = rng.choice((0, 90)) + rng.uniform(-6, 6)
        add(cx, cy, angle, short * rng.uniform(lo, hi) / 2, rng.uniform(0.6, 0.9))
    panel_gain = [[1 + pn * rng.uniform(-1, 1) for _ in xs_cut] for _ in ys_cut]

    # uint8 frame + float32 work on ≤ 1 MP strips only, so a 61 MP photo stays bounded.
    pixels = np.asarray(out, dtype=np.uint8).copy()
    strip = max(1, _GRADE_STRIP_PIXELS // max(1, w))
    xs = np.arange(w, dtype=np.float32)[None, :]
    col_idx = np.searchsorted(np.asarray(xs_cut[1:], dtype=np.float32), xs[0])
    for y0 in range(0, h, strip):
        y1 = min(h, y0 + strip)
        ys = np.arange(y0, y1, dtype=np.float32)[:, None]
        fine = np.random.default_rng((base_seed + y0) & 0xFFFFFFFF).random((y1 - y0, w), dtype=np.float32)
        shade = np.zeros((y1 - y0, w), dtype=np.float32)  # + lighten / − darken
        dirt = np.zeros_like(shade)
        scuff = np.zeros_like(shade)
        for c in creases:
            rx, ry = xs - c["px"], ys - c["py"]
            t = rx * c["dx"] + ry * c["dy"]
            if math.isinf(c["half"]):
                u = t / (abs(c["dx"]) * w + abs(c["dy"]) * h) + 0.5
                env = 0.6 + 0.4 * c["env"](u)
            else:
                u = t / (2 * c["half"]) + 0.5
                edge = np.clip(np.minimum(u, 1 - u) * 5, 0, 1)
                env = edge * edge * (3 - 2 * edge) * (0.6 + 0.4 * c["env"](u))
            d = (rx * -c["dy"] + ry * c["dx"]) / cw + (c["wobble"](u) - 0.5) * 1.6
            near = np.abs(d) < 10
            if not near.any():
                continue
            env = env * c["gain"]
            g = np.exp(-0.5 * d * d)
            shade += np.where(near, c["lit"] * -d * g * 1.65 * env, 0)
            dirt += np.where(near, np.exp(-0.5 * (d / 3.0) ** 2) * (0.5 + 0.5 * c["grit"](u)) * env, 0)
            # Cracked ink: thin core broken into patches, with fibrous pixel noise.
            broken = np.clip((c["cracks"](u) - 0.35) * 3.0, 0, 1)
            core = np.exp(-0.5 * (d / 0.9) ** 2) * (0.35 + 0.65 * fine)
            scuff = np.maximum(scuff, np.where(near, core * broken * env, 0))
        rgb = pixels[y0:y1].astype(np.float32)
        if pn > 0:
            row_idx = np.searchsorted(np.asarray(ys_cut[1:], dtype=np.float32), ys[:, 0])
            gains = np.asarray(panel_gain, dtype=np.float32)[row_idx][:, col_idx]
            rgb *= gains[..., None]
        if gr > 0:
            k = np.clip(dirt * gr * 0.35, 0, 0.6)[..., None]
            rgb *= 1 - k * (1 - np.asarray((0.82, 0.7, 0.55), dtype=np.float32))
        if s > 0:
            dl = (shade * s * 0.35)[..., None]
            rgb[:] = np.where(dl > 0, rgb + dl * (255 - rgb), rgb * (1 + dl))
        if wr > 0:
            m = np.clip(scuff * wr, 0, 1)[..., None]
            rgb[:] = rgb + m * (paper_rgb - rgb)
        pixels[y0:y1] = np.clip(rgb + 0.5, 0, 255).astype(np.uint8)
    out = Image.fromarray(pixels, "RGB")
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


def _check_xy(name: str, x: float | None, y: float | None) -> None:
    """`x` / `y` pin the centre only as a pair; one without the other is a preset typo."""
    if (x is None) != (y is None):
        raise ValueError(f"{name}: x and y must be given together")


def _alpha_centroid(alpha: Image.Image) -> tuple[float, float] | None:
    """Alpha-weighted centre (x, y) in pixels of an L mask, or None when empty."""
    import numpy as np

    small = alpha
    scale = 1.0
    if max(alpha.size) > 512:
        scale = 512 / max(alpha.size)
        small = alpha.resize((max(1, round(alpha.width * scale)), max(1, round(alpha.height * scale))), Image.Resampling.BILINEAR)
    a = np.asarray(small, dtype=np.float64)
    total = a.sum()
    if total <= 0:
        return None
    ys, xs = np.indices(a.shape)
    return ((xs * a).sum() / total + 0.5) / scale, ((ys * a).sum() / total + 0.5) / scale


# radial_blur limits: sweep caps keep the padded work copy ≤ ~2× the frame; enough
# samples that the outer streaks stay smooth (≤ ~2 px between taps at the caps).
_RADIAL_SPIN_MAX = 45.0
_RADIAL_ZOOM_MAX = 0.5
_RADIAL_MAX_SAMPLES = 96


def radial_blur(
    image: Image.Image,
    mode: str = "spin",
    amount: float = 10.0,
    x: float | None = None,
    y: float | None = None,
    offset_y: float = 0.0,
    exclude: Image.Image | None = None,
    exclude_grow: float = 0.004,
) -> Image.Image:
    """
    Circular (radial) blur around one centre: `spin` streaks along circles
    (rotational blur, `amount` = total sweep in degrees, ≤ 45) and `zoom`
    streaks along rays (`amount` = scale spread, e.g. 0.12 → 0.94×…1.06×, ≤ 0.5).
    The caps bound the edge padding (and so memory) of the work copy.
    Blur grows with distance from the centre, so the centre stays sharp.

    The centre is `x` / `y` (fractions of width / height) when given, else the
    alpha-weighted centre of `exclude` (e.g. the subject cutout, so the swirl
    sits behind the subject), else the frame centre; `offset_y` (fraction of
    the short side, negative = up) then nudges it. `exclude` also gives zero
    weight to the pixels under its alpha (grown by `exclude_grow` × short
    side), so a cut-out hole doesn't smear the subject's colours outward.
    Worked at ≤ 1600 px long edge (≤ 1024 with LIGHTWEIGHT=1) with edge-extended
    borders and scaled back, so cost is flat. RGBA blurs with its alpha as weight.
    """
    import numpy as np

    kind = (mode or "spin").strip().lower()
    if kind not in ("spin", "zoom"):
        raise ValueError("radial_blur: mode must be 'spin' or 'zoom'")
    for name, value in (("amount", amount), ("offset_y", offset_y), ("exclude_grow", exclude_grow)):
        if not math.isfinite(float(value)):
            raise ValueError(f"radial_blur: {name} must be a finite number")
    _check_xy("radial_blur", x, y)
    spread = max(0.0, min(_RADIAL_SPIN_MAX if kind == "spin" else _RADIAL_ZOOM_MAX, float(amount)))
    has_alpha = image.mode == "RGBA"
    src = _as_rgba(image) if has_alpha else _as_rgb(image)
    w, h = src.size
    if spread <= 0:
        return src.copy()

    # Centre in full-resolution pixels.
    hole = None
    if exclude is not None:
        hole = _as_rgba(exclude).getchannel("A")
        if hole.size != (w, h):
            hole = hole.resize((w, h), Image.Resampling.BILINEAR)
    if x is not None and y is not None:
        cx, cy = float(x) * w, float(y) * h
    else:
        found = _alpha_centroid(hole) if hole is not None else None
        cx, cy = found if found is not None else (w / 2, h / 2)
    cy += float(offset_y) * min(w, h)

    light = os.environ.get("LIGHTWEIGHT", "0").strip() == "1"
    work_edge = _MOTION_WORK_EDGE_LIGHT if light else _MOTION_WORK_EDGE
    scale = min(1.0, work_edge / max(w, h))
    ww, wh = max(1, round(w * scale)), max(1, round(h * scale))
    work = src if scale >= 1.0 else src.resize((ww, wh), Image.Resampling.BILINEAR)
    cx, cy = cx * scale, cy * scale

    rgb = np.asarray(work.convert("RGB"), dtype=np.float32)
    weight = np.asarray(work.getchannel("A"), dtype=np.float32) / 255 if has_alpha else None
    if hole is not None:
        small_hole = hole.resize((ww, wh), Image.Resampling.BILINEAR) if scale < 1.0 else hole
        grow = max(0.0, float(exclude_grow)) * min(ww, wh)
        if grow >= 0.5:
            small_hole = _dilate(small_hole, grow)
        keep_w = 1 - np.asarray(small_hole, dtype=np.float32) / 255
        weight = keep_w if weight is None else weight * keep_w
    # Planes: weighted colour (or plain colour) [, weight, plain colour].
    planes = [rgb[..., c] * weight if weight is not None else rgb[..., c] for c in range(3)]
    if weight is not None:
        planes += [weight] + [rgb[..., c] for c in range(3)]

    corners = [(0, 0), (ww, 0), (0, wh), (ww, wh)]
    max_r = max(math.hypot(px_ - cx, py_ - cy) for px_, py_ in corners)
    half = math.radians(spread) / 2 if kind == "spin" else spread / 2
    disp = half * max_r  # largest one-sided displacement (px), both modes
    samples = max(8, min(_RADIAL_MAX_SAMPLES, math.ceil(2 * disp / 1.5)))
    pad = math.ceil(disp) + 2
    padded = [
        Image.fromarray(np.pad(p, pad, mode="edge").astype(np.float32), "F") for p in planes
    ]
    acc = [np.zeros((wh, ww), dtype=np.float32) for _ in planes]
    for i in range(samples):
        t = i / (samples - 1) * 2 - 1  # −1…1
        if kind == "spin":
            th = t * half
            a, b, d, e = math.cos(th), -math.sin(th), math.sin(th), math.cos(th)
        else:
            s = 1 + t * half
            a, b, d, e = s, 0.0, 0.0, s
        coeffs = (a, b, cx - a * cx - b * cy + pad, d, e, cy - d * cx - e * cy + pad)
        for k, plane in enumerate(padded):
            acc[k] += np.asarray(
                plane.transform((ww, wh), Image.Transform.AFFINE, coeffs, Image.Resampling.BILINEAR)
            )
    del padded
    acc = [a_ / samples for a_ in acc]
    if weight is not None:
        wt = acc[3]
        t_ = np.clip(wt / 0.06, 0, 1)
        colour = [acc[c] / np.maximum(wt, 1e-4) * t_ + acc[4 + c] * (1 - t_) for c in range(3)]
    else:
        colour = acc[:3]
    out_px = np.clip(np.stack(colour, axis=-1) + 0.5, 0, 255).astype(np.uint8)
    out = Image.fromarray(out_px, "RGB")
    if has_alpha:
        alpha_src = work.getchannel("A")
        spun = radial_blur(alpha_src.convert("RGB"), kind, spread, x=cx / ww, y=cy / wh)
        out.putalpha(spun.convert("L"))
    if out.size != (w, h):
        out = out.resize((w, h), Image.Resampling.BICUBIC)
    return out


def _fill_hole(image: Image.Image, hole: Image.Image, radius_ratio: float = 0.05) -> Image.Image:
    """Replace the pixels under `hole` (L) with a hole-aware blur of their surroundings."""
    smooth = blur(image, radius_ratio, exclude=Image.merge("RGBA", (hole, hole, hole, hole)), exclude_grow=0)
    return Image.composite(smooth, image, hole)


def _mirror(coord: "np.ndarray", size: int) -> "np.ndarray":
    """Fold coordinates back into [0, size - 1] by mirroring at the edges."""
    import numpy as np

    if size <= 1:
        return np.zeros_like(coord)
    period = 2 * (size - 1)
    m = np.mod(coord, period)
    return np.where(m > size - 1, period - m, m)


def _bilinear(src: "np.ndarray", sx: "np.ndarray", sy: "np.ndarray", mirror: bool = False) -> "np.ndarray":
    """Sample `src` (H, W[, C]) at float coords; edges clamp, or mirror with `mirror`."""
    import numpy as np

    h, w = src.shape[:2]
    if mirror:
        sx, sy = _mirror(sx, w), _mirror(sy, h)
    sx = np.clip(sx, 0, w - 1)
    sy = np.clip(sy, 0, h - 1)
    x0 = np.floor(sx).astype(np.int32)
    y0 = np.floor(sy).astype(np.int32)
    x1 = np.minimum(x0 + 1, w - 1)
    y1 = np.minimum(y0 + 1, h - 1)
    fx = (sx - x0).astype(np.float32)
    fy = (sy - y0).astype(np.float32)
    if src.ndim == 3:
        fx, fy = fx[..., None], fy[..., None]
    top = src[y0, x0] * (1 - fx) + src[y0, x1] * fx
    bottom = src[y1, x0] * (1 - fx) + src[y1, x1] * fx
    return top * (1 - fy) + bottom * fy


_RAY_BINS = 720


def _ray_reach(mask: Image.Image, cx: float, cy: float) -> "np.ndarray":
    """
    Farthest mask pixel (alpha > half) from (cx, cy) per angle bin (`_RAY_BINS`
    around the circle), in full-resolution px; 0 where a ray never meets the
    mask. Measured on a ≤ 512 px copy, widened by one bin each side so the
    outline isn't jagged.
    """
    import numpy as np

    scale = min(1.0, 512 / max(mask.size))
    small = mask if scale >= 1.0 else mask.resize(
        (max(1, round(mask.width * scale)), max(1, round(mask.height * scale))), Image.Resampling.BILINEAR
    )
    ys, xs = np.nonzero(np.asarray(small) > 127)
    reach = np.zeros(_RAY_BINS, dtype=np.float32)
    if len(xs) == 0:
        return reach
    # Pixel corners farthest from the centre: + 1 px of slack at the work scale.
    dx = (xs + 0.5) / scale - cx
    dy = (ys + 0.5) / scale - cy
    r = np.hypot(dx, dy) + 1.0 / scale
    bins = ((np.arctan2(dy, dx) + math.pi) / (2 * math.pi) * _RAY_BINS).astype(np.int64) % _RAY_BINS
    np.maximum.at(reach, bins, r.astype(np.float32))
    return np.maximum(reach, np.maximum(np.roll(reach, 1), np.roll(reach, -1)))


def _reflect_out_of_subject(
    sx: "np.ndarray", sy: "np.ndarray", cx: float, cy: float, reach: "np.ndarray"
) -> tuple["np.ndarray", "np.ndarray"]:
    """Move samples inside the subject's reach outward, mirrored at that radius."""
    import numpy as np

    dx, dy = sx - cx, sy - cy
    r = np.hypot(dx, dy)
    pos = (np.arctan2(dy, dx) + math.pi) / (2 * math.pi) * _RAY_BINS - 0.5
    lo = np.floor(pos).astype(np.int64)
    f = (pos - lo).astype(np.float32)
    edge = reach[lo % _RAY_BINS] * (1 - f) + reach[(lo + 1) % _RAY_BINS] * f
    inside = r < edge
    if not inside.any():
        return sx, sy
    k = np.where(inside, (2 * edge - r) / np.maximum(r, 1e-3), 1.0)
    return cx + dx * k, cy + dy * k


_WARP_MODES = ("twirl", "ripple", "wave", "liquid")
_WARP_STRIP_PIXELS = 1_000_000
_WARP_STRIP_PIXELS_LIGHT = 250_000
# Liquid noise grid cap (coarse cells); keeps the 6× upsampled field ≤ ~1.5 MP per plane.
_WARP_LIQUID_MAX_CELLS = 40_000


def warp(
    image: Image.Image,
    mode: str = "ripple",
    amount: float = 0.012,
    wavelength: float = 0.06,
    radius: float = 1.0,
    falloff: float = 0.0,
    shade: float = 0.0,
    angle: float = 0.0,
    seed: int = 7,
    x: float | None = None,
    y: float | None = None,
    offset_y: float = 0.0,
    exclude: Image.Image | None = None,
    exclude_grow: float = 0.006,
) -> Image.Image:
    """
    Displace (re-map) pixels around one centre — a liquid / distortion warp
    that keeps detail sharp, unlike a blur.

    Modes (`amount` / `wavelength` are fractions of the short side unless noted):
    - `twirl`: rotate by `amount` **degrees** at the centre, easing to 0 at
      `radius` × the farthest corner (whirlpool).
    - `ripple`: concentric water rings — radial shift `amount` × sin(2πr / `wavelength`).
    - `wave`: squiggly wobble — x shifts with sin(y), y with sin(x), period
      `wavelength`, rotated by `angle` degrees.
    - `liquid`: smooth seeded noise flow (feature size `wavelength`, shift
      `amount`) — marbled, spilt-water look.
    `falloff` (fraction of the short side, 0 = off) fades the shift with
    distance from the centre (ripple / wave / liquid). `shade` (0–1) lights the
    slopes of ripple / liquid (bright crest, dark trough) for a water sheen.

    The centre is `x` / `y` (0–1) when both are given, else the alpha centroid
    of `exclude` (e.g. the subject cutout), else the frame centre; `offset_y`
    (fraction of short side) nudges it. With `exclude`, the pixels under its
    alpha (grown by `exclude_grow`) are first refilled from their surroundings,
    so the warp can't drag subject colours into the background (RGB and RGBA),
    and any sample that lands behind the subject is reflected outward past the
    subject's outline along its ray from the centre, so it picks up real
    texture instead of the smooth refill (no blurry patch beside the subject,
    even with a strong twirl).
    Sampled in row strips (smaller with LIGHTWEIGHT=1), mirrored at the frame
    edges (no smeared border streaks), so memory stays ≈ a few copies of the
    image. Liquid noise is capped at a fixed grid size, so a tiny `wavelength`
    can't blow up memory (features just stop shrinking).
    """
    import numpy as np

    kind = (mode or "").strip().lower()
    if kind not in _WARP_MODES:
        raise ValueError(f"warp: mode must be one of {', '.join(_WARP_MODES)}")
    for name, value in (("amount", amount), ("wavelength", wavelength), ("radius", radius),
                        ("falloff", falloff), ("shade", shade), ("angle", angle), ("offset_y", offset_y)):
        if not math.isfinite(float(value)):
            raise ValueError(f"warp: {name} must be a finite number")
    if float(wavelength) <= 0 or float(radius) <= 0:
        raise ValueError("warp: wavelength and radius must be > 0")
    _check_xy("warp", x, y)

    has_alpha = image.mode == "RGBA"
    src = _as_rgba(image) if has_alpha else _as_rgb(image)
    w, h = src.size
    short = min(w, h)
    hole = None
    if exclude is not None:
        hole = _as_rgba(exclude).getchannel("A")
        if hole.size != (w, h):
            hole = hole.resize((w, h), Image.Resampling.BILINEAR)
    if x is not None and y is not None:
        cx, cy = float(x) * w, float(y) * h
    else:
        found = _alpha_centroid(hole) if hole is not None else None
        cx, cy = found if found is not None else (w / 2, h / 2)
    cy += float(offset_y) * short

    reach = None  # outer radius of the subject along each ray from the centre
    if hole is not None and hole.getbbox() is not None:
        grow = max(0.0, float(exclude_grow)) * short
        filled_hole = _dilate(hole, grow) if grow >= 0.5 else hole
        src = _fill_hole(src, filled_hole)
        reach = _ray_reach(filled_hole, cx, cy)

    amt = float(amount)
    lam = float(wavelength) * short
    fall = max(0.0, float(falloff)) * short
    shd = max(0.0, min(1.0, float(shade)))
    max_r = max(math.hypot(px_ - cx, py_ - cy) for px_, py_ in ((0, 0), (w, 0), (0, h), (w, h)))

    field = None
    if kind == "liquid":
        # Smooth noise: one random value per half feature, bicubic-upsampled 6×.
        cell = max(2.0, lam / 2, math.sqrt(w * h / _WARP_LIQUID_MAX_CELLS))
        gw, gh = max(4, math.ceil(w / cell) + 2), max(4, math.ceil(h / cell) + 2)
        rng = np.random.default_rng(int(seed))
        planes = []
        for _ in range(2):
            noise = Image.fromarray(rng.standard_normal((gh, gw)).astype(np.float32), "F")
            smooth = np.asarray(noise.resize((gw * 6, gh * 6), Image.Resampling.BICUBIC), dtype=np.float32)
            planes.append(smooth / max(float(smooth.std()), 1e-6))
        field = np.stack(planes, axis=-1)
        div = np.gradient(field[..., 0], axis=1) + np.gradient(field[..., 1], axis=0)
        div /= max(float(np.abs(div).max()), 1e-6)

    px = np.asarray(src)  # uint8; _bilinear promotes per strip, so no full float copy
    out = np.empty_like(px)
    light_host = os.environ.get("LIGHTWEIGHT", "0").strip() == "1"
    strip = _WARP_STRIP_PIXELS_LIGHT if light_host else _WARP_STRIP_PIXELS
    rows = max(1, strip // max(1, w))
    xs = np.arange(w, dtype=np.float32) + 0.5
    rad = math.radians(float(angle))
    ca, sa = math.cos(rad), math.sin(rad)
    for top in range(0, h, rows):
        ys = np.arange(top, min(h, top + rows), dtype=np.float32) + 0.5
        gx, gy = np.meshgrid(xs, ys)
        dx_, dy_ = gx - cx, gy - cy
        r = np.hypot(dx_, dy_)
        light = None
        fade = np.exp(-r / fall) if fall > 0 else 1.0
        if kind == "twirl":
            t = np.clip(1 - r / (float(radius) * max_r), 0, 1)
            th = math.radians(amt) * t * t
            c, s = np.cos(th), np.sin(th)
            sx, sy = cx + c * dx_ - s * dy_, cy + s * dx_ + c * dy_
        elif kind == "ripple":
            phase = 2 * math.pi * r / lam
            shift = amt * short * np.sin(phase) * fade
            ux, uy = dx_ / np.maximum(r, 1e-3), dy_ / np.maximum(r, 1e-3)
            sx, sy = gx + ux * shift, gy + uy * shift
            if shd > 0:
                light = np.cos(phase) * fade
        elif kind == "wave":
            u = gx * ca + gy * sa
            v = -gx * sa + gy * ca
            k = 2 * math.pi / lam
            du = amt * short * np.sin(v * k) * fade
            dv = amt * short * np.sin(u * k) * fade
            sx, sy = gx + du * ca - dv * sa, gy + du * sa + dv * ca
        else:
            fxg = gx / w * (field.shape[1] - 1)
            fyg = gy / h * (field.shape[0] - 1)
            flow = _bilinear(field, fxg, fyg)
            sx = gx + flow[..., 0] * amt * short * fade
            sy = gy + flow[..., 1] * amt * short * fade
            if shd > 0:
                light = _bilinear(div, fxg, fyg) * fade
        if reach is not None:
            sx, sy = _reflect_out_of_subject(sx, sy, cx, cy, reach)
        sampled = _bilinear(px, sx - 0.5, sy - 0.5, mirror=True)
        if light is not None:
            gain = (1 + shd * 0.6 * light)[..., None]
            if has_alpha:
                sampled[..., :3] *= gain
            else:
                sampled *= gain
        out[top : top + len(ys)] = np.clip(sampled + 0.5, 0, 255).astype(np.uint8)
    return Image.fromarray(out, "RGBA" if has_alpha else "RGB")


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
    margins: Sequence[float] | None = None,
) -> Image.Image:
    """
    Place `image` on a larger solid canvas.

    `scale` multiplies width and height (e.g. 1.4 → 40% larger).
    `layout`:
      - `center` — equal margins all sides
      - `polaroid` — side margins equal; photo shifted up so the bottom band is larger

    `margins` ([left, top, right, bottom], fractions of the photo's short side)
    sets each border independently and overrides `scale` / `layout` — e.g. an
    instant-film card with thin sides and a deep bottom band.
    """
    photo = _as_rgba(image)
    tint = _rgb_tint(color if color is not None else fill, rgb, (255, 255, 255))
    if margins is not None:
        values = [float(m) for m in margins]
        if len(values) != 4 or any(not math.isfinite(m) or m < 0 or m > 2 for m in values):
            raise ValueError("margins must be four numbers in [0, 2] (left, top, right, bottom)")
        short = min(photo.size)
        left, top, right, bottom = (int(round(m * short)) for m in values)
        canvas = Image.new("RGBA", (photo.size[0] + left + right, photo.size[1] + top + bottom), (*tint, 255))
        canvas.paste(photo, (left, top), photo)
        return canvas
    factor = float(scale)
    if factor < 1.0:
        raise ValueError("scale must be >= 1.0")

    canvas_w = max(1, int(round(photo.size[0] * factor)))
    canvas_h = max(1, int(round(photo.size[1] * factor)))
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
    center: tuple[float, float] | None = None,
    shadow: float = 0.0,
    shadow_rgb: tuple[int, int, int] = (0, 0, 0),
    shadow_alpha: float = 0.0,
) -> Image.Image:
    """Render text on its own layer, stretch it, frame it, tilt it, add a neon glow, and paste it.

    Placement follows `align`, `xy` (top-left of the text / box), or `center`
    (pixel point the finished block is centred on) when given.
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
    spread = int(math.ceil(max(glow, shadow) * 3)) if max(glow, shadow) > 0 else 0
    if spread:
        padded = Image.new("RGBA", (layer.width + 2 * spread, layer.height + 2 * spread), (0, 0, 0, 0))
        padded.paste(layer, (spread, spread))
        layer = padded
    lw, lh = layer.size

    if center is not None:
        left, top = center[0] - lw / 2, center[1] - lh / 2
    elif xy is not None:
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

    if shadow > 0 and shadow_alpha > 0:
        # Soft shadow: blurred alpha multiplied in `shadow_rgb`, so it darkens a
        # bright backdrop under the letters and barely changes a dark one.
        soft = layer.getchannel("A").filter(ImageFilter.GaussianBlur(max(0.5, shadow)))
        soft = soft.point(lambda v: int(v * shadow_alpha))
        mask = Image.new("L", canvas.size, 0)
        mask.paste(soft, pos)
        white = Image.new("RGB", canvas.size, (255, 255, 255))
        mix = Image.composite(Image.new("RGB", canvas.size, shadow_rgb), white, mask)
        shaded = ImageChops.multiply(canvas.convert("RGB"), mix)
        canvas = Image.merge("RGBA", (*shaded.split(), canvas.getchannel("A")))
    if glow > 0:
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


# Some display fonts ship an almost zero-width space (Monoton / `neon_lines` is
# 0.11 em), so "MIDNIGHT DRIVE" reads as one word. Below the threshold, each
# space is repeated until the gap reaches about the target width.
_NARROW_SPACE_EM = 0.15
_MIN_WORD_GAP_EM = 0.28


def _widen_narrow_spaces(text: str, font: ImageFont.ImageFont, size: int) -> str:
    """Repeat spaces when the font's own space is too narrow to separate words."""
    if " " not in text or size <= 0:
        return text
    gap = font.getlength(" ")
    if gap <= 0 or gap >= _NARROW_SPACE_EM * size:
        return text
    return text.replace(" ", " " * math.ceil(_MIN_WORD_GAP_EM * size / gap))


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
    center_x: float | None = None,
    center_y: float | None = None,
    max_width_ratio: float | None = None,
    uppercase: bool = False,
    shadow_ratio: float = 0.0,
    shadow_color: Sequence[int] | None = None,
    shadow_opacity: float = 0.5,
) -> Image.Image:
    """
    Draw `text` onto an image.

    `uppercase: true` renders the text in capitals whatever the user typed.

    `shadow_ratio` (blur radius, fraction of the short side, capped at 0.05)
    adds a soft shadow in `shadow_color` (default near-black) at
    `shadow_opacity` (0–1) under the text. It is multiplied in, so it lifts
    pale text off a bright backdrop without drawing a hard outline.

    `center_x` / `center_y` (fractions of the width / height, both required)
    centre the finished text block on that point — e.g. inside a speech bubble
    or badge drawn with `draw_shape`. `max_width_ratio` (fraction of the width,
    default 0.9) caps the text width; longer text shrinks to fit.

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
    if uppercase:
        value = value.upper()
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
    value = _widen_narrow_spaces(value, font, size)
    draw = ImageDraw.Draw(canvas)
    width_cap = 0.9 if max_width_ratio is None else float(max_width_ratio)
    if not math.isfinite(width_cap) or not 0.05 <= width_cap <= 1.0:
        raise ValueError("max_width_ratio must be between 0.05 and 1")
    max_width = int(canvas.size[0] * width_cap)
    centre = None
    if center_x is not None or center_y is not None:
        if center_x is None or center_y is None:
            raise ValueError("center_x and center_y must be given together")
        cxf, cyf = float(center_x), float(center_y)
        if not (math.isfinite(cxf) and math.isfinite(cyf)):
            raise ValueError("center_x / center_y must be finite")
        centre = (cxf * canvas.size[0], cyf * canvas.size[1])
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
    shadow = _ratio_px(min(float(shadow_ratio), _MAX_TEXT_GLOW_RATIO), canvas.size, 0.0) if shadow_ratio else 0.0
    shadow_alpha = float(shadow_opacity)
    if not math.isfinite(shadow_alpha) or not 0.0 <= shadow_alpha <= 1.0:
        raise ValueError("shadow_opacity must be between 0 and 1")
    if shadow_alpha == 0:
        shadow = 0.0
    shadow_rgb = _rgb_tint(shadow_color, None, (20, 16, 12))
    layered = (
        stretch != 1.0 or bool(angle) or glow > 0 or shadow > 0 or frame is not None or centre is not None
    )
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
            mode, pad, frame, xy, centre, shadow, shadow_rgb, shadow_alpha,
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


# --- Repeated-text wall + half split ------------------------------------------

_TEXT_PATTERN_MAX_ROWS = 400


def text_pattern(
    image: Image.Image,
    text: str = "",
    separator: str = ".",
    color: Sequence[int] | None = None,
    rgb: Sequence[int] | None = None,
    colors: Sequence[Sequence[int]] | None = None,
    background: Sequence[int] | None = None,
    font_style: str = "bold_display",
    font_path: str | None = None,
    font_size_ratio: float = 0.06,
    sizes: Sequence[float] | None = None,
    line_spacing: float = 1.0,
    gap_ratio: float | None = None,
    stagger: float = 0.37,
    uppercase: bool = False,
    angle: float = 0.0,
    transparent: bool = False,
) -> Image.Image:
    """
    Fill a layer the size of `image` with `text` repeated as rows of
    ``TEXT.TEXT.TEXT.`` on a solid `background` (default off-white), or on a
    transparent layer with `transparent: true` (letters only — use it as a
    mask with `clip_to`).

    Sizes are fractions of the short side (`font_size_ratio`, or `sizes` cycled
    row by row for a mixed-size word wall), so the wall looks the same at any
    resolution. `colors` (list of [r, g, b]) cycles per row, else `color`.
    Rows advance by `line_spacing` × font size, or — with `gap_ratio` (fraction
    of the short side) — are packed by their actual ink height with that exact
    gap, so mixed sizes still get even spacing. Each row shifts by `stagger` of
    one repeat so words don't line up in columns. `angle` tilts the whole wall (degrees, counter-clockwise). The
    input pixels are not used — only its size. Returns RGB (RGBA if
    `transparent`).
    """
    w, h = image.size
    short = min(w, h)
    word = str(text or "").strip()
    if uppercase:
        word = word.upper()
    mode = "RGBA" if transparent else "RGB"
    fill = (0, 0, 0, 0) if transparent else _rgb_tint(background, None, (245, 243, 236))
    if not word:
        return Image.new(mode, (w, h), fill)

    ratios = [float(r) for r in (sizes or [font_size_ratio])]
    if not ratios or any(not math.isfinite(r) or r <= 0 or r > 0.5 for r in ratios):
        raise ValueError("text_pattern sizes must be in (0, 0.5]")
    spacing = float(line_spacing)
    if not math.isfinite(spacing) or spacing <= 0:
        raise ValueError("line_spacing must be > 0")
    gap_px: float | None = None
    if gap_ratio is not None:
        gap = float(gap_ratio)
        if not math.isfinite(gap) or not 0 <= gap <= 0.2:
            raise ValueError("gap_ratio must be between 0 and 0.2")
        gap_px = gap * short
    tilt = float(angle or 0.0)
    if not math.isfinite(tilt):
        raise ValueError("angle must be finite")
    palette = [_rgb_tint(c, None) for c in colors] if colors else [_rgb_tint(color, rgb, (20, 20, 20))]

    # Draw on a canvas big enough that rotating it still covers the frame.
    side = int(math.ceil(math.hypot(w, h))) + 4 if tilt else max(w, h)
    cw, ch = (side, side) if tilt else (w, h)
    canvas = Image.new(mode, (cw, ch), fill)
    draw = ImageDraw.Draw(canvas)
    unit_text = word + (separator or "")

    y = 0.0
    row = 0
    while y < ch and row < _TEXT_PATTERN_MAX_ROWS:
        size_px = max(6, int(round(ratios[row % len(ratios)] * short)))
        font = _load_font(size_px, font_style, font_path)
        unit_w = max(1.0, draw.textlength(unit_text, font=font))
        repeats = int(math.ceil(cw / unit_w)) + 2
        shift = ((row * float(stagger)) % 1.0) * unit_w
        line = unit_text * repeats
        fill_rgb = palette[row % len(palette)]
        if gap_px is None:
            draw.text((-shift, y), line, font=font, fill=fill_rgb)
            y += size_px * spacing
        else:
            # Pack by ink: put this row's glyph top at `y`, then advance by its ink height + gap.
            ink_top, ink_bottom = draw.textbbox((0, 0), unit_text, font=font)[1::2]
            draw.text((-shift, y - ink_top), line, font=font, fill=fill_rgb)
            y += max(1, ink_bottom - ink_top) + gap_px
        row += 1

    if tilt:
        canvas = canvas.rotate(tilt, resample=Image.Resampling.BICUBIC, fillcolor=fill)
        left, top = (cw - w) // 2, (ch - h) // 2
        canvas = canvas.crop((left, top, left + w, top + h))
    return canvas


def _split_x(width: int, around: Image.Image | None, split_at: str) -> float:
    """x of the vertical split line: the `around` layer's alpha centre, else mid-frame."""
    if around is None or around.mode != "RGBA":
        return width / 2
    alpha = around.getchannel("A")
    bbox = alpha.getbbox()
    if bbox is None:
        return width / 2
    if (split_at or "center").strip().lower() == "mass":
        import numpy as np

        scale = min(1.0, 512 / max(alpha.size))
        small = alpha.resize(
            (max(1, round(alpha.width * scale)), max(1, round(alpha.height * scale))),
            Image.Resampling.BILINEAR,
        )
        cols = np.asarray(small, dtype=np.float64).sum(axis=0)
        total = cols.sum()
        if total > 0:
            centre = float((cols * (np.arange(cols.size) + 0.5)).sum() / total)
            return centre / scale
    return (bbox[0] + bbox[2]) / 2


def half_mask(
    image: Image.Image,
    side: str = "left",
    around: Image.Image | None = None,
    split_at: str = "center",
    feather_ratio: float = 0.0,
) -> Image.Image:
    """
    Keep only the `side` (`left` / `right`) of a layer; the other side becomes
    transparent. The vertical split line runs through the middle of the
    `around` layer's alpha (`split_at: center` = bounding-box middle, `mass` =
    alpha centroid), or the frame's middle when `around` is missing or empty.
    `feather_ratio` (fraction of the short side) softens the cut. Returns RGBA.
    """
    keep = (side or "left").strip().lower()
    if keep not in {"left", "right"}:
        raise ValueError("side must be 'left' or 'right'")
    feather = float(feather_ratio)
    if not math.isfinite(feather) or feather < 0:
        raise ValueError("feather_ratio must be >= 0")
    base = _as_rgba(image)
    w, h = base.size
    split = _split_x(w, around, split_at)
    soft = feather * min(w, h)

    ramp = []
    for x in range(w):
        cx = x + 0.5
        if soft > 0:
            t = min(1.0, max(0.0, (split - cx) / soft + 0.5))
        else:
            t = 1.0 if cx < split else 0.0
        ramp.append(round(255 * (t if keep == "left" else 1.0 - t)))
    row = Image.new("L", (w, 1))
    row.putdata(ramp)
    mask = row.resize((w, h), Image.Resampling.NEAREST)
    base.putalpha(ImageChops.multiply(base.getchannel("A"), mask))
    return base


def clip_to(
    image: Image.Image,
    around: Image.Image | None = None,
    invert: bool = False,
) -> Image.Image:
    """
    Keep a layer only where the `around` layer is visible: the result's alpha
    is this layer's alpha times `around`'s alpha (or its inverse with
    `invert: true`). E.g. clip a photo to the letters of a transparent
    `text_pattern`, or a text wall to a subject's silhouette. Returns RGBA;
    without `around` the layer is returned unchanged.
    """
    base = _as_rgba(image)
    if around is None:
        return base
    shape = _as_rgba(around)
    if shape.size != base.size:
        shape = shape.resize(base.size, Image.Resampling.LANCZOS)
    alpha = shape.getchannel("A")
    if invert:
        alpha = ImageChops.invert(alpha)
    base.putalpha(ImageChops.multiply(base.getchannel("A"), alpha))
    return base


_BLEND_MODES = {
    "normal": None,
    "multiply": ImageChops.multiply,
    "screen": ImageChops.screen,
    "darken": ImageChops.darker,
    "lighten": ImageChops.lighter,
}


def blend(
    base: Image.Image,
    overlay: Image.Image,
    mode: str = "normal",
    opacity: float = 1.0,
) -> Image.Image:
    """
    Layer `overlay` on `base` like `composite`, with a blend `mode` (`normal`,
    `multiply`, `screen`, `darken`, `lighten`) and an `opacity` (0–1) on top of
    the overlay's own alpha. `multiply` keeps dark marks in the base showing
    through, as if the overlay were painted over print. Returns RGBA.
    """
    name = (mode or "normal").strip().lower()
    if name not in _BLEND_MODES:
        raise ValueError(f"mode must be one of {', '.join(sorted(_BLEND_MODES))}")
    amount = float(opacity)
    if not math.isfinite(amount) or not 0.0 <= amount <= 1.0:
        raise ValueError("opacity must be between 0 and 1")
    bottom = _as_rgba(base)
    top = _as_rgba(overlay)
    if top.size != bottom.size:
        top = top.resize(bottom.size, Image.Resampling.LANCZOS)
    op = _BLEND_MODES[name]
    if op is not None:
        mixed = op(bottom.convert("RGB"), top.convert("RGB")).convert("RGBA")
        mixed.putalpha(top.getchannel("A"))
        top = mixed
    if amount < 1.0:
        top.putalpha(top.getchannel("A").point(lambda v: round(v * amount)))
    return Image.alpha_composite(bottom, top)


# --- Basic shapes ---------------------------------------------------------------

_SHAPES = {"circle", "square", "triangle", "diamond", "star", "heart"}


def _shape_points(shape: str, radius: float, angle: float) -> list[tuple[float, float]]:
    """Polygon for `shape` centred on (0, 0), fitting a square of side 2·radius."""
    if shape == "square":
        pts = [(-1, -1), (1, -1), (1, 1), (-1, 1)]
    elif shape == "diamond":
        pts = [(0, -1), (1, 0), (0, 1), (-1, 0)]
    elif shape == "triangle":
        # Equilateral, as large as fits: base on y = 1, apex at y = -1.
        half = 2 / math.sqrt(3)
        pts = [(0, -1), (half, 1), (-half, 1)]
        pts = [(px / max(1.0, half), py) for px, py in pts]
    elif shape == "star":
        pts = []
        for i in range(10):
            r = 1.0 if i % 2 == 0 else 0.45
            a = math.radians(-90 + i * 36)
            pts.append((r * math.cos(a), r * math.sin(a) + 0.1))
    elif shape == "heart":
        pts = []
        for i in range(72):
            t = 2 * math.pi * i / 72
            hx = 16 * math.sin(t) ** 3
            hy = -(13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t))
            pts.append((hx / 17, (hy - 2.1) / 15))
    else:  # circle as a smooth polygon so rotation / outline share one path
        pts = [(math.cos(2 * math.pi * i / 128), math.sin(2 * math.pi * i / 128)) for i in range(128)]
    turn = math.radians(float(angle or 0.0))
    cos_t, sin_t = math.cos(turn), math.sin(turn)
    return [(radius * (px * cos_t - py * sin_t), radius * (px * sin_t + py * cos_t)) for px, py in pts]


def draw_shape(
    image: Image.Image,
    shape: str = "circle",
    x: float = 0.5,
    y: float = 0.5,
    size: float = 0.4,
    angle: float = 0.0,
    color: Sequence[int] | None = None,
    rgb: Sequence[int] | None = None,
    opacity: float = 1.0,
    fill: bool = True,
    stroke_ratio: float = 0.0,
    stroke_color: Sequence[int] | None = None,
    clear: bool = False,
) -> Image.Image:
    """
    Draw one basic `shape` (`circle`, `square`, `triangle`, `diamond`, `star`,
    `heart`) centred at (`x`, `y`) — fractions of the width / height — with
    `size` (its bounding square, a fraction of the short side) and `angle`
    (degrees, clockwise). `fill` paints it in `color`; `stroke_ratio` (fraction
    of the short side) adds an outline in `stroke_color`. `clear: true` starts
    from a transparent layer of the same size (a mask for `clip_to`). Only the
    shape's own region is drawn, 2× supersampled, so cost doesn't grow with
    the photo. Returns RGBA.
    """
    kind = (shape or "circle").strip().lower()
    if kind not in _SHAPES:
        raise ValueError(f"shape must be one of {', '.join(sorted(_SHAPES))}")
    values = {"x": x, "y": y, "size": size, "angle": angle, "opacity": opacity, "stroke_ratio": stroke_ratio}
    if any(not math.isfinite(float(v)) for v in values.values()):
        raise ValueError("draw_shape numbers must be finite")
    if float(size) <= 0 or float(size) > 3:
        raise ValueError("size must be in (0, 3]")
    if not 0.0 <= float(opacity) <= 1.0:
        raise ValueError("opacity must be between 0 and 1")
    if not 0.0 <= float(stroke_ratio) <= 0.1:
        raise ValueError("stroke_ratio must be between 0 and 0.1")

    base = Image.new("RGBA", image.size, (0, 0, 0, 0)) if clear else _as_rgba(image)
    w, h = base.size
    short = min(w, h)
    radius = float(size) * short / 2
    stroke = float(stroke_ratio) * short
    cx, cy = float(x) * w, float(y) * h
    half = radius * 1.5 + stroke + 2  # rotated corners reach √2·radius
    rx0, ry0 = max(0, int(cx - half)), max(0, int(cy - half))
    rx1, ry1 = min(w, int(math.ceil(cx + half))), min(h, int(math.ceil(cy + half)))
    if rx1 <= rx0 or ry1 <= ry0:
        return base

    ss = 2 if (rx1 - rx0) * (ry1 - ry0) <= 4_000_000 else 1
    region = ((rx1 - rx0) * ss, (ry1 - ry0) * ss)
    pts = [((px + cx - rx0) * ss, (py + cy - ry0) * ss) for px, py in _shape_points(kind, radius, angle)]
    fill_mask = Image.new("L", region, 0)
    line_mask = Image.new("L", region, 0)
    if fill:
        ImageDraw.Draw(fill_mask).polygon(pts, fill=255)
    if stroke > 0:
        ImageDraw.Draw(line_mask).line(pts + [pts[0]], fill=255, width=max(1, round(stroke * ss)), joint="curve")
    size_px = (rx1 - rx0, ry1 - ry0)
    if ss > 1:
        # Box (area) average: clean anti-aliasing without Lanczos ringing halos.
        fill_mask = fill_mask.resize(size_px, Image.Resampling.BOX)
        line_mask = line_mask.resize(size_px, Image.Resampling.BOX)

    patch = base.crop((rx0, ry0, rx1, ry1))
    scale = float(opacity)
    for mask, tint in ((fill_mask, _rgb_tint(color, rgb, (255, 255, 255))), (line_mask, _rgb_tint(stroke_color, None, (20, 20, 20)))):
        if mask.getbbox() is None:
            continue
        if scale < 1.0:
            mask = mask.point(lambda v: round(v * scale))
        layer = Image.new("RGBA", size_px, tint + (0,))
        layer.putalpha(mask)
        patch = Image.alpha_composite(patch, layer)
    base.paste(patch, (rx0, ry0))
    return base


def crop_aspect(
    image: Image.Image,
    ratio: float | Sequence[float] = 1.0,
    anchor: str = "center",
    auto_orient: bool = False,
) -> Image.Image:
    """
    Crop to an aspect `ratio` (width / height, or [width, height] such as
    [46, 62] for Instax Mini, [1, 1] Square, [99, 62] Wide), keeping as much
    of the photo as possible. `anchor` (`center` / `top` / `bottom` / `left` /
    `right`) picks which part is kept. `auto_orient: true` flips the ratio to
    match the photo's orientation (a landscape photo gets a landscape crop).
    """
    if isinstance(ratio, (int, float)):
        target = float(ratio)
    else:
        parts = [float(v) for v in ratio]
        if len(parts) != 2 or parts[1] == 0:
            raise ValueError("ratio must be a number or [width, height]")
        target = parts[0] / parts[1]
    if not math.isfinite(target) or target <= 0 or target > 20 or target < 0.05:
        raise ValueError("ratio must be between 0.05 and 20")
    w, h = image.size
    # Square photos keep the ratio as given; only clear landscape / portrait flips it.
    if auto_orient and w != h and (w > h) != (target > 1.0):
        target = 1.0 / target
    where = (anchor or "center").strip().lower()
    if where not in {"center", "top", "bottom", "left", "right"}:
        raise ValueError("anchor must be center, top, bottom, left or right")
    if w / h > target:  # too wide → trim the sides
        new_w = max(1, round(h * target))
        free = w - new_w
        left = 0 if where == "left" else free if where == "right" else free // 2
        box = (left, 0, left + new_w, h)
    else:  # too tall → trim top / bottom
        new_h = max(1, round(w / target))
        free = h - new_h
        top = 0 if where == "top" else free if where == "bottom" else free // 2
        box = (0, top, w, top + new_h)
    return image.crop(box)
