"""variants.py -- test-only variants + the perf/jetsam filler. All keep fictional-space
discipline and printable ASCII; each re-emits the SAME ground truth transformed to the variant's
coordinate space where applicable.

  scan-sim       packet rasterized at 150 DPI, image-only (no text layer) -> the
                 engine takes the OCR leg. Ground truth bboxes are resolution-independent (unchanged),
                 narrowed to leg ["ocr"].
  rotate-trigger every page /Rotate 90 -- a deliberate TRIGGER for the open rotated-coordinate P0
                 (a trigger, NOT a guard): ground truth is transformed to the rotated display space,
                 so it FAILS against the current engine until that fix lands.
  degrade        a 3-rung quality ladder (skew / blur / low-DPI) off the scan-sim raster.
                 Each rung re-emits ground truth narrowed to leg ["ocr"] (blur/low-DPI keep the
                 scan-sim geometry unchanged; skew boxes are the axis-aligned hull of the
                 1.5deg-rotated box -- APPROXIMATE by construction).
  perf-filler    a 50-200 pp dense born-digital filler (no firing PII) targeting the apply-phase
                 memory cliff.

Rasterization needs PyMuPDF (fitz). Run with: .venv/bin/python -m packet.variants
"""

from __future__ import annotations

import io
import json
from pathlib import Path

from reportlab import rl_config

rl_config.invariant = 1

from reportlab.lib.pagesizes import letter  # noqa: E402
from reportlab.lib.utils import ImageReader  # noqa: E402
from reportlab.pdfgen import canvas  # noqa: E402

from . import build_packet as B  # noqa: E402
from . import aruco as A  # noqa: E402
from . import layout as L  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
OUTDIR = REPO / "variants"
PW, PH = letter


def _have_fitz():
    try:
        import fitz  # noqa: F401

        return True
    except Exception:
        return False


# --------------------------------------------------------------------------------------------------
# deterministic finalize (shared) -- pinned metadata + fixed /ID
# --------------------------------------------------------------------------------------------------
def _finalize(pdf: bytes, title: str, doc_id: bytes) -> bytes:
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import ArrayObject, ByteStringObject

    r = PdfReader(io.BytesIO(pdf))
    w = PdfWriter(clone_from=r)
    creator = "Resecta Sample Packet Generator (variant)"
    w.add_metadata(
        {
            "/Title": title,
            "/Author": "Resecta",
            "/Creator": creator,
            "/Producer": creator,
            "/CreationDate": "D:20260614000000Z",
            "/ModDate": "D:20260614000000Z",
        }
    )
    fid = ByteStringObject(doc_id.ljust(24, b"0")[:24])
    w._ID = ArrayObject([fid, fid])
    out = io.BytesIO()
    w.write(out)
    return out.getvalue()


