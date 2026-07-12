"""urla_b.py -- URLA borrower (2pp): Delia R. Hartwell + loan originator Karen Delgado.
The anchor exhibit: it alone honestly carries name, labeled DOB, SSN, address, phone, email, account,
and credit card with genuine label vocabulary.

Page 1: Section 1a personal information + contact + addresses + Section 1b employment.
Page 2: Section 2 assets (12-digit bank accounts, phone-immune) and liabilities (credit cards under
"Account Number:"), kept in separate blocks; the textual "Born ..." DOB (C4) in a certification line;
Section 9 loan-originator block isolated from any phone keyword so the case-number phone negative
(occ_urlab_25) stays dropped.

Every character is printable ASCII.
"""
from __future__ import annotations

from .. import layout as L
from .. import occurrences as OCC
from . import _common as C

G = OCC.BY_ID


def _page1(rc, base_page):
    rc.begin_page(base_page)
    y = L.form_title(rc, "Uniform Residential Loan Application",
                     "Section 1: Borrower Information. Complete and sign before submitting.",
                     "Freddie Mac Form 65 / Fannie Mae Form 1003")

    # ---- Section 1a: Personal Information ----
    y = L.section_bar(rc, y, "Section 1a. Personal Information")
    y = C.frow(rc, y, G["occ_urlab_01"])               # Name (First, Middle, Last, Suffix): (MI -> SF)
    y = C.frow(rc, y, G["occ_urlab_09"])               # Social Security Number:
    y = C.frow(rc, y, G["occ_urlab_04"])               # Date of Birth (mm/dd/yyyy): numeric
    L.labeled(rc, L.LEFT, y, "Citizenship:", "U.S. Citizen")
    y -= 16

    # Contact -- phone block (phone kw boosts the three phone formats); email
    y = L.heading(rc, y, "Contact Information", size=9.5)
    y = C.frow(rc, y, G["occ_urlab_10"])               # Home Phone:
    y = C.frow(rc, y, G["occ_urlab_11"])               # Cell Phone:
    y = C.frow(rc, y, G["occ_urlab_12"])               # Work Phone:
    y = C.frow(rc, y, G["occ_urlab_13"], step=16)      # Email:

    # Addresses (multi-line via spans; no directional-with-period)
    y = C.frow_multi(rc, y, G["occ_urlab_06"], step=6)     # Current Address:
    y = C.frow_multi(rc, y, G["occ_urlab_06b"], step=6)    # Former Address: (CA)
    y = C.frow(rc, y, G["occ_urlab_07"], step=18)          # Mailing Address (P.O. Box)

    # ---- Section 1b: Current Employment ----
    y = L.section_bar(rc, y, "Section 1b. Current Employment and Income")
    L.labeled(rc, L.LEFT, y, "Employer or Business Name:", "Tannersworth Freight Systems, Inc.")
    y -= 14
    y = C.frow(rc, y, G["occ_urlab_08"], step=14)          # Employer Address:
    L.labeled(rc, L.LEFT, y, "Position or Title:", "Logistics Operations Coordinator")
    L.labeled(rc, L.LEFT + 300, y, "Gross Monthly Income:", "$6,200.00")
    y -= 18
    y = C.fine_print(rc, y, [
        "Provide the borrower's current employer and the gross monthly income before deductions. If "
        "the borrower has additional employment, attach a continuation with the same fields. Income "
        "shown on this sample is fictional and provided only so software can be checked end to end.",
    ])
    C.disclosures(rc, y - 6)
    C.page_footer(rc, "Page 1 of 12")
    rc.end_page()


