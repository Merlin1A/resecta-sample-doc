# Script and handwriting fixtures

Correct documents in non-Latin scripts and in synthetic handwriting:

- born-digital pages written by three real PDF writers;
- their scanned twins, with no text layer, with the page's own text layer placed over the picture,
  or with a layer from Apple's text recognition;
- three pages of synthetic handwriting.

Nothing in any of them is hidden or left over: every document is a clean input. Each one comes with
an expected file that records, line by line:

- what the page says, with a romanised gloss and its English meaning;
- where each word's ink sits;
- what the text layer decodes to.

Every line of text on these pages was written for this repository: short invented sentences, names
built from per-script syllable lists ([`texts.py`](texts.py)), and invented numbers. The
reserved-value rules of the other families hold: 555-01xx telephone numbers, RFC 2606 e-mail
domains, and invented account numbers.

## The documents (196)

| ids | count | what |
|---|---|---|
| `sh-born-<script>-prose` | 15 | a heading and six lines of prose: `zh-Hans`, `zh-Hant`, `ja`, `ja-vertical` (set in vertical columns), `ko`, `ar`, `he`, `hi` (Devanagari), `th`, `el`, `ru`, `vi`, `pl`, `is`, and `mixed` (Latin, Chinese and Arabic on the same lines) |
| `sh-born-<script>-form` | 13 | a form-like page: five label and value rows (name, telephone, account, date, e-mail) with a rule under each value; the same scripts without `ja-vertical` and `mixed` |
| `sh-scan-<script>-<layout>-<condition>-<layer>` | 156 | every born page as a picture: `clean` (300 dpi, JPEG quality 85) or `light` (200 dpi, seeded noise, a 0.4 px blur, quality 75, no skew); layer `none`, `placed` or `vision` |
| `sh-hand-<page>-<condition>-<layer>` | 12 | `note`, `form` and `letter`, `clean` or `light`, with no layer or a Vision layer |

The writers:
- macOS Core Text (`macos/ct_page.swift`) writes the prose pages in `zh-Hans`, `zh-Hant`, `ja`,
  `ja-vertical`, `ko`, `ar`, `he`, `hi`, `th` and `mixed`. These ten files need macOS, so they are
  kept as written in `coretext/` (dates and `/ID` fixed) and the build copies them.
- PyMuPDF writes the form pages in `zh-Hans`, `zh-Hant`, `ja`, `ko`, `hi` and `th` (HTML boxes laid
  out with HarfBuzz).
- reportlab writes the other pages. A right-to-left line is drawn by it in visual order, with
  Arabic presentation forms ([`rtl.py`](rtl.py)), because reportlab does not shape.

The `placed` layer is the born page's own text, drawn again over the picture in render mode 3, so it
carries the born page's fonts and ToUnicode maps at drift 0. The `vision` layer comes from Apple
Vision's words and boxes (`VNRecognizeTextRequest`, accurate level, language correction on, macOS
27.2.0, revision 3), recorded once per picture in `vision/` and drawn in render mode 3 in a glyphless
font made by [`vision.py`](vision.py). Vision on that macOS does not read Hebrew, Greek or Icelandic,
so those pages have no Vision twin. The mixed page is read with Chinese and English.

The handwriting ([`handwriting.py`](handwriting.py)) is synthetic: two openly licensed handwriting
fonts drawn glyph by glyph with seeded size, tilt, offset, baseline wobble and stroke weight, and a
stroke cursive drawn from Bézier letter shapes. The letter page ends with a cursive line and a
signature-like scrawl; neither copies anyone's hand.

## What the text layers hold

The expected file gives each line's `layer_text`: the layer read in content-stream order through
each font's ToUnicode map, with no reordering or normalising ([`layerread.py`](layerread.py)). It
also gives three facts derived from that:

- `decodes_exactly`: the layer equals the text;
- `decodes_normalised`: equal after Unicode NFKC, and, for a right-to-left line from a writer that
  draws in visual order, after reversing;
- `layer_unmapped`: the number of codes with no ToUnicode entry, which decode as U+FFFD.

How the born pages' lines (headings excluded) came out:

| writer | scripts | lines decoding exactly | after NFKC (and reversal) | with unmapped codes |
|---|---|---|---|---|
| reportlab | `el`, `ru`, `vi`, `pl`, `is` (prose and forms) | 80 of 80 | 80 | 0 |
| reportlab | `ar`, `he` forms | 8 of 20 | 20 | 0 |
| Core Text | `zh-Hans`, `zh-Hant`, `ja` | 18 of 18 | 18 | 0 |
| Core Text | `ko` | 2 of 6 | 2 | 4 |
| Core Text | `ja-vertical` | 4 of 6 | 4 | 2 |
| Core Text | `th` | 3 of 6 | 3 | 3 |
| Core Text | `he` | 0 of 6 | 3 (visual order) | 0 |
| Core Text | `ar`, `hi`, `mixed` | 0 of 16 | 0 | 16 |
| PyMuPDF | `zh-Hans`, `zh-Hant`, `ja`, `ko` forms | 24 of 40 | 36 | 4 |
| PyMuPDF | `hi`, `th` forms | 12 of 20 | 12 | 8 |

These are facts about the writers as they are, recorded so a test can tell an exact layer from an
imperfect one. Nothing here was altered to make a layer decode better or worse.

