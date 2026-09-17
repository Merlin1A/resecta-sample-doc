"""mail.py -- the C2 mail exhibits (capture packet): M1 benefits-determination letter behind a #10
window-envelope USPS block, and M2 a utility bill with a remittance stub. Both classify .financial
(payment / income / deposit / account / statement vocabulary), so DOB runs label-anchored only.

M1 zones: A letterhead + office code + letter date (no phone, no address) · B the window block
(ALL-CAPS name + USPS lines, no label: the address assembler's arm) · C the reference block
(claimant name, DOB, benefit account, phone on file -- each label adjacent to its value) · D the
determination body (financial vocabulary; NO appeal/hearing/letter/information words) · E an
isolated footer line carrying the 10-digit reference number > 80 chars from every phone keyword.
M2 zones: A masthead + statement no. + due date · B customer block (name, account, service
address, phone on file) · C usage table -- the meter number sits > 5 tokens from any account kw ·
D charges (one '$' column) · E remittance stub (billing line, masked autopay card).

Every character is printable ASCII.
"""

from __future__ import annotations

from .. import layout as L
from .. import occurrences_capture as OCC
from .. import personas as P
from . import _common as C

G = OCC.CAPTURE_BY_ID


def draw_m1(rc, base_page: int) -> None:
    rc.begin_page(base_page)
    # ---- Zone A: letterhead (org only) ----
    rc.text(L.LEFT, L.TOP - 14, P.BENEFITS_OFFICE, L.BOLD, 14, L.ACCENT)
    rc.text(
        L.LEFT, L.TOP - 28, "Regional Processing Center -- Determination Unit", L.REG, 8.5, L.GRAY
    )
    rc.hrule(L.TOP - 36, L.LEFT, L.RIGHT, L.ACCENT, 1.2)
    y = L.TOP - 52
    L.field(rc, L.LEFT, y, G["occ_m1_07"].label_context, G["occ_m1_07"])  # Date: 08/11/2026
    L.field(
        rc, L.LEFT + 300, y, G["occ_m1_08"].label_context, G["occ_m1_08"]
    )  # Office Code: 0417-B
    y -= 26

    # ---- Zone B: #10 window-envelope block (USPS Pub 28 ALL-CAPS; no labels) ----
    C.window_block(rc, L.LEFT, y - 52, 250, 60)
    rc.value(G["occ_m1_01"], L.LEFT + 8, y - 8, L.MED, 9.5, L.INK)  # NADIA PETROVA
    rc.value_multiline(G["occ_m1_02"], L.LEFT + 8, y - 22, L.MED, 9.5, L.INK, 13)  # USPS lines
    y -= 70

    # ---- Zone C: reference block ----
    y = L.section_bar(rc, y, "Determination Reference")
    y = C.frow(rc, y, G["occ_m1_03"], step=14)  # Claimant Name:
    y = C.frow(rc, y, G["occ_m1_04"], step=14)  # Date of Birth:
    y = C.frow(rc, y, G["occ_m1_05"], step=14)  # Benefit Account No.:
    y = C.frow(rc, y, G["occ_m1_06"], step=18)  # Daytime Phone on file:

    # ---- Zone D: determination body (financial vocabulary; dense) ----
    y = L.heading(rc, y, "Notice of Monthly Benefit Determination", size=10)
    y = C.fine_print(
        rc,
        y,
        [
            "We have completed the review of your claim. Based on the income you reported and the "
            "verification received from your employer, your monthly benefit payment has been determined as "
            "shown below. The first payment will be issued by direct deposit to the benefit account "
            "referenced above, and a statement of each payment will be mailed at the start of every month.",
            "Monthly benefit payment: $1,284.00. Effective month: September 2026. Payment method: direct "
            "deposit. Deductions withheld: none. If your income changes, report the change within ten days "
            "so the payment can be adjusted before the next statement is issued.",
            "If you believe this determination is incorrect, you may ask for a reconsideration in writing "
            "within sixty days of the date shown above. Include the reference number printed at the foot of "
            "this notice and any wage or income documents that support your position. A written response "
            "will be mailed to the address on file.",
            "This notice was generated for software testing. Every name, date, account, and payment value "
            "shown is fictional and disclosed in the accompanying manifest; no real claimant is described.",
        ],
        size=8,
        leading=10.5,
        gap=5,
    )
    y -= 4
    rc.text(L.LEFT, y, "Sincerely,", L.REG, 8.5, L.GRAY)
    y -= 14
    rc.text(L.LEFT, y, "Determination Unit, Regional Processing Center", L.REG, 8.5, L.GRAY)
    y -= 30

    # ---- Zone E: isolated reference line (10-digit decoy; > 80 chars from every phone kw) ----
    rc.hrule(y + 8, L.LEFT, L.RIGHT, L.RULE, 0.5)
    rc.text(L.LEFT, y - 6, "Keep this notice for your files.", L.REG, 8, L.GRAY)
    lx = rc.text(
        L.LEFT + 250, y - 6, G["occ_m1_09"].label_context, L.MED, 8, L.GRAY
    )  # Reference No.
    rc.value(G["occ_m1_09"], lx + 4, y - 6, L.REG, 9, L.INK)  # 4471029386

    C.page_footer(rc, "Page 1 of 1")
    rc.end_page()


