#!/usr/bin/env python3
"""
Local AI super-resolution (Real-ESRGAN `realesr-general-x4v3`, BSD-3-Clause).

Weights come from the official Real-ESRGAN GitHub release (xinntao/Real-ESRGAN
v0.2.5.0). They are converted to ONNX locally (no PyTorch needed) and cached
under ~/.local-studio/models/ — never under the git repo.

Like the upstream CLI, `denoise` blends the regular and "wdn" (weak-denoise)
checkpoints: 0.0 keeps the most grain/detail, 1.0 denoises the most.

  python upscale_model.py            # download + convert (warm cache)
"""

from __future__ import annotations

import hashlib
import os
import pickle
import shutil
import ssl
import urllib.request
import zipfile
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

MODEL_DIR = Path(
    os.environ.get("LOCAL_STUDIO_MODELS", Path.home() / ".local-studio" / "models")
).expanduser()

_RELEASE = "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0"
# name → (url, sha256). Pinned so a tampered download is rejected.
WEIGHTS: dict[str, tuple[str, str]] = {
    "realesr-general-x4v3.pth": (f"{_RELEASE}/realesr-general-x4v3.pth", "8dc7edb9ac80ccdc30c3a5dca6616509367f05fbc184ad95b731f05bece96292"),
    "realesr-general-wdn-x4v3.pth": (f"{_RELEASE}/realesr-general-wdn-x4v3.pth", "1641f8c4464b9f097c9fdda5589273713f67cf59f3d909e0bd688f0cee269dca"),
}
SCALE = 4
DEFAULT_DENOISE = 0.5
# Seconds a stalled connect/read may block before the download fails.
DOWNLOAD_TIMEOUT = 60


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ssl_context() -> ssl.SSLContext:
    """Verified TLS; prefer certifi's CA bundle (python.org macOS builds ship without one)."""
    try:
        import certifi
    except ImportError:
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())


def _part_path(dest: Path) -> Path:
    """Per-process temp path beside `dest`; renamed into place once complete."""
    return dest.with_name(f"{dest.name}.{os.getpid()}.part")


def download_weights(name: str) -> Path:
    url, expected = WEIGHTS[name]
    dest = MODEL_DIR / name
    if dest.is_file() and _sha256(dest) == expected:
        return dest
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _part_path(dest)
    try:
        with urllib.request.urlopen(
            url, timeout=DOWNLOAD_TIMEOUT, context=_ssl_context()
        ) as response, tmp.open("wb") as fh:
            shutil.copyfileobj(response, fh)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    actual = _sha256(tmp)
    if actual != expected:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"Checksum mismatch for {name}: got {actual}")
    tmp.replace(dest)
    return dest


class _TensorRef:
    def __init__(self, dtype: np.dtype, key: str) -> None:
        self.dtype = dtype
        self.key = key


_STORAGE_DTYPES = {
    "FloatStorage": np.float32,
    "HalfStorage": np.float16,
    "DoubleStorage": np.float64,
}


def load_state_dict(path: Path) -> dict[str, np.ndarray]:
    """Read a PyTorch zip checkpoint into numpy arrays without importing torch."""
    with zipfile.ZipFile(path) as archive:
        pkl_name = next(n for n in archive.namelist() if n.endswith("data.pkl"))
        prefix = pkl_name[: -len("data.pkl")]

        def rebuild(storage: _TensorRef, offset: int, size: tuple, stride: tuple, *_: Any):
            raw = np.frombuffer(archive.read(f"{prefix}data/{storage.key}"), dtype=storage.dtype)
            itemsize = raw.dtype.itemsize
            arr = np.lib.stride_tricks.as_strided(
                raw[offset:],
                shape=tuple(size),
                strides=tuple(s * itemsize for s in stride),
            )
            return np.array(arr, dtype=np.float32)

        class Unpickler(pickle.Unpickler):
            def find_class(self, module: str, name: str) -> Any:
                if module == "torch._utils" and name == "_rebuild_tensor_v2":
                    return rebuild
                if module == "torch" and name in _STORAGE_DTYPES:
                    return _STORAGE_DTYPES[name]
                if module == "collections" and name == "OrderedDict":
                    import collections

                    return collections.OrderedDict
                raise pickle.UnpicklingError(f"Refusing to load {module}.{name}")

            def persistent_load(self, pid: Any) -> _TensorRef:
                _, dtype, key, *_ = pid
                return _TensorRef(np.dtype(dtype), str(key))

        with archive.open(pkl_name) as fh:
            state = Unpickler(fh).load()
    return dict(state.get("params", state))


