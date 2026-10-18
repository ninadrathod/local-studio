---
name: create-preset
description: >-
  Create a new JSON preset for The Local Studio from a plain-language request (and
  optional reference images). Runs a gated POC → name → keywords → ar → text_input →
  HD pre-pass → ship → gallery preview workflow into backend/presets/, helpers/, the SQLite presets
  database, and previews/. Visual option rounds write comparison HTML under
  previews/_candidates/. Use when the user asks to create a preset, add a new
  look/filter recipe, design an image effect pipeline, or follow the
  create-preset skill.
disable-model-invocation: true
---

# Create preset

Follow this workflow **in order**. Do **not** skip ahead or write final files
until the user finalizes each gated step.

Read [backend/presets/PRESETS.md](../../../backend/presets/PRESETS.md) for the
current helpers, filters, shipped presets, and JSON step format.

## Progress checklist

```
Create-preset progress:
- [ ] 1. Understand the request (and any reference images)
- [ ] 2. Temporary POC presets + _candidates HTML (user picks one)
- [ ] 3. Propose preset names (user picks one)
- [ ] 4. Propose keywords (user finalizes the list)
- [ ] 5. Confirm `ar`: `square` (square-only) or `non-square` (any aspect ratio)
- [ ] 6. Confirm text input: `text_input` yes/no (+ default_text + text_character_limit if yes)
- [ ] 6a. Confirm HD pre-pass: turn the image to HD first (`ai_upscale` as step 0)? yes/no
- [ ] 6b. Font options via _candidates HTML (only if the look uses draw_text)
- [ ] 7. Ship: helpers (if needed) + presets/*.json + database row + docs/tests
- [ ] 8. Gallery previews: search → _candidates HTML → user picks → ship assets
```

## How the user will ask

I will tell what I want in plain language (may also provide some reference images as input)

- understand what I want
- once you understand it, create some temporary preset (as proof of concepts) along with how the output images would look like after applying preset.
- I'll finalize one of the presets.
- then give me potential preset names for the database. I'll finalize one name
- then generate a list of potential keywords that would associate well with the preset, I'll finalize this list
- then confirm whether the preset is square-only (`ar=square`) or works on any image (`ar=non-square`)
- then confirm whether the preset needs user text (`text_input=yes`) — if yes, finalize `default_text` and `text_character_limit` (1–200)
- then ask: "Would you like to turn the image to HD first before applying the new preset?" — if yes, the preset starts with an `ai_upscale` step and the rest of the recipe is re-checked at HD size
- after all of this is finalized, create any helper scripts in helper/ if necessary, add the preset json to presets/, create an entry for this new preset in the database.
- then find open-licensed candidate photos that suit the new preset, prepare square 720×720 previews, show me the applied results, and only after I pick one write `previews/pre-edit/`, `previews/post-edit/`, and `previews/presets.json`.

## Visual options (`previews/_candidates/`)

Whenever you present **visual** choices (POC edits, fonts, gallery photos, color/layout variants), **first** write a comparison page, **then** ask the user to pick a letter. Do not ask them to approve options they have not been able to open.

Text-only gates (preset names, keywords, `ar`, `text_input` / `default_text` / limit) do **not** need HTML.

### Rules

- Root: `previews/_candidates/<round>/` with `index.html` + the images for that round. Rounds: `poc`, `fonts`, `gallery`, or another short slug (`poc-2`, `glow-color`).
- Use [scripts/render_candidates.py](scripts/render_candidates.py). It calls existing helpers — `apply_preset.apply_preset_file` and `filters.draw_text`. Do **not** reimplement apply, text drawing, or a one-off HTML file.
- Run with `backend/.venv/bin/python` from the repo root. Pass `--open` so the page launches.
- Tell the user the path (`previews/_candidates/<round>/index.html`) and wait for a letter (`A` / `B` / …).
- This directory is gitignored scratch. Never copy it into `backend/presets/` or shipped `previews/pre-edit/` / `previews/post-edit/` until the user finalizes. After gallery ships, delete `previews/_candidates/`.

### Commands

```bash
# POC drafts (apply_preset.py per JSON)
backend/.venv/bin/python .claude/skills/create-preset/scripts/render_candidates.py poc \
  --input SAMPLE.jpg --outdir previews/_candidates/poc --text "Sample" --open \
  A=previews/_candidates/poc/draft_a.json B=previews/_candidates/poc/draft_b.json

# Fonts (filters.draw_text). Prefer font_style values the preset can ship (`sans`, `flow`).
backend/.venv/bin/python .claude/skills/create-preset/scripts/render_candidates.py fonts \
  --text "instant memory" --image previews/_candidates/poc/A.png \
  --align bottom --outdir previews/_candidates/fonts --open \
  A=sans B=flow

# Gallery before/after (square crop → 720 → apply_preset.py)
backend/.venv/bin/python .claude/skills/create-preset/scripts/render_candidates.py gallery \
  --preset FINAL_NAME --outdir previews/_candidates/gallery --text "caption" --open \
  --note A="CC0, Photographer, Wikimedia" \
  --crop A=left --crop B=top \
  A=previews/_candidates/gallery/src/a.jpg B=previews/_candidates/gallery/src/b.jpg

# Already-rendered variants
backend/.venv/bin/python .claude/skills/create-preset/scripts/render_candidates.py html \
  --title "Glow color" --outdir previews/_candidates/glow-color --open \
  --original SAMPLE.jpg A=red.png B=cyan.png
```

