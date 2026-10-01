# Contributing to resecta-sample-doc

Deterministic generators for the synthetic test documents of the Resecta iOS
app; what they produce is in [`README.md`](./README.md). Maintainer-run: issues
are welcome.

## Setup

Python 3.12 (pinned by `.python-version` and CI). `uv sync` installs the
generators' dependencies and the `dev` group; `uv sync --group harness` adds
OpenCV and pypdfium2 for `tools/register_capture.py`, `tools/verify_oracle.py`
and the tool-driven tests, which skip when their command-line tools are
absent. The dependency and licence list is in the README.

## Checks a change must pass

`.github/workflows/ci.yml` is the source of truth; both jobs run on every pull
request and every push to `main`. Its `build` job checks the lockfile
(`uv lock --check`), rebuilds the packet and byte-compares `packet.pdf` and
`packet-ground-truth.json` with the committed files, runs
`uv run python -m packet.acceptance`, rebuilds and byte-compares
`sample-bank-statement.pdf`, then runs `uv run python -m packet.variants`; its
`lint` job runs `uv run ruff check .`, `uv run ruff format --check .`,
`uv run mypy .` and `uv run pytest -q`. Locally, run the same plus
`uv run python verify.py` (needs poppler's `pdftotext` and `pdffonts`).

- A change to a drawn occurrence moves `packet-ground-truth.json` in the same
  commit; the byte-diff gate fails otherwise.
- The rules in the README (synthetic only, byte-reproducible, printable ASCII)
  are checked by `packet.acceptance`, by `verify.py` for the statement's
  content, and by the CI byte-diff steps; each script prints its check names
  when it runs.
- New source lines describe mechanisms, not private planning notes. The `lint`
  job reports a token in the register-identifier shape on each added `.py`
  line (report-only); `Shorthand:ok <reason>` on the line exempts it.

## Sign-off and licence

Apache-2.0; the bundled Inter font is under the SIL OFL 1.1
(`fonts/NOTICE.md`). A DCO sign-off (`git commit -s`) is asked of external
contributions.

## Security

Vulnerability disclosure goes through [`SECURITY.md`](./SECURITY.md), not the
public issue tracker.
