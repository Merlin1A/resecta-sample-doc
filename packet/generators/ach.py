"""ach.py -- ACH / direct-deposit authorization (1pp). Routing HOME; Sablebrook Bank.

The hardest spacing page. Zones keep the load-bearing windows clean:
  A  Originating institution -- routing values WITH routing kw, NO account kw within +-5 (so the
     9-digit routing is not also captured as an account).
  B  Authorization paragraph -- a token wall (no routing/account/phone kw) separating A from C by
     well over 8 tokens.
  C  Crediting account -- account must-fires (12-digit, phone-immune) WITH acct kw, NO routing kw
     within +-8.
  D  Receiving-entry descriptor (INDN/DES/CO ID) + holder name/address; the 10-digit CO ID kept far
     from any phone kw.
  E  Form-control / reference / trace -- the watch routing (occ_ach_03) sits here with NO routing kw
     within +-8 (so it stays 0.50), plus the two no-keyword 9-/15-digit negatives.
  F  Confirmation panel (bottom, isolated) -- N-ACCT-1: the 10-digit account-as-phone negative, the
     ONLY phone keyword on the page, >80 chars from the CO ID.

Every character is printable ASCII.
"""

from __future__ import annotations

from .. import layout as L
from .. import occurrences as OCC
from . import _common as C

G = OCC.BY_ID


def draw(rc, base_page: int) -> None:
    rc.begin_page(base_page)
    y = L.form_title(
        rc,
        "Direct Deposit Authorization (ACH)",
        "Enroll or update electronic crediting of funds. Attach a voided check.",
        "Sablebrook Bank",
    )

    # ---- Zone A: originating financial institution (routing context) ----
    y = L.section_bar(rc, y, "Originating Financial Institution")
    L.labeled(rc, L.LEFT, y, "Bank Name:", "Sablebrook Bank")
    y -= 14
    y = C.frow(rc, y, G["occ_ach_01"], step=14)  # Routing Number / ABA #:
    y = C.frow(rc, y, G["occ_ach_02"], step=14)  # Origin ABA:
    y = C.frow(rc, y, G["occ_ach_04"], step=14)  # Intermediary Wire Routing: (checksum fail)
    y = C.frow(rc, y, G["N-RTN-1"], step=16)  # 2nd Intermediary / Returns Wire Routing:

    # ---- Zone B: authorization paragraph (token wall; NO routing/account/phone kw) ----
    y = C.fine_print(
        rc,
        y,
        [
            "I authorize the named institution to deposit funds electronically to the crediting entry "
            "shown below, and to reverse any entry made in error, until I revoke this instruction in "
            "writing. This authorization remains in effect for the entries described and may be ended by "
            "written notice delivered with reasonable time to act on it.",
        ],
    )
    y -= 6

    # ---- Zone C: crediting account (account context; 12-digit -> phone-immune) ----
    y = L.section_bar(rc, y, "Crediting Account")
    y = C.frow(rc, y, G["occ_ach_05"], step=14)  # Account Type Checking -- Acct No.:
    y = C.frow(rc, y, G["occ_ach_06"], step=16)  # Crediting Account Type -- Receiving Acct No.:

    # ---- Zone D: receiving-entry descriptor (INDN/DES/CO ID) + holder name + mailing address ----
    y = L.section_bar(rc, y, "Receiving Entry Detail")
    y = C.frow(rc, y, G["occ_ach_07"], step=14)  # Account Holder Name: (clean two-token MF)
    # the INDN descriptor lines (ALL-CAPS -> NLTagger miss, should-fire); DES + CO ID ride alongside.
    lx = rc.text(L.LEFT, y, G["occ_ach_08"].label_context, L.MED, 8, L.GRAY)  # INDN:
    rc.value(G["occ_ach_08"], lx + 4, y, L.SEMI, 9, L.INK)
    rc.text(L.LEFT + 220, y, "DES: PAYROLL", L.REG, 8.5, L.GRAY)
    y -= 13
    lx = rc.text(L.LEFT, y, G["occ_ach_09"].label_context, L.MED, 8, L.GRAY)  # INDN: (offset)
    rc.value(G["occ_ach_09"], lx + 4, y, L.SEMI, 9, L.INK)
    # CO ID on the same line as the second INDN -- no phone keyword anywhere near it.
    lx = rc.text(L.LEFT + 220, y, G["occ_ach_11"].label_context, L.MED, 8, L.GRAY)  # CO ID:
    rc.value(G["occ_ach_11"], lx + 4, y, L.REG, 9, L.INK)
    y -= 15
    y = C.frow_multi(rc, y, G["occ_ach_13"], step=10)  # Account Holder Mailing Address:

    # ---- Zone E: form-control / reference / trace (watch routing has NO routing kw within +-8) ----
    y = L.section_bar(rc, y, "Form Control")
    lx = rc.text(L.LEFT, y, G["occ_ach_03"].label_context, L.MED, 8, L.GRAY)  # Form Control No.:
    rc.value(G["occ_ach_03"], lx + 4, y, L.REG, 9, L.INK)
    lx = rc.text(L.LEFT + 230, y, G["N-INV-1"].label_context, L.MED, 8, L.GRAY)  # Reference No.:
    rc.value(G["N-INV-1"], lx + 4, y, L.REG, 9, L.INK)
    y -= 14
    lx = rc.text(L.LEFT, y, G["N-RTN-2"].label_context, L.MED, 8, L.GRAY)  # Trace:
    rc.value(G["N-RTN-2"], lx + 4, y, L.REG, 9, L.INK)
    y -= 18

    # ---- signature row: printed name (ALL-CAPS, watch) + authorization date (MNF) ----
    C.signature_line(rc, y, "Authorized Signature")
    lx = rc.text(L.LEFT + 250, y, G["occ_ach_10"].label_context, L.MED, 8, L.GRAY)  # Printed Name:
    rc.value(G["occ_ach_10"], lx + 4, y, L.SEMI, 9, L.INK)
    L.field(rc, L.LEFT + 430, y, G["occ_ach_12"].label_context, G["occ_ach_12"])  # Date:
    y -= 22

    # ---- Zone F: confirmation panel (isolated bottom) -- the ONLY phone kw, >80 chars from CO ID ----
    y = L.heading(rc, y, "Telephone Confirmation Panel")
    lx = rc.text(L.LEFT, y, "Daytime Phone for confirmation --", L.MED, 8, L.GRAY)  # phone kw
    lx = rc.text(lx + 6, y, G["N-ACCT-1"].label_context, L.MED, 8, L.GRAY)  # Account Number:
    rc.value(G["N-ACCT-1"], lx + 4, y, L.REG, 9, L.INK)  # 4100773265

    C.page_footer(rc, "Page 9 of 12")
    rc.end_page()
