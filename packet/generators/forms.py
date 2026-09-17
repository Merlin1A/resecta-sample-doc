"""forms.py -- the C2 forms exhibits (capture packet): M3 a housing-assistance application with
boxed fields (the FLAT print master; its AcroForm twin is IM-15, a follow-on), and M4 a fax cover
sheet + transmittal (the fax-class master).

M3 zones (classifies .financial: income / employer / payment / deposit / credit): A boxed applicant
identity (name, hinted DOB, SSN, DL) · B contact (cell, email, current address) · C identity
verification (the clean 'Date of Birth:' surface) · D income and employment (financial vocabulary,
no PII) · E application id + signature + date signed. The SSN box sits > 5 tokens from every
(ssn, financial) negative phrase. M4 zones (classifies .generic: attachment / confidential /
message / forward / reply / reminder / regarding): A transmittal header (date sent, time, pages,
ref) · B recipient block (name, fax, phone) · C sender block (name, fax, phone) · D message +
confidentiality reminder · E account ref (an acct kw with no contiguous digit run).

Every character is printable ASCII.
"""

from __future__ import annotations

from .. import layout as L
from .. import occurrences_capture as OCC
from .. import personas as P
from . import _common as C

G = OCC.CAPTURE_BY_ID


def _boxed(rc, x0, y, w, h, occ, *, vsize=9):
    """A boxed field: caption = the occurrence's label_context, value inside. Returns nothing."""
    L.box_caption(rc, x0, y - h, x0 + w, y, occ.label_context)
    rc.value(occ, x0 + 6, y - h + 6, L.REG, vsize, L.INK)


def draw_m3(rc, base_page: int) -> None:
    rc.begin_page(base_page)
    y = L.form_title(
        rc,
        "Housing Assistance Application",
        "Complete every box in print. Boxed fields are read by the eligibility reviewer.",
        P.HOUSING_AUTHORITY,
    )

    # ---- Zone A: applicant identity (boxed) ----
    y = L.section_bar(rc, y, "Section 1. Applicant")
    colw = L.CONTENT_W / 2.0 - 6
    _boxed(rc, L.LEFT, y, colw, 26, G["occ_m3_01"])  # Applicant Name:
    _boxed(rc, L.LEFT + colw + 12, y, colw, 26, G["occ_m3_03"])  # Date of Birth (mm/dd/yyyy):
    y -= 32
    _boxed(rc, L.LEFT, y, colw, 26, G["occ_m3_04"])  # Social Security Number:
    _boxed(rc, L.LEFT + colw + 12, y, colw, 26, G["occ_m3_05"])  # Driver's License No:
    y -= 40

    # ---- Zone B: contact ----
    y = L.section_bar(rc, y, "Section 2. Contact")
    _boxed(rc, L.LEFT, y, colw, 26, G["occ_m3_06"])  # Cell Phone:
    _boxed(rc, L.LEFT + colw + 12, y, colw, 26, G["occ_m3_07"])  # Email:
    y -= 36
    y = C.frow_multi(rc, y, G["occ_m3_08"], step=10)  # Current Address:

    # ---- Zone C: identity verification (clean DOB surface) ----
    y = L.section_bar(rc, y, "Section 3. Identity Verification (reviewer use)")
    lx = rc.text(
        L.LEFT,
        y,
        "Photo identification presented and matched to the applicant.",
        L.REG,
        8.5,
        L.GRAY,
    )
    y -= 14
    y = C.frow(rc, y, G["occ_m3_02"], step=18)  # Date of Birth: (verified)

    # ---- Zone D: income and employment (financial vocabulary; no PII) ----
    y = L.section_bar(rc, y, "Section 4. Income and Employment")
    L.labeled(rc, L.LEFT, y, "Employer Name:", "Larkspur Dental Associates")
    L.labeled(rc, L.LEFT + 300, y, "Position:", "Front office coordinator")
    y -= 14
    L.labeled(rc, L.LEFT, y, "Monthly Gross Income:", "$2,940.00")
    L.labeled(rc, L.LEFT + 300, y, "Monthly Rent Payment:", "$1,150.00")
    y -= 14
    L.labeled(rc, L.LEFT, y, "Security Deposit Held:", "$1,150.00")
    L.labeled(rc, L.LEFT + 300, y, "Checking held at:", "Boise River Credit Union")
    y -= 18
    y = C.fine_print(
        rc,
        y,
        [
            "List every source of household income before deductions. Attach the two most recent pay "
            "statements from each employer and the most recent statement for each checking or savings "
            "account. Assistance is paid directly to the landlord as a monthly rent payment once "
            "eligibility is confirmed; the security deposit is not covered.",
            "Values on this sample application are fictional and disclosed so that software can be "
            "checked end to end. No real applicant, employer, or landlord is described.",
        ],
        size=7.5,
        leading=9.8,
    )
    y -= 6

    # ---- Zone E: application id + signature + date signed ----
    y = L.section_bar(rc, y, "Section 5. Certification")
    y = C.frow(rc, y, G["occ_m3_09"], step=22)  # Application ID:
    C.signature_line(rc, y, "Applicant Signature")
    L.field(rc, L.LEFT + 300, y, G["occ_m3_10"].label_context, G["occ_m3_10"])  # Date Signed:
    y -= 30
    C.disclosures(rc, y, title="Applicant Authorizations")

    C.page_footer(rc, "Page 1 of 1")
    rc.end_page()


