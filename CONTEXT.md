# CONTEXT.md — The Local Studio

Short briefing for AI agents and new contributors. Prefer this file for orientation; see `ARCHITECTURE.md` for deeper design.

## What this project is

A local **image editor** for applying JSON presets to photos:

1. User picks a preset from the gallery (post-edit thumbnails from `previews/`; hover — or press-and-hold on touch screens — shows the pre-edit original).
2. Image upload unlocks after a preset is selected. If that preset has `text_input: yes`, a text field appears (default + character limit from the preset).
3. Frontend `POST`s preset name + file (+ optional `text`) to `POST /api/apply-preset`.
4. Backend resolves the preset from SQLite, runs the JSON filter pipeline (each step names a helper + params; `$text` is bound in), returns a JPEG (for JPEG / HEIC uploads) or PNG.
5. Frontend shows (and can download) the result. Clicking **Download** increments `popular.used_count` immediately. The gallery does not reorder until the refresh control beside search is clicked (with **Popular** on). Unclicking **Popular** restores that visit's shuffled order. A page refresh clears in-memory session state.

Repo: https://github.com/ninadrathod/local-studio

## Layout (high level)

| Path | Role |
|------|------|
| `index.html`, `css/landing.css`, `js/landing.js` | Landing page (marketing; four full-screen scenes, links into the studio) |
| `studio.html`, `script.js`, `js/`, `css/styles.css`, `icons/` | Studio UI (preset gallery + upload + generate) |
| `previews/` | Preset gallery assets: `pre-edit/` + `post-edit/` (before/after per DB preset, 720×720 **WebP**, quality 85) + `presets.json` |
| `previews/_candidates/` | Gitignored create-preset comparison HTML (POC edits, fonts, gallery picks) — not shipped |
| `docs/` | GitHub Pages site (custom domain in `docs/CNAME`): the same four-scene landing as `index.html`, self-contained — `docs/css/styles.css` and `docs/js/landing.js` are **copies** of `css/landing.css` / `js/landing.js` (re-copy after editing those), `docs/previews/` holds downscaled JPEG previews + `manifest.json` (`{ count, presets }`) + `CREDITS.md`; every CTA goes to the GitHub repo / fork, never to a hosted app |
| `backend/` | FastAPI app |
| `backend/helpers/` | CLI helpers: subject extraction, local AI upscale model, JSON preset runner |
| `model/` | Real-ESRGAN `.pth` weights (`realesrgan/`, BSD-3-Clause) shipped with the repo |
| `backend/presets/` | JSON image presets (ordered filter steps); see `PRESETS.md` |
| `backend/database/` | SQLite preset metadata (local, gitignored `presets.local.db` + `db_ops.py` + `prepare_db.py`; committed `presets.db` is a frozen legacy copy) |
| `backend/fonts/` | Bundled open-licensed display fonts (OFL / Apache) for `draw_text` `font_style` |
| `.cursor/skills/create-preset/` | Skill: gated workflow to design and ship a new preset (visual rounds → `previews/_candidates/`) |
| `test-suite/` | Unit tests for backend **service functions** (not HTTP/API) |
| `.github/workflows/` | CI (runs `test-suite/` on PRs) |
| `scripts/setup.sh` | Full local setup (venv + deps) |
| `scripts/run.sh` | Start API + frontend in the background (logs in `logs/`) |
| `.env.example` | Settings template; copy to gitignored `.env` (loaded by `run.sh`), e.g. `LIGHTWEIGHT` |
| `scripts/update.sh` | `git pull` → `stop.sh` → `run.sh` (always all three) |
| `README.md` | Setup & run only |
| `ARCHITECTURE.md` | How the system works |
| `.cursor/rules/` | Agent rules (docs sync, branch safety, post-change review) |
| `.cursor/skills/cleanup-after-push/` | After push: checkout main, pull, delete local feature branch |
| `.cursor/skills/commit-draft-pr/` | Commit locally (no push) and draft PR title + description |
| `.cursor/skills/prune-unused-code/` | Audit + remove unused code without changing UI/workflows |

## Key conventions

