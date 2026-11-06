"""Scanned twins of the born-digital pages, and their text layers.

A twin's picture is the born-digital page rendered by PyMuPDF at the twin's resolution:
- ``clean``: 300 dpi, JPEG quality 85, nothing else;
- ``light``: 200 dpi, seeded grey noise of +/-``LIGHT_NOISE`` levels, a ``LIGHT_BLUR`` px blur, JPEG
  quality 75 (no skew, so a layer placed at drift 0 stays on the ink).

Its layer is one of:
- ``none``: the picture only;
- ``placed``: the born-digital page's own text drawn again over the picture in render mode 3, so the
  layer is the born page's text layer, with its fonts and ToUnicode maps, at drift 0;
- ``vision``: Apple Vision's words and boxes (``vision.py``), drawn in render mode 3 in a glyphless
  font whose cmap holds every recognised character.
"""

from __future__ import annotations

import io
from typing import Any

import numpy as np
import pymupdf
import pypdf
from PIL import Image, ImageFilter
from pypdf.generic import ContentStream, DecodedStreamObject, NameObject, NumberObject, StreamObject

from hidden_layer.rng import mix_seed, uniform_ints

LIGHT_NOISE = 10
LIGHT_BLUR = 0.4
CONDITIONS = {"clean": (300, 85), "light": (200, 75)}


def render_gray(pdf: bytes, dpi: int) -> np.ndarray:
    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        pix = doc[0].get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY, alpha=False)
        return np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width).copy()


def lighten(img: np.ndarray, seed: int) -> np.ndarray:
    """The ``light`` condition: seeded noise of +/-``LIGHT_NOISE`` levels, then a ``LIGHT_BLUR`` px blur."""
    noise = uniform_ints(mix_seed(seed, "light"), img.size, -LIGHT_NOISE, LIGHT_NOISE).reshape(
        img.shape
    )
    out = np.clip(img.astype(np.int64) + noise, 0, 255).astype(np.uint8)
    return np.asarray(Image.fromarray(out).filter(ImageFilter.GaussianBlur(LIGHT_BLUR)))


def picture(pdf: bytes, condition: str, seed: int) -> tuple[bytes, tuple[int, int]]:
    dpi, quality = CONDITIONS[condition]
    img = render_gray(pdf, dpi)
    if condition == "light":
        img = lighten(img, seed)
    buf = io.BytesIO()
    Image.fromarray(img).save(buf, "JPEG", quality=quality, dpi=(dpi, dpi), optimize=False)
    return buf.getvalue(), (img.shape[1], img.shape[0])


# Operators kept when the born page is redrawn as an invisible layer: graphics state, text, and the
# drawing of form XObjects; every path, image and shading operator is dropped.
KEEP_OUTSIDE_TEXT = {
    b"q",
    b"Q",
    b"cm",
    b"gs",
    b"Do",
    b"BT",
    b"W",
    b"W*",
    b"n",
    b"d",
    b"w",
    b"j",
    b"J",
    b"M",
    b"ri",
    b"i",
}
PATH_OPS = {
    b"m",
    b"l",
    b"c",
    b"v",
    b"y",
    b"h",
    b"re",
    b"S",
    b"s",
    b"f",
    b"F",
    b"f*",
    b"B",
    b"B*",
    b"b",
    b"b*",
    b"sh",
    b"BI",
    b"ID",
    b"EI",
}


def _invisible(stream: Any, rd: Any, writer: pypdf.PdfWriter) -> bytes:
    ops = ContentStream(stream, rd).operations
    kept: list[tuple[list[Any], bytes]] = []
    inside = False
    for operands, op in ops:
        if op == b"BT":
            inside = True
            kept.append(([], b"BT"))
            kept.append(([NumberObject(3)], b"Tr"))
            continue
        if op == b"ET":
            inside = False
            kept.append(([], b"ET"))
            continue
        if inside:
            if op == b"Tr":
                kept.append(([NumberObject(3)], b"Tr"))
            elif op not in PATH_OPS:
                kept.append((list(operands), op))
            continue
        if op in KEEP_OUTSIDE_TEXT and op not in (b"BT",):
            kept.append((list(operands), op))
    cs = ContentStream(None, writer)
    cs.operations = kept
    return cs.get_data()


def placed_layer_pdf(born: bytes, jpeg: bytes, image_px: tuple[int, int]) -> bytes:
    """The picture, then the born page's text alone in render mode 3."""
    w = pypdf.PdfWriter(clone_from=pypdf.PdfReader(io.BytesIO(born)))
    rd = w
    page: Any = w.pages[0]
    width, height = float(page.mediabox.width), float(page.mediabox.height)
    seen: set[int] = set()

    def visit(container: Any, depth: int) -> None:
        for ref in ((container.get("/Resources") or {}).get("/XObject") or {}).values():
            if ref.idnum in seen or depth > 8:
                continue
            seen.add(ref.idnum)
            xo = ref.get_object()
            if xo.get("/Subtype") == "/Form":
                xo.set_data(_invisible(xo, rd, w))
                visit(xo, depth + 1)

    visit(page, 0)
    text_ops = _invisible(page.get_contents(), rd, w)
    img = StreamObject()
    img._data = jpeg
    img.update(
        {
            NameObject("/Type"): NameObject("/XObject"),
            NameObject("/Subtype"): NameObject("/Image"),
            NameObject("/Width"): NumberObject(image_px[0]),
            NameObject("/Height"): NumberObject(image_px[1]),
            NameObject("/ColorSpace"): NameObject("/DeviceGray"),
            NameObject("/BitsPerComponent"): NumberObject(8),
            NameObject("/Filter"): NameObject("/DCTDecode"),
        }
    )
    res = page["/Resources"]
    if "/XObject" not in res:
        res[NameObject("/XObject")] = pypdf.generic.DictionaryObject()
    res["/XObject"][NameObject("/ImScan")] = w._add_object(img)
    content = DecodedStreamObject()
    content.set_data(f"q {width:g} 0 0 {height:g} 0 0 cm /ImScan Do Q\n".encode("ascii") + text_ops)
    page[NameObject("/Contents")] = w._add_object(content)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def image_only_pdf(
    jpeg: bytes, image_px: tuple[int, int], page: tuple[int, int] = (612, 792)
) -> bytes:
    """One page holding only the picture: no font, no text."""
    content = f"q {page[0]} 0 0 {page[1]} 0 0 cm /Im1 Do Q\n".encode("ascii")
    w, h = image_px
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {page[0]} {page[1]}] /Contents 4 0 R /Resources << /XObject << /Im1 5 0 R >> >> >>".encode(
            "ascii"
        ),
        f"<< /Length {len(content)} >>\nstream\n".encode("ascii") + content + b"endstream",
        f"<< /Type /XObject /Subtype /Image /Width {w} /Height {h} /ColorSpace /DeviceGray /BitsPerComponent 8 /Filter /DCTDecode /Length {len(jpeg)} >>\nstream\n".encode(
            "ascii"
        )
        + jpeg
        + b"\nendstream",
        b"<< /Title (Synthetic script fixture) /Producer (resecta-sample-doc scripts_handwriting writer) >>",
    ]
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode("ascii") + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("ascii")
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode("ascii")
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R /Info {len(objects)} 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode(
        "ascii"
    )
    return bytes(out)
