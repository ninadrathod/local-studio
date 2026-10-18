"""Unit tests for `app.services.preset` (service functions only)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from PIL import Image

from app.services.preset import (
    PresetAspectRatioError,
    PresetBusyError,
    PresetFileMissingError,
    PresetJobLimiter,
    PresetNotFoundError,
    PresetPathUnsafeError,
    PresetTextError,
    apply_named_preset,
    preset_job_slot,
    resolve_preset_file,
    run_preset_job,
)
from database.db_ops import add_preset
from database.init_db import init_db


def _make_repo(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Create a mini repo with presets/ + empty DB; return (repo_root, db_path, presets_dir)."""
    repo_root = tmp_path / "repo"
    presets_dir = repo_root / "backend" / "presets"
    presets_dir.mkdir(parents=True)
    db_path = tmp_path / "presets.db"
    init_db(db_path)
    return repo_root, db_path, presets_dir


def _write_gray_preset(
    presets_dir: Path,
    name: str = "simple_gray",
    *,
    ar: str | None = None,
) -> Path:
    preset_json = presets_dir / f"{name}.json"
    payload: dict = {
        "name": name,
        "steps": [{"filter": "grayscale", "on": "image"}],
    }
    if ar is not None:
        payload["ar"] = ar
    preset_json.write_text(json.dumps(payload), encoding="utf-8")
    return preset_json


def test_resolve_preset_file_requires_name(tmp_path: Path) -> None:
    _, db_path, _ = _make_repo(tmp_path)
    with pytest.raises(ValueError, match="preset_name"):
        resolve_preset_file("  ", db_path=db_path)


def test_resolve_preset_file_missing_db_row(tmp_path: Path) -> None:
    repo_root, db_path, _ = _make_repo(tmp_path)
    with pytest.raises(PresetNotFoundError):
        resolve_preset_file("no_such_preset", db_path=db_path, repo_root=repo_root)


def test_resolve_preset_file_missing_json(tmp_path: Path) -> None:
    repo_root, db_path, _ = _make_repo(tmp_path)
    add_preset(
        "ghost",
        "backend/presets/ghost.json",
        db_path=db_path,
    )
    with pytest.raises(PresetFileMissingError):
        resolve_preset_file("ghost", db_path=db_path, repo_root=repo_root)


def test_resolve_preset_file_finds_under_repo_root(tmp_path: Path) -> None:
    repo_root, db_path, presets_dir = _make_repo(tmp_path)
    preset_json = _write_gray_preset(presets_dir)
    add_preset(
        "simple_gray",
        "backend/presets/simple_gray.json",
        db_path=db_path,
    )

    resolved = resolve_preset_file(
        "simple_gray",
        db_path=db_path,
        repo_root=repo_root,
    )
    assert resolved == preset_json.resolve()


def test_resolve_preset_file_rejects_path_outside_presets(tmp_path: Path) -> None:
    repo_root, db_path, _ = _make_repo(tmp_path)
    outside = tmp_path / "outside.json"
    outside.write_text(
        json.dumps({"name": "evil", "steps": [{"filter": "grayscale", "on": "image"}]}),
        encoding="utf-8",
    )
    add_preset("evil", str(outside.resolve()), db_path=db_path)

    with pytest.raises(PresetPathUnsafeError):
        resolve_preset_file("evil", db_path=db_path, repo_root=repo_root)


def test_resolve_preset_file_rejects_traversal_segments(tmp_path: Path) -> None:
    repo_root, db_path, presets_dir = _make_repo(tmp_path)
    secret = tmp_path / "secret.json"
    secret.write_text(
        json.dumps({"name": "secret", "steps": [{"filter": "grayscale", "on": "image"}]}),
        encoding="utf-8",
    )
    # Point through presets dir with .. into tmp_path
    relative = Path("backend") / "presets" / ".." / ".." / ".." / secret.name
    # Actually repo_root/backend/presets/../../../secret.json from repo = tmp_path/secret
    # stored as relative from repo_root:
    traversal = "backend/presets/../../../secret.json"
    # From repo_root: backend/presets/../../../secret.json -> tmp_path/secret.json
    add_preset("leaky", traversal, db_path=db_path)

    # Ensure the traversal target exists and would resolve if not sandboxed
    assert (repo_root / traversal).resolve() == secret.resolve()
    assert presets_dir.is_dir()

    with pytest.raises(PresetPathUnsafeError):
        resolve_preset_file("leaky", db_path=db_path, repo_root=repo_root)


def test_apply_named_preset_runs_grayscale_steps(tmp_path: Path) -> None:
    repo_root, db_path, presets_dir = _make_repo(tmp_path)
    _write_gray_preset(presets_dir)
    add_preset(
        "simple_gray",
        "backend/presets/simple_gray.json",
        db_path=db_path,
    )

    source = Image.new("RGB", (8, 8), color=(200, 40, 40))
    result = apply_named_preset(
        source,
        "simple_gray",
        db_path=db_path,
        repo_root=repo_root,
    )

    assert result.size == source.size
    assert result.mode in ("RGB", "RGBA", "L")
    pixel = result.convert("RGB").getpixel((0, 0))
    assert pixel[0] == pixel[1] == pixel[2]
    assert pixel != (200, 40, 40)


