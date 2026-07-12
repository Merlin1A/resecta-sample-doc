"""veh.py -- VEH exhibit (1pp): a vehicle Certificate of Title framed by a DMV cover memo, designed
to classify .generic so licensePlate fires.

Load-bearing layout constraints honored here:
  * >=5 generic-EXCLUSIVE tokens (department, memo, regarding, enclosed, attachment, reminder,
    confidential) -> generic raw hits the cap-5 -> generic STRICTLY exceeds financial.
  * ZERO financial tokens, NO '$', NO Invoice/Statement/Receipt header (no currency_amount /
    invoice_label structural bonus); "memo" not "memorandum" (foia); no court/medical tokens.
  * C2: NO MM/DD/YYYY or month-name date anywhere ("Model Year: 2019" is a bare year the DOB
    detector ignores) -- the FULL DOBDetector runs on .generic.
  * occ_veh_01 plate: a vehicle-positive context kw (owner/vehicle/make) within +-5 tokens -> boost.
  * occ_veh_05 tag: negative-context "serial" within +-5 and NO vehicle-positive kw within +-5 ->
    dampened below threshold (isolated footer block).

Every character is printable ASCII.
"""
from __future__ import annotations

from .. import layout as L
from .. import occurrences as OCC
from . import _common as C

G = OCC.BY_ID


def draw(rc, base_page: int) -> None:
    rc.begin_page(base_page)
    y = L.form_title(rc, "Department of Motor Vehicles",
                     "Certificate of Title -- Vehicle Title Memo (synthetic sample)",
                     "Form DMV-TM (sample)")

    # ---- cover memo: seeds the generic-EXCLUSIVE tokens (department/memo/regarding/enclosed/
    #      attachment/reminder/confidential). NO financial/court/foia/medical keyword (scrubbed). ----
    y = L.section_bar(rc, y, "Internal Memo")
    rc.text(L.LEFT, y, "Department: Vehicle Title Services", L.MED, 9, L.INK)
    y -= 13
    rc.text(L.LEFT, y, "Memo Regarding: the enclosed certificate of title submitted with this file.",
            L.REG, 9, L.GRAY)
    y -= 13
    rc.text(L.LEFT, y, "Attachment: one certificate of title enclosed with this file.", L.REG, 9, L.GRAY)
    y -= 13
    rc.text(L.LEFT, y, "Reminder: Confidential -- handle this enclosed attachment per the cover memo.",
            L.REG, 9, L.GRAY)
    y -= 20

    # ---- certificate body: vehicle/owner block (vehicle-context kw feed the plate boost) ----
    y = L.heading(rc, y, "Certificate of Title")
    rc.text(L.LEFT, y, "Vehicle Make: utility wagon", L.MED, 9, L.INK)
    rc.text(L.LEFT + 200, y, "Model Year: 2019", L.MED, 9, L.INK)   # bare year -> DOB ignores it (C2)
    y -= 15

    # plate line: "Plate No: <plate>" with Vehicle/Owner within +-5 tokens; the Registered Owner name
    # rides on the same line so 'owner' boosts the plate AND the name is captured.
    lx = rc.text(L.LEFT, y, G["occ_veh_01"].label_context, L.MED, 9, L.GRAY)         # "Plate No:"
    px = rc.value(G["occ_veh_01"], lx + 5, y, L.REG, 9.5, L.INK)                     # 7XYZ842
    ox = rc.text(px + 18, y, G["occ_veh_02"].label_context, L.MED, 9, L.GRAY)        # "Registered Owner:"
    rc.value(G["occ_veh_02"], ox + 5, y, L.REG, 9.5, L.INK)                          # Delia Hartwell
    y -= 16

    # owner address (multiline)
    y = L.field_multiline(rc, L.LEFT, y, G["occ_veh_03"].label_context, G["occ_veh_03"],
                          vsize=9.5, leading=12)
    y -= 6

    # VIN line: behind a NON-plate "VIN:" label -> the plate regex never captures it (MNF)
    lx = rc.text(L.LEFT, y, G["occ_veh_04"].label_context, L.MED, 9, L.GRAY)         # "VIN:"
    rc.value(G["occ_veh_04"], lx + 5, y, L.REG, 9.5, L.INK)                          # 17-char VIN
    y -= 22

    # ---- vehicle-only fine print (dense; vehicle vocabulary is doctype-neutral; NO dates; every word
    #      vetted free of financial/court/foia/medical keywords -- verified by the acceptance gate) ----
    y = L.heading(rc, y, "Title Notes")
    y = C.fine_print(rc, y, [
        "This certificate of title is a synthetic sample prepared for software testing. The vehicle "
        "make, model year, and title notes shown here describe a fictional vehicle and registered "
        "owner. The enclosed attachment and this cover memo are provided together so the assigned "
        "department can confirm the owner and the registered vehicle from a single enclosed page.",
        "The registered owner keeps the title current with the department. A change of ownership is "
        "noted by the department when the prior owner endorses the title and the new owner submits the "
        "endorsed title. The department issues a corrected title to the owner on file after the change "
        "is confirmed. Keep the enclosed attachment with the title.",
        "The plate shown is assigned to the vehicle described and is kept with the title. A plate that "
        "is bent or worn may be surrendered to the department and a new plate issued to the owner. The "
        "make, model year, and plate shown are a matched set for this sample vehicle.",
        "Reminder: this enclosed memo and the attachment are confidential samples. The plate, vehicle "
        "make, and owner shown are fictional and disclosed. No real owner, vehicle, or plate is "
        "described. The department marker shown on the enclosed attachment is a sample marker.",
    ])
    y -= 8

    # ---- isolated footer: surrendered-tag inventory note. 'serial' within +-5 of the tag and NO
    #      vehicle-positive kw within +-5 -> the plate detector dampens it below threshold (MNF). ----
    rc.hrule(y, L.LEFT, L.RIGHT, L.RULE, 0.5)
    y -= 12
    rc.text(L.LEFT, y, "Surrendered Tag Inventory (enclosed attachment)", L.SEMI, 8.5, L.ACCENT)
    y -= 14
    lx = rc.text(L.LEFT, y, G["occ_veh_05"].label_context, L.MED, 9, L.GRAY)         # "Tag No:"
    tx = rc.value(G["occ_veh_05"], lx + 5, y, L.REG, 9.5, L.INK)                     # 88KJ2
    rc.text(tx + 10, y, "Serial No. on file; enclosed attachment item.", L.REG, 8.5, L.GRAY)

    C.page_footer(rc, "Page 12 of 12", veh_safe=True)
    rc.end_page()
