"""medical.py -- the C4 medical exhibits (capture packet): H1 a claim-form-STRUCTURED page (the
field STRUCTURE of a health-insurance claim -- our own captions, never a pixel-accurate government
or industry form, DR-4 SS9) and H2 a clinical visit summary with a prescription line.

Both classify .medical (patient / diagnosis / procedure / clinic / physician ... plus the icd_shape,
drug_dosage and vitals_bp bonuses), so MRN, NPI and DEA all run and the FULL DOBDetector runs.
H1 zones: A insured / patient identity (insured id sits > 5 tokens from any acct kw) · B patient
DOB + age + address + telephone + MRN (the MRN's +-5 tokens hold 'patient' / 'dob') · C referring
/ rendering / billing providers (three NPIs, one with a broken check digit) · D service lines
(diagnosis code, procedure, charge without '$') · E patient account + signature stroke · F carrier
block: the claim-control number with NO MRN positive within +-5 tokens.
H2 zones: A letterhead + clinic phone; specimen label (Code 128 barcode + accession number,
keyword-starved) at the right, ABOVE the patient header · B patient header (name, MRN, Patient ID,
DOB) · C narrative (no 'complaint'/'order'/'records' words) · D medication table -- the
keyword-starved DEA (watch) sits > 5 tokens from any dea/prescriber/prescription word · E the
prescription line (dea + prescriber positives adjacent) and the superseded checksum-fail DEA ·
F visit close: date of service (> 80 chars from 'DOB:'), attending provider + NPI.

Every character is printable ASCII.
"""
from __future__ import annotations

from .. import layout as L
from .. import occurrences_capture as OCC
from .. import personas as P
from . import _common as C

G = OCC.CAPTURE_BY_ID


def _box(rc, x0, y, w, h, caption, occ=None, text="", *, vsize=9, tail=""):
    """A numbered claim-form cell: caption at top-left, value (a row) or plain text inside."""
    L.box_caption(rc, x0, y - h, x0 + w, y, caption)
    if occ is not None:
        px = rc.value(occ, x0 + 6, y - h + 6, L.REG, vsize, L.INK)
        if tail:
            rc.text(px + 4, y - h + 6, tail, L.REG, 8, L.GRAY)
    elif text:
        rc.text(x0 + 6, y - h + 6, text, L.REG, vsize, L.INK)


