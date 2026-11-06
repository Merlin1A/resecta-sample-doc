"""The hidden text layer and the PDF writer.

The file is written directly (no PDF library), so every number in it is a decimal chosen here.
Each page is one JPEG image drawn over the whole page, then a text layer in render mode 3
(invisible), one positioned text object per hidden word, in the standard Helvetica font. A hidden
word is stretched horizontally (``Tz``) so that its advance equals a chosen width, and placed at a
chosen origin: for a placed layer, the printed word's ink box shifted by the document's offsets.

A hidden word's box is its text-space box: from its origin to origin + advance along the line, and
from the baseline + descender to the baseline + ascender of Helvetica (-207 and 718 per 1000 em).
Each glyph's box is the same band over that glyph's advance. All boxes are in PDF points,
bottom-left origin, as written to the file (rounded to 0.001 pt).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction

from reportlab.pdfbase.pdfmetrics import stringWidth

HIDDEN_FONT = "Helvetica"
ASCENT = Fraction(718, 1000)
DESCENT = Fraction(-207, 1000)
TITLE = "Synthetic hidden-layer scan fixture"


@dataclass
class HiddenPiece:
    text: str
    x_pt: Fraction
    baseline_pt: Fraction
    size_pt: int
    hscale: Fraction
    trailing_space: bool

    def advance(self, s: str) -> Fraction:
        natural = Fraction(stringWidth(s, HIDDEN_FONT, 1000)) / 1000 * self.size_pt
        return natural * self.hscale / 100

    def box(self) -> tuple[Fraction, Fraction, Fraction, Fraction]:
        y0 = self.baseline_pt + DESCENT * self.size_pt
        y1 = self.baseline_pt + ASCENT * self.size_pt
        return (self.x_pt, y0, self.x_pt + self.advance(self.text), y1)

    def glyphs(self) -> list[tuple[str, Fraction, Fraction]]:
        out = []
        x = self.x_pt
        for ch in self.text:
            w = self.advance(ch)
            out.append((ch, x, x + w))
            x += w
        return out


def fit_piece(
    text: str,
    x0_pt: Fraction,
    x1_pt: Fraction,
    baseline_pt: Fraction,
    size_pt: int,
    trailing_space: bool,
) -> HiddenPiece:
    """A piece whose advance spans [x0, x1]. The scale is rounded to 0.001 % and the origin to 0.01 pt,
    so the written numbers are short; the piece's recorded box follows from the written numbers."""
    natural = Fraction(stringWidth(text, HIDDEN_FONT, 1000)) / 1000 * size_pt
    hscale = round(Fraction(100) * (x1_pt - x0_pt) / natural, 3)
    return HiddenPiece(
        text,
        Fraction(round(x0_pt, 2)),
        Fraction(round(baseline_pt, 2)),
        size_pt,
        Fraction(hscale),
        trailing_space,
    )


def dec(f: Fraction, places: int) -> str:
    """``f`` rounded to ``places`` decimals, as the shortest decimal text."""
    d = Decimal(f.numerator) / Decimal(f.denominator)
    q = d.quantize(Decimal(1).scaleb(-places))
    text = format(q, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def _pdf_string(s: str) -> str:
    return "(" + s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") + ")"


def content_stream(pieces: list[HiddenPiece], width_pt: int, height_pt: int) -> bytes:
    ops = [f"q {width_pt} 0 0 {height_pt} 0 0 cm /Im1 Do Q"]
    if pieces:
        ops.append("BT 3 Tr")
        for p in pieces:
            text = p.text + (" " if p.trailing_space else "")
            ops.append(
                f"/F1 {p.size_pt} Tf {dec(p.hscale, 3)} Tz 1 0 0 1 {dec(p.x_pt, 2)} {dec(p.baseline_pt, 2)} Tm "
                f"{_pdf_string(text)} Tj"
            )
        ops.append("ET")
    return ("\n".join(ops) + "\n").encode("ascii")


def write_pdf(
    jpeg: bytes,
    image_px: tuple[int, int],
    pieces: list[HiddenPiece],
    width_pt: int = 612,
    height_pt: int = 792,
) -> bytes:
    """One page: the JPEG as /Im1 (DCTDecode, DeviceGray) over the page, then the hidden layer."""
    content = content_stream(pieces, width_pt, height_pt)
    w, h = image_px
    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {width_pt} {height_pt}] /Contents 4 0 R "
            "/Resources << /Font << /F1 5 0 R >> /XObject << /Im1 6 0 R >> >> >>"
        ).encode("ascii"),
        f"<< /Length {len(content)} >>\nstream\n".encode("ascii") + content + b"endstream",
        f"<< /Type /Font /Subtype /Type1 /BaseFont /{HIDDEN_FONT} /Encoding /WinAnsiEncoding >>".encode(
            "ascii"
        ),
        (
            f"<< /Type /XObject /Subtype /Image /Width {w} /Height {h} /ColorSpace /DeviceGray "
            f"/BitsPerComponent 8 /Filter /DCTDecode /Length {len(jpeg)} >>\nstream\n"
        ).encode("ascii")
        + jpeg
        + b"\nendstream",
        (
            f"<< /Title {_pdf_string(TITLE)} /Producer (resecta-sample-doc hidden_layer writer) "
            "/Subject (SYNTHETIC TEST DOCUMENT - FICTIONAL DATA) >>"
        ).encode("ascii"),
    ]
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode("ascii") + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("ascii")
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode("ascii")
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R /Info {len(objects)} 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode(
        "ascii"
    )
    return bytes(out)
