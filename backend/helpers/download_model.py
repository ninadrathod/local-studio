#!/usr/bin/env python3
"""
Download (or verify) the rembg u2net model used by extract_subject.py.

Weights are cached under $REMBG_HOME (default ~/.rembg/; the backend image bakes them
into /opt/local-studio/rembg) — never under the git repo.
"""

from __future__ import annotations

from rembg import new_session

from extract_subject import DEFAULT_MODEL


def main() -> int:
    print(f"Ensuring rembg model '{DEFAULT_MODEL}' is available…")
    new_session(DEFAULT_MODEL)
    print(f"Model '{DEFAULT_MODEL}' ready (cached under $REMBG_HOME, outside the repo).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
