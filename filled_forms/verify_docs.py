"""Check every filled-form document against its expected file.

    .venv/bin/python -I filled_forms/verify_docs.py <dir> [--only id,id] [--report out.json]

``<dir>`` holds ``manifest.json``, ``SHA256SUMS``, ``documents/`` and ``expected/``. Exit status 0
means every property of every document held. The properties (``CHECKS``):

- ``checksums``: the document and its expected file match ``manifest.json`` and ``SHA256SUMS``;
- ``facts``: the facts read from the bytes now (``facts.py``) equal the recorded ones;
- ``intent``: the facts meet what the document's producer was asked to write (``build.INTENT``);
- ``second-reader``: PyMuPDF's widget reader finds the same widgets: name, type, value, rectangle;
- ``visible``: rendering the page with and without annotations (PyMuPDF) changes no pixel inside
  the rectangle of a widget that is not shown (Hidden or NoView), and some pixels inside that of a
  shown widget whose appearance draws (``draws`` true in the expected file);
- ``reject``: the reject documents' own property: the hidden value is stored and drawn but not
  shown; the overflowing value's clipped part leaves no ink outside the field, and the split is as
  recorded; the drawn text differs from the stored value;
- ``cover``: on the cover document, the printed SSN is still page text and the widget renders as a
  dark box over it;
- ``xfa``: the XFA packets join into one well-formed XML document whose template has a repeating
  subform and whose data holds the values; the stand-in page carries its text.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pymupdf
import pypdf

from filled_forms import build, facts, producers
from hidden_layer.verify_docs import Result, read_sums

RENDER_DPI = 144
RECT_TOL_PT = 0.05
MU_TYPES = {
    "text": "Text",
    "multiline": "Text",
    "checkbox": "CheckBox",
    "radio": "RadioButton",
    "combo": "ComboBox",
    "list": "ListBox",
    "signature": "Signature",
}


def _render(pdf: bytes, annots: bool) -> np.ndarray:
    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        pix = doc[0].get_pixmap(
            dpi=RENDER_DPI, colorspace=pymupdf.csGRAY, alpha=False, annots=annots
        )
        return np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width).copy()


def _px(rect: list[float], shape: tuple[int, ...], pad: float = 0.0) -> tuple[int, int, int, int]:
    s = RENDER_DPI / 72
    x0, y0, x1, y1 = rect
    h = shape[0]
    return (
        max(0, int((x0 - pad) * s)),
        max(0, int(h - (y1 + pad) * s)),
        min(shape[1], round((x1 + pad) * s)),
        min(h, round(h - (y0 - pad) * s)),
    )


def check_facts(pdf: bytes, exp: dict[str, Any], r: Result) -> dict[str, Any]:
    now = facts.read(pdf)
    same = json.loads(json.dumps(now)) == json.loads(json.dumps(exp["facts"]))
    r.record(
        "facts",
        same,
        f"{len(now['widgets'])} widgets, {len(now['other_annotations'])} other annotations"
        + ("" if same else "; differ from the expected file"),
    )
    return now


def check_intent(doc_id: str, fx: dict[str, Any], r: Result) -> None:
    doc = next(d for d in build.DOCS if d[0] == doc_id)
    problems = doc[4](fx)
    r.record("intent", not problems, "; ".join(problems) or "as asked")


def _mu_value(w: Any) -> Any:
    v = w.field_value
    return None if v in ("", None) else str(v)


def _norm_value(v: Any) -> Any:
    if v is None or v == "":
        return None
    if isinstance(v, list):
        return v
    return v[1:] if isinstance(v, str) and v.startswith("/") else v


def check_second_reader(pdf: bytes, exp: dict[str, Any], r: Result) -> None:
    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        mu = [
            (w.field_name, w.field_type_string, _mu_value(w), list(w.rect))
            for w in doc[0].widgets()
        ]
    h = 792
    want = exp["facts"]["widgets"]
    bad = []
    if len(mu) != len(want):
        bad.append(f"{len(mu)} widgets read, {len(want)} expected")
    for w in want:
        x0, y0, x1, y1 = w["rect"]
        hit = next(
            (
                m
                for m in mu
                if all(
                    abs(a - b) <= RECT_TOL_PT
                    for a, b in zip(m[3], (x0, h - y1, x1, h - y0), strict=True)
                )
            ),
            None,
        )
        if hit is None:
            bad.append(f"{w['name']}: no widget at its rectangle")
            continue
        kind = build.field_kind(w["ft"], w["ff"])
        if hit[0] != w["name"]:
            bad.append(f"name {hit[0]!r} != {w['name']!r}")
        if hit[1] != MU_TYPES.get(kind):
            bad.append(f"{w['name']}: type {hit[1]} != {kind}")
        if kind in ("text", "multiline", "combo") and _norm_value(hit[2]) != _norm_value(
            w["value"]
        ):
            bad.append(f"{w['name']}: value {hit[2]!r} != {w['value']!r}")
    r.record(
        "second-reader", not bad, f"{len(mu)} widgets agree" if not bad else "; ".join(bad[:4])
    )


def check_visible(pdf: bytes, exp: dict[str, Any], r: Result) -> None:
    on, off = _render(pdf, True), _render(pdf, False)
    diff = on != off
    bad = []
    n = 0
    for w, ink in zip(exp["facts"]["widgets"], exp["draws"], strict=True):
        if ink is None:
            continue
        n += 1
        x0, y0, x1, y1 = _px(w["rect"], diff.shape)
        changed = int(diff[y0:y1, x0:x1].sum())
        if (changed > 0) != ink:
            bad.append(f"{w['name']}: {changed} px changed, draws={ink}")
    r.record("visible", not bad, f"{n} widgets as expected" if not bad else "; ".join(bad[:4]))


def check_reject(pdf: bytes, exp: dict[str, Any], r: Result) -> None:
    doc_id = exp["id"]
    fx = exp["facts"]
    if exp["kind"] != "reject":
        r.record("reject", None, "not a reject document")
        return
    problems = []
    if doc_id == "ff-reject-hidden-value":
        w = fx["widgets"][0]
        if not (
            w["value"]
            and w["value"] in w["appearance"]["drawn"]
            and "hidden" in w["annot_flag_names"]
        ):
            problems.append("hidden value not stored and drawn")
        if exp["visible"][0] is not False:
            problems.append("expected file says shown")
        with pymupdf.open(stream=pdf, filetype="pdf") as doc:
            if w["value"] in doc[0].get_text():
                problems.append("value in the page text")
    elif doc_id == "ff-reject-overflow":
        if not exp.get("overflow"):
            problems.append("no overflow recorded (the appearance has no clip, size or origin)")
        elif build.overflow_facts(fx) != exp["overflow"]:
            problems.append("overflow split differs")
        on, off = _render(pdf, True), _render(pdf, False)
        diff = on != off
        x0, y0, x1, y1 = _px(fx["widgets"][0]["rect"], diff.shape, pad=1.0)
        outside = int(diff.sum()) - int(diff[y0:y1, x0:x1].sum())
        if outside:
            problems.append(f"{outside} px of the appearance outside the field")
        if exp.get("overflow") and not exp["overflow"]["clipped_text"]:
            problems.append("nothing clipped")
    elif doc_id == "ff-reject-value-differs":
        w = fx["widgets"][0]
        if (
            w["appearance"]["drawn"] == [w["value"]]
            or exp.get("appearance_matches_value") is not False
        ):
            problems.append("drawn text equals the stored value")
    r.record("reject", not problems, "; ".join(problems) or "holds")


COVER_DARK_MIN = 0.85
DARK_LEVEL = 64


def check_cover(pdf: bytes, exp: dict[str, Any], r: Result) -> None:
    """The cover document: the printed SSN is still page text, and with annotations rendered the
    widget's rectangle is at least ``COVER_DARK_MIN`` dark pixels (below ``DARK_LEVEL``)."""
    if exp["id"] != "ff-pdfkit-blackwidget-cover":
        r.record("cover", None, "not the cover document")
        return
    w = exp["facts"]["widgets"][0]
    on, off = _render(pdf, True), _render(pdf, False)
    x0, y0, x1, y1 = _px(w["rect"], on.shape)
    dark_on = float((on[y0:y1, x0:x1] < DARK_LEVEL).mean())
    dark_off = float((off[y0:y1, x0:x1] < DARK_LEVEL).mean())
    ssn = next(f.value for f in build.FIELDS if f.name == "ssn") or ""
    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        in_text = ssn in doc[0].get_text()
    ok = dark_on >= COVER_DARK_MIN and in_text
    r.record(
        "cover",
        ok,
        f"box {dark_on:.2f} dark with annotations ({dark_off:.2f} without); SSN in page text: {in_text}",
    )


