# Hidden-layer scan fixtures

Single-page PDFs that look like scans made searchable by text recognition: each page is one picture
of printed text, with an invisible text layer (render mode 3) on top. The layer's words are placed
by the generator at chosen offsets from their printed ink, so a test knows where each word's
hidden copy sits relative to its print. When the layer has drifted, a word's hidden copy lies
outside a box drawn tightly over its printed ink. Each document comes with an expected file that
records that geometry, together with named box scenarios.

Everything on these pages is synthetic: the values come from [`values.py`](values.py). Telephone
numbers are in the 555-0100 to 555-0199 block, e-mail addresses use RFC 2606 domains, the ZIP code
and state code are unassigned, the SSN area is 000, and the card number is a published test number.

## What is here

| path | what |
|---|---|
| `build.py` | the generator: builds every document, its expected file, `manifest.json`, `SHA256SUMS` and `accept-scenarios.json` |
| `verify_docs.py` | checks each document's properties from its bytes and a render (below) |
| `mutants.py` | the recorded mutants: one deliberate defect per property, each of which `verify_docs` must report |
| `pages.py`, `layer.py`, `grid.py`, `scenarios.py`, `geometry.py`, `rng.py`, `values.py` | the page renderer, the PDF writer, the parameter grid, the box scenarios, exact rectangle arithmetic, the seeded integer stream, the synthetic values |
| `documents/` | the documents under 1 MiB (the rest are rebuilt locally; see `manifest.json` `stored`) |
| `expected/<id>.expected.json` | one expected file per document, committed for every document |
| `manifest.json` | one row per document: path, size, SHA-256, parameters, producer and versions, purpose, `committed` or `local` |
| `SHA256SUMS` | the SHA-256 of every document and expected file, including the local ones |
| `accept-scenarios.json` | the (document, scenario) pairs in which every boxed word's hidden copy lies inside the boxes' rectangles |

## Build and check

From the repository root, in the locked environment:

```sh
uv run python hidden_layer/build.py --out /tmp/hl-a            # all documents
uv run python hidden_layer/build.py --out /tmp/hl-b
# the two directories are byte-identical; compare them with SHA256SUMS
uv run python hidden_layer/verify_docs.py /tmp/hl-a             # exit 0 = every property held
uv run python hidden_layer/verify_docs.py hidden_layer          # the committed subset only
uv run python hidden_layer/mutants.py --out /tmp/hl-mutants     # exit 0 = every mutant reported
uv run python hidden_layer/build.py --out /tmp/hl-c --publish   # refresh the committed files here
```

