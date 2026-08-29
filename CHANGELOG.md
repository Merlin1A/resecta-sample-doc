# Changelog

All notable changes to resecta-sample-doc are recorded in this file.

The format is based on [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning 2.0.0](https://semver.org/spec/v2.0.0.html).

## Unreleased

### Added

- GitHub Actions: a pull-request gate that rebuilds both documents and checks
  them byte-for-byte; `uv.lock` now pins `pymupdf`.

### Changed

- Documentation: shorter code of conduct; README/CONTRIBUTING/SECURITY trimmed and corrected.
- ruff and mypy configuration with a `lint` CI job; `EMPLOYER_NAME` is the
  single source of the employer literal; the packet ground truth's watch-tier
  note is person-neutral; the README states which records carry measured
  boxes.

## 0.1.0 — 2026-06-24

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
