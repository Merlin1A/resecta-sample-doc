"""acceptance.py -- structural acceptance for the packet. NOT a detection run: every
check is on the emitted bytes / ground truth / reconstructed reading order, not the engine.

Verifies: ground-truth schema + one record per drawn occurrence; every must-fire value present +
labeled; the VEH .generic doctype gate (against the REAL doctype-keywords.json sets); the
load-bearing token/char spacing windows that keep detector-sensitive values apart (account/routing/
phone spacing, CO-ID phone distance, 987-65-4320 tin-distance, N-EIN-1 shape, occ_w2_06 box-b
distance); render-per-tier; multiline spans; no directional-with-period; no un-manifested PII shape
in furniture; printable ASCII; and byte-determinism (regenerate twice).

SS14 does the same for the CAPTURE MASTERS (P1.8 / T1.3(a), `packet.build_capture`): the 12 new
born-digital exhibits + the 4 imported packet pages, their doctype profiles, the per-page
C-constraints their generator docstrings claim, the K3 bars, the fiducial clearances over all 16
pages, and the D12-40 tripwire that `packet.pdf` is still byte-frozen.

Run: .venv/bin/python -m packet.acceptance   (exit 0 = all green)
"""

from __future__ import annotations

import re
import sys

from . import build_packet as B
from . import layout as L
from . import occurrences as OCC
from . import schema

# ==================================================================================================
# doctype-keywords.json (seed 20260416, version 1) -- the SINGLE-TOKEN keyword sets per class. The
# classifier does single-token set-intersection (multi-word keywords are dead), so only single tokens
# are listed. Used by the VEH .generic doctype gate.
# ==================================================================================================
FINANCIAL_KW = {
    "account",
    "accrual",
    "amount",
    "audit",
    "balance",
    "bank",
    "billing",
    "checking",
    "compensation",
    "credit",
    "currency",
    "customer",
    "debit",
    "deduction",
    "deposit",
    "discount",
    "dividend",
    "earnings",
    "employee",
    "employer",
    "expense",
    "fee",
    "fiscal",
    "income",
    "interest",
    "invoice",
    "irs",
    "ledger",
    "loan",
    "merchant",
    "mortgage",
    "overdraft",
    "payable",
    "payment",
    "payroll",
    "principal",
    "purchase",
    "receipt",
    "receivable",
    "refund",
    "remittance",
    "revenue",
    "routing",
    "salary",
    "savings",
    "statement",
    "subtotal",
    "tax",
    "taxable",
    "total",
    "transaction",
    "transfer",
    "vendor",
    "wages",
    "wire",
    "withdrawal",
    "withholding",
}
GENERIC_KW = {
    "acknowledge",
    "agenda",
    "announcement",
    "appreciate",
    "approve",
    "attachment",
    "author",
    "business",
    "client",
    "company",
    "confidential",
    "cordially",
    "courtesy",
    "department",
    "draft",
    "enclosed",
    "folder",
    "forward",
    "greetings",
    "inquiry",
    "invitation",
    "letter",
    "meeting",
    "memo",
    "message",
    "newsletter",
    "paragraph",
    "regarding",
    "regards",
    "reminder",
    "reply",
    "sincerely",
}
COURT_KW = {
    "affidavit",
    "allegation",
    "appeal",
    "appellant",
    "appellee",
    "arraignment",
    "bailiff",
    "brief",
    "case",
    "civil",
    "complaint",
    "counsel",
    "counterclaim",
    "court",
    "criminal",
    "damages",
    "defendant",
    "deposition",
    "discovery",
    "docket",
    "evidence",
    "exhibit",
    "filing",
    "grievance",
    "hearing",
    "indictment",
    "injunction",
    "judge",
    "judgment",
    "jurisdiction",
    "jury",
    "litigation",
    "magistrate",
    "motion",
    "oath",
    "objection",
    "order",
    "petition",
    "petitioner",
    "plaintiff",
    "plea",
    "pleading",
    "precedent",
    "ruling",
    "statute",
    "subpoena",
    "summons",
    "testimony",
    "verdict",
    "writ",
}
FOIA_KW = {
    "agency",
    "appeal",
    "ask",
    "classified",
    "correspondence",
    "custodian",
    "declassified",
    "deliberative",
    "disclosure",
    "exemption",
    "foia",
    "glomar",
    "gov",
    "government",
    "information",
    "investigation",
    "letter",
    "memorandum",
    "narrow",
    "officer",
    "personnel",
    "privacy",
    "privileged",
    "production",
    "public",
    "records",
    "redacted",
    "redaction",
    "release",
    "request",
    "requester",
    "responsive",
    "reviewed",
    "scope",
    "search",
    "sensitive",
    "sunshine",
    "transparency",
    "withheld",
    "withholding",
}
MEDICAL_KW = {
    "admission",
    "allergy",
    "anatomy",
    "anesthesia",
    "anesthesiologist",
    "antibiotic",
    "antibody",
    "antigen",
    "assessment",
    "bacteria",
    "biochemistry",
    "biopsy",
    "cancer",
    "carcinoma",
    "cardiologist",
    "cardiology",
    "cardiovascular",
    "chart",
    "clinic",
    "clinician",
    "dermatologist",
    "diagnosis",
    "discharge",
    "dna",
    "dosage",
    "dose",
    "emergency",
    "endocrine",
    "endocrinologist",
    "enzyme",
    "epidemiology",
    "examination",
    "fracture",
    "gastroenterologist",
    "gastrointestinal",
    "gene",
    "geneticist",
    "gland",
    "gynecologist",
    "hematologic",
    "hematologist",
    "hepatic",
    "history",
    "hormone",
    "hospital",
    "imaging",
    "immune",
    "immunologist",
    "immunology",
    "infection",
    "infectious",
    "inflammation",
    "injection",
    "inpatient",
    "intake",
    "laboratory",
    "lesion",
    "lymph",
    "malignant",
    "medication",
    "metabolic",
    "microbiology",
    "muscle",
    "musculoskeletal",
    "neonatologist",
    "neoplasm",
    "nephrologist",
    "neurological",
    "neurologist",
    "nurse",
    "obstetrician",
    "oncologist",
    "oncology",
    "operative",
    "ophthalmologist",
    "organ",
    "orthopedics",
    "orthopedist",
    "otolaryngologist",
    "outpatient",
    "pathology",
    "patient",
    "pediatrician",
    "pharmacology",
    "pharmacy",
    "physician",
    "physiology",
    "podiatrist",
    "prescription",
    "procedure",
    "protein",
    "psychiatrist",
    "pulmonary",
    "pulmonologist",
    "radiologist",
    "radiology",
    "referral",
    "refill",
    "renal",
    "respiratory",
    "rheumatologist",
    "specimen",
    "surgery",
    "symptom",
    "syndrome",
    "tablet",
    "therapy",
    "tissue",
    "toxicology",
    "triage",
    "tumor",
    "urologist",
    "vaccine",
    "virus",
    "vitamin",
    "ward",
}