def draw_h1(rc, base_page: int) -> None:
    rc.begin_page(base_page)
    y = L.form_title(rc, "Health Claim -- Field Structure Specimen",
                     "Structure-only specimen for software testing. Not an industry or government form.",
                     "Specimen CLAIM-LIKE")
    W = L.CONTENT_W
    h = 24
    # ---- Zone A: insured / patient identity ----
    _box(rc, L.LEFT, y, W * 0.34, h, G["occ_h1_04"].label_context, G["occ_h1_04"])           # 1a Insured ID
    _box(rc, L.LEFT + W * 0.34, y, W * 0.40, h, "2. " + G["occ_h1_01"].label_context, G["occ_h1_01"],
         tail="(self)")                                                                       # 2 Patient
    _box(rc, L.LEFT + W * 0.74, y, W * 0.26, h, "4. Insured relationship", text="Self")
    y -= h + 2
    # ---- Zone B: DOB + age, address, telephone, MRN ----
    L.box_caption(rc, L.LEFT, y - h, L.LEFT + W * 0.50, y, "3. " + G["occ_h1_02"].label_context)  # Patient Date of Birth:
    px = rc.value(G["occ_h1_02"], L.LEFT + 6, y - h + 6, L.REG, 9, L.INK)
    rc.text(px + 10, y - h + 6, "Sex: F", L.REG, 8.5, L.INK)
    rc.text(px + 50, y - h + 6, "Age: 37", L.REG, 8.5, L.INK)
    _box(rc, L.LEFT + W * 0.50, y, W * 0.50, h, "6. " + G["occ_h1_03"].label_context, G["occ_h1_03"],
         tail="(patient chart)")                                                              # 6 MRN
    y -= h + 2
    L.box_caption(rc, L.LEFT, y - 36, L.LEFT + W * 0.50, y, "5. " + G["occ_h1_09"].label_context)   # Patient Address:
    rc.value_multiline(G["occ_h1_09"], L.LEFT + 6, y - 15, L.REG, 9, L.INK, 11)
    _box(rc, L.LEFT + W * 0.50, y, W * 0.50, 36, "7. " + G["occ_h1_08"].label_context, G["occ_h1_08"])  # Patient Telephone
    y -= 38
    _box(rc, L.LEFT, y, W * 0.34, h, "9. Other insured", text="None")
    _box(rc, L.LEFT + W * 0.34, y, W * 0.33, h, "10. Condition related to employment", text="No")
    _box(rc, L.LEFT + W * 0.67, y, W * 0.33, h, "11. Group No.", text=P.GROUP_NO)
    y -= h + 8

    # ---- Zone C: providers (three NPIs) ----
    y = L.section_bar(rc, y, "Providers")
    _box(rc, L.LEFT, y, W * 0.34, h, "17b. " + G["occ_h1_07"].label_context, G["occ_h1_07"])   # Referring NPI (broken)
    _box(rc, L.LEFT + W * 0.34, y, W * 0.33, h, "24J. " + G["occ_h1_05"].label_context, G["occ_h1_05"])  # Rendering NPI
    _box(rc, L.LEFT + W * 0.67, y, W * 0.33, h, "33. " + G["occ_h1_06"].label_context, G["occ_h1_06"])   # Billing NPI
    y -= h + 2
    L.box_caption(rc, L.LEFT, y - h, L.LEFT + W * 0.50, y, "31. " + G["occ_h1_10"].label_context)  # Rendering Provider: Dr.
    px = rc.value(G["occ_h1_10"], L.LEFT + 6, y - h + 6, L.REG, 9, L.INK)
    rc.text(px + 4, y - h + 6, "(MD), physician of record", L.REG, 8, L.GRAY)
    _box(rc, L.LEFT + W * 0.50, y, W * 0.50, h, "33a. Billing provider", text=P.CLINIC_NAME + ", Nampa ID")
    y -= h + 8

    # ---- Zone D: service lines ----
    y = L.section_bar(rc, y, "Service Lines")
    cols = [(L.LEFT, "Place"), (L.LEFT + 90, "Procedure"), (L.LEFT + 180, "Diagnosis pointer"),
            (L.LEFT + 300, "Charge"), (L.LEFT + 380, "Days/Units"), (L.LEFT + 460, "Emergency")]
    y = C.table_header(rc, y, cols, size=7)
    C.cell(rc, L.LEFT, y, "outpatient clinic")
    C.cell(rc, L.LEFT + 90, y, "99213")
    C.cell(rc, L.LEFT + 180, y, "A")
    C.cell(rc, L.LEFT + 300, y, "142.00")
    C.cell(rc, L.LEFT + 380, y, "1")
    C.cell(rc, L.LEFT + 460, y, "No")
    y -= 14
    lx = rc.text(L.LEFT, y, "21. " + G["occ_h1_12"].label_context, L.MED, 8, L.GRAY)     # Diagnosis Code:
    px = rc.value(G["occ_h1_12"], lx + 4, y, L.REG, 9, L.INK)                             # E11.9
    rc.text(px + 8, y, "(pointer A) -- prior authorization on file: yes", L.REG, 8, L.GRAY)
    y -= 22

    # ---- Zone E: patient account + signature stroke ----
    y = L.section_bar(rc, y, "Patient Account and Authorization")
    y = C.frow(rc, y, G["occ_h1_11"], step=16)                                            # Patient Account No.
    rc.text(L.LEFT, y, "12. Patient authorization to release payment to the provider -- signed below.",
            L.REG, 8.5, L.GRAY)
    y -= 16
    rc.text(L.LEFT, y, G["occ_h1_14"].label_context, L.MED, 9, L.GRAY)                    # Signature:
    C.signature_stroke(rc, G["occ_h1_14"], L.LEFT + 70, y - 4)
    y -= 34

    # ---- Zone F: carrier block (claim control number, keyword-starved for MRN) ----
    rc.hrule(y + 10, L.LEFT, L.RIGHT, L.RULE, 0.6)
    rc.text(L.LEFT, y, "Carrier use only.", L.SEMI, 8, L.ACCENT)
    lx = rc.text(L.LEFT + 90, y, G["occ_h1_13"].label_context, L.MED, 8, L.GRAY)          # Claim Control No.
    px = rc.value(G["occ_h1_13"], lx + 4, y, L.REG, 9, L.INK)                             # HCF-2026041
    rc.text(px + 10, y, "Batch 14, entry 0092. Adjudicated as billed.", L.REG, 8, L.GRAY)
    y -= 12
    rc.text(L.LEFT, y, "Specimen prepared for software testing; every person, identifier, and charge shown is "
            "fictional and disclosed.", L.REG, 7.5, L.FAINT)

    C.page_footer(rc, "Page 1 of 1")
    rc.end_page()


