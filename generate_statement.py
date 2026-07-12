"""generate_statement.py — deterministic, OFFLINE renderer for sample-bank-statement.pdf.

3-page fictional US consumer (non-interest personal checking) statement, classic print/mail style.
Layout covers page allocation, anatomy, typography/metrics, and language.
Genuine embedded text layer with subset Inter (tnum frozen) fonts.

Determinism: reportlab `invariant` fixes internal dates + font subset
tags; a pypdf finalize pass sets the seeded metadata, a fixed creation timestamp, and a fixed
document /ID, so two runs are byte-identical. No randomness, no clock reads.
"""
from __future__ import annotations

import io
from pathlib import Path
from decimal import Decimal as D

from reportlab import rl_config
rl_config.invariant = 1  # noqa: E402  (must precede save; fixes dates + subset tags)

from reportlab.pdfgen import canvas  # noqa: E402
from reportlab.lib.pagesizes import letter  # noqa: E402
from reportlab.lib.colors import HexColor  # noqa: E402
from reportlab.pdfbase import pdfmetrics  # noqa: E402
from reportlab.pdfbase.ttfonts import TTFont  # noqa: E402

import statement_data as S  # noqa: E402

HERE = Path(__file__).resolve().parent
FONT_DIR = HERE / "fonts"
OUT = HERE / "sample-bank-statement.pdf"

# ---- fonts ----
REG, MED, SEMI, BOLD = "Inter", "Inter-Medium", "Inter-SemiBold", "Inter-Bold"
for _name, _fn in {REG: "Inter-Regular.ttf", MED: "Inter-Medium.ttf",
                   SEMI: "Inter-SemiBold.ttf", BOLD: "Inter-Bold.ttf"}.items():
    pdfmetrics.registerFont(TTFont(_name, str(FONT_DIR / _fn)))

# ---- geometry ----
PW, PH = letter                 # 612 x 792 pt
M = 36                          # 0.5 in margins
LEFT, RIGHT = M, PW - M         # 36, 576
TOP = PH - M                    # 756
COL_DATE = LEFT + 2             # 38
COL_DESC = 86
AMT_R = RIGHT - 2               # 574 (right edge for tabular amounts)
SUM_R = 322                     # right edge for summary-box amounts

# ---- palette: grayscale-dominant + one restrained accent ----
ACCENT = HexColor("#234E63")    # muted navy-teal
INK = HexColor("#1A1A1A")
GRAY = HexColor("#5C5C5C")
RULE = HexColor("#BEBEBE")
SHADE = HexColor("#F2F4F5")     # light-gray alternating row shading
WM = HexColor("#8C9398")        # watermark gray


# --------------------------------------------------------------------------------------------------
# primitives
# --------------------------------------------------------------------------------------------------
def text(c, x, y, s, font=REG, size=8.5, color=INK):
    c.setFillColor(color)
    c.setFont(font, size)
    c.drawString(x, y, s)


def rtext(c, x, y, s, font=REG, size=8.5, color=INK):
    c.setFillColor(color)
    c.setFont(font, size)
    c.drawRightString(x, y, s)


def hrule(c, y, x0=LEFT, x1=RIGHT, color=RULE, w=0.6):
    c.setStrokeColor(color)
    c.setLineWidth(w)
    c.line(x0, y, x1, y)


def shade_row(c, y_top, h):
    c.setFillColor(SHADE)
    c.rect(LEFT, y_top - h, RIGHT - LEFT, h, stroke=0, fill=1)


def wrap(c, x, y, s, width, font, size, leading, color):
    c.setFont(font, size)
    c.setFillColor(color)
    line = ""
    for word in s.split():
        trial = (line + " " + word).strip()
        if pdfmetrics.stringWidth(trial, font, size) <= width:
            line = trial
        else:
            c.drawString(x, y, line)
            y -= leading
            line = word
    if line:
        c.drawString(x, y, line)
        y -= leading
    return y