def check_xfa(pdf: bytes, exp: dict[str, Any], r: Result) -> None:
    if exp["kind"] != "xfa":
        r.record("xfa", None, "not an XFA document")
        return
    rd = pypdf.PdfReader(io.BytesIO(pdf))
    cat: Any = rd.trailer["/Root"]
    arr = cat["/AcroForm"]["/XFA"]
    xml = "".join(arr[i + 1].get_object().get_data().decode("utf-8") for i in range(0, len(arr), 2))
    problems = []
    try:
        root = ElementTree.fromstring(xml)  # noqa: S314 - the packets this repository wrote
    except ElementTree.ParseError as e:
        r.record("xfa", False, f"packets are not well-formed XML: {e}")
        return
    ns = "{http://www.xfa.org/schema/xfa-template/3.3/}"
    occur = root.findall(f".//{ns}occur")
    if not any(o.get("max") == "-1" for o in occur):
        problems.append("no repeating subform")
    data = ElementTree.tostring(root, encoding="unicode")
    for f in ("full_name", "phone", "ssn"):
        val = next(x.value for x in build.FIELDS if x.name == f)
        if val and val not in data:
            problems.append(f"{f} value missing")
    if producers.XFA_STAND_IN[1] not in exp["facts"]["page_text"]:
        problems.append("stand-in text missing")
    r.record(
        "xfa",
        not problems,
        "; ".join(problems)
        or f"{len(arr) // 2} packets, well-formed, repeating subform, values present",
    )


