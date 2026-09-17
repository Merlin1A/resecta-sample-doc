"""court.py -- the C3 court / FOIA exhibits (capture packet): K1 a pleading-paper caption page,
K2 a deposition exhibit page with Bates + stamp, K3 a FOIA release with (b)(6) / (b)(7)(C) bars
over synthetic names (the already-redacted-input case), K4 a docket / judgment sheet.

Doctype: K1/K2/K4 classify .court (court / plaintiff / defendant / complaint / docket ... plus the
case_caption_v and docket_number bonuses), K3 classifies .foia (request / records / exemption /
withheld ... plus the exemption_citation and foia_header bonuses). On all four the FULL
DOBDetector runs, so every bare date is kept > 80 chars from any DOB label and the one labeled DOB
per page sits in its own block. Names: Title-Case names follow a legal-prefix word (Plaintiff /
Defendant / Judge / Deponent) or a label the NLTagger host probe tags; party names in the K1
caption are ALL-CAPS (should-fire). Org names after a prefix word are ALL-CAPS or parenthesised so
the prefix pass cannot absorb them. K3's redacted values are bars with NO text underneath.

Every character is printable ASCII.
"""

from __future__ import annotations

from .. import layout as L
from .. import occurrences_capture as OCC
from .. import personas as P
from . import _common as C

G = OCC.CAPTURE_BY_ID
TX = L.LEFT + 34  # pleading-paper text start (right of the double rule)


def _line(rc, y, s, *, font=None, size=9, color=None, x=None):
    rc.text(
        TX if x is None else x,
        y,
        s,
        L.REG if font is None else font,
        size,
        L.INK if color is None else color,
    )


