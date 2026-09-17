"""t23.py -- T2.3 fixture family (P1.7): rotation 180/270 + annotated packet + incremental update.

  packet-rotate-180 / -270   IM-08 rotation legs via the now degrees-aware rotate_trigger
                             (C12-72). MEASURE-only: F12-04 (rotated searchable defect) stays
                             parked; these emit correct display-space GT for the 180/270 cells.
  packet-annotated           IM-14 realism leg: FreeText / Stamp / Square+Popup annotations over
                             packet pages with text-bearing /AP form XObjects and /Contents
                             values carrying planted PII shapes. Three surface signatures:
                             ap_and_contents (FreeText) · ap only (Stamp) · contents only
                             (Square whose /Popup mirrors it). Whether Scan/extractors see any
                             of them is a MEASUREMENT, not a premise.
  packet-incremental         IM-23: a REAL /Prev-chained two-revision packet. Revision 1 carries
                             an uncompressed overlay line with a prior-revision plant on page 0;
                             revision 2 replaces that overlay object via a classic appended
                             update section (current view is plant-free, prior bytes remain).

All outputs are deterministic byte-for-byte across rebuilds (pinned metadata + /ID via
variants._finalize; the incremental tail is computed from the finalized revision-1 bytes).
`documents.manifest.json` is NOT touched (T1.4 byte-stable) -- the family is DOCS_ROOT-direct
with its own sidecar manifest `t23/t23-fixtures.json` (the robustness/ discipline) plus
the plants sidecar `t23/packet-t23-plants.json`.

Run: .venv/bin/python -m packet.t23
"""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from typing import cast

from . import build_packet as B
from . import variants as V

REPO = Path(__file__).resolve().parent.parent
OUTDIR = REPO / "t23"

# Planted values: fictional shapes (SSN in the reserved 987-65-43xx fake range; 555 phone;
# invented name). Uniqueness against the packet is asserted at build time.
FT_TERM = "987-65-4310"
FT_TEXT = f"Verified against file: SSN {FT_TERM}"
STAMP_TERM = "(208) 555-0163"
STAMP_AP_TEXT = f"CALLBACK {STAMP_TERM}"
POPUP_TERM = "Margery Hollowell"
POPUP_TEXT = f"Route to records clerk {POPUP_TERM} for indexing."
PREV_TERM = "987-65-4351"
PREV_LINE = f"Prior-revision reference SSN {PREV_TERM} (superseded)"
PREV_LINE_V2 = "Prior-revision reference [withdrawn in revision 2]"

T23_FONT = "/T23F"  # added to the touched pages' /Resources /Font


# --------------------------------------------------------------------------------------------------
# annotated packet (IM-14)
# --------------------------------------------------------------------------------------------------
def _helvetica(w):
    from pypdf.generic import DictionaryObject, NameObject

    font = DictionaryObject()
    font[NameObject("/Type")] = NameObject("/Font")
    font[NameObject("/Subtype")] = NameObject("/Type1")
    font[NameObject("/BaseFont")] = NameObject("/Helvetica")
    font[NameObject("/Encoding")] = NameObject("/WinAnsiEncoding")
    return w._add_object(font)


def _ap_form(w, font_ref, text: str, wpt: float, hpt: float, size: float = 9.0):
    """Uncompressed /AP normal-appearance form XObject drawing `text`."""
    from pypdf.generic import ArrayObject, DictionaryObject, FloatObject, NameObject, StreamObject

    content = f"BT {T23_FONT} {size} Tf 3 {hpt / 2 - size / 2 + 1:.1f} Td ({text}) Tj ET"
    ap = StreamObject()
    ap[NameObject("/Type")] = NameObject("/XObject")
    ap[NameObject("/Subtype")] = NameObject("/Form")
    ap[NameObject("/BBox")] = ArrayObject(
        [FloatObject(0), FloatObject(0), FloatObject(wpt), FloatObject(hpt)]
    )
    res = DictionaryObject()
    fnt = DictionaryObject()
    fnt[NameObject(T23_FONT)] = font_ref
    res[NameObject("/Font")] = fnt
    ap[NameObject("/Resources")] = res
    ap.set_data(content.encode("ascii"))
    return w._add_object(ap)


