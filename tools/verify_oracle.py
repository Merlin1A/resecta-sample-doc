"""verify_oracle.py — H2.3 oracle runner v0 over H2.2 verification-corpus cells.

Layered, ANY-HIT = FAIL, recall-first (1.2 instrumentation plan §5). Consumes the cells an
engine-side `VerificationCorpusRunnerTests` run wrote (`<cells>/<doc>/<mode>/<set>/` with
output.pdf + regions.json + report.json) and classifies every cell's verdict against an
independent recovery stack:

  O0  qpdf/mutool normalize + structure census; multi-revision scan on the ORIGINAL output
      bytes (QDF drops prior revisions), per-revision decompression where parseable.
  O1  text extractors ×2 (pdftotext -layout AND -raw; mutool stext glyph boxes) + PyMuPDF
      rawdict char flags — region-localized where geometry exists.
  O2  decompressed-byte search (QDF + mutool clean + raw revision slices): literal, hex-string,
      octal-escaped, UTF-16BE(±BOM), TJ/Tj-reassembly (kern-stripped), case variants; plus
      pdfimages -all → exiftool EXIF census.
  O3  OCR ×2: pdftoppm 400 DPI (renderer independent of the verifier) → Tesseract oem 1 with
      PSM 6 ∪ 11 ∪ 12, and Vision .accurate via the engine test target's
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
  python tools/verify_oracle.py scan --cells <run>/cells --docs-root <sd-root>
  # then the printed engine-test Vision command, then:
  python tools/verify_oracle.py finalize --cells <run>/cells [--keep-renders]

Runs with the sd worktree venv (pymupdf + numpy + cv2 present); external tools per the D12-20
inventory (qpdf, mutool, poppler, tesseract, exiftool). Every run records tool versions.
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path
from xml.etree import ElementTree

SCHEMA_VERSION = 1
FILL_MAX_DEV = 13          # ≈5% of 255 — JPEG-artifact allowance inside a solid fill
NEAR_BLACK = 60            # component threshold for the placement mask
ERODE_PX = 2
FUZZY_MAX = 0.15           # normalized Levenshtein ceiling for OCR fuzzy matches
IN_REGION_COVERAGE = 0.5   # fraction of a hit box inside a region to count as in-region

STRUCTURE_KEYS = [
    "/JavaScript", "/OpenAction", "/AA", "/EmbeddedFiles", "/AcroForm",
    "/Metadata", "/Thumb", "/Outlines", "/OCProperties",
]
BENIGN_INFO = {"format", "encryption", "producer", "creationDate", "modDate", "creator"}


def run(cmd: list[str], timeout: int = 300) -> tuple[int, str, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout)
        return p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")
    except FileNotFoundError:
        return 127, "", f"not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout: {' '.join(cmd[:3])}"


def run_bytes(cmd: list[str], timeout: int = 300) -> bytes:
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout)
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
    return {t[i:i + 3] for i in range(len(t) - 2)} if len(t) >= 3 else {t} if t else set()


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
            window = " ".join(words[i:i + width])
            if abs(len(window) - len(ft)) > max(2, int(len(ft) * 0.4)):
                continue
            if levenshtein(window, ft) / max(len(ft), len(window)) <= FUZZY_MAX:
                return True
    return False


def sh256(path: Path) -> str:
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------- geometry

def region_to_px(rect: list[float], page_w_px: int, page_h_px: int) -> tuple[int, int, int, int]:
    """Normalized bottom-left [x,y,w,h] -> raster (left, top, right, bottom) px."""
    x, y, w, h = rect
    left = int(round(x * page_w_px))
    right = int(round((x + w) * page_w_px))
    top = int(round((1.0 - y - h) * page_h_px))
    bottom = int(round((1.0 - y) * page_h_px))
    return left, top, right, bottom


def region_to_pt(rect: list[float], page_w: float, page_h: float) -> tuple[float, float, float, float]:
    """Normalized bottom-left [x,y,w,h] -> top-left-origin points (l, t, r, b)."""
    x, y, w, h = rect
    return x * page_w, (1.0 - y - h) * page_h, (x + w) * page_w, (1.0 - y) * page_h


def box_coverage(box: tuple[float, float, float, float],
                 region: tuple[float, float, float, float]) -> float:
    l = max(box[0], region[0])
    t = max(box[1], region[1])
    r = min(box[2], region[2])
    b = min(box[3], region[3])
    if r <= l or b <= t:
        return 0.0
    area = (box[2] - box[0]) * (box[3] - box[1])
    return ((r - l) * (b - t)) / area if area > 0 else 0.0


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
                        run_bytes(["pdftotext", "-raw", "-enc", "UTF-8", "-nopgbrk",
                                   str(src), "-"]).decode("utf-8", "replace"))
                break

    ambient_folded = {fold(v) for v in ambient_values}
    for term in cell.terms:
        ft = fold(term)
        ambient = ft in ambient_folded or term in cell.expected_visible
        if not ambient and source_text:
            if source_text.count(ft) > burned_values.get(term, 0):
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


def o0_structure(cell: Cell, workdir: Path) -> dict:
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
        try:
            walk_json_keys(json.loads(out), json_keys)
        except json.JSONDecodeError:
            pass
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
        for i, page in enumerate(doc):
            if list(page.annots() or []):
                annots_pages.append(i)
        doc.close()
    except Exception as e:  # noqa: BLE001 — census stays best-effort per tool
        info_extra["_pymupdf_error"] = str(e)

    return {
        "qpdf_check_ok": rc_check == 0,
        "qpdf_check_tail": (out_check + err_check).strip().splitlines()[-1:]
        if (out_check or err_check) else [],
        "revisions": revisions,
        "structure_keys_json": sorted(json_keys),
        "structure_keys_bytes": sorted(byte_keys),
        "acroform_has_v": acroform_has_v,
        "info_extra_keys": info_extra,
        "annots_pages": annots_pages,
        "qdf_path": str(qdf) if qdf.exists() else None,
        "mu_clean_path": str(mu_clean) if mu_clean.exists() else None,
    }


def o4_census(cell: Cell) -> dict:
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

def stext_pages(output: Path) -> list[tuple[float, float, list[tuple[str, tuple[float, float, float, float]]]]]:
    """Per page: (width, height, [(char, (l,t,r,b))...]) from mutool stext."""
    xml = run_bytes(["mutool", "draw", "-q", "-F", "stext", "-o", "-", str(output)])
    pages = []
    try:
        root = ElementTree.fromstring(b"<all>" + xml + b"</all>")
    except ElementTree.ParseError:
        try:
            root = ElementTree.fromstring(xml)
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


def o1_text_layer(cell: Cell, scope: dict[str, str]) -> tuple[list[dict], dict]:
    hits: list[dict] = []
    pdftotext_layout = run_bytes(["pdftotext", "-layout", "-enc", "UTF-8", "-nopgbrk",
                                  str(cell.output), "-"]).decode("utf-8", "replace")
    pdftotext_raw = run_bytes(["pdftotext", "-raw", "-enc", "UTF-8", "-nopgbrk",
                               str(cell.output), "-"]).decode("utf-8", "replace")
    pages = stext_pages(cell.output)
    burned = cell.burned_by_page()

    import pymupdf
    rawdict_flags: dict[int, dict[str, int]] = {}
    rawdict_text: dict[int, str] = {}
    try:
        doc = pymupdf.open(cell.output)
        for i, page in enumerate(doc):
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
    except Exception:  # noqa: BLE001
        pass

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
                seg = flat[start:start + len(needle)]
                if seg:
                    l = min(b[0] for _, b in seg)
                    t = min(b[1] for _, b in seg)
                    r = max(b[2] for _, b in seg)
                    bt = max(b[3] for _, b in seg)
                    in_region = any(
                        box_coverage((l, t, r, bt), region_to_pt(reg, w, h))
                        >= IN_REGION_COVERAGE
                        for reg in burned.get(pageno, []))
                    localized.append({"page": pageno, "in_region": in_region})
                start = joined.find(needle, start + 1)
        if found_in or localized:
            in_region_hits = [x for x in localized if x["in_region"]]
            is_leak = bool(in_region_hits) or (scope.get(term) == "unique"
                                               and (found_in or localized))
            hits.append({
                "surface": "text_layer",
                "term": term,
                "scope": scope.get(term, "unique"),
                "extractors": found_in,
                "localized": localized,
                "leak": is_leak,
                "detail": "in-region text-layer content" if in_region_hits
                else "term present in output text layer",
            })
    diag = {"rawdict_char_flags": rawdict_flags}
    return hits, diag


# ---------------------------------------------------------------- O2

def octal_escape(term: str) -> bytes:
    return "".join(f"\\{ord(c):03o}" for c in term).encode()


def hex_string(term: str) -> bytes:
    return term.encode("latin-1", "replace").hex().encode()


def tj_reassembled(qdf_bytes: bytes) -> str:
    """Concatenate string operands of Tj/TJ/'/\" show ops, kern numbers stripped."""
    text_parts: list[str] = []
    for m in re.finditer(rb"\(((?:[^()\\]|\\.)*)\)", qdf_bytes):
        raw = m.group(1)
        raw = re.sub(rb"\\([0-7]{1,3})",
                     lambda g: bytes([int(g.group(1), 8) & 0xFF]), raw)
        raw = raw.replace(b"\\(", b"(").replace(b"\\)", b")").replace(b"\\\\", b"\\")
        text_parts.append(raw.decode("latin-1", "replace"))
    return "".join(text_parts)