def _page2(rc, base_page):
    rc.begin_page(base_page)
    y = C.continuation_header(rc, "Uniform Residential Loan Application -- continued", "Page 2 of 12")
    lx = rc.text(L.LEFT, y, G["occ_urlab_02"].label_context, L.MED, 8, L.GRAY)   # Borrower (printed):
    rc.value(G["occ_urlab_02"], lx + 5, y, L.REG, 9.5, L.INK)
    y -= 18

    # ---- Section 2a: Assets -- bank and retirement accounts (12-digit -> phone-immune) ----
    y = L.section_bar(rc, y, "Section 2a. Assets -- Bank and Retirement Accounts")
    y = C.frow(rc, y, G["occ_urlab_15"], step=14)      # Account #  (Checking)
    y = C.frow(rc, y, G["occ_urlab_16"], step=14)      # Acct No.   (401k)
    y = C.frow(rc, y, G["occ_urlab_17"], step=14)      # A/C        (Money Market)
    y = C.frow(rc, y, G["occ_urlab_18"], step=16)      # Account #  (masked, watch)

    # ---- Section 2b: Liabilities -- revolving credit (credit cards under "Account Number:") ----
    y = L.section_bar(rc, y, "Section 2b. Liabilities -- Revolving Credit and Tradelines")
    y = C.fine_print(rc, y, ["Enter each revolving tradeline with the full account identifier shown "
                             "on the most recent paper statement; mask only where the issuer masks."],
                     size=7)
    y -= 2
    y = C.frow(rc, y, G["occ_urlab_19"], step=13)      # Account Number: 4111 ... (Visa test PAN)
    y = C.frow(rc, y, G["occ_urlab_20"], step=13)      # Account Number: **** 1111 (masked)
    y = C.frow(rc, y, G["occ_urlab_21"], step=13)      # Account Number: 4111 ... 1112 (Luhn fail)
    y = C.frow(rc, y, G["N-CC-1"], step=13)            # Account Number: 9111 ... (bad IIN)
    y = C.frow(rc, y, G["N-CC-2"], step=13)            # Account Number: 5412 3456 7890 (short)
    y = C.frow(rc, y, G["occ_urlab_23"], step=14)      # Account / Tradeline -- SSN: XXX-XX-7438 (SF)
    y = C.frow(rc, y, G["occ_urlab_24"], step=18)      # Collateral Vehicle Plate No: (doctype-gated MNF)

    # ---- certification line carrying the textual "Born" DOB (C4 -> must-fire) ----
    lx = rc.text(L.LEFT, y, "I certify that the borrower named herein was", L.REG, 8.5, L.GRAY)
    bx = rc.text(lx + 4, y, G["occ_urlab_05"].label_context, L.MED, 8.5, L.GRAY)  # "Born"
    vx = rc.value(G["occ_urlab_05"], bx + 4, y, L.REG, 9, L.INK)                  # March 14, 1985
    rc.text(vx + 4, y, "and that the foregoing is true and correct.", L.REG, 8.5, L.GRAY)
    y -= 20

    # ---- Section 9: Loan Originator Information (no phone keyword here -> case-no phone stays dropped) ----
    y = L.section_bar(rc, y, "Section 9. Loan Originator Information")
    y = C.frow(rc, y, G["occ_urlab_03"], step=14)      # Loan Originator Name: Karen Delgado
    L.labeled(rc, L.LEFT, y, "NMLS ID:", "204878")
    y -= 14
    y = C.frow(rc, y, G["occ_urlab_14"], step=14)      # Email: k.delgado@example.com
    y = C.frow(rc, y, G["occ_urlab_25"], step=18)      # Loan File / Case No.: (negative-context phone)

    # ---- borrower signature + application date (bare date -> MNF) ----
    y = C.signature_line(rc, y, "Borrower Signature")
    L.field(rc, L.LEFT + 250, y + 20, G["occ_urlab_22"].label_context, G["occ_urlab_22"])   # Date:
    C.disclosures(rc, y - 6)

    C.page_footer(rc, "Page 2 of 12")
    rc.end_page()


def draw(rc, base_page: int) -> None:
    _page1(rc, base_page)
    _page2(rc, base_page + 1)
