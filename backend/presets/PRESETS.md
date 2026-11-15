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
| `backend/fonts/` | Bundled open-licensed display fonts (OFL / Apache, licence next to each) used by `draw_text` `font_style` |
| `backend/helpers/upscale_model.py` | Real-ESRGAN weights → local ONNX (`~/.local-studio/models/`) + tiled 4× inference for `ai_upscale`; `python upscale_model.py` warms the cache |
| `backend/database/` | SQLite metadata (local `presets.local.db`, `db_ops.py`, `prepare_db.py`) |
| `previews/pre-edit/` + `previews/post-edit/` + `previews/presets.json` | Before/after gallery assets per DB preset + name→path map (sources in `previews/CREDITS.md`) |
| `previews/_candidates/` | Gitignored create-preset comparison HTML (POC / fonts / gallery); not shipped |
| `.cursor/skills/create-preset/scripts/render_candidates.py` | Writes those HTML pages using `apply_preset_file` + `draw_text` |
| `POST /api/apply-preset` | HTTP: DB `preset_name` + image upload + optional `text` → JPEG (JPEG / HEIC upload) or PNG |

## Run a preset

```bash
source backend/.venv/bin/activate
python backend/helpers/apply_preset.py path/to/photo.jpg -p PRESET_NAME -o out.png
```

`PRESET_NAME` is a file under `backend/presets/` (with or without `.json`), or a full path to a JSON file. Input may be any Pillow-readable image, including HEIC/HEIF. An `-o` ending in `.jpg`/`.jpeg` writes JPEG (a transparent result is written as `.png` beside it instead); anything else writes PNG.

Via API (name must exist in the preset DB):

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