def _annot(
    w,
    page,
    subtype: str,
    rect,
    *,
    contents: str | None = None,
    ap_ref=None,
    name: str | None = None,
    parent_ref=None,
):
    from pypdf.generic import (
        ArrayObject,
        DictionaryObject,
        FloatObject,
        NameObject,
        NumberObject,
        TextStringObject,
    )

    a = DictionaryObject()
    a[NameObject("/Type")] = NameObject("/Annot")
    a[NameObject("/Subtype")] = NameObject(subtype)
    a[NameObject("/Rect")] = ArrayObject([FloatObject(v) for v in rect])
    a[NameObject("/F")] = NumberObject(4)
    if contents is not None:
        a[NameObject("/Contents")] = TextStringObject(contents)
    if ap_ref is not None:
        ap = DictionaryObject()
        ap[NameObject("/N")] = ap_ref
        a[NameObject("/AP")] = ap
    if name is not None:
        a[NameObject("/Name")] = NameObject(name)
    if subtype == "/FreeText":
        a[NameObject("/DA")] = TextStringObject(f"{T23_FONT} 9 Tf 0 g")
    if parent_ref is not None:
        a[NameObject("/Parent")] = parent_ref
    ref = w._add_object(a)
    if "/Annots" in page:
        page["/Annots"].append(ref)
    else:
        page[NameObject("/Annots")] = ArrayObject([ref])
    return ref


def annotated(packet_pdf: bytes):
    """FreeText(p0, value in /AP + /Contents) · Stamp(p2, value in /AP only) ·
    Square+Popup(p4, value in /Contents only). Rects live in the bottom-margin whitespace,
    covering no GT box."""
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import NameObject

    r = PdfReader(io.BytesIO(packet_pdf))
    w = PdfWriter(clone_from=r)
    font_ref = _helvetica(w)

    plants = []

    def nrect(rect, page_idx):
        x0, y0, x1, y1 = rect
        pw = float(w.pages[page_idx].mediabox.width)
        ph = float(w.pages[page_idx].mediabox.height)
        return [
            round(x0 / pw, 4),
            round(y0 / ph, 4),
            round((x1 - x0) / pw, 4),
            round((y1 - y0) / ph, 4),
        ]

    # p0 FreeText -- value drawn by /AP AND present in /Contents.
    rect = [320.0, 16.0, 566.0, 40.0]
    ap = _ap_form(w, font_ref, FT_TEXT, rect[2] - rect[0], rect[3] - rect[1])
    _annot(w, w.pages[0], "/FreeText", rect, contents=FT_TEXT, ap_ref=ap)
    plants.append(
        {
            "file": "packet-annotated.pdf",
            "page": 0,
            "subtype": "FreeText",
            "surface": "annotation_ap_and_contents",
            "term": FT_TERM,
            "shape": "ssn",
            "rect": nrect(rect, 0),
            "notes": "value drawn by the /AP normal appearance AND stored in /Contents",
        }
    )

    # p2 Stamp -- value ONLY in the /AP stream (contents benign).
    rect = [340.0, 16.0, 566.0, 44.0]
    ap = _ap_form(w, font_ref, STAMP_AP_TEXT, rect[2] - rect[0], rect[3] - rect[1], size=10.0)
    _annot(
        w, w.pages[2], "/Stamp", rect, contents="synthetic routing stamp", ap_ref=ap, name="/Draft"
    )
    plants.append(
        {
            "file": "packet-annotated.pdf",
            "page": 2,
            "subtype": "Stamp",
            "surface": "annotation_ap",
            "term": STAMP_TERM,
            "shape": "phone",
            "rect": nrect(rect, 2),
            "notes": "value only in the custom /AP appearance; /Contents is benign",
        }
    )

    # p4 Square + Popup -- value ONLY in the parent /Contents (popup text; no /AP).
    rect = [320.0, 16.0, 560.0, 42.0]
    parent = _annot(w, w.pages[4], "/Square", rect, contents=POPUP_TEXT)
    popup_rect = [420.0, 46.0, 560.0, 110.0]
    popup = _annot(w, w.pages[4], "/Popup", popup_rect, parent_ref=parent)
    pa = parent.get_object()
    pa[NameObject("/Popup")] = popup
    plants.append(
        {
            "file": "packet-annotated.pdf",
            "page": 4,
            "subtype": "Square+Popup",
            "surface": "annotation_contents",
            "term": POPUP_TERM,
            "shape": "name",
            "rect": nrect(rect, 4),
            "notes": "value only in the markup /Contents mirrored by its /Popup; no /AP",
        }
    )

    out = io.BytesIO()
    w.write(out)
    pdf = V._finalize(
        out.getvalue(),
        "Hartwell Packet -- annotated (IM-14, test-only)",
        b"ResectaPacketAnnotated1",
    )
    return pdf, plants


