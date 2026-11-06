"""Recorded mutants: one deliberate defect per property kind, each of which ``verify_docs`` must
report as a failed property.

    .venv/bin/python -I scripts_handwriting/mutants.py --out <empty dir> [--record mutants-record.json]

The run passes only when every unmutated control is green and every mutant turns its own property
red.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import shutil
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont as RLTTFont

from hidden_layer.build import json_bytes
from hidden_layer.verify_docs import read_sums
from scripts_handwriting import born, build, twins, verify_docs

Made = tuple[bytes, dict[str, Any]]
INTER = Path(__file__).resolve().parent.parent / "fonts" / "Inter-Regular.ttf"


def _spec(doc_id: str) -> build.Spec:
    return next(s for s in build.specs() if s.doc_id == doc_id)


def _make(doc_id: str) -> Made:
    return build.build_doc(_spec(doc_id))


def _foreign_font() -> Made:
    """The Latin runs of a reportlab page drawn in a font that is not one of the family's subsets."""
    real = born._rl_font

    def other(key: str) -> str:
        if key == "latin":
            if "Inter-Mutant" not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(RLTTFont("Inter-Mutant", str(INTER)))
            return "Inter-Mutant"
        return real(key)

    born._rl_font = other
    build._born_cache.clear()
    try:
        return _make("sh-born-el-prose")
    finally:
        born._rl_font = real
        build._born_cache.clear()


def _tounicode_changed() -> Made:
    """The first mapping to a real character in the page font's ToUnicode map is pointed at the next one (the page
    still draws the same glyphs)."""
    import pypdf

    pdf, exp = _make("sh-born-ru-form")
    w = pypdf.PdfWriter(clone_from=pypdf.PdfReader(io.BytesIO(pdf)))
    page: Any = w.pages[0]
    for ref in page["/Resources"]["/Font"].values():
        tu = ref.get_object().get("/ToUnicode")
        if tu is None:
            continue
        tu = tu.get_object()
        data = tu.get_data()
        m = next(
            (
                x
                for x in re.finditer(rb"<[0-9A-Fa-f]{2,4}>\s*<([0-9A-Fa-f]{4})>", data)
                if x.group(1) != b"0000"
            ),
            None,
        )
        if m:
            nxt = f"{int(m.group(1), 16) + 1:04X}".encode("ascii")
            tu.set_data(data[: m.start(1)] + nxt + data[m.end(1) :])
            break
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue(), exp


def _visible_layer() -> Made:
    real = twins._invisible

    def visible(stream: Any, rd: Any, writer: Any) -> bytes:
        return real(stream, rd, writer).replace(b"3 Tr", b"0 Tr")

    twins._invisible = visible
    try:
        return _make("sh-scan-zh-Hans-prose-clean-placed")
    finally:
        twins._invisible = real


def _ink_moved() -> Made:
    pdf, exp = _make("sh-scan-pl-prose-clean-none")
    b = exp["lines"][2]["ink_boxes_px"][0]
    exp["lines"][2]["ink_boxes_px"][0] = [b[0] + 12, b[1], b[2] + 12, b[3]]
    return pdf, exp


def _direction_flipped() -> Made:
    pdf, exp = _make("sh-born-he-form")
    ln = next(x for x in exp["lines"] if x["key"] == "label0")
    ln["align"] = "left"
    return pdf, exp


def _vision_piece_dropped() -> Made:
    pdf, exp = _make("sh-scan-th-prose-clean-vision")
    exp["vision"]["pieces"] = exp["vision"]["pieces"][:-1]
    return pdf, exp


def _jpeg_quality_off() -> Made:
    real = twins.picture

    def lower(pdf: bytes, condition: str, seed: int) -> tuple[bytes, tuple[int, int]]:
        jpeg, px = real(pdf, condition, seed)
        img = Image.open(io.BytesIO(jpeg))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=60)
        return buf.getvalue(), px

    twins.picture = lower
    build._pictures.clear()
    try:
        pdf, exp = _make("sh-scan-vi-form-clean-none")
    finally:
        twins.picture = real
        build._pictures.clear()
    return pdf, exp


