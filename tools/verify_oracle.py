"""verify_oracle.py — H2.3 oracle runner v0 over H2.2 verification-corpus cells.

Layered, ANY-HIT = FAIL, recall-first (1.2 instrumentation plan §5). Consumes the cells an
engine-side `VerificationCorpusRunnerTests` run wrote (`<cells>/<doc>/<mode>/<set>/` with
output.pdf + regions.json + report.json) and classifies every cell's verdict against an
independent recovery stack:

  O0  qpdf/mutool normalize + structure census; multi-revision scan on the ORIGINAL output
      bytes (QDF drops prior revisions), per-revision decompression where parseable.
  O1  text extractors x2 (pdftotext -layout AND -raw; mutool stext glyph boxes) + PyMuPDF
      rawdict char flags — region-localized where geometry exists.
  O2  decompressed-byte search (QDF + mutool clean + raw revision slices): literal, hex-string,
      octal-escaped, UTF-16BE(±BOM), TJ/Tj-reassembly (kern-stripped), case variants; plus
      pdfimages -all → exiftool EXIF census.
  O3  OCR x2: pdftoppm 400 DPI (renderer independent of the verifier) → Tesseract oem 1 with
      PSM 6 union 11 union 12, and Vision .accurate via the engine test target's
      `VisionOracleEmitterTests` (run between `scan` and `finalize`). OCR-only hits need
      quorum (Tesseract ∧ Vision) or fall to a review flag. Positive oracle only — a clean
      OCR pass proves nothing (JBIG2 caveat).
  O4  structure census: pdffonts (Type3 / missing ToUnicode / no-text-fonts), pdfimages -list,
      qpdf --json object walk; per-page `extractor_blind` flag.
  O5  pixel oracle: per-burned-region crops from TWO renderers (pdftoppm 400 / mutool 300),
      MAX channel deviation with 2 px border erosion; placement IoU vs the burned box
      (near-black connected component).
  O6  independent byte/term search over the raw output bytes: UTF-8/UTF-16BE, hex- and
      base64-encoded, UTF-7 adversarial probes.

Term scope: a burned value that survives legitimately elsewhere (an unburned GT occurrence,
a carried_stmt value, a source-text count above the burned-box count, or a declared
expected-visible term) is AMBIENT — only region-localized evidence (stext geometry, localized
OCR, pixels) counts against it. UNIQUE terms count document-wide, except OCR out-of-region
hits, which fall to review (OCR localization exists; an out-of-region OCR sighting of a
"unique" term is more often a ground-truth cataloguing gap than a filter miss — the text
legs adjudicate those).

Classification per cell (registers/10- §2): verdict ∈ {pass, info, warn} with any leak-class
hit → false_pass; clean → true_pass. attention → attention_true / attention_false.
fail → true_fail / false_fail. attributed_layer = the first report layer carrying the
verdict-driving status. A benign /Info (Producer/dates/creator only, no term match) is a
note, never a hit.

Usage:
  python tools/verify_oracle.py scan --cells <run>/cells --docs-root <sd-root> \
      [--jobs N] [--jobs-cells M] [--cache-dir DIR | --no-cache] [--cache-max-gb G] \\
      [--keep-work] [--dpi 400]
  # then the printed engine-test Vision command, then:
  python tools/verify_oracle.py finalize --cells <run>/cells [--keep-renders]

  # T2.2 oracle-recall calibration (P1.4, M12-12) -- the oracle runs DIRECTLY over the
  # planted corpus (each plant is a KNOWN leak it must find; no redaction pass):
  python tools/verify_oracle.py calibrate --planted <sd-root>/planted --out <run>/calibration
  # then the printed Vision command, then:
  python tools/verify_oracle.py calibrate-finalize --planted <sd-root>/planted --out <run>/calibration

  # PB-86 hidden-text re-exposure analysis over H2.2 section-E cells (M12-11):
  python tools/verify_oracle.py pb86 --cells <run>/cells

  # the cross-run tool-output cache (page renders + Tesseract text; never verdicts):
  python tools/verify_oracle.py cache-stats --cache-dir DIR
  python tools/verify_oracle.py cache-prune --cache-dir DIR [--max-gb G]

scan and calibrate run every DISTINCT (output.pdf, page) once — the two renders and the three
Tesseract recognitions — through a process pool of --jobs workers (default: every core), then
every cell's classification-bearing legs through the same pool; the records are byte-identical to
a serial run. --cache-dir (or RESECTA_ORACLE_CACHE) keeps the renders and the recognised text
across runs, keyed by input sha256 + argv + tool version (+ traineddata sha for OCR); --no-cache
turns it off (the pages then live in <cells>/_pages/ until finalize removes them). The per-cell
corpora (qdf, mu-clean, revision slices, extracted images) are deleted at the end of each cell
unless --keep-work; the partial's path fields are recorded before that.

Runs with the sd worktree venv (pymupdf + numpy + cv2 present); external tools per the D12-20
inventory (qpdf, mutool, poppler, tesseract, exiftool). Every run records tool versions.
"""

from __future__ import annotations

import argparse
import base64
import concurrent.futures
import contextlib
import hashlib
import json
import multiprocessing
import os
import re
import resource
import secrets
import shutil
import struct
import subprocess
import sys
import time
import unicodedata
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

SCHEMA_VERSION = 1
FILL_MAX_DEV = 13  # ≈5% of 255 — JPEG-artifact allowance inside a solid fill
NEAR_BLACK = 60  # component threshold for the placement mask
ERODE_PX = 2
FUZZY_MAX = 0.15  # normalized Levenshtein ceiling for OCR fuzzy matches
IN_REGION_COVERAGE = 0.5  # fraction of a hit box inside a region to count as in-region

STRUCTURE_KEYS = [
    "/JavaScript",
    "/OpenAction",
    "/AA",
    "/EmbeddedFiles",
    "/AcroForm",
    "/Metadata",
    "/Thumb",
    "/Outlines",
    "/OCProperties",
]
BENIGN_INFO = {"format", "encryption", "producer", "creationDate", "modDate", "creator"}


def run_raw(cmd: list[str], timeout: int = 300) -> tuple[int, bytes, bytes]:
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)
        return p.returncode, p.stdout, p.stderr
    except FileNotFoundError:
        return 127, b"", f"not found: {cmd[0]}".encode()
    except subprocess.TimeoutExpired:
        return 124, b"", f"timeout: {' '.join(cmd[:3])}".encode()


def run(cmd: list[str], timeout: int = 300) -> tuple[int, str, str]:
    rc, out, err = run_raw(cmd, timeout)
    return rc, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")


def run_bytes(cmd: list[str], timeout: int = 300) -> bytes:
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)
        return p.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return b""


def fold(s: str) -> str:
    s = unicodedata.normalize("NFC", s).casefold()
    return re.sub(r"\s+", " ", s).strip()


def fold_nospace(s: str) -> str:
    return re.sub(r"\s+", "", fold(s))


def levenshtein(a: str, b: str) -> int:
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def trigrams(s: str) -> set[str]:
    t = fold_nospace(s)
    return {t[i : i + 3] for i in range(len(t) - 2)} if len(t) >= 3 else {t} if t else set()


