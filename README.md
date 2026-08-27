# resecta-sample-doc

[![ci](https://github.com/Merlin1A/resecta-sample-doc/actions/workflows/ci.yml/badge.svg)](https://github.com/Merlin1A/resecta-sample-doc/actions/workflows/ci.yml)

Deterministic generators for the synthetic test documents used by the
[Resecta](https://github.com/Merlin1A/resecta) on-device iOS redaction app.

Two documents are produced, both entirely synthetic:

- **A sample bank statement** (`sample-bank-statement.pdf`) — also shipped as an
  in-app sample document.
- **The Hartwell loan/mortgage packet** (`packet.pdf`) — a 12-page, PII-dense
  multi-exhibit document that serves as the primary labeled detection corpus and
  a second in-app sample.

Every value is fictional and disclosed in the generator source; no minted entity
is ever promoted into a shipped gazetteer, document text stays within printable
ASCII, and output is byte-reproducible from a given commit.

**License:** [Apache-2.0](./LICENSE). The bundled Inter font is under the SIL
Open Font License 1.1 — see [`NOTICE`](./NOTICE) and [`fonts/`](./fonts/).

## Install

Python 3.12. The project is a [uv](https://docs.astral.sh/uv/) project, but uv
is optional — a standard virtualenv works.

```sh
uv sync          # or: python -m venv .venv && pip install -e .
```

Every pull request rebuilds both documents on a hosted runner and checks
them byte-for-byte against the committed files.

The core generator needs `reportlab` + `pypdf`; the test-only variants
additionally need `pymupdf` + `pillow`.

## Build

```sh
# Core deliverables: packet.pdf + packet-ground-truth.json (deterministic)
python -m packet.build_packet

# The bank-statement generator (byte-identical to the in-app sample)
python generate_statement.py

# Test-only variants + perf filler  (-> variants/, gitignored)
python -m packet.variants

# Acceptance: structural checks + byte-determinism  (exit 0 = all green)
python -m packet.acceptance
```

`verify.py` runs additional text and layout checks on the bank statement and
requires `pdftotext`/`pdffonts` (poppler).

## Packet layout

The packet is assembled in a fixed page order (0-indexed `pageIndex`):

```
0,1 URLA-B | 2 URLA-A | 3,4,5 statement (embedded) | 6,7 1040 | 8 ACH | 9 W-2 | 10 gov ID | 11 vehicle
```

```
packet/
  personas.py        the Hartwell household + org entities (single source of values)
  occurrences.py     every drawn occurrence as structured data
  manifest.py        draw-time bounding-box capture + ground-truth emit
  layout.py          geometry, fonts, palette, and form-furniture helpers
  schema.py          ground-truth schema validation
  build_packet.py    one-pass assembler -> packet.pdf + packet-ground-truth.json
  variants.py        scan-sim / rotate / degrade / perf filler (test-only)
  acceptance.py      structural acceptance suite + byte-determinism
  generators/        one module per exhibit: urla_a, urla_b, t1040, ach, w2, govid, veh, stmt
```

## Ground truth

`packet-ground-truth.json` carries one record per drawn occurrence (the 106
`occurrences`), each with a normalized (0–1, bottom-left origin) bounding box
that compares directly against the engine's detection rectangles. The 20
records carried over from the embedded statement (`carried_stmt`) ship with
`bbox: null` and `measured_pending: true`: their geometry is not resolved, so
they are checked by count, not by rectangle. It is the labeled reference for
measuring detection precision and recall.

## License

Licensed under the Apache License, Version 2.0 — see [`LICENSE`](./LICENSE). The
bundled Inter typeface is under the SIL Open Font License 1.1; see
[`NOTICE`](./NOTICE).

## Build dependencies & licenses

These are build/development dependencies of the generators; none of them ship in
the Resecta iOS app, and none contribute code to the synthetic document outputs:

- fonttools (MIT), opentype-feature-freezer (Apache-2.0), pypdf (BSD),
  reportlab (BSD), pillow (HPND).
- PyMuPDF (pymupdf) — AGPL-3.0. Used only as a build-time rasterization tool for
  the scan-simulation packet variants. The AGPL copyleft applies to PyMuPDF and
  its derivative works; the synthetic documents this tool emits are data outputs,
  not a derivative of PyMuPDF's source, and the generator is not network-served.
  No AGPL obligation attaches to the generated documents or to this Apache-2.0
  repository.
