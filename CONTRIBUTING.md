# Contributing to resecta-sample-doc

Thanks for your interest. This repository deterministically generates synthetic
test documents for the Resecta iOS redaction app — a PII-dense loan/mortgage
packet and a sample bank statement, each paired with labeled ground truth.

## Setup

Python 3.12 is required. The project is a [uv](https://docs.astral.sh/uv/)
project, but uv is optional — a standard virtualenv works.

```sh
uv sync                        # or: python -m venv .venv && pip install -e .
```

The core generator needs `reportlab` + `pypdf`; the test-only variants
additionally need `pymupdf` + `pillow`.

## Build and verify

```sh
python -m packet.build_packet   # -> packet.pdf + packet-ground-truth.json
python -m packet.acceptance     # structural acceptance + byte-determinism (exit 0 = green)
python verify.py                # bank-statement text/layout checks (needs pdftotext/poppler)
```

## Invariants

- **Synthetic only.** Every minted value is fictional and disclosed in the
  generator source; no real personal data, and no minted entity is ever promoted
  into a shipped gazetteer.
- **Byte-reproducible.** Re-running a generator on the same commit produces a
  byte-identical PDF (pinned `/ID`, fixed metadata, embedded font subset).
- **Printable ASCII.** Generated document text stays within printable ASCII.
- **Ground truth tracks the document.** When you change a drawn occurrence,
  update `packet-ground-truth.json` in the same commit.
- **Mechanism, not shorthand.** Source, docstrings and emitted strings describe
  what the code does; they never cite private planning notes, which a reader of
  this repository cannot resolve. The lint job reports a token in that shape (a
  short upper-case prefix, an optional hyphen, digits) on each line a change
  adds, as a warning; `Shorthand:ok <reason>` on the line exempts it.

## Commit format and sign-off

Describe the mechanism a change introduces, and sign off under the
[Developer Certificate of Origin 1.1](https://developercertificate.org/):

```sh
git commit -s -m "add <thing>"
```

## Security

Vulnerability disclosure goes through [`SECURITY.md`](./SECURITY.md), not the
public issue tracker.
