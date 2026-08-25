"""_common.py -- shared exhibit furniture (all PII-FREE so it never injects an un-manifested fire).

Furniture text must contain NO clean two-token name, SSN/9-digit/phone/email/account shape, or (on the
VEH .generic page) any MM/DD/YYYY or month-name date. The acceptance suite scans reconstructed page
text and asserts every PII-shaped match is a manifest value, so accidental injection is caught.

Every character is printable ASCII.
"""

from __future__ import annotations

from .. import layout as L

ROW = 15  # default vertical step between stacked single-line fields


def frow(rc, y, occ, *, x=None, step=ROW, **kw):
    """Draw a single-line labeled field (label_context + captured value) and advance the cursor."""
    L.field(rc, L.LEFT if x is None else x, y, occ.label_context, occ, **kw)
    return y - step


def frow_multi(rc, y, occ, *, x=None, step=4, **kw):
    """Draw a multi-line labeled field (one ordered span per line) and advance the cursor."""
    yy = L.field_multiline(rc, L.LEFT if x is None else x, y, occ.label_context, occ, **kw)
    return yy - step


def page_footer(rc, page_label: str):
    """A one-line disclosure footer drawn on every page."""
    rc.hrule(L.BOTTOM + 14, L.LEFT, L.RIGHT, L.RULE, 0.5)
    rc.text(
        L.LEFT,
        L.BOTTOM + 4,
        "Synthetic sample for software testing -- not real; values fictional and disclosed.",
        L.REG,
        6.5,
        L.FAINT,
    )
    rc.rtext(L.RIGHT, L.BOTTOM + 4, page_label, L.REG, 6.5, L.FAINT)


def continuation_header(rc, title: str, page_label: str):
    """Top-of-page continuation banner for multi-page exhibits. NO person name (would be an
    un-manifested name fire). Returns the y cursor below it."""
    rc.text(L.LEFT, L.TOP - 11, title, L.SEMI, 9, L.GRAY)
    rc.rtext(L.RIGHT, L.TOP - 11, page_label, L.MED, 8, L.FAINT)
    rc.hrule(L.TOP - 16, L.LEFT, L.RIGHT, L.ACCENT, 0.8)
    return L.TOP - 30


def fine_print(
    rc, y, paragraphs, *, x=None, width=None, size=7.0, leading=9.2, gap=3.0, color=None
):
    """Render a list of dense instructional paragraphs (drives up text-leg coverage; genre-honest
    for forms). Returns the y cursor below the last paragraph."""
    x = L.LEFT if x is None else x
    width = L.CONTENT_W if width is None else width
    color = L.GRAY if color is None else color
    for para in paragraphs:
        y = L.wrap(rc, x, y, para, width, L.REG, size, leading, color)
        y -= gap
    return y


def two_column_fine_print(rc, y, paragraphs, *, size=6.8, leading=8.8, gutter=16):
    """Two-column dense fine print (form back-page look). Returns the lower of the two column
    cursors."""
    colw = (L.CONTENT_W - gutter) / 2.0
    mid = len(paragraphs) // 2 + len(paragraphs) % 2
    left = fine_print(rc, y, paragraphs[:mid], x=L.LEFT, width=colw, size=size, leading=leading)
    right = fine_print(
        rc, y, paragraphs[mid:], x=L.LEFT + colw + gutter, width=colw, size=size, leading=leading
    )
    return min(left, right)


# Original financial-genre boilerplate (dense back-page fill -> exercises the >0.95 text-leg path).
# Vetted: NO 'ach'/'aba'/'routing'/'transit' substring (so it is safe even near a routing value -- note
# "every" not "each"), NO PII shape (no digit run / SSN / phone / email), NO denylisted brand. Financial
# keywords (account/statement/fee) are fine on the financial exhibits; NOT used on the VEH page.
DISCLOSURES = [
    "Privacy and Information Use. The information collected on this application is used to evaluate the "
    "request, to verify the statements made, and to service the resulting relationship. Every applicant "
    "authorizes the named parties to obtain and exchange the information needed to complete and service "
    "the request, and to retain a copy of this application whether or not it is approved.",
    "Electronic Records Consent. By signing, the applicant consents to receive disclosures and "
    "statements electronically at the electronic address provided, and confirms the ability to open and "
    "retain documents in electronic form. Consent may be withdrawn by written notice, after which paper "
    "copies are provided at no added cost to the applicant.",
    "Accuracy of Statements. Every applicant represents that the statements made are true and complete "
    "and understands that an intentional misstatement may delay or end consideration of the request. The "
    "applicant agrees to notify the named parties promptly of any material change before the request is "
    "final.",
    "Servicing and Assignment. The relationship resulting from an approved request may be serviced by "
    "the named party or by a successor. The applicant will be notified of any change in the party that "
    "collects payments and maintains the account, and the posted terms will not change solely because "
    "servicing is reassigned.",
    "Fees and Charges. A schedule of fees that may apply is provided separately. Fees are assessed only "
    "as described in that schedule and in the agreement that governs the account. Questions about a "
    "specific fee may be directed to the servicing contact named in the most recent statement.",
    "Record Retention. A copy of this application and the supporting documents is retained for the "
    "period set by the governing agreement. The applicant may request a copy of the retained documents "
    "by contacting the servicing party in writing at the posted business address.",
]