def section_heading(c, y, title):
    text(c, LEFT, y, title, SEMI, 11, INK)
    y -= 5
    hrule(c, y, color=ACCENT, w=1.0)
    return y - 13  # baseline for the column-header row


def col_headers(c, y, desc="DESCRIPTION", date="DATE"):
    text(c, COL_DATE, y, date, SEMI, 8, GRAY)
    text(c, COL_DESC, y, desc, SEMI, 8, GRAY)
    rtext(c, AMT_R, y, "AMOUNT", SEMI, 8, GRAY)
    y -= 4
    hrule(c, y, color=RULE, w=0.5)
    return y  # = top of first data row


# --------------------------------------------------------------------------------------------------
# page furniture: watermark (every page, margin zone) + footer
# --------------------------------------------------------------------------------------------------
def page_furniture(c, page_no):
    c.setFillColor(WM)
    c.setFont(SEMI, 12)
    c.drawCentredString(PW / 2, 24, "SAMPLE DOCUMENT")  # real text => searchable (assertion #3)
    hrule(c, 52, color=RULE, w=0.5)
    text(c, LEFT, 43, S.BANK_NAME, REG, 7, GRAY)
    rtext(c, RIGHT, 43, f"Page {page_no} of 3", REG, 7, GRAY)


def continuation_header(c, page_no):
    """Pages 2-3: {NAME} | Account {MASKED} | {PERIOD} | Page N of 3."""
    y = TOP - 4
    hdr = f"{S.ACCOUNT_HOLDER}   |   Account {S.ACCOUNT_MASKED}   |   {S.PERIOD_LABEL}   |   Page {page_no} of 3"
    text(c, LEFT, y, hdr, MED, 8.5, GRAY)
    y -= 6
    hrule(c, y, color=ACCENT, w=0.8)
    return y - 16


# --------------------------------------------------------------------------------------------------
# transaction table (shared by credits + withdrawals)
# --------------------------------------------------------------------------------------------------
def txn_table(c, y, title, txns, total_label, total):
    y = section_heading(c, y, title)
    y = col_headers(c, y)
    alt = False
    lh = 10.5
    for t in txns:
        n = len(t.desc_lines)
        rowh = lh * n + 2.5
        if alt:
            shade_row(c, y, rowh)
        b = y - 9.5
        text(c, COL_DATE, b, t.mmdd, REG, 8.5, INK)
        for i, ln in enumerate(t.desc_lines):
            text(c, COL_DESC, b - i * lh, ln, REG, 8.5, INK if i == 0 else GRAY)
        rtext(c, AMT_R, b, S.money(t.amount), REG, 8.5, INK)
        y -= rowh
        alt = not alt
    hrule(c, y, x0=COL_DESC, x1=AMT_R, color=RULE, w=0.6)
    b = y - 12
    text(c, COL_DESC, b, total_label, SEMI, 8.5, INK)
    rtext(c, AMT_R, b, S.money(total), SEMI, 8.5, INK)
    return b - 8


