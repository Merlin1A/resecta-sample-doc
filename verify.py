"""verify.py — acceptance suite for sample-bank-statement.pdf.

All 12 assertions must pass. Expected values are derived from statement_data.py (the source of truth)
so the manifest, the generator, and this suite cannot drift. Run: `uv run python verify.py`
(exit 0 = all green).
"""

from __future__ import annotations

import re
import subprocess
import sys
from decimal import Decimal as D
from pathlib import Path

from pypdf import PdfReader

import statement_data as S

PDF = Path(__file__).resolve().parent / "sample-bank-statement.pdf"
MODULE_SRC = (Path(__file__).resolve().parent / "statement_data.py").read_text()

# build-brief denylist (safety_constraints)
DENYLIST = [
    "CHASE",
    "JPMORGAN",
    "BANK OF AMERICA",
    "BOFA",
    "WELLS FARGO",
    "CITIBANK",
    "CITIGROUP",
    "U.S. BANK",
    "US BANK",
    "PNC",
    "CAPITAL ONE",
    "TRUIST",
    "TD BANK",
    "ALLY",
    "REGIONS",
    "FIFTH THIRD",
    "KEYBANK",
    "SANTANDER",
    "HSBC",
    "NAVY FEDERAL",
    "AMERICAN EXPRESS",
    "AMEX",
    "DISCOVER",
    "VISA",
    "MASTERCARD",
    "ZELLE",
    "VENMO",
    "PAYPAL",
    "CASHAPP",
    "TREAS",
    "IRS",
    "SSA",
    "FDIC",
    "NCUA",
    "EQUAL HOUSING",
    "AMAZON",
    "AMZN",
    "WALMART",
    "WAL-MART",
    "TARGET",
    "COSTCO",
    "KROGER",
    "STARBUCKS",
    "MCDONALD",
    "NETFLIX",
    "SPOTIFY",
    "APPLE.COM",
    "GOOGLE",
    "UBER",
    "LYFT",
    "EXXON",
    "SHELL OIL",
    "CHEVRON",
]

_results: list[tuple[bool, str, str]] = []


def check(ok: bool, name: str, detail: str = "") -> None:
    _results.append((bool(ok), name, detail))


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def run_tool(cmd: list[str], timeout: int = 120) -> str:
    """stdout of an external tool; a missing binary, a timeout or a non-zero exit ends the run."""
    try:
        return subprocess.run(
            cmd, capture_output=True, text=True, check=True, timeout=timeout
        ).stdout
    except (FileNotFoundError, subprocess.TimeoutExpired, subprocess.CalledProcessError) as e:
        sys.exit(f"{cmd[0]} unavailable or failed: {e}")


def pdftotext(page: int | None = None) -> str:
    cmd = ["pdftotext"]
    if page:
        cmd += ["-f", str(page), "-l", str(page)]
    cmd += [str(PDF), "-"]
    return run_tool(cmd)


# ---- gather ----
reader = PdfReader(str(PDF))
full_text = pdftotext()
page_text = {p: pdftotext(p) for p in (1, 2, 3)}
page_norm = {p: norm(t) for p, t in page_text.items()}

# =================================================================================================
# 1. page count
check(len(reader.pages) == 3, "1. page count == 3", f"got {len(reader.pages)}")

# =================================================================================================
# 2. every planted datum string present on its planned page (exact, whitespace-normalized)
expected: dict[int, list[str]] = {1: [], 2: [], 3: []}
# page 1 — identity / summary / credits
expected[1] += [
    S.BANK_NAME,
    S.BANK_TAGLINE,
    S.CUSTOMER_SERVICE_PHONE,
    S.ACCOUNT_HOLDER,
    S.HOLDER_ADDRESS_LINES[1],
    S.HOLDER_ADDRESS_LINES[2],
    S.ACCOUNT_NUMBER,
    S.CARD_LAST4,
    S.ACCOUNT_TYPE,
    S.PERIOD_LABEL,
    S.STATEMENT_DATE,
    S.CUSTOMER_EMAIL,
    "Statement Delivery",
    "Account Summary",
    "Beginning Balance",
    "Ending Balance",
    "Deposits and Other Credits",
    S.money(S.BEGINNING_BALANCE),
    S.money(S.TOTAL_CREDITS),
    S.money(S.TOTAL_WITHDRAWALS),
    S.money(S.TOTAL_CHECKS),
    S.money(S.TOTAL_FEES),
    S.money(S.ENDING_BALANCE),
]
for t in S.credits():
    expected[1] += list(t.desc_lines)
