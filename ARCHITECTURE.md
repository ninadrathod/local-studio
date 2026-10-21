# ARCHITECTURE.md — The Local Studio

Detailed architecture for the preset-based local image editor.

## Goals

- Let the user browse shipped presets via static gallery previews.
- Accept a user-uploaded image in the browser.
- Validate that the input is an image (client + server).
- Apply a DB-named JSON preset on the **server** (not in the browser canvas).
- Return binary image data and display it on the frontend.
- Stay modular and easy to extend with more edit endpoints.

## System overview

```
┌──────────────────────────────────────────────────────────────┐
│  Browser                                                     │
│  index.html + script.js                                      │
│    ├─ left: search + square switch + popular + preset gallery │
│    │         (GET /api/presets/search filters previews)      │
│    ├─ right: upload (after preset) + optional text + result  │
│    ├─ js/image.js   → validate MIME / extension, object URLs │
│    └─ js/api.js     → searchPresets + applyPreset + recordPresetUse   │
└────────────────────────────┬─────────────────────────────────┘
                             │ multipart: preset_name + file
                             │            (+ optional text)
                             ▼
┌──────────────────────────────────────────────────────────────┐
│  Local FastAPI (uvicorn) on port 8000                        │
│    routes/preset.py → validate upload, orchestrate           │
│    routes/search.py → name/keyword substring search          │
│    routes/popular.py → increment/list download counts        │
│    services/preset.py → DB name → JSON path → apply_preset   │
│    services/preset_search.py → DB name + keyword match       │
│    services/preset_popular.py → increment popular.used_count │
│    services/image_io.py → decode bytes ↔ Pillow / JPEG·PNG   │
│    helpers/apply_preset.py + filters.py → filter pipeline    │
└──────────────────────────────────────────────────────────────┘
```

## Frontend

### Entry points

- `index.html` — full-width two-column UI (Tailwind via CDN, Pop Poster theme in `css/styles.css` — Lilita One brand / Fredoka+Nunito UI, coral CTA, lemon header):
  - **Left (~65%):** search input, **Input square?** yes/no switch, **Popular** mode (off by default; unclick restores newest-first), refresh control beside search, and preset grid (newest first; post-edit preview + name; hover/focus — or press-and-hold on touch screens — reveals pre-edit original); search reloads the grid from DB name/keyword matches; **No** hides `ar=square` presets.
  - **Right (~35%):** file upload / original preview (enabled after a preset is selected), optional preset text field, then **Generate edit** / **Download**, then edited result.
- `script.js` — wires gallery load (newest first), debounced search (filters gallery), selection, upload unlock, optional text constraints, file pick/drag-drop, generate button, download use-count ping, popular-sort mode (unclick restores newest-first), search-row gallery refresh.
- `js/image.js` — `isImageFile`, object URL create/revoke.
- `js/api.js` — `searchPresets(baseUrl, query)` → match list; `listPopularPresets(baseUrl)` → popular rows; `applyPreset(baseUrl, presetName, file, text?)` → `Blob`; `recordPresetUse(baseUrl, presetName)` → `{ preset_id, used_count }` (also retains `blurImage` for `/api/blur`).

### UX flow

