"""Apple Vision layers for the twins and the handwriting pages.

``record`` (macOS) runs ``macos/vision_text`` on each picture with the languages listed in
``LANGUAGES`` and writes ``vision/<picture id>.vision.json``: the macOS version, the request revision,
the languages asked for, the picture's SHA-256, and every observation with its words and characters
and their boxes. The build reads these recordings and never runs Vision.

The layer: each recognised word (each character, for a word holding Chinese, Japanese or Korean
characters) is drawn in render mode 3 at its recorded box, in a glyphless font made here
(``glyphless_font``): one empty glyph per recognised character, so the font's cmap, and the ToUnicode
map the writer derives from it, holds every character. Glyph shapes do not matter for an invisible
layer; the font has no outlines.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import pymupdf
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

HERE = Path(__file__).resolve().parent
REC_DIR = HERE / "vision"
HELPER = HERE / "macos" / "vision_text"
GLYPHLESS_NAME = "GlyphlessLayer"
UPM = 1000
ADVANCE = 500
ASCENT = 800
DESCENT = -200

# Vision's languages per page script; scripts Vision does not read on the recording Mac are absent.
LANGUAGES: dict[str, list[str]] = {
    "zh-Hans": ["zh-Hans", "en-US"],
    "zh-Hant": ["zh-Hant", "en-US"],
    "ja": ["ja-JP", "en-US"],
    "ja-vertical": ["ja-JP", "en-US"],
    "ko": ["ko-KR", "en-US"],
    "ar": ["ar-SA", "en-US"],
    "hi": ["hi-IN", "en-US"],
    "th": ["th-TH", "en-US"],
    "ru": ["ru-RU", "en-US"],
    "vi": ["vi-VT", "en-US"],
    "pl": ["pl-PL", "en-US"],
    "mixed": ["zh-Hans", "en-US"],
    "handwriting": ["en-US"],
}


def recording_path(picture_id: str) -> Path:
    return REC_DIR / f"{picture_id}.vision.json"


def record(pictures: dict[str, tuple[bytes, list[str]]]) -> list[str]:
    """Run Vision on each (picture id -> (JPEG, languages)) and store the recordings."""
    REC_DIR.mkdir(exist_ok=True)
    out = []
    by_lang: dict[tuple[str, ...], list[str]] = {}
    for pid, (_, lang_list) in pictures.items():
        by_lang.setdefault(tuple(lang_list), []).append(pid)
    with tempfile.TemporaryDirectory() as td:
        for langs, pids in by_lang.items():
            paths = []
            for pid in pids:
                p = Path(td) / f"{pid}.jpg"
                p.write_bytes(pictures[pid][0])
                paths.append(str(p))
            cmd = [str(HELPER), "--languages", ",".join(langs), *paths]
            run = subprocess.run(cmd, capture_output=True, text=True, check=True)  # noqa: S603 - the helper in macos/
            data = json.loads(run.stdout)
            head = {k: v for k, v in data.items() if k != "images"}
            for pid, img in zip(pids, data["images"], strict=True):
                rec = {
                    **head,
                    "picture": pid,
                    "image_sha256": hashlib.sha256(pictures[pid][0]).hexdigest(),
                    **{k: img[k] for k in ("width", "height", "observations")},
                }
                recording_path(pid).write_text(
                    json.dumps(rec, indent=1, sort_keys=True, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
                out.append(pid)
    return out


def load(picture_id: str) -> dict[str, Any]:
    return json.loads(recording_path(picture_id).read_text(encoding="utf-8"))


def all_characters() -> list[str]:
    chars: set[str] = set()
    for p in sorted(REC_DIR.glob("*.vision.json")):
        rec = json.loads(p.read_text(encoding="utf-8"))
        for o in rec["observations"]:
            chars |= set(o["string"])
    chars.discard(" ")
    return sorted(chars)


def glyphless_font(chars: list[str]) -> bytes:
    """A TrueType font with one empty glyph per character (and a space), ``ADVANCE`` units wide."""
    names = [".notdef", "space"] + [f"u{ord(c):04X}" for c in chars]
    fb = FontBuilder(UPM, isTTF=True)
    fb.setupGlyphOrder(names)
    cmap = {0x20: "space"} | {ord(c): f"u{ord(c):04X}" for c in chars}
    fb.setupCharacterMap(cmap)
    empty = TTGlyphPen(None).glyph()
    fb.setupGlyf(dict.fromkeys(names, empty))
    fb.setupHorizontalMetrics(dict.fromkeys(names, (ADVANCE, 0)))
    fb.setupHorizontalHeader(ascent=ASCENT, descent=DESCENT)
    fb.setupNameTable(
        {
            "familyName": GLYPHLESS_NAME,
            "styleName": "Regular",
            "psName": f"{GLYPHLESS_NAME}-Regular",
        }
    )
    fb.setupOS2(
        sTypoAscender=ASCENT, sTypoDescender=DESCENT, usWinAscent=ASCENT, usWinDescent=-DESCENT
    )
    fb.setupPost()
    fb.font["head"].created = 3_900_000_000
    fb.font["head"].modified = 3_900_000_000
    fb.font.recalcTimestamp = False
    buf = __import__("io").BytesIO()
    fb.font.save(buf)
    return buf.getvalue()


def _is_cjk(ch: str) -> bool:
    o = ord(ch)
    return (
        0x3040 <= o <= 0x30FF
        or 0x3400 <= o <= 0x9FFF
        or 0xAC00 <= o <= 0xD7AF
        or 0xFF00 <= o <= 0xFFEF
    )


def pieces(
    rec: dict[str, Any], page_w: float, page_h: float
) -> list[tuple[str, tuple[float, float, float, float]]]:
    """(text, box in PDF points, bottom-left origin) for every piece the layer draws."""
    out = []
    for o in rec["observations"]:
        chars = [c for c in o.get("chars", []) if c["box"] is not None]
        for w in o["words"]:
            if w["box"] is None:
                continue
            if any(_is_cjk(c) for c in w["text"]):
                used = [c for c in chars if c["text"] in w["text"]]
                for c in used[: len(w["text"])]:
                    b = c["box"]
                    out.append(
                        (c["text"], (b[0] * page_w, b[1] * page_h, b[2] * page_w, b[3] * page_h))
                    )
                    chars.remove(c)
                continue
            b = w["box"]
            out.append((w["text"], (b[0] * page_w, b[1] * page_h, b[2] * page_w, b[3] * page_h)))
    return out


def layer_pdf(
    jpeg: bytes,
    image_px: tuple[int, int],
    rec: dict[str, Any],
    font: bytes,
    page: tuple[int, int] = (612, 792),
) -> bytes:
    """The picture with Vision's pieces drawn over it in render mode 3."""
    doc = pymupdf.open()
    pg = doc.new_page(width=page[0], height=page[1])
    pg.insert_image(pymupdf.Rect(0, 0, page[0], page[1]), stream=jpeg)
    with tempfile.NamedTemporaryFile(suffix=".ttf") as tf:
        tf.write(font)
        tf.flush()
        for text, (x0, y0, x1, y1) in pieces(rec, page[0], page[1]):
            size = max(1.0, y1 - y0)
            natural = len(text) * ADVANCE / UPM * size
            sx = (x1 - x0) / natural if natural else 1.0
            base = pymupdf.Point(x0, page[1] - y0 - (-DESCENT / UPM) * size)
            pg.insert_text(
                base,
                text,
                fontsize=size,
                fontname=GLYPHLESS_NAME,
                fontfile=tf.name,
                render_mode=3,
                morph=(base, pymupdf.Matrix(sx, 1)),
            )
    doc.set_metadata(
        {
            "title": "Synthetic script fixture",
            "creator": "PyMuPDF",
            "producer": "PyMuPDF",
            "creationDate": "",
            "modDate": "",
        }
    )
    doc.subset_fonts()
    out = doc.tobytes(garbage=3, deflate=True, no_new_id=True)
    doc.close()
    del image_px
    return bytes(out)


if __name__ == "__main__":
    sys.stderr.write("use build.py --record-vision\n")
    raise SystemExit(2)
