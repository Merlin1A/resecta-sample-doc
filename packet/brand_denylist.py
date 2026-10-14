"""The brand denylist shared by the statement acceptance suite (verify.py) and the packet
acceptance (packet/acceptance.py): real company and agency names that must not appear in any
generated document's text or in the values module. The list is the build brief's
safety_constraints denylist, unchanged."""

from __future__ import annotations

import re

DENYLIST: list[str] = [
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


# Names the packet acceptance exempts, each with the packet text that carries it: the 1040-like and
# W-2-like exhibits print the specimen disclaimer "Not an IRS form." -- the agency named is the one
# the sentence disclaims. The statement suite exempts nothing.
PACKET_DISCLAIMER_NAMES: tuple[str, ...] = ("IRS",)


def denylist_hits(text: str, *, exempt: tuple[str, ...] = ()) -> list[str]:
    """The denylisted names present in ``text`` (word-boundary, case-insensitive), in list order,
    minus the names in ``exempt``."""
    return [
        t
        for t in DENYLIST
        if t not in exempt and re.search(r"\b" + re.escape(t) + r"\b", text, re.I)
    ]