# page 2 — continuation furniture / withdrawals / checks / fees
expected[2] += [
    S.ACCOUNT_MASKED,
    "Page 2 of 3",
    S.PERIOD_LABEL,
    "Withdrawals and Other Subtractions",
    "Total Withdrawals and Other Subtractions",
    S.money(S.TOTAL_WITHDRAWALS),
    "Checks Paid",
    S.money(S.TOTAL_CHECKS),
    "Service Fees",
    "Monthly Maintenance Fee",
    "Fees Year-to-Date",
    S.money(S.FEES_YTD),
    S.money(S.TOTAL_FEES),
]
for t in S.withdrawals():
    expected[2] += list(t.desc_lines)
for t in S.checks():
    expected[2].append(t.check_no + ("*" if t.gap else ""))
# page 3 — daily balances / disclosures
expected[3] += [
    "Page 3 of 3",
    "Daily Ending Balance",
    S.REG_E_HEADING,
    S.CUSTOMER_SERVICE_PHONE,
    "60 days",
    "10 business days",
    S.money(S.ENDING_BALANCE),
]
expected[3] += [head for head, _ in S.OTHER_DISCLOSURES]
expected[3] += [S.money(bal) for _, bal in S.daily_ending_balances()]

missing = []
for pg, items in expected.items():
    for s in items:
        if norm(s) not in page_norm[pg]:
            missing.append(f"p{pg}:{s!r}")
check(
    not missing,
    "2. all manifest strings present per page",
    f"{len(missing)} missing: {missing[:6]}"
    if missing
    else f"{sum(len(v) for v in expected.values())} strings OK",
)

# =================================================================================================
# 3. "SAMPLE DOCUMENT" on every page
wm = [p for p in (1, 2, 3) if "SAMPLE DOCUMENT" not in page_norm[p]]
check(not wm, "3. watermark on every page", f"missing on {wm}" if wm else "all 3 pages")

# =================================================================================================
# 4. fonts: only OFL Inter, embedded + subset
pf = run_tool(["pdffonts", str(PDF)])
font_lines = [ln for ln in pf.splitlines()[2:] if ln.strip()]
bad_fonts = []
for ln in font_lines:
    m = re.search(r"\b(yes|no)\s+(yes|no)\s+(yes|no)\b", ln)
    emb, sub = (m.group(1), m.group(2)) if m else ("?", "?")
    if "Inter" not in ln or emb != "yes" or sub != "yes":
        bad_fonts.append(ln.strip())
check(
    bool(font_lines) and not bad_fonts,
    "4. only Inter, embedded+subset",
    f"offending: {bad_fonts}" if bad_fonts else f"{len(font_lines)} Inter faces, all emb+sub",
)


# =================================================================================================
# 5. denylist: zero hits in extracted text AND values module (word-boundary, case-insensitive)
def denylist_hits(text: str) -> list[str]:
    return [t for t in DENYLIST if re.search(r"\b" + re.escape(t) + r"\b", text, re.I)]


hits_text = denylist_hits(full_text)
hits_mod = denylist_hits(MODULE_SRC)
check(
    not hits_text and not hits_mod,
    "5. denylist clean (text + module)",
    f"text={hits_text} module={hits_mod}" if (hits_text or hits_mod) else "0 hits",
)

# =================================================================================================
# 6. every phone-shaped string is in the reserved fictional ranges
phone_re = re.compile(r"(?:1[-.\s])?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}")
bad_phones = []
for m in phone_re.finditer(full_text):
    digits = re.sub(r"\D", "", m.group())
    last10 = digits[-10:]
    ok = last10 == "8005550199" or re.fullmatch(r"\d{3}5550(1\d\d)", last10)
    if not ok:
        bad_phones.append(m.group())
check(
    not bad_phones,
    "6. phones in reserved range",
    f"bad: {bad_phones}" if bad_phones else "1-800-555-0199 only",
)