A U+FFFD character in an expected file's `layer_text` is what that page's text layer decodes to
(a code with no ToUnicode entry). It is not an encoding error in the expected file.

## Build and check

```sh
uv run python scripts_handwriting/build.py --out /tmp/sh-a
uv run python scripts_handwriting/build.py --out /tmp/sh-b         # byte-identical to /tmp/sh-a
uv run python scripts_handwriting/verify_docs.py /tmp/sh-a          # exit 0 = every property held
uv run python scripts_handwriting/verify_docs.py scripts_handwriting # the committed subset
uv run python scripts_handwriting/mutants.py --out /tmp/sh-mutants  # exit 0 = every mutant reported
uv run python scripts_handwriting/build.py --out /tmp/sh-c --publish
```

The build reads only committed inputs: the font subsets, the Core Text pages and the Vision
recordings. On macOS, `build.py --record-coretext` and `build.py --record-vision` write the last two
again, after the helpers are built:

```sh
swiftc -O -o scripts_handwriting/macos/ct_page scripts_handwriting/macos/ct_page.swift
swiftc -O -o scripts_handwriting/macos/vision_text scripts_handwriting/macos/vision_text.swift
```

A new recording on another macOS release can differ, and so change the documents built from it.
`fonts.py prepare <dir>` remakes the subsets from the source fonts, which are not committed. The
source of each is
`https://raw.githubusercontent.com/google/fonts/24ddc1f324cac5d9f5aedca126d298f56e3f1640/ofl/<path>`,
with the path and SHA-256 in `fonts.py`.

Two builds on one machine are byte-identical. On another platform the reportlab pages and the
twins made from them rebuild byte for byte (the tests check this), but the handwriting pictures do
not: the variable handwriting fonts rasterise slightly differently there. For those pages the
committed files are the reference.

The born pages and the `clean` pictures are committed (`documents/`). The `light` pictures stay
local and are rebuilt, and `SHA256SUMS` lists every document.

## The expected file

- **Born page:** `writer`, `fonts_embedded`, `render_modes`, and `lines`. Each line has `key`,
  `script`, `direction` (`ltr`, `rtl` or `ttb`), `vertical`, `align`, `anchor_pt` (the left edge, or
  the right edge for a right-aligned line, and the baseline; a vertical column's centre and top),
  `span_pt`, `size_pt`, `text`, `gloss`, `meaning`, `ink_boxes_px`, and the layer facts above.
  `ink_boxes_px` holds integer pixels at 300 dpi, with a top-left origin, measured as ink groups
  separated by at least 0.25 em (0.6 em down a vertical column) ([`ink.py`](ink.py)).
- **Scanned twin:** `source`, `condition`, `dpi`, `jpeg_quality`, `image`, `layer`, and `lines`, with
  ink boxes measured on its own picture; the line layer facts too for a `placed` twin. A `vision`
  twin has `vision`: the recording, the macOS version, the revision, the languages, and every
  drawn piece with its box.
- **Handwriting page:** `lines` (text, kind, font, meaning) and `words` (each word's box, from its
  own mask).

## The checks

| check | what must hold |
|---|---|
| `checksums` | SHA-256 and size equal `manifest.json` and `SHA256SUMS` |
| `fonts` | every embedded font is a family subset ("Subset" in its name) or the glyphless layer font |
| `layer` | each line decodes as recorded, the match flags follow from it, and a `placed` twin's layer equals its born page's |
| `render-mode` | a born page shows text in render mode 0; every layer show on a scan is in render mode 3; a `placed` twin renders exactly as its picture |
| `ink` | the word boxes measured again on a fresh render have the recorded count and edges within 3 px; on a born page, poppler's `pdftoppm` (where installed) finds no ink outside them; a handwriting word box's ink reaches its edges within 3 px |
| `direction` | a left-to-right line's ink starts at its anchor, a right-to-left line's ink ends at its anchor (within 0.3 em, a glyph's side bearing), and a vertical line's ink runs down one column |
| `vision` | the recording matches the picture, and the layer draws exactly the recorded pieces, in order |
| `picture` | the JPEG's quantization tables equal Pillow's at the stated quality, and its size gives the stated dpi |

Limits: the right-to-left and vertical facts come from where the ink sits, not from a reading of
the writer's intent. The layer is read through ToUnicode only, without reordering, so a reader that
applies the bidirectional algorithm can return different text. Glyph shapes are compared with no
reference beyond the rendered pixels.

`mutants.py` turns each check red once:
- a page drawn in a font that is not a family subset;
- one ToUnicode entry changed;
- a placed layer written in render mode 0;
- a word box moved;
- a right-to-left label recorded as left-aligned;
- a Vision piece dropped;
- a picture encoded at the wrong quality;
- a manifest checksum changed.

The run passes only when each defect is reported by its own check and the eight unmutated controls
are green. `mutants-record.json` holds the last run.

## Fonts

Every font is under the SIL Open Font License 1.1, from the Google Fonts catalogue at commit
`24ddc1f324cac5d9f5aedca126d298f56e3f1640`, with each family's licence in
`fonts/OFL-<family>.txt` and its copyright line in the repository's [`NOTICE`](../NOTICE). The
committed Noto files are subsets of a static instance, renamed `<family> Subset`, with every
reserved-name record removed. Caveat and Patrick Hand are unmodified and only draw page pictures.
No full source font file is committed, and no system font is embedded in any document.
