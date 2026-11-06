"""Build the hidden-layer family: each document's PDF and expected file, the manifest, SHA256SUMS
and the accept list.

    .venv/bin/python -I hidden_layer/build.py --out <empty dir> [--only id,id] [--publish]

``--publish`` then copies the expected files, the manifest, the checksums, the accept list and every
document under ``COMMIT_LIMIT`` (512 KiB) into ``hidden_layer/`` of this repository. Larger documents
stay in ``--out`` and are rebuilt from this generator.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import sys
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import PIL
import reportlab
from reportlab.pdfbase.pdfmetrics import stringWidth

from hidden_layer import geometry, grid, pages, scenarios
from hidden_layer.layer import ASCENT, DESCENT, HIDDEN_FONT, HiddenPiece, dec, fit_piece, write_pdf
from hidden_layer.rng import mix_seed, scalar_ints
from hidden_layer.values import MISREAD_SPLIT, MISREAD_SUBSTITUTE

HERE = Path(__file__).resolve().parent
SCHEMA = 1
COMMIT_LIMIT = 512 * 1024
SPLIT_GAP = Fraction(3, 2)
PAGE_W = 612
PAGE_H = 792


def num(f: Fraction | int, places: int = 3) -> float:
    return float(dec(Fraction(f), places))


def box_out(r: tuple[Fraction, Fraction, Fraction, Fraction]) -> list[float]:
    return [num(c) for c in r]


def ink_pt(ink_px: tuple[int, int, int, int], dpi: int) -> scenarios.Rect:
    k = Fraction(72, dpi)
    x0, y0, x1, y1 = ink_px
    return (x0 * k, PAGE_H - y1 * k, x1 * k, PAGE_H - y0 * k)


def jitter_pairs(spec: grid.DocSpec, n: int) -> list[tuple[int, int]]:
    if not spec.jitter_cpt:
        return [(0, 0)] * n
    vals = scalar_ints(mix_seed(spec.seed, "jitter"), 2 * n, -spec.jitter_cpt, spec.jitter_cpt)
    return [(vals[2 * i], vals[2 * i + 1]) for i in range(n)]


def placed_pieces(spec: grid.DocSpec, page: pages.Page) -> list[list[HiddenPiece]]:
    """The hidden pieces of every word, in word order (a split word has two)."""
    k = Fraction(72, page.dpi)
    jit = jitter_pairs(spec, len(page.words))
    out: list[list[HiddenPiece]] = []
    for wd, (jx, jy) in zip(page.words, jit, strict=True):
        dx = Fraction(spec.drift_cpt + jx, 100)
        dy = Fraction(spec.vshift_cpt + jy, 100)
        x0 = wd.ink_px[0] * k + dx
        x1 = wd.ink_px[2] * k + dx
        base = PAGE_H - wd.baseline_px * k + dy
        trail = not wd.segment_end
        target = (wd.line_key, wd.position) == scenarios.SURNAME
        if target and spec.misread == "substitute":
            out.append([fit_piece(MISREAD_SUBSTITUTE, x0, x1, base, wd.size_pt, trail)])
        elif target and spec.misread == "split":
            a, b = MISREAD_SPLIT
            f = Fraction(stringWidth(a, HIDDEN_FONT, 1000)) / Fraction(
                stringWidth(a + b, HIDDEN_FONT, 1000)
            )
            cut = x0 + f * (x1 - x0)
            out.append(
                [
                    fit_piece(a, x0, cut - SPLIT_GAP / 2, base, wd.size_pt, True),
                    fit_piece(b, cut + SPLIT_GAP / 2, x1, base, wd.size_pt, trail),
                ]
            )
        else:
            out.append([fit_piece(wd.text, x0, x1, base, wd.size_pt, trail)])
    return out


VISION_DIR = HERE / "vision"


def _overlap(a: scenarios.Rect, b: scenarios.Rect) -> Fraction:
    r = geometry.intersect(a, b)
    return Fraction(0) if r is None else geometry.area(r)


def vision_recording(doc_id: str) -> tuple[Path, dict[str, Any]]:
    path = VISION_DIR / f"{doc_id}.vision.json"
    return path, json.loads(path.read_text(encoding="ascii"), parse_float=Decimal)


def vision_pieces(
    spec: grid.DocSpec, page: pages.Page, jpg: bytes
) -> tuple[list[list[HiddenPiece]], list[HiddenPiece], list[HiddenPiece], dict[str, object]]:
    """The layer from a Vision recording: one piece per recognized word, with its advance spanning
    the word's box and its Helvetica ascender-to-descender band filling the box's height. Each piece
    goes to the printed word whose ink box it overlaps most; a piece overlapping none is unpaired.
    Returns (pieces per printed word, unpaired pieces, all pieces in Vision's order, the recording's
    facts)."""
    path, rec = vision_recording(spec.doc_id)
    if rec["image_sha256"] != sha256(jpg):
        raise SystemExit(f"{path.name}: recorded for a different picture; re-run vision/record.py")
    inks = [ink_pt(wd.ink_px, page.dpi) for wd in page.words]
    per_word: list[list[HiddenPiece]] = [[] for _ in page.words]
    unpaired: list[HiddenPiece] = []
    flat: list[HiddenPiece] = []
    skipped = 0
    band = ASCENT - DESCENT
    for obs in rec["observations"]:
        words = obs["words"]
        for wi, w in enumerate(words):
            if w["box"] is None:
                skipped += 1
                continue
            b = [Fraction(v) for v in w["box"]]
            box = (b[0] * PAGE_W, b[1] * PAGE_H, b[2] * PAGE_W, b[3] * PAGE_H)
            if box[2] <= box[0] or box[3] <= box[1]:
                skipped += 1
                continue
            size = Fraction(round((box[3] - box[1]) / band, 2))
            base = box[1] - DESCENT * size
            piece = fit_piece(w["text"], box[0], box[2], base, size, wi < len(words) - 1)
            flat.append(piece)
            overlaps = [_overlap(box, ink) for ink in inks]
            best = max(range(len(inks)), key=lambda j: overlaps[j])
            if overlaps[best] > 0:
                per_word[best].append(piece)
            else:
                unpaired.append(piece)
    for ps in per_word:
        ps.sort(key=lambda p: p.x_pt)
    facts: dict[str, object] = {
        "recording": f"vision/{path.name}",
        "recording_sha256": sha256(path.read_bytes()),
        "macos": rec["macos"],
        "request": rec["request"],
        "revision": int(rec["revision"]),
        "recognition_level": rec["recognition_level"],
        "language_correction": rec["language_correction"],
        "words_without_box": skipped,
    }
    return per_word, unpaired, flat, facts


def piece_out(p: HiddenPiece) -> dict[str, object]:
    return {
        "text": p.text,
        "box_pt": box_out(p.box()),
        "origin_pt": [num(p.x_pt, 2), num(p.baseline_pt, 2)],
        "size_pt": num(Fraction(p.size_pt), 2),
        "hscale_pct": num(p.hscale),
        "glyph_edges_pt": [num(p.x_pt)] + [num(b) for _, _, b in p.glyphs()],
    }


def piece_geom(p: HiddenPiece) -> scenarios.Piece:
    x0, y0, x1, y1 = p.box()
    glyphs = tuple(scenarios.Glyph(ch, (gx0, y0, gx1, y1)) for ch, gx0, gx1 in p.glyphs())
    return scenarios.Piece(p.text, (x0, y0, x1, y1), glyphs)


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _note_value(v: object) -> object:
    if isinstance(v, Fraction):
        return num(v)
    return v


def build_doc(spec: grid.DocSpec) -> tuple[bytes, dict[str, object]]:
    deg = pages.DEGRADES[spec.degrade]
    page, jpg = pages.render(spec.layout, spec.ground, spec.dpi, deg, spec.seed)
    unpaired: list[HiddenPiece] = []
    vision: dict[str, object] | None = None
    if spec.layer == "vision":
        pieces, unpaired, flat, vision = vision_pieces(spec, page, jpg)
    else:
        pieces = placed_pieces(spec, page)
        flat = [p for ps in pieces for p in ps]
    pdf = write_pdf(jpg, (page.width_px, page.height_px), flat, PAGE_W, PAGE_H)
    k = Fraction(72, page.dpi)
    geoms = []
    words_out = []
    for wd, ps in zip(page.words, pieces, strict=True):
        ink = ink_pt(wd.ink_px, page.dpi)
        geom = scenarios.WordGeom(
            wd.index,
            wd.line_key,
            wd.position,
            wd.text,
            ink,
            tuple(piece_geom(p) for p in ps),
            wd.under_bar,
        )
        geoms.append(geom)
        words_out.append(
            {
                "i": wd.index,
                "line": wd.line,
                "line_key": wd.line_key,
                "position": wd.position,
                "text": wd.text,
                "size_pt": wd.size_pt,
                "ink_px": list(wd.ink_px),
                "ink_pt": box_out(ink),
                "ink_polygon_pt": None
                if wd.ink_polygon_px is None
                else [
                    [
                        num(Fraction(x).limit_denominator(1000) * k),
                        num(PAGE_H - Fraction(y).limit_denominator(1000) * k),
                    ]
                    for x, y in wd.ink_polygon_px
                ],
                "baseline_pt": num(PAGE_H - wd.baseline_px * k),
                "under_bar": wd.under_bar,
                "hidden": [piece_out(p) for p in ps],
                "hidden_matches_print": " ".join(p.text for p in ps) == wd.text,
            }
        )
    page_rect = scenarios.rect(0, 0, PAGE_W, PAGE_H)
    bar = ink_pt(page.bar_px, page.dpi) if page.bar_px is not None else None
    scen_out = []
    sur = next(g for g in geoms if (g.line_key, g.position) == scenarios.SURNAME)
    misread = spec.misread is not None or " ".join(p.text for p in sur.hidden) != sur.text
    for name, kind, regions, notes in scenarios.scenario_regions(geoms, page_rect, bar, misread):
        scen_out.append(
            {
                "name": name,
                "kind": kind,
                "regions": [
                    {
                        "made_by": r.made_by,
                        "paint_pt": box_out(r.paint),
                        "strip_pt": None if r.strip is None else box_out(r.strip),
                    }
                    for r in regions
                ],
                "notes": {key: _note_value(val) for key, val in notes.items()},
                **scenarios.facts(geoms, regions),
            }
        )
    expected: dict[str, object] = {
        "schema": SCHEMA,
        "id": spec.doc_id,
        "family": "hidden-layer",
        "purpose": spec.purpose,
        "params": spec.params(),
        "page": {
            "width_pt": PAGE_W,
            "height_pt": PAGE_H,
            "dpi": spec.dpi,
            "image_px": [page.width_px, page.height_px],
        },
        "image": {"sha256": sha256(jpg), "bytes": len(jpg), "jpeg_quality": deg.jpeg_quality},
        "ground": {"kind": spec.ground, "text_fill": pages.TEXT_FILL[spec.ground]},
        "degrade": {
            "skew_deg": num(Fraction(deg.skew_centideg, 100), 2),
            "blur_px": num(Fraction(deg.blur_centipx, 100), 2),
            "jpeg_quality": deg.jpeg_quality,
        },
        "bar_pt": None if bar is None else box_out(bar),
        "bar_px": None if page.bar_px is None else list(page.bar_px),
        "rules_px": [list(r) for r in page.rules_px],
        "rules_polygon_px": [[list(pt) for pt in poly] for poly in page.rules_polygon_px] or None,
        "layer": {"render_mode": 3, "font": HIDDEN_FONT, "pieces": len(flat), "source": spec.layer},
        "vision": vision,
        "words": words_out,
        "unpaired_hidden": [piece_out(p) for p in unpaired],
        "scenarios": scen_out,
    }
    return pdf, expected


def producer() -> dict[str, str]:
    return {
        "writer": "resecta-sample-doc hidden_layer writer (direct PDF writer, this repository)",
        "python": platform.python_version(),
        "pillow": PIL.__version__,
        "numpy": np.__version__,
        "reportlab_metrics": reportlab.Version,
        "fonts": "page image: Inter 4.1 (bundled, SIL OFL 1.1), raster only; hidden layer: standard Helvetica, not embedded",
    }


def _compact(v: object) -> str:
    return json.dumps(v, separators=(", ", ": "), ensure_ascii=True)


def json_bytes(obj: object) -> bytes:
    """JSON with one top-level key per line, and one line per element of a list of objects (a word,
    a scenario, a manifest row), so a change shows as a change of one line."""
    if not isinstance(obj, dict):
        return (_compact(obj) + "\n").encode("ascii")
    lines = []
    for k, v in obj.items():
        key = json.dumps(k)
        if isinstance(v, list) and v and all(isinstance(e, dict) for e in v):
            inner = ",\n".join("  " + _compact(e) for e in v)
            lines.append(f" {key}: [\n{inner}\n ]")
        else:
            lines.append(f" {key}: {_compact(v)}")
    return ("{\n" + ",\n".join(lines) + "\n}\n").encode("ascii")


def build(out: Path, only: set[str] | None) -> list[dict[str, object]]:
    specs = [s for s in grid.all_specs() if only is None or s.doc_id in only]
    (out / "documents").mkdir(parents=True, exist_ok=True)
    (out / "expected").mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    accept: list[dict[str, str]] = []
    prod = producer()
    for spec in specs:
        pdf, expected = build_doc(spec)
        exp_b = json_bytes(expected)
        pdf_path = f"documents/{spec.doc_id}.pdf"
        exp_path = f"expected/{spec.doc_id}.expected.json"
        (out / pdf_path).write_bytes(pdf)
        (out / exp_path).write_bytes(exp_b)
        extra = {}
        if spec.layer == "vision":
            rec_path = VISION_DIR / f"{spec.doc_id}.vision.json"
            (out / "vision").mkdir(exist_ok=True)
            shutil.copyfile(rec_path, out / "vision" / rec_path.name)
            extra = {
                "vision_recording": f"vision/{rec_path.name}",
                "vision_recording_sha256": sha256(rec_path.read_bytes()),
            }
        scen = expected["scenarios"]
        for s in scen if isinstance(scen, list) else []:
            if s["hidden_copies_covered"]:
                accept.append({"document": spec.doc_id, "scenario": s["name"], "kind": s["kind"]})
        rows.append(
            {
                "path": pdf_path,
                "bytes": len(pdf),
                "sha256": sha256(pdf),
                "expected": exp_path,
                "expected_sha256": sha256(exp_b),
                "family": "hidden-layer",
                "axis": spec.axis,
                "params": spec.params(),
                "producer": prod,
                "purpose": spec.purpose,
                "stored": "committed" if len(pdf) < COMMIT_LIMIT else "local",
                **extra,
            }
        )
        sys.stdout.write(f"{spec.doc_id}  {len(pdf) // 1024} KiB  {sha256(pdf)[:12]}\n")
    manifest = {"schema": SCHEMA, "family": "hidden-layer", "documents": rows}
    (out / "manifest.json").write_bytes(json_bytes(manifest))
    (out / "accept-scenarios.json").write_bytes(
        json_bytes({"schema": SCHEMA, "rule": ACCEPT_RULE, "scenarios": accept})
    )
    sums = (
        [f"{r['sha256']}  {r['path']}" for r in rows]
        + [f"{r['expected_sha256']}  {r['expected']}" for r in rows]
        + [
            f"{r['vision_recording_sha256']}  {r['vision_recording']}"
            for r in rows
            if "vision_recording" in r
        ]
    )
    (out / "SHA256SUMS").write_text("\n".join(sums) + "\n", encoding="ascii")
    return rows


ACCEPT_RULE = (
    "Every scenario whose hidden_copies_covered is true: each marked word's hidden glyphs have their "
    "centres inside the union of the scenario's paint and strip rectangles (a scenario with no box "
    "is included)."
)


def publish(out: Path, dest: Path) -> None:
    manifest = json.loads((out / "manifest.json").read_text(encoding="ascii"))
    for sub in ("documents", "expected"):
        if (dest / sub).exists():
            shutil.rmtree(dest / sub)
        (dest / sub).mkdir(parents=True)
    for row in manifest["documents"]:
        shutil.copyfile(out / row["expected"], dest / row["expected"])
        if row["stored"] == "committed":
            shutil.copyfile(out / row["path"], dest / row["path"])
    for name in ("manifest.json", "SHA256SUMS", "accept-scenarios.json"):
        shutil.copyfile(out / name, dest / name)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=Path, required=True, help="an empty or new directory")
    ap.add_argument("--only", default="", help="comma-separated document ids")
    ap.add_argument(
        "--publish", action="store_true", help="copy the committed set into hidden_layer/"
    )
    a = ap.parse_args()
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
