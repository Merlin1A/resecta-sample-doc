# Font provenance & notices

## Inter (primary typeface)

- **Family:** Inter, version **4.1** (static instances).
- **Files:** `Inter-Regular.ttf`, `Inter-Medium.ttf`, `Inter-SemiBold.ttf`, `Inter-Bold.ttf`
  (from `extras/ttf/` of the official release).
- **Source (official Inter repository, rsms/inter):**
  `https://github.com/rsms/inter/releases/download/v4.1/Inter-4.1.zip`
- **Release archive SHA-256:** `9883fdd4a49d4fb66bd8177ba6625ef9a64aa45899767dde3d36aa425756b11e`
- **Fetched:** 2026-06-09
- **License:** SIL Open Font License, Version 1.1 — see [`OFL.txt`](./OFL.txt).
  Copyright (c) 2016 The Inter Project Authors (https://github.com/rsms/inter).
  Inter carries **no Reserved Font Name**, so modification while keeping the family name is permitted.
- **License posture (OFL FAQ):** OFL is OSI/FSF-approved and compatible with an
  Apache-2.0 software bundle. Redistributing these font files in the repo requires shipping `OFL.txt`
  + the copyright notice alongside them (done here). Embedding a **subset** of the font in the PDF is
  not "distribution" and does **not** relicense the PDF.

### Modification applied
The `tnum` (tabular figures) OpenType feature was **frozen into the default glyph set** of each weight
via `opentype-feature-freezer` (`pyftfeatfreeze -f tnum`), so the ten digits are equal-width. This is
required for vertical decimal-point alignment in the statement's amount columns, because
reportlab does not apply OpenType layout features (`tnum`) at render time — it renders default `cmap`
glyphs. No other modification was made. Regenerate deterministically with `prepare_fonts.py`.

## IBM Plex Sans (documented alternate — not bundled)
IBM Plex Sans (also SIL OFL 1.1) is a documented alternate. Inter was used as the
primary; IBM Plex Sans was **not** fetched or embedded, so it is intentionally absent here to keep the
embedded-font set to the single chosen family (acceptance assertion #4).