## Step details

### 1. Understand

- Restate the effect in 2–4 bullets (layers, order, look).
- If reference images were attached, note what to match (tone, border, B&W bg, etc.).
- Note whether the look is **square-only** (`ar=square`) or works on any frame (`ar=non-square`). Ask if that is unclear.
- Note whether the look needs **user text** (caption, title, initials, etc.). If yes, plan a step that uses `"$text"` (usually `draw_text`). Ask if that is unclear.
- Confirm understanding briefly; only ask clarifying questions if the request is ambiguous.
- Prefer existing filters in `backend/helpers/filters.py` before inventing new ones.
- Each JSON step’s `"filter"` is the helper function name; remaining keys are that helper’s parameters. Do **not** invent API if/else for a new look — register the helper in `FILTERS` instead.

### 2. Temporary POC presets + preview images

- Branch safety: if on `main`/`master`, create a feature branch before any repo edits.
- Write **2–3** draft preset JSON files under `previews/_candidates/poc/` (not under `backend/presets/` yet).
- Include `text_input` / `default_text` / `text_character_limit` in drafts when the look needs text; use `"text": "$text"` (or another `$text` param) in the step that consumes it.
- If the user did not provide an input image, use a clear sample (or a prior candidate photo) and say which file you used.
- If a draft is square-only (`"ar": "square"`), apply it to a **square** sample. A non-square input will error.
- Render + open the comparison page with `render_candidates.py poc` (that runs `apply_preset_file`). Optional extra rounds (`html` / another `poc` outdir) if you are varying color, border, or layout.
- Wait until the user **finalizes one** draft (a letter from the HTML). Do not propose DB names yet.

### 3. Preset names

- Offer **4–6** `snake_case` name candidates suitable for `preset_name` / filename.
- Wait until the user **finalizes one name**.

### 4. Keywords

- Offer a keyword list tied to the look (style, colors, subject treatment, use cases).
- Wait until the user **finalizes the list** (they may edit/remove items).

### 5. Aspect ratio (`ar`)

- Offer `square` (preset only works on square images) or `non-square` (works on any aspect ratio; default).
- Wait until the user **finalizes `ar`**. JSON, DB, and gallery `previews/presets.json` must all use that same value.

### 6. Text input

- Offer `text_input: no` (default — no caption field in the UI) or `text_input: yes`.
- If **yes**, also finalize:
  - `default_text` (prefill / fallback when apply omits `text`; may be `""`)
  - `text_character_limit` (integer **1–200**)
- If **no**, set `default_text: ""` and `text_character_limit: 0`.
- When `text_input` is `yes`, at least one step must use `"$text"` in a string parameter (typically `"text": "$text"` on `draw_text`).
- Wait until the user **finalizes** these fields. JSON, DB (`add_preset`), and `previews/presets.json` must all match.

### 6a. HD pre-pass

- Ask exactly: **"Would you like to turn the image to HD first before applying the new preset?"** Default is **no**.
- Skip the question (answer is effectively no) when the finalized POC already starts with `ai_upscale` or is itself an upscale/HD preset.
- If **yes**:
  - Prepend this as **step 0** of the finalized recipe, before every other step (including `extract_subject`):
    ```json
    { "filter": "ai_upscale", "on": "image", "long_edge": 1920, "denoise": 0.5 }
    ```
    `ai_upscale` (`backend/helpers/filters.py`, model code in `upscale_model.py`) is local Real-ESRGAN general-x4v3 (BSD-3-Clause, ONNX in `~/.local-studio/models/`). Offer `long_edge` 1920 (Full HD, default) or 3840 (4K), and `denoise` 0.5 (default) or lower (0.2–0.3) to keep grain. Never shrinks images already at/above `long_edge`.
  - Ship sizes as ratios of the short side (`draw_text` `font_size_ratio` / `margin_ratio` / `stroke_ratio`, glow `width_ratio` / `blur_ratio`, `sticker_outline` `width_ratio`, doodle `size` / `stroke`) — these need no change after upscale and keep the look identical on DSLR-size uploads. Only px params left over (`font_size`, `margin`, `stroke_width`, glow `width` / `blur`) need scaling by roughly `long_edge / POC sample long edge` (e.g. 720 → 1920 ≈ ×2.7); prefer converting them to ratios (px / sample short side).
  - Re-render the recipe with step 0 on the same sample via `render_candidates.py poc` into `previews/_candidates/poc-hd/` (`A` = without HD, `B` = with HD and scaled params) and confirm the look still matches the chosen POC. Wait for the user to confirm `B` (or adjust and re-render).
  - Do the fonts round (6b) on the HD output so text sizes are judged at final resolution.
- If **no**, ship the recipe unchanged.
- Wait until the user **finalizes** yes/no (+ `long_edge` / `denoise` if yes).

