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
│    services/image_io.py → decode bytes ↔ Pillow / PNG encode │
│    helpers/apply_preset.py + filters.py → filter pipeline    │
└──────────────────────────────────────────────────────────────┘
```

## Frontend

### Entry points

- `index.html` — full-width two-column UI (Tailwind via CDN, Pop Poster theme in `css/styles.css` — Lilita One brand / Fredoka+Nunito UI, coral CTA, lemon header):
  - **Left (~65%):** search input, **Input square?** yes/no switch, **Popular** mode (off by default; unclick restores newest-first), refresh control beside search, and preset grid (newest first; post-edit preview + name; hover/focus reveals pre-edit original); search reloads the grid from DB name/keyword matches; **No** hides `ar=square` presets.
  - **Right (~35%):** file upload / original preview (enabled after a preset is selected), optional preset text field, then **Generate edit** / **Download**, then edited result.
- `script.js` — wires gallery load (newest first), debounced search (filters gallery), selection, upload unlock, optional text constraints, file pick/drag-drop, generate button, download use-count ping, popular-sort mode (unclick restores newest-first), search-row gallery refresh.
- `js/image.js` — `isImageFile`, object URL create/revoke.
- `js/api.js` — `searchPresets(baseUrl, query)` → match list; `listPopularPresets(baseUrl)` → popular rows; `applyPreset(baseUrl, presetName, file, text?)` → `Blob`; `recordPresetUse(baseUrl, presetName)` → `{ preset_id, used_count }` (also retains `blurImage` for `/api/blur`).

### UX flow

1. Gallery loads from `previews/presets.json` (newest entries first) and renders post-edit thumbnails with pre-edit originals stacked underneath (entries must use a valid `preset_name`, `ar` of `square` or `non-square`, `text_input` of `yes` or `no`, `default_text`, `text_character_limit`, and relative paths under `previews/pre-edit/` and `previews/post-edit/`). Hover or keyboard focus reveals the original.
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
- **Pillow** — image decode / Gaussian blur / PNG encode
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
    init_db.py           # create presets.db
    db_ops.py            # CRUD for preset metadata + download counts
    presets.db           # SQLite file (created by setup/init)
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
| POST | `/api/blur` | `multipart/form-data` field `file` | `image/png` bytes |
| POST | `/api/apply-preset` | `multipart/form-data` fields `preset_name`, `file`, optional `text` (max 200) | `image/png` bytes |

Error responses use FastAPI `HTTPException` with JSON `detail` (e.g. non-image, empty file, unknown preset, decode failure, square-only preset on a non-square image). Oversized uploads/images return **413**. Apply-preset returns **503** when the concurrency gate is full. `POST /api/presets/use` returns **404** for an unknown `preset_name`.

Upload guards (`services/image_io.py`): max **20 MiB** body (`MAX_UPLOAD_BYTES`), max side **8000** px, max **25M** pixels. Preset JSON paths from the DB must resolve under `backend/presets/` (`PresetPathUnsafeError` otherwise). Apply-preset runs off the event loop via `asyncio.to_thread` and allows only **1** concurrent job (`MAX_CONCURRENT_PRESET_JOBS`) so rembg cannot pile up.

### Blur algorithm

- Pillow `ImageFilter.GaussianBlur` with default radius **12** (`DEFAULT_BLUR_RADIUS` in `services/blur.py`).
- Non-RGB(A) modes are converted to RGBA before filtering for stable PNG output.

### Subject extraction helper (CLI only)

- `backend/helpers/extract_subject.py` — local background removal via **rembg** (`u2net` session / onnxruntime).
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
- HTTP: `POST /api/apply-preset` looks up `preset_name` in `presets.db`, loads that JSON path, runs the same runner, returns PNG (`app/services/preset.py` + `app/routes/preset.py`). The route does not choose filters; it passes `preset_name`, the image, and optional `text`. Presets with `"ar": "square"` reject non-square input images (`PresetAspectRatioError` → HTTP **400**). Presets with `"text_input": "yes"` validate `text` against `text_character_limit` (`PresetTextError` → HTTP **400**); omitted text uses `default_text`.
- Built-in filters: `extract_subject`, `brightness`, `color`, `contrast`, `overlay`, `grayscale`, `glow_border`, `glow_line_border`, `composite`, `draw_text`, `place_on_canvas`, `upscale`, `sharpen`, `denoise`, `ai_upscale`.
- `glow_line_border` draws a colored outline ring only (does not fill/glow the subject body). Pass `"color": [R,G,B]` (or `"rgb"`).
- `draw_text` paints `text` onto a layer. Use `"$text"` for user caption, or `"$datetime"` / `"$date"` / `"$time"` for apply-time stamps. Common params: `font_size`, `color`/`rgb`, `align` (`center`/`top`/`bottom`/`top_right`/…), `font_style` (`sans`/`flow`), optional `font_path` (TTF/OTF/TTC, overrides style), `margin`, `x`/`y`, `stroke_width`.
- `place_on_canvas` puts a layer on a larger solid canvas (`scale`, `fill`, `layout`: `polaroid` or `center`).
- Shipped presets:
  - `bw_bg_glowing_subject` — extract → grayscale background → `glow_line_border` on subject → composite (`text_input: no`)
  - `polaroid_memory` — soft warm grade → `$datetime` stamp → 1.4× white polaroid mat → flow `$text` caption (`ar: square`, `text_input: yes`)
  - `warm_faded_print` — lower contrast → muted color → slight lift → cream-amber overlay (`ar: non-square`, `text_input: no`)
  - `full_hd` — `ai_upscale` to 1920 px long edge, denoise 0.5 (`ar: non-square`, `text_input: no`)
  - `4k_crisp` — `ai_upscale` to 3840 px long edge, denoise 0.3 → light `sharpen` → contrast ×1.04 (`ar: non-square`, `text_input: no`)
- Example CLI: `python backend/helpers/apply_preset.py photo.jpg -p bw_bg_glowing_subject -o out.png`
- Human/agent guide: `backend/presets/PRESETS.md`
- New-preset workflow skill: `.cursor/skills/create-preset/SKILL.md`

### Preset metadata database

- Location: `backend/database/` (SQLite file `presets.db`, same pattern as a lightweight local store).
- Table `presets`: `preset_id` (PK auto), `preset_name`, `preset_path`, `keywords` (JSON list), `ar` (`square` or `non-square`, default `non-square`), `text_input` (`yes` or `no`, default `no`), `default_text` (default `''`), `text_character_limit` (integer, default `0`, max 200), `created_date` (auto `datetime('now')`). Existing DBs gain `ar` and text columns via `migrate_schema()`. `list_presets()` returns rows `ORDER BY preset_id DESC` (newest first).
- Table `popular`: `preset_id` (PK + FK to `presets.preset_id`, `ON DELETE CASCADE`), `used_count` (integer, default `0`). One row per preset; `list_popular()` / `GET /api/presets/popular` return `{ preset_id, preset_name, used_count }` ordered by `used_count DESC`. Existing DBs gain the table (and a 0-count row per preset) via `migrate_schema()`.
- Service functions: `backend/database/db_ops.py` (`add_preset`, `list_presets`, `search_presets_by_keyword`, `get_preset_by_id`, `update_preset`, `delete_preset`, `seed_default_presets`, `list_popular`, `increment_used_count`, `increment_used_count_by_name`).
- Keyword search API: `GET /api/presets/search?q=…` → case-insensitive substring match against each preset’s `preset_name` and keywords (`services/preset_search.py` + `routes/search.py`). Returns `ar` plus text-input metadata, newest `preset_id` first.
- Download-count API: `POST /api/presets/use` increments `popular.used_count` for a `preset_name` (`services/preset_popular.py` + `routes/popular.py`). Unknown names return **404**.
- `./scripts/setup.sh` runs `init_db()` and seeds shipped presets (`bw_bg_glowing_subject`, `polaroid_memory`, `warm_faded_print`).

### CORS

- Development CORS allows all origins so any local static host can call the API. Tighten this before production deployment.

## Local run

- `./scripts/setup.sh` creates `backend/.venv` (or recreates it if relocated/broken), installs deps, and initializes the preset DB.
- `./scripts/run.sh` starts uvicorn on `0.0.0.0:8000` and a static frontend on port `5500` via the venv Python; fails fast if deps are missing or ports are taken.

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
| `scripts/run.sh` | One-command API + frontend start |
| `test-suite/` | Service-function unit tests (pytest); CI via `.github/workflows/test-suite.yml` |

When features change, update these in the same change set (enforced by `.cursor/rules/docs-and-branch-safety.mdc`). When `backend/app/services/` change, update matching `test-suite/` tests **only where necessary**. When helpers/filters/presets/DB metadata change, update `PRESETS.md` as needed.

## Helper scripts

- `scripts/setup.sh` — creates `backend/.venv` (recreates if shebangs/interpreter are broken after a folder rename), installs API + helper requirements, downloads rembg `u2net` into `~/.rembg/`, builds the Real-ESRGAN ONNX model in `~/.local-studio/models/`, initializes `backend/database/presets.db`, ensures scripts are executable.
- `scripts/run.sh` — starts uvicorn (port 8000) and a static file server on the repo root (port 5500) using `backend/.venv/bin/python -m …`; checks deps + free ports; Ctrl+C stops both.

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
