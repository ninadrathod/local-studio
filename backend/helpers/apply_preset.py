#!/usr/bin/env python3
"""
Apply a JSON preset (ordered filter steps) to an image.

Usage:
  python apply_preset.py INPUT.jpg --preset bw_bg_glowing_subject -o out.png
  python apply_preset.py INPUT.jpg --preset path/to/custom.json -o out.png

Presets live in backend/presets/ by default.

Each step names a registered filter and its parameters. The runner looks the
function up by name — it does not branch on filter type. User text is bound
into string params that equal (or contain) `$text`.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from PIL import Image

import filters as F

HELPERS_DIR = Path(__file__).resolve().parent
BACKEND_DIR = HELPERS_DIR.parent
DEFAULT_PRESETS_DIR = BACKEND_DIR / "presets"

AR_SQUARE = "square"
AR_NON_SQUARE = "non-square"
VALID_AR = frozenset({AR_SQUARE, AR_NON_SQUARE})

TEXT_INPUT_YES = "yes"
TEXT_INPUT_NO = "no"
VALID_TEXT_INPUT = frozenset({TEXT_INPUT_YES, TEXT_INPUT_NO})
MAX_PRESET_TEXT_CHARS = 200
TEXT_PLACEHOLDER = "$text"
DATETIME_PLACEHOLDER = "$datetime"
DATE_PLACEHOLDER = "$date"
TIME_PLACEHOLDER = "$time"
DATETIME_FORMAT = "%Y-%m-%d %H:%M"
DATE_FORMAT = "%Y-%m-%d"
TIME_FORMAT = "%H:%M"

# Keys that bind named layers; not forwarded to the filter function.
_LAYER_KEYS = frozenset({"on", "as", "bg_as", "base", "overlay"})


class PresetAspectRatioError(ValueError):
    """Raised when a square-only preset is applied to a non-square image."""


class PresetTextError(ValueError):
    """Raised when user text is missing or exceeds the preset's character limit."""


FilterHandler = Callable[..., None]


def normalize_ar(value: Any | None) -> str:
    """Return `square` or `non-square`. Missing/blank `ar` defaults to non-square."""
    if value is None:
        return AR_NON_SQUARE
    text = str(value).strip().lower()
    if not text:
        return AR_NON_SQUARE
    if text not in VALID_AR:
        raise ValueError("ar must be 'square' or 'non-square'")
    return text


def normalize_text_input(value: Any | None) -> str:
    """Return `yes` or `no`. Missing/blank `text_input` defaults to no."""
    if value is None:
        return TEXT_INPUT_NO
    text = str(value).strip().lower()
    if not text:
        return TEXT_INPUT_NO
    if text not in VALID_TEXT_INPUT:
        raise ValueError("text_input must be 'yes' or 'no'")
    return text


def normalize_text_character_limit(value: Any | None) -> int:
    if value is None or value == "":
        return 0
    try:
        limit = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("text_character_limit must be an integer") from exc
    if limit < 0:
        raise ValueError("text_character_limit must be >= 0")
    if limit > MAX_PRESET_TEXT_CHARS:
        raise ValueError(
            f"text_character_limit must be <= {MAX_PRESET_TEXT_CHARS}"
        )
    return limit


def normalize_default_text(value: Any | None, limit: int = 0) -> str:
    text = "" if value is None else str(value)
    cap = limit if limit > 0 else MAX_PRESET_TEXT_CHARS
    if len(text) > cap:
        raise ValueError("default_text exceeds text_character_limit")
    return text


def is_square_image(image: Image.Image) -> bool:
    width, height = image.size
    return width > 0 and width == height


def assert_preset_fits_image(image: Image.Image, ar: Any | None) -> None:
    """Square-only presets (`ar=square`) require width == height."""
    if normalize_ar(ar) == AR_SQUARE and not is_square_image(image):
        raise PresetAspectRatioError("This preset only applies to square images.")


