"""stmt.py -- the FROZEN bank statement exhibit. NOT drawn: embedded at the current bytes and
its records CARRIED from the values manifest (the measured/frozen rows).

Because the statement is frozen and shifts to packet pages 3-5, per-detection bboxes for it are not
resolved (the carried rows are aggregated, measured counts). These carried records therefore ship
with bbox=null / measured_pending=true; their geometry is not resolved on the assembled packet.
They live in the ground truth's `carried_stmt` array, distinct from the 106 draw-time
`occurrences`, and the acceptance suite checks them by count, not by rectangle.

Every character is printable ASCII.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from ..schema import SCHEMA_VERSION

_REPO = Path(__file__).resolve().parent.parent.parent
# The local repo copy is byte-identical to the FROZEN engine resource
# ~/resecta/Resources/SampleDocument.pdf (verified SHA, 2026-06-14).
FROZEN_STMT_PATH = _REPO / "sample-bank-statement.pdf"
FROZEN_STMT_SHA256 = "992ca0543eb1a2eaab8d8dba0a4ad4b8339cf95b804a0347ab1b0987ce18fa20"
STMT_PAGE_COUNT = 3
STMT_PACKET_BASE_PAGE = 3  # 0-indexed: STMT occupies packet pages 3, 4, 5


def frozen_bytes() -> bytes:
    data = FROZEN_STMT_PATH.read_bytes()
    got = hashlib.sha256(data).hexdigest()
    if got != FROZEN_STMT_SHA256:
        raise SystemExit(
            f"FROZEN statement drift: {FROZEN_STMT_PATH} sha256={got}, expected {FROZEN_STMT_SHA256}"
        )
    return data


# --------------------------------------------------------------------------------------------------
# Carried measured classes. One entry per distinct (value/class, category, tier,
# leg); `count` records the measured multiplicity. Page indices are 0-based WITHIN the statement
# (0,1,2); the packet offset (+3) is applied when emitted. bbox stays null (measured_pending).
# Tuple layout: ref, value, category, tier, legs, stmt_page_or_None, count, note
# --------------------------------------------------------------------------------------------------
CARRIED = [
    (
        "stmt_mf_email",
        "d.hartwell@example.net",
        "email",
        "MF",
        ("text", "ocr"),
        0,
        1,
        "conf 0.90 (= occ_urlab_13 value -- consistent).",
    ),
    (
        "stmt_mf_addr",
        "Boise ID 83701/83702 + institution/holder/P.O. Box 4827/Reg E blocks",
        "address",
        "MF",
        ("text", "ocr"),
        None,
        5,
        "assembled address spans.",
    ),
    (
        "stmt_mf_phone",
        "800-555-0199",
        "phone",
        "MF",
        ("text",),
        2,
        3,
        "Reg E, context-boosted 0.80.",
    ),
    (
        "stmt_mf_name",
        "Hartwell",
        "name",
        "MF",
        ("text",),
        None,
        2,
        "only NLTagger-tagged Hartwell form.",
    ),
    (
        "stmt_mf_acctphone",
        "4100773265",
        "phone",
        "MF",
        ("text", "ocr"),
        0,
        2,
        "NANP shape wins overlap vs account 0.75 (Probe B). last-4 3265 = occ_urlab_18 tie.",
    ),
    (
        "stmt_mnf_ocrconcat_1",
        "0510112026",
        "account",
        "MNF",
        ("ocr",),
        0,
        1,
        "OCR-concatenated date -> false account.",
    ),
    (
        "stmt_mnf_ocrconcat_2",
        "0513112026",
        "account",
        "MNF",
        ("ocr",),
        1,
        1,
        "OCR-concatenated date -> false account.",
    ),
    (
        "stmt_mnf_ocrconcat_3",
        "0610112026",
        "account",
        "MNF",
        ("ocr",),
        2,
        1,
        "OCR-concatenated date -> false account.",
    ),
    (
        "stmt_mnf_acctasacct",
        "4100773265",
        "account",
        "MNF",
        ("text", "ocr"),
        0,
        1,
        "detected 0.75 then overlap-suppressed to phone (aspirational should-fire-as-account).",
    ),
    (
        "stmt_mnf_nameprec",
        "POS / Pos / Lulu / P.o",
        "name",
        "MNF",
        ("text", "ocr"),
        None,
        4,
        "NLTagger mis-tag, bloom-confirmed -> precision hazard.",
    ),
    (
        "stmt_mnf_coid",
        "9100004821 / 8120049173 / 7330081265 / 6650094412 / 5540063370",
        "phone",
        "MNF",
        ("text", "ocr"),
        None,
        6,
        "near ID:, no acct kw; sub-threshold phone 0.60 < 0.70.",
    ),
    (
        "stmt_mnf_dob",
        "statement/transaction dates",
        "dateOfBirth",
        "MNF",
        ("text", "ocr"),
        None,
        1,
        "label-anchored-only gate holds (bare dates suppressed).",
    ),
    (
        "stmt_mnf_trap_addr",
        "BOISE ID / MERIDIAN ID",
        "address",
        "MNF",
        ("text", "ocr"),
        None,
        2,
        "state-abbrev trap held silent (address aspect).",
    ),
    (
        "stmt_mnf_trap_dl",
        "BOISE ID / MERIDIAN ID",
        "driversLicense",
        "MNF",
        ("text", "ocr"),
        None,
        2,
        "state-abbrev trap held silent (DL aspect).",
    ),
    (
        "stmt_sf_indn",
        "INDN: DELIA HARTWELL",
        "name",
        "SF",
        ("text", "ocr"),
        None,
        6,
        "NLTagger-limited miss (ALL-CAPS + INDN prefix).",
    ),
    (
        "stmt_sf_mi",
        "Delia R. Hartwell",
        "name",
        "SF",
        ("text", "ocr"),
        None,
        1,
        "middle-initial span break.",
    ),
    (
        "stmt_sf_firstinit",
        "MARCUS B / JORDAN K / PRIYA S",
        "name",
        "SF",
        ("text", "ocr"),
        None,
        3,
        "first+initial NLTagger-limited.",
    ),
    (
        "stmt_watch_acct",
        "XXXXXX3265",
        "account",
        "W",
        ("text", "ocr"),
        0,
        1,
        "masked -> invisible.",
    ),
    (
        "stmt_watch_phone",
        "800-555-0199",
        "phone",
        "W",
        ("text", "ocr"),
        0,
        1,
        "sub-threshold on page 0.",
    ),
    (
        "stmt_watch_coid",
        "CO-IDs near ID:",
        "phone",
        "W",
        ("text", "ocr"),
        None,
        1,
        "sub-threshold CO-ID class.",
    ),
]

TIER = {"MF": "must_fire", "SF": "should_fire", "W": "watch", "MNF": "must_not_fire"}


def carried_records() -> list[dict]:
    """Ground-truth-shaped carried records (bbox=null, measured_pending=true). Page is the packet-global index
    (STMT base + stmt_page) when the manifest pins a page, else null (assembled across pages)."""
    out = []
    for ref, value, cat, tier, legs, spage, count, note in CARRIED:
        page = (STMT_PACKET_BASE_PAGE + spage) if spage is not None else None
        out.append(
            {
                "id": ref,
                "value": value,
                "category": cat,
                "page": page,
                "bbox": None,
                "bbox_origin": "bottom-left",
                "expectation": TIER[tier],
                "leg_applicability": list(legs),
                "label_context": "",
                "context_class": "none",
                "caption_clearance_pt": None,
                "caption_text": None,
                "render": {"all_caps": False, "masked": value.startswith("X"), "multiline": False},
                "spans": [],
                "overlaps": [],
                "count": count,
                "measured_pending": True,
                "justification": note,
                "source_range": "frozen statement; geometry not resolved (measured_pending)",
                "schema_version": SCHEMA_VERSION,
            }
        )
    return out