def check_one(root: Path, row: dict[str, Any], sums: dict[str, str]) -> Result:
    doc_id = Path(row["path"]).stem
    r = Result(doc_id)
    pdf = (root / row["path"]).read_bytes()
    exp_b = (root / row["expected"]).read_bytes()
    exp = json.loads(exp_b.decode("ascii"))
    sha, esha = hashlib.sha256(pdf).hexdigest(), hashlib.sha256(exp_b).hexdigest()
    ok = (
        sha == row["sha256"] == sums.get(row["path"])
        and esha == row["expected_sha256"] == sums.get(row["expected"])
        and len(pdf) == row["bytes"]
    )
    r.record("checksums", ok, f"pdf {sha[:12]}, expected {esha[:12]}")
    fx = check_facts(pdf, exp, r)
    check_intent(doc_id, fx, r)
    check_second_reader(pdf, exp, r)
    check_visible(pdf, exp, r)
    check_reject(pdf, exp, r)
    check_cover(pdf, exp, r)
    check_xfa(pdf, exp, r)
    return r


CHECKS = ("checksums", "facts", "intent", "second-reader", "visible", "reject", "cover", "xfa")


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
    sys.stdout.write(f"{len(results)} checked, {len(failed)} failed\n")
    if a.report:
        a.report.write_text(
            json.dumps([{"doc": x.doc, "ok": x.ok, "checks": x.checks} for x in results], indent=1)
            + "\n",
            encoding="ascii",
        )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
