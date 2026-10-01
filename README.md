# resecta-sample-doc

[![ci](https://github.com/Merlin1A/resecta-sample-doc/actions/workflows/ci.yml/badge.svg)](https://github.com/Merlin1A/resecta-sample-doc/actions/workflows/ci.yml)

Deterministic generators for the synthetic test documents used by the
[Resecta](https://github.com/Merlin1A/resecta) on-device iOS redaction app.

Three documents are the primary outputs, all entirely synthetic:

- **A sample bank statement** (`sample-bank-statement.pdf`) — also shipped as the
  in-app sample document; the app repository's tests pin both of its copies to
  this file's SHA-256, and its commit hook checks that the two are
  byte-identical.
- **The Hartwell loan/mortgage packet** (`packet.pdf`) — a 12-page, PII-dense
  multi-exhibit document that serves as the primary labeled detection corpus; a
  copy is also bundled in the app.
- **The capture masters** (`capture-masters-2026-08.pdf`) — a 16-page print
  document for the test harness's capture and OCR evaluation legs: four pages
  imported from the packet plus twelve born-digital exhibits (mail and forms,
  court and FOIA, medical and HR), with its own ground truth and a
  fiducial-marks sidecar.

The repository also commits fixture sets for the app's test harness: `planted/`
(hand-built PDFs, one per place a value can sit outside the visible page —
hidden text, annotations, metadata, a prior revision, an embedded file — plus
clean controls), `t23/` (rotated, annotated and incrementally updated copies of
the packet), `robustness/` (oversized pages, page-count boundaries, encrypted
and byte-damaged copies of the packet) and the search ground truth described
below.

Four rules hold for the three documents:

- every person and organization is invented, identifiers are invented or taken
  from published test and reserved ranges, and every value is disclosed in the
  generator source;
- no invented entity is added to a gazetteer the app ships (a project rule;
  no automated check covers it);
- document text stays within printable ASCII;
- the outputs are byte-reproducible from a given commit and its locked
  dependency versions.

**License:** [Apache-2.0](./LICENSE). The bundled Inter font is under the SIL
Open Font License 1.1 — see [`NOTICE`](./NOTICE) and [`fonts/`](./fonts/).

## Install

Python 3.12, pinned by `.python-version` and CI (`pyproject.toml` allows newer;
only 3.12 is tested). [uv](https://docs.astral.sh/uv/) is the supported install
path:

```sh
uv sync
```

`uv sync` installs the generators' dependencies and the `dev` group (ruff, mypy,
pytest). The packet and statement generators use `reportlab` and `pypdf`; the
rasterized variants use `pymupdf`, `pillow` and `numpy`. Two tools,
`tools/register_capture.py` and `tools/verify_oracle.py`, also need the opt-in
`harness` group (`uv sync --group harness`) for OpenCV and pypdfium2.

Every pull request and every push to `main` runs two jobs
(`.github/workflows/ci.yml`). `build` checks the lockfile, rebuilds the packet
and compares `packet.pdf` and `packet-ground-truth.json` byte-for-byte with the
committed files, runs the acceptance suite, rebuilds and compares
`sample-bank-statement.pdf` the same way, then builds the variants. `lint` runs
`ruff check`, `ruff format --check`, `mypy` and `pytest`. The acceptance suite
byte-compares the capture-masters ground truth with the committed file, and the
variants step checks the rebuilt capture-masters PDF against a SHA-256 pinned in
`packet/build_capture.py`. The fixture sets under `planted/`, `t23/` and
`robustness/` are not rebuilt in CI.

## Build

```sh
# Core deliverables: packet.pdf + packet-ground-truth.json (deterministic)
uv run python -m packet.build_packet

# The bank-statement generator (byte-identical to the in-app sample)
uv run python generate_statement.py

# The capture masters + ground truth + marks sidecar (asserts packet.pdf is unchanged)
uv run python -m packet.build_capture

# Test-only variants + perf filler  (-> variants/, gitignored)
uv run python -m packet.variants

# Acceptance: structural checks + byte-determinism  (exit 0 = all green;
# it rebuilds the packet and capture files in place)
uv run python -m packet.acceptance
```

`uv run python verify.py` runs twelve checks on the bank statement (content,
fonts, arithmetic, metadata) and requires `pdftotext`/`pdffonts` (poppler).

## Packet layout

The packet is assembled in a fixed page order (0-indexed `pageIndex`):

```
0,1 URLA-B | 2 URLA-A | 3,4,5 statement (embedded) | 6,7 1040 | 8 ACH | 9 W-2 | 10 gov ID | 11 vehicle
```

```
packet/
  personas.py             the Hartwell household + org entities (single source of values)
  occurrences.py          every drawn occurrence as structured data
  manifest.py             draw-time bounding-box capture + ground-truth emit
  layout.py               geometry, fonts, palette, and form-furniture helpers
  schema.py               ground-truth schema validation
  build_packet.py         one-pass assembler -> packet.pdf + packet-ground-truth.json
  variants.py             scan-sim / rotate / the degrade ladder / perf filler (test-only),
                          and the fiducial stamping the capture masters use
  acceptance.py           structural acceptance suite + byte-determinism
  generators/             one module per packet exhibit (urla_a, urla_b, t1040, ach, w2,
                          govid, veh, stmt) and five for the capture exhibits (mail, forms,
                          court, medical, hr)
  build_capture.py        assembles the capture masters, their ground truth and marks sidecar
  occurrences_capture.py  the capture masters' drawn occurrences
  aruco.py                the marker table behind the capture fiducials
  pdfutil.py              a shared pypdf pass over the emitted PDFs
  t23.py                  the rotated / annotated / incremental-update fixtures (t23/)
  robustness.py           the scale, page-cap and encryption fixtures (robustness/)
  fuzz.py                 copies the pipeline's byte-damaged packets into robustness/fuzz/
```

## Ground truth

`packet-ground-truth.json` carries one record per drawn occurrence (the 106
`occurrences`), each with a normalized (0–1, bottom-left origin) bounding box
that compares directly against the engine's detection rectangles. The 20
records carried over from the embedded statement (`carried_stmt`) ship with
`bbox: null` and `measured_pending: true`: their geometry is not resolved, so
they are checked by count, not by rectangle.

Schema 2 adds three columns to every record. `context_class` names the
name-context shape a value is drawn in, from the same vocabulary the data
pipeline's synthetic text corpus uses (`caption_left`, `role_label`,
`title_label`, `closing_line`, `body_prose`, ... or `none`); every packet
record carries `none` (its names all sit under form-field labels), the capture
masters carry sixteen classed rows. `caption_clearance_pt` and `caption_text`
record the nearest furniture text above the value that overlaps it horizontally
and the vertical gap to it in points, measured from the draw geometry; a
negative clearance means the caption overprints the value.

The rasterized variants (`variants/`, built, never committed) narrow every
record to the OCR leg. The degrade-ladder rungs also add a `polygon` beside
each box: the skew rung's rotated quad, whose axis-aligned hull is the record's
`bbox`; every other rung inherits the master's geometry. The degrade ladder is
one declarative table (`packet/variants.py` `_RUNGS`) applied to both masters:
skew 1.5°, blur, low-DPI 100 and 75, JPEG quality 85 and 70, seeded noise,
duplex bleed-through, and fax at 204×98 and 204×196 DPI (1-bit). Every rung is
a pure function of the master's bytes and its recorded seed, so under the
locked dependency versions the outputs are byte-reproducible.

## Search ground truth

`search-ground-truth/` holds the frozen expectations for the app's search
feature on the packet and its scan-simulated variant: `search-queries.json`
(the query bank, generated by `tools/build_search_queries.py`) and one
`*.search-gt.json` sidecar per document, emitted by `tools/search_oracle.py`
from an official harness run plus the adjudication file. The sidecars change
only through a row in
[`REBASELINE-LOG.md`](./search-ground-truth/REBASELINE-LOG.md), which records
what changed, why, and its kind: the initial freeze, a bug fix, an intentional
rebaseline or a regenerated OCR leg.

## Build dependencies & licenses

These are build/development dependencies of the generators; none of them ship in
the Resecta iOS app, and none contribute code to the synthetic document outputs:

- fonttools (MIT), opentype-feature-freezer (Apache-2.0), pypdf (BSD),
  reportlab (BSD), pillow (MIT-CMU), numpy (BSD-3-Clause, with bundled
  components under 0BSD, MIT, Zlib and CC0-1.0; the seeded noise rung of the
  degrade ladder).
- The `dev` group (ruff, mypy, pytest — MIT) and the opt-in `harness` group
  (opencv-python-headless — Apache-2.0; pypdfium2 — BSD-3-Clause / Apache-2.0;
  augraphy, albumentations, pdfplumber — MIT) are tooling only.
- PyMuPDF (pymupdf) — AGPL-3.0. Used at build time only: to rasterize the
  scan-simulation and degrade variants, to compose the oversized-page
  robustness fixtures, and as a text extractor in the acceptance suite and the
  search and verification tools. The AGPL copyleft applies to PyMuPDF and
  its derivative works; the synthetic documents this tool emits are data outputs,
  not a derivative of PyMuPDF's source, and the generator is not network-served.
  No AGPL obligation attaches to the generated documents or to this Apache-2.0
  repository.
