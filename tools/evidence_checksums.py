"""SHA256SUMS for an evidence run directory (stdlib): `write <dir>` hashes every file under it
(recursive, sorted relative paths, SHA256SUMS excluded); `verify <dir>` exits 1 on the first mismatch,
missing or unlisted file, else 0."""

from __future__ import annotations

import sys
from hashlib import sha256
from pathlib import Path

NAME = "SHA256SUMS"


def _files(root: Path) -> dict[str, Path]:
    return {
        p.relative_to(root).as_posix(): p for p in root.rglob("*") if p.is_file() and p.name != NAME
    }


def write(root: Path) -> int:
    files = _files(root)
    lines = [f"{sha256(files[r].read_bytes()).hexdigest()}  {r}" for r in sorted(files)]
    (root / NAME).write_text("\n".join(lines) + "\n", encoding="ascii")
    return print(f"wrote {root / NAME} ({len(lines)} files)") or 0


def verify(root: Path) -> int:
    listed = dict(line.split("  ", 1)[::-1] for line in (root / NAME).read_text().splitlines())
    files = _files(root)
    for rel in sorted(set(listed) | set(files)):
        state = "unlisted" if rel not in listed else "missing" if rel not in files else ""
        if state or sha256(files[rel].read_bytes()).hexdigest() != listed[rel]:
            return print(f"{root}: {state or 'mismatch'} {rel}") or 1
    return print(f"{root}: OK ({len(listed)} files)") or 0


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in ("write", "verify"):
        sys.exit(__doc__)
    sys.exit({"write": write, "verify": verify}[sys.argv[1]](Path(sys.argv[2]).resolve()))
