"""
CRUD helpers for the presets and popular tables in presets.db.

Keywords are stored as a JSON array string in SQLite and returned as list[str].
`popular` tracks download/use counts per preset_id (FK to presets).
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

try:
    from .init_db import DB_PATH, init_db, migrate_schema
except ImportError:  # running as a script inside backend/database/
    from init_db import DB_PATH, init_db, migrate_schema

TABLE_NAME = "presets"
POPULAR_TABLE = "popular"
DEFAULT_AR = "non-square"
VALID_AR = frozenset({"square", "non-square"})
DEFAULT_TEXT_INPUT = "no"
VALID_TEXT_INPUT = frozenset({"yes", "no"})
MAX_PRESET_TEXT_CHARS = 200


def get_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    """Open a connection; create the DB/schema if missing."""
    if not db_path.is_file():
        init_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    migrate_schema(conn)
    # executescript() commits; re-assert FKs for this connection.
    conn.execute("PRAGMA foreign_keys = ON")
    conn.commit()
    return conn


def _normalize_ar(value: str | None) -> str:
    text = (DEFAULT_AR if value is None else str(value)).strip().lower()
    if text not in VALID_AR:
        raise ValueError("ar must be 'square' or 'non-square'")
    return text


def _normalize_text_input(value: str | None) -> str:
    text = (DEFAULT_TEXT_INPUT if value is None else str(value)).strip().lower()
    if text not in VALID_TEXT_INPUT:
        raise ValueError("text_input must be 'yes' or 'no'")
    return text


def _normalize_text_character_limit(value: int | str | None) -> int:
    if value is None or value == "":
        return 0
    try:
        limit = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("text_character_limit must be an integer") from exc
    if limit < 0:
        raise ValueError("text_character_limit must be >= 0")
    if limit > MAX_PRESET_TEXT_CHARS:
        raise ValueError(
            f"text_character_limit must be <= {MAX_PRESET_TEXT_CHARS}"
        )
    return limit


def _normalize_default_text(value: str | None, limit: int) -> str:
    text = "" if value is None else str(value)
    cap = limit if limit > 0 else MAX_PRESET_TEXT_CHARS
    if len(text) > cap:
        raise ValueError("default_text exceeds text_character_limit")
    return text


def _normalize_text_fields(
    text_input: str | None,
    default_text: str | None,
    text_character_limit: int | str | None,
) -> tuple[str, str, int]:
    wants = _normalize_text_input(text_input)
    if wants == DEFAULT_TEXT_INPUT:
        return DEFAULT_TEXT_INPUT, "", 0
    limit = _normalize_text_character_limit(text_character_limit)
    if limit < 1:
        raise ValueError("text_character_limit must be >= 1 when text_input is yes")
    return wants, _normalize_default_text(default_text, limit), limit


def _keywords_to_json(keywords: list[str] | None) -> str:
    cleaned: list[str] = []
    for item in keywords or []:
        text = str(item).strip()
        if text:
            cleaned.append(text)
    return json.dumps(cleaned, ensure_ascii=False)


def _keywords_from_json(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return [str(item).strip() for item in data if str(item).strip()]


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    keys = set(row.keys())
    raw_ar = row["ar"] if "ar" in keys else None
    try:
        ar = _normalize_ar(raw_ar)
    except ValueError:
        ar = DEFAULT_AR
    raw_text_input = row["text_input"] if "text_input" in keys else None
    try:
        text_input = _normalize_text_input(raw_text_input)
    except ValueError:
        text_input = DEFAULT_TEXT_INPUT
    raw_limit = row["text_character_limit"] if "text_character_limit" in keys else 0
    try:
        text_character_limit = _normalize_text_character_limit(raw_limit)
    except ValueError:
        text_character_limit = 0
    if text_input == DEFAULT_TEXT_INPUT:
        default_text = ""
        text_character_limit = 0
    else:
        raw_default = row["default_text"] if "default_text" in keys else ""
        try:
            default_text = _normalize_default_text(raw_default, text_character_limit)
        except ValueError:
            default_text = str(raw_default or "")[:text_character_limit]
    return {
        "preset_id": row["preset_id"],
        "preset_name": row["preset_name"],
        "preset_path": row["preset_path"],
        "keywords": _keywords_from_json(row["keywords"]),
        "ar": ar,
        "text_input": text_input,
        "default_text": default_text,
        "text_character_limit": text_character_limit,
        "created_date": row["created_date"],
    }


def add_preset(
    preset_name: str,
    preset_path: str,
    keywords: list[str] | None = None,
    ar: str = DEFAULT_AR,
    text_input: str = DEFAULT_TEXT_INPUT,
    default_text: str = "",
    text_character_limit: int = 0,
    *,
    db_path: Path = DB_PATH,
) -> dict[str, Any]:
    """Insert a preset row. created_date is set by SQLite. Returns the new row."""
    name = preset_name.strip()
    path = preset_path.strip()
    if not name:
        raise ValueError("preset_name is required")
    if not path:
        raise ValueError("preset_path is required")
    ar_value = _normalize_ar(ar)
    text_input_value, default_text_value, limit_value = _normalize_text_fields(
        text_input, default_text, text_character_limit
    )

    with get_connection(db_path) as conn:
        cur = conn.execute(
            f"""
            INSERT INTO {TABLE_NAME} (
                preset_name, preset_path, keywords, ar,
                text_input, default_text, text_character_limit
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name,
                path,
                _keywords_to_json(keywords),
                ar_value,
                text_input_value,
                default_text_value,
                limit_value,
            ),
        )
        preset_id = int(cur.lastrowid)
        conn.execute(
            f"INSERT OR IGNORE INTO {POPULAR_TABLE} (preset_id, used_count) "
            "VALUES (?, 0)",
            (preset_id,),
        )
        conn.commit()

    row = get_preset_by_id(preset_id, db_path=db_path)
    if row is None:
        raise RuntimeError("Insert succeeded but row could not be read back")
    return row


