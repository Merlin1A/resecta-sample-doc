"""Build the filled-form family: each document, its expected file, ``manifest.json`` and
``SHA256SUMS``.

    .venv/bin/python -I filled_forms/build.py --out <empty dir> [--only id,id] [--publish]
    .venv/bin/python -I filled_forms/build.py --record-pdfkit      # macOS: write the PDFKit files again

Every document is small, so ``--publish`` copies all of them, with their expected files, into
``filled_forms/``. The build checks each document's facts against what its producer was asked to
write (``INTENT``) and stops on a mismatch.
"""

from __future__ import annotations

import argparse
import hashlib
import platform
import shutil
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pymupdf
import pypdf
import reportlab
from reportlab.pdfbase.pdfmetrics import stringWidth

from filled_forms import facts, pdfkit, producers
from filled_forms.form import FIELDS, by_name
from hidden_layer.build import json_bytes

HERE = Path(__file__).resolve().parent
SCHEMA = 1

FF_MULTILINE = 1 << 12
FF_COMBO = 1 << 17
FF_RADIO = 1 << 15
FF_PUSHBUTTON = 1 << 16


def field_kind(ft: str | None, ff: int) -> str:
    if ft == "/Tx":
        return "multiline" if ff & FF_MULTILINE else "text"
    if ft == "/Btn":
        if ff & FF_PUSHBUTTON:
            return "pushbutton"
        return "radio" if ff & FF_RADIO else "checkbox"
    if ft == "/Ch":
        return "combo" if ff & FF_COMBO else "list"
    if ft == "/Sig":
        return "signature"
    return "unknown"


def visible(w: dict[str, Any]) -> bool | None:
    """Whether a widget's normal appearance is drawn on screen: it has one and neither the Hidden
    nor the NoView flag is set. ``None`` where there is no appearance stream (a viewer may make one)."""
    if not w["appearance"]["present"]:
        return None
    return not ({"hidden", "noview", "invisible"} & set(w["annot_flag_names"]))


def draws(w: dict[str, Any]) -> bool | None:
    """Whether a shown widget's current appearance puts ink on the page: it draws a string, it is a
    button in a state other than Off, or it is a signature field (its appearance is a stroke).
    ``False`` for a widget that is not shown; ``None`` where neither can be said (no appearance, or
    a shown appearance with nothing to draw, whose border depends on the producer)."""
    vis = visible(w)
    if vis is None:
        return None
    if not vis:
        return False
    ap = w["appearance"]
    if any(s.strip() for s in ap.get("drawn", [])):
        return True
    if w["ft"] == "/Btn" and w["state"] not in (None, "/Off"):
        return True
    if w["ft"] == "/Sig":
        return True
    return None


