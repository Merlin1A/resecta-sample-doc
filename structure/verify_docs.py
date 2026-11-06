"""Check every structure document against its expected file.

    .venv/bin/python -I structure/verify_docs.py <dir> [--only id,id] [--report out.json]

The properties (``CHECKS``):

- ``checksums``: the document and its expected file match ``manifest.json`` and ``SHA256SUMS``;
- ``size``: the file's size equals the recorded one;
- ``property``: the document's property, measured again from its bytes (``measure.py``: a byte walk,
  zlib and pypdf, not the code that wrote it), equals the recorded facts;
- ``qpdf``: where qpdf is installed, ``qpdf --check`` exits with the status recorded at build time.

Exit status 0 means every property of every checked document held; a ``local`` document absent from
the directory is reported as not checked.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hidden_layer.verify_docs import Result, read_sums
from structure import build, measure


def _norm(x: Any) -> Any:
    if isinstance(x, float):
        return round(x, 3)
    if isinstance(x, list | tuple):
        return [_norm(v) for v in x]
    if isinstance(x, dict):
        return {k: _norm(v) for k, v in x.items()}
    return x


def check_one(root: Path, row: dict[str, Any], sums: dict[str, str]) -> Result:
    doc_id = Path(row["path"]).stem
    r = Result(doc_id)
    exp_b = (root / row["expected"]).read_bytes()
    exp = json.loads(exp_b.decode("ascii"))
    pdf_path = root / row["path"]
    if not pdf_path.exists():
        r.record("present", None, f"stored {row['stored']}: not in this directory; not checked")
        return r
    data = pdf_path.read_bytes()
    sha, esha = hashlib.sha256(data).hexdigest(), hashlib.sha256(exp_b).hexdigest()
    ok = sha == row["sha256"] == sums.get(row["path"]) and esha == row[
        "expected_sha256"
    ] == sums.get(row["expected"])
    r.record("checksums", ok, f"pdf {sha[:12]}, expected {esha[:12]}")
    r.record("size", len(data) == exp["bytes"] == row["bytes"], f"{len(data):,} bytes")
    try:
        got = measure.measure(exp["kind"], data, exp["facts"])
    except Exception as e:
        r.record("property", False, f"could not measure: {type(e).__name__}: {e}")
    else:
        same = _norm(got) == _norm(exp["facts"])
        r.record(
            "property",
            same,
            f"{exp['property']}" + ("" if same else f"; measured {json.dumps(got)[:200]}"),
        )
    code = build.qpdf_check(data)
    if code is None or exp["qpdf_check_exit"] is None:
        r.record("qpdf", None, "qpdf not installed or not recorded")
    else:
        r.record(
            "qpdf",
            code == exp["qpdf_check_exit"],
            f"qpdf --check exit {code} (recorded {exp['qpdf_check_exit']})",
        )
    return r


CHECKS = ("checksums", "size", "property", "qpdf")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("root", type=Path)
    ap.add_argument("--only", default="")
    ap.add_argument("--report", type=Path)
    a = ap.parse_args()
    manifest = json.loads((a.root / "manifest.json").read_text(encoding="ascii"))
    sums = read_sums(a.root / "SHA256SUMS")
    only = {x for x in a.only.split(",") if x}
    results = []
    for row in manifest["documents"]:
        if only and Path(row["path"]).stem not in only:
            continue
        res = check_one(a.root, row, sums)
        results.append(res)
        sys.stdout.write(f"{'ok  ' if res.ok else 'FAIL'} {res.doc}\n")
        for name, c in res.checks.items():
            if c["ok"] is False or a.only:
                state = "ok" if c["ok"] else ("n/a" if c["ok"] is None else "FAIL")
                sys.stdout.write(f"     {name}: {state}  {c['detail']}\n")
    failed = [x.doc for x in results if not x.ok]
    checked = sum(1 for x in results if "present" not in x.checks)
    sys.stdout.write(
        f"{checked} checked, {len(results) - checked} not present, {len(failed)} failed\n"
    )
    if a.report:
        a.report.write_text(
            json.dumps([{"doc": x.doc, "ok": x.ok, "checks": x.checks} for x in results], indent=1)
            + "\n",
            encoding="ascii",
        )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