def o2_bytes(cell: Cell, o0: dict, scope: dict[str, str], workdir: Path) -> list[dict]:
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
            rc, _, _ = run(["qpdf", "--qdf", "--object-streams=disable",
                            str(slice_path), str(rev_qdf)])
            corpora[f"revision-{i}"] = (rev_qdf.read_bytes() if rc == 0 and rev_qdf.exists()
                                        else raw[:off])
    tj_texts = {name: fold_nospace(tj_reassembled(data))
                for name, data in corpora.items() if name != "raw"}

    for term in cell.terms:
        found: list[str] = []
        variants = {term, term.upper(), term.lower()}
        for name, data in corpora.items():
            for v in variants:
                if (v.encode("utf-8") in data
                        or v.encode("utf-16-be") in data
                        or (b"\xfe\xff" + v.encode("utf-16-be")) in data
                        or hex_string(v) in data or hex_string(v).upper() in data
                        or octal_escape(v) in data):
                    found.append(name)
                    break
        for name, text in tj_texts.items():
            if fold_nospace(term) and fold_nospace(term) in text:
                found.append(f"{name}-tj")
        if found:
            hits.append({
                "surface": "decompressed_bytes",
                "term": term,
                "scope": scope.get(term, "unique"),
                "corpora": sorted(set(found)),
                # Byte legs have no geometry: ambient terms legitimately
                # remain in the bytes; only unique terms are leak evidence.
                "leak": scope.get(term) == "unique",
                "detail": "term recoverable from output bytes",
            })

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
                    hits.append({
                        "surface": "image",
                        "term": None,
                        "scope": "unique",
                        "leak": True,
                        "detail": f"GPS EXIF survives in extracted image "
                                  f"{Path(meta.get('SourceFile', '?')).name}: "
                                  f"{sorted(gps)[:4]}",
                    })
                term_hits = [t for t in cell.terms
                             if any(fold(t) in fold(str(v)) for v in meta.values())]
                for t in term_hits:
                    hits.append({
                        "surface": "image",
                        "term": t,
                        "scope": scope.get(t, "unique"),
                        "leak": scope.get(t) == "unique",
                        "detail": "term in extracted-image metadata",
                    })
    return hits


