"""Born-digital script pages: one layout, three writers.

- macOS Core Text (``macos/ct_page.swift``) lays out each line (shaping, bidi, vertical forms) and
  draws it into a CGPDFContext; its dates and ``/ID`` are replaced by fixed values of the same
  length (``filled_forms/pdfkit.py`` ``pin``);
- PyMuPDF lays out HTML boxes with HarfBuzz shaping (``insert_htmlbox``);
- reportlab draws each line with a registered TrueType font; it does not shape, so a right-to-left
  line is drawn in visual order with Arabic presentation forms (``rtl.py``).

Every page embeds only the committed font subsets (``fonts.py``). A line is split into runs by the
font that holds each character, so no writer falls back to a system font.

Layout (PDF points, bottom-left origin, Letter): a Latin heading at the top; prose lines from
``PROSE_TOP`` at ``PITCH``; right-to-left lines aligned to ``RIGHT``; the vertical page sets each
line as a column from the right, ``COLUMN_PITCH`` apart; form rows put the label at ``LEFT`` (``RIGHT``
for right-to-left) and the value after it, with a rule under each value.
"""

from __future__ import annotations

import io
import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pymupdf
from fontTools.ttLib import TTFont
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont as RLTTFont
from reportlab.pdfgen import canvas

from filled_forms.pdfkit import pin

from . import fonts, rtl, texts

HERE = Path(__file__).resolve().parent
CT_HELPER = HERE / "macos" / "ct_page"
PAGE = (612, 792)
LEFT = 72
RIGHT = 540
PROSE_TOP = 680
PITCH = 34
COLUMN_PITCH = 46
VERTICAL_RIGHT = 520
VERTICAL_TOP = 700
SIZE = 14
HEADING = "SYNTHETIC SCRIPT PAGE - FICTIONAL DATA"
FORM_LABEL_W = 170
FORM_TOP = 660
FORM_PITCH = 44

_cmaps: dict[str, set[int]] = {}


def cmap(key: str) -> set[int]:
    if key not in _cmaps:
        _cmaps[key] = set(TTFont(str(fonts.path_of(key))).getBestCmap())
    return _cmaps[key]


def runs(text: str, code: str) -> list[tuple[str, str]]:
    """(text, font key) runs: each character in its script's font, else the Latin subset."""
    out: list[tuple[str, str]] = []
    primary = fonts.SCRIPT_FONT.get(code, "latin")
    for ch in text:
        key = fonts.mixed_font(ch) if code == "mixed" else primary
        if ord(ch) not in cmap(key):
            key = "latin"
        if out and out[-1][1] == key:
            out[-1] = (out[-1][0] + ch, key)
        else:
            out.append((ch, key))
    return out


@dataclass(frozen=True)
class PlacedLine:
    """One line as laid out: what it says, where, and how."""

    key: str
    text: str
    x: float
    y: float
    align: str  # left | right
    vertical: bool
    script: str
    direction: str  # ltr | rtl | ttb
    span: tuple[float, float] = (0.0, 612.0)  # the x range that holds the line's shows


def prose_lines(code: str) -> list[PlacedLine]:
    s = texts.scripts()["ja" if code == "ja-vertical" else code]
    out = [PlacedLine("heading", HEADING, LEFT, 740, "left", False, "latin", "ltr")]
    for i, ln in enumerate(s.lines):
        if code == "ja-vertical":
            out.append(
                PlacedLine(
                    f"line{i}",
                    ln.text,
                    VERTICAL_RIGHT - COLUMN_PITCH * i,
                    VERTICAL_TOP,
                    "left",
                    True,
                    "ja",
                    "ttb",
                )
            )
        elif s.direction == "rtl":
            out.append(
                PlacedLine(
                    f"line{i}", ln.text, RIGHT, PROSE_TOP - PITCH * i, "right", False, code, "rtl"
                )
            )
        else:
            out.append(
                PlacedLine(
                    f"line{i}", ln.text, LEFT, PROSE_TOP - PITCH * i, "left", False, code, "ltr"
                )
            )
    return out


