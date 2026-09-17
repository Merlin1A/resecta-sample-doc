#!/usr/bin/env python3
"""H3.2 — the differential search oracle (1.2 instrumentation plan §6).

An INDEPENDENT re-implementation of the engine's documented search semantics
(Models/SearchTypes.swift option contracts + Utilities/TextNormalizer.swift
rules + the DocumentSearcher matcher shapes), run over two independent text
extractions (PyMuPDF and Poppler pdftotext -raw), diffed against the H3.1
product hits, with a metamorphic-relation layer, the M12-14 OCR legs, and
the freeze/score phases that produce and grade the adjudicated GT sidecars.

Differential doctrine ([R03]): extractor disagreement is real — expectations
are computed per extractor and a cell is oracle-CLEAN only when both agree;
scoring authority is presence/count on agreed text, never exact byte
offsets. Geometry is audited separately via word-box IoU on single-token
literal queries (text-appropriate threshold 0.7).

Phases (all deterministic; no dates — run ids come from the caller):
  expect       PDFs + query bank -> oracle-expect-<doc>.json
  diff         product run vs expectations -> diff-<doc>.json
  metamorphic  relation checks over product hits -> metamorphic.json
  ocr          M12-14 legs over scan-sim hits + ocr-lines -> ocr-report.json
  freeze       product hits + adjudication -> ../search-ground-truth/*.search-gt.json
  score        product hits vs frozen GT -> score.json (M12-13 table)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

import pymupdf

SD_ROOT = Path(__file__).resolve().parent.parent
GT_DIR = SD_ROOT / "search-ground-truth"

TOGGLES = [
    "caseSensitive",
    "wholeWord",
    "includeOCR",
    "normalizeUnicode",
    "exactMatch",
    "stripDigitSeparators",
    "normalizeSmartPunctuation",
    "foldDiacritics",
    "multiTermConjunction",
]

# ---------------------------------------------------------------------------
# Engine-rule re-implementation (from the documented spec, not the source
# call graph): TextNormalizer rules + matcher shapes.
# ---------------------------------------------------------------------------

LIGATURES = {
    "ﬃ": "ffi",
    "ﬄ": "ffl",
    "ﬀ": "ff",
    "ﬁ": "fi",
    "ﬂ": "fl",
}
SMART_PUNCT = {
    "“": '"',
    "”": '"',
    "‘": "'",  # noqa: RUF001 -- deliberate Unicode variant under test
    "’": "'",  # noqa: RUF001 -- deliberate Unicode variant under test
    "–": "-",  # noqa: RUF001 -- deliberate Unicode variant under test
    "—": "-",
    "‒": "-",  # noqa: RUF001 -- deliberate Unicode variant under test
    "‑": "-",  # noqa: RUF001 -- deliberate Unicode variant under test
    "­": "-",
}
SEPARATORS = set("- ./,")


def nfkc(text: str) -> str:
    for lig, rep in LIGATURES.items():
        text = text.replace(lig, rep)
    return unicodedata.normalize("NFKC", text)


def normalize_for_search(text: str, case_sensitive: bool) -> str:
    out = nfkc(text)
    return out if case_sensitive else out.lower()


def smart_punct(text: str) -> str:
    return "".join(SMART_PUNCT.get(c, c) for c in text)


def strip_separators(text: str) -> tuple[str, list[int]]:
    out, omap = [], []
    for i, c in enumerate(text):
        if c in SEPARATORS:
            continue
        out.append(c)
        omap.append(i)
    return "".join(out), omap


def fold_diacritics(text: str) -> tuple[str, list[int]]:
    out, omap = [], []
    for i, c in enumerate(text):
        kept = [s for s in unicodedata.normalize("NFD", c) if unicodedata.category(s) != "Mn"]
        if not kept:
            continue
        piece = unicodedata.normalize("NFC", "".join(kept))
        for pc in piece:
            out.append(pc)
            omap.append(i)
    return "".join(out), omap


def apply_extensions(page: str, query: str, opt: dict):
    """Mirror of applySearchExtensions: smart -> fold -> strip, maps composed
    back to the post-smart 'base' space. Returns (page, query, base, map|None)."""
    if opt["normalizeSmartPunctuation"]:
        page = smart_punct(page)
        query = smart_punct(query)
    base = page
    omap = None
    if opt["foldDiacritics"]:
        page, m = fold_diacritics(page)
        omap = m
        query, _ = fold_diacritics(query)
    if opt["stripDigitSeparators"]:
        page, m = strip_separators(page)
        omap = [omap[i] for i in m] if omap is not None else m
        query, _ = strip_separators(query)
    return page, query, base, omap


def is_word_char(c: str) -> bool:
    return c.isalnum() or c == "_"


def whole_word_ok(chars: str, start: int, end_exclusive: int) -> bool:
    if start > 0 and is_word_char(chars[start - 1]):
        return False
    return not (end_exclusive < len(chars) and is_word_char(chars[end_exclusive]))


def literal_matches(page_text: str, query: str, opt: dict) -> list[tuple[int, int]]:
    """Text-mode matcher over one page's text: (base_start, base_end) tuples
    in the post-smart base space (== the searched space when no length-
    changing extension is active). Non-overlapping left-to-right, matching
    the engine's searchStart = matchRange.upperBound walk."""
    npage = (
        normalize_for_search(page_text, opt["caseSensitive"])
        if opt["normalizeUnicode"]
        else (page_text if opt["caseSensitive"] else page_text.lower())
    )
    nquery = (
        normalize_for_search(query, opt["caseSensitive"])
        if opt["normalizeUnicode"]
        else (query if opt["caseSensitive"] else query.lower())
    )
    if not nquery:
        return []
    spage, squery, base, omap = apply_extensions(npage, nquery, opt)
    if not squery:
        return []
    hits = []
    idx = 0
    while True:
        found = spage.find(squery, idx)
        if found < 0:
            break
        s, length = found, len(squery)
        if omap is not None:
            if s + length - 1 >= len(omap):
                break
            bs = omap[s]
            be = omap[s + length - 1] + 1
        else:
            bs, be = s, s + length
        ok = True
        if opt["wholeWord"] or opt["exactMatch"]:
            ok = whole_word_ok(base, bs, be)
        if ok:
            hits.append((bs, be))
        idx = found + length
    return hits


