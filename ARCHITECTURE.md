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
│  index.html (landing, static) ──► studio.html + script.js    │
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

- `index.html` — landing page (no Tailwind; `css/landing.css` + `js/landing.js` module). Four full-viewport scenes stacked in a `perspective` stage — **Origin** (pitch + rotating CSS-3D ring of feature cards (inline SVG icons, not photos; each card is a size container and its padding, icon and type use `cqi` units so the contents fit the fixed card shape at any ring size), drag to spin), **Protocol** (3 steps, before/after scanner, setup commands), **Fusion** (exploded layer stack of the `da_vinci_wings` recipe: source → `extract_subject` → `color`/`paper_texture` → `codex_doodle` → composite), **Archive** (marquee wall of random post-edit previews + CTA to `studio.html`). Page scroll is disabled; wheel (one scene per gesture, inertia ignored), vertical swipe, arrow/Page/Space/Home/End keys, the section rail and the Next button call `go()`, which toggles `is-active` / `is-past` / `is-future` (depth + blur transitions), marks off-screen scenes `inert`, syncs `#hash`, and warps the canvas particle field. A scene gets `is-tall` (internal scroll) only when its content outgrows the viewport; scene changes wait until that inner scroll reaches its edge. Floating = CSS `drift` keyframes on `.fl` + pointer parallax through the `translate` property on `.par`. Navigation is spelled out for visitors: the section rail shows numbered stops (01 Intro, 02 How it works, 03 Inside a preset, 04 Presets — the scenes' `data-name`) on a progress line, with the current name always visible on wide screens; a **Next** button (bottom centre on desktop, bottom right on phones beside the stops) says how to move ("Scroll or click" / "Swipe up or tap") and where it goes, and on the last scene becomes "Back to start" (`landing.js` keeps its label and `aria-label` current). `prefers-reduced-motion` turns transitions into fades and stops all ambient motion. On phones and portrait tablets (≤ 900 px) sections are laid out for reading rather than squeezed into one screen (they scroll inside, fully masked under the HUD and the bottom dot bar), and the Origin scene stacks title → 3D model → pitch → CTAs so the title and the whole model open the page; `js/landing.js` shrinks the feature-card ring (`--cw` / `--r`) whenever the full ring would not fit across the screen. Reads only `previews/presets.json` (count + archive tiles).
- `studio.html` — full-viewport two-column UI, plain CSS in `css/styles.css` (Orbital theme shared with the landing page; no Tailwind). HUD header (brand → `index.html`, 01 Look / 02 Photo / 03 Result tracker, Home link). Progress styling is pure CSS: `:has(.preset-card--selected)`, `:has(#preview-original:not(.hidden))` and `:has(#preview-edited:not(.hidden))` light the tracker and the step cards (current step lemon, done steps green), so `script.js` needs no theme hooks. Phones (< 768 px) switch to a scrolling page.
  - **Left (~62%) "Choose a look" console:** heading with a count pill (`#preset-count`: the total, or `shown / total` in lemon when search or **Square photo? No** narrows the list; an sr-only twin announces "Showing X of Y presets"), search input, **Square photo?** yes/no switch, **Popular** mode (off by default; unclick restores the default shuffled order), refresh control beside search, and preset grid with a page-drawn scroller (`#preset-scroller`, positioned by `initPresetScroller()` in `script.js`: neon sky→violet pill thumb on a faint dashed rail, lemon→coral on hover / drag; draggable by mouse, pen or finger, tap the rail to page; hidden when nothing overflows; exposed as an ARIA `scrollbar` with `aria-controls="preset-grid"` and a live `aria-valuenow` / `aria-valuetext` 0–100 %, not a tab stop — like a native scrollbar). The native scrollbar is hidden because mobile browsers and Firefox ignore scrollbar styling; wheel / touch / keyboard scrolling are unchanged (random order on every page load; post-edit preview + name; hover/focus — or press-and-hold on touch screens — reveals pre-edit original); search reloads the grid from DB name/keyword matches; **No** hides `ar=square` presets.
  - **Right (~38%) pipeline:** step 01 (selected look name + optional preset text field), step 02 (file upload / original preview, enabled after a preset is selected), **Download** / **Generate edit**, step 03 (edited result, with a scanning beam over the loading state).
- `script.js` — wires gallery load (shuffled into a fresh random order on every page load), debounced search (filters gallery), selection, upload unlock, optional text constraints, file pick/drag-drop, generate button, download use-count ping, popular-sort mode (unclick restores the shuffled order), search-row gallery refresh.
- `js/image.js` — `isImageFile`, object URL create/revoke.
- `js/api.js` — `searchPresets(baseUrl, query)` → match list; `listPopularPresets(baseUrl)` → popular rows; `applyPreset(baseUrl, presetName, file, text?)` → `Blob`; `previewImage(baseUrl, file)` → preview `Blob` (used when the `<img>` fails to decode the upload, e.g. HEIC in Chrome); `recordPresetUse(baseUrl, presetName)` → `{ preset_id, used_count }` (also retains `blurImage` for `/api/blur`).

### UX flow

1. Gallery loads from `previews/presets.json` (stored newest first), shuffles it into a fresh random order on every page load (Fisher–Yates with `crypto.getRandomValues` when available), marks the 5 newest manifest entries with a **New** badge (so new presets stay findable in the random order), and renders post-edit thumbnails with pre-edit originals stacked underneath (entries must use a valid `preset_name`, `ar` of `square` or `non-square`, `text_input` of `yes` or `no`, `default_text`, `text_character_limit`, and relative paths under `previews/pre-edit/` and `previews/post-edit/`). Hover or keyboard focus reveals the original as a left-to-right wipe (clip-path) led by a lemon scanning beam, and the card's corner tag flips from **After** to **Before**; the first card in the grid plays this wipe twice on load as a demo. Touch screens have no hover, so `bindTouchCompare` (`script.js`, pointer events delegated on the grid) adds `.preset-card--peek` after a 180 ms touch/pen hold and removes it on release; a hold doesn't select the card (the trailing click is swallowed), a quick tap still selects, and moving > 10 px or `pointercancel` (gallery scroll) cancels. The long-press image callout / context menu is suppressed on cards, and the gallery header carries a looping mini demo of the wipe whose wording switches from "Hover" to "Press & hold" under `@media (hover: none)`.
2. User can set **Square photo?** to **Yes** (show all presets) or **No** (show only `ar=non-square` presets). **Popular** (off by default) is a mode only — it does not reload the gallery. The refresh button beside the search box fetches `GET /api/presets/popular` and reorders visible cards by `used_count` descending. Unclicking **Popular** restores that visit's shuffled order. Download increments the table immediately but does not reorder the grid.
3. User clicks a preset card to select it, **or** types in the left-column search box (debounced) to query DB `preset_name` + keywords via `GET /api/presets/search?q=…` — the gallery reloads to matching presets only (kept in this visit's shuffled order, so cards don't jump while typing; cleared query restores the AR-filtered shuffled gallery).
4. Selecting a preset unlocks the upload form. If `text_input` is `yes`, a text field appears prefilled with `default_text` and capped at `text_character_limit`.
5. User selects or drops a file; client rejects non-images and shows an inline error.
6. Original preview uses a local object URL.
7. When **both** preset and file are set, **Generate edit** enables.
8. On generate, the file + preset name (+ `text` when required) are posted to the API; a loading state covers the result panel. Changing preset/file while a request is in flight discards the stale response. A `ar=square` preset on a non-square image is rejected (client + HTTP **400**). Oversized preset text is rejected (HTTP **400**).
9. Response blob is shown via another object URL; download link reuses that URL. Clicking **Download** also `POST`s form field `preset_name` to `/api/presets/use` to increment `popular.used_count` immediately (best-effort; a failed ping does not block the file download). The gallery is not reordered until the search-row refresh is clicked with **Popular** on.
10. Refresh clears all in-memory state (no persistence of upload or result).

### Config

- API base URL: `script.js` uses `API_BASE = ""` — same origin; the frontend container's nginx proxies `/api/*` to the backend.

### Preset preview assets

- `previews/pre-edit/` — open-licensed source photo per shipped DB preset (see `previews/CREDITS.md`), 720×720 WebP (quality 85).
- `previews/post-edit/` — same photo after that preset is applied, 720×720 WebP (quality 85). Both sets used to be PNG / JPEG (~85 MB); WebP keeps them ~16 MB with no visible difference at gallery size.
- `previews/presets.json` — array of `{ preset_name, ar, text_input, default_text, text_character_limit, pre_edit_image, post_edit_image }` (repo-relative paths). Newest gallery entries first (matches `list_presets`). Consumed by the studio gallery (and by the landing page for its preset count and archive wall). `ar` is `square` or `non-square`. `text_input` is `yes` or `no`.
- `previews/_candidates/` — gitignored scratch for the create-preset skill. Comparison `index.html` pages (POC edits, font samples, gallery before/after) are generated by `.cursor/skills/create-preset/scripts/render_candidates.py`, which calls `apply_preset.apply_preset_file` and `filters.draw_text`. Not served by the studio UI.

### Marketing page

- `index.html` (repo root) is the local landing page served at `/` by the frontend server; it links into `studio.html`.
- `docs/index.html` is the GitHub Pages version of the landing page (published from `/docs`), identical scenes and motion, but self-contained because Pages only serves `docs/`: `docs/css/styles.css` and `docs/js/landing.js` are byte-for-byte copies of `css/landing.css` and `js/landing.js`; images come from `docs/previews/{post,pre}/` (560 px JPEG copies of the repo previews, licensed per `docs/previews/CREDITS.md`, linked from the page); `<body data-presets="previews/manifest.json">` points `landing.js` at a trimmed manifest `{ presets: [{ preset_name, post_edit_image }] }` instead of `previews/presets.json`. Every CTA sends users to the GitHub repo to **clone** it (README `#setup`) — there is no hosted live app and no fork step; only the owner pushes, users update with `git pull` + `docker compose up -d --build`. After changing the landing CSS/JS, re-copy them into `docs/`; the manifest has an inline copy (`<script type="application/json" id="lp-presets">` in `docs/index.html`, which `landing.js` prefers over fetching so the page also works opened straight from disk). The landing copy never states a preset total (it says "growing library" instead), so adding presets needs no landing-page edit. Both landing pages load `landing.js` as a classic `defer` script (not a module) for the same reason.

## Backend

### Stack

- **Python 3.12**
- **FastAPI** — HTTP API
- **Pillow** (+ **pillow-heif** for HEIC/HEIF) — image decode (EXIF orientation, ICC → sRGB via `ImageCms`) / Gaussian blur / JPEG·PNG encode
- **NumPy** — array maths in the preset filters (`color_grade`, `light_leak`, `blur`, `halftone`, …); the API runs presets in-process, so it is a core dependency
- **uvicorn** — ASGI server
- **python-multipart** — file uploads

### Package layout

```
backend/
  requirements.txt
  helpers/
    requirements.txt     # rembg[cpu] + onnx + certifi — installed in the backend image
    download_model.py    # warm-cache the rembg model ($REMBG_HOME)
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
    prepare_db.py        # init + migrate + seed (run on every backend container start)
    db_ops.py            # CRUD for preset metadata + download counts
    presets.local.db     # live SQLite file (local, gitignored; created by prepare_db.py)
    presets.db           # legacy committed copy, frozen (seed source for old clones)
  app/
    main.py              # FastAPI app, /health, router mount (no CORS — same-origin via nginx)
    routes/
      blur.py            # POST /api/blur
      preset.py          # POST /api/apply-preset
      preview.py         # POST /api/preview
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
| POST | `/api/blur` | `multipart/form-data` field `file` | `image/jpeg` for a JPEG / HEIC upload, else `image/png` |
| POST | `/api/apply-preset` | `multipart/form-data` fields `preset_name`, `file`, optional `text` (max 200) | `image/jpeg` for a JPEG / HEIC upload with an opaque result, else `image/png` |
| POST | `/api/preview` | `multipart/form-data` field `file` | ≤ 2048 px `image/jpeg` (or `image/png` with transparency) for browsers that can't render the upload |

Error responses use FastAPI `HTTPException` with JSON `detail` (e.g. non-image, empty file, unknown preset, decode failure, square-only preset on a non-square image). Oversized uploads/images return **413**. Apply-preset returns **503** when the concurrency gate is full. `POST /api/presets/use` returns **404** for an unknown `preset_name`.

Upload guards (`services/image_io.py`): max **100 MiB** body (`MAX_UPLOAD_BYTES`, full-quality DSLR JPEG/TIFF); images over the working size (max side **12000** px / **64M** pixels — full-frame DSLR files up to 61 MP stay native) are **downscaled to fit**; with `LIGHTWEIGHT=1` (env, set in the gitignored `.env` that `docker compose` passes to the backend; read once at import) the working cap drops to **2M pixels**, so every input is downscaled to ≤ 2 MP before any filter runs (low-RAM hosts); the same flag makes `filters.ai_upscale` skip Real-ESRGAN and do a plain Lanczos `upscale` to the same target (so Full HD / 4K Crisp still deliver their resolution) and `extract_subject.py` use `u2netp` (~5 MB; ~0.9 GB peak vs ~2.1 GB for `u2net` at 2 MP, slightly rougher edges; downloaded by rembg on first use) (LANCZOS, aspect kept; JPEGs decode at reduced scale via `draft` first), not rejected; images over **120M** pixels (`MAX_DECODE_PIXELS`) are rejected from the header before decoding. At 61 MP the heaviest (cut-out) presets take ~5–10 s and peak at ~3.8 GiB, of which ~1.75 GiB is the fixed rembg/ONNX model. Decode and encode run via `asyncio.to_thread` so a large file doesn't stall the event loop. Preset JSON paths from the DB must resolve under `backend/presets/` (`PresetPathUnsafeError` otherwise). Apply-preset runs off the event loop via `asyncio.to_thread` and allows only **1** concurrent job (`MAX_CONCURRENT_PRESET_JOBS`) so rembg cannot pile up. `/api/apply-preset`, `/api/blur` and `/api/preview` all take that slot (`preset_job_slot`) **before** reading the upload into memory and hold it through decode → filters → encode, so extra requests get **503** immediately without buffering or decoding (the multipart body is already spooled to a temp file).

### Blur algorithm

- Pillow `ImageFilter.GaussianBlur` with default radius **12** (`DEFAULT_BLUR_RADIUS` in `services/blur.py`).
- `load_image_with_format` applies EXIF orientation (camera portrait shots), converts an embedded ICC profile (Adobe RGB, ProPhoto, CMYK) to sRGB, and normalises 16-bit / float / grey / CMYK / palette input to 8-bit `RGB`/`RGBA` (`to_working_mode`; 16-bit is scaled, not clipped). HEIC/HEIF decodes through the `pillow-heif` opener registered in `image_io.py`. `encode_result` returns JPEG (quality 95, 4:4:4, sRGB-tagged) for a JPEG or HEIC upload with an opaque result, else PNG (sRGB-tagged); camera EXIF (GPS, serials) is not carried over: the loader keeps the upload's EXIF on the in-memory image (re-attached after ICC conversion) only so presets can read the capture date, and every encoder writes `exif=b""`.

### Subject extraction helper (CLI only)

- `backend/helpers/extract_subject.py` — local background removal via **rembg** (`u2net` session / onnxruntime). Only rembg's alpha is kept; colour comes from the source photo, because rembg darkens soft edge pixels (≈ premultiplied), which otherwise shows as a dark rim after compositing.
- Input: any Pillow-readable image path. Output: PNG with alpha (subject kept, background transparent).
- Not mounted as an HTTP route.
- The backend image installs `backend/helpers/requirements.txt` and bakes `u2net` (~176MB) and `u2netp` into `REMBG_HOME=/opt/local-studio/rembg` at build time (outside the repo).
- Gitignore blocks `.rembg/`, `*.onnx`, and `backend/helpers/models/` so weights are never committed.
- Example: `docker compose run --rm dev python backend/helpers/extract_subject.py photo.jpg -o subject.png`

### AI upscale helper

- `backend/helpers/upscale_model.py` — Real-ESRGAN `realesr-general-x4v3` (BSD-3-Clause) from the official `xinntao/Real-ESRGAN` v0.2.5.0 release. Both checkpoints (regular + `wdn`) are SHA-256 pinned and fetched over verified HTTPS (certifi CA bundle, 60 s stall timeout; temp file renamed into place only after the hash matches); a restricted unpickler reads them without PyTorch, `denoise` blends them (upstream DNI), and `onnx` builds the SRVGGNetCompact graph (conv/PReLU body → `DepthToSpace` + nearest residual).
- Cache: `LOCAL_STUDIO_MODELS` (default `~/.local-studio/models/`; the backend image uses `/opt/local-studio/models`, seeded with the repo's `model/realesrgan/*.pth` so nothing is downloaded) — one `realesr-general-x4v3-dn<strength>.onnx` per denoise value, written to a temp file and renamed so a crash never leaves a partial model. The image build pre-builds the ONNX graphs for the denoise strengths presets use (0.3, 0.5).
- Inference: onnxruntime CPU, 256 px tiles with 24 px overlap; session cached per model path.
- `filters.ai_upscale` runs the 4× pass then Lanczos-resizes to `long_edge` (capped by `max_scale`, never shrinks). Inputs over `max_input_pixels` (default 1 MP) are reduced first so time/memory stay bounded (~1–4 s per image on CPU).

### JSON preset pipeline

- Presets live in `backend/presets/*.json` as ordered `steps`. Each step sets `"filter"` to a registered helper name plus that helper's parameters. The runner looks the function up in `FILTERS` — it does not branch on filter type. String params equal to (or containing) `$text` receive the user/default text. Any step may add the generic gate `"requires_layer": "<layer>"` (optionally `"min_coverage": 0–1`, the layer's mean alpha): the runner skips that step when the layer is missing, fully transparent, or covers less than that share of the frame (e.g. darken the background only when `extract_subject` found a real subject).
- Runner: `backend/helpers/apply_preset.py` (uses `filters.py`).
- HTTP: `POST /api/apply-preset` looks up `preset_name` in the preset DB, loads that JSON path, runs the same runner, returns PNG (`app/services/preset.py` + `app/routes/preset.py`). The route does not choose filters; it passes `preset_name`, the image, and optional `text`. Presets with `"ar": "square"` reject non-square input images (`PresetAspectRatioError` → HTTP **400**). Presets with `"text_input": "yes"` validate `text` against `text_character_limit` (`PresetTextError` → HTTP **400**); omitted text uses `default_text`.
- Built-in filters: `extract_subject`, `brightness`, `color`, `contrast`, `overlay`, `grayscale`, `glow_border`, `glow_line_border`, `composite`, `draw_text`, `place_on_canvas`, `upscale`, `sharpen`, `denoise`, `ai_upscale`, `doodle`, `sticker_outline`, `posterize`, `ink_edges`, `halftone`, `paper_texture`, `color_grade`, `vignette`, `bloom`, `halation`, `light_leak`, `film_dust`, `chromatic_aberration`, `blur`, `selective_color`, `doodle_frame`, `tone_curve`, `shadows_highlights`, `motion_blur`, `radial_blur`, `warp`, `codex_doodle`, `circle_backdrop`, `text_pattern`, `half_mask`, `clip_to`, `blend`, `draw_shape`, `crop_aspect`.
- `glow_line_border` draws a colored outline ring only (does not fill/glow the subject body). Pass `"color": [R,G,B]` (or `"rgb"`). `glow_border` / `glow_line_border` take px `width`/`blur` or `width_ratio`/`blur_ratio` (fractions of the short side; the ratio path grows the mask with flat-cost blur+threshold, since `MaxFilter` cost grows with width²).
- `posterize` flattens channels to N levels; `ink_edges` draws comic outlines from a difference of Gaussians; `halftone` renders a mono or CMYK dot screen (own grey-component-replacement separation, since Pillow's RGB→CMYK leaves K empty; processed at ≤ 2400 px long edge and resized back, pitch enlarged when a screen would exceed 160k dots); `paper_texture` adds seeded grain, stains and fade (tone steps as point tables, grain tiled in place, stain grid follows aspect ratio). `halftone`/`ink_edges` flatten RGBA onto paper/white before analysing tone, so pixels under transparency never print. All sizes are fractions of the short side; at 25 MP these presets peak at ~0.5–0.65 GB.
- `color_grade` folds white balance, exposure, contrast curve, black lift and highlight shoulder into per-channel point tables (flat cost), then runs split toning / saturation / vibrance with numpy in horizontal strips of ≤ 1 MP so a 61 MP frame stays bounded (~1.6 GiB peak per grade preset incl. the HD step); out-of-gamut pixels are scaled back along their own luma rather than clipped per channel. `vignette` builds its mask at ≤ 256 px and scales it up. `bloom` / `halation` blur a highlight mask on a ≤ 1024 px copy and screen it back; `light_leak` is generated at ≤ 256 px; `blur` shrinks before large radii and does a normalised (weighted) blur for RGBA and `exclude` masks; `chromatic_aberration` zooms the R/G channels about the centre; `film_dust` draws seeded specks/hairs/scratches sized to the short side — all keep cost roughly flat at DSLR sizes.
- `tone_curve` turns `[in, out]` control points into a monotone cubic (Fritsch–Carlson) table per channel (master, then R/G/B) and applies it as one point table. `shadows_highlights` bends luma with a per-pixel gamma weighted by a tone mask (pixel luma mixed with a self-guided filter whose box-averaged coefficients are fitted at ≤ 1024 px and applied to full-res luma — regions move together, hard edges get no halo), scales RGB by the luma ratio and gamut-fits like `color_grade` (shared `_fit_gamut`), in ≤ 1 MP strips. `motion_blur` averages up to 96 integer-shifted copies along `angle` on an edge-padded ≤ 1600 px working copy (≤ 1024 with `LIGHTWEIGHT=1`; premultiplied for RGBA), then scales back; `freeze` composites the sharp source on top; `exclude` (runner resolves the layer like `blur`, via `_run_excluding`) zero-weights the grown subject hole, falling back to the plain streak deep inside it. Per-pixel grading strips (`_GRADE_STRIP_PIXELS`) are 1 MP so each pass stays near 100 MB.
- `sticker_outline` draws a solid outline sized by `width_ratio` × short side via blur + threshold (cost independent of width; round corners).
- `extract_subject` with `"require_clear_subject": true` (opt-in; the doodle presets use it) falls back to an empty subject + untouched background when `is_reliable_cutout` rejects the rembg mask, so the preset degrades to "no cutout" instead of a smeared shape. Rejected when solid alpha is < 0.3% of pixels, or when soft pixels *outside* a band around the solid body outnumber solid pixels (band = max(4% of short side, 0.75 × body equivalent radius)), so hair/fur hugging the body is accepted. Presets without the flag keep the raw mask. `"single_subject": true` (opt-in; doodle presets) then runs `keep_main_subject`: it labels solid islands on a working mask capped at 256 px short / 1024 px long side (flood fill seeded via `getbbox`, after a 1.5% merge dilation) and keeps every bottom-touching island ≥ 25% of the largest — else just the largest — plus a 3% soft-edge band, so rembg's second salient object (e.g. a framed picture behind a person) stays in the untouched background.
- `draw_text` paints `text` onto a layer. Use `"$text"` for user caption, or `"$datetime"` / `"$date"` / `"$time"` for stamps — the photo's EXIF capture time (`DateTimeOriginal` → `DateTimeDigitized` → `DateTime`, via `apply_preset.photo_datetime`), else apply time. Common params: `font_size`, `color`/`rgb`, `align` (`center`/`top`/`bottom`/`top_left`/`top_right`/`bottom_left`/`bottom_right`), `font_style` (`sans`/`flow`/`stamp`), optional `font_path` (TTF/OTF/TTC, overrides style), `margin`, `x`/`y`, `stroke_width`; `font_size_ratio` / `margin_ratio` / `stroke_ratio` (fractions of the short side) override the px values so text keeps its proportions at any resolution. Text wider than 90% of the layer shrinks straight to the fitting size. Poster-title extras render the text on its own layer: `scale_y` stretches it, `box` (`frame`/`double`/`corners`/`label`) draws a thin box around the inked glyphs, `angle` tilts it, and `glow_ratio` (capped at 0.05 of the short side; fixed brightness, not a preset knob) screens a blurred halo (`glow_color`) under it before pasting. With `x`/`y` the same layer path is used, so these extras still apply. Named `font_style`s for posters resolve through `filters._DISPLAY_FONT_CANDIDATES`: system Impact / Brush Script when installed, else bundled fonts in `backend/fonts/` (OFL / Apache, licences alongside); `scribble` is bundled Nanum Pen Script (loose pen handwriting); `graffiti` / `wet_paint` / `spray` are bundled OFL graffiti fonts (Sedgwick Ave Display, Rubik Wet Paint, Rubik Spray Paint); `neon_lines` and `marquee` fonts are caps-only.
- `selective_color` boosts one HSV hue band (`hue` by degrees, name or [r,g,b]; smooth `width` falloff; near-greys weighted down) and scales the saturation of everything else by `others`; numpy in ≤ 1 MP strips like `color_grade`.
- `place_on_canvas` puts a layer on a larger solid canvas (`scale`, `fill`, `layout`: `polaroid` or `center`).
- `draw_text` can centre text on a point (`center_x` / `center_y`, fractions of the frame) and cap its width (`max_width_ratio`), so titles sit inside shapes or run vertically along an edge; `uppercase: true` forces capitals.
- `crop_aspect` centre-crops to a film / print ratio (e.g. Instax Mini [46, 62], Square [1, 1], Wide [99, 62]); `place_on_canvas` `margins` sets each card border independently (fractions of the photo's short side) for instant-film cards.
- `draw_shape` draws one basic shape (circle / square / triangle / diamond / star / heart) at fractional `x`/`y` with a short-side-relative `size`; `clear: true` gives a transparent mask layer for `clip_to`.
- `text_pattern` fills a layer with `$text` repeated as `TEXT.TEXT.` rows (sizes cycle per row; `gap_ratio` packs rows by ink height for even gaps; `transparent` leaves only the letters). `half_mask` keeps the left or right side of a layer, split through the `around` layer's alpha centre. `clip_to` keeps a layer only inside another layer's alpha. `blend` is `composite` with a blend mode (`multiply`, `screen`, …) and opacity (two-layer handler `_run_blend` in the runner, like `_run_composite`).
- `circle_backdrop` paints one filled, semi-transparent disc (`size` / `offset_y` / `softness` as fractions of the short side) centred like `doodle` (`anchor: subject` + `around`), optionally capped at `subject_fit` × the subject bbox's long side; an empty subject layer makes it a no-op. It draws only the disc's region, so cost follows the disc, not the frame.
- `doodle_frame` draws a hand-drawn border just inside the edges (`line`/`double`/`dashes`/`dots`/`zigzag`/`waves`/`corners`) into a one-channel mask (2× supersampled up to 4 MP) and paints the ink through it onto a single copy — about one image copy + 1 byte/pixel extra (≈ +0.3 GB at 61 MP).
- `doodle` draws one hand-drawn doodle (`style`: `xo`/`rings`/`wiggles`/`stars`/`hearts`/`arrow`/`sun`/`cloud`/`zigzag`/`dots`/`flower`/`spiral`/`bolt`) with seeded wobble. It draws only the doodle's neighbourhood (not a full-frame layer), 2× supersampled when that region is ≤ 4 MP and 1× above, so a 25 MP upload stays bounded; `count` is capped at 12. Sizes are fractions of the short side. Its runner (`_run_around`, shared with `circle_backdrop`) accepts an optional `around` layer so `anchor: subject` centres on that layer's alpha bbox. The same layer drives `avoid_subject` (corner/edge anchors flip to a mirror the subject doesn't cover; `avoid_busy` also skips cluttered background, scored on a blurred ≤128 px edge map); `color: "auto"` picks dark or white ink from the region's mean luma.
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
  - Tone curves & motion (`ar: non-square`, `text_input: no`): HD → `shadows_highlights` → `tone_curve` → `color_grade` → optional `vignette` / `bloom` / `sharpen` / grain — `print_film_2383`, `cross_process`, `hdr_clarity_pop`, `bleach_bypass`, `mocha_moody`, `lavender_dusk`, `hdr_noir_mono` (grayscale), `mint_pastel_film`; no HD: `extract_subject` → `motion_blur` on `subject` (`shutter_drag`, trailing streak + `freeze`) or `background` (`speed_pan`, with `exclude: subject`) → `composite` → curves grade; `radial_swirl` swaps the streak for `radial_blur` (`mode: spin`, 14°) on `background`, centred on the subject's alpha centroid via `exclude: subject`, then `composite`; `twirl_vortex` / `water_ripple` / `squiggle_wave` / `liquid_spill` use `warp` (`twirl` / `ripple` / `wave` / `liquid`) on `background` instead — a sharp displacement centred the same way, with the cut-out hole refilled from its surroundings first and samples that land behind the subject reflected outward past its outline
  - RGB-curve film looks (`ar: non-square`, `text_input: no`, HD pass 1920 / denoise 0.3): HD → optional `shadows_highlights` → per-channel `tone_curve` (master + red / green / blue) → `color_grade` saturation / vibrance → optional `vignette` → grain via `paper_texture` (`tint` 0) — `vista_red_film`, `golden_consumer_film`, `green_cast_film`, `classic_slide_64`, `expired_film`
  - Poster titles (`ar: non-square`, `text_input: yes`, default `TITLE` — `MIDNIGHT DRIVE` / `LEVEL UP` / `Neon Nights` for the retrowave / mission-passed / neon-nights titles — limit 16): `extract_subject` → background grade / `selective_color` → `draw_text` `$text` on the background (tall `scale_y`, optional `angle` / `glow_ratio` / `box`) → `composite` subject on top → optional finish (`halation` / `vignette` / grain) — `poster_title_yellow_pop`, `poster_title_blue_pop`, `retro_70s_poster`, `brush_script_poster`, `neon_nights_script`, `mission_passed_title`, `wanted_stencil_title`, `retrowave_neon_title`, `art_deco_marquee`, `velvet_ticket_title`
  - Subject spotlight (`ar: non-square`, `text_input: no`, no HD): `extract_subject` → `color` + white `overlay` on `background` → `circle_backdrop` behind the subject → `sticker_outline` on `subject` → `composite` — `red_halo_spotlight`
  - Flash look (`ar: non-square`, `text_input: no`, no HD): `extract_subject` (`single_subject: false`, `require_clear_subject: true`) → dark cool `color_grade` + `vignette` on `background` (gated by `requires_layer: subject`, `min_coverage: 0.04`) → bright cool `color_grade` + `tone_curve` + small `bloom` on `subject` → `composite` → `chromatic_aberration` → grain — `digicam_flash`
  - Light gel (`ar: non-square`, `text_input: no`, no HD): `extract_subject` (`single_subject: false`) → `color` + blue `tone_curve` + slight darken (`color_grade`) on `background` → red-highlight `tone_curve` on `subject` → `composite` — `red_gel_portrait`; the same recipe with other colour pairs (subject whites → a light gel shade, background → a contrasting tint) — `amber_teal_gel`, `ice_gel_orange`, `pistachio_gel_rose`, `sky_gel_amber`, `coral_gel_lagoon`
  - Typographic split (`ar: non-square`, `text_input: yes`, default `DREAM`, limit 20, no HD): `extract_subject` → `half_mask` (left half of `subject`, split at its centre) → white left half via `overlay` + `half_mask` + `composite` → transparent `text_pattern` of `$text` → `clip_to` the subject's left half to the letters → `composite` — `split_word_portrait`
  - Shape windows (`ar: non-square`, `text_input: no`, no HD): `extract_subject` → white `overlay` canvas → four `draw_shape` (circle / square / square / circle, one per quadrant, `clear` mask) → `clip_to` the original photo to the shapes → `composite` onto the canvas → `composite` the subject on top — `shape_window_portrait`
  - Instant film (`ar: non-square`, `text_input: yes`, empty default, limit 24, no HD): `crop_aspect` to the Instax film shape → `color_grade` (± `grayscale` / `bloom`) → `vignette` → grain → `place_on_canvas` with Instax card `margins` → `draw_text` `$text` caption (`scribble`) in the bottom band — `instax_mini_classic`, `instax_square_sunny`, `instax_wide_cool`, `instax_monochrome`, `instax_sky_flash`
  - Text + shape overlays (`ar: non-square`, `text_input: yes`, no HD): `extract_subject` → background treatment (grade / `halftone` / `text_pattern` wall / canvas + `clip_to` window) → `draw_shape` (sun, diamond, circle, neon square) → `composite` → `draw_text` `$text` (bottom, top, top-left caption box, or vertical via `center_x`/`center_y` + `angle`) — `synthwave_sun`, `diamond_editorial`, `word_wall_poster`, `neon_frame_sign`, `pop_art_panel`
  - Street graffiti (`ar: non-square`, `text_input: yes`, limit 16, no HD): `extract_subject` → wall treatment on `background` (grade / `posterize` / `paper_texture`) → `$text` as graffiti on the wall (`graffiti` / `wet_paint` / `spray` / `poster` fonts; vertical column, top masthead, sticker `box: label`, or hollow outline via two empty `draw_shape` layers + `clip_to` `invert`) → `doodle` crown / arrow / stars / bolt → `composite` — `graffiti_drip_column`, `graffiti_throwup_masthead`, `graffiti_sticker_slap`, `graffiti_outline_mural`, `graffiti_outline_tower`
  - Leonardo codex doodles (`ar: non-square`, `text_input: no`, no HD): `extract_subject` → paper-toned background (sepia / blue-grey / rose duotone `tone_curve` + `paper_texture`) → several `codex_doodle` elements (mirror-written `notes` + diagrams such as `aerial_screw`, `parachute`, `optics`, `vitruvian`, `bird_wing`) with `avoid_subject` or subject-anchored sizing → `composite` — `codex_chalk_sepia`, `codex_blueprint`, `vitruvian_study`, `da_vinci_wings`; `inventors_notebook` instead pastes the photo on a page (`place_on_canvas`) and draws in the margins
  - Border doodles (`ar: non-square`, `text_input: no`, no cutout, no HD): optional colour treatment → `doodle` marks at edge `x`/`y` and/or `doodle_frame` — `marker_frame_doodle`, `sunny_sketchbook_doodle`, `neon_doodle_nights`, `chalkboard_doodle`, `love_notes_doodle`, `retro_70s_doodle`, `comic_pop_doodle`, `scrapbook_doodle`, `cyanotype_doodle`, `confetti_pastel_doodle`
  - `doodle_halo_rings` — extract → white `sticker_outline` → `doodle` rings around subject + stars (top-left) on background → composite (`ar: non-square`, `text_input: no`)
- Example CLI: `python backend/helpers/apply_preset.py photo.jpg -p bw_bg_glowing_subject -o out.png`
- Human/agent guide: `backend/presets/PRESETS.md`
- New-preset workflow skill: `.cursor/skills/create-preset/SKILL.md`

### Preset metadata database

- Location: `backend/database/` (SQLite file `presets.local.db`, same pattern as a lightweight local store; `LOCAL_STUDIO_DB` overrides the file path via `init_db.default_db_path()` — Docker sets `/data/presets.local.db` on a volume). The file is **not committed** (gitignored):  each install keeps its own `popular` counts, so `git pull` can't conflict on it. `prepare_db.py` (run on every backend container start) runs `init_db()` + `migrate_schema()` + `seed_default_presets()`, which inserts any shipped preset that is missing and syncs metadata of existing ones without touching counts; the `defaults` list in `seed_default_presets()` is the source of truth for shipped presets. `presets.db` stays committed but **frozen** (legacy: never written, never change or delete it) so clones from before this change can `git pull` cleanly; its rows and counts are copied into `presets.local.db` the first time that file is created.
- Table `presets`: `preset_id` (PK auto), `preset_name`, `preset_path`, `keywords` (JSON list), `ar` (`square` or `non-square`, default `non-square`), `text_input` (`yes` or `no`, default `no`), `default_text` (default `''`), `text_character_limit` (integer, default `0`, max 200), `created_date` (auto `datetime('now')`). Existing DBs gain `ar` and text columns via `migrate_schema()`. `list_presets()` returns rows `ORDER BY preset_id DESC` (newest first).
- Table `popular`: `preset_id` (PK + FK to `presets.preset_id`, `ON DELETE CASCADE`), `used_count` (integer, default `0`). One row per preset; `list_popular()` / `GET /api/presets/popular` return `{ preset_id, preset_name, used_count }` ordered by `used_count DESC`. Existing DBs gain the table (and a 0-count row per preset) via `migrate_schema()`.
- Service functions: `backend/database/db_ops.py` (`add_preset`, `list_presets`, `search_presets_by_keyword`, `get_preset_by_id`, `update_preset`, `delete_preset`, `seed_default_presets`, `list_popular`, `increment_used_count`, `increment_used_count_by_name`).
- Keyword search API: `GET /api/presets/search?q=…` → case-insensitive substring match against each preset’s `preset_name` and keywords (`services/preset_search.py` + `routes/search.py`). Returns `ar` plus text-input metadata, newest `preset_id` first.
- Download-count API: `POST /api/presets/use` increments `popular.used_count` for a `preset_name` (`services/preset_popular.py` + `routes/popular.py`). Unknown names return **404**.
- The backend container runs `prepare_db.py` (`init_db()` + migrate + seed shipped presets) on every start.

### CORS

- None. The browser only reaches the API same-origin through the frontend's nginx proxy, and the backend has no host port, so `main.py` installs no CORS middleware (cross-origin calls are refused by the browser).

## Running (Docker)

`docker compose up -d --build` (`compose.yaml`, project `local-studio`) is the only way to run the app — there is no host Python environment:

```
browser ──▶ host :5500 ──▶ frontend (nginx :8080) ──studio-internal──▶ backend (uvicorn :8000)
                            ├─ static site (index.html, studio.html, js/, css/, icons/, previews/)
                            └─ /api/*, /health → proxy_pass http://backend:8000   (script.js API_BASE = "")
```

- **Networks:** `studio-internal` is `internal: true` (no published ports, no internet egress) and holds both containers; the backend is *only* there and has `expose: 8000` but no `ports:`, so the API is reachable solely through the frontend proxy. The frontend also joins `studio-edge` to publish `${FRONTEND_PORT:-5500}:8080`. Only `/api/` and `/health` are proxied — FastAPI's `/docs` / `/openapi.json` are not exposed.
- **Backend image** (`docker/backend/Dockerfile`): `python:3.12-slim-bookworm`, `backend/requirements.txt` + `backend/helpers/requirements.txt`. Because the container has no internet, models are baked in at build time: the repo's `model/realesrgan/*.pth` are copied into `LOCAL_STUDIO_MODELS=/opt/local-studio/models` (sha256-matched, so `upscale_model.py` never downloads) and ONNX graphs are pre-built for the denoise strengths presets use (0.3, 0.5); rembg `u2net` + `u2netp` are fetched into `REMBG_HOME=/opt/local-studio/rembg`. Runs as uid 10001, `cap_drop: ALL`, `no-new-privileges`; start = `prepare_db.py` then a single uvicorn worker (the API serialises image jobs). DB on the `studio-data` volume (`LOCAL_STUDIO_DB=/data/presets.local.db`; first start copies the committed legacy `presets.db` counts). `LIGHTWEIGHT` comes from `.env`.
- **Frontend image** (`docker/frontend/Dockerfile` + `nginx.conf`): `nginxinc/nginx-unprivileged:1.27-alpine` (non-root, port 8080), `Cache-Control: no-cache` (browsers revalidate JS / CSS on every load), `client_max_body_size 101m` (API cap 100 MiB), 600 s proxy timeouts for slow AI edits, Docker DNS re-resolution so a restarted backend is found again. Waits for the backend health check before starting.
- **Dev image** (`dev` stage of the backend Dockerfile, compose service `dev`, profile `dev`): the backend image plus `test-suite/requirements.txt`, the repo bind-mounted at `/repo`, `network_mode: none`. `docker compose run --rm dev` runs the test suite; `docker compose run --rm dev python <script> …` runs CLI helpers (`apply_preset.py`, `extract_subject.py`) and the create-preset renderer against the working copy.
- `.dockerignore` keeps `.git`, venvs, `docs/`, `test-suite/` (except its `requirements.txt`), logs and any local DB out of the build context.

## Documentation responsibilities

| File | Contents |
|------|----------|
| `README.md` | Setup & run only |
| `CONTEXT.md` | Short agent/contributor briefing |
| `ARCHITECTURE.md` | This file — design & data flow |
| `backend/presets/PRESETS.md` | Helpers, filters, shipped presets, create-preset how-to |
| `.cursor/skills/create-preset/SKILL.md` | Gated agent workflow to design/ship a new preset |
| `docs/` | GitHub Pages pitch (`docs/index.html`); CTAs send users to clone the repo (README setup) |
| `compose.yaml`, `docker/` | How the app runs: frontend (nginx + API proxy) and backend containers on a private network, plus the `dev` tooling service |
| `test-suite/` | Service-function unit tests (pytest); CI via `.github/workflows/test-suite.yml` |

When features change, update these in the same change set (enforced by `.cursor/rules/docs-and-branch-safety.mdc`). When `backend/app/services/` change, update matching `test-suite/` tests **only where necessary**. When helpers/filters/presets/DB metadata change, update `PRESETS.md` as needed.

## Extension points

New edits should follow the same pattern:

1. Add a service function under `backend/app/services/`.
2. Add or update unit tests under `test-suite/` for that service (not the HTTP route).
3. Add a thin route under `backend/app/routes/` and mount it from `main.py`.
4. Add a small client helper under `js/` and wire it from `script.js`.
5. Refresh docs + `docs/index.html` if user-visible behavior changed.

### Testing

- Scope: **service functions only** (`app.services.*`). Do not exercise FastAPI routes here.
- Local: `docker compose run --rm dev` (same Python, packages and models as the backend; working copy mounted).
- CI: `.github/workflows/test-suite.yml` runs the same suite on pull requests (and pushes to `main`).
