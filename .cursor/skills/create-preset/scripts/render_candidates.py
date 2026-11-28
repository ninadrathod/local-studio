#!/usr/bin/env python3
"""
Write a local comparison HTML page for create-preset gated choices.

Uses existing helpers — do not reimplement the filter pipeline:
  backend/helpers/apply_preset.py  (apply_preset_file)
  backend/helpers/filters.py       (draw_text)

Usage (from the repo root, in the dev container; open the written index.html on the host —
the container has no browser, so --open only prints a notice there):

  docker compose run --rm dev python .cursor/skills/create-preset/scripts/render_candidates.py poc \\
    --input photo.jpg --outdir previews/_candidates/poc \\
    A=previews/_candidates/poc/draft_a.json B=previews/_candidates/poc/draft_b.json

  docker compose run --rm dev python .cursor/skills/create-preset/scripts/render_candidates.py fonts \\
    --text "instant memory" --outdir previews/_candidates/fonts \\
    --image previews/_candidates/poc/A.png A=sans B=flow

  docker compose run --rm dev python .cursor/skills/create-preset/scripts/render_candidates.py gallery \\
    --preset polaroid_memory --outdir previews/_candidates/gallery \\
    --crop A=left --crop B=top \\
    A=src/street.jpg B=src/portrait.jpg

  docker compose run --rm dev python .cursor/skills/create-preset/scripts/render_candidates.py html \\
    --title "Glow color" --outdir previews/_candidates/variants \\
    --original original.jpg A=red.png B=cyan.png
"""

from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

_CARD_ID = re.compile(r"^[A-Za-z0-9_-]+$")

REPO_ROOT = Path(__file__).resolve().parents[4]
HELPERS_DIR = REPO_ROOT / "backend" / "helpers"

if str(HELPERS_DIR) not in sys.path:
    sys.path.insert(0, str(HELPERS_DIR))

from apply_preset import apply_preset_file  # noqa: E402
import filters as F  # noqa: E402

GALLERY_SIZE = 720
CROP_ALIGNS = frozenset({"center", "left", "right", "top", "bottom"})


def _parse_id_value(spec: str) -> tuple[str, str]:
    if "=" not in spec:
        raise ValueError(f"Expected ID=value, got: {spec}")
    card_id, value = spec.split("=", 1)
    card_id = card_id.strip()
    value = value.strip()
    if not card_id or not value:
        raise ValueError(f"Expected ID=value, got: {spec}")
    if not _CARD_ID.fullmatch(card_id):
        raise ValueError(f"ID must be letters, numbers, _ or -: {card_id}")
    return card_id, value


def _parse_notes(items: list[str] | None) -> dict[str, str]:
    notes: dict[str, str] = {}
    for spec in items or []:
        card_id, value = _parse_id_value(spec)
        notes[card_id] = value
    return notes


def _copy_into(src: Path, dest_dir: Path, name: str) -> str:
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / name
    src = src.resolve()
    if dest.resolve() != src:
        shutil.copy2(src, dest)
    return dest.name


def _steps_summary(preset: dict[str, Any]) -> str:
    steps = preset.get("steps") or []
    parts: list[str] = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        name = str(step.get("filter") or "?")
        extras = []
        for key, val in step.items():
            if key in {"filter", "on", "as", "bg_as", "base", "overlay"}:
                continue
            extras.append(f"{key}={val}")
        parts.append(name + (f" ({', '.join(extras)})" if extras else ""))
    return " → ".join(parts) if parts else ""


def normalize_crop_align(value: str | None) -> str:
    text = (value or "center").strip().lower()
    if text not in CROP_ALIGNS:
        allowed = ", ".join(sorted(CROP_ALIGNS))
        raise ValueError(f"crop align must be one of: {allowed}")
    return text


def crop_square(image: Image.Image, align: str = "center") -> Image.Image:
    """Crop to a square, keeping the named edge when the frame is wider or taller."""
    mode = normalize_crop_align(align)
    width, height = image.size
    side = min(width, height)
    left = 0
    top = 0
    if width > height:
        if mode == "left":
            left = 0
        elif mode == "right":
            left = width - side
        else:
            left = (width - side) // 2
    elif height > width:
        if mode == "top":
            top = 0
        elif mode == "bottom":
            top = height - side
        else:
            top = (height - side) // 2
    return image.crop((left, top, left + side, top + side))


def downscale_square(
    image: Image.Image,
    size: int = GALLERY_SIZE,
    align: str = "center",
) -> Image.Image:
    # Phone photos often store rotation as an EXIF tag; apply it so the crop isn't sideways.
    image = ImageOps.exif_transpose(image) or image
    square = crop_square(image, align)
    if square.size[0] == size:
        return square
    return square.resize((size, size), Image.Resampling.LANCZOS)