`--only id,id` limits a build or a check to some documents. The build writes no clock fields and
draws every random value from a SplitMix64 integer stream, so the output depends only on this
commit and the locked versions of Pillow, NumPy and reportlab (whose Helvetica metrics give the
layer's advances). `tests/test_hidden_layer.py` checks the committed documents and rebuilds the
smallest one, comparing its bytes.

## The page

- **Layouts:** a statement, a letter and an intake form (`pages.py`). Each carries the same six
  scenario lines in 13 pt type, for example "Contact Teodora Delgado about the file today." and
  "Signed by Lee on the date below.", which the box scenarios refer to.
- **Print:** the bundled Inter font, rendered into an 8-bit grey picture at 150, 200 or 300 dpi
  (612 x 792 pt). Each word's ink box is measured from its own coverage mask, in whole pixels.
- **Grounds:** `clean` (level 252); `light-noise` (228-252); `heavy-noise` (150-230); `textured`
  (a smooth 196-244 field plus fine noise); `dark` (28-48, with light text at 222); `black-bar`
  (clean, with a noisy bar at levels 4-44 painted over the four account digits on the "Account"
  line). Noise grain is 1/150 inch.
- **Degradation:** `none`; `mild` (0.4 degree skew, 0.5 px blur, JPEG quality 75); `rough` (1.0
  degree, 1.0 px, quality 55). `none` is JPEG quality 85. On a skewed page each ink box is the
  hull of the rotated rectangle, and `ink_polygon_pt` gives the rotated corners.
- **The PDF:** written directly by `layer.py`: the picture as `/Im1` (DCTDecode) drawn over the
  page, then one text object per hidden word in render mode 3, standard Helvetica (not embedded),
  stretched (`Tz`) so its advance equals the printed word's ink width.

## The hidden layer

A word's hidden copy starts at its ink box's left edge plus the along-line drift and per-word jitter.
Its baseline is the printed baseline plus the vertical shift and jitter. The parameters (centipoints,
`manifest.json` `params`):

| axis | documents | what varies |
|---|---|---|
| `a1` | 36 | the six grounds x along-line drift 0, 2, 5, 8, 15, 30 pt; 300 dpi; no degradation |
| `a2` | 16 | clean and heavy-noise x 150 / 200 / 300 dpi x none / mild / rough; drift 30 pt |
| `a3` | 14 | clean and heavy-noise at 300 dpi: per-word jitter up to 1.5 pt (drift 8); the layer 4 pt above the ink; 12 pt below and 15 pt along; the surname's hidden copy spelled "Delgaclo" (drift 0 and 8); split as "Del gado" (drift 8); a 30 pt drift to the left |

A set whose layer comes from Apple's Vision text recognition run on the same kind of pictures
follows in a later change.

## The expected file

All coordinates are PDF points with a bottom-left origin, except the `*_px` fields, which are
picture pixels with a top-left origin and exclusive right and bottom edges.

- `words[]`: `text` (the print), `ink_px` and `ink_pt` (the printed ink box), `baseline_pt`,
  `under_bar`, and `hidden[]`: each hidden piece's `text`, `box_pt` (from the origin to the end of
  its advance, and from the Helvetica descender to its ascender), `origin_pt`, `hscale_pct` and
  `glyph_x_pt` (each glyph's advance range). A split word has two pieces.
- `scenarios[]`: one entry per box scenario, with its `regions`. Each region has a `paint_pt`
  rectangle (the box) and a `strip_pt` rectangle (the hidden-copy box of the word it was placed
  from, for boxes placed from a search of the hidden layer; `null` otherwise). The facts recorded
  per scenario, all computed exactly from the recorded numbers:
  - `marked`: the words whose ink box has its centre inside some region's paint;
  - `must_be_absent`: those words' hidden strings;
  - `glyphs`: for each marked word, each hidden glyph's relation to the union of every paint and
    strip rectangle (`i` inside, `p` partial, `o` outside, by area);
  - `hidden_copies_covered`: true when every marked word's hidden glyphs have their centres inside
    that union; when it is false, `uncovered_glyphs` lists the glyphs whose centres lie outside it;
  - `unmarked_glyphs_meeting_rects`: hidden glyphs of unmarked words that share area with the union.

The scenarios (`scenarios.py`; boxes drawn by hand are the ink box grown by 1.5 pt):

| name | regions |
|---|---|
| `no-box` | none |
| `hand-box-surname` | a box by hand over "Delgado" |
| `hand-box-short-word` | a box by hand over "Lee" |
| `hand-box-first-word` | a box by hand over "Signed", the first word of its line |
| `hand-box-narrow-first-word` | a box by hand over "The", the first word of its line (`notes.ink_width_pt` gives its width) |
| `duplicate-moved` | a copy of the search box on "Delgado", moved onto "Hartigan"; no strip |
| `search-resized` | the search box on "Signed", its paint grown by hand over "by Lee"; the strip of "Signed" |
| `search-moved` | the search box on "Delgado", its paint moved onto "Okafor"; the strip of "Delgado" |
| `recognition-box-surname` | on misread documents only: a box over the printed "Delgado", whose hidden copy is spelled differently; no strip |
| `search-as-placed-surname`, `search-as-placed-short-word` | the search box on "Delgado" or "Lee", left as placed: paint and strip |
| `whole-page` | the whole page |
| `two-boxes-surname` | box A over the printed "Delgado" and box B over its hidden copy, both by hand |
| `bar-box` | on the black-bar ground only: a box over the bar |

`accept-scenarios.json` lists every (document, scenario) pair whose `hidden_copies_covered` is true.

## The checks

`verify_docs.py` reports each property per document, and any failed property is exit status 1:

| check | what it reads | what must hold |
|---|---|---|
| `checksums` | the files | SHA-256 and size equal `manifest.json` and `SHA256SUMS` |
| `structure` | the content stream (pypdf) | one 612 x 792 page; the first operation draws `/Im1` over the page; `/Im1` is the expected JPEG; every text show comes after it, in render mode 3 |
| `jpeg` | the JPEG | its quantization tables equal Pillow's at the stated quality; its size gives the stated dpi |
| `ground` | a PyMuPDF render | the left-margin strip's mean and spread fall inside the ground's class; the bar's inside is dark |
| `ink` | the render | each word's measured ink box is within `1 + 3 x blur` px of the expected box (inward also by the skew slack); words under the bar are skipped |
| `layer` | PyMuPDF's characters | each hidden piece reads back with the expected text, origin and glyph advances within 0.02 pt |
| `drift` | the layer and the render | each word's hidden left edge minus its measured ink left edge equals drift + jitter (recomputed from the seed); the median equals the drift; the hidden baseline equals the ink baseline plus the vertical shift, on words with no descender |
| `misread` | PyMuPDF's characters | the surname's hidden copy reads as the misread spelling, never as the printed one |
| `scenarios` | the expected file | every scenario recomputed from the recorded numbers equals the recorded one |

The ink is measured per word with a threshold halfway between the darkest pixel in its window and
the median of the ring around its expected box. Limits: blur is not measured on its own (it enters
through the ink tolerance), the hidden boxes' heights come from Helvetica's metrics rather than from
a reader, and the scenario facts are geometry over the recorded rectangles. They say nothing about
what any program does with them.

`mutants.py` builds `hl-a3-heavy-300-none-d8-misread-substitute` once clean and once per defect
(the drift written as zero, render mode 0, the JPEG quality changed, the ground swapped, one ink
box moved, one hidden letter changed, the misread dropped, one scenario fact emptied, one manifest
checksum changed). It passes when the clean build is green and each defect is reported by its own
check.

## Licences

The page pictures are drawn with the bundled Inter font (SIL Open Font License 1.1, see
[`../fonts/`](../fonts/)); no font is embedded in these PDFs. The documents are synthetic data
produced by this Apache-2.0 repository's code.