### 6b. Fonts (only if a step uses `draw_text`)

- Offer **2–4** options the runner can actually use: `font_style` `sans` or `flow` (via `filters.draw_text`), or a specific `.ttf` path via `font_path` (same helper; add that file to `_font_candidates` if you later ship it as a style).
- Render + open `previews/_candidates/fonts/index.html` with `render_candidates.py fonts` (always `filters.draw_text`). Prefer the chosen POC output as `--image` so the type sits on the look. Match caption placement with `--align` when needed.
- Wait until the user **finalizes one** letter. Ship that `font_style` (or register the TTF in `filters.py` if they picked a file).

### 7. Ship (only after 2–6b are finalized, including the 6a HD answer)

1. Add any new filter ops under `backend/helpers/filters.py` and register them in `backend/helpers/apply_preset.py` `FILTERS` (use `_run_simple` for single-layer ops). Keep helpers modular. Do not add per-filter if/else in the API or the step runner.
2. Write `backend/presets/<final_name>.json` with `name`, `label`, `description`, `ar` (`square` or `non-square`), `text_input` (`yes` or `no`), `default_text`, `text_character_limit`, and `steps`. Each step’s `"filter"` is the helper function name; remaining keys are that helper’s parameters. Use `"$text"` in a param when the step should receive the user string. If 6a was **yes**, `steps[0]` is the finalized `ai_upscale` step and later pixel-sized params are the HD-scaled values.
3. Insert a DB row:

```bash
source backend/.venv/bin/activate
python -c "
import sys
sys.path.insert(0, 'backend')
from database.db_ops import add_preset
print(add_preset(
    '<final_name>',
    'backend/presets/<final_name>.json',
    <final_keywords_list>,
    ar='<square|non-square>',
    text_input='<yes|no>',
    default_text='<default or empty>',
    text_character_limit=<n>,
))
"
```

4. Update `backend/presets/PRESETS.md`, `CONTEXT.md`, and `ARCHITECTURE.md` for the new preset/filter.
5. Add/adjust `test-suite/` coverage when new filter behavior needs it.
6. Run a final apply on a sample image (pass `--text` when `text_input=yes`) and show the shipped output once.

Do **not** write gallery assets under `previews/` in this step — that is step 8.

### 8. Gallery previews (only after step 7)

Understand what the shipped preset does, then pick photos where that effect actually looks good (subject cutout, color vs B&W, silhouette + glow, caption placement, etc.). Subject matter can be anything that fits the look — scenic, street, portrait, poster/music-cover vibe — not limited to landscapes.

1. **Search** for several **open-licensed** photographs on the internet that would show this preset well. Prefer CC0 / CC BY / CC BY-SA (e.g. Wikimedia Commons) or other clearly free licenses. Never use unlicensed stock. Verify license + photographer/source for each candidate.
2. **Download** into `previews/_candidates/gallery/src/` (do not overwrite shipped `pre-edit/` / `post-edit/` yet).
3. **Render** with `render_candidates.py gallery` (square-crop → **720×720** → `apply_preset_file` on the shipped preset; pass `--text` when `text_input=yes`). Default crop is **center**. If the subject sits off-center, pass `--crop A=left` / `right` / `top` / `bottom` so the kept square still frames it. Open the HTML and **ask which letter is best**. Wait for the user to finalize one.
4. **Once finalized**, write:
   - `previews/pre-edit/<final_name>.*` — the chosen square 720×720 source
   - `previews/post-edit/<final_name>.png` — same crop after the preset. If the preset has the HD pre-pass, Lanczos-downscale this file by the HD factor (e.g. 1920 → 720) so the gallery asset stays light and the same size it would be without HD
   - prepend `{ "preset_name", "ar", "text_input", "default_text", "text_character_limit", "pre_edit_image", "post_edit_image" }` to `previews/presets.json` (newest first)
   - record source + photographer + license in `previews/CREDITS.md`
   - delete `previews/_candidates/`

## Rules

- Never commit rembg/ONNX weights; models stay in `~/.rembg/` (rembg) and `~/.local-studio/models/` (Real-ESRGAN for `ai_upscale`).
- Do not invent extra HTTP routes unless asked — apply by DB name via existing `POST /api/apply-preset` (optional multipart `text` when needed).
- Do not finalize name/keywords/`ar`/text fields/HD pre-pass/fonts/DB/files/gallery assets before the user confirms each gate.
- HD pre-pass means one `ai_upscale` step at index 0 — reuse that helper; never write a separate upscaler or call a cloud API.
- Keep `ar` and text-input fields in sync across preset JSON, `add_preset(...)`, and `previews/presets.json`.
- Gallery previews must be open-licensed, square **720×720**, with matching pre-edit and post-edit crops.
- If a needed look cannot be done with current filters, say so in step 1–2 and propose a small new helper filter before POC.
- Studio UX assumes **select preset first**, then upload; presets with `text_input=yes` show a constrained text field before generate.
- Prefer `backend/helpers/apply_preset.py`, `filters.py` (`draw_text`, `_font_candidates`), `extract_subject.py`, and `database/db_ops.py` over new one-off scripts.
