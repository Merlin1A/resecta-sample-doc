"""hr.py -- the C4 HR exhibits (capture packet): H3 an employee file with the work-authorization
identity documents (I-9-like STRUCTURE only -- our own captions, never a pixel-accurate government
form, DR-4 SS9) and H4 a payroll / benefits enrollment sheet with a deposit instruction.

Both pages carry C4 content but must classify **.financial**, not .medical: that gate is what makes
occ_h3_11 (an MRN-shaped Employee ID) and occ_h4_13 (a VALID NPI) must-not-fire, since runsMRN is
medical-only and runsNPI is medical + foia only. Medical vocabulary is therefore STARVED on both --
no patient / clinic / physician / medication / history / intake / emergency / discharge word appears,
and the alternate contact is an "Alternate Contact", never an "Emergency Contact". The financial
class is carried by employee / employer / payroll / salary / wages / deduction / withholding / tax /
deposit, and on .financial the DOBDetector is label-anchored-ONLY, which is what suppresses the hire
date and the pay-period date while the labeled births fire.

H3 zones: A employee identity (name, label-anchored DOB, SSN -- the SSN box carries no 'account' /
'routing' / 'ein' word anywhere within its window because the page carries none at all) · B work
authorization documents (driver's licence, passport) · C contact (home address, home phone, personal
email) · D alternate contact (name + phone) · E payroll assignment -- the three must-not-fires
(MRN-shaped Employee ID, bare hire date, 4-digit cost center) with the financial vocabulary ·
F certification: a drawn signature stroke beside an exact "Signature:" block (an image-leg region).
H4 zones: A employee identity (name, Employee No., SSN -- kept clear of the deposit zone) · B pay
period and earnings (the bare pay-period date) · C deposit instruction -- routing WITH a routing
keyword and NO account keyword within +-5, then a token wall of well over eight keyword-free tokens,
then the account must-fire WITH an account keyword and NO routing keyword within +-8, plus its masked
twin · D dependents (two labeled births) · E benefit elections -- the plan code and the doctype-gated
NPI, which is kept > 80 chars from every 'number' / phone keyword so the bare phone shape stays
0.60 · F certification.

Every character is printable ASCII.
"""
from __future__ import annotations

from .. import layout as L
from .. import occurrences_capture as OCC
from .. import personas as P
from . import _common as C

G = OCC.CAPTURE_BY_ID


def _boxed(rc, x0, y, w, h, occ, *, vsize=9, tail=""):
    """A boxed field: caption = the occurrence's label_context, value inside, optional gray tail."""
    L.box_caption(rc, x0, y - h, x0 + w, y, occ.label_context)
    px = rc.value(occ, x0 + 6, y - h + 6, L.REG, vsize, L.INK)
    if tail:
        rc.text(px + 4, y - h + 6, tail, L.REG, 7.5, L.GRAY)


