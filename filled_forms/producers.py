"""One function per document: each returns the document's bytes, written by a real PDF writer.

- reportlab draws the printed page in every document and creates the fields of the blank and the
  reportlab-filled forms (its ``acroForm``);
- pypdf fills the reportlab blank (with or without appearance streams), and adds the signature
  field, the flags and the reject documents' hand-made appearances;
- PyMuPDF adds and fills its own widgets on the printed page;
- macOS PDFKit writes its documents through ``pdfkit/gen_pdfkit.swift`` (see ``pdfkit.py``).
"""

from __future__ import annotations

import io
from collections.abc import Callable
from typing import Any

import pymupdf
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    ArrayObject,
    BooleanObject,
    DecodedStreamObject,
    DictionaryObject,
    FloatObject,
    NameObject,
    NumberObject,
    TextStringObject,
)
from reportlab.pdfgen import canvas

from hidden_layer import values as v

from . import form
from .form import FIELDS, PAGE, FieldSpec, by_name

ANNOT_PRINT = 4
ANNOT_HIDDEN = 2
ANNOT_NOVIEW = 32
OVERFLOW_VALUE = f"{v.EMAIL}; {v.EMAIL_2}; {v.PHONE}; {v.PHONE_2}; {v.PERSON['full']}"
DIFFERS_DRAWN = "Wren Castellano"


_MU: Any = pymupdf  # the widget constants are not in PyMuPDF's type stubs


def _root(w: PdfWriter) -> Any:
    return w._root_object


def _page(w: PdfWriter) -> Any:
    return w.pages[0]


# ------------------------------------------------------------------------------------- reportlab
def _rl_fields(c: canvas.Canvas, filled: bool, names: set[str] | None = None) -> None:
    af = c.acroForm
    for f in FIELDS:
        if names is not None and f.name not in names:
            continue
        x0, y0, x1, y1 = f.rect
        w, h = x1 - x0, y1 - y0
        common: dict[str, Any] = {
            "name": f.name,
            "x": x0,
            "y": y0,
            "borderWidth": 1,
            "forceBorder": True,
        }
        if f.kind == "text":
            af.textfield(
                value=f.value if filled else "",
                width=w,
                height=h,
                fontName="Helvetica",
                fontSize=11,
                **common,
            )
        elif f.kind == "multiline":
            af.textfield(
                value=f.value if filled else "",
                width=w,
                height=h,
                fontName="Helvetica",
                fontSize=11,
                fieldFlags="multiline",
                maxlen=1000,
                **common,
            )
        elif f.kind == "checkbox":
            af.checkbox(checked=filled and f.value == "on", size=w, **common)
        elif f.kind == "radio":
            for opt, r in f.radio_rects:
                af.radio(
                    value=opt,
                    selected=filled and opt == f.value,
                    size=r[2] - r[0],
                    name=f.name,
                    x=r[0],
                    y=r[1],
                    borderWidth=1,
                    forceBorder=True,
                )
        elif f.kind == "combo":
            af.choice(
                value=f.value if filled else f.options[0],
                options=list(f.options),
                width=w,
                height=h,
                fontName="Helvetica",
                fontSize=11,
                **common,
            )
        elif f.kind == "list":
            af.listbox(
                value=f.value if filled else f.options[0],
                options=list(f.options),
                width=w,
                height=h,
                fontName="Helvetica",
                fontSize=11,
                **common,
            )


