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
| `POST /api/apply-preset` | HTTP: DB `preset_name` + image upload + optional `text` → JPEG (JPEG upload) or PNG |

## Run a preset

```bash
source backend/.venv/bin/activate
python backend/helpers/apply_preset.py path/to/photo.jpg -p PRESET_NAME -o out.png
```

`PRESET_NAME` is a file under `backend/presets/` (with or without `.json`), or a full path to a JSON file.

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

Ten poster looks: subject cut out (`single_subject: true`) → one colour family pushed on the background with `selective_color` → a large `$text` title painted on the **background** → subject composited back on top, so it covers part of the title. All are `ar: non-square`, `text_input: yes`, `default_text: "TITLE"`, `text_character_limit: 16`, no HD pass, seeded via `seed_default_presets()` / setup. Titles are top-aligned (`margin_ratio` 0.03–0.05), stretched tall with `scale_y`, and auto-fit to 90% of the width. Text keeps the user's casing, except `neon_lines` (Monoton) and `marquee` (Bungee), whose fonts only have capitals.

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
| `composite` | Paste overlay on base | `base`, `overlay`, `as` |
| `place_on_canvas` | Put layer on a larger solid canvas | `on`, `scale` (e.g. `1.4`), `fill`/`color`, `layout` (`polaroid` or `center`), `as` |
| `upscale` | Pillow resize so the long side reaches `long_edge` (keeps aspect; never shrinks) | `on`, `long_edge`, `max_scale` (default 4), `resample` (`lanczos`/`bicubic`/`bilinear`) |
| `sharpen` | Unsharp mask | `on`, `radius`, `percent`, `threshold` |
| `denoise` | Median filter (noise / JPEG blocking) | `on`, `size` (odd ≥ 3) |
| `ai_upscale` | Local Real-ESRGAN 4× super-resolution, then Lanczos to target (keeps aspect + alpha; never shrinks; with `LIGHTWEIGHT=1` the model is skipped and it is a plain Lanczos `upscale` to the same target) | `on`, `long_edge` (default 1920), `max_scale` (4), `denoise` (0 keep grain – 1 smoothest; 0.5), `max_input_pixels` (1 000 000), `tile` (256) |
| `doodle` | One hand-drawn white (or tinted) doodle; sizes are fractions of the short side so it scales with resolution; seeded wobble is deterministic; draws only its own region (2× supersampled up to 4 MP regions, 1× above) |  `on`, `style` (`xo`/`rings`/`wiggles`/`stars`/`hearts`/`arrow`/`sun`/`cloud`/`zigzag`/`dots`/`flower`/`spiral`/`bolt`; `count` = marks, rays or petals, `angle` rotates wiggles/zigzag/arrow), `anchor` (`top_right`/`top_left`/`bottom_left`/`bottom_right`/`top`/`bottom`/`left`/`right`/`center`/`subject`), `around` (layer whose alpha bbox centres `anchor: subject`), `x`/`y` (0–1, override anchor), `size`, `stroke`, `count` (1–12), `angle` (wiggles), `color`/`rgb` (`[r, g, b]`, or `color: "auto"` = dark ink when the region's mean luma > 150, else white), `avoid_subject` (with `around`: a corner/edge anchor the subject covers > 8% of moves to its first clear mirror — x-flip, y-flip, then both), `avoid_busy` (also skip mirrors whose background is cluttered — mean edge strength > 8 on a blurred ≤128 px copy, so fine texture doesn't count; works without `around`), `opacity`, `jitter`, `seed` |
| `doodle_frame` | Hand-drawn border just inside the edges (marker wobble); drawn into a 1-channel mask and painted onto one copy, so memory stays ≈ one image copy (2× supersampled up to 4 MP, 1× above) | `on`, `style` (`line`/`double`/`dashes`/`dots`/`zigzag`/`waves`/`corners`), `color`/`rgb` or `"auto"` (dark ink on light borders, white on dark), `inset`, `stroke` (fractions of the short side), `jitter`, `opacity`, `seed` |
| `posterize` | Flatten each RGB channel to N levels (comic colour bands); optional median smooth first | `on`, `levels` (2–32), `smooth` (0 or odd ≥ 3) |
| `ink_edges` | Comic ink outlines via difference of Gaussians on luminance; scales with resolution; RGBA is flattened on white first so hidden pixels don't create edges | `on`, `detail` (blur, fraction of short side), `threshold` (lower = more lines), `thickness` (fraction of short side), `color`/`rgb`, `opacity` |
| `halftone` | Printed dot screen: `mono` (one ink at `angle`) or `cmyk` (process inks at 15/75/0/45° with grey-component replacement); dot area ≈ ink coverage; processed at ≤ 2400 px long edge then resized back; pitch auto-enlarges if a screen would need > 160k dots; transparent pixels print as paper | `on`, `mode`, `cell` (dot pitch, 0.002–0.1 of short side), `angle`, `paper`, `ink`, `mix` (blend back over original), `gcr` (0–1, share of grey on black plate) |
| `paper_texture` | Age onto paper: multiply tint, seeded fine grain (scales with resolution), low-frequency stains (grid follows aspect ratio), fade toward paper; tone steps run as point tables, grain is applied tile by tile | `on`, `color`/`rgb`, `tint`, `grain`, `stains`, `fade` (0–1 each), `seed` |
| `color_grade` | Photographic grade in one pass: white balance, exposure, contrast S-curve (or flatten), matte black lift, soft highlight shoulder (per-channel point tables, flat cost); luminance-preserving split toning, saturation and vibrance (numpy in ≤ 4 MP strips); out-of-gamut pixels are pulled back along their own luma so highlights don't clip or shift hue; neutral params are an exact no-op | `on`, `temperature` (−1 cool…1 warm), `tint` (−1 green…1 magenta), `exposure` (stops), `contrast` (−1…1), `pivot`, `black_lift` (0–0.3), `white_rolloff` (0–1), `shadows` / `highlights` ([r,g,b]), `split` (0–1), `balance` (−1…1 crossover), `saturation`, `vibrance` (0–1) |
| `vignette` | Edge falloff toward black (or `color`); mask built at ≤ 256 px and scaled up, so it is resolution-independent | `on`, `amount` (0–1), `midpoint` (0–1), `feather`, `roundness` (0 frame-shaped…1 circle), `color`/`rgb` |
| `bloom` | Diffusion glow: highlights above `threshold` are blurred and screened back (Pro-Mist / dreamy); worked at ≤ 1024 px, so cost is flat | `on`, `threshold` (0–1), `radius_ratio` (fraction of short side), `amount` (0–1), `color`/`rgb` (glow tint) |
| `halation` | Film halation: a red-orange halo around (not on) bright highlights; worked at ≤ 1024 px | `on`, `threshold`, `radius_ratio`, `amount`, `color`/`rgb` (default [255, 70, 30]) |
| `light_leak` | Analog light leak / "sun puddle" screened in from an edge or corner, with a hot `core` and a `streak` stretched along the edge; built at ≤ 256 px | `on`, `anchor` (`top_right`/`top_left`/`bottom_right`/`bottom_left`/`left`/`right`/`top`/`bottom`), `size` (reach, fraction of diagonal), `amount`, `color`/`rgb`, `core`, `streak` (0–1) |
| `film_dust` | Seeded scanned-film dust: white (and some dark) specks, curly hairs, faint vertical scratches; sizes are fractions of the short side | `on`, `amount` (0–1 speck count), `hairs`, `scratches`, `opacity`, `seed` |
| `chromatic_aberration` | Radial lens fringing: red scaled out, green half, blue fixed, so colour edges split more toward the corners (no border) | `on`, `amount` (fraction of size, ≤ 0.05) |
| `blur` | Gaussian blur by `radius_ratio` × short side; large radii run on a shrunken copy (flat cost). RGBA blurs with premultiplied alpha (no dark edges toward transparency). `exclude` names a layer (e.g. `subject`) whose alpha, grown by `exclude_grow`, gets zero weight, so the blurred background fills the cut-out hole from its surroundings | `on`, `radius_ratio`, `exclude` (layer name), `exclude_grow` (fraction of short side; default 0.004) |
| `selective_color` | Push one colour family (HSV hue band) and optionally mute the rest; near-greys get little weight; numpy in ≤ 4 MP strips | `on`, `hue` (degrees, name `red`/`orange`/`yellow`/`green`/`cyan`/`teal`/`blue`/`purple`/`magenta`/`pink`, or [r,g,b]), `width` (band half-width, degrees), `saturation` (in-band ×), `lightness` (in-band lift 0–1), `others` (out-of-band saturation ×; 0 = grey), `pull` (0–1, rotate in-band hues toward the target) |
| `draw_text` | Paint a string onto a layer | `on`, `text` (`$text` / `$datetime` / `$date` / `$time` — stamps use the photo's EXIF capture time, else now), `font_size`, `color`/`rgb`, `align` (`center`/`top`/`bottom`/`top_left`/`top_right`/`bottom_left`/`bottom_right`), `font_style` (`sans`/`flow`/`stamp` — bold mono date imprint; poster styles `poster` (Impact → bundled Anton), `brush` (Brush Script → bundled Yellowtail), `slab`, `signature`, `bold_display`, `stencil`, caps-only `neon_lines` / `marquee`), `font_path` (optional TTF/OTF/TTC; overrides `font_style`), `margin`, `x`, `y`, `stroke_width` (px), or `font_size_ratio` / `margin_ratio` / `stroke_ratio` (fractions of the short side — prefer these); too-wide text shrinks to fit. Poster extras: `scale_y` (vertical stretch), `angle` (tilt, degrees), `glow_ratio` (≤ 0.05) / `glow_color` (neon halo, fixed brightness), `box` (`frame`/`double`/`corners`/`label`) with `box_color`, `box_fill` ([r,g,b(,a)]), `box_ratio`, `box_pad_ratio`, `box_radius_ratio` — the box stretches, tilts and glows with the text |

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
7. HD pre-pass: put `{ "filter": "ai_upscale", "on": "image", "long_edge": 1920 }` as step 0 so later steps work at HD size — ratio params (rule 3) need no change; only remaining px params (`font_size`, `margin`, `stroke_width`, glow `width`/`blur`) need scaling by about the upscale factor.

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