def _open_html(path: Path) -> None:
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    try:
        subprocess.run([opener, str(path)], check=False)
    except OSError as exc:
        print(f"Could not open {path}: {exc}", file=sys.stderr)


def write_html(
    outdir: Path,
    *,
    title: str,
    cards: list[dict[str, str]],
    original: str | None = None,
    intro: str = "",
) -> Path:
    outdir.mkdir(parents=True, exist_ok=True)
    cards_html: list[str] = []
    for card in cards:
        card_id = html.escape(card["id"])
        heading = html.escape(card.get("title") or card["id"])
        notes = html.escape(card.get("notes") or "")
        image = html.escape(card["image"])
        before = html.escape(card["before"]) if card.get("before") else ""
        if before:
            media = f"""
        <div class="pair">
          <figure>
            <img src="{before}" alt="{card_id} before">
            <figcaption>Before</figcaption>
          </figure>
          <figure>
            <img src="{image}" alt="{card_id} after">
            <figcaption>After</figcaption>
          </figure>
        </div>"""
        else:
            media = f"""
        <figure class="solo">
          <img src="{image}" alt="{card_id}">
        </figure>"""
        notes_html = f'<p class="notes">{notes}</p>' if notes else ""
        cards_html.append(
            f"""
      <article class="card">
        <header>
          <span class="badge">{card_id}</span>
          <h2>{heading}</h2>
        </header>
        {media}
        {notes_html}
      </article>"""
        )

    original_html = ""
    if original:
        original_html = f"""
    <section class="original">
      <h2>Original</h2>
      <img src="{html.escape(original)}" alt="Original input">
    </section>"""

    intro_html = f"<p class='intro'>{html.escape(intro)}</p>" if intro else ""
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #1c1917;
      --mute: #57534e;
      --paper: #f5f0e8;
      --card: #fffdf8;
      --line: #d6d3d1;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: ui-sans-serif, system-ui, -apple-system, sans-serif;
      background: var(--paper);
      color: var(--ink);
      line-height: 1.4;
    }}
    header.page {{
      padding: 1.25rem 1.25rem 0.5rem;
      max-width: 1200px;
      margin: 0 auto;
    }}
    h1 {{ font-size: 1.35rem; margin: 0 0 0.35rem; }}
    .intro, .notes, figcaption {{ color: var(--mute); font-size: 0.9rem; }}
    .original {{
      max-width: 1200px;
      margin: 0 auto;
      padding: 0 1.25rem 1rem;
    }}
    .original img {{
      width: min(280px, 100%);
      height: auto;
      border: 1px solid var(--line);
      background: #fff;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(min(100%, 320px), 1fr));
      gap: 1rem;
      padding: 0 1.25rem 2rem;
      max-width: 1200px;
      margin: 0 auto;
    }}
    .card {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 0.85rem;
      min-width: 0;
    }}
    .card header {{
      display: flex;
      align-items: center;
      gap: 0.6rem;
      margin-bottom: 0.7rem;
    }}
    .card h2 {{ font-size: 1rem; margin: 0; }}
    .badge {{
      flex: none;
      width: 1.8rem;
      height: 1.8rem;
      border-radius: 999px;
      display: grid;
      place-items: center;
      background: var(--ink);
      color: #fff;
      font-weight: 700;
      font-size: 0.85rem;
    }}
    img {{
      display: block;
      width: 100%;
      height: auto;
      border-radius: 8px;
      background: #fff;
    }}
    .pair {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 0.5rem;
    }}
    @media (max-width: 420px) {{
      .pair {{ grid-template-columns: 1fr; }}
    }}
    figure {{ margin: 0; }}
    figcaption {{ margin-top: 0.3rem; }}
    .notes {{ margin: 0.65rem 0 0; word-break: break-word; }}
  </style>
</head>
<body>
  <header class="page">
    <h1>{html.escape(title)}</h1>
    {intro_html}
  </header>
  {original_html}
  <section class="grid">
    {"".join(cards_html)}
  </section>