# ---------------------------------------------------------------- O3

def o3_tesseract(cell: Cell, render_dir: Path) -> dict:
    """Per page: union text over PSM 6/11/12 + PSM-6 TSV word boxes."""
    pages: dict[int, dict] = {}
    for png in sorted(render_dir.glob("pp-*.png")):
        m = re.search(r"pp-0*(\d+)\.png$", png.name)
        if not m:
            continue
        pageno = int(m.group(1)) - 1
        texts = []
        for psm in ("6", "11", "12"):
            _, out, _ = run(["tesseract", str(png), "stdout", "--oem", "1",
                             "--psm", psm, "-c", "preserve_interword_spaces=1"],
                            timeout=600)
            texts.append(out)
        _, tsv, _ = run(["tesseract", str(png), "stdout", "--oem", "1",
                         "--psm", "6", "-c", "preserve_interword_spaces=1", "tsv"],
                        timeout=600)
        words: list[tuple[str, tuple[float, float, float, float]]] = []
        for line in tsv.splitlines()[1:]:
            cols = line.split("\t")
            if len(cols) >= 12 and cols[11].strip():
                try:
                    left, top, w, h = (float(cols[6]), float(cols[7]),
                                       float(cols[8]), float(cols[9]))
                except ValueError:
                    continue
                words.append((cols[11], (left, top, left + w, top + h)))
        pages[pageno] = {"text": "\n".join(texts), "words": words, "png": png.name}
    return pages


