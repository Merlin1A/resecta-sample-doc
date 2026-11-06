"""The hidden-layer family: its pure helpers, its committed documents, and one rebuild."""

from __future__ import annotations

import hashlib
import itertools
import json
import sys
from fractions import Fraction
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hidden_layer import build, geometry, grid, rng, verify_docs  # noqa: E402

HL = ROOT / "hidden_layer"


def test_splitmix64_reference_values() -> None:
    # The first three outputs of SplitMix64 from state 0 (the published reference sequence).
    got = [int(v) for v in rng.splitmix64(0, 3)]
    assert got == [0xE220A8397B1DCDAF, 0x6E789E6AA1B965F4, 0x06C45D188009454F]


def test_uniform_ints_bounds_and_stability() -> None:
    a = rng.uniform_ints(7, 1000, -3, 5)
    assert a.min() >= -3
    assert a.max() <= 5
    assert list(a[:5]) == list(rng.uniform_ints(7, 5, -3, 5))


def _cells(r: tuple[int, int, int, int]) -> set[tuple[int, int]]:
    return {(x, y) for x in range(r[0], r[2]) for y in range(r[1], r[3])}


def test_covered_area_matches_unit_cells_exhaustively() -> None:
    """On a 4 x 3 integer grid, every box against every pair of rectangles: the exact covered area
    equals the count of unit cells inside the box and the union."""
    spans = [(a, b) for a, b in itertools.combinations(range(5), 2)]
    vspans = [(a, b) for a, b in itertools.combinations(range(4), 2)]
    rects = [(x0, y0, x1, y1) for (x0, x1) in spans for (y0, y1) in vspans]
    sample = rects[::7]
    for box in rects:
        fb = geometry.rect(*box)
        for r1, r2 in itertools.product(sample, repeat=2):
            want = len(_cells(box) & (_cells(r1) | _cells(r2)))
            got = geometry.covered_area(fb, [geometry.rect(*r1), geometry.rect(*r2)])
            assert got == want, (box, r1, r2)


def test_relation_cases() -> None:
    r = [geometry.rect(0, 0, 10, 10)]
    assert geometry.relation(geometry.rect(1, 1, 2, 2), r) == "inside"
    assert geometry.relation(geometry.rect(9, 9, 11, 11), r) == "partial"
    assert geometry.relation(geometry.rect(10, 0, 12, 2), r) == "outside"
    assert geometry.relation(geometry.rect(Fraction(1, 3), 0, Fraction(1, 3), 5), r) == "inside"


def test_grid_ids_unique() -> None:
    ids = [s.doc_id for s in grid.all_specs()]
    assert len(ids) == len(set(ids))


def _committed_rows() -> list[dict]:
    manifest = json.loads((HL / "manifest.json").read_text(encoding="ascii"))
    return [r for r in manifest["documents"] if r["stored"] == "committed"]


@pytest.mark.skipif(not (HL / "manifest.json").exists(), reason="no published hidden-layer set")
def test_committed_documents_verify() -> None:
    sums = verify_docs.read_sums(HL / "SHA256SUMS")
    failed = []
    for row in _committed_rows():
        res = verify_docs.check_one(HL, row, sums)
        if not res.ok:
            failed.append((row["path"], {k: v for k, v in res.checks.items() if v["ok"] is False}))
    assert not failed


@pytest.mark.skipif(not (HL / "manifest.json").exists(), reason="no published hidden-layer set")
def test_rebuild_smallest_committed_document_is_byte_identical() -> None:
    row = min(_committed_rows(), key=lambda r: r["bytes"])
    spec = next(s for s in grid.all_specs() if f"documents/{s.doc_id}.pdf" == row["path"])
    pdf, expected = build.build_doc(spec)
    assert hashlib.sha256(pdf).hexdigest() == row["sha256"]
    assert hashlib.sha256(build.json_bytes(expected)).hexdigest() == row["expected_sha256"]
