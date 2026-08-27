"""urla_a.py -- URLA Additional Borrower (1pp): Mateo Hartwell, resident alien -> ITIN.

The Additional Borrower form repeats Section 1 so the household PII spreads across members. The
co-applicant carries the ITIN + foreign passport; the savings account (12-digit, immune to the
10-digit phone shape) sits in Assets, separated from the masked 401k 'Account Number' line.

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
        "Uniform Residential Loan Application",
        "Additional Borrower (URLA-A) -- Section 1: Borrower Information.",
        "Freddie Mac Form 65 / Fannie Mae Form 1003",
    )

    # ---- Section 1a: Personal Information ----
    y = L.section_bar(rc, y, "Section 1a. Personal Information")
    y = C.frow(rc, y, G["occ_urlaa_01"])
    # ITIN (the resident-alien co-applicant legitimately uses an ITIN) -- long label on its own line
    rc.text(L.LEFT, y, G["occ_urlaa_03"].label_context, L.MED, 8, L.GRAY)
    y -= 12
    rc.value(G["occ_urlaa_03"], L.LEFT + 8, y, L.REG, 9.5, L.INK)
    y -= 16
    y = C.frow(rc, y, G["occ_urlaa_04"])
    # combined SSN/ITIN field (OCR variant) -- inconsistent separator -> ITIN backref fails (N-ITIN-3)
    y = C.frow(rc, y, G["N-ITIN-3"])
    # Contact (phone is here in 1a -- well away from the Assets accounts below)
    y = C.frow(rc, y, G["occ_urlaa_07"])
    y = C.frow(rc, y, G["occ_urlaa_08"])
    y = C.frow_multi(rc, y, G["occ_urlaa_05"])
    y = C.frow(rc, y, G["occ_urlaa_06"], step=18)

    # ---- Section 1b: Current Employment ----
    y = L.section_bar(rc, y, "Section 1b. Current Employment and Income")
    L.labeled(rc, L.LEFT, y, "Employer or Business Name:", P.EMPLOYER_NAME)
    y -= 14
    y = C.frow(rc, y, G["occ_urlaa_11"], step=14)
    L.labeled(rc, L.LEFT, y, "Position or Title:", "Logistics Coordinator")
    y -= 18

    # ---- Section 2: Financial Information -- Assets (savings 12-digit; 401k masked) ----
    y = L.section_bar(rc, y, "Section 2a. Assets -- Bank and Retirement Accounts")
    y = C.frow(rc, y, G["occ_urlaa_09"], step=14)
    y = C.fine_print(
        rc,
        y,
        [
            "List each retirement account separately. Enter the institution and the "
            "account identifier exactly as shown on the most recent paper notice."
        ],
        size=7,
    )
    y -= 4
    y = C.frow(rc, y, G["occ_urlaa_10"], step=18)

    # ---- Acknowledgment + ALL-CAPS printed name (should-fire) + signature date (MNF) ----
    y = L.heading(rc, y, "Acknowledgments and Agreements")
    y = C.fine_print(
        rc,
        y,
        [
            "Each Additional Borrower certifies that the information provided in this application is true "
            "and correct as of the date set forth opposite the signature. The Additional Borrower "
            "acknowledges that the information may be verified with the parties named in this application "
            "and consents to that verification.",
        ],
    )
    y -= 6
    y = C.frow(rc, y, G["occ_urlaa_02"], step=20, vfont=L.SEMI)
    ynext = C.signature_line(rc, y, "Additional Borrower Signature")
    L.field(rc, L.LEFT + 250, y, G["occ_urlaa_12"].label_context, G["occ_urlaa_12"])
    C.disclosures(rc, ynext - 6)

    C.page_footer(rc, "Page 3 of 12")
    rc.end_page()
