# Presets & helpers

Guide for The Local Studio JSON presets: what exists today, and how to add a new one.

For the agent workflow (POC → name → keywords → ar → text → HD pre-pass → fonts → ship → gallery),
use the project skill `.cursor/skills/create-preset/SKILL.md`. Visual option rounds
write comparison HTML under `previews/_candidates/` via
`.cursor/skills/create-preset/scripts/render_candidates.py` (calls `apply_preset.py`
and `filters.draw_text`).

## Layout

| Path | Role |
|------|------|
| `backend/presets/*.json` | Named recipes (ordered filter steps) |
| `backend/helpers/filters.py` | Filter implementations (Pillow + rembg) |
| `backend/helpers/apply_preset.py` | Step runner + CLI |
| `backend/helpers/extract_subject.py` | Subject cutout CLI (rembg / `u2net`) |
| `backend/helpers/download_model.py` | Warm-cache `u2net` during setup |
| `backend/helpers/upscale_model.py` | Real-ESRGAN weights → local ONNX (`~/.local-studio/models/`) + tiled 4× inference for `ai_upscale`; `python upscale_model.py` warms the cache |
| `backend/database/` | SQLite metadata (`presets.db`, `db_ops.py`) |
| `previews/pre-edit/` + `previews/post-edit/` + `previews/presets.json` | Before/after gallery assets per DB preset + name→path map (sources in `previews/CREDITS.md`) |
| `previews/_candidates/` | Gitignored create-preset comparison HTML (POC / fonts / gallery); not shipped |
| `.cursor/skills/create-preset/scripts/render_candidates.py` | Writes those HTML pages using `apply_preset_file` + `draw_text` |
| `POST /api/apply-preset` | HTTP: DB `preset_name` + image upload + optional `text` → PNG |

## Run a preset

```bash
source backend/.venv/bin/activate
python backend/helpers/apply_preset.py path/to/photo.jpg -p PRESET_NAME -o out.png
```

`PRESET_NAME` is a file under `backend/presets/` (with or without `.json`), or a full path to a JSON file.

Via API (name must exist in `presets.db`):

```bash
curl -s -X POST "http://localhost:8000/api/apply-preset" \
  -F "preset_name=bw_bg_glowing_subject" \
  -F "file=@path/to/photo.jpg" \
  -o out.png
```

For a preset with `text_input: yes`, also send `-F "text=Your caption"`. If `text` is omitted, `default_text` is used. The runner does not branch on filter type: each JSON step names a registered helper and its parameters.

Only one apply-preset job runs at a time; concurrent extras get HTTP **503**.
## Shipped presets

### `bw_bg_glowing_subject`

- **Idea:** Extract subject → grayscale background → glowing **line** border on subject → composite.
- **File:** `backend/presets/bw_bg_glowing_subject.json`
- **AR:** `non-square` (any aspect ratio)
- **Text input:** `no`
- **DB:** seeded via `seed_default_presets()` / setup

### `polaroid_memory`

- **Idea:** Soft warm film grade → date/time stamp on the photo (top-right) → white polaroid mat at **1.4×** (`layout: polaroid`) → flow-script caption in the bottom band (`$text`).
- **File:** `backend/presets/polaroid_memory.json`
- **AR:** `square` (square-only)
- **Text input:** `yes` — default `instant memory`, limit **24**
- **DB:** seeded via `seed_default_presets()` / setup

### `warm_faded_print`

- **Idea:** Softer contrast → muted saturation → slight brightness lift → cream-amber overlay (sun-faded color print).
- **File:** `backend/presets/warm_faded_print.json`
- **AR:** `non-square` (any aspect ratio)
- **Text input:** `no`
- **DB:** seeded via `seed_default_presets()` / setup

### `full_hd`

- **Idea:** Local AI super-resolution (Real-ESRGAN general-x4v3, denoise 0.5) to a **1920 px** long edge.
- **File:** `backend/presets/full_hd.json`
- **AR:** `non-square` (any aspect ratio)
- **Text input:** `no`
- **DB:** seeded via `seed_default_presets()` / setup

### `4k_crisp`

- **Idea:** Local AI super-resolution (denoise 0.3, keeps more texture) to a **3840 px** long edge → light unsharp mask → contrast ×1.04.
- **File:** `backend/presets/4k_crisp.json`
- **AR:** `non-square` (any aspect ratio)
- **Text input:** `no`
- **DB:** seeded via `seed_default_presets()` / setup

### `doodle_corner_xo`