def regex_matches(page_text: str, pattern: str, opt: dict):
    """Regex-mode matcher: page-side NFKC (per option) + smart punct; the
    pattern is NEVER transformed and case is NEVER folded. Returns
    (list[(start,end)], error|None) — python `re` stands in for ICU, so a
    compile divergence is reported, not asserted."""
    text = nfkc(page_text) if opt["normalizeUnicode"] else page_text
    if opt["normalizeSmartPunctuation"]:
        text = smart_punct(text)
    try:
        rx = re.compile(pattern)
    except re.error as e:
        return [], f"py-compile: {e}"
    hits = []
    for m in rx.finditer(text):
        if m.start() == m.end():
            continue
        if opt["wholeWord"] and not whole_word_ok(text, m.start(), m.end()):
            continue
        hits.append((m.start(), m.end()))
    return hits, None


def multiterm_page_counts(page_text: str, terms: list[str], opt: dict) -> dict[str, int]:
    return {t: len(literal_matches(page_text, t, opt)) for t in terms}


def cell_counts(pages: list[str], row: dict, opt: dict):
    """Per-page expected hit counts for one (query, vector) on one extractor
    text. Returns (per_page_counts, note|None)."""
    mode = row["mode"]
    if mode == "text":
        return [len(literal_matches(t, row["query"], opt)) for t in pages], None
    if mode == "regex":
        counts, err = [], None
        for t in pages:
            h, e = regex_matches(t, row["pattern"], opt)
            counts.append(len(h))
            err = err or e
        return counts, err
    if mode == "multiTerm":
        per_page = [multiterm_page_counts(t, row["terms"], opt) for t in pages]
        if opt["multiTermConjunction"]:
            distinct = set(row["terms"])
            return [
                sum(c.values()) if all(c.get(t, 0) > 0 for t in distinct) else 0 for c in per_page
            ], None
        return [sum(c.values()) for c in per_page], None
    raise ValueError(mode)


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------


def extract_pymupdf(pdf: Path) -> list[str]:
    doc = pymupdf.open(pdf)
    return [p.get_text() for p in doc]


