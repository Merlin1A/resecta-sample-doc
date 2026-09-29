# Contributing to resecta-sample-doc

Deterministic generators for the synthetic test documents of the Resecta iOS
app; what they produce is in [`README.md`](./README.md). Maintainer-run: issues
are welcome.

## Setup

Python 3.12 (pinned by `.python-version` and CI). `uv sync` installs every
dependency; `uv sync --group harness` adds the search-oracle tooling that
`tools/` and the full `pytest` run need. The dependency and licence list is in
the README.

## Checks a change must pass

`.github/workflows/ci.yml` is the source of truth. Its `build` job rebuilds the
documents and byte-compares `packet.pdf`, `packet-ground-truth.json` and
`sample-bank-statement.pdf` with the committed files, then runs
`python -m packet.acceptance` and `python -m packet.variants`; its `lint` job
runs `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy .`
and `uv run pytest -q`. Locally, run the same plus `python verify.py` (needs
poppler's `pdftotext` and `pdffonts`).

- A change to a drawn occurrence moves `packet-ground-truth.json` in the same
  commit; the byte-diff gate fails otherwise.
- The invariants (synthetic only, byte-reproducible, printable ASCII) are
  enforced by `packet.acceptance` and `verify.py`; their docstrings list the
  current checks.
- Source and docstrings describe mechanisms, never private planning notes. The
  `lint` job reports a token in the register-identifier shape on each added
  `.py` line (report-only); `Shorthand:ok <reason>` on the line exempts it.

## Sign-off and licence

Apache-2.0; the bundled Inter font is under the SIL OFL 1.1
(`fonts/NOTICE.md`). A DCO sign-off (`git commit -s`) is asked of external
contributions.

## Security

Vulnerability disclosure goes through [`SECURITY.md`](./SECURITY.md), not the
public issue tracker.