# --------------------------------------------------------------------------------------------------
# incremental update (IM-23) -- REAL /Prev chain over the packet
# --------------------------------------------------------------------------------------------------
def incremental(packet_pdf: bytes):
    """Revision 1 = packet + an uncompressed overlay content stream (plant line) on page 0;
    revision 2 = classic appended update section replacing that overlay object (plant removed).
    The prior revision's bytes remain in the file -- the [R01] §1.5 leak class."""
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import ArrayObject, DictionaryObject, NameObject, StreamObject

    r = PdfReader(io.BytesIO(packet_pdf))
    w = PdfWriter(clone_from=r)
    font_ref = _helvetica(w)

    page = w.pages[0]
    res = cast(DictionaryObject, page["/Resources"].get_object())
    fonts = cast(DictionaryObject, res["/Font"].get_object())
    fonts[NameObject(T23_FONT)] = font_ref

    overlay = StreamObject()
    overlay.set_data(f"BT {T23_FONT} 8 Tf 322 20 Td ({PREV_LINE}) Tj ET".encode("ascii"))
    overlay_ref = w._add_object(overlay)
    contents_raw = page.raw_get("/Contents")
    if isinstance(contents_raw.get_object(), ArrayObject):
        page[NameObject("/Contents")] = ArrayObject([*contents_raw.get_object(), overlay_ref])
    else:
        page[NameObject("/Contents")] = ArrayObject([contents_raw, overlay_ref])

    out = io.BytesIO()
    w.write(out)
    rev1 = V._finalize(
        out.getvalue(),
        "Hartwell Packet -- incremental (IM-23, test-only)",
        b"ResectaPacketIncremen1",
    )

    # Locate the overlay object + trailer facts in the FINALIZED revision-1 bytes.
    fr = PdfReader(io.BytesIO(rev1))
    cont = cast(ArrayObject, fr.pages[0]["/Contents"].get_object())
    assert isinstance(cont, ArrayObject) and len(cont) >= 2, "overlay array lost in finalize"
    overlay_num = cont[-1].idnum
    probe = cast(StreamObject, fr.get_object(cont[-1])).get_data()
    assert PREV_TERM.encode() in probe, "overlay stream is not the last /Contents element"

    trailer = fr.trailer
    size = int(cast(int, trailer["/Size"]))
    root_num = trailer.raw_get("/Root").idnum
    info_num = trailer.raw_get("/Info").idnum if "/Info" in trailer else None
    fid = cast(ArrayObject, trailer["/ID"])[0].original_bytes

    tail = rev1[rev1.rfind(b"startxref") :]
    rev1_xref_off = int(tail.split()[1])

    v2_stream = f"BT {T23_FONT} 8 Tf 322 20 Td ({PREV_LINE_V2}) Tj ET".encode("ascii")
    upd = b"\n"
    obj_off = len(rev1) + len(upd)
    upd += (
        b"%d 0 obj\n<< /Length %d >>\nstream\n" % (overlay_num, len(v2_stream))
        + v2_stream
        + b"\nendstream\nendobj\n"
    )
    xref2_off = len(rev1) + len(upd)
    fid_hex = fid.hex().upper().encode("ascii")
    trailer_bits = b"/Size %d /Root %d 0 R" % (size, root_num)
    if info_num is not None:
        trailer_bits += b" /Info %d 0 R" % info_num
    trailer_bits += b" /Prev %d /ID [<%s><%s>]" % (rev1_xref_off, fid_hex, fid_hex)
    upd += b"xref\n0 1\n0000000000 65535 f \n%d 1\n%010d 00000 n \n" % (
        overlay_num,
        obj_off,
    ) + b"trailer\n<< %s >>\nstartxref\n%d\n%%%%EOF\n" % (trailer_bits, xref2_off)
    return rev1 + upd