def draw_h3(rc, base_page: int) -> None:
    rc.begin_page(base_page)
    y = L.form_title(rc, "Employee File and Work Authorization",
                     "Structure-only specimen for software testing. Not a government or industry form.",
                     P.EMPLOYER_C4)
    colw = L.CONTENT_W / 2.0 - 6

    # ---- Zone A: employee identity (the labeled DOB fires; no account/routing/ein word on the page) ----
    y = L.section_bar(rc, y, "Section 1. Employee")
    _boxed(rc, L.LEFT, y, colw, 26, G["occ_h3_01"])                       # Employee Name:
    _boxed(rc, L.LEFT + colw + 12, y, colw, 26, G["occ_h3_02"])           # Date of Birth:
    y -= 32
    _boxed(rc, L.LEFT, y, colw, 26, G["occ_h3_03"])                       # Social Security No.:
    L.box_caption(rc, L.LEFT + colw + 12, y - 26, L.RIGHT, y, "Citizenship or work status")
    rc.text(L.LEFT + colw + 18, y - 20, "Citizen of the United States", L.REG, 9, L.INK)
    y -= 40

    # ---- Zone B: work authorization documents ----
    y = L.section_bar(rc, y, "Section 2. Identity and Work Authorization Documents")
    rc.text(L.LEFT, y, "The employee presented the documents below in person; the issuing state and "
            "the expiry were sighted and returned.", L.REG, 8, L.GRAY)
    y -= 15
    _boxed(rc, L.LEFT, y, colw, 26, G["occ_h3_04"], tail="Idaho, unexpired")     # Driver's License:
    _boxed(rc, L.LEFT + colw + 12, y, colw, 26, G["occ_h3_05"], tail="unexpired")  # Passport No:
    y -= 40

    # ---- Zone C: contact ----
    y = L.section_bar(rc, y, "Section 3. Contact")
    y = C.frow_multi(rc, y, G["occ_h3_06"], step=10)                      # Home Address:
    y = C.frow(rc, y, G["occ_h3_07"], step=14)                            # Home Phone:
    y = C.frow(rc, y, G["occ_h3_08"], step=20)                            # Personal Email:

    # ---- Zone D: alternate contact (NEVER "emergency" -- that word would pull the page medical) ----
    y = L.section_bar(rc, y, "Section 4. Alternate Contact")
    lx = rc.text(L.LEFT, y, G["occ_h3_09"].label_context, L.MED, 8.5, L.GRAY)     # Alternate Contact:
    px = rc.value(G["occ_h3_09"], lx + 4, y, L.REG, 9.5, L.INK)                   # Samuel Okafor
    rc.text(px + 4, y, "(spouse)", L.REG, 8, L.GRAY)
    y -= 14
    y = C.frow(rc, y, G["occ_h3_10"], step=20)                            # Contact Phone:

    # ---- Zone E: payroll assignment -- the three must-not-fires + the financial vocabulary ----
    y = L.section_bar(rc, y, "Section 5. Payroll Assignment")
    lx = rc.text(L.LEFT, y, G["occ_h3_11"].label_context, L.MED, 8.5, L.GRAY)     # Employee ID:
    rc.value(G["occ_h3_11"], lx + 4, y, L.REG, 9, L.INK)                          # EMP-0048213
    lx = rc.text(L.LEFT + 200, y, G["occ_h3_12"].label_context, L.MED, 8.5, L.GRAY)   # Hire Date:
    rc.value(G["occ_h3_12"], lx + 4, y, L.REG, 9, L.INK)                          # 03/16/2020
    lx = rc.text(L.LEFT + 380, y, G["occ_h3_13"].label_context, L.MED, 8.5, L.GRAY)   # Cost Center:
    rc.value(G["occ_h3_13"], lx + 4, y, L.REG, 9, L.INK)                          # 4410
    y -= 14
    L.labeled(rc, L.LEFT, y, "Employer:", P.EMPLOYER_C4)
    L.labeled(rc, L.LEFT + 300, y, "Pay Class:", "salaried, exempt")
    y -= 14
    L.labeled(rc, L.LEFT, y, "Annual Salary:", "$54,600.00")
    L.labeled(rc, L.LEFT + 300, y, "Payroll Cycle:", "semi-monthly")
    y -= 18
    y = C.fine_print(rc, y, [
        "Each payroll deduction is applied to gross salary in the sequence set by the plan and by "
        "law. Withholding is calculated from the current federal and state tax tables and from the "
        "elections on file; a change to those elections takes effect on the first full pay cycle "
        "after it is filed with the payroll office.",
        "Wages, the compensation total, and every withholding shown on this file are fictional and "
        "disclosed so that software can be checked end to end. No real employee or employer is "
        "described.",
    ], size=7.5, leading=9.8)
    y -= 8

    # ---- Zone F: certification (the drawn stroke is an image-leg region, never text) ----
    y = L.section_bar(rc, y, "Section 6. Certification")
    rc.text(L.LEFT, y, "The employee certifies that the identity documents presented are genuine and "
            "relate to the employee named above.", L.REG, 8.5, L.GRAY)
    y -= 20
    rc.text(L.LEFT, y, G["occ_h3_14"].label_context, L.MED, 9, L.GRAY)            # Signature:
    C.signature_stroke(rc, G["occ_h3_14"], L.LEFT + 70, y - 4)
    rc.text(L.LEFT + 230, y, "Date signed on file with the payroll office.", L.REG, 8, L.FAINT)
    y -= 34

    # ---- employer notices: OCR surface for the capture. Vetted against every keyword set -- no
    # 'records' / 'request' / 'ask' / 'privacy' / 'information' / 'personnel' (foia), no medical or
    # court or generic keyword, no PII shape, no clean two-token Title-Case name. ----
    y = L.heading(rc, y, "Employer Notices", size=9.5)
    y = C.fine_print(rc, y, [
        "Retention. This file is retained for the period set by the employer's schedule and by "
        "applicable law, and is held apart from the payroll ledger. A copy is provided to the "
        "employee in writing by the payroll office.",
        "Verification of Employment. A third party seeking to verify wages or the employment term "
        "is directed to the payroll office, and is given only the term of employment and the "
        "compensation total unless the employee consents in writing to more.",
        "Accuracy. The employee certifies that every entry above is true and complete, and agrees "
        "to notify the payroll office promptly of a change to a name, an address, or a work "
        "authorization document. An intentional misstatement may end consideration of continued "
        "employment.",
    ], size=7.5, leading=9.8)

    C.page_footer(rc, "Page 1 of 1")
    rc.end_page()


