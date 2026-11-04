"""build_planted_corpus.py -- T2.2: the planted-leak corpus v0 (oracle-recall calibration set).

One synthetic fixture per oracle-visible surface (registers/31- SSB row 3; 10- SS2 + SS9 fold 2),
each carrying exactly ONE unique planted term (`PLANT-<SURFACE>-<nn>`), plus a small CLEAN
control set. The corpus calibrates `tools/verify_oracle.py` (H2.3): every plant is a KNOWN leak
the oracle must FIND (no redaction pass); every clean doc must produce zero leak-class hits.

Surfaces (v0): visible text control | hidden text x4 (white-on-white, `3 Tr`, opaque painted box,
OCG /OFF) | hex-string text operand | Flate-compressed content stream | PDF-1.5 object stream
(ObjStm + xref stream) | inline image (BI/ID/EI, ASCIIHex) | annotation /AP | annotation
/Contents | XMP /Metadata | /Info | EXIF (ImageDescription) | AcroForm /V | /Outlines bookmark |
/Thumb pixels | REAL /Prev-linked prior revision | embedded file | /JavaScript.
Extended surfaces: invisible (`3 Tr`) text layer over a full-page raster | text in a nested
form XObject (depth 2) | FlateDecode XMP /Metadata | ToUnicode remap (drawn glyphs differ from
the extracted text) | Type 3 font with a ToUnicode map | Widget /AP without a catalog /AcroForm |
unreferenced FlateDecode object (free in the single xref, one %%EOF); plus one clean control
carrying those structural shapes with benign text.
Text-as-outlines is a STRETCH row -- emitted only if the mutool vectorize probe verifies
(otherwise recorded as skipped in the manifest notes).

Determinism: hand-rolled PDF bytes (no library metadata stamps, no dates anywhere); zlib level
pinned; raster plants (inline image / thumb / JPEG) drawn with the repo's pinned Inter font via
PIL and hash-recorded in the manifest (PIL/libjpeg encoding is version-stable, not spec-stable).

Manifest: `planted/planted-leaks.json` -- rows mirror the documents.manifest.json spirit
(fixture id, path, sha256, provenance) plus the 31- SSB row-3 trio (surface, term,
expect_visible_in_output) and `expected_legs` (which O-legs SHOULD find the plant; the
calibration grades found-by-any and found-by-expected separately).

Usage:  .venv/bin/python tools/build_planted_corpus.py   (from the sample-doc root)
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import zlib
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
OUTDIR = REPO / "planted"
CLEANDIR = OUTDIR / "clean"
FONT_PATH = REPO / "fonts" / "Inter-Regular.ttf"

PW, PH = 612, 792
HEADER = b"%\xe2\xe3\xcf\xd3\n"
HELV = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"


# ---------------------------------------------------------------- raw writer


def build_pdf(
    objects: list[tuple[int, bytes]], root: int, info: int | None = None, version: bytes = b"1.4"
) -> bytes:
    """Classic single-xref writer (the RawPDFBuilder.buildRawPDF shape, in Python)."""
    body = b"%PDF-" + version + b"\n" + HEADER
    offsets: dict[int, int] = {}
    for oid, content in objects:
        offsets[oid] = len(body)
        body += b"%d 0 obj\n" % oid + content + b"\nendobj\n\n"
    xref_off = len(body)
    max_id = max(oid for oid, _ in objects)
    xref = b"xref\n0 %d\n" % (max_id + 1)
    xref += b"0000000000 65535 f \n"
    for oid in range(1, max_id + 1):
        xref += (b"%010d 00000 n \n" % offsets[oid]) if oid in offsets else b"0000000000 00000 f \n"
    info_entry = b" /Info %d 0 R" % info if info else b""
    trailer = (
        b"trailer\n<< /Size %d /Root %d 0 R" % (max_id + 1, root)
        + info_entry
        + b" >>\nstartxref\n%d\n%%%%EOF" % xref_off
    )
    return body + xref + trailer


def stream_obj(dict_body: bytes, data: bytes) -> bytes:
    d = b"<< " + dict_body + b" /Length %d >>" % len(data)
    return d + b"\nstream\n" + data + b"\nendstream"


def esc(s: str) -> bytes:
    return s.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)").encode("latin-1")


def text_op(x: int, y: int, size: int, s: str, pre: bytes = b"") -> bytes:
    return b"BT " + pre + b"/F1 %d Tf %d %d Td (" % (size, x, y) + esc(s) + b") Tj ET\n"


def page_pdf(
    content: bytes,
    *,
    extra_page: bytes = b"",
    extra_objects: list[tuple[int, bytes]] | None = None,
    catalog_extra: bytes = b"",
    resources: bytes = b"/Font << /F1 5 0 R >>",
    info: int | None = None,
    version: bytes = b"1.4",
    content_dict: bytes = b"",
) -> bytes:
    """1-page skeleton: 1 catalog / 2 pages / 3 page / 4 contents / 5 Helvetica (+extras)."""
    objs = [
        (1, b"<< /Type /Catalog /Pages 2 0 R" + catalog_extra + b" >>"),
        (2, b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>"),
        (
            3,
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] /Contents 4 0 R "
            b"/Resources << " % (PW, PH) + resources + b" >>" + extra_page + b" >>",
        ),
        (4, stream_obj(content_dict, content)),
        (5, HELV),
    ]
    if extra_objects:
        objs += extra_objects
    return build_pdf(objs, root=1, info=info, version=version)


def nrect(x: float, y: float, w: float, h: float) -> list[float]:
    """points (bottom-left) -> normalized [x, y, w, h]."""
    return [round(x / PW, 4), round(y / PH, 4), round(w / PW, 4), round(h / PH, 4)]


def anchor(label: str) -> bytes:
    return text_op(72, 730, 14, f"Synthetic planted-leak fixture -- {label}") + text_op(
        72, 706, 10, "Fictional content; no real PII. Oracle-calibration corpus (T2.2)."
    )


# ---------------------------------------------------------------- raster helpers


def render_term_image(term: str, w: int, h: int, px: int):
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("L", (w, h), 255)
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype(str(FONT_PATH), px)
    d.text((12, (h - px) // 2 - 2), term, fill=0, font=font)
    return img


def ahx(data: bytes) -> bytes:
    out = data.hex().upper().encode()
    return b"\n".join(out[i : i + 64] for i in range(0, len(out), 64)) + b">"


def exif_app1(description: str) -> bytes:
    """Minimal EXIF APP1: TIFF II with IFD0 {ImageDescription}."""
    desc = description.encode("ascii") + b"\x00"
    # IFD0 at offset 8: count=1, one 12-byte entry, next=0 -> value area at 8+2+12+4=26
    entry = (
        b"\x0e\x01"  # tag 0x010E ImageDescription
        b"\x02\x00" + len(desc).to_bytes(4, "little") + (26).to_bytes(4, "little")  # type ASCII
    )
    tiff = (
        b"II*\x00"
        + (8).to_bytes(4, "little")
        + (1).to_bytes(2, "little")
        + entry
        + (0).to_bytes(4, "little")
        + desc
    )
    payload = b"Exif\x00\x00" + tiff
    return b"\xff\xe1" + (len(payload) + 2).to_bytes(2, "big") + payload


def jpeg_with_exif(term: str, w: int = 400, h: int = 300, benign_text: str = "") -> bytes:
    """Deterministic-enough JPEG (hash-recorded): PIL encode, then hand-splice APP1 after SOI."""
    import io

    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("L", (w, h), 235)
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype(str(FONT_PATH), 28)
    d.text((20, h // 2 - 14), benign_text or "SYNTHETIC PHOTO PAGE", fill=40, font=font)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    raw = buf.getvalue()
    if raw[:2] != b"\xff\xd8":
        raise AssertionError("JPEG SOI marker missing")
    return raw[:2] + (exif_app1(term) if term else b"") + raw[2:]


# ---------------------------------------------------------------- fixtures

ROWS: list[dict] = []
SKIPPED: list[dict] = []


def emit(
    fixture: str, pdf: bytes, plants: list[dict], *, clean: bool = False, notes: str = ""
) -> None:
    outdir = CLEANDIR if clean else OUTDIR
    path = outdir / f"{fixture}.pdf"
    path.write_bytes(pdf)
    row = {
        "fixture": fixture,
        "path": str(path.relative_to(REPO)),
        "sha256": hashlib.sha256(pdf).hexdigest(),
        "clean": clean,
        "plants": plants,
        "notes": notes,
        "provenance": {"generator": "tools/build_planted_corpus.py", "seed": None},
    }
    ROWS.append(row)
    print(f"  {fixture}: {len(pdf):,} B, {len(plants)} plant(s)")


def plant(
    surface: str,
    term: str,
    expected_legs: list[str],
    *,
    hidden_class: str | None = None,
    expect_visible_in_output: bool,
    page: int = 0,
    bbox: list[float] | None = None,
    notes: str = "",
) -> dict:
    return {
        "surface": surface,
        "term": term,
        "hidden_class": hidden_class,
        "expect_visible_in_output": expect_visible_in_output,
        "expected_legs": expected_legs,
        "page": page,
        "bbox": bbox,
        "notes": notes,
    }


def fx_visible() -> None:
    t = "PLANT-VISIBLE-01"
    c = anchor("visible text control") + text_op(72, 400, 18, f"Reference value: {t}")
    emit(
        "planted-visible",
        page_pdf(c),
        [
            plant(
                "visible_text",
                t,
                ["o1"],
                expect_visible_in_output=True,
                bbox=nrect(72, 396, 300, 22),
            )
        ],
        notes="control row: the term is plainly visible born-digital text",
    )


def fx_wow() -> None:
    t = "PLANT-WOW-01"
    c = anchor("white-on-white hidden text") + b"1 g\n" + text_op(72, 400, 18, t) + b"0 g\n"
    emit(
        "planted-hidden-wow",
        page_pdf(c),
        [
            plant(
                "hidden_text",
                t,
                ["o1"],
                hidden_class="white_on_white",
                expect_visible_in_output=False,
                bbox=nrect(72, 396, 190, 22),
                notes="1 g fill -- white glyphs on the white page",
            )
        ],
        notes="extractors see white text; the eye does not",
    )


def fx_tr3() -> None:
    t = "PLANT-TRTHREE-01"
    c = anchor("render-mode-3 hidden text") + text_op(72, 400, 18, t, pre=b"3 Tr ")
    emit(
        "planted-hidden-tr3",
        page_pdf(c),
        [
            plant(
                "hidden_text",
                t,
                ["o1"],
                hidden_class="tr3_invisible",
                expect_visible_in_output=False,
                bbox=nrect(72, 396, 210, 22),
                notes="3 Tr text rendering mode (invisible)",
            )
        ],
        notes="rawdict char flags should label the run invisible",
    )


def fx_box() -> None:
    t = "PLANT-BOX-01"
    c = (
        anchor("opaque painted box over text")
        + text_op(72, 400, 18, t)
        + b"0 g 66 392 220 30 re f\n"
    )
    emit(
        "planted-hidden-box",
        page_pdf(c),
        [
            plant(
                "hidden_text",
                t,
                ["o1"],
                hidden_class="opaque_box",
                expect_visible_in_output=False,
                bbox=nrect(72, 396, 190, 22),
                notes="content-stream `re f` painted AFTER the glyphs (the [R01] SS1.1 construct)",
            )
        ],
        notes="text under a painted rect, NOT an annotation cover",
    )


def fx_ocg() -> None:
    t = "PLANT-OCGOFF-01"
    c = anchor("OCG /OFF hidden layer") + b"/OC /OC1 BDC\n" + text_op(72, 400, 18, t) + b"EMC\n"
    pdf = page_pdf(
        c,
        catalog_extra=b" /OCProperties << /OCGs [6 0 R] /D << /OFF [6 0 R] >> >>",
        resources=b"/Font << /F1 5 0 R >> /Properties << /OC1 6 0 R >>",
        extra_objects=[(6, b"<< /Type /OCG /Name (Hidden Layer) >>")],
    )
    emit(
        "planted-hidden-ocg",
        pdf,
        [
            plant(
                "hidden_text",
                t,
                ["o2", "structure"],
                hidden_class="ocg_off",
                expect_visible_in_output=False,
                bbox=nrect(72, 396, 200, 22),
                notes="optional-content group default /OFF; /OCProperties is itself a census key. "
                "MEASURED at build: ALL THREE O1 extractors (pdftotext, mutool stext, "
                "pymupdf rawdict) respect /OFF and skip this text -- the byte leg is the "
                "oracle's detector, while PDFKit-class page.string (the PRODUCT extractor) "
                "reads /OFF layers",
            )
        ],
        notes="O1-blind by renderer policy; O2 + /OCProperties census carry the surface",
    )


def fx_hex() -> None:
    t = "PLANT-HEXSTR-01"
    hexs = t.encode("latin-1").hex().upper().encode()
    c = anchor("hex-string text operand") + b"BT /F1 18 Tf 72 400 Td <" + hexs + b"> Tj ET\n"
    emit(
        "planted-hex-string",
        page_pdf(c),
        [
            plant(
                "hex_string",
                t,
                ["o1", "o2"],
                expect_visible_in_output=True,
                bbox=nrect(72, 396, 200, 22),
                notes="term appears only as a hex string operand in the raw bytes",
            )
        ],
        notes="visible when rendered; raw bytes carry hex, not the literal",
    )


def fx_flate() -> None:
    t = "PLANT-FLATE-01"
    inner = anchor("Flate-compressed content stream") + text_op(
        72, 400, 18, f"Compressed value: {t}"
    )
    emit(
        "planted-flate-content",
        page_pdf(zlib.compress(inner, 9), content_dict=b"/Filter /FlateDecode"),
        [
            plant(
                "flate_stream",
                t,
                ["o1", "o2"],
                expect_visible_in_output=True,
                bbox=nrect(72, 396, 330, 22),
                notes="page content stream is FlateDecode; the literal term is absent from the raw bytes",
            )
        ],
        notes="tests the decompression legs; extractors inflate transparently",
    )


def fx_objstm() -> None:
    """PDF-1.5 object stream: /Info lives INSIDE a Flate ObjStm; xref is a stream."""
    t = "PLANT-OBJSTM-01"
    content = anchor("object-stream (ObjStm) fixture") + text_op(
        72, 400, 12, "The document Info dictionary is packed in a compressed object stream."
    )
    objs: list[tuple[int, bytes]] = [
        (1, b"<< /Type /Catalog /Pages 2 0 R >>"),
        (2, b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>"),
        (
            3,
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R >> >> >>",
        ),
        (4, stream_obj(b"", content)),
        (5, HELV),
    ]
    info_body = b"<< /Title (Synthetic ObjStm fixture) /Subject (" + esc(t) + b") >>"
    objstm_payload = b"7 0\n" + info_body
    first = len(b"7 0\n")
    objstm_data = zlib.compress(objstm_payload, 9)
    objs.append(
        (6, stream_obj(b"/Type /ObjStm /N 1 /First %d /Filter /FlateDecode" % first, objstm_data))
    )

    body = b"%PDF-1.5\n" + HEADER
    offsets: dict[int, int] = {}
    for oid, c in objs:
        offsets[oid] = len(body)
        body += b"%d 0 obj\n" % oid + c + b"\nendobj\n\n"
    xref_off = len(body)
    # XRef stream obj 8: entries 0..8 -- W [1 4 2]; obj 7 is type-2 (in stream 6, index 0).
    rows = [(0, 0, 65535)]
    for oid in (1, 2, 3, 4, 5, 6):
        rows.append((1, offsets[oid], 0))
    rows.append((2, 6, 0))  # obj 7
    rows.append((1, xref_off, 0))  # obj 8 (the xref stream itself)
    data = b"".join(
        bytes([tp]) + off.to_bytes(4, "big") + g.to_bytes(2, "big") for tp, off, g in rows
    )
    xref_dict = (
        b"/Type /XRef /Size 9 /W [1 4 2] /Index [0 9] /Root 1 0 R /Info 7 0 R"
        b" /Length %d" % len(data)
    )
    body += b"8 0 obj\n<< " + xref_dict + b" >>\nstream\n" + data + b"\nendstream\nendobj\n\n"
    body += b"startxref\n%d\n%%%%EOF" % xref_off
    emit(
        "planted-objstm",
        body,
        [
            plant(
                "object_stream",
                t,
                ["o2", "structure"],
                expect_visible_in_output=False,
                notes="/Info /Subject packed inside a FlateDecode ObjStm behind an xref stream; "
                "raw bytes carry neither the literal nor a hex form",
            )
        ],
        notes="the qpdf --object-streams=disable QDF leg is the designed detector",
    )


def fx_inline_image() -> None:
    t = "PLANT-INLINEIMG-01"
    img = render_term_image(t, 600, 100, 44)
    c = (
        anchor("inline image (BI/ID/EI)")
        + b"q 450 0 0 75 81 380 cm\nBI /W 600 /H 100 /CS /G /BPC 8 /F /AHx ID\n"
        + ahx(img.tobytes())
        + b"\nEI\nQ\n"
    )
    emit(
        "planted-inline-image",
        page_pdf(c),
        [
            plant(
                "inline_image",
                t,
                ["o3"],
                expect_visible_in_output=True,
                bbox=nrect(81, 380, 450, 75),
                notes="term exists only as rendered pixels inside a BI/ID/EI inline image "
                "(ASCIIHex); pdfimages does not list inline images ([R04])",
            )
        ],
        notes="OCR is the only text-shaped recovery path",
    )


def fx_annot_ap() -> None:
    t = "PLANT-ANNOTAP-01"
    ap = b"BT /F1 16 Tf 6 12 Td (" + esc(t) + b") Tj ET"
    pdf = page_pdf(
        anchor("annotation appearance stream"),
        extra_page=b" /Annots [6 0 R]",
        extra_objects=[
            (
                6,
                b"<< /Type /Annot /Subtype /FreeText /Rect [72 380 372 416] "
                b"/Contents (synthetic note) /DA (/F1 16 Tf 0 g) /F 4 /AP << /N 7 0 R >> >>",
            ),
            (
                7,
                stream_obj(
                    b"/Type /XObject /Subtype /Form /BBox [0 0 300 36] "
                    b"/Resources << /Font << /F1 5 0 R >> >>",
                    ap,
                ),
            ),
        ],
    )
    emit(
        "planted-annot-ap",
        pdf,
        [
            plant(
                "annotation_ap",
                t,
                ["o2", "structure"],
                expect_visible_in_output=True,
                bbox=nrect(72, 380, 300, 36),
                notes="term drawn by the /AP normal-appearance form XObject; page text extractors "
                "generally skip annotation appearances",
            )
        ],
        notes="renders on screen; /Annots is a census key",
    )


def fx_annot_contents() -> None:
    t = "PLANT-ANNOTC-01"
    pdf = page_pdf(
        anchor("annotation /Contents string"),
        extra_page=b" /Annots [6 0 R]",
        extra_objects=[
            (
                6,
                b"<< /Type /Annot /Subtype /Square /Rect [72 380 272 420] "
                b"/Contents (" + esc(t) + b") /F 4 >>",
            ),
        ],
    )
    emit(
        "planted-annot-contents",
        pdf,
        [
            plant(
                "annotation_contents",
                t,
                ["o2", "structure"],
                expect_visible_in_output=False,
                bbox=nrect(72, 380, 200, 40),
                notes="term only in the annotation /Contents value (popup text)",
            )
        ],
        notes="not rendered on the page surface",
    )


def fx_xmp() -> None:
    t = "PLANT-XMP-01"
    xmp = (
        b'<?xpacket begin="\xef\xbb\xbf" id="W5M0MpCehiHzreSzNTczkc9d"?>\n'
        b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF '
        b'xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
        b'<rdf:Description xmlns:dc="http://purl.org/dc/elements/1.1/">'
        b'<dc:description><rdf:Alt><rdf:li xml:lang="x-default">'
        + esc(t)
        + b"</rdf:li></rdf:Alt></dc:description></rdf:Description>"
        b'</rdf:RDF></x:xmpmeta>\n<?xpacket end="w"?>'
    )
    pdf = page_pdf(
        anchor("XMP /Metadata stream"),
        catalog_extra=b" /Metadata 6 0 R",
        extra_objects=[(6, stream_obj(b"/Type /Metadata /Subtype /XML", xmp))],
    )
    emit(
        "planted-xmp",
        pdf,
        [
            plant(
                "xmp_metadata",
                t,
                ["o2", "structure"],
                expect_visible_in_output=False,
                notes="dc:description in the catalog XMP packet",
            )
        ],
        notes="/Metadata is a census key; term recoverable from the stream bytes",
    )


def fx_info() -> None:
    t = "PLANT-INFO-01"
    pdf = page_pdf(
        anchor("/Info dictionary"),
        info=6,
        extra_objects=[
            (
                6,
                b"<< /Title (Synthetic Info fixture) /Subject (" + esc(t) + b") "
                b"/Author (Fixture Author) >>",
            )
        ],
    )
    emit(
        "planted-info",
        pdf,
        [
            plant(
                "info_dict",
                t,
                ["o2", "structure"],
                expect_visible_in_output=False,
                notes="/Info /Subject; non-benign keys are census-flagged",
            )
        ],
        notes="the classic metadata surface",
    )


def fx_exif() -> None:
    t = "PLANT-EXIF-01"
    jpg = jpeg_with_exif(t)
    pdf = page_pdf(
        anchor("EXIF ImageDescription in a page JPEG") + b"q 400 0 0 300 106 300 cm /Im1 Do Q\n",
        resources=b"/Font << /F1 5 0 R >> /XObject << /Im1 6 0 R >>",
        extra_objects=[
            (
                6,
                stream_obj(
                    b"/Type /XObject /Subtype /Image /Width 400 /Height 300 "
                    b"/ColorSpace /DeviceGray /BitsPerComponent 8 /Filter /DCTDecode",
                    jpg,
                ),
            )
        ],
    )
    emit(
        "planted-exif",
        pdf,
        [
            plant(
                "exif",
                t,
                ["o2"],
                expect_visible_in_output=False,
                bbox=nrect(106, 300, 400, 300),
                notes="EXIF APP1 ImageDescription inside the embedded JPEG; "
                "pdfimages -all + exiftool is the designed detector",
            )
        ],
        notes="image pixels are benign; the term rides the EXIF container",
    )


def fx_acroform() -> None:
    t = "PLANT-ACROV-01"
    pdf = page_pdf(
        anchor("AcroForm field value (/V)"),
        catalog_extra=b" /AcroForm << /Fields [6 0 R] /NeedAppearances true /DA (/F1 12 Tf 0 g) >>",
        extra_page=b" /Annots [6 0 R]",
        extra_objects=[
            (
                6,
                b"<< /Type /Annot /Subtype /Widget /FT /Tx /T (field1) /V (" + esc(t) + b") "
                b"/Rect [72 380 372 410] /P 3 0 R /F 4 /DA (/F1 12 Tf 0 g) >>",
            ),
        ],
    )
    emit(
        "planted-acroform-v",
        pdf,
        [
            plant(
                "acroform_v",
                t,
                ["o2", "structure"],
                expect_visible_in_output=False,
                bbox=nrect(72, 380, 300, 30),
                notes="unrendered field value ([R01] SS1.9); NeedAppearances true, no /AP",
            )
        ],
        notes="/AcroForm with /V is the census signal",
    )


def fx_outlines() -> None:
    t = "PLANT-OUTLINE-01"
    pdf = page_pdf(
        anchor("/Outlines bookmark title"),
        catalog_extra=b" /Outlines 6 0 R",
        extra_objects=[
            (6, b"<< /Type /Outlines /First 7 0 R /Last 7 0 R /Count 1 >>"),
            (7, b"<< /Title (" + esc(t) + b") /Parent 6 0 R /Dest [3 0 R /Fit] >>"),
        ],
    )
    emit(
        "planted-outlines",
        pdf,
        [
            plant(
                "outlines",
                t,
                ["o2", "structure"],
                expect_visible_in_output=False,
                notes="bookmark /Title ([R01] SS1.8, the EU-AstraZeneca class)",
            )
        ],
        notes="never rendered on the page",
    )


def fx_thumb() -> None:
    t = "PLANT-THUMB-01"
    img = render_term_image(t, 380, 80, 30)
    pdf = page_pdf(
        anchor("page /Thumb thumbnail pixels"),
        extra_page=b" /Thumb 6 0 R",
        extra_objects=[
            (
                6,
                stream_obj(
                    b"/Type /XObject /Subtype /Image /Width 380 /Height 80 "
                    b"/ColorSpace /DeviceGray /BitsPerComponent 8 /Filter /ASCIIHexDecode",
                    ahx(img.tobytes()),
                ),
            )
        ],
    )
    emit(
        "planted-thumb",
        pdf,
        [
            plant(
                "thumb",
                t,
                ["structure"],
                expect_visible_in_output=False,
                notes="term exists only as thumbnail PIXELS; v0's page-render OCR never sees "
                "/Thumb -- the /Thumb census key is the designed signal ([R01] SS1.7)",
            )
        ],
        notes="known partial surface: presence is detectable, pixel content is not (v0)",
    )


def fx_prev_revision() -> None:
    t = "PLANT-PREVREV-01"
    rev1_content = anchor("prior revision (REAL /Prev chain)") + text_op(
        72, 400, 18, f"Original value: {t}"
    )
    objs = [
        (1, b"<< /Type /Catalog /Pages 2 0 R >>"),
        (2, b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>"),
        (
            3,
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R >> >> >>",
        ),
        (4, stream_obj(b"", rev1_content)),
        (5, HELV),
    ]
    rev1 = build_pdf(objs, root=1)
    rev1_xref_off = rev1.rfind(b"\nxref\n") + 1  # NOT rfind("xref") -- that matches startxref
    # Revision 2: replace obj 4 (term removed), append an update section with /Prev.
    rev2_content = anchor("prior revision (REAL /Prev chain)") + text_op(
        72, 400, 18, "Original value: [withdrawn in revision 2]"
    )
    upd = b"\n"
    obj4_off = len(rev1) + len(upd)
    obj4 = b"4 0 obj\n" + stream_obj(b"", rev2_content) + b"\nendobj\n\n"
    upd += obj4
    xref2_off = len(rev1) + len(upd)
    upd += (
        b"xref\n0 1\n0000000000 65535 f \n4 1\n%010d 00000 n \n" % obj4_off
        + b"trailer\n<< /Size 6 /Root 1 0 R /Prev %d >>\nstartxref\n%d\n%%%%EOF"
        % (rev1_xref_off, xref2_off)
    )
    emit(
        "planted-prior-revision",
        rev1 + upd,
        [
            plant(
                "prior_revision",
                t,
                ["o2", "structure"],
                expect_visible_in_output=False,
                notes="rev-1 content stream carries the term; rev-2 replaces obj 4 via a REAL "
                "/Prev-linked incremental update (current view is term-free)",
            )
        ],
        notes="per-revision original-byte scanning is the designed detector (QDF drops priors)",
    )


def fx_embedded_file() -> None:
    t = "PLANT-EMBED-01"
    payload = b"attachment payload: " + t.encode() + b"\n"
    pdf = page_pdf(
        anchor("embedded file (/EmbeddedFiles)"),
        catalog_extra=b" /Names << /EmbeddedFiles << /Names [(note.txt) 6 0 R] >> >>",
        extra_objects=[
            (6, b"<< /Type /Filespec /F (note.txt) /EF << /F 7 0 R >> >>"),
            (7, stream_obj(b"/Type /EmbeddedFile", payload)),
        ],
    )
    emit(
        "planted-embedded-file",
        pdf,
        [
            plant(
                "embedded_file",
                t,
                ["o2", "structure"],
                expect_visible_in_output=False,
                notes="term inside the embedded file stream",
            )
        ],
        notes="/EmbeddedFiles is a census key; mutool extract reaches the payload",
    )


def fx_javascript() -> None:
    t = "PLANT-JS-01"
    pdf = page_pdf(
        anchor("catalog /JavaScript action"),
        catalog_extra=b" /JavaScript << /Names [(script1) 6 0 R] >>",
        extra_objects=[
            (6, b"<< /Type /Action /S /JavaScript /JS (var note = '" + esc(t) + b"';) >>"),
        ],
    )
    emit(
        "planted-javascript",
        pdf,
        [
            plant(
                "javascript",
                t,
                ["o2", "structure"],
                expect_visible_in_output=False,
                notes="term inside the /JS script string",
            )
        ],
        notes="/JavaScript is a census key",
    )


# ---------------------------------------------------------------- structural surfaces


def remap_codes(s: str, first: int = 0x80) -> tuple[bytes, dict[int, str]]:
    """One single-byte code per distinct character of `s` (first appearance order, from
    `first`): the hex-string operand that shows `s`, and the code -> character map."""
    codes: dict[str, int] = {}
    for ch in s:
        codes.setdefault(ch, first + len(codes))
    operand = b"<" + bytes(codes[ch] for ch in s).hex().upper().encode() + b">"
    return operand, {code: ch for ch, code in codes.items()}


def tounicode_cmap(mapping: dict[int, str]) -> bytes:
    """A minimal single-byte ToUnicode CMap (bfchar rows, UTF-16BE destinations)."""
    rows = b"".join(
        b"<%02X> <" % code + ch.encode("utf-16-be").hex().upper().encode() + b">\n"
        for code, ch in sorted(mapping.items())
    )
    return (
        b"/CIDInit /ProcSet findresource begin\n12 dict begin\nbegincmap\n"
        b"/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def\n"
        b"/CMapName /Adobe-Identity-UCS def\n/CMapType 2 def\n"
        b"1 begincodespacerange\n<00> <FF>\nendcodespacerange\n"
        + b"%d beginbfchar\n" % len(mapping)
        + rows
        + b"endbfchar\nendcmap\nCMapName currentdict /CMap defineresource pop\nend\nend\n"
    )


def remap_font(mapping: dict[int, str], glyph: bytes, tounicode_ref: int) -> bytes:
    """Helvetica whose every mapped code draws the same `glyph` (e.g. /X), while the font's
    /ToUnicode maps each code to a different character."""
    lo = min(mapping)
    diffs = b"[%d" % lo + b"".join(b" /" + glyph for _ in mapping) + b"]"
    return (
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
        b"/Encoding << /Type /Encoding /BaseEncoding /WinAnsiEncoding /Differences "
        + diffs
        + b" >> /ToUnicode %d 0 R >>" % tounicode_ref
    )


def type3_font(mapping: dict[int, str], procs_first_ref: int, tounicode_ref: int) -> bytes:
    """A Type 3 font (no /BaseFont) whose glyph procedures draw plain shapes; /ToUnicode maps
    each code to a character. Glyph proc objects are numbered from `procs_first_ref`."""
    lo, hi = min(mapping), max(mapping)
    names = [b"g%d" % i for i in range(hi - lo + 1)]
    charprocs = b" ".join(
        b"/" + n + b" %d 0 R" % (procs_first_ref + i) for i, n in enumerate(names)
    )
    diffs = b"[%d " % lo + b" ".join(b"/" + n for n in names) + b"]"
    return (
        b"<< /Type /Font /Subtype /Type3 /FontBBox [0 0 600 700] "
        b"/FontMatrix [0.001 0 0 0.001 0 0] /CharProcs << " + charprocs + b" >> "
        b"/Encoding << /Type /Encoding /Differences "
        + diffs
        + b" >> /FirstChar %d /LastChar %d /Widths [" % (lo, hi)
        + b" ".join(b"600" for _ in names)
        + b"] /Resources << >> /ToUnicode %d 0 R >>" % tounicode_ref
    )


def type3_glyph_procs(n: int) -> list[bytes]:
    """`n` glyph procedures alternating a filled box and a filled triangle (d1: shape only)."""
    box = b"600 0 0 0 600 700 d1\n60 0 480 700 re f\n"
    tri = b"600 0 0 0 600 700 d1\n60 0 m 540 0 l 300 700 l h f\n"
    return [stream_obj(b"", box if i % 2 == 0 else tri) for i in range(n)]


def scan_like_raster(w: int, h: int, bar_px: tuple[int, int, int, int]) -> bytes:
    """A deterministic full-page grayscale raster (no font rendering): gray line rules standing
    in for scanned text, plus a black bar burned into the pixels at `bar_px` (l, t, r, b)."""
    from PIL import Image, ImageDraw

    img = Image.new("L", (w, h), 255)
    d = ImageDraw.Draw(img)
    for i in range(14):
        y = 180 + i * 90
        d.rectangle((144, y, w - 144 - (i % 4) * 120, y + 22), fill=150)
    d.rectangle(bar_px, fill=0)
    return img.tobytes()


def fx_raster_ocr_layer() -> None:
    t = "PLANT-OCRLAYER-01"
    s = 2  # raster pixels per point (144 DPI)
    bar = (66, 392, 220, 30)  # points, bottom-left origin
    bar_px = (bar[0] * s, (PH - bar[1] - bar[3]) * s, (bar[0] + bar[2]) * s, (PH - bar[1]) * s)
    pixels = scan_like_raster(PW * s, PH * s, bar_px)
    c = (
        b"q %d 0 0 %d 0 0 cm /Im1 Do Q\n" % (PW, PH)
        + b"3 Tr\n"
        + anchor("invisible text layer over a full-page raster")
        + text_op(72, 400, 18, t)
        + b"0 Tr\n"
    )
    pdf = page_pdf(
        c,
        resources=b"/Font << /F1 5 0 R >> /XObject << /Im1 6 0 R >>",
        extra_objects=[
            (
                6,
                stream_obj(
                    b"/Type /XObject /Subtype /Image /Width %d /Height %d "
                    b"/ColorSpace /DeviceGray /BitsPerComponent 8 /Filter /FlateDecode"
                    % (PW * s, PH * s),
                    zlib.compress(pixels, 9),
                ),
            )
        ],
    )
    emit(
        "planted-raster-ocr-layer",
        pdf,
        [
            plant(
                "raster_text_layer",
                t,
                ["o1", "o2"],
                hidden_class="tr3_over_raster",
                expect_visible_in_output=False,
                bbox=nrect(*bar),
                notes="the page content is one full-page Flate image with a black bar in its "
                "pixels; a `3 Tr` (invisible) text line carrying the term sits over the bar, "
                "the shape of a text layer left over from an earlier recognition pass",
            )
        ],
        notes="pixels show only the bar; extractors read the invisible layer",
    )


def fx_nested_form() -> None:
    t = "PLANT-NESTFORM-01"
    inner = text_op(72, 400, 18, f"Nested value: {t}")
    outer = b"q /Fm2 Do Q\n"
    pdf = page_pdf(
        anchor("text in a nested form XObject") + b"q /Fm1 Do Q\n",
        resources=b"/Font << /F1 5 0 R >> /XObject << /Fm1 6 0 R >>",
        extra_objects=[
            (
                6,
                stream_obj(
                    b"/Type /XObject /Subtype /Form /BBox [0 0 %d %d] "
                    b"/Resources << /XObject << /Fm2 7 0 R >> >>" % (PW, PH),
                    outer,
                ),
            ),
            (
                7,
                stream_obj(
                    b"/Type /XObject /Subtype /Form /BBox [0 0 %d %d] "
                    b"/Resources << /Font << /F1 5 0 R >> >>" % (PW, PH),
                    inner,
                ),
            ),
        ],
    )
    emit(
        "planted-nested-form",
        pdf,
        [
            plant(
                "form_xobject_nested",
                t,
                ["o1", "o2", "o3"],
                expect_visible_in_output=True,
                bbox=nrect(72, 396, 300, 22),
                notes="page -> form XObject -> form XObject -> visible text (depth 2)",
            )
        ],
        notes="the page content stream itself carries no text operands for the term",
    )


def fx_xmp_flate() -> None:
    t = "PLANT-XMPFLATE-01"
    xmp = (
        b'<?xpacket begin="\xef\xbb\xbf" id="W5M0MpCehiHzreSzNTczkc9d"?>\n'
        b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF '
        b'xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
        b'<rdf:Description xmlns:dc="http://purl.org/dc/elements/1.1/">'
        b'<dc:description><rdf:Alt><rdf:li xml:lang="x-default">'
        + esc(t)
        + b"</rdf:li></rdf:Alt></dc:description></rdf:Description>"
        b'</rdf:RDF></x:xmpmeta>\n<?xpacket end="w"?>'
    )
    pdf = page_pdf(
        anchor("FlateDecode-compressed XMP /Metadata stream"),
        catalog_extra=b" /Metadata 6 0 R",
        extra_objects=[
            (
                6,
                stream_obj(
                    b"/Type /Metadata /Subtype /XML /Filter /FlateDecode", zlib.compress(xmp, 9)
                ),
            )
        ],
    )
    emit(
        "planted-xmp-flate",
        pdf,
        [
            plant(
                "xmp_metadata_flate",
                t,
                ["o2", "structure"],
                expect_visible_in_output=False,
                notes="dc:description in a FlateDecode catalog XMP packet; the raw bytes carry "
                "no literal form of the term",
            )
        ],
        notes="/Metadata is a census key; the term is recoverable only after inflation",
    )


def fx_tounicode_remap() -> None:
    t = "PLANT-REMAP-01"
    operand, mapping = remap_codes(t)
    c = anchor("ToUnicode remap (glyphs differ from the text)") + (
        b"BT /F2 18 Tf 72 400 Td " + operand + b" Tj ET\n"
    )
    pdf = page_pdf(
        c,
        resources=b"/Font << /F1 5 0 R /F2 6 0 R >>",
        extra_objects=[
            (6, remap_font(mapping, b"X", 7)),
            (7, stream_obj(b"", tounicode_cmap(mapping))),
        ],
    )
    emit(
        "planted-tounicode-remap",
        pdf,
        [
            plant(
                "tounicode_remap",
                t,
                ["o1"],
                expect_visible_in_output=False,
                bbox=nrect(72, 396, 12 * len(t), 22),
                notes="every code draws the glyph X; the font's /ToUnicode maps the codes to "
                "the term's characters, so text extraction yields the term while the page "
                "shows a run of X",
            )
        ],
        notes="neither the content operand nor the CMap carries the term as a contiguous string",
    )


def fx_type3() -> None:
    t = "PLANT-TYPETHREE-01"
    operand, mapping = remap_codes(t)
    n = len(mapping)
    procs = type3_glyph_procs(n)
    c = anchor("Type 3 font with a ToUnicode map") + (
        b"BT /F2 18 Tf 72 400 Td " + operand + b" Tj ET\n"
    )
    pdf = page_pdf(
        c,
        resources=b"/Font << /F1 5 0 R /F2 6 0 R >>",
        extra_objects=[
            (6, type3_font(mapping, 8, 7)),
            (7, stream_obj(b"", tounicode_cmap(mapping))),
            *[(8 + i, p) for i, p in enumerate(procs)],
        ],
    )
    emit(
        "planted-type3-font",
        pdf,
        [
            plant(
                "type3_font",
                t,
                ["o1"],
                expect_visible_in_output=False,
                bbox=nrect(72, 396, round(10.8 * len(t)), 22),
                notes="Type 3 font without /BaseFont; glyph procedures draw boxes and "
                "triangles, /ToUnicode maps the codes to the term's characters",
            )
        ],
        notes="the rendered page shows shapes; extraction yields the term",
    )


def fx_widget_ap() -> None:
    t = "PLANT-WIDGETAP-01"
    ap = b"/Tx BMC q BT /F1 16 Tf 0 g 6 12 Td (" + esc(t) + b") Tj ET Q EMC"
    pdf = page_pdf(
        anchor("Widget annotation appearance without /AcroForm"),
        extra_page=b" /Annots [6 0 R]",
        extra_objects=[
            (
                6,
                b"<< /Type /Annot /Subtype /Widget /FT /Tx /T (field1) /Rect [72 380 372 416] "
                b"/P 3 0 R /F 4 /DA (/F1 16 Tf 0 g) /MK << >> /AP << /N 7 0 R >> >>",
            ),
            (
                7,
                stream_obj(
                    b"/Type /XObject /Subtype /Form /BBox [0 0 300 36] "
                    b"/Resources << /Font << /F1 5 0 R >> >> /Filter /FlateDecode",
                    zlib.compress(ap, 9),
                ),
            ),
        ],
    )
    emit(
        "planted-widget-ap",
        pdf,
        [
            plant(
                "widget_ap",
                t,
                ["o1", "o2", "o3"],
                expect_visible_in_output=True,
                bbox=nrect(72, 380, 300, 36),
                notes="a text Widget whose FlateDecode /AP /N stream draws the term; the field "
                "has no /V and the catalog carries no /AcroForm. pdftotext, mutool and pdftoppm "
                "all draw the appearance; PyMuPDF's page.annots() skips widgets, so the "
                "annotation census key does not fire here",
            )
        ],
        notes="an orphan widget: annotation-only form field, no form dictionary",
    )


def fx_unreferenced_object() -> None:
    t = "PLANT-DEADOBJ-01"
    objs = [
        (1, b"<< /Type /Catalog /Pages 2 0 R >>"),
        (2, b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>"),
        (
            3,
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R >> >> >>" % (PW, PH),
        ),
        (4, stream_obj(b"", anchor("unreferenced compressed object"))),
        (5, HELV),
        (
            6,
            stream_obj(
                b"/Filter /FlateDecode",
                zlib.compress(text_op(72, 400, 18, f"Unused value: {t}"), 9),
            ),
        ),
    ]
    body = b"%PDF-1.4\n" + HEADER
    offsets: dict[int, int] = {}
    for oid, content in objs:
        offsets[oid] = len(body)
        body += b"%d 0 obj\n" % oid + content + b"\nendobj\n\n"
    xref_off = len(body)
    # Object 6 sits in the body but the xref marks it free (generation bumped to 1, head of the
    # free list): no reader that follows the xref reaches it. One xref, one %%EOF.
    xref = b"xref\n0 7\n0000000006 65535 f \n"
    xref += b"".join(b"%010d 00000 n \n" % offsets[oid] for oid in range(1, 6))
    xref += b"0000000000 00001 f \n"
    trailer = b"trailer\n<< /Size 7 /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF" % xref_off
    emit(
        "planted-unreferenced-object",
        body + xref + trailer,
        [
            plant(
                "unreferenced_object",
                t,
                ["o2"],
                expect_visible_in_output=False,
                notes="a FlateDecode stream object present in the file body but marked free in "
                "the single classic xref; nothing references it, and the file has one %%EOF "
                "(not an incremental update)",
            )
        ],
        notes="reachable only by scanning the original bytes and inflating every stream",
    )


def fx_text_outlines_probe() -> str:
    """STRETCH row: text-as-outlines. Verified only if a vectorized copy of the
    visible fixture truly loses its fonts; otherwise records a skip note."""
    src = OUTDIR / "planted-visible.pdf"
    out = OUTDIR / "planted-text-outlines.pdf"
    for args in (["mutool", "convert", "-O", "text=path", "-o", str(out), str(src)],):
        try:
            r = subprocess.run(args, capture_output=True, timeout=120, check=False)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
        if r.returncode != 0 or not out.exists():
            out.unlink(missing_ok=True)
            continue
        fonts = subprocess.run(["pdffonts", str(out)], capture_output=True, timeout=60, check=False)
        font_rows = len(fonts.stdout.decode().splitlines()) - 2
        text = subprocess.run(
            ["pdftotext", str(out), "-"], capture_output=True, timeout=60, check=False
        )
        if font_rows <= 0 and b"PLANT-VISIBLE-01" not in text.stdout:
            pdf = out.read_bytes()
            emit(
                "planted-text-outlines",
                pdf,
                [
                    plant(
                        "text_as_outlines",
                        "PLANT-VISIBLE-01",
                        ["o3"],
                        expect_visible_in_output=True,
                        notes="the visible fixture vectorized to paths (mutool convert "
                        "-O text=path); extractors are blind, only OCR sees it",
                    )
                ],
                notes="STRETCH row, verified vectorized (no fonts, no extractable text)",
            )
            return "emitted"
        out.unlink(missing_ok=True)
    SKIPPED.append(
        {
            "fixture": "planted-text-outlines",
            "surface": "text_as_outlines",
            "reason": "vectorize probe unverified on this rig (mutool convert "
            "text=path did not strip fonts/text); rides IM-19 in P1.5+",
        }
    )
    print("  planted-text-outlines: SKIPPED (stretch; probe unverified)")
    return "skipped"


# ---------------------------------------------------------------- clean controls


def clean_docs() -> None:
    c1 = (
        anchor("clean control letter")
        + text_op(72, 650, 12, "Dear Records Office,")
        + text_op(72, 620, 12, "This letter confirms the synthetic archive contains no live data.")
        + text_op(72, 590, 12, "Reference series: AA-100 through AA-140, all fictional.")
        + text_op(72, 540, 12, "Sincerely, Fixture Clerk")
    )
    emit(
        "clean-letter",
        page_pdf(c1),
        [],
        clean=True,
        notes="benign visible text only; no metadata beyond the skeleton",
    )

    c2 = anchor("clean control table")
    y = 640
    for i, (k, v) in enumerate(
        [
            ("Row", "Amount"),
            ("AA-101", "12.00"),
            ("AA-102", "7.50"),
            ("AA-103", "19.25"),
            ("AA-104", "3.10"),
        ]
    ):
        c2 += text_op(90, y - i * 24, 11, k) + text_op(300, y - i * 24, 11, v)
    pdf2 = page_pdf(
        c2,
        info=6,
        extra_objects=[
            (6, b"<< /Producer (Synthetic Fixture Producer) /Creator (build_planted_corpus) >>")
        ],
    )
    emit(
        "clean-table",
        pdf2,
        [],
        clean=True,
        notes="benign table + BENIGN-ONLY /Info (Producer/Creator) -- the allowlist probe",
    )

    jpg = jpeg_with_exif("", benign_text="CLEAN SAMPLE IMAGE")
    pdf3 = page_pdf(
        anchor("clean control image page") + b"q 400 0 0 300 106 300 cm /Im1 Do Q\n",
        resources=b"/Font << /F1 5 0 R >> /XObject << /Im1 6 0 R >>",
        extra_objects=[
            (
                6,
                stream_obj(
                    b"/Type /XObject /Subtype /Image /Width 400 /Height 300 "
                    b"/ColorSpace /DeviceGray /BitsPerComponent 8 /Filter /DCTDecode",
                    jpg,
                ),
            )
        ],
    )
    emit("clean-image", pdf3, [], clean=True, notes="benign JPEG page, EXIF-free")

    emit(
        "clean-structures",
        clean_structures_pdf(),
        [],
        clean=True,
        notes="benign text carried by the structural shapes of the extended surfaces: a "
        "full-page raster under an invisible text layer (page 1); a nested form XObject, a "
        "ToUnicode-remapped font, a Type 3 font, an orphan Widget /AP and a free-marked "
        "compressed object (page 2). No /Metadata (any /Metadata is a census key by design)",
    )


def clean_structures_pdf() -> bytes:
    """Two-page clean control for the extended structural surfaces (benign strings only)."""
    s = 2
    bar = (66, 392, 220, 30)
    bar_px = (bar[0] * s, (PH - bar[1] - bar[3]) * s, (bar[0] + bar[2]) * s, (PH - bar[1]) * s)
    pixels = scan_like_raster(PW * s, PH * s, bar_px)
    p1 = (
        b"q %d 0 0 %d 0 0 cm /Im1 Do Q\n3 Tr\n" % (PW, PH)
        + anchor("clean control: raster page with a text layer")
        + text_op(72, 400, 18, "Archive series AA-150")
        + b"0 Tr\n"
    )
    remap_op, remap_map = remap_codes("Ledger BB-210", first=0x80)
    t3_op, t3_map = remap_codes("Summary CC-330", first=0x80)
    procs = type3_glyph_procs(len(t3_map))
    p2 = (
        anchor("clean control: structural shapes")
        + b"q /Fm1 Do Q\n"
        + b"BT /F2 14 Tf 72 300 Td "
        + remap_op
        + b" Tj ET\n"
        + b"BT /F3 14 Tf 72 250 Td "
        + t3_op
        + b" Tj ET\n"
    )
    widget_ap = b"/Tx BMC q BT /F1 14 Tf 0 g 6 12 Td (Field note DD-440) Tj ET Q EMC"
    form_obj = b"/Type /XObject /Subtype /Form /BBox [0 0 %d %d] /Resources << " % (PW, PH)
    objs: list[tuple[int, bytes]] = [
        (1, b"<< /Type /Catalog /Pages 2 0 R >>"),
        (2, b"<< /Type /Pages /Kids [3 0 R 10 0 R] /Count 2 >>"),
        (
            3,
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R >> /XObject << /Im1 6 0 R >> >> >>" % (PW, PH),
        ),
        (4, stream_obj(b"", p1)),
        (5, HELV),
        (
            6,
            stream_obj(
                b"/Type /XObject /Subtype /Image /Width %d /Height %d "
                b"/ColorSpace /DeviceGray /BitsPerComponent 8 /Filter /FlateDecode"
                % (PW * s, PH * s),
                zlib.compress(pixels, 9),
            ),
        ),
        (
            10,
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] /Contents 11 0 R "
            b"/Resources << /Font << /F1 5 0 R /F2 14 0 R /F3 16 0 R >> "
            b"/XObject << /Fm1 12 0 R >> >> /Annots [18 0 R] >>" % (PW, PH),
        ),
        (11, stream_obj(b"", p2)),
        (12, stream_obj(form_obj + b"/XObject << /Fm2 13 0 R >> >>", b"q /Fm2 Do Q\n")),
        (
            13,
            stream_obj(
                form_obj + b"/Font << /F1 5 0 R >> >>",
                text_op(72, 400, 14, "Nested heading: quarterly archive index"),
            ),
        ),
        (14, remap_font(remap_map, b"X", 15)),
        (15, stream_obj(b"", tounicode_cmap(remap_map))),
        (16, type3_font(t3_map, 20, 17)),
        (17, stream_obj(b"", tounicode_cmap(t3_map))),
        (
            18,
            b"<< /Type /Annot /Subtype /Widget /FT /Tx /T (field1) /Rect [72 150 372 186] "
            b"/P 10 0 R /F 4 /DA (/F1 14 Tf 0 g) /MK << >> /AP << /N 19 0 R >> >>",
        ),
        (
            19,
            stream_obj(
                b"/Type /XObject /Subtype /Form /BBox [0 0 300 36] "
                b"/Resources << /Font << /F1 5 0 R >> >> /Filter /FlateDecode",
                zlib.compress(widget_ap, 9),
            ),
        ),
        *[(20 + i, p) for i, p in enumerate(procs)],
        (
            9,
            stream_obj(
                b"/Filter /FlateDecode",
                zlib.compress(text_op(72, 400, 12, "Unused draft line EE-550"), 9),
            ),
        ),
    ]
    # build_pdf marks the absent ids (7, 8) free; object 9 is written to the body and then
    # re-marked free below, so it is an unreferenced compressed object, as in the planted row.
    pdf = build_pdf(objs, root=1)
    xref_at = pdf.rfind(b"\nxref\n") + 1
    head, tail = pdf[:xref_at], pdf[xref_at:]
    entry9 = b"%010d 00000 n \n" % (head.find(b"\n9 0 obj\n") + 1)
    if tail.count(entry9) != 1:
        raise AssertionError("object 9 xref entry not found exactly once")
    return head + tail.replace(entry9, b"0000000000 00001 f \n")


# ---------------------------------------------------------------- main


def main() -> None:
    OUTDIR.mkdir(exist_ok=True)
    CLEANDIR.mkdir(exist_ok=True)
    print(f"[planted] building into {OUTDIR}")
    fx_visible()
    fx_wow()
    fx_tr3()
    fx_box()
    fx_ocg()
    fx_hex()
    fx_flate()
    fx_objstm()
    fx_inline_image()
    fx_annot_ap()
    fx_annot_contents()
    fx_xmp()
    fx_info()
    fx_exif()
    fx_acroform()
    fx_outlines()
    fx_thumb()
    fx_prev_revision()
    fx_embedded_file()
    fx_javascript()
    fx_raster_ocr_layer()
    fx_nested_form()
    fx_xmp_flate()
    fx_tounicode_remap()
    fx_type3()
    fx_widget_ap()
    fx_unreferenced_object()
    fx_text_outlines_probe()
    clean_docs()

    manifest: dict[str, Any] = {
        "schema_version": 1,
        "generated_by": "tools/build_planted_corpus.py",
        "term_convention": "PLANT-<SURFACE>-<nn>; every term unique corpus-wide",
        "rows": [r for r in ROWS if not r["clean"]],
        "clean": [r for r in ROWS if r["clean"]],
        "skipped": SKIPPED,
    }
    (OUTDIR / "planted-leaks.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )
    n_plants = sum(len(r["plants"]) for r in ROWS)
    print(
        f"[planted] {len(manifest['rows'])} planted + {len(manifest['clean'])} clean fixtures, "
        f"{n_plants} plants -> {OUTDIR / 'planted-leaks.json'}"
    )


if __name__ == "__main__":
    main()
