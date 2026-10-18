"""
Apply a database-named JSON preset to an image.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from PIL import Image

from database.db_ops import get_preset_by_name

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_DIR.parent
HELPERS_DIR = BACKEND_DIR / "helpers"

# Cap concurrent rembg-heavy preset jobs (reject extras with 503).
MAX_CONCURRENT_PRESET_JOBS = 1


class PresetNotFoundError(LookupError):
    """Raised when `preset_name` is not in the presets table."""


class PresetFileMissingError(FileNotFoundError):
    """Raised when the DB row exists but the JSON file cannot be found."""


class PresetPathUnsafeError(ValueError):
    """Raised when a DB preset_path resolves outside the presets directory."""


class PresetBusyError(RuntimeError):
    """Raised when the concurrent preset job limit is already reached."""


class PresetAspectRatioError(ValueError):
    """Raised when a square-only preset is applied to a non-square image."""


class PresetTextError(ValueError):
    """Raised when user text is missing or exceeds the preset's character limit."""


class PresetJobLimiter:
    """Non-blocking concurrency gate for CPU-heavy preset work."""

    def __init__(self, limit: int = MAX_CONCURRENT_PRESET_JOBS) -> None:
        if limit < 1:
            raise ValueError("limit must be >= 1")
        self._limit = limit
        self._in_use = 0
        self._lock = asyncio.Lock()

    @property
    def in_use(self) -> int:
        return self._in_use

    @property
    def limit(self) -> int:
        return self._limit

    async def try_acquire(self) -> bool:
        async with self._lock:
            if self._in_use >= self._limit:
                return False
            self._in_use += 1
            return True

    async def release(self) -> None:
        async with self._lock:
            if self._in_use > 0:
                self._in_use -= 1


# Process-wide limiter shared by the HTTP routes (apply-preset and blur): it
# bounds image memory, not just rembg, so it covers upload read → decode →
# filters → encode.
preset_job_limiter = PresetJobLimiter()


@asynccontextmanager
async def preset_job_slot(limiter: PresetJobLimiter | None = None) -> AsyncIterator[None]:
    """
    Hold one job slot for the duration of the block; raise PresetBusyError
    straight away (nothing read or decoded yet) when none is free.
    """
    gate = limiter if limiter is not None else preset_job_limiter
    if not await gate.try_acquire():
        raise PresetBusyError("Preset processing is busy; try again shortly.")
    try:
        yield
    finally:
        await gate.release()


def _helpers_apply_preset():
    """Import CLI helper module (expects `helpers/` on sys.path for `filters`)."""
    helpers = str(HELPERS_DIR)
    if helpers not in sys.path:
        sys.path.insert(0, helpers)
    import apply_preset as apply_preset_mod  # type: ignore

    return apply_preset_mod


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def resolve_preset_file(
    preset_name: str,
    *,
    db_path: Path | None = None,
    repo_root: Path = REPO_ROOT,
    presets_dir: Path | None = None,
) -> Path:
    """
    Look up `preset_name` in SQLite and resolve `preset_path` to a JSON file
    that must live under the presets directory (path traversal safe).
    """
    name = (preset_name or "").strip()
    if not name:
        raise ValueError("preset_name is required")

    kwargs: dict = {}
    if db_path is not None:
        kwargs["db_path"] = db_path

    row = get_preset_by_name(name, **kwargs)
    if row is None:
        raise PresetNotFoundError(f"Preset not found: {name}")

    stored = str(row["preset_path"]).strip()
    if not stored:
        raise PresetFileMissingError(f"Preset '{name}' has an empty preset_path")

    presets_root = (
        Path(presets_dir) if presets_dir is not None else (repo_root / "backend" / "presets")
    ).resolve()

    stored_path = Path(stored)
    candidates: list[Path] = []
    if stored_path.is_absolute():
        candidates.append(stored_path)
    else:
        candidates.append(repo_root / stored_path)
        candidates.append(presets_root / stored_path.name)

    saw_existing_outside = False
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if not resolved.is_file():
            continue
        if not _is_under(resolved, presets_root):
            saw_existing_outside = True
            continue
        return resolved

    if saw_existing_outside:
        raise PresetPathUnsafeError(
            f"Preset path for '{name}' is outside the presets directory."
        )
    raise PresetFileMissingError(f"Preset file missing for '{name}': {stored}")


def apply_named_preset(
    image: Image.Image,
    preset_name: str,
    *,
    text: str | None = None,
    db_path: Path | None = None,
    repo_root: Path = REPO_ROOT,
    presets_dir: Path | None = None,
) -> Image.Image:
    """Resolve preset by DB name and run its JSON steps on `image`."""
    preset_path = resolve_preset_file(
        preset_name,
        db_path=db_path,
        repo_root=repo_root,
        presets_dir=presets_dir,
    )
    apply_preset_mod = _helpers_apply_preset()
    try:
        return apply_preset_mod.apply_preset(image, preset_path, text=text)
    except apply_preset_mod.PresetAspectRatioError as exc:
        raise PresetAspectRatioError(str(exc)) from exc
    except apply_preset_mod.PresetTextError as exc:
        raise PresetTextError(str(exc)) from exc


async def run_preset_job(
    image: Image.Image,
    preset_name: str,
    *,
    text: str | None = None,
    limiter: PresetJobLimiter | None = None,
    db_path: Path | None = None,
    repo_root: Path = REPO_ROOT,
    presets_dir: Path | None = None,
) -> Image.Image:
    """
    Apply a named preset off the event loop, respecting the concurrency gate.
    Raises PresetBusyError if another job already holds the slot.
    """
    async with preset_job_slot(limiter):
        return await asyncio.to_thread(
            apply_named_preset,
            image,
            preset_name,
            text=text,
            db_path=db_path,
            repo_root=repo_root,
            presets_dir=presets_dir,
        )