def form_lines(code: str) -> tuple[list[PlacedLine], list[tuple[float, float, float, float]]]:
    s = texts.scripts()[code]
    lines = [PlacedLine("heading", HEADING, LEFT, 740, "left", False, "latin", "ltr")]
    rules: list[tuple[float, float, float, float]] = []
    for i, (label, value, _, k) in enumerate(texts.form_rows(s)):
        y = FORM_TOP - FORM_PITCH * i
        value_script = (
            "latin"
            if k in ("phone", "account", "email")
            or (k == "date" and code not in ("zh-Hans", "zh-Hant", "ja", "ko"))
            else code
        )
        if s.direction == "rtl":
            cut = RIGHT - FORM_LABEL_W
            lines.append(
                PlacedLine(
                    f"label{i}", label, RIGHT, y, "right", False, code, "rtl", (cut, PAGE[0])
                )
            )
            lines.append(
                PlacedLine(
                    f"value{i}",
                    value,
                    cut,
                    y,
                    "right",
                    False,
                    value_script if value_script != "latin" else code,
                    "rtl" if value_script != "latin" else "ltr",
                    (0.0, cut),
                )
            )
            rules.append((RIGHT - FORM_LABEL_W - 260, y - 5, RIGHT - FORM_LABEL_W, y - 4.5))
        else:
            cut = LEFT + FORM_LABEL_W
            lines.append(
                PlacedLine(
                    f"label{i}", label, LEFT, y, "left", False, code, "ltr", (0.0, cut - 0.5)
                )
            )
            lines.append(
                PlacedLine(
                    f"value{i}",
                    value,
                    cut,
                    y,
                    "left",
                    False,
                    value_script if value_script != "latin" else code,
                    "ltr",
                    (cut - 0.5, PAGE[0]),
                )
            )
            rules.append((LEFT + FORM_LABEL_W, y - 5, LEFT + FORM_LABEL_W + 260, y - 4.5))
    return lines, rules


def _line_code(ln: PlacedLine, page_code: str) -> str:
    return "latin" if ln.script == "latin" else ("mixed" if page_code == "mixed" else ln.script)


# ------------------------------------------------------------------------------------ Core Text
def coretext_spec(
    lines: list[PlacedLine], rules: list[tuple[float, float, float, float]], page_code: str
) -> dict[str, Any]:
    out = []
    for ln in lines:
        code = _line_code(ln, page_code)
        rs = [
            {"text": t, "font": str(fonts.path_of(k))}
            for t, k in (runs(ln.text, code) if code != "latin" else [(ln.text, "latin")])
        ]
        out.append(
            {
                "runs": rs,
                "size": 10 if ln.key == "heading" else SIZE,
                "x": ln.x,
                "y": ln.y,
                "align": ln.align,
                "vertical": ln.vertical,
            }
        )
    return {"page": list(PAGE), "lines": out, "rules": [list(r) for r in rules]}


def write_coretext(
    lines: list[PlacedLine], rules: list[tuple[float, float, float, float]], page_code: str
) -> bytes:
    spec = coretext_spec(lines, rules, page_code)
    with tempfile.TemporaryDirectory() as td:
        sp, out = Path(td) / "spec.json", Path(td) / "out.pdf"
        sp.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
        subprocess.run([str(CT_HELPER), str(sp), str(out)], check=True, capture_output=True)  # noqa: S603 - the helper in macos/
        return pin(out.read_bytes())


# --------------------------------------------------------------------------------------- PyMuPDF
def _css() -> str:
    faces = "".join(
        f"@font-face {{font-family: f{k}; src: url({fonts.path_of(k).name});}}\n"
        for k in fonts.SOURCES
    )
    return faces + "* {margin: 0; padding: 0;}\n"


def _html(text: str, code: str, size: float, rtl: bool) -> str:
    spans = "".join(
        f'<span style="font-family: f{k};">{_esc(t)}</span>'
        for t, k in (runs(text, code) if code != "latin" else [(text, "latin")])
    )
    d = ' dir="rtl"' if rtl else ""
    align = "right" if rtl else "left"
    return (
        f'<p{d} style="font-size: {size}pt; text-align: {align}; white-space: nowrap;">{spans}</p>'
    )


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