def test_preset_job_limiter_rejects_when_full() -> None:
    limiter = PresetJobLimiter(limit=1)

    async def _run() -> None:
        assert await limiter.try_acquire() is True
        assert await limiter.try_acquire() is False
        await limiter.release()
        assert await limiter.try_acquire() is True
        await limiter.release()

    asyncio.run(_run())


def test_preset_job_slot_rejects_before_running_and_always_releases() -> None:
    limiter = PresetJobLimiter(limit=1)
    ran: list[str] = []

    async def _run() -> None:
        async with preset_job_slot(limiter):
            assert limiter.in_use == 1
            # A second request is refused before its block (upload read/decode) runs.
            with pytest.raises(PresetBusyError):
                async with preset_job_slot(limiter):
                    ran.append("second")
        assert limiter.in_use == 0
        # The slot is released even when the work inside fails.
        with pytest.raises(ValueError):
            async with preset_job_slot(limiter):
                raise ValueError("decode failed")
        assert limiter.in_use == 0

    asyncio.run(_run())
    assert ran == []


def test_run_preset_job_raises_busy_when_slot_taken(tmp_path: Path) -> None:
    repo_root, db_path, presets_dir = _make_repo(tmp_path)
    _write_gray_preset(presets_dir)
    add_preset(
        "simple_gray",
        "backend/presets/simple_gray.json",
        db_path=db_path,
    )
    limiter = PresetJobLimiter(limit=1)
    source = Image.new("RGB", (4, 4), color=(10, 20, 30))

    async def _run() -> None:
        assert await limiter.try_acquire() is True
        with pytest.raises(PresetBusyError):
            await run_preset_job(
                source,
                "simple_gray",
                limiter=limiter,
                db_path=db_path,
                repo_root=repo_root,
            )
        await limiter.release()
        result = await run_preset_job(
            source,
            "simple_gray",
            limiter=limiter,
            db_path=db_path,
            repo_root=repo_root,
        )
        assert result.size == source.size

    asyncio.run(_run())


def test_apply_named_preset_rejects_non_square_for_square_ar(tmp_path: Path) -> None:
    repo_root, db_path, presets_dir = _make_repo(tmp_path)
    _write_gray_preset(presets_dir, "square_only", ar="square")
    add_preset(
        "square_only",
        "backend/presets/square_only.json",
        ar="square",
        db_path=db_path,
    )

    wide = Image.new("RGB", (12, 8), color=(200, 40, 40))
    with pytest.raises(PresetAspectRatioError, match="square"):
        apply_named_preset(
            wide,
            "square_only",
            db_path=db_path,
            repo_root=repo_root,
        )

    square = Image.new("RGB", (8, 8), color=(200, 40, 40))
    result = apply_named_preset(
        square,
        "square_only",
        db_path=db_path,
        repo_root=repo_root,
    )
    assert result.size == square.size


def _write_caption_preset(presets_dir: Path, name: str = "caption_look") -> Path:
    preset_json = presets_dir / f"{name}.json"
    preset_json.write_text(
        json.dumps(
            {
                "name": name,
                "text_input": "yes",
                "default_text": "Hi",
                "text_character_limit": 8,
                "steps": [
                    {
                        "filter": "draw_text",
                        "on": "image",
                        "text": "$text",
                        "font_size": 20,
                        "color": [255, 255, 255],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return preset_json


def test_apply_named_preset_binds_user_text(tmp_path: Path) -> None:
    repo_root, db_path, presets_dir = _make_repo(tmp_path)
    _write_caption_preset(presets_dir)
    add_preset(
        "caption_look",
        "backend/presets/caption_look.json",
        text_input="yes",
        default_text="Hi",
        text_character_limit=8,
        db_path=db_path,
    )

    source = Image.new("RGB", (64, 64), color=(0, 0, 0))
    result = apply_named_preset(
        source,
        "caption_look",
        text="ABC",
        db_path=db_path,
        repo_root=repo_root,
    )
    assert result.convert("L").getextrema()[1] > 0


def test_apply_named_preset_rejects_text_over_limit(tmp_path: Path) -> None:
    repo_root, db_path, presets_dir = _make_repo(tmp_path)
    _write_caption_preset(presets_dir)
    add_preset(
        "caption_look",
        "backend/presets/caption_look.json",
        text_input="yes",
        default_text="Hi",
        text_character_limit=8,
        db_path=db_path,
    )

    source = Image.new("RGB", (32, 32), color=(0, 0, 0))
    with pytest.raises(PresetTextError, match="at most 8"):
        apply_named_preset(
            source,
            "caption_look",
            text="123456789",
            db_path=db_path,
            repo_root=repo_root,
        )