def _with_page(
    add: Callable[[canvas.Canvas], None] | None, extra: form.PageText | None = None
) -> bytes:
    """The printed page (see ``form.printed_page``) with fields added on the same canvas."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=PAGE, invariant=1, pageCompression=0)
    c.setTitle(form.DOC_TITLE)
    c.setAuthor("resecta-sample-doc (synthetic)")
    c.setSubject("SYNTHETIC TEST DOCUMENT - FICTIONAL DATA")
    form.draw_page(c, extra)
    if add is not None:
        add(c)
    c.showPage()
    c.save()
    return buf.getvalue()


def control_no_widgets() -> bytes:
    return _with_page(None)


def reportlab_blank() -> bytes:
    return _with_page(lambda c: _rl_fields(c, filled=False))


def reportlab_all() -> bytes:
    return _with_page(lambda c: _rl_fields(c, filled=True))


# ------------------------------------------------------------------------------------------ pypdf
def _write(w: PdfWriter) -> bytes:
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def _widgets(w: PdfWriter) -> dict[str, list[DictionaryObject]]:
    out: dict[str, list[DictionaryObject]] = {}
    for ref in _page(w).get("/Annots", []):
        a = ref.get_object()
        if a.get("/Subtype") != "/Widget":
            continue
        name = a.get("/T") or a.get("/Parent", {}).get_object().get("/T")
        out.setdefault(str(name), []).append(a)
    return out


def _drop_need_appearances(w: PdfWriter) -> None:
    af = _root(w)["/AcroForm"]
    if "/NeedAppearances" in af:
        del af[NameObject("/NeedAppearances")]


def pypdf_text(with_ap: bool) -> bytes:
    """The reportlab blank with its five single-line text fields filled by pypdf."""
    w = PdfWriter(clone_from=PdfReader(io.BytesIO(reportlab_blank())))
    vals = {f.name: f.value for f in FIELDS if f.kind == "text" and f.value}
    w.update_page_form_field_values(_page(w), vals, auto_regenerate=False)
    _drop_need_appearances(w)
    if not with_ap:
        for name in vals:
            for a in _widgets(w)[name]:
                if "/AP" in a:
                    del a[NameObject("/AP")]
        _root(w)["/AcroForm"][NameObject("/NeedAppearances")] = BooleanObject(True)
    return _write(w)


def _on_state(a: DictionaryObject) -> str:
    ap: Any = a["/AP"].get_object()
    n = ap["/N"].get_object()
    return next(str(k) for k in n if k != "/Off")


def pypdf_buttons() -> bytes:
    """The reportlab blank with its checkboxes set (one on, one off) and one radio option chosen."""
    w = PdfWriter(clone_from=PdfReader(io.BytesIO(reportlab_blank())))
    ws = _widgets(w)
    for f in FIELDS:
        if f.kind == "checkbox":
            (a,) = ws[f.name]
            state = _on_state(a) if f.value == "on" else "/Off"
            a[NameObject("/V")] = NameObject(state)
            a[NameObject("/AS")] = NameObject(state)
        elif f.kind == "radio":
            parent: Any = ws[f.name][0]["/Parent"].get_object()
            for a in ws[f.name]:
                on = _on_state(a)
                a[NameObject("/AS")] = NameObject(on if on == f"/{f.value}" else "/Off")
            parent[NameObject("/V")] = NameObject(f"/{f.value}")
    _drop_need_appearances(w)
    return _write(w)


def _form_xobject(w: PdfWriter, bbox: tuple[float, float], content: str, helv: bool = True) -> Any:
    s = DecodedStreamObject()
    s.set_data(content.encode("latin-1"))
    s[NameObject("/Type")] = NameObject("/XObject")
    s[NameObject("/Subtype")] = NameObject("/Form")
    s[NameObject("/BBox")] = ArrayObject(
        [FloatObject(0), FloatObject(0), FloatObject(bbox[0]), FloatObject(bbox[1])]
    )
    if helv:
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
                NameObject("/Encoding"): NameObject("/WinAnsiEncoding"),
            }
        )
        s[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/Helv"): w._add_object(font)})}
        )
    return w._add_object(s)


def _pdf_str(s: str) -> str:
    return "(" + s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") + ")"


def text_ap(text: str, w: float, h: float, size: float = 11, clip: bool = True) -> str:
    """A text-field appearance: optional clip to the inner box, then one line of Helvetica."""
    body = ["/Tx BMC q"]
    if clip:
        body.append(f"1 1 {w - 2:g} {h - 2:g} re W n")
    body += [
        "BT",
        f"/Helv {size:g} Tf 0 g",
        f"2 {(h - size) / 2 + 2:g} Td",
        f"{_pdf_str(text)} Tj",
        "ET Q EMC",
    ]
    return "\n".join(body) + "\n"


def _add_widget(
    w: PdfWriter, spec_rect: tuple[float, float, float, float], entries: dict[str, Any]
) -> DictionaryObject:
    page = _page(w)
    a = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Annot"),
            NameObject("/Subtype"): NameObject("/Widget"),
            NameObject("/Rect"): ArrayObject([FloatObject(x) for x in spec_rect]),
            NameObject("/P"): page.indirect_reference,
            **{NameObject(k): val for k, val in entries.items()},
        }
    )
    ref = w._add_object(a)
    if "/Annots" not in page:
        page[NameObject("/Annots")] = ArrayObject()
    page["/Annots"].append(ref)
    root = _root(w)
    if "/AcroForm" not in root:
        root[NameObject("/AcroForm")] = DictionaryObject({NameObject("/Fields"): ArrayObject()})
    root["/AcroForm"]["/Fields"].append(ref)
    return a


SIGNATURE_STROKE = (
    "0 0 0.35 RG 1.2 w 6 10 m 30 34 54 2 78 22 c 96 38 118 4 140 20 c 158 30 176 12 192 18 c S\n"
)


def pypdf_signature() -> bytes:
    """The printed page with one unsigned signature field (``/FT /Sig``, no ``/V``) whose appearance
    is a drawn stroke, a visual mark only."""
    w = PdfWriter(clone_from=PdfReader(io.BytesIO(control_no_widgets())))
    f = by_name("signature")
    x0, y0, x1, y1 = f.rect
    ap = _form_xobject(w, (x1 - x0, y1 - y0), SIGNATURE_STROKE, helv=False)
    _add_widget(
        w,
        f.rect,
        {
            "/FT": NameObject("/Sig"),
            "/T": TextStringObject(f.name),
            "/F": NumberObject(ANNOT_PRINT),
            "/AP": DictionaryObject({NameObject("/N"): ap}),
        },
    )
    return _write(w)


def _text_field_doc(entries: list[tuple[FieldSpec, str, str, int]], need_da: bool = True) -> bytes:
    """The printed page with hand-made text fields: (spec, stored value, drawn text, annotation flags)."""
    w = PdfWriter(clone_from=PdfReader(io.BytesIO(control_no_widgets())))
    for spec, stored, drawn, flags in entries:
        x0, y0, x1, y1 = spec.rect
        ap = _form_xobject(w, (x1 - x0, y1 - y0), text_ap(drawn, x1 - x0, y1 - y0))
        d: dict[str, Any] = {
            "/FT": NameObject("/Tx"),
            "/T": TextStringObject(spec.name),
            "/V": TextStringObject(stored),
            "/F": NumberObject(flags),
            "/AP": DictionaryObject({NameObject("/N"): ap}),
        }
        if need_da:
            d["/DA"] = TextStringObject("/Helv 11 Tf 0 g")
        _add_widget(w, spec.rect, d)
    _root(w)["/AcroForm"][NameObject("/DA")] = TextStringObject("/Helv 11 Tf 0 g")
    return _write(w)


def pypdf_hidden_noview() -> bytes:
    """Five filled text fields; the SSN's widget is flagged Hidden and the date of birth's NoView."""
    rows = []
    for f in FIELDS:
        if f.kind != "text" or not f.value:
            continue
        flags = ANNOT_PRINT
        if f.name == "ssn":
            flags = ANNOT_HIDDEN | ANNOT_PRINT
        elif f.name == "dob":
            flags = ANNOT_NOVIEW | ANNOT_PRINT
        rows.append((f, f.value, f.value, flags))
    return _text_field_doc(rows)


def reject_hidden_value() -> bytes:
    """One text field, flagged Hidden, whose stored value and appearance both hold the SSN."""
    f = by_name("ssn")
    return _text_field_doc([(f, f.value or "", f.value or "", ANNOT_HIDDEN | ANNOT_PRINT)])


def reject_overflow() -> bytes:
    """One single-line text field whose value is longer than the field; the appearance draws the
    whole value and clips it to the field's inner box."""
    f = by_name("email")
    return _text_field_doc([(f, OVERFLOW_VALUE, OVERFLOW_VALUE, ANNOT_PRINT)])