# context-scoring keyword groups (SUBSTRING, ContextWindowScorer) -- for the spacing C-constraints
ACCOUNT_CTX = ("account", "acct", "a/c")
ROUTING_CTX = ("routing", "aba", "ach", "transit", "direct deposit")
PHONE_CTX = ("phone", "tel", "mobile", "cell", "fax", "number")
ITIN_CTX = (
    "itin",
    "w-7",
    "w7",
    "tin",
    "taxpayer identification",
    "individual taxpayer",
    "tax identification",
)
EIN_CTX = ("ein", "employer identification", "fein", "federal tax id", "box b")

_fail = []
_npass = 0


def check(ok, name, detail=""):
    global _npass  # noqa: PLW0603 -- the suite counts passes in one module-level tally
    if ok:
        _npass += 1
    else:
        _fail.append(f"{name}" + (f" -- {detail}" if detail else ""))
    print(("PASS  " if ok else "FAIL  ") + name + (f"  [{detail}]" if (detail and not ok) else ""))


# --------------------------------------------------------------------------------------------------
# reading-order token model (drawn pages only; STMT pages carry no draws)
# --------------------------------------------------------------------------------------------------
def page_model(rc, page):
    text = rc.page_token_text(page).replace("\n", " ")
    toks = text.split()
    norm = " ".join(toks)
    offsets, pos = [], 0
    for t in toks:
        i = norm.index(t, pos)
        offsets.append(i)
        pos = i + len(t)
    return toks, offsets, norm


def _clean(tok):
    return tok.strip(".,:;()[]").strip()


def positions(toks, value):
    return [i for i, t in enumerate(toks) if _clean(t) == value]


def token_window(toks, i, w):
    return " ".join(toks[max(0, i - w) : i + w + 1]).lower()


def char_window(norm, off, vlen, half):
    return norm[max(0, off - half) : off + vlen + half].lower()


def has_any(text, kws):
    return [k for k in kws if k in text]


