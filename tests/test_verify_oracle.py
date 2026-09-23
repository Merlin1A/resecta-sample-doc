"""Tests for tools/verify_oracle.py: the parallel scan engine, the tool-output cache, the O2
operand regex and the PSM-6 file renderers.

Two tests are pure Python and run everywhere (the cache and the regex). Two drive the external
tools the oracle drives (qpdf, mutool, poppler, tesseract, exiftool) and skip where any is absent;
on a host that has them they build two tiny PDFs with reportlab and prove that the parallel engine
writes the same partials as the serial one, byte for byte, and that a warm cache reports no misses.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import random
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

_SPEC = importlib.util.spec_from_file_location("verify_oracle", REPO / "tools" / "verify_oracle.py")
assert _SPEC is not None and _SPEC.loader is not None
VO = importlib.util.module_from_spec(_SPEC)
sys.modules["verify_oracle"] = VO
_SPEC.loader.exec_module(VO)

TOOLS = (
    "qpdf",
    "mutool",
    "pdftoppm",
    "pdfinfo",
    "pdftotext",
    "pdffonts",
    "pdfimages",
    "tesseract",
    "exiftool",
)
_MISSING = [t for t in TOOLS if shutil.which(t) is None]
needs_tools = pytest.mark.skipif(bool(_MISSING), reason=f"oracle tools absent: {_MISSING}")


# ---------------------------------------------------------------- (1) the cache


def _writer(name: str, payload: bytes):
    def produce(out: Path) -> bool:
        (out / name).write_bytes(payload)
        return True

    return produce


def _never(_out: Path) -> bool:
    pytest.fail("the producer ran on a cache hit")


def test_cache_key_and_atomic_write(tmp_path: Path) -> None:
    desc: dict[str, Any] = {
        "step": "render_pp",
        "input_sha256": "ab" * 32,
        "page": 3,
        "argv": ["pdftoppm", "-r", "400", "-f", "3", "-l", "3", "<IN>", "<OUT>/pp"],
        "versions": {"pdftoppm": "pdftoppm version 26.07.0"},
    }
    canonical = json.dumps(desc, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    key = VO.cache_key(desc)
    assert key == hashlib.sha256(canonical.encode()).hexdigest()
    assert VO.cache_key(dict(reversed(list(desc.items())))) == key  # key order is irrelevant
    assert VO.cache_key({**desc, "page": 4}) != key
    assert VO.cache_key({**desc, "argv": [*desc["argv"], "-gray"]}) != key

    cache = VO.OracleCache(tmp_path / "cache")
    payload = b"x" * 10_000
    gate = threading.Barrier(2)
    outcomes: list[tuple[Path | None, bool]] = []

    def racing_producer(out: Path) -> bool:
        gate.wait()  # both writers produce at the same moment
        (out / "pp-3.png").write_bytes(payload)
        time.sleep(0.05)
        return True

    def worker() -> None:
        outcomes.append(cache.get_or_produce("render_pp", desc, racing_producer))

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    entry = cache.entry_dir("render_pp", key)
    assert entry.is_dir() and (entry / "meta.json").is_file()
    assert (entry / "pp-3.png").read_bytes() == payload
    assert [e for e, _hit in outcomes] == [entry, entry]
    assert list(entry.parent.glob("*.tmp-*")) == []  # the loser cleaned its tmp dir up
    meta = json.loads((entry / "meta.json").read_text())
    assert meta["step"] == "render_pp" and meta["key"] == key
    assert meta["descriptor"] == desc and meta["bytes"] == len(payload)

    # a hit never produces and touches the meta mtime (the LRU clock)
    meta_path = entry / "meta.json"
    old = time.time() - 86_400
    os.utime(meta_path, (old, old))
    hit_entry, hit = cache.get_or_produce("render_pp", desc, _never)
    assert hit and hit_entry == entry
    assert meta_path.stat().st_mtime > old + 3_600

    # a producer that fails leaves nothing behind and is not a hit next time
    bad = {**desc, "page": 99}
    assert cache.get_or_produce("render_pp", bad, lambda _out: False) == (None, False)
    assert not cache.entry_dir("render_pp", VO.cache_key(bad)).exists()
    assert list(entry.parent.glob("*.tmp-*")) == []

    # prune: three more entries with staged ages; the byte cap removes the oldest first
    aged: dict[int, Path] = {}
    for i, page in enumerate((10, 11, 12)):
        e, was_hit = cache.get_or_produce(
            "render_pp", {**desc, "page": page}, _writer("pp.png", b"y" * (1000 * (i + 1)))
        )
        assert e is not None and not was_hit
        stamp = time.time() - 3_600 * (3 - i)  # page 10 is the oldest
        os.utime(e / "meta.json", (stamp, stamp))
        aged[page] = e
    now = time.time()
    os.utime(meta_path, (now, now))  # the first entry is the newest
    stats = cache.stats()
    assert stats["entries"] == 4
    assert stats["bytes"] == len(payload) + 1000 + 2000 + 3000
    removed = cache.prune(max_bytes=stats["bytes"] - 1)
    assert removed["entries"] == 1 and removed["bytes"] == 1000
    assert not aged[10].exists() and aged[11].exists() and aged[12].exists() and entry.exists()
    assert cache.stats()["bytes"] == len(payload) + 2000 + 3000
    removed = cache.prune(max_bytes=len(payload))
    assert removed["entries"] == 2 and entry.exists()
    assert cache.stats() == {"entries": 1, "bytes": len(payload), "by_step": {"render_pp": 1}}
    assert cache.prune(max_bytes=0) == {"entries": 1, "bytes": len(payload)}
    assert cache.stats()["entries"] == 0


# ---------------------------------------------------------------- (2) the O2 operand regex

# The regex tools/verify_oracle.py used before the unrolled-loop rewrite, kept here as a literal:
# the two define the same language and must agree on every span and every reassembled text.
OLD_TJ_OPERAND_RE = re.compile(rb"\(((?:[^()\\]|\\.)*)\)")


def _old_tj_reassembled(qdf_bytes: bytes) -> str:
    text_parts: list[str] = []
    for m in OLD_TJ_OPERAND_RE.finditer(qdf_bytes):
        raw = m.group(1)
        raw = re.sub(rb"\\([0-7]{1,3})", lambda g: bytes([int(g.group(1), 8) & 0xFF]), raw)
        raw = raw.replace(b"\\(", b"(").replace(b"\\)", b")").replace(b"\\\\", b"\\")
        text_parts.append(raw.decode("latin-1", "replace"))
    return "".join(text_parts)


def test_tj_reassembled_regex_equivalence() -> None:
    rng = random.Random(20260922)
    alphabet = b"ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 \n\t\r"
    corpora: list[bytes] = []
    # a paren-free megabyte run (the decoded-raster shape) with operands around it
    run = bytes(rng.choice(alphabet) for _ in range(1_000_000))
    corpora.append(b"BT (Hello) Tj " + run + b" (World) Tj ET")
    # escaped parens, escaped backslashes, octal escapes, a trailing escaped backslash
    corpora.append(rb"(a\(b\)c) (x\\y) (\101\102\103) (\7\77\777) (tail\\) (\)) (\() (\\\\) ()")
    # unbalanced, nested-looking, an unclosed operand, a newline after a backslash
    corpora.append(b"((nested) open (a(b)c) ) (unclosed \n (another) (bs\\\nnl) (x\\\ry)")
    corpora.append(b")))(((" + b"(" * 5_000 + b")" * 5_000 + b"(" * 3 + b")")
    # binary noise over every byte value
    corpora.append(bytes(rng.getrandbits(8) for _ in range(500_000)))
    # a backslash before every byte value, inside one operand and outside any
    every = b"".join(b"\\" + bytes([b]) for b in range(256))
    corpora.append(b"(" + every + b")" + every)
    # runs of backslashes of odd and even length
    corpora.append(b"(" + b"\\" * 1_001 + b")" + b"(" + b"\\" * 1_000 + b")" + b"\\" * 999)
    # operands sprinkled through raster-like noise
    noisy = bytearray(rng.choice(alphabet) for _ in range(200_000))
    for _ in range(300):
        pos = rng.randrange(len(noisy) - 8)
        noisy[pos : pos + 8] = rng.choice([b"(ab\\)c)x", b"(\\(x\\))", b"((a)b)c)", b"\\(no\\)xx"])
    corpora.append(bytes(noisy))
    assert VO.TJ_OPERAND_RE.pattern != OLD_TJ_OPERAND_RE.pattern
    for data in corpora:
        new_spans = [m.span() for m in VO.TJ_OPERAND_RE.finditer(data)]
        old_spans = [m.span() for m in OLD_TJ_OPERAND_RE.finditer(data)]
        assert new_spans == old_spans
        assert VO.tj_reassembled(data) == _old_tj_reassembled(data)


def test_tj_terms_present_equals_whole_string_fold() -> None:
    rng = random.Random(20260923)
    pieces = [b"(x)"]
    # operands of every byte value, whitespace runs, µ and ß (casefold leaves latin-1), NBSP/NEL
    for _ in range(3000):
        pieces.append(
            b"("
            + bytes(
                rng.choice(b"ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 \n\t\r")
                for _ in range(rng.randrange(0, 4000))
            )
            + b")"
        )
        if rng.random() < 0.2:
            pieces.append(b"(" + bytes(b for b in range(256) if b not in b"()\\") + b")")
        if rng.random() < 0.2:
            pieces.append(b"(\xb5 \xdf\xa0\x85 Zo\xeb)")
    # one giant operand (a decoded raster is one operand tens of MB long) with terms inside
    # and escapes at every position a split could land on; and an octal-dense operand that
    # spells a term in escapes, forcing the split search past every backslash
    body = bytearray(rng.choice(b"ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 \n") for _ in range(300_000))
    for pos in range(500, 300_000, 977):
        body[pos : pos + 5] = rng.choice([b"\\101B", b"Zo\\353x", b"a\\\\b", b"\\(\\)", b"\\12\\3"])
    pieces.append(b"(" + bytes(body) + b")")
    pieces.append(b"(" + b"\\132\\157\\353" * 2000 + b"\\101" * 5000 + b")")
    data = b" 12 Tj ".join(pieces)
    terms = ["Zoë", "µ", "ß", "not there", "ABC", "12 tj", "", "  ", "AB", "ëZoë"]
    folded_terms = [VO.fold_nospace(t) for t in terms]
    whole = VO.fold_nospace(VO.tj_reassembled(data))
    expected = {ft for ft in folded_terms if ft and ft in whole}
    for chunk in (1, 7, 100, 4_000, VO.TJ_CHUNK_CHARS):
        assert VO.tj_terms_present(data, folded_terms, chunk_chars=chunk) == expected
    # terms straddling a chunk boundary: every chunk size must still find them
    straddle = b"(abc)(def)(ghi)(jkl)"
    for chunk in range(1, 14):
        found = VO.tj_terms_present(
            straddle, ["cdefg", "abcdefghijkl", "lm", "kl"], chunk_chars=chunk
        )
        assert found == {"cdefg", "abcdefghijkl", "kl"}
    assert VO.tj_terms_present(data, ["", "   "]) == set()


# ---------------------------------------------------------------- (3) parallel == serial


def _fixture(root: Path) -> Path:
    """Two tiny PDFs, three cells: two cells share doc A (one burns a term with a black
    rectangle), one cell is doc B."""
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    doc_a = root / "docA.pdf"
    c = canvas.Canvas(str(doc_a), pagesize=letter, invariant=1)
    c.setFont("Helvetica", 28)
    c.drawString(72, 700, "Patient Jane Example")
    c.drawString(72, 640, "Account 4417 1234 5678")
    c.setFillGray(0.0)
    c.rect(72, 630, 330, 40, fill=1, stroke=0)  # burn the account line
    c.showPage()
    c.setFont("Helvetica", 28)
    c.drawString(72, 700, "Second page for Jane Example")
    c.showPage()
    c.save()
    doc_b = root / "docB.pdf"
    c = canvas.Canvas(str(doc_b), pagesize=letter, invariant=1)
    c.setFont("Helvetica", 28)
    c.drawString(72, 700, "Invoice for Omar Sample")
    c.showPage()
    c.save()

    cells = root / "cells"

    def cell(
        doc_id: str, mode: str, region_set: str, pdf: Path, terms: list[str], regions: list
    ) -> None:
        d = cells / doc_id / mode / region_set
        d.mkdir(parents=True)
        shutil.copyfile(pdf, d / "output.pdf")
        regions_json = {
            "schema_version": 1,
            "doc_id": doc_id,
            "mode": mode,
            "region_set": region_set,
            "region_source": "synthetic",
            "sensitive_terms": [{"text": t} for t in terms],
            "expected_visible_terms": [],
            "regions": regions,
        }
        (d / "regions.json").write_text(json.dumps(regions_json, indent=1))
        report = {
            "overall": {"case": "pass", "message": ""},
            "layers": [{"name": "Text Extraction", "status": {"case": "pass"}}],
        }
        (d / "report.json").write_text(json.dumps(report, indent=1))
        (d / "cell.json").write_text("{}\n")

    rect = [72 / 612, 630 / 792, 330 / 612, 40 / 792]
    burned = [{"page": 0, "rect": rect, "value": "4417 1234 5678", "gt_id": "g1"}]
    cell("docA", "searchableRedaction", "set1", doc_a, ["4417 1234 5678", "Jane Example"], burned)
    cell("docA", "searchableRedaction", "set2", doc_a, ["Jane Example"], [])
    cell("docB", "secureRasterization", "set1", doc_b, ["Omar Sample"], [])
    return cells


def _partials(cells_dir: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(cells_dir)): p.read_bytes()
        for p in sorted(cells_dir.glob("*/*/*/oracle-partial.json"))
    }


def _clean_outputs(cells_dir: Path) -> None:
    for p in cells_dir.glob("*/*/*/oracle-partial.json"):
        p.unlink()
    for d in (
        *cells_dir.glob("*/*/*/render"),
        *cells_dir.glob("*/*/*/oracle-work"),
        cells_dir / "vision-in",
        cells_dir / "_pages",
    ):
        shutil.rmtree(d, ignore_errors=True)


@needs_tools
def test_scan_parallel_matches_serial(tmp_path: Path) -> None:
    cells_dir = _fixture(tmp_path)
    cells = VO.discover_cells(cells_dir)
    assert [c.key for c in cells] == [
        "docA__searchableRedaction__set1",
        "docA__searchableRedaction__set2",
        "docB__secureRasterization__set1",
    ]
    dpi = 120
    serial_stats = VO._scan_cells(
        cells_dir, cells, mode="scan", docs_root=None, dpi=dpi, jobs=1, cache_dir=None
    )
    serial = _partials(cells_dir)
    assert len(serial) == 3
    assert serial_stats["distinct_pdfs"] == 2
    assert serial_stats["distinct_pages"] == 3
    assert serial_stats["cell_pages"] == 5
    assert serial_stats["hits"] == {} and serial_stats["misses"] == {}
    first = json.loads(serial["docA/searchableRedaction/set1/oracle-partial.json"])
    assert first["px_dims"] == {"0": [1020, 1320], "1": [1020, 1320]}
    assert [h["term"] for h in first["o1_hits"]] == ["4417 1234 5678", "Jane Example"]
    assert first["o5"]["regions"] == 1 and first["o5"]["fill_fail"] == []
    assert first["versions"]["tesseract"].startswith("tesseract ")
    # the per-cell corpora are deleted at the end of each cell unless keep_work
    work = cells_dir / "docA/searchableRedaction/set1/oracle-work"
    assert not (work / "qdf.pdf").exists() and not (work / "mu-clean.pdf").exists()

    _clean_outputs(cells_dir)
    cache_dir = tmp_path / "cache"
    cold = VO._scan_cells(
        cells_dir, cells, mode="scan", docs_root=None, dpi=dpi, jobs=4, cache_dir=cache_dir
    )
    assert _partials(cells_dir) == serial
    assert sum(cold["hits"].values()) == 0
    assert cold["misses"] == {
        "render_pp": 3,
        "render_mu": 3,
        "ocr_psm6": 3,
        "ocr_psm11": 3,
        "ocr_psm12": 3,
    }
    for cell in cells:
        links = sorted(p.name for p in (cell.dir / "render").iterdir())
        n = 2 if cell.doc_id == "docA" else 1
        assert links == sorted(
            [f"pp-{i}.png" for i in range(1, n + 1)] + [f"mu-{i}.png" for i in range(1, n + 1)]
        )
        for link in (cell.dir / "render").iterdir():
            assert link.is_symlink() and link.resolve().is_relative_to(cache_dir)
    vision_in = sorted(cells_dir.glob("vision-in/*"))
    assert [p.name for p in vision_in] == [
        "docA__searchableRedaction__set1__pp-1.png",
        "docA__searchableRedaction__set1__pp-2.png",
        "docA__searchableRedaction__set2__pp-1.png",
        "docA__searchableRedaction__set2__pp-2.png",
        "docB__secureRasterization__set1__pp-1.png",
    ]
    assert all(p.is_symlink() and p.resolve().is_file() for p in vision_in)

    _clean_outputs(cells_dir)
    warm = VO._scan_cells(
        cells_dir,
        cells,
        mode="scan",
        docs_root=None,
        dpi=dpi,
        jobs=4,
        cache_dir=cache_dir,
        keep_work=True,
    )
    assert _partials(cells_dir) == serial
    assert sum(warm["misses"].values()) == 0
    assert warm["hits"] == cold["misses"]
    assert (work / "qdf.pdf").exists() and (work / "mu-clean.pdf").exists()


# ---------------------------------------------------------------- (4) the PSM-6 file renderers


@needs_tools
def test_psm6_file_renderers_equal_stdout(tmp_path: Path) -> None:
    _fixture(tmp_path)
    pdf = tmp_path / "docB.pdf"
    subprocess.run(
        [
            "pdftoppm",
            "-r",
            "150",
            "-gray",
            "-png",
            "-f",
            "1",
            "-l",
            "1",
            str(pdf),
            str(tmp_path / "pp"),
        ],
        check=True,
    )
    png = tmp_path / "pp-1.png"
    assert png.is_file()
    txt, tsv = VO.ocr_psm6_files(png, tmp_path / "psm6")
    common = ["--oem", "1", "--psm", "6", "-c", "preserve_interword_spaces=1"]
    stdout_txt = subprocess.run(
        ["tesseract", str(png), "stdout", *common], capture_output=True, check=True
    ).stdout
    stdout_tsv = subprocess.run(
        ["tesseract", str(png), "stdout", *common, "tsv"], capture_output=True, check=True
    ).stdout
    assert txt.read_bytes() == stdout_txt
    assert tsv.read_bytes() == stdout_tsv
    assert b"Omar" in stdout_txt or b"Sample" in stdout_txt
