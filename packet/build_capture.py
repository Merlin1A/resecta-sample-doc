"""build_capture.py -- the CAPTURE-MASTER assembler (P1.8 / T1.3(a)): a SEPARATE 16-page print
document for the device capture Friday, plus its draw-time ground truth and a DOCS_ROOT-direct
marker sidecar.

**Why a sibling builder and not a parameter on build_packet.build() (D12-41).** `build_packet` is
the module that writes the sha256-frozen `packet.pdf`; every edit to it puts that freeze -- and with
it the T4.3 mutation base, the `packet` manifest row, every `robustness/` `planted/` `t23/` fixture,
the frozen search GT and M12-01..19 -- at risk. A sibling keeps the D12-40 tripwire STRUCTURAL
rather than behavioural: this module never writes `packet.pdf` and asserts at the end that the file
on disk is still byte-identical. The `build(assembly=..., write=False)` route would not have worked
as written in any case: `build()` hardcodes `OCC.BY_EXHIBIT` for its registered-vs-drawn assert
(capture occurrences live in `CAPTURE_BY_EXHIBIT`) and `_assemble()` hardcodes the STMT splice plus
the Hartwell `/Title` metadata. What IS genuinely shared is imported, not forked:
`build_packet._strip_default_helvetica`, the `_render_drawables` pattern, and the determinism recipe
(`rl_config.invariant` + pinned metadata + a fixed document `/ID`).

Final page order (0-indexed, matching PageDetectionResult.pageIndex):
    0..3   IMPORTED from packet.pdf -- pages 0, 5, 7, 9 (`31-` SSC.1 rows 01-04: urla_b p1, the
           frozen statement p3, t1040 p2, w2). Their ground truth is CARRIED FORWARD verbatim with
           the page index remapped; nothing is redrawn, so the values are bit-for-bit the packet's.
    4..15  the 12 NEW born-digital exhibits (`31-` SSC.1 rows 05-16), in class order:
           M1 M2 M3 M4 (C2 mail/forms) | K1 K2 K3 K4 (C3 court/FOIA) | H1 H2 H3 H4 (C4 medical/HR).

`variants.print_master()` then stamps four ArUco corner fiducials per page (ids 4*(page-1)..+3, in
the [18, 42] pt margin band the evaluated image is cropped back to) plus an ASCII footer, and returns
the per-page marker geometry that becomes the registration step's input.

Run with: .venv/bin/python -m packet.build_capture

Every character is printable ASCII.
"""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

from reportlab import rl_config

rl_config.invariant = 1  # must precede save; fixes dates + font subset tags

from reportlab.lib.pagesizes import letter  # noqa: E402
from reportlab.pdfgen import canvas  # noqa: E402

from . import build_packet as B  # noqa: E402
from . import layout as L  # noqa: E402
from . import occurrences_capture as OCC  # noqa: E402
from . import schema  # noqa: E402
from . import variants as V  # noqa: E402
from .generators import court, forms, hr, mail, medical  # noqa: E402
from .manifest import RecordingCanvas  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
PACKET_PDF = REPO / "packet.pdf"
OUT_PDF = REPO / "capture-masters-2026-08.pdf"
OUT_JSON = REPO / "capture-masters-2026-08-ground-truth.json"
OUT_MARKS = REPO / "capture-masters-2026-08-marks.json"

# The D12-40 tripwire: the frozen packet sha256. Asserted against the file on disk AND against a
# fresh in-memory rebuild at the end of every capture build.
PACKET_SHA256 = "362375692b8cff378d66c43fcf46f00ba09e1ea982602fcc5c8b70e96f54339a"

# The frozen capture masters (never re-cut; every derived variant rasters THESE bytes). Asserted by
# variants.build_all() before the capture ladder is built.
MASTERS_SHA256 = "96de0cb8c2cc00cf90e9a3a2969b1b3adc20e71501fd0fab101fa1e05b73a1b3"