def draw_k1(rc, base_page: int) -> None:
    rc.begin_page(base_page)
    leading, ys = C.numbered_margin(rc, L.TOP - 18, L.BOTTOM + 34, n=28)

    # ---- lines 1-6: counsel block ----
    lx = rc.text(
        TX, ys[0], G["occ_k1_03"].label_context, L.MED, 9, L.GRAY
    )  # Attorney for Plaintiff:
    rc.value(G["occ_k1_03"], lx + 4, ys[0], L.REG, 9.5, L.INK)  # Priya Ramaswamy
    lx = rc.text(TX, ys[1], G["occ_k1_07"].label_context, L.MED, 9, L.GRAY)  # Idaho State Bar No.
    rc.value(G["occ_k1_07"], lx + 4, ys[1], L.REG, 9.5, L.INK)  # 284415
    _line(rc, ys[2], P.FIRM_NAME)
    rc.value_multiline(
        G["occ_k1_04"], TX, ys[3], L.REG, 9.5, L.INK, leading
    )  # firm address (2 lines)
    lx = rc.text(TX, ys[5], G["occ_k1_05"].label_context, L.MED, 9, L.GRAY)  # Telephone:
    px = rc.value(G["occ_k1_05"], lx + 4, ys[5], L.REG, 9.5, L.INK)
    lx = rc.text(px + 16, ys[5], G["occ_k1_06"].label_context, L.MED, 9, L.GRAY)  # Email:
    rc.value(G["occ_k1_06"], lx + 4, ys[5], L.REG, 9.5, L.INK)

    # ---- lines 8-9: court ----
    rc.c.setFillColor(L.INK)
    for i, s in (
        (7, "IN THE DISTRICT COURT OF THE SEVENTH JUDICIAL DISTRICT OF THE STATE OF IDAHO,"),
        (8, "IN AND FOR THE COUNTY OF WESTFALL"),
    ):
        rc.c.setFont(L.SEMI, 9.5)
        rc.c.drawCentredString((TX + L.RIGHT) / 2.0, ys[i], s)
        rc.draws.append((rc.page, ys[i], TX + 40, s))

    # ---- lines 11-17: caption (parties left, case block right) ----
    mid = TX + 250
    rc.value(G["occ_k1_01"], TX, ys[10], L.REG, 9.5, L.INK)  # MARCUS BELLAMY
    rc.text(TX, ys[11], "Plaintiff,", L.REG, 9, L.INK)
    rc.text(TX + 40, ys[12], "v.", L.REG, 9, L.INK)
    px = rc.value(G["occ_k1_02"], TX, ys[13], L.REG, 9.5, L.INK)  # TERRENCE WHITFIELD
    rc.text(px + 4, ys[13], "and", L.REG, 9, L.INK)
    rc.text(TX, ys[14], P.DEFENDANT_ORG.upper() + ",", L.REG, 9.5, L.INK)
    rc.text(TX, ys[15], "Defendants.", L.REG, 9, L.INK)
    rc.c.setStrokeColor(L.INK)
    rc.c.setLineWidth(0.7)
    rc.c.line(mid - 12, ys[10] + 10, mid - 12, ys[15] - 4)
    rc.c.line(TX, ys[15] - 6, mid - 12, ys[15] - 6)
    rc.c.line(mid - 12, ys[15] - 6, mid + 6, ys[15] - 6)
    lx = rc.text(mid, ys[10], G["occ_k1_08"].label_context, L.MED, 9, L.GRAY)  # Case No.
    rc.value(G["occ_k1_08"], lx + 4, ys[10], L.REG, 9.5, L.INK)  # 26-CV-01842
    rc.text(mid, ys[11], "COMPLAINT FOR DAMAGES", L.SEMI, 9.5, L.INK)
    rc.text(mid, ys[12], "(Civil action; jury trial demanded)", L.REG, 9, L.INK)
    lx = rc.text(mid, ys[13], G["occ_k1_09"].label_context, L.MED, 9, L.GRAY)  # Filed:
    rc.value(G["occ_k1_09"], lx + 4, ys[13], L.REG, 9.5, L.INK)  # 08/12/2026
    lx = rc.text(mid, ys[14], G["occ_k1_12"].label_context, L.MED, 9, L.GRAY)  # Assigned to: Judge
    rc.value(G["occ_k1_12"], lx + 4, ys[14], L.REG, 9.5, L.INK)  # Beatrice Lindqvist
    rc.text(mid, ys[15], "Bellamy v. Whitfield -- Complaint", L.REG, 8.5, L.GRAY)

    # ---- lines 18-28: allegations (Title-Case names after prefix words are rows) ----
    _line(rc, ys[17], "Plaintiff, by and through counsel, alleges as follows:", size=9)
    lx = rc.text(TX, ys[18], "1.", L.REG, 9, L.INK)
    lx = rc.text(lx + 8, ys[18], G["occ_k1_10"].label_context, L.REG, 9, L.INK)  # Plaintiff
    px = rc.value(G["occ_k1_10"], lx + 4, ys[18], L.REG, 9, L.INK)  # Marcus Bellamy
    lx = rc.text(px + 4, ys[18], G["occ_k1_11"].label_context, L.REG, 9, L.INK)  # resides at
    rc.value(G["occ_k1_11"], lx + 4, ys[18], L.REG, 9, L.INK)  # 4415 Camas Lane, ...
    _line(rc, ys[19], "and is a citizen of the state of Idaho.")
    lx = rc.text(TX, ys[20], "2.", L.REG, 9, L.INK)
    lx = rc.text(lx + 8, ys[20], G["occ_k1_13"].label_context, L.REG, 9, L.INK)  # Defendant
    px = rc.value(G["occ_k1_13"], lx + 4, ys[20], L.REG, 9, L.INK)  # Terrence Whitfield
    rc.text(
        px + 4,
        ys[20],
        "is an individual who at all relevant times managed the freight",
        L.REG,
        9,
        L.INK,
    )
    _line(
        rc,
        ys[21],
        "operations of the co-defendant (a domestic corporation) within this judicial district.",
    )
    _line(
        rc,
        ys[22],
        "3.   This court has jurisdiction over the parties and the subject matter, and venue is",
    )
    _line(
        rc,
        ys[23],
        "proper because the events giving rise to the claims occurred within the county.",
    )
    _line(
        rc,
        ys[24],
        "4.   Plaintiff seeks compensatory damages, costs, and such further relief as the court",
    )
    _line(rc, ys[25], "deems just. A jury trial is demanded on every claim so triable.")
    _line(
        rc,
        ys[26],
        "Synthetic pleading prepared for software testing; every party, counsel, and value is",
        size=8,
        color=L.GRAY,
    )
    _line(rc, ys[27], "fictional and disclosed in the accompanying manifest.", size=8, color=L.GRAY)

    C.page_footer(rc, "Page 1 of 1")
    rc.end_page()


