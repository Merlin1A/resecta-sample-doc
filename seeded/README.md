# Seeded leaks: what Resecta's verifier flags in a tampered output

This folder measures **the verifier, not the export.** Each row takes a real Resecta output, plants exactly one hidden copy of a redacted value in one PDF channel, and records what Resecta's verification report then says about that file.

Resecta's own export writes a fresh PDF: one raster image per page, plus, in Searchable mode, a text layer built from the text that survives. None of the channels below can come from that export. A row here shows whether the verifier would notice the value if something else had put it there.

## What is here

| path | what |
|---|---|
| `bases/<base>/base.json` | a base: a source document in this repository, a mode (`searchableRedaction` = Searchable, `secureRasterization` = Secure Rasterization), and the boxes, located without the app's own search |
| `emit/bases/<base>/` | Resecta's records of that base: `output.pdf` (the redacted output the rows are planted into; sample statement only), `replay.json` (every input the verifier received), `run.json` and `report.json` (its verdict on the unplanted output) |
| `expected/rows.json` | one entry per planted row: the class, the planted value and where it sits, the sha256 of the planted file, whether the independent oracle recovers the value from it (`leak: live`), and the verdict, per check |
| `known-blind-spots.txt` | the classes the verifier is known not to flag today (below), one `class/variant` per line |

The planted files themselves are not stored: the sample statement's rows alone come to ≈ 460 MB. To rebuild them byte for byte, run this from the repository root:

```
.venv/bin/python -I tools/seeded_plant.py --bases seeded/bases --emit seeded/emit --out <dir>
```

Each `<dir>/<row>/seeded.pdf` matches its `seeded_sha256`. The packet's outputs are 11 MB each, so for the packet only their records and hashes are here. Liveness comes from `tools/seeded_oracle.py` (text extractors, decompressed bytes, Tesseract, an adversarial byte search; no Apple framework decides it). `tools/seeded_score.py` turns verdicts into the measures below.

## How a row is read

- **flagged**: one of the verifier's own checks raises the confirmation Resecta shows before sharing, or the possible-items sweep counts more items than on the same output before the plant. The possible-items line alone is not counted: it appears on most clean outputs too.
- **Checks Passed**: the report's headline reads Checks Passed, so nothing tells the user to look.
- **live**: the oracle recovers the planted value from the planted file and not from the unplanted one. Only live rows count.

## Results (sample statement, both modes)

Measured 2026-11-03 with Resecta engine 5ef252fb on an iOS 26.4.1 simulator. Each row was run twice, with identical verdicts.

| class | channel | variant | live | flagged | Checks Passed |
|---|---|---|---|---|---|
| C-01 | control: the output, no plant | twin | 2/2 | 0 | 2 |
| C-02 | control: rewritten, no plant | roundtrip | 2/2 | 0 | 2 |
| O-01 | text left in the text layer inside a box | centre | 4/4 | 4 | 0 |
| O-01 | text left in the text layer inside a box | hex | 4/4 | 4 | 0 |
| O-01 | text left in the text layer inside a box | partial | 0/4 | 0 | 0 |
| O-01 | text left in the text layer inside a box | zero-width | 4/4 | 4 | 0 |
| O-02 | text on a raster page | invisible | 2/2 | 2 | 0 |
| O-02 | text on a raster page | off-crop | 2/2 | 0 | 2 |
| O-02 | text on a raster page | white | 2/2 | 2 | 0 |
| O-03 | an invisible OCR-like text layer | flate | 2/4 | 2 | 0 |
| O-03 | an invisible OCR-like text layer | plain | 2/4 | 2 | 0 |
| O-04 | text inside a form XObject | depth1 | 4/4 | 4 | 0 |
| O-04 | text inside a form XObject | depth2 | 4/4 | 4 | 0 |
| O-04 | text inside a form XObject | depth2-flate | 4/4 | 4 | 0 |
| O-05 | a font whose Unicode map lies | remap | 4/4 | 4 | 0 |
| O-06 | annotations | freetext | 4/4 | 4 | 0 |
| O-06 | annotations | square-contents | 4/4 | 4 | 0 |
| O-06 | annotations | text-contents | 4/4 | 4 | 0 |
| O-06 | annotations | widget-no-acroform | 4/4 | 4 | 0 |
| O-07 | form fields | value-only | 4/4 | 4 | 0 |
| O-07 | form fields | with-appearance | 4/4 | 4 | 0 |
| O-08 | metadata | info-custom | 4/4 | 4 | 0 |
| O-08 | metadata | info-producer | 4/4 | 4 | 0 |
| O-08 | metadata | info-title | 4/4 | 4 | 0 |
| O-08 | metadata | xmp-flate | 4/4 | 0 | 0 |
| O-08 | metadata | xmp-plain | 4/4 | 0 | 0 |
| O-09 | an earlier revision; an unreferenced object | dead-object | 4/4 | 0 | 4 |
| O-09 | an earlier revision; an unreferenced object | prior-revision | 4/4 | 4 | 0 |
| O-10 | inside a compressed content stream | actualtext | 4/4 | 0 | 4 |
| O-10 | inside a compressed content stream | content-comment | 4/4 | 0 | 4 |
| O-11 | raster residue at a box | alpha50 | 0/4 | 0 | 0 |
| O-11 | raster residue at a box | edge-residue | 0/4 | 0 | 0 |
| O-11 | raster residue at a box | offset | 0/4 | 0 | 0 |
| O-11 | raster residue at a box | unpainted | 2/4 | 2 | 0 |
| O-12 | an image the OCR check does not read | flate-image | 4/4 | 2 | 4 |
| O-13 | container keys | af-file | 4/4 | 0 | 4 |
| O-13 | container keys | pieceinfo | 4/4 | 4 | 0 |
| O-13 | container keys | thumb | 0/4 | 0 | 0 |
| O-14 | a page swapped for the source page | source-page | 4/4 | 4 | 0 |
| O-15 | the value elsewhere on the page | layer-casefold | 4/4 | 3 | 1 |
| O-15 | the value elsewhere on the page | layer-elsewhere | 4/4 | 4 | 0 |
| O-15 | the value elsewhere on the page | raster-elsewhere | 4/4 | 4 | 2 |

On the packet, the unplanted output already raises a confirmation (the OCR check on its scanned pages), so every row on it reads flagged and the packet does not separate one class from another. Its rows are listed in `expected/rows.json` for completeness.

## Known blind spots

In these classes some or all live rows read Checks Passed today (the counts are in the table above). Each is a verifier-only gap (the export never writes the channel), and each stays on this list until a verifier change flags it. The list only shrinks.

- `O-09/dead-object`: an earlier revision; an unreferenced object
- `O-10/actualtext`: inside a compressed content stream
- `O-10/content-comment`: inside a compressed content stream
- `O-02/off-crop`: text on a raster page
- `O-15/layer-casefold`: the value elsewhere on the page

These verdicts are planned to change in a coming verifier update: `O-08/xmp-plain` → FAILED, `O-08/xmp-flate` → FAILED, `O-13/af-file` → FAILED, `O-12/flate-image` → INCOMPLETE. When they do, `expected/rows.json` is updated in the same change.
