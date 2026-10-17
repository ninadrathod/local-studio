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