# --------------------------------------------------------------------------------------------------
def _sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _self_check(out: dict) -> None:
    import fitz
    from pypdf import PdfReader
    from pypdf.generic import ArrayObject

    base = out["_base_packet"]
    base_doc = fitz.open(stream=base, filetype="pdf")
    base_text = "".join(p.get_text() for p in base_doc)

    # rotations: /Rotate set everywhere; text unchanged; GT corners inside [0,1].
    for deg in (180, 270):
        pdf, vgt = out[f"rotate_{deg}"]
        pr = PdfReader(io.BytesIO(pdf))
        assert all(int(p.get("/Rotate", 0)) % 360 == deg for p in pr.pages), f"/Rotate {deg}"
        d = fitz.open(stream=pdf, filetype="pdf")
        assert "".join(p.get_text() for p in d) == base_text, f"text drift at {deg}"
        for rec in vgt["occurrences"]:
            x0, y0, x1, y1 = rec["bbox"]
            assert 0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1, f"degenerate bbox at {deg}"

    # annotated: annot census; terms in raw bytes; terms NOT in page text; unique vs the base.
    pdf, _plants = out["annotated"]
    d = fitz.open(stream=pdf, filetype="pdf")
    apr = PdfReader(io.BytesIO(pdf))
    subtypes = [str(a.get_object()["/Subtype"]) for pg in apr.pages for a in pg.get("/Annots", [])]
    for want in ("/FreeText", "/Stamp", "/Square", "/Popup"):
        assert want in subtypes, f"missing annot {want}: {subtypes}"
    mupdf_text = "".join(p.get_text() for p in d)
    pypdf_text = "".join(pg.extract_text() for pg in apr.pages)
    for t in (FT_TERM, STAMP_TERM, POPUP_TERM):
        assert t.encode("ascii") in pdf, f"term not in raw bytes: {t}"
        assert t not in pypdf_text, f"annotation term in the content-stream text: {t}"
        assert t not in base_text and t.encode("ascii") not in base, f"term collides: {t}"
    # Pinned extractor split (drift here = re-adjudicate): mupdf get_text SURFACES /AP-drawn
    # annotation text; the /Contents-only value stays invisible to both extractors.
    assert FT_TERM in mupdf_text and STAMP_TERM in mupdf_text, "mupdf /AP visibility changed"
    assert POPUP_TERM not in mupdf_text, "contents-only term surfaced"
    assert len(apr.pages) == len(base_doc)

    # incremental: current view plant-free; prior bytes present; both revisions parse.
    pdf = out["incremental"]
    assert pdf.count(b"%%EOF") == 2, "expected exactly two revisions"
    d = fitz.open(stream=pdf, filetype="pdf")
    cur = "".join(p.get_text() for p in d)
    assert PREV_TERM not in cur and "withdrawn in revision 2" in cur, "rev-2 view wrong"
    assert PREV_TERM.encode("ascii") in pdf, "prior-revision bytes missing"
    pr = PdfReader(io.BytesIO(pdf))
    assert len(pr.pages) == len(base_doc)
    last = cast(ArrayObject, pr.pages[0]["/Contents"].get_object())[-1]
    assert PREV_TERM.encode() not in last.get_data()