def build_onnx(params: dict[str, np.ndarray], dest: Path) -> Path:
    """Write SRVGGNetCompact (conv/PReLU body → PixelShuffle + nearest residual) as ONNX."""
    import onnx
    from onnx import TensorProto, helper, numpy_helper

    indices = sorted({int(k.split(".")[1]) for k in params if k.startswith("body.")})
    nodes, inits = [], []
    current = "input"
    for idx in indices:
        weight = params[f"body.{idx}.weight"]
        out = f"body_{idx}"
        if weight.ndim == 4:
            inits += [
                numpy_helper.from_array(weight, f"w{idx}"),
                numpy_helper.from_array(params[f"body.{idx}.bias"], f"b{idx}"),
            ]
            nodes.append(
                helper.make_node(
                    "Conv", [current, f"w{idx}", f"b{idx}"], [out], kernel_shape=[3, 3], pads=[1, 1, 1, 1]
                )
            )
        else:
            inits.append(numpy_helper.from_array(weight.reshape(-1, 1, 1), f"a{idx}"))
            nodes.append(helper.make_node("PRelu", [current, f"a{idx}"], [out]))
        current = out

    inits.append(numpy_helper.from_array(np.array([1, 1, SCALE, SCALE], dtype=np.float32), "scales"))
    nodes += [
        helper.make_node("DepthToSpace", [current], ["shuffled"], blocksize=SCALE, mode="CRD"),
        helper.make_node("Resize", ["input", "", "scales"], ["base"], mode="nearest"),
        helper.make_node("Add", ["shuffled", "base"], ["output"]),
    ]
    graph = helper.make_graph(
        nodes,
        "realesr_general_x4v3",
        [helper.make_tensor_value_info("input", TensorProto.FLOAT, [1, 3, "h", "w"])],
        [helper.make_tensor_value_info("output", TensorProto.FLOAT, [1, 3, "H", "W"])],
        inits,
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 17)], ir_version=8)
    onnx.checker.check_model(model)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = _part_path(dest)
    try:
        onnx.save(model, tmp)
        tmp.replace(dest)
    finally:
        tmp.unlink(missing_ok=True)
    return dest


def _denoise_tag(denoise: float) -> str:
    return f"{float(denoise):.2f}".replace(".", "")


def ensure_model(denoise: float = DEFAULT_DENOISE) -> Path:
    """Return the cached ONNX path for this denoise strength, building it if needed."""
    strength = float(denoise)
    if not 0.0 <= strength <= 1.0:
        raise ValueError("denoise must be between 0.0 and 1.0")
    dest = MODEL_DIR / f"realesr-general-x4v3-dn{_denoise_tag(strength)}.onnx"
    if dest.is_file():
        return dest
    base = load_state_dict(download_weights("realesr-general-x4v3.pth"))
    if strength == 0.0:
        params = base
    else:
        # Upstream DNI: weight `strength` on the wdn checkpoint.
        wdn = load_state_dict(download_weights("realesr-general-wdn-x4v3.pth"))
        params = {k: (strength * wdn[k] + (1.0 - strength) * base[k]).astype(np.float32) for k in base}
    return build_onnx(params, dest)


@lru_cache(maxsize=4)
def _session(model_path: str):
    import onnxruntime as ort

    return ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])


def super_resolve(rgb: np.ndarray, denoise: float = DEFAULT_DENOISE, tile: int = 256, pad: int = 24) -> np.ndarray:
    """
    4× upscale an HxWx3 uint8 array. Runs in overlapping tiles so memory stays bounded.
    """
    session = _session(str(ensure_model(denoise)))
    height, width = rgb.shape[:2]
    src = rgb.astype(np.float32).transpose(2, 0, 1)[None] / 255.0
    out = np.empty((height * SCALE, width * SCALE, 3), dtype=np.uint8)
    step = max(16, int(tile))
    for y0 in range(0, height, step):
        for x0 in range(0, width, step):
            y1, x1 = min(y0 + step, height), min(x0 + step, width)
            py0, px0 = max(0, y0 - pad), max(0, x0 - pad)
            py1, px1 = min(height, y1 + pad), min(width, x1 + pad)
            result = session.run(["output"], {"input": src[:, :, py0:py1, px0:px1]})[0][0]
            crop = result[
                :,
                (y0 - py0) * SCALE : (y0 - py0 + y1 - y0) * SCALE,
                (x0 - px0) * SCALE : (x0 - px0 + x1 - x0) * SCALE,
            ]
            out[y0 * SCALE : y1 * SCALE, x0 * SCALE : x1 * SCALE] = (
                np.clip(crop, 0.0, 1.0).transpose(1, 2, 0) * 255.0 + 0.5
            ).astype(np.uint8)
    return out


def main() -> int:
    print("Ensuring Real-ESRGAN general-x4v3 (BSD-3-Clause) is available…")
    path = ensure_model(DEFAULT_DENOISE)
    print(f"Model ready: {path} (outside the repo).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