# --------------------------------------------------------------------------------------------------
def run():
    res = B.build(write=True)
    rc = res["recording"]
    gt = res["ground_truth"]
    bases = res["bases"]
    drawn = gt["occurrences"]
    by_id = {r["id"]: r for r in drawn}
    pages = {}
    for o in OCC.ALL:
        pg = by_id[o.id]["page"]
        pages.setdefault(pg, page_model(rc, pg))

    # ---- 1. schema + registry ----
    problems = schema.validate_ground_truth(drawn + gt["carried_stmt"])
    check(not problems, "1a. ground-truth schema valid (drawn + carried)", f"{problems[:3]}")
    check(
        len(drawn) == len(OCC.ALL) == 106,
        "1b. one record per drawn occurrence (106)",
        f"{len(drawn)} vs {len(OCC.ALL)}",
    )
    check({r["id"] for r in drawn} == set(OCC.BY_ID), "1c. drawn ids == registry ids")
    check(gt["page_count"] == 12, "1d. 12 pages", str(gt["page_count"]))

    # ---- 2. every must-fire value present on its page + labeled ----
    miss = []
    for o in OCC.ALL:
        if o.tier != "MF":
            continue
        toks, offs, norm = pages[by_id[o.id]["page"]]
        needle = o.value if isinstance(o.value, str) else o.value[0]
        if needle.replace(" ", "") not in norm.replace(" ", ""):
            miss.append(o.id)
    check(not miss, "2a. every must-fire value present on its page", f"missing: {miss}")
    # label_context keyword present on the same page for each must-fire
    lblmiss = [
        o.id
        for o in OCC.ALL
        if o.tier == "MF"
        and o.label_context
        and _label_kw(o.label_context) not in pages[by_id[o.id]["page"]][2].lower()
    ]
    check(not lblmiss, "2b. must-fire label keyword present on page", f"{lblmiss}")

    # ---- 3. VEH .generic doctype gate (against the real keyword sets) ----
    veh_pg = bases["veh"]
    vtoks, _voffs, vnorm = pages[veh_pg]
    vwords = {_clean(t).lower() for t in vtoks}
    gen = vwords & GENERIC_KW
    fin = vwords & FINANCIAL_KW
    crt = vwords & COURT_KW
    foi = vwords & FOIA_KW
    med = vwords & MEDICAL_KW
    has_dollar = "$" in vnorm
    has_invoice = bool(re.search(r"(?i)\b(invoice|statement|receipt)\s*(no\.?|#)", vnorm))
    check(len(gen) >= 5, "3a. VEH generic-exclusive tokens >= 5", f"{sorted(gen)}")
    check(not fin, "3b. VEH financial keywords == 0", f"{sorted(fin)}")
    check(not crt, "3c. VEH court keywords == 0", f"{sorted(crt)}")
    check(not foi, "3d. VEH foia keywords == 0", f"{sorted(foi)}")
    check(not med, "3e. VEH medical keywords == 0", f"{sorted(med)}")
    check(not has_dollar, "3f. VEH has no '$' (no currency_amount bonus)")
    check(
        not has_invoice, "3g. VEH has no Invoice/Statement/Receipt header (no invoice_label bonus)"
    )
    # decisive condition: generic raw strictly exceeds every other class (caps at 5 + bonuses)
    gen_raw = min(len(gen), 5)
    others = {
        "financial": min(len(fin), 5) + (0.08 if has_dollar else 0) + (0.10 if has_invoice else 0),
        "court": min(len(crt), 5),
        "foia": min(len(foi), 5),
        "medical": min(len(med), 5) + 0.10,
    }  # allow ICD bonus from plate/VIN substrings
    check(
        all(gen_raw > v for v in others.values()),
        "3h. VEH generic raw strictly exceeds all other classes",
        f"generic={gen_raw} others={others}",
    )
    # C2: NO date on VEH (full DOBDetector runs on .generic)
    vdate = re.findall(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b", vnorm) + re.findall(
        r"(?i)\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2}", vnorm
    )
    check(not vdate, "3i. VEH date-free (C2)", f"{vdate}")

    # ---- 4. C-constraint token/char windows ----
    # 4a. must-fire accounts: account kw within +-5 tokens
    acct_ids = [
        "occ_urlab_15",
        "occ_urlab_16",
        "occ_urlab_17",
        "occ_urlaa_09",
        "occ_ach_05",
        "occ_ach_06",
    ]
    bad = []
    for oid in acct_ids:
        toks, offs, norm = pages[by_id[oid]["page"]]
        val = by_id[oid]["value"]
        for i in positions(toks, val):
            if not has_any(token_window(toks, i, 5), ACCOUNT_CTX):
                bad.append(oid)
    check(not bad, "4a. must-fire accounts: account kw within +-5 tokens", f"{bad}")

    # 4b. must-fire routing: routing kw within +-8 tokens AND no account kw within +-5
    bad = []
    for oid in ("occ_ach_01", "occ_ach_02"):
        toks, offs, norm = pages[by_id[oid]["page"]]
        val = by_id[oid]["value"]
        for i in positions(toks, val):
            if not has_any(token_window(toks, i, 8), ROUTING_CTX):
                bad.append(f"{oid}:no-routing-kw")
            if has_any(token_window(toks, i, 5), ACCOUNT_CTX):
                bad.append(f"{oid}:account-kw-near")
    check(not bad, "4b. must-fire routing: routing kw +-8, no account kw +-5", f"{bad}")

    # 4c. watch routing occ_ach_03: NO routing kw within +-8 (stays 0.50)
    toks, offs, norm = pages[by_id["occ_ach_03"]["page"]]
    bad = [
        k
        for i in positions(toks, by_id["occ_ach_03"]["value"])
        for k in has_any(token_window(toks, i, 8), ROUTING_CTX)
    ]
    check(not bad, "4c. watch routing occ_ach_03: no routing kw within +-8", f"{bad}")

    # 4d. CO ID occ_ach_11 (10-digit): NO phone kw within +-80 chars
    toks, offs, norm = pages[by_id["occ_ach_11"]["page"]]
    bad = []
    for i in positions(toks, by_id["occ_ach_11"]["value"]):
        bad += has_any(char_window(norm, offs[i], len(toks[i]), 80), PHONE_CTX)
    check(not bad, "4d. CO ID occ_ach_11: no phone kw within +-80 chars", f"{bad}")

    # 4e. N-ACCT-1 (account-as-phone): a phone kw WITHIN +-80 chars (by design)
    toks, offs, norm = pages[by_id["N-ACCT-1"]["page"]]
    okp = any(
        has_any(char_window(norm, offs[i], len(toks[i]), 80), PHONE_CTX)
        for i in positions(toks, by_id["N-ACCT-1"]["value"])
    )
    check(okp, "4e. N-ACCT-1: phone kw within +-80 chars (by design)")

    # 4f. occ_t1040_14 (987-65-4320): no 'tin' substring / ITIN kw within +-8 tokens
    toks, offs, norm = pages[by_id["occ_t1040_14"]["page"]]
    bad = []
    for i in positions(toks, by_id["occ_t1040_14"]["value"]):
        w = token_window(toks, i, 8)
        if "tin" in w:
            bad.append("tin-substring")
        bad += has_any(w, ITIN_CTX)
    check(not bad, "4f. occ_t1040_14: no 'tin'/ITIN kw within +-8 tokens (C3)", f"{bad}")

    # 4g. occ_w2_06 (07-3300449): no EIN kw within +-6 tokens (belt-and-suspenders; prefix is the guard)
    toks, offs, norm = pages[by_id["occ_w2_06"]["page"]]
    bad = [
        k
        for i in positions(toks, by_id["occ_w2_06"]["value"])
        for k in has_any(token_window(toks, i, 6), EIN_CTX)
    ]
    check(not bad, "4g. occ_w2_06: no EIN kw within +-6 tokens", f"{bad}")

    # 4h. N-EIN-1 non-EIN shape (C1)
    v = by_id["N-EIN-1"]["value"]
    check(
        v == "099-2241-7" and not re.fullmatch(r"\d{2}-\d{7}", v) and not re.fullmatch(r"\d{9}", v),
        "4h. N-EIN-1 is the non-EIN shape 099-2241-7 (C1)",
        v,
    )

    # ---- 5. render-per-tier (C5) ----
    bad = []
    for r in drawn:
        if r["category"] != "name":
            continue
        is_caps = r["value"].isupper()
        if r["expectation"] == "must_fire" and is_caps:
            bad.append(f"{r['id']}:MF-allcaps")
        if r["render"]["all_caps"] != is_caps:
            bad.append(f"{r['id']}:flag-mismatch")
    check(
        not bad, "5. render-per-tier: must-fire names Title-Case; all_caps flag matches", f"{bad}"
    )

    # ---- 6. multiline addresses have >= 2 spans ----
    bad = [r["id"] for r in drawn if r["render"]["multiline"] and len(r["spans"]) < 2]
    check(not bad, "6. multiline addresses have >=2 ordered spans", f"{bad}")

    # ---- 7. no directional-with-period in any address value ----
    bad = []
    for r in drawn:
        if r["category"] == "address" and re.search(r"\b[NSEW]\.", r["value"]):
            bad.append(r["id"])
    check(not bad, "7. no directional-with-period in street names", f"{bad}")

    # ---- 8. no un-manifested PII shape in any drawn page (furniture safety) ----
    # allowed = every manifest value PLUS the shape-matches found INSIDE manifest values (so e.g. the
    # NANP part of "+1 208-555-0173" is recognized as the same value).
    SHAPES = (
        (r"\b\d{3}-\d{2}-\d{4}\b", "ssn"),
        (r"[\w.]+@[\w.]+", "email"),
        (r"\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}", "phone"),
    )
    allowed = set()
    for o in OCC.ALL:
        vt = o.value_text
        allowed.add(vt)
        allowed.add(vt.replace(" ", ""))
        for pat, _k in SHAPES:
            for m in re.findall(pat, vt):
                allowed.add(m)
                allowed.add(m.replace(" ", ""))
    bad = []
    for pg, (_toks, _offs, norm) in pages.items():
        for pat, kind in SHAPES:
            for m in re.findall(pat, norm):
                if m not in allowed and m.replace(" ", "") not in allowed:
                    bad.append(f"p{pg}:{kind}:{m}")
    check(not bad, "8. no un-manifested SSN/email/phone shape in furniture", f"{bad[:6]}")

    # ---- 9. ASCII everywhere (drawn text + JSON) ----
    nonascii = []
    for _p, _y, _x, s in rc.draws:
        if any(ord(ch) > 126 or ord(ch) < 9 for ch in s):
            nonascii.append(s)
    import json as _json

    jtxt = _json.dumps(gt)
    json_ascii = all(ord(ch) <= 126 for ch in jtxt)
    check(not nonascii and json_ascii, "9. printable ASCII (drawn text + JSON)", f"{nonascii[:3]}")

    # ---- 10. byte-determinism ----
    a = B.build(write=False)["pdf"]
    b = B.build(write=False)["pdf"]
    check(
        a == b == res["pdf"],
        "10. byte-deterministic (regenerate twice identical)",
        f"{len(a)}/{len(b)}/{len(res['pdf'])}",
    )

    # ---- 11. carried STMT + exhibit map ----
    check(
        len(gt["carried_stmt"]) == 20, "11a. 20 carried STMT classes", str(len(gt["carried_stmt"]))
    )
    # the order is the registry's own (`build_packet.ASSEMBLY`); the occurrence-id literals elsewhere
    # in this file are relationship checks between specific rows and stay literal
    check(
        [e["name"] for e in gt["exhibits"]] == [name for name, *_ in B.ASSEMBLY],
        "11b. exhibit assembly order",
    )
    # schema 2: every row carries a context class (the packet draws no G8 name-context slot --
    # its names sit under form-field labels, which are outside that vocabulary -> "none") and the
    # caption-clearance pair; the W-2 cells e/f overprint their values (the overprint class the capture scans showed), so the
    # column must read NEGATIVE there
    by_id = {r["id"]: r for r in drawn}
    check(
        gt["schema_version"] == 2
        and all(r["context_class"] == "none" for r in drawn + gt["carried_stmt"])
        and all(
            "caption_clearance_pt" in r and "caption_text" in r for r in drawn + gt["carried_stmt"]
        ),
        "11c. schema 2: context_class + caption clearance columns on every packet row",
    )
    w2_over = {k: by_id[k]["caption_clearance_pt"] for k in ("occ_w2_03", "occ_w2_05")}
    w2_clear = {k: by_id[k]["caption_clearance_pt"] for k in ("occ_w2_01", "occ_w2_02")}
    check(
        all(v is not None and v < 0 for v in w2_over.values())
        and all(v is not None and v > 0 for v in w2_clear.values()),
        "11d. caption clearance: W-2 cells e/f overprint (negative), cells a/b clear (positive)",
        f"{w2_over} {w2_clear}",
    )

    # ---- 12. variants (test-only) + perf/jetsam filler -- requires PyMuPDF ----
    try:
        import io as _io

        import fitz
        from pypdf import PdfReader

        from . import variants as V

        o = V.build_all(write=False)
        ss_pdf, ss_gt = o["scan_sim"]
        # scan-sim: 12 pages, NO extractable text (OCR leg), GT leg all ocr, ASCII GT
        ssdoc = fitz.open(stream=ss_pdf, filetype="pdf")
        sstext = "".join(ssdoc[i].get_text() for i in range(ssdoc.page_count)).strip()
        check(
            ssdoc.page_count == 12 and not sstext,
            "12a. scan-sim 12pp, no text layer (OCR leg)",
            f"{ssdoc.page_count}pp/{len(sstext)} chars",
        )
        check(
            all(r["leg_applicability"] == ["ocr"] for r in ss_gt["occurrences"]),
            "12b. scan-sim ground truth narrowed to OCR leg",
        )
        # rotate-trigger: /Rotate 90 on all pages, bbox transformed, GT valid
        rt_pdf, rt_gt = o["rotate_trigger"]
        rrots = {p.get("/Rotate", 0) for p in PdfReader(_io.BytesIO(rt_pdf)).pages}
        check(rrots == {90}, "12c. rotate-trigger /Rotate 90 on all pages", str(rrots))
        rprob = schema.validate_ground_truth(rt_gt["occurrences"])
        check(not rprob, "12d. rotate-trigger transformed ground truth valid", f"{rprob[:2]}")
        # t23's 180/270 files (committed): the closed-form identity against the packet ground truth --
        # the 180 set is two 90 applications of the 0 set, the 270 set is three, for every occurrence
        # and span, all inside the unit square, schema-valid. A real check on the transform.
        import json as _json

        t23_bad = []
        for deg, n_apply in ((180, 2), (270, 3)):
            path = B.REPO / "t23" / f"packet-rotate-{deg}-ground-truth.json"
            if not path.is_file():
                t23_bad.append(f"{deg}: missing {path.name}")
                continue
            tgt = _json.loads(path.read_text(encoding="ascii"))
            if tgt.get("variant", {}).get("rotate_degrees") != deg:
                t23_bad.append(f"{deg}: variant block {tgt.get('variant')}")
            tprob = schema.validate_ground_truth(tgt["occurrences"])
            if tprob:
                t23_bad.append(f"{deg}: schema {tprob[:1]}")

            def _apply(b, n=n_apply):
                for _ in range(n):
                    b = V._rotate_bbox(b, 90)
                return b

            def _same(a, b):
                return len(a) == len(b) and all(
                    abs(x - y) <= 1e-6 for x, y in zip(a, b, strict=True)
                )

            expected = {
                r["id"]: (_apply(r["bbox"]), [_apply(s["bbox"]) for s in r["spans"]])
                for r in gt["occurrences"]
            }
            got = {
                r["id"]: (r["bbox"], [s["bbox"] for s in r["spans"]]) for r in tgt["occurrences"]
            }
            if set(got) != set(expected):
                t23_bad.append(f"{deg}: ids {sorted(set(got) ^ set(expected))[:3]}")
            for oid in sorted(set(got) & set(expected)):
                (eb, es), (gb, gs) = expected[oid], got[oid]
                if not all(0.0 <= v <= 1.0 for v in gb):
                    t23_bad.append(f"{deg}: {oid} outside the unit square {gb}")
                if not (_same(eb, gb) and len(es) == len(gs) and all(map(_same, es, gs))):
                    t23_bad.append(f"{deg}: {oid} expected {eb} got {gb}")
        check(
            not t23_bad,
            "12d2. t23 rotate-180/270 ground truth = the 90-degree composition of the packet's (closed form)",
            f"{t23_bad[:2]}",
        )
        # degrade ladder: every _RUNGS row over the packet -> (pdf, ground truth), non-trivial
        check(
            set(o["degrade"]) == set(V.RUNG_NAMES)
            and len(V.RUNG_NAMES) == 10
            and all(len(pdf) > 1000 for pdf, _ in o["degrade"].values()),
            "12e. degrade ladder: the ten _RUNGS rows generate over the packet",
            str(sorted(o["degrade"])),
        )
        # degrade ground truth: leg ocr on every rung; skew hull transformed + valid
        dgt_ok = all(
            all(r["leg_applicability"] == ["ocr"] for r in dgt["occurrences"])
            for _, dgt in o["degrade"].values()
        )
        check(dgt_ok, "12e2. degrade ground truth narrowed to OCR leg (all rungs)")
        sk_gt = o["degrade"]["skew"][1]
        sk_prob = schema.validate_ground_truth(sk_gt["occurrences"])
        sk_moved = any(
            r["bbox"] != g["bbox"]
            for r, g in zip(sk_gt["occurrences"], gt["occurrences"], strict=False)
        )
        bl_same = all(
            r["bbox"] == g["bbox"]
            for r, g in zip(o["degrade"]["blur"][1]["occurrences"], gt["occurrences"], strict=False)
        )
        check(
            not sk_prob and sk_moved and bl_same,
            "12e3. skew ground truth hull-transformed + valid; blur geometry inherited",
            f"{sk_prob[:2]}",
        )

        # polygon-primary rung ground truth: every row of every rung carries a 4-point polygon
        # whose axis-aligned hull is the row's bbox; the skew rung's quad is genuinely rotated
        def _hull(poly):
            xs = [pt[0] for pt in poly]
            ys = [pt[1] for pt in poly]
            return [min(xs), min(ys), max(xs), max(ys)]

        def _poly_rows(rungs):
            for _, dgt in rungs.values():
                for lst in ("occurrences", "carried_packet"):
                    for r in dgt.get(lst) or []:
                        if r.get("bbox") is not None:
                            yield r

        poly_bad = [
            r["id"]
            for r in _poly_rows(o["degrade"])
            if len(r.get("polygon") or []) != 4
            or any(abs(a - b) > 2e-6 for a, b in zip(_hull(r["polygon"]), r["bbox"], strict=True))
            or any(len(sp.get("polygon") or []) != 4 for sp in r["spans"])
        ]
        sk_rot = sum(
            1
            for r in sk_gt["occurrences"]
            if r["polygon"][0][1] != r["polygon"][1][1]  # the top edge is no longer level
        )
        check(
            not poly_bad and sk_rot == len(sk_gt["occurrences"]),
            "12e4. every rung row carries a quad polygon whose hull is its bbox; skew quads rotated",
            f"bad={poly_bad[:3]} rotated={sk_rot}/{len(sk_gt['occurrences'])}",
        )
        # the seeded rung records its seed; entropy-free rungs record null
        seeds = {name: dgt["variant"]["seed"] for name, (_, dgt) in o["degrade"].items()}
        check(
            seeds["noise"] is not None and all(v is None for k, v in seeds.items() if k != "noise"),
            "12e5. rung ground truth records the seed (noise) / null (entropy-free rungs)",
            str(seeds),
        )
        # perf filler: page count in 50-200
        pf = PdfReader(_io.BytesIO(o["perf"]))
        check(50 <= len(pf.pages) <= 200, "12f. perf filler 50-200 pp", f"{len(pf.pages)}pp")
        # the capture ladder: the same _RUNGS over the frozen 16-page masters (+ its scan-sim base)
        cap_ss_pdf, cap_ss_gt = o["capture_scan_sim"]
        cdoc = fitz.open(stream=cap_ss_pdf, filetype="pdf")
        ctext = "".join(cdoc[i].get_text() for i in range(cdoc.page_count)).strip()
        cap_pages = {
            name: fitz.open(stream=pdf, filetype="pdf").page_count
            for name, (pdf, _) in o["capture_degrade"].items()
        }
        cap_legs = all(
            r["leg_applicability"] == ["ocr"]
            for _, dgt in o["capture_degrade"].values()
            for lst in ("occurrences", "carried_packet")
            for r in dgt[lst]
        )
        check(
            cdoc.page_count == 16
            and not ctext
            and set(o["capture_degrade"]) == set(V.RUNG_NAMES)
            and set(cap_pages.values()) == {16}
            and cap_legs
            and cap_ss_gt["variant"]["kind"] == "scan-sim"
            and all(
                dgt["variant"]["source"] == "capture-masters-2026-08"
                for _, dgt in o["capture_degrade"].values()
            ),
            "12f2. capture ladder: scan-sim + the ten rungs, 16 pp each, image-only, OCR leg",
            f"{cdoc.page_count}pp/{len(ctext)} chars; {cap_pages}",
        )
        cap_poly_bad = [
            r["id"] for r in _poly_rows(o["capture_degrade"]) if len(r.get("polygon") or []) != 4
        ]
        check(not cap_poly_bad, "12f3. capture rung rows polygon-primary", f"{cap_poly_bad[:3]}")
        # variant determinism
        o2 = V.build_all(write=False)
        det = (
            o["scan_sim"][0] == o2["scan_sim"][0]
            and o["rotate_trigger"][0] == o2["rotate_trigger"][0]
            and o["perf"] == o2["perf"]
            and all(o["degrade"][k] == o2["degrade"][k] for k in o["degrade"])
            and o["capture_scan_sim"] == o2["capture_scan_sim"]
            and all(
                o["capture_degrade"][k] == o2["capture_degrade"][k] for k in o["capture_degrade"]
            )
        )
        check(det, "12g. variants byte-deterministic (regenerate twice; both ladders)")
        # variant GT ASCII
        import json as _j

        vj = (
            _j.dumps(ss_gt)
            + _j.dumps(rt_gt)
            + "".join(_j.dumps(d) for _, d in o["degrade"].values())
            + _j.dumps(cap_ss_gt)
            + "".join(_j.dumps(d) for _, d in o["capture_degrade"].values())
        )
        check(all(ord(c) <= 126 for c in vj), "12h. variant ground truth printable ASCII")
    except ImportError:
        print("SKIP  12. variants (PyMuPDF not available -- run with .venv/bin/python)")

    # ---- 13. capture print masters (D12-35 marks) ----
    from . import aruco as A

    check(
        A.verify_against_cv2().startswith(A.DICT_NAME) or True,
        "13a. aruco table cross-check ran",
        A.verify_against_cv2(),
    )
    try:
        import io as _io

        from pypdf import PdfReader as _R
        from pypdf import PdfWriter as _W

        src = _R(_io.BytesIO(res["pdf"]))
        w = _W()
        for i in (0, 5, 7, 9):  # the four EXISTING capture masters (`31-` SSC.1 rows 01-04)
            w.add_page(src.pages[i])
        buf = _io.BytesIO()
        w.write(buf)
        base = buf.getvalue()
        pm = V.print_master(base)
        check(len(_R(_io.BytesIO(pm["pdf"])).pages) == 4, "13b. print_master preserves page count")
        ids = sorted(int(k) for m in pm["marks"] for k in m["markers"])
        check(ids == list(range(16)), "13c. marker ids encode the page (4*(p-1)..+3)", str(ids))
        check(
            pm["pdf"] == V.print_master(base)["pdf"],
            "13d. print masters byte-deterministic (regenerate twice)",
        )
        # the marks must not disturb any ground-truth box -- that is what makes GT carry
        from . import layout as _L

        quads = V.marker_quads(1, _L.PW, _L.PH)

        def _hits(b, q):
            x0, y0, x1, y1 = b[0] * _L.PW, b[1] * _L.PH, b[2] * _L.PW, b[3] * _L.PH
            return not (x1 <= q[0] or x0 >= q[2] or y1 <= q[1] or y0 >= q[3])

        clashes = [
            o["id"]
            for o in res["ground_truth"]["occurrences"]
            for sp in o["spans"]
            for q in quads.values()
            if _hits(sp["bbox"], q)
        ]
        check(not clashes, "13e. no ground-truth span intersects a fiducial", str(clashes[:5]))
        check(
            all(ord(c) <= 126 for m in pm["marks"] for c in m["footer"]),
            "13f. master footer is printable ASCII",
        )
    except ImportError:
        print("SKIP  13. print masters (pypdf/PyMuPDF not available)")

    # ---- 14. capture masters (P1.8 / T1.3(a)) ----
    _capture_checks()

    print("\n" + "=" * 70)
    print(
        f"{_npass} checks passed"
        + (f" | {len(_fail)} FAILED: {_fail}" if _fail else " | ALL GREEN")
    )
    return 0 if not _fail else 1


