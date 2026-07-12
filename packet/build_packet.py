"""build_packet.py -- one-pass assembler: draw the exhibits + embed the FROZEN statement -> a single
deterministic packet.pdf, and emit the draw-time ground truth in the SAME pass.

Final page order (0-indexed pageIndex, matching PageDetectionResult.pageIndex):
    0,1 URLA-B | 2 URLA-A | 3,4,5 STMT (embedded, frozen) | 6,7 T1040 | 8 ACH | 9 W-2 | 10 GOVID | 11 VEH

The drawable exhibits are rendered to one reportlab canvas in assembly order (skipping STMT); the 3
frozen STMT pages are then spliced in via pypdf at the STMT slot. Determinism: reportlab invariant +
pinned metadata + fixed document /ID -> byte-identical re-runs.

Every character is printable ASCII.
"""
from __future__ import annotations

import io
import json
import re
from pathlib import Path

from reportlab import rl_config
rl_config.invariant = 1  # noqa: E402  (must precede save; fixes dates + font subset tags)

from reportlab.pdfgen import canvas  # noqa: E402
from reportlab.lib.pagesizes import letter  # noqa: E402

from . import layout as L  # noqa: E402
from . import occurrences as OCC  # noqa: E402
from . import schema  # noqa: E402
from .manifest import RecordingCanvas  # noqa: E402
from .generators import stmt as STMT  # noqa: E402
from .generators import urla_b, urla_a, t1040, ach, w2, govid, veh  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
OUT_PDF = REPO / "packet.pdf"
OUT_JSON = REPO / "packet-ground-truth.json"

# (name, page_count, draw_fn). STMT has no draw fn -- it is embedded from frozen bytes.
ASSEMBLY = [
    ("urla_b", 2, urla_b.draw),
    ("urla_a", 1, urla_a.draw),
    ("stmt", STMT.STMT_PAGE_COUNT, None),
    ("t1040", 2, t1040.draw),
    ("ach", 1, ach.draw),
    ("w2", 1, w2.draw),
    ("govid", 1, govid.draw),
    ("veh", 1, veh.draw),
]


def _bases(assembly):
    base, out = 0, {}
    for name, n, _fn in assembly:
        out[name] = base
        base += n
    return out, base


def _render_drawables(assembly, bases):
    """Render every drawable exhibit (in assembly order, skipping STMT) onto one reportlab canvas."""
    L.register_fonts()
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter, invariant=1, pageCompression=1)
    rc = RecordingCanvas(c, L.PW, L.PH)
    for name, n, fn in assembly:
        if fn is None:
            continue
        fn(rc, bases[name])
    c.save()
    return buf.getvalue(), rc


# reportlab emits an empty default-font (Helvetica) preamble at each page start; strip it so only the
# embedded-subset Inter survives (font hygiene -- mirrors the statement generator).
_HELV_PREAMBLE = re.compile(rb"BT\s*/F1\s+12\s+Tf\s+14\.4\s+TL\s*ET")


def _strip_default_helvetica(writer) -> None:
    from pypdf.generic import DecodedStreamObject, NullObject
    for page in writer.pages:
        res = page.get("/Resources")
        res = res.get_object() if res is not None else None
        fonts = res.get("/Font").get_object() if (res is not None and "/Font" in res) else None
        if fonts is not None and "/F1" in fonts:
            del fonts["/F1"]
        contents = page.get_contents()
        if contents is None:
            continue
        data = contents.get_data()
        new = _HELV_PREAMBLE.sub(b"", data)
        if new != data:
            obj = DecodedStreamObject()
            obj.set_data(new)
            page.replace_contents(obj)
    for idx, obj in enumerate(writer._objects):
        o = obj.get_object() if obj is not None else None
        try:
            is_helv = o is not None and o.get("/Type") == "/Font" and "Helvetica" in str(o.get("/BaseFont", ""))
        except AttributeError:
            is_helv = False
        if is_helv:
            writer._objects[idx] = NullObject()


