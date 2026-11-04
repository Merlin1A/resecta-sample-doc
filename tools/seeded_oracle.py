"""seeded_oracle.py -- is each seeded row's planted value recoverable, and by what?

The judge for the seeded-leak rows. It runs the calibrated legs of
`verify_oracle.py` (O1 text extractors, O2 decompressed bytes, O3 Tesseract,
O6 adversarial byte search; O0 structure for O2's inputs) over every row's
`seeded.pdf` AND over the clean twin it was seeded from (the base output), and
calls a row LIVE only when a leg finds the planted value in the seeded file
that the same leg does not find in the twin. A value that is legitimately
visible elsewhere in the twin therefore never counts.

Every deciding leg is a non-Apple tool. OCR runs on the planted value's page
only (the oracle's own render and Tesseract settings: pdftoppm 400 DPI gray,
PSM 6 union 11 union 12) and decides on Tesseract alone.

One leg is added here: PX, a pixel differential for rows whose value was
planted inside a burned box. It renders the box from the seeded file and the
twin (pdftoppm 150 DPI gray, 2 px inner erosion) and reports the share of
light pixels (> 128). PX is evidence that content is visible in the box, not
that the value is readable; the scorer keeps it apart from the reading legs.

Usage: .venv/bin/python -I tools/seeded_oracle.py --rows DIR --emit DIR --out DIR [--jobs 2]
Writes OUT/rows/<row_id>/oracle.json, OUT/twins/<base_id>/oracle.json, OUT/oracle-summary.json.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import multiprocessing
import sys
import tempfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import verify_oracle as vo

READING_LEGS = ("o1", "o2", "o3", "o6")
PX_DPI = 150
PX_LIGHT = 128
PX_ERODE = 2


def _ocr_pages(cell: vo.CalCell, pages: list[int], dpi: int, work: Path) -> dict[str, list[dict]]:
    """Tesseract hits (the oracle's own argv) on the listed 0-based pages only."""
    render = work / "render"
    render.mkdir(parents=True, exist_ok=True)
    ocr_files: dict[int, dict[str, Path | None]] = {}
    for p in sorted(set(pages)):
        vo.run(vo._fill(vo._argv_render_pp(dpi, p + 1), cell.output, render))
        png = vo._page_file(render, "pp", p + 1)
        if png is None:
            continue
        txt, tsv = vo.ocr_psm6_files(png, work / f"p{p}-psm6")
        files: dict[str, Path | None] = {"psm6_txt": txt, "psm6_tsv": tsv}
        for psm in ("11", "12"):
            rc, out, _err = vo.run_raw(vo._fill(vo._argv_ocr(psm), png, work), timeout=600)
            f = work / f"p{p}-psm{psm}.txt"
            f.write_bytes(out if rc == 0 else b"")
            files[f"psm{psm}"] = f
        ocr_files[p] = files
    tess = vo.o3_tesseract(cell, render, ocr_files)
    px_dims: dict[int, tuple[int, int]] = {}
    for p, d in tess.items():
        dims = vo.png_dims(render / d["png"])
        if dims:
            px_dims[p] = dims
    return vo.ocr_hits_for_engine(
        cell,
        {p: d["text"] for p, d in tess.items()},
        {p: d["words"] for p, d in tess.items()},
        px_dims,
    )


def _px_light(pdf: Path, page: int, rect: list[float]) -> float | None:
    """Share of light pixels inside the normalized box (bottom-left origin)."""
    from PIL import Image

    with tempfile.TemporaryDirectory() as td:
        stem = Path(td) / "px"
        rc, _out, _err = vo.run(
            [
                "pdftoppm",
                "-r",
                str(PX_DPI),
                "-gray",
                "-png",
                "-singlefile",
                "-f",
                str(page + 1),
                "-l",
                str(page + 1),
                str(pdf),
                str(stem),
            ]
        )
        png = Path(f"{stem}.png")
        if rc != 0 or not png.exists():
            return None
        img = Image.open(png).convert("L")
        w, h = img.size
        x, y, rw, rh = rect
        box = (
            round(x * w) + PX_ERODE,
            round((1 - y - rh) * h) + PX_ERODE,
            round((x + rw) * w) - PX_ERODE,
            round((1 - y) * h) - PX_ERODE,
        )
        if box[2] <= box[0] or box[3] <= box[1]:
            return None
        crop = img.crop(box)
        px = list(crop.getdata())
        return round(sum(1 for v in px if v > PX_LIGHT) / max(1, len(px)), 4)


def judge(spec: dict[str, Any]) -> dict[str, Any]:
    """One cell (a seeded row or a twin): which legs find which terms."""
    out_dir = Path(spec["out_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    cell = vo.CalCell(out_dir, Path(spec["pdf"]), spec["key"], list(spec["terms"]))
    scope = dict.fromkeys(cell.terms, "unique")
    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        o0 = vo.o0_structure(cell, work)
        o1_hits, _diag = vo.o1_text_layer(cell, scope)
        o2_hits = vo.o2_bytes(cell, o0, scope, work)
        o6_hits = vo.o6_adversarial(cell, scope)
        o3_hits = _ocr_pages(cell, spec["ocr_pages"], int(spec["dpi"]), work)
    found: dict[str, list[str]] = {leg: [] for leg in READING_LEGS}
    for leg, hits in (("o1", o1_hits), ("o2", o2_hits), ("o6", o6_hits)):
        found[leg] = sorted({h["term"] for h in hits if h.get("term")})
    found["o3"] = sorted(t for t, hs in o3_hits.items() if hs)
    px = {}
    for probe in spec.get("px", []):
        px[probe["key"]] = _px_light(Path(spec["pdf"]), probe["page"], probe["rect"])
    result = {
        "key": spec["key"],
        "pdf": spec["pdf"],
        "terms": cell.terms,
        "found": found,
        "px_light": px,
        "o2_corpora": sorted({c for h in o2_hits for c in h.get("corpora", [])}),
        "versions": spec["versions"],
    }
    (out_dir / "oracle.json").write_text(json.dumps(result, indent=1, sort_keys=True) + "\n")
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", required=True, type=Path)
    ap.add_argument("--emit", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--jobs", type=int, default=2)
    ap.add_argument("--dpi", type=int, default=400)
    args = ap.parse_args()
    versions = vo.tool_versions()
    rows = [json.loads(p.read_text()) for p in sorted(args.rows.glob("*/row.json"))]
    by_base: dict[str, list[dict]] = {}
    for r in rows:
        by_base.setdefault(r["base_id"], []).append(r)
    specs: list[dict[str, Any]] = []
    for base_id, all_rs in sorted(by_base.items()):
        rs = [r for r in all_rs if r.get("twin", True)]
        if not rs:
            continue
        terms = sorted({r["needle"]["text"] for r in rs})
        probes = [
            {
                "key": f"{r['needle']['page']}:{json.dumps(r['needle']['rect'])}",
                "page": r["needle"]["page"],
                "rect": r["needle"]["rect"],
            }
            for r in rs
            if r["needle"].get("in_box")
        ]
        uniq = {p["key"]: p for p in probes}
        specs.append(
            {
                "key": f"twin:{base_id}",
                "pdf": str(args.emit / "bases" / base_id / "output.pdf"),
                "out_dir": str(args.out / "twins" / base_id),
                "terms": terms,
                "ocr_pages": sorted({r["needle"]["page"] for r in rs}),
                "px": list(uniq.values()),
                "dpi": args.dpi,
                "versions": versions,
            }
        )
    for r in rows:
        n = r["needle"]
        specs.append(
            {
                "key": r["row_id"],
                "pdf": str(args.rows / r["row_id"] / "seeded.pdf"),
                "out_dir": str(args.out / "rows" / r["row_id"]),
                "terms": [n["text"]],
                "ocr_pages": [n["page"]],
                "px": (
                    [
                        {
                            "key": f"{n['page']}:{json.dumps(n['rect'])}",
                            "page": n["page"],
                            "rect": n["rect"],
                        }
                    ]
                    if n.get("in_box")
                    else []
                ),
                "dpi": args.dpi,
                "versions": versions,
            }
        )
    results: dict[str, dict] = {}
    ctx = multiprocessing.get_context("spawn")
    with concurrent.futures.ProcessPoolExecutor(
        max_workers=max(1, args.jobs), mp_context=ctx
    ) as pool:
        futs = {pool.submit(judge, s): s["key"] for s in specs}
        for i, fut in enumerate(concurrent.futures.as_completed(futs), 1):
            key = futs[fut]
            try:
                results[key] = fut.result()
            except Exception as e:  # one broken cell is recorded, never fatal to the run
                results[key] = {"key": key, "error": f"{type(e).__name__}: {e}"}
            print(f"[seeded-oracle] {i}/{len(specs)} {key}", flush=True)
    summary = []
    for r in rows:
        res = results.get(r["row_id"], {})
        twin = (
            results.get(f"twin:{r['base_id']}", {})
            if r.get("twin", True)
            else {"found": {leg: [] for leg in READING_LEGS}, "px_light": {}}
        )
        needle = r["needle"]["text"]
        if "error" in res or "error" in twin:
            summary.append(
                {
                    "row_id": r["row_id"],
                    "live": None,
                    "error": res.get("error") or twin.get("error"),
                }
            )
            continue
        legs_seeded = [leg for leg in READING_LEGS if needle in res["found"][leg]]
        legs_twin = [leg for leg in READING_LEGS if needle in twin["found"][leg]]
        live_legs = [leg for leg in legs_seeded if leg not in legs_twin]
        px_key = f"{r['needle']['page']}:{json.dumps(r['needle']['rect'])}"
        px_seeded = res["px_light"].get(px_key)
        px_twin = twin["px_light"].get(px_key)
        px_delta = (
            round(px_seeded - px_twin, 4) if px_seeded is not None and px_twin is not None else None
        )
        summary.append(
            {
                "row_id": r["row_id"],
                "live": bool(live_legs),
                "live_legs": live_legs,
                "legs_seeded": legs_seeded,
                "legs_twin": legs_twin,
                "px_light_seeded": px_seeded,
                "px_light_twin": px_twin,
                "px_delta": px_delta,
            }
        )
    (args.out / "oracle-summary.json").write_text(
        json.dumps({"schema": 1, "versions": versions, "rows": summary}, indent=1, sort_keys=True)
        + "\n"
    )
    live = sum(1 for s in summary if s.get("live"))
    print(f"[seeded-oracle] {len(summary)} rows; live by a reading leg: {live}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
