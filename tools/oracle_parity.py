"""oracle_parity.py — byte parity of oracle JSON records between two run directories.

  python tools/oracle_parity.py <ref-root> <new-root> [--glob GLOB]... [--exclude DOTTED.KEY]...

For every file a glob matches under <ref-root> (default: every `cells/*/*/*/oracle-partial.json`),
the same relative path must exist under <new-root>. Both files are loaded as JSON, exactly the
excluded dotted keys are deleted (each must be present on BOTH sides — an absent key is reported,
never ignored), both are re-serialised with sort_keys=True, indent=1 and compared byte for byte.
One line per file, a summary line, exit status 1 on any difference, missing file or missing key.

The oracle's volatile fields, by rule: `oracle-partial.json` / `calibrate-partial.json` carry two
run-local paths (`o0.qdf_path`, `o0.mu_clean_path`); records written before the tesseract stamp
fix carry `versions.tesseract` = "?"; the summaries carry nothing volatile.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def pop_dotted(obj: Any, dotted: str) -> bool:
    """Delete `a.b.c` from nested dicts; True when the key was present."""
    parts = dotted.split(".")
    node = obj
    for part in parts[:-1]:
        if not isinstance(node, dict) or part not in node:
            return False
        node = node[part]
    if not isinstance(node, dict) or parts[-1] not in node:
        return False
    del node[parts[-1]]
    return True


def differing_keys(a: Any, b: Any) -> list[str]:
    if isinstance(a, dict) and isinstance(b, dict):
        return sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))
    return ["<root>"]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("ref", type=Path)
    ap.add_argument("new", type=Path)
    ap.add_argument("--glob", action="append", default=[])
    ap.add_argument("--exclude", action="append", default=[])
    args = ap.parse_args()
    globs = args.glob or ["cells/*/*/*/oracle-partial.json"]
    counts = {"identical": 0, "different": 0, "missing": 0, "unexcludable": 0}
    for pattern in globs:
        for ref in sorted(args.ref.glob(pattern)):
            rel = ref.relative_to(args.ref)
            new = args.new / rel
            if not new.is_file():
                counts["missing"] += 1
                print(f"MISSING    {rel}")
                continue
            a = json.loads(ref.read_text())
            b = json.loads(new.read_text())
            absent = []
            for key in args.exclude:
                in_a = pop_dotted(a, key)
                in_b = pop_dotted(b, key)
                if not (in_a and in_b):
                    absent.append(key)
            if absent:
                counts["unexcludable"] += 1
                print(f"NO-KEY     {rel}: {absent}")
                continue
            sa = json.dumps(a, sort_keys=True, indent=1)
            sb = json.dumps(b, sort_keys=True, indent=1)
            if sa == sb:
                counts["identical"] += 1
                print(f"IDENTICAL  {rel}")
            else:
                counts["different"] += 1
                print(f"DIFFERENT  {rel}: {differing_keys(a, b)}")
    print(f"[parity] {json.dumps(counts)} excluded={args.exclude}")
    ok = counts["different"] == counts["missing"] == counts["unexcludable"] == 0
    ok = ok and counts["identical"] > 0
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
