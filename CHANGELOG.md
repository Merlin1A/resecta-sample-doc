# Changelog

All notable changes to resecta-sample-doc are recorded in this file.

The format is based on [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning 2.0.0](https://semver.org/spec/v2.0.0.html).

## Unreleased

### Added

- A grammar-faithful plant mode (`tools/seeded_plant.py --mode faithful`, or
  `both`): a planted row changes only what its class needs, in the grammar
  Resecta's writer uses: one content stream per page, the writer's own font
  on a Searchable page, the page JPEG re-encoded with its own tables,
  sampling, restart interval and APP segments, and one content-derived
  trailer `/ID`. The default (`legacy`) still rebuilds the published
  `seeded/` rows byte for byte.
  Text drawn into images uses the bundled Inter in faithful mode, so those
  plants run the same on every host; legacy keeps the font its rows were built
  with.
- Every planted row records its side effects (`tools/seeded_effects.py`): a
  structural diff against the base output, each change tagged inherent (the
  class needs it) or artefact (a mark of how it was planted). Two new controls
  per base: a page image re-encoded with nothing planted, and an empty
  operator group added to the page's content.
- `tools/seeded_score.py` compares the two modes (`fidelity` in its
  summary: flagged rows per mode, catches only the legacy planter's marks
  explain, and the routes' joint miss on faithful rows), and
  `--expected-from` chooses which mode's rows an expected table is written
  from.
- Seeded leaks (`seeded/`): what Resecta's verifier says about a real output
  with one hidden copy of a redacted value planted into one PDF channel. The base
  specs, Resecta's outputs and input records for the sample statement (the
  packet's as records and hashes), the expected verdict of every planted row,
  and the known blind spots. The planted files are rebuilt byte for byte by
  `tools/seeded_plant.py`.
- The seeded-leak tools: `tools/seeded_bases.py`, `seeded_plant.py`,
  `seeded_oracle.py` and `seeded_score.py`. The scorer can write an expected
  table from a baseline run and read a later run against it
  (`--write-expected`, `--gate`, `--prereg`).
- Seven planted-leak surfaces under `planted/` (an invisible text line over a
  raster page, a nested form XObject, compressed XMP, a ToUnicode remap, a Type
  3 font, a widget appearance without `/AcroForm`, an unreferenced compressed
  object) and a clean control. The oracle's decompressed-byte leg also inflates
  every zlib stream body in the file, whether or not the xref reaches it.
- The capture masters (`capture-masters-2026-08.pdf`, built by
  `packet/build_capture.py`) with their ground truth and fiducial-marks
  sidecar; the fixture sets under `planted/`, `t23/` and `robustness/`; the
  search ground truth (`search-ground-truth/`) and the tools under `tools/`;
  a `tests/` suite and the opt-in `harness` dependency group.
- Packet variants: the degrade ladder is a declarative rung table applied to
  both masters (the packet and the capture masters), with seven new rungs
  (low-DPI 75, JPEG quality 85 and 70, seeded noise, duplex bleed-through, fax
  204×98 and 204×196) beside the original three; the capture masters gain their
  own scan-sim base. Rung ground truth is polygon-primary (the skew rung's true
  rotated quad, the bbox as its hull). `numpy` joins the build dependencies.
- Ground-truth schema 2: every record carries `context_class` (the name-context
  vocabulary of the data pipeline's synthetic text corpus; sixteen capture rows
  are classed), and the
  caption clearance pair `caption_clearance_pt` / `caption_text` measured from
  the draw geometry. The committed ground-truth files are regenerated; no PDF
  byte changes.
- GitHub Actions: a gate on pull requests and pushes to `main` that rebuilds
  the packet (with its ground truth) and the statement and checks them
  byte-for-byte; `uv.lock` now pins `pymupdf`.

### Changed

- The capture masters are re-cut under pypdf 6.19.0, and their two pins and
  manifest rows follow.
- Search ground truth: the literal-as-regex row r02 is rebaselined on the
  case-insensitive vectors (rebaseline log row 7).
- Search ground truth: the scan-simulated twin (`packet-scan-sim-150dpi`) is
  re-frozen for the engine's confusable-character matching on scanned pages
  and its word-level boxes (rebaseline log row 8); the packet sidecar is
  unchanged.
- Search ground truth: the scan-simulated twin lists its regex matches in page
  order for r09 and r06 (rebaseline log row 9); order only, the scores and
  the packet sidecar unchanged.
- Dependencies: Dependabot moves to pypdf 6.21.2, pillow 13.0.0, fonttools
  4.67.0, numpy 2.5.4 and pypdfium2 5.14.0, and to the current setup-python
  and setup-uv actions.
- Security: a report-only pip-audit workflow over the locked set; Dependabot
  reads `uv.lock`; CI checkouts no longer persist the token.
- Documentation: shorter code of conduct; the public documents trimmed and
  re-checked against the tree; 0.1.0 is dated by the first public commit.
- ruff and mypy configuration with a `lint` CI job; `EMPLOYER_NAME` is the
  single source of the employer literal; the packet ground truth's watch-tier
  note is person-neutral; the README states which records carry measured
  boxes.

## 0.1.0 — 2026-07-11 (untagged)

Initial public release.

### Added

- **Synthetic bank-statement generator** (`generate_statement.py`,
  `statement_data.py`) producing a deterministic `sample-bank-statement.pdf`,
  also shipped as an in-app sample document.
- **Hartwell loan/mortgage packet** (`packet/`) — a 12-page, PII-dense
  multi-exhibit synthetic document (URLA, 1040, ACH, W-2, government ID, vehicle
  title, and the embedded statement) built on the same reportlab + pypdf
  pipeline, emitted with `packet-ground-truth.json` labeled ground truth.
- **Test-only variants** (`packet/variants.py`) — scan-simulation, rotation, and
  degradation ladders for detector testing.
- **Structural acceptance suite** (`packet/acceptance.py`) with byte-determinism
  checks.