def reject_value_differs() -> bytes:
    """One text field whose stored value is one name and whose appearance draws another."""
    f = by_name("full_name")
    return _text_field_doc([(f, f.value or "", DIFFERS_DRAWN, ANNOT_PRINT)])


# ---------------------------------------------------------------------------------------- PyMuPDF
def _mu_rect(r: tuple[float, float, float, float]) -> pymupdf.Rect:
    return pymupdf.Rect(r[0], PAGE[1] - r[3], r[2], PAGE[1] - r[1])


def _mu_add(page: Any, f: FieldSpec) -> None:
    kinds = {
        "text": _MU.PDF_WIDGET_TYPE_TEXT,
        "multiline": _MU.PDF_WIDGET_TYPE_TEXT,
        "checkbox": _MU.PDF_WIDGET_TYPE_CHECKBOX,
        "combo": _MU.PDF_WIDGET_TYPE_COMBOBOX,
        "list": _MU.PDF_WIDGET_TYPE_LISTBOX,
    }
    if f.kind == "radio":
        # PyMuPDF refuses a radio button added already selected; add all off, then select one.
        for _, r in f.radio_rects:
            wd = pymupdf.Widget()
            wd.field_type = _MU.PDF_WIDGET_TYPE_RADIOBUTTON
            wd.field_name = f.name
            wd.rect = _mu_rect(r)
            wd.field_value = False
            page.add_widget(wd)
        mine = [w for w in page.widgets() if w.field_name == f.name]
        pick = [opt for opt, _ in f.radio_rects].index(f.value or "")
        mine[pick].field_value = True
        mine[pick].update()
        return
    wd = pymupdf.Widget()
    wd.field_type = kinds[f.kind]
    wd.field_name = f.name
    wd.rect = _mu_rect(f.rect)
    wd.text_font = "Helv"
    wd.text_fontsize = 11
    if f.kind == "multiline":
        wd.field_flags = _MU.PDF_TX_FIELD_IS_MULTILINE
    if f.kind in ("combo", "list"):
        wd.choice_values = list(f.options)
    if f.kind == "checkbox":
        wd.field_value = f.value == "on"
    else:
        wd.field_value = f.value or ""
    page.add_widget(wd)


