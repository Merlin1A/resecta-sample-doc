# Structure fixtures: unusual, at the limits, malformed

**This folder holds malformed and hostile-shaped test inputs, and every active element in them is
inert.**
- A script is a comment and an empty function.
- A Launch action names a file that does not exist and runs nothing.
- The one embedded file is a short invented text.
- No file carries an exploit for any reader, and none is built against a specific product.

Each document holds one structural property and comes with an expected file that states it as a
sentence and as numbers. [`verify_docs.py`](verify_docs.py) measures the numbers again from the
bytes alone, with code that did not write them ([`measure.py`](measure.py): a byte walk, zlib and
pypdf). The files are built by [`pdfbytes.py`](pdfbytes.py), a small writer in which every object,
offset and trailer key is chosen, so a malformed property is exact. Three documents come from
elsewhere: object streams from PyMuPDF, and two files kept as written in `recorded/`, a linearized
file from qpdf and the encrypted file (below).

All text in the files is synthetic.

## The documents (70)

**Unusual but valid (16)**

| id | property |
|---|---|
| `st-unusual-rotate-90`, `-180`, `-270` | the one page has /Rotate 90, 180 or 270 |
| `st-unusual-rotate-inherited` | the page has no /Rotate of its own; the Pages node it inherits from has /Rotate 90 |
| `st-unusual-mixed-sizes` | five pages: A4, Letter, A3, 72 x 72 pt and 200 x 2000 pt |
| `st-unusual-scan-150dpi`, `-72dpi` | one page that is a 150 dpi or a 72 dpi picture |
| `st-unusual-white-on-white` | the page text is filled with white on the white page |
| `st-unusual-object-streams` | the objects sit in object streams indexed by a cross-reference stream |
| `st-unusual-incremental-2`, `-5` | an original and one or four incremental updates, their sections joined by /Prev |
| `st-unusual-linearized` | a linearized file |
| `st-unusual-pdf20` | the header declares PDF 2.0 |
| `st-unusual-tagged` | a tagged file: a structure tree with one paragraph element bound to MCID 0 |
| `st-unusual-optional-content-off` | one line sits in an optional-content group the default configuration switches off |
| `st-unusual-annotation-kinds` | a link, a text note, a highlight, an ink mark, a stamp and a file attachment |

**At and one past each named limit (40).** Each has a pair: `st-limit-<limit>-at` is exactly at the
limit, and `st-limit-<limit>-past` is one unit past it. The limits are those of the Resecta byte
reader's design: a value equal to a limit is within it, and the first unit past it is not.

| limit | at | one past |
|---|---|---|
| `input-bytes` | the file is 52,428,800 bytes | 52,428,801 |
| `objects` | 100,000 objects | 100,001 |
| `stream-inflated` | one stream inflates to 16,777,216 bytes | 16,777,217 |
| `total-inflated` | five streams inflate to 67,108,864 bytes in all, each under the per-stream and ratio limits | 67,108,865 |
| `inflate-ratio` | one stream inflates to exactly 1,000 bytes per encoded byte | 1,001 |
| `nesting` | an array nests 32 levels deep | 33 |
| `content-operators` | the content streams hold 1,000,000 operators | 1,000,001 |
| `form-depth` | form XObjects nest 8 levels deep | 9 |
| `pages` | 2,000 pages | 2,001 |
| `image-pixels` | one 1-bit image of 10,000 x 10,000 pixels | 100,000,001 x 1 |
| `string-bytes` | one string of 32,767 bytes | 32,768 |
| `name-bytes` | one name of 127 bytes | 128 |
| `array-elements` | one array of 8,191 elements | 8,192 |
| `dictionary-entries` | one dictionary of 4,095 entries | 4,096 |
| `graphics-state-depth` | saved graphics states nest 28 levels deep | 29 |
| `operands` | one operator with 64 operands (inside a BX/EX section) | 65 |
| `number-digits` | a number with 18 significant digits | 19 |
| `number-scale` | a number with 18 decimal places | 19 |
| `wide-digits` | two cm operators whose first entries are 18-digit integers (a product of 36 digits) | three (54) |
| `wide-scale` | the same with 18 decimal places each (36 places) | three (54) |

The exact-ratio streams are built so the ratio holds with no trailing byte. The body is zero bytes
deflated and sync-flushed, then one final stored block sized to make the ratio exact, then the
checksum (`docs.exact_ratio_body`).

**The one document allowed past 64 MiB of inflated output** is `st-limit-total-inflated-past`
(67,108,865 bytes across five streams). It is the only way to show the total limit one unit past,
and it is never committed.

**Malformed or hostile, inert (14)**

