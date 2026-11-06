"""Build the script and handwriting family: every document, its expected file, ``manifest.json`` and
``SHA256SUMS``.

    .venv/bin/python -I scripts_handwriting/build.py --out <empty dir> [--only id,id] [--publish]
    .venv/bin/python -I scripts_handwriting/build.py --record-vision      # macOS: Vision recordings

The documents:
- ``sh-born-<script>-<layout>``: a born-digital page (``born.py``), prose or a form;
- ``sh-scan-<script>-<layout>-<condition>-<layer>``: its scanned twin (``twins.py``), ``clean`` (300 dpi)
  or ``light`` (200 dpi), with no layer, the born page's own layer (``placed``), or Vision's;
- ``sh-hand-<page>-<condition>-<layer>``: a synthetic handwriting page (``handwriting.py``).

The Core Text pages need macOS: they are kept as written in ``coretext/`` (committed) and copied by
the build; ``--record-coretext`` writes them again. Every other document is rebuilt here.
``--publish`` copies the expected files, the checksums, the manifest, every born-digital page and
every ``clean`` (300 dpi) picture into ``scripts_handwriting/``; the ``light`` (200 dpi) pictures
stay in ``--out``.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import platform
import shutil
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import PIL
import pymupdf
import reportlab
from PIL import Image

from hidden_layer.build import json_bytes
from hidden_layer.rng import mix_seed
from scripts_handwriting import born, fonts, handwriting, ink, layerread, texts, twins, vision

HERE = Path(__file__).resolve().parent
CORETEXT_DIR = HERE / "coretext"
SCHEMA = 1

PROSE = (
    "zh-Hans",
    "zh-Hant",
    "ja",
    "ja-vertical",
    "ko",
    "ar",
    "he",
    "hi",
    "th",
    "el",
    "ru",
    "vi",
    "pl",
    "is",
    "mixed",
)
FORMS = ("zh-Hans", "zh-Hant", "ja", "ko", "ar", "he", "hi", "th", "el", "ru", "vi", "pl", "is")
CORETEXT_PROSE = {"zh-Hans", "zh-Hant", "ja", "ja-vertical", "ko", "ar", "he", "hi", "th", "mixed"}
PYMUPDF_FORMS = {"zh-Hans", "zh-Hant", "ja", "ko", "hi", "th"}
HAND_PAGES = ("note", "form", "letter")
RTL_VISUAL_WRITERS = {"coretext", "reportlab"}


@dataclass(frozen=True)
class Spec:
    doc_id: str
    kind: str  # born | scan | hand
    code: str  # script code, or the handwriting page name
    layout: str  # prose | form | hand
    writer: str
    condition: str = ""
    layer: str = ""
    seed: int = 0


def writer_of(code: str, layout: str) -> str:
    if layout == "prose":
        return "coretext" if code in CORETEXT_PROSE else "reportlab"
    return "pymupdf" if code in PYMUPDF_FORMS else "reportlab"


def specs() -> list[Spec]:
    out: list[Spec] = []
    pages = [(c, "prose") for c in PROSE] + [(c, "form") for c in FORMS]
    for code, layout in pages:
        out.append(Spec(f"sh-born-{code}-{layout}", "born", code, layout, writer_of(code, layout)))
    for code, layout in pages:
        for cond in twins.CONDITIONS:
            layers = ["none", "placed"] + (["vision"] if code in vision.LANGUAGES else [])
            for layer in layers:
                out.append(
                    Spec(
                        f"sh-scan-{code}-{layout}-{cond}-{layer}",
                        "scan",
                        code,
                        layout,
                        writer_of(code, layout),
                        cond,
                        layer,
                        mix_seed(code, layout, cond),
                    )
                )
    for page in HAND_PAGES:
        for cond in twins.CONDITIONS:
            for layer in ("none", "vision"):
                out.append(
                    Spec(
                        f"sh-hand-{page}-{cond}-{layer}",
                        "hand",
                        page,
                        "hand",
                        "PIL",
                        cond,
                        layer,
                        mix_seed("hand", page, cond),
                    )
                )
    return out


def picture_id(spec: Spec) -> str:
    if spec.kind == "hand":
        return f"sh-pic-hand-{spec.code}-{spec.condition}"
    return f"sh-pic-{spec.code}-{spec.layout}-{spec.condition}"


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


# --------------------------------------------------------------------------------------- born pages
def placed_lines(
    code: str, layout: str
) -> tuple[list[born.PlacedLine], list[tuple[float, float, float, float]]]:
    return (born.prose_lines(code), []) if layout == "prose" else born.form_lines(code)


def coretext_path(code: str, layout: str) -> Path:
    return CORETEXT_DIR / f"sh-born-{code}-{layout}.pdf"


_born_cache: dict[tuple[str, str], bytes] = {}


def born_pdf(code: str, layout: str) -> bytes:
    key = (code, layout)
    if key not in _born_cache:
        w = writer_of(code, layout)
        if w == "coretext":
            _born_cache[key] = coretext_path(code, layout).read_bytes()
        else:
            lines, rules = placed_lines(code, layout)
            _born_cache[key] = born.WRITERS[w](lines, rules, code)
    return _born_cache[key]


def _gloss(code: str, ln: born.PlacedLine) -> tuple[str, str]:
    if ln.key == "heading":
        return "", "heading"
    s = texts.scripts()["ja" if code == "ja-vertical" else code]
    if ln.key.startswith("line"):
        t = s.lines[int(ln.key[4:])]
        return t.gloss, t.meaning
    i = int(ln.key[5:])
    _label, _value, label_gloss, field = texts.form_rows(s)[i]
    if ln.key.startswith("label"):
        return label_gloss, f"label: {field}"
    return "", f"value: {field}"


def layer_facts(
    ln: born.PlacedLine, writer: str, all_shows: list[layerread.Show]
) -> dict[str, Any]:
    got = layerread.line_text(all_shows, ln.y, ln.span, ln.x if ln.vertical else None)
    nf_text = unicodedata.normalize("NFKC", ln.text)
    candidates = [got]
    if ln.direction == "rtl" and writer in RTL_VISUAL_WRITERS:
        candidates.append(got[::-1])
    return {
        "layer_text": got,
        "layer_unmapped": got.count("�"),
        "decodes_exactly": got == ln.text,
        "decodes_normalised": any(unicodedata.normalize("NFKC", c) == nf_text for c in candidates),
    }


def line_records(
    code: str, layout: str, writer: str, pdf: bytes | None, img: np.ndarray, dpi: int
) -> list[dict[str, Any]]:
    lines, rules = placed_lines(code, layout)
    all_shows = layerread.shows(pdf) if pdf is not None else []
    out = []
    for ln in lines:
        gloss, meaning = _gloss(code, ln)
        size = 10 if ln.key == "heading" else born.SIZE
        rec: dict[str, Any] = {
            "key": ln.key,
            "script": ln.script,
            "direction": ln.direction,
            "vertical": ln.vertical,
            "align": ln.align,
            "anchor_pt": [ln.x, ln.y],
            "span_pt": list(ln.span),
            "size_pt": size,
            "text": ln.text,
            "gloss": gloss,
            "meaning": meaning,
            "ink_boxes_px": ink.word_boxes(
                img, dpi, size, ln.y, ln.span, ln.x if ln.vertical else None, exclude=rules
            ),
        }
        if pdf is not None:
            rec.update(layer_facts(ln, writer, all_shows))
        out.append(rec)
    return out


def font_files() -> dict[str, str]:
    return {fonts.path_of(k).name: sha256(fonts.path_of(k).read_bytes()) for k in fonts.SOURCES}


def build_born(spec: Spec) -> tuple[bytes, dict[str, Any]]:
    pdf = born_pdf(spec.code, spec.layout)
    img = twins.render_gray(pdf, 300)
    return pdf, {
        "schema": SCHEMA,
        "id": spec.doc_id,
        "family": "scripts-handwriting",
        "kind": "born",
        "script": spec.code,
        "layout": spec.layout,
        "writer": spec.writer,
        "fonts_embedded": layerread.embedded_fonts(pdf),
        "render_modes": sorted({s.render_mode for s in layerread.shows(pdf)}),
        "ink_dpi": 300,
        "lines": line_records(spec.code, spec.layout, spec.writer, pdf, img, 300),
    }


# --------------------------------------------------------------------------------------- pictures
_pictures: dict[str, tuple[bytes, tuple[int, int]]] = {}
_hand_pages: dict[str, handwriting.HandPage] = {}


def picture_of(spec: Spec) -> tuple[bytes, tuple[int, int]]:
    pid = picture_id(spec)
    if pid not in _pictures:
        if spec.kind == "hand":
            dpi, quality = twins.CONDITIONS[spec.condition]
            page = handwriting.build_page(spec.code, dpi, spec.seed)
            _hand_pages[pid] = page
            arr = handwriting.pixels(page)
            if spec.condition == "light":
                arr = twins.lighten(arr, spec.seed)
            buf = io.BytesIO()
            Image.fromarray(arr).save(buf, "JPEG", quality=quality, dpi=(dpi, dpi), optimize=False)
            _pictures[pid] = (buf.getvalue(), (arr.shape[1], arr.shape[0]))
        else:
            _pictures[pid] = twins.picture(
                born_pdf(spec.code, spec.layout), spec.condition, spec.seed
            )
    return _pictures[pid]


def decode_jpeg(jpeg: bytes) -> np.ndarray:
    return np.asarray(Image.open(io.BytesIO(jpeg)).convert("L"))


_glyphless: bytes | None = None


def glyphless() -> bytes:
    global _glyphless  # noqa: PLW0603 - one font per build, made from the committed recordings
    if _glyphless is None:
        _glyphless = vision.glyphless_font(vision.all_characters())
    return _glyphless


def _vision_part(spec: Spec, jpeg: bytes, px: tuple[int, int]) -> tuple[bytes, dict[str, Any]]:
    pid = picture_id(spec)
    rec = vision.load(pid)
    if rec["image_sha256"] != sha256(jpeg):
        raise SystemExit(
            f"{pid}: the recording was made from a different picture; run --record-vision"
        )
    pdf = vision.layer_pdf(jpeg, px, rec, glyphless())
    facts = {
        "recording": f"vision/{vision.recording_path(pid).name}",
        "recording_sha256": sha256(vision.recording_path(pid).read_bytes()),
        "macos": rec["macos"],
        "revision": rec["revision"],
        "languages": rec["languages"],
        "pieces": [[t, [round(v, 3) for v in b]] for t, b in vision.pieces(rec, 612, 792)],
    }
    return pdf, facts


def build_scan(spec: Spec) -> tuple[bytes, dict[str, Any]]:
    jpeg, px = picture_of(spec)
    dpi, quality = twins.CONDITIONS[spec.condition]
    img = decode_jpeg(jpeg)
    vis = None
    if spec.layer == "none":
        pdf = twins.image_only_pdf(jpeg, px)
    elif spec.layer == "placed":
        pdf = twins.placed_layer_pdf(born_pdf(spec.code, spec.layout), jpeg, px)
    else:
        pdf, vis = _vision_part(spec, jpeg, px)
    lines = line_records(
        spec.code, spec.layout, spec.writer, pdf if spec.layer == "placed" else None, img, dpi
    )
    shows = layerread.shows(pdf)
    return pdf, {
        "schema": SCHEMA,
        "id": spec.doc_id,
        "family": "scripts-handwriting",
        "kind": "scan",
        "script": spec.code,
        "layout": spec.layout,
        "source": f"sh-born-{spec.code}-{spec.layout}",
        "condition": spec.condition,
        "dpi": dpi,
        "jpeg_quality": quality,
        "image": {"sha256": sha256(jpeg), "px": list(px)},
        "layer": spec.layer,
        "fonts_embedded": layerread.embedded_fonts(pdf),
        "render_modes": sorted({s.render_mode for s in shows}),
        "ink_dpi": dpi,
        "lines": lines,
        "vision": vis,
    }


def build_hand(spec: Spec) -> tuple[bytes, dict[str, Any]]:
    jpeg, px = picture_of(spec)
    dpi, quality = twins.CONDITIONS[spec.condition]
    page = _hand_pages[picture_id(spec)]
    vis = None
    if spec.layer == "none":
        pdf = twins.image_only_pdf(jpeg, px)
    else:
        pdf, vis = _vision_part(spec, jpeg, px)
    shows = layerread.shows(pdf)
    return pdf, {
        "schema": SCHEMA,
        "id": spec.doc_id,
        "family": "scripts-handwriting",
        "kind": "hand",
        "page": spec.code,
        "condition": spec.condition,
        "dpi": dpi,
        "jpeg_quality": quality,
        "image": {"sha256": sha256(jpeg), "px": list(px)},
        "layer": spec.layer,
        "fonts_embedded": layerread.embedded_fonts(pdf),
        "render_modes": sorted({s.render_mode for s in shows}),
        "lines": page.lines,
        "words": [
            {"line": w.line, "text": w.text, "kind": w.kind, "box_px": w.box} for w in page.words
        ],
        "vision": vis,
    }


def build_doc(spec: Spec) -> tuple[bytes, dict[str, Any]]:
    return {"born": build_born, "scan": build_scan, "hand": build_hand}[spec.kind](spec)


def producer(spec: Spec) -> dict[str, Any]:
    p: dict[str, Any] = {
        "writer": {
            "coretext": "macOS Core Text (macos/ct_page.swift)",
            "pymupdf": "PyMuPDF (insert_htmlbox, HarfBuzz)",
            "reportlab": "reportlab",
            "PIL": "Pillow",
        }[spec.writer],
        "python": platform.python_version(),
        "pillow": PIL.__version__,
        "pymupdf": pymupdf.VersionBind,
        "reportlab": reportlab.Version,
        "font_source": f"github.com/google/fonts at {fonts.SOURCE_COMMIT}",
    }
    if spec.writer == "coretext":
        p["recorded"] = f"coretext/sh-born-{spec.code}-{spec.layout}.pdf"
    return p


def build(out: Path, only: set[str] | None) -> list[dict[str, Any]]:
    (out / "documents").mkdir(parents=True, exist_ok=True)
    (out / "expected").mkdir(parents=True, exist_ok=True)
    rows = []
    extra_sums = []
    for spec in specs():
        if only is not None and spec.doc_id not in only:
            continue
        pdf, exp = build_doc(spec)
        exp_b = json_bytes(exp)
        (out / f"documents/{spec.doc_id}.pdf").write_bytes(pdf)
        (out / f"expected/{spec.doc_id}.expected.json").write_bytes(exp_b)
        row: dict[str, Any] = {
            "path": f"documents/{spec.doc_id}.pdf",
            "bytes": len(pdf),
            "sha256": sha256(pdf),
            "expected": f"expected/{spec.doc_id}.expected.json",
            "expected_sha256": sha256(exp_b),
            "family": "scripts-handwriting",
            "kind": spec.kind,
            "script": spec.code,
            "layout": spec.layout,
            "condition": spec.condition,
            "layer": spec.layer,
            "producer": producer(spec),
            "stored": "committed" if spec.kind == "born" or spec.condition == "clean" else "local",
        }
        if exp.get("vision"):
            row["vision_recording"] = exp["vision"]["recording"]
            row["vision_recording_sha256"] = exp["vision"]["recording_sha256"]
            (out / "vision").mkdir(exist_ok=True)
            src = HERE / exp["vision"]["recording"]
            shutil.copyfile(src, out / exp["vision"]["recording"])
            extra_sums.append(f"{row['vision_recording_sha256']}  {row['vision_recording']}")
        rows.append(row)
        sys.stdout.write(f"{spec.doc_id}  {len(pdf) // 1024} KiB  {row['stored']}\n")
    manifest = {
        "schema": SCHEMA,
        "family": "scripts-handwriting",
        "font_files": font_files(),
        "documents": rows,
    }
    (out / "manifest.json").write_bytes(json_bytes(manifest))
    sums = (
        [f"{r['sha256']}  {r['path']}" for r in rows]
        + [f"{r['expected_sha256']}  {r['expected']}" for r in rows]
        + sorted(set(extra_sums))
    )
    (out / "SHA256SUMS").write_text("\n".join(sums) + "\n", encoding="ascii")
    return rows


def publish(out: Path, dest: Path) -> None:
    import json

    manifest = json.loads((out / "manifest.json").read_text(encoding="ascii"))
    for sub in ("documents", "expected"):
        if (dest / sub).exists():
            shutil.rmtree(dest / sub)
        (dest / sub).mkdir(parents=True)
    for row in manifest["documents"]:
        shutil.copyfile(out / row["expected"], dest / row["expected"])
        if row["stored"] == "committed":
            shutil.copyfile(out / row["path"], dest / row["path"])
    for name in ("manifest.json", "SHA256SUMS"):
        shutil.copyfile(out / name, dest / name)


def record_coretext() -> list[str]:
    CORETEXT_DIR.mkdir(exist_ok=True)
    out = []
    for code in sorted(CORETEXT_PROSE):
        lines, rules = placed_lines(code, "prose")
        pdf = born.write_coretext(lines, rules, code)
        coretext_path(code, "prose").write_bytes(pdf)
        out.append(coretext_path(code, "prose").name)
    return out


def record_vision() -> list[str]:
    pictures: dict[str, tuple[bytes, list[str]]] = {}
    for spec in specs():
        if spec.layer != "vision":
            continue
        jpeg, _ = picture_of(spec)
        langs = vision.LANGUAGES["handwriting" if spec.kind == "hand" else spec.code]
        pictures[picture_id(spec)] = (jpeg, langs)
    return vision.record(pictures)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=Path)
    ap.add_argument("--only", default="")
    ap.add_argument("--publish", action="store_true")
    ap.add_argument("--record-coretext", action="store_true")
    ap.add_argument("--record-vision", action="store_true")
    a = ap.parse_args()
    if a.record_coretext:
        for name in record_coretext():
            sys.stdout.write(f"recorded coretext/{name}\n")
        return 0
    if a.record_vision:
        for pid in record_vision():
            sys.stdout.write(f"recorded vision/{pid}.vision.json\n")
        return 0
    if a.out is None:
        ap.error("--out is required")
    if a.out.exists() and any(a.out.iterdir()):
        sys.stderr.write(f"refusing to write into a non-empty directory: {a.out}\n")
        return 2
    only = {x for x in a.only.split(",") if x} or None
    build(a.out, only)
    if a.publish:
        publish(a.out, HERE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