def draw_k2(rc, base_page: int) -> None:
    rc.begin_page(base_page)
    # header: running caption + case no + deposition date; exhibit stamp at right
    rc.text(L.LEFT, L.TOP - 14, "Bellamy v. Whitfield", L.SEMI, 10, L.INK)
    lx = rc.text(L.LEFT, L.TOP - 28, G["occ_k2_09"].label_context, L.MED, 8.5, L.GRAY)  # Case No.
    rc.value(G["occ_k2_09"], lx + 4, L.TOP - 28, L.REG, 9, L.INK)
    lx = rc.text(
        L.LEFT, L.TOP - 42, G["occ_k2_10"].label_context, L.MED, 8.5, L.GRAY
    )  # Deposition taken
    px = rc.value(G["occ_k2_10"], lx + 4, L.TOP - 42, L.REG, 9, L.INK)  # 07/30/2026
    rc.text(
        px + 6,
        L.TOP - 42,
        "-- excerpt, pages 14 to 15 of the certified transcript.",
        L.REG,
        8.5,
        L.GRAY,
    )
    C.stamp_box(rc, L.RIGHT - 120, L.TOP - 54, 120, 44, ["EXHIBIT", "4"], size=12)
    rc.hrule(L.TOP - 62, L.LEFT, L.RIGHT, L.ACCENT, 1.0)
    y = L.TOP - 78
    lx = rc.text(L.LEFT, y, G["occ_k2_01"].label_context, L.MED, 9, L.GRAY)  # Deponent:
    px = rc.value(G["occ_k2_01"], lx + 4, y, L.REG, 9.5, L.INK)  # Marcus Bellamy
    rc.text(
        px + 12,
        y,
        "-- duly sworn under oath; counsel for both parties present.",
        L.REG,
        8.5,
        L.GRAY,
    )
    y -= 22

    # numbered transcript lines (testimony). Names / DOB / address / phone / SSN-last-4 are rows.
    _leading, ys = C.numbered_margin(rc, y, L.BOTTOM + 60, n=22, x_rule=L.LEFT + 20)
    tx = L.LEFT + 30

    def q(i, s):
        rc.text(tx, ys[i], "Q.", L.SEMI, 9, L.INK)
        rc.text(tx + 16, ys[i], s, L.REG, 9, L.INK)

    def a_label_value(i, occ, tail=""):
        rc.text(tx, ys[i], "A.", L.SEMI, 9, L.INK)
        lx = rc.text(tx + 16, ys[i], occ.label_context, L.REG, 9, L.INK)
        px = rc.value(occ, lx + 4, ys[i], L.REG, 9, L.INK)
        if tail:
            rc.text(px + 1, ys[i], tail, L.REG, 9, L.INK)

    q(0, "Please state your full name for the transcript.")
    a_label_value(1, G["occ_k2_02"], ".")  # A. My name is Marcus Bellamy.
    q(2, "And your date of birth, for identification?")
    a_label_value(3, G["occ_k2_03"], ".")  # A. Sure, my date of birth is September 9, 1983.
    q(4, "Counsel has asked for the last four digits only. Please state them.")
    a_label_value(5, G["occ_k2_04"], ".")  # A. The last four digits ... are 3308.
    q(6, "Where do you live?")
    a_label_value(7, G["occ_k2_05"], ".")  # A. I live at 4415 Camas Lane, ...
    q(8, "What is the best number to reach you at during the day?")
    a_label_value(9, G["occ_k2_06"], ".")  # A. My cell is 208-555-0152.
    q(10, "Who was your supervisor at the company in the spring of that year?")
    rc.text(tx, ys[11], "A.", L.SEMI, 9, L.INK)
    lx = rc.text(tx + 16, ys[11], "At that time", L.REG, 9, L.INK)
    lx = rc.text(lx + 4, ys[11], G["occ_k2_07"].label_context, L.REG, 9, L.INK)  # my supervisor,
    px = rc.value(G["occ_k2_07"], lx + 4, ys[11], L.REG, 9, L.INK)  # Terrence Whitfield
    rc.text(px + 1, ys[11], ", told me the route had changed.", L.REG, 9, L.INK)
    q(12, "Did anyone else give you instructions about the route?")
    rc.text(tx, ys[13], "A.", L.SEMI, 9, L.INK)
    rc.text(
        tx + 16,
        ys[13],
        "No. The dispatch desk sent the paperwork, but the instruction came from him.",
        L.REG,
        9,
        L.INK,
    )
    q(14, "I am handing you what has been marked as this exhibit. Do you recognize it?")
    rc.text(tx, ys[15], "A.", L.SEMI, 9, L.INK)
    rc.text(
        tx + 16,
        ys[15],
        "Yes. That is the route sheet from that week, with my initials in the corner.",
        L.REG,
        9,
        L.INK,
    )
    q(16, "Is the testimony you have given today true and complete to the best of your knowledge?")
    rc.text(tx, ys[17], "A.", L.SEMI, 9, L.INK)
    rc.text(tx + 16, ys[17], "It is.", L.REG, 9, L.INK)
    rc.text(
        tx,
        ys[19],
        "(Whereupon a recess was taken. The deposition resumed as reflected in the",
        L.REG,
        8.5,
        L.GRAY,
    )
    rc.text(
        tx,
        ys[20],
        "certified transcript. Synthetic exhibit prepared for software testing; every",
        L.REG,
        8.5,
        L.GRAY,
    )
    rc.text(
        tx,
        ys[21],
        "person and value is fictional and disclosed in the accompanying manifest.)",
        L.REG,
        8.5,
        L.GRAY,
    )

    # Bates number, bottom-right (no label)
    rc.value(G["occ_k2_08"], L.RIGHT - 72, L.BOTTOM + 30, L.MED, 8.5, L.INK)  # BELL-0000123
    C.page_footer(rc, "Page 1 of 1")
    rc.end_page()


