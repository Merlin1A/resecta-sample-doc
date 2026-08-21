"""Single source of truth for the Resecta sample statement (entirely fictional data).

Every value here is fictional (reserved example spaces). Arithmetic — the account-summary box and
the Daily Ending Balance table — is COMPUTED from the ledger below; no totals are hand-typed.
Deterministic: no randomness, no clock reads.

Descriptor grammar avoids brand marks
(person-to-person => "ONLINE TRANSFER", no card-network names, no government-deposit template).
Long ACH descriptors are pre-split into the exact rendered lines so the embedded text layer extracts
each data token contiguously (supports the acceptance suite's per-string matching).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal as D

# --------------------------------------------------------------------------------------------------
# Identity — fictional bank (cleared against the federal bank & credit-union registries)
# --------------------------------------------------------------------------------------------------
BANK_NAME = "Sablebrook Bank"
BANK_TAGLINE = "Personal & Community Banking"
# remittance / "write us" address — fictional P.O. Box, real city + real P.O.-Box ZIP
BANK_ADDRESS_LINES = ["Sablebrook Bank", "P.O. Box 4827", "Boise, ID 83701"]
CUSTOMER_SERVICE_PHONE = "1-800-555-0199"  # single reserved fictional toll-free

# --------------------------------------------------------------------------------------------------
# Identity — account holder (decision Q2; canonical Resecta persona)
# --------------------------------------------------------------------------------------------------
ACCOUNT_HOLDER = "Delia R. Hartwell"
ACCOUNT_HOLDER_ACH = "DELIA HARTWELL"  # INDN: form in ACH descriptors (uppercase, no middle initial)
# fictional street number + name; real city/state/ZIP for plausibility
HOLDER_ADDRESS_LINES = ["Delia R. Hartwell", "4127 N. Wrenfield Pl", "Boise, ID 83702"]

ACCOUNT_TYPE = "Personal Checking"
ACCOUNT_NUMBER = "4100773265"            # full 10-digit fictional (decision Q1b; no checksum std §6.2)
ACCOUNT_MASKED = "XXXXXX" + ACCOUNT_NUMBER[-4:]  # continuation-header / masked form
CARD_LAST4 = "8043"                      # debit card last-4 (card masking)
# customer email — RFC-2606-reserved domain (never a real freemail domain, never an invented squattable
# one); handle matches the persona. Carried as a "Statement Delivery: Paperless" line.
CUSTOMER_EMAIL = "d.hartwell@example.net"
STATEMENT_DELIVERY = f"Paperless ({CUSTOMER_EMAIL})"

# --------------------------------------------------------------------------------------------------
# Period (decision Q4 — fixed)
# --------------------------------------------------------------------------------------------------
STATEMENT_DATE = "06/01/2026"
PERIOD_LABEL = "05/01/2026 - 05/31/2026"

BEGINNING_BALANCE = D("2847.13")
FEES_YTD = D("60.00")  # Jan–May monthly maintenance fees (multi-month accumulator; see manifest)


# --------------------------------------------------------------------------------------------------
# Ledger
# --------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Txn:
    day: int                     # day in May 2026
    section: str                 # 'credit' | 'withdrawal' | 'check' | 'fee'
    amount: D                    # positive magnitude
    desc_lines: tuple            # exact rendered description line(s)
    check_no: str = ""           # checks only
    gap: bool = False            # True => print check number with trailing '*' (skip in sequence)

    @property
    def signed(self) -> D:
        return self.amount if self.section == "credit" else -self.amount

    @property
    def mmdd(self) -> str:
        return f"05/{self.day:02d}"


def _ach(line1: str, coid: str, sec: str) -> tuple:
    """Second ACH line carries INDN + 10-digit CO ID + SEC code."""
    return (line1, f"INDN:{ACCOUNT_HOLDER_ACH} CO ID:{coid} {sec}")


# Chronological. CO IDs are fictional 10-digit company identifiers (never 9 digits).
TRANSACTIONS: list[Txn] = [
    # ---- credits (page 1) ----
    Txn(1, "credit", D("2113.44"), _ach("NORTHLINE LOGISTICS DIRECT DEP DES:PAYROLL ID:PR4471", "9100004821", "PPD")),
    Txn(15, "credit", D("2113.44"), _ach("NORTHLINE LOGISTICS DIRECT DEP DES:PAYROLL ID:PR4472", "9100004821", "PPD")),
    Txn(18, "credit", D("120.00"), ("ONLINE TRANSFER FROM MARCUS B CONF# 8XK4Q2",)),

    # ---- withdrawals & other subtractions (page 2) ----
    Txn(1, "withdrawal", D("1450.00"), _ach("ASHWOOD RESIDENTIAL DES:RENT ID:RNT0521", "8120049173", "PPD")),
    Txn(2, "withdrawal", D("4.95"), ("CHECKCARD 0501 BLUEPINE COFFEE #142 BOISE ID",)),
    Txn(4, "withdrawal", D("84.17"), ("CHECKCARD 0503 CEDAR STREET MARKET #0428 BOISE ID",)),
    Txn(5, "withdrawal", D("41.20"), ("CHECKCARD 0504 RIVER ROAD FUEL #77 MERIDIAN ID",)),
    Txn(6, "withdrawal", D("128.64"), _ach("VALLEY POWER & LIGHT DES:UTILITY ID:VPL55021", "7330081265", "WEB")),
    Txn(7, "withdrawal", D("23.46"), ("POS PURCHASE NORTHGATE PHARMACY BOISE ID",)),
    Txn(8, "withdrawal", D("39.00"), ("CHECKCARD 0507 SUMMIT ATHLETIC CLUB BOISE ID",)),
    Txn(9, "withdrawal", D("80.00"), ("ATM WITHDRAWAL 0509 #BO1427 CEDAR ST BRANCH BOISE ID",)),
    Txn(9, "withdrawal", D("12.75"), ("CHECKCARD 0508 THE DAILY LOAF BAKERY BOISE ID",)),
    # R1 (Sunday-ACH fix): 05/10/2026 is a Sunday and the ACH network does not settle on weekends, so
    # this WEB/ACH debit posts the next business day (Mon 05/11). Kept immediately before the 05/11 card
    # row so ACH lists before card within the date (matches the 05/14 STREAMHARBOR/PINEHILL precedent).
    Txn(11, "withdrawal", D("79.99"), _ach("NORTHSTAR BROADBAND DES:INTERNET ID:NSB73310", "6650094412", "WEB")),
    Txn(11, "withdrawal", D("57.89"), ("CHECKCARD 0510 GARDEN CITY HARDWARE #12 GARDEN CITY ID",)),
    Txn(12, "withdrawal", D("28.40"), ("CHECKCARD 0511 LULU'S TAQUERIA BOISE ID",)),
    Txn(13, "withdrawal", D("53.61"), ("CHECKCARD 0512 CEDAR STREET MARKET #0428 BOISE ID",)),
    Txn(14, "withdrawal", D("15.99"), _ach("STREAMHARBOR MEDIA DES:SUBSCRIPT ID:SHM10293", "5540063370", "WEB")),
    Txn(14, "withdrawal", D("19.99"), ("POS PURCHASE PINEHILL BOOKS BOISE ID",)),
    Txn(16, "withdrawal", D("38.77"), ("CHECKCARD 0515 RIVER ROAD FUEL #77 MERIDIAN ID",)),
    Txn(17, "withdrawal", D("64.08"), ("CHECKCARD 0516 BRIGHT BASKET GROCERY NAMPA ID",)),
    Txn(18, "withdrawal", D("6.50"), ("POS PURCHASE CITYLINE TRANSIT FARE BOISE ID",)),
    Txn(19, "withdrawal", D("48.30"), ("POS PURCHASE EVERGREEN GARDEN SUPPLY BOISE ID",)),
    Txn(20, "withdrawal", D("75.00"), ("ONLINE TRANSFER TO JORDAN K CONF# 5RT9P8",)),
    Txn(21, "withdrawal", D("60.00"), ("ATM WITHDRAWAL 0521 #BO0938 MERIDIAN CROSSROADS MERIDIAN ID",)),
    Txn(21, "withdrawal", D("32.15"), ("CHECKCARD 0520 SUNRISE DINER MERIDIAN ID",)),
    Txn(22, "withdrawal", D("45.00"), ("CHECKCARD 0521 PETALS & STEMS FLORIST BOISE ID",)),
    Txn(24, "withdrawal", D("200.00"), ("ONLINE TRANSFER TO PRIYA S CONF# 2WN6LM",)),
    Txn(25, "withdrawal", D("27.50"), ("POS PURCHASE PARKVIEW CINEMA BOISE ID",)),
    Txn(28, "withdrawal", D("71.93"), ("CHECKCARD 0527 CEDAR STREET MARKET #0428 BOISE ID",)),

    # ---- checks paid (page 2 table); exactly one gap: 1023 skipped -> 1024 marked '*' ----
    Txn(5, "check", D("145.00"), ("Check 1021",), check_no="1021"),
    Txn(12, "check", D("62.50"), ("Check 1022",), check_no="1022"),
    Txn(19, "check", D("300.00"), ("Check 1024",), check_no="1024", gap=True),
    Txn(27, "check", D("88.75"), ("Check 1025",), check_no="1025"),

    # ---- service fee (page 2) ----
    Txn(31, "fee", D("12.00"), ("Monthly Maintenance Fee",)),
]


# --------------------------------------------------------------------------------------------------
# Derived figures (computed — never hand-typed)
# --------------------------------------------------------------------------------------------------
def _sum(section: str) -> D:
    return sum((t.amount for t in TRANSACTIONS if t.section == section), D("0.00"))


TOTAL_CREDITS = _sum("credit")
TOTAL_WITHDRAWALS = _sum("withdrawal")     # non-check, non-fee subtractions
TOTAL_CHECKS = _sum("check")
TOTAL_FEES = _sum("fee")
TOTAL_DEBITS = TOTAL_WITHDRAWALS + TOTAL_CHECKS + TOTAL_FEES
ENDING_BALANCE = BEGINNING_BALANCE + TOTAL_CREDITS - TOTAL_DEBITS


def credits() -> list[Txn]:
    return [t for t in TRANSACTIONS if t.section == "credit"]


def withdrawals() -> list[Txn]:
    return [t for t in TRANSACTIONS if t.section == "withdrawal"]


def checks() -> list[Txn]:
    return [t for t in TRANSACTIONS if t.section == "check"]


def fees() -> list[Txn]:
    return [t for t in TRANSACTIONS if t.section == "fee"]


def daily_ending_balances() -> list[tuple[int, D]]:
    """Fold the ledger day-by-day; one row per day that has activity."""
    bal = BEGINNING_BALANCE
    out: list[tuple[int, D]] = []
    for day in sorted({t.day for t in TRANSACTIONS}):
        for t in (x for x in TRANSACTIONS if x.day == day):
            bal += t.signed
        out.append((day, bal))
    return out


def money(d: D) -> str:
    return f"${d:,.2f}"


# --------------------------------------------------------------------------------------------------
# Disclosures
#   Reg E error-resolution notice = VERBATIM public-domain model clause (12 C.F.R.
#   Part 1005 App. A §1005.8(b)), bracket fields filled with fictional values.
#   All OTHER disclosures are ORIGINAL prose authored for this fixture,
#   never copied from any bank.
# --------------------------------------------------------------------------------------------------
REG_E_HEADING = "In Case of Errors or Questions About Your Electronic Transfers"
_BANK_WRITE_US = f"{BANK_NAME}, P.O. Box 4827, Boise, ID 83701"
REG_E_PARAS = [
    f"Telephone us at {CUSTOMER_SERVICE_PHONE} or Write us at {_BANK_WRITE_US} as soon as you can, "
    "if you think your statement or receipt is wrong or if you need more information about a transfer "
    "on the statement or receipt. We must hear from you no later than 60 days after we sent you the "
    "FIRST statement on which the error or problem appeared.",
    "(1) Tell us your name and account number (if any).",
    "(2) Describe the error or the transfer you are unsure about, and explain as clearly as you can "
    "why you believe it is an error or why you need more information.",
    "(3) Tell us the dollar amount of the suspected error.",
    "We will investigate your complaint and will correct any error promptly. If we take more than 10 "
    "business days to do this, we will credit your account for the amount you think is in error, so "
    "that you will have the use of the money during the time it takes us to complete our investigation.",
]

OTHER_DISCLOSURES = [
    ("Changing Your Address",
     f"To report a change of address, please call us at {CUSTOMER_SERVICE_PHONE} so we can keep your "
     "account records current."),
    ("How Your Balance Is Determined",
     "Your ending balance equals your beginning balance plus deposits and other credits, less checks, "
     "withdrawals, other subtractions, and any service fees posted during the statement period. The "
     "monthly maintenance fee shown in the account summary is assessed once per statement cycle."),
    ("Overdrafts and Returned Items",
     "If a transaction posts against insufficient available funds, it may be returned unpaid or create "
     "an overdraft, and a fee may apply as described in your fee schedule. Coverage of everyday debit "
     "card and ATM transactions applies only if you have asked us to provide it."),
    ("Your Account Agreement",
     f"This account is governed by your {BANK_NAME} Deposit Account Agreement and the accompanying fee "
     "schedule, which set out the terms, fees, and disclosures that apply to your account. Please keep "
     "them with your records; copies are available on request by calling the number above."),
    ("Please Review This Statement Promptly",
     "Except for the electronic transfers covered by the notice above, if you believe a check or other "
     "item shown here is in error or unauthorized, tell us within the time period described in your "
     f"Deposit Account Agreement so we can help. If you receive direct deposits, you can confirm a "
     f"deposit has posted by reviewing this statement or by calling {CUSTOMER_SERVICE_PHONE}."),
]


if __name__ == "__main__":
    bals = daily_ending_balances()
    print("transactions:", len(TRANSACTIONS),
          "| credits:", len(credits()), "withdrawals:", len(withdrawals()),
          "checks:", len(checks()), "fees:", len(fees()))
    print("BEGINNING       ", money(BEGINNING_BALANCE))
    print("TOTAL_CREDITS   ", money(TOTAL_CREDITS))
    print("TOTAL_WITHDRAWLS", money(TOTAL_WITHDRAWALS))
    print("TOTAL_CHECKS    ", money(TOTAL_CHECKS))
    print("TOTAL_FEES      ", money(TOTAL_FEES))
    print("TOTAL_DEBITS    ", money(TOTAL_DEBITS))
    print("ENDING          ", money(ENDING_BALANCE))
    print("ending check    ", money(BEGINNING_BALANCE + TOTAL_CREDITS - TOTAL_DEBITS))
    print("distinct days   ", len(bals), "min daily bal:", money(min(b for _, b in bals)))
    print("daily:", [(d, str(b)) for d, b in bals])
