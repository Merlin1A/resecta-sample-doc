"""t1040.py -- 1040-like income tax return, ORIGINAL layout (2pp).

Carries the household SSNs (taxpayer/spouse-ITIN/two dependents) + the employer EIN. The three SSN/
ITIN negatives live here. C3 (load-bearing): the SSA-advertising negative occ_t1040_14 (987-65-4320)
sits in an ISOLATED note whose +-8-token neighborhood contains NO substring 'tin' (so no -ting/-tin-
word like routing/printing/reporting/continuing) and none of {itin,w-7,tin,taxpayer identification,
individual taxpayer,tax identification}; N-ITIN-2 is likewise keyword-starved.

Every character is printable ASCII.
"""
from __future__ import annotations

from .. import layout as L
from .. import occurrences as OCC
from . import _common as C

G = OCC.BY_ID


def _dep_row(rc, y, name_occ, ssn_occ, dob_occ):
    """One dependents-table row: Name | SSN | Date of Birth, each label its gating keyword."""
    lx = rc.text(L.LEFT, y, name_occ.label_context, L.MED, 8, L.GRAY)
    rc.value(name_occ, lx + 4, y, L.REG, 9, L.INK)
    lx = rc.text(L.LEFT + 200, y, ssn_occ.label_context, L.MED, 8, L.GRAY)
    rc.value(ssn_occ, lx + 4, y, L.REG, 9, L.INK)
    lx = rc.text(L.LEFT + 360, y, dob_occ.label_context, L.MED, 8, L.GRAY)
    rc.value(dob_occ, lx + 4, y, L.REG, 9, L.INK)
    return y - 16


def draw(rc, base_page: int) -> None:
    # ============================ PAGE 1 ============================
    rc.begin_page(base_page)
    y = L.form_title(rc, "U.S. Individual Income Tax Return (specimen)",
                     "Original-layout specimen for software testing. Not an IRS form.",
                     "Specimen 1040-LIKE")
    y = C.frow(rc, y, G["occ_t1040_15"], step=18)   # "For the calendar year:" bare span (MNF date)

    # ---- Filing: taxpayer + spouse ----
    y = L.section_bar(rc, y, "Filing Information")
    lx = rc.text(L.LEFT, y, G["occ_t1040_02"].label_context, L.MED, 8, L.GRAY)
    rc.value(G["occ_t1040_02"], lx + 4, y, L.REG, 9.5, L.INK)
    lx = rc.text(L.LEFT + 300, y, G["occ_t1040_01"].label_context, L.MED, 8, L.GRAY)
    rc.value(G["occ_t1040_01"], lx + 4, y, L.REG, 9.5, L.INK)
    y -= 16
    rc.text(L.LEFT, y, G["occ_t1040_04"].label_context, L.MED, 8, L.GRAY)        # Spouse's name:
    rc.value(G["occ_t1040_04"], L.LEFT + 90, y, L.REG, 9.5, L.INK)
    y -= 14
    rc.text(L.LEFT, y, G["occ_t1040_05"].label_context, L.MED, 8, L.GRAY)        # Spouse's ITIN (long)
    y -= 12
    rc.value(G["occ_t1040_05"], L.LEFT + 8, y, L.REG, 9.5, L.INK)
    y -= 16
    y = C.frow_multi(rc, y, G["occ_t1040_03"], step=8)                            # home address

    # ---- Dependents table ----
    y = L.section_bar(rc, y, "Dependents")
    y = _dep_row(rc, y, G["occ_t1040_06"], G["occ_t1040_07"], G["occ_t1040_08"])   # Lena
    y = _dep_row(rc, y, G["occ_t1040_09"], G["occ_t1040_10"], G["occ_t1040_11"])   # Theo
    y -= 6

    # ---- Employer / wage source ----
    y = L.section_bar(rc, y, "Wage and Tax Statement Source")
    L.labeled(rc, L.LEFT, y, "Employer Name:", "Tannersworth Freight Systems, Inc.")
    y -= 14
    rc.text(L.LEFT, y, G["occ_t1040_12"].label_context, L.MED, 8, L.GRAY)        # EIN label
    rc.value(G["occ_t1040_12"], L.LEFT + 210, y, L.REG, 9.5, L.INK)
    y -= 18

    # ---- Spouse-ITIN instruction footnote (negative: bad group; ITIN kw present but group invalid) ----
    y = C.frow(rc, y, G["N-ITIN-1"], step=16)
    y = C.fine_print(rc, y, [
        "Sample note: enter every taxpayer and dependent identifier exactly as issued. The values on "
        "this sample are fictional and disclosed; they are provided so software can be checked end "
        "to end without using a real person's data.",
    ])
    C.disclosures(rc, y - 6, title="Filing Notes and Authorizations")
    C.page_footer(rc, "Page 7 of 12")
    rc.end_page()

    # ============================ PAGE 2 ============================
    rc.begin_page(base_page + 1)
    y = C.continuation_header(rc, "U.S. Individual Income Tax Return (specimen) -- continued",
                              "Page 8 of 12")
    rc.text(L.LEFT, y, G["occ_t1040_13"].label_context, L.MED, 8, L.GRAY)        # page-2 SSN header
    rc.value(G["occ_t1040_13"], L.LEFT + 150, y, L.REG, 9.5, L.INK)
    y -= 22

    # ---- ISOLATED SSA-advertising note (C3): every word vetted free of substring 'tin' / ITIN kw ----
    y = L.heading(rc, y, "Sample Identifier Note")
    rc.text(L.LEFT, y, "Sample only -- do not enter. A sample value follows", L.REG, 8.5, L.GRAY)
    y -= 12
    lx = rc.text(L.LEFT, y, G["occ_t1040_14"].label_context, L.REG, 8.5, L.GRAY)  # "for example, 987-65-4320."
    rc.value(G["occ_t1040_14"], lx + 5, y, L.REG, 9.5, L.INK)
    y -= 12
    rc.text(L.LEFT, y, "Do not copy this sample value onto a real form.", L.REG, 8.5, L.GRAY)
    y -= 26

    # ---- keyword-starved reference number (N-ITIN-2) -- isolated from any ITIN keyword ----
    y = L.heading(rc, y, "Control Block")
    y = C.frow(rc, y, G["N-ITIN-2"], step=20)

    # ---- SSN-instruction footnote (N-SSN-2: area 900 reject) ----
    y = C.frow(rc, y, G["N-SSN-2"], step=24)

    # ---- signatures (two bare dates, MNF) ----
    y = L.heading(rc, y, "Sign Here")
    C.signature_line(rc, y, "Taxpayer Signature")
    L.field(rc, L.LEFT + 250, y, G["occ_t1040_16"].label_context, G["occ_t1040_16"])
    y -= 26
    C.signature_line(rc, y, "Spouse Signature")
    L.field(rc, L.LEFT + 250, y, G["occ_t1040_17"].label_context, G["occ_t1040_17"])
    y -= 14

    y = C.fine_print(rc, y, [
        "Under penalties applicable to this sample only, the persons named above declare that the "
        "fictional entries shown were prepared for software testing and disclosed in the accompanying "
        "manifest. No real taxpayer is described and no real return is filed.",
    ])
    C.disclosures(rc, y - 6, title="Taxpayer Authorizations")
    C.page_footer(rc, "Page 8 of 12")
    rc.end_page()