# packet pages imported whole (0-indexed). `31-` SSC.1 rows 01-04 == acceptance check 13b's slice.
PACKET_SLICE = (0, 5, 7, 9)
PACKET_SLICE_LABEL = {0: "urla_b p1", 5: "stmt p3 (frozen)", 7: "t1040 p2", 9: "w2"}

# (exhibit name, draw fn) in final order; every exhibit is exactly one page.
CAPTURE_ASSEMBLY = [
    ("mail_m1", mail.draw_m1),
    ("mail_m2", mail.draw_m2),
    ("forms_m3", forms.draw_m3),
    ("forms_m4", forms.draw_m4),
    ("court_k1", court.draw_k1),
    ("court_k2", court.draw_k2),
    ("court_k3", court.draw_k3),
    ("court_k4", court.draw_k4),
    ("medical_h1", medical.draw_h1),
    ("medical_h2", medical.draw_h2),
    ("hr_h3", hr.draw_h3),
    ("hr_h4", hr.draw_h4),
]

DOC_ID = b"ResectaCaptureMaster01"
_PRE_DOC_ID = b"ResectaCaptureMasterPre0"


def _bases(assembly=CAPTURE_ASSEMBLY):
    """exhibit -> its 0-indexed page in the MASTER (the imported slice occupies 0..len-1)."""
    base = len(PACKET_SLICE)
    out = {}
    for name, _fn in assembly:
        out[name] = base
        base += 1
    return out, base


def _render_drawables(assembly, bases):
    """Render every capture exhibit onto ONE reportlab canvas, in assembly order (the
    build_packet._render_drawables pattern; the recording canvas emits the ground truth as a side
    effect of each rc.value*/region_value call)."""
    L.register_fonts()
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter, invariant=1, pageCompression=1)
    rc = RecordingCanvas(c, L.PW, L.PH)
    for name, fn in assembly:
        fn(rc, bases[name])
    c.save()
    rc.annotate_clearance()  # the caption-clearance column: a post-pass, once every page is drawn
    return buf.getvalue(), rc


def _assemble(form_pdf: bytes, packet_pdf: bytes) -> bytes:
    """Imported packet pages first, then the drawn pages; finalize deterministically. The metadata
    and /ID pinned here are provisional -- print_master's _finalize sets the shipping values -- but
    pinning them keeps THIS stage byte-stable too, so a determinism failure localizes."""
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import ArrayObject, ByteStringObject

    src = PdfReader(io.BytesIO(packet_pdf))
    drawn = PdfReader(io.BytesIO(form_pdf))
    writer = PdfWriter()
    for i in PACKET_SLICE:
        writer.add_page(src.pages[i])
    for p in drawn.pages:
        writer.add_page(p)

    B._strip_default_helvetica(writer)
    creator = "Resecta Sample Packet Generator (capture master)"
    writer.add_metadata(
        {
            "/Title": f"{V.CAPTURE_SET_ID} capture masters (synthetic sample)",
            "/Author": "Resecta",
            "/Subject": "Synthetic PII-dense capture masters for print-and-scan measurement",
            "/Creator": creator,
            "/Producer": creator,
            "/CreationDate": "D:20260614000000Z",
            "/ModDate": "D:20260614000000Z",
        }
    )
    fixed = ByteStringObject(_PRE_DOC_ID)
    writer._ID = ArrayObject([fixed, fixed])
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def _carry_packet_ground_truth(packet_gt: dict) -> tuple[list, dict]:
    """Carry the ground truth of the imported pages forward, remapping page indices into the master.

    Nothing is re-measured: the imported pages are the packet's own bytes, so their boxes are exact.
    Rows on packet pages the master does NOT import are DROPPED, and the FROZEN statement rows whose
    page is still unresolved (`measured_pending`, page null) are dropped too -- the master's ground
    truth states only what is provably on the master. Both counts are reported in the sidecar."""
    remap = {p: i for i, p in enumerate(PACKET_SLICE)}
    carried, dropped, unresolved = [], 0, 0
    for row in packet_gt["occurrences"] + packet_gt["carried_stmt"]:
        page = row.get("page")
        if page is None:
            unresolved += 1
            continue
        if page not in remap:
            dropped += 1
            continue
        r = json.loads(json.dumps(row))  # deep copy; never mutate the packet's own GT
        r["page"] = remap[page]
        for span in r.get("spans") or []:
            span["page"] = remap[page]
        r["carried_from"] = {"document": "packet.pdf", "page": page}
        carried.append(r)
    return carried, {
        "carried": len(carried),
        "dropped_other_pages": dropped,
        "unresolved_stmt_rows": unresolved,
    }