- **Idea:** Extract subject (`require_clear_subject: true`) → white sticker outline (`sticker_outline`, `width_ratio` 0.008 — ~6 px at 720, scales with size) → hand-drawn X/O grid top-right + three wiggly lines bottom-left on the **background** → composite (subject sits over the doodles).
- **File:** `backend/presets/doodle_corner_xo.json`
- **AR:** `non-square` (any aspect ratio)
- **Text input:** `no`
- **DB:** seeded via `seed_default_presets()` / setup

### `doodle_halo_rings`

- **Idea:** Extract subject → white sticker outline → four wobbly concentric rings centred on the subject (`anchor: subject`, `around: subject`) + three sparkles top-left on the background → composite.
- **File:** `backend/presets/doodle_halo_rings.json`
- **AR:** `non-square` (any aspect ratio)
- **Text input:** `no`
- **DB:** seeded via `seed_default_presets()` / setup

### `comic_pop`

- **Idea:** contrast ×1.11 → colour ×1.24 → `posterize` 6 levels → light CMYK `halftone` (25% mix) → `ink_edges` (74%) → faint `paper_texture`. Bold comic-panel colour with soft dots and outlines.
- **File:** `backend/presets/comic_pop.json`
- **AR:** `non-square` (any aspect ratio)
- **Text input:** `no`
- **DB:** seeded via `seed_default_presets()` / setup

### `old_newspaper`

- **Idea:** grayscale → slight lift + contrast → mono black-ink `halftone` (70% mix) on warm newsprint → `paper_texture` grain, stains and fade.
- **File:** `backend/presets/old_newspaper.json`
- **AR:** `non-square` (any aspect ratio)
- **Text input:** `no`
- **DB:** seeded via `seed_default_presets()` / setup

### `vintage_comic`

- **Idea:** brighten → colour ×1.1 → `posterize` 8 → CMYK `halftone` (55% mix, `gcr` 0.4) on cream paper → soft `ink_edges` → aged `paper_texture`.
- **File:** `backend/presets/vintage_comic.json`
- **AR:** `non-square` (any aspect ratio)
- **Text input:** `no`
- **DB:** seeded via `seed_default_presets()` / setup

## Built-in filters

| Filter | What it does | Common params |
|--------|----------------|---------------|
| `extract_subject` | rembg cutout + blurred fill background. With `require_clear_subject: true`, an unreliable mask (tiny, or semi-transparent smear away from the body — e.g. dark backlit subjects) gives an empty subject and the untouched original as background; soft hair/fur next to the body is fine | `on`, `as` (subject), `bg_as` (background), `require_clear_subject` (default `false`) |
| `brightness` | Brightness enhance | `on`, `amount` |
| `color` | Saturation enhance | `on`, `amount` |
| `contrast` | Contrast enhance | `on`, `amount` |
| `overlay` | Blend a solid tint | `on`, `rgb`/`color`, `alpha` |
| `grayscale` | Desaturate | `on` |
| `glow_border` | Soft halo under subject (fills expanded mask) | `on`, `rgb`/`color`, `width`, `blur` |
| `glow_line_border` | Outline **ring** only (subject body unchanged) | `on`, `color`/`rgb`, `width`, `blur` |
| `sticker_outline` | Solid round-cornered outline whose width scales with the image (blur + threshold dilation, flat cost at any width) | `on`, `color`/`rgb`, `width_ratio` (fraction of short side; default 0.008), `softness` (edge AA px) |
| `composite` | Paste overlay on base | `base`, `overlay`, `as` |
| `place_on_canvas` | Put layer on a larger solid canvas | `on`, `scale` (e.g. `1.4`), `fill`/`color`, `layout` (`polaroid` or `center`), `as` |
| `upscale` | Pillow resize so the long side reaches `long_edge` (keeps aspect; never shrinks) | `on`, `long_edge`, `max_scale` (default 4), `resample` (`lanczos`/`bicubic`/`bilinear`) |
| `sharpen` | Unsharp mask | `on`, `radius`, `percent`, `threshold` |
| `denoise` | Median filter (noise / JPEG blocking) | `on`, `size` (odd ≥ 3) |
| `ai_upscale` | Local Real-ESRGAN 4× super-resolution, then Lanczos to target (keeps aspect + alpha; never shrinks) | `on`, `long_edge` (default 1920), `max_scale` (4), `denoise` (0 keep grain – 1 smoothest; 0.5), `max_input_pixels` (1 000 000), `tile` (256) |
| `doodle` | One hand-drawn white (or tinted) doodle; sizes are fractions of the short side so it scales with resolution; seeded wobble is deterministic; draws only its own region (2× supersampled up to 4 MP regions, 1× above) |  `on`, `style` (`xo`/`rings`/`wiggles`/`stars`), `anchor` (`top_right`/`top_left`/`bottom_left`/`bottom_right`/`top`/`bottom`/`left`/`right`/`center`/`subject`), `around` (layer whose alpha bbox centres `anchor: subject`), `x`/`y` (0–1, override anchor), `size`, `stroke`, `count` (1–12), `angle` (wiggles), `color`/`rgb`, `opacity`, `jitter`, `seed` |
| `posterize` | Flatten each RGB channel to N levels (comic colour bands); optional median smooth first | `on`, `levels` (2–32), `smooth` (0 or odd ≥ 3) |
| `ink_edges` | Comic ink outlines via difference of Gaussians on luminance; scales with resolution; RGBA is flattened on white first so hidden pixels don't create edges | `on`, `detail` (blur, fraction of short side), `threshold` (lower = more lines), `thickness` (fraction of short side), `color`/`rgb`, `opacity` |
| `halftone` | Printed dot screen: `mono` (one ink at `angle`) or `cmyk` (process inks at 15/75/0/45° with grey-component replacement); dot area ≈ ink coverage; processed at ≤ 2400 px long edge then resized back; pitch auto-enlarges if a screen would need > 160k dots; transparent pixels print as paper | `on`, `mode`, `cell` (dot pitch, 0.002–0.1 of short side), `angle`, `paper`, `ink`, `mix` (blend back over original), `gcr` (0–1, share of grey on black plate) |
| `paper_texture` | Age onto paper: multiply tint, seeded fine grain (scales with resolution), low-frequency stains (grid follows aspect ratio), fade toward paper; tone steps run as point tables, grain is applied tile by tile | `on`, `color`/`rgb`, `tint`, `grain`, `stains`, `fade` (0–1 each), `seed` |
| `draw_text` | Paint a string onto a layer | `on`, `text` (`$text` / `$datetime` / `$date` / `$time`), `font_size`, `color`/`rgb`, `align` (`center`/`top`/`bottom`/`top_right`/…), `font_style` (`sans`/`flow`), `font_path` (optional TTF/OTF/TTC; overrides `font_style`), `margin`, `x`, `y`, `stroke_width` |

