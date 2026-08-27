"""w2.py -- W-2 Wage and Tax Statement, original layout (1pp). Employee Delia; employer Tannersworth.

IRS box grammar: Box a masked SSN (should-fire), Box b real EIN (must-fire), Box c employer name+
address, Boxes e/f employee name+address. The two negatives live in a bottom Notice section, >6
tokens from the real Box-b cell: occ_w2_06 (invalid-prefix EIN, with NO ein keyword within +-6 of it
as belt-and-suspenders) and N-SSN-1 (the Woolworth SSN -- validator hard-reject). N-EIN-1 sits in
Box 15 in its non-EIN shape (the shape gate rejects it even though 'employer' is adjacent, C1).

Every character is printable ASCII.
"""

from __future__ import annotations

from .. import layout as L
from .. import occurrences as OCC
from .. import personas as P
from . import _common as C

G = OCC.BY_ID


def draw(rc, base_page: int) -> None:
    rc.begin_page(base_page)
    y = L.form_title(
        rc,
        "Wage and Tax Statement (specimen)",
        "Original-layout specimen for software testing. Not an IRS form.",
        "Specimen W-2-LIKE",
    )
    y = C.frow(rc, y, G["occ_w2_07"], step=16)  # For Tax Year: bare span (MNF date)

    # ---- box grid (left column: a, e, f; right column: b, c) ----
    colR = L.LEFT + 300
    # Box a -- masked SSN (should-fire)
    L.box_caption(rc, L.LEFT, y - 28, colR - 12, y, G["occ_w2_01"].label_context)
    rc.value(G["occ_w2_01"], L.LEFT + 6, y - 22, L.REG, 10, L.INK)
    # Box b -- employer EIN (must-fire) -- the REAL Box-b cell
    L.box_caption(rc, colR, y - 28, L.RIGHT, y, G["occ_w2_02"].label_context)
    rc.value(G["occ_w2_02"], colR + 6, y - 22, L.REG, 10, L.INK)
    y -= 34
    # Box c -- employer name + address (org name rides as a sibling; address is the fire, single line)
    L.box_caption(rc, L.LEFT, y - 40, L.RIGHT, y, G["occ_w2_04"].label_context)
    rc.text(L.LEFT + 6, y - 16, P.EMPLOYER_NAME, L.REG, 9, L.INK)
    rc.value(G["occ_w2_04"], L.LEFT + 6, y - 28, L.REG, 9, L.INK)
    y -= 46
    # Box e/f -- employee name + address
    L.box_caption(rc, L.LEFT, y - 18, L.RIGHT, y, G["occ_w2_03"].label_context)
    rc.value(G["occ_w2_03"], L.LEFT + 6, y - 13, L.REG, 9.5, L.INK)
    y -= 24
    L.box_caption(rc, L.LEFT, y - 30, L.RIGHT, y, G["occ_w2_05"].label_context)
    rc.value_multiline(G["occ_w2_05"], L.LEFT + 6, y - 13, L.REG, 9, L.INK, 11)
    y -= 36

    # ---- state boxes row: Box 15 employer state ID (N-EIN-1 non-EIN shape; 'employer' adjacent OK) ----
    L.box_caption(rc, L.LEFT, y - 16, colR - 12, y, "15 State")
    rc.text(L.LEFT + 6, y - 12, "ID", L.REG, 9, L.INK)
    lx = rc.text(
        colR, y - 12, G["N-EIN-1"].label_context, L.MED, 8, L.GRAY
    )  # 15 Employer's state ID no.:
    rc.value(G["N-EIN-1"], lx + 4, y - 12, L.REG, 9.5, L.INK)
    y -= 26

    # ---- Notice to Employee (bottom; the two example negatives, far from the Box-b cell) ----
    y = L.heading(rc, y, "Notice to Employee")
    y = C.fine_print(
        rc,
        y,
        [
            "This specimen reproduces the box layout of a wage statement so software can be checked against "
            "the same field grammar a real statement uses. Every value shown is fictional and disclosed in "
            "the accompanying manifest.",
        ],
    )
    y -= 2
    # occ_w2_06: invalid-prefix example -- NO ein/box-b/employer keyword within +-6 tokens of it.
    rc.text(L.LEFT, y, G["N-SSN-1"].label_context, L.MED, 8, L.GRAY)  # Notice (Box a example):
    rc.value(G["N-SSN-1"], L.LEFT + 220, y, L.REG, 9, L.INK)  # 078-05-1120 (Woolworth)
    y -= 14
    rc.text(L.LEFT, y, "A sample state value is shown", L.REG, 8.5, L.GRAY)
    lx = rc.text(
        L.LEFT + 150, y, G["occ_w2_06"].label_context, L.REG, 8.5, L.GRAY
    )  # for example, 07-3300449.
    rc.value(G["occ_w2_06"], lx + 5, y, L.REG, 9, L.INK)
    y -= 12
    rc.text(L.LEFT, y, "Do not copy the sample values onto a real statement.", L.REG, 8.5, L.GRAY)
    y -= 16
    C.disclosures(rc, y, title="Employer and Employee Authorizations")

    C.page_footer(rc, "Page 10 of 12")
    rc.end_page()