def resolve_user_text(preset: dict[str, Any], text: str | None) -> str:
    """
    Resolve the string passed into `$text` placeholders.

    Presets with `text_input: no` ignore submitted text.
    When `text_input: yes`, omitted text uses `default_text`; a provided value
    (including empty) is used as-is and must fit `text_character_limit`.
    """
    wants_text = normalize_text_input(preset.get("text_input")) == TEXT_INPUT_YES
    if text is not None and len(text) > MAX_PRESET_TEXT_CHARS:
        raise PresetTextError(
            f"Text must be at most {MAX_PRESET_TEXT_CHARS} characters."
        )
    if not wants_text:
        return ""

    limit = normalize_text_character_limit(preset.get("text_character_limit"))
    if limit < 1:
        raise PresetTextError(
            "text_character_limit must be >= 1 when text_input is yes"
        )
    default = normalize_default_text(preset.get("default_text"), limit)
    value = default if text is None else str(text)
    if len(value) > limit:
        raise PresetTextError(f"Text must be at most {limit} characters.")
    return value


def bind_placeholders(
    value: Any,
    *,
    text: str,
    now: datetime | None = None,
) -> Any:
    """Replace `$text` / `$datetime` / `$date` / `$time` in strings (and nested structures)."""
    if isinstance(value, str):
        if value == TEXT_PLACEHOLDER:
            return text
        if value == DATETIME_PLACEHOLDER:
            stamp = now or datetime.now()
            return stamp.strftime(DATETIME_FORMAT)
        if value == DATE_PLACEHOLDER:
            stamp = now or datetime.now()
            return stamp.strftime(DATE_FORMAT)
        if value == TIME_PLACEHOLDER:
            stamp = now or datetime.now()
            return stamp.strftime(TIME_FORMAT)
        out = value
        if TEXT_PLACEHOLDER in out:
            out = out.replace(TEXT_PLACEHOLDER, text)
        if DATETIME_PLACEHOLDER in out or DATE_PLACEHOLDER in out or TIME_PLACEHOLDER in out:
            stamp = now or datetime.now()
            out = out.replace(DATETIME_PLACEHOLDER, stamp.strftime(DATETIME_FORMAT))
            out = out.replace(DATE_PLACEHOLDER, stamp.strftime(DATE_FORMAT))
            out = out.replace(TIME_PLACEHOLDER, stamp.strftime(TIME_FORMAT))
        return out
    if isinstance(value, list):
        return [bind_placeholders(item, text=text, now=now) for item in value]
    if isinstance(value, dict):
        return {
            key: bind_placeholders(item, text=text, now=now)
            for key, item in value.items()
        }
    return value


