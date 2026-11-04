"""seeded_bases.py -- base specs for the seeded-leak replay runner.

A base is one (source PDF, mode, boxes) triple. The engine-side replay runner
(`SeededLeakReplayTests`, RedactionEngine tests) redacts each base and writes
its output plus a record of every verification input; `seeded_plant.py` then
plants one fault per row into copies of that output.

Boxes come from one of three locators, none of which uses the app's own
search:
  gt    -- the document's ground-truth file (`occurrences`, must_fire rows,
           normalized [x0, y0, x1, y1] bottom-left), optionally limited to pages;
  text  -- PyMuPDF `search_for` over the text layer, every occurrence of each
           needle on every page;
  ocr   -- Tesseract word boxes on a pdftoppm render, for image-only pages.

Config (JSON):
  {"bases": [{"id": "b01-statement", "source": "/abs/file.pdf",
              "modes": ["secureRasterization", "searchableRedaction"],
              "locate": "text", "needles": ["..."], "category": "custom",
              "gt": "/abs/gt.json", "gt_pages": [0, 1, 2], "pad_pt": 0.75}]}

Usage: .venv/bin/python -I tools/seeded_bases.py --config CFG --out DIR
Writes DIR/<id>-<s|h>/base.json and DIR/bases-index.json.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pymupdf

EDGE = ".,;:()[]\"'"
MODE_TAG = {"secureRasterization": "s", "searchableRedaction": "h"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def norm_rect(page: pymupdf.Page, r: pymupdf.Rect, pad: float) -> list[float]:
    """PyMuPDF top-left points -> normalized [x, y, w, h], bottom-left."""
    box = page.rect
    w, h = box.width, box.height
    x0, y0, x1, y1 = r.x0 - pad, r.y0 - pad, r.x1 + pad, r.y1 + pad
    x0, y0 = max(x0, 0.0), max(y0, 0.0)
    x1, y1 = min(x1, w), min(y1, h)
    return [
        round(x0 / w, 6),
        round((h - y1) / h, 6),
        round((x1 - x0) / w, 6),
        round((y1 - y0) / h, 6),
    ]


def locate_text(src: Path, needles: list[str], category: str, pad: float) -> list[dict]:
    regions: list[dict] = []
    doc = pymupdf.open(src)
    for pno in range(doc.page_count):
        page = doc[pno]
        for needle in needles:
            for r in page.search_for(needle):
                regions.append(
                    {
                        "page": pno,
                        "rect": norm_rect(page, r, pad),
                        "value": needle,
                        "category": category,
                    }
                )
    return regions


def locate_gt(gt_path: Path, pages: list[int] | None, category_map: dict | None) -> list[dict]:
    gt = json.loads(gt_path.read_text())
    regions: list[dict] = []
    for occ in gt["occurrences"]:
        if occ.get("expectation") != "must_fire":
            continue
        spans = occ.get("spans") or (
            [{"page": occ.get("page"), "bbox": occ.get("bbox")}] if occ.get("bbox") else []
        )
        for sp in spans:
            if sp.get("bbox") is None or sp.get("page") is None:
                continue
            if pages is not None and sp["page"] not in pages:
                continue
            x0, y0, x1, y1 = sp["bbox"]
            cat = occ["category"]
            regions.append(
                {
                    "page": sp["page"],
                    "rect": [round(x0, 6), round(y0, 6), round(x1 - x0, 6), round(y1 - y0, 6)],
                    "value": occ["value"],
                    "category": (category_map or {}).get(cat, cat),
                }
            )
    return regions


def locate_ocr(
    src: Path, needles: list[str], category: str, pad: float, dpi: int = 300
) -> list[dict]:
    regions: list[dict] = []
    doc = pymupdf.open(src)
    with tempfile.TemporaryDirectory() as td:
        for pno in range(doc.page_count):
            page = doc[pno]
            stem = Path(td) / f"p{pno}"
            subprocess.run(
                [
                    "pdftoppm",
                    "-r",
                    str(dpi),
                    "-f",
                    str(pno + 1),
                    "-l",
                    str(pno + 1),
                    "-singlefile",
                    "-png",
                    str(src),
                    str(stem),
                ],
                check=True,
            )
            tsv = subprocess.run(
                ["tesseract", f"{stem}.png", "stdout", "--psm", "6", "tsv"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout
            words = [
                row
                for row in csv.DictReader(io.StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE)
                if row.get("level") == "5" and row.get("text", "").strip()
            ]
            toks = [w["text"].strip().strip(EDGE) for w in words]
            scale = 72.0 / dpi
            for needle in needles:
                parts = [t.strip(EDGE) for t in needle.split()]
                for i in range(len(toks) - len(parts) + 1):
                    if toks[i : i + len(parts)] != parts:
                        continue
                    ws = words[i : i + len(parts)]
                    x0 = min(int(w["left"]) for w in ws) * scale
                    y0 = min(int(w["top"]) for w in ws) * scale
                    x1 = max(int(w["left"]) + int(w["width"]) for w in ws) * scale
                    y1 = max(int(w["top"]) + int(w["height"]) for w in ws) * scale
                    regions.append(
                        {
                            "page": pno,
                            "rect": norm_rect(page, pymupdf.Rect(x0, y0, x1, y1), pad),
                            "value": needle,
                            "category": category,
                        }
                    )
    return regions


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()
    cfg = json.loads(args.config.read_text())
    args.out.mkdir(parents=True, exist_ok=True)
    index = []
    for b in cfg["bases"]:
        src = Path(b["source"])
        pad = float(b.get("pad_pt", 0.75))
        cat = b.get("category", "custom")
        if b["locate"] == "gt":
            regions = locate_gt(Path(b["gt"]), b.get("gt_pages"), b.get("category_map"))
        elif b["locate"] == "text":
            regions = locate_text(src, b["needles"], cat, pad)
        elif b["locate"] == "ocr":
            regions = locate_ocr(src, b["needles"], cat, pad)
        else:
            sys.exit(f"unknown locator {b['locate']!r}")
        if not regions:
            sys.exit(f"{b['id']}: no regions located")
        found = sorted({r["value"] for r in regions})
        missing = sorted(set(b.get("needles", [])) - set(found))
        for mode in b["modes"]:
            base_id = f"{b['id']}-{MODE_TAG[mode]}"
            spec = {
                "schema": 1,
                "base_id": base_id,
                "source": str(src),
                "source_sha256": sha256(src),
                "mode": mode,
                "regions": regions,
                "password": None,
                "notes": b.get("notes", ""),
            }
            d = args.out / base_id
            d.mkdir(parents=True, exist_ok=True)
            (d / "base.json").write_text(json.dumps(spec, indent=1, sort_keys=True) + "\n")
            index.append(
                {
                    "base_id": base_id,
                    "regions": len(regions),
                    "values": found,
                    "needles_not_located": missing,
                }
            )
            print(f"{base_id}: {len(regions)} regions; not located: {missing or '-'}")
    (args.out / "bases-index.json").write_text(json.dumps(index, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
