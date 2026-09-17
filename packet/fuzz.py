"""fuzz.py -- T4.3 mutated set v0 (P1.7): the DOCS_ROOT adapter for the dp fixture set.

The fixtures themselves are built in resecta-datapipeline (`resecta-data build fuzz
pdf-mutations --packet packet.pdf`), which damages this repo's canonical packet four ways --
byte_flip (one inverted bit, stratified across signature / version / body / xref table /
trailer) · truncation (an even ladder of short cuts) · xref_damage (startxref offset, an
entry offset, or the xref keyword) · bad_length (a misstated stream length). Three of the
four families are length preserving, so a fixture differs from the packet in a handful of
bytes and nothing downstream shifts.

This module does no mutation of its own. It mirrors that build into `robustness/fuzz/` and
writes the sidecar H4.2 reads, translating the dp manifest into the runner's row shape:

  expected.import        the generator's STRUCTURAL PRIOR, carried through verbatim. It is
                         what the damaged layout implies, not ground truth -- H4.2 measures
                         the real outcome and a disagreement is a result to adjudicate.
  expected.import_error  "corrupt" for every reject: the import mirror's only reachable
                         class for byte-level damage (the page-count, dimension and password
                         gates all sit behind a successful open).
  expected.redact        v0 runs import+scan only, so "skip_v0" where import is expected to
                         open and "skip" where it is expected to reject -- the sibling
                         convention in robustness-fixtures.json.

Sidecar: robustness/robustness-fuzz.json, read by RobustnessRunnerTests.fuzzFixtures via
RESECTA_DOCS_ROOT. Deliberately a SECOND file rather than rows appended to
robustness-fixtures.json: that manifest is regenerated wholesale by packet/robustness.py,
which would silently drop rows it does not own. documents.manifest.json is untouched
(T1.4 stays byte-stable -- the PB-86 DOCS_ROOT-direct precedent).

Run with: .venv/bin/python -m packet.fuzz [<dp build/fuzz dir>]
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUTDIR = REPO / "robustness" / "fuzz"
SIDECAR = REPO / "robustness" / "robustness-fuzz.json"

# Where the dp build lands. Overridable by argv[1] or RESECTA_DP_FUZZ so the adapter does not
# hard-depend on one worktree name.
DEFAULT_SRC = REPO.parent / "resecta-datapipeline-1.2" / "build" / "fuzz"

# The import mirror reaches passwordProtected / tooLarge / invalidPageDimensions only after a
# successful open, so byte-level damage that rejects can only land here.
_REJECT_CLASS = "corrupt"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _resolve_src(argv: list[str]) -> Path:
    if len(argv) > 1:
        return Path(argv[1]).expanduser().resolve()
    env = os.environ.get("RESECTA_DP_FUZZ")
    if env:
        return Path(env).expanduser().resolve()
    return DEFAULT_SRC


def build_fuzz_set(src: Path, *, write: bool = True) -> dict:
    """Mirror the dp fixture set into robustness/fuzz/ and build the sidecar.

    Verifies that the set was derived from THIS repo's packet.pdf before writing anything --
    a stale dp build against a different base would otherwise land silently.
    """
    manifest_path = src / "pdf_mutations.json"
    if not manifest_path.is_file():
        raise SystemExit(
            f"dp manifest not found: {manifest_path}\n"
            "Build it first:  resecta-data build fuzz pdf-mutations "
            "--build-dir build --packet <this repo>/packet.pdf"
        )
    dp = json.loads(manifest_path.read_text(encoding="utf-8"))

    packet_sha = _sha256((REPO / "packet.pdf").read_bytes())
    if dp["base_sha256"] != packet_sha:
        raise SystemExit(
            "dp fixture set was built from a different base document.\n"
            f"  manifest base_sha256: {dp['base_sha256']}\n"
            f"  this repo's packet:   {packet_sha}\n"
            "Rebuild the dp set against this packet.pdf before mirroring."
        )

    blobs: dict[str, bytes] = {}
    rows: list[dict] = []
    for m in dp["mutations"]:
        data = (src / m["path"]).read_bytes()
        if _sha256(data) != m["sha256"]:
            raise SystemExit(f"{m['path']}: bytes do not match the manifest sha256")
        rel = f"robustness/fuzz/{m['id']}.pdf"
        blobs[rel] = data
        rejects = m["expected"] == "reject"
        rows.append(
            {
                "id": m["id"],
                "path": rel,
                "kind": m["kind"],
                "pages": None if rejects else 12,
                "gt": None,
                "expected": {
                    "import": m["expected"],
                    "import_error": _REJECT_CLASS if rejects else None,
                    "scan": not rejects,
                    "redact": "skip" if rejects else "skip_v0",
                    "redact_error": None,
                },
                "notes": m["notes"],
                "sha256": m["sha256"],
            }
        )

    manifest = {
        "schema_version": 1,
        "generator": "packet/fuzz.py (T4.3 adapter, P1.7)",
        "source": {
            "builder": dp["generated_by"],
            "seed": dp["seed"],
            "base_sha256": dp["base_sha256"],
            "base_bytes": dp["base_bytes"],
        },
        "taxonomy": (
            "engine PipelineError.ImportFailure case names. expected.import is the "
            "generator's structural prior, not ground truth -- H4.2 measures the real "
            "outcome and divergence is a result, not a harness defect."
        ),
        "fixtures": rows,
    }

    if write:
        OUTDIR.mkdir(parents=True, exist_ok=True)
        for rel, data in blobs.items():
            (REPO / rel).write_bytes(data)
        SIDECAR.write_text(json.dumps(manifest, indent=2) + "\n", encoding="ascii")
    return {"blobs": blobs, "manifest": manifest}


def main() -> None:
    src = _resolve_src(sys.argv)
    out = build_fuzz_set(src)
    rows = out["manifest"]["fixtures"]
    by_kind: dict[str, int] = {}
    for r in rows:
        by_kind[r["kind"]] = by_kind.get(r["kind"], 0) + 1
    opens = sum(1 for r in rows if r["expected"]["import"] == "open")
    print(f"source: {src}")
    print(f"mirrored {len(rows)} fixtures -> {OUTDIR}")
    for kind in sorted(by_kind):
        print(f"  {kind:14s} {by_kind[kind]:>3d}")
    print(f"priors: {opens} open / {len(rows) - opens} reject")
    print(f"-> {SIDECAR}")


if __name__ == "__main__":
    main()
