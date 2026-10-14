"""The capture-master pins and the packet-wide brand check.

Two pins live in packet/build_capture.py beside the frozen packet's: the capture masters' PDF and
their fiducial sidecar (the marks file, which embeds the masters' digest). The brand denylist that
verify.py applies to the statement is shared with the packet acceptance through
packet/brand_denylist.py, so the packet's own text is checked against the same list.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from pypdf import PdfReader

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from packet import build_capture as BC  # noqa: E402
from packet.brand_denylist import DENYLIST, PACKET_DISCLAIMER_NAMES, denylist_hits  # noqa: E402


def test_marks_pin_matches_the_committed_sidecar_and_the_rebuild() -> None:
    """MARKS_SHA256 names the committed marks file and the bytes an in-memory rebuild
    would write for it (the same serialisation build_capture.build uses)."""
    committed = hashlib.sha256(BC.OUT_MARKS.read_bytes()).hexdigest()
    assert committed == BC.MARKS_SHA256
    rebuilt = BC.build(write=False)
    sidecar_bytes = (json.dumps(rebuilt["sidecar"], indent=2) + "\n").encode("ascii")
    assert hashlib.sha256(sidecar_bytes).hexdigest() == BC.MARKS_SHA256


def test_denylist_flags_a_brand_and_passes_the_packet() -> None:
    """The shared check flags a denylisted brand in synthetic text (word-boundary,
    case-insensitive) and finds none in the packet's own extracted text."""
    assert "WELLS FARGO" in DENYLIST
    assert denylist_hits("Statement issued by Wells Fargo Bank, N.A.") == ["WELLS FARGO"]
    assert denylist_hits("Hartwell Savings statement, May 2026") == []
    text = "\n".join((page.extract_text() or "") for page in PdfReader(REPO / "packet.pdf").pages)
    assert len(text) > 10_000, "packet text extraction came back near-empty"
    # The one name the packet carries is the agency its specimen disclaimer names ("Not an IRS
    # form." on the 1040-like and W-2-like pages); the packet check exempts it by name.
    assert denylist_hits(text) == ["IRS"]
    assert "Not an IRS form." in text
    assert denylist_hits(text, exempt=PACKET_DISCLAIMER_NAMES) == []
