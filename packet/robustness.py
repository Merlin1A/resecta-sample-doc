"""robustness.py -- Family-4 fixtures (T4.1 / T4.2 / T4.4): scale + robustness inputs.

All fixtures derive from the canonical packet (fictional-space discipline carries) and are
deterministic byte-for-byte across rebuilds (pinned metadata + /ID via variants._finalize;
the encrypted variants pin pypdf's salt/IV randomness to a seeded SplitMix64 stream for the
build -- IV quality is irrelevant in a public test fixture, reproducibility is not).

  huge-4999       packet page 0 scaled aspect-true so the LONG side is 4,999 pt -- just under
                  the engine's 5,000 pt validatePage pre-flight and the import dimension cap.
                  Normalized ground truth carries verbatim (full-bleed placement).
  huge-5001       same, long side 5,001 pt -- import must REJECT (invalidPageDimensions).
  repeat-500pp    packet x 42 trimmed to exactly 500 pages (the import cap boundary: 500
                  passes, 501 rejects) WITH ground truth (page offsets, copy-suffixed ids).
  filler-501pp    the perf filler built past its 200-page clamp (variants.perf_filler
                  clamp=False) -- import must REJECT (tooLarge, page-count cap).
  encrypted x3    packet encrypted RC4-128 / AES-128 / AES-256 with EMPTY user password --
                  PDFKit must open these unlocked (isLocked == false).
  locked          AES-256 with a user password set -- import must REJECT (passwordProtected).
                  Password (public test fixture): resecta-locked-2026

Sidecar: robustness/robustness-fixtures.json -- one row per fixture with the EXPECTED
outcome per pipeline leg (engine PipelineError.ImportError taxonomy strings). H4.2
(RobustnessRunnerTests) reads this manifest via RESECTA_DOCS_ROOT; rows here never touch
documents.manifest.json (T1.4 stays byte-stable -- the PB-86 DOCS_ROOT-direct precedent).

Run with: .venv/bin/python -m packet.robustness
"""
from __future__ import annotations

import hashlib
import io
import json
from contextlib import contextmanager
from pathlib import Path

from . import build_packet as B
from . import variants as V

REPO = Path(__file__).resolve().parent.parent
OUTDIR = REPO / "robustness"

_LOCKED_USER_PW = "resecta-locked-2026"


# --------------------------------------------------------------------------------------------------
# deterministic stand-in for pypdf's encryption randomness (salts + AES IVs)
# --------------------------------------------------------------------------------------------------
class _DetTokenBytes:
    """SplitMix64-backed drop-in for secrets.token_bytes (build-time only)."""

    def __init__(self, seed: int):
        self._state = seed & 0xFFFFFFFFFFFFFFFF

    def __call__(self, n: int) -> bytes:
        out = bytearray()
        while len(out) < n:
            self._state = (self._state + 0x9E3779B97F4A7C15) & 0xFFFFFFFFFFFFFFFF
            z = self._state
            z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & 0xFFFFFFFFFFFFFFFF
            z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & 0xFFFFFFFFFFFFFFFF
            out += (z ^ (z >> 31)).to_bytes(8, "big")
        return bytes(out[:n])


@contextmanager
def _pinned_encryption_rng(seed: int):
    import secrets

    orig = secrets.token_bytes
    secrets.token_bytes = _DetTokenBytes(seed)
    try:
        yield
    finally:
        secrets.token_bytes = orig