def ocr_hits_for_engine(cell: Cell, page_texts: dict[int, str],
                        page_words: dict[int, list[tuple[str, tuple[float, float, float, float]]]],
                        px_dims: dict[int, tuple[int, int]]) -> dict[str, list[dict]]:
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
                    seg = words[i:i + k]
                    window = " ".join(w for w, _ in seg)
                    if levenshtein(fold(window), fold(term)) / max(
                            len(fold(term)), len(fold(window)), 1) <= FUZZY_MAX:
                        l = min(b[0] for _, b in seg)
                        t = min(b[1] for _, b in seg)
                        r = max(b[2] for _, b in seg)
                        bt = max(b[3] for _, b in seg)
                        for reg in burned.get(pageno, []):
                            if box_coverage((l, t, r, bt),
                                            region_to_px(reg, dims[0], dims[1])) \
                                    >= IN_REGION_COVERAGE:
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
    result = {"regions": 0, "fill_fail": [], "iou": [], "max_dev_pp": 0, "max_dev_mu": 0}
    burned = cell.burned_by_page()
    pp = {int(re.search(r"pp-0*(\d+)", p.name).group(1)) - 1: p
          for p in render_dir.glob("pp-*.png") if re.search(r"pp-0*(\d+)", p.name)}
    mu = {int(re.search(r"mu-0*(\d+)", p.name).group(1)) - 1: p
          for p in render_dir.glob("mu-*.png") if re.search(r"mu-0*(\d+)", p.name)}
    for pageno, regions in burned.items():
        img_pp = cv2.imread(str(pp[pageno]), cv2.IMREAD_GRAYSCALE) if pageno in pp else None
        img_mu = cv2.imread(str(mu[pageno]), cv2.IMREAD_GRAYSCALE) if pageno in mu else None
        if img_pp is None:
            continue
        h_pp, w_pp = img_pp.shape
        mask = (img_pp <= NEAR_BLACK).astype(np.uint8)
        n_comp, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        for idx, reg in enumerate(regions):
            result["regions"] += 1
            for img, tag in ((img_pp, "pp"), (img_mu, "mu")):
                if img is None:
                    continue
                ih, iw = img.shape
                l, t, r, b = region_to_px(reg, iw, ih)
                li, ti = l + ERODE_PX, t + ERODE_PX
                ri, bi = r - ERODE_PX, b - ERODE_PX
                if ri - li < 2 or bi - ti < 2:
                    continue
                crop = img[max(0, ti):max(0, bi), max(0, li):max(0, ri)]
                if crop.size == 0:
                    continue
                dev = int(crop.max())  # deviation from black fill = the value itself
                result[f"max_dev_{tag}"] = max(result[f"max_dev_{tag}"], dev)
                if dev > FILL_MAX_DEV:
                    crop_path = workdir / f"fillfail-p{pageno}-r{idx}-{tag}.png"
                    cv2.imwrite(str(crop_path), crop)
                    result["fill_fail"].append({
                        "page": pageno, "region_index": idx, "renderer": tag,
                        "max_dev": dev, "crop": crop_path.name,
                    })
            # Placement IoU on the pdftoppm render.
            l, t, r, b = region_to_px(reg, w_pp, h_pp)
            l, t = max(0, l), max(0, t)
            r, b = min(w_pp, r), min(h_pp, b)
            if r <= l or b <= t:
                continue
            window = labels[t:b, l:r]
            comp_ids, counts = np.unique(window[window > 0], return_counts=True)
            if len(comp_ids) == 0:
                result["iou"].append({"page": pageno, "region_index": idx, "iou": 0.0})
                continue
            comp = int(comp_ids[np.argmax(counts)])
            cl, ct = int(stats[comp, cv2.CC_STAT_LEFT]), int(stats[comp, cv2.CC_STAT_TOP])
            cr = cl + int(stats[comp, cv2.CC_STAT_WIDTH])
            cb = ct + int(stats[comp, cv2.CC_STAT_HEIGHT])
            inter = max(0, min(r, cr) - max(l, cl)) * max(0, min(b, cb) - max(t, ct))
            union = (r - l) * (b - t) + (cr - cl) * (cb - ct) - inter
            result["iou"].append({
                "page": pageno, "region_index": idx,
                "iou": round(inter / union, 4) if union else 0.0,
            })
    return result