MUTANTS: list[tuple[str, str, str, Callable[[], Made]]] = [
    (
        "foreign-font",
        "fonts",
        "the Latin text of a reportlab page is drawn in a font that is not a family subset",
        _foreign_font,
    ),
    (
        "tounicode-changed",
        "layer",
        "one ToUnicode entry of a Cyrillic page maps to the next letter",
        _tounicode_changed,
    ),
    (
        "layer-visible",
        "render-mode",
        "a placed twin's layer is written in render mode 0",
        _visible_layer,
    ),
    ("ink-box-moved", "ink", "one recorded word ink box is moved 12 px", _ink_moved),
    (
        "direction-flipped",
        "direction",
        "a right-to-left label is recorded as left-aligned",
        _direction_flipped,
    ),
    (
        "vision-piece-dropped",
        "vision",
        "one recorded Vision piece is left out of the expected file",
        _vision_piece_dropped,
    ),
    (
        "jpeg-quality-off",
        "picture",
        "a twin's picture is encoded at quality 60 instead of 85",
        _jpeg_quality_off,
    ),
]
CONTROLS = (
    "sh-born-el-prose",
    "sh-born-ru-form",
    "sh-scan-zh-Hans-prose-clean-placed",
    "sh-scan-pl-prose-clean-none",
    "sh-born-he-form",
    "sh-scan-th-prose-clean-vision",
    "sh-scan-vi-form-clean-none",
    "sh-hand-letter-clean-vision",
)


def run_one(out: Path, name: str, made: Made, tamper_manifest: bool = False) -> dict[str, Any]:
    pdf, exp = made
    d = out / name
    (d / "documents").mkdir(parents=True)
    (d / "expected").mkdir()
    doc = exp["id"]
    exp_b = json_bytes(exp)
    (d / f"documents/{doc}.pdf").write_bytes(pdf)
    (d / f"expected/{doc}.expected.json").write_bytes(exp_b)
    if exp.get("vision"):
        (d / "vision").mkdir()
        shutil.copyfile(build.HERE / exp["vision"]["recording"], d / exp["vision"]["recording"])
    if exp["kind"] == "scan":
        src_id = exp["source"]
        _, src_exp = build.build_doc(_spec(src_id))
        (d / f"expected/{src_id}.expected.json").write_bytes(json_bytes(src_exp))
    row = {
        "path": f"documents/{doc}.pdf",
        "bytes": len(pdf),
        "sha256": hashlib.sha256(pdf).hexdigest(),
        "expected": f"expected/{doc}.expected.json",
        "expected_sha256": hashlib.sha256(exp_b).hexdigest(),
        "stored": "committed",
    }
    (d / "SHA256SUMS").write_text(
        f"{row['sha256']}  {row['path']}\n{row['expected_sha256']}  {row['expected']}\n",
        encoding="ascii",
    )
    if tamper_manifest:
        row["sha256"] = "0" * 64
    (d / "manifest.json").write_bytes(json_bytes({"documents": [row]}))
    res = verify_docs.check_one(d, row, read_sums(d / "SHA256SUMS"))
    return {k: v["ok"] for k, v in res.checks.items()}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--record", type=Path)
    a = ap.parse_args()
    if a.out.exists() and any(a.out.iterdir()):
        sys.stderr.write(f"refusing to write into a non-empty directory: {a.out}\n")
        return 2
    rows = []
    ok = True
    for doc_id in CONTROLS:
        checks = run_one(a.out, f"control-{doc_id}", _make(doc_id))
        green = all(v is not False for v in checks.values())
        ok = ok and green
        rows.append(
            {
                "mutant": f"control {doc_id}",
                "target": None,
                "checks": checks,
                "outcome": "green" if green else "RED",
            }
        )
    plan = [(n, t, w, m, False) for n, t, w, m in MUTANTS]
    plan.append(
        (
            "manifest-sha-changed",
            "checksums",
            "the manifest's SHA-256 for the document is changed",
            lambda: _make("sh-born-is-prose"),
            True,
        )
    )
    for name, target, what, make, tamper in plan:
        checks = run_one(a.out, name, make(), tamper)
        killed = checks.get(target) is False
        ok = ok and killed
        rows.append(
            {
                "mutant": name,
                "target": target,
                "what": what,
                "checks": checks,
                "outcome": "killed" if killed else "SURVIVED",
            }
        )
        sys.stdout.write(f"{'killed  ' if killed else 'SURVIVED'} {name} -> {target}\n")
    sys.stdout.write(
        f"{'controls green; all mutants killed' if ok else 'a control is red or a mutant survived'}\n"
    )
    if a.record:
        a.record.write_bytes(json_bytes({"rows": rows}))
        json.loads(a.record.read_text(encoding="ascii"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
