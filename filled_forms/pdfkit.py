"""The macOS PDFKit documents.

PDFKit writes a fresh creation date, modification date, per-annotation ``/M`` and trailer ``/ID`` on
every write. ``pin`` replaces each with a fixed value of the same byte length, so every xref offset
PDFKit wrote stays valid and the file is otherwise PDFKit's own bytes.

PDFKit runs only on macOS, so its outputs are kept in ``filled_forms/pdfkit/<id>.pdf`` (committed).
The build copies them; ``record`` (macOS) writes them again with the helper.
"""

from __future__ import annotations

import hashlib
import json
import platform
import re
import subprocess
import tempfile
from pathlib import Path

from .form import PageText, by_name
from .producers import _with_page

HERE = Path(__file__).resolve().parent / "pdfkit"
HELPER = HERE / "gen_pdfkit"
PINNED_DATE = b"D:20261105000000Z00'00'"


def pin(data: bytes) -> bytes:
    def date(m: re.Match[bytes]) -> bytes:
        old = m.group(2)
        new = (PINNED_DATE + b" " * len(old))[: len(old)]
        return m.group(1) + new + m.group(3)

    out = re.sub(rb"(/(?:CreationDate|ModDate|M)\s*\()([^)]*)(\))", date, data)
    idm = re.search(rb"/ID\s*\[\s*<([0-9a-fA-F]{32})>\s*<([0-9a-fA-F]{32})>", out)
    if idm:
        zeroed = (
            out[: idm.start(1)]
            + b"0" * 32
            + out[idm.end(1) : idm.start(2)]
            + b"0" * 32
            + out[idm.end(2) :]
        )
        h = hashlib.md5(zeroed, usedforsecurity=False).hexdigest().encode("ascii")
        out = out[: idm.start(1)] + h + out[idm.end(1) : idm.start(2)] + h + out[idm.end(2) :]
    return out


def _filled_specs() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for name in ("full_name", "phone", "email", "ssn", "dob"):
        f = by_name(name)
        rows.append(
            {
                "name": f.name,
                "kind": "text",
                "rect": list(f.rect),
                "value": f.value,
                "background": "grey",
            }
        )
    for name in ("consent", "mailing"):
        f = by_name(name)
        rows.append(
            {
                "name": f.name,
                "kind": "checkbox",
                "rect": list(f.rect),
                "state": f.value,
                "background": "grey",
            }
        )
    return rows


COVER_TEXT_X_OFFSET = 4


def _cover_page() -> bytes:
    """The printed page with the SSN printed as page text inside the SSN field's rectangle."""
    f = by_name("ssn")
    return _with_page(
        None, PageText([(f.rect[0] + COVER_TEXT_X_OFFSET, f.rect[1] + 6, f.value or "")])
    )


def _cover_specs() -> list[dict[str, object]]:
    f = by_name("ssn")
    return [
        {
            "name": "ssn_cover",
            "kind": "text",
            "rect": list(f.rect),
            "value": "",
            "background": "black",
        }
    ]


DOCS = {
    "ff-pdfkit-filled": (lambda: _with_page(None), _filled_specs),
    "ff-pdfkit-blackwidget-cover": (_cover_page, _cover_specs),
}


def cover_page_bytes() -> bytes:
    return _cover_page()


def run_helper(doc_id: str) -> bytes:
    page, specs = DOCS[doc_id]
    with tempfile.TemporaryDirectory() as td:
        src, dst, spec = Path(td) / "in.pdf", Path(td) / "out.pdf", Path(td) / "w.json"
        src.write_bytes(page())
        spec.write_text(json.dumps(specs()), encoding="ascii")
        cmd = [str(HELPER), str(src), str(dst), str(spec)]
        subprocess.run(cmd, check=True, capture_output=True)  # noqa: S603 - the helper in this folder
        return pin(dst.read_bytes())


def recorded(doc_id: str) -> bytes:
    return (HERE / f"{doc_id}.pdf").read_bytes()


RECORD_FILE = HERE / "recorded.json"


def record() -> list[str]:
    """Write every PDFKit document again and note the macOS version and each file's SHA-256."""
    out = []
    shas = {}
    for doc_id in DOCS:
        data = run_helper(doc_id)
        (HERE / f"{doc_id}.pdf").write_bytes(data)
        shas[doc_id] = hashlib.sha256(data).hexdigest()
        out.append(doc_id)
    rec = {
        "macos": platform.mac_ver()[0],
        "writer": "PDFKit PDFDocument.write (gen_pdfkit.swift)",
        "sha256": shas,
    }
    RECORD_FILE.write_text(json.dumps(rec, indent=1, sort_keys=True) + "\n", encoding="ascii")
    return out


def recording_facts() -> dict[str, object]:
    return json.loads(RECORD_FILE.read_text(encoding="ascii"))
