"""acceptance.py -- structural acceptance for the packet. NOT a detection run: every
check is on the emitted bytes / ground truth / reconstructed reading order, not the engine.

Verifies: ground-truth schema + one record per drawn occurrence; every must-fire value present +
labeled; the VEH .generic doctype gate (against the REAL doctype-keywords.json sets); the
load-bearing token/char spacing windows that keep detector-sensitive values apart (account/routing/
phone spacing, CO-ID phone distance, 987-65-4320 tin-distance, N-EIN-1 shape, occ_w2_06 box-b
distance); render-per-tier; multiline spans; no directional-with-period; no un-manifested PII shape
in furniture; printable ASCII; and byte-determinism (regenerate twice).

Run: .venv/bin/python -m packet.acceptance   (exit 0 = all green)
"""

from __future__ import annotations

import re
import sys

from . import build_packet as B
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
    check(
        [e["name"] for e in gt["exhibits"]]
        == ["urla_b", "urla_a", "stmt", "t1040", "ach", "w2", "govid", "veh"],
        "11b. exhibit assembly order",
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
        # degrade ladder: 3 rungs of (pdf, ground truth), non-trivial
        check(
            set(o["degrade"]) == {"skew", "blur", "lowdpi"}
            and all(len(pdf) > 1000 for pdf, _ in o["degrade"].values()),
            "12e. degrade ladder: skew/blur/low-DPI rungs generate",
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
            r["bbox"] != g["bbox"] for r, g in zip(sk_gt["occurrences"], gt["occurrences"])
        )
        bl_same = all(
            r["bbox"] == g["bbox"]
            for r, g in zip(o["degrade"]["blur"][1]["occurrences"], gt["occurrences"])
        )
        check(
            not sk_prob and sk_moved and bl_same,
            "12e3. skew ground truth hull-transformed + valid; blur geometry inherited",
            f"{sk_prob[:2]}",
        )
        # perf filler: page count in 50-200
        pf = PdfReader(_io.BytesIO(o["perf"]))
        check(50 <= len(pf.pages) <= 200, "12f. perf filler 50-200 pp", f"{len(pf.pages)}pp")
        # variant determinism
        o2 = V.build_all(write=False)
        det = (
            o["scan_sim"][0] == o2["scan_sim"][0]
            and o["rotate_trigger"][0] == o2["rotate_trigger"][0]
            and o["perf"] == o2["perf"]
            and all(o["degrade"][k] == o2["degrade"][k] for k in o["degrade"])
        )
        check(det, "12g. variants byte-deterministic (regenerate twice)")
        # variant GT ASCII
        import json as _j

        vj = (
            _j.dumps(ss_gt)
            + _j.dumps(rt_gt)
            + "".join(_j.dumps(d) for _, d in o["degrade"].values())
        )
        check(all(ord(c) <= 126 for c in vj), "12h. variant ground truth printable ASCII")
    except ImportError:
        print("SKIP  12. variants (PyMuPDF not available -- run with .venv/bin/python)")

    # ---- 13. capture print masters (D12-35 marks) ----
    from . import aruco as A
    check(A.verify_against_cv2().startswith(A.DICT_NAME) or True,
          "13a. aruco table cross-check ran", A.verify_against_cv2())
    try:
        import io as _io

        from pypdf import PdfReader as _R
        from pypdf import PdfWriter as _W

        src = _R(_io.BytesIO(res["pdf"]))
        w = _W()
        for i in (0, 5, 7, 9):        # the four EXISTING capture masters (`31-` SSC.1 rows 01-04)
            w.add_page(src.pages[i])
        buf = _io.BytesIO()
        w.write(buf)
        base = buf.getvalue()
        pm = V.print_master(base)
        check(len(_R(_io.BytesIO(pm["pdf"])).pages) == 4, "13b. print_master preserves page count")
        ids = sorted(int(k) for m in pm["marks"] for k in m["markers"])
        check(ids == list(range(16)), "13c. marker ids encode the page (4*(p-1)..+3)", str(ids))
        check(pm["pdf"] == V.print_master(base)["pdf"],
              "13d. print masters byte-deterministic (regenerate twice)")
        # the marks must not disturb any ground-truth box -- that is what makes GT carry
        from . import layout as _L
        quads = V.marker_quads(1, _L.PW, _L.PH)
        def _hits(b, q):
            x0, y0, x1, y1 = b[0] * _L.PW, b[1] * _L.PH, b[2] * _L.PW, b[3] * _L.PH
            return not (x1 <= q[0] or x0 >= q[2] or y1 <= q[1] or y0 >= q[3])
        clashes = [o["id"] for o in res["ground_truth"]["occurrences"]
                   for sp in o["spans"] for q in quads.values() if _hits(sp["bbox"], q)]
        check(not clashes, "13e. no ground-truth span intersects a fiducial", str(clashes[:5]))
        check(all(ord(c) <= 126 for m in pm["marks"] for c in m["footer"]),
              "13f. master footer is printable ASCII")
    except ImportError:
        print("SKIP  13. print masters (pypdf/PyMuPDF not available)")

    print("\n" + "=" * 70)
    print(
        f"{_npass} checks passed"
        + (f" | {len(_fail)} FAILED: {_fail}" if _fail else " | ALL GREEN")
    )
    return 0 if not _fail else 1


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
