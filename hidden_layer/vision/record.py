"""Record Apple Vision's reading of the Vision-set page pictures (macOS only).

    swiftc -O -o hidden_layer/vision/vision_words hidden_layer/vision/vision_words.swift
    .venv/bin/python -I hidden_layer/vision/record.py [--only id,id]

For each Vision-set document this renders its page picture (the same JPEG the PDF embeds), runs
``vision_words`` on it, and writes ``hidden_layer/vision/<id>.vision.json``: the macOS version and
request revision, the picture's SHA-256, and Vision's observations. The build reads these files and
never runs Vision itself, so the PDFs rebuild on any platform. A new recording is a new input: its
documents' checksums change with it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from hidden_layer import grid, pages

HERE = Path(__file__).resolve().parent
HELPER = HERE / "vision_words"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    only = {x for x in a.only.split(",") if x}
    specs = [s for s in grid.all_specs() if s.layer == "vision" and (not only or s.doc_id in only)]
    if not HELPER.exists():
        sys.stderr.write(
            f"build the helper first: swiftc -O -o {HELPER} {HERE / 'vision_words.swift'}\n"
        )
        return 2
    with tempfile.TemporaryDirectory() as td:
        shas = {}
        paths = []
        for spec in specs:
            _, jpg = pages.render(
                spec.layout, spec.ground, spec.dpi, pages.DEGRADES[spec.degrade], spec.seed
            )
            p = Path(td) / f"{spec.doc_id}.jpg"
            p.write_bytes(jpg)
            shas[spec.doc_id] = hashlib.sha256(jpg).hexdigest()
            paths.append(str(p))
        run = subprocess.run([str(HELPER), *paths], capture_output=True, text=True, check=False)  # noqa: S603
        if run.returncode != 0:
            sys.stderr.write(run.stderr)
            return 1
        out = json.loads(run.stdout)
    header = {k: v for k, v in out.items() if k != "images"}
    for spec, image in zip(specs, out["images"], strict=True):
        rec = {
            **header,
            "document": spec.doc_id,
            "image_sha256": shas[spec.doc_id],
            "width": image["width"],
            "height": image["height"],
            "observations": image["observations"],
        }
        (HERE / f"{spec.doc_id}.vision.json").write_text(
            json.dumps(rec, indent=1, sort_keys=True) + "\n", encoding="ascii"
        )
        n = sum(len(o["words"]) for o in image["observations"])
        sys.stdout.write(f"{spec.doc_id}: {len(image['observations'])} observations, {n} words\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