def bind_step_params(
    step: dict[str, Any],
    text: str,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    return {
        key: bind_placeholders(value, text=text, now=now)
        for key, value in step.items()
        if key != "filter"
    }


def _run_simple(fn: Callable[..., Image.Image]) -> FilterHandler:
    def run(layers: dict[str, Image.Image], *, index: int = 0, **step: Any) -> None:
        on_key = step.get("on", "image")
        if on_key not in layers:
            raise KeyError(f"Step {index}: unknown layer '{on_key}'")
        dest = step.get("as", on_key)
        call_params = {key: value for key, value in step.items() if key not in _LAYER_KEYS}
        layers[dest] = fn(layers[on_key], **call_params)

    return run


def _run_extract_subject(
    layers: dict[str, Image.Image],
    *,
    index: int = 0,
    **step: Any,
) -> None:
    source_key = step.get("on", "image")
    if source_key not in layers:
        raise KeyError(f"Step {index}: unknown layer '{source_key}'")
    subject, background = F.extract_subject_layers(
        layers[source_key],
        require_clear_subject=bool(step.get("require_clear_subject", False)),
        single_subject=bool(step.get("single_subject", False)),
    )
    layers[step.get("as", "subject")] = subject
    layers[step.get("bg_as", "background")] = background


def _run_composite(
    layers: dict[str, Image.Image],
    *,
    index: int = 0,
    **step: Any,
) -> None:
    base_key = step.get("base", "background")
    overlay_key = step.get("overlay", "subject")
    if base_key not in layers:
        raise KeyError(f"Step {index}: unknown base layer '{base_key}'")
    if overlay_key not in layers:
        raise KeyError(f"Step {index}: unknown overlay layer '{overlay_key}'")
    result = F.composite(layers[base_key], layers[overlay_key])
    layers[step.get("as", "image")] = result


def _run_doodle(
    layers: dict[str, Image.Image],
    *,
    index: int = 0,
    **step: Any,
) -> None:
    on_key = step.get("on", "image")
    if on_key not in layers:
        raise KeyError(f"Step {index}: unknown layer '{on_key}'")
    around_key = step.get("around")
    if around_key is not None and around_key not in layers:
        raise KeyError(f"Step {index}: unknown around layer '{around_key}'")
    call_params = {
        key: value for key, value in step.items() if key not in _LAYER_KEYS and key != "around"
    }
    around = layers[around_key] if around_key is not None else None
    layers[step.get("as", on_key)] = F.doodle(layers[on_key], around=around, **call_params)


def _run_excluding(fn: Callable[..., Image.Image]) -> FilterHandler:
    """Like `_run_simple`, but resolves an optional `exclude` layer name to its image."""

    def run(layers: dict[str, Image.Image], *, index: int = 0, **step: Any) -> None:
        on_key = step.get("on", "image")
        if on_key not in layers:
            raise KeyError(f"Step {index}: unknown layer '{on_key}'")
        exclude_key = step.get("exclude")
        if exclude_key is not None and exclude_key not in layers:
            raise KeyError(f"Step {index}: unknown exclude layer '{exclude_key}'")
        call_params = {
            key: value for key, value in step.items() if key not in _LAYER_KEYS and key != "exclude"
        }
        exclude = layers[exclude_key] if exclude_key is not None else None
        layers[step.get("as", on_key)] = fn(layers[on_key], exclude=exclude, **call_params)

    return run


# JSON `"filter"` name → function. Add new ops here; do not add if/else in the runner.
FILTERS: dict[str, FilterHandler] = {
    "extract_subject": _run_extract_subject,
    "composite": _run_composite,
    "brightness": _run_simple(F.brightness),
    "color": _run_simple(F.color),
    "contrast": _run_simple(F.contrast),
    "overlay": _run_simple(F.overlay),
    "grayscale": _run_simple(F.grayscale),
    "glow_border": _run_simple(F.glow_border),
    "glow_line_border": _run_simple(F.glow_line_border),
    "sticker_outline": _run_simple(F.sticker_outline),
    "posterize": _run_simple(F.posterize),
    "ink_edges": _run_simple(F.ink_edges),
    "halftone": _run_simple(F.halftone),
    "paper_texture": _run_simple(F.paper_texture),
    "color_grade": _run_simple(F.color_grade),
    "tone_curve": _run_simple(F.tone_curve),
    "shadows_highlights": _run_simple(F.shadows_highlights),
    "selective_color": _run_simple(F.selective_color),
    "vignette": _run_simple(F.vignette),
    "bloom": _run_simple(F.bloom),
    "halation": _run_simple(F.halation),
    "light_leak": _run_simple(F.light_leak),
    "film_dust": _run_simple(F.film_dust),
    "chromatic_aberration": _run_simple(F.chromatic_aberration),
    "motion_blur": _run_excluding(F.motion_blur),
    "blur": _run_excluding(F.blur),
    "draw_text": _run_simple(F.draw_text),
    "place_on_canvas": _run_simple(F.place_on_canvas),
    "upscale": _run_simple(F.upscale),
    "sharpen": _run_simple(F.sharpen),
    "denoise": _run_simple(F.denoise),
    "ai_upscale": _run_simple(F.ai_upscale),
    "doodle": _run_doodle,
}


def resolve_preset_path(preset: str | Path, presets_dir: Path = DEFAULT_PRESETS_DIR) -> Path:
    path = Path(preset)
    if path.is_file():
        return path
    candidate = presets_dir / path
    if candidate.is_file():
        return candidate
    if not path.suffix:
        candidate = presets_dir / f"{path.name}.json"
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"Preset not found: {preset} (looked in {presets_dir})")