def _mu_save(doc: Any) -> bytes:
    return bytes(doc.tobytes(garbage=0, deflate=False, no_new_id=True))


def pymupdf_all() -> bytes:
    """The printed page with every field kind but the signature added and filled by PyMuPDF."""
    doc = pymupdf.open(stream=control_no_widgets(), filetype="pdf")
    page = doc[0]
    for f in FIELDS:
        if f.kind != "signature":
            _mu_add(page, f)
    out = _mu_save(doc)
    doc.close()
    return out


def pymupdf_annotation_beside() -> bytes:
    """Filled text widgets (PyMuPDF), with three non-widget annotations beside them: a text note,
    a free-text box and a square."""
    doc = pymupdf.open(stream=control_no_widgets(), filetype="pdf")
    page = doc[0]
    for f in FIELDS:
        if f.kind == "text":
            _mu_add(page, f)
    ssn = by_name("ssn").rect
    note = page.add_text_annot(
        pymupdf.Point(ssn[2] + 40, PAGE[1] - ssn[3]), f"Checked against file {v.CASE_NO}."
    )
    note.set_info(title="Records Office", subject="Note")
    note.update()
    dob = by_name("dob").rect
    box = pymupdf.Rect(dob[2] + 20, PAGE[1] - dob[3] - 4, dob[2] + 200, PAGE[1] - dob[1] + 4)
    ft = page.add_freetext_annot(box, f"Call {v.PHONE_2} first.", fontsize=10, fontname="helv")
    ft.update()
    sq = page.add_rect_annot(pymupdf.Rect(LABEL_BOX))
    sq.update()
    out = _mu_save(doc)
    doc.close()
    return out


