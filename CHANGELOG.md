# Changelog

All notable changes to resecta-sample-doc are recorded in this file.

The format is based on [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning 2.0.0](https://semver.org/spec/v2.0.0.html).

## Unreleased

### Added

- The capture masters (`capture-masters-2026-08.pdf`, built by
  `packet/build_capture.py`) with their ground truth and fiducial-marks
  sidecar; the fixture sets under `planted/`, `t23/` and `robustness/`; the
  search ground truth (`search-ground-truth/`) and the oracle tools under
  `tools/`; a `tests/` suite and the opt-in `harness` dependency group.
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

- Documentation: shorter code of conduct; README/CONTRIBUTING/SECURITY trimmed and corrected.
- Documentation: the public documents re-checked line by line against the tree
  (the install groups, the CI steps, the capture-masters pin, the dependency
  licences, the fixture sets, the rebaseline log); the 0.1.0 date below is the
  date of the first public commit.
- ruff and mypy configuration with a `lint` CI job; `EMPLOYER_NAME` is the
  single source of the employer literal; the packet ground truth's watch-tier
  note is person-neutral; the README states which records carry measured
  boxes.

## 0.1.0 — 2026-07-11

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