# ---------------------------------------------------------------- O6

def utf7(term: str) -> bytes:
    try:
        return term.encode("utf-7")
    except Exception:  # noqa: BLE001
        return b""


def o6_adversarial(cell: Cell, scope: dict[str, str]) -> list[dict]:
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
            hits.append({
                "surface": "decompressed_bytes",
                "term": term,
                "scope": scope.get(term, "unique"),
                "encodings": exotic,
                "leak": scope.get(term) == "unique",
                "detail": "adversarial-encoding byte probe hit",
            })
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
        line = (err if use_err else out).strip().splitlines()
        vs[name] = line[0] if line else "?"
    return vs


# ---------------------------------------------------------------- phases

def phase_scan(cells_dir: Path, docs_root: Path | None, dpi: int) -> None:
    cells = discover_cells(cells_dir)
    if not cells:
        sys.exit(f"no cells under {cells_dir}")
    vision_in = cells_dir / "vision-in"
    vision_in.mkdir(exist_ok=True)
    versions = tool_versions()
    print(f"[oracle] scan: {len(cells)} cells, dpi={dpi}")
    for cell in cells:
        workdir = cell.dir / "oracle-work"
        workdir.mkdir(exist_ok=True)
        render = cell.dir / "render"
        render.mkdir(exist_ok=True)
        if not list(render.glob("pp-*.png")):
            run(["pdftoppm", "-r", str(dpi), "-gray", "-png",
                 str(cell.output), str(render / "pp")], timeout=900)
        if not list(render.glob("mu-*.png")):
            run(["mutool", "draw", "-q", "-r", "300", "-o",
                 str(render / "mu-%d.png"), str(cell.output)], timeout=900)
        for png in sorted(render.glob("pp-*.png")):
            link = vision_in / f"{cell.key}__{png.name}"
            if not link.exists():
                link.symlink_to(png.resolve())

        scope = compute_term_scope(cell, docs_root)
        o0 = o0_structure(cell, workdir)
        o1_hits, o1_diag = o1_text_layer(cell, scope)
        o2_hits = o2_bytes(cell, o0, scope, workdir)
        tess = o3_tesseract(cell, render)
        import pymupdf
        # px dims for OCR localization (tesseract ran on the pdftoppm renders)
        px_dims: dict[int, tuple[int, int]] = {}
        try:
            import cv2
            for png in render.glob("pp-*.png"):
                m = re.search(r"pp-0*(\d+)", png.name)
                if m:
                    img = cv2.imread(str(png), cv2.IMREAD_GRAYSCALE)
                    if img is not None:
                        px_dims[int(m.group(1)) - 1] = (img.shape[1], img.shape[0])
        except Exception:  # noqa: BLE001
            pass
        tess_hits = ocr_hits_for_engine(
            cell, {p: d["text"] for p, d in tess.items()},
            {p: d["words"] for p, d in tess.items()}, px_dims)
        o4 = o4_census(cell)
        o5 = o5_pixels(cell, render, workdir)
        o6_hits = o6_adversarial(cell, scope)

        partial = {
            "schema_version": SCHEMA_VERSION,
            "cell": cell.key,
            "term_scope": scope,
            "o0": o0,
            "o1_hits": o1_hits,
            "o1_diag": o1_diag,
            "o2_hits": o2_hits,
            "o3_tesseract_hits": tess_hits,
            "o4": o4,
            "o5": o5,
            "o6_hits": o6_hits,
            "px_dims": {str(k): v for k, v in px_dims.items()},
            "versions": versions,
            "dpi": dpi,
        }
        (cell.dir / "oracle-partial.json").write_text(
            json.dumps(partial, indent=1, sort_keys=True))
        print(f"[oracle] scanned {cell.key}")
    print(
        "[oracle] scan done. Run the Vision leg from the iOS worktree "
        "(HOST swift test), then finalize:\n"
        f"  cd <ios>/Packages/RedactionEngine && RESECTA_VISION_IN={vision_in} "
        f"RESECTA_VISION_OUT={cells_dir / 'vision-out'} "
        "swift test --filter VisionOracleEmitterTests\n"
        f"  python tools/verify_oracle.py finalize --cells {cells_dir}"
    )


