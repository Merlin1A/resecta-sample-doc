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
  perf-filler    a 50-200 pp dense born-digital filler (no firing PII) targeting the apply-phase
                 memory cliff.

Rasterization needs PyMuPDF (fitz). Run with: .venv/bin/python -m packet.variants
"""
from __future__ import annotations

import io
import json
from pathlib import Path

from reportlab import rl_config
rl_config.invariant = 1  # noqa: E402

from reportlab.pdfgen import canvas  # noqa: E402
from reportlab.lib.pagesizes import letter  # noqa: E402
from reportlab.lib.utils import ImageReader  # noqa: E402

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
    w.add_metadata({"/Title": title, "/Author": "Resecta", "/Creator": creator, "/Producer": creator,
                    "/CreationDate": "D:20260614000000Z", "/ModDate": "D:20260614000000Z"})
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
        c.drawImage(ImageReader(png), 0, 0, width=PW, height=PH,
                    preserveAspectRatio=False, mask=None)
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
    pdf = _images_to_pdf(images, f"Hartwell Packet -- scan-sim {dpi} DPI (test-only)",
                         b"ResectaPacketScanSim150")
    vgt = json.loads(json.dumps(gt))   # deep copy; bboxes are resolution-independent
    vgt["variant"] = {"kind": "scan-sim", "dpi": dpi, "rasterized": True, "text_layer": False}
    for r in vgt["occurrences"]:
        r["leg_applicability"] = ["ocr"]   # image-only -> OCR leg only
    return pdf, vgt


# --------------------------------------------------------------------------------------------------
# rotate-trigger (/Rotate 90; transformed ground truth; FAILS until the engine rotated-coord fix)
# --------------------------------------------------------------------------------------------------
def _rotate_bbox_90(b):
    """(nx,ny) bottom-left -> /Rotate 90 clockwise display space: (nx,ny)->(ny,1-nx).
    bbox [x0,y0,x1,y1] -> [y0, 1-x1, y1, 1-x0]."""
    x0, y0, x1, y1 = b
    return [round(y0, 6), round(1 - x1, 6), round(y1, 6), round(1 - x0, 6)]


def rotate_trigger(packet_pdf: bytes, gt: dict, degrees: int = 90):
    from pypdf import PdfReader, PdfWriter
    r = PdfReader(io.BytesIO(packet_pdf))
    w = PdfWriter(clone_from=r)
    for page in w.pages:
        page.rotate(degrees)
    out = io.BytesIO()
    w.write(out)
    pdf = _finalize(out.getvalue(), "Hartwell Packet -- rotate-trigger 90deg (test-only)",
                    b"ResectaPacketRotate90")
    vgt = json.loads(json.dumps(gt))
    vgt["variant"] = {"kind": "rotate-trigger", "rotate_degrees": degrees,
                      "note": "TRIGGER for the open rotated-coordinate P0; FAILS until the engine "
                              "fix lands. bbox transformed (nx,ny)->(ny,1-nx)."}
    for rec in vgt["occurrences"]:
        rec["bbox"] = _rotate_bbox_90(rec["bbox"])
        for s in rec["spans"]:
            s["bbox"] = _rotate_bbox_90(s["bbox"])
    return pdf, vgt


# --------------------------------------------------------------------------------------------------
# degrade ladder (skew / blur / low-DPI), off the 150-DPI raster -- deterministic transforms
# --------------------------------------------------------------------------------------------------
def degrade_ladder(packet_pdf: bytes):
    from PIL import Image
    base = _rasterize(packet_pdf, 150)
    rungs = {}
    # skew: small rotation, white fill (no random)
    skew = [im.rotate(1.5, resample=Image.BILINEAR, expand=False, fillcolor=255) for im in base]
    rungs["skew"] = _images_to_pdf(skew, "Hartwell Packet -- degrade skew 1.5deg (test-only)",
                                   b"ResectaPacketDegSkew01")
    # blur: downscale 50% then back up (deterministic softening)
    blur = [im.resize((im.width // 2, im.height // 2), Image.BILINEAR).resize(im.size, Image.BILINEAR)
            for im in base]
    rungs["blur"] = _images_to_pdf(blur, "Hartwell Packet -- degrade blur (test-only)",
                                   b"ResectaPacketDegBlur01")
    # low-DPI: re-rasterize the source at 100 DPI
    low = _rasterize(packet_pdf, 100)
    rungs["lowdpi"] = _images_to_pdf(low, "Hartwell Packet -- degrade low-DPI 100 (test-only)",
                                     b"ResectaPacketDegLow100")
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


def perf_filler(pages: int = 120) -> bytes:
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
        c.drawString(margin, margin - 12, "Synthetic perf/jetsam filler -- not real; no PII; fictional.")
        c.showPage()
    c.save()
    return _finalize(buf.getvalue(), f"Hartwell Packet -- perf filler {pages}pp (test-only)",
                     b"ResectaPacketPerfFill01")


# --------------------------------------------------------------------------------------------------
def build_all(perf_pages: int = 120, *, write=True) -> dict:
    if not _have_fitz():
        raise SystemExit("variants require PyMuPDF (fitz): pip install pymupdf  (or uv sync)")
    res = B.build(write=False)
    packet_pdf, gt = res["pdf"], res["ground_truth"]
    out = {}
    ss_pdf, ss_gt = scan_sim(packet_pdf, gt)
    rt_pdf, rt_gt = rotate_trigger(packet_pdf, gt)
    deg = degrade_ladder(packet_pdf)
    perf = perf_filler(perf_pages)
    out = {"scan_sim": (ss_pdf, ss_gt), "rotate_trigger": (rt_pdf, rt_gt),
           "degrade": deg, "perf": perf}
    if write:
        OUTDIR.mkdir(exist_ok=True)
        (OUTDIR / "packet-scan-sim-150dpi.pdf").write_bytes(ss_pdf)
        (OUTDIR / "packet-scan-sim-150dpi-ground-truth.json").write_text(
            json.dumps(ss_gt, indent=2) + "\n", encoding="ascii")
        (OUTDIR / "packet-rotate-trigger.pdf").write_bytes(rt_pdf)
        (OUTDIR / "packet-rotate-trigger-ground-truth.json").write_text(
            json.dumps(rt_gt, indent=2) + "\n", encoding="ascii")
        for name, pdf in deg.items():
            (OUTDIR / f"packet-degrade-{name}.pdf").write_bytes(pdf)
        (OUTDIR / f"perf-filler-{perf_pages}pp.pdf").write_bytes(perf)
    return out


def main() -> None:
    out = build_all()
    print(f"scan-sim:       {len(out['scan_sim'][0]):,} bytes (image-only, OCR leg)")
    print(f"rotate-trigger: {len(out['rotate_trigger'][0]):,} bytes (/Rotate 90; transformed GT)")
    for name, pdf in out["degrade"].items():
        print(f"degrade/{name:7s} {len(pdf):,} bytes")
    print(f"perf-filler:    {len(out['perf']):,} bytes")
    print(f"-> {OUTDIR}")


if __name__ == "__main__":
    main()