def _marks_sidecar(marks: list, master_sha: str, carry_stats: dict, bases: dict) -> dict:
    """The DOCS_ROOT-direct registration sidecar (the robustness/ + fuzz sibling-sidecar precedent:
    a SECOND file, never rows appended to documents.manifest.json, so T1.4 stays byte-stable and the
    K0 manifest rows can DEFER to the capture session for a single re-pin, L-25)."""
    from . import aruco as A

    return {
        "schema_version": 1,
        "family": "capture-masters",
        "set_id": V.CAPTURE_SET_ID,
        "document": OUT_PDF.name,
        "sha256": master_sha,
        "ground_truth": OUT_JSON.name,
        "page_count": len(marks),
        "dictionary": {
            "name": A.DICT_NAME,
            "count": A.COUNT,
            "markers_per_page": len(marks[0]["markers"]) if marks else 0,
            "marker_side_pt": 24.0,
            "margin_band_pt": [18.0, 42.0],
            "id_rule": "4*(page_number-1) .. +3, page_number 1-indexed",
        },
        "imported_pages": [
            {
                "master_page": i,
                "packet_page": p,
                "source": "packet.pdf",
                "exhibit": PACKET_SLICE_LABEL[p],
                "ground_truth": "carried forward verbatim, page index remapped",
            }
            for i, p in enumerate(PACKET_SLICE)
        ],
        "drawn_pages": [
            {
                "master_page": bases[name],
                "exhibit": name,
                "class": OCC.EXHIBIT_CLASS[name],
                "designed_doctype": OCC.EXHIBIT_DOCTYPE[name],
            }
            for name, _fn in CAPTURE_ASSEMBLY
        ],
        "carried_ground_truth": carry_stats,
        "pages": marks,
        "notes": (
            "Registration input for the device capture (P1.9). Each page carries four vector ArUco "
            "fiducials in the margin band the evaluated image is cropped back to, so no ground-truth "
            "box is disturbed and the packet-page boxes carry verbatim. PROOF-PRINT FIRST: the band "
            "is [18, 42] pt, so a printer whose unprintable margin exceeds 1/4 in will clip the "
            "fiducials. DOCS_ROOT-direct: this file is a SIBLING sidecar and never touches "
            "documents.manifest.json (T1.4 stays byte-stable -- the PB-86 precedent)."
        ),
    }