- Keep code **modular and easy to read** (small modules, clear names).
- Landing page (`index.html`): plain CSS in `css/landing.css` — dark **Orbital** theme (Unbounded / Instrument Sans / JetBrains Mono, brand coral/sky/lemon as neon). No page scroll: `js/landing.js` swaps four scenes (Origin → Protocol → Fusion → Archive) on wheel / swipe / keys with depth transitions; scenes only scroll internally when their content is taller than the viewport. Static only — reads `previews/presets.json`, never the API.
- Studio styling (`studio.html`): plain CSS in `css/styles.css` (no Tailwind) — same **Orbital** theme as the landing page (dark void, glass panels, neon coral/sky/lemon, Unbounded / Instrument Sans / JetBrains Mono). Progress (tracker + step states) is pure CSS `:has()` on page state, so `script.js` stays theme-agnostic; keep every element ID and the `hidden` class that `script.js` uses.
- Backend image work lives in `backend/app/services/`; routes stay thin.
- Service-function tests live in `test-suite/` (pytest); keep them in sync when service behavior changes.
- Do **not** put architecture detail in `README.md`.
- After meaningful product/code changes, update `docs/index.html`, `README.md`, `ARCHITECTURE.md`, `CONTEXT.md`, `scripts/setup.sh` / `scripts/run.sh`, and `test-suite/` as needed.
- **Never commit directly on `main`** — create a feature branch first (see Cursor rule).
- After finishing product/code changes on a branch, the agent must run a thorough **bug + security** review of branch changes (and **UI responsiveness** across phone/tablet/desktop when frontend layout changed) and list **all** findings at once (see `.cursor/rules/docs-and-branch-safety.mdc`).

## Local defaults

- API: `http://localhost:8000`
- Frontend static server: typically `http://localhost:5500` via `scripts/serve_frontend.py` (`http.server` that sends `Cache-Control: no-cache`, so browsers revalidate JS / CSS and never mix an old `styles.css` with a new `script.js`); any static host of the repo root works, ideally with the same header
- Health check: `GET /health`
- Blur endpoint: `POST /api/blur` (multipart field name: `file`)
- Apply-preset endpoint: `POST /api/apply-preset` (multipart fields: `preset_name`, `file`, optional `text`) → JPEG for JPEG / HEIC uploads, else PNG
- Preview endpoint: `POST /api/preview` (multipart field `file`) → ≤ 2048 px JPEG (PNG if transparent); the UI calls it only when the browser can't render the upload itself (HEIC outside Safari, TIFF)
- Accepted uploads: JPEG, PNG, WEBP, GIF, BMP, TIFF, HEIC/HEIF (HEIC via `pillow-heif`)
- Preset search: `GET /api/presets/search?q=…` → JSON list of `{ preset_name, keywords, ar, text_input, default_text, text_character_limit }` (matches name or keywords; newest `preset_id` first)
- Popular / download count: `POST /api/presets/use` form field `preset_name` → `{ preset_id, used_count }`; `GET /api/presets/popular` → `{ preset_id, preset_name, used_count }` sorted by `used_count` descending
- Upload caps (blur + apply-preset): 100 MiB body; images up to 64M pixels / 12000 px side stay at native resolution (full-frame DSLR), larger ones are downscaled to fit (with `LIGHTWEIGHT=1` in `.env` — for low-RAM machines like a 1 GB Raspberry Pi — every input is downscaled to ≤ 2M pixels, `ai_upscale` steps become a plain Lanczos resize (no AI model), and `extract_subject` uses the small `u2netp` model); over 120M pixels is rejected; EXIF orientation and ICC colour (→ sRGB) are applied on load; EXIF stays on the in-memory image (so `$date` / `$time` / `$datetime` stamps show the capture time) but is never written to results; one image job at a time across apply-preset + blur + preview (others get 503 before the upload is read); preset JSON paths must stay under `backend/presets/`
- Apply-preset concurrency: 1 in-flight job (extra requests get **503**)

## Current scope

- Preset gallery (left "Choose a look" console, ~62% width on desktop): heading with a count pill (total, or `shown / total` while filtered) + page-drawn neon-pill scroller (same on desktop, mobile and Firefox; native scrollbar hidden) + search + **Square photo?** yes/no switch + **Popular** mode (off by default) + refresh control beside search + post-edit thumbnails from `previews/presets.json` (shuffled into a fresh random order on every page load); hover/focus (or press-and-hold on touch) reveals pre-edit original; click/tap to select
- Search filters the gallery in place via realtime `GET /api/presets/search?q=…` (DB `preset_name` + `keywords`)
- **Square photo?** **Yes** shows all presets; **No** hides `ar=square` presets
- Gallery default order is a fresh random shuffle on every page load (`previews/presets.json` is stored newest first; `script.js` shuffles it once per load). Search shows only the matches, kept in that same shuffled order. The 5 newest presets (top of the manifest) carry a **New** badge so they stay easy to spot. **Popular** selects popular-sort mode. The search-row refresh reloads the visible gallery from `GET /api/presets/popular` (`used_count` descending). Unclicking **Popular** restores that visit's shuffled order. Download does not reorder the grid.
- Image upload (right, ~35% width on desktop): locked until a preset is selected; clearing the preset clears the upload; then client-side type check + preview
- `/` is the landing page; the studio lives at `/studio.html` (landing CTAs, the HUD "Open studio" link and the final "Explore the presets" CTA all go there; the studio logo / About link go back to the landing)
- Studio layout: HUD header with a 01 Look → 02 Photo → 03 Result tracker; left "Choose a look" console (search, square filter, Popular, gallery); right pipeline of three step cards (selected look + optional text, photo drop zone, result) with Generate / Download between photo and result. Tablet/desktop fit one viewport (gallery scrolls internally); phones (< 768 px) scroll the page — gallery first, then the pipeline
- Preset cards compare by a labelled wipe: hover (or keyboard focus, or press-and-hold on touch) sweeps the original photo in behind a scanning beam and flips the corner tag from **After** to **Before**; a looping mini demo in the gallery header explains it ("Hover" / "Press & hold" by input type) and the first card plays the wipe twice on load
- Generate edit when both preset + file are set → `POST /api/apply-preset` → result + download
- Download click increments `popular.used_count` for the selected preset (`POST /api/presets/use`) without reordering the gallery
- Applying a `ar=square` preset to a non-square image fails with HTTP **400**
- Presets with `text_input: yes` show a text field (`default_text`, `maxlength` from `text_character_limit`, max 200) and send `text` with generate
- Session state is in-memory only (refresh clears upload + edited result)
- Gallery only accepts `preset_name` + `ar` (`square` / `non-square`) + `text_input` (`yes` / `no`) + `default_text` + `text_character_limit` + relative `previews/pre-edit|post-edit/…` paths from `presets.json`
- Server-side Gaussian blur still available via `POST /api/blur` (not the primary UI flow)