def fuzzy_find(term: str, text: str) -> bool:
    """Sliding token-window fuzzy match, trigram-prefiltered (OCR legs)."""
    ft, fx = fold(term), fold(text)
    if not ft or not fx:
        return False
    if ft in fx or fold_nospace(term) in fold_nospace(text):
        return True
    tg = trigrams(term)
    if tg and len(tg & trigrams(text)) < max(1, len(tg) // 2):
        return False
    words = fx.split()
    k = max(1, len(ft.split()))
    for width in (k, k + 1):
        for i in range(0, max(0, len(words) - width) + 1):
            window = " ".join(words[i : i + width])
            if abs(len(window) - len(ft)) > max(2, int(len(ft) * 0.4)):
                continue
            if levenshtein(window, ft) / max(len(ft), len(window)) <= FUZZY_MAX:
                return True
    return False


def sh256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------- geometry


def region_to_px(rect: list[float], page_w_px: int, page_h_px: int) -> tuple[int, int, int, int]:
    """Normalized bottom-left [x,y,w,h] -> raster (left, top, right, bottom) px."""
    x, y, w, h = rect
    left = round(x * page_w_px)
    right = round((x + w) * page_w_px)
    top = round((1.0 - y - h) * page_h_px)
    bottom = round((1.0 - y) * page_h_px)
    return left, top, right, bottom


def region_to_pt(
    rect: list[float], page_w: float, page_h: float
) -> tuple[float, float, float, float]:
    """Normalized bottom-left [x,y,w,h] -> top-left-origin points (l, t, r, b)."""
    x, y, w, h = rect
    return x * page_w, (1.0 - y - h) * page_h, (x + w) * page_w, (1.0 - y) * page_h


def box_coverage(
    box: tuple[float, float, float, float], region: tuple[float, float, float, float]
) -> float:
    left = max(box[0], region[0])
    t = max(box[1], region[1])
    r = min(box[2], region[2])
    b = min(box[3], region[3])
    if r <= left or b <= t:
        return 0.0
    area = (box[2] - box[0]) * (box[3] - box[1])
    return ((r - left) * (b - t)) / area if area > 0 else 0.0


# ---------------------------------------------------------------- cell model


class Cell:
    def __init__(self, cell_dir: Path):
        self.dir = cell_dir
        self.regions = json.loads((cell_dir / "regions.json").read_text())
        self.report = json.loads((cell_dir / "report.json").read_text())
        self.output = cell_dir / "output.pdf"
        self.doc_id = self.regions["doc_id"]
        self.mode = self.regions["mode"]
        self.region_set = self.regions["region_set"]
        self.key = f"{self.doc_id}__{self.mode}__{self.region_set}"
        self.terms = [t["text"] for t in self.regions.get("sensitive_terms", [])]
        self.expected_visible = set(self.regions.get("expected_visible_terms", []))
        self.burned = self.regions.get("regions", [])

    def burned_by_page(self) -> dict[int, list[list[float]]]:
        out: dict[int, list[list[float]]] = {}
        for r in self.burned:
            out.setdefault(int(r["page"]), []).append([float(v) for v in r["rect"]])
        return out


def discover_cells(cells_dir: Path) -> list[Cell]:
    cells = []
    for rj in sorted(cells_dir.glob("*/*/*/regions.json")):
        d = rj.parent
        if (d / "output.pdf").exists() and (d / "report.json").exists():
            cells.append(Cell(d))
    return cells


# ---------------------------------------------------------------- term scope


def compute_term_scope(cell: Cell, docs_root: Path | None) -> dict[str, str]:
    """unique | ambient per term (module docstring rules)."""
    scope: dict[str, str] = {}
    burned_values: dict[str, int] = {}
    burned_ids = set()
    for r in cell.burned:
        if r.get("value"):
            burned_values[r["value"]] = burned_values.get(r["value"], 0) + 1
        if r.get("gt_id"):
            burned_ids.add(r["gt_id"])

    ambient_values: set[str] = set(cell.expected_visible)
    source_text = ""
    if docs_root is not None and cell.regions.get("region_source") == "gt":
        manifest_path = docs_root / "documents.manifest.json"
        if manifest_path.exists():
            for row in json.loads(manifest_path.read_text()):
                if row.get("id") != cell.doc_id:
                    continue
                gt_path = docs_root / row["gt"] if row.get("gt") else None
                if gt_path and gt_path.exists():
                    gt = json.loads(gt_path.read_text())
                    for occ in gt.get("occurrences", []):
                        if occ.get("id") not in burned_ids and occ.get("value"):
                            ambient_values.add(occ["value"])
                    for occ in gt.get("carried_stmt", []) or []:
                        if occ.get("value"):
                            ambient_values.add(occ["value"])
                src = docs_root / row["path"]
                if src.exists():
                    source_text = fold(
                        run_bytes(
                            ["pdftotext", "-raw", "-enc", "UTF-8", "-nopgbrk", str(src), "-"]
                        ).decode("utf-8", "replace")
                    )
                break

    ambient_folded = {fold(v) for v in ambient_values}
    for term in cell.terms:
        ft = fold(term)
        ambient = ft in ambient_folded or term in cell.expected_visible
        if not ambient and source_text and source_text.count(ft) > burned_values.get(term, 0):
            ambient = True
        scope[term] = "ambient" if ambient else "unique"
    return scope


# ---------------------------------------------------------------- O0 / O4


def walk_json_keys(node: object, found: set[str]) -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            if isinstance(k, str) and k in STRUCTURE_KEYS:
                found.add(k)
            walk_json_keys(v, found)
    elif isinstance(node, list):
        for v in node:
            walk_json_keys(v, found)


def o0_structure(cell: Cell | CalCell, workdir: Path) -> dict:
    raw = cell.output.read_bytes()
    revisions = raw.count(b"%%EOF")
    rc_check, out_check, err_check = run(["qpdf", "--check", str(cell.output)])
    qdf = workdir / "qdf.pdf"
    run(["qpdf", "--qdf", "--object-streams=disable", str(cell.output), str(qdf)])
    mu_clean = workdir / "mu-clean.pdf"
    run(["mutool", "clean", "-d", str(cell.output), str(mu_clean)])

    json_keys: set[str] = set()
    rc, out, _ = run(["qpdf", "--json=2", str(cell.output)])
    acroform_has_v = False
    if rc == 0 and out:
        with contextlib.suppress(json.JSONDecodeError):
            walk_json_keys(json.loads(out), json_keys)
    qdf_bytes = qdf.read_bytes() if qdf.exists() else b""
    byte_keys = {k for k in STRUCTURE_KEYS if k.encode() in qdf_bytes or k.encode() in raw}
    if "/AcroForm" in json_keys | byte_keys:
        acroform_has_v = bool(re.search(rb"/V\s*[(<\[/]", qdf_bytes))

    import pymupdf

    info_extra: dict[str, str] = {}
    annots_pages: list[int] = []
    try:
        doc = pymupdf.open(cell.output)
        for k, v in (doc.metadata or {}).items():
            if v and k not in BENIGN_INFO:
                info_extra[k] = str(v)
        for i, page in enumerate(doc.pages()):
            if list(page.annots() or []):
                annots_pages.append(i)
        doc.close()
    except Exception as e:  # census stays best-effort per tool
        info_extra["_pymupdf_error"] = str(e)

    return {
        "qpdf_check_ok": rc_check == 0,
        "qpdf_check_tail": (out_check + err_check).strip().splitlines()[-1:]
        if (out_check or err_check)
        else [],
        "revisions": revisions,
        "structure_keys_json": sorted(json_keys),
        "structure_keys_bytes": sorted(byte_keys),
        "acroform_has_v": acroform_has_v,
        "info_extra_keys": info_extra,
        "annots_pages": annots_pages,
        "qdf_path": str(qdf) if qdf.exists() else None,
        "mu_clean_path": str(mu_clean) if mu_clean.exists() else None,
    }


def o4_census(cell: Cell | CalCell) -> dict:
    _, fonts_out, _ = run(["pdffonts", str(cell.output)])
    font_rows = fonts_out.splitlines()[2:]
    type3 = [r for r in font_rows if " Type 3 " in f" {r} "]
    no_tounicode = []
    for r in font_rows:
        cols = r.split()
        if len(cols) >= 5 and cols[-5] == "no":  # "uni" column
            no_tounicode.append(r.strip())
    _, imgs_out, _ = run(["pdfimages", "-list", str(cell.output)])
    image_rows = max(0, len(imgs_out.splitlines()) - 2)
    return {
        "font_rows": len(font_rows),
        "type3_rows": len(type3),
        "no_tounicode_rows": len(no_tounicode),
        "image_rows": image_rows,
        "no_text_fonts": len(font_rows) == 0,
    }


# ---------------------------------------------------------------- O1


def stext_pages(
    output: Path,
) -> list[tuple[float, float, list[tuple[str, tuple[float, float, float, float]]]]]:
    """Per page: (width, height, [(char, (l,t,r,b))...]) from mutool stext."""
    xml = run_bytes(["mutool", "draw", "-q", "-F", "stext", "-o", "-", str(output)])
    pages = []
    try:
        root = ElementTree.fromstring(  # noqa: S314 -- parses the synthetic fixture XML this tool itself wrote
            b"<all>" + xml + b"</all>"
        )
    except ElementTree.ParseError:
        try:
            root = ElementTree.fromstring(  # noqa: S314 -- parses the synthetic fixture XML this tool itself wrote
                xml
            )
        except ElementTree.ParseError:
            return []
    for page in root.iter("page"):
        w = float(page.get("width", "612"))
        h = float(page.get("height", "792"))
        chars: list[tuple[str, tuple[float, float, float, float]]] = []
        for ch in page.iter("char"):
            c = ch.get("c", "")
            quad = ch.get("quad")
            if quad:
                q = [float(v) for v in quad.split()]
                xs, ys = q[0::2], q[1::2]
                chars.append((c, (min(xs), min(ys), max(xs), max(ys))))
            else:
                x, y = float(ch.get("x", "0")), float(ch.get("y", "0"))
                chars.append((c, (x, y - 8, x + 4, y)))
        pages.append((w, h, chars))
    return pages


def o1_text_layer(cell: Cell | CalCell, scope: dict[str, str]) -> tuple[list[dict], dict]:
    hits: list[dict] = []
    pdftotext_layout = run_bytes(
        ["pdftotext", "-layout", "-enc", "UTF-8", "-nopgbrk", str(cell.output), "-"]
    ).decode("utf-8", "replace")
    pdftotext_raw = run_bytes(
        ["pdftotext", "-raw", "-enc", "UTF-8", "-nopgbrk", str(cell.output), "-"]
    ).decode("utf-8", "replace")
    pages = stext_pages(cell.output)
    burned = cell.burned_by_page()

    import pymupdf

    rawdict_flags: dict[int, dict[str, int]] = {}
    rawdict_text: dict[int, str] = {}
    with contextlib.suppress(Exception):
        doc = pymupdf.open(cell.output)
        for i, page in enumerate(doc.pages()):
            rd = page.get_text("rawdict")
            buf: list[str] = []
            flag_hist: dict[str, int] = {}
            for block in rd.get("blocks", []):
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        for ch in span.get("chars", []):
                            buf.append(ch.get("c", ""))
                            cf = ch.get("char_flags", span.get("char_flags"))
                            if cf is not None:
                                flag_hist[str(cf)] = flag_hist.get(str(cf), 0) + 1
                    buf.append("\n")
            rawdict_text[i] = "".join(buf)
            if flag_hist:
                rawdict_flags[i] = flag_hist
        doc.close()

    folded_extractor = {
        "pdftotext-layout": fold(pdftotext_layout),
        "pdftotext-raw": fold(pdftotext_raw),
        "pymupdf-rawdict": fold("\n".join(rawdict_text.values())),
    }
    for term in cell.terms:
        ft = fold(term)
        found_in = [name for name, text in folded_extractor.items() if ft and ft in text]
        # Region-localized stext pass: where does the term sit, and is any
        # occurrence inside a burned region?
        localized: list[dict] = []
        for pageno, (w, h, chars) in enumerate(pages):
            if not chars:
                continue
            stream = fold_nospace("".join(c for c, _ in chars))
            needle = fold_nospace(term)
            if not needle or needle not in stream:
                continue
            # map char indices: rebuild with positions
            flat = [(c, b) for c, b in chars if fold_nospace(c)]
            joined = "".join(fold_nospace(c) for c, _ in flat)
            start = joined.find(needle)
            while start != -1:
                seg = flat[start : start + len(needle)]
                if seg:
                    left = min(b[0] for _, b in seg)
                    t = min(b[1] for _, b in seg)
                    r = max(b[2] for _, b in seg)
                    bt = max(b[3] for _, b in seg)
                    in_region = any(
                        box_coverage((left, t, r, bt), region_to_pt(reg, w, h))
                        >= IN_REGION_COVERAGE
                        for reg in burned.get(pageno, [])
                    )
                    localized.append({"page": pageno, "in_region": in_region})
                start = joined.find(needle, start + 1)
        if found_in or localized:
            in_region_hits = [x for x in localized if x["in_region"]]
            is_leak = bool(in_region_hits) or (
                scope.get(term) == "unique" and (found_in or localized)
            )
            hits.append(
                {
                    "surface": "text_layer",
                    "term": term,
                    "scope": scope.get(term, "unique"),
                    "extractors": found_in,
                    "localized": localized,
                    "leak": is_leak,
                    "detail": "in-region text-layer content"
                    if in_region_hits
                    else "term present in output text layer",
                }
            )
    diag = {"rawdict_char_flags": rawdict_flags}
    return hits, diag


# ---------------------------------------------------------------- O2


def octal_escape(term: str) -> bytes:
    return "".join(f"\\{ord(c):03o}" for c in term).encode()


def hex_string(term: str) -> bytes:
    return term.encode("latin-1", "replace").hex().encode()


# A PDF literal string operand: `(` … `)` with `\x` escapes. This is the unrolled-loop form of
# `\(((?:[^()\\]|\\.)*)\)` — the same language (the plain-char and escape alternatives are
# disjoint, so the tokenisation is unique and both engines try the same candidate ends in the same
# order) — but it does not keep per-iteration backtracking state over the megabyte paren-free runs
# a `mutool clean -d` corpus of decoded raster contains (3.5 GB / 2.9 s → 72 MB / 0.7 s on 51 MB).
# tests/test_verify_oracle.py holds the old form and proves span- and output-equality.
TJ_OPERAND_RE = re.compile(rb"\(([^()\\]*(?:\\.[^()\\]*)*)\)")


def _tj_operands(qdf_bytes: bytes):
    """The string operands of Tj/TJ/'/\" show ops, unescaped, as latin-1 text, in order."""
    for m in TJ_OPERAND_RE.finditer(qdf_bytes):
        raw = m.group(1)
        raw = re.sub(rb"\\([0-7]{1,3})", lambda g: bytes([int(g.group(1), 8) & 0xFF]), raw)
        raw = raw.replace(b"\\(", b"(").replace(b"\\)", b")").replace(b"\\\\", b"\\")
        yield raw.decode("latin-1", "replace")


def tj_reassembled(qdf_bytes: bytes) -> str:
    """Concatenate string operands of Tj/TJ/'/\" show ops, kern numbers stripped."""
    return "".join(_tj_operands(qdf_bytes))


TJ_CHUNK_CHARS = 4_000_000


def tj_terms_present(
    qdf_bytes: bytes, folded_terms: list[str], chunk_chars: int = TJ_CHUNK_CHARS
) -> set[str]:
    """Which folded terms occur in fold_nospace(tj_reassembled(qdf_bytes)) — computed without
    materialising that string. The operands are latin-1 text, on which NFC is the identity and
    casefold / whitespace removal act per code point, so folding chunk by chunk concatenates to
    the whole fold; a term straddling two chunks is caught in the overlap window (the last and
    first max-term-length - 1 folded characters of the two chunks). Presence per term is
    therefore exactly that of the whole-string test."""
    terms = [t for t in folded_terms if t]
    if not terms:
        return set()
    window = max(len(t) for t in terms) - 1
    present: set[str] = set()
    pending = list(terms)
    buf: list[str] = []
    size = 0
    tail = ""

    def flush() -> None:
        nonlocal buf, size, tail, pending
        folded = fold_nospace("".join(buf))
        buf, size = [], 0
        joint = tail + folded[:window] if window else ""
        pending = [t for t in pending if t not in folded and t not in joint]
        present.update(set(terms) - set(pending))
        tail = (tail + folded)[-window:] if window else ""  # rolling: a term may span chunks

    for piece in _tj_operands(qdf_bytes):
        buf.append(piece)
        size += len(piece)
        if size >= chunk_chars:
            flush()
            if not pending:
                return present
    if buf:
        flush()
    return present


def o2_bytes(cell: Cell | CalCell, o0: dict, scope: dict[str, str], workdir: Path) -> list[dict]:
    hits: list[dict] = []
    raw = cell.output.read_bytes()
    corpora: dict[str, bytes] = {"raw": raw}
    for name in ("qdf_path", "mu_clean_path"):
        p = o0.get(name)
        if p and Path(p).exists():
            corpora[name.replace("_path", "")] = Path(p).read_bytes()
    # Per-revision slices of the ORIGINAL bytes, decompressed where qpdf can.
    if o0["revisions"] > 1:
        offsets = [m.end() for m in re.finditer(rb"%%EOF", raw)]
        for i, off in enumerate(offsets[:-1]):
            slice_path = workdir / f"rev{i}.pdf"
            slice_path.write_bytes(raw[:off])
            rev_qdf = workdir / f"rev{i}-qdf.pdf"
            rc, _, _ = run(
                ["qpdf", "--qdf", "--object-streams=disable", str(slice_path), str(rev_qdf)]
            )
            corpora[f"revision-{i}"] = (
                rev_qdf.read_bytes() if rc == 0 and rev_qdf.exists() else raw[:off]
            )
    folded_terms = [fold_nospace(t) for t in cell.terms]
    tj_present = {
        name: tj_terms_present(data, folded_terms)
        for name, data in corpora.items()
        if name != "raw"
    }

    for term in cell.terms:
        found: list[str] = []
        variants = {term, term.upper(), term.lower()}
        for name, data in corpora.items():
            for v in variants:
                if (
                    v.encode("utf-8") in data
                    or v.encode("utf-16-be") in data
                    or (b"\xfe\xff" + v.encode("utf-16-be")) in data
                    or hex_string(v) in data
                    or hex_string(v).upper() in data
                    or octal_escape(v) in data
                ):
                    found.append(name)
                    break
        for name, present in tj_present.items():
            if fold_nospace(term) and fold_nospace(term) in present:
                found.append(f"{name}-tj")
        if found:
            hits.append(
                {
                    "surface": "decompressed_bytes",
                    "term": term,
                    "scope": scope.get(term, "unique"),
                    "corpora": sorted(set(found)),
                    # Byte legs have no geometry: ambient terms legitimately
                    # remain in the bytes; only unique terms are leak evidence.
                    "leak": scope.get(term) == "unique",
                    "detail": "term recoverable from output bytes",
                }
            )

    # EXIF via extracted images (JPEG passthrough keeps APP1).
    imgdir = workdir / "imgs"
    imgdir.mkdir(exist_ok=True)
    run(["pdfimages", "-all", str(cell.output), str(imgdir / "img")])
    extracted = sorted(imgdir.glob("img-*"))
    if extracted:
        rc, out, _ = run(["exiftool", "-j", "-n", *map(str, extracted)])
        if rc == 0 and out:
            try:
                metas = json.loads(out)
            except json.JSONDecodeError:
                metas = []
            for meta in metas:
                gps = {k: v for k, v in meta.items() if k.startswith("GPS")}
                if gps:
                    hits.append(
                        {
                            "surface": "image",
                            "term": None,
                            "scope": "unique",
                            "leak": True,
                            "detail": f"GPS EXIF survives in extracted image "
                            f"{Path(meta.get('SourceFile', '?')).name}: "
                            f"{sorted(gps)[:4]}",
                        }
                    )
                term_hits = [
                    t for t in cell.terms if any(fold(t) in fold(str(v)) for v in meta.values())
                ]
                for t in term_hits:
                    hits.append(
                        {
                            "surface": "image",
                            "term": t,
                            "scope": scope.get(t, "unique"),
                            "leak": scope.get(t) == "unique",
                            "detail": "term in extracted-image metadata",
                        }
                    )
    return hits


# ---------------------------------------------------------------- O3


def _read_text(path: Path | None) -> str:
    return (
        path.read_bytes().decode("utf-8", "replace") if path is not None and path.is_file() else ""
    )


def o3_tesseract(
    cell: Cell | CalCell, render_dir: Path, ocr_files: dict[int, dict[str, Path | None]]
) -> dict:
    """Per page, ascending: union text over PSM 6/11/12 + PSM-6 TSV word boxes, read from the
    text the page phase recognised (PSM 6 txt+tsv by file renderers, PSM 11/12 stdout)."""
    pages: dict[int, dict] = {}
    for png in sorted(render_dir.glob("pp-*.png")):
        m = re.search(r"pp-0*(\d+)\.png$", png.name)
        if not m:
            continue
        pageno = int(m.group(1)) - 1
        files = ocr_files.get(pageno, {})
        texts = [_read_text(files.get(k)) for k in ("psm6_txt", "psm11", "psm12")]
        tsv = _read_text(files.get("psm6_tsv"))
        words: list[tuple[str, tuple[float, float, float, float]]] = []
        for line in tsv.splitlines()[1:]:
            cols = line.split("\t")
            if len(cols) >= 12 and cols[11].strip():
                try:
                    left, top, w, h = (
                        float(cols[6]),
                        float(cols[7]),
                        float(cols[8]),
                        float(cols[9]),
                    )
                except ValueError:
                    continue
                words.append((cols[11], (left, top, left + w, top + h)))
        pages[pageno] = {"text": "\n".join(texts), "words": words, "png": png.name}
    return pages


def ocr_hits_for_engine(
    cell: Cell | CalCell,
    page_texts: dict[int, str],
    page_words: dict[int, list[tuple[str, tuple[float, float, float, float]]]],
    px_dims: dict[int, tuple[int, int]],
) -> dict[str, list[dict]]:
    burned = cell.burned_by_page()
    out: dict[str, list[dict]] = {}
    for term in cell.terms:
        term_hits = []
        for pageno, text in page_texts.items():
            if not fuzzy_find(term, text):
                continue
            in_region = False
            words = page_words.get(pageno, [])
            dims = px_dims.get(pageno)
            if words and dims:
                k = max(1, len(fold(term).split()))
                for i in range(0, max(0, len(words) - k) + 1):
                    seg = words[i : i + k]
                    window = " ".join(w for w, _ in seg)
                    if (
                        levenshtein(fold(window), fold(term))
                        / max(len(fold(term)), len(fold(window)), 1)
                        <= FUZZY_MAX
                    ):
                        left = min(b[0] for _, b in seg)
                        t = min(b[1] for _, b in seg)
                        r = max(b[2] for _, b in seg)
                        bt = max(b[3] for _, b in seg)
                        for reg in burned.get(pageno, []):
                            if (
                                box_coverage((left, t, r, bt), region_to_px(reg, dims[0], dims[1]))
                                >= IN_REGION_COVERAGE
                            ):
                                in_region = True
                                break
                    if in_region:
                        break
            term_hits.append({"page": pageno, "in_region": in_region})
        if term_hits:
            out[term] = term_hits
    return out


# ---------------------------------------------------------------- O5


def o5_pixels(cell: Cell, render_dir: Path, workdir: Path) -> dict:
    import cv2
    import numpy as np

    result: dict[str, Any] = {
        "regions": 0,
        "fill_fail": [],
        "iou": [],
        "max_dev_pp": 0,
        "max_dev_mu": 0,
    }
    burned = cell.burned_by_page()
    pp = {}
    for p in render_dir.glob("pp-*.png"):
        m = re.search(r"pp-0*(\d+)", p.name)
        if m is not None:
            pp[int(m.group(1)) - 1] = p
    mu = {}
    for p in render_dir.glob("mu-*.png"):
        m = re.search(r"mu-0*(\d+)", p.name)
        if m is not None:
            mu[int(m.group(1)) - 1] = p
    for pageno, regions in burned.items():
        img_pp = cv2.imread(str(pp[pageno]), cv2.IMREAD_GRAYSCALE) if pageno in pp else None
        img_mu = cv2.imread(str(mu[pageno]), cv2.IMREAD_GRAYSCALE) if pageno in mu else None
        if img_pp is None:
            continue
        h_pp, w_pp = img_pp.shape
        mask = (img_pp <= NEAR_BLACK).astype(np.uint8)
        _n_comp, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        for idx, reg in enumerate(regions):
            result["regions"] += 1
            for img, tag in ((img_pp, "pp"), (img_mu, "mu")):
                if img is None:
                    continue
                ih, iw = img.shape
                left, t, r, b = region_to_px(reg, iw, ih)
                li, ti = left + ERODE_PX, t + ERODE_PX
                ri, bi = r - ERODE_PX, b - ERODE_PX
                if ri - li < 2 or bi - ti < 2:
                    continue
                crop = img[max(0, ti) : max(0, bi), max(0, li) : max(0, ri)]
                if crop.size == 0:
                    continue
                dev = int(crop.max())  # deviation from black fill = the value itself
                result[f"max_dev_{tag}"] = max(result[f"max_dev_{tag}"], dev)
                if dev > FILL_MAX_DEV:
                    crop_path = workdir / f"fillfail-p{pageno}-r{idx}-{tag}.png"
                    cv2.imwrite(str(crop_path), crop)
                    result["fill_fail"].append(
                        {
                            "page": pageno,
                            "region_index": idx,
                            "renderer": tag,
                            "max_dev": dev,
                            "crop": crop_path.name,
                        }
                    )
            # Placement IoU on the pdftoppm render.
            left, t, r, b = region_to_px(reg, w_pp, h_pp)
            left, t = max(0, left), max(0, t)
            r, b = min(w_pp, r), min(h_pp, b)
            if r <= left or b <= t:
                continue
            window = labels[t:b, left:r]
            comp_ids, counts = np.unique(window[window > 0], return_counts=True)
            if len(comp_ids) == 0:
                result["iou"].append({"page": pageno, "region_index": idx, "iou": 0.0})
                continue
            comp = int(comp_ids[np.argmax(counts)])
            cl, ct = int(stats[comp, cv2.CC_STAT_LEFT]), int(stats[comp, cv2.CC_STAT_TOP])
            cr = cl + int(stats[comp, cv2.CC_STAT_WIDTH])
            cb = ct + int(stats[comp, cv2.CC_STAT_HEIGHT])
            inter = max(0, min(r, cr) - max(left, cl)) * max(0, min(b, cb) - max(t, ct))
            union = (r - left) * (b - t) + (cr - cl) * (cb - ct) - inter
            result["iou"].append(
                {
                    "page": pageno,
                    "region_index": idx,
                    "iou": round(inter / union, 4) if union else 0.0,
                }
            )
    return result


# ---------------------------------------------------------------- O6


def utf7(term: str) -> bytes:
    try:
        return term.encode("utf-7")
    except Exception:
        return b""


def o6_adversarial(cell: Cell | CalCell, scope: dict[str, str]) -> list[dict]:
    raw = cell.output.read_bytes()
    hits = []
    for term in cell.terms:
        probes = {
            "utf-8": term.encode("utf-8"),
            "utf-16-be": term.encode("utf-16-be"),
            "utf-16-be-bom": b"\xfe\xff" + term.encode("utf-16-be"),
            "hex": term.encode().hex().encode(),
            "HEX": term.encode().hex().upper().encode(),
            "base64": base64.b64encode(term.encode()),
            "utf-7": utf7(term),
        }
        found = [name for name, probe in probes.items() if probe and probe in raw]
        # utf-8 presence duplicates O1/O2 literal searches; keep the exotic ones.
        exotic = [f for f in found if f not in ("utf-8",)]
        if exotic:
            hits.append(
                {
                    "surface": "decompressed_bytes",
                    "term": term,
                    "scope": scope.get(term, "unique"),
                    "encodings": exotic,
                    "leak": scope.get(term) == "unique",
                    "detail": "adversarial-encoding byte probe hit",
                }
            )
    return hits


# ---------------------------------------------------------------- versions


def tool_versions() -> dict[str, str]:
    import pymupdf

    vs: dict[str, str] = {"python": sys.version.split()[0], "pymupdf": pymupdf.__version__}
    for name, cmd, use_err in (
        ("pdftotext", ["pdftotext", "-v"], True),
        ("pdftoppm", ["pdftoppm", "-v"], True),
        ("qpdf", ["qpdf", "--version"], False),
        ("mutool", ["mutool", "-v"], True),
        ("tesseract", ["tesseract", "--version"], True),
        ("exiftool", ["exiftool", "-ver"], False),
    ):
        _, out, err = run(cmd, timeout=30)
        primary, secondary = (err, out) if use_err else (out, err)
        # Tesseract 5 prints --version to stdout; the other tools where the table says.
        line = primary.strip().splitlines() or secondary.strip().splitlines()
        vs[name] = line[0] if line else "?"
    return vs


# ---------------------------------------------------------------- phases


# ---------------------------------------------------------------- the parallel engine

# scan and calibrate share one engine. Phase A runs every DISTINCT (output.pdf, page) once: the
# pdftoppm render at --dpi (gray PNG), the mutool render at 300 DPI (scan only) and the three
# Tesseract recognitions (PSM 6 with the txt + tsv file renderers = ONE recognition, PSM 11,
# PSM 12), each step through the content-addressed cache or, without one, into the run-local
# `_pages/` dir. Phase B runs every cell: `render/` becomes symlinks to those page files, the
# `vision-in/` links are made, and the classification-bearing legs (term scope, O0-O2, O3 from
# the recognised text, O4-O6) run and write the cell's partial. Both phases run in a spawn-context
# process pool of --jobs workers; every record is assembled per cell in ascending page order, so
# the output is byte-identical to the serial engine's (tools/oracle_parity.py proves it).

CACHE_VERSION = "v1"
CACHE_STEPS = ("render_pp", "render_mu", "ocr_psm6", "ocr_psm11", "ocr_psm12")
DEFAULT_CACHE_MAX_GB = 20.0
MU_DPI = "300"
# Phase-B workers hold a cell's corpora (raw + qdf + mu-clean, up to ≈ 400 MB each) plus the
# renders; measured peak RSS per worker 1.55 GB on the 12/16-page JPEG-passthrough documents.
# By rule the cell phase is capped so that ten such workers cannot exceed an 8 GB budget:
# ⌊8 GB ÷ peak⌋ workers; --jobs-cells overrides.
PHASE_B_WORKER_PEAK_GB = 1.55
PHASE_B_BUDGET_GB = 8.0
TESSDATA_LANG = "eng.traineddata"


def cache_key(descriptor: dict) -> str:
    """sha256 of the canonical JSON of a step descriptor."""
    canonical = json.dumps(descriptor, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


class OracleCache:
    """Cross-run store of expensive tool OUTPUTS (page renders, Tesseract text) — never verdicts.

    Layout `<root>/v1/<step>/<key[:2]>/<key>/` = `meta.json` + the produced files; `key` = sha256
    of the canonical descriptor {step, input sha256, page, argv template with <IN>/<OUT>
    placeholders, tool version line, traineddata sha256 for OCR} — any argv or version change is
    a new key by construction. Entries are produced into a tmp dir and renamed into place (atomic
    on APFS; a loser whose target now exists deletes its tmp dir); readers accept only dirs that
    carry meta.json. A hit touches meta.json (the LRU clock; atime is unreliable); prune() drops
    the oldest entries first down to a byte cap."""

    def __init__(self, root: Path):
        self.root = root
        self.hits: dict[str, int] = dict.fromkeys(CACHE_STEPS, 0)
        self.misses: dict[str, int] = dict.fromkeys(CACHE_STEPS, 0)

    def entry_dir(self, step: str, key: str) -> Path:
        return self.root / CACHE_VERSION / step / key[:2] / key

    def get_or_produce(
        self, step: str, descriptor: dict, produce: Callable[[Path], bool]
    ) -> tuple[Path | None, bool]:
        """(entry dir, hit). `produce(out_dir)` writes the step's files there and returns
        whether it succeeded; nothing is stored for a failure."""
        key = cache_key(descriptor)
        entry = self.entry_dir(step, key)
        meta = entry / "meta.json"
        if meta.is_file():
            with contextlib.suppress(OSError):
                os.utime(meta)
            self.hits[step] = self.hits.get(step, 0) + 1
            return entry, True
        self.misses[step] = self.misses.get(step, 0) + 1
        entry.parent.mkdir(parents=True, exist_ok=True)
        tmp = entry.parent / f"{key}.tmp-{os.getpid()}-{secrets.token_hex(4)}"
        tmp.mkdir()
        try:
            if not produce(tmp):
                shutil.rmtree(tmp, ignore_errors=True)
                return None, False
            size = sum(p.stat().st_size for p in tmp.iterdir() if p.is_file())
            record = {
                "step": step,
                "key": key,
                "descriptor": descriptor,
                "created": time.time(),
                "bytes": size,
            }
            (tmp / "meta.json").write_text(json.dumps(record, indent=1, sort_keys=True))
            try:
                tmp.rename(entry)
            except OSError:
                if not meta.is_file():
                    raise
                shutil.rmtree(tmp, ignore_errors=True)  # a concurrent producer won the rename
        except BaseException:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        return entry, False

    def entries(self) -> list[tuple[Path, float, int]]:
        """(entry dir, meta mtime, bytes of the produced files) for every complete entry."""
        rows: list[tuple[Path, float, int]] = []
        for meta in self.root.glob(f"{CACHE_VERSION}/*/*/*/meta.json"):
            entry = meta.parent
            size = sum(
                p.stat().st_size for p in entry.iterdir() if p.is_file() and p.name != "meta.json"
            )
            rows.append((entry, meta.stat().st_mtime, size))
        return rows

    def stats(self) -> dict:
        rows = self.entries()
        by_step: dict[str, int] = {}
        for entry, _mtime, _size in rows:
            step = entry.parent.parent.name
            by_step[step] = by_step.get(step, 0) + 1
        return {
            "entries": len(rows),
            "bytes": sum(size for _entry, _mtime, size in rows),
            "by_step": dict(sorted(by_step.items())),
        }

    def prune(self, max_bytes: int) -> dict:
        """LRU by meta mtime: remove the oldest entries until the cache fits max_bytes; also
        drops tmp dirs older than a day (a crashed producer)."""
        rows = sorted(self.entries(), key=lambda r: (r[1], str(r[0])))
        total = sum(size for _entry, _mtime, size in rows)
        removed = {"entries": 0, "bytes": 0}
        for entry, _mtime, size in rows:
            if total <= max_bytes:
                break
            shutil.rmtree(entry, ignore_errors=True)
            total -= size
            removed["entries"] += 1
            removed["bytes"] += size
        for tmp in self.root.glob(f"{CACHE_VERSION}/*/*/*.tmp-*"):
            with contextlib.suppress(OSError):
                if time.time() - tmp.stat().st_mtime > 86_400:
                    shutil.rmtree(tmp, ignore_errors=True)
        return removed


def traineddata_sha256() -> str:
    """sha256 of Tesseract's eng.traineddata (part of every OCR key); "?" if unlocatable."""
    _, out, err = run(["tesseract", "--list-langs"], timeout=30)
    m = re.search(r'"([^"]+)"', out + err)
    if m:
        td = Path(m.group(1)) / TESSDATA_LANG
        if td.is_file():
            return sh256(td)
    return "?"


def pdf_page_counts(pdf: Path) -> tuple[int | None, int | None]:
    """(poppler's page count via pdfinfo, mupdf's via pymupdf); None where a reader fails.
    Single-page rendering is used only when both agree — otherwise the whole document is
    rendered, exactly as the serial engine did."""
    _, out, _ = run(["pdfinfo", str(pdf)], timeout=120)
    m = re.search(r"^Pages:\s+(\d+)\s*$", out, re.M)
    poppler = int(m.group(1)) if m else None
    mupdf: int | None = None
    with contextlib.suppress(Exception):
        import pymupdf

        doc = pymupdf.open(pdf)
        mupdf = int(doc.page_count)
        doc.close()
    return poppler, mupdf


def _argv_render_pp(dpi: int, page: int) -> list[str]:
    p = str(page)
    return ["pdftoppm", "-r", str(dpi), "-gray", "-png", "-f", p, "-l", p, "<IN>", "<OUT>/pp"]


def _argv_render_mu(page: int) -> list[str]:
    return ["mutool", "draw", "-q", "-r", MU_DPI, "-o", "<OUT>/mu-%d.png", "<IN>", str(page)]


def _argv_ocr(psm: str) -> list[str]:
    out = "<OUT>/psm6" if psm == "6" else "stdout"
    argv = [
        "tesseract",
        "<IN>",
        out,
        "--oem",
        "1",
        "--psm",
        psm,
        "-c",
        "preserve_interword_spaces=1",
    ]
    return [*argv, "txt", "tsv"] if psm == "6" else argv


def _fill(template: list[str], inp: Path, out: Path) -> list[str]:
    return [a.replace("<IN>", str(inp)).replace("<OUT>", str(out)) for a in template]


def ocr_psm6_files(png: Path, base: Path) -> tuple[Path, Path]:
    """PSM 6 recognised ONCE with the txt and tsv file renderers: `<base>.txt` / `<base>.tsv`
    are byte-equal to the two separate `stdout` invocations (proof 0 of the speed-up)."""
    run(_fill(_argv_ocr("6"), png, base.parent), timeout=600)
    return Path(f"{base}.txt"), Path(f"{base}.tsv")


def _ocr_producer(psm: str, png: Path) -> Callable[[Path], bool]:
    def produce(out: Path) -> bool:
        if psm == "6":
            txt, tsv = ocr_psm6_files(png, out / "psm6")
            return txt.is_file() and tsv.is_file()
        rc, stdout, _err = run_raw(_fill(_argv_ocr(psm), png, out), timeout=600)
        if rc != 0:
            return False
        (out / f"psm{psm}.txt").write_bytes(stdout)
        return True

    return produce


def _page_file(out: Path | None, prefix: str, page: int) -> Path | None:
    if out is None or not out.is_dir():
        return None
    pat = re.compile(rf"^{prefix}-0*{page}\.png$")
    found = sorted(p for p in out.iterdir() if pat.match(p.name))
    return found[0] if len(found) == 1 else None


def _produce_step(
    cache: OracleCache | None,
    step: str,
    descriptor: dict,
    local: Path,
    produce: Callable[[Path], bool],
) -> Path | None:
    """The dir holding the step's files: a cache entry, or the run-local page dir (a done
    marker per step makes an interrupted run resumable)."""
    if cache is not None:
        entry, _hit = cache.get_or_produce(step, descriptor, produce)
        return entry
    local.mkdir(parents=True, exist_ok=True)
    marker = local / f".{step}.done"
    if marker.exists():
        return local
    if produce(local):
        marker.touch()
        return local
    return None


def png_dims(png: Path) -> tuple[int, int] | None:
    """(width, height) from the IHDR chunk — the numbers cv2 reports, without a decode."""
    try:
        with png.open("rb") as f:
            head = f.read(24)
    except OSError:
        return None
    if len(head) < 24 or head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
        return None
    w, h = struct.unpack(">II", head[16:24])
    return (w, h) if w > 0 and h > 0 else None


def _maxrss() -> int:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss


def _relink(link: Path, target: Path) -> None:
    if link.is_symlink() or link.exists():
        link.unlink()
    link.symlink_to(target)


def _delete_work_files(workdir: Path) -> None:
    """Drop the per-cell corpora (qdf, mu-clean, revision slices, extracted images); the
    partial's path strings were recorded before this runs; finalize's cleanup stays idempotent."""
    for p in workdir.glob("*"):
        if not (p.name.startswith(("qdf", "mu-clean", "rev")) or p.name == "imgs"):
            continue
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        else:
            p.unlink(missing_ok=True)


def _page_task(spec: dict[str, Any]) -> dict[str, Any]:
    """Phase A: render + recognise one page of one distinct PDF (or, when the page counts
    disagree, the whole document) through the cache / the run-local page dir."""
    t0 = time.monotonic()
    pdf, sha, dpi = Path(spec["pdf"]), str(spec["sha"]), int(spec["dpi"])
    page: int | None = spec["page"]
    versions, traineddata = spec["versions"], spec["traineddata"]
    cache = OracleCache(Path(spec["cache_dir"])) if spec.get("cache_dir") else None
    local_root = Path(spec["pages_dir"]) / f"{sha}-{dpi}"
    want_mu = spec["mode"] == "scan"
    rendered: list[tuple[int, Path | None, Path | None]] = []
    if page is None:
        out = local_root / "all"
        out.mkdir(parents=True, exist_ok=True)
        if not list(out.glob("pp-*.png")):
            run(
                ["pdftoppm", "-r", str(dpi), "-gray", "-png", str(pdf), str(out / "pp")],
                timeout=900,
            )
        if want_mu and not list(out.glob("mu-*.png")):
            run(
                ["mutool", "draw", "-q", "-r", MU_DPI, "-o", str(out / "mu-%d.png"), str(pdf)],
                timeout=900,
            )
        for pp_all in sorted(out.glob("pp-*.png")):
            m = re.search(r"pp-0*(\d+)\.png$", pp_all.name)
            if m:
                n = int(m.group(1))
                rendered.append((n, pp_all, _page_file(out, "mu", n) if want_mu else None))
    else:
        local = local_root / f"p{page}"
        argv_pp = _argv_render_pp(dpi, page)
        d_pp = {
            "step": "render_pp",
            "input_sha256": sha,
            "page": page,
            "argv": argv_pp,
            "versions": {"pdftoppm": versions.get("pdftoppm", "?")},
        }

        def produce_pp(out: Path) -> bool:
            run(_fill(argv_pp, pdf, out), timeout=900)
            return _page_file(out, "pp", page) is not None

        pp = _page_file(_produce_step(cache, "render_pp", d_pp, local, produce_pp), "pp", page)
        mu: Path | None = None
        if want_mu:
            argv_mu = _argv_render_mu(page)
            d_mu = {
                "step": "render_mu",
                "input_sha256": sha,
                "page": page,
                "argv": argv_mu,
                "versions": {"mutool": versions.get("mutool", "?")},
            }

            def produce_mu(out: Path) -> bool:
                run(_fill(argv_mu, pdf, out), timeout=900)
                return _page_file(out, "mu", page) is not None

            mu = _page_file(_produce_step(cache, "render_mu", d_mu, local, produce_mu), "mu", page)
        rendered.append((page, pp, mu))

    pages: list[dict[str, Any]] = []
    for n, pp, mu in rendered:
        rec: dict[str, Any] = {
            "page": n,
            "pp": str(pp) if pp else None,
            "mu": str(mu) if mu else None,
            "psm6_txt": None,
            "psm6_tsv": None,
            "psm11": None,
            "psm12": None,
        }
        if pp is not None:
            png_sha = sh256(pp)
            local = local_root / f"p{n}"
            for psm in ("6", "11", "12"):
                d_ocr = {
                    "step": f"ocr_psm{psm}",
                    "input_sha256": png_sha,
                    "page": None,
                    "argv": _argv_ocr(psm),
                    "versions": {"tesseract": versions.get("tesseract", "?")},
                    "traineddata_sha256": traineddata,
                }
                entry = _produce_step(cache, f"ocr_psm{psm}", d_ocr, local, _ocr_producer(psm, pp))
                if entry is None:
                    continue
                if psm == "6":
                    rec["psm6_txt"] = str(entry / "psm6.txt")
                    rec["psm6_tsv"] = str(entry / "psm6.tsv")
                else:
                    rec[f"psm{psm}"] = str(entry / f"psm{psm}.txt")
        pages.append(rec)
    return {
        "sha": sha,
        "pages": pages,
        "hits": cache.hits if cache else {},
        "misses": cache.misses if cache else {},
        "seconds": time.monotonic() - t0,
        "maxrss": _maxrss(),
    }


def _cell_task(spec: dict[str, Any]) -> dict[str, Any]:
    """Phase B: one cell's classification-bearing legs over the phase-A page files; writes the
    cell's partial (the scan or calibrate shape, unchanged)."""
    t0 = time.monotonic()
    mode = spec["mode"]
    cell_dir = Path(spec["cell_dir"])
    cell: Cell | CalCell
    if mode == "scan":
        cell = Cell(cell_dir)
    else:
        cell = CalCell(cell_dir, Path(spec["pdf"]), str(spec["fixture"]), list(spec["terms"]))
    docs_root = Path(spec["docs_root"]) if spec.get("docs_root") else None
    dpi = int(spec["dpi"])
    versions = spec["versions"]
    vision_in = Path(spec["vision_in"])
    cell.dir.mkdir(parents=True, exist_ok=True)
    workdir = cell.dir / "oracle-work"
    workdir.mkdir(exist_ok=True)
    render = cell.dir / "render"
    render.mkdir(exist_ok=True)
    for stale in render.iterdir():
        if stale.is_symlink() or stale.is_file():
            stale.unlink()
    ocr_files: dict[int, dict[str, Path | None]] = {}
    for page_str, rec in sorted(spec["pages"].items(), key=lambda kv: int(kv[0])):
        page = int(page_str)
        for kind in ("pp", "mu"):
            if rec.get(kind):
                target = Path(rec[kind])
                _relink(render / target.name, target)
        ocr_files[page - 1] = {
            k: (Path(rec[k]) if rec.get(k) else None)
            for k in ("psm6_txt", "psm6_tsv", "psm11", "psm12")
        }
    for png in sorted(render.glob("pp-*.png")):
        _relink(vision_in / f"{cell.key}__{png.name}", png.resolve())

    if isinstance(cell, Cell):
        scope = compute_term_scope(cell, docs_root)
    else:
        scope = dict.fromkeys(cell.terms, "unique")
    o0 = o0_structure(cell, workdir)
    o1_hits, o1_diag = o1_text_layer(cell, scope)
    o2_hits = o2_bytes(cell, o0, scope, workdir)
    tess = o3_tesseract(cell, render, ocr_files)
    # px dims for OCR localization (tesseract ran on the pdftoppm renders)
    px_dims: dict[int, tuple[int, int]] = {}
    for png in render.glob("pp-*.png"):
        m = re.search(r"pp-0*(\d+)", png.name)
        dims = png_dims(png) if m else None
        if m and dims:
            px_dims[int(m.group(1)) - 1] = dims
    tess_hits = ocr_hits_for_engine(
        cell,
        {p: d["text"] for p, d in tess.items()},
        {p: d["words"] for p, d in tess.items()},
        px_dims,
    )
    o4 = o4_census(cell)
    o6_hits = o6_adversarial(cell, scope)
    partial: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "o0": o0,
        "o1_hits": o1_hits,
        "o1_diag": o1_diag,
        "o2_hits": o2_hits,
        "o3_tesseract_hits": tess_hits,
        "o4": o4,
        "o6_hits": o6_hits,
        "px_dims": {str(k): v for k, v in px_dims.items()},
        "versions": versions,
        "dpi": dpi,
    }
    if isinstance(cell, Cell):
        partial["cell"] = cell.key
        partial["term_scope"] = scope
        partial["o5"] = o5_pixels(cell, render, workdir)
        out_name = "oracle-partial.json"
    else:
        partial["fixture"] = cell.key
        out_name = "calibrate-partial.json"
    (cell.dir / out_name).write_text(json.dumps(partial, indent=1, sort_keys=True))
    if not spec.get("keep_work"):
        _delete_work_files(workdir)
    return {"key": cell.key, "seconds": time.monotonic() - t0, "maxrss": _maxrss()}


def _run_pool(
    fn: Callable[[dict[str, Any]], dict[str, Any]],
    specs: list[dict[str, Any]],
    jobs: int,
    on_result: Callable[[dict[str, Any]], None],
) -> None:
    if jobs <= 1 or len(specs) <= 1:
        for spec in specs:
            on_result(fn(spec))
        return
    ctx = multiprocessing.get_context("spawn")  # cv2 / pymupdf are not fork-safe
    workers = min(jobs, len(specs))
    with concurrent.futures.ProcessPoolExecutor(max_workers=workers, mp_context=ctx) as pool:
        futures = [pool.submit(fn, spec) for spec in specs]
        for fut in concurrent.futures.as_completed(futures):
            on_result(fut.result())


def _scan_cells(
    root: Path,
    cells: Sequence[Cell | CalCell],
    *,
    mode: str,
    docs_root: Path | None,
    dpi: int,
    jobs: int,
    cache_dir: Path | None,
    keep_work: bool = False,
    versions: dict[str, str] | None = None,
    jobs_cells: int | None = None,
) -> dict[str, Any]:
    """Phase A over the distinct pages, phase B over the cells; returns the run's stats (also
    written to <root>/<tag>-scan-stats.json and, with a cache, <cache>/last-run.json)."""
    os.environ["OMP_THREAD_LIMIT"] = "1"  # one Tesseract thread per worker (a fence)
    here = str(Path(__file__).resolve().parent)
    if here not in sys.path:
        sys.path.insert(0, here)  # spawned workers import this module by name
    jobs = max(1, int(jobs))
    if jobs_cells is None:
        jobs_cells = min(jobs, max(1, int(PHASE_B_BUDGET_GB // PHASE_B_WORKER_PEAK_GB)))
    jobs_cells = max(1, int(jobs_cells))
    tag = "oracle" if mode == "scan" else "calibrate"
    versions = dict(versions) if versions else tool_versions()
    traineddata = traineddata_sha256()
    vision_in = root / "vision-in"
    vision_in.mkdir(parents=True, exist_ok=True)
    pages_dir = root / "_pages"
    t_start = time.monotonic()

    by_sha: dict[str, dict[str, Any]] = {}
    cell_sha: dict[str, str] = {}
    for cell in cells:
        sha = sh256(cell.output)
        cell_sha[cell.key] = sha
        if sha in by_sha:
            continue
        poppler, mupdf = pdf_page_counts(cell.output)
        agree = poppler is not None and (mode == "calibrate" or poppler == mupdf)
        by_sha[sha] = {
            "pdf": cell.output,
            "bytes": cell.output.stat().st_size,
            "npages": poppler if agree else None,
            "poppler": poppler,
            "mupdf": mupdf,
        }
    whole = sorted(s for s, d in by_sha.items() if d["npages"] is None)

    def proxy(sha: str) -> float:  # bytes per page: the noise scans first
        d = by_sha[sha]
        return d["bytes"] / max(1, d["npages"] or d["poppler"] or 1)

    specs_a: list[dict[str, Any]] = []
    for sha in sorted(by_sha, key=lambda s: (-proxy(s), s)):
        d = by_sha[sha]
        base = {
            "pdf": str(d["pdf"]),
            "sha": sha,
            "dpi": dpi,
            "mode": mode,
            "versions": versions,
            "traineddata": traineddata,
            "cache_dir": str(cache_dir) if cache_dir else None,
            "pages_dir": str(pages_dir),
        }
        if d["npages"] is None:
            specs_a.append({**base, "page": None})
        else:
            specs_a.extend({**base, "page": p} for p in range(1, d["npages"] + 1))
    print(
        f"[{tag}] phase A: {len(specs_a)} page tasks over {len(by_sha)} distinct PDFs "
        f"({len(cells)} cells), jobs={jobs}, cache={cache_dir if cache_dir else 'off'}"
    )
    if whole:
        print(f"[{tag}] whole-document renders (page counts unreadable or disagreeing): {whole}")
    hits: dict[str, int] = {}
    misses: dict[str, int] = {}
    page_files: dict[str, dict[int, dict[str, Any]]] = {s: {} for s in by_sha}
    peak = {"a": 0, "b": 0}

    def on_page(res: dict[str, Any]) -> None:
        for rec in res["pages"]:
            page_files[res["sha"]][int(rec["page"])] = rec
        for k, v in res["hits"].items():
            hits[k] = hits.get(k, 0) + v
        for k, v in res["misses"].items():
            misses[k] = misses.get(k, 0) + v
        peak["a"] = max(peak["a"], int(res["maxrss"]))
        first = res["pages"][0]["page"] if res["pages"] else "?"
        print(f"[{tag}] page {res['sha'][:8]} p{first} {res['seconds']:.1f}s")

    _run_pool(_page_task, specs_a, jobs, on_page)
    t_a = time.monotonic() - t_start

    specs_b: list[dict[str, Any]] = []
    for cell in sorted(cells, key=lambda c: (-by_sha[cell_sha[c.key]]["bytes"], c.key)):
        sha = cell_sha[cell.key]
        spec: dict[str, Any] = {
            "mode": mode,
            "cell_dir": str(cell.dir),
            "docs_root": str(docs_root) if docs_root else None,
            "dpi": dpi,
            "versions": versions,
            "keep_work": keep_work,
            "vision_in": str(vision_in),
            "pages": {str(p): rec for p, rec in sorted(page_files[sha].items())},
        }
        if isinstance(cell, CalCell):
            spec.update({"pdf": str(cell.output), "fixture": cell.key, "terms": list(cell.terms)})
        specs_b.append(spec)
    print(f"[{tag}] phase B: {len(specs_b)} cells, jobs={jobs_cells}")

    def on_cell(res: dict[str, Any]) -> None:
        peak["b"] = max(peak["b"], int(res["maxrss"]))
        print(f"[{tag}] scanned {res['key']} ({res['seconds']:.1f}s)")

    _run_pool(_cell_task, specs_b, jobs_cells, on_cell)
    t_b = time.monotonic() - t_start - t_a
    stats: dict[str, Any] = {
        "mode": mode,
        "root": str(root),
        "cells": len(cells),
        "distinct_pdfs": len(by_sha),
        "distinct_pages": sum(len(v) for v in page_files.values()),
        "cell_pages": sum(len(page_files[cell_sha[c.key]]) for c in cells),
        "whole_render_pdfs": whole,
        "jobs": jobs,
        "jobs_cells": jobs_cells,
        "dpi": dpi,
        "cache_dir": str(cache_dir) if cache_dir else None,
        "hits": hits,
        "misses": misses,
        "phase_a_s": round(t_a, 1),
        "phase_b_s": round(t_b, 1),
        "phase_a_worker_maxrss": peak["a"],
        "phase_b_worker_maxrss": peak["b"],
        "versions": versions,
        "traineddata_sha256": traineddata,
        "finished": time.time(),
    }
    (root / f"{tag}-scan-stats.json").write_text(json.dumps(stats, indent=1, sort_keys=True))
    if cache_dir is not None:
        (cache_dir / "last-run.json").write_text(json.dumps(stats, indent=1, sort_keys=True))
    print(
        f"[{tag}] phase A {t_a:.0f} s, phase B {t_b:.0f} s; cache hits {sum(hits.values())} / "
        f"misses {sum(misses.values())}; worker peak RSS A {peak['a']:,} B {peak['b']:,}"
    )
    return stats


def _auto_prune(cache_dir: Path | None, max_gb: float, tag: str) -> None:
    if cache_dir is None:
        return
    cache = OracleCache(cache_dir)
    removed = cache.prune(int(max_gb * 2**30))
    st = cache.stats()
    print(
        f"[{tag}] cache {cache_dir}: {st['entries']} entries, {st['bytes'] / 2**30:.2f} GB "
        f"(cap {max_gb} GB; pruned {removed['entries']} entries / {removed['bytes'] / 2**30:.2f} GB)"
    )


def phase_cache_stats(cache_dir: Path) -> None:
    cache = OracleCache(cache_dir)
    report: dict[str, Any] = {"cache_dir": str(cache_dir), **cache.stats()}
    last = cache_dir / "last-run.json"
    if last.is_file():
        lr = json.loads(last.read_text())
        keys = (
            "root",
            "mode",
            "cells",
            "distinct_pdfs",
            "distinct_pages",
            "jobs",
            "hits",
            "misses",
            "phase_a_s",
            "phase_b_s",
            "finished",
        )
        report["last_run"] = {k: lr.get(k) for k in keys}
    print(json.dumps(report, indent=1, sort_keys=True))


def phase_cache_prune(cache_dir: Path, max_gb: float) -> None:
    cache = OracleCache(cache_dir)
    removed = cache.prune(int(max_gb * 2**30))
    print(json.dumps({"cache_dir": str(cache_dir), "removed": removed, **cache.stats()}, indent=1))


# ---------------------------------------------------------------- phases


def phase_scan(
    cells_dir: Path,
    docs_root: Path | None,
    dpi: int,
    *,
    jobs: int,
    cache_dir: Path | None,
    keep_work: bool,
    cache_max_gb: float,
    jobs_cells: int | None = None,
) -> None:
    cells = discover_cells(cells_dir)
    if not cells:
        sys.exit(f"no cells under {cells_dir}")
    print(f"[oracle] scan: {len(cells)} cells, dpi={dpi}")
    _scan_cells(
        cells_dir,
        cells,
        mode="scan",
        docs_root=docs_root,
        dpi=dpi,
        jobs=jobs,
        cache_dir=cache_dir,
        keep_work=keep_work,
        jobs_cells=jobs_cells,
    )
    _auto_prune(cache_dir, cache_max_gb, "oracle")
    vision_in = cells_dir / "vision-in"
    print(
        "[oracle] scan done. Run the Vision leg from the iOS worktree "
        "(HOST swift test), then finalize:\n"
        f"  cd <ios>/Packages/RedactionEngine && RESECTA_VISION_IN={vision_in} "
        f"RESECTA_VISION_OUT={cells_dir / 'vision-out'} "
        "swift test --filter VisionOracleEmitterTests\n"
        f"  python tools/verify_oracle.py finalize --cells {cells_dir}"
    )


TERM_PRESENCE_LAYERS = {
    "Text Extraction",
    "OCR Check",
    "Binary String Search",
    "Operator Re-Extraction",
}
TERM_SURFACES = ("text_layer", "decompressed_bytes", "ocr")


def classify(cell: Cell, leak_hits: list[dict], review: list[dict]) -> tuple[str, str | None]:
    """Attribution-aware grading. A PASS is graded on leak-class hits alone
    (ambient term presence is legitimate content, never a false-pass driver).
    An ATTENTION/FAIL driven by a term-presence layer (L1/L2/L3/L10 — their
    claim is document-wide readability of redaction-matching text) is
    corroborated by term presence in any oracle text surface, ambient
    included. A FAIL/ATTENTION from the geometry/count layers (L6/L7/L9,
    structure, page count) needs leak-class evidence — ambient text elsewhere
    says nothing about an in-region overlap or a count deficit."""
    overall = cell.report["overall"]["case"]
    leaked = bool(leak_hits)
    attributed = None
    if overall in ("fail", "attention", "warn"):
        for layer in cell.report.get("layers", []):
            if layer["status"]["case"] == overall:
                attributed = layer["name"]
                break
    term_presence = leaked or any(
        r.get("surface") in TERM_SURFACES and r.get("term") for r in review
    )
    corroborated = term_presence if attributed in TERM_PRESENCE_LAYERS else leaked
    if overall in ("pass", "info", "warn"):
        cls = "false_pass" if leaked else "true_pass"
    elif overall == "attention":
        cls = "attention_true" if corroborated else "attention_false"
    elif overall == "fail":
        cls = "true_fail" if corroborated else "false_fail"
    else:  # skipped — no app verdict to grade
        cls = "skipped"
    return cls, attributed


def phase_finalize(cells_dir: Path, keep_renders: bool) -> None:
    cells = discover_cells(cells_dir)
    vision_out = cells_dir / "vision-out"
    summary_cells = []
    for cell in cells:
        partial_path = cell.dir / "oracle-partial.json"
        if not partial_path.exists():
            print(f"[oracle] MISSING scan for {cell.key}; skipped")
            continue
        partial = json.loads(partial_path.read_text())
        scope = partial["term_scope"]

        # Vision leg: merge per-page reports for this cell.
        vision_pages: dict[int, dict] = {}
        vision_present = False
        if vision_out.exists():
            for vp in vision_out.glob(f"{cell.key}__pp-*.json"):
                vision_present = True
                m = re.search(r"pp-0*(\d+)\.json$", vp.name)
                if not m:
                    continue
                pageno = int(m.group(1)) - 1
                vision_pages[pageno] = json.loads(vp.read_text())
        px_dims = {int(k): tuple(v) for k, v in partial.get("px_dims", {}).items()}
        vision_texts: dict[int, str] = {}
        vision_words: dict[int, list] = {}
        for pageno, rep in vision_pages.items():
            vision_texts[pageno] = "\n".join(ln["text"] for ln in rep.get("lines", []))
            words = []
            dims = px_dims.get(pageno)
            if dims:
                w_px, h_px = dims
                for ln in rep.get("lines", []):
                    bx, by, bw, bh = ln["bbox"]  # normalized bottom-left
                    box = (bx * w_px, (1 - by - bh) * h_px, (bx + bw) * w_px, (1 - by) * h_px)
                    words.append((ln["text"], box))
            vision_words[pageno] = words
        vision_hits = ocr_hits_for_engine(cell, vision_texts, vision_words, px_dims)

        # OCR quorum + review flags.
        tess_hits = partial["o3_tesseract_hits"]
        ocr_leaks: list[dict] = []
        review: list[dict] = []
        for term in sorted(set(tess_hits) | set(vision_hits)):  # deterministic record order
            t_pages = {h["page"]: h for h in tess_hits.get(term, [])}
            v_pages = {h["page"]: h for h in vision_hits.get(term, [])}
            quorum_pages = sorted(set(t_pages) & set(v_pages))
            single_pages = sorted(set(t_pages) ^ set(v_pages))
            for pageno in quorum_pages:
                in_region = t_pages[pageno]["in_region"] or v_pages[pageno]["in_region"]
                is_leak = in_region  # out-of-region OCR falls to review (docstring)
                entry = {
                    "surface": "ocr",
                    "term": term,
                    "page": pageno,
                    "scope": scope.get(term, "unique"),
                    "engines": ["tesseract", "vision"],
                    "in_region": in_region,
                    "leak": is_leak,
                    "detail": "OCR quorum recovery"
                    + (" inside a burned region" if in_region else " outside every burned region"),
                }
                (ocr_leaks if is_leak else review).append(entry)
            for pageno in single_pages:
                src = "tesseract" if pageno in t_pages else "vision"
                review.append(
                    {
                        "surface": "ocr",
                        "term": term,
                        "page": pageno,
                        "scope": scope.get(term, "unique"),
                        "engines": [src],
                        "leak": False,
                        "detail": f"single-engine OCR sighting ({src})"
                        + ("" if vision_present else "; Vision leg absent — quorum unreachable"),
                    }
                )

        # Structure hits (content-bearing keys only).
        o0 = partial["o0"]
        structure_hits: list[dict] = []
        content_keys = set(o0["structure_keys_json"])
        for key in sorted(content_keys):
            if key == "/AcroForm" and not o0["acroform_has_v"]:
                review.append(
                    {
                        "surface": "structure",
                        "key": key,
                        "leak": False,
                        "detail": "AcroForm present without field values",
                    }
                )
                continue
            structure_hits.append(
                {
                    "surface": "structure",
                    "key": key,
                    "leak": True,
                    "detail": f"content-bearing key {key} survives in the output",
                }
            )
        byte_only = sorted(set(o0["structure_keys_bytes"]) - content_keys)
        for key in byte_only:
            review.append(
                {
                    "surface": "structure",
                    "key": key,
                    "leak": False,
                    "detail": "key token in bytes but not in the qpdf object tree",
                }
            )
        if o0["revisions"] > 1:
            structure_hits.append(
                {
                    "surface": "structure",
                    "key": "revisions",
                    "leak": True,
                    "detail": f"output carries {o0['revisions']} %%EOF revisions",
                }
            )
        if o0["info_extra_keys"]:
            vals = " ".join(str(v) for v in o0["info_extra_keys"].values())
            term_hit = any(fold(t) in fold(vals) for t in cell.terms)
            structure_hits.append(
                {
                    "surface": "structure",
                    "key": "/Info",
                    "leak": True,
                    "detail": "non-benign Info keys "
                    f"{sorted(o0['info_extra_keys'])}"
                    + (" INCLUDING a sensitive term" if term_hit else ""),
                }
            )
        if o0["annots_pages"]:
            structure_hits.append(
                {
                    "surface": "structure",
                    "key": "/Annots",
                    "leak": True,
                    "detail": f"annotations survive on pages {o0['annots_pages']}",
                }
            )

        pixel_hits = [
            {
                "surface": "pixel",
                "leak": True,
                "detail": f"fill deviation {f['max_dev']} > {FILL_MAX_DEV} "
                f"({f['renderer']}) page {f['page']} region {f['region_index']}",
                **f,
            }
            for f in partial["o5"]["fill_fail"]
        ]

        text_leaks = [h for h in partial["o1_hits"] if h["leak"]]
        text_review = [h for h in partial["o1_hits"] if not h["leak"]]
        byte_leaks = [h for h in partial["o2_hits"] + partial["o6_hits"] if h["leak"]]
        byte_review = [h for h in partial["o2_hits"] + partial["o6_hits"] if not h["leak"]]
        image_leaks = [h for h in byte_leaks if h["surface"] == "image"]
        byte_leaks = [h for h in byte_leaks if h["surface"] != "image"]

        leak_hits = text_leaks + byte_leaks + image_leaks + ocr_leaks + structure_hits + pixel_hits
        review += text_review + byte_review
        cls, attributed = classify(cell, leak_hits, review)

        ious = [r["iou"] for r in partial["o5"]["iou"]]
        oracle = {
            "schema_version": SCHEMA_VERSION,
            "cell": cell.key,
            "doc_id": cell.doc_id,
            "mode": cell.mode,
            "region_set": cell.region_set,
            "verdict_overall": cell.report["overall"]["case"],
            "classification": cls,
            "attributed_layer": attributed,
            "oracle_hits": leak_hits,
            "review_flags": review,
            "term_scope": scope,
            "o0": {k: v for k, v in o0.items() if not k.endswith("_path")},
            "o4": partial["o4"],
            "o5_summary": {
                "regions": partial["o5"]["regions"],
                "fill_fail": len(partial["o5"]["fill_fail"]),
                "max_dev_pp": partial["o5"]["max_dev_pp"],
                "max_dev_mu": partial["o5"]["max_dev_mu"],
                "iou_median": round(sorted(ious)[len(ious) // 2], 4) if ious else None,
                "iou_min": round(min(ious), 4) if ious else None,
                "iou_all": ious,
            },
            "vision_leg_present": vision_present,
            "versions": partial["versions"],
        }
        (cell.dir / "oracle.json").write_text(json.dumps(oracle, indent=1, sort_keys=True))
        summary_cells.append(oracle)
        if not keep_renders:
            shutil.rmtree(cell.dir / "render", ignore_errors=True)
            work = cell.dir / "oracle-work"
            for p in work.glob("*"):
                if p.name.startswith(("qdf", "mu-clean", "rev")) or p.is_dir():
                    shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink()
        print(
            f"[oracle] {cell.key}: {cls}" + (f" (attributed: {attributed})" if attributed else "")
        )
    if not keep_renders:
        shutil.rmtree(cells_dir / "_pages", ignore_errors=True)  # the no-cache page files

    # ------- summary (feeds M12-07..10) -------
    by_class: dict[str, int] = {}
    false_fail_by_layer: dict[str, int] = {}
    false_pass_cells: list[str] = []
    surface_recovery: dict[str, set] = {
        s: set() for s in ("text_layer", "decompressed_bytes", "ocr", "image", "structure")
    }
    burned_items = 0
    ious_all: list[float] = []
    fill_fail_total = 0
    for cell, oracle in zip(cells, summary_cells, strict=False):
        by_class[oracle["classification"]] = by_class.get(oracle["classification"], 0) + 1
        if oracle["classification"] == "false_fail":
            false_fail_by_layer[oracle["attributed_layer"] or "?"] = (
                false_fail_by_layer.get(oracle["attributed_layer"] or "?", 0) + 1
            )
        if oracle["classification"] == "false_pass":
            false_pass_cells.append(oracle["cell"])
        valued = {r["gt_id"] for r in cell.burned if r.get("value") and r.get("gt_id")}
        burned_items += len(valued)
        term_to_ids: dict[str, set] = {}
        for r in cell.burned:
            if r.get("value") and r.get("gt_id"):
                term_to_ids.setdefault(r["value"], set()).add(r["gt_id"])
        for hit in oracle["oracle_hits"]:
            surface = hit.get("surface")
            term = hit.get("term")
            if surface in surface_recovery and term and term in term_to_ids:
                for gt_id in term_to_ids[term]:
                    surface_recovery[surface].add((oracle["cell"], gt_id))
        ious_all += oracle["o5_summary"]["iou_all"]
        fill_fail_total += oracle["o5_summary"]["fill_fail"]

    ious_sorted = sorted(ious_all)
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_by": "verify_oracle.py finalize",
        "cells": len(summary_cells),
        "classification_counts": by_class,
        "false_pass_cells": false_pass_cells,
        "false_fail_by_attributed_layer": false_fail_by_layer,
        "residual_leak_by_surface": {
            s: {
                "recovered_items": len(v),
                "burned_items_total": burned_items,
                "rate": round(len(v) / burned_items, 6) if burned_items else None,
            }
            for s, v in surface_recovery.items()
        },
        "placement_iou": {
            "n": len(ious_sorted),
            "median": round(ious_sorted[len(ious_sorted) // 2], 4) if ious_sorted else None,
            "p10": round(ious_sorted[len(ious_sorted) // 10], 4) if ious_sorted else None,
            "min": round(min(ious_sorted), 4) if ious_sorted else None,
        },
        "fill_fail_regions": fill_fail_total,
        "review_flag_cells": {
            o["cell"]: len(o["review_flags"]) for o in summary_cells if o["review_flags"]
        },
        "vision_leg_present_everywhere": all(o["vision_leg_present"] for o in summary_cells)
        if summary_cells
        else False,
    }
    (cells_dir / "oracle-summary.json").write_text(json.dumps(summary, indent=1, sort_keys=True))
    print(
        f"[oracle] finalize done: {len(summary_cells)} cells -> {cells_dir / 'oracle-summary.json'}"
    )
    print(
        json.dumps(
            {
                k: summary[k]
                for k in (
                    "classification_counts",
                    "false_fail_by_attributed_layer",
                    "fill_fail_regions",
                    "placement_iou",
                )
            },
            indent=1,
        )
    )


# ---------------------------------------------------------------- calibration (T2.2, M12-12)

SURFACE_STRUCTURE_SIGNALS = {
    "ocg_off": "/OCProperties",
    "xmp_metadata": "/Metadata",
    "acroform_v": "/AcroForm",
    "outlines": "/Outlines",
    "thumb": "/Thumb",
    "embedded_file": "/EmbeddedFiles",
    "javascript": "/JavaScript",
    "object_stream": "info_extra",
    "info_dict": "info_extra",
    "prior_revision": "revisions",
    "annotation_ap": "annots",
    "annotation_contents": "annots",
}


class CalCell:
    """Duck-typed Cell for a planted fixture: no burned regions, no report."""

    def __init__(self, cell_dir: Path, pdf: Path, fixture: str, terms: list[str]):
        self.dir = cell_dir
        self.output = pdf
        self.doc_id = fixture
        self.mode = "calibration"
        self.region_set = "planted"
        self.key = fixture
        self.terms = terms
        self.expected_visible: set[str] = set()
        self.burned: list[Any] = []

    def burned_by_page(self) -> dict:
        return {}


def load_planted(planted_dir: Path) -> dict:
    return json.loads((planted_dir / "planted-leaks.json").read_text())


def cal_cells(planted_dir: Path, out: Path) -> list[tuple[CalCell, dict | None]]:
    """(cell, manifest_row) per planted fixture; clean rows probe ALL plant terms."""
    manifest = load_planted(planted_dir)
    repo = planted_dir.parent
    all_terms = sorted({p["term"] for r in manifest["rows"] for p in r["plants"]})
    cells: list[tuple[CalCell, dict | None]] = []
    for row in manifest["rows"]:
        pdf = repo / row["path"]
        terms = [p["term"] for p in row["plants"]]
        cells.append((CalCell(out / row["fixture"], pdf, row["fixture"], terms), row))
    for row in manifest["clean"]:
        pdf = repo / row["path"]
        cells.append((CalCell(out / row["fixture"], pdf, row["fixture"], all_terms), None))
    return cells


def phase_calibrate(
    planted_dir: Path,
    out: Path,
    dpi: int,
    *,
    jobs: int,
    cache_dir: Path | None,
    keep_work: bool,
    cache_max_gb: float,
    jobs_cells: int | None = None,
) -> None:
    out.mkdir(parents=True, exist_ok=True)
    cells = cal_cells(planted_dir, out)
    print(f"[calibrate] {len(cells)} fixtures, dpi={dpi}")
    for cell, _row in cells:
        cell.dir.mkdir(parents=True, exist_ok=True)
    _scan_cells(
        out,
        [cell for cell, _row in cells],
        mode="calibrate",
        docs_root=None,
        dpi=dpi,
        jobs=jobs,
        cache_dir=cache_dir,
        keep_work=keep_work,
        jobs_cells=jobs_cells,
    )
    _auto_prune(cache_dir, cache_max_gb, "calibrate")
    vision_in = out / "vision-in"
    print(
        "[calibrate] scan done. Run the Vision leg, then calibrate-finalize:\n"
        f"  RESECTA_VISION_IN={vision_in} RESECTA_VISION_OUT={out / 'vision-out'} "
        "swift test --filter VisionOracleEmitterTests\n"
        f"  python tools/verify_oracle.py calibrate-finalize --planted {planted_dir} --out {out}"
    )


def _structure_signal_fired(surface: str, o0: dict) -> bool:
    sig = SURFACE_STRUCTURE_SIGNALS.get(surface)
    if sig is None:
        return False
    if sig == "info_extra":
        return bool(o0["info_extra_keys"])
    if sig == "revisions":
        return o0["revisions"] > 1
    if sig == "annots":
        return bool(o0["annots_pages"])
    if sig == "/AcroForm":
        return (
            "/AcroForm" in set(o0["structure_keys_json"]) | set(o0["structure_keys_bytes"])
        ) and o0["acroform_has_v"]
    return sig in set(o0["structure_keys_json"]) | set(o0["structure_keys_bytes"])


def phase_calibrate_finalize(planted_dir: Path, out: Path) -> None:
    cells = cal_cells(planted_dir, out)
    vision_out = out / "vision-out"
    plant_results: list[dict] = []
    clean_results: list[dict] = []
    for cell, row in cells:
        partial_path = cell.dir / "calibrate-partial.json"
        if not partial_path.exists():
            print(f"[calibrate] MISSING scan for {cell.key}; skipped")
            continue
        partial = json.loads(partial_path.read_text())
        px_dims = {int(k): tuple(v) for k, v in partial.get("px_dims", {}).items()}
        vision_texts: dict[int, str] = {}
        vision_words: dict[int, list] = {}
        vision_present = False
        if vision_out.exists():
            for vp in vision_out.glob(f"{cell.key}__pp-*.json"):
                vision_present = True
                m = re.search(r"pp-0*(\d+)\.json$", vp.name)
                if not m:
                    continue
                pageno = int(m.group(1)) - 1
                rep = json.loads(vp.read_text())
                vision_texts[pageno] = "\n".join(ln["text"] for ln in rep.get("lines", []))
                words = []
                dims = px_dims.get(pageno)
                if dims:
                    w_px, h_px = dims
                    for ln in rep.get("lines", []):
                        bx, by, bw, bh = ln["bbox"]
                        words.append(
                            (
                                ln["text"],
                                (
                                    bx * w_px,
                                    (1 - by - bh) * h_px,
                                    (bx + bw) * w_px,
                                    (1 - by) * h_px,
                                ),
                            )
                        )
                vision_words[pageno] = words
        vision_hits = ocr_hits_for_engine(cell, vision_texts, vision_words, px_dims)
        tess_hits = partial["o3_tesseract_hits"]

        def term_legs(
            term: str,
            partial=partial,
            tess_hits=tess_hits,
            vision_hits=vision_hits,
            vision_present=vision_present,
        ) -> tuple[list[str], bool]:
            legs: list[str] = []
            for h in partial["o1_hits"]:
                if h["term"] == term and (h.get("extractors") or h.get("localized")):
                    legs.append("o1")
                    break
            for h in partial["o2_hits"]:
                if h.get("term") == term:
                    legs.append("o2-image" if h["surface"] == "image" else "o2")
            if term in tess_hits:
                legs.append("o3-tesseract")
            if term in vision_hits:
                legs.append("o3-vision")
            if term in tess_hits and term in vision_hits:
                legs.append("o3-quorum")
            for h in partial["o6_hits"]:
                if h.get("term") == term:
                    legs.append("o6")
            return sorted(set(legs)), vision_present

        if row is not None:
            for plant in row["plants"]:
                term = plant["term"]
                surface = plant["surface"]
                legs, vision_leg_present = term_legs(term)
                structure_fired = _structure_signal_fired(surface, partial["o0"])
                term_recovered = bool(legs)
                structure_only_expected = plant["expected_legs"] == ["structure"]
                found = term_recovered or (structure_only_expected and structure_fired)
                expected_found = any(
                    (e == "structure" and structure_fired)
                    or (e == "o1" and "o1" in legs)
                    or (e == "o2" and any(leg.startswith("o2") for leg in legs))
                    or (e == "o3" and any(leg.startswith("o3") for leg in legs))
                    or (e == "o6" and "o6" in legs)
                    for e in plant["expected_legs"]
                )
                plant_results.append(
                    {
                        "fixture": cell.key,
                        "surface": surface,
                        "hidden_class": plant.get("hidden_class"),
                        "term": term,
                        "expected_legs": plant["expected_legs"],
                        "legs_found": legs,
                        "structure_signal_fired": structure_fired,
                        "term_recovered": term_recovered,
                        "found": found,
                        "found_by_expected_leg": expected_found,
                        "vision_leg_present": vision_leg_present,
                    }
                )
        else:
            spurious_terms = []
            for t in cell.terms:
                legs, _vp = term_legs(t)
                if legs:
                    spurious_terms.append({"term": t, "legs": legs})
            o0 = partial["o0"]
            content_keys = sorted(set(o0["structure_keys_json"]))
            clean_results.append(
                {
                    "fixture": cell.key,
                    "spurious_term_hits": spurious_terms,
                    "content_structure_keys": content_keys,
                    "info_extra_keys": sorted(o0["info_extra_keys"]),
                    "revisions": o0["revisions"],
                    "false_fail": bool(spurious_terms)
                    or bool(content_keys)
                    or o0["revisions"] > 1
                    or bool(o0["info_extra_keys"]),
                }
            )

    by_surface: dict[str, dict] = {}
    for r in plant_results:
        d = by_surface.setdefault(
            r["surface"], {"n": 0, "found": 0, "expected": 0, "term_recovered": 0}
        )
        d["n"] += 1
        d["found"] += int(r["found"])
        d["expected"] += int(r["found_by_expected_leg"])
        d["term_recovered"] += int(r["term_recovered"])
    leg_matrix: dict[str, dict[str, int]] = {}
    for r in plant_results:
        row_m = leg_matrix.setdefault(r["surface"], {})
        for leg in r["legs_found"]:
            row_m[leg] = row_m.get(leg, 0) + 1
        if r["structure_signal_fired"]:
            row_m["structure"] = row_m.get("structure", 0) + 1
    misses = [r for r in plant_results if not r["found"]]
    manifest = load_planted(planted_dir)
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_by": "verify_oracle.py calibrate-finalize",
        "plants": len(plant_results),
        "plants_found_any": sum(r["found"] for r in plant_results),
        "recall_by_surface": {
            s: {
                "n": d["n"],
                "found_any": d["found"],
                "found_by_expected_leg": d["expected"],
                "term_recovered": d["term_recovered"],
                "recall": round(d["found"] / d["n"], 4) if d["n"] else None,
            }
            for s, d in sorted(by_surface.items())
        },
        "leg_matrix": {s: dict(sorted(v.items())) for s, v in sorted(leg_matrix.items())},
        "misses": misses,
        "clean_docs": len(clean_results),
        "clean_false_fails": sum(r["false_fail"] for r in clean_results),
        "clean_detail": clean_results,
        "skipped_stretch_rows": manifest.get("skipped", []),
        "vision_leg_present_everywhere": all(r["vision_leg_present"] for r in plant_results)
        if plant_results
        else False,
    }
    (out / "calibration-summary.json").write_text(
        json.dumps({"plant_results": plant_results, **summary}, indent=1, sort_keys=False)
    )
    print(
        f"[calibrate] {summary['plants_found_any']}/{summary['plants']} plants found; "
        f"clean false-FAILs {summary['clean_false_fails']}/{summary['clean_docs']}"
    )
    print(json.dumps({k: summary[k] for k in ("recall_by_surface", "clean_false_fails")}, indent=1))


# PB-86 (M12-11) phase, below.


def phase_pb86(cells_dir: Path) -> None:
    plants_path = cells_dir / "pb86-plants.json"
    if not plants_path.exists():
        sys.exit(f"no pb86-plants.json under {cells_dir}")
    plants = json.loads(plants_path.read_text())["plants"]
    results: list[dict] = []
    qdf_cache: dict[str, bytes] = {}
    for row in plants:
        cell_dir = cells_dir / row["cell"]
        output = cell_dir / "output.pdf"
        if not output.exists():
            results.append({**row, "status": "cell-missing"})
            continue
        term = row["term"]
        ft = fold(term)
        fn = fold_nospace(term)
        text_legs: list[str] = []
        for name, cmd in (
            (
                "pdftotext-layout",
                ["pdftotext", "-layout", "-enc", "UTF-8", "-nopgbrk", str(output), "-"],
            ),
            ("pdftotext-raw", ["pdftotext", "-raw", "-enc", "UTF-8", "-nopgbrk", str(output), "-"]),
        ):
            if ft in fold(run_bytes(cmd).decode("utf-8", "replace")):
                text_legs.append(name)
        stext = "".join(c for _w, _h, chars in stext_pages(output) for c, _b in chars)
        if fn and fn in fold_nospace(stext):
            text_legs.append("mutool-stext")
        with contextlib.suppress(Exception):
            import pymupdf

            doc = pymupdf.open(output)
            rd = "".join(pg.get_text() for pg in doc.pages())
            doc.close()
            if ft in fold(rd):
                text_legs.append("pymupdf")
        key = row["cell"]
        if key not in qdf_cache:
            qdf_path = cell_dir / "oracle-work"
            qdf_path.mkdir(exist_ok=True)
            qdf_file = qdf_path / "pb86-qdf.pdf"
            run(["qpdf", "--qdf", "--object-streams=disable", str(output), str(qdf_file)])
            qdf_cache[key] = qdf_file.read_bytes() if qdf_file.exists() else b""
        qdf = qdf_cache[key]
        byte_hit = (
            term.encode() in qdf
            or hex_string(term) in qdf
            or hex_string(term).upper() in qdf
            or octal_escape(term) in qdf
            or fn in fold_nospace(tj_reassembled(qdf))
        )
        cell_meta = {}
        cj = cell_dir / "cell.json"
        if cj.exists():
            c = json.loads(cj.read_text())
            cell_meta = {
                "per_page_modes": c.get("per_page_modes"),
                "verdict": (c.get("overall_per_sweep") or [None])[0],
            }
        results.append(
            {
                **row,
                "status": "measured",
                "text_layer_legs": text_legs,
                "re_exposed_text_layer": bool(text_legs),
                "bytes_hit": bool(byte_hit),
                **cell_meta,
            }
        )

    def rate(rows: list[dict]) -> dict:
        n = len(rows)
        re_exp = sum(r["re_exposed_text_layer"] for r in rows)
        return {"n": n, "re_exposed": re_exp, "rate": round(re_exp / n, 4) if n else None}

    classes = sorted({r["hidden_class"] for r in results})
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_by": "verify_oracle.py pb86",
        "measured": sum(r["status"] == "measured" for r in results),
        "missing_cells": [r["cell"] for r in results if r["status"] == "cell-missing"],
        "re_exposure_by_class": {
            cls: {
                "uncovered": rate(
                    [
                        r
                        for r in results
                        if r["hidden_class"] == cls
                        and not r["covered"]
                        and r["status"] == "measured"
                    ]
                ),
                "covered_residual": rate(
                    [
                        r
                        for r in results
                        if r["hidden_class"] == cls and r["covered"] and r["status"] == "measured"
                    ]
                ),
            }
            for cls in classes
        },
        "rows": results,
    }
    (cells_dir / "pb86-summary.json").write_text(json.dumps(summary, indent=1, sort_keys=False))
    print(json.dumps(summary["re_exposure_by_class"], indent=1))
    print(f"[pb86] {summary['measured']} plant-cells -> {cells_dir / 'pb86-summary.json'}")


def _env_cache_dir() -> Path | None:
    env = os.environ.get("RESECTA_ORACLE_CACHE")
    return Path(env) if env else None


def _add_engine_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--jobs", type=int, default=os.cpu_count() or 1, help="workers (default: cores)")
    p.add_argument(
        "--jobs-cells", type=int, default=None, help="cell-phase workers (default: capped)"
    )
    p.add_argument("--cache-dir", type=Path, default=_env_cache_dir())
    p.add_argument("--no-cache", action="store_true")
    p.add_argument("--cache-max-gb", type=float, default=DEFAULT_CACHE_MAX_GB)
    p.add_argument("--keep-work", action="store_true")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="phase", required=True)
    scan = sub.add_parser("scan", help="renders + O0-O2/O4-O6 + Tesseract; stages the Vision leg")
    scan.add_argument("--cells", required=True, type=Path)
    scan.add_argument("--docs-root", type=Path, default=None)
    scan.add_argument("--dpi", type=int, default=400)
    _add_engine_args(scan)
    fin = sub.add_parser("finalize", help="merge the Vision leg, quorum, classification, summary")
    fin.add_argument("--cells", required=True, type=Path)
    fin.add_argument("--keep-renders", action="store_true")
    cal = sub.add_parser("calibrate", help="T2.2: O-legs directly over the planted corpus")
    cal.add_argument("--planted", required=True, type=Path)
    cal.add_argument("--out", required=True, type=Path)
    cal.add_argument("--dpi", type=int, default=400)
    _add_engine_args(cal)
    calf = sub.add_parser("calibrate-finalize", help="merge Vision + per-plant recall summary")
    calf.add_argument("--planted", required=True, type=Path)
    calf.add_argument("--out", required=True, type=Path)
    pb = sub.add_parser("pb86", help="M12-11: hidden-text re-exposure over section-E cells")
    pb.add_argument("--cells", required=True, type=Path)
    cst = sub.add_parser("cache-stats", help="entries / bytes of the tool-output cache + last run")
    cst.add_argument("--cache-dir", type=Path, default=_env_cache_dir())
    cpr = sub.add_parser("cache-prune", help="LRU-prune the tool-output cache to --max-gb")
    cpr.add_argument("--cache-dir", type=Path, default=_env_cache_dir())
    cpr.add_argument("--max-gb", type=float, default=DEFAULT_CACHE_MAX_GB)
    args = ap.parse_args()
    if args.phase in ("scan", "calibrate"):
        cache_dir = None if args.no_cache else args.cache_dir
        if args.phase == "scan":
            phase_scan(
                args.cells,
                args.docs_root,
                args.dpi,
                jobs=args.jobs,
                cache_dir=cache_dir,
                keep_work=args.keep_work,
                cache_max_gb=args.cache_max_gb,
                jobs_cells=args.jobs_cells,
            )
        else:
            phase_calibrate(
                args.planted,
                args.out,
                args.dpi,
                jobs=args.jobs,
                cache_dir=cache_dir,
                keep_work=args.keep_work,
                cache_max_gb=args.cache_max_gb,
                jobs_cells=args.jobs_cells,
            )
    elif args.phase == "finalize":
        phase_finalize(args.cells, args.keep_renders)
    elif args.phase == "calibrate-finalize":
        phase_calibrate_finalize(args.planted, args.out)
    elif args.phase in ("cache-stats", "cache-prune"):
        if args.cache_dir is None:
            sys.exit("--cache-dir (or RESECTA_ORACLE_CACHE) is required")
        if args.phase == "cache-stats":
            phase_cache_stats(args.cache_dir)
        else:
            phase_cache_prune(args.cache_dir, args.max_gb)
    else:
        phase_pb86(args.cells)


if __name__ == "__main__":
    main()
