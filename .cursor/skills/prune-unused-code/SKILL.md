---
name: prune-unused-code
description: >-
  Audit the Local Studio repo and remove redundant unused code without changing
  UI, product behavior, or workflows. Use when the user asks to prune unused
  code, remove dead code, clean redundant files, or says to go through the
  project repo and remove unused code while leaving UI and functionalities
  unchanged.
disable-model-invocation: true
---

# Prune unused code (no behavior changes)

## How the user will ask

1) go through the project repo
2) remove all the redundant and unnecessary code from the project that is not being used.
3) Do not make any changes to the UI or project functionalities and workflows

Treat close paraphrases the same (e.g. “delete dead code”, “remove unused exports”, “clean redundant code but don’t change behavior”).

## Hard rules

- **No UI changes** — do not edit layout, styling, copy, markup structure, or visual behavior in `index.html`, `docs/`, `css/`, `icons/`, or frontend JS **except** to delete proven-unused symbols/imports that have zero effect on runtime UI.
- **No functionality or workflow changes** — keep the same user flows, APIs, CLI helpers, scripts, presets, and gallery behavior. Prefer keeping dual-use / secondary surfaces over deleting them.
- **Proof required** — delete only what you can show is unreferenced (grep, import graph, tests, docs, scripts). “Looks unused” or “UI doesn’t call it” is **not** enough when docs/scripts/API still expose it.
- **Gated deletes** — inventory first, show the user a deletion plan, wait for approval, then apply. Do not mass-delete in the same turn as the first inventory unless the user already approved a concrete list.
- **Branch safety** — if on `main`/`master`, create `feature/prune-unused-code` (or similar) before editing.
- Follow repo doc-sync and post-change review rules after meaningful removals.

## Progress checklist

```
Prune-unused-code progress:
- [ ] 1. Orient (CONTEXT + ARCHITECTURE + branch check)
- [ ] 2. Inventory candidates with evidence
- [ ] 3. Filter out protected / intentional surfaces
- [ ] 4. Present deletion plan — wait for user approval
- [ ] 5. Apply approved removals only
- [ ] 6. Verify (tests + smoke) and sync docs if needed
- [ ] 7. Report what was removed / kept / skipped
```

## Step details

### 1. Orient

Read [CONTEXT.md](../../../CONTEXT.md) and [ARCHITECTURE.md](../../../ARCHITECTURE.md).

Map the live surfaces before hunting “dead” code:

| Area | Role |
|------|------|
| `index.html`, `script.js`, `js/`, `css/` | Primary studio UI |
| `docs/` | Pitch site for GitHub Pages (keep unless user asks to change marketing) |
| `backend/app/routes/`, `services/` | HTTP API |
| `backend/helpers/` | CLI + preset pipeline (used by the API and the `dev` container) |
| `backend/presets/`, `backend/database/`, `previews/` | Shipped presets + gallery |
| `compose.yaml`, `docker/` | Build / run (frontend, backend, `dev` tooling) |
| `test-suite/` | Service-function tests |
| `.cursor/skills/`, `.cursor/rules/` | Agent workflows — not product dead code |

### 2. Inventory candidates

Search the repo for redundancy. Typical candidates:

- Unreferenced functions, classes, constants, or modules
- Unused imports / re-exports
- Commented-out code blocks left behind
- Duplicate helpers that are never called
- Orphan files not imported, routed, scripted, tested, or documented as a supported entry point
- Tests that only cover already-removed APIs (only after the code is gone / approved)

For **each** candidate, record evidence:

```
- Path / symbol:
- Why it looks unused:
- References checked: (rg hits, importers, routes, scripts, tests, docs)
- Risk: low | medium | high
- Proposed action: delete file | delete symbol | keep
```

Use ripgrep / codebase search from multiple angles (symbol name, filename, route path, HTML id). Check:

- Frontend imports (`script.js`, `js/*`)
- Backend routers registered in `backend/app/main.py`
- Helpers invoked from `apply_preset.py`, filters, `docker/`, README
- `test-suite/` imports
- Docs: `CONTEXT.md`, `ARCHITECTURE.md`, `README.md`, `PRESETS.md`

### 3. Protected / intentional (do **not** remove without explicit user OK)

These often look “unused by the main UI” but are **in scope** for the product:

- `POST /api/blur` and `js/api.js` → `blurImage` (documented secondary API; UI may not call it)
- `backend/helpers/extract_subject.py`, `download_model.py`, and filter `extract_subject` (preset pipeline + CLI; the backend Dockerfile references them)
- Shipped presets, `previews/**`, DB seed paths
- `compose.yaml` / `docker/` build and run behavior
- Health endpoint and apply-preset / search APIs
- Skills and Cursor rules
- Comments or thin wrappers that exist for clarity/security boundaries

Also **keep**:

- Anything required for a documented workflow even if rarely used
- Public function signatures used by tests
- CSS tied to classes present in HTML (including responsive / reduced-motion variants)

When unsure → **keep** and list under “Skipped (needs decision)”.

### 4. Present plan — gate

Show the user a concise plan **before** deleting:

```markdown
## Prune plan

### Proposed deletions
| Item | Evidence | Risk |

### Explicitly keeping (intentional)
| Item | Why |

### Skipped / needs your decision
| Item | Question |

No UI or workflow changes are included.
Reply with which deletions to apply (all / subset / none).
```

**Stop and wait** for approval.

### 5. Apply approved removals only

- Delete only approved items.
- Do not “while we’re here” refactor, rename, restyle, or rewire flows.
- Do not change request/response shapes, validation rules, or preset JSON behavior.
- If removing a backend service symbol, remove or adjust **only** the matching dead tests for that symbol — do not weaken tests for live behavior.
- If docs reference removed code, update docs in the same change set so they stay accurate (allowed doc edits; not a feature change).

### 6. Verify

After edits:

```bash
# Prefer project venv
docker compose run --rm dev
```

Smoke-check mentally (or with a running app if already up):

- Gallery load / search / select preset
- Upload + generate apply-preset
- No accidental route registration loss in `main.py`

If anything fails, fix or revert the related deletion before finishing.

### 7. Final report

Return a short summary:

- Removed (paths/symbols)
- Kept on purpose
- Skipped pending user decision
- Tests run + result
- Confirm: no intentional UI/workflow changes

If nothing was safely removable, say so — an empty prune is a valid outcome.

## Out of scope (reject or ask first)

- Feature work, UX tweaks, dependency upgrades “for cleanup”
- Rewriting working code for style-only reasons
- Removing secondary APIs/helpers because the primary UI doesn’t use them
- Large formatting-only diffs
- Deleting `previews/`, presets, or DB data as “unused”

## Example: good vs bad removal

**Good:** An exported JS helper never imported by any module, with zero string references in HTML/tests → delete after plan approval.

**Bad:** Removing `/api/blur` because `script.js` never calls `blurImage` → violates rule 3 (workflow/API still documented and supported).
