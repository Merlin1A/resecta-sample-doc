"""The filled-form family: its pure helpers, its committed documents, and their rebuild."""

from __future__ import annotations

import hashlib
import itertools
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from filled_forms import build, pdfkit, producers, verify_docs  # noqa: E402
from hidden_layer.verify_docs import read_sums  # noqa: E402

FF = ROOT / "filled_forms"
# The widget-free control is a fixed document: a change to these bytes is a change to the family.
CONTROL_SHA256 = "c06904590bf26538bf4f977d1a509ef6fd5b08489e631d65304ec9b1fb2c9b14"


def _rule(ft: str | None, ff: int) -> str:
    """The field-kind rule written out case by case (PDF 32000-1, 12.7.4)."""
    if ft == "/Tx":
        kind = "multiline" if ff & 4096 else "text"
    elif ft == "/Btn":
        kind = "pushbutton" if ff & 65536 else ("radio" if ff & 32768 else "checkbox")
    elif ft == "/Ch":
        kind = "combo" if ff & 131072 else "list"
    elif ft == "/Sig":
        kind = "signature"
    else:
        kind = "unknown"
    return kind


def test_field_kind_every_type_and_flag_combination() -> None:
    bits = (4096, 32768, 65536, 131072)
    for ft in ("/Tx", "/Btn", "/Ch", "/Sig", None):
        for chosen in itertools.product((0, 1), repeat=len(bits)):
            ff = sum(b for b, on in zip(bits, chosen, strict=True) if on)
            assert build.field_kind(ft, ff) == _rule(ft, ff), (ft, ff)


def test_pin_keeps_length_and_fixes_dates_and_id() -> None:
    raw = (
        b"<< /CreationDate (D:20261106123456Z) /M (D:20261106) >> trailer << /ID [<"
        + b"a" * 32
        + b"> <"
        + b"b" * 32
        + b">] >>"
    )
    out = pdfkit.pin(raw)
    assert len(out) == len(raw)
    assert b"20261106123456" not in out
    assert out == pdfkit.pin(out.replace(b"a" * 32, b"c" * 32))


def test_control_document_is_pinned() -> None:
    assert hashlib.sha256(producers.control_no_widgets()).hexdigest() == CONTROL_SHA256


def _rows() -> list[dict]:
    return json.loads((FF / "manifest.json").read_text(encoding="ascii"))["documents"]


@pytest.mark.skipif(not (FF / "manifest.json").exists(), reason="no published filled-form set")
def test_committed_documents_verify() -> None:
    sums = read_sums(FF / "SHA256SUMS")
    failed = []
    for row in _rows():
        res = verify_docs.check_one(FF, row, sums)
        if not res.ok:
            failed.append((row["path"], {k: v for k, v in res.checks.items() if v["ok"] is False}))
    assert not failed


@pytest.mark.skipif(not (FF / "manifest.json").exists(), reason="no published filled-form set")
def test_rebuild_is_byte_identical() -> None:
    """Every document but the recorded PDFKit ones is rebuilt from its producer and compared."""
    by_id = {Path(r["path"]).stem: r for r in _rows()}
    for doc in build.DOCS:
        if doc[2] == "PDFKit":
            continue
        pdf, expected = build.build_doc(doc)
        row = by_id[doc[0]]
        assert hashlib.sha256(pdf).hexdigest() == row["sha256"], doc[0]
        assert hashlib.sha256(build.json_bytes(expected)).hexdigest() == row["expected_sha256"], (
            doc[0]
        )