def draw_h4(rc, base_page: int) -> None:
    rc.begin_page(base_page)
    y = L.form_title(rc, "Payroll and Benefits Enrollment",
                     "Structure-only specimen for software testing. Not a government or industry form.",
                     P.EMPLOYER_C4)

    # ---- Zone A: employee identity (SSN kept well clear of the deposit zone) ----
    y = L.section_bar(rc, y, "Section 1. Employee")
    lx = rc.text(L.LEFT, y, G["occ_h4_01"].label_context, L.MED, 8.5, L.GRAY)     # Employee:
    rc.value(G["occ_h4_01"], lx + 4, y, L.REG, 9.5, L.INK)                        # Rosalind Okafor
    lx = rc.text(L.LEFT + 220, y, G["occ_h4_10"].label_context, L.MED, 8.5, L.GRAY)   # Employee No.
    rc.value(G["occ_h4_10"], lx + 4, y, L.REG, 9, L.INK)                          # 48213
    lx = rc.text(L.LEFT + 360, y, G["occ_h4_02"].label_context, L.MED, 8.5, L.GRAY)   # SSN:
    rc.value(G["occ_h4_02"], lx + 4, y, L.REG, 9, L.INK)                          # 487-62-1930
    y -= 14
    L.labeled(rc, L.LEFT, y, "Employer:", P.EMPLOYER_C4)
    L.labeled(rc, L.LEFT + 300, y, "Pay Class:", "salaried, exempt")
    y -= 22

    # ---- Zone B: pay period and earnings (the bare date; suppressed on .financial) ----
    y = L.section_bar(rc, y, "Section 2. Pay Period and Earnings")
    lx = rc.text(L.LEFT, y, G["occ_h4_12"].label_context, L.MED, 8.5, L.GRAY)     # Pay Period Ending:
    px = rc.value(G["occ_h4_12"], lx + 4, y, L.REG, 9, L.INK)                     # 08/15/2026
    rc.text(px + 12, y, "semi-monthly cycle; gross wages before every deduction.", L.REG, 8.5, L.GRAY)
    y -= 15
    cols = [(L.LEFT, "Earnings"), (L.LEFT + 160, "Current"), (L.LEFT + 250, "Year to date"),
            (L.LEFT + 370, "Withholding"), (L.LEFT + 470, "Current")]
    y = C.table_header(rc, y, cols)
    C.cell(rc, L.LEFT, y, "regular salary")
    C.cell(rc, L.LEFT + 160, y, "$2,275.00")
    C.cell(rc, L.LEFT + 250, y, "$36,400.00")
    C.cell(rc, L.LEFT + 370, y, "federal income tax")
    C.cell(rc, L.LEFT + 470, y, "$271.40")
    y -= 13
    C.cell(rc, L.LEFT, y, "shift premium")
    C.cell(rc, L.LEFT + 160, y, "$85.00")
    C.cell(rc, L.LEFT + 250, y, "$1,360.00")
    C.cell(rc, L.LEFT + 370, y, "state income tax")
    C.cell(rc, L.LEFT + 470, y, "$103.10")
    y -= 22

    # ---- Zone C: deposit instruction. Routing WITH a routing kw and NO acct kw within +-5; a token
    # wall of well over eight keyword-free tokens; then the account WITH an acct kw and NO routing kw
    # within +-8. The wall carries no 'account' / 'acct' / 'a/c' / 'routing' / 'aba' / 'ach' (the
    # substring, so no "each" / "attach" / "reach") / 'transit' / 'direct deposit'. ----
    y = L.section_bar(rc, y, "Section 3. Deposit Instruction")
    L.labeled(rc, L.LEFT, y, "Depositing institution:", "Boise River Credit Union")
    L.labeled(rc, L.LEFT + 300, y, "Type:", "checking")
    y -= 14
    lx = rc.text(L.LEFT, y, G["occ_h4_03"].label_context, L.MED, 8.5, L.GRAY)     # Routing Number:
    px = rc.value(G["occ_h4_03"], lx + 4, y, L.REG, 9, L.INK)                     # 124007112
    rc.text(px + 8, y, "-- nine digits, direct deposit line, verified at enrollment.",
            L.REG, 8.5, L.GRAY)
    y -= 15
    y = C.fine_print(rc, y, [
        "Funds are credited electronically to the crediting entry shown below on the regular payroll "
        "cycle, and any entry made in error is reversed on the following cycle. This instruction "
        "stays in effect until the employee files a written replacement with the payroll office, "
        "and the employer will give notice before the first pay cycle it governs.",
    ], size=8, leading=10.5)
    y -= 4
    lx = rc.text(L.LEFT, y, G["occ_h4_04"].label_context, L.MED, 8.5, L.GRAY)     # Account Number:
    rc.value(G["occ_h4_04"], lx + 4, y, L.REG, 9, L.INK)                          # 640081127735
    lx = rc.text(L.LEFT + 250, y, G["occ_h4_05"].label_context, L.MED, 8.5, L.GRAY)   # Account on file:
    rc.value(G["occ_h4_05"], lx + 4, y, L.REG, 9, L.INK)                          # XXXXXX7735 (masked)
    y -= 22

    # ---- Zone D: dependents (two labeled births; both fire on the .financial label-anchored path) ----
    y = L.section_bar(rc, y, "Section 4. Dependents Enrolled")
    lx = rc.text(L.LEFT, y, G["occ_h4_06"].label_context, L.MED, 8.5, L.GRAY)     # Dependent:
    rc.value(G["occ_h4_06"], lx + 4, y, L.REG, 9.5, L.INK)                        # Ezra Okafor
    lx = rc.text(L.LEFT + 220, y, G["occ_h4_07"].label_context, L.MED, 8.5, L.GRAY)   # Date of Birth:
    px = rc.value(G["occ_h4_07"], lx + 4, y, L.REG, 9, L.INK)                     # 04/09/2015
    rc.text(px + 10, y, "child", L.REG, 8.5, L.GRAY)
    y -= 14
    lx = rc.text(L.LEFT, y, G["occ_h4_08"].label_context, L.MED, 8.5, L.GRAY)     # Dependent:
    rc.value(G["occ_h4_08"], lx + 4, y, L.REG, 9.5, L.INK)                        # Amara Okafor
    lx = rc.text(L.LEFT + 220, y, G["occ_h4_09"].label_context, L.MED, 8.5, L.GRAY)   # Date of Birth:
    px = rc.value(G["occ_h4_09"], lx + 4, y, L.REG, 9, L.INK)                     # 12/30/2018
    rc.text(px + 10, y, "child", L.REG, 8.5, L.GRAY)
    y -= 22

    # ---- Zone E: benefit elections. The NPI is a VALID enumerated identifier that must NOT fire:
    # runsNPI is medical + foia only, so the detector never runs here, and the 10-digit run is kept
    # > 80 chars from every phone keyword ('phone', 'tel', 'cell', 'fax', 'mobile', 'number') so the
    # bare phone shape stays at 0.60, below the 0.70 gate. ----
    y = L.section_bar(rc, y, "Section 5. Benefit Elections")
    lx = rc.text(L.LEFT, y, G["occ_h4_11"].label_context, L.MED, 8.5, L.GRAY)     # Plan:
    px = rc.value(G["occ_h4_11"], lx + 4, y, L.REG, 9, L.INK)                     # MED-HDHP-2
    rc.text(px + 10, y, "high deductible with a savings election; employee plus family tier.",
            L.REG, 8.5, L.GRAY)
    y -= 14
    lx = rc.text(L.LEFT, y, G["occ_h4_13"].label_context, L.MED, 8.5, L.GRAY)     # Primary Care Provider NPI:
    px = rc.value(G["occ_h4_13"], lx + 4, y, L.REG, 9, L.INK)                     # 1497734081
    rc.text(px + 10, y, "as elected by the employee at enrollment.", L.REG, 8.5, L.GRAY)
    y -= 16
    y = C.fine_print(rc, y, [
        "The election above sets the payroll deduction for the enrollment year and cannot be changed "
        "until the open enrollment window opens again, except on a qualifying life event filed with "
        "the employer within thirty days of the event.",
    ], size=7.5, leading=9.8)
    y -= 8

    # ---- Zone F: certification ----
    rc.hrule(y + 8, L.LEFT, L.RIGHT, L.RULE, 0.6)
    rc.text(L.LEFT, y, "The employee authorizes the deduction shown and certifies that every "
            "dependent listed is eligible under the plan.", L.REG, 8.5, L.GRAY)
    y -= 18
    C.signature_line(rc, y, "Employee Signature")
    rc.text(L.LEFT + 250, y, "Filed with the payroll office; retained for the plan year.",
            L.REG, 8, L.FAINT)
    y -= 26

    # ---- plan notices: OCR surface for the capture. No 'account' / 'routing' / 'aba' / 'ach'
    # (substring) / 'transit' / 'direct deposit' word appears here, so nothing in this block can
    # reach back into the section-3 windows; and no phone positive sits within 80 chars of the NPI.
    y = L.heading(rc, y, "Plan Notices", size=9.5)
    y = C.fine_print(rc, y, [
        "Deduction Authority. The deduction shown is applied to gross wages on the regular payroll "
        "cycle and continues until the employee files a written change with the payroll office. The "
        "employer will give notice before the first cycle a change governs.",
        "Tax Treatment. The premium for the elected plan is withheld before federal income tax "
        "where the plan allows, which lowers taxable wages for the year. The withholding total "
        "shown above is an estimate; the year-end wage statement is the record of what was "
        "actually withheld.",
    ], size=7.5, leading=9.8)
    y -= 6
    rc.text(L.LEFT, y, "Synthetic enrollment prepared for software testing; every person, identifier, "
            "wage, and date shown is fictional and disclosed.", L.REG, 7.5, L.FAINT)

    C.page_footer(rc, "Page 1 of 1")
    rc.end_page()
