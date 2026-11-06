# Filled-form fixtures

One synthetic intake form, filled by four real PDF writers (reportlab, pypdf, PyMuPDF and macOS
PDFKit), plus a widget-free control, a dynamic XFA form and three reject documents. Each document
comes with an expected file that records what the bytes hold: every field's name, type, stored
value, flags, appearance streams and drawn text, and where its widget sits on the page.

Everything on these pages is synthetic. The values come from the hidden-layer family's value set
([`../hidden_layer/values.py`](../hidden_layer/values.py)): 555-01xx telephone numbers, RFC 2606
e-mail domains, an SSN in the never-issued 000 area, an unassigned ZIP code.

## What is here

| path | what |
|---|---|
| `build.py` | the generator: builds every document, checks it against what its producer was asked to write, writes its expected file, `manifest.json` and `SHA256SUMS` |
| `verify_docs.py` | checks each document's properties from its bytes and a render (below) |
| `mutants.py` | the recorded mutants: one deliberate defect per property, each of which `verify_docs` must report |
| `form.py`, `producers.py`, `facts.py`, `pdfkit.py` | the printed form and its field table, one producer function per document, the fact reader, the PDFKit runner |
| `pdfkit/` | `gen_pdfkit.swift` (a small PDFKit helper), the two PDFKit documents as written, and `recorded.json` (the macOS version and their SHA-256) |
| `documents/`, `expected/` | every document (all are small) and its expected file |
| `manifest.json`, `SHA256SUMS` | one row per document (path, size, SHA-256, kind, producer and versions, purpose) and the checksums |

## The documents

| id | kind | producer | what |
|---|---|---|---|
| `ff-reportlab-all` | form | reportlab | every field kind but the signature, created and filled by reportlab: five text fields, two checkboxes (on, off), a radio group, a combo box, a list box, and a multi-line field whose value overflows it |
| `ff-pypdf-text-ap` | form | pypdf | the reportlab blank with its five text fields filled by pypdf, with appearance streams and no `/NeedAppearances` |
| `ff-pypdf-text-needappearances` | form | pypdf | the same values with every text widget's appearance stream removed and `/NeedAppearances` true |
| `ff-pypdf-buttons` | form | pypdf | the blank with one checkbox on, one off and the radio group set (`/V` and `/AS`) |
| `ff-pymupdf-all` | form | PyMuPDF | every field kind but the signature, added and filled by PyMuPDF with its own appearance streams |
| `ff-pypdf-signature` | form | pypdf | one unsigned signature field (`/FT /Sig`, no `/V`) whose appearance is a drawn stroke; no signing key, a visual mark only |
| `ff-pypdf-hidden-noview` | form | pypdf | five filled text fields; the SSN widget is flagged Hidden and the date-of-birth widget NoView |
| `ff-pymupdf-annotation-beside` | form | PyMuPDF | five filled text widgets with a text note (and its popup), a free-text box and a square beside them |
| `ff-pdfkit-filled` | form | PDFKit | five text widgets and two checkboxes written by macOS PDFKit |
| `ff-pdfkit-blackwidget-cover` | form | PDFKit | the SSN printed as page text, with an empty black-background text widget drawn over it |
| `ff-control-no-widgets` | control | reportlab | the printed form with no fields and no annotations; its SHA-256 is pinned in `tests/test_filled_forms.py` |
| `ff-xfa-dynamic` | xfa | pypdf | a dynamic XFA form: template and data packets in `/AcroForm /XFA`, a repeating subform, `/NeedsRendering`, and the stand-in page a viewer without XFA shows |
| `ff-reject-hidden-value` | reject | pypdf | one text field flagged Hidden whose stored value and appearance hold the SSN, which the page does not print |
| `ff-reject-overflow` | reject | pypdf | one single-line text field whose appearance draws a value longer than the field, clipped to its inner box |
| `ff-reject-value-differs` | reject | pypdf | one text field whose stored value is one name and whose appearance draws another |

Some facts the expected files record come from the producers themselves, as written:

- PDFKit writes no catalog `/AcroForm`: its widgets hang off the page's `/Annots` only.
- PDFKit names the fields itself (`text0` ... `text4`, `button0`, `button1`) and stores a checkbox
  value as a string.