- **Idea:** Extract subject (`single_subject: true`, so a wall frame or sign doesn't glow) → grayscale background → glowing **line** border on subject (`width_ratio` 0.007 / `blur_ratio` 0.0028 — 5 px / 2 px at 720, scales to DSLR size) → composite.
- **File:** `backend/presets/bw_bg_glowing_subject.json`
- **AR:** `non-square` (any aspect ratio)
- **Text input:** `no`
- **DB:** seeded via `seed_default_presets()` / setup

### `polaroid_memory`

- **Idea:** Soft warm film grade → date/time stamp on the photo (top-right) → white polaroid mat at **1.4×** (`layout: polaroid`) → flow-script caption in the bottom band (`$text`). Stamp and caption sizes are `*_ratio` params (stamp relative to the photo, caption to the 1.4× canvas), so text keeps its proportions at any resolution.
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

- **Idea:** Extract subject (`require_clear_subject: true`, `single_subject: true`) → white sticker outline (`sticker_outline`, `width_ratio` 0.008 — ~6 px at 720, scales with size) → hand-drawn X/O grid top-right + three wiggly lines bottom-left on the **background** → composite (subject sits over the doodles). Doodles use `color: "auto"` (dark ink on pale walls, white on dark) and `avoid_subject: true` (a corner the subject covers flips to its mirror, e.g. wiggles → bottom-right); the X/O grid also sets `avoid_busy: true`, so it skips a cluttered corner such as a framed picture.
- **File:** `backend/presets/doodle_corner_xo.json`
- **AR:** `non-square` (any aspect ratio)
- **Text input:** `no`
- **DB:** seeded via `seed_default_presets()` / setup

### `doodle_halo_rings`

- **Idea:** Extract subject (`single_subject: true`) → white sticker outline → four wobbly concentric rings centred on the subject (`anchor: subject`, `around: subject`) + three sparkles top-left (`avoid_subject: true`) on the background → composite. Doodles use `color: "auto"`.
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

### Professional colour grades

Ten grades for professional photographs (model shoots, street, travel, weddings). Each starts with the HD pass `{ "filter": "ai_upscale", "long_edge": 1920, "denoise": 0.3 }` (a no-op on files already ≥ 1920 px, e.g. DSLR), then grades with `color_grade`. All are `ar: non-square`, `text_input: no`, seeded via `seed_default_presets()` / setup, and run in ~3–4 s at 61 MP (~1.6 GiB peak).

#### `cinematic_teal_orange` — Cinematic teal & orange

- **Idea:** HD pass, then a film-poster grade: teal shadows, warm orange highlights, S-curve contrast with a soft highlight shoulder, and a gentle vignette.
- **Steps:** HD → `color_grade` (temperature 0.1, contrast 0.35, black_lift 0.03, white_rolloff 0.4, split 0.55, saturation 0.95, vibrance 0.2, shadows [20, 110, 130] / highlights [255, 170, 90]) → `vignette` 0.25
- **File:** `backend/presets/cinematic_teal_orange.json`

#### `warm_portrait_film` — Warm portrait film

- **Idea:** HD pass, then a flattering warm film grade: soft contrast, lifted blacks, creamy highlights, gentle vibrance for skin, and fine grain.
- **Steps:** HD → `color_grade` (temperature 0.45, tint 0.06, exposure 0.12, contrast -0.1, black_lift 0.07, white_rolloff 0.6, split 0.45, saturation 0.9, vibrance 0.35, shadows [70, 105, 125] / highlights [255, 200, 150]) → grain 0.05 (`paper_texture`, tint/stains/fade 0)
- **File:** `backend/presets/warm_portrait_film.json`

#### `nordic_cool_matte` — Nordic cool matte

- **Idea:** HD pass, then a cool, muted Scandinavian grade: blue white balance, faded matte blacks, icy highlights, and restrained colour.
- **Steps:** HD → `color_grade` (temperature -0.45, exposure 0.05, contrast -0.1, black_lift 0.1, white_rolloff 0.5, split 0.4, saturation 0.7, shadows [60, 100, 140] / highlights [220, 235, 245])
- **File:** `backend/presets/nordic_cool_matte.json`

#### `golden_hour_glow` — Golden hour glow

- **Idea:** HD pass, then a sunset grade: strong amber warmth, glowing golden highlights, warm shadows, extra vibrance, and a warm-brown vignette.
- **Steps:** HD → `color_grade` (temperature 0.5, tint 0.08, exposure 0.1, contrast 0.15, white_rolloff 0.5, split 0.45, balance 0.2, vibrance 0.35, shadows [120, 70, 60] / highlights [255, 190, 90]) → `vignette` 0.2 toward [40, 20, 0]
- **File:** `backend/presets/golden_hour_glow.json`

#### `emerald_moody` — Emerald moody

- **Idea:** HD pass, then a dark, cinematic green grade: deep emerald shadows, warm muted highlights, lowered exposure, punchy contrast, and a vignette.
- **Steps:** HD → `color_grade` (temperature -0.05, tint -0.3, exposure -0.15, contrast 0.3, black_lift 0.04, split 0.65, balance -0.2, saturation 0.85, vibrance 0.1, shadows [0, 90, 60] / highlights [235, 215, 160]) → `vignette` 0.35
- **File:** `backend/presets/emerald_moody.json`

#### `fine_art_mono` — Fine-art mono

- **Idea:** HD pass, then contrasty black and white with a subtle split tone (cool shadows, warm highlights), fine grain, and a vignette.
- **Steps:** HD → `grayscale` → `color_grade` (contrast 0.45, black_lift 0.02, white_rolloff 0.3, split 0.25, shadows [60, 70, 95] / highlights [235, 225, 205]) → grain 0.06 (`paper_texture`, tint/stains/fade 0) → `vignette` 0.3
- **File:** `backend/presets/fine_art_mono.json`

#### `bright_airy` — Bright & airy

- **Idea:** HD pass, then a clean high-key grade: lifted exposure, soft contrast, smooth highlight roll-off, and gentle vibrance.
- **Steps:** HD → `color_grade` (temperature -0.05, exposure 0.4, contrast -0.25, black_lift 0.05, white_rolloff 0.7, split 0.1, saturation 0.9, vibrance 0.3)
- **File:** `backend/presets/bright_airy.json`

#### `vintage_slide_punch` — Vintage slide punch

- **Idea:** HD pass, then a retro slide-film grade: saturated reds and blues, deep contrast, warm highlights, cool shadows, and a light vignette.
- **Steps:** HD → `color_grade` (temperature 0.15, contrast 0.4, white_rolloff 0.3, split 0.3, saturation 1.2, vibrance 0.2, shadows [40, 50, 90] / highlights [255, 220, 170]) → `vignette` 0.15
- **File:** `backend/presets/vintage_slide_punch.json`

#### `blush_rose_pastel` — Blush rose pastel

- **Idea:** HD pass, then a soft romantic grade: rose-magenta cast, pink highlights, lifted blacks, and low contrast.
- **Steps:** HD → `color_grade` (temperature 0.1, tint 0.5, exposure 0.15, contrast -0.3, black_lift 0.08, white_rolloff 0.6, split 0.6, saturation 0.8, vibrance 0.15, shadows [150, 100, 140] / highlights [255, 200, 215])
- **File:** `backend/presets/blush_rose_pastel.json`

#### `blue_hour_noir` — Blue hour noir

- **Idea:** HD pass, then a cold night grade: deep blue shadows, steel highlights, lowered exposure, strong contrast, and a heavy vignette.
- **Steps:** HD → `color_grade` (temperature -0.45, exposure -0.2, contrast 0.4, black_lift 0.02, split 0.55, balance -0.3, saturation 0.75, shadows [10, 40, 110] / highlights [200, 220, 255]) → `vignette` 0.4
- **File:** `backend/presets/blue_hour_noir.json`


### Prequel-style looks

Ten looks recreated from popular Prequel app filters, aimed at a professionally shot-and-edited feel. All are `ar: non-square`, `text_input: no`, seeded via `seed_default_presets()` / setup. Eight start with the HD pass `{ "filter": "ai_upscale", "long_edge": 1920, "denoise": 0.3 }`; `film_dust` and `disposable_flash` skip it on purpose (lo-fi looks). Each runs in ~3.5–5 s at 33 MP (~1.2 GiB peak; `portrait_bokeh` ~3 GiB for the cutout).

#### `dreamy_glow` — Dreamy glow

- **Idea:** HD pass, then a warm soft-focus (Pro-Mist) look: lifted low-contrast grade with creamy highlights and a diffusion bloom.
- **Steps:** HD → `color_grade` (temperature 0.2, exposure 0.1, contrast -0.2, black_lift 0.06, white_rolloff 0.6, saturation 0.92, vibrance 0.2) → `bloom` (threshold 0.45, radius_ratio 0.04, amount 0.9, color [255, 235, 210])
- **File:** `backend/presets/dreamy_glow.json`

#### `film_halation` — Film halation

- **Idea:** HD pass, then a warm consumer-film grade with a red-orange halation halo around bright lights and fine grain.
- **Steps:** HD → `color_grade` (temperature 0.25, tint -0.05, contrast 0.15, black_lift 0.05, white_rolloff 0.5, split 0.35, saturation 1.05, vibrance 0.1, shadows [40, 70, 60] / highlights [255, 210, 140]) → `halation` (threshold 0.55, radius_ratio 0.015, amount 1.0) → grain 0.06 (`paper_texture`, tint/stains/fade 0)
- **File:** `backend/presets/film_halation.json`

#### `film_dust` — Film dust

- **Idea:** Faded warm film with matte blacks, grain, and scanned-film dust specks, hairs and scratches. No HD pass.
- **Steps:** `color_grade` (temperature 0.2, contrast -0.1, black_lift 0.1, white_rolloff 0.5, split 0.3, saturation 0.8, shadows [60, 70, 80] / highlights [255, 225, 180]) → grain 0.07 → `film_dust` (amount 0.5, hairs 3, scratches 2) → `vignette` 0.2
- **File:** `backend/presets/film_dust.json`

#### `miami_neon` — Miami neon

- **Idea:** HD pass, then a neon-dusk grade: purple shadows, hot-pink highlights, and a pink bloom.
- **Steps:** HD → `color_grade` (tint 0.3, exposure -0.05, contrast 0.2, black_lift 0.03, split 0.7, balance 0.1, saturation 1.15, vibrance 0.2, shadows [80, 40, 160] / highlights [255, 120, 170]) → `bloom` (threshold 0.6, radius_ratio 0.035, amount 0.45, color [255, 170, 220])
- **File:** `backend/presets/miami_neon.json`

#### `prism_glow` — Prism glow

- **Idea:** HD pass, then an editorial prism look: radial colour fringing, a faint violet-blue leak from the left, and a soft bloom.
- **Steps:** HD → `color_grade` (contrast 0.15, saturation 1.1) → `chromatic_aberration` 0.018 → `light_leak` (anchor left, size 0.55, amount 0.3, color [190, 60, 255], core [120, 200, 255], streak 0.7) → `bloom` (threshold 0.55, radius_ratio 0.04, amount 0.5)
- **File:** `backend/presets/prism_glow.json`

#### `disposable_flash` — Disposable flash

- **Idea:** 90s disposable camera: harsh flash contrast, green-tinted shadows, flash falloff, grain, and an orange `$date` stamp (bottom-right, `font_style: stamp`) showing when the photo was taken (EXIF), or today when the file has no capture date. No HD pass.
- **Steps:** `color_grade` (temperature 0.1, tint -0.1, exposure 0.1, contrast 0.35, split 0.3, saturation 1.1, shadows [30, 70, 50] / highlights [255, 240, 215]) → `vignette` (0.35, midpoint 0.4) → grain 0.07 → `draw_text` (`$date`, [255, 140, 40], `bottom_right`, font_size_ratio 0.04, margin_ratio 0.04, `stamp`)
- **File:** `backend/presets/disposable_flash.json`

#### `portrait_bokeh` — Portrait bokeh

- **Idea:** HD pass, then DSLR portrait mode: subject cutout, lens-blurred background with a gentle highlight bloom, composite, light grade.
- **Steps:** HD → `extract_subject` (`single_subject: true`) → `blur` on background (radius_ratio 0.012, `exclude: subject` so the cut-out hole doesn't bleed a dark rim) → `bloom` on background (threshold 0.72, radius_ratio 0.02, amount 0.2) → `composite` → `color_grade` (contrast 0.1, white_rolloff 0.4, vibrance 0.2)
- **File:** `backend/presets/portrait_bokeh.json`


#### `tungsten_night_film` — Tungsten night film

- **Idea:** HD pass, then a tungsten-balanced night film look (800T style): cool blue-teal cast, warm highlights, red halation around lights, light bloom, grain.
- **Steps:** HD → `color_grade` (temperature -0.35, tint 0.05, exposure 0.05, contrast 0.2, black_lift 0.04, white_rolloff 0.5, split 0.5, saturation 0.95, vibrance 0.15, shadows [20, 70, 110] / highlights [255, 200, 170]) → `halation` (threshold 0.55, radius_ratio 0.018, amount 1.0, color [255, 40, 30]) → `bloom` (threshold 0.7, radius_ratio 0.02, amount 0.2) → grain 0.07
- **File:** `backend/presets/tungsten_night_film.json`

#### `muted_chrome_film` — Muted chrome film

- **Idea:** HD pass, then a muted documentary film grade (Classic Chrome style): lowered saturation, firm contrast with a slight matte lift, cyan-teal shadows, warm highlights, fine grain.
- **Steps:** HD → `color_grade` (temperature -0.05, tint 0.05, contrast 0.4, black_lift 0.06, white_rolloff 0.4, split 0.45, saturation 0.8, shadows [30, 90, 100] / highlights [255, 215, 185]) → grain 0.05 → `vignette` 0.15
- **File:** `backend/presets/muted_chrome_film.json`

#### `studio_spotlight` — Studio spotlight

- **Idea:** HD pass, then a low-key studio portrait: subject cut out, background darkened, desaturated, softened and vignetted so the subject sits in a spotlight.
- **Steps:** HD → `extract_subject` (`single_subject: true`) → `color_grade` on background (exposure -0.8, contrast 0.1, saturation 0.6) → `blur` on background (radius_ratio 0.004, `exclude: subject`) → `vignette` on background (0.55, midpoint 0.3, roundness 0.6) → `composite` → `color_grade` (contrast 0.15, white_rolloff 0.4, vibrance 0.15) → `vignette` 0.2
- **File:** `backend/presets/studio_spotlight.json`


### Poster titles (text behind subject)

Ten poster looks: subject cut out (`single_subject: true`) → one colour family pushed on the background with `selective_color` → a large `$text` title painted on the **background** → subject composited back on top, so it covers part of the title. All are `ar: non-square`, `text_input: yes`, `default_text: "TITLE"` (`retrowave_neon_title` defaults to `MIDNIGHT DRIVE`, `mission_passed_title` to `LEVEL UP`, `neon_nights_script` to `Neon Nights`), `text_character_limit: 16`, no HD pass, seeded via `seed_default_presets()` / setup. Titles are top-aligned (`margin_ratio` 0.03–0.05), stretched tall with `scale_y`, and auto-fit to 90% of the width. Text keeps the user's casing, except `neon_lines` (Monoton) and `marquee` (Bungee), whose fonts only have capitals.

#### `poster_title_yellow_pop` — Poster title: yellow pop

- **Steps:** `extract_subject` → `selective_color` yellow (width 45, saturation 1.8, lightness 0.12, others 0.35, pull 0.4) → `draw_text` red [220, 30, 30], `font_style: poster`, font_size_ratio 0.34, `scale_y` 1.9 → `composite`
- **File:** `backend/presets/poster_title_yellow_pop.json`

#### `poster_title_blue_pop` — Poster title: blue pop

- **Steps:** `extract_subject` → `selective_color` blue (saturation 1.7, others 0.5) → `draw_text` orange [255, 120, 0], `poster`, `scale_y` 1.9 → `composite`
- **File:** `backend/presets/poster_title_blue_pop.json`

#### `retro_70s_poster` — Retro 70s poster

- **Steps:** `extract_subject` → `selective_color` orange (saturation 1.6, others 0.5) → `draw_text` teal [0, 120, 125], `font_style: slab` → `composite` → warm faded `color_grade` → `paper_texture` (sun-faded paper)
- **File:** `backend/presets/retro_70s_poster.json`

#### `brush_script_poster` — Brush script poster

- **Steps:** `extract_subject` → `selective_color` yellow → `draw_text` red, `font_style: brush`, font_size_ratio 0.4, `scale_y` 1.3, same-colour stroke to thicken → `composite`
- **File:** `backend/presets/brush_script_poster.json`

#### `neon_nights_script` — Neon nights script

- **Steps:** `extract_subject` → night `color_grade` on background (magenta tint, sunset split-tone) → `selective_color` magenta → `draw_text` pale-pink core + hot-pink stroke, `font_style: signature`, `angle` −8, `glow_ratio` 0.025 → cyan `glow_line_border` on subject → `composite` → grain
- **File:** `backend/presets/neon_nights_script.json`

#### `mission_passed_title` — Mission passed title

- **Steps:** `extract_subject` → night `color_grade` (exposure −0.8) → `selective_color` blue → `draw_text` gold [255, 200, 40] with black stroke (stroke_ratio 0.01), `font_style: bold_display`, `angle` −4, `scale_y` 1.5 → `composite` → grain
- **File:** `backend/presets/mission_passed_title.json`

#### `wanted_stencil_title` — Wanted stencil title

- **Steps:** `extract_subject` → dark `color_grade` (exposure −0.9) → `selective_color` red (others 0.25) → `draw_text` red with black stroke, `font_style: stencil`, `scale_y` 1.6 → `composite` → `halation` → grain
- **File:** `backend/presets/wanted_stencil_title.json`

#### `retrowave_neon_title` — Retrowave neon title

- **Steps:** `extract_subject` → purple night `color_grade` → `selective_color` purple → `draw_text` pale-cyan, `font_style: neon_lines` (caps only), pink `glow_color`, `glow_ratio` 0.03 → pink `glow_line_border` on subject → `composite` → grain
- **File:** `backend/presets/retrowave_neon_title.json`

#### `art_deco_marquee` — Art deco marquee

- **Steps:** `extract_subject` → teal night `color_grade` → `selective_color` teal → `draw_text` gold [255, 195, 60], `font_style: marquee` (caps only), `box: double` (box_ratio 0.004, box_pad_ratio 0.03) → `composite` → warm `halation` → grain
- **File:** `backend/presets/art_deco_marquee.json`

#### `velvet_ticket_title` — Velvet ticket title

- **Steps:** `extract_subject` → sunset `color_grade` (magenta / orange split) → `selective_color` magenta → `draw_text` cream, `font_style: signature`, `box: double` in gold [235, 190, 90], box_radius_ratio 0.03, `angle` −3 → `composite` → `vignette` → grain
- **File:** `backend/presets/velvet_ticket_title.json`

### Border doodles (no cutout)

Ten looks that keep the photo intact: an optional colour treatment, then a few simple hand-drawn marks (`doodle` at explicit `x`/`y` within ~0.15 of an edge) and/or a hand-drawn border (`doodle_frame`). No `extract_subject`, no HD pass, so they are fast and light (good with `LIGHTWEIGHT=1`). All are `ar: non-square`, `text_input: no`, seeded via `seed_default_presets()` / setup.

#### `marker_frame_doodle` — Marker frame doodle

- **Idea:** White hand-drawn marker border with sparkles and a spiral in the corners.
- **Steps:** `doodle_frame` line auto → `doodle` stars [255, 255, 255] at (0.86, 0.13) → `doodle` spiral [255, 255, 255] at (0.12, 0.88)
- **File:** `backend/presets/marker_frame_doodle.json`

#### `sunny_sketchbook_doodle` — Sunny sketchbook doodle

- **Idea:** Warm lift with a yellow sun, white cloud, pink hearts and an orange flower doodled in the corners.
- **Steps:** `color_grade` → `doodle` sun [255, 205, 40] at (0.13, 0.13) → `doodle` cloud [255, 255, 255] at (0.86, 0.12) → `doodle` hearts [255, 90, 150] at (0.87, 0.87) → `doodle` flower [255, 140, 40] at (0.12, 0.88)
- **File:** `backend/presets/sunny_sketchbook_doodle.json`

#### `neon_doodle_nights` — Neon doodle nights

- **Idea:** Darker cool grade, hot-pink dashed frame, cyan spiral and sparkles, a yellow lightning bolt, soft glow.
- **Steps:** `color_grade` → `doodle_frame` dashes [255, 90, 150] → `doodle` spiral [40, 220, 255] at (0.13, 0.13) → `doodle` stars [40, 220, 255] at (0.86, 0.14) → `doodle` bolt [255, 205, 40] at (0.87, 0.86) → `bloom`
- **File:** `backend/presets/neon_doodle_nights.json`

#### `chalkboard_doodle` — Chalkboard doodle

- **Idea:** Black and white with extra contrast and grain; white dotted frame, tic-tac-toe, curved arrow and sparkles.
- **Steps:** `grayscale` → `contrast` → `doodle_frame` dots [255, 255, 255] → `doodle` xo [255, 255, 255] at (0.86, 0.14) → `doodle` arrow [255, 255, 255] at (0.15, 0.88) → `doodle` stars [255, 255, 255] at (0.13, 0.13) → `paper_texture`
- **File:** `backend/presets/chalkboard_doodle.json`

#### `love_notes_doodle` — Love notes doodle

- **Idea:** Blush pastel grade, pink wavy frame and red hearts in two corners.
- **Steps:** `color_grade` → `doodle_frame` waves [255, 150, 185] → `doodle` hearts [230, 40, 80] at (0.13, 0.13) → `doodle` hearts [230, 40, 80] at (0.87, 0.87)
- **File:** `backend/presets/love_notes_doodle.json`

#### `retro_70s_doodle` — Retro 70s doodle

- **Idea:** Warm faded print on paper with a mustard double frame, orange flowers and brown dots.
- **Steps:** `color_grade` → `doodle_frame` double [225, 165, 40] → `doodle` flower [230, 100, 40] at (0.12, 0.12) → `doodle` flower [230, 100, 40] at (0.88, 0.88) → `doodle` dots [120, 70, 40] at (0.87, 0.13) → `paper_texture`
- **File:** `backend/presets/retro_70s_doodle.json`

#### `comic_pop_doodle` — Comic pop doodle

- **Idea:** Punchy colour with light halftone dots, black zigzag frame, yellow lightning bolts and red dots.
- **Steps:** `color_grade` → `halftone` → `doodle_frame` zigzag [20, 20, 20] → `doodle` bolt [255, 205, 40] at (0.87, 0.14) → `doodle` bolt [255, 205, 40] at (0.13, 0.86) → `doodle` dots [230, 30, 40] at (0.13, 0.13)
- **File:** `backend/presets/comic_pop_doodle.json`

#### `scrapbook_doodle` — Scrapbook doodle

- **Idea:** Cream paper texture, brown corner brackets, teal arrow and tic-tac-toe, coral wiggles.
- **Steps:** `paper_texture` → `doodle_frame` corners [90, 60, 40] → `doodle` arrow [20, 140, 140] at (0.15, 0.12) → `doodle` xo [20, 140, 140] at (0.87, 0.87) → `doodle` wiggles [240, 110, 90] at (0.13, 0.88)
- **File:** `backend/presets/scrapbook_doodle.json`

#### `cyanotype_doodle` — Cyanotype doodle

- **Idea:** Blue duotone with a thin white frame, white rings, a spiral and sparkles.
- **Steps:** `grayscale` → `color_grade` → `doodle_frame` line [255, 255, 255] → `doodle` rings [255, 255, 255] at (0.87, 0.13) → `doodle` spiral [255, 255, 255] at (0.13, 0.87) → `doodle` stars [255, 255, 255] at (0.13, 0.13)
- **File:** `backend/presets/cyanotype_doodle.json`

#### `confetti_pastel_doodle` — Confetti pastel doodle

- **Idea:** Bright airy grade with pastel confetti dots in every corner, a lilac zigzag on top and a mint wave below.
- **Steps:** `color_grade` → `doodle` dots [255, 150, 190] at (0.12, 0.13) → `doodle` dots [120, 220, 190] at (0.88, 0.13) → `doodle` dots [255, 210, 90] at (0.12, 0.87) → `doodle` dots [180, 150, 255] at (0.88, 0.87) → `doodle` zigzag [180, 150, 255] at (0.5, 0.07) → `doodle` wiggles [120, 210, 180] at (0.5, 0.94)
- **File:** `backend/presets/confetti_pastel_doodle.json`


### Tone curves & motion

Ten looks built on point curves (`tone_curve`) and local shadow / highlight recovery (`shadows_highlights`); the last two add a directional shutter `motion_blur` (plus `radial_swirl`, a circular `radial_blur`). All are `ar: non-square`, `text_input: no`, seeded via `seed_default_presets()` / setup. The eight grades start with the HD pass `{ "filter": "ai_upscale", "long_edge": 1920, "denoise": 0.3 }`; `shutter_drag` and `speed_pan` skip it on purpose (motion blur hides the extra detail, and with `LIGHTWEIGHT=1` the enlarged cut-out would push a 1 GB host past its RAM). Grades run in ~3.7 s / ~0.9 GiB peak at 24 MP; the motion presets ~6 s / ~2.9 GiB (rembg cutout), and ~0.83–0.9 GiB with `LIGHTWEIGHT=1` at 2 MP (like `portrait_bokeh`).

#### `print_film_2383` — Print film 2383

- **Idea:** HD pass, then cinema print-film curves: lifted blue blacks, warm compressed highlights, recovered skies, opened shadows.
- **Steps:** HD → `shadows_highlights` (+0.25 / -0.45) → `tone_curve` (master 0→8 60→48 128→130 200→212 255→245; red 0→0 128→134 255→255; green 0→4 128→128 255→250; blue 0→26 110→112 200→186 255→225) → `color_grade` (saturation 0.95, vibrance 0.15) → `vignette` 0.2
- **File:** `backend/presets/print_film_2383.json`

#### `cross_process` — Cross process

- **Idea:** HD pass, then classic cross-processed slide: hard red S-curve, yellow-green highlights, lifted blue blacks, punchy colour.
- **Steps:** HD → `shadows_highlights` (+0.15 / -0.25) → `tone_curve` (red 0→0 64→40 128→140 192→225 255→255; green 0→0 64→52 128→135 192→212 255→250; blue 0→45 128→118 255→200) → `color_grade` (saturation 1.15)
- **File:** `backend/presets/cross_process.json`

#### `hdr_clarity_pop` — HDR clarity pop

- **Idea:** HD pass, then strong local shadow lift + highlight recovery, then an S-curve to restore punch — detailed, high dynamic range look.
- **Steps:** HD → `shadows_highlights` (+0.7 / -0.7, radius_ratio 0.03, local 0.7) → `tone_curve` (master 0→0 40→30 128→132 215→230 255→255) → `color_grade` (vibrance 0.35) → `sharpen` (radius 4.0, percent 50, threshold 2)
- **File:** `backend/presets/hdr_clarity_pop.json`

#### `bleach_bypass` — Bleach bypass

- **Idea:** HD pass, then silver-retention look: half saturation, steep contrast curve, recovered highlights, cool-neutral cast.
- **Steps:** HD → `shadows_highlights` (-0.1 / -0.35) → `color_grade` (saturation 0.45, contrast 0.2) → `tone_curve` (master 0→0 50→30 128→128 200→222 255→252; blue 0→6 255→245) → `vignette` 0.25
- **File:** `backend/presets/bleach_bypass.json`

#### `mocha_moody` — Mocha moody

- **Idea:** HD pass, then brown, matte moody edit: faded blacks, pulled whites, warm-brown curves, muted colour, deep highlight recovery.
- **Steps:** HD → `shadows_highlights` (+0.3 / -0.65) → `tone_curve` (master 0→38 70→72 180→176 255→226; red 0→10 128→138 255→248; green 0→2 128→120 255→232; blue 0→0 128→100 255→196) → `color_grade` (saturation 0.62, temperature 0.1)
- **File:** `backend/presets/mocha_moody.json`

#### `lavender_dusk` — Lavender dusk

- **Idea:** HD pass, then dreamy violet curves: blue lifted throughout, green dipped in mids, soft lifted blacks, gentle lavender bloom.
- **Steps:** HD → `shadows_highlights` (+0.35 / -0.4) → `tone_curve` (master 0→16 128→134 255→248; red 0→10 128→132 255→250; green 0→0 96→84 180→174 255→240; blue 0→36 128→142 255→255) → `color_grade` (saturation 0.85, vibrance 0.2) → `bloom` (threshold 0.65, radius_ratio 0.03, amount 0.3, color [230, 210, 255])
- **File:** `backend/presets/lavender_dusk.json`

#### `hdr_noir_mono` — HDR noir mono

- **Idea:** HD pass, then dramatic black & white: big shadow lift + highlight recovery, steep S-curve, vignette.
- **Steps:** HD → `shadows_highlights` (+0.55 / -0.75, radius_ratio 0.03, local 0.75) → `grayscale` → `tone_curve` (master 0→0 45→22 128→128 205→232 255→255) → `sharpen` (radius 4.0, percent 40, threshold 2) → `vignette` 0.35
- **File:** `backend/presets/hdr_noir_mono.json`

#### `mint_pastel_film` — Mint pastel film

- **Idea:** HD pass, then fuji-pastel style: mint-green lifted shadows, airy matte curve, soft highlights, low saturation, fine grain.
- **Steps:** HD → `shadows_highlights` (+0.45 / -0.5) → `tone_curve` (master 0→26 64→74 128→142 200→214 255→244; red 0→0 128→118 255→250; green 0→22 128→138 255→255; blue 0→16 128→132 255→236) → `color_grade` (saturation 0.78, vibrance 0.25, temperature -0.08, tint -0.1) → grain 0.04
- **File:** `backend/presets/mint_pastel_film.json`

#### `shutter_drag` — Shutter drag

- **Idea:** Subject streaks like a fast-moving object at a slow shutter (trail behind, faint flash-frozen copy on top); cool contrast curve, recovered highlights.
- **Steps:** `extract_subject` (`single_subject: true`) → `motion_blur` on subject (length_ratio 0.14, angle 0, trail 0.85, fade 0.55, freeze 0.35) → `composite` → `shadows_highlights` (+0.3 / -0.45) → `tone_curve` (master 0→6 60→44 128→128 200→214 255→250; red 0→0 128→126 255→255; green 0→6 128→130 255→252; blue 0→22 128→136 255→238) → `color_grade` (saturation 0.9, vibrance 0.2) → `vignette` 0.25
- **File:** `backend/presets/shutter_drag.json`

#### `speed_pan` — Speed pan

- **Idea:** Panning shot: subject sharp, background streaked horizontally; warm punchy S-curve with opened shadows and a vignette.
- **Steps:** `extract_subject` (`single_subject: true`) → `motion_blur` on background (length_ratio 0.09, angle 0, trail 0) → `composite` → `shadows_highlights` (+0.35 / -0.5) → `tone_curve` (master 0→0 50→36 128→132 205→224 255→252; red 0→0 128→136 255→255; blue 0→10 128→122 255→240) → `color_grade` (saturation 1.05, vibrance 0.25) → `vignette` 0.3
- **File:** `backend/presets/speed_pan.json`

#### `radial_swirl` — Radial swirl

- **Idea:** Subject stays sharp while the background spins in a circular (rotational) blur centred behind the subject — the swirl gets stronger toward the frame edges. `ar: non-square`, `text_input: no`, no HD.
- **Steps:** `extract_subject` (`single_subject: true`) → `radial_blur` on background (`mode: spin`, amount 14°, `exclude: subject` — centre = subject's alpha centroid, hole colours kept out) → `composite`
- **File:** `backend/presets/radial_swirl.json`

#### `twirl_vortex` — Twirl vortex

- **Idea:** Subject sharp; the background twisted into a whirlpool centred behind the subject (detail stays sharp — a warp, not a blur), light vignette. `ar: non-square`, `text_input: no`, no HD.
- **Steps:** `extract_subject` (`single_subject: true`) → `warp` on background (`mode: twirl`, amount 160°, radius 1.0, `exclude: subject`) → `composite` → `vignette` 0.3
- **File:** `backend/presets/twirl_vortex.json`

#### `water_ripple` — Water ripple

- **Idea:** Concentric pond rings spread out from behind the subject, shaded crests fading toward the edges, cool grade on the background.
- **Steps:** `extract_subject` → `warp` on background (`mode: ripple`, amount 0.014, wavelength 0.06, shade 0.35, falloff 1.6, `exclude: subject`) → `color_grade` on background (temperature -0.2, saturation 0.9) → `composite`
- **File:** `backend/presets/water_ripple.json`

#### `squiggle_wave` — Squiggle wave

- **Idea:** Psychedelic squiggly background — diagonal sine wobble on both axes with boosted colour; subject crisp.
- **Steps:** `extract_subject` → `warp` on background (`mode: wave`, amount 0.025, wavelength 0.09, angle 20, `exclude: subject`) → `color_grade` on background (saturation 1.35, contrast 0.1) → `composite`
- **File:** `backend/presets/squiggle_wave.json`

#### `liquid_spill` — Liquid spill

- **Idea:** Background melts into a glossy, marbled flow like spilled water (seeded noise warp with slope shading), soft highlight bloom.
- **Steps:** `extract_subject` → `warp` on background (`mode: liquid`, amount 0.06, wavelength 0.18, shade 0.6, seed 7, `exclude: subject`) → `composite` → `bloom` (threshold 0.75, radius_ratio 0.02, amount 0.15)
- **File:** `backend/presets/liquid_spill.json`

### RGB-curve film looks

Five professional film-stock looks driven by per-channel RGB curves (`tone_curve`), built from published film-emulation principles (soft consumer-film curves with lifted matte blacks; red pulled from shadows / lifted in mid-highs; blue dipped in highlights for warmth; green lifted in shadows for a green-cyan cast). They are stylised interpretations of classic film character, hand-built from those principles — not measured emulations of any specific stock — and brand names stay out of names, labels, descriptions and keywords. All `ar: non-square`, `text_input: no`, and start with the HD pass `{ "filter": "ai_upscale", "long_edge": 1920, "denoise": 0.3 }` (denoise 0.3 keeps texture under the added grain). Grain is `paper_texture` with `tint` 0 (grain only; size scales with resolution). `expired_film` uses `seed: "auto"`, so each photo gets its own stain layout.

#### `vista_red_film` — Vista red film

- **Idea:** a crisp colour-negative look: red pulled down in the shadows and lifted in the mid-highs, slightly cool shadows, saturated reds and cyan-leaning skies, fine grain.
- **Steps:** HD → `shadows_highlights` → `tone_curve` (master 0→6 64→56 128→132 192→204 255→250; red 0→0 64→54 128→134 200→214 255→255; green 0→4 128→128 255→250; blue 0→14 128→124 255→236) → `color_grade` → `paper_texture`
- **File:** `backend/presets/vista_red_film.json`

#### `golden_consumer_film` — Golden consumer film

- **Idea:** a warm consumer colour-negative look: blue dipped in the highlights for golden warmth, lifted blacks, soft contrast, fine grain.
- **Steps:** HD → `shadows_highlights` → `tone_curve` (master 0→14 64→66 128→134 200→212 255→248; red 0→6 128→138 255→255; green 0→8 128→132 255→246; blue 0→0 128→110 255→212) → `color_grade` → `paper_texture`
- **File:** `backend/presets/golden_consumer_film.json`

#### `green_cast_film` — Green cast film

- **Idea:** an everyday colour-negative look with a green-cyan cast: green lifted in the shadows and low mids, red trimmed, slightly cool, fine grain.
- **Steps:** HD → `shadows_highlights` → `tone_curve` (master 0→10 64→60 128→130 200→206 255→246; red 0→0 128→122 255→248; green 0→16 64→70 128→134 255→252; blue 0→12 128→128 255→240) → `color_grade` → `paper_texture`
- **File:** `backend/presets/green_cast_film.json`

#### `classic_slide_64` — Classic slide 64

- **Idea:** a dense classic slide-film look: firm contrast, rich reds, blue lowered in the highlights for warmth, teal-cyan shadows, vignette, fine grain.
- **Steps:** HD → `shadows_highlights` → `tone_curve` (master 0→0 48→30 128→126 205→222 255→252; red 0→0 64→58 128→136 255→255; green 0→0 128→126 255→246; blue 0→10 64→66 128→120 255→214) → `color_grade` → `vignette` → `paper_texture`
- **File:** `backend/presets/classic_slide_64.json`

#### `expired_film` — Expired film

- **Idea:** an expired-roll look: flattened, faded blacks, a magenta-cyan colour crossover (red and blue lifted in the shadows, green dipped), muted colour, grain and faint stains.
- **Steps:** HD → `tone_curve` (master 0→20 128→128 255→235; red 0→26 128→138 255→238; green 0→10 128→118 255→230; blue 0→32 128→132 255→224) → `color_grade` → `paper_texture`
- **File:** `backend/presets/expired_film.json`

### Subject spotlights

#### `red_halo_spotlight` — Red halo spotlight

- **Idea:** Subject pops off a muted, lightly white-washed background with a yellow sticker outline and a large translucent red disc behind it. `ar: non-square`, `text_input: no`, no HD.
- **Steps:** `extract_subject` (`single_subject: true`) → `color` 0.35 on background → `overlay` white α 0.15 on background → `circle_backdrop` on background (`anchor: subject`, `around: subject`, color [220, 30, 30], opacity 0.55, size 0.85, subject_fit 1.15) → `sticker_outline` on subject ([255, 214, 0], width_ratio 0.012) → `composite`
- **File:** `backend/presets/red_halo_spotlight.json`

### Flash looks

#### `digicam_flash` — Digicam flash

- **Idea:** Y2K point-and-shoot night flash (Prequel "Digital Flash" style). Everyone in front is cut out and lit with a cool, glossy on-camera flash, and the background falls off to blue-black like an unlit room behind the flash. `single_subject: false` so every person in a group is lit. Slight lens fringing and fine digital noise. `ar: non-square`, `text_input: no`, no HD (noise and fringing are part of the look). The background is only darkened when the cutout covers at least 4% of the frame (`requires_layer: subject`, `min_coverage: 0.04`), so a photo with no clear subject (a landscape where rembg only finds a bench or a flag) stays near the original instead of going black. Large objects (a tram, a building) still get the flash look.
- **Steps:** `extract_subject` (`single_subject: false`, `require_clear_subject: true`) → `color_grade` on background (temperature -0.35, exposure -1.7, contrast 0.35, saturation 0.6) → `vignette` on background (0.8, midpoint 0.2, feather 0.8, roundness 0.6) — both gated by `requires_layer: subject`, `min_coverage: 0.04` → `color_grade` on subject (temperature -0.12, exposure 0.25, contrast 0.3, white_rolloff 0.45, saturation 0.95, vibrance 0.15) → `tone_curve` on subject (master 0→0 45→30 128→140 255→255; blue 0→8 128→132 255→255) → `bloom` on subject (threshold 0.7, radius_ratio 0.006, amount 0.35, color [240, 245, 255]) → `composite` → `chromatic_aberration` 0.002 → grain 0.04
- **File:** `backend/presets/digicam_flash.json`
- **AR:** `non-square` (any aspect ratio)
- **Text input:** `no`
- **DB:** seeded via `seed_default_presets()` / setup

### Light gels

#### `red_gel_portrait` — Red gel portrait

- **Idea:** A soft red gel light cast over the subject, which keeps the colour fairly subtle: whites and highlights take a rose-red tint and skin warms slightly, while darks stay put. The background is muted and pushed toward a cool blue, slightly darker. `single_subject: false`, so everyone in front gets the red light. Subjects in dark or strongly coloured clothes show less red (the cast follows brightness); the background still goes blue. `ar: non-square`, `text_input: no`, no HD.
- **Steps:** `extract_subject` (`single_subject: false`) → `color` 0.55 on background → `tone_curve` on background (red 0→0 128→110 255→225; green 0→0 128→120 255→236; blue 0→24 128→146 255→255) → `color_grade` on background (exposure -0.15, contrast 0.05) → `tone_curve` on subject (red 0→6 128→140 255→255; green and blue 0→0 128→118 255→205) → `composite`
- **File:** `backend/presets/red_gel_portrait.json`
- **AR:** `non-square` (any aspect ratio)
- **Text input:** `no`
- **DB:** seeded via `seed_default_presets()` / setup

#### More gel colour pairs

Five variations on `red_gel_portrait` with the same steps — `extract_subject` (`single_subject: false`) → `color` 0.55 + tint `tone_curve` + `color_grade` (exposure -0.15, contrast 0.05) on background → tint `tone_curve` on subject → `composite` — but different colours. The subject curve sends pure white to a **light shade** of the gel colour (darks stay put), and the background curve pushes the muted background toward a **contrasting** tint. Curves come from a target colour: each channel's white point is the target, the midpoint moves by its offset from the target's mean (×0.36 on the subject, ×1.0 on the background). Black points: the background lifts at most 10 (blacks stay near-black, so night shots don't turn deep red / teal), and the subject's darks lean toward the gel by up to 18 (offset × 0.45), so dark clothing still picks up a little colour. The background tint sits ≥ 90° of hue from the gel (complementary-ish). All `ar: non-square`, `text_input: no`, no HD, seeded via `seed_default_presets()` / setup.

| Preset | Subject whites → | Background tint | File |
|---|---|---|---|
| `amber_teal_gel` — Amber teal gel | light cream-amber [255, 222, 170] | teal | `backend/presets/amber_teal_gel.json` |
| `ice_gel_orange` — Ice gel orange | light ice blue [180, 236, 255] | warm orange | `backend/presets/ice_gel_orange.json` |
| `pistachio_gel_rose` — Pistachio gel rose | light pistachio green [185, 255, 215] | rose pink | `backend/presets/pistachio_gel_rose.json` |
| `sky_gel_amber` — Sky gel amber | light sky blue [190, 210, 255] | golden amber (the reverse of red gel) | `backend/presets/sky_gel_amber.json` |
| `coral_gel_lagoon` — Coral gel lagoon | light coral peach [255, 190, 170] | lagoon turquoise | `backend/presets/coral_gel_lagoon.json` |

### Typographic split

#### `split_word_portrait` — Split word portrait

- **Idea:** The photo is split by a vertical line through the middle of the subject. Left of the line the background becomes plain white and the subject's left half is shown only through a dense wall of the user's text (`$text`, repeated as `TEXT.TEXT.TEXT.` in bold capitals, mixed mostly-large sizes, even tight line gaps); the gaps between letters are white. Right of the line the original photo is untouched. `ar: non-square`, `text_input: yes` (default `DREAM`, max 20 characters), no HD.
- **Steps:** `extract_subject` (`single_subject: true`) → `half_mask` on subject (`side: left`, `around: subject`) as `subject_left` → white `overlay` (α 1) as `white` → `half_mask` on `white` (left, around subject) → `composite` (left half white) → `text_pattern` as `letters` (`$text`, `transparent`, `bold_display`, uppercase, sizes [0.11, 0.05, 0.09, 0.035, 0.1, 0.06, 0.075], `gap_ratio` 0.004) → `clip_to` on `subject_left` around `letters` as `painted` → `composite`
- **File:** `backend/presets/split_word_portrait.json`
- **AR:** `non-square` (any aspect ratio)
- **Text input:** `yes` — default `DREAM`, limit **20**
- **DB:** seeded via `seed_default_presets()` / setup

### Shape windows

#### `shape_window_portrait` — Shape window portrait

- **Idea:** Graphic collage: the frame becomes plain white and four large shapes — circle (top-left), square (top-right), square (bottom-left), circle (bottom-right), each 0.44 of the short side and nudged up-right so the top pair is cropped by the frame edge — act as windows onto the original photo. The full cut-out subject sits on top. `ar: non-square` (positions are fractions of width / height, sizes of the short side, so shapes stay round / square), `text_input: no`, no HD. Works best when the photo's background has colour or texture (on a plain white wall the windows disappear into the canvas).
- **Steps:** `extract_subject` (`single_subject: true`) → white `overlay` (α 1) as `canvas` → four `draw_shape` into `shapes` (first with `clear: true`) at (0.32, 0.18), (0.82, 0.18), (0.32, 0.68), (0.82, 0.68), size 0.44 → `clip_to` on `image` around `shapes` as `windows` → `composite` canvas + windows → `composite` subject on top
- **File:** `backend/presets/shape_window_portrait.json`
- **AR:** `non-square` (any aspect ratio)
- **Text input:** `no`
- **DB:** seeded via `seed_default_presets()` / setup

### Instant film (Instax)

Five instant-print looks. Each crops the photo to its real Instax film shape with `crop_aspect` (Mini [46, 62] portrait, Square [1, 1], Wide [99, 62] landscape), grades it, then mounts it on a card with real Instax proportions via `place_on_canvas` `margins` (thin sides and top, deep bottom band) and writes the user's optional caption in the band (`$text`, `font_style: scribble`, dark grey [60, 60, 60]; caption size matched to the physical card so it looks the same on every format). All are `ar: non-square` (any upload; the crop sets the shape), `text_input: yes` with an empty `default_text` (no caption unless the user types one) and a 24-character limit, no HD, seeded via `seed_default_presets()` / setup. Mini / Square / Wide card margins: [0.087, 0.141, 0.087, 0.38] / [0.081, 0.097, 0.081, 0.29] / [0.073, 0.089, 0.073, 0.30].

#### `instax_mini_classic` — Instax mini classic

- **Steps:** `crop_aspect` [46, 62] → `color_grade` (temperature -0.05, exposure 0.15, contrast -0.1, black_lift 0.06, white_rolloff 0.5, split 0.3, shadows [60, 90, 120] / highlights [255, 245, 230], saturation 0.92) → `bloom` (threshold 0.75, radius_ratio 0.02, amount 0.2) → `vignette` 0.15 → grain 0.04 → off-white [250, 250, 247] Mini card → caption (font_size_ratio 0.13, margin_ratio 0.095)
- **File:** `backend/presets/instax_mini_classic.json`

#### `instax_square_sunny` — Instax square sunny

- **Steps:** `crop_aspect` [1, 1] → warm overexposed `color_grade` (temperature 0.3, exposure 0.3, contrast -0.05, black_lift 0.05, white_rolloff 0.6, split 0.35, shadows [110, 80, 70] / highlights [255, 230, 190], saturation 1.05, vibrance 0.2) → warm `bloom` (threshold 0.6, radius_ratio 0.03, amount 0.35) → `vignette` 0.1 → grain 0.04 → off-white Square card → caption (0.097 / 0.071)
- **File:** `backend/presets/instax_square_sunny.json`

#### `instax_wide_cool` — Instax wide cool

- **Steps:** `crop_aspect` [99, 62] → faded cool `color_grade` (temperature -0.25, tint -0.05, exposure 0.05, contrast -0.1, black_lift 0.08, white_rolloff 0.5, split 0.4, shadows [30, 90, 100] / highlights [235, 245, 240], saturation 0.85) → `vignette` 0.12 → grain 0.045 → off-white Wide card → caption (0.095 / 0.06)
- **File:** `backend/presets/instax_wide_cool.json`

#### `instax_monochrome` — Instax monochrome

- **Steps:** `crop_aspect` [46, 62] → `grayscale` → `color_grade` (exposure 0.05, contrast 0.2, black_lift 0.04, white_rolloff 0.4, split 0.15, cool shadows [90, 95, 105] / warm-white highlights [250, 248, 242]) → `vignette` 0.2 → grain 0.06 → off-white Mini card → caption (0.13 / 0.095)
- **File:** `backend/presets/instax_monochrome.json`

#### `instax_sky_flash` — Instax sky flash

- **Steps:** `crop_aspect` [46, 62] → punchy flash `color_grade` (temperature 0.05, exposure 0.2, contrast 0.25, white_rolloff 0.35, saturation 1.1, vibrance 0.15) → flash-falloff `vignette` (0.3, midpoint 0.4) → grain 0.04 → sky-blue [176, 212, 238] Mini card → caption (0.13 / 0.095)
- **File:** `backend/presets/instax_sky_flash.json`

### Text + shape overlays

Five poster-style overlays that pair a shape with the user's text. All extract the subject (`single_subject: true`) so the shape sits behind it, are `ar: non-square`, `text_input: yes`, no HD, and are seeded via `seed_default_presets()` / setup.

#### `synthwave_sun` — Synthwave sun

- **Idea:** Night-purple grade on the background, a big coral sun disc behind the subject with a pink bloom, and the text in glowing neon tube capitals at the bottom. Default `MIDNIGHT`, limit **14**.
- **Steps:** `extract_subject` → `color_grade` on background (temperature -0.3, tint 0.45, exposure -1.3, contrast 0.25, split 0.75, shadows [40, 10, 90] / highlights [255, 80, 200], saturation 1.15) → `draw_shape` circle on background (0.5, 0.42, size 0.62, [255, 96, 128]) → pink `bloom` → `composite` → `draw_text` `$text` (`neon_lines`, bottom, font_size_ratio 0.11, glow_ratio 0.03 pink)
- **File:** `backend/presets/synthwave_sun.json`

#### `diamond_editorial` — Diamond editorial

- **Idea:** Sand canvas [214, 196, 176] with a large diamond window onto the photo and an offset outline diamond, subject on top, text as a tall vertical title up the left edge. Default `EDITION`, limit **14**.
- **Steps:** `extract_subject` → `overlay` canvas → `draw_shape` diamond mask (0.56, 0.5, size 0.95, `clear`) → `clip_to` → `composite` → outline `draw_shape` diamond (0.6, 0.54, stroke 0.004) → `composite` subject → `draw_text` `$text` (`poster`, angle 90, `center_x` 0.085 / `center_y` 0.5, font_size_ratio 0.13)
- **File:** `backend/presets/diamond_editorial.json`

#### `word_wall_poster` — Word wall poster

- **Idea:** The background becomes a wall of the text (`text_pattern`, separator ` • `, uppercase, sizes [0.09, 0.05, 0.07, 0.04], gap_ratio 0.01, black / coral / black / grey rows on cream), a yellow circle behind the head, and a white sticker outline on the subject. Default `GOOD VIBES`, limit **16**.
- **Steps:** `extract_subject` → `text_pattern` as `background` → `draw_shape` circle (0.5, 0.36, size 0.6, [255, 200, 40]) → `sticker_outline` → `composite`
- **File:** `backend/presets/word_wall_poster.json`

#### `neon_frame_sign` — Neon frame sign

- **Idea:** Dark, cool background, a hot-pink square neon outline behind the subject (bloomed so it glows), and the text as a pink neon script sign at the top. Default `after dark`, limit **16**.
- **Steps:** `extract_subject` → `color_grade` on background (exposure -1.3, temperature -0.3, saturation 0.6) → outline `draw_shape` square (0.5, 0.52, size 0.72, stroke 0.012, [255, 70, 180]) → pink `bloom` → `composite` → `draw_text` `$text` (`signature`, top, font_size_ratio 0.12, glow_ratio 0.025, angle -4)
- **File:** `backend/presets/neon_frame_sign.json`

#### `pop_art_panel` — Pop art panel

- **Idea:** Lichtenstein-style comic panel: background as red halftone dots on yellow (on dark backgrounds the dots merge into near-solid red), subject posterised with ink outlines and a thin dark sticker outline, text in a framed white comic caption box top-left. Default `POW! WHAT NOW?`, limit **20**.
- **Steps:** `extract_subject` → `halftone` mono on background (cell 0.02, paper [255, 215, 0], ink [225, 30, 60]) → `posterize` 6 + `ink_edges` on subject → `sticker_outline` [20, 20, 20] → `composite` → `draw_text` `$text` (`marquee`, top_left, `box: frame` with white fill, max_width_ratio 0.6)
- **File:** `backend/presets/pop_art_panel.json`


### Street graffiti

Five street-graffiti looks inspired by Indian hip-hop street posters (original artwork, no copied titles): the subject is cut out (`single_subject: true`) and stands in front of a wall painted with the user's text as graffiti plus street doodles (crown, arrows, stars, bolts). No spray-paint splatter in this set. All are `ar: non-square`, `text_input: yes` (limit **16**), no HD, seeded via `seed_default_presets()` / setup. Fonts are bundled OFL graffiti styles: `graffiti` (Sedgwick Ave Display), `wet_paint` (Rubik Wet Paint), `spray` (Rubik Spray Paint). Hollow outline lettering is built from existing steps: an empty layer (`draw_shape` with `clear: true` placed off-frame) gets the text with a stroke, a second gets the plain text, and `clip_to` with `invert: true` keeps only the ring.

#### `graffiti_drip_column` — Graffiti drip column

- **Idea:** Text runs up the left edge as a dripping neon-green `wet_paint` piece with a pink 3-D shadow (`angle` 90, `center_x` ≈ 0.11), on a darkened muted wall; white crown, arrow, stars and a pink bolt on the right. The text appears only in this title. Default `STAY REAL`.
- **File:** `backend/presets/graffiti_drip_column.json`

#### `graffiti_throwup_masthead` — Graffiti throw-up masthead

- **Idea:** A huge full-width white `spray` throw-up with a thick black outline and red shadow across the top (`center_y` 0.13, `max_width_ratio` 1.0), small `graffiti` tags of the text in the lower corners, a crown and dots, on a saturated posterised wall. Default `OUR BLOCK`.
- **File:** `backend/presets/graffiti_throwup_masthead.json`

#### `graffiti_sticker_slap` — Graffiti sticker slap

- **Idea:** The text on two tilted street stickers (`draw_text` `box: label`, rounded): white at (0.8, 0.42, −12°) and yellow at (0.22, 0.72, 9°), on a weathered wall (`paper_texture` stains + grain) with a white arrow, yellow crown and sparkles. Default `KEEP IT REAL`.
- **File:** `backend/presets/graffiti_sticker_slap.json`

#### `graffiti_outline_mural` — Graffiti outline mural

- **Idea:** Hollow pink outline letters (`graffiti`, font_size_ratio 0.3, −6°) painted across the upper wall on a dimmed wall, cyan crown and sparkles. Default `DREAM BIG`.
- **File:** `backend/presets/graffiti_outline_mural.json`

#### `graffiti_outline_tower` — Graffiti outline tower

- **Idea:** One giant white outline word in `poster` capitals (`uppercase: true`, font_size_ratio 0.24, `angle` −90) running up the right edge of a darkened wall, white crown and arrow. Default `HUSTLE`.
- **File:** `backend/presets/graffiti_outline_tower.json`


### Leonardo codex doodles

Five notebook-page looks inspired by Leonardo da Vinci's codices: rough mirror-written notes (Italian-flavoured filler words, no quotations) and hand-inked diagrams from `codex_doodle`, each on its own paper tone. All extract the subject (`single_subject: true`) so diagrams sit behind it, use `avoid_subject` to keep notes clear of the subject, are `ar: non-square`, `text_input: no`, no HD, and are seeded via `seed_default_presets()` / setup.

#### `codex_chalk_sepia` — Codex chalk sepia

- **Idea:** Whole photo turned warm sepia parchment; white-chalk aerial screw, pulley and two blocks of notes.
- **Steps:** `extract_subject` → `grayscale` + sepia `tone_curve` + `paper_texture` on background → `codex_doodle` (white chalk [248, 240, 222]) `notes` top-left, `aerial_screw` top-right, `pulley` bottom-left, `notes` left → sepia subject → `composite` → light `paper_texture` → brown `vignette`
- **File:** `backend/presets/codex_chalk_sepia.json`

#### `codex_blueprint` — Codex blueprint

- **Idea:** Subject in full colour over blue-grey prepared paper; white-chalk parachute and optics (eye + lens) studies, notes.
- **Steps:** `extract_subject` → `grayscale` + blue-grey duotone `tone_curve` + `paper_texture` [204, 212, 218] on background → `codex_doodle` (white chalk) `parachute`, `optics`, two `notes` → `composite`
- **File:** `backend/presets/codex_blueprint.json`

#### `vitruvian_study` — Vitruvian study

- **Idea:** Rose (red-chalk) paper background with a blue-black Vitruvian circle-and-square sized to the subject, a proportion scale and notes.
- **Steps:** `extract_subject` → `grayscale` + rose duotone `tone_curve` + `paper_texture` [232, 196, 180] on background → `codex_doodle` (ink [26, 34, 68]) `vitruvian` (`anchor: subject`, `subject_fit` 1.12, `max_size` 1.0), `proportion` right, `notes` top-left → `composite`
- **File:** `backend/presets/vitruvian_study.json`

#### `inventors_notebook` — Inventor's notebook

- **Idea:** The photo pasted onto a sage-green notebook page with sepia margin notes and gear, geometry and wing sketches. No cutout.
- **Steps:** light `paper_texture` → `place_on_canvas` (margins [0.06, 0.06, 0.42, 0.42] — a square photo gives a square page, [206, 212, 182]) → `paper_texture` → `codex_doodle` (sepia) `notes` + `gears` + `geometry` in the right margin, `notes` + `wing` along the bottom (explicit `x` / `y`)
- **File:** `backend/presets/inventors_notebook.json`

#### `da_vinci_wings` — Da Vinci wings

- **Idea:** Feathered flight-study wings drawn behind the subject at shoulder height (a mirrored pair), on a muted parchment background, with notes.
- **Steps:** `extract_subject` → `color` 0.25 + `paper_texture` on background → two `codex_doodle` `bird_wing` (`anchor: subject`, `subject_fit` 0.95, `max_size` 0.62, `subject_y` 0.24, `offset_x` ±0.47, second `flip: true`, feathers filled with `paper` [238, 224, 194]) → two `notes` → `composite`
- **File:** `backend/presets/da_vinci_wings.json`

## Built-in filters

| Filter | What it does | Common params |
|--------|----------------|---------------|
| `extract_subject` | rembg cutout (rembg's alpha, the source photo's colour — rembg darkens soft edge pixels) + blurred fill background. With `require_clear_subject: true`, an unreliable mask (tiny, or semi-transparent smear away from the body — e.g. dark backlit subjects) gives an empty subject and the untouched original as background; soft hair/fur next to the body is fine. With `single_subject: true`, only the main solid island(s) are kept — every island touching the bottom edge that is ≥ 25% of the largest (so two people side by side both stay), else just the largest — plus pieces within ~1.5% of the short side and soft edges within 3%, so a second salient object (wall frame, poster) stays in the background instead of being cut out | `on`, `as` (subject), `bg_as` (background), `require_clear_subject` (default `false`), `single_subject` (default `false`) |
| `brightness` | Brightness enhance | `on`, `amount` |
| `color` | Saturation enhance | `on`, `amount` |
| `contrast` | Contrast enhance | `on`, `amount` |
| `overlay` | Blend a solid tint | `on`, `rgb`/`color`, `alpha` |
| `grayscale` | Desaturate | `on` |
| `glow_border` | Soft halo under subject (fills expanded mask) | `on`, `rgb`/`color`, `width`, `blur` (px), or `width_ratio` / `blur_ratio` (fractions of the short side — prefer these) |
| `glow_line_border` | Outline **ring** only (subject body unchanged) | `on`, `color`/`rgb`, `width`, `blur` (px), or `width_ratio` / `blur_ratio` (fractions of the short side — prefer these) |
| `sticker_outline` | Solid round-cornered outline whose width scales with the image (blur + threshold dilation, flat cost at any width) | `on`, `color`/`rgb`, `width_ratio` (fraction of short side; default 0.008), `softness` (edge AA px) |
| `circle_backdrop` | One filled, semi-transparent disc (e.g. behind a cut-out); placement like `doodle` (`anchor: subject` + `around` centres on the subject's alpha bbox); only the disc's region is drawn (2× supersampled up to 4 MP) | `on`, `around`, `color`/`rgb`, `opacity` (0–1), `size` (diameter, fraction of short side), `anchor`, `x`/`y` (0–1), `offset_y` (fraction of short side, negative = up), `softness` (edge feather, fraction of short side), `subject_fit` (cap the diameter at this × the subject bbox's long side so small subjects aren't dwarfed). With `anchor: subject` and an empty `around` layer (no subject found) the step is a no-op; non-finite numbers raise `ValueError` |
| `composite` | Paste overlay on base | `base`, `overlay`, `as` |
| `blend` | Like `composite` with a blend mode: layer `overlay` on `base` in `normal` / `multiply` / `screen` / `darken` / `lighten`, times `opacity` | `base`, `overlay`, `as`, `mode`, `opacity` (0–1) |
| `text_pattern` | Fill a layer with the text repeated as `TEXT.TEXT.TEXT.` rows (a word wall); only the input's size is used. Rows cycle through `sizes` / `colors`, each row offset by `stagger`; `gap_ratio` packs rows by their ink height with an exact even gap (else `line_spacing` × size); `transparent: true` leaves only the letters (use with `clip_to`); `angle` tilts the wall | `on`, `as`, `text` (`$text`), `separator` (`.`), `color`/`rgb` or `colors`, `background`, `transparent`, `font_style` / `font_path`, `font_size_ratio` or `sizes` (fractions of the short side, ≤ 0.5), `line_spacing`, `gap_ratio` (≤ 0.2), `stagger`, `uppercase`, `angle` |
| `half_mask` | Keep only the `left` / `right` side of a layer (the rest goes transparent); the vertical split runs through the `around` layer's alpha — bounding-box middle (`split_at: center`) or alpha centroid (`mass`) — or the frame centre when `around` is missing/empty | `on`, `as`, `side`, `around`, `split_at`, `feather_ratio` (soft edge, fraction of the short side) |
| `draw_shape` | One basic shape (`circle` / `square` / `triangle` / `diamond` / `star` / `heart`) centred at `x`, `y` (fractions of width / height), `size` = bounding square as a fraction of the short side, `angle` (degrees); filled in `color` and/or outlined (`stroke_ratio`, `stroke_color`). `clear: true` starts from a transparent layer (a mask for `clip_to`). Only the shape's region is drawn (2× supersampled, box-filtered) | `on`, `as`, `shape`, `x`, `y`, `size` (≤ 3), `angle`, `color`/`rgb`, `opacity`, `fill`, `stroke_ratio` (≤ 0.1), `stroke_color`, `clear` |
| `clip_to` | Keep a layer only where the `around` layer is visible (alpha × `around` alpha, or its inverse with `invert`) — e.g. a photo through the letters of a transparent `text_pattern`, or a text wall inside a silhouette | `on`, `as`, `around`, `invert` |
| `place_on_canvas` | Put layer on a larger solid canvas | `on`, `scale` (e.g. `1.4`), `fill`/`color`, `layout` (`polaroid` or `center`), `as`, or `margins` ([left, top, right, bottom], fractions of the photo's short side — independent borders, overrides `scale` / `layout`, e.g. an Instax card) |
| `crop_aspect` | Centre-crop to an aspect `ratio` (width / height, or [w, h] such as [46, 62] Instax Mini, [1, 1], [99, 62] Wide), keeping as much as possible; `anchor` picks the kept part; `auto_orient` flips the ratio to match a clearly landscape / portrait photo (square photos keep it as given) | `on`, `ratio`, `anchor` (`center`/`top`/`bottom`/`left`/`right`), `auto_orient` |
| `upscale` | Pillow resize so the long side reaches `long_edge` (keeps aspect; never shrinks) | `on`, `long_edge`, `max_scale` (default 4), `resample` (`lanczos`/`bicubic`/`bilinear`) |
| `sharpen` | Unsharp mask | `on`, `radius`, `percent`, `threshold` |
| `denoise` | Median filter (noise / JPEG blocking) | `on`, `size` (odd ≥ 3) |
| `ai_upscale` | Local Real-ESRGAN 4× super-resolution, then Lanczos to target (keeps aspect + alpha; never shrinks; with `LIGHTWEIGHT=1` the model is skipped and it is a plain Lanczos `upscale` to the same target) | `on`, `long_edge` (default 1920), `max_scale` (4), `denoise` (0 keep grain – 1 smoothest; 0.5), `max_input_pixels` (1 000 000), `tile` (256) |
| `doodle` | One hand-drawn white (or tinted) doodle; sizes are fractions of the short side so it scales with resolution; seeded wobble is deterministic; draws only its own region (2× supersampled up to 4 MP regions, 1× above) |  `on`, `style` (`xo`/`rings`/`wiggles`/`stars`/`hearts`/`arrow`/`sun`/`cloud`/`zigzag`/`dots`/`flower`/`spiral`/`bolt`/`crown`; `count` = marks, rays or petals, `angle` rotates wiggles/zigzag/arrow), `anchor` (`top_right`/`top_left`/`bottom_left`/`bottom_right`/`top`/`bottom`/`left`/`right`/`center`/`subject`), `around` (layer whose alpha bbox centres `anchor: subject`), `x`/`y` (0–1, override anchor), `size`, `stroke`, `count` (1–12), `angle` (wiggles), `color`/`rgb` (`[r, g, b]`, or `color: "auto"` = dark ink when the region's mean luma > 150, else white), `avoid_subject` (with `around`: a corner/edge anchor the subject covers > 8% of moves to its first clear mirror — x-flip, y-flip, then both), `avoid_busy` (also skip mirrors whose background is cluttered — mean edge strength > 8 on a blurred ≤128 px copy, so fine texture doesn't count; works without `around`), `opacity`, `jitter`, `seed` |
| `doodle_frame` | Hand-drawn border just inside the edges (marker wobble); drawn into a 1-channel mask and painted onto one copy, so memory stays ≈ one image copy (2× supersampled up to 4 MP, 1× above) | `on`, `style` (`line`/`double`/`dashes`/`dots`/`zigzag`/`waves`/`corners`), `color`/`rgb` or `"auto"` (dark ink on light borders, white on dark), `inset`, `stroke` (fractions of the short side), `jitter`, `opacity`, `seed` |
| `codex_doodle` | One Leonardo-notebook element in thin ink (sepia by default), seeded and drawn only in its region (2× supersampled up to 4 MP). `kind`: `notes` (rough mirror-written handwriting, `lines` lines, `size` wide), `geometry`, `vitruvian`, `gears`, `wing`, `vortex`, `proportion`, `aerial_screw`, `parachute`, `pulley`, `optics`, `bird_wing` (shingled feathers; `paper` fills them), `bat_wing`. Placement like `doodle` (`anchor` / `x`, `y` / `avoid_subject`); with `anchor: subject`, `subject_fit` sizes from the subject bbox, `max_size` caps it, `subject_y` (0 top…1 bottom) sets the height within the subject; `offset_x` / `offset_y` shift by a fraction of the size; `flip` mirrors (wing pairs). Each element is capped at 1.2 × the short side (huge ones draw at reduced scale, buffer ≤ 16 MP) and records its box in `image.info["codex_boxes"]`, so a later `avoid_subject` element avoids earlier ones too (mirror corners, then edge centres). Unknown `font_style` raises | `on`, `around`, `kind`, `color`/`rgb`, `anchor`, `x`, `y`, `size`, `stroke`, `angle`, `opacity`, `lines`, `mirror`, `font_style` (`scribble`), `labels`, `subject_fit`, `max_size`, `subject_y`, `paper`, `flip`, `offset_x`, `offset_y`, `jitter`, `seed`, `avoid_subject` |
| `posterize` | Flatten each RGB channel to N levels (comic colour bands); optional median smooth first | `on`, `levels` (2–32), `smooth` (0 or odd ≥ 3) |
| `ink_edges` | Comic ink outlines via difference of Gaussians on luminance; scales with resolution; RGBA is flattened on white first so hidden pixels don't create edges | `on`, `detail` (blur, fraction of short side), `threshold` (lower = more lines), `thickness` (fraction of short side), `color`/`rgb`, `opacity` |
| `halftone` | Printed dot screen: `mono` (one ink at `angle`) or `cmyk` (process inks at 15/75/0/45° with grey-component replacement); dot area ≈ ink coverage; processed at ≤ 2400 px long edge then resized back; pitch auto-enlarges if a screen would need > 160k dots; transparent pixels print as paper | `on`, `mode`, `cell` (dot pitch, 0.002–0.1 of short side), `angle`, `paper`, `ink`, `mix` (blend back over original), `gcr` (0–1, share of grey on black plate) |
| `paper_texture` | Age onto paper: multiply tint, seeded fine grain (scales with resolution), low-frequency stains (grid follows aspect ratio), fade toward paper; tone steps run as point tables, grain is applied tile by tile | `on`, `color`/`rgb`, `tint`, `grain`, `stains`, `fade` (0–1 each), `seed` (int, or `"auto"` = derived from the photo so each picture gets its own layout) |
| `color_grade` | Photographic grade in one pass: white balance, exposure, contrast S-curve (or flatten), matte black lift, soft highlight shoulder (per-channel point tables, flat cost); luminance-preserving split toning, saturation and vibrance (numpy in ≤ 1 MP strips); out-of-gamut pixels are pulled back along their own luma so highlights don't clip or shift hue; neutral params are an exact no-op | `on`, `temperature` (−1 cool…1 warm), `tint` (−1 green…1 magenta), `exposure` (stops), `contrast` (−1…1), `pivot`, `black_lift` (0–0.3), `white_rolloff` (0–1), `shadows` / `highlights` ([r,g,b]), `split` (0–1), `balance` (−1…1 crossover), `saturation`, `vibrance` (0–1) |
| `tone_curve` | Photoshop / Lightroom point curves: `[[in, out], …]` on 0–255 joined by a monotone cubic spline (no overshoot); `master` on all channels first, then `red` / `green` / `blue`; folded into one point table, flat cost; omitted curves are identity | `on`, `master`, `red`, `green`, `blue` |
| `shadows_highlights` | Local Shadows / Highlights: a gamma bend weighted by a tone mask (pixel luma mixed with an edge-aware fast guided filter of it, fitted at ≤ 1024 px and applied at full resolution, so hard edges get no halo), so dark regions open up and bright ones recover as areas; black and white stay fixed, colour scales with brightness (hue kept, gamut-fitted); numpy in ≤ 1 MP strips | `on`, `shadows` (−1 deepen…1 open), `highlights` (−1 recover…1 brighten), `radius_ratio` (mask blur, fraction of short side; 0.02), `local` (0–1 share of the blurred mask; 0.6) |
| `motion_blur` | Directional shutter blur: averaged shifted copies along `angle` with edge-extended borders; RGBA uses premultiplied alpha so a cut-out streaks into transparency; worked at ≤ 1600 px long edge (≤ 1024 with `LIGHTWEIGHT=1`) and scaled back (flat cost). `exclude` names a layer (e.g. `subject`, RGB layers only) whose alpha, grown by `exclude_grow`, gets zero weight, so the subject-coloured hole fill isn't smeared past the outline | `on`, `length_ratio` (streak, fraction of short side, ≤ 0.5), `angle` (motion direction, 0 → right, 90 → up), `trail` (0 both ways / pan … 1 behind only), `fade` (0–1 thinner tail), `freeze` (0–1 sharp copy on top, rear-curtain flash), `exclude`, `exclude_grow` (fraction of short side; 0.004) |
| `radial_blur` | Circular blur around one centre: `spin` streaks along circles (rotational), `zoom` along rays; blur grows with distance so the centre stays sharp. Centre = `x` / `y` (0–1, both or neither) if set, else the alpha centroid of `exclude` (e.g. `subject`, so the swirl sits behind it), else frame centre; `offset_y` nudges it. `exclude` also gives the hole zero weight (grown by `exclude_grow`). Edge-extended, worked at ≤ 1600 px long edge (≤ 1024 with `LIGHTWEIGHT=1`), flat cost; RGBA blurs with alpha as weight | `on`, `mode` (`spin`/`zoom`), `amount` (spin: total sweep in degrees, capped at 45; zoom: scale spread, capped at 0.5, e.g. 0.12 — caps bound memory), `x`, `y`, `offset_y`, `exclude`, `exclude_grow` (0.004) |
| `warp` | Displace (re-map) pixels around one centre — sharp distortion, not blur. `twirl` rotates by `amount` **degrees** at the centre easing to 0 at `radius` × farthest corner; `ripple` = concentric rings (radial shift `amount` × sin(2πr / `wavelength`)); `wave` = squiggly sin wobble on both axes, rotated by `angle`; `liquid` = smooth seeded noise flow (feature size `wavelength`). `falloff` fades the shift with distance; `shade` lights ripple / liquid slopes (water sheen). Centre like `radial_blur` (`x` / `y` both or neither, else `exclude` alpha centroid, else frame centre; `offset_y`). With `exclude` (RGB or RGBA layers), the hole (grown by `exclude_grow`) is first refilled from its surroundings, and any sample landing behind the subject is reflected outward past the subject's outline along its ray from the centre — so subject colours aren't dragged out and no smooth refill patch shows beside the subject. Row strips (smaller with `LIGHTWEIGHT=1`), mirrored at frame edges (no border streaks); liquid noise grid is capped, so a tiny `wavelength` can't blow up memory | `on`, `mode` (`twirl`/`ripple`/`wave`/`liquid`), `amount` (twirl: degrees; others: fraction of short side), `wavelength` (fraction of short side; 0.06), `radius` (twirl, 0–1 of farthest corner), `falloff` (fraction of short side, 0 off), `shade` (0–1), `angle` (wave, degrees), `seed` (liquid), `x`, `y`, `offset_y`, `exclude`, `exclude_grow` (0.006) |
| `vignette` | Edge falloff toward black (or `color`); mask built at ≤ 256 px and scaled up, so it is resolution-independent | `on`, `amount` (0–1), `midpoint` (0–1), `feather`, `roundness` (0 frame-shaped…1 circle), `color`/`rgb` |
| `bloom` | Diffusion glow: highlights above `threshold` are blurred and screened back (Pro-Mist / dreamy); worked at ≤ 1024 px, so cost is flat | `on`, `threshold` (0–1), `radius_ratio` (fraction of short side), `amount` (0–1), `color`/`rgb` (glow tint) |
| `halation` | Film halation: a red-orange halo around (not on) bright highlights; worked at ≤ 1024 px | `on`, `threshold`, `radius_ratio`, `amount`, `color`/`rgb` (default [255, 70, 30]) |
| `light_leak` | Analog light leak / "sun puddle" screened in from an edge or corner, with a hot `core` and a `streak` stretched along the edge; built at ≤ 256 px | `on`, `anchor` (`top_right`/`top_left`/`bottom_right`/`bottom_left`/`left`/`right`/`top`/`bottom`), `size` (reach, fraction of diagonal), `amount`, `color`/`rgb`, `core`, `streak` (0–1) |
| `film_dust` | Seeded scanned-film dust: white (and some dark) specks, curly hairs, faint vertical scratches; sizes are fractions of the short side | `on`, `amount` (0–1 speck count), `hairs`, `scratches`, `opacity`, `seed` |
| `chromatic_aberration` | Radial lens fringing: red scaled out, green half, blue fixed, so colour edges split more toward the corners (no border) | `on`, `amount` (fraction of size, ≤ 0.05) |
| `blur` | Gaussian blur by `radius_ratio` × short side; large radii run on a shrunken copy (flat cost). RGBA blurs with premultiplied alpha (no dark edges toward transparency). `exclude` names a layer (e.g. `subject`) whose alpha, grown by `exclude_grow`, gets zero weight, so the blurred background fills the cut-out hole from its surroundings | `on`, `radius_ratio`, `exclude` (layer name), `exclude_grow` (fraction of short side; default 0.004) |
| `selective_color` | Push one colour family (HSV hue band) and optionally mute the rest; near-greys get little weight; numpy in ≤ 1 MP strips | `on`, `hue` (degrees, name `red`/`orange`/`yellow`/`green`/`cyan`/`teal`/`blue`/`purple`/`magenta`/`pink`, or [r,g,b]), `width` (band half-width, degrees), `saturation` (in-band ×), `lightness` (in-band lift 0–1), `others` (out-of-band saturation ×; 0 = grey), `pull` (0–1, rotate in-band hues toward the target) |
| `draw_text` | Paint a string onto a layer | `on`, `text` (`$text` / `$datetime` / `$date` / `$time` — stamps use the photo's EXIF capture time, else now), `font_size`, `color`/`rgb`, `align` (`center`/`top`/`bottom`/`top_left`/`top_right`/`bottom_left`/`bottom_right`), `font_style` (`sans`/`flow`/`stamp` — bold mono date imprint; poster styles `poster` (Impact → bundled Anton), `brush` (Brush Script → bundled Yellowtail), `slab`, `signature`, `scribble` (bundled Nanum Pen Script, loose felt-pen handwriting), graffiti styles `graffiti` (Sedgwick Ave Display) / `wet_paint` (Rubik Wet Paint, dripping) / `spray` (Rubik Spray Paint), `bold_display`, `stencil`, caps-only `neon_lines` / `marquee`), `font_path` (optional TTF/OTF/TTC; overrides `font_style`), `margin`, `x`, `y`, `stroke_width` (px), or `font_size_ratio` / `margin_ratio` / `stroke_ratio` (fractions of the short side — prefer these); too-wide text shrinks to fit. Poster extras: `scale_y` (vertical stretch), `angle` (tilt, degrees), `glow_ratio` (≤ 0.05) / `glow_color` (neon halo, fixed brightness), `box` (`frame`/`double`/`corners`/`label`) with `box_color`, `box_fill` ([r,g,b(,a)]), `box_ratio`, `box_pad_ratio`, `box_radius_ratio` — the box stretches, tilts and glows with the text. Placement extras: `center_x` / `center_y` (fractions of width / height, together) centre the finished block on a point — e.g. inside a `draw_shape` badge or along an edge with `angle: 90`; `max_width_ratio` (0.05–1, default 0.9 of the width) caps the text width before it shrinks; `uppercase: true` renders the text in capitals |

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
      "bg_as": "background",
      "single_subject": true
    },
    { "filter": "grayscale", "on": "background" },
    {
      "filter": "glow_line_border",
      "on": "subject",
      "color": [0, 255, 200],
      "width_ratio": 0.007,
      "blur_ratio": 0.0028
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
  "font_size_ratio": 0.045,
  "color": [255, 255, 255],
  "align": "bottom",
  "stroke_ratio": 0.002
}
```

Rules of thumb:

1. Always end with a `composite` (or other step) that writes `as: "image"`.
2. Apply background edits with `"on": "background"`; subject edits with `"on": "subject"`.
3. For colour looks, prefer `color_grade` (+ `vignette`, grain via `paper_texture` with tint/stains/fade 0) over flat `overlay` tints, which wash out blacks. Prefer `glow_line_border` for a glow ring and `sticker_outline` for a solid outline. **Size everything as a fraction of the short side** (`width_ratio`, `blur_ratio`, `font_size_ratio`, `margin_ratio`, `stroke_ratio`, doodle `size`/`stroke`) so the look is identical from a 720 px phone shot to a 61 MP DSLR file; px params only stay for backward compatibility. To convert a value tuned on a 720 px sample: ratio = px / 720 (for a step after `place_on_canvas`, divide by the canvas short side instead, e.g. 1008 at 1.4×).
4. Set `"ar": "square"` when the recipe only works on square images; `"ar": "non-square"` (default) works on any aspect ratio. A square-only preset applied to a non-square image raises `PresetAspectRatioError`.
5. Set `"text_input": "yes"` only when a step uses `$text`. Then `text_character_limit` must be 1–200. `"no"` (default) ignores submitted text.
6. Doodles: apply `doodle` steps `"on": "background"` before the final `composite` so the subject covers them; use `"anchor": "subject", "around": "subject"` to centre rings behind the cutout. Prefer `"color": "auto"` over fixed white, add `"around": "subject", "avoid_subject": true` to corner doodles so they aren't hidden (plus `"avoid_busy": true` on dense ones like `xo`), and set `"single_subject": true` on `extract_subject` for one-subject looks.
7. Conditional steps: any step may add `"requires_layer": "subject"` (plus optional `"min_coverage": 0.04`, the layer's mean alpha as a 0–1 share of the frame). The runner skips that step when the layer is missing, empty, or smaller than that, so a background-darkening step does not black out a photo where `extract_subject` found nothing meaningful. This is generic (the runner never branches on filter type).
8. HD pre-pass: put `{ "filter": "ai_upscale", "on": "image", "long_edge": 1920 }` as step 0 so later steps work at HD size — ratio params (rule 3) need no change; only remaining px params (`font_size`, `margin`, `stroke_width`, glow `width`/`blur`) need scaling by about the upscale factor.

## Database metadata

`backend/database/presets.local.db` is **local and gitignored**: `scripts/setup.sh` and `scripts/run.sh` call `backend/database/prepare_db.py`, which creates/migrates it and runs `seed_default_presets()` (adds missing shipped presets, syncs their metadata, never resets `popular` counts). The seed list in `db_ops.py` is the source of truth for shipped presets. `presets.db` stays committed but **frozen** (legacy: never written, never change or delete it) so clones from before this change can `git pull` cleanly; its rows and counts are copied into `presets.local.db` the first time that file is created.

Table `presets` in `backend/database/presets.local.db`:

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
   - adds an entry to `seed_default_presets()` in `backend/database/db_ops.py` (name, path, keywords, `ar`, text fields) and runs `python backend/database/prepare_db.py`, which inserts it (plus a `popular` row at `used_count` 0) into the local DB
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