Optional helpers:
- `backend/helpers/extract_subject.py` — background removal (rembg / `u2net`)
- `backend/helpers/upscale_model.py` — local AI super-resolution (Real-ESRGAN `realesr-general-x4v3`, BSD-3-Clause): downloads the official release weights (SHA-256 pinned), converts them to ONNX locally (no PyTorch), runs tiled on onnxruntime CPU. Used by the `ai_upscale` filter.
- `backend/helpers/apply_preset.py` — run a JSON preset from `backend/presets/` (also used by the apply-preset API)
- Example presets: `bw_bg_glowing_subject`, `polaroid_memory` (square-only; optional caption via `text_input`), `warm_faded_print` (any aspect ratio; sun-faded color grade), `full_hd` / `4k_crisp` (any aspect ratio; local AI upscale to 1920 / 3840 px long edge), `doodle_corner_xo` / `doodle_halo_rings` (any aspect ratio; white sticker outline on the subject + hand-drawn background doodles), `comic_pop` / `old_newspaper` / `vintage_comic` (any aspect ratio; posterize, halftone dots, ink outlines, paper texture), and ten professional colour grades — `cinematic_teal_orange`, `warm_portrait_film`, `nordic_cool_matte`, `golden_hour_glow`, `emerald_moody`, `fine_art_mono`, `bright_airy`, `vintage_slide_punch`, `blush_rose_pastel`, `blue_hour_noir` (any aspect ratio; HD `ai_upscale` first, then `color_grade` ± `vignette` / grain), and ten Prequel-style looks — `dreamy_glow`, `film_halation`, `film_dust`, `miami_neon`, `prism_glow`, `disposable_flash` (orange `$date` stamp), `portrait_bokeh` (subject cutout + blurred background), `tungsten_night_film`, `muted_chrome_film`, `studio_spotlight` (subject cutout + darkened background) (any aspect ratio; `bloom` / `halation` / `light_leak` / `film_dust` / `chromatic_aberration` / `blur` on top of `color_grade`; HD first except `film_dust` and `disposable_flash`), and ten poster-title looks — `poster_title_yellow_pop`, `poster_title_blue_pop`, `retro_70s_poster`, `brush_script_poster`, `neon_nights_script`, `mission_passed_title`, `wanted_stencil_title`, `retrowave_neon_title`, `art_deco_marquee`, `velvet_ticket_title` (any aspect ratio; subject cutout + `selective_color` background + large `$text` title behind the subject, default `TITLE` (three titles ship sample text: `MIDNIGHT DRIVE`, `LEVEL UP`, `Neon Nights`), max 16 chars), and ten border-doodle looks — `marker_frame_doodle`, `sunny_sketchbook_doodle`, `neon_doodle_nights`, `chalkboard_doodle`, `love_notes_doodle`, `retro_70s_doodle`, `comic_pop_doodle`, `scrapbook_doodle`, `cyanotype_doodle`, `confetti_pastel_doodle` (any aspect ratio; no cutout; colour treatment + simple hand-drawn marks near the edges via `doodle` / `doodle_frame`), and ten tone-curve looks — `print_film_2383`, `cross_process`, `hdr_clarity_pop`, `bleach_bypass`, `mocha_moody`, `lavender_dusk`, `hdr_noir_mono`, `mint_pastel_film` (HD first, then `shadows_highlights` + `tone_curve` + grade), `shutter_drag` (subject streaks behind itself) and `speed_pan` (sharp subject, streaked background), `vista_red_film` / `golden_consumer_film` / `green_cast_film` / `classic_slide_64` / `expired_film` (HD + per-channel RGB-curve film-stock looks), `radial_swirl` (sharp subject, background spun in a circular blur centred behind the subject), `twirl_vortex` / `water_ripple` / `squiggle_wave` / `liquid_spill` (background warped — whirlpool, pond rings, squiggles, spilled-liquid marble — around a sharp subject), `codex_chalk_sepia` / `codex_blueprint` / `vitruvian_study` / `inventors_notebook` / `da_vinci_wings` (Leonardo da Vinci notebook pages — mirror-written notes and hand-inked diagrams on tinted paper) (cutout + `motion_blur`, no HD), and `red_halo_spotlight` (any aspect ratio; cutout with a yellow `sticker_outline`, muted white-washed background, translucent red `circle_backdrop` disc behind the subject), and `digicam_flash` (any aspect ratio; Y2K night-flash look: everyone in front cut out and lit with a cool glossy flash, background dropped to blue-black), and `red_gel_portrait` (any aspect ratio; soft red gel light on the cut-out subject's whites and highlights, muted cool-blue background), `amber_teal_gel` / `ice_gel_orange` / `pistachio_gel_rose` / `sky_gel_amber` / `coral_gel_lagoon` (same gel recipe: subject whites become a light colour shade over a contrasting background tint), and `split_word_portrait` (any aspect ratio; `text_input: yes`, default `DREAM`, max 20: photo split down the subject's middle — left half white with the subject shown through a wall of the user's text, right half the original), and `shape_window_portrait` (any aspect ratio; white canvas with four large circle / square windows onto the photo, one per quadrant, cut-out subject on top), and five instant-film looks — `instax_mini_classic`, `instax_square_sunny`, `instax_wide_cool`, `instax_monochrome`, `instax_sky_flash` (any aspect ratio; cropped to the Instax Mini / Square / Wide shape, graded, mounted on an Instax-proportioned card with an optional handwritten `$text` caption, max 24, no default), and five text + shape overlays — `synthwave_sun`, `diamond_editorial`, `word_wall_poster`, `neon_frame_sign`, `pop_art_panel` (any aspect ratio; cut-out subject over a shape — sun, diamond window, word wall + circle, neon square, pop-art dots — with the user's `$text` as a title, sign or caption), and five street-graffiti looks — `graffiti_drip_column`, `graffiti_throwup_masthead`, `graffiti_sticker_slap`, `graffiti_outline_mural`, `graffiti_outline_tower` (any aspect ratio; cut-out subject in front of a wall painted with the user's `$text` as graffiti — dripping vertical column, top throw-up, sticker slaps, hollow outline mural / tower — plus crowns and arrows; bundled OFL graffiti fonts)
- `backend/database/` — lightweight SQLite file (`presets.local.db`) for preset metadata (name, path, keywords, `ar`, `text_input`, `default_text`, `text_character_limit`) plus `popular` download counts (`preset_id` FK, `used_count`). Ops in `db_ops.py`. The file is local and gitignored (per-install download counts); `backend/database/prepare_db.py` creates/migrates it and seeds shipped presets from `seed_default_presets()`, run by both `./scripts/setup.sh` and `./scripts/run.sh` — so a `git pull` never conflicts on it and new presets appear on the next start. `presets.db` stays committed but **frozen** (legacy: never written, never change or delete it) so clones from before this change can `git pull` cleanly; its rows and counts are copied into `presets.local.db` the first time that file is created.
- `previews/` — static preset gallery assets (`pre-edit/` + `post-edit/` + `presets.json`); wired into the index UI gallery
- Preset catalog + how-to: `backend/presets/PRESETS.md`
- To design/ship a new preset from plain language, use skill `.cursor/skills/create-preset/` (visual option rounds write `previews/_candidates/<round>/index.html` via `scripts/render_candidates.py`, which calls `apply_preset` + `draw_text`)
- To commit locally without pushing and get PR title/description copy, use skill `.cursor/skills/commit-draft-pr/`
- To remove unused/redundant code without changing UI or workflows, use skill `.cursor/skills/prune-unused-code/`

`./scripts/setup.sh` installs helper deps and downloads the `u2net` model into `~/.rembg/` and builds the Real-ESRGAN ONNX model in `~/.local-studio/models/` (both outside the repo; override with `LOCAL_STUDIO_MODELS`). It also recreates `backend/.venv` if the project was renamed/moved and console-script shebangs are stale. `./scripts/run.sh` uses the venv Python directly, starts both servers in the background (`nohup`, logs in `logs/`), returns once the API is healthy, and exits with a clear error if deps are missing or ports `8000`/`5500` are already taken. `./scripts/stop.sh` stops them.
