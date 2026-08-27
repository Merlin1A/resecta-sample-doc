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