def _images_to_pdf(images, title: str, doc_id: bytes) -> bytes:
    """Build a born-digital-free, image-only PDF (one full-page image per page)."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter, invariant=1, pageCompression=1)
    for img in images:
        png = io.BytesIO()
        img.save(png, format="PNG", optimize=False)
        png.seek(0)
        c.drawImage(
            ImageReader(png), 0, 0, width=PW, height=PH, preserveAspectRatio=False, mask=None
        )
        c.showPage()
    c.save()
    return _finalize(buf.getvalue(), title, doc_id)


def _rasterize(pdf_bytes: bytes, dpi: int):
    """PDF bytes -> list of grayscale PIL page images at `dpi` (PyMuPDF render; deterministic)."""
    import fitz
    from PIL import Image

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    mat = fitz.Matrix(dpi / 72.0, dpi / 72.0)
    out = []
    for page in doc:
        pix = page.get_pixmap(matrix=mat, colorspace=fitz.csGRAY, alpha=False)
        out.append(Image.open(io.BytesIO(pix.tobytes("png"))).convert("L"))
    doc.close()
    return out


# --------------------------------------------------------------------------------------------------
# scan-sim (150 DPI, OCR leg)
# --------------------------------------------------------------------------------------------------
def scan_sim(packet_pdf: bytes, gt: dict, dpi: int = 150):
    images = _rasterize(packet_pdf, dpi)
    pdf = _images_to_pdf(
        images, f"Hartwell Packet -- scan-sim {dpi} DPI (test-only)", b"ResectaPacketScanSim150"
    )
    vgt = json.loads(json.dumps(gt))  # deep copy; bboxes are resolution-independent
    vgt["variant"] = {"kind": "scan-sim", "dpi": dpi, "rasterized": True, "text_layer": False}
    for r in vgt["occurrences"]:
        r["leg_applicability"] = ["ocr"]  # image-only -> OCR leg only
    return pdf, vgt


# --------------------------------------------------------------------------------------------------
# rotate-trigger (/Rotate 90; transformed ground truth; FAILS until the engine rotated-coord fix)
# --------------------------------------------------------------------------------------------------
def _rotate_bbox(b, degrees: int):
    """Degrees-aware GT transform into the /Rotate display space (C12-72).

    Normalized bottom-left coords; the point maps (clockwise display):
      90:  (nx,ny) -> (ny, 1-nx)      bbox [x0,y0,x1,y1] -> [y0, 1-x1, y1, 1-x0]
      180: (nx,ny) -> (1-nx, 1-ny)    bbox -> [1-x1, 1-y1, 1-x0, 1-y0]
      270: (nx,ny) -> (1-ny, nx)      bbox -> [1-y1, x0, 1-y0, x1]
    Normalization absorbs the 90/270 page-dimension swap (both axes stay 0..1).
    """
    x0, y0, x1, y1 = b
    if degrees == 90:
        return [round(y0, 6), round(1 - x1, 6), round(y1, 6), round(1 - x0, 6)]
    if degrees == 180:
        return [round(1 - x1, 6), round(1 - y1, 6), round(1 - x0, 6), round(1 - y0, 6)]
    if degrees == 270:
        return [round(1 - y1, 6), round(x0, 6), round(1 - y0, 6), round(x1, 6)]
    raise ValueError(f"unsupported rotation {degrees} (90/180/270 only)")


_ROTATE_NOTES = {
    # The 90deg wording is FROZEN (byte-stable committed GT + the T1.4 manifest pin).
    90: "TRIGGER for the open rotated-coordinate P0; FAILS until the engine "
    "fix lands. bbox transformed (nx,ny)->(ny,1-nx).",
    180: "IM-08 rotation leg. /Rotate 180 keeps the axes (no width/height swap); "
    "bbox transformed (nx,ny)->(1-nx,1-ny). Measures only -- F12-04 stays parked.",
    270: "IM-08 rotation leg. /Rotate 270 swaps the axes like 90; "
    "bbox transformed (nx,ny)->(1-ny,nx). Measures only -- F12-04 stays parked.",
}


def rotate_trigger(packet_pdf: bytes, gt: dict, degrees: int = 90):
    from pypdf import PdfReader, PdfWriter

    r = PdfReader(io.BytesIO(packet_pdf))
    w = PdfWriter(clone_from=r)
    for page in w.pages:
        page.rotate(degrees)
    out = io.BytesIO()
    w.write(out)
    pdf = _finalize(
        out.getvalue(),
        f"Hartwell Packet -- rotate-trigger {degrees}deg (test-only)",
        f"ResectaPacketRotate{degrees}".encode("ascii"),
    )
    vgt = json.loads(json.dumps(gt))
    vgt["variant"] = {
        "kind": "rotate-trigger",
        "rotate_degrees": degrees,
        "note": _ROTATE_NOTES[degrees],
    }
    for rec in vgt["occurrences"]:
        rec["bbox"] = _rotate_bbox(rec["bbox"], degrees)
        for s in rec["spans"]:
            s["bbox"] = _rotate_bbox(s["bbox"], degrees)
    return pdf, vgt


# --------------------------------------------------------------------------------------------------
# degrade ladder (skew / blur / low-DPI), off the 150-DPI raster -- deterministic transforms
# --------------------------------------------------------------------------------------------------
_SKEW_DEGREES = 1.5


def _skew_bbox_hull(b, degrees=_SKEW_DEGREES):
    """Axis-aligned hull of a normalized bbox after the skew-rung rotation.

    PIL's ``Image.rotate(degrees)`` turns the page content ``degrees``
    counter-clockwise (as viewed) about the image center; the full-page raster
    makes that the page center. The rotation is isotropic in POINT space, not
    in normalized units (letter pages are not square), so the corners are
    rotated in points and re-normalized. The hull over-covers the true rotated
    quad -- polygons arrive with the E1 factory; this stays APPROXIMATE.
    """
    import math

    cx, cy = PW / 2.0, PH / 2.0
    th = math.radians(degrees)
    cos_t, sin_t = math.cos(th), math.sin(th)
    x0, y0, x1, y1 = b[0] * PW, b[1] * PH, b[2] * PW, b[3] * PH
    xs, ys = [], []
    for px, py in ((x0, y0), (x1, y0), (x0, y1), (x1, y1)):
        dx, dy = px - cx, py - cy
        xs.append(cx + dx * cos_t - dy * sin_t)
        ys.append(cy + dx * sin_t + dy * cos_t)
    hull = [min(xs) / PW, min(ys) / PH, max(xs) / PW, max(ys) / PH]
    return [round(max(0.0, min(1.0, v)), 6) for v in hull]


def _degrade_gt(gt: dict, rung: str, note: str, skewed: bool) -> dict:
    """Ground truth for one degrade rung: leg ["ocr"], geometry per rung."""
    vgt = json.loads(json.dumps(gt))  # deep copy; bboxes are resolution-independent
    vgt["variant"] = {
        "kind": "degrade",
        "rung": rung,
        "rasterized": True,
        "text_layer": False,
        "gt_geometry": (
            "axis-aligned hull of the %.1fdeg-rotated box (approximate)" % _SKEW_DEGREES
        )
        if skewed
        else "inherited (unchanged)",
        "note": note,
    }
    for r in vgt["occurrences"]:
        r["leg_applicability"] = ["ocr"]  # image-only -> OCR leg only
        if skewed:
            r["bbox"] = _skew_bbox_hull(r["bbox"])
            for s in r["spans"]:
                s["bbox"] = _skew_bbox_hull(s["bbox"])
    return vgt


def degrade_ladder(packet_pdf: bytes, gt: dict):
    from PIL import Image

    base = _rasterize(packet_pdf, 150)
    rungs = {}
    # skew: small rotation, white fill (no random)
    skew = [
        im.rotate(_SKEW_DEGREES, resample=Image.Resampling.BILINEAR, expand=False, fillcolor=255)
        for im in base
    ]
    rungs["skew"] = (
        _images_to_pdf(
            skew, "Hartwell Packet -- degrade skew 1.5deg (test-only)", b"ResectaPacketDegSkew01"
        ),
        _degrade_gt(
            gt, "skew", "150 DPI raster rotated 1.5deg CCW about the page center.", skewed=True
        ),
    )
    # blur: downscale 50% then back up (deterministic softening)
    blur = [
        im.resize((im.width // 2, im.height // 2), Image.Resampling.BILINEAR).resize(
            im.size, Image.Resampling.BILINEAR
        )
        for im in base
    ]
    rungs["blur"] = (
        _images_to_pdf(
            blur, "Hartwell Packet -- degrade blur (test-only)", b"ResectaPacketDegBlur01"
        ),
        _degrade_gt(gt, "blur", "150 DPI raster softened by a 50% down/up resample.", skewed=False),
    )
    # low-DPI: re-rasterize the source at 100 DPI
    low = _rasterize(packet_pdf, 100)
    rungs["lowdpi"] = (
        _images_to_pdf(
            low, "Hartwell Packet -- degrade low-DPI 100 (test-only)", b"ResectaPacketDegLow100"
        ),
        _degrade_gt(gt, "lowdpi", "Source re-rasterized at 100 DPI.", skewed=False),
    )
    return rungs


# --------------------------------------------------------------------------------------------------
# perf / jetsam filler (50-200 pp dense born-digital; no firing PII) -- deterministic
# --------------------------------------------------------------------------------------------------
_FILLER_SENTENCES = [
    "The reviewing office keeps a working copy of every page in the order it was received.",
    "Each page carries a printed marker so a reader can confirm the page is part of the set.",
    "The text on these pages is original filler prepared only to lengthen the document for testing.",
    "No personal value appears on these pages; the content is neutral prose with no identifiers.",
    "A long document is useful for checking how the software handles many pages at once.",
    "The filler repeats in a fixed pattern so the output is the same every time it is built.",
    "Readers may skip these pages; they exist to add length and to stress the page pipeline.",
    "The pages are plain and dense so the text layer is easy to extract on every run.",
    "When a document grows large, the work of preparing it page by page grows with it.",
    "This sample is fictional and is provided so that software can be checked end to end.",
]


def perf_filler(pages: int = 120, *, clamp: bool = True) -> bytes:
    # clamp=False is the T4.2 escape hatch (IM-18): the 501-pp import-cap
    # rejection fixture needs to build past the 200-page jetsam-filler range.
    if clamp:
        pages = max(50, min(200, pages))
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter, invariant=1, pageCompression=1)
    L.register_fonts()
    margin, lead, size = 54, 12.5, 9
    for p in range(pages):
        c.setFont(L.SEMI, 10)
        c.setFillColor(L.ACCENT)
        c.drawString(margin, PH - margin, f"Perf Filler -- Page {p + 1} of {pages} (test-only)")
        c.setFont(L.REG, size)
        c.setFillColor(L.INK)
        y = PH - margin - 22
        # deterministic dense body: rotate the sentence bank by page index, ~50 lines/page
        ln = 0
        while y > margin:
            s = _FILLER_SENTENCES[(p + ln) % len(_FILLER_SENTENCES)]
            c.drawString(margin, y, f"{ln + 1:02d}. {s}")
            y -= lead
            ln += 1
        c.setFont(L.REG, 6.5)
        c.setFillColor(L.FAINT)
        c.drawString(
            margin, margin - 12, "Synthetic perf/jetsam filler -- not real; no PII; fictional."
        )
        c.showPage()
    c.save()
    return _finalize(
        buf.getvalue(),
        f"Hartwell Packet -- perf filler {pages}pp (test-only)",
        b"ResectaPacketPerfFill01",
    )


# --------------------------------------------------------------------------------------------------
# print masters -- capture fiducials + human-readable footer (D12-35; `31-` SSC.2)
# --------------------------------------------------------------------------------------------------
CAPTURE_SET_ID = "RESECTA-CAP-2026-08"

# D12-35 places the marks ">= 1/4 in from the edge, in the margins outside the content crop".
# The content margin is layout.M = 42 pt and 1/4 in = 18 pt, so the usable band is exactly
# [18, 42] and the marker fills it. Tight by construction: a printer whose unprintable margin
# exceeds 1/4 in will clip the fiducials, which the capture runsheet's first proof print checks.
_MARK_EDGE = 18.0
_MARK_SIDE = 24.0
_MARKS_PER_PAGE = 4
_FOOTER_SIZE = 7.0
_FOOTER_BASELINE = 8.0


def _draw_marker(c, marker_id: int, x0: float, y0: float, side: float) -> None:
    """Draw one ArUco marker as vector cells, bottom-left corner at (x0, y0).

    Vector rather than a raster stamp: the marker then prints crisply at any DPI and adds no
    image object to the page, so the master stays small and byte-deterministic.
    """
    cells = A.marker_cells(marker_id)
    step = side / A.SIDE_CELLS
    c.setFillColorRGB(0, 0, 0)
    for row_index, row in enumerate(cells):
        # cells[0] is the marker's TOP row; PDF y grows upward.
        y = y0 + (A.SIDE_CELLS - 1 - row_index) * step
        for col_index, bit in enumerate(row):
            if bit:
                c.rect(x0 + col_index * step, y, step, step, stroke=0, fill=1)


def _mark_positions(page_w: float, page_h: float):
    """Return the four (x0, y0) corners, ordered bottom-left, bottom-right, top-right, top-left."""
    lo = _MARK_EDGE
    hi_x = page_w - _MARK_EDGE - _MARK_SIDE
    hi_y = page_h - _MARK_EDGE - _MARK_SIDE
    return [(lo, lo), (hi_x, lo), (hi_x, hi_y), (lo, hi_y)]


def marker_ids(page_number: int) -> list[int]:
    """Return the four marker ids page ``page_number`` (1-indexed) carries (D12-35)."""
    first = _MARKS_PER_PAGE * (page_number - 1)
    return [first + k for k in range(_MARKS_PER_PAGE)]


def marker_quads(page_number: int, page_w: float, page_h: float) -> dict:
    """Return ``{marker_id: [x0, y0, x1, y1]}`` in POINTS for one page.

    The registration step needs the masters' marker geometry to pair with the detected corners
    in a scan, so it is emitted alongside the PDF rather than re-derived by eye.
    """
    return {
        mid: [x0, y0, x0 + _MARK_SIDE, y0 + _MARK_SIDE]
        for mid, (x0, y0) in zip(
            marker_ids(page_number), _mark_positions(page_w, page_h), strict=True
        )
    }


def print_master(
    pdf_bytes: bytes, *, set_id: str = CAPTURE_SET_ID, doc_id: bytes = b"ResectaCaptureMaster01"
) -> dict:
    """Add capture marks to every page of ``pdf_bytes`` without disturbing its content.

    Each page gains four ArUco corner fiducials (ids ``4*(page-1) .. 4*(page-1)+3``) and a
    human-readable footer, drawn on a transparent overlay that is merged over the original page.
    Nothing inside the content margin is touched, so **every ground-truth box carries verbatim** --
    the marks live in the margins the evaluated image is cropped back to.

    Returns ``{"pdf": bytes, "marks": [{page, page_size_pt, markers, footer}, ...]}``; the marks
    list is the registration side's input.
    """
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(io.BytesIO(pdf_bytes))
    total = len(reader.pages)
    if total * _MARKS_PER_PAGE > A.COUNT:
        raise SystemExit(
            f"{total} pages need {total * _MARKS_PER_PAGE} marker ids but "
            f"{A.DICT_NAME} holds {A.COUNT}"
        )

    L.register_fonts()
    marks = []
    overlay_buf = io.BytesIO()
    overlay = canvas.Canvas(overlay_buf, pagesize=(L.PW, L.PH), invariant=1, pageCompression=1)
    for index, page in enumerate(reader.pages):
        box = page.mediabox
        page_w, page_h = float(box.width), float(box.height)
        overlay.setPageSize((page_w, page_h))
        page_number = index + 1
        for mid, (x0, y0) in zip(
            marker_ids(page_number), _mark_positions(page_w, page_h), strict=True
        ):
            _draw_marker(overlay, mid, x0, y0, _MARK_SIDE)
        footer = f"{set_id} | page {page_number:02d}/{total:02d} | synthetic - no real data"
        overlay.setFillColor(L.INK)
        overlay.setFont(L.REG, _FOOTER_SIZE)
        overlay.drawCentredString(page_w / 2.0, _FOOTER_BASELINE, footer)
        overlay.showPage()
        marks.append(
            {
                "page": index,
                "page_size_pt": [page_w, page_h],
                "markers": marker_quads(page_number, page_w, page_h),
                "footer": footer,
            }
        )
    overlay.save()

    stamped = PdfReader(io.BytesIO(overlay_buf.getvalue()))
    writer = PdfWriter()
    for page, mark in zip(reader.pages, stamped.pages, strict=True):
        page.merge_page(mark)
        writer.add_page(page)
    out = io.BytesIO()
    writer.write(out)
    return {"pdf": _finalize(out.getvalue(), f"{set_id} print masters", doc_id), "marks": marks}


# --------------------------------------------------------------------------------------------------
def build_all(perf_pages: int = 120, *, write=True) -> dict:
    if not _have_fitz():
        raise SystemExit("variants require PyMuPDF (fitz): pip install pymupdf  (or uv sync)")
    res = B.build(write=False)
    packet_pdf, gt = res["pdf"], res["ground_truth"]
    out = {}
    ss_pdf, ss_gt = scan_sim(packet_pdf, gt)
    rt_pdf, rt_gt = rotate_trigger(packet_pdf, gt)
    deg = degrade_ladder(packet_pdf, gt)
    perf = perf_filler(perf_pages)
    out = {
        "scan_sim": (ss_pdf, ss_gt),
        "rotate_trigger": (rt_pdf, rt_gt),
        "degrade": deg,
        "perf": perf,
    }
    if write:
        OUTDIR.mkdir(exist_ok=True)
        (OUTDIR / "packet-scan-sim-150dpi.pdf").write_bytes(ss_pdf)
        (OUTDIR / "packet-scan-sim-150dpi-ground-truth.json").write_text(
            json.dumps(ss_gt, indent=2) + "\n", encoding="ascii"
        )
        (OUTDIR / "packet-rotate-trigger.pdf").write_bytes(rt_pdf)
        (OUTDIR / "packet-rotate-trigger-ground-truth.json").write_text(
            json.dumps(rt_gt, indent=2) + "\n", encoding="ascii"
        )
        for name, (pdf, dgt) in deg.items():
            (OUTDIR / f"packet-degrade-{name}.pdf").write_bytes(pdf)
            (OUTDIR / f"packet-degrade-{name}-ground-truth.json").write_text(
                json.dumps(dgt, indent=2) + "\n", encoding="ascii"
            )
        (OUTDIR / f"perf-filler-{perf_pages}pp.pdf").write_bytes(perf)
    return out


def main() -> None:
    out = build_all()
    print(f"scan-sim:       {len(out['scan_sim'][0]):,} bytes (image-only, OCR leg)")
    print(f"rotate-trigger: {len(out['rotate_trigger'][0]):,} bytes (/Rotate 90; transformed GT)")
    for name, (pdf, _dgt) in out["degrade"].items():
        print(f"degrade/{name:7s} {len(pdf):,} bytes (+ transformed ground truth)")
    print(f"perf-filler:    {len(out['perf']):,} bytes")
    print(f"-> {OUTDIR}")


if __name__ == "__main__":
    main()


# --------------------------------------------------------------------------------------------------
# hidden-text packet variants (T2.4 / IM-09..12 -- the PB-86 realism leg)
# --------------------------------------------------------------------------------------------------
# Plants live in the page-0 bottom margin (footer occupies user-space y 44..52; both bands below
# it are measured char-free): band A (covered, baseline y 26) carries the plants the H2.2 cell
# burns; band B (uncovered, baseline y 10) carries the re-exposure probes no region touches.
# Classes: white-on-white (`1 g`), `3 Tr`, content-stream opaque box -- in packet-hidden-text.pdf;
# OCG /OFF in packet-hidden-ocg.pdf (SEPARATE file: hidden OCG triggers the engine's AD-2-1
# per-page secure fallback, which would drag the other classes off the searchable path).
# Sidecar: variants/packet-hidden-plants.json (term, class, role, bbox + burn region, normalized
# bottom-left, y-up). Deterministic via _finalize (pinned metadata + /ID).

_HIDDEN_FONT = "FPLNT"
_BAND_A_Y, _BAND_B_Y = 26, 10
_SLOT_X = (60, 240, 420)
_PLANT_SIZE = 9


def _plant_bbox(x: float, y: float) -> list:
    return [round(x / PW, 4), round((y - 2) / PH, 4), round(120 / PW, 4), round(13 / PH, 4)]


def _burn_region(x: float) -> list:
    # generous pad around a band-A slot; stays inside the char-free margin band
    return [round((x - 6) / PW, 4), round(21 / PH, 4), round(136 / PW, 4), round(17 / PH, 4)]


def _hidden_ops(cls: str, term: str, x: float, y: float) -> bytes:
    def esc(s: str) -> bytes:
        return s.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)").encode("latin-1")

    tj = b"BT %s/%s %d Tf %d %d Td (%s) Tj ET\n" % (
        b"3 Tr " if cls == "tr3_invisible" else b"",
        _HIDDEN_FONT.encode(),
        _PLANT_SIZE,
        int(x),
        int(y),
        esc(term),
    )
    if cls == "white_on_white":
        return b"1 g\n" + tj + b"0 g\n"
    if cls == "tr3_invisible":
        return tj
    if cls == "opaque_box":
        return tj + b"0 g %d %d 132 15 re f\n" % (int(x) - 6, int(y) - 3)
    if cls == "ocg_off":
        return b"/OC /OCPLNT BDC\n" + tj + b"EMC\n"
    raise ValueError(cls)


def _assert_band_free(pdf_bytes: bytes, page_index: int) -> None:
    """Both margin bands must be char-free on the target page (fitz, top-down y)."""
    import fitz

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    words = doc[page_index].get_text("words")
    doc.close()
    for w in words:
        top, bottom = w[1], w[3]
        if bottom > PH - 40:  # anything below user-space y=40
            raise AssertionError(f"margin band occupied on page {page_index}: {w[:5]}")


def _packet_with_hidden(
    packet_pdf: bytes, specs: list[dict], *, ocg: bool, title: str, doc_id: bytes
) -> bytes:
    import io as _io
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import (
        ArrayObject,
        DecodedStreamObject,
        DictionaryObject,
        NameObject,
        TextStringObject,
    )

    _assert_band_free(packet_pdf, 0)
    reader = PdfReader(_io.BytesIO(packet_pdf))
    writer = PdfWriter(clone_from=reader)
    page = writer.pages[0]

    font_ref = writer._add_object(
        DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
                NameObject("/Encoding"): NameObject("/WinAnsiEncoding"),
            }
        )
    )
    resources = page["/Resources"]
    resources = resources.get_object()
    fonts = resources.get("/Font")
    fonts = fonts.get_object() if fonts is not None else None
    if fonts is None:
        fonts = DictionaryObject()
        resources[NameObject("/Font")] = fonts
    fonts[NameObject("/" + _HIDDEN_FONT)] = font_ref

    if ocg:
        ocg_ref = writer._add_object(
            DictionaryObject(
                {
                    NameObject("/Type"): NameObject("/OCG"),
                    NameObject("/Name"): TextStringObject("Planted Hidden Layer"),
                }
            )
        )
        writer._root_object[NameObject("/OCProperties")] = DictionaryObject(
            {
                NameObject("/OCGs"): ArrayObject([ocg_ref]),
                NameObject("/D"): DictionaryObject(
                    {
                        NameObject("/OFF"): ArrayObject([ocg_ref]),
                    }
                ),
            }
        )
        props = resources.get("/Properties")
        props = props.get_object() if props is not None else None
        if props is None:
            props = DictionaryObject()
            resources[NameObject("/Properties")] = props
        props[NameObject("/OCPLNT")] = ocg_ref

    ops = b"".join(_hidden_ops(s["hidden_class"], s["term"], s["x"], s["y"]) for s in specs)
    stream = DecodedStreamObject()
    stream.set_data(b"q\n" + ops + b"Q\n")
    stream_ref = writer._add_object(stream)
    raw_contents = page.raw_get("/Contents")
    existing = raw_contents.get_object()
    if isinstance(existing, ArrayObject):
        arr = ArrayObject(list(existing) + [stream_ref])
    else:
        arr = ArrayObject([raw_contents, stream_ref])
    page[NameObject("/Contents")] = arr

    out = _io.BytesIO()
    writer.write(out)
    return _finalize(out.getvalue(), title, doc_id)


def hidden_text(packet_pdf: bytes):
    """IM-09..12: page-0 margin plants x4 hidden classes, covered (band A) + uncovered
    (band B) roles. Returns (hidden_text_pdf, hidden_ocg_pdf, sidecar_dict)."""
    trio = [
        {"hidden_class": "white_on_white", "term_stem": "PKTWOW"},
        {"hidden_class": "tr3_invisible", "term_stem": "PKTTR3"},
        {"hidden_class": "opaque_box", "term_stem": "PKTBOX"},
    ]
    specs, rows = [], []
    for i, t in enumerate(trio):
        for role, y, nn in (("covered", _BAND_A_Y, "01"), ("uncovered", _BAND_B_Y, "02")):
            term = f"PLANT-{t['term_stem']}-{nn}"
            spec = {"hidden_class": t["hidden_class"], "term": term, "x": _SLOT_X[i], "y": y}
            specs.append(spec)
            rows.append(
                {
                    "file": "packet-hidden-text.pdf",
                    "page": 0,
                    "hidden_class": t["hidden_class"],
                    "term": term,
                    "role": role,
                    "bbox": _plant_bbox(_SLOT_X[i], y),
                    "burn_region": _burn_region(_SLOT_X[i]) if role == "covered" else None,
                }
            )
    ht = _packet_with_hidden(
        packet_pdf,
        specs,
        ocg=False,
        title="Hartwell Packet -- hidden-text variant (test-only)",
        doc_id=b"ResectaPacketHiddenTx1",
    )

    ocg_specs, ocg_rows = [], []
    for role, x, y, nn in (
        ("covered", _SLOT_X[0], _BAND_A_Y, "01"),
        ("uncovered", _SLOT_X[1], _BAND_B_Y, "02"),
    ):
        term = f"PLANT-PKTOCG-{nn}"
        ocg_specs.append({"hidden_class": "ocg_off", "term": term, "x": x, "y": y})
        ocg_rows.append(
            {
                "file": "packet-hidden-ocg.pdf",
                "page": 0,
                "hidden_class": "ocg_off",
                "term": term,
                "role": role,
                "bbox": _plant_bbox(x, y),
                "burn_region": _burn_region(x) if role == "covered" else None,
            }
        )
    ho = _packet_with_hidden(
        packet_pdf,
        ocg_specs,
        ocg=True,
        title="Hartwell Packet -- hidden-OCG variant (test-only)",
        doc_id=b"ResectaPacketHiddenOc1",
    )

    sidecar = {
        "schema_version": 1,
        "generated_by": "packet.variants hidden_text (IM-09..12)",
        "coordinates": "normalized bottom-left [x, y, w, h] (y-up)",
        "plants": rows + ocg_rows,
    }
    return ht, ho, sidecar


def build_hidden(write: bool = True) -> dict:
    if not _have_fitz():
        raise SystemExit("hidden variants require PyMuPDF (fitz)")
    res = B.build(write=False)
    ht, ho, sidecar = hidden_text(res["pdf"])
    if write:
        OUTDIR.mkdir(exist_ok=True)
        (OUTDIR / "packet-hidden-text.pdf").write_bytes(ht)
        (OUTDIR / "packet-hidden-ocg.pdf").write_bytes(ho)
        (OUTDIR / "packet-hidden-plants.json").write_text(
            json.dumps(sidecar, indent=2) + "\n", encoding="ascii"
        )
    return {"hidden_text": ht, "hidden_ocg": ho, "sidecar": sidecar}
