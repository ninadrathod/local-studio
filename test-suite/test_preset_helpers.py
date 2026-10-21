"""Unit tests for preset filter helpers (no rembg / no HTTP)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
HELPERS = ROOT / "backend" / "helpers"
PRESETS = ROOT / "backend" / "presets"
if str(HELPERS) not in sys.path:
    sys.path.insert(0, str(HELPERS))

import filters as F  # noqa: E402
from apply_preset import (  # noqa: E402
    FILTERS,
    photo_datetime,
    PresetAspectRatioError,
    PresetTextError,
    apply_preset,
    apply_steps,
    load_preset,
    resolve_preset_path,
    resolve_user_text,
)


def test_resolve_preset_by_name() -> None:
    path = resolve_preset_path("bw_bg_glowing_subject", presets_dir=PRESETS)
    assert path.name == "bw_bg_glowing_subject.json"


def test_preset_files_have_steps() -> None:
    data = load_preset(PRESETS / "bw_bg_glowing_subject.json")
    assert data["steps"]
    assert data["steps"][0]["filter"] == "extract_subject"
    assert data.get("ar") == "non-square"
    assert data.get("text_input") == "no"
    assert data.get("default_text") == ""
    assert data.get("text_character_limit") == 0


def test_filter_registry_is_name_lookup() -> None:
    assert set(FILTERS) >= {
        "extract_subject",
        "composite",
        "grayscale",
        "glow_line_border",
        "draw_text",
        "place_on_canvas",
        "upscale",
        "sharpen",
        "denoise",
        "ai_upscale",
        "doodle",
        "sticker_outline",
        "posterize",
        "ink_edges",
        "halftone",
        "paper_texture",
        "selective_color",
    }


def test_grayscale_and_composite() -> None:
    bg = Image.new("RGB", (32, 32), (200, 40, 40))
    subject = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    # opaque white square in center
    for y in range(8, 24):
        for x in range(8, 24):
            subject.putpixel((x, y), (255, 255, 255, 255))

    gray = F.grayscale(bg)
    assert gray.getpixel((0, 0))[0] == gray.getpixel((0, 0))[1]
    out = F.composite(gray, subject)
    assert out.getpixel((16, 16))[:3] == (255, 255, 255)


def test_glow_line_border_keeps_interior_and_accepts_color() -> None:
    subject = Image.new("RGBA", (48, 48), (0, 0, 0, 0))
    for y in range(12, 36):
        for x in range(12, 36):
            subject.putpixel((x, y), (10, 20, 30, 255))

    outlined = F.glow_line_border(subject, color=(255, 0, 0), width=4, blur=0)
    assert outlined.mode == "RGBA"
    # Interior subject pixels stay original (not filled with red glow)
    assert outlined.getpixel((24, 24))[:3] == (10, 20, 30)
    # Some ring pixel outside the solid square should pick up red
    edge = outlined.getpixel((10, 24))
    assert edge[0] > edge[1] and edge[0] > edge[2]


def test_apply_steps_without_extract() -> None:
    image = Image.new("RGB", (24, 24), (100, 120, 140))
    steps = [
        {"filter": "grayscale", "on": "image"},
        {"filter": "brightness", "on": "image", "amount": 1.1},
    ]
    out = apply_steps(image, steps)
    assert out.size == (24, 24)


def test_apply_preset_square_ar_requires_square_image(tmp_path: Path) -> None:
    preset = tmp_path / "square_only.json"
    preset.write_text(
        json.dumps(
            {
                "name": "square_only",
                "ar": "square",
                "steps": [{"filter": "grayscale", "on": "image"}],
            }
        ),
        encoding="utf-8",
    )

    wide = Image.new("RGB", (10, 6), (1, 2, 3))
    with pytest.raises(PresetAspectRatioError, match="square"):
        apply_preset(wide, preset)

    square = Image.new("RGB", (6, 6), (1, 2, 3))
    out = apply_preset(square, preset)
    assert out.size == (6, 6)


def test_draw_text_paints_over_background() -> None:
    image = Image.new("RGB", (96, 96), (0, 0, 0))
    out = F.draw_text(image, text="HI", font_size=40, color=(255, 255, 255))
    assert out.convert("L").getextrema()[1] > 0


def _first_truetype_path() -> str:
    for path in F._SANS_FONT_CANDIDATES:
        if Path(path).is_file():
            return path
    from PIL import ImageFont

    try:
        ImageFont.truetype("DejaVuSans.ttf", 12)
        return "DejaVuSans.ttf"
    except OSError:
        pytest.skip("No TrueType font available")


def test_draw_text_font_path_paints_like_align() -> None:
    font_path = _first_truetype_path()
    image = Image.new("RGB", (160, 80), (0, 0, 0))
    out = F.draw_text(
        image,
        text="HI",
        font_size=28,
        color=(255, 255, 255),
        align="bottom",
        font_path=font_path,
    )
    gray = out.convert("L")
    top_ink = gray.crop((0, 0, 160, 24)).getextrema()[1]
    bottom_ink = gray.crop((0, 56, 160, 80)).getextrema()[1]
    assert bottom_ink > top_ink
    assert gray.getextrema()[1] > 0


def test_draw_text_missing_font_path_raises() -> None:
    image = Image.new("RGB", (32, 32), (0, 0, 0))
    with pytest.raises(ValueError, match="Could not load font"):
        F.draw_text(image, text="HI", font_path="/no/such/font.ttf")


def test_apply_steps_font_path() -> None:
    font_path = _first_truetype_path()
    image = Image.new("RGB", (96, 96), (0, 0, 0))
    steps = [
        {
            "filter": "draw_text",
            "on": "image",
            "text": "HI",
            "font_size": 28,
            "color": [255, 255, 255],
            "font_path": font_path,
        }
    ]
    out = apply_steps(image, steps)
    assert out.convert("L").getextrema()[1] > 0


def test_apply_steps_binds_text_placeholder() -> None:
    image = Image.new("RGB", (96, 96), (0, 0, 0))
    steps = [
        {
            "filter": "draw_text",
            "on": "image",
            "text": "$text",
            "font_size": 36,
            "color": [255, 255, 255],
        }
    ]
    blank = apply_steps(image, steps, text="")
    painted = apply_steps(image, steps, text="HELLO")
    assert blank.convert("L").getextrema()[1] == 0
    assert painted.convert("L").getextrema()[1] > 0


def test_resolve_user_text_default_and_limit() -> None:
    preset = {
        "text_input": "yes",
        "default_text": "Hi",
        "text_character_limit": 4,
    }
    assert resolve_user_text(preset, None) == "Hi"
    assert resolve_user_text(preset, "Yo") == "Yo"
    with pytest.raises(PresetTextError, match="at most 4"):
        resolve_user_text(preset, "Hello")
    assert resolve_user_text({"text_input": "no"}, "ignored") == ""


def test_place_on_canvas_polaroid_has_larger_bottom() -> None:
    photo = Image.new("RGB", (100, 100), (10, 20, 30))
    framed = F.place_on_canvas(photo, scale=1.4, layout="polaroid", fill=(255, 255, 255))
    assert framed.size == (140, 140)
    # Top band matches side margin (~20); bottom leftover is larger.
    assert framed.getpixel((70, 10))[:3] == (255, 255, 255)
    assert framed.getpixel((70, 130))[:3] == (255, 255, 255)
    assert framed.getpixel((70, 50))[:3] == (10, 20, 30)


def test_bind_datetime_placeholder() -> None:
    from datetime import datetime

    from apply_preset import bind_placeholders

    fixed = datetime(2026, 9, 20, 18, 30)
    assert bind_placeholders("$datetime", text="", now=fixed) == "2026-09-20 18:30"
    assert bind_placeholders("$date", text="", now=fixed) == "2026-09-20"
    assert bind_placeholders("$time", text="", now=fixed) == "18:30"


def test_polaroid_memory_preset_file() -> None:
    data = load_preset(PRESETS / "polaroid_memory.json")
    assert data["ar"] == "square"
    assert data["text_input"] == "yes"
    assert data["default_text"] == "instant memory"
    assert data["text_character_limit"] == 24
    assert data["steps"][0]["filter"] == "contrast"
    assert any(s.get("filter") == "place_on_canvas" for s in data["steps"])
    assert any(s.get("text") == "$datetime" for s in data["steps"])
    assert any(s.get("text") == "$text" for s in data["steps"])


def test_apply_polaroid_memory_on_square(tmp_path: Path) -> None:
    from datetime import datetime

    from apply_preset import apply_steps

    data = load_preset(PRESETS / "polaroid_memory.json")
    square = Image.new("RGB", (80, 80), (120, 80, 40))
    out = apply_steps(
        square,
        data["steps"],
        text="instant memory",
        now=datetime(2026, 9, 20, 18, 30),
    )
    assert out.size == (112, 112)


def test_warm_faded_print_preset_file() -> None:
    data = load_preset(PRESETS / "warm_faded_print.json")
    assert data["ar"] == "non-square"
    assert data["text_input"] == "no"
    assert data["default_text"] == ""
    assert data["text_character_limit"] == 0
    assert [s["filter"] for s in data["steps"]] == [
        "contrast",
        "color",
        "brightness",
        "overlay",
    ]


def test_apply_warm_faded_print_on_non_square() -> None:
    src = (40, 90, 160)
    wide = Image.new("RGB", (24, 16), src)
    out = apply_preset(wide, PRESETS / "warm_faded_print.json")
    assert out.size == wide.size
    pixel = out.convert("RGB").getpixel((12, 8))
    assert pixel[0] > src[0]
    assert pixel[2] < src[2]


def test_upscale_hits_long_edge_and_keeps_aspect() -> None:
    out = F.upscale(Image.new("RGB", (40, 20), (10, 20, 30)), long_edge=100)
    assert out.size == (100, 50)


def test_upscale_never_shrinks_and_caps_scale() -> None:
    big = Image.new("RGB", (200, 100))
    assert F.upscale(big, long_edge=100).size == (200, 100)
    assert F.upscale(Image.new("RGB", (10, 10)), long_edge=1000, max_scale=2.0).size == (20, 20)


def test_upscale_keeps_alpha_and_rejects_bad_resample() -> None:
    rgba = Image.new("RGBA", (10, 10), (255, 0, 0, 0))
    out = F.upscale(rgba, long_edge=20)
    assert out.mode == "RGBA"
    assert out.getpixel((10, 10))[3] == 0
    with pytest.raises(ValueError):
        F.upscale(rgba, long_edge=20, resample="nearest-ish")


def test_sharpen_and_denoise_preserve_size_and_alpha() -> None:
    rgba = Image.new("RGBA", (16, 12), (90, 90, 90, 128))
    for out in (F.sharpen(rgba), F.denoise(rgba, size=3)):
        assert out.size == rgba.size
        assert out.mode == "RGBA"
        assert out.getpixel((5, 5))[3] == 128
    with pytest.raises(ValueError):
        F.denoise(rgba, size=4)


def _fake_super_resolve(rgb, denoise=0.5, tile=256):
    import numpy as np

    return np.repeat(np.repeat(rgb, 4, axis=0), 4, axis=1)


def test_ai_upscale_sizes_output(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("numpy")
    import upscale_model

    monkeypatch.setattr(upscale_model, "super_resolve", _fake_super_resolve)
    out = F.ai_upscale(Image.new("RGB", (30, 20), (1, 2, 3)), long_edge=90)
    assert out.size == (90, 60)
    assert out.getpixel((45, 30)) == (1, 2, 3)
    big = Image.new("RGB", (100, 50))
    assert F.ai_upscale(big, long_edge=80).size == (100, 50)


def test_ai_upscale_bounds_model_input_and_keeps_alpha(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("numpy")
    import upscale_model

    seen: list[tuple[int, int]] = []

    def spy(rgb, denoise=0.5, tile=256):
        seen.append(rgb.shape[:2])
        return _fake_super_resolve(rgb)

    monkeypatch.setattr(upscale_model, "super_resolve", spy)
    rgba = Image.new("RGBA", (40, 40), (5, 5, 5, 60))
    out = F.ai_upscale(rgba, long_edge=80, max_input_pixels=400)
    assert seen == [(20, 20)]
    assert out.size == (80, 80)
    assert out.mode == "RGBA"
    assert out.getpixel((40, 40))[3] == 60


def test_upscale_model_onnx_graph_and_tiling(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("numpy")
    pytest.importorskip("onnx")
    pytest.importorskip("onnxruntime")
    import numpy as np
    import upscale_model as U

    # Zero conv weights → network output is exactly the nearest-upsampled residual.
    params = {
        "body.0.weight": np.zeros((4, 3, 3, 3), np.float32),
        "body.0.bias": np.zeros(4, np.float32),
        "body.1.weight": np.full(4, 0.25, np.float32),
        "body.2.weight": np.zeros((48, 4, 3, 3), np.float32),
        "body.2.bias": np.zeros(48, np.float32),
    }
    model = U.build_onnx(params, tmp_path / "tiny.onnx")
    monkeypatch.setattr(U, "ensure_model", lambda denoise=0.5: model)
    rgb = np.random.default_rng(0).integers(0, 256, (37, 23, 3), dtype=np.uint8)
    out = U.super_resolve(rgb, tile=16, pad=4)
    assert out.shape == (148, 92, 3)
    assert np.array_equal(out, np.repeat(np.repeat(rgb, 4, axis=0), 4, axis=1))


def test_upscale_model_rejects_bad_denoise() -> None:
    pytest.importorskip("numpy")
    import upscale_model as U

    with pytest.raises(ValueError):
        U.ensure_model(1.5)


def test_hd_preset_files() -> None:
    full = load_preset(PRESETS / "full_hd.json")
    crisp = load_preset(PRESETS / "4k_crisp.json")
    for data in (full, crisp):
        assert data["ar"] == "non-square"
        assert data["text_input"] == "no"
        assert data["text_character_limit"] == 0
        assert data["steps"][0]["filter"] == "ai_upscale"
    assert full["steps"][0]["long_edge"] == 1920
    assert crisp["steps"][0]["long_edge"] == 3840
    assert [s["filter"] for s in crisp["steps"]] == ["ai_upscale", "sharpen", "contrast"]


def test_upscale_model_download_uses_timeout_and_cleans_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("numpy")
    import io
    import upscale_model as U

    seen: dict[str, object] = {}

    def fake_urlopen(url, timeout=None, context=None):
        seen["timeout"] = timeout
        seen["verify"] = context.verify_mode
        return io.BytesIO(b"not the real weights")

    monkeypatch.setattr(U, "MODEL_DIR", tmp_path)
    monkeypatch.setattr(U.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(RuntimeError, match="Checksum mismatch"):
        U.download_weights("realesr-general-x4v3.pth")
    assert seen["timeout"] == U.DOWNLOAD_TIMEOUT
    assert seen["verify"] == __import__("ssl").CERT_REQUIRED
    assert list(tmp_path.iterdir()) == []

    def stalled(url, timeout=None, context=None):
        raise TimeoutError("read timed out")

    monkeypatch.setattr(U.urllib.request, "urlopen", stalled)
    with pytest.raises(TimeoutError):
        U.download_weights("realesr-general-x4v3.pth")
    assert list(tmp_path.iterdir()) == []


def test_upscale_model_build_onnx_is_atomic(tmp_path: Path) -> None:
    pytest.importorskip("numpy")
    pytest.importorskip("onnx")
    import numpy as np
    import upscale_model as U

    params = {
        "body.0.weight": np.zeros((48, 3, 3, 3), np.float32),
        "body.0.bias": np.zeros(48, np.float32),
    }
    dest = U.build_onnx(params, tmp_path / "m.onnx")
    assert [p.name for p in tmp_path.iterdir()] == ["m.onnx"]
    assert dest.stat().st_size > 0


@pytest.mark.parametrize("style", ["xo", "rings", "wiggles", "stars"])
def test_doodle_styles_draw_white_and_keep_size(style: str) -> None:
    base = Image.new("RGB", (200, 120), (20, 20, 20))
    out = F.doodle(base, style=style, anchor="center", size=0.6, count=3)
    assert out.size == base.size
    assert out.mode == "RGB"
    assert out.convert("L").getextrema()[1] > 200


def test_doodle_is_deterministic_and_seeded() -> None:
    base = Image.new("RGB", (160, 160), (0, 0, 0))
    a = F.doodle(base, style="xo", seed=1)
    assert a.tobytes() == F.doodle(base, style="xo", seed=1).tobytes()
    assert a.tobytes() != F.doodle(base, style="xo", seed=2).tobytes()


def test_doodle_anchor_places_in_corner() -> None:
    base = Image.new("RGB", (200, 200), (0, 0, 0))
    out = F.doodle(base, style="xo", anchor="top_right", size=0.2).convert("L")
    bbox = out.point(lambda v: 255 if v > 60 else 0).getbbox()
    assert bbox is not None
    assert bbox[0] > 100 and bbox[3] < 100


def test_doodle_subject_anchor_centres_on_around_layer() -> None:
    base = Image.new("RGB", (200, 200), (0, 0, 0))
    subject = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    subject.paste((255, 0, 0, 255), (120, 120, 180, 180))
    out = F.doodle(base, style="rings", anchor="subject", around=subject, size=0.3, count=2)
    bbox = out.convert("L").point(lambda v: 255 if v > 60 else 0).getbbox()
    assert bbox is not None
    assert abs((bbox[0] + bbox[2]) / 2 - 150) < 6
    assert abs((bbox[1] + bbox[3]) / 2 - 150) < 6


def test_doodle_rejects_bad_params() -> None:
    base = Image.new("RGB", (50, 50))
    with pytest.raises(ValueError):
        F.doodle(base, style="hearts")
    with pytest.raises(ValueError):
        F.doodle(base, anchor="middle_ish")
    with pytest.raises(ValueError):
        F.doodle(base, count=0)
    with pytest.raises(ValueError):
        F.doodle(base, count=F.DOODLE_MAX_COUNT + 1)


def test_apply_steps_doodle_with_around_layer() -> None:
    background = Image.new("RGB", (64, 64), (10, 10, 10))
    subject = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    subject.paste((200, 50, 50, 255), (24, 24, 40, 40))
    layers = {"background": background, "subject": subject}
    steps = [
        {"filter": "doodle", "on": "background", "style": "rings", "anchor": "subject", "around": "subject"},
        {"filter": "composite", "base": "background", "overlay": "subject", "as": "image"},
    ]
    from apply_preset import FILTERS as REG

    for i, step in enumerate(steps):
        params = dict(step)
        REG[params.pop("filter")](layers, index=i, **params)
    assert layers["image"].size == (64, 64)
    with pytest.raises(KeyError):
        REG["doodle"](layers, index=0, on="background", around="missing")


def test_doodle_preset_files() -> None:
    for name, styles in (
        ("doodle_corner_xo", ["xo", "wiggles"]),
        ("doodle_halo_rings", ["rings", "stars"]),
    ):
        data = load_preset(PRESETS / f"{name}.json")
        assert data["ar"] == "non-square"
        assert data["text_input"] == "no"
        filters = [s["filter"] for s in data["steps"]]
        assert filters[0] == "extract_subject"
        assert filters[1] == "sticker_outline"
        assert filters[-1] == "composite"
        assert [s["style"] for s in data["steps"] if s["filter"] == "doodle"] == styles
        assert all(s["on"] == "background" for s in data["steps"] if s["filter"] == "doodle")
        assert data["steps"][0]["single_subject"] is True
        assert all(s["color"] == "auto" for s in data["steps"] if s["filter"] == "doodle")


def test_doodle_draws_only_near_anchor_and_offscreen_is_noop() -> None:
    base = Image.new("RGB", (400, 400), (0, 0, 0))
    out = F.doodle(base, style="stars", anchor="top_left", size=0.2, count=2)
    bbox = out.convert("L").point(lambda v: 255 if v > 40 else 0).getbbox()
    assert bbox is not None and bbox[2] < 200 and bbox[3] < 200
    off = F.doodle(base, style="xo", x=5.0, y=5.0)
    assert off.tobytes() == base.tobytes()


def test_doodle_large_region_skips_supersample(monkeypatch: pytest.MonkeyPatch) -> None:
    sizes: list[tuple[int, int]] = []
    real_new = Image.new

    def spy(mode, size, *args, **kwargs):
        if mode == "RGBA":
            sizes.append(tuple(size))
        return real_new(mode, size, *args, **kwargs)

    monkeypatch.setattr(F.Image, "new", spy)
    monkeypatch.setattr(F, "_DOODLE_SUPERSAMPLE_MAX_PIXELS", 100)
    F.doodle(real_new("RGB", (60, 60)), style="rings", anchor="center", size=0.8)
    assert sizes and max(w * h for w, h in sizes) <= 60 * 60


def test_sticker_outline_scales_with_image_and_keeps_subject() -> None:
    def outline_px(side: int) -> int:
        subject = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        lo, hi = side // 4, side * 3 // 4
        subject.paste((200, 0, 0, 255), (lo, lo, hi, hi))
        out = F.sticker_outline(subject, width_ratio=0.02, softness=0)
        assert out.getpixel((side // 2, side // 2)) == (200, 0, 0, 255)
        assert out.getpixel((lo - 2, side // 2))[:3] == (255, 255, 255)
        return lo - out.getchannel("A").getbbox()[0]

    small, large = outline_px(200), outline_px(800)
    assert 3 <= small <= 6
    assert 14 <= large <= 22
    with pytest.raises(ValueError):
        F.sticker_outline(Image.new("RGBA", (10, 10)), width_ratio=0)


def test_is_reliable_cutout_rejects_smear_and_tiny_masks() -> None:
    solid = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
    solid.paste((9, 9, 9, 255), (20, 20, 80, 80))
    assert F.is_reliable_cutout(solid)
    smear = Image.new("RGBA", (100, 100), (0, 0, 0, 60))
    smear.paste((9, 9, 9, 255), (48, 48, 52, 52))
    assert not F.is_reliable_cutout(smear)
    assert not F.is_reliable_cutout(Image.new("RGBA", (100, 100), (0, 0, 0, 0)))
    assert not F.is_reliable_cutout(Image.new("RGB", (10, 10)))


def test_extract_subject_layers_falls_back_when_cutout_unreliable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import types

    smear = Image.new("RGBA", (40, 40), (0, 0, 0, 50))
    fake = types.ModuleType("extract_subject")
    fake.extract_subject = lambda image: smear
    monkeypatch.setitem(sys.modules, "extract_subject", fake)
    original = Image.new("RGB", (40, 40), (90, 120, 150))
    subject, background = F.extract_subject_layers(original, require_clear_subject=True)
    assert subject.getchannel("A").getbbox() is None
    assert background.tobytes() == original.tobytes()

    # Off by default: existing presets keep the rembg mask as-is.
    kept, _ = F.extract_subject_layers(original)
    assert kept.tobytes() == smear.tobytes()


def _two_island_alpha() -> Image.Image:
    alpha = Image.new("L", (300, 200), 0)
    alpha.paste(255, (10, 60, 130, 200))  # large "person"
    alpha.paste(255, (180, 10, 280, 110))  # smaller "frame"
    return alpha


def test_keep_main_subject_drops_smaller_islands() -> None:
    alpha = _two_island_alpha()
    alpha.paste(70, (130, 100, 136, 120))  # soft fringe hugging the body
    kept = F.keep_main_subject(alpha)
    assert kept.getpixel((70, 130)) == 255
    assert kept.getpixel((133, 110)) == 70
    assert kept.getpixel((230, 60)) == 0
    # One island (or none) comes back unchanged.
    single = Image.new("L", (80, 80), 0)
    single.paste(255, (20, 20, 60, 60))
    assert F.keep_main_subject(single).tobytes() == single.tobytes()
    empty = Image.new("L", (40, 40), 0)
    assert F.keep_main_subject(empty).tobytes() == empty.tobytes()
    # Too many islands to rank (speckle noise): leave the mask alone.
    noisy = Image.new("L", (256, 256), 0)
    for i in range(300):
        x, y = (i % 20) * 12 + 2, (i // 20) * 12 + 2
        noisy.paste(255, (x, y, x + 3, y + 3))
    assert F.keep_main_subject(noisy).tobytes() == noisy.tobytes()


def test_keep_main_subject_prefers_island_touching_bottom() -> None:
    alpha = Image.new("L", (300, 200), 0)
    alpha.paste(255, (10, 10, 160, 110))  # bigger sign on the wall
    alpha.paste(255, (200, 100, 260, 200))  # person cropped by the bottom edge
    kept = F.keep_main_subject(alpha)
    assert kept.getpixel((230, 150)) == 255
    assert kept.getpixel((80, 60)) == 0
    # A tiny bottom crumb doesn't beat a large floating subject.
    crumb = Image.new("L", (300, 200), 0)
    crumb.paste(255, (10, 10, 200, 150))
    crumb.paste(255, (260, 190, 266, 200))
    assert F.keep_main_subject(crumb).getpixel((100, 80)) == 255


def test_keep_main_subject_keeps_two_people_side_by_side() -> None:
    alpha = Image.new("L", (300, 200), 0)
    alpha.paste(255, (10, 60, 110, 200))
    alpha.paste(255, (180, 80, 260, 200))
    alpha.paste(255, (120, 5, 170, 40))  # floating frame still dropped
    kept = F.keep_main_subject(alpha)
    assert kept.getpixel((60, 130)) == 255
    assert kept.getpixel((220, 150)) == 255
    assert kept.getpixel((145, 20)) == 0


def test_keep_main_subject_is_bounded_on_panoramas() -> None:
    import time

    alpha = Image.new("L", (12000, 400), 0)
    for i in range(40):  # many islands across a very wide frame
        alpha.paste(255, (i * 300, 100, i * 300 + 120, 400 if i == 0 else 300))
    start = time.perf_counter()
    kept = F.keep_main_subject(alpha)
    assert time.perf_counter() - start < 5
    assert kept.getpixel((60, 350)) == 255
    assert kept.getpixel((3060, 200)) == 0


def test_keep_main_subject_merges_pieces_across_a_small_gap() -> None:
    alpha = Image.new("L", (400, 400), 0)
    alpha.paste(255, (50, 50, 200, 350))
    alpha.paste(255, (202, 100, 260, 200))  # arm split off by a 2 px seam
    assert F.keep_main_subject(alpha).getpixel((230, 150)) == 255


def test_extract_subject_layers_single_subject(monkeypatch: pytest.MonkeyPatch) -> None:
    import types

    cutout = Image.new("RGBA", (300, 200), (200, 50, 50, 0))
    cutout.putalpha(_two_island_alpha())
    fake = types.ModuleType("extract_subject")
    fake.extract_subject = lambda image: cutout.copy()
    monkeypatch.setitem(sys.modules, "extract_subject", fake)
    original = Image.new("RGB", (300, 200), (90, 120, 150))
    subject, background = F.extract_subject_layers(original, single_subject=True)
    assert subject.getpixel((230, 60))[3] == 0
    assert subject.getpixel((70, 130))[3] == 255
    # The dropped island stays as untouched background, not a blurred hole.
    assert background.getpixel((230, 60)) == (90, 120, 150)
    both, _ = F.extract_subject_layers(original)
    assert both.getpixel((230, 60))[3] == 255


def test_doodle_auto_color_contrasts_with_background() -> None:
    light = F.doodle(Image.new("RGB", (200, 200), (235, 230, 215)), style="xo", anchor="center", size=0.6, color="auto")
    assert light.convert("L").getextrema()[0] < 80
    dark = F.doodle(Image.new("RGB", (200, 200), (20, 20, 20)), style="xo", anchor="center", size=0.6, color="auto")
    assert dark.convert("L").getextrema()[1] > 200
    with pytest.raises(ValueError):
        F.doodle(Image.new("RGB", (50, 50)), color="pink")


def test_doodle_avoid_subject_moves_to_mirrored_corner() -> None:
    base = Image.new("RGB", (200, 200), (0, 0, 0))
    subject = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    subject.paste((255, 0, 0, 255), (0, 100, 100, 200))  # covers bottom-left
    out = F.doodle(base, style="xo", anchor="bottom_left", size=0.2, around=subject, avoid_subject=True)
    bbox = out.convert("L").point(lambda v: 255 if v > 60 else 0).getbbox()
    assert bbox is not None and bbox[0] > 100 and bbox[1] > 100
    # Without the flag (or with a clear corner) the anchor is respected.
    stay = F.doodle(base, style="xo", anchor="bottom_left", size=0.2, around=subject)
    bbox = stay.convert("L").point(lambda v: 255 if v > 60 else 0).getbbox()
    assert bbox is not None and bbox[2] < 100


def test_doodle_avoid_busy_skips_cluttered_corner() -> None:
    from PIL import ImageDraw

    base = Image.new("RGB", (400, 400), (0, 0, 0))
    draw = ImageDraw.Draw(base)
    for i in range(220, 400, 16):  # bold stripes fill the top-right corner
        draw.rectangle((i, 0, i + 7, 180), fill=(140, 140, 140))
    out = F.doodle(base, style="xo", anchor="top_right", size=0.2, avoid_busy=True)
    diff = Image.eval(F.ImageChops.difference(out, base).convert("L"), lambda v: 255 if v > 60 else 0)
    bbox = diff.getbbox()
    assert bbox is not None and bbox[2] < 200 and bbox[3] < 200  # moved to top-left
    calm = Image.new("RGB", (400, 400), (0, 0, 0))
    out = F.doodle(calm, style="xo", anchor="top_right", size=0.2, avoid_busy=True)
    bbox = out.convert("L").point(lambda v: 255 if v > 60 else 0).getbbox()
    assert bbox is not None and bbox[0] > 200


def test_is_reliable_cutout_accepts_fluffy_edges_near_body() -> None:
    from PIL import ImageDraw

    def blob(r_body: int, r_soft: int, soft_alpha: int = 90) -> Image.Image:
        alpha = Image.new("L", (400, 400), 0)
        draw = ImageDraw.Draw(alpha)
        draw.ellipse((200 - r_soft, 200 - r_soft, 200 + r_soft, 200 + r_soft), fill=soft_alpha)
        draw.ellipse((200 - r_body, 200 - r_body, 200 + r_body, 200 + r_body), fill=255)
        subject = Image.new("RGBA", (400, 400), (0, 0, 0, 0))
        subject.putalpha(alpha)
        return subject

    # Fur area > body area, but hugging the body → still a real subject.
    assert F.is_reliable_cutout(blob(60, 95))
    # Soft haze far beyond the body → smear.
    assert not F.is_reliable_cutout(blob(30, 190))


def test_doodle_presets_require_clear_subject() -> None:
    for name in ("doodle_corner_xo", "doodle_halo_rings"):
        step = load_preset(PRESETS / f"{name}.json")["steps"][0]
        assert step["filter"] == "extract_subject"
        assert step["require_clear_subject"] is True
    assert "require_clear_subject" not in load_preset(PRESETS / "bw_bg_glowing_subject.json")["steps"][0]


def test_run_extract_subject_passes_require_clear_subject(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[bool, bool]] = []

    def fake_layers(image, require_clear_subject=False, single_subject=False):
        seen.append((require_clear_subject, single_subject))
        return Image.new("RGBA", image.size), image

    monkeypatch.setattr(F, "extract_subject_layers", fake_layers)
    layers = {"image": Image.new("RGB", (8, 8))}
    FILTERS["extract_subject"](layers, index=0, on="image", require_clear_subject=True)
    FILTERS["extract_subject"](layers, index=1, on="image", single_subject=True)
    FILTERS["extract_subject"](layers, index=2, on="image")
    assert seen == [(True, False), (False, True), (False, False)]


def _gradient(width: int = 120, height: int = 80) -> Image.Image:
    img = Image.new("RGB", (width, height))
    for x in range(width):
        v = int(x / (width - 1) * 255)
        for y in range(height):
            img.putpixel((x, y), (v, 255 - v, (v + y) % 256))
    return img


def test_posterize_limits_channel_values_and_keeps_alpha() -> None:
    out = F.posterize(_gradient(), levels=4, smooth=0)
    allowed = {0, 85, 170, 255}
    for band in out.split():
        assert {v for v, n in enumerate(band.histogram()) if n} <= allowed
    rgba = Image.new("RGBA", (10, 10), (100, 150, 200, 77))
    assert F.posterize(rgba, levels=3).getpixel((5, 5))[3] == 77
    with pytest.raises(ValueError):
        F.posterize(rgba, levels=1)
    with pytest.raises(ValueError):
        F.posterize(rgba, smooth=4)


def test_ink_edges_draws_dark_line_on_boundary_only() -> None:
    img = Image.new("RGB", (100, 100), (230, 230, 230))
    img.paste((40, 40, 40), (50, 0, 100, 100))
    out = F.ink_edges(img, detail=0.02, threshold=4, thickness=0.0)
    assert out.size == img.size
    assert out.getpixel((10, 50)) == (230, 230, 230)
    row = [out.getpixel((x, 50))[0] for x in range(40, 60)]
    assert min(row) < 40
    faint = F.ink_edges(img, detail=0.02, threshold=4, thickness=0.0, opacity=0.3)
    assert min(faint.getpixel((x, 50))[0] for x in range(40, 60)) > min(row)


@pytest.mark.parametrize("mode", ["mono", "cmyk"])
def test_halftone_preserves_tone_roughly(mode: str) -> None:
    for grey in (60, 128, 200):
        img = Image.new("RGB", (160, 160), (grey, grey, grey))
        out = F.halftone(img, mode=mode, cell=0.06).convert("L")
        assert out.size == img.size
        mean = sum(v * n for v, n in enumerate(out.histogram())) / (160 * 160)
        assert abs(mean - grey) < 45


def test_halftone_draws_dots_and_mix_blends_back() -> None:
    img = Image.new("RGB", (120, 120), (128, 128, 128))
    out = F.halftone(img, mode="mono", cell=0.08, paper=[250, 250, 250], ink=[0, 0, 0])
    lo, hi = out.convert("L").getextrema()
    assert lo < 40 and hi > 220
    half = F.halftone(img, mode="mono", cell=0.08, mix=0.0)
    assert half.tobytes() == img.tobytes()
    with pytest.raises(ValueError):
        F.halftone(img, mode="spot")
    with pytest.raises(ValueError):
        F.halftone(img, cell=0.5)


def test_separate_cmyk_moves_grey_to_black_plate() -> None:
    c, m, y, k = F._separate_cmyk(Image.new("RGB", (4, 4), (100, 100, 100)), gcr=1.0)
    assert k.getpixel((0, 0)) == 155
    assert c.getpixel((0, 0)) == m.getpixel((0, 0)) == y.getpixel((0, 0)) == 0
    c2, _, _, k2 = F._separate_cmyk(Image.new("RGB", (4, 4), (255, 0, 0)), gcr=1.0)
    assert k2.getpixel((0, 0)) == 0 and c2.getpixel((0, 0)) == 0


def test_halftone_large_image_is_bounded_and_keeps_size() -> None:
    big = Image.new("RGB", (F._HALFTONE_MAX_EDGE * 2, 300), (128, 128, 128))
    out = F.halftone(big, mode="mono", cell=0.05)
    assert out.size == big.size


def test_paper_texture_tints_and_is_deterministic() -> None:
    img = Image.new("RGB", (64, 64), (255, 255, 255))
    a = F.paper_texture(img, color=[230, 210, 170], tint=1.0, grain=0.1, stains=0.3, seed=4)
    assert a.tobytes() == F.paper_texture(img, color=[230, 210, 170], tint=1.0, grain=0.1, stains=0.3, seed=4).tobytes()
    assert a.tobytes() != F.paper_texture(img, color=[230, 210, 170], tint=1.0, grain=0.1, stains=0.3, seed=5).tobytes()
    r, g, b = a.getpixel((30, 30))
    assert r > b
    plain = F.paper_texture(img, tint=0, grain=0, stains=0, fade=0)
    assert plain.tobytes() == img.tobytes()
    black = F.paper_texture(Image.new("RGB", (8, 8)), tint=0, grain=0, stains=0, fade=1.0, color=[200, 190, 170])
    assert black.getpixel((4, 4)) == (200, 190, 170)


def test_comic_newsprint_preset_files() -> None:
    expected = {
        "comic_pop": ["contrast", "color", "posterize", "halftone", "ink_edges", "paper_texture"],
        "old_newspaper": ["grayscale", "brightness", "contrast", "halftone", "paper_texture"],
        "vintage_comic": ["brightness", "color", "posterize", "halftone", "ink_edges", "paper_texture"],
    }
    for name, filters in expected.items():
        data = load_preset(PRESETS / f"{name}.json")
        assert data["ar"] == "non-square"
        assert data["text_input"] == "no"
        assert [s["filter"] for s in data["steps"]] == filters


@pytest.mark.parametrize("name", ["comic_pop", "old_newspaper", "vintage_comic"])
def test_apply_comic_newsprint_presets_on_non_square(name: str) -> None:
    out = apply_preset(_gradient(150, 90), PRESETS / f"{name}.json")
    assert out.size == (150, 90)


def test_halftone_caps_dot_count(monkeypatch: pytest.MonkeyPatch) -> None:
    cells: list[float] = []
    real = F._dot_screen

    def spy(ink, cell, angle):
        cells.append(cell)
        return real(ink, cell, angle)

    monkeypatch.setattr(F, "_dot_screen", spy)
    monkeypatch.setattr(F, "_HALFTONE_MAX_DOTS", 500)
    img = Image.new("RGB", (200, 100), (128, 128, 128))
    F.halftone(img, mode="mono", cell=0.002)
    area = (200 + 100) ** 2 / 2
    assert cells and area / cells[0] ** 2 <= 500 + 1


def test_halftone_and_ink_edges_ignore_pixels_under_transparency() -> None:
    # Hidden RGB is black, but fully transparent: it must not print ink or edges.
    rgba = Image.new("RGBA", (120, 120), (0, 0, 0, 0))
    rgba.paste((200, 200, 200, 255), (30, 30, 90, 90))
    paper = [250, 245, 235]
    out = F.halftone(rgba, mode="mono", cell=0.05, paper=paper)
    assert out.mode == "RGBA"
    # Transparent area prints exactly like plain paper, not like the hidden black.
    plain = F.halftone(Image.new("RGB", (120, 120), tuple(paper)), mode="mono", cell=0.05, paper=paper)
    box = (0, 0, 20, 20)
    assert out.convert("RGB").crop(box).tobytes() == plain.crop(box).tobytes()
    hidden_black = F.halftone(Image.new("RGB", (120, 120), (0, 0, 0)), mode="mono", cell=0.05, paper=paper)
    assert out.convert("RGB").crop(box).tobytes() != hidden_black.crop(box).tobytes()
    flat = F._flatten(rgba, paper)
    assert flat.getpixel((5, 5)) == tuple(paper)
    assert flat.getpixel((60, 60)) == (200, 200, 200)
    edges = F.ink_edges(rgba, detail=0.02, threshold=4, thickness=0.0)
    assert edges.getpixel((5, 5))[3] == 0
    assert edges.getpixel((60, 60))[:3] == (200, 200, 200)


def test_paper_texture_stains_follow_aspect_ratio(monkeypatch: pytest.MonkeyPatch) -> None:
    sizes: list[tuple[int, int]] = []
    real = Image.frombytes

    def spy(mode, size, data, *args, **kwargs):
        sizes.append(tuple(size))
        return real(mode, size, data, *args, **kwargs)

    monkeypatch.setattr(F.Image, "frombytes", spy)
    F.paper_texture(Image.new("RGB", (1000, 100)), grain=0, stains=0.5)
    assert sizes == [(120, 12)]


def test_paper_texture_tone_curves_match_blend_math() -> None:
    img = Image.new("RGB", (4, 4), (200, 100, 50))
    paper = (240, 200, 160)
    tinted = F.paper_texture(img, color=list(paper), tint=0.5, grain=0, stains=0, fade=0)
    expected = tuple(round(v * (1 - 0.5 + 0.5 * p / 255)) for v, p in zip((200, 100, 50), paper))
    assert tinted.getpixel((1, 1)) == expected
    faded = F.paper_texture(Image.new("RGB", (4, 4), (0, 250, 100)), color=list(paper), tint=0, grain=0, stains=0, fade=0.5)
    assert faded.getpixel((1, 1)) == (120, 250, 130)


def test_filters_do_not_mutate_input() -> None:
    img = _gradient(80, 60)
    before = img.tobytes()
    F.ink_edges(img)
    F.paper_texture(img, grain=0.2, stains=0.5)
    F.halftone(img, mode="cmyk", cell=0.05)
    assert img.tobytes() == before


def _ring_width(out: Image.Image, row: int) -> int:
    """Count tinted (glow) pixels along one row of a glow_line_border result."""
    pixels = [out.getpixel((x, row)) for x in range(out.width)]
    return sum(1 for r, g, _, a in pixels if a > 100 and g > 150 and r < 80)


def test_glow_line_border_ratio_scales_with_resolution() -> None:
    def ring(side: int, **kw) -> int:
        subject = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        subject.paste((200, 0, 0, 255), (side // 4, side // 4, side * 3 // 4, side * 3 // 4))
        return _ring_width(F.glow_line_border(subject, color=[0, 255, 200], **kw), side // 2)

    small, large = ring(200, width_ratio=0.03, blur_ratio=0), ring(800, width_ratio=0.03, blur_ratio=0)
    assert small > 0 and abs(large / small - 4) < 1
    # Fixed px params keep their original meaning.
    assert ring(200, width=4, blur=0) == ring(800, width=4, blur=0)
    with pytest.raises(ValueError):
        F.glow_line_border(Image.new("RGBA", (10, 10)), width_ratio=-1)


def test_glow_border_ratio_scales_with_resolution() -> None:
    def spread(side: int) -> int:
        subject = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        subject.paste((200, 0, 0, 255), (side // 4, side // 4, side * 3 // 4, side * 3 // 4))
        out = F.glow_border(subject, width_ratio=0.04, blur_ratio=0)
        return out.getchannel("A").getbbox()[2] - side * 3 // 4

    assert abs(spread(800) / spread(200) - 4) < 1


def test_draw_text_ratio_params_scale_with_canvas() -> None:
    def text_height(side: int) -> int:
        canvas = Image.new("RGB", (side, side), (255, 255, 255))
        out = F.draw_text(canvas, text="Hi", color=[0, 0, 0], font_size_ratio=0.1, margin_ratio=0.02, align="top")
        bbox = out.convert("L").point(lambda v: 255 if v < 128 else 0).getbbox()
        assert bbox is not None and bbox[1] >= int(0.02 * side) - 2
        return bbox[3] - bbox[1]

    assert abs(text_height(1200) / text_height(300) - 4) < 1


def test_draw_text_shrinks_large_fonts_to_fit() -> None:
    canvas = Image.new("RGB", (600, 200), (255, 255, 255))
    out = F.draw_text(canvas, text="a fairly long caption", color=[0, 0, 0], font_size=900)
    bbox = out.convert("L").point(lambda v: 255 if v < 128 else 0).getbbox()
    assert bbox is not None and bbox[2] - bbox[0] <= 600 * 0.9 + 2


def test_shipped_presets_use_resolution_relative_sizes() -> None:
    for name, filt, keys in (
        ("bw_bg_glowing_subject", "glow_line_border", ("width_ratio", "blur_ratio")),
        ("polaroid_memory", "draw_text", ("font_size_ratio", "margin_ratio")),
    ):
        data = load_preset(PRESETS / f"{name}.json")
        steps = [s for s in data["steps"] if s["filter"] == filt]
        assert steps and all(all(k in s for k in keys) for s in steps)
        assert all("width" not in s and "font_size" not in s for s in steps)


PRO_GRADE_PRESETS = [
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
]


def _ramp(width: int = 64, height: int = 16) -> Image.Image:
    """Neutral grey ramp, black → white left to right, plus one saturated and one muted strip."""
    img = Image.new("RGB", (width, height))
    for x in range(width):
        v = round(255 * x / (width - 1))
        for y in range(height):
            img.putpixel((x, y), (v, v, v))
    return img


def test_color_grade_neutral_is_identity_and_keeps_alpha() -> None:
    base = _gradient()
    assert F.color_grade(base).tobytes() == base.tobytes()
    rgba = base.convert("RGBA")
    rgba.putalpha(77)
    out = F.color_grade(rgba, temperature=0.5, split=0.4, shadows=[0, 80, 120])
    assert out.mode == "RGBA" and out.getchannel("A").getextrema() == (77, 77)


def test_color_grade_white_balance_and_exposure() -> None:
    grey = Image.new("RGB", (8, 8), (128, 128, 128))
    r, g, b = F.color_grade(grey, temperature=0.6).getpixel((0, 0))
    assert r > 128 > b
    r, g, b = F.color_grade(grey, temperature=-0.6).getpixel((0, 0))
    assert b > 128 > r
    assert F.color_grade(grey, tint=0.8).getpixel((0, 0))[1] < 128  # magenta = less green
    assert F.color_grade(grey, exposure=1.0).getpixel((0, 0))[0] > 240
    assert F.color_grade(grey, exposure=-1.0).getpixel((0, 0))[0] < 70


def test_color_grade_tone_curve_shapes() -> None:
    ramp = _ramp()
    def value(img: Image.Image, x: int) -> int:
        return img.getpixel((x, 0))[0]

    punchy = F.color_grade(ramp, contrast=0.8)
    assert value(punchy, 10) < value(ramp, 10) and value(punchy, 55) > value(ramp, 55)
    flat = F.color_grade(ramp, contrast=-0.8)
    assert value(flat, 5) > value(ramp, 5) and value(flat, 60) < value(ramp, 60)
    matte = F.color_grade(ramp, black_lift=0.2)
    assert value(matte, 0) >= 50  # blacks fade, no true black
    rolled = F.color_grade(ramp, white_rolloff=1.0)
    assert value(rolled, 63) < 255 and value(rolled, 20) == value(ramp, 20)
    # Every curve stays monotonic, so gradients never band or invert.
    for img in (punchy, flat, matte, rolled):
        values = [value(img, x) for x in range(64)]
        assert values == sorted(values)


def test_color_grade_split_tone_keeps_luminance_and_targets_range() -> None:
    ramp = _ramp()
    out = F.color_grade(ramp, shadows=[0, 90, 140], highlights=[255, 160, 60], split=1.0)
    dark, light = out.getpixel((8, 0)), out.getpixel((58, 0))
    assert dark[2] > dark[0]  # shadows lean blue/teal
    assert light[0] > light[2]  # highlights lean orange
    middle_in, middle_out = ramp.getpixel((32, 0)), out.getpixel((32, 0))
    assert max(abs(a - b) for a, b in zip(middle_in, middle_out)) <= 6  # crossover barely touched

    def luma(px: tuple[int, int, int]) -> float:
        return 0.2126 * px[0] + 0.7152 * px[1] + 0.0722 * px[2]

    for x in (8, 58, 62):  # 62 ≈ 248: near white, where naive clipping would lose brightness
        assert abs(luma(out.getpixel((x, 0))) - luma(ramp.getpixel((x, 0)))) < 4
    assert all(0 <= c <= 255 for c in out.getpixel((62, 0)))


def test_color_grade_vibrance_favours_muted_colours() -> None:
    img = Image.new("RGB", (2, 1))
    img.putpixel((0, 0), (140, 120, 110))  # muted skin-like
    img.putpixel((1, 0), (230, 30, 30))  # already saturated red
    out = F.color_grade(img, vibrance=1.0)

    def spread(px: tuple[int, int, int]) -> int:
        return max(px) - min(px)

    muted_gain = spread(out.getpixel((0, 0))) / spread(img.getpixel((0, 0)))
    vivid_gain = spread(out.getpixel((1, 0))) / spread(img.getpixel((1, 0)))
    assert muted_gain > 1.3 and vivid_gain < 1.1
    grey = F.color_grade(img, saturation=0.0).getpixel((1, 0))
    assert max(grey) - min(grey) <= 1


def test_color_grade_strips_match_single_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    base = _gradient(120, 80)
    kw = dict(split=0.6, shadows=[0, 90, 140], highlights=[255, 170, 90], vibrance=0.4)
    whole = F.color_grade(base, **kw)
    monkeypatch.setattr(F, "_GRADE_STRIP_PIXELS", 120 * 7)  # 7-row strips
    assert F.color_grade(base, **kw).tobytes() == whole.tobytes()


def test_vignette_darkens_edges_not_centre_and_scales() -> None:
    for size in ((300, 200), (200, 300), (900, 600)):
        white = Image.new("RGB", size, (255, 255, 255))
        out = F.vignette(white, amount=0.6, midpoint=0.3, feather=0.5)
        w, h = size
        assert out.getpixel((w // 2, h // 2)) == (255, 255, 255)
        assert out.getpixel((1, 1))[0] < 150
        assert out.getpixel((w - 2, h - 2))[0] < 150
    tinted = F.vignette(Image.new("RGB", (100, 100), (255, 255, 255)), amount=1.0, midpoint=0.2, color=[200, 0, 0])
    corner = tinted.getpixel((0, 0))
    assert corner[0] > corner[1] + 100  # pulls toward the tint, not black
    same = Image.new("RGB", (10, 10), (9, 9, 9))
    assert F.vignette(same, amount=0).tobytes() == same.tobytes()


def test_vignette_roundness_makes_circle_on_wide_frames() -> None:
    wide = Image.new("RGB", (400, 100), (255, 255, 255))
    frame = F.vignette(wide, amount=1.0, midpoint=0.5, feather=0.2, roundness=0.0)
    circle = F.vignette(wide, amount=1.0, midpoint=0.5, feather=0.2, roundness=1.0)
    # A circular falloff reaches the far left/right edges harder than a frame-shaped one.
    assert circle.getpixel((5, 50))[0] < frame.getpixel((5, 50))[0]


@pytest.mark.parametrize("name", PRO_GRADE_PRESETS)
def test_pro_grade_preset_files(name: str) -> None:
    data = load_preset(PRESETS / f"{name}.json")
    assert data["name"] == name
    assert data["ar"] == "non-square" and data["text_input"] == "no"
    assert data["default_text"] == "" and data["text_character_limit"] == 0
    steps = data["steps"]
    assert steps[0] == {"filter": "ai_upscale", "on": "image", "long_edge": 1920, "denoise": 0.3}
    assert any(s["filter"] == "color_grade" for s in steps)
    assert all(s["filter"] in FILTERS for s in steps)


@pytest.mark.parametrize("name", PRO_GRADE_PRESETS)
def test_pro_grade_presets_apply_without_upscale(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    # Skip the ONNX model: stub ai_upscale to a plain resize so the grade steps run fast.
    monkeypatch.setattr(F, "ai_upscale", lambda image, **kw: F.upscale(image, long_edge=kw.get("long_edge", 1920)))
    from apply_preset import FILTERS as REG, _run_simple

    monkeypatch.setitem(REG, "ai_upscale", _run_simple(F.ai_upscale))
    source = _gradient(640, 480)
    out = apply_preset(source, PRESETS / f"{name}.json")
    assert out.size == (1920, 1440)  # HD step 0 ran first
    assert out.tobytes() != F.upscale(source, long_edge=1920).convert(out.mode).tobytes()


def _spot(size: tuple[int, int] = (200, 200), radius: int = 12) -> Image.Image:
    """Black frame with one white disc in the centre."""
    from PIL import ImageDraw

    img = Image.new("RGB", size, (0, 0, 0))
    cx, cy = size[0] // 2, size[1] // 2
    ImageDraw.Draw(img).ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=(255, 255, 255))
    return img


def test_bloom_spreads_highlights_and_ignores_shadows() -> None:
    src = _spot()
    out = F.bloom(src, threshold=0.5, radius_ratio=0.05, amount=1.0)
    assert out.size == src.size and out.mode == "RGB"
    assert out.getpixel((100, 120))[0] > src.getpixel((100, 120))[0]  # glow just outside the disc
    assert out.getpixel((2, 2)) == (0, 0, 0)  # far corner stays black
    dark = Image.new("RGB", (64, 64), (60, 60, 60))
    assert F.bloom(dark, threshold=0.5).tobytes() == dark.tobytes()
    rgba = src.convert("RGBA")
    assert F.bloom(rgba).mode == "RGBA"


def test_halation_adds_warm_halo_around_highlights() -> None:
    src = _spot()
    out = F.halation(src, threshold=0.5, radius_ratio=0.05, amount=1.0)
    r, g, b = out.getpixel((100, 122))
    assert r > 20 and r > g and r > b  # red-orange ring just past the edge
    assert out.getpixel((2, 2)) == (0, 0, 0)


def test_light_leak_glows_from_anchor_corner() -> None:
    grey = Image.new("RGB", (300, 200), (40, 40, 40))
    out = F.light_leak(grey, anchor="top_right", size=0.6, amount=1.0)
    near, far = out.getpixel((295, 5)), out.getpixel((5, 195))
    assert near[0] > far[0] + 60
    assert near[0] > near[2]  # warm, not cool
    assert far == (40, 40, 40)


def test_film_dust_is_seeded_and_scales() -> None:
    grey = Image.new("RGB", (400, 300), (100, 100, 100))
    a = F.film_dust(grey, amount=0.8, seed=3)
    b = F.film_dust(grey, amount=0.8, seed=3)
    c = F.film_dust(grey, amount=0.8, seed=4)
    assert a.tobytes() == b.tobytes() and a.tobytes() != c.tobytes()
    assert a.tobytes() != grey.tobytes()
    clean = F.film_dust(grey, amount=0, hairs=0, scratches=0)
    assert clean.tobytes() == grey.tobytes()
    # Same seed at 2× resolution touches about the same share of pixels (above the
    # ~1 px minimum speck size, which dominates on thumbnails).
    import numpy as np

    def share(size: tuple[int, int]) -> float:
        out = np.asarray(F.film_dust(Image.new("RGB", size, (100, 100, 100)), amount=0.8, seed=3))
        return float((out != 100).any(axis=2).mean())

    assert 0.7 < share((2400, 1800)) / share((1200, 900)) < 1.4


def test_chromatic_aberration_fringes_edges_not_centre() -> None:
    src = Image.new("RGB", (200, 200), (0, 0, 0))
    src.paste((255, 255, 255), (170, 90, 190, 110))  # white block near the right edge
    out = F.chromatic_aberration(src, amount=0.02)
    assert out.size == src.size
    r, g, b = out.getpixel((191, 100))
    assert r > b  # red is pushed outward past the block's outer edge
    assert out.getpixel((100, 100)) == (0, 0, 0)
    assert F.chromatic_aberration(src, amount=0).tobytes() == src.tobytes()


def test_blur_radius_scales_and_keeps_mode() -> None:
    src = _spot((200, 200), radius=20)
    soft = F.blur(src, radius_ratio=0.02)
    softer = F.blur(src, radius_ratio=0.1)  # takes the shrink path
    assert soft.size == softer.size == src.size
    assert softer.getpixel((100, 135))[0] > soft.getpixel((100, 135))[0]
    assert F.blur(src, radius_ratio=0).tobytes() == src.tobytes()
    assert F.blur(src.convert("RGBA"), radius_ratio=0.05).mode == "RGBA"


def test_draw_text_bottom_corners() -> None:
    blank = Image.new("RGB", (300, 200), (0, 0, 0))
    for align, in_right in (("bottom_right", True), ("bottom_left", False)):
        out = F.draw_text(blank, text="1999", color=[255, 255, 255], align=align, font_size_ratio=0.1, margin_ratio=0.03)
        bbox = out.convert("L").getbbox()
        assert bbox is not None
        assert bbox[1] > 100  # lower half
        assert (bbox[0] > 150) if in_right else (bbox[2] < 150)


def test_stamp_font_style_has_mono_fallbacks() -> None:
    candidates = F._font_candidates("stamp")
    assert candidates != F._font_candidates("sans")
    assert any("Mono" in c for c in candidates) and candidates[-1] == "DejaVuSans.ttf"


PREQUEL_PRESETS = {
    "dreamy_glow": True,
    "film_halation": True,
    "film_dust": False,
    "miami_neon": True,
    "prism_glow": True,
    "disposable_flash": False,
    "portrait_bokeh": True,
    "tungsten_night_film": True,
    "muted_chrome_film": True,
    "studio_spotlight": True,
}


@pytest.mark.parametrize("name,hd", PREQUEL_PRESETS.items())
def test_prequel_preset_files(name: str, hd: bool) -> None:
    data = load_preset(PRESETS / f"{name}.json")
    assert data["name"] == name
    assert data["ar"] == "non-square" and data["text_input"] == "no"
    assert data["default_text"] == "" and data["text_character_limit"] == 0
    steps = data["steps"]
    has_hd = steps[0] == {"filter": "ai_upscale", "on": "image", "long_edge": 1920, "denoise": 0.3}
    assert has_hd is hd
    assert all(s["filter"] in FILTERS for s in steps)
    assert sum(s["filter"] == "ai_upscale" for s in steps) == (1 if hd else 0)


_NEEDS_REMBG = {"portrait_bokeh", "studio_spotlight"}


@pytest.mark.parametrize("name", [n for n in PREQUEL_PRESETS if n not in _NEEDS_REMBG])
def test_prequel_presets_apply_without_upscale(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(F, "ai_upscale", lambda image, **kw: F.upscale(image, long_edge=kw.get("long_edge", 1920)))
    from apply_preset import FILTERS as REG, _run_simple

    monkeypatch.setitem(REG, "ai_upscale", _run_simple(F.ai_upscale))
    source = _gradient(640, 480)
    out = apply_preset(source, PRESETS / f"{name}.json")
    assert out.size == ((1920, 1440) if PREQUEL_PRESETS[name] else (640, 480))
    baseline = F.upscale(source, long_edge=1920) if PREQUEL_PRESETS[name] else source
    assert out.tobytes() != baseline.convert(out.mode).tobytes()


def test_blur_exclude_keeps_hole_colour_out_of_the_background() -> None:
    from PIL import ImageDraw

    # Grey background whose centre (the "hole" behind a cut-out) is filled black.
    bg = Image.new("RGB", (300, 300), (180, 180, 180))
    ImageDraw.Draw(bg).rectangle((100, 100, 200, 200), fill=(0, 0, 0))
    subject = Image.new("RGBA", (300, 300), (0, 0, 0, 0))
    ImageDraw.Draw(subject).rectangle((100, 100, 200, 200), fill=(255, 255, 255, 255))
    plain = F.blur(bg, radius_ratio=0.05)
    steered = F.blur(bg, radius_ratio=0.05, exclude=subject)
    # Just outside the hole, the plain blur darkens (a rim); the excluded one stays grey.
    assert plain.getpixel((215, 150))[0] < 150
    assert steered.getpixel((215, 150))[0] > 170
    # Just inside the hole edge (seen through a cut-out's soft edge) fills from the surroundings.
    assert steered.getpixel((196, 150))[0] > 150
    assert steered.size == bg.size and steered.mode == "RGB"


def test_blur_rgba_does_not_darken_toward_transparency() -> None:
    # Opaque white square on fully transparent *black* pixels.
    img = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    img.paste((255, 255, 255, 255), (50, 50, 150, 150))
    out = F.blur(img, radius_ratio=0.05)
    assert out.mode == "RGBA"
    r, g, b, a = out.getpixel((152, 100))  # soft edge just outside the square
    assert 0 < a < 255
    assert min(r, g, b) > 240  # colour stays white, not dragged toward black


def test_run_blur_rejects_unknown_exclude_layer() -> None:
    with pytest.raises(KeyError, match="exclude"):
        apply_steps(Image.new("RGB", (32, 32)), [{"filter": "blur", "on": "image", "exclude": "nope"}])


def test_portrait_bokeh_blur_excludes_subject() -> None:
    steps = load_preset(PRESETS / "portrait_bokeh.json")["steps"]
    blur_step = next(s for s in steps if s["filter"] == "blur")
    assert blur_step["on"] == "background" and blur_step["exclude"] == "subject"


def _with_exif(tags: dict[tuple[int | None, int], str]) -> Image.Image:
    img = Image.new("RGB", (40, 30), (90, 90, 90))
    exif = Image.Exif()
    for (ifd, tag), value in tags.items():
        if ifd is None:
            exif[tag] = value
        else:
            exif.get_ifd(ifd)[tag] = value
    from io import BytesIO

    buffer = BytesIO()
    img.save(buffer, format="JPEG", exif=exif.tobytes())
    return Image.open(BytesIO(buffer.getvalue()))


def test_photo_datetime_prefers_capture_time() -> None:
    from datetime import datetime

    both = _with_exif({(0x8769, 0x9003): "2019:07:04 18:30:00", (None, 0x0132): "2024:01:01 00:00:00"})
    assert photo_datetime(both) == datetime(2019, 7, 4, 18, 30)
    only_modified = _with_exif({(None, 0x0132): "2024:01:02 03:04:05"})
    assert photo_datetime(only_modified) == datetime(2024, 1, 2, 3, 4, 5)
    assert photo_datetime(_with_exif({(None, 0x0132): "not a date"})) is None
    assert photo_datetime(Image.new("RGB", (4, 4))) is None


def test_date_stamp_uses_photo_capture_date(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []
    real = F.draw_text

    def spy(image: Image.Image, **kw: object) -> Image.Image:
        seen.append(str(kw.get("text")))
        return real(image, **kw)

    from apply_preset import FILTERS as REG, _run_simple

    monkeypatch.setitem(REG, "draw_text", _run_simple(spy))
    photo = _with_exif({(0x8769, 0x9003): "2019:07:04 18:30:00"})
    apply_preset(photo, PRESETS / "disposable_flash.json")
    assert seen == ["2019-07-04"]


def test_draw_text_fallback_places_bottom_anchors_inside(monkeypatch: pytest.MonkeyPatch) -> None:
    from PIL import ImageDraw

    real_text = ImageDraw.ImageDraw.text

    def no_anchor(self, xy, text, *args, **kwargs):  # type: ignore[no-untyped-def]
        if kwargs.get("anchor"):
            raise ValueError("anchors unsupported")
        return real_text(self, xy, text, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, "text", no_anchor)
    blank = Image.new("RGB", (300, 200), (0, 0, 0))
    for align in ("bottom_right", "bottom_left", "bottom"):
        out = F.draw_text(blank, text="1999", color=[255, 255, 255], align=align, font_size_ratio=0.1, margin_ratio=0.03)
        bbox = out.convert("L").getbbox()
        assert bbox is not None and bbox[1] > 100 and bbox[3] <= 200, align


def test_extract_subject_takes_colour_from_source(monkeypatch: pytest.MonkeyPatch) -> None:
    import extract_subject as ES

    source = Image.new("RGB", (20, 20), (200, 150, 100))

    def fake_remove(rgb: Image.Image, session: object = None) -> Image.Image:
        # rembg-style output: soft edge colour pre-multiplied (darkened) by alpha.
        out = Image.new("RGBA", rgb.size, (0, 0, 0, 0))
        out.paste((200, 150, 100, 255), (5, 5, 15, 15))
        out.putpixel((4, 10), (50, 37, 25, 64))
        return out

    monkeypatch.setattr(ES, "_rembg", lambda: (lambda name: None, fake_remove))
    monkeypatch.setattr(ES, "_SESSION", object())
    subject = ES.extract_subject(source)
    assert subject.getpixel((4, 10)) == (200, 150, 100, 64)  # colour restored, alpha kept
    assert subject.getpixel((10, 10)) == (200, 150, 100, 255)
    assert subject.getpixel((0, 0))[3] == 0


def test_studio_spotlight_darkens_background_around_subject() -> None:
    steps = load_preset(PRESETS / "studio_spotlight.json")["steps"]
    bg = [s for s in steps if s.get("on") == "background"]
    grade = next(s for s in bg if s["filter"] == "color_grade")
    assert grade["exposure"] < 0 and grade["saturation"] < 1
    assert any(s["filter"] == "blur" and s.get("exclude") == "subject" for s in bg)
    assert steps.index(next(s for s in steps if s["filter"] == "composite")) > steps.index(grade)


def _saturation(rgb: tuple[int, int, int]) -> float:
    hi, lo = max(rgb), min(rgb)
    return 0.0 if hi == 0 else (hi - lo) / hi


def test_selective_color_boosts_target_and_mutes_others() -> None:
    img = Image.new("RGB", (3, 1))
    img.putpixel((0, 0), (200, 180, 90))  # muted yellow
    img.putpixel((1, 0), (60, 90, 200))  # blue
    img.putpixel((2, 0), (128, 128, 128))  # grey
    out = F.selective_color(img, hue="yellow", saturation=1.8, others=0.3)
    assert _saturation(out.getpixel((0, 0))) > _saturation(img.getpixel((0, 0))) + 0.15
    assert _saturation(out.getpixel((1, 0))) < _saturation(img.getpixel((1, 0))) * 0.5
    assert out.getpixel((2, 0)) == (128, 128, 128)


def test_selective_color_hue_forms_and_alpha() -> None:
    img = Image.new("RGBA", (2, 1), (60, 90, 200, 255))
    img.putpixel((1, 0), (60, 90, 200, 0))
    by_name = F.selective_color(img, hue="blue")
    assert by_name.mode == "RGBA" and by_name.getpixel((1, 0))[3] == 0
    assert by_name.tobytes() == F.selective_color(img, hue=220).tobytes()
    assert F.selective_color(img, hue=[0, 0, 255]).size == img.size
    with pytest.raises(ValueError, match="Unknown hue"):
        F.selective_color(img, hue="chartreuse-ish")


def _ink_bbox(image: Image.Image, background: int = 0) -> tuple[int, int, int, int]:
    bbox = image.convert("L").point(lambda v: 255 if abs(v - background) > 40 else 0).getbbox()
    assert bbox is not None
    return bbox


def test_draw_text_scale_y_stretches_vertically() -> None:
    canvas = Image.new("RGB", (400, 400), (0, 0, 0))
    plain = _ink_bbox(F.draw_text(canvas, text="Hi", font_size=60, align="top"))
    tall = _ink_bbox(F.draw_text(canvas, text="Hi", font_size=60, align="top", scale_y=2.0))
    assert abs((tall[3] - tall[1]) / (plain[3] - plain[1]) - 2) < 0.2
    assert abs((tall[2] - tall[0]) - (plain[2] - plain[0])) <= 2


def test_draw_text_box_styles_frame_the_text() -> None:
    canvas = Image.new("RGB", (400, 300), (0, 0, 0))
    plain = _ink_bbox(F.draw_text(canvas, text="Hi", font_size=60))
    for style in ("frame", "double", "corners"):
        boxed = _ink_bbox(F.draw_text(canvas, text="Hi", font_size=60, box=style, box_ratio=0.01, box_pad_ratio=0.05))
        assert boxed[0] < plain[0] - 10 and boxed[2] > plain[2] + 10, style
        assert boxed[1] < plain[1] - 10 and boxed[3] > plain[3] + 10, style
    label = F.draw_text(canvas, text="Hi", font_size=60, color=[255, 255, 255], box="label", box_fill=[200, 0, 0])
    assert (200, 0, 0, 255) in [px for _, px in label.getcolors(1 << 16)]
    with pytest.raises(ValueError, match="Unknown box"):
        F.draw_text(canvas, text="Hi", box="circle")


def test_draw_text_glow_lights_pixels_around_text() -> None:
    canvas = Image.new("RGB", (400, 200), (0, 0, 0))
    plain = F.draw_text(canvas, text="Hi", font_size=60, color=[255, 255, 255])
    glow = F.draw_text(canvas, text="Hi", font_size=60, color=[255, 255, 255], glow_color=[255, 0, 200], glow_ratio=0.05)
    x0, y0, x1, y1 = _ink_bbox(plain)
    probe = (x1 + 6, (y0 + y1) // 2)
    assert plain.getpixel(probe)[:3] == (0, 0, 0)
    r, g, b = glow.getpixel(probe)[:3]
    assert r > 20 and b > 20 and g < r


def test_draw_text_angle_tilts_text() -> None:
    canvas = Image.new("RGB", (400, 400), (0, 0, 0))
    flat = _ink_bbox(F.draw_text(canvas, text="Hello", font_size=50))
    tilted = _ink_bbox(F.draw_text(canvas, text="Hello", font_size=50, angle=-15))
    assert tilted[3] - tilted[1] > (flat[3] - flat[1]) + 20


def test_display_font_styles_resolve_to_files() -> None:
    for style, candidates in F._DISPLAY_FONT_CANDIDATES.items():
        bundled = [p for p in candidates if p.startswith(str(F._FONTS_DIR))]
        assert bundled and all(Path(p).is_file() for p in bundled), style
        font = F._load_font(40, style)
        assert Path(font.path).is_file(), style


POSTER_TITLE_PRESETS = (
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
)


@pytest.mark.parametrize("name", POSTER_TITLE_PRESETS)
def test_poster_title_presets_shape(name: str) -> None:
    data = load_preset(PRESETS / f"{name}.json")
    assert data["name"] == name
    assert (data["ar"], data["text_input"], data["default_text"], data["text_character_limit"]) == (
        "non-square",
        "yes",
        "TITLE",
        16,
    )
    steps = data["steps"]
    assert all(step["filter"] in FILTERS for step in steps)
    assert steps[0]["filter"] == "extract_subject"
    title = next(i for i, s in enumerate(steps) if s["filter"] == "draw_text")
    comp = next(i for i, s in enumerate(steps) if s["filter"] == "composite")
    # Title is painted on the background before the subject goes back on top.
    assert steps[title]["on"] == "background" and title < comp
    assert steps[title]["text"] == "$text"
    assert steps[title]["font_style"] in F._DISPLAY_FONT_CANDIDATES
    assert "font_path" not in steps[title]
    assert any(s["filter"] == "selective_color" and s["on"] == "background" for s in steps)


def test_draw_text_xy_keeps_stretch_and_box() -> None:
    canvas = Image.new("RGB", (400, 400), (0, 0, 0))
    plain = _ink_bbox(F.draw_text(canvas, text="Hi", font_size=60, x=40, y=50))
    tall = _ink_bbox(F.draw_text(canvas, text="Hi", font_size=60, x=40, y=50, scale_y=2.0))
    boxed = _ink_bbox(F.draw_text(canvas, text="Hi", font_size=60, x=40, y=50, box="frame", box_ratio=0.01))
    assert (tall[3] - tall[1]) > 1.6 * (plain[3] - plain[1])
    assert abs(boxed[0] - 40) <= 3 and abs(boxed[1] - 50) <= 3
    assert boxed[2] - boxed[0] > plain[2] - plain[0] + 10


def test_draw_text_glow_radius_is_capped() -> None:
    canvas = Image.new("RGB", (400, 200), (0, 0, 0))
    capped = F.draw_text(canvas, text="Hi", font_size=60, color=[255, 255, 255], glow_ratio=F._MAX_TEXT_GLOW_RATIO)
    huge = F.draw_text(canvas, text="Hi", font_size=60, color=[255, 255, 255], glow_ratio=5.0)
    assert huge.tobytes() == capped.tobytes()
    with pytest.raises(TypeError):
        F.draw_text(canvas, text="Hi", glow_ratio=0.02, glow_strength=3.0)