def extract_pdftotext(pdf: Path) -> list[str]:
    out = subprocess.run(
        ["pdftotext", "-raw", "-enc", "UTF-8", "-nopgbrk", str(pdf), "-"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    # -nopgbrk drops the \f page breaks; re-run WITH breaks for page split.
    out = subprocess.run(
        ["pdftotext", "-raw", "-enc", "UTF-8", str(pdf), "-"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    pages = out.split("\f")
    if pages and pages[-1] == "":
        pages.pop()
    return pages


def word_boxes(pdf: Path) -> list[list[tuple[str, tuple[float, float, float, float]]]]:
    """PyMuPDF word boxes per page, normalized 0-1 BOTTOM-LEFT origin
    (the SearchResult.normalizedRect convention)."""
    doc = pymupdf.open(pdf)
    pages = []
    for p in doc:
        W, H = p.rect.width, p.rect.height
        rows = []
        for x0, y0, x1, y1, word, *_ in p.get_text("words"):
            rows.append((word, (x0 / W, 1 - y1 / H, (x1 - x0) / W, (y1 - y0) / H)))
        pages.append(rows)
    return pages


def iou(a, b) -> float:
    ax0, ay0, aw, ah = a
    bx0, by0, bw, bh = b
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax0 + aw, bx0 + bw), min(ay0 + ah, by0 + bh)
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    inter = (ix1 - ix0) * (iy1 - iy0)
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


# ---------------------------------------------------------------------------
# Shared loading
# ---------------------------------------------------------------------------


def load_bank():
    bank = json.loads((GT_DIR / "search-queries.json").read_text())
    vectors = {v["id"]: v["options"] for v in bank["vectors"]}
    queries = {q["qid"]: q for q in bank["queries"]}
    return bank, vectors, queries


def load_run(hits_dir: Path, doc_id: str, run: int = 1) -> dict:
    return json.loads((hits_dir / doc_id / f"run-{run}.json").read_text())


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(obj, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, sort_keys=True, ensure_ascii=True) + "\n")
    print(f"wrote {path}")


def product_page_counts(cell: dict, page_count: int) -> list[int]:
    counts = [0] * page_count
    for h in cell["hits"]:
        counts[h["page"]] += 1
    return counts


# ---------------------------------------------------------------------------
# Phase "expect"
# ---------------------------------------------------------------------------


def phase_expect(args):
    bank, vectors, queries = load_bank()
    doc_id = args.doc
    pdf = SD_ROOT / bank["docs"][doc_id]["path"]
    if not sha256(pdf) == bank["docs"][doc_id]["sha256"]:
        raise AssertionError("doc drift vs bank pin")
    texts = {
        "pymupdf": extract_pymupdf(pdf),
        "pdftotext_raw": extract_pdftotext(pdf),
    }
    n_pages = len(texts["pymupdf"])
    rows = {}
    for qid, row in queries.items():
        for vid, opt in vectors.items():
            per_ex = {}
            note = None
            for ex, pages in texts.items():
                counts, n = cell_counts(pages, row, opt)
                per_ex[ex] = counts
                note = note or n
            entry = {
                "counts": per_ex,
                "agree": per_ex["pymupdf"] == per_ex["pdftotext_raw"],
            }
            if note:
                entry["note"] = note
            rows[f"{qid}|{vid}"] = entry
    agree_n = sum(1 for r in rows.values() if r["agree"])
    out = {
        "schema_version": 1,
        "generated_by": "search_oracle.py expect",
        "doc_id": doc_id,
        "doc_sha256": bank["docs"][doc_id]["sha256"],
        "page_count": n_pages,
        "extractors": ["pymupdf", "pdftotext_raw"],
        "cells": rows,
        "agree_cells": agree_n,
        "total_cells": len(rows),
    }
    dump(out, Path(args.out) / f"oracle-expect-{doc_id}.json")
    print(f"[expect] {doc_id}: {agree_n}/{len(rows)} extractor-agreed cells")


# ---------------------------------------------------------------------------
# Phase: diff  (text legs; the oracle models the TEXT-LAYER path, so this
# phase is for the all-rich packet — the scan-sim OCR leg is graded by
# phase `ocr` against the product's own Vision text.)
# ---------------------------------------------------------------------------


def phase_diff(args):
    bank, _vectors, queries = load_bank()
    doc_id = args.doc
    expect = json.loads((Path(args.out) / f"oracle-expect-{doc_id}.json").read_text())
    run = load_run(Path(args.hits), doc_id)
    n_pages = run["page_count"]
    boxes = word_boxes(SD_ROOT / bank["docs"][doc_id]["path"])

    classes = Counter()
    divergent = []
    iou_audit = []
    for cell in run["cells"]:
        key = f"{cell['qid']}|{cell['vector_id']}"
        exp = expect["cells"][key]
        got = product_page_counts(cell, n_pages)
        m_py = got == exp["counts"]["pymupdf"]
        m_pt = got == exp["counts"]["pdftotext_raw"]
        if m_py and m_pt:
            cls = "match_both"
        elif m_py or m_pt:
            cls = "extractor_split"
        else:
            cls = "product_diverges"
        classes[cls] += 1
        if cls != "match_both":
            divergent.append(
                {
                    "qid": cell["qid"],
                    "vector_id": cell["vector_id"],
                    "class": cls,
                    "product": got,
                    "pymupdf": exp["counts"]["pymupdf"],
                    "pdftotext_raw": exp["counts"]["pdftotext_raw"],
                    "note": exp.get("note"),
                }
            )
        # Geometry audit: single-token literal text queries, agreed cells.
        q = queries[cell["qid"]]
        if q["mode"] == "text" and cls == "match_both" and cell["hits"] and " " not in q["query"]:
            ious = []
            for h in cell["hits"]:
                page_words = boxes[h["page"]]
                cand = [
                    iou(h["rect"], wb) for w, wb in page_words if q["query"].lower() in w.lower()
                ]
                if cand:
                    ious.append(max(cand))
            if ious:
                ious.sort()
                iou_audit.append(
                    {
                        "qid": cell["qid"],
                        "vector_id": cell["vector_id"],
                        "n": len(ious),
                        "median_iou": round(ious[len(ious) // 2], 4),
                        "min_iou": round(ious[0], 4),
                    }
                )
    med = sorted(a["median_iou"] for a in iou_audit)
    out = {
        "schema_version": 1,
        "generated_by": "search_oracle.py diff",
        "doc_id": doc_id,
        "classes": dict(classes),
        "divergent_cells": divergent,
        "iou_audit": {
            "cells": len(iou_audit),
            "median_of_medians": med[len(med) // 2] if med else None,
            "below_0_7": [a for a in iou_audit if a["median_iou"] < 0.7],
        },
    }
    dump(out, Path(args.out) / f"diff-{doc_id}.json")
    print(f"[diff] {doc_id}: {dict(classes)}; {len(out['iou_audit']['below_0_7'])} iou<0.7 cells")


# ---------------------------------------------------------------------------
# Phase "metamorphic"
# ---------------------------------------------------------------------------


def hit_multiset(cell, key=lambda h: (h["page"], tuple(h["rect"]))):
    return Counter(key(h) for h in cell["hits"])


def phase_metamorphic(args):
    bank, vectors, queries = load_bank()
    results = []

    def add(relation, doc, qid, va, vb, ok, detail=""):
        results.append(
            {
                "relation": relation,
                "doc": doc,
                "qid": qid,
                "vectors": [va, vb],
                "ok": ok,
                "detail": detail,
            }
        )

    hamming = []
    vids = sorted(vectors)
    for i, a in enumerate(vids):
        for b in vids[i + 1 :]:
            d = [t for t in TOGGLES if vectors[a][t] != vectors[b][t]]
            if len(d) == 1:
                hamming.append((a, b, d[0]))

    for doc_id in args.docs.split(","):
        run = load_run(Path(args.hits), doc_id)
        cells = {(c["qid"], c["vector_id"]): c for c in run["cells"]}

        for a, b, t in hamming:
            on, off = (a, b) if vectors[a][t] else (b, a)
            for qid, q in queries.items():
                ca, cb = cells[(qid, on)], cells[(qid, off)]
                ms_on, ms_off = hit_multiset(ca), hit_multiset(cb)
                if t == "caseSensitive" and q["mode"] in ("text", "multiTerm"):
                    ok = all(ms_on[k] <= ms_off[k] for k in ms_on)
                    add(
                        "ci-superset-of-cs",
                        doc_id,
                        qid,
                        off,
                        on,
                        ok,
                        "" if ok else "case-sensitive produced hits the insensitive run lacks",
                    )
                if t == "wholeWord":
                    ok = all(ms_on[k] <= ms_off[k] for k in ms_on)
                    add("wholeword-subset", doc_id, qid, off, on, ok)
                if t == "foldDiacritics" and q["mode"] in ("text", "multiTerm"):
                    ok = all(ms_off[k] <= ms_on[k] for k in ms_off)
                    add("folded-superset", doc_id, qid, off, on, ok)
                if t == "multiTermConjunction" and q["mode"] == "multiTerm":
                    pages_on = {h["page"] for h in ca["hits"]}
                    pages_off = {h["page"] for h in cb["hits"]}
                    ok = pages_on <= pages_off
                    add("and-pages-subset-of-or", doc_id, qid, off, on, ok)
                # Inert-toggle invariance claims.
                inert = (
                    (t == "multiTermConjunction" and q["mode"] in ("text", "regex"))
                    or (
                        q["mode"] == "regex"
                        and t
                        in ("caseSensitive", "exactMatch", "stripDigitSeparators", "foldDiacritics")
                    )
                    or (doc_id == "packet" and t == "includeOCR")
                    or (
                        doc_id == "packet"
                        and t in ("normalizeUnicode", "foldDiacritics")
                        and q["mode"] in ("text", "multiTerm")
                        and q["family"] != "smartpunct-probe"
                    )
                )
                if inert:
                    ok = ms_on == ms_off
                    add(
                        f"inert-{t}",
                        doc_id,
                        qid,
                        off,
                        on,
                        ok,
                        "" if ok else f"{sum(ms_on.values())} vs {sum(ms_off.values())} hits",
                    )

        # exactMatch == wholeWord equivalence on text/multiTerm.
        for qid, q in queries.items():
            if q["mode"] not in ("text", "multiTerm"):
                continue
            ce = cells[(qid, "v05-flip-exactMatch")]
            cw = cells[(qid, "v02-flip-wholeWord")]
            ok = hit_multiset(ce) == hit_multiset(cw)
            add(
                "exactmatch-equiv-wholeword",
                doc_id,
                qid,
                "v05-flip-exactMatch",
                "v02-flip-wholeWord",
                ok,
            )

        # Literal/regex twins on caseSensitive vectors without strip/fold.
        twin_vecs = [
            v
            for v in vids
            if vectors[v]["caseSensitive"]
            and not vectors[v]["stripDigitSeparators"]
            and not vectors[v]["foldDiacritics"]
        ]
        for lit, rx in bank["metamorphic"]["literal_regex_twins"]:
            for v in twin_vecs:
                cl, cr = cells[(lit, v)], cells[(rx, v)]
                ok = hit_multiset(cl) == hit_multiset(cr)
                add("literal-equals-escaped-regex", doc_id, f"{lit}~{rx}", v, v, ok)

    # Annotate failures on burst cells (the bufferingNewest drop makes any
    # cross-vector count comparison unreliable there) — kept in the report,
    # sliced apart from real relation violations.
    for r in results:
        if r["ok"]:
            continue
        run = load_run(Path(args.hits), r["doc"])
        cs = {(c["qid"], c["vector_id"]): c for c in run["cells"]}
        qids = r["qid"].split("~")
        burst = False
        for qid in qids:
            for v in r["vectors"]:
                cell = cs.get((qid, v))
                if cell:
                    pages = Counter(h["page"] for h in cell["hits"])
                    if pages and max(pages.values()) > 100:
                        burst = True
        r["burst_drop_suspect"] = burst

    failures = [r for r in results if not r["ok"]]
    by_rel = Counter(r["relation"] for r in results)
    fail_rel = Counter(r["relation"] for r in failures)
    out = {
        "schema_version": 1,
        "generated_by": "search_oracle.py metamorphic",
        "checked": len(results),
        "by_relation": dict(by_rel),
        "failures": failures,
        "failed_by_relation": dict(fail_rel),
        "failures_non_burst": [r for r in failures if not r.get("burst_drop_suspect")],
    }
    dump(out, Path(args.out) / "metamorphic.json")
    print(
        f"[metamorphic] {len(results)} checks, {len(failures)} failures "
        f"{dict(fail_rel) if failures else ''}"
    )


# ---------------------------------------------------------------------------
# Phase: ocr  (M12-14 — correctness-vs-OCR-text + end-to-end findability)
# ---------------------------------------------------------------------------

# OCRTextNormalizer re-implementation (confusable correction, from spec).
DIGIT_MAP = {"O": "0", "o": "0", "I": "1", "l": "1", "B": "8", "S": "5", "Z": "2", "G": "6"}
LETTER_MAP = {"0": "O", "1": "I", "5": "S", "8": "B"}
AMBIG_LETTERS = set("OoIlBSZG")
AMBIG_DIGITS = set("0158")


def _tendency(chars):
    digits = sum(1 for c in chars if c.isdigit() and c not in AMBIG_DIGITS)
    letters = sum(1 for c in chars if c.isalpha() and c not in AMBIG_LETTERS)
    if digits > 0 and letters == 0:
        return "digit"
    if letters > 0 and digits == 0:
        return "letter"
    if digits > letters:
        return "digit"
    if letters > digits:
        return "letter"
    return "pass"


def confusable_normalize(line: str) -> str:
    line_t = _tendency([c for c in line if c.isalnum()])
    out = []
    token = []

    def flush():
        if not token:
            return
        t = _tendency(token)
        if t == "pass":
            t = line_t
        for c in token:
            if t == "digit":
                out.append(DIGIT_MAP.get(c, c))
            elif t == "letter":
                out.append(LETTER_MAP.get(c, c))
            else:
                out.append(c)
        token.clear()

    for c in line:
        if c.isalnum():
            token.append(c)
        else:
            flush()
            out.append(c)
    flush()
    return "".join(out)


def ocr_literal_line_hits(norm_line: str, query: str, opt: dict) -> int:
    """Literal OCR-leg matcher: per line, on the product-normalized line."""
    return len(literal_matches(norm_line, query, opt))


def phase_ocr(args):
    _bank, vectors, queries = load_bank()
    doc_id = args.doc
    hits_dir = Path(args.hits)
    run = load_run(hits_dir, doc_id)
    lines_file = json.loads(
        (hits_dir / doc_id / f"ocr-lines-run-{run['run_index']}.json").read_text()
    )
    norm_lines = {
        p["page"]: [line["normalized"] for line in p["lines"]] for p in lines_file["pages"]
    }
    raw_lines = {p["page"]: [line["text"] for line in p["lines"]] for p in lines_file["pages"]}
    n_pages = run["page_count"]

    # Confusable-normalizer cross-check (spec reimpl vs product output).
    confusable_diffs = []
    for page, raws in raw_lines.items():
        for i, raw in enumerate(raws):
            mine = confusable_normalize(raw)
            theirs = norm_lines[page][i]
            if mine != theirs:
                confusable_diffs.append(
                    {"page": page, "line": i, "raw": raw, "product": theirs, "reimpl": mine}
                )

    # Correctness-vs-OCR-text: re-derive expected per-page counts from the
    # product's own Vision lines under the documented OCR-leg semantics.
    # Patterns the product safety-REJECTS (established on the text-leg diff)
    # are graded separately: the pure-regex reimpl cannot model the rejection,
    # so the check there is that the rejection holds on this leg too
    # (product all-zero), not count equality.
    safety_rejected = set((args.safety_rejected or "").split(",")) - {""}
    rejected_cells = []
    cell_results = []
    for cell in run["cells"]:
        q = queries[cell["qid"]]
        opt = vectors[cell["vector_id"]]
        got = product_page_counts(cell, n_pages)
        want = [0] * n_pages
        if opt["includeOCR"]:
            for page in range(n_pages):
                lines = norm_lines.get(page, [])
                if q["mode"] == "text":
                    want[page] = sum(ocr_literal_line_hits(line, q["query"], opt) for line in lines)
                elif q["mode"] == "multiTerm":
                    per_term = {
                        t: sum(ocr_literal_line_hits(line, t, opt) for line in lines)
                        for t in q["terms"]
                    }
                    if opt["multiTermConjunction"]:
                        want[page] = (
                            sum(per_term.values())
                            if all(per_term[t] > 0 for t in set(q["terms"]))
                            else 0
                        )
                    else:
                        want[page] = sum(per_term.values())
                else:  # regex: joined lines, NEVER NFKC, page-side smart punct
                    text = "\n".join(lines)
                    if opt["normalizeSmartPunctuation"]:
                        text = smart_punct(text)
                    try:
                        rx = re.compile(q["pattern"])
                        n = 0
                        for m in rx.finditer(text):
                            if m.start() == m.end():
                                continue
                            if opt["wholeWord"] and not whole_word_ok(text, m.start(), m.end()):
                                continue
                            n += 1
                        want[page] = n
                    except re.error:
                        want[page] = None  # py-compile divergence; skip cell
        if None in want:
            continue
        if cell["qid"] in safety_rejected:
            rejected_cells.append(
                {
                    "qid": cell["qid"],
                    "vector_id": cell["vector_id"],
                    "product_zero": sum(got) == 0,
                }
            )
            continue
        cell_results.append(
            {
                "qid": cell["qid"],
                "vector_id": cell["vector_id"],
                "match": got == want,
                "product": got,
                "reimpl": want,
            }
        )
    matched = sum(1 for c in cell_results if c["match"])
    mismatches = [c for c in cell_results if not c["match"]]

    # End-to-end findability: gt-value text queries at v00 — pages found on
    # the packet text leg vs pages found here.
    packet_run = load_run(hits_dir, "packet")
    packet_cells = {(c["qid"], c["vector_id"]): c for c in packet_run["cells"]}
    scan_cells = {(c["qid"], c["vector_id"]): c for c in run["cells"]}
    findability = []
    for qid, q in queries.items():
        if q["mode"] != "text" or q["family"] not in ("gt-value",):
            continue
        truth_pages = {h["page"] for h in packet_cells[(qid, "v00-default")]["hits"]}
        found_pages = {h["page"] for h in scan_cells[(qid, "v00-default")]["hits"]}
        if not truth_pages:
            continue
        findability.append(
            {
                "qid": qid,
                "query": q["query"],
                "truth_pages": sorted(truth_pages),
                "found_pages": sorted(found_pages),
                "found_frac": round(len(truth_pages & found_pages) / len(truth_pages), 4),
                "spurious_pages": sorted(found_pages - truth_pages),
            }
        )
    fracs = sorted(f["found_frac"] for f in findability)
    out = {
        "schema_version": 1,
        "generated_by": "search_oracle.py ocr",
        "doc_id": doc_id,
        "confusable_reimpl_diffs": confusable_diffs,
        "correctness_vs_ocr_text": {
            "cells_graded": len(cell_results),
            "cells_matched": matched,
            "rate": round(matched / len(cell_results), 6) if cell_results else None,
            "mismatches": mismatches,
        },
        "safety_rejected_cells": {
            "qids": sorted(safety_rejected),
            "n": len(rejected_cells),
            "all_product_zero": all(c["product_zero"] for c in rejected_cells),
            "nonzero": [c for c in rejected_cells if not c["product_zero"]],
        },
        "findability_vs_packet_text": {
            "queries": findability,
            "median_found_frac": fracs[len(fracs) // 2] if fracs else None,
            "mean_found_frac": round(sum(fracs) / len(fracs), 4) if fracs else None,
        },
    }
    dump(out, Path(args.out) / f"ocr-report-{doc_id}.json")
    print(
        f"[ocr] correctness {matched}/{len(cell_results)}; "
        f"findability mean {out['findability_vs_packet_text']['mean_found_frac']}; "
        f"confusable diffs {len(confusable_diffs)}"
    )


# ---------------------------------------------------------------------------
# Phase "freeze"
# ---------------------------------------------------------------------------


def phase_freeze(args):
    _bank, _vectors, _queries = load_bank()
    doc_id = args.doc
    run = load_run(Path(args.hits), doc_id)
    run2 = load_run(Path(args.hits), doc_id, run=2)
    cells2 = {(c["qid"], c["vector_id"]): c for c in run2["cells"]}
    adjudication = (
        json.loads(Path(args.adjudication).read_text()) if args.adjudication else {"rows": []}
    )
    adj_by_key = {}
    for row in adjudication["rows"]:
        if row.get("doc") in (doc_id, "*"):
            adj_by_key[(row["qid"], row.get("vector_id", "*"))] = row

    def is_burst(cell):
        pages = Counter(h["page"] for h in cell["hits"])
        return bool(pages) and max(pages.values()) > 100

    ocr_leg = any(s != "rich" for s in run["text_layer_status"])
    cells_out = {}
    burst_max_cells = []
    unadjudicated_nondet = []
    for cell in run["cells"]:
        key = f"{cell['qid']}|{cell['vector_id']}"
        adj = adj_by_key.get((cell["qid"], cell["vector_id"])) or adj_by_key.get((cell["qid"], "*"))
        source_note = None
        c2 = cells2.get((cell["qid"], cell["vector_id"]))
        # Cross-run reconciliation. Text leg: a run difference is legal only
        # on burst cells (the bufferingNewest drop) — freeze the higher-yield
        # run (drops only LOSE hits; max-of-runs is a lower bound on truth).
        # OCR leg: run 2 is an independent Vision pass — variance expected;
        # GT regenerates from run 1 by definition.
        cell_row = cell
        if not ocr_leg and c2 is not None and cell["hits"] != c2["hits"]:
            if is_burst(cell) or is_burst(c2):
                if c2["yielded"] > cell["yielded"]:
                    cell_row = c2
                burst_max_cells.append(key)
                source_note = "burst-max-of-runs"
            elif not adj:
                unadjudicated_nondet.append(key)
        expected_hits = [
            {
                "page": h["page"],
                "start": h.get("start"),
                "end": h.get("end"),
                "text": h["text"],
                "bbox": h["rect"],
            }
            for h in cell_row["hits"]
        ]
        entry = {
            "expected_n": len(expected_hits),
            "hits": expected_hits,
            "source": source_note or ("regenerated-ocr" if ocr_leg else "adjudicated-product"),
        }
        if adj:
            entry["adjudication"] = {
                "decision": adj["decision"],
                "rationale": adj["rationale"],
            }
            for k in ("f12", "c12"):
                if adj.get(k):
                    entry["adjudication"][k] = adj[k]
        cells_out[key] = entry
    if unadjudicated_nondet:
        sys.exit(
            f"[freeze] REFUSED: non-burst cross-run differences need "
            f"adjudication: {unadjudicated_nondet}"
        )
    out = {
        "schema_version": 1,
        "generated_by": "search_oracle.py freeze",
        "doc_id": doc_id,
        "doc_sha256": run["doc_sha256"],
        "queries_sha256": run["queries_sha256"],
        "leg": "ocr" if ocr_leg else "text",
        "regenerated": ocr_leg,
        "source_run_index": run["run_index"],
        "burst_max_cells": burst_max_cells,
        "cells": cells_out,
    }
    dump(out, GT_DIR / f"{doc_id}.search-gt.json")
    print(
        f"[freeze] {doc_id}: {len(cells_out)} cells frozen "
        f"({'OCR-regenerated' if ocr_leg else 'adjudicated text leg'}; "
        f"{len(adj_by_key)} adjudication rows; "
        f"{len(burst_max_cells)} burst-max cells)"
    )


# ---------------------------------------------------------------------------
# Phase "score" (M12-13)
# ---------------------------------------------------------------------------


def phase_score(args):
    _bank, _vectors, queries = load_bank()
    rows = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0, "cells": 0, "exact_cells": 0})
    for doc_id in args.docs.split(","):
        gt = json.loads((GT_DIR / f"{doc_id}.search-gt.json").read_text())
        run = load_run(Path(args.hits), doc_id, run=int(args.run))
        leg = gt["leg"]
        for cell in run["cells"]:
            key = f"{cell['qid']}|{cell['vector_id']}"
            want = Counter((h["page"], h["text"]) for h in gt["cells"][key]["hits"])
            got = Counter((h["page"], h["text"]) for h in cell["hits"])
            tp = sum((want & got).values())
            fp = sum((got - want).values())
            fn = sum((want - got).values())
            k = (leg, queries[cell["qid"]]["mode"], cell["vector_id"])
            rows[k]["tp"] += tp
            rows[k]["fp"] += fp
            rows[k]["fn"] += fn
            rows[k]["cells"] += 1
            rows[k]["exact_cells"] += 1 if (fp == 0 and fn == 0) else 0
    table = []
    for (leg, mode, vid), r in sorted(rows.items()):
        p = r["tp"] / (r["tp"] + r["fp"]) if r["tp"] + r["fp"] else 1.0
        rec = r["tp"] / (r["tp"] + r["fn"]) if r["tp"] + r["fn"] else 1.0
        table.append(
            {
                "leg": leg,
                "mode": mode,
                "vector_id": vid,
                "tp": r["tp"],
                "fp": r["fp"],
                "fn": r["fn"],
                "precision": round(p, 6),
                "recall": round(rec, 6),
                "cells": r["cells"],
                "exact_cells": r["exact_cells"],
            }
        )
    out = {
        "schema_version": 1,
        "generated_by": "search_oracle.py score",
        "run_index": int(args.run),
        "rows": table,
    }
    dump(out, Path(args.out) / "score.json")
    imperfect = [t for t in table if t["precision"] < 1 or t["recall"] < 1]
    print(f"[score] {len(table)} (leg,mode,vector) rows; {len(imperfect)} below 1.0")


# ---------------------------------------------------------------------------


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="phase", required=True)

    p = sub.add_parser("expect")
    p.add_argument("--doc", required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(fn=phase_expect)

    p = sub.add_parser("diff")
    p.add_argument("--doc", required=True)
    p.add_argument("--hits", required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(fn=phase_diff)

    p = sub.add_parser("metamorphic")
    p.add_argument("--docs", required=True, help="comma list")
    p.add_argument("--hits", required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(fn=phase_metamorphic)

    p = sub.add_parser("ocr")
    p.add_argument("--doc", required=True)
    p.add_argument("--hits", required=True)
    p.add_argument("--out", required=True)
    p.add_argument(
        "--safety-rejected",
        default=None,
        help="comma qids the product safety-rejects (graded as product-zero rows)",
    )
    p.set_defaults(fn=phase_ocr)

    p = sub.add_parser("freeze")
    p.add_argument("--doc", required=True)
    p.add_argument("--hits", required=True)
    p.add_argument("--adjudication", default=None)
    p.set_defaults(fn=phase_freeze)

    p = sub.add_parser("score")
    p.add_argument("--docs", required=True)
    p.add_argument("--hits", required=True)
    p.add_argument("--run", default="1")
    p.add_argument("--out", required=True)
    p.set_defaults(fn=phase_score)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
