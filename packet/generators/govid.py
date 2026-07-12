"""govid.py -- government-ID / KYC verification block (1pp). DL = California, passport = Mexico.
driversLicense/passport are NOT doctype-gated, so a financial-genre ID block exercises
them legitimately.

Label discipline: the real DOBs are anchored "Date of Birth:" (label-anchored path fires on
financial); the expiry / issue dates carry NON-DOB labels ("License Expires:", "Date of Issue:")
that do not contain the "date of birth" anchor, so they stay suppressed. DL/passport negatives sit at
the length extremes (too long / too short / all-numeric) so the per-state/issuer gazetteer suppresses
them.

Every character is printable ASCII.
"""
from __future__ import annotations

from .. import layout as L
from .. import occurrences as OCC
from . import _common as C

G = OCC.BY_ID


def draw(rc, base_page: int) -> None:
    rc.begin_page(base_page)
    y = L.form_title(rc, "Government-Issued Identification Verification",
                     "Know-Your-Customer (KYC) identity verification record.",
                     "Quillhaven Lending")

    # ---- primary applicant identity ----
    y = L.section_bar(rc, y, "Primary Applicant Identity")
    y = C.frow(rc, y, G["occ_govid_01"])               # Full Legal Name: Delia
    y = C.frow(rc, y, G["occ_govid_03"])               # Date of Birth: (anchored -> fires)
    y = C.frow_multi(rc, y, G["occ_govid_05"], step=8) # Current Residential Address:

    # ---- driver's license block (California) ----
    y = L.section_bar(rc, y, "Driver's License (Primary Photo ID)")
    y = C.frow(rc, y, G["occ_govid_06"])               # Driver's License: D4729153 (CA pattern)
    y = C.frow(rc, y, G["occ_govid_07"])               # Primary ID verified -- Driver's License:
    y = C.frow(rc, y, G["occ_govid_11"])               # License Expires: (bare date, NON-DOB label)
    y = C.frow(rc, y, G["occ_govid_08"], step=18)      # Secondary ID DL (too long -> suppressed)

    # ---- passport block (Mexico; co-applicant) ----
    y = L.section_bar(rc, y, "Passport (Co-Applicant)")
    y = C.frow(rc, y, G["occ_govid_02"], vfont=L.SEMI) # Name (as shown on passport): ALL-CAPS SF
    y = C.frow(rc, y, G["occ_govid_04"])               # Date of Birth: Mateo (anchored)
    y = C.frow(rc, y, G["occ_govid_09"])               # Passport No: N42851960 (MX pattern)
    y = C.frow(rc, y, G["occ_govid_12"])               # Passport Date of Issue: (bare date, NON-DOB)
    y = C.frow(rc, y, G["occ_govid_10"])               # Prior Passport No: (too short -> suppressed)
    y = C.frow(rc, y, G["N-PP-1"])                      # Legacy / Prior Passport No: (all-numeric)
    y = C.frow(rc, y, G["N-PP-2"], step=18)            # Transcription-error Passport No: (bad len)

    # ---- verification attestation (density) ----
    y = L.heading(rc, y, "Verification Attestation")
    y = C.fine_print(rc, y, [
        "The identity documents listed above were reviewed for this synthetic verification record. The "
        "document identifiers, names, and dates shown are fictional and disclosed in the accompanying "
        "manifest. This record exists so identity-verification software can be checked against the "
        "label grammar a real KYC review uses, without handling a real person's documents.",
        "Secondary and prior document entries are retained for completeness; entries that do not match "
        "a recognized issuer pattern are kept on file but are not treated as a verified identifier.",
    ])
    ynext = C.signature_line(rc, y, "Reviewer Initials")
    C.disclosures(rc, ynext - 6, title="KYC Authorizations")

    C.page_footer(rc, "Page 11 of 12")
    rc.end_page()
