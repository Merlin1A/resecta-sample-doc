"""Recorded mutants: for every property kind, a document whose bytes and expected file disagree by one
unit or one fact, which ``verify_docs`` must report as a failed property.

    .venv/bin/python -I structure/mutants.py --built <a build directory> --out <empty dir> [--record f.json]

- each limit's file at the limit is checked against the expected file of the file one past it (the
  measured value differs by one unit);
- paired unusual and malformed documents are swapped the same way (rotation 180 for 90, 72 dpi for
  150, two revisions for five, a long /Length for a short one);
- every other kind has one recorded fact changed in its expected file;
- one manifest checksum is changed.

The run passes when every unmutated document is green and every mutant turns its own check red.
It reads an existing build, so the large local files are not built again.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hidden_layer.build import json_bytes
from structure import docs, verify_docs

SWAPS = {
    "st-unusual-rotate-90": "st-unusual-rotate-180",
    "st-unusual-scan-150dpi": "st-unusual-scan-72dpi",
    "st-unusual-incremental-5": "st-unusual-incremental-2",
    "st-malformed-length-short": "st-malformed-length-long",
}


def _perturb(facts: dict[str, Any]) -> dict[str, Any]:
    """One fact changed: the first boolean flipped, else the first number moved by one, else the
    first string or list altered."""
    f = copy.deepcopy(facts)
    for k, v in f.items():
        if isinstance(v, bool):
            f[k] = not v
            return f
    for k, v in f.items():
        if isinstance(v, int | float):
            f[k] = v + 1
            return f
    for k, v in f.items():
        if isinstance(v, str):
            f[k] = v + "x"
            return f
        if isinstance(v, list) and v:
            f[k] = v[:-1]
            return f
    raise ValueError("nothing to perturb")


def _check(
    out: Path, name: str, pdf: bytes, exp: dict[str, Any], tamper: bool = False
) -> dict[str, Any]:
    d = out / name
    (d / "documents").mkdir(parents=True)
    (d / "expected").mkdir()
    exp_b = json_bytes(exp)
    (d / "documents/x.pdf").write_bytes(pdf)
    (d / "expected/x.expected.json").write_bytes(exp_b)
    row = {
        "path": "documents/x.pdf",
        "bytes": len(pdf),
        "sha256": hashlib.sha256(pdf).hexdigest(),
        "expected": "expected/x.expected.json",
        "expected_sha256": hashlib.sha256(exp_b).hexdigest(),
        "stored": "committed",
    }
    (d / "SHA256SUMS").write_text(
        f"{row['sha256']}  {row['path']}\n{row['expected_sha256']}  {row['expected']}\n",
        encoding="ascii",
    )
    if tamper:
        row["sha256"] = "0" * 64
    res = verify_docs.check_one(d, row, verify_docs.read_sums(d / "SHA256SUMS"))
    shutil.rmtree(d)
    return {k: v["ok"] for k, v in res.checks.items()}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--built", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--record", type=Path)
    a = ap.parse_args()
    if a.out.exists() and any(a.out.iterdir()):
        sys.stderr.write(f"refusing to write into a non-empty directory: {a.out}\n")
        return 2

    def load(doc_id: str) -> tuple[bytes, dict[str, Any]]:
        pdf = (a.built / f"documents/{doc_id}.pdf").read_bytes()
        exp = json.loads((a.built / f"expected/{doc_id}.expected.json").read_text(encoding="ascii"))
        return pdf, exp

    rows = []
    ok = True
    all_docs = docs.docs()
    kinds_done: set[str] = set()
    for d in all_docs:
        pdf, exp = load(d.doc_id)
        kind = exp["kind"]
        if kind in kinds_done:
            continue
        kinds_done.add(kind)
        control = _check(a.out, f"control-{d.doc_id}", pdf, exp)
        green = all(v is not False for v in control.values())
        if d.group == "limit-at":
            other = d.doc_id.replace("-at", "-past")
            _, wrong = load(other)
            wrong = {**wrong, "bytes": exp["bytes"]}
            how = f"the file at the limit checked against the expected file of {other}"
        elif d.doc_id in SWAPS:
            _, wrong = load(SWAPS[d.doc_id])
            wrong = {**wrong, "bytes": exp["bytes"], "kind": kind}
            how = f"checked against the expected file of {SWAPS[d.doc_id]}"
        else:
            wrong = {**exp, "facts": _perturb(exp["facts"])}
            how = "one recorded fact changed"
        checks = _check(a.out, f"mutant-{d.doc_id}", pdf, wrong)
        killed = checks.get("property") is False
        ok = ok and green and killed
        rows.append(
            {
                "kind": kind,
                "document": d.doc_id,
                "control": "green" if green else "RED",
                "mutant": how,
                "outcome": "killed" if killed else "SURVIVED",
            }
        )
        sys.stdout.write(
            f"{'killed  ' if killed else 'SURVIVED'} {kind:22s} {d.doc_id} ({'control green' if green else 'CONTROL RED'})\n"
        )
    pdf, exp = load(all_docs[0].doc_id)
    checks = _check(a.out, "manifest-sha-changed", pdf, exp, tamper=True)
    killed = checks.get("checksums") is False
    ok = ok and killed
    rows.append(
        {
            "kind": "checksums",
            "document": all_docs[0].doc_id,
            "mutant": "the manifest's SHA-256 changed",
            "outcome": "killed" if killed else "SURVIVED",
        }
    )
    sys.stdout.write(
        f"{len(rows)} mutants; {'every control green, every mutant killed' if ok else 'a control is red or a mutant survived'}\n"
    )
    if a.record:
        a.record.write_bytes(json_bytes({"rows": rows}))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
