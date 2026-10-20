#!/usr/bin/env python3
"""
Extract the main subject from an image (background removed).

Uses rembg (U²-Net) locally — no cloud API.

Usage:
  python extract_subject.py INPUT.png [-o OUTPUT.png]

Requires helper deps:
  pip install -r backend/helpers/requirements.txt
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image

# u2net (~176MB) — much smaller than rembg's default bria-rmbg (~1GB)
DEFAULT_MODEL = "u2net"
_SESSION = None


def _rembg():
    """Lazy import so unit tests can load helpers without rembg installed."""
    try:
        from rembg import new_session, remove
    except ImportError as exc:
        raise RuntimeError(
            "rembg is required for subject extraction. "
            "Install with: pip install -r backend/helpers/requirements.txt"
        ) from exc
    return new_session, remove


def _session(model_name: str = DEFAULT_MODEL):
    global _SESSION
    if _SESSION is None:
        new_session, _ = _rembg()
        _SESSION = new_session(model_name)
    return _SESSION


def extract_subject(image: Image.Image, *, model_name: str = DEFAULT_MODEL) -> Image.Image:
    """
    Return an RGBA image with the main subject kept and background transparent.
    """
    _, remove = _rembg()
    rgb = image.convert("RGB") if image.mode not in ("RGB", "RGBA") else image
    cutout = remove(rgb, session=_session(model_name))
    if not isinstance(cutout, Image.Image):
        raise RuntimeError("rembg did not return a Pillow image.")
    # rembg darkens soft edge pixels (colour ≈ premultiplied by alpha), which
    # shows as a dark rim once composited as straight alpha. Keep its mask, take
    # the colour from the source.
    subject = rgb.convert("RGB")
    subject.putalpha(cutout.convert("RGBA").getchannel("A"))
    return subject


def extract_subject_file(input_path: str | Path, output_path: str | Path) -> Path:
    """Load an image file, extract the subject, save PNG (with alpha), return output path."""
    src = Path(input_path)
    dst = Path(output_path)
    if not src.is_file():
        raise FileNotFoundError(f"Input image not found: {src}")

    with Image.open(src) as image:
        image.load()
        subject = extract_subject(image)

    dst.parent.mkdir(parents=True, exist_ok=True)
    subject.save(dst, format="PNG")
    return dst


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Extract the main subject from an image (transparent background)."
    )
    parser.add_argument("input", type=Path, help="Path to the input image")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output PNG path (default: <input>_subject.png)",
    )
    args = parser.parse_args(argv)

    output = args.output
    if output is None:
        output = args.input.with_name(f"{args.input.stem}_subject.png")

    try:
        path = extract_subject_file(args.input, output)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Wrote subject cutout: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