1. Gallery loads from `previews/presets.json` (newest entries first) and renders post-edit thumbnails with pre-edit originals stacked underneath (entries must use a valid `preset_name`, `ar` of `square` or `non-square`, `text_input` of `yes` or `no`, `default_text`, `text_character_limit`, and relative paths under `previews/pre-edit/` and `previews/post-edit/`). Hover or keyboard focus reveals the original. Touch screens have no hover, so `bindTouchCompare` (`script.js`, pointer events delegated on the grid) adds `.preset-card--peek` after a 180 ms touch/pen hold and removes it on release; a hold doesn't select the card (the trailing click is swallowed), a quick tap still selects, and moving > 10 px or `pointercancel` (gallery scroll) cancels. The long-press image callout / context menu is suppressed on cards, and a "Hold to compare" hint shows next to the Presets heading only under `@media (hover: none)`.
2. User can set **Input square?** to **Yes** (show all presets) or **No** (show only `ar=non-square` presets). **Popular** (off by default) is a mode only — it does not reload the gallery. The refresh button beside the search box fetches `GET /api/presets/popular` and reorders visible cards by `used_count` descending. Unclicking **Popular** restores newest-first order. Download increments the table immediately but does not reorder the grid.
3. User clicks a preset card to select it, **or** types in the left-column search box (debounced) to query DB `preset_name` + keywords via `GET /api/presets/search?q=…` — the gallery reloads to matching presets only (newest `preset_id` first; cleared query restores the AR-filtered newest-first gallery).
4. Selecting a preset unlocks the upload form. If `text_input` is `yes`, a text field appears prefilled with `default_text` and capped at `text_character_limit`.
5. User selects or drops a file; client rejects non-images and shows an inline error.
6. Original preview uses a local object URL.
7. When **both** preset and file are set, **Generate edit** enables.
8. On generate, the file + preset name (+ `text` when required) are posted to the API; a loading state covers the result panel. Changing preset/file while a request is in flight discards the stale response. A `ar=square` preset on a non-square image is rejected (client + HTTP **400**). Oversized preset text is rejected (HTTP **400**).
9. Response blob is shown via another object URL; download link reuses that URL. Clicking **Download** also `POST`s form field `preset_name` to `/api/presets/use` to increment `popular.used_count` immediately (best-effort; a failed ping does not block the file download). The gallery is not reordered until the search-row refresh is clicked with **Popular** on.
10. Refresh clears all in-memory state (no persistence of upload or result).

### Config

- API base URL is derived in `script.js` from the page host (`127.0.0.1:8000` when the UI is on `localhost`, otherwise same hostname on port 8000).

### Preset preview assets

- `previews/pre-edit/` — open-licensed source photo per shipped DB preset (see `previews/CREDITS.md`).
- `previews/post-edit/` — same photo after that preset is applied.
- `previews/presets.json` — array of `{ preset_name, ar, text_input, default_text, text_character_limit, pre_edit_image, post_edit_image }` (repo-relative paths). Newest gallery entries first (matches `list_presets`). Consumed by the index gallery. `ar` is `square` or `non-square`. `text_input` is `yes` or `no`.
- `previews/_candidates/` — gitignored scratch for the create-preset skill. Comparison `index.html` pages (POC edits, font samples, gallery before/after) are generated by `.cursor/skills/create-preset/scripts/render_candidates.py`, which calls `apply_preset.apply_preset_file` and `filters.draw_text`. Not served by the studio UI.

### Marketing page

- `docs/index.html` is a lightweight advertise-style page (flow, CTAs), published via GitHub Pages from `/docs`. It points users to **fork the GitHub repo** and run locally — there is no hosted live app.

## Backend

### Stack

- **Python 3.12**
- **FastAPI** — HTTP API
- **Pillow** — image decode (EXIF orientation, ICC → sRGB via `ImageCms`) / Gaussian blur / JPEG·PNG encode
- **NumPy** — array maths in the preset filters (`color_grade`, `light_leak`, `blur`, `halftone`, …); the API runs presets in-process, so it is a core dependency
- **uvicorn** — ASGI server
- **python-multipart** — file uploads

### Package layout

