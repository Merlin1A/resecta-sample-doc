"""Build the structure family: every document, its expected file, ``manifest.json`` and
``SHA256SUMS``.

    .venv/bin/python -I structure/build.py --out <empty dir> [--only id,id] [--publish]
    .venv/bin/python -I structure/build.py --record-linearized   # writes recorded/ again (needs qpdf)

``--publish`` copies the expected files, the manifest, the checksums and every document marked
``committed`` into ``structure/``. The ``local`` ones (the 50 MiB, 100,000-object, 1,000,000-operator,
2,000-page and 64 MiB-inflate files) stay in ``--out``, rebuilt from this generator.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hidden_layer.build import json_bytes
from structure import docs

HERE = Path(__file__).resolve().parent
SCHEMA = 1

# The measured property of each document (structure/measure.py).
KIND: dict[str, str] = {
    "st-unusual-rotate-90": "rotate",
    "st-unusual-rotate-180": "rotate",
    "st-unusual-rotate-270": "rotate",
    "st-unusual-rotate-inherited": "rotate",
    "st-unusual-mixed-sizes": "media",
    "st-unusual-scan-150dpi": "scan",
    "st-unusual-scan-72dpi": "scan",
    "st-unusual-white-on-white": "white",
    "st-unusual-object-streams": "objstm",
    "st-unusual-incremental-2": "incremental",
    "st-unusual-incremental-5": "incremental",
    "st-unusual-linearized": "linearized",
    "st-unusual-pdf20": "header",
    "st-unusual-tagged": "tagged",
    "st-unusual-optional-content-off": "ocg",
    "st-unusual-annotation-kinds": "annots",
    "st-malformed-xref-offsets-lie": "xref-lies",
    "st-malformed-length-short": "length-lies",
    "st-malformed-length-long": "length-lies",
    "st-malformed-trailer-missing-object": "trailer-missing",
    "st-malformed-kids-cycle": "kids-cycle",
    "st-malformed-next-cycle": "next-cycle",
    "st-malformed-next-shared-chain": "shared-chain",
    "st-malformed-duplicate-object": "duplicate",
    "st-malformed-bytes-after-endstream": "after-endstream",
    "st-malformed-bytes-after-eof": "after-eof",
    "st-malformed-second-eof": "second-eof",
    "st-malformed-bounded-bomb": "bomb",
    "st-malformed-encrypted-empty-user": "encrypted",
    "st-malformed-active-elements": "active",
}


def kind_of(d: docs.Doc) -> str:
    return KIND.get(d.doc_id) or d.tags[0]


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def qpdf_check(data: bytes) -> int | None:
    """``qpdf --check``'s exit status (0 clean, 2 errors, 3 warnings), or None without qpdf."""
    exe = shutil.which("qpdf")
    if not exe:
        return None
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "f.pdf"
        p.write_bytes(data)
        cmd = [exe, "--check", "--password=", str(p)]
        run = subprocess.run(cmd, capture_output=True, check=False)  # noqa: S603 - qpdf on PATH
        return run.returncode


def build_doc(d: docs.Doc) -> tuple[bytes, dict[str, Any]]:
    data, facts = d.make()
    return data, {
        "schema": SCHEMA,
        "id": d.doc_id,
        "family": "structure",
        "group": d.group,
        "kind": kind_of(d),
        "property": d.property,
        "facts": facts,
        "bytes": len(data),
        "qpdf_check_exit": qpdf_check(data),
    }


def build(out: Path, only: set[str] | None) -> list[dict[str, Any]]:
    (out / "documents").mkdir(parents=True, exist_ok=True)
    (out / "expected").mkdir(parents=True, exist_ok=True)
    rows = []
    for d in docs.docs():
        if only is not None and d.doc_id not in only:
            continue
        data, exp = build_doc(d)
        exp_b = json_bytes(exp)
        (out / f"documents/{d.doc_id}.pdf").write_bytes(data)
        (out / f"expected/{d.doc_id}.expected.json").write_bytes(exp_b)
        rows.append(
            {
                "path": f"documents/{d.doc_id}.pdf",
                "bytes": len(data),
                "sha256": sha256(data),
                "expected": f"expected/{d.doc_id}.expected.json",
                "expected_sha256": sha256(exp_b),
                "family": "structure",
                "group": d.group,
                "kind": kind_of(d),
                "property": d.property,
                "stored": d.stored,
                "writer": "pymupdf"
                if d.doc_id == "st-unusual-object-streams"
                else "qpdf (recorded)"
                if d.doc_id == "st-unusual-linearized"
                else "structure/pdfbytes.py",
            }
        )
        sys.stdout.write(f"{d.doc_id}  {len(data):>10,} bytes  {d.stored}\n")
    (out / "manifest.json").write_bytes(
        json_bytes({"schema": SCHEMA, "family": "structure", "documents": rows})
    )
    sums = [f"{r['sha256']}  {r['path']}" for r in rows] + [
        f"{r['expected_sha256']}  {r['expected']}" for r in rows
    ]
    (out / "SHA256SUMS").write_text("\n".join(sums) + "\n", encoding="ascii")
    return rows


def publish(out: Path, dest: Path) -> None:
    import json

    manifest = json.loads((out / "manifest.json").read_text(encoding="ascii"))
    for sub in ("documents", "expected"):
        if (dest / sub).exists():
            shutil.rmtree(dest / sub)
        (dest / sub).mkdir(parents=True)
    for row in manifest["documents"]:
        shutil.copyfile(out / row["expected"], dest / row["expected"])
        if row["stored"] == "committed":
            shutil.copyfile(out / row["path"], dest / row["path"])
    for name in ("manifest.json", "SHA256SUMS"):
        shutil.copyfile(out / name, dest / name)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=Path)
    ap.add_argument("--only", default="")
    ap.add_argument("--publish", action="store_true")
    ap.add_argument("--record-linearized", action="store_true")
    a = ap.parse_args()
    if a.record_linearized:
        sys.stdout.write(docs.record_linearized() + "\n")
        return 0
    if a.out is None:
        ap.error("--out is required")
    if a.out.exists() and any(a.out.iterdir()):
        sys.stderr.write(f"refusing to write into a non-empty directory: {a.out}\n")
        return 2
    only = {x for x in a.only.split(",") if x} or None
    build(a.out, only)
    if a.publish:
        publish(a.out, HERE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
