"""The synthetic value set of the hidden-layer family, minted once.

Every person and organization here is invented. Telephone numbers sit in the 555-0100 to 555-0199
block reserved for fiction; e-mail domains are the RFC 2606 example domains; the ZIP code 00000 and
the state code ZZ are never assigned; Social Security numbers use area 000, which is never issued;
the card number is a published test number. No value is taken from a real document.
"""

from __future__ import annotations

PERSON = {"first": "Teodora", "last": "Delgado", "full": "Teodora Delgado"}
SIGNER = "Lee"
OTHERS = ("Hartigan", "Okafor")
ORG = "Fallowmere Mutual Savings"
OFFICE = "Fallowmere Records Office"
STREET = "418 Quarry Bend Road"
CITY_LINE = "Fallowmere, ZZ 00000"
PHONE = "(206) 555-0143"
PHONE_2 = "(206) 555-0187"
EMAIL = "t.delgado@example.org"
EMAIL_2 = "records@example.com"
SSN = "000-41-7720"
DOB = "03/14/1979"
ACCOUNT = ("0000", "4471", "2290", "18")
CARD = "4111 1111 1111 1111"
CASE_NO = "CV-0000-0417"
DATE = "October 30, 2026"

# How the hidden layer may misread the printed surname (a substitution and a split).
MISREAD_SUBSTITUTE = "Delgaclo"
MISREAD_SPLIT = ("Del", "gado")

# The lines every layout carries, in this order: the region scenarios target words on them.
# Keys name the lines; the scenario table in scenarios.py refers to them by key.
SCENARIO_LINES: tuple[tuple[str, str], ...] = (
    ("ask", "Questions about this notice go to the office named below."),
    ("contact", f"Contact {PERSON['full']} about the file today."),
    ("signed", f"Signed by {SIGNER} on the date below."),
    ("holds", "The file holds the plan, the notes and the final summary."),
    ("copies", f"Copies went to {OTHERS[0]} and {OTHERS[1]} last week."),
    ("account", f"Account {' '.join(ACCOUNT)} is held for this file."),
)