```
backend/
  requirements.txt
  helpers/
    requirements.txt     # rembg[cpu] + onnx + certifi — installed by setup.sh
    download_model.py    # warm-cache u2net during setup (~/.rembg)
    extract_subject.py   # CLI: image in → subject PNG (transparent bg)
    upscale_model.py     # Real-ESRGAN weights → local ONNX + tiled 4× inference
    filters.py           # Pillow + rembg + upscale filter ops for presets
    apply_preset.py      # CLI: apply JSON preset steps to an image
  presets/
    bw_bg_glowing_subject.json
    polaroid_memory.json
    warm_faded_print.json
    full_hd.json
    4k_crisp.json
  database/
    schema.sql           # presets + popular tables
    init_db.py           # create presets.local.db (first time: copy legacy presets.db)
    prepare_db.py        # init + migrate + seed (run by setup.sh and run.sh)
    db_ops.py            # CRUD for preset metadata + download counts
    presets.local.db     # live SQLite file (local, gitignored; created by prepare_db.py)
    presets.db           # legacy committed copy, frozen (seed source for old clones)
  app/
    main.py              # FastAPI app, CORS, /health, router mount
    routes/
      blur.py            # POST /api/blur
      preset.py          # POST /api/apply-preset
      search.py          # GET /api/presets/search
      popular.py         # POST /api/presets/use, GET /api/presets/popular
    services/
      blur.py            # is_allowed_image, apply_blur
      image_io.py        # load_image, save_png_bytes, upload/dimension caps
      preset.py          # resolve DB preset name → JSON (sandboxed); apply_named_preset
      preset_search.py   # name/keyword substring search over presets table
      preset_popular.py  # increment/list popular.used_count

test-suite/              # pytest unit tests for services only (not routes/HTTP)
  conftest.py            # adds backend/ to sys.path
  requirements.txt       # pytest
  test_blur.py
  test_image_io.py
  test_preset.py
  test_preset_search.py
  test_preset_popular.py
  test_database.py
```
### API contracts

| Method | Path | Request | Response |
|--------|------|---------|----------|
| GET | `/health` | — | `{ "status": "ok" }` |
| GET | `/api/presets/search` | query `q` (name/keyword substring, max 64) | JSON `[{ "preset_name", "keywords", "ar", "text_input", "default_text", "text_character_limit" }, …]` newest `preset_id` first |
| GET | `/api/presets/popular` | — | JSON `[{ "preset_id", "preset_name", "used_count" }, …]` sorted by `used_count` descending |
| POST | `/api/presets/use` | `application/x-www-form-urlencoded` field `preset_name` (max 64) | JSON `{ "preset_id", "used_count" }` |
| POST | `/api/blur` | `multipart/form-data` field `file` | `image/jpeg` for a JPEG upload, else `image/png` |
| POST | `/api/apply-preset` | `multipart/form-data` fields `preset_name`, `file`, optional `text` (max 200) | `image/jpeg` for a JPEG upload with an opaque result, else `image/png` |

Error responses use FastAPI `HTTPException` with JSON `detail` (e.g. non-image, empty file, unknown preset, decode failure, square-only preset on a non-square image). Oversized uploads/images return **413**. Apply-preset returns **503** when the concurrency gate is full. `POST /api/presets/use` returns **404** for an unknown `preset_name`.

Upload guards (`services/image_io.py`): max **100 MiB** body (`MAX_UPLOAD_BYTES`, full-quality DSLR JPEG/TIFF); images over the working size (max side **12000** px / **64M** pixels — full-frame DSLR files up to 61 MP stay native) are **downscaled to fit**; with `LIGHTWEIGHT=1` (env, set in the gitignored `.env` that `run.sh` exports; read once at import) the working cap drops to **2M pixels**, so every input is downscaled to ≤ 2 MP before any filter runs (low-RAM hosts) (LANCZOS, aspect kept; JPEGs decode at reduced scale via `draft` first), not rejected; images over **120M** pixels (`MAX_DECODE_PIXELS`) are rejected from the header before decoding. At 61 MP the heaviest (cut-out) presets take ~5–10 s and peak at ~3.8 GiB, of which ~1.75 GiB is the fixed rembg/ONNX model. Decode and encode run via `asyncio.to_thread` so a large file doesn't stall the event loop. Preset JSON paths from the DB must resolve under `backend/presets/` (`PresetPathUnsafeError` otherwise). Apply-preset runs off the event loop via `asyncio.to_thread` and allows only **1** concurrent job (`MAX_CONCURRENT_PRESET_JOBS`) so rembg cannot pile up. Both `/api/apply-preset` and `/api/blur` take that slot (`preset_job_slot`) **before** reading the upload into memory and hold it through decode → filters → encode, so extra requests get **503** immediately without buffering or decoding (the multipart body is already spooled to a temp file).

### Blur algorithm