def build_t23(write: bool = True) -> dict:
    res = B.build(write=False)
    packet_pdf, gt = res["pdf"], res["ground_truth"]

    out: dict = {"_base_packet": packet_pdf}
    for deg in (180, 270):
        out[f"rotate_{deg}"] = V.rotate_trigger(packet_pdf, gt, deg)
    out["annotated"] = annotated(packet_pdf)
    out["incremental"] = incremental(packet_pdf)

    # determinism: full second build must be byte-identical.
    again = {f"rotate_{d}": V.rotate_trigger(packet_pdf, gt, d) for d in (180, 270)}
    again["annotated"] = annotated(packet_pdf)
    again["incremental"] = incremental(packet_pdf)
    for k in ("rotate_180", "rotate_270", "annotated"):
        assert out[k][0] == again[k][0], f"nondeterministic build: {k}"
    assert out["incremental"] == again["incremental"], "nondeterministic build: incremental"

    _self_check(out)

    if write:
        OUTDIR.mkdir(exist_ok=True)
        rows = []
        for deg in (180, 270):
            pdf, vgt = out[f"rotate_{deg}"]
            (OUTDIR / f"packet-rotate-{deg}.pdf").write_bytes(pdf)
            gt_name = f"packet-rotate-{deg}-ground-truth.json"
            (OUTDIR / gt_name).write_text(json.dumps(vgt, indent=2) + "\n", encoding="ascii")
            rows.append(
                {
                    "id": f"packet-rotate-{deg}",
                    "path": f"t23/packet-rotate-{deg}.pdf",
                    "pages": 12,
                    "gt": f"t23/{gt_name}",
                    "sha256": _sha256(pdf),
                    "notes": f"IM-08 /Rotate {deg} leg, degrees-aware display-space GT "
                    "(C12-72). Measures only -- F12-04 stays parked.",
                }
            )
        pdf, plants = out["annotated"]
        (OUTDIR / "packet-annotated.pdf").write_bytes(pdf)
        rows.append(
            {
                "id": "packet-annotated",
                "path": "t23/packet-annotated.pdf",
                "pages": 12,
                "gt": "t23/packet-t23-plants.json",
                "sha256": _sha256(pdf),
                "notes": "IM-14 annotation realism leg: FreeText(/AP+/Contents) - "
                "Stamp(/AP only) - Square+Popup(/Contents only).",
            }
        )
        inc = out["incremental"]
        (OUTDIR / "packet-incremental.pdf").write_bytes(inc)
        rows.append(
            {
                "id": "packet-incremental",
                "path": "t23/packet-incremental.pdf",
                "pages": 12,
                "gt": "t23/packet-t23-plants.json",
                "sha256": _sha256(inc),
                "notes": "IM-23 REAL /Prev two-revision packet: rev-1 overlay carries the "
                "plant, rev-2 replaces it; prior bytes remain ([R01] 1.5).",
            }
        )
        plants_all = [
            *plants,
            {
                "file": "packet-incremental.pdf",
                "page": 0,
                "subtype": None,
                "surface": "prior_revision",
                "term": PREV_TERM,
                "shape": "ssn",
                "rect": None,
                "notes": "rev-1 overlay line carries the term; the rev-2 current view is "
                "term-free. Original-byte scanning is the designed detector.",
            },
        ]
        (OUTDIR / "packet-t23-plants.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "generated_by": "packet.t23 (IM-14 / IM-23, P1.7)",
                    "coordinates": "rect = normalized bottom-left [x, y, w, h] (y-up); null = whole-file",
                    "plants": plants_all,
                },
                indent=2,
            )
            + "\n",
            encoding="ascii",
        )
        (OUTDIR / "t23-fixtures.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "generator": "packet/t23.py (T2.3, P1.7)",
                    "notes": "DOCS_ROOT-direct family (T1.4 manifest untouched); deterministic "
                    "byte-for-byte; plants sidecar = packet-t23-plants.json",
                    "fixtures": rows,
                },
                indent=2,
            )
            + "\n",
            encoding="ascii",
        )
    return out


def main() -> None:
    out = build_t23()
    for deg in (180, 270):
        print(f"rotate-{deg}:   {len(out[f'rotate_{deg}'][0]):,} bytes (+ transformed GT)")
    print(f"annotated:    {len(out['annotated'][0]):,} bytes ({len(out['annotated'][1])} plants)")
    print(f"incremental:  {len(out['incremental']):,} bytes (2 revisions, REAL /Prev)")
    print(f"-> {OUTDIR}")


if __name__ == "__main__":
    main()
