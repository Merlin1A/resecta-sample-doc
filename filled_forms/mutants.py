"""Recorded mutants: one deliberate defect per property kind, each of which ``verify_docs`` must
report as a failed property.

    .venv/bin/python -I filled_forms/mutants.py --out <empty dir> [--record mutants-record.json]

Each mutant builds one document with the defect applied (to its producer, or to the files after the
build) and runs the checks. The run passes only when every unmutated control is green and every
mutant turns its own property red.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject, TextStringObject

from filled_forms import build, producers, verify_docs
from hidden_layer.build import json_bytes
from hidden_layer.verify_docs import read_sums

Made = tuple[bytes, dict[str, Any]]


@contextmanager
def patched(obj: Any, name: str, value: Any) -> Iterator[None]:
    old = getattr(obj, name)
    setattr(obj, name, value)
    try:
        yield
    finally:
        setattr(obj, name, old)


def _doc(doc_id: str) -> build.Doc:
    return next(d for d in build.DOCS if d[0] == doc_id)


def _make(doc_id: str) -> Made:
    return build.build_doc(_doc(doc_id), check_intent=False)


def _value_written_wrong() -> Made:
    w = PdfWriter(clone_from=PdfReader(io.BytesIO(producers.pypdf_text(True))))
    page: Any = w.pages[0]
    for ref in page["/Annots"]:
        a = ref.get_object()
        if a.get("/T") == "ssn":
            a[NameObject("/V")] = TextStringObject("000-41-7721")
    buf = io.BytesIO()
    w.write(buf)
    doc = _doc("ff-pypdf-text-ap")
    return build.build_doc(
        (doc[0], doc[1], doc[2], buf.getvalue, doc[4], doc[5]), check_intent=False
    )


def _expected_value_changed() -> Made:
    pdf, exp = _make("ff-pypdf-buttons")
    exp["facts"]["widgets"][0]["value"] = "changed"
    return pdf, exp


def _expected_widget_moved() -> Made:
    pdf, exp = _make("ff-reportlab-all")
    w = exp["facts"]["widgets"][0]
    w["rect"] = [w["rect"][0] + 30, w["rect"][1], w["rect"][2] + 30, w["rect"][3]]
    return pdf, exp


def _draws_flipped() -> Made:
    pdf, exp = _make("ff-pypdf-hidden-noview")
    i = next(k for k, w in enumerate(exp["facts"]["widgets"]) if w["name"] == "ssn")
    exp["draws"][i] = True
    return pdf, exp


def _overflow_unclipped() -> Made:
    real = producers.text_ap
    with patched(
        producers, "text_ap", lambda text, w, h, size=11, clip=True: real(text, w, h, size, False)
    ):
        return _make("ff-reject-overflow")


def _cover_emptied() -> Made:
    pdf, _ = _make("ff-pdfkit-blackwidget-cover")
    w = PdfWriter(clone_from=PdfReader(io.BytesIO(pdf)))
    page: Any = w.pages[0]
    annot: Any = page["/Annots"][0].get_object()
    blank = DecodedStreamObject()
    blank.set_data(b"")
    blank[NameObject("/Type")] = NameObject("/XObject")
    blank[NameObject("/Subtype")] = NameObject("/Form")
    blank[NameObject("/BBox")] = annot["/AP"]["/N"].get_object()["/BBox"]
    annot["/AP"][NameObject("/N")] = w._add_object(blank)
    buf = io.BytesIO()
    w.write(buf)
    doc = _doc("ff-pdfkit-blackwidget-cover")
    return build.build_doc(
        (doc[0], doc[1], doc[2], buf.getvalue, doc[4], doc[5]), check_intent=False
    )


def _xfa_value_dropped() -> Made:
    real = producers._xfa_packets

    def dropped() -> list[tuple[str, str]]:
        return [(n, x.replace(producers.v.SSN, "")) for n, x in real()]

    with patched(producers, "_xfa_packets", dropped):
        return _make("ff-xfa-dynamic")


MUTANTS: list[tuple[str, str, str, Callable[[], Made]]] = [
    (
        "value-written-wrong",
        "intent",
        "pypdf fills the SSN with a different last digit",
        _value_written_wrong,
    ),
    (
        "expected-value-changed",
        "facts",
        "one recorded value in the expected file is changed",
        _expected_value_changed,
    ),
    (
        "expected-widget-moved",
        "second-reader",
        "one recorded widget rectangle is moved 30 pt",
        _expected_widget_moved,
    ),
    ("draws-flipped", "visible", "the Hidden SSN widget is recorded as drawing", _draws_flipped),
    (
        "overflow-unclipped",
        "reject",
        "the overflowing appearance is written without its clip",
        _overflow_unclipped,
    ),
    (
        "cover-emptied",
        "cover",
        "the black cover widget's appearance is replaced by an empty one",
        _cover_emptied,
    ),
    ("xfa-value-dropped", "xfa", "the SSN is left out of the XFA packets", _xfa_value_dropped),
]


def run_one(out: Path, name: str, made: Made, tamper_manifest: bool = False) -> dict[str, Any]:
    pdf, exp = made
    d = out / name
    (d / "documents").mkdir(parents=True)
    (d / "expected").mkdir()
    exp_b = json_bytes(exp)
    doc = exp["id"]
    (d / f"documents/{doc}.pdf").write_bytes(pdf)
    (d / f"expected/{doc}.expected.json").write_bytes(exp_b)
    row = {
        "path": f"documents/{doc}.pdf",
        "bytes": len(pdf),
        "sha256": hashlib.sha256(pdf).hexdigest(),
        "expected": f"expected/{doc}.expected.json",
        "expected_sha256": hashlib.sha256(exp_b).hexdigest(),
    }
    sums = f"{row['sha256']}  {row['path']}\n{row['expected_sha256']}  {row['expected']}\n"
    (d / "SHA256SUMS").write_text(sums, encoding="ascii")
    if tamper_manifest:
        row["sha256"] = "0" * 64
    (d / "manifest.json").write_bytes(json_bytes({"documents": [row]}))
    res = verify_docs.check_one(d, row, read_sums(d / "SHA256SUMS"))
    return {k: v["ok"] for k, v in res.checks.items()}


CONTROLS = (
    "ff-pypdf-text-ap",
    "ff-pypdf-buttons",
    "ff-reportlab-all",
    "ff-pypdf-hidden-noview",
    "ff-reject-overflow",
    "ff-pdfkit-blackwidget-cover",
    "ff-xfa-dynamic",
)


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
            lambda: _make("ff-control-no-widgets"),
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
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