TERM_PRESENCE_LAYERS = {
    "Text Extraction", "OCR Check", "Binary String Search", "Operator Re-Extraction",
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
        r.get("surface") in TERM_SURFACES and r.get("term") for r in review)
    corroborated = (term_presence if attributed in TERM_PRESENCE_LAYERS else leaked)
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
            vision_texts[pageno] = "\n".join(l["text"] for l in rep.get("lines", []))
            words = []
            dims = px_dims.get(pageno)
            if dims:
                w_px, h_px = dims
                for l in rep.get("lines", []):
                    bx, by, bw, bh = l["bbox"]  # normalized bottom-left
                    box = (bx * w_px, (1 - by - bh) * h_px,
                           (bx + bw) * w_px, (1 - by) * h_px)
                    words.append((l["text"], box))
            vision_words[pageno] = words
        vision_hits = ocr_hits_for_engine(cell, vision_texts, vision_words, px_dims)

        # OCR quorum + review flags.
        tess_hits = partial["o3_tesseract_hits"]
        ocr_leaks: list[dict] = []
        review: list[dict] = []
        for term in set(tess_hits) | set(vision_hits):
            t_pages = {h["page"]: h for h in tess_hits.get(term, [])}
            v_pages = {h["page"]: h for h in vision_hits.get(term, [])}
            quorum_pages = sorted(set(t_pages) & set(v_pages))
            single_pages = sorted(set(t_pages) ^ set(v_pages))
            for pageno in quorum_pages:
                in_region = t_pages[pageno]["in_region"] or v_pages[pageno]["in_region"]
                is_leak = in_region  # out-of-region OCR falls to review (docstring)
                entry = {
                    "surface": "ocr", "term": term, "page": pageno,
                    "scope": scope.get(term, "unique"),
                    "engines": ["tesseract", "vision"],
                    "in_region": in_region, "leak": is_leak,
                    "detail": "OCR quorum recovery"
                              + (" inside a burned region" if in_region else
                                 " outside every burned region"),
                }
                (ocr_leaks if is_leak else review).append(entry)
            for pageno in single_pages:
                src = "tesseract" if pageno in t_pages else "vision"
                review.append({
                    "surface": "ocr", "term": term, "page": pageno,
                    "scope": scope.get(term, "unique"), "engines": [src],
                    "leak": False,
                    "detail": f"single-engine OCR sighting ({src})"
                              + ("" if vision_present else
                                 "; Vision leg absent — quorum unreachable"),
                })

        # Structure hits (content-bearing keys only).
        o0 = partial["o0"]
        structure_hits: list[dict] = []
        content_keys = set(o0["structure_keys_json"])
        for key in sorted(content_keys):
            if key == "/AcroForm" and not o0["acroform_has_v"]:
                review.append({"surface": "structure", "key": key, "leak": False,
                               "detail": "AcroForm present without field values"})
                continue
            structure_hits.append({
                "surface": "structure", "key": key, "leak": True,
                "detail": f"content-bearing key {key} survives in the output",
            })
        byte_only = sorted(set(o0["structure_keys_bytes"]) - content_keys)
        for key in byte_only:
            review.append({"surface": "structure", "key": key, "leak": False,
                           "detail": "key token in bytes but not in the qpdf object tree"})
        if o0["revisions"] > 1:
            structure_hits.append({
                "surface": "structure", "key": "revisions", "leak": True,
                "detail": f"output carries {o0['revisions']} %%EOF revisions",
            })
        if o0["info_extra_keys"]:
            vals = " ".join(str(v) for v in o0["info_extra_keys"].values())
            term_hit = any(fold(t) in fold(vals) for t in cell.terms)
            structure_hits.append({
                "surface": "structure", "key": "/Info", "leak": True,
                "detail": "non-benign Info keys "
                          f"{sorted(o0['info_extra_keys'])}"
                          + (" INCLUDING a sensitive term" if term_hit else ""),
            })
        if o0["annots_pages"]:
            structure_hits.append({
                "surface": "structure", "key": "/Annots", "leak": True,
                "detail": f"annotations survive on pages {o0['annots_pages']}",
            })

        pixel_hits = [{
            "surface": "pixel", "leak": True,
            "detail": f"fill deviation {f['max_dev']} > {FILL_MAX_DEV} "
                      f"({f['renderer']}) page {f['page']} region {f['region_index']}",
            **f,
        } for f in partial["o5"]["fill_fail"]]

        text_leaks = [h for h in partial["o1_hits"] if h["leak"]]
        text_review = [h for h in partial["o1_hits"] if not h["leak"]]
        byte_leaks = [h for h in partial["o2_hits"] + partial["o6_hits"] if h["leak"]]
        byte_review = [h for h in partial["o2_hits"] + partial["o6_hits"] if not h["leak"]]
        image_leaks = [h for h in byte_leaks if h["surface"] == "image"]
        byte_leaks = [h for h in byte_leaks if h["surface"] != "image"]

        leak_hits = (text_leaks + byte_leaks + image_leaks + ocr_leaks
                     + structure_hits + pixel_hits)
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
        print(f"[oracle] {cell.key}: {cls}"
              + (f" (attributed: {attributed})" if attributed else ""))

    # ------- summary (feeds M12-07..10) -------
    by_class: dict[str, int] = {}
    false_fail_by_layer: dict[str, int] = {}
    false_pass_cells: list[str] = []
    surface_recovery: dict[str, set] = {s: set() for s in (
        "text_layer", "decompressed_bytes", "ocr", "image", "structure")}
    burned_items = 0
    ious_all: list[float] = []
    fill_fail_total = 0
    for cell, oracle in zip(cells, summary_cells, strict=False):
        by_class[oracle["classification"]] = by_class.get(oracle["classification"], 0) + 1
        if oracle["classification"] == "false_fail":
            false_fail_by_layer[oracle["attributed_layer"] or "?"] = \
                false_fail_by_layer.get(oracle["attributed_layer"] or "?", 0) + 1
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
            s: {"recovered_items": len(v), "burned_items_total": burned_items,
                "rate": round(len(v) / burned_items, 6) if burned_items else None}
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
        "vision_leg_present_everywhere": all(
            o["vision_leg_present"] for o in summary_cells) if summary_cells else False,
    }
    (cells_dir / "oracle-summary.json").write_text(
        json.dumps(summary, indent=1, sort_keys=True))
    print(f"[oracle] finalize done: {len(summary_cells)} cells -> "
          f"{cells_dir / 'oracle-summary.json'}")
    print(json.dumps({k: summary[k] for k in (
        "classification_counts", "false_fail_by_attributed_layer",
        "fill_fail_regions", "placement_iou")}, indent=1))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="phase", required=True)
    scan = sub.add_parser("scan", help="renders + O0-O2/O4-O6 + Tesseract; stages the Vision leg")
    scan.add_argument("--cells", required=True, type=Path)
    scan.add_argument("--docs-root", type=Path, default=None)
    scan.add_argument("--dpi", type=int, default=400)
    fin = sub.add_parser("finalize", help="merge the Vision leg, quorum, classification, summary")
    fin.add_argument("--cells", required=True, type=Path)
    fin.add_argument("--keep-renders", action="store_true")
    args = ap.parse_args()
    if args.phase == "scan":
        phase_scan(args.cells, args.docs_root, args.dpi)
    else:
        phase_finalize(args.cells, args.keep_renders)


if __name__ == "__main__":
    main()