</body>
</html>
"""
    dest = outdir / "index.html"
    dest.write_text(page, encoding="utf-8")
    return dest


def cmd_html(args: argparse.Namespace) -> Path:
    outdir = Path(args.outdir)
    notes = _parse_notes(args.note)
    cards: list[dict[str, str]] = []
    for spec in args.cards:
        card_id, value = _parse_id_value(spec)
        src = Path(value)
        if not src.is_file():
            raise FileNotFoundError(f"Image not found for {card_id}: {src}")
        suffix = src.suffix.lower() or ".png"
        image_name = _copy_into(src, outdir, f"{card_id}{suffix}")
        before_spec = (args.before or {}).get(card_id) if isinstance(args.before, dict) else None
        card = {
            "id": card_id,
            "title": card_id,
            "notes": notes.get(card_id, ""),
            "image": image_name,
        }
        if before_spec:
            before_src = Path(before_spec)
            if not before_src.is_file():
                raise FileNotFoundError(f"Before image not found for {card_id}: {before_src}")
            card["before"] = _copy_into(
                before_src, outdir, f"{card_id}_before{before_src.suffix.lower() or '.jpg'}"
            )
        cards.append(card)

    original = None
    if args.original:
        src = Path(args.original)
        if not src.is_file():
            raise FileNotFoundError(f"Original image not found: {src}")
        original = _copy_into(src, outdir, f"original{src.suffix.lower() or '.jpg'}")

    return write_html(
        outdir,
        title=args.title or "Candidates",
        cards=cards,
        original=original,
        intro=args.intro or "Pick a letter, then reply with that id.",
    )


def cmd_poc(args: argparse.Namespace) -> Path:
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    input_path = Path(args.input)
    if not input_path.is_file():
        raise FileNotFoundError(f"Input image not found: {input_path}")

    original = _copy_into(input_path, outdir, f"original{input_path.suffix.lower() or '.jpg'}")
    notes = _parse_notes(args.note)
    cards: list[dict[str, str]] = []
    for spec in args.cards:
        card_id, value = _parse_id_value(spec)
        preset_path = Path(value)
        if not preset_path.is_file():
            raise FileNotFoundError(f"Preset not found for {card_id}: {preset_path}")
        preset_copy = outdir / f"{card_id}.json"
        if preset_path.resolve() != preset_copy.resolve():
            shutil.copy2(preset_path, preset_copy)
        out_img = outdir / f"{card_id}.png"
        apply_preset_file(input_path, preset_copy, out_img, text=args.text)
        data = json.loads(preset_copy.read_text(encoding="utf-8"))
        title = str(data.get("label") or data.get("name") or card_id)
        summary = notes.get(card_id) or _steps_summary(data)
        cards.append(
            {
                "id": card_id,
                "title": title,
                "notes": summary,
                "image": out_img.name,
            }
        )

    return write_html(
        outdir,
        title=args.title or "POC drafts",
        cards=cards,
        original=original,
        intro=args.intro or "Each card is a draft preset applied with apply_preset.py. Pick one letter.",
    )


def _render_font_sample(
    *,
    text: str,
    font_style: str | None,
    font_path: str | None,
    backdrop: Image.Image,
    font_size: int,
    color: tuple[int, ...],
    align: str,
) -> Image.Image:
    kwargs: dict[str, object] = {
        "text": text,
        "font_size": font_size,
        "color": color,
        "align": align,
    }
    if font_path:
        kwargs["font_path"] = font_path
    else:
        kwargs["font_style"] = font_style or "sans"
    return F.draw_text(backdrop, **kwargs)


def cmd_fonts(args: argparse.Namespace) -> Path:
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    notes = _parse_notes(args.note)
    if args.image:
        with Image.open(args.image) as image:
            image.load()
            backdrop = image.convert("RGBA")
    else:
        backdrop = Image.new("RGBA", (720, 360), (245, 240, 232, 255))

    cards: list[dict[str, str]] = []
    for spec in args.cards:
        card_id, value = _parse_id_value(spec)
        path = Path(value)
        looks_like_path = ("/" in value) or path.suffix.lower() in {".ttf", ".otf", ".ttc"}
        if looks_like_path and not path.is_file():
            raise FileNotFoundError(f"Font file not found for {card_id}: {path}")
        font_path = str(path) if path.is_file() else None
        font_style = None if font_path else value
        sample = _render_font_sample(
            text=args.text,
            font_style=font_style,
            font_path=font_path,
            backdrop=backdrop.copy(),
            font_size=args.font_size,
            color=tuple(args.color),
            align=args.align,
        )
        out_img = outdir / f"{card_id}.png"
        sample.save(out_img, format="PNG")
        label = path.name if font_path else f"font_style={font_style}"
        cards.append(
            {
                "id": card_id,
                "title": label,
                "notes": notes.get(card_id, ""),
                "image": out_img.name,
            }
        )

    return write_html(
        outdir,
        title=args.title or "Font options",
        cards=cards,
        intro=args.intro
        or "Samples use filters.draw_text (same align/size path the preset will ship). Pick the letter that should ship.",
    )


def cmd_gallery(args: argparse.Namespace) -> Path:
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    notes = _parse_notes(args.note)
    crops = dict(_parse_id_value(spec) for spec in (args.crop or []))
    default_align = normalize_crop_align(args.crop_align)
    size = int(args.size)
    cards: list[dict[str, str]] = []
    for spec in args.cards:
        card_id, value = _parse_id_value(spec)
        src = Path(value)
        if not src.is_file():
            raise FileNotFoundError(f"Source photo not found for {card_id}: {src}")
        align = normalize_crop_align(crops.get(card_id, default_align))
        with Image.open(src) as image:
            image.load()
            prepared = downscale_square(image, size, align)
        before_path = outdir / f"{card_id}_before.jpg"
        prepared.convert("RGB").save(before_path, format="JPEG", quality=92)
        after_path = outdir / f"{card_id}.png"
        apply_preset_file(before_path, args.preset, after_path, text=args.text)
        crop_note = f"crop={align}"
        extra = notes.get(card_id, src.name)
        caption = extra if extra == crop_note or extra.endswith(crop_note) else f"{extra} · {crop_note}"
        cards.append(
            {
                "id": card_id,
                "title": card_id,
                "notes": caption,
                "image": after_path.name,
                "before": before_path.name,
            }
        )

    return write_html(
        outdir,
        title=args.title or "Gallery candidates",
        cards=cards,
        intro=args.intro
        or (
            f"Each photo is cropped to {size}×{size} "
            f"(default {default_align}; override with --crop ID=left|right|top|bottom), "
            "then apply_preset.py ran the shipped preset. Pick one letter."
        ),
    )


def _add_shared_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--outdir",
        type=Path,
        required=True,
        help="Directory under previews/_candidates/ for this round",
    )
    parser.add_argument("--title", default="", help="HTML page title")
    parser.add_argument("--intro", default="", help="Short blurb at the top of the page")
    parser.add_argument(
        "--note",
        action="append",
        default=[],
        help="Optional caption, repeatable: ID=text",
    )
    parser.add_argument(
        "--open",
        action="store_true",
        help="Open index.html after writing (macOS open / xdg-open)",
    )
    parser.add_argument(
        "cards",
        nargs="+",
        help="One or more ID=value specs (preset path, image path, or font_style)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Write create-preset comparison HTML using apply_preset and draw_text."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    poc = sub.add_parser("poc", help="Apply draft preset JSON files and write a comparison page")
    _add_shared_args(poc)
    poc.add_argument("--input", type=Path, required=True, help="Sample photo to apply drafts to")
    poc.add_argument("--text", default=None, help="Caption for text_input drafts")
    poc.set_defaults(func=cmd_poc)

    fonts = sub.add_parser("fonts", help="Render font_style / TTF samples with draw_text")
    _add_shared_args(fonts)
    fonts.add_argument("--text", required=True, help="Sample string to paint")
    fonts.add_argument("--image", type=Path, default=None, help="Optional backdrop (POC output)")
    fonts.add_argument("--font-size", type=int, default=48)
    fonts.add_argument(
        "--align",
        default="bottom",
        help="draw_text align (default: bottom)",
    )
    fonts.add_argument(
        "--color",
        nargs=3,
        type=int,
        default=[40, 32, 28],
        metavar=("R", "G", "B"),
    )
    fonts.set_defaults(func=cmd_fonts)

    gallery = sub.add_parser(
        "gallery",
        help="Square-crop sources, apply a shipped preset, write before/after HTML",
    )
    _add_shared_args(gallery)
    gallery.add_argument(
        "--preset",
        required=True,
        help="Shipped preset name or JSON path (passed to apply_preset.py)",
    )
    gallery.add_argument("--text", default=None, help="Caption when text_input=yes")
    gallery.add_argument("--size", type=int, default=GALLERY_SIZE)
    gallery.add_argument(
        "--crop-align",
        default="center",
        help="Default square crop: center, left, right, top, or bottom",
    )
    gallery.add_argument(
        "--crop",
        action="append",
        default=[],
        help="Per-photo crop override, repeatable: ID=left|right|top|bottom|center",
    )
    gallery.set_defaults(func=cmd_gallery)

    page = sub.add_parser("html", help="Write HTML from existing images (no apply)")
    _add_shared_args(page)
    page.add_argument("--original", type=Path, default=None)
    page.add_argument(
        "--before",
        action="append",
        default=[],
        help="Optional before image, repeatable: ID=path",
    )
    page.set_defaults(func=_cmd_html_with_before)
    return parser


def _cmd_html_with_before(args: argparse.Namespace) -> Path:
    args.before = dict(_parse_id_value(spec) for spec in (args.before or []))
    return cmd_html(args)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        html_path = args.func(args)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Wrote {html_path}")
    if args.open:
        _open_html(html_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