# --------------------------------------------------------------------------------------------------
# page 1
# --------------------------------------------------------------------------------------------------
def page1(c):
    # masthead
    text(c, LEFT, TOP - 16, S.BANK_NAME, BOLD, 21, ACCENT)
    text(c, LEFT, TOP - 28, S.BANK_TAGLINE, MED, 8, GRAY)
    yb = TOP - 6
    rtext(c, RIGHT, yb, S.BANK_ADDRESS_LINES[1], REG, 8, GRAY)
    rtext(c, RIGHT, yb - 10, S.BANK_ADDRESS_LINES[2], REG, 8, GRAY)
    rtext(c, RIGHT, yb - 22, f"Customer Service:  {S.CUSTOMER_SERVICE_PHONE}", MED, 8.5, INK)
    hrule(c, TOP - 40, color=ACCENT, w=1.2)

    # statement title band
    text(c, LEFT, TOP - 58, "Account Statement", SEMI, 13, INK)
    rtext(c, RIGHT, TOP - 56, f"Statement Period:  {S.PERIOD_LABEL}", REG, 9, INK)

    # account-holder address block — window-envelope zone: ~2 in from top, left
    ax, ay = 54, 650
    text(c, ax, ay, S.ACCOUNT_HOLDER, REG, 10.5, INK)
    text(c, ax, ay - 13, S.HOLDER_ADDRESS_LINES[1], REG, 10.5, INK)
    text(c, ax, ay - 26, S.HOLDER_ADDRESS_LINES[2], REG, 10.5, INK)

    # account-information box (right; outside the window)
    # left edge widened (336->320) and bottom dropped (596->583) to seat the 5th row (Statement
    # Delivery) whose value is the widest in the box; keeps a >=17pt label/value gutter (R2).
    bx0, by0, bx1, by1 = 320, 583, RIGHT, 672
    c.setStrokeColor(RULE)
    c.setLineWidth(0.7)
    c.roundRect(bx0, by0, bx1 - bx0, by1 - by0, 4, stroke=1, fill=0)
    text(c, bx0 + 10, by1 - 14, "ACCOUNT INFORMATION", SEMI, 8, ACCENT)
    info = [("Account Number", S.ACCOUNT_NUMBER),
            ("Account Type", S.ACCOUNT_TYPE),
            ("Card Ending In", S.CARD_LAST4),
            ("Statement Date", S.STATEMENT_DATE),
            ("Statement Delivery", S.STATEMENT_DELIVERY)]
    ry = by1 - 30
    for label, val in info:
        text(c, bx0 + 10, ry, label, REG, 8, GRAY)
        rtext(c, bx1 - 10, ry, val, MED, 8.5, INK)
        ry -= 13

    # account summary (left; clear arithmetic)
    y = 560
    text(c, LEFT, y, "Account Summary", SEMI, 11.5, INK)
    y -= 5
    hrule(c, y, x0=LEFT, x1=SUM_R, color=ACCENT, w=1.0)
    y -= 16
    rows = [("Beginning Balance", S.money(S.BEGINNING_BALANCE), REG),
            ("Deposits and Other Credits", "+" + S.money(S.TOTAL_CREDITS), REG),
            ("Withdrawals and Other Subtractions", "-" + S.money(S.TOTAL_WITHDRAWALS), REG),
            ("Checks", "-" + S.money(S.TOTAL_CHECKS), REG),
            ("Service Fees", "-" + S.money(S.TOTAL_FEES), REG),
            ("Ending Balance", S.money(S.ENDING_BALANCE), SEMI)]
    for label, val, fnt in rows:
        if label == "Ending Balance":
            hrule(c, y + 9, x0=LEFT, x1=SUM_R, color=RULE, w=0.6)
        text(c, LEFT + 4, y, label, fnt, 9, INK)
        rtext(c, SUM_R, y, val, fnt, 9, INK)
        y -= 14

    # start of transaction detail: deposits & other credits
    y -= 14
    txn_table(c, y, "Deposits and Other Credits", S.credits(),
              "Total Deposits and Other Credits", S.TOTAL_CREDITS)

    page_furniture(c, 1)


