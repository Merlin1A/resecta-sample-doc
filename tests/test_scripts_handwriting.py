"""The script and handwriting family: its pure helpers, its committed documents, and a rebuild."""

from __future__ import annotations

import hashlib
import json
import sys
import unicodedata
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hidden_layer.verify_docs import read_sums  # noqa: E402
from scripts_handwriting import build, layerread, rtl, texts, verify_docs  # noqa: E402

SH = ROOT / "scripts_handwriting"


def test_arabic_visual_order_round_trips() -> None:
    """Every pure right-to-left label and name: NFKC of the reversed visual string is the text."""
    for code in ("ar", "he"):
        s = texts.scripts()[code]
        for label, value, _, field in texts.form_rows(s):
            for t in (label, value) if field == "name" else (label,):
                assert unicodedata.normalize("NFKC", rtl.visual(t)[::-1]) == t, (code, t)


def test_cmap_parsing() -> None:
    cmap = b"1 begincodespacerange <0000> <FFFF> endcodespacerange\n2 beginbfchar <0001> <0041> <0002> <00420043> endbfchar\n1 beginbfrange <0010> <0012> <0061> endbfrange"
    got, width = layerread.parse_cmap(cmap)
    assert width == 2
    assert got == {1: "A", 2: "BC", 0x10: "a", 0x11: "b", 0x12: "c"}


def test_invented_names_are_stable() -> None:
    assert texts.invented_name("zh-Hans") == texts.invented_name("zh-Hans")
    assert all(texts.invented_name(k)[0] for k in texts.SYLLABLES)


def _rows() -> list[dict]:
    return json.loads((SH / "manifest.json").read_text(encoding="ascii"))["documents"]


@pytest.mark.skipif(not (SH / "manifest.json").exists(), reason="no published set")
def test_committed_born_and_reportlab_documents_verify() -> None:
    sums = read_sums(SH / "SHA256SUMS")
    failed = []
    for row in _rows():
        if row["kind"] != "born" or not (SH / row["path"]).exists():
            continue
        res = verify_docs.check_one(SH, row, sums)
        if not res.ok:
            failed.append((row["path"], {k: v for k, v in res.checks.items() if v["ok"] is False}))
    assert not failed


@pytest.mark.skipif(not (SH / "manifest.json").exists(), reason="no published set")
def test_rebuild_reportlab_pages_and_a_twin_byte_identical() -> None:
    """The reportlab pages and a twin of one rebuild byte for byte on any platform. The handwriting
    pictures are left out: they rebuild identically on one platform, but the variable handwriting
    font rasterises differently elsewhere (see the README)."""
    by_id = {Path(r["path"]).stem: r for r in _rows()}
    picks = [s for s in build.specs() if s.kind == "born" and s.writer == "reportlab"]
    picks += [s for s in build.specs() if s.doc_id == "sh-scan-el-prose-clean-placed"]
    for spec in picks:
        pdf, exp = build.build_doc(spec)
        row = by_id[spec.doc_id]
        assert hashlib.sha256(pdf).hexdigest() == row["sha256"], spec.doc_id
        assert hashlib.sha256(build.json_bytes(exp)).hexdigest() == row["expected_sha256"], (
            spec.doc_id
        )