# --------------------------------------------------------------------------------------------------
# T4.1 -- huge page (IM-17)
# --------------------------------------------------------------------------------------------------
def huge_page(packet_pdf: bytes, gt: dict, long_side_pt: float = 4999.0):
    """Packet page 0 scaled aspect-true to `long_side_pt` on the long (792 pt) side.

    Full-bleed placement => normalized ground-truth bboxes carry VERBATIM.
    Returns (pdf_bytes, gt_dict | None) -- GT only for the openable 4,999 variant.
    """
    import fitz

    scale = long_side_pt / V.PH
    w, h = V.PW * scale, long_side_pt
    src = fitz.open(stream=packet_pdf, filetype="pdf")
    doc = fitz.open()
    page = doc.new_page(width=w, height=h)
    page.show_pdf_page(fitz.Rect(0, 0, w, h), src, 0)
    # A bare fitz doc writes no /Info dict; pypdf's add_metadata (inside
    # variants._finalize) asserts one exists. The stub is overwritten there.
    doc.set_metadata({"title": "stub"})
    raw = doc.tobytes()
    doc.close()
    src.close()
    tag = str(int(long_side_pt))
    pdf = V._finalize(raw, f"Hartwell Packet -- huge page {tag}pt (test-only)",
                      b"ResectaPacketHuge" + tag.encode("ascii"))

    if long_side_pt > 5000:
        return pdf, None
    vgt = json.loads(json.dumps(gt))
    vgt["page_count"] = 1
    vgt["page_size_pt"] = [round(w, 3), round(h, 3)]
    vgt["variant"] = {
        "kind": "huge_page", "long_side_pt": long_side_pt, "source_page": 0,
        "gt_geometry": "inherited (full-bleed aspect-true scale; normalized boxes unchanged)",
    }
    vgt["occurrences"] = [
        o for o in vgt["occurrences"]
        if (o.get("page") == 0 if o.get("spans") is None
            else all(s["page"] == 0 for s in o["spans"]))
    ]
    vgt.pop("carried_stmt", None)
    for o in vgt["occurrences"]:
        # A 4,999 pt page rasterizes to a ~10,400 px bitmap at 150 DPI -- the OCR
        # leg is out of scope for this fixture; the text layer carries.
        o["leg_applicability"] = ["text"]
    return pdf, vgt