LABEL_BOX = (66, PAGE[1] - 704, 200, PAGE[1] - 680)


# -------------------------------------------------------------------------------------------- XFA
XFA_STAND_IN = (
    "This document is a dynamic XFA form.",
    "A viewer that does not read XFA shows only this page.",
    "The form's fields and values are in the XFA packets of the file.",
)


def _xfa_packets() -> list[tuple[str, str]]:
    name, phone, ssn = v.PERSON["full"], v.PHONE, v.SSN
    template = """<template xmlns="http://www.xfa.org/schema/xfa-template/3.3/">
<subform name="intake" layout="tb" locale="en_US">
<pageSet><pageArea name="page1"><contentArea x="0.5in" y="0.5in" w="7.5in" h="10in"/><medium stock="letter" short="8.5in" long="11in"/></pageArea></pageSet>
<subform name="person" layout="tb" w="7.5in">
<field name="full_name" w="4in" h="0.3in"><ui><textEdit/></ui><caption><value><text>Full name</text></value></caption></field>
<field name="phone" w="4in" h="0.3in"><ui><textEdit/></ui><caption><value><text>Telephone</text></value></caption></field>
<field name="ssn" w="3in" h="0.3in"><ui><textEdit/></ui><caption><value><text>SSN</text></value></caption></field>
</subform>
<subform name="visits" layout="tb" w="7.5in"><occur min="1" max="-1" initial="2"/>
<field name="visit_date" w="2in" h="0.3in"><ui><dateTimeEdit/></ui></field>
</subform>
</subform>
</template>"""
    datasets = f"""<xfa:datasets xmlns:xfa="http://www.xfa.org/schema/xfa-data/1.0/">
<xfa:data><intake><person><full_name>{name}</full_name><phone>{phone}</phone><ssn>{ssn}</ssn></person>
<visits><visit_date>2026-10-30</visit_date></visits><visits><visit_date>2026-11-02</visit_date></visits></intake></xfa:data>
</xfa:datasets>"""
    return [
        ("preamble", '<xdp:xdp xmlns:xdp="http://ns.adobe.com/xdp/">'),
        ("template", template),
        ("datasets", datasets),
        ("postamble", "</xdp:xdp>"),
    ]


def xfa_dynamic() -> bytes:
    """A stand-in page (what a viewer without XFA shows) and an ``/AcroForm`` whose ``/XFA`` array
    holds the template and data packets; the catalog sets ``/NeedsRendering``."""
    extra = form.PageText([(form.LABEL_X, 640 - 18 * i, s) for i, s in enumerate(XFA_STAND_IN)])
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=PAGE, invariant=1, pageCompression=0)
    c.setTitle(form.DOC_TITLE)
    c.setAuthor("resecta-sample-doc (synthetic)")
    c.setSubject("SYNTHETIC TEST DOCUMENT - FICTIONAL DATA")
    c.setFont("Helvetica-Bold", 14)
    c.drawString(form.LABEL_X, 740, form.TITLE)
    c.setFont("Helvetica", 12)
    for x, y, s in extra.items:
        c.drawString(x, y, s)
    c.showPage()
    c.save()
    w = PdfWriter(clone_from=PdfReader(io.BytesIO(buf.getvalue())))
    arr = ArrayObject()
    for name, xml in _xfa_packets():
        packet = DecodedStreamObject()
        packet.set_data(xml.encode("utf-8"))
        arr.append(TextStringObject(name))
        arr.append(w._add_object(packet))
    _root(w)[NameObject("/AcroForm")] = DictionaryObject(
        {NameObject("/Fields"): ArrayObject(), NameObject("/XFA"): arr}
    )
    _root(w)[NameObject("/NeedsRendering")] = BooleanObject(True)
    return _write(w)
