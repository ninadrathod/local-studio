# The Local Studio

Upload an image, send it to the API, and get a blurred copy back.

## Requirements

- Python 3.12+ (3.14 works with the pinned dependencies)
- A modern browser (Chrome, Firefox, Safari, or Edge)

## Quick start (scripts)

1. Clone the repository:

```bash
git clone https://github.com/ninadrathod/local-studio.git
cd local-studio
```

2. Set up the project (creates `backend/.venv`, installs API + helper deps, downloads the rembg `u2net` model into `~/.rembg/`, prepares the Real-ESRGAN upscale model in `~/.local-studio/models/`, and initializes `backend/database/presets.db`):

```bash
./scripts/setup.sh
```

3. Run the API and frontend:

```bash
./scripts/run.sh
```

4. Open [http://localhost:5500](http://localhost:5500), pick a preset, upload an image, and click **Generate edit**.

Press **Ctrl+C** in the terminal to stop both servers, or free the ports anytime with:

```bash
./scripts/stop.sh
```

If `./scripts/run.sh` reports a broken virtualenv or a port already in use, re-run `./scripts/setup.sh` (it recreates a relocated/broken `backend/.venv`) and run `./scripts/stop.sh` (or override with `API_PORT=…` / `FRONTEND_PORT=…`).

## Run tests

Service-function unit tests (not HTTP/API) live in `test-suite/` and run on PRs via GitHub Actions.

```bash
source backend/.venv/bin/activate
pip install -r test-suite/requirements.txt
pytest test-suite/ -v
```

## Optional: subject extraction helper

Setup already installs helper deps and pulls the `u2net` model. To run:

```bash
source backend/.venv/bin/activate
python backend/helpers/extract_subject.py path/to/photo.jpg -o subject.png
```

Model weights live in `~/.rembg/` (rembg) and `~/.local-studio/models/` (Real-ESRGAN for the HD presets), outside the repo; `*.onnx` is gitignored.

## Optional: JSON presets

Presets are JSON step lists in `backend/presets/`.

```bash
source backend/.venv/bin/activate
python backend/helpers/apply_preset.py path/to/photo.jpg -p bw_bg_glowing_subject -o out.png
```
