<!-- Migrated from .cursor/rules/docs-and-branch-safety.mdc (Cursor "always apply" rule). Loads unconditionally, same as the original. -->

# Docs sync, branch safety & post-change review

## Before any code or doc edits

1. Check the current git branch.
2. If the branch is `main` or `master`, **create and switch to a new feature branch** before changing files.
   - Name branches like `feature/<short-description>` or `fix/<short-description>`.
   - Example: `git checkout -b feature/add-sharpen-endpoint`
3. Do not commit or push to `main`/`master` directly.

## After meaningful project changes

When you change product behavior, APIs, setup steps, UI flows, or project structure, update **all** of the following that are affected (same change set):

| File | Update when… |
|------|----------------|
| `CONTEXT.md` | Scope, layout, conventions, or local defaults change |
| `ARCHITECTURE.md` | Design, data flow, endpoints, stack, or extension points change |
| `README.md` | Setup, run, or stop instructions change (keep **setup/run only** — no architecture) |
| `backend/presets/PRESETS.md` | Helpers, filters, shipped presets, preset JSON shape, DB metadata, or "how to create a preset" guidance change |
| `.claude/skills/create-preset/SKILL.md` | The gated create-preset workflow (POC → name → keywords → ship) changes |
| `docs/index.html` | Public pitch, diagram, features, or the clone / setup CTA should reflect the new story |
| `compose.yaml`, `docker/` | How the app is built or run changes (images, deps, models, ports, networks, volumes, env, health checks, the `dev` tooling service) |
| `test-suite/` | Backend **service-function** behavior, contracts, or coverage expectations change (not HTTP/API tests) |

### Rules of thumb

- Prefer accurate, concise updates over rewriting unchanged sections.
- `README.md` must remain **instructions only** (clone, install/run, stop). No architecture essays.
- `docs/index.html` stays advertise-level (short, visual); CTAs should send users to **clone the GitHub repo** (the README setup section) and run it locally with Docker — do not link to a hosted app or ask them to fork. Only the owner pushes; users get updates with `git pull` + `docker compose up -d --build`. Keep pitch assets under `docs/` so GitHub Pages (`/docs` source) stays self-contained.
- Keep `compose.yaml` / `docker/` aligned with `README.md` so `docker compose up -d --build` stays the one-command setup/run. There is no host Python environment: run tests with `docker compose run --rm dev`.
- When you change `backend/app/services/` (or add a new service module), update or add matching tests under `test-suite/` in the same change set — **only where necessary**.
- When you change `backend/helpers/` filters, `backend/helpers/apply_preset.py`, `backend/presets/`, or `backend/database/` preset metadata, update `backend/presets/PRESETS.md` (and `CONTEXT.md` / `ARCHITECTURE.md` if layout or contracts changed) in the same change set.
- If a change is purely internal with zero user/setup/API/preset impact, skip doc/script updates — but when in doubt, update `CONTEXT.md`, `ARCHITECTURE.md`, `PRESETS.md` when presets/helpers are involved, and `compose.yaml` / `docker/` if startup changed.

## After all changes are finished — bug, security & UI review

Once the requested work (code + required doc/script updates) is **complete**, review **branch changes** vs `main`/`master` (committed + uncommitted) before ending the turn.

### When to skip review

- **Skip entirely** for pure doc/typo/rule-text edits with no product or script behavior change.

### What to run

1. **Always** (unless full skip): a **fast local/manual** review of the branch diff — correctness, edge cases, API/input validation, auth/CORS, uploads, secrets, deps, XSS.
2. **UI responsiveness** — when the change touches frontend UI (`index.html`, `docs/`, `css/`, `script.js`, `js/`, or other user-facing layout/styles): check that the layout works across screen sizes before ending the turn. Cover at least:
   - **Narrow phone** (~320–390px width)
   - **Tablet / medium** (~768px width)
   - **Desktop** (~1280px+ width)
   - **Short landscape** (optional but preferred when CSS has height-based breakpoints)
   Look for overflow, clipped text/controls, unusable sticky bars, stacked columns that break, and stages/grids that ignore their responsive rules. Prefer resizing the running app or browser tools; if the app isn't running, review the CSS/HTML breakpoints in the diff and call out unverified risks.
3. **Security review subagent** — optional; launch only when the change touches auth, uploads, secrets, network, new endpoints, or user-controlled input. Use `Diff: branch changes`.
4. **Bugbot** — **do not launch**. Never start Bugbot (or relaunch it) unless the user **explicitly** asks for Bugbot in that turn. Prefer the local/manual pass above.
5. **List every finding in one response** — one combined list/table, severity highest first. Columns: **Severity | Location (`file:line`) | Finding | Type** (`bug`, `security`, or `ui`). Do not auto-fix unless asked. If none, say so in one short line.

## Do not

- Skip the branch check because the change "is small".
- Leave docs or scripts describing endpoints, ports, or flows that no longer exist.
- Put deep architecture detail into `README.md`.
- Change `backend/app/services/` without updating `test-suite/` when those changes need test coverage.
- Change helpers, filters, preset JSON, or preset DB behavior without updating `backend/presets/PRESETS.md` when that catalog/how-to is affected.
- End a feature/fix turn without the post-change findings listing (when the skip condition does not apply).
- Skip UI responsiveness checks when frontend layout/CSS/HTML changed.
- Launch Bugbot unless the user explicitly requests it.
- Assume cloud image APIs (e.g. Gemini) are part of this project — image edits use local helpers/presets only.
