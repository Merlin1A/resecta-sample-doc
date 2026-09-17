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
    fx_text_outlines_probe()
    clean_docs()

    manifest = {
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