def build(*, write=True) -> dict:
    bases, total_pages = _bases()

    # the packet is rebuilt IN MEMORY (write=False) -- this module must never write packet.pdf
    packet = B.build(write=False)
    packet_pdf, packet_gt = packet["pdf"], packet["ground_truth"]

    form_pdf, rc = _render_drawables(CAPTURE_ASSEMBLY, bases)
    drawn = rc.occurrences
    pre = _assemble(form_pdf, packet_pdf)
    master = V.print_master(pre, doc_id=DOC_ID)
    pdf, marks = master["pdf"], master["marks"]

    carried, carry_stats = _carry_packet_ground_truth(packet_gt)
    gt = {
        "schema_version": schema.SCHEMA_VERSION,
        "packet": "resecta-capture-masters-2026-08",
        "generator": "resecta-sample-doc/packet",
        "set_id": V.CAPTURE_SET_ID,
        "page_count": total_pages,
        "bbox_origin": "bottom-left",
        "page_size_pt": [L.PW, L.PH],
        "imported": [
            {"master_page": i, "packet_page": p, "exhibit": PACKET_SLICE_LABEL[p]}
            for i, p in enumerate(PACKET_SLICE)
        ],
        "exhibits": [
            {
                "name": name,
                "base_page": bases[name],
                "pages": 1,
                "class": OCC.EXHIBIT_CLASS[name],
                "designed_doctype": OCC.EXHIBIT_DOCTYPE[name],
            }
            for name, _fn in CAPTURE_ASSEMBLY
        ],
        "occurrences": drawn,
        "carried_packet": carried,
    }

    # ---- integrity checks (structural; not a detection run) ----
    problems = schema.validate_ground_truth(drawn + carried)
    if problems:
        raise SystemExit("capture ground-truth schema violations:\n  " + "\n  ".join(problems))

    expected_ids = set(OCC.CAPTURE_BY_ID)
    drawn_ids = {r["id"] for r in drawn}
    missing, extra = expected_ids - drawn_ids, drawn_ids - expected_ids
    if missing or extra:
        raise SystemExit(
            f"capture occurrence mismatch -- missing: {sorted(missing)} extra: {sorted(extra)}"
        )
    if len(drawn_ids) != len(drawn):
        raise SystemExit("duplicate drawn capture occurrence id")
    for name, _fn in CAPTURE_ASSEMBLY:
        want = bases[name]
        for o in OCC.CAPTURE_BY_EXHIBIT[name]:
            rec = next(r for r in drawn if r["id"] == o.id)
            if rec["page"] != want:
                raise SystemExit(f"{o.id} on page {rec['page']}, expected {want} ({name})")
    from pypdf import PdfReader

    got_pages = len(PdfReader(io.BytesIO(pdf)).pages)
    if got_pages != total_pages:
        raise SystemExit(f"capture master has {got_pages} pages, expected {total_pages}")

    # ---- the D12-40 tripwire: packet.pdf must be untouched, on disk AND on rebuild ----
    disk_sha = hashlib.sha256(PACKET_PDF.read_bytes()).hexdigest()
    mem_sha = hashlib.sha256(packet_pdf).hexdigest()
    if disk_sha != PACKET_SHA256 or mem_sha != PACKET_SHA256:
        raise SystemExit(
            "D12-40 TRIPWIRE: packet.pdf is no longer the frozen artifact.\n"
            f"  expected {PACKET_SHA256}\n  on disk  {disk_sha}\n  rebuilt  {mem_sha}"
        )

    master_sha = hashlib.sha256(pdf).hexdigest()
    sidecar = _marks_sidecar(marks, master_sha, carry_stats, bases)

    if write:
        OUT_PDF.write_bytes(pdf)
        OUT_JSON.write_text(json.dumps(gt, indent=2) + "\n", encoding="ascii")
        OUT_MARKS.write_text(json.dumps(sidecar, indent=2) + "\n", encoding="ascii")
    return {
        "pdf": pdf,
        "ground_truth": gt,
        "marks": marks,
        "sidecar": sidecar,
        "pages": total_pages,
        "bases": bases,
        "drawn": len(drawn),
        "carried": len(carried),
        "sha256": master_sha,
        "recording": rc,
    }


def main() -> None:
    r = build()
    print(f"wrote {OUT_PDF}  ({len(r['pdf']):,} bytes, {r['pages']} pages)")
    print(f"     sha256 {r['sha256']}")
    print(
        f"wrote {OUT_JSON}  ({r['drawn']} drawn occurrences + {r['carried']} carried packet rows)"
    )
    print(
        f"wrote {OUT_MARKS}  ({r['pages']} pages x "
        f"{r['sidecar']['dictionary']['markers_per_page']} fiducials)"
    )
    print(f"packet.pdf byte-unchanged at {PACKET_SHA256} (D12-40 tripwire held)")


if __name__ == "__main__":
    main()