# =================================================================================================
# 7. NO standalone 9-digit number (max digit run length != 9)
runs9 = [r for r in re.findall(r"\d+", full_text) if len(r) == 9]
check(
    not runs9,
    "7. no standalone 9-digit number",
    f"found: {runs9}" if runs9 else "none (routing omitted)",
)

# =================================================================================================
# 8. NO SSN-shaped string
ssn = re.findall(r"\b\d{3}-\d{2}-\d{4}\b", full_text) + re.findall(
    r"\b\d{3}\s\d{2}\s\d{4}\b", full_text
)
check(not ssn, "8. no SSN-shaped string", f"found: {ssn}" if ssn else "none")

# =================================================================================================
# 9. arithmetic — recompute INDEPENDENTLY from the ledger, compare to claimed + fold daily balances
ind_credits = sum((t.amount for t in S.TRANSACTIONS if t.section == "credit"), D("0"))
ind_wd = sum((t.amount for t in S.TRANSACTIONS if t.section == "withdrawal"), D("0"))
ind_ck = sum((t.amount for t in S.TRANSACTIONS if t.section == "check"), D("0"))
ind_fee = sum((t.amount for t in S.TRANSACTIONS if t.section == "fee"), D("0"))
ind_end = S.BEGINNING_BALANCE + ind_credits - (ind_wd + ind_ck + ind_fee)
bal = S.BEGINNING_BALANCE
ind_daily = []
for day in sorted({t.day for t in S.TRANSACTIONS}):
    for t in (x for x in S.TRANSACTIONS if x.day == day):
        bal += t.signed
    ind_daily.append((day, bal))
arith_ok = (
    ind_credits == S.TOTAL_CREDITS
    and ind_wd == S.TOTAL_WITHDRAWALS
    and ind_ck == S.TOTAL_CHECKS
    and ind_fee == S.TOTAL_FEES
    and ind_end == S.ENDING_BALANCE
    and ind_daily == S.daily_ending_balances()
    and ind_daily[-1][1] == S.ENDING_BALANCE
)
check(
    arith_ok,
    "9. arithmetic consistent (summary + daily fold)",
    f"ending={S.money(ind_end)} daily[-1]={S.money(ind_daily[-1][1])}",
)

# =================================================================================================
# 10. all transaction dates within 05/01/2026-05/31/2026
bad_days = [t.day for t in S.TRANSACTIONS if not (1 <= t.day <= 31)]
emb_dates = re.findall(
    r"(?:CHECKCARD|ATM WITHDRAWAL)\s+(\d{2})(\d{2})",
    " ".join(ln for t in S.TRANSACTIONS for ln in t.desc_lines),
)
bad_emb = [f"{mm}{dd}" for mm, dd in emb_dates if mm != "05" or not (1 <= int(dd) <= 31)]
check(
    not bad_days and not bad_emb,
    "10. txn dates within period",
    f"days={bad_days} emb={bad_emb}" if (bad_days or bad_emb) else "all in May 2026",
)

# =================================================================================================
# 11. metadata equals locked values
md: dict[str, object] = dict(reader.metadata or {})
want_md = {
    "/Title": f"Account Statement {S.PERIOD_LABEL}",
    "/Author": S.BANK_NAME,
    "/Subject": "Monthly Account Statement",
    "/Creator": f"{S.BANK_NAME} Statement Services",
}
md_bad = {k: (md.get(k), v) for k, v in want_md.items() if md.get(k) != v}
check(
    not md_bad,
    "11. metadata == locked values",
    f"mismatch: {md_bad}" if md_bad else "Title/Author/Subject/Creator OK",
)

# =================================================================================================
# 12. file size < 1.5 MB
size = PDF.stat().st_size
check(size < 1_500_000, "12. file size < 1.5 MB", f"{size:,} bytes")

# ---- report ----
print(f"\nAcceptance suite — {PDF.name}\n" + "=" * 58)
allok: bool = True
for passed, name, detail in _results:
    allok = allok and passed
    print(f"  [{'PASS' if passed else 'FAIL'}] {name}" + (f"  — {detail}" if detail else ""))
print("=" * 58)
print("RESULT:", "ALL PASS ✓" if allok else "FAILURES ✗")
sys.exit(0 if allok else 1)