def disclosures(rc, y, *, title="Disclosures and Authorizations", paragraphs=None):
    """Dense two-column back-page disclosures to fill whitespace (text-leg coverage). Returns the y
    cursor below."""
    if y < L.BOTTOM + 70:
        return y
    y = L.heading(rc, y, title, size=9.5)
    return two_column_fine_print(rc, y, paragraphs or DISCLOSURES, size=6.6, leading=8.4)


def signature_line(rc, y, label, width=210):
    """A blank signature rule + caption (NO printed name -- that would be an un-manifested fire)."""
    rc.hrule(y, L.LEFT, L.LEFT + width, L.LINEFILL, 0.7)
    rc.text(L.LEFT, y - 9, label, L.REG, 7, L.FAINT)
    return y - 20


# ==================================================================================================
# Capture-packet furniture (P1.8 / T1.3(a)). All PII-FREE; every character printable ASCII.
# ==================================================================================================
def table_header(rc, y, cols, *, size=7.5, color=None, rule=True):
    """Draw a row of column captions. `cols` = [(x, caption), ...]. Returns the y below the rule."""
    color = L.ACCENT if color is None else color
    for x, cap in cols:
        rc.text(x, y, cap, L.SEMI, size, color)
    if rule:
        rc.hrule(y - 4, L.LEFT, L.RIGHT, L.RULE, 0.6)
    return y - 15


def cell(rc, x, y, s, *, font=None, size=8.5, color=None):
    """One plain (non-PII) table cell."""
    return rc.text(x, y, s, L.REG if font is None else font, size, L.INK if color is None else color)


def numbered_margin(rc, top_y, bottom_y, n=28, x_num=None, x_rule=None):
    """Pleading-paper furniture: `n` numbered lines down the left margin and the double vertical
    rule. Returns (leading, [baseline_y ...]) so the caller can place text on the numbered lines."""
    x_num = L.LEFT if x_num is None else x_num
    x_rule = L.LEFT + 22 if x_rule is None else x_rule
    leading = (top_y - bottom_y) / float(n - 1)
    ys = [top_y - i * leading for i in range(n)]
    for i, yy in enumerate(ys):
        rc.rtext(x_num + 12, yy, str(i + 1), L.REG, 7, L.FAINT)
    rc.c.setStrokeColor(L.RULE)
    rc.c.setLineWidth(0.6)
    rc.c.line(x_rule, top_y + leading * 0.6, x_rule, bottom_y - leading * 0.6)
    rc.c.line(x_rule + 3, top_y + leading * 0.6, x_rule + 3, bottom_y - leading * 0.6)
    rc.c.line(L.RIGHT - 4, top_y + leading * 0.6, L.RIGHT - 4, bottom_y - leading * 0.6)
    return leading, ys


def stamp_box(rc, x, y, w, h, lines, *, size=10):
    """A bordered 'stamp' (exhibit / received) -- heavier rule, centered caption lines."""
    rc.box(x, y, x + w, y + h, L.INK, 1.4)
    yy = y + h - size - 4
    for ln in lines:
        rc.c.setFillColor(L.INK)
        rc.c.setFont(L.BOLD, size)
        rc.c.drawCentredString(x + w / 2.0, yy, ln)
        rc.draws.append((rc.page, yy, x + 4, ln))
        yy -= size + 3


def window_block(rc, x, y, w, h):
    """The #10 window-envelope address block: a dashed box the mail class prints into."""
    rc.c.setStrokeColor(L.LINEFILL)
    rc.c.setLineWidth(0.6)
    rc.c.setDash(3, 3)
    rc.c.rect(x, y, w, h, stroke=1, fill=0)
    rc.c.setDash()


def barcode_code128(rc, occ, x, y, *, bar_height=28, bar_width=0.9):
    """Draw a REAL Code 128 symbol (vector bars, no human-readable line) encoding `occ.value` and
    emit an `image`-leg ground-truth region for it. Returns the symbol width in points."""
    from reportlab.graphics.barcode import code128
    bc = code128.Code128(occ.value_text, barHeight=bar_height, barWidth=bar_width,
                         humanReadable=False, quiet=True)
    bc.drawOn(rc.c, x, y)
    rc.region_value(occ, x, y, x + bc.width, y + bar_height)
    return bc.width


def signature_stroke(rc, occ, x, y, w=120, h=22):
    """A deterministic handwriting-like stroke (two cubic beziers) to the right of a 'Signature:'
    label -- the DRAW-3 heuristic's candidate region. Emits an `image`-leg ground-truth region."""
    c = rc.c
    c.setStrokeColor(L.INK)
    c.setLineWidth(1.3)
    c.setLineCap(1)
    base = y + 4
    p = c.beginPath()
    p.moveTo(x + 2, base + 2)
    p.curveTo(x + 10, base + h, x + 22, base - 6, x + 34, base + 8)
    p.curveTo(x + 44, base + h - 2, x + 52, base - 4, x + 62, base + 6)
    p.curveTo(x + 74, base + h, x + 86, base - 8, x + 98, base + 4)
    p.curveTo(x + 106, base + 12, x + 112, base + 2, x + w - 4, base + 6)
    c.drawPath(p, stroke=1, fill=0)
    c.setLineWidth(0.7)
    c.line(x, y, x + w, y)
    rc.region_value(occ, x, y - 2, x + w, y + h + 2)
    return x + w