def draw_h2(rc, base_page: int) -> None:
    rc.begin_page(base_page)
    # ---- Zone A: letterhead + clinic phone; specimen label at right ----
    rc.text(L.LEFT, L.TOP - 14, P.CLINIC_NAME, L.BOLD, 13, L.ACCENT)
    rc.value_multiline(G["occ_h2_11"], L.LEFT, L.TOP - 28, L.REG, 8.5, L.GRAY, 11)      # clinic address
    lx = rc.text(L.LEFT, L.TOP - 52, G["occ_h2_10"].label_context, L.MED, 8.5, L.GRAY)  # Clinic Phone:
    rc.value(G["occ_h2_10"], lx + 4, L.TOP - 52, L.REG, 9, L.INK)
    # specimen label box (barcode = MRN payload; accession keyword-starved)
    bx0 = L.RIGHT - 150
    rc.box(bx0, L.TOP - 60, L.RIGHT, L.TOP - 6, L.RULE, 0.7)
    rc.text(bx0 + 6, L.TOP - 16, "SPECIMEN LABEL", L.SEMI, 7.5, L.ACCENT)
    C.barcode_code128(rc, G["occ_h2_12"], bx0 + 6, L.TOP - 46, bar_height=24, bar_width=0.9)
    lx = rc.text(bx0 + 6, L.TOP - 56, G["occ_h2_13"].label_context, L.MED, 7, L.GRAY)   # Accession No.
    rc.value(G["occ_h2_13"], lx + 3, L.TOP - 56, L.REG, 7.5, L.INK)                      # LAB-4471902
    rc.hrule(L.TOP - 66, L.LEFT, L.RIGHT, L.ACCENT, 1.0)
    # A keyword-free buffer line: it holds the section bar's "Patient" more than five tokens away
    # from the accession number in the specimen label, which is what keeps occ_h2_13 starved of an
    # MRN positive and therefore must-not-fire at 0.55. It carries no patient/mrn/chart/dob/
    # physician/hospital/diagnosis word of its own.
    rc.text(L.LEFT, L.TOP - 78, "Visit summary generated at the close of the encounter; retain with "
            "the clinical file.", L.REG, 8, L.GRAY)
    y = L.TOP - 94

    # ---- Zone B: patient header ----
    y = L.section_bar(rc, y, "Visit Summary -- Established Patient")
    lx = rc.text(L.LEFT, y, G["occ_h2_01"].label_context, L.MED, 8.5, L.GRAY)            # Patient:
    px = rc.value(G["occ_h2_01"], lx + 4, y, L.REG, 9.5, L.INK)                          # Rosalind Okafor
    rc.text(px + 4, y, "(established)", L.REG, 8, L.GRAY)
    lx = rc.text(L.LEFT + 300, y, G["occ_h2_02"].label_context, L.MED, 8.5, L.GRAY)      # MRN:
    rc.value(G["occ_h2_02"], lx + 4, y, L.REG, 9.5, L.INK)                               # 40018827
    y -= 14
    lx = rc.text(L.LEFT, y, G["occ_h2_04"].label_context, L.MED, 8.5, L.GRAY)            # DOB:
    px = rc.value(G["occ_h2_04"], lx + 4, y, L.REG, 9.5, L.INK)                          # 11/23/1988
    rc.text(px + 10, y, "Sex: F", L.REG, 8.5, L.INK)
    lx = rc.text(L.LEFT + 300, y, G["occ_h2_03"].label_context, L.MED, 8.5, L.GRAY)      # Patient ID:
    rc.value(G["occ_h2_03"], lx + 4, y, L.REG, 9.5, L.INK)                               # P40018827
    y -= 20

    # ---- Zone C: narrative (medical vocabulary; no complaint/order/records words) ----
    y = L.heading(rc, y, "Reason for Visit and History", size=9.5)
    y = C.fine_print(rc, y, [
        "Routine follow-up of essential hypertension and type 2 diabetes mellitus. The patient reports "
        "good adherence, no hypoglycemia, and no new symptom since the last visit. History taken with "
        "the patient; all chronic diagnoses carried forward from the chart without change. Physical "
        "examination unremarkable; no lesion, no edema, and no respiratory finding on auscultation.",
        "Assessment and therapy discussed with the patient in clinic. Metabolic laboratory work "
        "collected today under the specimen label above; the pharmacy will hold the dispense until "
        "the result posts. Nurse to place a follow-up call once the physician signs the result.",
    ], size=8.5, leading=11, gap=5)
    y -= 2
    rc.text(L.LEFT, y, "Vitals: BP 128/78 mmHg, pulse 72, temperature 98.4 F, weight 164 lb.",
            L.REG, 8.5, L.INK)
    y -= 14
    lx = rc.text(L.LEFT, y, "Assessment --", L.MED, 8.5, L.GRAY)
    lx = rc.text(lx + 4, y, G["occ_h2_15"].label_context, L.MED, 8.5, L.GRAY)            # Dx:
    px = rc.value(G["occ_h2_15"], lx + 4, y, L.REG, 9, L.INK)                            # I10
    rc.text(px + 6, y, "essential hypertension, stable on the current therapy.", L.REG, 8.5, L.INK)
    y -= 22

    # ---- Zone D: medication table -- the keyword-starved DEA (watch) in the Auth column ----
    # occ_h2_08 carries the SAME valid DEA as occ_h2_06, with NO dea/prescriber/prescription/
    # registration keyword within +-5 tokens: the nearest such word is the "Auth" caption a full
    # table row away, and Zone E opens well past the window. That starvation is the whole point of
    # the row -- it is a valid value that must NOT fire.
    y = L.heading(rc, y, "Active Medication List", size=9.5)
    cols = [(L.LEFT, "Medication"), (L.LEFT + 150, "Strength"), (L.LEFT + 215, "Sig"),
            (L.LEFT + 400, "Dispense"), (L.LEFT + 470, "Auth")]
    y = C.table_header(rc, y, cols)
    C.cell(rc, L.LEFT, y, "lisinopril")
    C.cell(rc, L.LEFT + 150, y, "10 mg")
    C.cell(rc, L.LEFT + 215, y, "one tablet each morning")
    C.cell(rc, L.LEFT + 400, y, "90 tablets")
    rc.value(G["occ_h2_08"], L.LEFT + 470, y, L.REG, 8.5, L.INK)                         # CT4471328 (starved)
    y -= 13
    C.cell(rc, L.LEFT, y, "metformin hydrochloride")
    C.cell(rc, L.LEFT + 150, y, "500 mg")
    C.cell(rc, L.LEFT + 215, y, "one tablet twice daily with a meal")
    C.cell(rc, L.LEFT + 400, y, "180 tablets")
    C.cell(rc, L.LEFT + 470, y, "on file")
    y -= 13
    rc.text(L.LEFT, y, "No allergy documented. Neither tablet was changed today; the dosage carried "
            "forward from the last visit.", L.REG, 8, L.GRAY)
    y -= 22

    # ---- Zone E: the prescription line (dea + prescriber positives adjacent) ----
    y = L.heading(rc, y, "Prescription Authority", size=9.5)
    lx = rc.text(L.LEFT, y, "Prescriber registration --", L.MED, 8.5, L.GRAY)
    lx = rc.text(lx + 4, y, G["occ_h2_06"].label_context, L.MED, 8.5, L.GRAY)            # DEA No.
    px = rc.value(G["occ_h2_06"], lx + 4, y, L.REG, 9, L.INK)                            # CT4471328
    rc.text(px + 6, y, "-- current; checked at the point of dispense.", L.REG, 8.5, L.GRAY)
    y -= 14
    lx = rc.text(L.LEFT, y, "Superseded", L.MED, 8.5, L.GRAY)
    lx = rc.text(lx + 4, y, G["occ_h2_07"].label_context, L.MED, 8.5, L.GRAY)            # prior DEA No.
    px = rc.value(G["occ_h2_07"], lx + 4, y, L.REG, 9, L.INK)                            # CT4471329 (bad digit)
    rc.text(px + 6, y, "-- retired registration, retained in the chart only.", L.REG, 8.5, L.GRAY)
    y -= 22

    # ---- Zone F: visit close (date of service > 80 chars from the 'DOB:' label) ----
    y = L.heading(rc, y, "Visit Close", size=9.5)
    lx = rc.text(L.LEFT, y, G["occ_h2_14"].label_context, L.MED, 8.5, L.GRAY)            # Date of Service:
    px = rc.value(G["occ_h2_14"], lx + 4, y, L.REG, 9, L.INK)                            # 08/11/2026
    rc.text(px + 12, y, "Visit type: office follow-up, established patient, outpatient clinic.",
            L.REG, 8.5, L.INK)
    y -= 14
    lx = rc.text(L.LEFT, y, G["occ_h2_05"].label_context, L.MED, 8.5, L.GRAY)            # Attending NPI:
    px = rc.value(G["occ_h2_05"], lx + 4, y, L.REG, 9, L.INK)                            # 1497734081
    rc.text(px + 12, y, "Enumerated, individual. Next visit in three months or sooner if a symptom "
            "returns.", L.REG, 8.5, L.INK)
    y -= 14
    # the probed surface is exactly "Attending: Dr. Imani Thorne" -- nothing Title-Case may follow the
    # name on this line or the 'Dr.' prefix pass would absorb it into the captured span.
    lx = rc.text(L.LEFT, y, G["occ_h2_09"].label_context, L.MED, 9, L.GRAY)              # Attending: Dr.
    rc.value(G["occ_h2_09"], lx + 4, y, L.REG, 9.5, L.INK)                               # Imani Thorne
    y -= 13
    rc.text(L.LEFT, y, "signed the summary electronically at the close of the visit.", L.REG, 8.5, L.GRAY)
    y -= 20

    # ---- closing instructions: OCR surface for the capture (the fine_print text-leg motivation).
    # Vetted: no 'complaint' / 'order' / 'records' word (the zone-C rule), no court / foia / generic
    # keyword, no phone positive near the NPI, no PII shape, no clean two-token Title-Case name.
    y = L.heading(rc, y, "Instructions Given at Discharge from the Visit", size=9.5)
    y = C.fine_print(rc, y, [
        "Continue both medications at the dosage shown and take the morning tablet with water. "
        "Check blood pressure twice weekly at rest and bring the readings to the next visit. Return "
        "to the clinic if a symptom returns between visits, or sooner if swelling, shortness of "
        "breath, or a persistent headache develops.",
        "The metabolic panel collected today is processed by the reference laboratory; the result "
        "posts to the chart within three working days and the nurse will relay it. A renewal is "
        "permitted for both medications through the next visit, and the pharmacy will hold the "
        "dispense until the panel result posts.",
    ], size=7.5, leading=9.8)
    y -= 6
    rc.text(L.LEFT, y, "Synthetic visit summary prepared for software testing; every person, "
            "identifier, medication, and date shown is fictional and disclosed.", L.REG, 7.5, L.FAINT)

    C.page_footer(rc, "Page 1 of 1")
    rc.end_page()
