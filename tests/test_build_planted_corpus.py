"""Tests for tools/build_planted_corpus.py: the hand-rolled PDF writer's helpers and a full build of
the planted-leak corpus into a temporary directory, compared with the committed fixtures. The tool
is loaded by file path like its siblings; the committed `planted/` tree is never written.
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import sys
from pathlib import Path

import pytest
from pypdf import PdfReader

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

_SPEC = importlib.util.spec_from_file_location(
    "build_planted_corpus", REPO / "tools" / "build_planted_corpus.py"
)
assert _SPEC is not None and _SPEC.loader is not None
BP = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(BP)

# Fixtures whose bytes come through an image encoder (PIL / libjpeg): their digests are compared
# only when they match, since the encoder's output is version-stable, not spec-stable.
RASTER_FIXTURES = {"planted-inline-image", "planted-thumb", "planted-exif", "clean-image"}
# The stretch row depends on a mutool probe on the building host.
PROBE_FIXTURES = {"planted-text-outlines"}


def test_pdf_string_escaping() -> None:
    assert BP.esc("a(b)\\") == b"a\\(b\\)\\\\"


def test_text_operator_shape() -> None:
    assert BP.text_op(72, 700, 12, "Hi") == b"BT /F1 12 Tf 72 700 Td (Hi) Tj ET\n"


def test_normalised_rect_is_relative_to_the_letter_page() -> None:
    assert (BP.PW, BP.PH) == (612, 792)
    assert BP.nrect(61.2, 79.2, 306, 396) == [0.1, 0.1, 0.5, 0.5]


def test_stream_object_carries_its_length() -> None:
    assert BP.stream_obj(b"/Filter /None", b"abc") == (
        b"<< /Filter /None /Length 3 >>\nstream\nabc\nendstream"
    )


def test_one_page_skeleton_parses_and_carries_its_text() -> None:
    pdf = BP.page_pdf(BP.text_op(72, 700, 12, "Hello"))
    assert pdf.startswith(b"%PDF-1.4\n")
    reader = PdfReader(io.BytesIO(pdf))
    assert len(reader.pages) == 1
    assert reader.pages[0].extract_text() == "Hello"


def test_full_build_into_a_temporary_tree_matches_the_committed_corpus(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """main() rebuilt under a temporary REPO reproduces the committed manifest's fixtures, plants
    and (for the hand-rolled fixtures) bytes; the committed `planted/` tree is untouched."""
    monkeypatch.setattr(BP, "REPO", tmp_path)
    monkeypatch.setattr(BP, "OUTDIR", tmp_path / "planted")
    monkeypatch.setattr(BP, "CLEANDIR", tmp_path / "planted" / "clean")
    monkeypatch.setattr(BP, "ROWS", [])
    monkeypatch.setattr(BP, "SKIPPED", [])
    BP.main()

    built = json.loads((tmp_path / "planted" / "planted-leaks.json").read_text(encoding="utf-8"))
    committed = json.loads((REPO / "planted" / "planted-leaks.json").read_text(encoding="utf-8"))

    def rows(manifest: dict) -> dict[str, dict]:
        return {
            r["fixture"]: r
            for r in manifest["rows"] + manifest["clean"]
            if r["fixture"] not in PROBE_FIXTURES
        }

    built_rows, committed_rows = rows(built), rows(committed)
    assert set(built_rows) == set(committed_rows)
    for fixture, row in committed_rows.items():
        got = built_rows[fixture]
        assert got["clean"] == row["clean"], fixture
        assert [(p["surface"], p["term"]) for p in got["plants"]] == [
            (p["surface"], p["term"]) for p in row["plants"]
        ], fixture
        path = tmp_path / got["path"]
        assert path.is_file(), fixture
        assert hashlib.sha256(path.read_bytes()).hexdigest() == got["sha256"], fixture
        if fixture not in RASTER_FIXTURES:
            assert got["sha256"] == row["sha256"], fixture
    terms = [p["term"] for r in built["rows"] for p in r["plants"]]
    assert len(terms) == len(set(terms)), "every planted term is unique corpus-wide"