# --------------------------------------------------------------------------------------------------
# page 2
# --------------------------------------------------------------------------------------------------
def checks_table(c, y):
    y = section_heading(c, y, "Checks Paid")
    text(c, COL_DATE, y, "CHECK NO.", SEMI, 8, GRAY)
    text(c, 150, y, "DATE", SEMI, 8, GRAY)
    rtext(c, AMT_R, y, "AMOUNT", SEMI, 8, GRAY)
    y -= 4
    hrule(c, y, color=RULE, w=0.5)
    alt = False
    for t in S.checks():
        rowh = 14
        if alt:
            shade_row(c, y, rowh)
        b = y - 11
        text(c, COL_DATE, b, t.check_no + ("*" if t.gap else ""), REG, 8.5, INK)
        text(c, 150, b, t.mmdd, REG, 8.5, INK)
        rtext(c, AMT_R, b, S.money(t.amount), REG, 8.5, INK)
        y -= rowh
        alt = not alt
    hrule(c, y, x0=150, x1=AMT_R, color=RULE, w=0.6)
    b = y - 12
    text(c, 150, b, "Total Checks Paid", SEMI, 8.5, INK)
    rtext(c, AMT_R, b, S.money(S.TOTAL_CHECKS), SEMI, 8.5, INK)
    b -= 13
    text(c, COL_DATE, b, "* Indicates a skip in the check-number sequence.", REG, 7, GRAY)
    return b - 10


def fees_block(c, y):
    y = section_heading(c, y, "Service Fees")
    y = col_headers(c, y)
    for t in S.fees():
        b = y - 11
        text(c, COL_DATE, b, t.mmdd, REG, 8.5, INK)
        text(c, COL_DESC, b, t.desc_lines[0], REG, 8.5, INK)
        rtext(c, AMT_R, b, S.money(t.amount), REG, 8.5, INK)
        y -= 14
    hrule(c, y, x0=COL_DESC, x1=AMT_R, color=RULE, w=0.6)
    b = y - 12
    text(c, COL_DESC, b, "Total Service Fees This Period", SEMI, 8.5, INK)
    rtext(c, AMT_R, b, S.money(S.TOTAL_FEES), SEMI, 8.5, INK)
    b -= 13
    text(c, COL_DESC, b, "Fees Year-to-Date", REG, 8.5, GRAY)
    rtext(c, AMT_R, b, S.money(S.FEES_YTD), REG, 8.5, GRAY)
    return b - 12


def page2(c):
    y = continuation_header(c, 2)
    y = txn_table(c, y, "Withdrawals and Other Subtractions", S.withdrawals(),
                  "Total Withdrawals and Other Subtractions", S.TOTAL_WITHDRAWALS)
    y -= 6
    y = checks_table(c, y)
    y -= 6
    fees_block(c, y)
    page_furniture(c, 2)


# --------------------------------------------------------------------------------------------------
# page 3
# --------------------------------------------------------------------------------------------------
def daily_balance_table(c, y):
    y = section_heading(c, y, "Daily Ending Balance")
    bals = S.daily_ending_balances()
    # Split at the half-month boundary (05/01-05/14 left, 05/15-05/31 right), anchored by DATE not row
    # count: dropping a no-activity day (post-R1, 05/10) shrinks the left column to a 12/13 split without
    # shifting 05/15 across the gutter.
    colA = [(d, ba) for d, ba in bals if d <= 14]
    colB = [(d, ba) for d, ba in bals if d >= 15]
    cAr, cBd, cBr = 300, 330, AMT_R
    text(c, LEFT + 4, y, "DATE", SEMI, 8, GRAY)
    rtext(c, cAr, y, "BALANCE", SEMI, 8, GRAY)
    text(c, cBd, y, "DATE", SEMI, 8, GRAY)
    rtext(c, cBr, y, "BALANCE", SEMI, 8, GRAY)
    y -= 4
    hrule(c, y, color=RULE, w=0.5)
    rowh = 13
    for i in range(max(len(colA), len(colB))):
        if i % 2:
            shade_row(c, y, rowh)
        b = y - 11
        if i < len(colA):
            d, ba = colA[i]
            text(c, LEFT + 4, b, f"05/{d:02d}", REG, 8.5, INK)
            rtext(c, cAr, b, S.money(ba), REG, 8.5, INK)
        if i < len(colB):
            d2, ba2 = colB[i]
            text(c, cBd, b, f"05/{d2:02d}", REG, 8.5, INK)
            rtext(c, cBr, b, S.money(ba2), REG, 8.5, INK)
        y -= rowh
    return y - 8


