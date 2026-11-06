"""The structure family: its writer, its helpers, and its committed documents."""

from __future__ import annotations

import hashlib
import json
import sys
import zlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hidden_layer.verify_docs import read_sums  # noqa: E402
from structure import build, docs, rc4, verify_docs  # noqa: E402

ST = ROOT / "structure"


def test_exact_ratio_bodies() -> None:
    for ratio in (docs.MAX_INFLATE_RATIO, docs.MAX_INFLATE_RATIO + 1):
        body, out = docs.exact_ratio_body(ratio)
        d = zlib.decompressobj()
        assert len(d.decompress(body)) == out
        assert d.unused_data == b""
        assert out == ratio * len(body)


def test_rc4_known_vector() -> None:
    # RC4 with key "Key" on "Plaintext" (the published test vector).
    assert rc4.rc4(b"Key", b"Plaintext").hex() == "bbf316e8d940af0ad3"


def test_every_document_has_a_measured_kind() -> None:
    for d in docs.docs():
        assert build.kind_of(d)


def _rows() -> list[dict]:
    return json.loads((ST / "manifest.json").read_text(encoding="ascii"))["documents"]


@pytest.mark.skipif(not (ST / "manifest.json").exists(), reason="no published set")
def test_committed_documents_verify() -> None:
    sums = read_sums(ST / "SHA256SUMS")
    failed = []
    for row in _rows():
        if row["stored"] != "committed":
            continue
        res = verify_docs.check_one(ST, row, sums)
        if not res.ok:
            failed.append((row["path"], {k: v for k, v in res.checks.items() if v["ok"] is False}))
    assert not failed


@pytest.mark.skipif(not (ST / "manifest.json").exists(), reason="no published set")
def test_rebuild_committed_documents_byte_identical() -> None:
    by_id = {Path(r["path"]).stem: r for r in _rows()}
    for d in docs.docs():
        row = by_id[d.doc_id]
        if row["stored"] != "committed":
            continue
        data, _ = d.make()
        assert hashlib.sha256(data).hexdigest() == row["sha256"], d.doc_id