HTML_BOX_H = 3.0  # box height in units of the font size
HTML_BOX_W = 520


def _html_rect(ln: PlacedLine, size: float, top: float) -> Any:
    if ln.align == "right":
        return pymupdf.Rect(ln.x - HTML_BOX_W, top, ln.x, top + size * HTML_BOX_H)
    return pymupdf.Rect(ln.x, top, min(PAGE[0], ln.x + HTML_BOX_W), top + size * HTML_BOX_H)


def _baseline_offset(html: str, css: str, arch: Any, ln: PlacedLine, size: float) -> float:
    """Where the first baseline lands below a box's top edge (measured on a scratch page)."""
    doc = pymupdf.open()
    page = doc.new_page(width=PAGE[0], height=PAGE[1])
    page.insert_htmlbox(_html_rect(ln, size, 100.0), html, css=css, archive=arch)
    origins = [
        c["origin"][1]
        for b in page.get_text("rawdict")["blocks"]
        for line in b.get("lines", [])
        for sp in line["spans"]
        for c in sp["chars"]
    ]
    doc.close()
    return (min(origins) if origins else 100.0 + size) - 100.0


def write_pymupdf(
    lines: list[PlacedLine], rules: list[tuple[float, float, float, float]], page_code: str
) -> bytes:
    doc = pymupdf.open()
    page = doc.new_page(width=PAGE[0], height=PAGE[1])
    arch = pymupdf.Archive(str(fonts.FONT_DIR))
    css = _css()
    h = PAGE[1]
    for ln in lines:
        size = 10 if ln.key == "heading" else SIZE
        code = _line_code(ln, page_code)
        html = _html(ln.text, code, size, ln.direction == "rtl")
        top = (h - ln.y) - _baseline_offset(html, css, arch, ln, size)
        spare, scale = page.insert_htmlbox(_html_rect(ln, size, top), html, css=css, archive=arch)
        if scale < 1 or spare < 0:
            raise ValueError(f"{ln.key}: the HTML box does not fit (scale {scale})")
    for x0, y0, x1, y1 in rules:
        page.draw_rect(pymupdf.Rect(x0, h - y1, x1, h - y0), color=None, fill=(0, 0, 0))
    doc.set_metadata(
        {
            "title": "Synthetic script fixture",
            "creator": "PyMuPDF",
            "producer": "PyMuPDF",
            "creationDate": "",
            "modDate": "",
        }
    )
    doc.subset_fonts()
    out = doc.tobytes(garbage=3, deflate=True, no_new_id=True)
    doc.close()
    return bytes(out)


# ------------------------------------------------------------------------------------- reportlab
def _rl_font(key: str) -> str:
    name = f"F-{key}"
    if name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(RLTTFont(name, str(fonts.path_of(key))))
    return name


def write_reportlab(
    lines: list[PlacedLine], rules: list[tuple[float, float, float, float]], page_code: str
) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(
        buf, pagesize=PAGE, invariant=1, pageCompression=1, initialFontName=_rl_font("latin")
    )
    c.setTitle("Synthetic script fixture")
    c.setAuthor("resecta-sample-doc (synthetic)")
    c.setSubject("SYNTHETIC TEST DOCUMENT - FICTIONAL DATA")
    for ln in lines:
        size = 10 if ln.key == "heading" else SIZE
        code = _line_code(ln, page_code)
        text = rtl.visual(ln.text) if ln.direction == "rtl" else ln.text
        pieces = runs(text, code) if code != "latin" else [(text, "latin")]
        width = sum(pdfmetrics.stringWidth(t, _rl_font(k), size) for t, k in pieces)
        x = ln.x - width if ln.align == "right" else ln.x
        for t, k in pieces:
            c.setFont(_rl_font(k), size)
            c.drawString(x, ln.y, t)
            x += pdfmetrics.stringWidth(t, _rl_font(k), size)
    for x0, y0, x1, y1 in rules:
        c.rect(x0, y0, x1 - x0, y1 - y0, stroke=0, fill=1)
    c.showPage()
    c.save()
    return buf.getvalue()


WRITERS = {"coretext": write_coretext, "pymupdf": write_pymupdf, "reportlab": write_reportlab}
