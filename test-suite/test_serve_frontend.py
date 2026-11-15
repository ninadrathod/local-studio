"""The run.sh frontend server sends Cache-Control: no-cache so updated JS/CSS load on refresh."""

from __future__ import annotations

import importlib.util
import threading
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_module():
    spec = importlib.util.spec_from_file_location("serve_frontend", ROOT / "scripts" / "serve_frontend.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_frontend_server_sends_no_cache(tmp_path: Path) -> None:
    (tmp_path / "script.js").write_text("console.log('hi');\n")
    server = _load_module().make_server(0, directory=str(tmp_path), host="127.0.0.1")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/script.js", timeout=5) as resp:
            assert resp.status == 200
            assert resp.headers["Cache-Control"] == "no-cache"
            assert resp.read() == b"console.log('hi');\n"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_frontend_server_rejects_bad_args() -> None:
    assert _load_module().main(["serve_frontend.py"]) == 2
    assert _load_module().main(["serve_frontend.py", "abc"]) == 2