def draw_m4(rc, base_page: int) -> None:
    rc.begin_page(base_page)
    rc.text(L.LEFT, L.TOP - 16, "FAX TRANSMITTAL", L.BOLD, 18, L.INK)
    rc.text(
        L.LEFT,
        L.TOP - 30,
        "Cover sheet -- a confidential attachment follows this page.",
        L.REG,
        8.5,
        L.GRAY,
    )
    rc.hrule(L.TOP - 38, L.LEFT, L.RIGHT, L.ACCENT, 1.2)
    y = L.TOP - 56

    # ---- Zone A: transmittal header ----
    L.field(rc, L.LEFT, y, G["occ_m4_07"].label_context, G["occ_m4_07"])  # Date Sent:
    L.labeled(rc, L.LEFT + 180, y, "Time Sent:", "14:32")
    L.labeled(rc, L.LEFT + 300, y, "Pages:", "3 (including this cover)")
    y -= 14
    L.field(rc, L.LEFT, y, G["occ_m4_08"].label_context, G["occ_m4_08"])  # Transmittal Ref:
    L.labeled(rc, L.LEFT + 300, y, "Regarding:", "housing application follow-up")
    y -= 22

    # ---- Zone B: recipient ----
    y = L.section_bar(rc, y, "To")
    y = C.frow(rc, y, G["occ_m4_01"], step=14)  # Recipient Name:
    L.labeled(rc, L.LEFT, y, "Organization:", P.HOUSING_AUTHORITY)
    y -= 14
    y = C.frow(rc, y, G["occ_m4_03"], step=14)  # Recipient Fax:
    y = C.frow(rc, y, G["occ_m4_04"], step=20)  # Recipient Phone:

    # ---- Zone C: sender ----
    y = L.section_bar(rc, y, "From")
    y = C.frow(rc, y, G["occ_m4_02"], step=14)  # Sender Name:
    y = C.frow(rc, y, G["occ_m4_05"], step=14)  # Sender Fax:
    y = C.frow(rc, y, G["occ_m4_06"], step=20)  # Sender Phone:

    # ---- Zone D: message + confidentiality reminder (generic vocabulary) ----
    y = L.section_bar(rc, y, "Message")
    y = C.fine_print(
        rc,
        y,
        [
            "Please forward the attached pages to the reviewer named above. The attachment contains the "
            "signed application and the two pay statements that were requested at the appointment. Reply "
            "by fax if any page arrives unreadable and the pages will be resent the same day.",
            "Reminder: this cover sheet and the attachment are confidential and intended only for the "
            "recipient named above. If this message reached you in error, notify the sender and destroy "
            "every page. Do not forward the attachment to anyone else.",
            "This transmittal is a synthetic sample prepared for software testing. Every name, fax "
            "number, and telephone number shown is fictional and disclosed in the accompanying manifest.",
        ],
        size=8.5,
        leading=11,
        gap=6,
    )
    y -= 12

    # ---- Zone E: account ref (acct kw, no contiguous digit run) ----
    rc.hrule(y + 6, L.LEFT, L.RIGHT, L.RULE, 0.5)
    y -= 8
    y = C.frow(rc, y, G["occ_m4_09"], step=14)  # Account Ref: 4471-0293
    rc.text(
        L.LEFT,
        y,
        "Internal routing of the attachment is by the reference shown; no reply is needed "
        "unless a page is missing.",
        L.REG,
        8,
        L.GRAY,
    )

    C.page_footer(rc, "Page 1 of 3")
    rc.end_page()