def draw_k3(rc, base_page: int) -> None:
    rc.begin_page(base_page)
    # letterhead: agency + address (a row) + office
    rc.text(L.LEFT, L.TOP - 14, P.AGENCY_NAME, L.BOLD, 13, L.ACCENT)
    rc.text(
        L.LEFT,
        L.TOP - 27,
        "Office of Public Disclosure -- Freedom of Information Program",
        L.REG,
        8.5,
        L.GRAY,
    )
    rc.value_multiline(
        G["occ_k3_11"], L.LEFT, L.TOP - 41, L.REG, 8.5, L.GRAY, 11
    )  # agency address (2 lines)
    rc.hrule(L.TOP - 58, L.LEFT, L.RIGHT, L.ACCENT, 1.2)
    y = L.TOP - 74
    rc.value(G["occ_k3_10"], L.LEFT, y, L.REG, 9, L.INK)  # August 14, 2026
    lx = rc.text(
        L.LEFT + 300, y, G["occ_k3_09"].label_context, L.MED, 8.5, L.GRAY
    )  # FOIA Request No.
    rc.value(G["occ_k3_09"], lx + 4, y, L.REG, 9, L.INK)  # 2026-01447
    y -= 20
    y = C.frow(rc, y, G["occ_k3_04"], step=13)  # Name of Requester:
    rc.text(L.LEFT, y, P.FIRM_NAME + " (by electronic correspondence)", L.REG, 8.5, L.GRAY)
    y -= 22

    # body (foia vocabulary)
    y = C.fine_print(
        rc,
        y,
        [
            "This responds to your request under the Freedom of Information Act for records concerning "
            "the agency's investigation of the freight-route matter you described. A search of the "
            "responsive records was completed and the results were reviewed for release.",
            "Three pages are released in full. Portions of two further pages are withheld under the "
            "personal-privacy exemptions cited below; the redacted material consists of the names and one "
            "identifier of private individuals whose disclosure would constitute a clearly unwarranted "
            "invasion of personal privacy. No fees were assessed for this request.",
        ],
        size=8.5,
        leading=11,
        gap=5,
    )
    lx = rc.text(
        L.LEFT, y, G["occ_k3_08"].label_context, L.MED, 8.5, L.GRAY
    )  # Exemptions cited: (b)(6) and
    rc.value(G["occ_k3_08"], lx + 4, y, L.REG, 9, L.INK)  # (b)(7)(C)
    y -= 22

    # released record excerpt with bars (NO text under the bars)
    y = L.section_bar(rc, y, "Responsive Record 1 of 3 (released in part)")
    top = y + 6
    lx = rc.text(L.LEFT + 6, y, "Complainant:", L.MED, 9, L.GRAY)
    bx = rc.bar_value(G["occ_k3_01"], lx + 6, y, L.REG, 9.5)  # bar (Leonard Achterberg)
    rc.text(bx + 6, y, P.EXEMPTION_B6, L.REG, 8, L.FAINT)
    y -= 16
    lx = rc.text(L.LEFT + 6, y, "Statement provided by:", L.MED, 9, L.GRAY)
    bx = rc.bar_value(G["occ_k3_02"], lx + 6, y, L.REG, 9.5)  # bar (Corinne Vasquez)
    rc.text(bx + 6, y, P.EXEMPTION_B7C, L.REG, 8, L.FAINT)
    y -= 16
    lx = rc.text(L.LEFT + 6, y, "Identifier on file (SSN):", L.MED, 9, L.GRAY)
    bx = rc.bar_value(G["occ_k3_03"], lx + 6, y, L.REG, 9.5)  # bar (441-27-1911)
    rc.text(bx + 6, y, P.EXEMPTION_B6, L.REG, 8, L.FAINT)
    y -= 16
    rc.text(
        L.LEFT + 6,
        y,
        "Summary: the complaint alleged that a freight route was altered without notice. "
        "The reviewing",
        L.REG,
        8.5,
        L.INK,
    )
    y -= 12
    rc.text(
        L.LEFT + 6,
        y,
        "officer found the account credible and referred the matter for further review.",
        L.REG,
        8.5,
        L.INK,
    )
    y -= 18
    rc.text(L.LEFT + 6, y, "Provider roster entry (released in full):", L.MED, 9, L.GRAY)
    y -= 13
    lx = rc.text(L.LEFT + 6, y, G["occ_k3_07"].label_context, L.MED, 9, L.GRAY)  # Provider NPI:
    px = rc.value(G["occ_k3_07"], lx + 4, y, L.REG, 9.5, L.INK)  # 1245602234
    rc.text(
        px + 8,
        y,
        "-- individual, enumerated; roster line released without redaction.",
        L.REG,
        8.5,
        L.GRAY,
    )
    y -= 10
    rc.box(L.LEFT, y - 4, L.RIGHT, top, L.RULE, 0.7)
    y -= 22

    # appeal rights + signature block
    y = C.fine_print(
        rc,
        y,
        [
            "You may appeal this determination in writing within ninety days of the date of this "
            "correspondence. Mark the envelope and the appeal 'Freedom of Information Act Appeal' and "
            "describe the records or portions withheld that you believe should be released.",
        ],
        size=8.5,
        leading=11,
    )
    y -= 4
    rc.text(L.LEFT, y, G["occ_k3_05"].label_context, L.REG, 9, L.INK)  # Sincerely,
    y -= 26
    rc.value(G["occ_k3_05"], L.LEFT, y, L.REG, 9.5, L.INK)  # Dana Whitcombe
    y -= 12
    rc.text(L.LEFT, y, "Government Information Specialist", L.REG, 8.5, L.GRAY)
    y -= 13
    y = C.frow(rc, y, G["occ_k3_06"], step=14)  # Telephone:
    rc.text(
        L.LEFT,
        y,
        "Synthetic release prepared for software testing; every person, identifier, and "
        "request value is fictional and disclosed in the accompanying manifest.",
        L.REG,
        7.5,
        L.FAINT,
    )

    C.page_footer(rc, "Page 1 of 2")
    rc.end_page()