def draw_m2(rc, base_page: int) -> None:
    rc.begin_page(base_page)
    # ---- Zone A: masthead ----
    rc.text(L.LEFT, L.TOP - 14, P.UTILITY_NAME, L.BOLD, 14, L.ACCENT)
    rc.text(
        L.LEFT,
        L.TOP - 28,
        "Residential electric service -- monthly billing statement",
        L.REG,
        8.5,
        L.GRAY,
    )
    rc.hrule(L.TOP - 36, L.LEFT, L.RIGHT, L.ACCENT, 1.2)
    y = L.TOP - 52
    L.field(rc, L.LEFT, y, G["occ_m2_07"].label_context, G["occ_m2_07"])  # Statement No.
    L.field(rc, L.LEFT + 300, y, G["occ_m2_08"].label_context, G["occ_m2_08"])  # Due Date:
    y -= 24

    # ---- Zone B: customer block ----
    y = L.section_bar(rc, y, "Customer and Service Details")
    y = C.frow(rc, y, G["occ_m2_02"], step=14)  # Customer Name:
    y = C.frow(rc, y, G["occ_m2_01"], step=14)  # Account No.
    y = C.frow_multi(rc, y, G["occ_m2_03"], step=6)  # Service Address:
    y = C.frow(rc, y, G["occ_m2_04"], step=20)  # Telephone on file:

    # ---- Zone C: usage table (meter number > 5 tokens from any account kw) ----
    y = L.section_bar(rc, y, "Electric Usage This Period")
    cols = [
        (L.LEFT, "Previous Reading"),
        (L.LEFT + 120, "Current Reading"),
        (L.LEFT + 240, "kWh Used"),
        (L.LEFT + 320, "Rate Schedule"),
        (L.LEFT + 410, "Billing Days"),
    ]
    y = C.table_header(rc, y, cols)
    C.cell(rc, L.LEFT, y, "41,220")
    C.cell(rc, L.LEFT + 120, y, "42,006")
    C.cell(rc, L.LEFT + 240, y, "786")
    C.cell(rc, L.LEFT + 320, y, "RS-2")
    C.cell(rc, L.LEFT + 410, y, "31")
    y -= 16
    lx = rc.text(L.LEFT, y, G["occ_m2_06"].label_context, L.MED, 8, L.GRAY)  # Meter No.
    rc.value(G["occ_m2_06"], lx + 4, y, L.REG, 9, L.INK)  # 48213077
    rc.text(L.LEFT + 200, y, "Read type: actual (automated)", L.REG, 8.5, L.GRAY)
    y -= 22

    # ---- Zone D: charges ----
    y = L.section_bar(rc, y, "Charges and Balance")
    cols = [(L.LEFT, "Description"), (L.LEFT + 360, "Amount")]
    y = C.table_header(rc, y, cols)
    for desc, amt in (
        ("Previous balance", "$118.62"),
        ("Payment received -- thank you", "-$118.62"),
        ("Energy charge (786 kWh)", "$71.40"),
        ("Basic service charge", "$12.50"),
        ("Delivery and transmission", "$44.19"),
        ("Franchise fee and tax", "$14.08"),
    ):
        C.cell(rc, L.LEFT, y, desc)
        C.cell(rc, L.LEFT + 360, y, amt)
        y -= 13
    rc.hrule(y + 8, L.LEFT, L.RIGHT, L.RULE, 0.6)
    rc.text(L.LEFT, y - 4, "Total amount due by the due date shown above", L.SEMI, 9, L.INK)
    rc.text(L.LEFT + 360, y - 4, "$142.17", L.SEMI, 9, L.INK)
    y -= 24
    y = C.fine_print(
        rc,
        y,
        [
            "A late payment charge may be added to any balance that remains unpaid after the due date. "
            "Budget billing and paperless statements are available on request. This statement is a "
            "synthetic sample prepared for software testing; the customer, account, and usage values are "
            "fictional and disclosed in the accompanying manifest.",
        ],
        size=7.5,
        leading=9.8,
    )
    y -= 10

    # ---- Zone E: remittance stub ----
    rc.c.setStrokeColor(L.RULE)
    rc.c.setLineWidth(0.6)
    rc.c.setDash(4, 3)
    rc.c.line(L.LEFT, y, L.RIGHT, y)
    rc.c.setDash()
    y -= 16
    rc.text(
        L.LEFT, y, "Remittance Stub -- detach and return with your payment", L.SEMI, 9, L.ACCENT
    )
    y -= 16
    y = C.frow(rc, y, G["occ_m2_05"], step=14)  # Billing questions? Call
    y = C.frow(rc, y, G["occ_m2_09"], step=14)  # Autopay card on file: **** 4421
    rc.text(L.LEFT, y, "Amount enclosed:  $ ______________", L.REG, 9, L.INK)
    rc.text(L.LEFT + 300, y, "Make checks payable to the cooperative.", L.REG, 8, L.GRAY)

    C.page_footer(rc, "Page 1 of 1")
    rc.end_page()
