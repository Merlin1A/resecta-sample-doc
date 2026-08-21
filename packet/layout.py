"""layout.py -- shared geometry, fonts, palette, and form-furniture helpers for the packet
exhibits. Furniture (labels, headings, rules, boxes, instructions) is drawn through the
RecordingCanvas so its text is captured for the reading-order / token-distance checks.

A labeled field places the label IMMEDIATELY before its value on the same line, so the gating
keyword sits inside the value's context window. Every character is printable ASCII;
embedded-subset Inter only (font hygiene).
"""
from __future__ import annotations

from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import letter
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# ---- fonts (reuse the statement's prepared, tnum-frozen, embedded-subset Inter) -------------------
REG, MED, SEMI, BOLD = "Inter", "Inter-Medium", "Inter-SemiBold", "Inter-Bold"
_FONT_DIR = Path(__file__).resolve().parent.parent / "fonts"
_REGISTERED = False


def register_fonts() -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    for name, fn in {REG: "Inter-Regular.ttf", MED: "Inter-Medium.ttf",
                     SEMI: "Inter-SemiBold.ttf", BOLD: "Inter-Bold.ttf"}.items():
        pdfmetrics.registerFont(TTFont(name, str(_FONT_DIR / fn)))
    _REGISTERED = True


# ---- geometry (letter) ---------------------------------------------------------------------------
PW, PH = letter                 # 612 x 792 pt
M = 42                          # margin
LEFT, RIGHT = M, PW - M         # 42, 570
TOP = PH - M                    # 750
BOTTOM = M                      # 42
CONTENT_W = RIGHT - LEFT

# ---- palette (restrained, print-form look) -------------------------------------------------------
INK = HexColor("#161616")
GRAY = HexColor("#565656")
FAINT = HexColor("#8A8A8A")
RULE = HexColor("#B9B9B9")
ACCENT = HexColor("#2B3A55")    # muted slate (distinct from the statement's teal)
SHADE = HexColor("#EEF1F4")
LINEFILL = HexColor("#C9CFD6")


# --------------------------------------------------------------------------------------------------
# headings / rules / furniture
# --------------------------------------------------------------------------------------------------
def form_title(rc, title, subtitle="", agency=""):
    """Top-of-page form masthead. Returns the y cursor below it. The decorative agency text is drawn
    next to the title only if it fits (else dropped to the subtitle line, else omitted) -- never
    overlapping the title."""
    rc.text(LEFT, TOP - 14, title, BOLD, 15, INK)
    if agency:
        tw = pdfmetrics.stringWidth(title, BOLD, 15)
        aw = pdfmetrics.stringWidth(agency, MED, 8)
        if LEFT + tw + 18 + aw <= RIGHT:
            rc.rtext(RIGHT, TOP - 13, agency, MED, 8, FAINT)
        elif subtitle and LEFT + pdfmetrics.stringWidth(subtitle, REG, 8.5) + 18 + aw <= RIGHT:
            rc.rtext(RIGHT, TOP - 27, agency, MED, 8, FAINT)
        # else: omit (decorative)
    if subtitle:
        rc.text(LEFT, TOP - 27, subtitle, REG, 8.5, GRAY)
    rc.hrule(TOP - 34, LEFT, RIGHT, ACCENT, 1.2)
    return TOP - 50


def section_bar(rc, y, label):
    """A shaded section header bar (URLA-style). Returns the y cursor below it."""
    rc.c.setFillColor(SHADE)
    rc.c.rect(LEFT, y - 13, CONTENT_W, 16, stroke=0, fill=1)
    rc.text(LEFT + 5, y - 9.5, label, SEMI, 9.5, ACCENT)
    return y - 24


def heading(rc, y, label, size=10.5):
    rc.text(LEFT, y, label, SEMI, size, INK)
    rc.hrule(y - 4, LEFT, RIGHT, RULE, 0.6)
    return y - 16


def note(rc, y, text, x=LEFT, size=7.5, color=FAINT, font=REG):
    rc.text(x, y, text, font, size, color)
    return y - (size + 2.5)


def wrap(rc, x, y, s, width, font=REG, size=7.5, leading=10, color=GRAY):
    """Word-wrap a paragraph; returns the y cursor below the last line."""
    line = ""
    for word in s.split():
        trial = (line + " " + word).strip()
        if pdfmetrics.stringWidth(trial, font, size) <= width:
            line = trial
        else:
            rc.text(x, y, line, font, size, color)
            y -= leading
            line = word
    if line:
        rc.text(x, y, line, font, size, color)
        y -= leading
    return y


# --------------------------------------------------------------------------------------------------
# labeled fields -- the label sits immediately before the captured value (context-window adjacency)
# --------------------------------------------------------------------------------------------------
def field(rc, x, y, label, occ, *, vfont=REG, vsize=9, lsize=8, gap=4, label_color=GRAY,
          value_color=INK, label_font=MED):
    """Draw `label` then the occurrence's value to its right on one line; capture the value bbox.
    Returns the x just past the value (for same-line continuation)."""
    lx = rc.text(x, y, label, label_font, lsize, label_color)
    vx = rc.value(occ, lx + gap, y, vfont, vsize, value_color)
    return vx


def field_multiline(rc, x, y, label, occ, *, vfont=REG, vsize=9, lsize=8, label_color=GRAY,
                    value_color=INK, leading=12, label_font=MED):
    """Label then a multi-line value (one ordered span per line). Returns the y cursor below."""
    rc.text(x, y, label, label_font, lsize, label_color)
    y -= leading
    yy = rc.value_multiline(occ, x, y, vfont, vsize, value_color, leading)
    return yy


def labeled(rc, x, y, label, text, *, vfont=REG, vsize=9, lsize=8, gap=4, label_color=GRAY,
            value_color=INK, label_font=MED):
    """A NON-PII labeled value (employer name, plan year, etc.) -- recorded for reading order but
    not emitted as an occurrence."""
    lx = rc.text(x, y, label, label_font, lsize, label_color)
    rc.text(lx + gap, y, text, vfont, vsize, value_color)
    return y


def box_caption(rc, x0, y0, x1, y1, caption):
    """A bordered cell with a small top-left caption (IRS-box / KYC-cell look)."""
    rc.box(x0, y0, x1, y1, RULE, 0.7)
    rc.text(x0 + 4, y1 - 9, caption, MED, 6.5, FAINT)