- PyMuPDF gives every radio button the on-state `/Yes`.
- reportlab's list box appearance draws every option.
- PyMuPDF adds a `/Popup` with a text note.

## Build and check

```sh
uv run python filled_forms/build.py --out /tmp/ff-a
uv run python filled_forms/build.py --out /tmp/ff-b            # byte-identical to /tmp/ff-a
uv run python filled_forms/verify_docs.py /tmp/ff-a             # exit 0 = every property held
uv run python filled_forms/verify_docs.py filled_forms          # the committed set
uv run python filled_forms/mutants.py --out /tmp/ff-mutants     # exit 0 = every mutant reported
uv run python filled_forms/build.py --out /tmp/ff-c --publish   # refresh the committed files here
```

reportlab writes with `invariant=1`, and neither pypdf nor PyMuPDF writes a clock field here, so
those documents depend only on this commit and the locked versions. PDFKit runs only on macOS and
embeds a font subset for its check mark that varies from one write to the next. Its two documents
are therefore kept as written in `pdfkit/`, with their dates and `/ID` replaced by fixed values of
the same length, and the build copies them. On macOS,
`swiftc -O -o filled_forms/pdfkit/gen_pdfkit filled_forms/pdfkit/gen_pdfkit.swift` and
`build.py --record-pdfkit` write them again. `tests/test_filled_forms.py` rebuilds every other
document and compares its bytes.

## The expected file

- `facts`: what `facts.py` reads from the bytes. That is the catalog's `/AcroForm` (present,
  `/NeedAppearances`, `/SigFlags`, the number of `/Fields`, the `/XFA` packet names) and
  `/NeedsRendering`, plus the page's printed text. Per widget, in page order, it records: the fully
  qualified name, `/FT`, `/Ff`, `/V`, `/DV`, `/Opt`, the annotation flags, `/Rect` (PDF points,
  bottom-left origin), `/AS`, the `/MK /BG` colour, and the normal appearance. For the appearance
  that is either a stream with its `/BBox`, the strings it draws, its clip, its text size and its
  text origin, or a set of states and the strings the current one draws. Other annotations get
  their subtype, rectangle and contents.
- `fields`: the widgets grouped by field name, with each field's kind (text, multiline, checkbox,
  radio, combo, list, signature) from `/FT` and `/Ff`.
- `visible`: per widget, whether it has an appearance and neither the Hidden nor the NoView flag
  (`null` where there is no appearance stream).
- `draws`: per widget, whether its shown appearance puts ink on the page (it draws a string, it is
  a button in a state other than Off, or it is a signature stroke). It is `false` for a widget that
  is not shown, and `null` where neither can be said.
- `overflow` (`ff-reject-overflow`): the value's advance in Helvetica at the appearance's size, the
  clip's right edge, and the value split into the part inside the clip and the part beyond it.
- `appearance_matches_value` (`ff-reject-value-differs`): `false`.

## The checks

| check | what it reads | what must hold |
|---|---|---|
| `checksums` | the files | SHA-256 and size equal `manifest.json` and `SHA256SUMS` |
| `facts` | pypdf | the facts read now equal the recorded ones |
| `intent` | the facts | the document holds what its producer was asked to write (`build.py`, one function per document) |
| `second-reader` | PyMuPDF's widget reader | the same widgets at the same rectangles, with the same names, types and text values |
| `visible` | two PyMuPDF renders (with and without annotations) | no pixel changes inside a widget that is not shown; some pixels change inside a shown widget whose appearance draws |
| `reject` | the facts and the renders | the hidden value is stored and drawn but not shown, and not in the page text; the overflowing appearance leaves no pixel outside its field and splits as recorded; the drawn text differs from the stored value |
| `cover` | the renders and the page text | the printed SSN is still page text, and the cover widget renders at least 85 % dark |
| `xfa` | the `/XFA` packets | they join into well-formed XML with a repeating subform and the data values; the stand-in page carries its text |

The renders come from one reader (PyMuPDF). A widget whose appearance stream is missing is not
judged by the render, since a viewer may make one. `mutants.py` turns each check red once: a value
written wrong, an expected value changed, a widget rectangle moved, a hidden widget recorded as
drawing, the overflow written without its clip, the cover's appearance emptied, the SSN dropped from
the XFA data, a manifest checksum changed. Each defect is reported by its own check, and
`mutants-record.json` holds the last run.
