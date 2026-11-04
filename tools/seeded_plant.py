"""seeded_plant.py -- plant exactly one fault into copies of redacted outputs.

Input: an emit directory written by the engine-side replay runner
(`<emit>/bases/<base_id>/{output.pdf, replay.json}`) and the base specs it ran
(`<bases>/<base_id>/base.json`). Output: `<out>/<row_id>/{seeded.pdf, row.json}`.

Each row carries ONE planted value (a "needle": one of the values the base
burned) on ONE surface of the file. Two control rows per base come first:
  twin       -- the output as written (no change);
  roundtrip  -- the output opened and saved by the same rewrite path every
                structural plant uses, with no plant. A plant row is only
                meaningful against this control: whatever the rewrite alone
                changes, the roundtrip shows.

Every rewritten file gets its trailer `/ID` pair restamped with the writer's
own rule (the first 16 bytes of SHA-256 over the file with both payloads read
as ASCII zeros), so an `/ID` mismatch is never the reason a row is caught
unless the row's class is about revisions.

Ground truth is the planter's own drawing: `row.json` records the needle, the
page, the box and the surface. Whether the needle is recoverable is the
oracle's call (`seeded_oracle.py`), never this file's.

Usage: .venv/bin/python -I tools/seeded_plant.py --bases DIR --emit DIR --out DIR
       [--classes O-01,O-08] [--max-needles 2]
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import pymupdf
from PIL import Image, ImageDraw, ImageFont

ID_RE = re.compile(rb"/ID\s*\[\s*<([0-9A-Fa-f]{32})>\s*<([0-9A-Fa-f]{32})>\s*\]")
TRAILER_ID_RE = re.compile(rb"/ID\s*\[\s*<[0-9A-Fa-f]{32}>\s*<[0-9A-Fa-f]{32}>\s*\]")
FONT = "/System/Library/Fonts/Supplemental/Courier New.ttf"


# ---------------------------------------------------------------- /ID restamp


def restamp_id(data: bytes) -> bytes:
    """Rewrite the single /ID pair in the file's tail with the content-derived
    identifier. Files with no pair, or more than one, are returned unchanged."""
    tail_start = max(0, len(data) - 262_144)
    hits = list(ID_RE.finditer(data, tail_start))
    if len(hits) != 1:
        return data
    m = hits[0]
    a0, a1 = m.span(1)
    b0, b1 = m.span(2)
    zeros = b"0" * 32
    h = hashlib.sha256(data[:a0] + zeros + data[a1:b0] + zeros + data[b1:]).digest()[:16]
    hexid = h.hex().encode()
    return data[:a0] + hexid + data[a1:b0] + hexid + data[b1:]


def id_matches(data: bytes) -> bool | None:
    tail_start = max(0, len(data) - 262_144)
    hits = list(ID_RE.finditer(data, tail_start))
    if len(hits) != 1:
        return None
    return restamp_id(data) == data


def save(doc: pymupdf.Document, *, objstm: bool = False) -> bytes:
    raw = doc.tobytes(garbage=0, deflate=False, no_new_id=True, use_objstms=1 if objstm else 0)
    return restamp_id(raw)


# ---------------------------------------------------------------- geometry


def box_pts(page: pymupdf.Page, rect_norm: list[float]) -> pymupdf.Rect:
    """Normalized [x, y, w, h] bottom-left -> PyMuPDF top-left Rect in points."""
    W, H = page.rect.width, page.rect.height
    x, y, w, h = rect_norm
    return pymupdf.Rect(x * W, H - (y + h) * H, (x + w) * W, H - y * H)


def fit_size(r: pymupdf.Rect, text: str) -> float:
    by_h = r.height * 0.8
    by_w = r.width / max(1, 0.6 * len(text))
    return max(2.0, min(by_h, by_w))


def baseline(r: pymupdf.Rect, size: float) -> pymupdf.Point:
    return pymupdf.Point(r.x0 + 0.5, r.y0 + (r.height + size * 0.7) / 2)


# ---------------------------------------------------------------- page helpers


def add_content(
    doc: pymupdf.Document,
    page: pymupdf.Page,
    ops: bytes,
    *,
    compress: bool = False,
    fonts: dict[str, str] | None = None,
    xobjects: dict[str, int] | None = None,
) -> None:
    """Append one content stream (wrapped in q/Q) to the page, with resources."""
    xref = doc.get_new_xref()
    doc.update_object(xref, "<<>>")
    doc.update_stream(xref, b"q\n" + ops + b"\nQ\n", compress=compress)
    page_xref = page.xref
    contents = doc.xref_get_key(page_xref, "Contents")
    if contents[0] == "array":
        arr = contents[1].strip()[1:-1]
        doc.xref_set_key(page_xref, "Contents", f"[{arr} {xref} 0 R]")
    else:
        doc.xref_set_key(page_xref, "Contents", f"[{contents[1]} {xref} 0 R]")
    for name, src in (fonts or {}).items():
        set_resource(doc, page_xref, "Font", name, src)
    for name, ox in (xobjects or {}).items():
        set_resource(doc, page_xref, "XObject", name, f"{ox} 0 R")


def set_resource(doc: pymupdf.Document, page_xref: int, kind: str, name: str, value: str) -> None:
    """Set /Resources/<kind>/<name> on a page, following indirect levels."""
    res_kind, res_val = doc.xref_get_key(page_xref, "Resources")
    if res_kind == "xref":
        holder, prefix = int(res_val.split()[0]), ""
    else:
        holder, prefix = page_xref, "Resources/"
    sub_kind, sub_val = doc.xref_get_key(holder, f"{prefix}{kind}")
    if sub_kind == "xref":
        doc.xref_set_key(int(sub_val.split()[0]), name, value)
    else:
        doc.xref_set_key(holder, f"{prefix}{kind}/{name}", value)


COURIER = "<</Type/Font/Subtype/Type1/BaseFont/Courier/Encoding/WinAnsiEncoding>>"


def pdf_lit(s: str) -> bytes:
    b = s.encode("cp1252", errors="replace")
    return b"(" + b.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)") + b")"


def text_ops(
    r: pymupdf.Rect,
    page: pymupdf.Page,
    text: str,
    *,
    mode: int = 3,
    gray: float | None = None,
    show: bytes | None = None,
    tz: float | None = None,
) -> bytes:
    size = fit_size(r, text)
    H = page.rect.height
    p = baseline(r, size)
    x, y = p.x, H - p.y
    parts = [b"BT", f"/FLH {size:.2f} Tf".encode(), f"{mode} Tr".encode()]
    if gray is not None:
        parts.append(f"{gray:.3f} g".encode())
    if tz is not None:
        parts.append(f"{tz:.1f} Tz".encode())
    parts.append(f"1 0 0 1 {x:.2f} {y:.2f} Tm".encode())
    parts.append((show or pdf_lit(text)) + b" Tj")
    parts.append(b"ET")
    return b"\n".join(parts)


# ---------------------------------------------------------------- raster helpers


def page_image(doc: pymupdf.Document, page: pymupdf.Page) -> tuple[int, Image.Image] | None:
    imgs = page.get_images(full=True)
    if not imgs:
        return None
    biggest = max(imgs, key=lambda t: t[2] * t[3])
    xref = biggest[0]
    raw = doc.xref_stream_raw(xref)
    return xref, Image.open(io.BytesIO(raw)).convert("RGB")


def replace_jpeg(doc: pymupdf.Document, xref: int, img: Image.Image) -> None:
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=92, subsampling=2)
    doc.update_stream(xref, buf.getvalue(), compress=False)
    doc.xref_set_key(xref, "Filter", "/DCTDecode")
    doc.xref_set_key(xref, "Length", str(len(buf.getvalue())))


def render_source(src: Path, pno: int, size: tuple[int, int]) -> Image.Image:
    """The SOURCE page rendered by poppler at the output image's pixel size."""
    with tempfile.TemporaryDirectory() as td:
        stem = Path(td) / "p"
        subprocess.run(
            [
                "pdftoppm",
                "-f",
                str(pno + 1),
                "-l",
                str(pno + 1),
                "-singlefile",
                "-scale-to-x",
                str(size[0]),
                "-scale-to-y",
                str(size[1]),
                "-png",
                str(src),
                str(stem),
            ],
            check=True,
        )
        return Image.open(f"{stem}.png").convert("RGB")