# --------------------------------------------------------------------------------------------------
# T4.2 -- many pages (IM-18)
# --------------------------------------------------------------------------------------------------
def packet_repeat(packet_pdf: bytes, gt: dict, pages: int = 500):
    """packet x ceil(pages/12) trimmed to exactly `pages`, WITH page-offset ground truth.

    Built with pypdf (writer object-map dedup: repeated appends of the same reader's
    pages share font/resource objects instead of embedding 42 copies).
    """
    from pypdf import PdfReader, PdfWriter

    src_pages = gt["page_count"]
    reader = PdfReader(io.BytesIO(packet_pdf))
    writer = PdfWriter()
    copies = -(-pages // src_pages)
    for _ in range(copies):
        for p in reader.pages:
            writer.add_page(p)
    while len(writer.pages) > pages:
        del writer.pages[len(writer.pages) - 1]
    buf = io.BytesIO()
    writer.write(buf)
    pdf = V._finalize(buf.getvalue(), f"Hartwell Packet -- repeat {pages}pp (test-only)",
                      b"ResectaPacketRepeat500")

    vgt = json.loads(json.dumps(gt))
    vgt["page_count"] = pages
    vgt["variant"] = {
        "kind": "packet_repeat", "pages": pages, "copies": copies,
        "gt_geometry": "inherited per copy; page indices offset by 12 x copy",
    }
    out_occ = []
    for k in range(copies):
        off = k * src_pages
        for o in gt["occurrences"]:
            span_pages = ([s["page"] for s in o["spans"]] if o.get("spans")
                          else [o["page"]])
            if any(p + off >= pages for p in span_pages):
                continue
            c = json.loads(json.dumps(o))
            c["id"] = f"{o['id']}--r{k:02d}"
            if c.get("page") is not None:
                c["page"] += off
            for s in c.get("spans") or []:
                s["page"] += off
            out_occ.append(c)
    vgt["occurrences"] = out_occ
    vgt.pop("carried_stmt", None)
    return pdf, vgt


# --------------------------------------------------------------------------------------------------
# T4.4 -- encrypted input (IM-22)
# --------------------------------------------------------------------------------------------------
_ALGOS = {"rc4": "RC4-128", "aes128": "AES-128", "aes256": "AES-256"}


def encrypted(packet_pdf: bytes, algo: str, user_pw: str = "", owner_pw: str = "resecta-owner"):
    """Packet encrypted with `algo`; empty user_pw => opens unlocked in PDFKit."""
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import ArrayObject, ByteStringObject

    reader = PdfReader(io.BytesIO(packet_pdf))
    writer = PdfWriter(clone_from=reader)
    creator = "Resecta Sample Packet Generator (variant)"
    label = "locked" if user_pw else algo
    writer.add_metadata({
        "/Title": f"Hartwell Packet -- encrypted {label} (test-only)",
        "/Author": "Resecta", "/Creator": creator, "/Producer": creator,
        "/CreationDate": "D:20260614000000Z", "/ModDate": "D:20260614000000Z",
    })
    fid = ByteStringObject(f"ResectaPacketEnc{label}".encode("ascii").ljust(24, b"0")[:24])
    writer._ID = ArrayObject([fid, fid])
    seed = int.from_bytes(hashlib.sha256(f"resecta-f4-{label}".encode()).digest()[:8], "big")
    with _pinned_encryption_rng(seed):
        writer.encrypt(user_password=user_pw, owner_password=owner_pw,
                       algorithm=_ALGOS[algo])
        buf = io.BytesIO()
        writer.write(buf)
    return buf.getvalue()


# --------------------------------------------------------------------------------------------------
# build + sidecar manifest
# --------------------------------------------------------------------------------------------------
def _sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _self_check(name: str, pdf: bytes, pages: int, must_contain: str | None):
    """Every openable fixture proves itself at build (T3.1 self-verifying precedent)."""
    import fitz

    doc = fitz.open(stream=pdf, filetype="pdf")
    assert doc.page_count == pages, f"{name}: {doc.page_count} pages, expected {pages}"
    if must_contain is not None:
        text = doc[0].get_text()
        assert must_contain in text, f"{name}: page-0 text layer missing {must_contain!r}"
    doc.close()


def build_family4(write: bool = True) -> dict:
    if not V._have_fitz():
        raise SystemExit("family-4 fixtures require PyMuPDF (fitz)")
    res = B.build(write=False)
    packet_pdf, gt = res["pdf"], res["ground_truth"]
    probe = gt["occurrences"][0]["value"]          # "Delia R. Hartwell", page 0

    h4999, h4999_gt = huge_page(packet_pdf, gt, 4999.0)
    h5001, _ = huge_page(packet_pdf, gt, 5001.0)
    rep500, rep500_gt = packet_repeat(packet_pdf, gt, 500)
    fil501 = V.perf_filler(501, clamp=False)
    enc = {a: encrypted(packet_pdf, a) for a in _ALGOS}
    locked = encrypted(packet_pdf, "aes256", user_pw=_LOCKED_USER_PW)

    _self_check("huge-4999", h4999, 1, probe)
    _self_check("huge-5001", h5001, 1, probe)
    _self_check("repeat-500pp", rep500, 500, probe)
    _self_check("filler-501pp", fil501, 501, None)
    for a, b_ in enc.items():
        _self_check(f"encrypted-{a}", b_, 12, probe)   # fitz opens empty-user-pw transparently

    rows = [
        {"id": "packet-huge-4999", "path": "robustness/packet-huge-4999.pdf", "pages": 1,
         "gt": "robustness/packet-huge-4999-ground-truth.json",
         "expected": {"import": "open", "import_error": None, "scan": True,
                      "redact": "open", "redact_error": None},
         "notes": "long side 4,999 pt -- inside both the import dimension cap and the "
                  "validatePage 5,000 pt pre-flight; text leg only."},
        {"id": "packet-huge-5001", "path": "robustness/packet-huge-5001.pdf", "pages": 1,
         "gt": None,
         "expected": {"import": "reject", "import_error": "invalidPageDimensions",
                      "scan": False, "redact": "skip", "redact_error": None},
         "notes": "long side 5,001 pt -- import per-page dimension guard must reject."},
        {"id": "packet-repeat-500pp", "path": "robustness/packet-repeat-500pp.pdf", "pages": 500,
         "gt": "robustness/packet-repeat-500pp-ground-truth.json",
         "expected": {"import": "open", "import_error": None, "scan": True,
                      "redact": "skip_v0", "redact_error": None},
         "notes": "exactly AT the 500-page import cap (must open). v0 runs import+scan; "
                  "the 500-pp redact/verify leg rides the perf track (H4.1 device / IM-18)."},
        {"id": "perf-filler-501pp", "path": "robustness/perf-filler-501pp.pdf", "pages": 501,
         "gt": None,
         "expected": {"import": "reject", "import_error": "tooLarge",
                      "scan": False, "redact": "skip", "redact_error": None},
         "notes": "one past the page-count cap -- import must reject tooLarge."},
    ]
    for a in _ALGOS:
        rows.append({
            "id": f"packet-encrypted-{a}", "path": f"robustness/packet-encrypted-{a}.pdf",
            "pages": 12, "gt": None,
            "expected": {"import": "open", "import_error": None, "scan": True,
                         "redact": "open", "redact_error": None},
            "notes": f"{_ALGOS[a]}, empty user password -- PDFKit opens unlocked "
                     "(isLocked false); content identical to packet post-decrypt."})
    rows.append({
        "id": "packet-encrypted-locked", "path": "robustness/packet-encrypted-locked.pdf",
        "pages": 12, "gt": None,
        "expected": {"import": "reject", "import_error": "passwordProtected",
                     "scan": False, "redact": "skip", "redact_error": None},
        "notes": f"AES-256 with a user password set (fixture password: {_LOCKED_USER_PW}) "
                 "-- import must reject passwordProtected."})

    blobs = {
        "robustness/packet-huge-4999.pdf": h4999,
        "robustness/packet-huge-5001.pdf": h5001,
        "robustness/packet-repeat-500pp.pdf": rep500,
        "robustness/perf-filler-501pp.pdf": fil501,
        "robustness/packet-encrypted-rc4.pdf": enc["rc4"],
        "robustness/packet-encrypted-aes128.pdf": enc["aes128"],
        "robustness/packet-encrypted-aes256.pdf": enc["aes256"],
        "robustness/packet-encrypted-locked.pdf": locked,
    }
    for row in rows:
        row["sha256"] = _sha256(blobs[row["path"]])

    manifest = {
        "schema_version": 1,
        "generator": "packet/robustness.py (T4.1/T4.2/T4.4, P1.6)",
        "taxonomy": "engine PipelineError.ImportError case names; redact classes as measured",
        "fixtures": rows,
    }

    if write:
        OUTDIR.mkdir(exist_ok=True)
        for rel, data in blobs.items():
            (REPO / rel).write_bytes(data)
        (OUTDIR / "packet-huge-4999-ground-truth.json").write_text(
            json.dumps(h4999_gt, indent=2) + "\n", encoding="ascii")
        (OUTDIR / "packet-repeat-500pp-ground-truth.json").write_text(
            json.dumps(rep500_gt, indent=2) + "\n", encoding="ascii")
        (OUTDIR / "robustness-fixtures.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="ascii")
    return {"blobs": blobs, "manifest": manifest,
            "gt": {"huge4999": h4999_gt, "repeat500": rep500_gt}}


def main() -> None:
    out = build_family4()
    for rel, data in out["blobs"].items():
        print(f"{rel:48s} {len(data):>10,} bytes  {_sha256(data)[:16]}")
    print(f"-> {OUTDIR}")


if __name__ == "__main__":
    main()
