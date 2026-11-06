"""Check every script and handwriting document against its expected file.

    .venv/bin/python -I scripts_handwriting/verify_docs.py <dir> [--only id,id] [--report out.json]

Exit status 0 means every property of every checked document held (a document listed as ``local``
and absent is reported as not checked). The properties (``CHECKS``):

- ``checksums``: the document and its expected file match ``manifest.json`` and ``SHA256SUMS``;
- ``fonts``: every embedded font is one of the family's subsets (its name holds "Subset") or the
  glyphless layer font; no other font is embedded;
- ``layer``: each line's text layer, decoded in content order through the fonts' ToUnicode maps
  (``layerread.py``), equals the recorded ``layer_text``, and the recorded match flags follow from
  it; a ``placed`` twin's layer equals its born page's;
- ``render-mode``: a born page shows its text in render mode 0; every show of a scanned or
  handwriting page's layer is in render mode 3, and a ``placed`` twin renders exactly as its picture;
- ``ink``: each line's word ink boxes, measured again on a fresh render (poppler's ``pdftoppm`` for a
  born page where it is installed, PyMuPDF otherwise; the embedded picture for a scan), have the
  recorded count and edges within ``INK_TOL_PX``; on a handwriting page, the ink inside each word box
  reaches that box's edges within ``INK_TOL_PX``;
- ``direction``: a left-to-right line's first ink box starts at its anchor, a right-to-left line's
  last ink box ends at its anchor (within ``ANCHOR_TOL_EM`` em, a glyph's side bearing); a vertical line's ink groups run down
  one column;
- ``vision``: the recording's SHA-256 and picture match, and the layer draws exactly the recorded
  pieces, in order;
- ``picture``: the JPEG's quantization tables equal Pillow's at the stated quality, and its size
  gives the stated resolution.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pypdf
from PIL import Image

from hidden_layer.verify_docs import Result, read_sums
from scripts_handwriting import build, ink, layerread, twins

INK_TOL_PX = 3
ANCHOR_TOL_EM = 0.3  # a first or last glyph's side bearing
VERTICAL_COLUMN_TOL_PT = 12.0
GLYPHLESS = "GlyphlessLayer"


def _base(name: str) -> str:
    return name.lstrip("/").split("+", 1)[-1]


def check_fonts(pdf: bytes, exp: dict[str, Any], r: Result) -> None:
    names = layerread.embedded_fonts(pdf)
    bad = [n for n in names if "Subset" not in _base(n) and not _base(n).startswith(GLYPHLESS)]
    same = names == exp["fonts_embedded"]
    r.record(
        "fonts",
        not bad and same,
        f"{len(names)} fonts"
        + (f"; not allowed: {bad}" if bad else "")
        + ("" if same else "; differ from the expected file"),
    )


def check_layer(pdf: bytes, exp: dict[str, Any], root: Path, r: Result) -> None:
    has_layer = exp["kind"] == "born" or exp.get("layer") == "placed"
    if not has_layer:
        r.record("layer", None, "no line layer recorded (none or Vision)")
        return
    shows = layerread.shows(pdf)
    writer = next(
        s.writer
        for s in build.specs()
        if s.doc_id == (exp["id"] if exp["kind"] == "born" else exp["source"])
    )
    bad = []
    for ln in exp["lines"]:
        span = (float(ln["span_pt"][0]), float(ln["span_pt"][1]))
        got = layerread.line_text(
            shows,
            float(ln["anchor_pt"][1]),
            span,
            float(ln["anchor_pt"][0]) if ln["vertical"] else None,
        )
        if got != ln["layer_text"]:
            bad.append(f"{ln['key']}: decoded {got[:20]!r}")
        cands = (
            [got, got[::-1]]
            if ln["direction"] == "rtl" and writer in build.RTL_VISUAL_WRITERS
            else [got]
        )
        flags = (
            got == ln["text"],
            any(
                unicodedata.normalize("NFKC", c) == unicodedata.normalize("NFKC", ln["text"])
                for c in cands
            ),
            got.count("�"),
        )
        if flags != (ln["decodes_exactly"], ln["decodes_normalised"], ln["layer_unmapped"]):
            bad.append(f"{ln['key']}: flags {flags}")
    if exp["kind"] == "scan":
        src = root / f"expected/{exp['source']}.expected.json"
        if src.exists():
            born = {
                x["key"]: x["layer_text"]
                for x in json.loads(src.read_text(encoding="utf-8"))["lines"]
            }
            diff = [ln["key"] for ln in exp["lines"] if born.get(ln["key"]) != ln["layer_text"]]
            if diff:
                bad.append(f"differs from the born page at {diff[:3]}")
    n = len(exp["lines"])
    exact = sum(1 for ln in exp["lines"] if ln["decodes_exactly"])
    r.record(
        "layer",
        not bad,
        f"{n - len(bad)}/{n} lines decode as recorded ({exact} exactly the text)"
        + (f"; {bad[:3]}" if bad else ""),
    )


def _embedded_jpeg(pdf: bytes) -> bytes | None:
    rd = pypdf.PdfReader(io.BytesIO(pdf))
    page: Any = rd.pages[0]

    def find(container: Any, depth: int) -> bytes | None:
        for ref in ((container.get("/Resources") or {}).get("/XObject") or {}).values():
            xo = ref.get_object()
            if xo.get("/Subtype") == "/Image" and xo.get("/Filter") == "/DCTDecode":
                return bytes(xo._data)
            if xo.get("/Subtype") == "/Form" and depth < 4:
                got = find(xo, depth + 1)
                if got:
                    return got
        return None

    return find(page, 0)


def check_render_mode(pdf: bytes, exp: dict[str, Any], r: Result) -> None:
    modes = sorted({s.render_mode for s in layerread.shows(pdf)})
    if exp["kind"] == "born":
        ok = modes == [0] and modes == exp["render_modes"]
        r.record("render-mode", ok, f"born page shows in mode {modes}")
        return
    if exp.get("layer") == "none":
        r.record("render-mode", modes == [] == exp["render_modes"], f"no text shows: {modes == []}")
        return
    ok = modes == [3] == exp["render_modes"]
    detail = f"layer shows in mode {modes}"
    if exp.get("layer") == "placed":
        jpeg = _embedded_jpeg(pdf)
        pic = np.asarray(Image.open(io.BytesIO(jpeg or b"")).convert("L")) if jpeg else None
        rendered = twins.render_gray(pdf, int(exp["dpi"]))
        same = (
            pic is not None
            and pic.shape == rendered.shape
            and int(np.abs(pic.astype(int) - rendered.astype(int)).max()) <= 1
        )
        ok = ok and same
        detail += f"; renders as its picture: {same}"
    r.record("render-mode", ok, detail)


def _render_independent(pdf: bytes, dpi: int) -> tuple[np.ndarray, str]:
    exe = shutil.which("pdftoppm")
    if exe:
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "p.pdf"
            src.write_bytes(pdf)
            cmd = [
                exe,
                "-r",
                str(dpi),
                "-gray",
                "-singlefile",
                "-png",
                str(src),
                str(Path(td) / "o"),
            ]
            subprocess.run(cmd, check=True, capture_output=True)  # noqa: S603 - poppler, on PATH
            return np.asarray(Image.open(Path(td) / "o.png").convert("L")), "pdftoppm"
    return twins.render_gray(pdf, dpi), "PyMuPDF"


def check_ink(pdf: bytes, exp: dict[str, Any], r: Result) -> None:
    if exp["kind"] == "hand":
        jpeg = _embedded_jpeg(pdf)
        img = np.asarray(Image.open(io.BytesIO(jpeg or b"")).convert("L"))
        thr = ink.threshold(img)
        bad = []
        for w in exp["words"]:
            x0, y0, x1, y1 = w["box_px"]
            t = INK_TOL_PX
            sub = img[max(0, y0 - t) : y1 + t, max(0, x0 - t) : x1 + t] < thr
            ys, xs = np.nonzero(sub)
            if xs.size == 0:
                bad.append(f"{w['text']}: no ink")
                continue
            m = (
                max(0, x0 - t) + int(xs.min()),
                max(0, y0 - t) + int(ys.min()),
                max(0, x0 - t) + int(xs.max()) + 1,
                max(0, y0 - t) + int(ys.max()) + 1,
            )
            if any(abs(a - b) > INK_TOL_PX for a, b in zip(m, (x0, y0, x1, y1), strict=True)):
                bad.append(f"{w['text']}: {[x0, y0, x1, y1]} -> {list(m)}")
        r.record(
            "ink",
            not bad,
            f"{len(exp['words']) - len(bad)}/{len(exp['words'])} word boxes hold their ink"
            + (f"; {bad[:3]}" if bad else ""),
        )
        return
    dpi = int(exp["ink_dpi"])
    if exp["kind"] == "born":
        img = twins.render_gray(pdf, dpi)
    else:
        jpeg = _embedded_jpeg(pdf)
        img = np.asarray(Image.open(io.BytesIO(jpeg or b"")).convert("L"))
    rules = _rules(exp)
    bad = []
    for ln in exp["lines"]:
        span = (float(ln["span_pt"][0]), float(ln["span_pt"][1]))
        got = ink.word_boxes(
            img,
            dpi,
            float(ln["size_pt"]),
            float(ln["anchor_pt"][1]),
            span,
            float(ln["anchor_pt"][0]) if ln["vertical"] else None,
            exclude=rules,
        )
        want = ln["ink_boxes_px"]
        if len(got) != len(want) or any(
            abs(a - b) > INK_TOL_PX
            for g, w in zip(got, want, strict=False)
            for a, b in zip(g, w, strict=True)
        ):
            bad.append(f"{ln['key']}: {len(got)} boxes vs {len(want)}")
    how = "PyMuPDF render" if exp["kind"] == "born" else "the embedded picture"
    if exp["kind"] == "born":
        other, name = _render_independent(pdf, dpi)
        if name != "PyMuPDF":
            bad += _containment(other, dpi, exp, rules)
            how += f", and {name} for containment"
    n = len(exp["lines"])
    r.record("ink", not bad, f"{n} lines checked ({how})" + (f"; {bad[:3]}" if bad else ""))


def _containment(
    img: np.ndarray, dpi: int, exp: dict[str, Any], rules: list[tuple[float, float, float, float]]
) -> list[str]:
    """On a second renderer: every recorded box holds ink, and no ink in a line's band lies more than
    ``INK_TOL_PX`` outside the union of its recorded boxes."""
    bad = []
    for ln in exp["lines"]:
        span = (float(ln["span_pt"][0]), float(ln["span_pt"][1]))
        got = ink.word_boxes(
            img,
            dpi,
            float(ln["size_pt"]),
            float(ln["anchor_pt"][1]),
            span,
            float(ln["anchor_pt"][0]) if ln["vertical"] else None,
            exclude=rules,
        )
        t = INK_TOL_PX
        for g in got:
            if not any(w[0] - t <= g[0] and g[2] <= w[2] + t for w in ln["ink_boxes_px"]) and not (
                min(w[0] for w in ln["ink_boxes_px"]) - t <= g[0]
                and g[2] <= max(w[2] for w in ln["ink_boxes_px"]) + t
            ):
                bad.append(f"{ln['key']}: ink at {g} outside the recorded boxes")
        if not got and ln["ink_boxes_px"]:
            bad.append(f"{ln['key']}: no ink on the second render")
    return bad


def _rules(exp: dict[str, Any]) -> list[tuple[float, float, float, float]]:
    if exp["layout"] != "form":
        return []
    return build.placed_lines(exp["script"], "form")[1]


def check_direction(exp: dict[str, Any], r: Result) -> None:
    if exp["kind"] == "hand":
        r.record("direction", None, "handwriting: left to right by construction")
        return
    s = int(exp["ink_dpi"]) / 72
    bad = []
    for ln in exp["lines"]:
        boxes = ln["ink_boxes_px"]
        if not boxes:
            bad.append(f"{ln['key']}: no ink")
            continue
        ax, ay = float(ln["anchor_pt"][0]), float(ln["anchor_pt"][1])
        tol = ANCHOR_TOL_EM * float(ln["size_pt"])
        if ln["vertical"]:
            tops = [b[1] for b in boxes]
            centre = [(b[0] + b[2]) / 2 / s for b in boxes]
            if tops != sorted(tops) or any(abs(c - ax) > VERTICAL_COLUMN_TOL_PT for c in centre):
                bad.append(f"{ln['key']}: not one column")
        elif ln["align"] == "right":
            if abs(max(b[2] for b in boxes) / s - ax) > tol:
                bad.append(f"{ln['key']}: right edge {max(b[2] for b in boxes) / s:.1f} vs {ax}")
        elif abs(min(b[0] for b in boxes) / s - ax) > tol:
            bad.append(f"{ln['key']}: left edge {min(b[0] for b in boxes) / s:.1f} vs {ax}")
        del ay
    n = len(exp["lines"])
    r.record(
        "direction",
        not bad,
        f"{n - len(bad)}/{n} lines sit as their direction says" + (f"; {bad[:3]}" if bad else ""),
    )


def check_vision(pdf: bytes, exp: dict[str, Any], root: Path, r: Result) -> None:
    v = exp.get("vision")
    if not v:
        r.record("vision", None, "no Vision layer")
        return
    path = root / v["recording"]
    if not path.exists():
        r.record("vision", False, f"{v['recording']} missing")
        return
    raw = path.read_bytes()
    rec = json.loads(raw.decode("utf-8"))
    problems = []
    if hashlib.sha256(raw).hexdigest() != v["recording_sha256"]:
        problems.append("recording checksum differs")
    if rec["image_sha256"] != exp["image"]["sha256"]:
        problems.append("recorded from a different picture")
    jpeg = _embedded_jpeg(pdf)
    if jpeg is None or hashlib.sha256(jpeg).hexdigest() != exp["image"]["sha256"]:
        problems.append("embedded picture differs")
    drawn = [s.text for s in layerread.shows(pdf)]
    want = [p[0] for p in v["pieces"]]
    if drawn != want:
        problems.append(f"layer draws {len(drawn)} pieces, recording has {len(want)}")
    r.record(
        "vision",
        not problems,
        "; ".join(problems)
        or f"{len(want)} recorded pieces drawn in order (macOS {v['macos']}, revision {v['revision']})",
    )


def check_picture(pdf: bytes, exp: dict[str, Any], r: Result) -> None:
    if exp["kind"] == "born":
        r.record("picture", None, "born-digital")
        return
    jpeg = _embedded_jpeg(pdf)
    if jpeg is None:
        r.record("picture", False, "no JPEG picture")
        return
    im: Any = Image.open(io.BytesIO(jpeg))
    ref = io.BytesIO()
    Image.new("L", im.size, 128).save(ref, "JPEG", quality=int(exp["jpeg_quality"]))
    want: Any = Image.open(io.BytesIO(ref.getvalue()))
    dpi = round(im.size[0] * 72 / 612)
    ok = (
        im.quantization == want.quantization
        and dpi == int(exp["dpi"])
        and hashlib.sha256(jpeg).hexdigest() == exp["image"]["sha256"]
    )
    r.record(
        "picture",
        ok,
        f"q{exp['jpeg_quality']} tables {'equal' if im.quantization == want.quantization else 'differ'}; {dpi} dpi",
    )


def check_one(root: Path, row: dict[str, Any], sums: dict[str, str]) -> Result:
    doc_id = Path(row["path"]).stem
    r = Result(doc_id)
    pdf_path = root / row["path"]
    exp_b = (root / row["expected"]).read_bytes()
    exp = json.loads(exp_b.decode("ascii"))
    if not pdf_path.exists():
        r.record("present", None, f"stored {row['stored']}: not in this directory; not checked")
        return r
    pdf = pdf_path.read_bytes()
    sha, esha = hashlib.sha256(pdf).hexdigest(), hashlib.sha256(exp_b).hexdigest()
    ok = (
        sha == row["sha256"] == sums.get(row["path"])
        and esha == row["expected_sha256"] == sums.get(row["expected"])
        and len(pdf) == row["bytes"]
    )
    r.record("checksums", ok, f"pdf {sha[:12]}, expected {esha[:12]}")
    check_fonts(pdf, exp, r)
    check_layer(pdf, exp, root, r)
    check_render_mode(pdf, exp, r)
    check_ink(pdf, exp, r)
    check_direction(exp, r)
    check_vision(pdf, exp, root, r)
    check_picture(pdf, exp, r)
    return r


CHECKS = ("checksums", "fonts", "layer", "render-mode", "ink", "direction", "vision", "picture")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("root", type=Path)
    ap.add_argument("--only", default="")
    ap.add_argument("--report", type=Path)
    a = ap.parse_args()
    manifest = json.loads((a.root / "manifest.json").read_text(encoding="ascii"))
    sums = read_sums(a.root / "SHA256SUMS")
    only = {x for x in a.only.split(",") if x}
    results = []
    for row in manifest["documents"]:
        if only and Path(row["path"]).stem not in only:
            continue
        res = check_one(a.root, row, sums)
        results.append(res)
        sys.stdout.write(f"{'ok  ' if res.ok else 'FAIL'} {res.doc}\n")
        for name, c in res.checks.items():
            if c["ok"] is False or a.only:
                state = "ok" if c["ok"] else ("n/a" if c["ok"] is None else "FAIL")
                sys.stdout.write(f"     {name}: {state}  {c['detail']}\n")
    failed = [x.doc for x in results if not x.ok]
    checked = sum(1 for x in results if "present" not in x.checks)
    sys.stdout.write(
        f"{checked} checked, {len(results) - checked} not present, {len(failed)} failed\n"
    )
    if a.report:
        a.report.write_text(
            json.dumps(
                [{"doc": x.doc, "ok": x.ok, "checks": x.checks} for x in results],
                indent=1,
                ensure_ascii=True,
            )
            + "\n",
            encoding="ascii",
        )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