def load_preset(preset_path: Path) -> dict[str, Any]:
    data = json.loads(preset_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "steps" not in data:
        raise ValueError(f"Preset must be an object with a 'steps' array: {preset_path}")
    if not isinstance(data["steps"], list) or not data["steps"]:
        raise ValueError(f"Preset 'steps' must be a non-empty list: {preset_path}")
    return data


def apply_steps(
    image: Image.Image,
    steps: list[dict[str, Any]],
    *,
    text: str = "",
    now: datetime | None = None,
) -> Image.Image:
    """Run ordered preset steps over named layers. Returns the final `image` layer."""
    layers: dict[str, Image.Image] = {"image": image.convert("RGBA")}
    stamp = now or datetime.now()

    for index, step in enumerate(steps):
        if not isinstance(step, dict) or "filter" not in step:
            raise ValueError(f"Step {index} must be an object with a 'filter' key")

        name = step["filter"]
        handler = FILTERS.get(name)
        if handler is None:
            allowed = ", ".join(sorted(FILTERS))
            raise ValueError(
                f"Step {index}: unknown filter '{name}'. Allowed: {allowed}"
            )

        params = bind_step_params(step, text, now=stamp)
        try:
            handler(layers, index=index, **params)
        except TypeError as exc:
            raise ValueError(f"Step {index}: {exc}") from exc

    if "image" not in layers:
        raise RuntimeError("Preset finished without an 'image' layer — add composite with as=image")
    return layers["image"]


# EXIF capture time, most specific first: DateTimeOriginal, DateTimeDigitized (Exif IFD), DateTime (IFD0).
_EXIF_IFD = 0x8769
_EXIF_DATE_TAGS = ((_EXIF_IFD, 0x9003), (_EXIF_IFD, 0x9004), (None, 0x0132))


def photo_datetime(image: Image.Image) -> datetime | None:
    """When the photo was taken, from EXIF (`YYYY:MM:DD HH:MM:SS`), or None."""
    try:
        exif = image.getexif()
    except (AttributeError, OSError, ValueError):
        return None
    for ifd, tag in _EXIF_DATE_TAGS:
        try:
            value = exif.get_ifd(ifd).get(tag) if ifd is not None else exif.get(tag)
        except (KeyError, OSError, ValueError):
            continue
        if isinstance(value, bytes):
            value = value.decode("ascii", "ignore")
        if not isinstance(value, str):
            continue
        try:
            return datetime.strptime(value.strip().strip("\x00")[:19], "%Y:%m:%d %H:%M:%S")
        except ValueError:
            continue
    return None


def apply_preset(
    image: Image.Image,
    preset: str | Path,
    *,
    presets_dir: Path = DEFAULT_PRESETS_DIR,
    text: str | None = None,
) -> Image.Image:
    path = resolve_preset_path(preset, presets_dir=presets_dir)
    data = load_preset(path)
    assert_preset_fits_image(image, data.get("ar"))
    resolved_text = resolve_user_text(data, text)
    # `$date` / `$time` stamp when the photo was taken; falls back to now.
    return apply_steps(image, data["steps"], text=resolved_text, now=photo_datetime(image))


def apply_preset_file(
    input_path: str | Path,
    preset: str | Path,
    output_path: str | Path,
    *,
    presets_dir: Path = DEFAULT_PRESETS_DIR,
    text: str | None = None,
) -> Path:
    src = Path(input_path)
    dst = Path(output_path)
    if not src.is_file():
        raise FileNotFoundError(f"Input image not found: {src}")

    with Image.open(src) as image:
        image.load()
        result = apply_preset(image, preset, presets_dir=presets_dir, text=text)

    dst.parent.mkdir(parents=True, exist_ok=True)
    # Preserve alpha if present
    if result.mode == "RGBA" and result.getchannel("A").getextrema() != (255, 255):
        result.save(dst, format="PNG")
    else:
        result.convert("RGB").save(dst, format="PNG")
    return dst


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply a JSON image preset (step pipeline).")
    parser.add_argument("input", type=Path, help="Input image path")
    parser.add_argument(
        "--preset",
        "-p",
        required=True,
        help="Preset name (in backend/presets/) or path to a .json file",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output PNG path (default: <input>_<preset>.png)",
    )
    parser.add_argument(
        "--presets-dir",
        type=Path,
        default=DEFAULT_PRESETS_DIR,
        help="Directory of preset JSON files",
    )
    parser.add_argument(
        "--text",
        default=None,
        help="Text for presets with text_input=yes (otherwise default_text is used)",
    )
    args = parser.parse_args(argv)

    preset_label = Path(args.preset).stem
    output = args.output or args.input.with_name(f"{args.input.stem}_{preset_label}.png")

    try:
        path = apply_preset_file(
            args.input,
            args.preset,
            output,
            presets_dir=args.presets_dir,
            text=args.text,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Wrote preset result: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