- Pillow `ImageFilter.GaussianBlur` with default radius **12** (`DEFAULT_BLUR_RADIUS` in `services/blur.py`).
- `load_image_with_format` applies EXIF orientation (camera portrait shots), converts an embedded ICC profile (Adobe RGB, ProPhoto, CMYK) to sRGB, and normalises 16-bit / float / grey / CMYK / palette input to 8-bit `RGB`/`RGBA` (`to_working_mode`; 16-bit is scaled, not clipped). `encode_result` returns JPEG (quality 95, 4:4:4, sRGB-tagged) for a JPEG upload with an opaque result, else PNG (sRGB-tagged); camera EXIF (GPS, serials) is not carried over: the loader keeps the upload's EXIF on the in-memory image (re-attached after ICC conversion) only so presets can read the capture date, and every encoder writes `exif=b""`.

### Subject extraction helper (CLI only)

- `backend/helpers/extract_subject.py` — local background removal via **rembg** (`u2net` session / onnxruntime). Only rembg's alpha is kept; colour comes from the source photo, because rembg darkens soft edge pixels (≈ premultiplied), which otherwise shows as a dark rim after compositing.
- Input: any Pillow-readable image path. Output: PNG with alpha (subject kept, background transparent).
- Not mounted as an HTTP route.
- `./scripts/setup.sh` installs `backend/helpers/requirements.txt` and runs `download_model.py` so `u2net` (~176MB) is cached under `~/.rembg/` (outside the repo).
- Gitignore blocks `.rembg/`, `*.onnx`, and `backend/helpers/models/` so weights are never committed.
- Example: `python backend/helpers/extract_subject.py photo.jpg -o subject.png`

### AI upscale helper

- `backend/helpers/upscale_model.py` — Real-ESRGAN `realesr-general-x4v3` (BSD-3-Clause) from the official `xinntao/Real-ESRGAN` v0.2.5.0 release. Both checkpoints (regular + `wdn`) are SHA-256 pinned and fetched over verified HTTPS (certifi CA bundle, 60 s stall timeout; temp file renamed into place only after the hash matches); a restricted unpickler reads them without PyTorch, `denoise` blends them (upstream DNI), and `onnx` builds the SRVGGNetCompact graph (conv/PReLU body → `DepthToSpace` + nearest residual).
- Cache: `~/.local-studio/models/` (`LOCAL_STUDIO_MODELS` overrides) — one `realesr-general-x4v3-dn<strength>.onnx` per denoise value, written to a temp file and renamed so a crash never leaves a partial model. `./scripts/setup.sh` warms the default (`python upscale_model.py`).
- Inference: onnxruntime CPU, 256 px tiles with 24 px overlap; session cached per model path.
- `filters.ai_upscale` runs the 4× pass then Lanczos-resizes to `long_edge` (capped by `max_scale`, never shrinks). Inputs over `max_input_pixels` (default 1 MP) are reduced first so time/memory stay bounded (~1–4 s per image on CPU).

### JSON preset pipeline

