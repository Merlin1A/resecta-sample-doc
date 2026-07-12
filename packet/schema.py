"""schema.py -- validation for the FROZEN per-occurrence ground-truth record.

Pure-Python (no jsonschema dependency). `validate_record` returns a list of problems (empty == OK);
`validate_ground_truth` validates a whole emitted list. Every character is printable ASCII.
"""
from __future__ import annotations

# the 17+ PIIKind keys (mirrors Models/RedactionRegion.swift:116 in the iOS engine)
PII_KINDS = {
    "ssn", "creditCard", "name", "address", "email", "phone", "ein", "itin",
    "driversLicense", "passport", "medicalRecord", "dateOfBirth", "npi", "dea",
    "account", "routingNumber", "licensePlate", "barcode", "signatureCandidate", "other",
}
EXPECTATIONS = {"must_fire", "should_fire", "watch", "must_not_fire"}
LEGS = {"text", "ocr"}


def _bbox_problems(bbox, where):
    out = []
    if not (isinstance(bbox, (list, tuple)) and len(bbox) == 4):
        return [f"{where}: bbox must be 4 numbers, got {bbox!r}"]
    x0, y0, x1, y1 = bbox
    for v in bbox:
        if not isinstance(v, (int, float)):
            out.append(f"{where}: bbox component not numeric: {v!r}")
            return out
        if not (-0.0001 <= v <= 1.0001):
            out.append(f"{where}: bbox component out of 0-1: {v}")
    if x1 < x0:
        out.append(f"{where}: bbox x1 < x0 ({x0}..{x1})")
    if y1 < y0:
        out.append(f"{where}: bbox y1 < y0 (bottom-left origin requires y0<=y1) ({y0}..{y1})")
    return out


def validate_record(r: dict) -> list[str]:
    p = []
    rid = r.get("id", "<no-id>")
    required = ["id", "value", "category", "page", "bbox", "bbox_origin", "expectation",
               "leg_applicability", "label_context", "render", "spans", "overlaps",
               "justification", "source_range", "schema_version"]
    for k in required:
        if k not in r:
            p.append(f"{rid}: missing required key {k!r}")
    if p:
        return p
    # carried/measured records (the FROZEN STMT rows) have no draw-time geometry yet -- resolved
    # later. Validate everything EXCEPT geometry for those.
    measured = bool(r.get("measured_pending"))
    if not isinstance(r["id"], str) or not r["id"]:
        p.append(f"{rid}: id must be a non-empty string")
    if not isinstance(r["value"], str):
        p.append(f"{rid}: value must be a string")
    if r["category"] not in PII_KINDS:
        p.append(f"{rid}: category {r['category']!r} not a PIIKind")
    if r["bbox_origin"] != "bottom-left":
        p.append(f"{rid}: bbox_origin must be 'bottom-left'")
    if r["expectation"] not in EXPECTATIONS:
        p.append(f"{rid}: expectation {r['expectation']!r} invalid")
    legs = r["leg_applicability"]
    if not (isinstance(legs, list) and legs and set(legs) <= LEGS):
        p.append(f"{rid}: leg_applicability must be a non-empty subset of {sorted(LEGS)}")
    if not isinstance(r["label_context"], str):
        p.append(f"{rid}: label_context must be a string")
    render = r["render"]
    if not (isinstance(render, dict) and set(render) == {"all_caps", "masked", "multiline"}
            and all(isinstance(v, bool) for v in render.values())):
        p.append(f"{rid}: render must be {{all_caps,masked,multiline}} booleans")
    if not isinstance(r["overlaps"], list):
        p.append(f"{rid}: overlaps must be a list")
    if r["schema_version"] != 1:
        p.append(f"{rid}: schema_version must be 1")

    if measured:
        # geometry deferred (carried rows): page may be null, bbox null, spans empty
        if r["page"] is not None and not (isinstance(r["page"], int) and r["page"] >= 0):
            p.append(f"{rid}: measured page must be null or a non-negative int")
        if r["bbox"] is not None:
            p += _bbox_problems(r["bbox"], rid)
        if not isinstance(r["spans"], list):
            p.append(f"{rid}: spans must be a list")
        return p

    if not (isinstance(r["page"], int) and r["page"] >= 0):
        p.append(f"{rid}: page must be a non-negative int (0-indexed pageIndex)")
    p += _bbox_problems(r["bbox"], rid)
    spans = r["spans"]
    if not (isinstance(spans, list) and spans):
        p.append(f"{rid}: spans must be a non-empty list")
    else:
        for i, s in enumerate(spans):
            if not (isinstance(s, dict) and "page" in s and "bbox" in s):
                p.append(f"{rid}: span[{i}] must have page+bbox")
                continue
            p += _bbox_problems(s["bbox"], f"{rid} span[{i}]")
    if render.get("multiline") and len(spans) < 2:
        p.append(f"{rid}: render.multiline=true but <2 spans")
    return p


def validate_ground_truth(records: list[dict]) -> list[str]:
    problems = []
    seen = set()
    for r in records:
        problems += validate_record(r)
        rid = r.get("id")
        if rid in seen:
            problems.append(f"duplicate occurrence id {rid!r}")
        seen.add(rid)
    # referential integrity of overlaps[]
    ids = {r.get("id") for r in records}
    for r in records:
        for o in r.get("overlaps", []):
            if o not in ids:
                problems.append(f"{r.get('id')}: overlaps references unknown id {o!r}")
    return problems