def get_preset_by_id(preset_id: int, *, db_path: Path = DB_PATH) -> dict[str, Any] | None:
    with get_connection(db_path) as conn:
        row = conn.execute(
            f"SELECT * FROM {TABLE_NAME} WHERE preset_id = ?",
            (preset_id,),
        ).fetchone()
    return _row_to_dict(row) if row else None


def get_preset_by_name(preset_name: str, *, db_path: Path = DB_PATH) -> dict[str, Any] | None:
    with get_connection(db_path) as conn:
        row = conn.execute(
            f"SELECT * FROM {TABLE_NAME} WHERE preset_name = ?",
            (preset_name.strip(),),
        ).fetchone()
    return _row_to_dict(row) if row else None


def list_presets(*, db_path: Path = DB_PATH) -> list[dict[str, Any]]:
    """Return presets with newest rows first (highest preset_id)."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM {TABLE_NAME} ORDER BY preset_id DESC"
        ).fetchall()
    return [_row_to_dict(row) for row in rows]


def search_presets_by_keyword(
    query: str,
    *,
    db_path: Path = DB_PATH,
) -> list[dict[str, Any]]:
    """
    Return presets whose `preset_name` or keywords contain `query`
    (case-insensitive substring). Matches keep newest-first list order.
    Empty/whitespace query returns [].
    """
    needle = (query or "").strip().lower()
    if not needle:
        return []

    matches: list[dict[str, Any]] = []
    for row in list_presets(db_path=db_path):
        name = str(row.get("preset_name") or "").lower()
        name_spaced = name.replace("_", " ")
        keywords = row.get("keywords") or []
        if (
            needle in name
            or needle in name_spaced
            or any(needle in str(kw).lower() for kw in keywords)
        ):
            matches.append(row)
    return matches


def update_preset(
    preset_id: int,
    *,
    preset_name: str | None = None,
    preset_path: str | None = None,
    keywords: list[str] | None = None,
    ar: str | None = None,
    text_input: str | None = None,
    default_text: str | None = None,
    text_character_limit: int | None = None,
    db_path: Path = DB_PATH,
) -> dict[str, Any] | None:
    """Partial update. Returns the updated row, or None if missing."""
    fields: list[str] = []
    values: list[Any] = []

    if preset_name is not None:
        name = preset_name.strip()
        if not name:
            raise ValueError("preset_name cannot be empty")
        fields.append("preset_name = ?")
        values.append(name)
    if preset_path is not None:
        path = preset_path.strip()
        if not path:
            raise ValueError("preset_path cannot be empty")
        fields.append("preset_path = ?")
        values.append(path)
    if keywords is not None:
        fields.append("keywords = ?")
        values.append(_keywords_to_json(keywords))
    if ar is not None:
        fields.append("ar = ?")
        values.append(_normalize_ar(ar))

    text_fields_touched = (
        text_input is not None
        or default_text is not None
        or text_character_limit is not None
    )
    if text_fields_touched:
        current = get_preset_by_id(preset_id, db_path=db_path)
        if current is None:
            return None
        merged_input = current["text_input"] if text_input is None else text_input
        merged_default = current["default_text"] if default_text is None else default_text
        merged_limit = (
            current["text_character_limit"]
            if text_character_limit is None
            else text_character_limit
        )
        input_value, default_value, limit_value = _normalize_text_fields(
            merged_input, merged_default, merged_limit
        )
        fields.extend(
            [
                "text_input = ?",
                "default_text = ?",
                "text_character_limit = ?",
            ]
        )
        values.extend([input_value, default_value, limit_value])

    if not fields:
        return get_preset_by_id(preset_id, db_path=db_path)

    values.append(preset_id)
    with get_connection(db_path) as conn:
        cur = conn.execute(
            f"UPDATE {TABLE_NAME} SET {', '.join(fields)} WHERE preset_id = ?",
            values,
        )
        conn.commit()
        if cur.rowcount == 0:
            return None
    return get_preset_by_id(preset_id, db_path=db_path)


def list_popular(*, db_path: Path = DB_PATH) -> list[dict[str, Any]]:
    """Return popular rows ordered by used_count descending (then preset_id)."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT p.preset_id, pr.preset_name, p.used_count
            FROM {POPULAR_TABLE} AS p
            INNER JOIN {TABLE_NAME} AS pr ON pr.preset_id = p.preset_id
            ORDER BY p.used_count DESC, p.preset_id ASC
            """
        ).fetchall()
    return [
        {
            "preset_id": int(row["preset_id"]),
            "preset_name": str(row["preset_name"]),
            "used_count": int(row["used_count"]),
        }
        for row in rows
    ]


def _bump_used_count(
    conn: sqlite3.Connection,
    preset_id: int,
) -> dict[str, Any] | None:
    """Increment used_count for an existing preset. Caller owns the connection."""
    exists = conn.execute(
        f"SELECT preset_id FROM {TABLE_NAME} WHERE preset_id = ?",
        (preset_id,),
    ).fetchone()
    if exists is None:
        return None
    conn.execute(
        f"""
        INSERT INTO {POPULAR_TABLE} (preset_id, used_count) VALUES (?, 1)
        ON CONFLICT(preset_id) DO UPDATE SET
            used_count = {POPULAR_TABLE}.used_count + 1
        """,
        (preset_id,),
    )
    row = conn.execute(
        f"SELECT preset_id, used_count FROM {POPULAR_TABLE} WHERE preset_id = ?",
        (preset_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "preset_id": int(row["preset_id"]),
        "used_count": int(row["used_count"]),
    }


def increment_used_count(
    preset_id: int,
    *,
    db_path: Path = DB_PATH,
) -> dict[str, Any] | None:
    """Add 1 to used_count for `preset_id`. Returns the row, or None if missing."""
    with get_connection(db_path) as conn:
        row = _bump_used_count(conn, preset_id)
        conn.commit()
    return row


def increment_used_count_by_name(
    preset_name: str,
    *,
    db_path: Path = DB_PATH,
) -> dict[str, Any] | None:
    """Increment used_count for the preset with this name. None if unknown."""
    name = (preset_name or "").strip()
    if not name:
        return None
    with get_connection(db_path) as conn:
        found = conn.execute(
            f"SELECT preset_id FROM {TABLE_NAME} WHERE preset_name = ?",
            (name,),
        ).fetchone()
        if found is None:
            return None
        row = _bump_used_count(conn, int(found["preset_id"]))
        conn.commit()
    return row


def delete_preset(preset_id: int, *, db_path: Path = DB_PATH) -> bool:
    """Delete by id. Returns True if a row was removed."""
    with get_connection(db_path) as conn:
        cur = conn.execute(
            f"DELETE FROM {TABLE_NAME} WHERE preset_id = ?",
            (preset_id,),
        )
        conn.commit()
        return cur.rowcount > 0


def seed_default_presets(*, db_path: Path = DB_PATH) -> list[dict[str, Any]]:
    """Insert known shipped presets if missing; sync text/ar metadata when present."""
    defaults = [
        {
            "preset_name": "bw_bg_glowing_subject",
            "preset_path": "backend/presets/bw_bg_glowing_subject.json",
            "keywords": [
                "grayscale",
                "black and white",
                "glow",
                "outline",
                "subject",
                "border",
            ],
            "ar": "non-square",
            "text_input": "no",
            "default_text": "",
            "text_character_limit": 0,
        },
        {
            "preset_name": "polaroid_memory",
            "preset_path": "backend/presets/polaroid_memory.json",
            "keywords": [
                "polaroid",
                "instant",
                "film",
                "vintage",
                "warm",
                "white frame",
                "caption",
                "timestamp",
                "square",
                "memory",
                "nostalgia",
                "brush script",
                "photo border",
            ],
            "ar": "square",
            "text_input": "yes",
            "default_text": "instant memory",
            "text_character_limit": 24,
        },
        {
            "preset_name": "warm_faded_print",
            "preset_path": "backend/presets/warm_faded_print.json",
            "keywords": [
                "vintage",
                "faded",
                "warm",
                "amber",
                "print",
                "film",
                "retro",
                "sepia-adjacent",
                "nostalgic",
                "analog",
                "sun-faded",
                "cream",
                "photograph",
                "color-grade",
                "old-photo",
            ],
            "ar": "non-square",
            "text_input": "no",
            "default_text": "",
            "text_character_limit": 0,
        },
        {
            "preset_name": "full_hd",
            "preset_path": "backend/presets/full_hd.json",
            "keywords": [
                "hd",
                "full hd",
                "1080p",
                "upscale",
                "enhance",
                "ai upscale",
                "super resolution",
                "sharpen",
                "clarity",
                "restore",
                "low res fix",
                "pixelated",
                "blurry",
                "old photo",
                "quality boost",
                "real-esrgan",
            ],
            "ar": "non-square",
            "text_input": "no",
            "default_text": "",
            "text_character_limit": 0,
        },
        {
            "preset_name": "4k_crisp",
            "preset_path": "backend/presets/4k_crisp.json",
            "keywords": [
                "4k",
                "uhd",
                "ultra hd",
                "2160p",
                "upscale",
                "ai upscale",
                "super resolution",
                "crisp",
                "sharp",
                "detail",
                "high resolution",
                "print",
                "wallpaper",
                "enhance",
                "clarity",
                "real-esrgan",
            ],
            "ar": "non-square",
            "text_input": "no",
            "default_text": "",
            "text_character_limit": 0,
        },
        {
            "preset_name": "doodle_corner_xo",
            "preset_path": "backend/presets/doodle_corner_xo.json",
            "keywords": [
                "doodle",
                "hand drawn",
                "sketch",
                "tic tac toe",
                "x and o",
                "xo",
                "wiggly lines",
                "squiggle",
                "sticker",
                "white outline",
                "cutout",
                "subject",
                "playful",
                "fun",
                "scrapbook",
                "social media",
                "instagram story",
            ],
            "ar": "non-square",
            "text_input": "no",
            "default_text": "",
            "text_character_limit": 0,
        },
        {
            "preset_name": "doodle_halo_rings",
            "preset_path": "backend/presets/doodle_halo_rings.json",
            "keywords": [
                "doodle",
                "hand drawn",
                "sketch",
                "rings",
                "circles",
                "concentric",
                "halo",
                "ripple",
                "sparkles",
                "stars",
                "sticker",
                "white outline",
                "cutout",
                "subject",
                "spotlight",
                "portrait",
                "social media",
                "poster",
            ],
            "ar": "non-square",
            "text_input": "no",
            "default_text": "",
            "text_character_limit": 0,
        },
        {
            "preset_name": "comic_pop",
            "preset_path": "backend/presets/comic_pop.json",
            "keywords": [
                "comic",
                "comic book",
                "pop art",
                "halftone",
                "dots",
                "ink outlines",
                "posterize",
                "cartoon",
                "graphic novel",
                "bold colors",
                "vibrant",
                "illustration",
                "superhero",
                "poster",
            ],
            "ar": "non-square",
            "text_input": "no",
            "default_text": "",
            "text_character_limit": 0,
        },
        {
            "preset_name": "old_newspaper",
            "preset_path": "backend/presets/old_newspaper.json",
            "keywords": [
                "newspaper",
                "newsprint",
                "old newspaper",
                "halftone",
                "black and white",
                "grayscale",
                "vintage",
                "retro",
                "press photo",
                "print",
                "aged paper",
                "grain",
                "sepia",
                "old photo",
            ],
            "ar": "non-square",
            "text_input": "no",
            "default_text": "",
            "text_character_limit": 0,
        },
        {
            "preset_name": "vintage_comic",
            "preset_path": "backend/presets/vintage_comic.json",
            "keywords": [
                "vintage comic",
                "retro comic",
                "comic",
                "cmyk",
                "halftone",
                "dots",
                "pop art",
                "aged paper",
                "yellowed",
                "print",
                "pulp",
                "retro",
                "vintage",
                "ink outlines",
            ],
            "ar": "non-square",
            "text_input": "no",
            "default_text": "",
            "text_character_limit": 0,
        },
        {
            "preset_name": "cinematic_teal_orange",
            "preset_path": "backend/presets/cinematic_teal_orange.json",
            "keywords": [
                "cinematic",
                "teal",
                "orange",
                "movie",
                "film look",
                "blockbuster",
                "split tone",
                "contrast",
                "moody",
                "street",
            ],
            "ar": "non-square",
            "text_input": "no",
            "default_text": "",
            "text_character_limit": 0,
        },
        {
            "preset_name": "warm_portrait_film",
            "preset_path": "backend/presets/warm_portrait_film.json",
            "keywords": [
                "warm",
                "film",
                "portrait",
                "skin tones",
                "soft",
                "creamy",
                "analog",
                "grain",
                "wedding",
                "faded",
            ],
            "ar": "non-square",
            "text_input": "no",
            "default_text": "",
            "text_character_limit": 0,
        },
        {
            "preset_name": "nordic_cool_matte",
            "preset_path": "backend/presets/nordic_cool_matte.json",
            "keywords": [
                "cool",
                "nordic",
                "matte",
                "muted",
                "blue",
                "faded",
                "minimal",
                "scandinavian",
                "winter",
                "calm",
            ],
            "ar": "non-square",
            "text_input": "no",
            "default_text": "",
            "text_character_limit": 0,
        },
        {
            "preset_name": "golden_hour_glow",
            "preset_path": "backend/presets/golden_hour_glow.json",
            "keywords": [
                "golden hour",
                "warm",
                "sunset",
                "amber",
                "glow",
                "sunny",
                "orange",
                "summer",
                "travel",
                "gold",
            ],
            "ar": "non-square",
            "text_input": "no",
            "default_text": "",
            "text_character_limit": 0,
        },
        {
            "preset_name": "emerald_moody",
            "preset_path": "backend/presets/emerald_moody.json",
            "keywords": [
                "green",
                "emerald",
                "moody",
                "forest",
                "dark",
                "deep",
                "nature",
                "cinematic",
                "shadows",
                "jade",
            ],
            "ar": "non-square",
            "text_input": "no",
            "default_text": "",
            "text_character_limit": 0,
        },
        {
            "preset_name": "fine_art_mono",
            "preset_path": "backend/presets/fine_art_mono.json",
            "keywords": [
                "black and white",
                "monochrome",
                "fine art",
                "split tone",
                "grain",
                "contrast",
                "gallery",
                "classic",
                "noir",
                "portrait",
            ],
            "ar": "non-square",
            "text_input": "no",
            "default_text": "",
            "text_character_limit": 0,
        },
        {
            "preset_name": "bright_airy",
            "preset_path": "backend/presets/bright_airy.json",
            "keywords": [
                "bright",
                "airy",
                "light",
                "clean",
                "soft",
                "wedding",
                "lifestyle",
                "product",
                "pastel",
                "high key",
            ],
            "ar": "non-square",
            "text_input": "no",
            "default_text": "",
            "text_character_limit": 0,
        },
        {
            "preset_name": "vintage_slide_punch",
            "preset_path": "backend/presets/vintage_slide_punch.json",
            "keywords": [
                "vintage",
                "slide film",
                "retro",
                "saturated",
                "punchy",
                "red",
                "contrast",
                "70s",
                "analog",
                "colourful",
            ],
            "ar": "non-square",
            "text_input": "no",
            "default_text": "",
            "text_character_limit": 0,
        },
        {
            "preset_name": "blush_rose_pastel",
            "preset_path": "backend/presets/blush_rose_pastel.json",
            "keywords": [
                "pink",
                "rose",
                "blush",
                "pastel",
                "romantic",
                "soft",
                "dreamy",
                "magenta",
                "feminine",
                "fashion",
            ],
            "ar": "non-square",
            "text_input": "no",
            "default_text": "",
            "text_character_limit": 0,
        },
        {
            "preset_name": "blue_hour_noir",
            "preset_path": "backend/presets/blue_hour_noir.json",
            "keywords": [
                "blue",
                "blue hour",
                "night",
                "noir",
                "cold",
                "moody",
                "dark",
                "city",
                "cinematic",
                "steel",
            ],
            "ar": "non-square",
            "text_input": "no",
            "default_text": "",
            "text_character_limit": 0,
        },
    ]
    created: list[dict[str, Any]] = []
    for item in defaults:
        existing = get_preset_by_name(item["preset_name"], db_path=db_path)
        if existing is None:
            created.append(
                add_preset(
                    item["preset_name"],
                    item["preset_path"],
                    item["keywords"],
                    item.get("ar", DEFAULT_AR),
                    item.get("text_input", DEFAULT_TEXT_INPUT),
                    item.get("default_text", ""),
                    item.get("text_character_limit", 0),
                    db_path=db_path,
                )
            )
            continue

        desired_ar = item.get("ar", DEFAULT_AR)
        desired_text_input = item.get("text_input", DEFAULT_TEXT_INPUT)
        desired_default = item.get("default_text", "")
        desired_limit = item.get("text_character_limit", 0)
        needs_sync = (
            existing.get("ar") != desired_ar
            or existing.get("text_input") != desired_text_input
            or existing.get("default_text") != desired_default
            or existing.get("text_character_limit") != desired_limit
            or existing.get("preset_path") != item["preset_path"]
            or existing.get("keywords") != item["keywords"]
        )
        if needs_sync:
            update_preset(
                int(existing["preset_id"]),
                preset_path=item["preset_path"],
                keywords=item["keywords"],
                ar=desired_ar,
                text_input=desired_text_input,
                default_text=desired_default,
                text_character_limit=desired_limit,
                db_path=db_path,
            )
    return created