- Presets live in `backend/presets/*.json` as ordered `steps`. Each step sets `"filter"` to a registered helper name plus that helper's parameters. The runner looks the function up in `FILTERS` — it does not branch on filter type. String params equal to (or containing) `$text` receive the user/default text.
- Runner: `backend/helpers/apply_preset.py` (uses `filters.py`).
- HTTP: `POST /api/apply-preset` looks up `preset_name` in the preset DB, loads that JSON path, runs the same runner, returns PNG (`app/services/preset.py` + `app/routes/preset.py`). The route does not choose filters; it passes `preset_name`, the image, and optional `text`. Presets with `"ar": "square"` reject non-square input images (`PresetAspectRatioError` → HTTP **400**). Presets with `"text_input": "yes"` validate `text` against `text_character_limit` (`PresetTextError` → HTTP **400**); omitted text uses `default_text`.
- Built-in filters: `extract_subject`, `brightness`, `color`, `contrast`, `overlay`, `grayscale`, `glow_border`, `glow_line_border`, `composite`, `draw_text`, `place_on_canvas`, `upscale`, `sharpen`, `denoise`, `ai_upscale`, `doodle`, `sticker_outline`, `posterize`, `ink_edges`, `halftone`, `paper_texture`, `color_grade`, `vignette`, `bloom`, `halation`, `light_leak`, `film_dust`, `chromatic_aberration`, `blur`, `selective_color`.
- `glow_line_border` draws a colored outline ring only (does not fill/glow the subject body). Pass `"color": [R,G,B]` (or `"rgb"`). `glow_border` / `glow_line_border` take px `width`/`blur` or `width_ratio`/`blur_ratio` (fractions of the short side; the ratio path grows the mask with flat-cost blur+threshold, since `MaxFilter` cost grows with width²).
- `posterize` flattens channels to N levels; `ink_edges` draws comic outlines from a difference of Gaussians; `halftone` renders a mono or CMYK dot screen (own grey-component-replacement separation, since Pillow's RGB→CMYK leaves K empty; processed at ≤ 2400 px long edge and resized back, pitch enlarged when a screen would exceed 160k dots); `paper_texture` adds seeded grain, stains and fade (tone steps as point tables, grain tiled in place, stain grid follows aspect ratio). `halftone`/`ink_edges` flatten RGBA onto paper/white before analysing tone, so pixels under transparency never print. All sizes are fractions of the short side; at 25 MP these presets peak at ~0.5–0.65 GB.
- `color_grade` folds white balance, exposure, contrast curve, black lift and highlight shoulder into per-channel point tables (flat cost), then runs split toning / saturation / vibrance with numpy in horizontal strips of ≤ 4 MP so a 61 MP frame stays bounded (~1.6 GiB peak per grade preset incl. the HD step); out-of-gamut pixels are scaled back along their own luma rather than clipped per channel. `vignette` builds its mask at ≤ 256 px and scales it up. `bloom` / `halation` blur a highlight mask on a ≤ 1024 px copy and screen it back; `light_leak` is generated at ≤ 256 px; `blur` shrinks before large radii and does a normalised (weighted) blur for RGBA and `exclude` masks; `chromatic_aberration` zooms the R/G channels about the centre; `film_dust` draws seeded specks/hairs/scratches sized to the short side — all keep cost roughly flat at DSLR sizes.
- `sticker_outline` draws a solid outline sized by `width_ratio` × short side via blur + threshold (cost independent of width; round corners).
- `extract_subject` with `"require_clear_subject": true` (opt-in; the doodle presets use it) falls back to an empty subject + untouched background when `is_reliable_cutout` rejects the rembg mask, so the preset degrades to "no cutout" instead of a smeared shape. Rejected when solid alpha is < 0.3% of pixels, or when soft pixels *outside* a band around the solid body outnumber solid pixels (band = max(4% of short side, 0.75 × body equivalent radius)), so hair/fur hugging the body is accepted. Presets without the flag keep the raw mask. `"single_subject": true` (opt-in; doodle presets) then runs `keep_main_subject`: it labels solid islands on a working mask capped at 256 px short / 1024 px long side (flood fill seeded via `getbbox`, after a 1.5% merge dilation) and keeps every bottom-touching island ≥ 25% of the largest — else just the largest — plus a 3% soft-edge band, so rembg's second salient object (e.g. a framed picture behind a person) stays in the untouched background.
- `draw_text` paints `text` onto a layer. Use `"$text"` for user caption, or `"$datetime"` / `"$date"` / `"$time"` for stamps — the photo's EXIF capture time (`DateTimeOriginal` → `DateTimeDigitized` → `DateTime`, via `apply_preset.photo_datetime`), else apply time. Common params: `font_size`, `color`/`rgb`, `align` (`center`/`top`/`bottom`/`top_left`/`top_right`/`bottom_left`/`bottom_right`), `font_style` (`sans`/`flow`/`stamp`), optional `font_path` (TTF/OTF/TTC, overrides style), `margin`, `x`/`y`, `stroke_width`; `font_size_ratio` / `margin_ratio` / `stroke_ratio` (fractions of the short side) override the px values so text keeps its proportions at any resolution. Text wider than 90% of the layer shrinks straight to the fitting size. Poster-title extras render the text on its own layer: `scale_y` stretches it, `box` (`frame`/`double`/`corners`/`label`) draws a thin box around the inked glyphs, `angle` tilts it, and `glow_ratio` (capped at 0.05 of the short side; fixed brightness, not a preset knob) screens a blurred halo (`glow_color`) under it before pasting. With `x`/`y` the same layer path is used, so these extras still apply. Named `font_style`s for posters resolve through `filters._DISPLAY_FONT_CANDIDATES`: system Impact / Brush Script when installed, else bundled fonts in `backend/fonts/` (OFL / Apache, licences alongside); `neon_lines` and `marquee` fonts are caps-only.
- `selective_color` boosts one HSV hue band (`hue` by degrees, name or [r,g,b]; smooth `width` falloff; near-greys weighted down) and scales the saturation of everything else by `others`; numpy in ≤ 4 MP strips like `color_grade`.
- `place_on_canvas` puts a layer on a larger solid canvas (`scale`, `fill`, `layout`: `polaroid` or `center`).
- `doodle` draws one hand-drawn doodle (`style`: `xo`/`rings`/`wiggles`/`stars`) with seeded wobble. It draws only the doodle's neighbourhood (not a full-frame layer), 2× supersampled when that region is ≤ 4 MP and 1× above, so a 25 MP upload stays bounded; `count` is capped at 12. Sizes are fractions of the short side. Its runner (`_run_doodle`) accepts an optional `around` layer so `anchor: subject` centres on that layer's alpha bbox — the only filter that reads a second layer besides `composite`. The same layer drives `avoid_subject` (corner/edge anchors flip to a mirror the subject doesn't cover; `avoid_busy` also skips cluttered background, scored on a blurred ≤128 px edge map); `color: "auto"` picks dark or white ink from the region's mean luma.
- Shipped presets:
  - `bw_bg_glowing_subject` — extract (`single_subject`) → grayscale background → `glow_line_border` (ratio width/blur) on subject → composite (`text_input: no`)
  - `polaroid_memory` — soft warm grade → `$datetime` stamp → 1.4× white polaroid mat → flow `$text` caption (`ar: square`, `text_input: yes`)
  - `warm_faded_print` — lower contrast → muted color → slight lift → cream-amber overlay (`ar: non-square`, `text_input: no`)
  - `full_hd` — `ai_upscale` to 1920 px long edge, denoise 0.5 (`ar: non-square`, `text_input: no`)
  - `4k_crisp` — `ai_upscale` to 3840 px long edge, denoise 0.3 → light `sharpen` → contrast ×1.04 (`ar: non-square`, `text_input: no`)
  - `doodle_corner_xo` — extract → white `sticker_outline` → `doodle` xo (top-right) + wiggles (bottom-left) on background → composite (`ar: non-square`, `text_input: no`)
  - `comic_pop` — contrast/colour lift → `posterize` 6 → light CMYK `halftone` → `ink_edges` → faint `paper_texture` (`ar: non-square`, `text_input: no`)
  - `old_newspaper` — grayscale → lift/contrast → mono `halftone` on newsprint → `paper_texture` grain/stains/fade (`ar: non-square`, `text_input: no`)
  - `vintage_comic` — brighten → `posterize` 8 → CMYK `halftone` (55% mix) → soft `ink_edges` → aged `paper_texture` (`ar: non-square`, `text_input: no`)
  - Professional colour grades (`ar: non-square`, `text_input: no`): `ai_upscale` (1920, denoise 0.3) → `color_grade` → optional `vignette` / grain — `cinematic_teal_orange`, `warm_portrait_film`, `nordic_cool_matte`, `golden_hour_glow`, `emerald_moody`, `fine_art_mono` (grayscale first), `bright_airy`, `vintage_slide_punch`, `blush_rose_pastel`, `blue_hour_noir`
  - Prequel-style looks (`ar: non-square`, `text_input: no`): `dreamy_glow` (HD → grade → `bloom`), `film_halation` (HD → grade → `halation` → grain), `film_dust` (grade → grain → `film_dust` → `vignette`), `miami_neon` (HD → grade → `bloom`), `prism_glow` (HD → grade → `chromatic_aberration` → `light_leak` → `bloom`), `disposable_flash` (grade → `vignette` → grain → `draw_text` `$date`, `stamp` font), `portrait_bokeh` (HD → `extract_subject` → `blur` with `exclude: subject` + `bloom` on background → `composite` → grade), `tungsten_night_film` (HD → cool grade → red `halation` → `bloom` → grain), `muted_chrome_film` (HD → muted grade → grain → `vignette`), `studio_spotlight` (HD → `extract_subject` → darken/desaturate + `blur` (`exclude: subject`) + `vignette` on background → `composite` → grade → `vignette`)
  - Poster titles (`ar: non-square`, `text_input: yes`, default `TITLE`, limit 16): `extract_subject` → background grade / `selective_color` → `draw_text` `$text` on the background (tall `scale_y`, optional `angle` / `glow_ratio` / `box`) → `composite` subject on top → optional finish (`halation` / `vignette` / grain) — `poster_title_yellow_pop`, `poster_title_blue_pop`, `retro_70s_poster`, `brush_script_poster`, `neon_nights_script`, `mission_passed_title`, `wanted_stencil_title`, `retrowave_neon_title`, `art_deco_marquee`, `velvet_ticket_title`
  - `doodle_halo_rings` — extract → white `sticker_outline` → `doodle` rings around subject + stars (top-left) on background → composite (`ar: non-square`, `text_input: no`)
- Example CLI: `python backend/helpers/apply_preset.py photo.jpg -p bw_bg_glowing_subject -o out.png`
- Human/agent guide: `backend/presets/PRESETS.md`
- New-preset workflow skill: `.cursor/skills/create-preset/SKILL.md`

### Preset metadata database

- Location: `backend/database/` (SQLite file `presets.local.db`, same pattern as a lightweight local store). The file is **not committed** (gitignored):  each install keeps its own `popular` counts, so `git pull` can't conflict on it. `prepare_db.py` (called by `setup.sh` and on every `run.sh`) runs `init_db()` + `migrate_schema()` + `seed_default_presets()`, which inserts any shipped preset that is missing and syncs metadata of existing ones without touching counts; the `defaults` list in `seed_default_presets()` is the source of truth for shipped presets. `presets.db` stays committed but **frozen** (legacy: never written, never change or delete it) so clones from before this change can `git pull` cleanly; its rows and counts are copied into `presets.local.db` the first time that file is created.
- Table `presets`: `preset_id` (PK auto), `preset_name`, `preset_path`, `keywords` (JSON list), `ar` (`square` or `non-square`, default `non-square`), `text_input` (`yes` or `no`, default `no`), `default_text` (default `''`), `text_character_limit` (integer, default `0`, max 200), `created_date` (auto `datetime('now')`). Existing DBs gain `ar` and text columns via `migrate_schema()`. `list_presets()` returns rows `ORDER BY preset_id DESC` (newest first).
- Table `popular`: `preset_id` (PK + FK to `presets.preset_id`, `ON DELETE CASCADE`), `used_count` (integer, default `0`). One row per preset; `list_popular()` / `GET /api/presets/popular` return `{ preset_id, preset_name, used_count }` ordered by `used_count DESC`. Existing DBs gain the table (and a 0-count row per preset) via `migrate_schema()`.
- Service functions: `backend/database/db_ops.py` (`add_preset`, `list_presets`, `search_presets_by_keyword`, `get_preset_by_id`, `update_preset`, `delete_preset`, `seed_default_presets`, `list_popular`, `increment_used_count`, `increment_used_count_by_name`).
- Keyword search API: `GET /api/presets/search?q=…` → case-insensitive substring match against each preset’s `preset_name` and keywords (`services/preset_search.py` + `routes/search.py`). Returns `ar` plus text-input metadata, newest `preset_id` first.
- Download-count API: `POST /api/presets/use` increments `popular.used_count` for a `preset_name` (`services/preset_popular.py` + `routes/popular.py`). Unknown names return **404**.
- `./scripts/setup.sh` runs `init_db()` and seeds shipped presets (`bw_bg_glowing_subject`, `polaroid_memory`, `warm_faded_print`).

### CORS

- Development CORS allows all origins so any local static host can call the API. Tighten this before production deployment.

## Local run

- `./scripts/setup.sh` creates `backend/.venv` (or recreates it if relocated/broken), installs deps, and prepares the local preset DB (`prepare_db.py`); `run.sh` re-runs `prepare_db.py` on every start so presets from a `git pull` are seeded.
- `./scripts/run.sh` starts uvicorn on `0.0.0.0:8000` and a static frontend on port `5500` via the venv Python, in the background; fails fast if deps are missing or ports are taken.

## Documentation responsibilities

| File | Contents |
|------|----------|
| `README.md` | Setup & run only |
| `CONTEXT.md` | Short agent/contributor briefing |
| `ARCHITECTURE.md` | This file — design & data flow |
| `backend/presets/PRESETS.md` | Helpers, filters, shipped presets, create-preset how-to |
| `.cursor/skills/create-preset/SKILL.md` | Gated agent workflow to design/ship a new preset |
| `docs/` | GitHub Pages pitch (`docs/index.html`); CTAs link to GitHub fork |
| `scripts/setup.sh` | One-command local bootstrap |
| `scripts/run.sh` | One-command API + frontend start (background) |
| `scripts/update.sh` | Pull latest code, stop, and restart |
| `test-suite/` | Service-function unit tests (pytest); CI via `.github/workflows/test-suite.yml` |

When features change, update these in the same change set (enforced by `.cursor/rules/docs-and-branch-safety.mdc`). When `backend/app/services/` change, update matching `test-suite/` tests **only where necessary**. When helpers/filters/presets/DB metadata change, update `PRESETS.md` as needed.

## Helper scripts

- `scripts/setup.sh` — creates `backend/.venv` (recreates if shebangs/interpreter are broken after a folder rename), installs API + helper requirements, downloads rembg `u2net` into `~/.rembg/`, builds the Real-ESRGAN ONNX model in `~/.local-studio/models/`, creates/seeds the local `backend/database/presets.local.db` via `prepare_db.py`, ensures scripts are executable.
- `scripts/run.sh` — starts uvicorn (port 8000) and a static file server on the repo root (port 5500) using `backend/.venv/bin/python -m …`; loads `.env` (copy of `.env.example`) into the environment; checks deps + free ports; runs `backend/database/prepare_db.py` (seed new presets, keep counts); both run under `nohup` in the background with output in `logs/api.log` / `logs/frontend.log` (gitignored). The script waits up to ~30 s for `/health`, then returns and leaves them running; on a failed start it kills what it launched and prints the log tail. Stop with `scripts/stop.sh`.
- `scripts/stop.sh` — sends SIGTERM to whatever listens on ports 8000 / 5500, waits up to ~10 s for both ports to free (SIGKILL after that), so `run.sh` can start straight after.
- `scripts/update.sh` — runs `git pull`, `scripts/stop.sh`, then `scripts/run.sh` in that order, with no checks (all three run even when there is nothing to pull or a step fails).

## Extension points

New edits should follow the same pattern:

1. Add a service function under `backend/app/services/`.
2. Add or update unit tests under `test-suite/` for that service (not the HTTP route).
3. Add a thin route under `backend/app/routes/` and mount it from `main.py`.
4. Add a small client helper under `js/` and wire it from `script.js`.
5. Refresh docs + `docs/index.html` if user-visible behavior changed.

### Testing

- Scope: **service functions only** (`app.services.*`). Do not exercise FastAPI routes here.
- Local: after `./scripts/setup.sh`, install `test-suite/requirements.txt` into the same venv, then `pytest test-suite/ -v`.
- CI: `.github/workflows/test-suite.yml` runs the same suite on pull requests (and pushes to `main`).