| id | property |
|---|---|
| `st-malformed-xref-offsets-lie` | the cross-reference entry for object 4 points 7 bytes before the object |
| `st-malformed-length-short`, `-long` | the content stream's /Length is 40 bytes short of, or runs 40 bytes past, its endstream |
| `st-malformed-trailer-missing-object` | the trailer's /Info points at object 40, which the file does not hold |
| `st-malformed-kids-cycle` | the Pages node lists itself among its /Kids |
| `st-malformed-next-cycle` | the open action's /Next chain returns to itself after two GoTo actions |
| `st-malformed-next-shared-chain` | 400 link annotations share one /Next chain of 400 GoTo actions |
| `st-malformed-duplicate-object` | object 5 appears twice at two offsets; the table points at the second |
| `st-malformed-bytes-after-endstream` | ten bytes sit between a stream's endstream and its endobj |
| `st-malformed-bytes-after-eof` | bytes follow the final %%EOF |
| `st-malformed-second-eof` | a second %%EOF follows the first |
| `st-malformed-bounded-bomb` | one stream inflates to 33,554,432 bytes (32 MiB) from under 100 KiB: past the per-stream and ratio limits, under 64 MiB |
| `st-malformed-encrypted-empty-user` | RC4-encrypted (standard handler, revision 2) with an empty user password; kept as written in `recorded/` (below) |
| `st-malformed-active-elements` | a document JavaScript that is a comment and an empty function, an open action that runs it, and a Launch action naming a file that does not exist |

The nesting depth past its limit is `st-limit-nesting-past`.

**The encrypted document.** `st-malformed-encrypted-empty-user` is kept as written. Its encryption
dictionary is `/Filter /Standard /V 1 /R 2 /P -4`, with
`/O <6c7fbd492bf971a9f62afc778b48ab3056a0c52a5c63af9c8d43755230e4635c>` and
`/U <a6a9030418d429ac07ce2cc08912e93a35a1910bff014ca9e6fadaa02641443e>`, and its `/ID` is
`<7220bd22cf67a6af45e1cf6ddc4db2da>` twice. It was written once by the standard security handler,
revision 2 (40-bit RC4), as ISO 32000-1 section 7.6.3 defines it; no code for that handler is kept
in this repository. The user password is empty, and the owner password is the synthetic string
`synthetic-owner-password`. The steps:

1. `/O`: the owner password, padded to 32 bytes with the standard padding string, is hashed with
   MD5. The first 5 bytes of the hash are an RC4 key, which encrypts the padded user password.
2. The file key: MD5 over the padded user password, `/O`, `/P` as four little-endian bytes and the
   first `/ID` string. Its first 5 bytes are the key.
3. `/U`: the padding string, encrypted with the file key.
4. Each object: MD5 over the file key, the object number (three little-endian bytes) and the
   generation (two little-endian bytes). The first 10 bytes are the RC4 key for that object's
   strings and streams.

The expected file holds these entries as facts and the same steps as a `note`. Verify reads the
entries from the bytes and opens the file with an empty password through pypdf.

## Build and check

```sh
uv run python structure/build.py --out /tmp/st-a
uv run python structure/build.py --out /tmp/st-b                       # byte-identical to /tmp/st-a
uv run python structure/verify_docs.py /tmp/st-a                        # exit 0 = every property held
uv run python structure/verify_docs.py structure                        # the committed set
uv run python structure/mutants.py --built /tmp/st-a --out /tmp/st-mut  # exit 0 = every mutant reported
uv run python structure/build.py --out /tmp/st-c --publish
```

These ten documents stay local, rebuilt by the generator and listed in `SHA256SUMS` and
`manifest.json` (`stored: local`): the input-bytes, objects, content-operators and pages pairs, and
both total-inflated files. Every other document is committed. A full build takes about 15 seconds
and writes about 118 MB.

## The expected file and the checks

Each expected file gives the document's `group`, its `kind` (the measured property), the
`property` sentence, the `facts` (the property's numbers), its size in `bytes`, and
`qpdf_check_exit`: the status `qpdf --check` returned when the file was built (0 clean, 2 errors,
3 warnings), or `null` where qpdf was not installed.

| check | what must hold |
|---|---|
| `checksums` | SHA-256 equals `manifest.json` and `SHA256SUMS` |
| `size` | the file's size equals the recorded one |
| `property` | the facts measured again from the bytes equal the recorded facts |
| `qpdf` | where qpdf is installed, `qpdf --check` exits as recorded |

The expected file states what each document is. It does not say how any reader handles it.

`mutants.py` shows each property kind can fail. Each limit's file at the limit is checked against
the expected file of the one past it, so the measurement must tell the two apart by one unit.
Paired documents are swapped the same way, every other kind has one recorded fact changed, and
one manifest checksum is changed. `mutants-record.json` holds the last run: 45 mutants, each
reported by its own check.
