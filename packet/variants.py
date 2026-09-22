"""variants.py -- test-only variants + the perf/jetsam filler. All keep fictional-space
discipline and printable ASCII; each re-emits the SAME ground truth transformed to the variant's
coordinate space where applicable.

  scan-sim       packet rasterized at 150 DPI, image-only (no text layer) -> the
                 engine takes the OCR leg. Ground truth bboxes are resolution-independent (unchanged),
                 narrowed to leg ["ocr"].
  rotate-trigger every page /Rotate 90 -- the rotated-coordinate trigger for the engine's page
                 reconstruction path (a trigger, NOT a guard): the ground truth transformed into the
                 rotated display space is the record; the text leg matches it in full and the
                 rotated OCR leg is a measured cell, not a detection failure.
  degrade        a declarative quality ladder (`_RUNGS`) off the 150-DPI raster, built for BOTH
                 masters (the 12-page packet and the 16-page capture masters): skew 1.5deg / blur /
                 low-DPI 100 / low-DPI 75 / JPEG QF 85 / JPEG QF 70 / seeded noise / bleed-through
                 / fax 204x98 / fax 204x196. Each rung re-emits ground truth narrowed to leg
                 ["ocr"] with a `polygon` beside every bbox (the skew rung's rotated quad; the
                 bbox is its axis-aligned hull; photometric rungs inherit the geometry).
  perf-filler    a 50-200 pp dense born-digital filler (no firing PII) targeting the apply-phase
                 memory cliff.

Rasterization needs PyMuPDF (fitz). Run with: .venv/bin/python -m packet.variants
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import cast

from reportlab import rl_config

rl_config.invariant = 1

from reportlab.lib.pagesizes import letter  # noqa: E402
from reportlab.lib.utils import ImageReader  # noqa: E402
from reportlab.pdfgen import canvas  # noqa: E402

from . import aruco as A  # noqa: E402
from . import build_packet as B  # noqa: E402
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


def _rasterize(pdf_bytes: bytes, dpi: int, dpi_y: int | None = None):
    """PDF bytes -> list of grayscale PIL page images at `dpi` (PyMuPDF render; deterministic).
    `dpi_y` makes the raster anisotropic (the fax rungs: 204 x 98 / 204 x 196)."""
    import fitz
    from PIL import Image

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    mat = fitz.Matrix(dpi / 72.0, (dpi if dpi_y is None else dpi_y) / 72.0)
    out = []
    for page in doc:
        pix = page.get_pixmap(matrix=mat, colorspace=fitz.csGRAY, alpha=False)
        out.append(Image.open(io.BytesIO(pix.tobytes("png"))).convert("L"))
    doc.close()
    return out


# --------------------------------------------------------------------------------------------------
# scan-sim (150 DPI, OCR leg)
# --------------------------------------------------------------------------------------------------
# the row lists of a ground-truth file that carry draw-time geometry (the packet's carried_stmt
# rows have none and are left as the master states them)
_GEOMETRY_LISTS = ("occurrences", "carried_packet")


def _rows_with_geometry(vgt: dict):
    for key in _GEOMETRY_LISTS:
        yield from vgt.get(key) or []


def scan_sim(
    packet_pdf: bytes,
    gt: dict,
    dpi: int = 150,
    *,
    title: str | None = None,
    doc_id: bytes = b"ResectaPacketScanSim150",
):
    images = _rasterize(packet_pdf, dpi)
    pdf = _images_to_pdf(
        images, title or f"Hartwell Packet -- scan-sim {dpi} DPI (test-only)", doc_id
    )
    vgt = json.loads(json.dumps(gt))  # deep copy; bboxes are resolution-independent
    vgt["variant"] = {"kind": "scan-sim", "dpi": dpi, "rasterized": True, "text_layer": False}
    for r in _rows_with_geometry(vgt):
        r["leg_applicability"] = ["ocr"]  # image-only -> OCR leg only
    return pdf, vgt


# --------------------------------------------------------------------------------------------------
# rotate-trigger (/Rotate N; ground truth transformed into the rotated display space = the record)
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
    # The note strings reach the emitted variant ground truth only; the manifest pins the PDF bytes.
    90: "Rotated-coordinate trigger for the engine's page-reconstruction path; the rotated "
    "display-space ground truth is the record. bbox transformed (nx,ny)->(ny,1-nx).",
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
# degrade ladder -- a declarative rung table off the 150-DPI raster (E1 stage 1)
#
# Every rung is a pure function of (the master's bytes, the rung's seed): the photometric rungs draw
# their only entropy from an integer SplitMix64 stream (the robustness.py pattern; bit-exact on every
# platform), the geometric rung is a fixed rotation, and the fax rungs are anisotropic renders.
# Parameters are chosen inside the ranges the document-image degradation literature states (the
# return gives no grayscale-noise or bleed-through row) and are NOT calibrated against real captures:
# the synthetic-vs-real gap measured at 150/300 DPI sat inside +-4 pts, so the ladder stands as a
# conservative lower bound and stays as written.
# --------------------------------------------------------------------------------------------------
_SKEW_DEGREES = 1.5
_JPEG_QUALITY = {"jpeg85": 85, "jpeg70": 70}
_NOISE_SIGMA = 12.0  # gray levels of 255, additive Gaussian at 150 DPI
_NOISE_SALT_PEPPER = 0.005  # fraction of pixels forced to 0 or 255
_BLEED_ALPHA = 0.18  # how much of the verso's ink shows through
_BLEED_CONTRAST = (40, 225)  # black / white end points after contrast loss
_FAX_DPI = {"fax98": (204, 98), "fax196": (204, 196)}  # CCITT standard / fine
_FAX_THRESHOLD = 128


def _rotate_corners(b, degrees=_SKEW_DEGREES):
    """The four corners (TL, TR, BR, BL) of a normalized bbox after the skew-rung rotation, in
    normalized bottom-left coordinates.

    PIL's ``Image.rotate(degrees)`` turns the page content ``degrees`` counter-clockwise (as
    viewed) about the image center; the full-page raster makes that the page center. The rotation
    is isotropic in POINT space, not in normalized units (letter pages are not square), so the
    corners are rotated in points and re-normalized.
    """
    import math

    cx, cy = PW / 2.0, PH / 2.0
    th = math.radians(degrees)
    cos_t, sin_t = math.cos(th), math.sin(th)
    x0, y0, x1, y1 = b[0] * PW, b[1] * PH, b[2] * PW, b[3] * PH
    out = []
    for px, py in ((x0, y1), (x1, y1), (x1, y0), (x0, y0)):
        dx, dy = px - cx, py - cy
        out.append(((cx + dx * cos_t - dy * sin_t) / PW, (cy + dx * sin_t + dy * cos_t) / PH))
    return out


def _skew_polygon(b, degrees=_SKEW_DEGREES):
    """The rotated quad of a normalized bbox: the polygon-primary ground truth of the skew rung
    (``tools/register_capture.py``'s shape -- [[x, y], ...] TL, TR, BR, BL, bottom-left origin)."""
    return [[round(x, 6), round(y, 6)] for x, y in _rotate_corners(b, degrees)]


def _skew_bbox_hull(b, degrees=_SKEW_DEGREES):
    """Axis-aligned hull of the rotated quad -- the bbox consumers that need a box read."""
    corners = _rotate_corners(b, degrees)
    xs = [x for x, _y in corners]
    ys = [y for _x, y in corners]
    hull = [min(xs), min(ys), max(xs), max(ys)]
    return [round(max(0.0, min(1.0, v)), 6) for v in hull]


def _bbox_polygon(b):
    """A bbox as its own quad (TL, TR, BR, BL) -- the polygon column of a rung that keeps the
    master's geometry, so every rung row is polygon-primary."""
    x0, y0, x1, y1 = b
    return [[x0, y1], [x1, y1], [x1, y0], [x0, y0]]


def _degrade_gt(gt: dict, rung, source: str) -> dict:
    """Ground truth for one degrade rung: leg ["ocr"], a polygon beside every box, geometry per
    rung (the skew rung rotates; every other rung inherits the master's boxes)."""
    vgt = json.loads(json.dumps(gt))  # deep copy; bboxes are resolution-independent
    vgt["variant"] = {
        "kind": "degrade",
        "rung": rung.name,
        "source": source,
        "rasterized": True,
        "text_layer": False,
        "gt_geometry": (
            f"polygon = the box rotated {_SKEW_DEGREES:.1f}deg about the page center; "
            "bbox = its axis-aligned hull"
        )
        if rung.skewed
        else "inherited (unchanged); polygon = the box's own corners",
        "seed": rung.seed,
        "note": rung.note,
    }
    for r in _rows_with_geometry(vgt):
        r["leg_applicability"] = ["ocr"]  # image-only -> OCR leg only
        if r.get("bbox") is None:
            continue
        if rung.skewed:
            r["polygon"] = _skew_polygon(r["bbox"])
            r["bbox"] = _skew_bbox_hull(r["bbox"])
            for sp in r["spans"]:
                sp["polygon"] = _skew_polygon(sp["bbox"])
                sp["bbox"] = _skew_bbox_hull(sp["bbox"])
        else:
            r["polygon"] = _bbox_polygon(r["bbox"])
            for sp in r["spans"]:
                sp["polygon"] = _bbox_polygon(sp["bbox"])
    return vgt


def _splitmix64_bytes(seed: int, n: int):
    """``n`` deterministic bytes from a SplitMix64 stream seeded with ``seed`` (integer arithmetic
    only; the same bytes on every platform). The robustness.py pattern, vectorized."""
    import numpy as np

    words = (n + 7) // 8
    k = np.arange(1, words + 1, dtype=np.uint64)
    with np.errstate(over="ignore"):
        z = np.uint64(seed & 0xFFFFFFFFFFFFFFFF) + k * np.uint64(0x9E3779B97F4A7C15)
        z = (z ^ (z >> np.uint64(30))) * np.uint64(0xBF58476D1CE4E5B9)
        z = (z ^ (z >> np.uint64(27))) * np.uint64(0x94D049BB133111EB)
        z = z ^ (z >> np.uint64(31))
    return z.view(np.uint8)[:n]


class _Master:
    """One source document of the ladder: its bytes, its ground truth, and the 150-DPI raster the
    photometric rungs start from (rendered once)."""

    def __init__(self, name: str, pdf: bytes, gt: dict, *, title_prefix: str, id_prefix: bytes):
        self.name = name
        self.pdf = pdf
        self.gt = gt
        self.title_prefix = title_prefix
        self.id_prefix = id_prefix
        self._base = None

    @property
    def base150(self):
        if self._base is None:
            self._base = _rasterize(self.pdf, 150)
        return self._base


def _rung_skew(m: _Master, _seed):
    from PIL import Image

    # small rotation, white fill (no random)
    return [
        im.rotate(_SKEW_DEGREES, resample=Image.Resampling.BILINEAR, expand=False, fillcolor=255)
        for im in m.base150
    ]


def _rung_blur(m: _Master, _seed):
    from PIL import Image

    # downscale 50% then back up (deterministic softening)
    return [
        im.resize((im.width // 2, im.height // 2), Image.Resampling.BILINEAR).resize(
            im.size, Image.Resampling.BILINEAR
        )
        for im in m.base150
    ]


def _rung_lowdpi(dpi: int):
    def fn(m: _Master, _seed):
        return _rasterize(m.pdf, dpi)  # re-rasterize the source at the lower DPI

    return fn


def _rung_jpeg(quality: int):
    def fn(m: _Master, _seed):
        from PIL import Image

        out = []
        for im in m.base150:
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=quality, optimize=False)
            buf.seek(0)
            out.append(Image.open(buf).convert("L"))
        return out

    return fn


def _rung_noise(m: _Master, seed: int):
    """Additive Gaussian noise (sigma _NOISE_SIGMA) + salt-and-pepper (_NOISE_SALT_PEPPER), both
    drawn from the seeded integer stream: the Gaussian term is the sum of four uniform bytes
    (Irwin-Hall, sigma 147.8 gray levels) rescaled, so no libm call enters the bytes."""
    import numpy as np
    from PIL import Image

    out = []
    scale = _NOISE_SIGMA / 147.8
    sp_lo = round(_NOISE_SALT_PEPPER / 2.0 * 65536)
    for index, im in enumerate(m.base150):
        arr = np.asarray(im, dtype=np.int16)
        n = arr.size
        page_seed = seed + 0x1000 * (index + 1)
        u = _splitmix64_bytes(page_seed, 4 * n).reshape(n, 4).astype(np.int16)
        gauss = np.rint((u.sum(axis=1) - 510) * scale).astype(np.int16).reshape(arr.shape)
        noisy = np.clip(arr + gauss, 0, 255)
        u16 = _splitmix64_bytes(page_seed ^ 0xA5A5, 2 * n).view(np.uint16).reshape(arr.shape)
        noisy = np.where(u16 < sp_lo, 0, noisy)
        noisy = np.where(u16 >= 65536 - sp_lo, 255, noisy)
        out.append(Image.fromarray(noisy.astype(np.uint8), mode="L"))
    return out


def _rung_bleed(m: _Master, _seed):
    """Duplex show-through: the verso (page i ^ 1, mirrored) darkens the recto by _BLEED_ALPHA of
    its ink, then the whole page loses contrast to _BLEED_CONTRAST. Pure lookup tables."""
    from PIL import ImageChops, ImageOps

    base = m.base150
    show = [round(255 - _BLEED_ALPHA * (255 - v)) for v in range(256)]
    lo, hi = _BLEED_CONTRAST
    squash = [round(lo + v * (hi - lo) / 255.0) for v in range(256)]
    out = []
    for index, im in enumerate(base):
        verso = index ^ 1
        page = im
        if verso < len(base):
            page = ImageChops.darker(im, ImageOps.mirror(base[verso]).point(show))
        out.append(page.point(squash))
    return out


def _rung_fax(dpi_x: int, dpi_y: int):
    def fn(m: _Master, _seed):
        # anisotropic render, fixed threshold -> 1-bit content (kept in an 8-bit container), then
        # _images_to_pdf stretches the page back to letter as a fax printout would
        return [
            im.point(lambda v: 255 if v >= _FAX_THRESHOLD else 0)
            for im in _rasterize(m.pdf, dpi_x, dpi_y)
        ]

    return fn


class Rung:
    """One row of the ladder: name, title fragment, /ID stem (<= 10 ASCII chars), the image
    function, the ground-truth note, the seed (None = the transform draws no entropy)."""

    def __init__(self, name, part, id_stem, image_fn, note, *, seed=None, skewed=False):
        self.name = name
        self.part = part
        self.id_stem = id_stem
        self.image_fn = image_fn
        self.note = note
        self.seed = seed
        self.skewed = skewed


_RUNGS = (
    Rung(
        "skew",
        "degrade skew 1.5deg",
        "DegSkew01",
        _rung_skew,
        "150 DPI raster rotated 1.5deg CCW about the page center.",
        skewed=True,
    ),
    Rung(
        "blur",
        "degrade blur",
        "DegBlur01",
        _rung_blur,
        "150 DPI raster softened by a 50% down/up resample.",
    ),
    Rung(
        "lowdpi",
        "degrade low-DPI 100",
        "DegLow100",
        _rung_lowdpi(100),
        "Source re-rasterized at 100 DPI.",
    ),
    Rung(
        "lowdpi75",
        "degrade low-DPI 75",
        "DegLow075",
        _rung_lowdpi(75),
        "Source re-rasterized at 75 DPI.",
    ),
    Rung(
        "jpeg85",
        "degrade JPEG QF 85",
        "DegJpg085",
        _rung_jpeg(85),
        "150 DPI raster JPEG-encoded at quality 85 and decoded (scanner-software class).",
    ),
    Rung(
        "jpeg70",
        "degrade JPEG QF 70",
        "DegJpg070",
        _rung_jpeg(70),
        "150 DPI raster JPEG-encoded at quality 70 and decoded (phone-camera floor).",
    ),
    Rung(
        "noise",
        "degrade noise",
        "DegNoise1",
        _rung_noise,
        "150 DPI raster + seeded additive Gaussian noise (sigma 12/255) + 0.5% salt-and-pepper "
        "(SplitMix64 stream; integer arithmetic only).",
        seed=0x5E1D_2026_0917,
    ),
    Rung(
        "bleed",
        "degrade bleed-through",
        "DegBleed1",
        _rung_bleed,
        "150 DPI raster with the duplex verso (page i^1) mirrored and shown through at 18% of "
        "its ink, then contrast compressed to [40, 225].",
    ),
    Rung(
        "fax98",
        "degrade fax 204x98",
        "DegFax098",
        _rung_fax(204, 98),
        "Source rendered at 204x98 DPI (CCITT standard), thresholded at 50% to 1-bit content, "
        "stretched back to the page.",
    ),
    Rung(
        "fax196",
        "degrade fax 204x196",
        "DegFax196",
        _rung_fax(204, 196),
        "Source rendered at 204x196 DPI (CCITT fine), thresholded at 50% to 1-bit content, "
        "stretched back to the page.",
    ),
)
RUNG_NAMES = tuple(r.name for r in _RUNGS)


def degrade_ladder(packet_pdf: bytes, gt: dict, *, master: _Master | None = None):
    """Every `_RUNGS` row over one master -> {rung name: (pdf bytes, ground truth)}.

    The default master is the Hartwell packet (the historical signature); `master` names another
    source (the capture masters) with its own title prefix and /ID prefix.
    """
    m = master or _Master(
        "packet", packet_pdf, gt, title_prefix="Hartwell Packet", id_prefix=b"ResectaPacket"
    )
    rungs = {}
    for rung in _RUNGS:
        images = rung.image_fn(m, rung.seed)
        pdf = _images_to_pdf(
            images,
            f"{m.title_prefix} -- {rung.part} (test-only)",
            m.id_prefix + rung.id_stem.encode(),
        )
        rungs[rung.name] = (pdf, _degrade_gt(m.gt, rung, m.name))
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
def _capture_master() -> _Master:
    """The frozen capture masters, rebuilt in memory and asserted against their pin -- the ladder
    rasters exactly the bytes the device captures were printed from."""
    import hashlib

    from . import build_capture as BC

    cap = BC.build(write=False)
    got = hashlib.sha256(cap["pdf"]).hexdigest()
    if got != BC.MASTERS_SHA256:
        raise SystemExit(
            "MASTERS TRIPWIRE: the capture masters no longer match their pin.\n"
            f"  expected {BC.MASTERS_SHA256}\n  rebuilt  {got}"
        )
    return _Master(
        "capture-masters-2026-08",
        cap["pdf"],
        cap["ground_truth"],
        title_prefix=CAPTURE_SET_ID,
        id_prefix=b"ResectaCapture",
    )


CAPTURE_STEM = "capture-masters-2026-08"


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
    cap = _capture_master()
    cap_ss = scan_sim(
        cap.pdf,
        cap.gt,
        title=f"{CAPTURE_SET_ID} -- scan-sim 150 DPI (test-only)",
        doc_id=b"ResectaCaptureScanSim1",
    )
    cap_deg = degrade_ladder(cap.pdf, cap.gt, master=cap)
    out = {
        "scan_sim": (ss_pdf, ss_gt),
        "rotate_trigger": (rt_pdf, rt_gt),
        "degrade": deg,
        "perf": perf,
        "capture_scan_sim": cap_ss,
        "capture_degrade": cap_deg,
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
        (OUTDIR / f"{CAPTURE_STEM}-scan-sim-150dpi.pdf").write_bytes(cap_ss[0])
        (OUTDIR / f"{CAPTURE_STEM}-scan-sim-150dpi-ground-truth.json").write_text(
            json.dumps(cap_ss[1], indent=2) + "\n", encoding="ascii"
        )
        for name, (pdf, dgt) in cap_deg.items():
            (OUTDIR / f"{CAPTURE_STEM}-degrade-{name}.pdf").write_bytes(pdf)
            (OUTDIR / f"{CAPTURE_STEM}-degrade-{name}-ground-truth.json").write_text(
                json.dumps(dgt, indent=2) + "\n", encoding="ascii"
            )
    return out


def main() -> None:
    out = build_all()
    print(f"scan-sim:       {len(out['scan_sim'][0]):,} bytes (image-only, OCR leg)")
    print(f"rotate-trigger: {len(out['rotate_trigger'][0]):,} bytes (/Rotate 90; transformed GT)")
    for name, (pdf, _dgt) in out["degrade"].items():
        print(f"degrade/{name:8s} {len(pdf):,} bytes (+ transformed ground truth)")
    print(f"perf-filler:    {len(out['perf']):,} bytes")
    print(f"capture scan-sim: {len(out['capture_scan_sim'][0]):,} bytes (16 pp, OCR leg)")
    for name, (pdf, _dgt) in out["capture_degrade"].items():
        print(f"capture degrade/{name:8s} {len(pdf):,} bytes (+ transformed ground truth)")
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
        bottom = w[3]
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
    resources = cast(DictionaryObject, page["/Resources"].get_object())
    fonts_raw = resources.get("/Font")
    fonts = cast(DictionaryObject, fonts_raw.get_object()) if fonts_raw is not None else None
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
        props_raw = resources.get("/Properties")
        props = cast(DictionaryObject, props_raw.get_object()) if props_raw is not None else None
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
        arr = ArrayObject([*existing, stream_ref])
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
