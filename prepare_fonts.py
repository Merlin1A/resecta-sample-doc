#!/usr/bin/env python3
"""Regenerable font preparation for the Resecta sample statement (build-time; needs network).

Fetches the official Inter v4.1 release (rsms/inter), extracts the static TTF instances used by the
statement, and freezes the `tnum` (tabular figures) OpenType feature into the default glyph set so
digits are equal-width for decimal alignment — reportlab does not apply OpenType
features at render time. Output: ./fonts/Inter-{Regular,Medium,SemiBold,Bold}.ttf + OFL.txt.

This is the *sources* step (network). `generate_statement.py` is fully offline and deterministic.

Run:  uv run python prepare_fonts.py
"""
from __future__ import annotations
import hashlib
import io
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

INTER_VERSION = "4.1"
INTER_URL = f"https://github.com/rsms/inter/releases/download/v{INTER_VERSION}/Inter-{INTER_VERSION}.zip"
INTER_SHA256 = "9883fdd4a49d4fb66bd8177ba6625ef9a64aa45899767dde3d36aa425756b11e"

# release-internal path -> output filename
WEIGHTS = {
    "extras/ttf/Inter-Regular.ttf": "Inter-Regular.ttf",
    "extras/ttf/Inter-Medium.ttf": "Inter-Medium.ttf",
    "extras/ttf/Inter-SemiBold.ttf": "Inter-SemiBold.ttf",
    "extras/ttf/Inter-Bold.ttf": "Inter-Bold.ttf",
}
FONTS_DIR = Path(__file__).resolve().parent / "fonts"
CACHE = Path("/tmp") / f"Inter-{INTER_VERSION}.zip"


def fetch() -> bytes:
    if CACHE.exists():
        data = CACHE.read_bytes()
        if hashlib.sha256(data).hexdigest() == INTER_SHA256:
            return data
    print(f"downloading {INTER_URL}")
    with urllib.request.urlopen(INTER_URL, timeout=120) as r:  # noqa: S310 (pinned host+sha)
        data = r.read()
    got = hashlib.sha256(data).hexdigest()
    if got != INTER_SHA256:
        sys.exit(f"SHA-256 mismatch: expected {INTER_SHA256}, got {got}")
    CACHE.write_bytes(data)
    return data


def freeze_tnum(path: Path) -> None:
    """Bake the tnum feature into the default glyphs (idempotent on re-run)."""
    exe = shutil.which("pyftfeatfreeze")
    cmd = [exe] if exe else [sys.executable, "-m", "opentype_feature_freezer.cli"]
    out = path.with_suffix(".tf.ttf")
    # SOURCE_DATE_EPOCH fixes head.created/modified (fontTools honors it) => byte-stable output.
    env = dict(os.environ, SOURCE_DATE_EPOCH="1780272000")  # 2026-06-01T00:00:00Z
    subprocess.run([*cmd, "-f", "tnum", str(path), str(out)], check=True, env=env,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    out.replace(path)


def main() -> None:
    FONTS_DIR.mkdir(exist_ok=True)
    z = zipfile.ZipFile(io.BytesIO(fetch()))
    for src, dst in WEIGHTS.items():
        (FONTS_DIR / dst).write_bytes(z.read(src))
        freeze_tnum(FONTS_DIR / dst)
        print(f"  prepared {dst} (tnum frozen)")
    (FONTS_DIR / "OFL.txt").write_text(z.read("LICENSE.txt").decode("utf-8"))
    print(f"  wrote OFL.txt\nDone -> {FONTS_DIR}")


if __name__ == "__main__":
    main()