Layers are named images in memory. Typical keys: `image`, `subject`, `background`.

## Preset JSON shape

```json
{
  "name": "example_name",
  "label": "Human label",
  "description": "What this look does.",
  "ar": "non-square",
  "text_input": "no",
  "default_text": "",
  "text_character_limit": 0,
  "steps": [
    {
      "filter": "extract_subject",
      "on": "image",
      "as": "subject",
      "bg_as": "background"
    },
    { "filter": "grayscale", "on": "background" },
    {
      "filter": "glow_line_border",
      "on": "subject",
      "color": [0, 255, 200],
      "width": 5,
      "blur": 2
    },
    {
      "filter": "composite",
      "base": "background",
      "overlay": "subject",
      "as": "image"
    }
  ]
}
```

Each step’s `"filter"` is the helper function name. Remaining keys are that function’s parameters (plus layer bindings `on` / `as` / `bg_as` / `base` / `overlay`). The runner looks the name up in `FILTERS` and calls the function — there is no per-filter if/else in the API or the step loop.

When `"text_input": "yes"`, set `default_text` and `text_character_limit` (1–200). Any string param equal to `$text` (or containing `$text`) is replaced with the user’s text (or the default if they omit it). Example step:

```json
{
  "filter": "draw_text",
  "on": "image",
  "text": "$text",
  "font_size": 48,
  "color": [255, 255, 255],
  "align": "bottom",
  "stroke_width": 2
}
```

Rules of thumb:

1. Always end with a `composite` (or other step) that writes `as: "image"`.
2. Apply background edits with `"on": "background"`; subject edits with `"on": "subject"`.
3. Prefer `glow_line_border` for a glow ring and `sticker_outline` for a solid outline that should scale with resolution.
4. Set `"ar": "square"` when the recipe only works on square images; `"ar": "non-square"` (default) works on any aspect ratio. A square-only preset applied to a non-square image raises `PresetAspectRatioError`.
5. Set `"text_input": "yes"` only when a step uses `$text`. Then `text_character_limit` must be 1–200. `"no"` (default) ignores submitted text.
6. Doodles: apply `doodle` steps `"on": "background"` before the final `composite` so the subject covers them; use `"anchor": "subject", "around": "subject"` to centre rings behind the cutout.
7. HD pre-pass: put `{ "filter": "ai_upscale", "on": "image", "long_edge": 1920 }` as step 0 so later steps work at HD size — then scale pixel-sized params (`font_size`, `margin`, `stroke_width`, glow `width`/`blur`) by about the upscale factor.