def px_box(
    page: pymupdf.Page, img: Image.Image, rect_norm: list[float]
) -> tuple[int, int, int, int]:
    x, y, w, h = rect_norm
    W, H = img.size
    return (round(x * W), round((1 - y - h) * H), round((x + w) * W), round((1 - y) * H))


def draw_text_px(img: Image.Image, xy: tuple[int, int], text: str, height_px: int) -> None:
    font = ImageFont.truetype(FONT, max(8, int(height_px * 0.8)))
    ImageDraw.Draw(img).text(xy, text, fill=(0, 0, 0), font=font)


# ---------------------------------------------------------------- the plants
# Each plant: fn(ctx) -> (bytes, extra) or None when not applicable.
# ctx: doc (fresh copy of the base output), page, pno, rect (norm), needle,
#      src (source PDF path), mode ("s"/"h"), base (bytes of output.pdf).


def p_text_in_box(ctx, variant):
    page, r = ctx["page"], box_pts(ctx["page"], ctx["rect"])
    needle = ctx["needle"]
    if variant == "centre":
        ops = text_ops(r, page, needle)
    elif variant == "partial":
        half = needle[: max(1, len(needle) // 2)]
        ops = text_ops(r, page, half)
    elif variant == "zero-width":
        ops = text_ops(r, page, needle, tz=0.0)
    elif variant == "hex":
        ops = text_ops(
            r, page, needle, show=b"<" + needle.encode("cp1252", "replace").hex().encode() + b">"
        )
    else:
        return None
    add_content(ctx["doc"], page, ops, fonts={"FLH": COURIER})
    return save(ctx["doc"]), {"surface": "text_layer", "in_box": True}


def p_text_on_raster(ctx, variant):
    page, r = ctx["page"], box_pts(ctx["page"], ctx["rect"])
    needle = ctx["needle"]
    if variant == "invisible":
        ops = text_ops(r, page, needle, mode=3)
    elif variant == "white":
        ops = text_ops(r, page, needle, mode=0, gray=1.0)
    elif variant == "off-crop":
        W, H = page.rect.width, page.rect.height
        ops = (
            b"BT /FLH 9 Tf 0 Tr "
            + f"1 0 0 1 {W + 40:.1f} {H / 2:.1f} Tm ".encode()
            + pdf_lit(needle)
            + b" Tj ET"
        )
    else:
        return None
    add_content(ctx["doc"], page, ops, fonts={"FLH": COURIER})
    return save(ctx["doc"]), {"surface": "text_layer", "in_box": variant != "off-crop"}


def p_stale_ocr(ctx, variant):
    """A Tesseract sandwich layer of the SOURCE page, invisible, over the output."""
    doc, page, pno = ctx["doc"], ctx["page"], ctx["pno"]
    H = page.rect.height
    with tempfile.TemporaryDirectory() as td:
        stem = Path(td) / "p"
        subprocess.run(
            [
                "pdftoppm",
                "-r",
                "200",
                "-f",
                str(pno + 1),
                "-l",
                str(pno + 1),
                "-singlefile",
                "-png",
                str(ctx["src"]),
                str(stem),
            ],
            check=True,
        )
        tsv = subprocess.run(
            ["tesseract", f"{stem}.png", "stdout", "--psm", "6", "tsv"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    scale = 72.0 / 200
    ops = [b"BT 3 Tr"]
    for line in tsv.splitlines()[1:]:
        f = line.split("\t")
        if len(f) < 12 or f[0] != "5" or not f[11].strip():
            continue
        left, top, _w, h = (int(v) * scale for v in f[6:10])
        size = max(2.0, h * 0.9)
        ops.append(
            f"/FLH {size:.2f} Tf 1 0 0 1 {left:.2f} {H - top - h:.2f} Tm".encode()
            + b" "
            + pdf_lit(f[11])
            + b" Tj"
        )
    ops.append(b"ET")
    add_content(doc, page, b"\n".join(ops), compress=(variant == "flate"), fonts={"FLH": COURIER})
    return save(doc), {"surface": "text_layer", "in_box": True}


def p_form_xobject(ctx, variant):
    doc, page, r = ctx["doc"], ctx["page"], box_pts(ctx["page"], ctx["rect"])
    mode = 3 if ctx["mode"] == "h" else 0
    inner_ops = text_ops(r, page, ctx["needle"], mode=mode)
    W, H = page.rect.width, page.rect.height
    res = f"<</Font<</FLH {COURIER}>>>>"
    inner = doc.get_new_xref()
    doc.update_object(
        inner, f"<</Type/XObject/Subtype/Form/BBox[0 0 {W:.2f} {H:.2f}]/Resources{res}>>"
    )
    doc.update_stream(inner, inner_ops, compress=(variant == "depth2-flate"))
    target = inner
    if variant.startswith("depth2"):
        outer = doc.get_new_xref()
        doc.update_object(
            outer,
            f"<</Type/XObject/Subtype/Form/BBox[0 0 {W:.2f} {H:.2f}]"
            f"/Resources<</XObject<</FX1 {inner} 0 R>>>>>>",
        )
        doc.update_stream(outer, b"/FX1 Do", compress=False)
        target = outer
    add_content(doc, page, b"/FXO Do", xobjects={"FXO": target})
    return save(doc), {"surface": "form_xobject", "in_box": True}


def p_tounicode(ctx, variant):
    """Glyphs show X; the font's ToUnicode maps the codes to the needle."""
    doc, page, r = ctx["doc"], ctx["page"], box_pts(ctx["page"], ctx["rect"])
    needle = ctx["needle"]
    codes = list(range(0x21, 0x21 + len(needle)))
    bf = "\n".join(f"<{c:02X}> <{ord(ch):04X}>" for c, ch in zip(codes, needle, strict=True))
    cmap = (
        "/CIDInit /ProcSet findresource begin 12 dict begin begincmap\n"
        "/CMapName /Seeded def 1 begincodespacerange <00> <FF> endcodespacerange\n"
        f"{len(codes)} beginbfchar\n{bf}\nendbfchar endcmap CMapName currentdict /CMap defineresource pop end end"
    )
    cx = doc.get_new_xref()
    doc.update_object(cx, "<<>>")
    doc.update_stream(cx, cmap.encode(), compress=False)
    # Differences make every code draw the glyph X; ToUnicode says otherwise.
    diffs = " ".join(f"{c} /X" for c in codes)
    font = (
        f"<</Type/Font/Subtype/Type1/BaseFont/Courier/Encoding<</Type/Encoding"
        f"/Differences[{diffs}]>>/ToUnicode {cx} 0 R>>"
    )
    show = b"<" + bytes(codes).hex().encode() + b">"
    mode = 3 if ctx["mode"] == "h" else 0
    ops = text_ops(r, page, needle, mode=mode, show=show)
    add_content(doc, page, ops, fonts={"FLH": font})
    return save(doc), {"surface": "tounicode", "in_box": True}


def p_annotation(ctx, variant):
    doc, page, r = ctx["doc"], ctx["page"], box_pts(ctx["page"], ctx["rect"])
    needle = ctx["needle"]
    if variant == "text-contents":
        a = page.add_text_annot(r.tl, needle)
    elif variant == "freetext":
        a = page.add_freetext_annot(r, needle, fontsize=6)
    elif variant == "square-contents":
        a = page.add_rect_annot(r)
        a.set_colors(stroke=(0, 0, 0), fill=(0, 0, 0))
        a.set_info(content=needle)
        a.update()
    elif variant == "widget-no-acroform":
        ap = doc.get_new_xref()
        doc.update_object(
            ap,
            f"<</Type/XObject/Subtype/Form/BBox[0 0 {r.width:.2f} {r.height:.2f}]"
            f"/Resources<</Font<</FLH {COURIER}>>>>>>",
        )
        doc.update_stream(ap, b"BT /FLH 6 Tf 1 1 Td " + pdf_lit(needle) + b" Tj ET", compress=False)
        H = page.rect.height
        annot = doc.get_new_xref()
        doc.update_object(
            annot,
            f"<</Type/Annot/Subtype/Widget/FT/Tx/T(f1)/V{pdf_lit(needle).decode('latin-1')}"
            f"/Rect[{r.x0:.2f} {H - r.y1:.2f} {r.x1:.2f} {H - r.y0:.2f}]"
            f"/AP<</N {ap} 0 R>>/P {page.xref} 0 R/F 4>>",
        )
        kind, val = doc.xref_get_key(page.xref, "Annots")
        arr = val.strip()[1:-1] if kind == "array" else ""
        doc.xref_set_key(page.xref, "Annots", f"[{arr} {annot} 0 R]")
        return save(doc), {"surface": "annotation", "in_box": True}
    else:
        return None
    return save(doc), {"surface": "annotation", "in_box": True}


def p_form_field(ctx, variant):
    doc, page, r = ctx["doc"], ctx["page"], box_pts(ctx["page"], ctx["rect"])
    w = pymupdf.Widget()
    w.field_type = pymupdf.PDF_WIDGET_TYPE_TEXT
    w.field_name = "f1"
    w.rect = r
    w.field_value = ctx["needle"]
    w.text_fontsize = 6
    page.add_widget(w)
    if variant == "value-only":
        for wd in page.widgets():
            doc.xref_set_key(wd.xref, "AP", "null")
    return save(doc), {"surface": "acroform", "in_box": True}


def p_metadata(ctx, variant):
    doc, needle = ctx["doc"], ctx["needle"]
    info_kind, info_val = doc.xref_get_key(-1, "Info")
    info = int(info_val.split()[0]) if info_kind == "xref" else None
    lit = pdf_lit(needle).decode("latin-1")
    if variant in ("info-title", "info-custom", "info-producer"):
        if info is None:
            return None
        key = {"info-title": "Title", "info-custom": "XNote", "info-producer": "Producer"}[variant]
        doc.xref_set_key(info, key, lit)
        return save(doc), {"surface": "info", "in_box": False}
    xmp = (
        '<?xpacket begin="" id="W5M0MpCehiHzreSzNTczkc9d"?><x:xmpmeta xmlns:x="adobe:ns:meta/">'
        '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"><rdf:Description '
        f'xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>{needle}</dc:title>'
        '</rdf:Description></rdf:RDF></x:xmpmeta><?xpacket end="w"?>'
    ).encode()
    mx = doc.get_new_xref()
    doc.update_object(mx, "<</Type/Metadata/Subtype/XML>>")
    doc.update_stream(mx, xmp, compress=(variant == "xmp-flate"))
    doc.xref_set_key(doc.pdf_catalog(), "Metadata", f"{mx} 0 R")
    if variant == "xmp-objstm-info":
        return None
    return save(doc), {"surface": "xmp", "in_box": False}


def p_revision(ctx, variant):
    """The needle in an earlier revision of the file."""
    page, r = ctx["page"], box_pts(ctx["page"], ctx["rect"])
    if variant == "dead-object":
        doc = ctx["doc"]
        x = doc.get_new_xref()
        doc.update_object(x, "<<>>")
        doc.update_stream(x, b"BT /F1 9 Tf " + pdf_lit(ctx["needle"]) + b" Tj ET", compress=True)
        return save(doc), {"surface": "unreferenced_object", "in_box": False}
    if variant == "prior-revision":
        doc = ctx["doc"]
        orig_contents = doc.xref_get_key(page.xref, "Contents")[1]
        add_content(doc, page, text_ops(r, page, ctx["needle"], mode=0), fonts={"FLH": COURIER})
        rev1 = doc.tobytes(garbage=0, deflate=False, no_new_id=True)
        d2 = pymupdf.open(stream=rev1, filetype="pdf")
        d2.xref_set_key(d2[ctx["pno"]].xref, "Contents", orig_contents)
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "r.pdf"
            f.write_bytes(rev1)
            d3 = pymupdf.open(f)
            d3.xref_set_key(d3[ctx["pno"]].xref, "Contents", orig_contents)
            d3.saveIncr()
            d3.close()
            # The incremental trailer gets a fresh random second /ID; carry the first
            # revision's instead (same length, so no offset moves) to keep rows reproducible.
            data = f.read_bytes()
            first = TRAILER_ID_RE.findall(rev1)[-1]
            last = list(TRAILER_ID_RE.finditer(data))[-1]
            data = data[: last.start()] + first + data[last.end() :]
            return data, {"surface": "prior_revision", "in_box": True}
    return None


def p_compressed(ctx, variant):
    doc, page = ctx["doc"], ctx["page"]
    needle = ctx["needle"]
    if variant == "content-comment":
        ops = b"% " + needle.encode() + b"\n"
    elif variant == "actualtext":
        ops = b"/Span <</ActualText " + pdf_lit(needle) + b">> BDC EMC"
    else:
        return None
    add_content(doc, page, ops, compress=True)
    return save(doc), {"surface": "compressed_stream", "in_box": False}


def p_raster(ctx, variant):
    doc, page = ctx["doc"], ctx["page"]
    got = page_image(doc, page)
    if got is None:
        return None
    xref, img = got
    src = render_source(ctx["src"], ctx["pno"], img.size)
    x0, y0, x1, y1 = px_box(page, img, ctx["rect"])
    if variant == "unpainted":
        img.paste(src.crop((x0, y0, x1, y1)), (x0, y0))
    elif variant == "alpha50":
        blend = Image.blend(img.crop((x0, y0, x1, y1)), src.crop((x0, y0, x1, y1)), 0.5)
        img.paste(blend, (x0, y0))
    elif variant == "offset":
        k = max(4, (x1 - x0) // 3)
        img.paste(src.crop((x0, y0, x1, y1)), (x0, y0))
        black = Image.new("RGB", (x1 - x0, y1 - y0), (0, 0, 0))
        img.paste(black, (x0 + k, y0))
    elif variant == "edge-residue":
        k = max(3, (x1 - x0) // 4)
        img.paste(src.crop((x1 - k, y0, x1, y1)), (x1 - k, y0))
    else:
        return None
    replace_jpeg(doc, xref, img)
    return save(doc), {"surface": "raster", "in_box": True}


def p_unread_image(ctx, variant):
    doc, page = ctx["doc"], ctx["page"]
    needle = ctx["needle"]
    img = Image.new("RGB", (900, 60), (255, 255, 255))
    draw_text_px(img, (6, 6), needle, 50)
    W, H = page.rect.width, page.rect.height
    r = pymupdf.Rect(W * 0.05, H * 0.92, W * 0.05 + 180, H * 0.92 + 12)
    buf = io.BytesIO()
    if variant == "flate-image":
        img.save(buf, "PNG")
        page.insert_image(r, stream=buf.getvalue())
    else:
        return None
    return save(doc), {"surface": "image", "in_box": False}


def p_container(ctx, variant):
    doc, needle = ctx["doc"], ctx["needle"]
    cat = doc.pdf_catalog()
    if variant == "pieceinfo":
        doc.xref_set_key(
            cat, "PieceInfo", f"<</Seeded<</Private{pdf_lit(needle).decode('latin-1')}>>>>"
        )
    elif variant == "af-file":
        ef = doc.get_new_xref()
        doc.update_object(ef, "<</Type/EmbeddedFile>>")
        doc.update_stream(ef, needle.encode("utf-8"), compress=False)
        fs = doc.get_new_xref()
        doc.update_object(fs, f"<</Type/Filespec/F(note.txt)/UF(note.txt)/EF<</F {ef} 0 R>>>>")
        doc.xref_set_key(cat, "AF", f"[{fs} 0 R]")
    elif variant == "thumb":
        page = ctx["page"]
        img = Image.new("RGB", (400, 40), (255, 255, 255))
        draw_text_px(img, (4, 4), needle, 32)
        tx = doc.get_new_xref()
        raw = img.convert("RGB").tobytes()
        doc.update_object(tx, "<</Width 400/Height 40/ColorSpace/DeviceRGB/BitsPerComponent 8>>")
        doc.update_stream(tx, raw, compress=True)
        doc.xref_set_key(page.xref, "Thumb", f"{tx} 0 R")
    else:
        return None
    return save(doc), {"surface": "container", "in_box": False}


def p_page_tamper(ctx, variant):
    doc = ctx["doc"]
    if variant == "source-page":
        src = pymupdf.open(ctx["src"])
        pno = ctx["pno"]
        doc.delete_page(pno)
        doc.insert_pdf(src, from_page=pno, to_page=pno, start_at=pno)
        return save(doc), {"surface": "page", "in_box": True}
    return None


def p_out_of_region(ctx, variant):
    doc, page = ctx["doc"], ctx["page"]
    needle = ctx["needle"]
    W, H = page.rect.width, page.rect.height
    far = pymupdf.Rect(W * 0.08, H * 0.95, W * 0.92, H * 0.975)
    if variant == "raster-elsewhere":
        got = page_image(doc, page)
        if got is None:
            return None
        xref, img = got
        Wp, Hp = img.size
        draw_text_px(img, (int(Wp * 0.08), int(Hp * 0.95)), needle, int(Hp * 0.02))
        replace_jpeg(doc, xref, img)
        return save(doc), {"surface": "raster", "in_box": False}
    text = {"layer-elsewhere": needle, "layer-casefold": needle.swapcase(), "layer-zwsp": None}.get(
        variant, needle
    )
    if variant == "layer-zwsp":
        return None
    add_content(doc, page, text_ops(far, page, text, mode=3), fonts={"FLH": COURIER})
    return save(doc), {"surface": "text_layer", "in_box": False}


def p_roundtrip(ctx, variant):
    return save(ctx["doc"]), {"surface": None, "in_box": None}


# class -> (plant fn, variants, modes it applies to, digest policies, expect_catch)
CLASSES = {
    "C-01": (None, ["twin"], "sh", ["recorded"], False),
    "C-02": (p_roundtrip, ["roundtrip"], "sh", ["recorded"], False),
    "O-01": (
        p_text_in_box,
        ["centre", "partial", "zero-width", "hex"],
        "h",
        ["consistent", "recorded"],
        True,
    ),
    "O-02": (p_text_on_raster, ["invisible", "white", "off-crop"], "s", ["recorded"], True),
    "O-03": (p_stale_ocr, ["plain", "flate"], "sh", ["consistent"], True),
    "O-04": (p_form_xobject, ["depth1", "depth2", "depth2-flate"], "sh", ["consistent"], True),
    "O-05": (p_tounicode, ["remap"], "sh", ["consistent"], True),
    "O-06": (
        p_annotation,
        ["text-contents", "freetext", "square-contents", "widget-no-acroform"],
        "sh",
        ["recorded"],
        True,
    ),
    "O-07": (p_form_field, ["with-appearance", "value-only"], "sh", ["recorded"], True),
    "O-08": (
        p_metadata,
        ["info-title", "info-custom", "info-producer", "xmp-plain", "xmp-flate"],
        "sh",
        ["recorded"],
        True,
    ),
    "O-09": (p_revision, ["prior-revision", "dead-object"], "sh", ["recorded"], True),
    "O-10": (p_compressed, ["content-comment", "actualtext"], "sh", ["recorded"], True),
    "O-11": (
        p_raster,
        ["unpainted", "alpha50", "offset", "edge-residue"],
        "sh",
        ["recorded"],
        True,
    ),
    "O-12": (p_unread_image, ["flate-image"], "sh", ["recorded"], True),
    "O-13": (p_container, ["pieceinfo", "af-file", "thumb"], "sh", ["recorded"], True),
    "O-14": (p_page_tamper, ["source-page"], "sh", ["recorded"], True),
    "O-15": (
        p_out_of_region,
        ["raster-elsewhere", "layer-elsewhere", "layer-casefold"],
        "sh",
        ["consistent"],
        True,
    ),
}


def pick_needles(replay: dict, k: int) -> list[dict]:
    """Up to k distinct burned values with a box, preferring longer values."""
    seen, out = set(), []
    for r in sorted(replay["regions"], key=lambda r: (-len(r["value"]), r["page"])):
        v = r["value"]
        if not v or v in seen or len(v) < 4:
            continue
        seen.add(v)
        out.append(r)
        if len(out) == k:
            break
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bases", required=True, type=Path, action="append")
    ap.add_argument("--emit", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--classes", default="")
    ap.add_argument("--max-needles", type=int, default=2)
    args = ap.parse_args()
    only = {c for c in args.classes.split(",") if c}
    args.out.mkdir(parents=True, exist_ok=True)
    index: list[dict[str, Any]] = []
    for bdir in sorted((args.emit / "bases").iterdir()):
        out_pdf, replay_p = bdir / "output.pdf", bdir / "replay.json"
        if not (out_pdf.exists() and replay_p.exists()):
            continue
        base_id = bdir.name
        found = [
            b / base_id / "base.json" for b in args.bases if (b / base_id / "base.json").exists()
        ]
        if not found:
            continue
        spec = json.loads(found[0].read_text())
        if spec.get("applied_query") and spec.get("family") != "I":
            # A cache-control base: compared by verdict, never planted. (A
            # family-I base with a search applied is an end-to-end row.)
            continue
        replay = json.loads(replay_p.read_text())
        base_bytes = out_pdf.read_bytes()
        mode = "h" if spec["mode"] == "searchableRedaction" else "s"
        page_modes = replay["per_page_modes"]
        if spec.get("family") == "I":
            # An end-to-end row: the output itself, judged for each value the
            # source hid or the user meant to remove. No plant, no twin.
            for ni, nd in enumerate(spec.get("needles", [])):
                row_id = f"{spec['class']}.{spec.get('variant', 'v')}.{base_id}.n{ni}.r"
                rd = args.out / row_id
                rd.mkdir(parents=True, exist_ok=True)
                (rd / "seeded.pdf").write_bytes(base_bytes)
                row = {
                    "schema": 1,
                    "row_id": row_id,
                    "base_id": base_id,
                    "class": spec["class"],
                    "variant": spec.get("variant", "v"),
                    "digest": "recorded",
                    "family": "I",
                    "mode": mode,
                    "page_mode": "h" if page_modes[nd["page"]] == "searchableRedaction" else "s",
                    "expect_catch": True,
                    "twin": False,
                    "needle": {
                        "text": nd["text"],
                        "page": nd["page"],
                        "rect": nd.get("rect"),
                        "surface": nd.get("surface"),
                        "in_box": bool(nd.get("rect")),
                    },
                    "seeded_sha256": hashlib.sha256(base_bytes).hexdigest(),
                    "base_sha256": hashlib.sha256(base_bytes).hexdigest(),
                    "id_matches": id_matches(base_bytes),
                }
                (rd / "row.json").write_text(json.dumps(row, indent=1, sort_keys=True) + "\n")
                index.append({"row_id": row_id, "status": "planted"})
            continue
        needles = pick_needles(replay, args.max_needles)
        for cls, (fn, variants, modes, digests, expect) in CLASSES.items():
            if only and cls not in only:
                continue
            if mode not in modes:
                continue
            for variant in variants:
                for ni, nr in enumerate(needles if fn not in (None, p_roundtrip) else needles[:1]):
                    pno = nr["page"]
                    page_mode = "h" if page_modes[pno] == "searchableRedaction" else "s"
                    if cls in ("O-01",) and page_mode != "h":
                        continue
                    doc = pymupdf.open(stream=base_bytes, filetype="pdf")
                    ctx = {
                        "doc": doc,
                        "page": doc[pno],
                        "pno": pno,
                        "rect": nr["rect"],
                        "needle": nr["value"],
                        "src": Path(spec["source"]),
                        "mode": page_mode,
                        "base": base_bytes,
                    }
                    err: str | None = None
                    try:
                        res = (
                            (base_bytes, {"surface": None, "in_box": None})
                            if fn is None
                            else fn(ctx, variant)
                        )
                    except Exception as e:  # a plant that cannot apply is recorded, not fatal
                        res = None
                        err = f"{type(e).__name__}: {e}"
                    if res is None:
                        index.append(
                            {
                                "base_id": base_id,
                                "class": cls,
                                "variant": variant,
                                "needle_index": ni,
                                "status": "not-applicable",
                                "error": err,
                            }
                        )
                        continue
                    data, extra = res
                    for dg in digests:
                        row_id = f"{cls}.{variant}.{base_id}.n{ni}.{dg[0]}"
                        rd = args.out / row_id
                        rd.mkdir(parents=True, exist_ok=True)
                        (rd / "seeded.pdf").write_bytes(data)
                        row = {
                            "schema": 1,
                            "row_id": row_id,
                            "base_id": base_id,
                            "class": cls,
                            "variant": variant,
                            "digest": dg,
                            "family": cls[0],
                            "mode": mode,
                            "page_mode": page_mode,
                            "expect_catch": expect,
                            "needle": {
                                "text": nr["value"],
                                "page": pno,
                                "rect": nr["rect"],
                                "surface": extra["surface"],
                                "in_box": extra["in_box"],
                            },
                            "seeded_sha256": hashlib.sha256(data).hexdigest(),
                            "base_sha256": hashlib.sha256(base_bytes).hexdigest(),
                            "id_matches": id_matches(data),
                        }
                        (rd / "row.json").write_text(
                            json.dumps(row, indent=1, sort_keys=True) + "\n"
                        )
                        index.append({"row_id": row_id, "status": "planted"})
    (args.out / "rows-index.json").write_text(json.dumps(index, indent=1) + "\n")
    planted = sum(1 for i in index if i.get("status") == "planted")
    na = [i for i in index if i.get("status") == "not-applicable"]
    print(f"planted {planted} rows; not applicable {len(na)}")
    for i in na:
        if i.get("error"):
            print("  NA", i["class"], i["variant"], i["base_id"], i["error"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