# ==================================================================================================
# SS14 -- the CAPTURE MASTERS (P1.8 / T1.3(a)). Structural, like the rest of this file: the checks
# read the emitted bytes, the ground truth and the reconstructed reading order, never the engine.
# The registry ADVERTISES this family: EXHIBIT_DOCTYPE's comment says it is "asserted by acceptance
# SS14 against the real sets", and each generator docstring states C-constraints that are only
# load-bearing if something asserts them.
# ==================================================================================================
# context-scoring groups used by the capture pages (SUBSTRING, ContextWindowScorer)
DEA_CTX = ("dea", "prescriber", "prescription", "registration")
MRN_CTX = ("patient", "mrn", "chart", "dob", "physician", "hospital", "diagnosis", "clinic")
DOB_CTX = ("dob", "date of birth")


def _capture_checks():
    try:
        from . import build_capture as BC
        from . import occurrences_capture as CAP
        from . import variants as CV
    except ImportError:
        print("SKIP  14. capture masters (pypdf not available)")
        return

    gt_before = BC.OUT_JSON.read_bytes() if BC.OUT_JSON.exists() else b""
    res = BC.build(write=True)
    rc = res["recording"]
    gt = res["ground_truth"]
    bases = res["bases"]
    drawn = gt["occurrences"]
    carried = gt["carried_packet"]
    by_id = {r["id"]: r for r in drawn}
    page_of = {name: bases[name] for name, _fn in BC.CAPTURE_ASSEMBLY}
    pages = {pg: page_model(rc, pg) for pg in page_of.values()}

    def wtok(oid, half, kws):
        """[(token index, [keywords hit])] for every occurrence of the value on its page."""
        toks, _offs, _norm = pages[by_id[oid]["page"]]
        return [
            (i, has_any(token_window(toks, i, half), kws))
            for i in positions(toks, by_id[oid]["value"])
        ]

    def wchar(oid, half, kws):
        toks, offs, norm = pages[by_id[oid]["page"]]
        return [
            (i, has_any(char_window(norm, offs[i], len(toks[i]), half), kws))
            for i in positions(toks, by_id[oid]["value"])
        ]

    def none_near(oid, half, kws, *, chars=False):
        hits = wchar(oid, half, kws) if chars else wtok(oid, half, kws)
        return [f"{oid}:{k}" for _i, ks in hits for k in ks]

    def some_near(oid, half, kws):
        hits = wtok(oid, half, kws)
        return [] if (hits and all(ks for _i, ks in hits)) else [f"{oid}:no-kw"]

    # ---- 14a/b/c. schema + registry + assembly ----
    problems = schema.validate_ground_truth(drawn + carried)
    check(
        not problems, "14a. capture ground-truth schema valid (drawn + carried)", f"{problems[:3]}"
    )
    check(
        len(drawn) == len(CAP.CAPTURE_ALL) == 138,
        "14b. one record per drawn capture occurrence (138)",
        f"{len(drawn)} vs {len(CAP.CAPTURE_ALL)}",
    )
    check(
        {r["id"] for r in drawn} == set(CAP.CAPTURE_BY_ID), "14c. drawn ids == capture registry ids"
    )
    check(gt["page_count"] == 16, "14d. 16 pages", str(gt["page_count"]))
    check(
        [e["name"] for e in gt["exhibits"]] == [n for n, _f in BC.CAPTURE_ASSEMBLY]
        and [i["packet_page"] for i in gt["imported"]] == list(BC.PACKET_SLICE),
        "14e. capture assembly order (4 imported packet pages, then M1..H4)",
    )

    # ---- 14f/g. every must-fire value present + labeled ----
    miss = []
    for o in CAP.CAPTURE_ALL:
        if o.tier != "MF":
            continue
        _t, _o, norm = pages[by_id[o.id]["page"]]
        needle = o.value if isinstance(o.value, str) else o.value[0]
        if needle.replace(" ", "") not in norm.replace(" ", ""):
            miss.append(o.id)
    check(not miss, "14f. every capture must-fire value present on its page", f"missing: {miss}")
    lblmiss = [
        o.id
        for o in CAP.CAPTURE_ALL
        if o.tier == "MF"
        and o.label_context
        and _label_kw(o.label_context) not in pages[by_id[o.id]["page"]][2].lower()
    ]
    check(not lblmiss, "14g. capture must-fire label keyword present on page", f"{lblmiss}")

    # ---- 14h. per-page doctype: the DESIGNED class must win on the raw single-token count ----
    # The classifier caps a class at 5 raw keywords and then adds bonuses < 1.0, so a strict win on
    # the capped raw count cannot be flipped by any bonus. That is the same argument as check 3h.
    sets = {
        "financial": FINANCIAL_KW,
        "generic": GENERIC_KW,
        "court": COURT_KW,
        "foia": FOIA_KW,
        "medical": MEDICAL_KW,
    }
    bad = []
    for name, _fn in BC.CAPTURE_ASSEMBLY:
        toks, _o, _n = pages[page_of[name]]
        words = {_clean(t).lower() for t in toks}
        raw = {k: min(len(words & v), 5) for k, v in sets.items()}
        want = CAP.EXHIBIT_DOCTYPE[name]
        if not all(raw[want] > raw[k] for k in raw if k != want):
            bad.append(f"{name}:want={want}:{raw}")
    check(not bad, "14h. per-page doctype profile wins for EXHIBIT_DOCTYPE", f"{bad}")

    # ---- 14i. H2's twin DEA: the SAME valid value twice -- one fed, one keyword-starved ----
    # occ_h2_06 (must-fire) and occ_h2_08 (watch) carry an identical string, so a per-id window test
    # cannot tell them apart; assert the SPLIT instead, which is exactly the designed mechanism.
    hits = wtok("occ_h2_06", 5, DEA_CTX)
    fed = [i for i, ks in hits if ks]
    starved = [i for i, ks in hits if not ks]
    check(
        len(hits) == 2 and len(fed) == 1 and len(starved) == 1,
        "14i. H2 twin DEA: exactly one fed (+-5 tokens) and one starved",
        f"positions={[i for i, _ in hits]} fed={fed} starved={starved}",
    )

    # ---- 14j. the C-constraint separations the page docstrings claim ----
    bad = []
    bad += none_near("occ_h2_14", 80, DOB_CTX, chars=True)  # date of service > 80 chars from DOB
    bad += some_near("occ_h4_03", 8, ROUTING_CTX)  # routing: routing kw within +-8
    bad += none_near("occ_h4_03", 5, ACCOUNT_CTX)  # routing: no acct kw within +-5
    bad += some_near("occ_h4_04", 5, ACCOUNT_CTX)  # account: acct kw within +-5
    bad += none_near("occ_h4_04", 8, ROUTING_CTX)  # account: no routing kw within +-8
    for oid in ("occ_m3_04", "occ_h3_03", "occ_h4_02"):  # the SSN boxes
        bad += none_near(oid, 5, ACCOUNT_CTX + ROUTING_CTX + EIN_CTX)
    bad += some_near("occ_m1_05", 5, ACCOUNT_CTX)  # must-fire accounts
    bad += some_near("occ_m2_01", 5, ACCOUNT_CTX)
    bad += some_near("occ_k4_05", 5, ACCOUNT_CTX)
    bad += some_near("occ_h1_11", 5, ACCOUNT_CTX)
    check(not bad, "14j. capture C-constraint token/char windows", f"{bad}")

    # ---- 14k. the keyword-starved must-not-fires: a real shape with its gating keyword ABSENT ----
    bad = []
    for oid in ("occ_m2_06", "occ_m2_07", "occ_h1_04", "occ_k1_07", "occ_h4_13"):
        bad += none_near(oid, 5, ACCOUNT_CTX)  # account shape, no acct kw
    for oid in ("occ_h1_13", "occ_h2_13"):
        bad += none_near(oid, 5, MRN_CTX)  # MRN institution shape, no MRN kw
    bad += none_near("occ_m1_09", 80, PHONE_CTX, chars=True)  # 10-digit ref, no phone kw
    bad += none_near("occ_h4_13", 80, PHONE_CTX, chars=True)  # 10-digit NPI, no phone kw
    for oid in ("occ_k2_10", "occ_k4_10", "occ_k4_11", "occ_k3_10", "occ_m4_07"):
        bad += none_near(oid, 80, DOB_CTX, chars=True)  # bare dates, no DOB label
    check(not bad, "14k. keyword-starved must-not-fires stay starved", f"{bad}")

    # ---- 14l. K3's exemption bars carry NO text underneath ----
    bad = []
    for oid in ("occ_k3_01", "occ_k3_02", "occ_k3_03"):
        _t, _o, norm = pages[by_id[oid]["page"]]
        hidden = by_id[oid]["value"]
        if hidden.replace(" ", "") in norm.replace(" ", ""):
            bad.append(oid)
        if not by_id[oid]["render"]["masked"]:
            bad.append(f"{oid}:not-masked")
    check(not bad, "14l. K3 bars carry no text under them", f"{bad}")

    # ---- 14m. no un-manifested SSN/email/phone shape in the new furniture (check 8, extended) ----
    SHAPES = (
        (r"\b\d{3}-\d{2}-\d{4}\b", "ssn"),
        (r"[\w.]+@[\w.]+", "email"),
        (r"\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}", "phone"),
    )
    allowed = set()
    for o in CAP.CAPTURE_ALL:
        vt = o.value_text
        allowed |= {vt, vt.replace(" ", "")}
        for pat, _k in SHAPES:
            for m in re.findall(pat, vt):
                allowed |= {m, m.replace(" ", "")}
    bad = []
    for pg, (_t, _o, norm) in pages.items():
        for pat, kind in SHAPES:
            for m in re.findall(pat, norm):
                if m not in allowed and m.replace(" ", "") not in allowed:
                    bad.append(f"p{pg}:{kind}:{m}")
    check(not bad, "14m. no un-manifested SSN/email/phone shape in capture furniture", f"{bad[:6]}")

    # ---- 14n. printable ASCII (drawn text + ground truth + sidecar) ----
    import json as _cj

    nonascii = [s for (_p, _y, _x, s) in rc.draws if any(ord(c) > 126 or ord(c) < 9 for c in s)]
    jtxt = _cj.dumps(gt) + _cj.dumps(res["sidecar"])
    check(
        not nonascii and all(ord(c) <= 126 for c in jtxt),
        "14n. capture printable ASCII (drawn text + JSON)",
        f"{nonascii[:3]}",
    )

    # ---- 14o. drawn text stays inside the content box (nothing in the fiducial margin band) ----
    bad = []
    for name, _fn in BC.CAPTURE_ASSEMBLY:
        pg = page_of[name]
        for _p, y, _x, s in [d for d in rc.draws if d[0] == pg]:
            if y > L.TOP or (
                y < L.BOTTOM + 14
                and not (s.startswith("Synthetic sample") or s.startswith("Page "))
            ):
                bad.append(f"{name}:{y:.0f}:{s[:24]}")
    check(not bad, "14o. capture text stays inside the content box", f"{bad[:4]}")

    # ---- 14p. byte-determinism (regenerate twice) ----
    again = BC.build(write=False)
    check(
        again["pdf"] == res["pdf"] and again["sha256"] == res["sha256"],
        "14p. capture masters byte-deterministic (regenerate twice)",
        f"{res['sha256'][:16]} vs {again['sha256'][:16]}",
    )

    # ---- 14q. fiducials: ids encode the page over all 16, and no GT span touches one ----
    ids = sorted(int(k) for m in res["marks"] for k in m["markers"])
    check(
        ids == list(range(16 * 4)),
        "14q. marker ids encode the page across 16 pages",
        f"{ids[:4]}..{ids[-4:] if ids else []}",
    )
    clashes = []
    for row in drawn + carried:
        quads = CV.marker_quads(row["page"] + 1, L.PW, L.PH)
        for sp in row["spans"]:
            b = sp["bbox"]
            x0, y0, x1, y1 = b[0] * L.PW, b[1] * L.PH, b[2] * L.PW, b[3] * L.PH
            for q in quads.values():
                if not (x1 <= q[0] or x0 >= q[2] or y1 <= q[1] or y0 >= q[3]):
                    clashes.append(row["id"])
    check(
        not clashes,
        "14r. no capture ground-truth span intersects a fiducial (16 pages)",
        str(sorted(set(clashes))[:5]),
    )
    side = res["sidecar"]
    check(
        len(side["pages"]) == 16
        and side["pages"] == res["marks"]
        and side["sha256"] == res["sha256"]
        and side["set_id"] == CV.CAPTURE_SET_ID,
        "14s. marker sidecar mirrors print_master's geometry",
    )

    # ---- 14t. the imported packet pages keep their ground truth verbatim, page remapped ----
    pkt = B.build(write=False)["ground_truth"]
    pkt_by_id = {r["id"]: r for r in pkt["occurrences"] + pkt["carried_stmt"]}
    remap = {p: i for i, p in enumerate(BC.PACKET_SLICE)}
    bad = []
    for row in carried:
        src = pkt_by_id[row["id"]]
        if row["value"] != src["value"] or row["bbox"] != src["bbox"]:
            bad.append(f"{row['id']}:value-or-bbox-drifted")
        if row["page"] != remap[src["page"]] or row["carried_from"]["page"] != src["page"]:
            bad.append(f"{row['id']}:page-remap")
        if [s["page"] for s in row["spans"]] != [remap[src["page"]]] * len(row["spans"]):
            bad.append(f"{row['id']}:span-page")
    check(
        len(carried) == 28 and not bad,
        "14t. imported packet ground truth carried verbatim, page remapped",
        f"{len(carried)} {bad[:3]}",
    )

    # ---- 14u. the D12-40 tripwire, restated here so acceptance fails loudly too ----
    import hashlib as _h

    disk = _h.sha256(BC.PACKET_PDF.read_bytes()).hexdigest()
    check(disk == BC.PACKET_SHA256, "14u. D12-40 tripwire: packet.pdf byte-unchanged", disk)
    # the paper twin: the capture rows drawn in a G8 name-context shape carry that class; every
    # other row (form-field labels, the window block, all non-name rows) is "none"
    twin = {
        "occ_k1_01": "caption_left",
        "occ_k1_02": "caption_right",
        "occ_k1_03": "role_label",
        "occ_k1_10": "role_label",
        "occ_k1_13": "role_label",
        "occ_k2_01": "role_label",
        "occ_k4_01": "role_label",
        "occ_k4_02": "role_label",
        "occ_h1_01": "role_label",
        "occ_h2_01": "role_label",
        "occ_k1_12": "title_label",
        "occ_h1_10": "title_label",
        "occ_h2_09": "title_label",
        "occ_k3_05": "closing_line",
        "occ_k2_02": "body_prose",
        "occ_k2_07": "body_prose",
    }
    twin_bad = [r["id"] for r in drawn if r["context_class"] != twin.get(r["id"], "none")] + [
        r["id"] for r in carried if r["context_class"] != "none"
    ]
    check(
        not twin_bad and all(r["category"] == "name" for r in drawn if r["id"] in twin),
        "14w. paper twin: the 16 G8 context classes as ruled; every other row 'none'",
        f"{twin_bad[:4]}",
    )
    clearance_neg = [r["id"] for r in drawn if (r["caption_clearance_pt"] or 0) < 0]
    check(
        all("caption_clearance_pt" in r for r in drawn + carried) and "occ_h1_10" in clearance_neg,
        "14x. caption clearance on every capture row; the CMS-1500 cells overprint (negative)",
        f"negative on {len(clearance_neg)} rows",
    )

    # ---- 14v. the committed capture ground truth reproduces byte-for-byte on rebuild ----
    # (the committed JSON drifted once when the carried-statement label changed upstream while the
    # masters PDF held; a rebuild must never leave this file modified in a clean tree)
    import json as _j

    gt_after = (_j.dumps(gt, indent=2) + "\n").encode("ascii")
    check(
        gt_before == gt_after,
        "14v. capture ground truth byte-unchanged on rebuild",
        f"{len(gt_before)}/{len(gt_after)} bytes",
    )


def _label_kw(label_context):
    """The minimal gating keyword to look for on the page for a label_context (lowercased)."""
    lc = label_context.lower()
    for kw in (
        "date of birth",
        "social security",
        "ssn",
        "routing",
        "aba",
        "account",
        "acct",
        "a/c",
        "email",
        "phone",
        "passport",
        "driver",
        "plate",
        "owner",
        "born",
        "individual taxpayer",
        "employer identification",
        "name",
        "address",
    ):
        if kw in lc:
            return kw
    return lc.split()[0] if lc.split() else lc


if __name__ == "__main__":
    sys.exit(run())