def _assemble(form_pdf: bytes, assembly, bases) -> bytes:
    """Splice the frozen STMT pages into the drawable pages at the STMT slot; finalize deterministically."""
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import ArrayObject, ByteStringObject

    forms = PdfReader(io.BytesIO(form_pdf))
    stmt = PdfReader(io.BytesIO(STMT.frozen_bytes()))
    writer = PdfWriter()

    stmt_base = bases["stmt"]
    # drawable pages are in assembly order; the first `stmt_base` of them precede the STMT slot
    form_pages = list(forms.pages)
    for p in form_pages[:stmt_base]:
        writer.add_page(p)
    for p in stmt.pages:
        writer.add_page(p)
    for p in form_pages[stmt_base:]:
        writer.add_page(p)

    _strip_default_helvetica(writer)
    creator = "Resecta Sample Packet Generator"
    writer.add_metadata({
        "/Title": "Hartwell Loan Application Packet (synthetic sample)",
        "/Author": "Resecta",
        "/Subject": "Synthetic PII-dense sample/test document packet",
        "/Creator": creator,
        "/Producer": creator,
        "/CreationDate": "D:20260614000000Z",
        "/ModDate": "D:20260614000000Z",
    })
    fixed = ByteStringObject(b"ResectaHartwellPacketID01")  # fixed doc /ID -> byte-stable output
    writer._ID = ArrayObject([fixed, fixed])
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def build(assembly=ASSEMBLY, *, write=True) -> dict:
    bases, total_pages = _bases(assembly)
    form_pdf, rc = _render_drawables(assembly, bases)
    drawn = rc.occurrences
    pdf = _assemble(form_pdf, assembly, bases)

    # ground truth: drawn occurrences + carried STMT classes (if STMT is in the assembly)
    live = {name for name, _n, _fn in assembly}
    carried = STMT.carried_records() if "stmt" in live else []
    gt = {
        "schema_version": 1,
        "packet": "hartwell-loan-packet",
        "generator": "resecta-sample-doc/packet",
        "page_count": total_pages,
        "bbox_origin": "bottom-left",
        "page_size_pt": [L.PW, L.PH],
        "exhibits": [{"name": n, "base_page": bases[n], "pages": pc}
                     for (n, pc, _fn) in assembly],
        "occurrences": drawn,
        "carried_stmt": carried,
    }

    # ---- integrity checks (structural; not a detection run) ----
    problems = schema.validate_ground_truth(drawn + carried)
    if problems:
        raise SystemExit("ground-truth schema violations:\n  " + "\n  ".join(problems))

    expected_ids = {o.id for name in live if name != "stmt" for o in OCC.BY_EXHIBIT.get(name, [])}
    drawn_ids = {r["id"] for r in drawn}
    missing = expected_ids - drawn_ids
    extra = drawn_ids - expected_ids
    if missing or extra:
        raise SystemExit(f"occurrence mismatch -- missing: {sorted(missing)} extra: {sorted(extra)}")
    if len(drawn_ids) != len(drawn):
        raise SystemExit("duplicate drawn occurrence id")
    # every drawn occurrence sits on a page within its exhibit's range
    for name, pc, _fn in assembly:
        if name == "stmt":
            continue
        lo, hi = bases[name], bases[name] + pc - 1
        for o in OCC.BY_EXHIBIT.get(name, []):
            rec = next(r for r in drawn if r["id"] == o.id)
            if not (lo <= rec["page"] <= hi):
                raise SystemExit(f"{o.id} on page {rec['page']} outside {name} range {lo}-{hi}")

    if write:
        OUT_PDF.write_bytes(pdf)
        OUT_JSON.write_text(json.dumps(gt, indent=2) + "\n", encoding="ascii")
    return {"pdf": pdf, "ground_truth": gt, "pages": total_pages, "bases": bases,
            "drawn": len(drawn), "carried": len(carried), "recording": rc}


def main() -> None:
    r = build()
    print(f"wrote {OUT_PDF}  ({len(r['pdf']):,} bytes, {r['pages']} pages)")
    print(f"wrote {OUT_JSON}  ({r['drawn']} drawn occurrences + {r['carried']} carried STMT classes)")


if __name__ == "__main__":
    main()