def draw_k4(rc, base_page: int) -> None:
    rc.begin_page(base_page)
    y = L.form_title(
        rc,
        "Civil Docket and Judgment Sheet",
        "District Court, Seventh Judicial District, County of Westfall -- register of actions.",
        "Clerk of the District Court",
    )
    lx = rc.text(L.LEFT, y, G["occ_k4_08"].label_context, L.MED, 9, L.GRAY)  # Case No.
    px = rc.value(G["occ_k4_08"], lx + 4, y, L.REG, 9.5, L.INK)  # 26-CV-01842
    rc.text(px + 12, y, "Bellamy v. Whitfield -- civil complaint for damages", L.REG, 9, L.INK)
    y -= 20

    # ---- docket table (bare dates; no DOB label within 80 chars) ----
    y = L.section_bar(rc, y, "Docket Entries")
    cols = [(L.LEFT, "Date"), (L.LEFT + 80, "Entry"), (L.LEFT + 440, "By")]
    y = C.table_header(rc, y, cols)
    rc.value(G["occ_k4_11"], L.LEFT, y, L.REG, 8.5, L.INK)  # 08/12/2026 (row)
    C.cell(rc, L.LEFT + 80, y, "Complaint for damages filed; summons issued to both defendants.")
    C.cell(rc, L.LEFT + 440, y, "PLA")
    y -= 13
    C.cell(rc, L.LEFT, y, "08/18/2026")
    C.cell(rc, L.LEFT + 80, y, "Answer and counterclaim filed; jury demand noted.")
    C.cell(rc, L.LEFT + 440, y, "DEF")
    y -= 13
    C.cell(rc, L.LEFT, y, "08/19/2026")
    C.cell(rc, L.LEFT + 80, y, "Motion for summary judgment heard; ruling from the bench.")
    C.cell(rc, L.LEFT + 440, y, "CRT")
    y -= 13
    rc.value(G["occ_k4_10"], L.LEFT, y, L.REG, 8.5, L.INK)  # 08/20/2026 (row)
    C.cell(rc, L.LEFT + 80, y, "Judgment entered; writ of garnishment issued to the garnishee.")
    C.cell(rc, L.LEFT + 440, y, "CRT")
    y -= 22

    # ---- judgment block ----
    y = L.section_bar(rc, y, "Judgment")
    lx = rc.text(L.LEFT, y, G["occ_k4_09"].label_context, L.MED, 8.5, L.GRAY)  # Judgment sum:
    px = rc.value(G["occ_k4_09"], lx + 4, y, L.REG, 9, L.INK)  # $4,250.00
    rc.text(
        px + 12,
        y,
        "plus costs; accruing at the statutory rate until satisfied.",
        L.REG,
        8.5,
        L.GRAY,
    )
    y -= 14
    lx = rc.text(L.LEFT, y, "Garnishee:", L.MED, 8.5, L.GRAY)
    rc.text(lx + 4, y, "Boise River Credit Union (financial institution)", L.REG, 9, L.INK)
    y -= 14
    y = C.frow(rc, y, G["occ_k4_05"], step=20)  # Garnishee Account No.

    # ---- parties (names after prefix words; entity in ALL-CAPS) ----
    y = L.section_bar(rc, y, "Parties of Record")
    y = C.frow(rc, y, G["occ_k4_01"], step=14)  # Plaintiff / Creditor:
    y = C.frow(rc, y, G["occ_k4_02"], step=14)  # Defendant / Debtor:
    L.labeled(rc, L.LEFT, y, "Co-Defendant (entity):", P.DEFENDANT_ORG.upper())
    y -= 14
    y = C.frow_multi(rc, y, G["occ_k4_03"], step=16)  # Debtor Address:

    # ---- isolated party-identification block (the one labeled DOB; > 80 chars from any bare date) ----
    y = L.section_bar(rc, y, "Party Identification (debtor)")
    y = C.fine_print(
        rc,
        y,
        [
            "Identification below is carried from the judgment debtor's answer so the garnishee can match "
            "the account holder with certainty before any funds are withheld from the account.",
        ],
        size=8,
        leading=10.5,
    )
    lx = rc.text(L.LEFT, y, "Debtor", L.MED, 8.5, L.GRAY)
    lx = rc.text(lx + 4, y, G["occ_k4_04"].label_context, L.MED, 8.5, L.GRAY)  # DOB:
    rc.value(G["occ_k4_04"], lx + 4, y, L.REG, 9, L.INK)  # 09/09/1983
    rc.text(L.LEFT + 200, y, "State of issue for identification: Idaho", L.REG, 8.5, L.GRAY)
    y -= 24

    # ---- clerk block ----
    rc.hrule(y + 8, L.LEFT, L.RIGHT, L.RULE, 0.6)
    y = C.frow(rc, y, G["occ_k4_07"], step=13)  # Prepared by:
    rc.text(L.LEFT, y, "Deputy Clerk of the District Court", L.REG, 8.5, L.GRAY)
    y -= 13
    y = C.frow(rc, y, G["occ_k4_06"], step=16)  # Clerk's Office Tel:
    rc.text(
        L.LEFT,
        y,
        "Synthetic docket prepared for software testing; every party, sum, date, and account "
        "value is fictional and disclosed.",
        L.REG,
        7.5,
        L.FAINT,
    )

    C.page_footer(rc, "Page 1 of 1")
    rc.end_page()
