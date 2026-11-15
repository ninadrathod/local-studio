"""Unit tests for backend/database preset metadata (SQLite)."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from database.db_ops import (  # noqa: E402
    add_preset,
    delete_preset,
    get_preset_by_id,
    get_preset_by_name,
    increment_used_count,
    increment_used_count_by_name,
    list_popular,
    list_presets,
    search_presets_by_keyword,
    seed_default_presets,
    update_preset,
)
from database.init_db import init_db  # noqa: E402


def test_init_and_crud(tmp_path: Path) -> None:
    db = tmp_path / "presets.db"
    init_db(db)

    row = add_preset(
        "demo",
        "backend/presets/demo.json",
        ["glow", "subject"],
        db_path=db,
    )
    assert row["preset_id"] == 1
    assert row["preset_name"] == "demo"
    assert row["preset_path"] == "backend/presets/demo.json"
    assert row["keywords"] == ["glow", "subject"]
    assert row["ar"] == "non-square"
    assert row["text_input"] == "no"
    assert row["default_text"] == ""
    assert row["text_character_limit"] == 0
    assert row["created_date"]

    by_id = get_preset_by_id(1, db_path=db)
    assert by_id is not None
    assert by_id["preset_name"] == "demo"

    by_name = get_preset_by_name("demo", db_path=db)
    assert by_name is not None
    assert by_name["preset_id"] == 1

    updated = update_preset(1, keywords=["outline", "bw"], db_path=db)
    assert updated is not None
    assert updated["keywords"] == ["outline", "bw"]

    square = update_preset(1, ar="square", db_path=db)
    assert square is not None
    assert square["ar"] == "square"

    assert list_presets(db_path=db)[0]["preset_name"] == "demo"
    assert list_popular(db_path=db) == [
        {"preset_id": 1, "preset_name": "demo", "used_count": 0}
    ]
    assert delete_preset(1, db_path=db) is True
    assert get_preset_by_id(1, db_path=db) is None
    assert list_popular(db_path=db) == []


def test_seed_default_presets_is_idempotent(tmp_path: Path) -> None:
    db = tmp_path / "presets.db"
    init_db(db)
    first = seed_default_presets(db_path=db)
    second = seed_default_presets(db_path=db)
    assert len(first) == 100
    names = {row["preset_name"] for row in first}
    assert names == {
        "bw_bg_glowing_subject",
        "polaroid_memory",
        "warm_faded_print",
        "full_hd",
        "4k_crisp",
        "doodle_corner_xo",
        "doodle_halo_rings",
        "comic_pop",
        "old_newspaper",
        "vintage_comic",
        "cinematic_teal_orange",
        "warm_portrait_film",
        "nordic_cool_matte",
        "golden_hour_glow",
        "emerald_moody",
        "fine_art_mono",
        "bright_airy",
        "vintage_slide_punch",
        "blush_rose_pastel",
        "blue_hour_noir",
        "dreamy_glow",
        "film_halation",
        "film_dust",
        "miami_neon",
        "prism_glow",
        "disposable_flash",
        "portrait_bokeh",
        "tungsten_night_film",
        "muted_chrome_film",
        "studio_spotlight",
        "poster_title_yellow_pop",
        "poster_title_blue_pop",
        "retro_70s_poster",
        "brush_script_poster",
        "neon_nights_script",
        "mission_passed_title",
        "wanted_stencil_title",
        "retrowave_neon_title",
        "art_deco_marquee",
        "velvet_ticket_title",
        "marker_frame_doodle",
        "sunny_sketchbook_doodle",
        "neon_doodle_nights",
        "chalkboard_doodle",
        "love_notes_doodle",
        "retro_70s_doodle",
        "comic_pop_doodle",
        "scrapbook_doodle",
        "cyanotype_doodle",
        "confetti_pastel_doodle",
        "print_film_2383",
        "cross_process",
        "hdr_clarity_pop",
        "bleach_bypass",
        "mocha_moody",
        "lavender_dusk",
        "hdr_noir_mono",
        "mint_pastel_film",
        "shutter_drag",
        "speed_pan",
        "red_halo_spotlight",
        "digicam_flash",
        "red_gel_portrait",
        "split_word_portrait",
        "shape_window_portrait",
        "instax_mini_classic",
        "instax_square_sunny",
        "instax_wide_cool",
        "instax_monochrome",
        "instax_sky_flash",
        "synthwave_sun",
        "diamond_editorial",
        "word_wall_poster",
        "neon_frame_sign",
        "pop_art_panel",
        "graffiti_drip_column",
        "graffiti_throwup_masthead",
        "graffiti_sticker_slap",
        "graffiti_outline_mural",
        "graffiti_outline_tower",
        "radial_swirl",
        "twirl_vortex",
        "water_ripple",
        "squiggle_wave",
        "liquid_spill",
        "codex_chalk_sepia",
        "codex_blueprint",
        "vitruvian_study",
        "inventors_notebook",
        "da_vinci_wings",
        "amber_teal_gel",
        "ice_gel_orange",
        "pistachio_gel_rose",
        "sky_gel_amber",
        "coral_gel_lagoon",
        "vista_red_film",
        "golden_consumer_film",
        "green_cast_film",
        "classic_slide_64",
        "expired_film",
    }
    by_name = {row["preset_name"]: row for row in first}
    assert by_name["bw_bg_glowing_subject"]["ar"] == "non-square"
    assert by_name["bw_bg_glowing_subject"]["text_input"] == "no"
    assert by_name["polaroid_memory"]["ar"] == "square"
    assert by_name["polaroid_memory"]["text_input"] == "yes"
    assert by_name["polaroid_memory"]["default_text"] == "instant memory"
    assert by_name["polaroid_memory"]["text_character_limit"] == 24
    assert by_name["warm_faded_print"]["ar"] == "non-square"
    assert by_name["warm_faded_print"]["text_input"] == "no"
    assert by_name["warm_faded_print"]["default_text"] == ""
    assert by_name["warm_faded_print"]["text_character_limit"] == 0
    assert by_name["art_deco_marquee"]["text_input"] == "yes"
    assert by_name["art_deco_marquee"]["default_text"] == "TITLE"
    assert by_name["art_deco_marquee"]["text_character_limit"] == 16
    assert by_name["split_word_portrait"]["text_input"] == "yes"
    assert by_name["split_word_portrait"]["default_text"] == "DREAM"
    assert by_name["split_word_portrait"]["text_character_limit"] == 20
    for name in ("instax_mini_classic", "instax_square_sunny", "instax_wide_cool", "instax_monochrome", "instax_sky_flash"):
        assert by_name[name]["ar"] == "non-square"
        assert by_name[name]["text_input"] == "yes"
        assert by_name[name]["default_text"] == ""
        assert by_name[name]["text_character_limit"] == 24
    for name, default, limit in (
        ("synthwave_sun", "MIDNIGHT", 14),
        ("diamond_editorial", "EDITION", 14),
        ("word_wall_poster", "GOOD VIBES", 16),
        ("neon_frame_sign", "after dark", 16),
        ("pop_art_panel", "POW! WHAT NOW?", 20),
        ("graffiti_drip_column", "STAY REAL", 16),
        ("graffiti_throwup_masthead", "OUR BLOCK", 16),
        ("graffiti_sticker_slap", "KEEP IT REAL", 16),
        ("graffiti_outline_mural", "DREAM BIG", 16),
        ("graffiti_outline_tower", "HUSTLE", 16),
    ):
        assert by_name[name]["text_input"] == "yes"
        assert by_name[name]["default_text"] == default
        assert by_name[name]["text_character_limit"] == limit
    for name in (
        "full_hd",
        "4k_crisp",
        "doodle_corner_xo",
        "doodle_halo_rings",
        "comic_pop",
        "old_newspaper",
        "vintage_comic",
        "cinematic_teal_orange",
        "warm_portrait_film",
        "nordic_cool_matte",
        "golden_hour_glow",
        "emerald_moody",
        "fine_art_mono",
        "bright_airy",
        "vintage_slide_punch",
        "blush_rose_pastel",
        "blue_hour_noir",
        "dreamy_glow",
        "film_halation",
        "film_dust",
        "miami_neon",
        "prism_glow",
        "disposable_flash",
        "portrait_bokeh",
        "tungsten_night_film",
        "muted_chrome_film",
        "studio_spotlight",
        "print_film_2383",
        "cross_process",
        "hdr_clarity_pop",
        "bleach_bypass",
        "mocha_moody",
        "lavender_dusk",
        "hdr_noir_mono",
        "mint_pastel_film",
        "shutter_drag",
        "speed_pan",
        "red_halo_spotlight",
        "digicam_flash",
        "red_gel_portrait",
        "shape_window_portrait",
        "radial_swirl",
        "twirl_vortex",
        "water_ripple",
        "squiggle_wave",
        "liquid_spill",
        "codex_chalk_sepia",
        "codex_blueprint",
        "vitruvian_study",
        "inventors_notebook",
        "da_vinci_wings",
        "amber_teal_gel",
        "ice_gel_orange",
        "pistachio_gel_rose",
        "sky_gel_amber",
        "coral_gel_lagoon",
        "vista_red_film",
        "golden_consumer_film",
        "green_cast_film",
        "classic_slide_64",
        "expired_film",
    ):
        assert by_name[name]["ar"] == "non-square"
        assert by_name[name]["text_input"] == "no"
        assert by_name[name]["text_character_limit"] == 0
    assert second == []
    names_in_order = [row["preset_name"] for row in list_presets(db_path=db)]
    assert names_in_order == [
        "expired_film",
        "classic_slide_64",
        "green_cast_film",
        "golden_consumer_film",
        "vista_red_film",
        "coral_gel_lagoon",
        "sky_gel_amber",
        "pistachio_gel_rose",
        "ice_gel_orange",
        "amber_teal_gel",
        "da_vinci_wings",
        "inventors_notebook",
        "vitruvian_study",
        "codex_blueprint",
        "codex_chalk_sepia",
        "liquid_spill",
        "squiggle_wave",
        "water_ripple",
        "twirl_vortex",
        "radial_swirl",
        "graffiti_outline_tower",
        "graffiti_outline_mural",
        "graffiti_sticker_slap",
        "graffiti_throwup_masthead",
        "graffiti_drip_column",
        "pop_art_panel",
        "neon_frame_sign",
        "word_wall_poster",
        "diamond_editorial",
        "synthwave_sun",
        "instax_sky_flash",
        "instax_monochrome",
        "instax_wide_cool",
        "instax_square_sunny",
        "instax_mini_classic",
        "shape_window_portrait",
        "split_word_portrait",
        "red_gel_portrait",
        "digicam_flash",
        "red_halo_spotlight",
        "speed_pan",
        "shutter_drag",
        "mint_pastel_film",
        "hdr_noir_mono",
        "lavender_dusk",
        "mocha_moody",
        "bleach_bypass",
        "hdr_clarity_pop",
        "cross_process",
        "print_film_2383",
        "confetti_pastel_doodle",
        "cyanotype_doodle",
        "scrapbook_doodle",
        "comic_pop_doodle",
        "retro_70s_doodle",
        "love_notes_doodle",
        "chalkboard_doodle",
        "neon_doodle_nights",
        "sunny_sketchbook_doodle",
        "marker_frame_doodle",
        "velvet_ticket_title",
        "art_deco_marquee",
        "retrowave_neon_title",
        "wanted_stencil_title",
        "mission_passed_title",
        "neon_nights_script",
        "brush_script_poster",
        "retro_70s_poster",
        "poster_title_blue_pop",
        "poster_title_yellow_pop",
        "studio_spotlight",
        "muted_chrome_film",
        "tungsten_night_film",
        "portrait_bokeh",
        "disposable_flash",
        "prism_glow",
        "miami_neon",
        "film_dust",
        "film_halation",
        "dreamy_glow",
        "blue_hour_noir",
        "blush_rose_pastel",
        "vintage_slide_punch",
        "bright_airy",
        "fine_art_mono",
        "emerald_moody",
        "golden_hour_glow",
        "nordic_cool_matte",
        "warm_portrait_film",
        "cinematic_teal_orange",
        "vintage_comic",
        "old_newspaper",
        "comic_pop",
        "doodle_halo_rings",
        "doodle_corner_xo",
        "4k_crisp",
        "full_hd",
        "warm_faded_print",
        "polaroid_memory",
        "bw_bg_glowing_subject",
    ]
    popular = list_popular(db_path=db)
    assert len(popular) == 100
    assert all(row["used_count"] == 0 for row in popular)


def test_seed_default_presets_syncs_text_fields(tmp_path: Path) -> None:
    db = tmp_path / "presets.db"
    init_db(db)
    row = add_preset(
        "bw_bg_glowing_subject",
        "backend/presets/bw_bg_glowing_subject.json",
        ["stale"],
        ar="square",
        text_input="yes",
        default_text="stale",
        text_character_limit=12,
        db_path=db,
    )
    assert row["text_input"] == "yes"

    created = seed_default_presets(db_path=db)
    assert [row["preset_name"] for row in created] == [
        "polaroid_memory",
        "warm_faded_print",
        "full_hd",
        "4k_crisp",
        "doodle_corner_xo",
        "doodle_halo_rings",
        "comic_pop",
        "old_newspaper",
        "vintage_comic",
        "cinematic_teal_orange",
        "warm_portrait_film",
        "nordic_cool_matte",
        "golden_hour_glow",
        "emerald_moody",
        "fine_art_mono",
        "bright_airy",
        "vintage_slide_punch",
        "blush_rose_pastel",
        "blue_hour_noir",
        "dreamy_glow",
        "film_halation",
        "film_dust",
        "miami_neon",
        "prism_glow",
        "disposable_flash",
        "portrait_bokeh",
        "tungsten_night_film",
        "muted_chrome_film",
        "studio_spotlight",
        "poster_title_yellow_pop",
        "poster_title_blue_pop",
        "retro_70s_poster",
        "brush_script_poster",
        "neon_nights_script",
        "mission_passed_title",
        "wanted_stencil_title",
        "retrowave_neon_title",
        "art_deco_marquee",
        "velvet_ticket_title",
        "marker_frame_doodle",
        "sunny_sketchbook_doodle",
        "neon_doodle_nights",
        "chalkboard_doodle",
        "love_notes_doodle",
        "retro_70s_doodle",
        "comic_pop_doodle",
        "scrapbook_doodle",
        "cyanotype_doodle",
        "confetti_pastel_doodle",
        "print_film_2383",
        "cross_process",
        "hdr_clarity_pop",
        "bleach_bypass",
        "mocha_moody",
        "lavender_dusk",
        "hdr_noir_mono",
        "mint_pastel_film",
        "shutter_drag",
        "speed_pan",
        "red_halo_spotlight",
        "digicam_flash",
        "red_gel_portrait",
        "split_word_portrait",
        "shape_window_portrait",
        "instax_mini_classic",
        "instax_square_sunny",
        "instax_wide_cool",
        "instax_monochrome",
        "instax_sky_flash",
        "synthwave_sun",
        "diamond_editorial",
        "word_wall_poster",
        "neon_frame_sign",
        "pop_art_panel",
        "graffiti_drip_column",
        "graffiti_throwup_masthead",
        "graffiti_sticker_slap",
        "graffiti_outline_mural",
        "graffiti_outline_tower",
        "radial_swirl",
        "twirl_vortex",
        "water_ripple",
        "squiggle_wave",
        "liquid_spill",
        "codex_chalk_sepia",
        "codex_blueprint",
        "vitruvian_study",
        "inventors_notebook",
        "da_vinci_wings",
        "amber_teal_gel",
        "ice_gel_orange",
        "pistachio_gel_rose",
        "sky_gel_amber",
        "coral_gel_lagoon",
        "vista_red_film",
        "golden_consumer_film",
        "green_cast_film",
        "classic_slide_64",
        "expired_film",
    ]
    synced =get_preset_by_name("bw_bg_glowing_subject", db_path=db)
    assert synced is not None
    assert synced["ar"] == "non-square"
    assert synced["text_input"] == "no"
    assert synced["default_text"] == ""
    assert synced["text_character_limit"] == 0
    assert synced["keywords"] == [
        "grayscale",
        "black and white",
        "glow",
        "outline",
        "subject",
        "border",
    ]
    polaroid = get_preset_by_name("polaroid_memory", db_path=db)
    assert polaroid is not None
    assert polaroid["text_input"] == "yes"
    assert polaroid["default_text"] == "instant memory"


def test_search_presets_by_keyword(tmp_path: Path) -> None:
    db = tmp_path / "presets.db"
    init_db(db)
    add_preset("glow_look", "backend/presets/a.json", ["glow", "outline"], db_path=db)
    add_preset("warm_look", "backend/presets/b.json", ["warm", "sunset"], db_path=db)

    assert search_presets_by_keyword("", db_path=db) == []
    assert search_presets_by_keyword("   ", db_path=db) == []

    glow = search_presets_by_keyword("GLOW", db_path=db)
    assert len(glow) == 1
    assert glow[0]["preset_name"] == "glow_look"

    partial = search_presets_by_keyword("out", db_path=db)
    assert [r["preset_name"] for r in partial] == ["glow_look"]

    by_name = search_presets_by_keyword("warm_look", db_path=db)
    assert [r["preset_name"] for r in by_name] == ["warm_look"]

    by_name_spaced = search_presets_by_keyword("warm look", db_path=db)
    assert [r["preset_name"] for r in by_name_spaced] == ["warm_look"]

    newest_first = search_presets_by_keyword("look", db_path=db)
    assert [r["preset_name"] for r in newest_first] == ["warm_look", "glow_look"]

    assert search_presets_by_keyword("missing", db_path=db) == []


def test_add_preset_stores_ar_and_rejects_invalid(tmp_path: Path) -> None:
    db = tmp_path / "presets.db"
    init_db(db)

    square = add_preset(
        "square_look",
        "backend/presets/square.json",
        ar="square",
        db_path=db,
    )
    assert square["ar"] == "square"

    try:
        add_preset("bad", "backend/presets/bad.json", ar="wide", db_path=db)
    except ValueError as exc:
        assert "ar must be" in str(exc)
    else:
        raise AssertionError("expected ValueError for invalid ar")


def test_migrate_adds_ar_column_to_existing_db(tmp_path: Path) -> None:
    db = tmp_path / "presets.db"
    with sqlite3.connect(db) as conn:
        conn.execute(
            """
            CREATE TABLE presets (
                preset_id INTEGER PRIMARY KEY AUTOINCREMENT,
                preset_name TEXT NOT NULL UNIQUE,
                preset_path TEXT NOT NULL UNIQUE,
                keywords TEXT NOT NULL DEFAULT '[]',
                created_date TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        conn.execute(
            "INSERT INTO presets (preset_name, preset_path, keywords) "
            "VALUES ('legacy', 'backend/presets/legacy.json', '[]')"
        )
        conn.commit()

    init_db(db)
    row = get_preset_by_name("legacy", db_path=db)
    assert row is not None
    assert row["ar"] == "non-square"
    assert row["text_input"] == "no"
    assert row["default_text"] == ""
    assert row["text_character_limit"] == 0
    assert list_popular(db_path=db) == [
        {"preset_id": row["preset_id"], "preset_name": "legacy", "used_count": 0}
    ]


def test_add_preset_stores_text_fields_and_rejects_invalid(tmp_path: Path) -> None:
    db = tmp_path / "presets.db"
    init_db(db)

    row = add_preset(
        "caption_look",
        "backend/presets/caption.json",
        text_input="yes",
        default_text="Hello",
        text_character_limit=12,
        db_path=db,
    )
    assert row["text_input"] == "yes"
    assert row["default_text"] == "Hello"
    assert row["text_character_limit"] == 12

    try:
        add_preset(
            "bad_flag",
            "backend/presets/bad_flag.json",
            text_input="maybe",
            db_path=db,
        )
    except ValueError as exc:
        assert "text_input must be" in str(exc)
    else:
        raise AssertionError("expected ValueError for invalid text_input")

    try:
        add_preset(
            "bad_limit",
            "backend/presets/bad_limit.json",
            text_input="yes",
            default_text="Hi",
            text_character_limit=0,
            db_path=db,
        )
    except ValueError as exc:
        assert "text_character_limit" in str(exc)
    else:
        raise AssertionError("expected ValueError for missing character limit")


def test_popular_increments_and_sorts_descending(tmp_path: Path) -> None:
    db = tmp_path / "presets.db"
    init_db(db)
    a = add_preset("alpha", "backend/presets/a.json", db_path=db)
    b = add_preset("beta", "backend/presets/b.json", db_path=db)
    c = add_preset("gamma", "backend/presets/c.json", db_path=db)

    assert increment_used_count(999, db_path=db) is None
    assert increment_used_count_by_name("missing", db_path=db) is None
    assert increment_used_count_by_name("  ", db_path=db) is None

    first = increment_used_count_by_name("beta", db_path=db)
    second = increment_used_count(int(b["preset_id"]), db_path=db)
    third = increment_used_count_by_name("alpha", db_path=db)

    assert first == {"preset_id": b["preset_id"], "used_count": 1}
    assert second == {"preset_id": b["preset_id"], "used_count": 2}
    assert third == {"preset_id": a["preset_id"], "used_count": 1}

    ranked = list_popular(db_path=db)
    assert [row["preset_name"] for row in ranked] == ["beta", "alpha", "gamma"]
    assert [row["preset_id"] for row in ranked] == [
        b["preset_id"],
        a["preset_id"],
        c["preset_id"],
    ]
    assert [row["used_count"] for row in ranked] == [2, 1, 0]


def test_list_presets_newest_first(tmp_path: Path) -> None:
    db = tmp_path / "presets.db"
    init_db(db)
    add_preset("alpha", "backend/presets/a.json", db_path=db)
    add_preset("beta", "backend/presets/b.json", db_path=db)
    add_preset("gamma", "backend/presets/c.json", db_path=db)

    names = [row["preset_name"] for row in list_presets(db_path=db)]
    ids = [row["preset_id"] for row in list_presets(db_path=db)]
    assert names == ["gamma", "beta", "alpha"]
    assert ids == sorted(ids, reverse=True)


def test_list_popular_skips_orphan_rows(tmp_path: Path) -> None:
    db = tmp_path / "presets.db"
    init_db(db)
    row = add_preset("kept", "backend/presets/kept.json", db_path=db)

    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute(
            "INSERT INTO popular (preset_id, used_count) VALUES (?, 9)",
            (row["preset_id"] + 99,),
        )
        conn.commit()

    ranked = list_popular(db_path=db)
    assert ranked == [
        {
            "preset_id": row["preset_id"],
            "preset_name": "kept",
            "used_count": 0,
        }
    ]


def test_init_db_copies_legacy_db_once(tmp_path: Path, monkeypatch) -> None:
    init_mod = sys.modules["database.init_db"]  # the package re-exports the init_db function

    legacy = tmp_path / "presets.db"
    live = tmp_path / "presets.local.db"
    monkeypatch.setattr(init_mod, "LEGACY_DB_PATH", legacy)
    monkeypatch.setattr(init_mod, "DB_PATH", live)
    init_db(legacy)
    add_preset("demo", "backend/presets/demo.json", ["x"], db_path=legacy)
    increment_used_count_by_name("demo", db_path=legacy)

    init_db(live)
    assert [r["used_count"] for r in list_popular(db_path=live)] == [1]

    # Once the live DB exists it is never overwritten from the legacy copy.
    increment_used_count_by_name("demo", db_path=live)
    init_db(live)
    assert [r["used_count"] for r in list_popular(db_path=live)] == [2]
    assert [r["used_count"] for r in list_popular(db_path=legacy)] == [1]