def grouped(fx: dict[str, Any]) -> list[dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for i, w in enumerate(fx["widgets"]):
        g = out.setdefault(
            w["name"],
            {
                "name": w["name"],
                "ft": w["ft"],
                "kind": field_kind(w["ft"], w["ff"]),
                "ff": w["ff"],
                "value": w["value"],
                "widgets": [],
            },
        )
        g["widgets"].append(i)
    return list(out.values())


# ------------------------------------------------------------------------------------- intent
Problems = list[str]


def _field(fx: dict[str, Any], name: str) -> dict[str, Any] | None:
    return next((g for g in grouped(fx) if g["name"] == name), None)


def _expect(p: Problems, ok: bool, what: str) -> None:
    if not ok:
        p.append(what)


def _text_values(fx: dict[str, Any], p: Problems, ap: bool | None = True) -> None:
    for f in FIELDS:
        if f.kind != "text":
            continue
        g = _field(fx, f.name)
        _expect(p, g is not None and g["value"] == f.value, f"{f.name} value")
        if g is not None and ap is not None:
            _expect(
                p,
                all(fx["widgets"][i]["appearance"]["present"] == ap for i in g["widgets"]),
                f"{f.name} appearance {ap}",
            )


def _all_kinds(fx: dict[str, Any], p: Problems) -> None:
    _text_values(fx, p)
    kinds = {g["name"]: g["kind"] for g in grouped(fx)}
    for f in FIELDS:
        if f.kind != "signature":
            _expect(p, kinds.get(f.name) == f.kind, f"{f.name} kind {kinds.get(f.name)}")
    c = _field(fx, "consent")
    m = _field(fx, "mailing")
    _expect(p, c is not None and c["value"] not in (None, "/Off", "Off"), "consent on")
    _expect(p, m is not None and m["value"] in ("/Off", "Off"), "mailing off")
    _expect(p, (_field(fx, "notes") or {}).get("value") == by_name("notes").value, "notes value")


def intent_reportlab_all(fx: dict[str, Any]) -> Problems:
    p: Problems = []
    _all_kinds(fx, p)
    _expect(p, (_field(fx, "contact_pref") or {}).get("value") == "/email", "radio value")
    return p


def intent_pymupdf_all(fx: dict[str, Any]) -> Problems:
    p: Problems = []
    _all_kinds(fx, p)
    radios = [fx["widgets"][i] for i in (_field(fx, "contact_pref") or {"widgets": []})["widgets"]]
    _expect(p, [w["state"] for w in radios] == ["/Off", "/Yes", "/Off"], "radio second option on")
    return p


def intent_text_ap(fx: dict[str, Any]) -> Problems:
    p: Problems = []
    _text_values(fx, p, ap=True)
    _expect(p, fx["acroform"].get("need_appearances") is False, "no NeedAppearances")
    return p


def intent_text_noap(fx: dict[str, Any]) -> Problems:
    p: Problems = []
    _text_values(fx, p, ap=False)
    _expect(p, fx["acroform"].get("need_appearances") is True, "NeedAppearances true")
    return p


def intent_buttons(fx: dict[str, Any]) -> Problems:
    p: Problems = []
    c, m, r = _field(fx, "consent"), _field(fx, "mailing"), _field(fx, "contact_pref")
    _expect(
        p,
        c is not None
        and c["value"] == "/Yes"
        and fx["widgets"][c["widgets"][0]]["state"] == "/Yes",
        "consent on",
    )
    _expect(
        p,
        m is not None
        and m["value"] == "/Off"
        and fx["widgets"][m["widgets"][0]]["state"] == "/Off",
        "mailing off",
    )
    _expect(p, r is not None and r["value"] == "/email", "radio value /email")
    if r is not None:
        _expect(
            p,
            [fx["widgets"][i]["state"] for i in r["widgets"]] == ["/Off", "/email", "/Off"],
            "radio states",
        )
    return p


def intent_signature(fx: dict[str, Any]) -> Problems:
    p: Problems = []
    g = _field(fx, "signature")
    _expect(
        p, g is not None and g["ft"] == "/Sig" and g["value"] is None, "unsigned signature field"
    )
    _expect(
        p,
        g is not None and fx["widgets"][g["widgets"][0]]["appearance"]["present"],
        "visible appearance",
    )
    return p


def intent_hidden_noview(fx: dict[str, Any]) -> Problems:
    p: Problems = []
    _text_values(fx, p)
    flags = {w["name"]: set(w["annot_flag_names"]) for w in fx["widgets"]}
    _expect(p, "hidden" in flags.get("ssn", set()), "ssn hidden")
    _expect(p, "noview" in flags.get("dob", set()), "dob noview")
    _expect(
        p,
        all(not ({"hidden", "noview"} & f) for n, f in flags.items() if n not in ("ssn", "dob")),
        "others shown",
    )
    return p


def intent_annotation_beside(fx: dict[str, Any]) -> Problems:
    p: Problems = []
    _text_values(fx, p)
    _expect(
        p,
        sorted(o["subtype"] for o in fx["other_annotations"])
        == ["/FreeText", "/Popup", "/Square", "/Text"],
        "three other annotations and the note popup",
    )
    return p


def intent_pdfkit_filled(fx: dict[str, Any]) -> Problems:
    p: Problems = []
    _expect(p, not fx["acroform"]["present"], "no AcroForm")
    vals = [w["value"] for w in fx["widgets"] if w["ft"] == "/Tx"]
    _expect(
        p,
        vals == [by_name(n).value for n in ("full_name", "phone", "email", "ssn", "dob")],
        "text values",
    )
    _expect(
        p,
        [w["value"] for w in fx["widgets"] if w["ft"] == "/Btn"] == ["Yes", "Off"],
        "checkbox values",
    )
    return p


def intent_pdfkit_cover(fx: dict[str, Any]) -> Problems:
    p: Problems = []
    _expect(p, not fx["acroform"]["present"], "no AcroForm")
    _expect(
        p, len(fx["widgets"]) == 1 and fx["widgets"][0]["value"] in ("", None), "one empty widget"
    )
    _expect(p, (by_name("ssn").value or "") in fx["page_text"], "SSN in the page text")
    return p


def intent_control(fx: dict[str, Any]) -> Problems:
    p: Problems = []
    _expect(p, not fx["widgets"] and not fx["other_annotations"], "no annotations")
    _expect(p, not fx["acroform"]["present"], "no AcroForm")
    return p


def intent_xfa(fx: dict[str, Any]) -> Problems:
    p: Problems = []
    _expect(
        p,
        fx["acroform"].get("xfa_packets") == ["preamble", "template", "datasets", "postamble"],
        "XFA packets",
    )
    _expect(p, fx["needs_rendering"], "NeedsRendering")
    _expect(p, producers.XFA_STAND_IN[0] in fx["page_text"], "stand-in page text")
    return p


def intent_reject_hidden(fx: dict[str, Any]) -> Problems:
    p: Problems = []
    (w,) = fx["widgets"] or [None]
    ssn = by_name("ssn").value
    _expect(p, w is not None and "hidden" in w["annot_flag_names"], "hidden flag")
    _expect(
        p,
        w is not None and w["value"] == ssn and ssn in w["appearance"].get("drawn", []),
        "value stored and drawn",
    )
    _expect(p, ssn not in fx["page_text"], "not in the page text")
    return p


def intent_reject_overflow(fx: dict[str, Any]) -> Problems:
    p: Problems = []
    o = overflow_facts(fx)
    _expect(p, o is not None and o["clipped_text"] != "", "value overflows the field")
    return p


def intent_reject_differs(fx: dict[str, Any]) -> Problems:
    p: Problems = []
    (w,) = fx["widgets"] or [None]
    _expect(p, w is not None and w["value"] == by_name("full_name").value, "stored value")
    _expect(
        p, w is not None and w["appearance"].get("drawn") == [producers.DIFFERS_DRAWN], "drawn text"
    )
    return p


def overflow_facts(fx: dict[str, Any]) -> dict[str, Any] | None:
    """For a one-widget text field with a clipped appearance: the value's advance from its text
    origin in Helvetica at the appearance's size, the clip's right edge, and the value split at the
    last glyph whose advance ends inside the clip."""
    if len(fx["widgets"]) != 1:
        return None
    ap = fx["widgets"][0]["appearance"]
    if not ap.get("clip") or ap.get("size") is None or not ap.get("origin") or not ap.get("drawn"):
        return None
    text = ap["drawn"][0]
    size = float(ap["size"])
    x = float(ap["origin"][0])
    right = float(ap["clip"][0]) + float(ap["clip"][2])
    cut = 0
    for i, ch in enumerate(text):
        x += stringWidth(ch, "Helvetica", size)
        if x <= right:
            cut = i + 1
    return {
        "font": "Helvetica",
        "size_pt": size,
        "advance_pt": round(float(ap["origin"][0]) + stringWidth(text, "Helvetica", size), 3),
        "clip_right_pt": right,
        "visible_text": text[:cut],
        "clipped_text": text[cut:],
    }


# -------------------------------------------------------------------------------------- documents
Doc = tuple[str, str, str, Callable[[], bytes], Callable[[dict[str, Any]], Problems], str]

DOCS: list[Doc] = [
    (
        "ff-reportlab-all",
        "form",
        "reportlab",
        producers.reportlab_all,
        intent_reportlab_all,
        "every field kind but the signature, created and filled by reportlab: five text fields, two checkboxes (on, off), a radio group, a combo box, a list box and a multi-line field whose value overflows it",
    ),
    (
        "ff-pypdf-text-ap",
        "form",
        "pypdf",
        lambda: producers.pypdf_text(True),
        intent_text_ap,
        "the reportlab blank with its five text fields filled by pypdf, appearance streams written, no /NeedAppearances",
    ),
    (
        "ff-pypdf-text-needappearances",
        "form",
        "pypdf",
        lambda: producers.pypdf_text(False),
        intent_text_noap,
        "the same values with every text widget's appearance stream removed and /NeedAppearances true",
    ),
    (
        "ff-pypdf-buttons",
        "form",
        "pypdf",
        producers.pypdf_buttons,
        intent_buttons,
        "the reportlab blank with one checkbox on, one off and the radio group set by pypdf (/V and /AS)",
    ),
    (
        "ff-pymupdf-all",
        "form",
        "PyMuPDF",
        producers.pymupdf_all,
        intent_pymupdf_all,
        "every field kind but the signature, added and filled by PyMuPDF, which writes its own appearance streams",
    ),
    (
        "ff-pypdf-signature",
        "form",
        "pypdf",
        producers.pypdf_signature,
        intent_signature,
        "one unsigned signature field (/FT /Sig, no /V) whose appearance is a drawn stroke; no signing key, a visual mark only",
    ),
    (
        "ff-pypdf-hidden-noview",
        "form",
        "pypdf",
        producers.pypdf_hidden_noview,
        intent_hidden_noview,
        "five filled text fields; the SSN widget is flagged Hidden and the date-of-birth widget NoView",
    ),
    (
        "ff-pymupdf-annotation-beside",
        "form",
        "PyMuPDF",
        producers.pymupdf_annotation_beside,
        intent_annotation_beside,
        "five filled text widgets with a text note, a free-text box and a square annotation beside them",
    ),
    (
        "ff-pdfkit-filled",
        "form",
        "PDFKit",
        lambda: pdfkit.recorded("ff-pdfkit-filled"),
        intent_pdfkit_filled,
        "five text widgets and two checkboxes written by macOS PDFKit (which writes no catalog /AcroForm and names the fields itself)",
    ),
    (
        "ff-pdfkit-blackwidget-cover",
        "form",
        "PDFKit",
        lambda: pdfkit.recorded("ff-pdfkit-blackwidget-cover"),
        intent_pdfkit_cover,
        "the SSN printed as page text, with an empty black-background PDFKit text widget drawn over it",
    ),
    (
        "ff-control-no-widgets",
        "control",
        "reportlab",
        producers.control_no_widgets,
        intent_control,
        "the printed form with no fields and no annotations",
    ),
    (
        "ff-xfa-dynamic",
        "xfa",
        "pypdf",
        producers.xfa_dynamic,
        intent_xfa,
        "a dynamic XFA form: template and data packets in /AcroForm /XFA, /NeedsRendering, and the stand-in page other viewers show",
    ),
    (
        "ff-reject-hidden-value",
        "reject",
        "pypdf",
        producers.reject_hidden_value,
        intent_reject_hidden,
        "one text field flagged Hidden whose stored value and appearance hold the SSN, which the page does not print",
    ),
    (
        "ff-reject-overflow",
        "reject",
        "pypdf",
        producers.reject_overflow,
        intent_reject_overflow,
        "one single-line text field whose appearance draws a value longer than the field, clipped to its inner box",
    ),
    (
        "ff-reject-value-differs",
        "reject",
        "pypdf",
        producers.reject_value_differs,
        intent_reject_differs,
        "one text field whose stored value is one name and whose appearance draws another",
    ),
]


def producer_versions() -> dict[str, str]:
    return {
        "python": platform.python_version(),
        "reportlab": reportlab.Version,
        "pypdf": pypdf.__version__,
        "pymupdf": pymupdf.VersionBind,
    }


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def build_doc(doc: Doc, check_intent: bool = True) -> tuple[bytes, dict[str, Any]]:
    doc_id, kind, producer, make, intent, purpose = doc
    pdf = make()
    fx = facts.read(pdf)
    problems = intent(fx)
    if problems and check_intent:
        raise SystemExit(f"{doc_id}: the producer did not write what was asked: {problems}")
    exp: dict[str, Any] = {
        "schema": SCHEMA,
        "id": doc_id,
        "family": "filled-forms",
        "kind": kind,
        "purpose": purpose,
        "producer": producer,
        "facts": fx,
        "fields": grouped(fx),
        "visible": [visible(w) for w in fx["widgets"]],
        "draws": [draws(w) for w in fx["widgets"]],
    }
    if doc_id == "ff-reject-overflow":
        exp["overflow"] = overflow_facts(fx)
    if doc_id == "ff-reject-value-differs":
        w = fx["widgets"][0]
        exp["appearance_matches_value"] = w["appearance"].get("drawn") == [w["value"]]
    return pdf, exp


def build(out: Path, only: set[str] | None) -> list[dict[str, Any]]:
    (out / "documents").mkdir(parents=True, exist_ok=True)
    (out / "expected").mkdir(parents=True, exist_ok=True)
    rows = []
    vers = producer_versions()
    for doc in DOCS:
        if only is not None and doc[0] not in only:
            continue
        pdf, exp = build_doc(doc)
        exp_b = json_bytes(exp)
        (out / f"documents/{doc[0]}.pdf").write_bytes(pdf)
        (out / f"expected/{doc[0]}.expected.json").write_bytes(exp_b)
        prod = {"name": doc[2], "versions": vers}
        if doc[2] == "PDFKit":
            rec = pdfkit.recording_facts()
            prod["recorded"] = f"pdfkit/{doc[0]}.pdf"
            prod["macos"] = str(rec["macos"])
        rows.append(
            {
                "path": f"documents/{doc[0]}.pdf",
                "bytes": len(pdf),
                "sha256": sha256(pdf),
                "expected": f"expected/{doc[0]}.expected.json",
                "expected_sha256": sha256(exp_b),
                "family": "filled-forms",
                "kind": doc[1],
                "producer": prod,
                "purpose": doc[5],
                "stored": "committed",
            }
        )
        sys.stdout.write(f"{doc[0]}  {len(pdf) // 1024} KiB  {sha256(pdf)[:12]}\n")
    (out / "manifest.json").write_bytes(
        json_bytes({"schema": SCHEMA, "family": "filled-forms", "documents": rows})
    )
    sums = [f"{r['sha256']}  {r['path']}" for r in rows] + [
        f"{r['expected_sha256']}  {r['expected']}" for r in rows
    ]
    (out / "SHA256SUMS").write_text("\n".join(sums) + "\n", encoding="ascii")
    return rows


def publish(out: Path, dest: Path) -> None:
    for sub in ("documents", "expected"):
        if (dest / sub).exists():
            shutil.rmtree(dest / sub)
        shutil.copytree(out / sub, dest / sub)
    for name in ("manifest.json", "SHA256SUMS"):
        shutil.copyfile(out / name, dest / name)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=Path)
    ap.add_argument("--only", default="")
    ap.add_argument("--publish", action="store_true")
    ap.add_argument(
        "--record-pdfkit",
        action="store_true",
        help="macOS: run the PDFKit helper and store its outputs",
    )
    a = ap.parse_args()
    if a.record_pdfkit:
        for doc_id in pdfkit.record():
            sys.stdout.write(f"recorded pdfkit/{doc_id}.pdf\n")
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
