# The Local Studio — API container (FastAPI + uvicorn).
#
# Build context is the repo root (see compose.yaml). The AI models are baked in at
# build time, so the running container needs no internet access: compose puts it
# on an internal-only network that just the frontend can reach.

FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # Real-ESRGAN weights + the ONNX graphs built from them (helpers/upscale_model.py)
    LOCAL_STUDIO_MODELS=/opt/local-studio/models \
    # rembg subject-cutout models (u2net, and u2netp for LIGHTWEIGHT=1)
    REMBG_HOME=/opt/local-studio/rembg \
    # Live preset DB on the /data volume, so download counts survive rebuilds
    LOCAL_STUDIO_DB=/data/presets.local.db \
    # numba (via rembg → pymatting) caches compiled code. It must stay writable by the
    # runtime user, or numba refuses to load (`cannot cache function … no locator`):
    # it lives under /opt/local-studio, which is chowned to that user below.
    NUMBA_CACHE_DIR=/opt/local-studio/numba

WORKDIR /app/backend

# System fonts that draw_text falls back to on Linux (backend/helpers/filters.py):
# DejaVu Sans for the default `sans` style, Liberation Serif Italic for `flow`
# captions, Liberation Mono Bold for the `stamp` date imprint. The slim base image
# ships no fonts, so without these those styles drop to a tiny fixed bitmap font.
# (Other styles use the open-licensed fonts bundled in backend/fonts/.)
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies (cached layer while only app code changes)
COPY backend/requirements.txt requirements.txt
COPY backend/helpers/requirements.txt helpers/requirements.txt
RUN pip install -r requirements.txt -r helpers/requirements.txt

# Models. The repo ships the Real-ESRGAN weights under model/realesrgan/; placing them
# in the cache dir means upscale_model.py finds them (sha256-checked) instead of
# downloading. Pre-build the ONNX graphs for the denoise strengths the presets use,
# and fetch both rembg models — the only network access, and only during the build.
COPY model/realesrgan/*.pth ${LOCAL_STUDIO_MODELS}/
COPY backend/helpers/upscale_model.py helpers/upscale_model.py
RUN cd helpers \
    && python -c "import upscale_model as m; [m.ensure_model(d) for d in (0.3, 0.5)]" \
    && python -c "from rembg import new_session; new_session('u2net'); new_session('u2netp')"

# App code
COPY backend/ .

# Unprivileged runtime user. It owns /opt/local-studio (models — another denoise
# strength can be built from the bundled weights at runtime — and the numba cache)
# and /data (the DB volume).
RUN useradd --uid 10001 --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin studio \
    && mkdir -p /data \
    && chown -R studio:studio /data /opt/local-studio
USER studio

VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=40s --retries=5 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"]

# Create / migrate the DB and add any new shipped presets, then serve.
# One worker: the API runs one image job at a time (others get HTTP 503).
CMD ["sh", "-c", "python database/prepare_db.py && exec python -m uvicorn app.main:app --host 0.0.0.0 --port 8000"]


# ── Dev tooling (compose service `dev`, profile "dev") ────────────────────────
# Same Python, packages and baked-in models as the API, plus the test deps. The repo
# is bind-mounted at /repo, so the test suite and the create-preset renderer run
# against your working copy: `docker compose run --rm dev` runs the tests.
FROM runtime AS dev
USER root
COPY test-suite/requirements.txt /tmp/test-requirements.txt
RUN pip install -r /tmp/test-requirements.txt
USER studio
WORKDIR /repo
ENV PYTHONPATH=/repo/backend
HEALTHCHECK NONE
CMD ["python", "-m", "pytest", "test-suite", "-q", "-p", "no:cacheprovider"]