def disclosures(c, y):
    text(c, LEFT, y, S.REG_E_HEADING, SEMI, 9, INK)
    y -= 12
    for para in S.REG_E_PARAS:
        y = wrap(c, LEFT, y, para, RIGHT - LEFT, REG, 7, 9.3, INK)
        y -= 2
    y -= 8
    for head, body in S.OTHER_DISCLOSURES:
        text(c, LEFT, y, head, SEMI, 8, ACCENT)
        y -= 10
        y = wrap(c, LEFT, y, body, RIGHT - LEFT, REG, 7, 9.3, GRAY)
        y -= 7
    return y


def page3(c):
    y = continuation_header(c, 3)
    y = daily_balance_table(c, y)
    y -= 12
    disclosures(c, y)
    page_furniture(c, 3)


# --------------------------------------------------------------------------------------------------
# build + deterministic finalize
# --------------------------------------------------------------------------------------------------
def _render() -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter, invariant=1, pageCompression=1)
    page1(c)
    c.showPage()
    page2(c)
    c.showPage()
    page3(c)
    c.showPage()
    c.save()
    return buf.getvalue()


import re  # noqa: E402

# reportlab emits an empty default-font preamble (Helvetica) at each page start; no glyphs are drawn
# with it, but it declares Helvetica in the page resources. Strip it so ONLY Inter remains (#4).
_HELV_PREAMBLE = re.compile(rb"BT\s*/F1\s+12\s+Tf\s+14\.4\s+TL\s*ET")


def _strip_default_helvetica(writer) -> None:
    from pypdf.generic import DecodedStreamObject
    for page in writer.pages:
        res = page.get("/Resources")
        res = res.get_object() if res is not None else None
        fonts = res.get("/Font").get_object() if (res is not None and "/Font" in res) else None
        if fonts is not None and "/F1" in fonts:
            del fonts["/F1"]
        contents = page.get_contents()
        if contents is None:
            continue
        data = contents.get_data()
        new = _HELV_PREAMBLE.sub(b"", data)
        if new != data:
            obj = DecodedStreamObject()
            obj.set_data(new)
            page.replace_contents(obj)
    # The default font is now unreferenced by any page, but reportlab's orphaned Helvetica font object
    # still lives in the cloned object list (verified: object 6, /BaseFont /Helvetica). Null it so no
    # unembedded base-14 font reference survives in the output -- the acceptance suite asserts its
    # absence, since unembedded font references aren't allowed in the shipped PDF.
    from pypdf.generic import NullObject
    for idx, obj in enumerate(writer._objects):
        o = obj.get_object() if obj is not None else None
        try:
            is_helv = o is not None and o.get("/Type") == "/Font" and "Helvetica" in str(o.get("/BaseFont", ""))
        except AttributeError:
            is_helv = False
        if is_helv:
            writer._objects[idx] = NullObject()


def _finalize(pdf: bytes) -> bytes:
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import ArrayObject, ByteStringObject

    reader = PdfReader(io.BytesIO(pdf))
    writer = PdfWriter(clone_from=reader)
    _strip_default_helvetica(writer)
    creator = f"{S.BANK_NAME} Statement Services"
    writer.add_metadata({
        "/Title": f"Account Statement {S.PERIOD_LABEL}",
        "/Author": S.BANK_NAME,
        "/Subject": "Monthly Account Statement",
        "/Creator": creator,
        "/Producer": creator,
        "/CreationDate": "D:20260601000000Z",
        "/ModDate": "D:20260601000000Z",
    })
    fixed = ByteStringObject(b"SablebrookSampleStmtID01")  # fixed doc /ID => byte-stable output
    writer._ID = ArrayObject([fixed, fixed])
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def main() -> None:
    OUT.write_bytes(_finalize(_render()))
    print(f"wrote {OUT}  ({OUT.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