## Database metadata

Table `presets` in `backend/database/presets.db`:

| Column | Meaning |
|--------|---------|
| `preset_id` | Auto primary key (`list_presets` / search return highest id first) |
| `preset_name` | Unique name (usually matches JSON `name` / filename stem) |
| `preset_path` | Repo-relative path, e.g. `backend/presets/foo.json` |
| `keywords` | JSON list of search tags (also searched with `preset_name` by `GET /api/presets/search?q=…`) |
| `ar` | `square` (square-only) or `non-square` (any aspect ratio; default) |
| `text_input` | `yes` if the preset needs a caption/string; `no` otherwise (default) |
| `default_text` | Prefill for the UI / fallback when apply omits `text` (empty when `text_input` is `no`) |
| `text_character_limit` | Max length for user text (1–200 when `text_input` is `yes`; `0` otherwise) |
| `created_date` | Auto timestamp |

Table `popular` (one row per preset; ordered by `used_count` descending when listed):

| Column | Meaning |
|--------|---------|
| `preset_id` | Primary key and foreign key to `presets.preset_id` (`ON DELETE CASCADE`) |
| `used_count` | Download count (starts at `0`; incremented by `POST /api/presets/use`) |

`add_preset` inserts a `popular` row with `used_count = 0`. Existing databases gain the table via `migrate_schema()`. List with `list_presets()` (newest `preset_id` first) and `list_popular()` / `GET /api/presets/popular` (`preset_id`, `preset_name`, `used_count`, highest count first). Download increments `used_count` immediately. The studio **Popular** control turns that sort on; the refresh button beside search reloads the gallery in that order. Unclicking **Popular** restores newest-first order. New gallery entries go at the top of `previews/presets.json`.

```bash
source backend/.venv/bin/activate
python -c '
import sys
sys.path.insert(0, "backend")
from database.db_ops import add_preset, list_presets, list_popular, search_presets_by_keyword
print(list_presets())
print(search_presets_by_keyword("glow"))
print(list_popular())
'
```

## How to create a new preset (human checklist)

1. Describe the look in plain language (optional reference images).
2. Ask the agent to use **create-preset** (or follow that skill).
3. Review the comparison page at `previews/_candidates/poc/index.html` (agent writes it with `render_candidates.py`, which runs `apply_preset.py`) and pick one recipe.
4. Pick a final `snake_case` preset name.
5. Finalize the keywords list.
6. Finalize `ar`: `square` (square-only) or `non-square` (any aspect ratio).
7. Finalize text input: `text_input` `yes`/`no`; if yes, also `default_text` and `text_character_limit` (1–200).
8. Answer "Would you like to turn the image to HD first before applying the new preset?" — if yes, the recipe gains an `ai_upscale` step 0 (local Real-ESRGAN; `long_edge` 1920 or 3840, `denoise`), pixel-sized params are scaled for HD, and you confirm the re-render at `previews/_candidates/poc-hd/index.html`.
9. If the look uses `draw_text`, pick a font from `previews/_candidates/fonts/index.html`.
10. Agent then ships code:
   - adds helpers/filters only if needed (register in `FILTERS`; no API if/else)
   - writes `backend/presets/<name>.json` (include `"ar"` and `text_input` / `default_text` / `text_character_limit`)
   - inserts a row with `add_preset(..., ar=..., text_input=..., default_text=..., text_character_limit=...)` (also creates a `popular` row at `used_count` 0)
   - updates this file + CONTEXT/ARCHITECTURE (+ tests if needed)
11. Gallery previews (gated — see create-preset skill step 8):
   - search open-licensed candidates that suit the preset
   - agent writes `previews/_candidates/gallery/index.html` (`render_candidates.py gallery`: square crop + **720×720** + `apply_preset.py`; `--crop ID=left|right|top|bottom` when center clips the subject; pass `--text` when `text_input=yes`)
   - pick the best preview from that page
   - write `previews/pre-edit/<name>.*`, `previews/post-edit/<name>.png`, prepend the new object to `previews/presets.json` (newest first), and `previews/CREDITS.md`

## Adding a new filter (when needed)

1. Implement a function in `backend/helpers/filters.py`.
2. Register it in `backend/helpers/apply_preset.py` → `FILTERS` (wrap with `_run_simple` if it takes one layer image plus kwargs).
3. If it takes a tint, accept `color` and/or `rgb` inside the filter (not in the runner).
4. Add a focused unit test under `test-suite/` when behavior is non-trivial.
5. Document it in the filters table above.
