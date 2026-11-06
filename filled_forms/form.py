"""The printed intake form and its field table.

The page is drawn once by reportlab (labels, rules, a heading), identically for every document; the
fields are then added by the document's producer at the rectangles below (PDF points, bottom-left
origin). Every value is synthetic (``hidden_layer/values.py``).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from reportlab.pdfgen import canvas

from hidden_layer import values as v

PAGE = (612, 792)
TITLE = "SYNTHETIC INTAKE FORM - FICTIONAL DATA"
DOC_TITLE = "Synthetic filled-form fixture"
LABEL_X = 72
FIELD_X = 210


@dataclass(frozen=True)
class FieldSpec:
    name: str
    kind: str  # text | multiline | checkbox | radio | combo | list | signature
    label: str
    rect: tuple[float, float, float, float]  # x0, y0, x1, y1
    value: str | None = None
    options: tuple[str, ...] = ()
    radio_rects: tuple[tuple[str, tuple[float, float, float, float]], ...] = ()


def _row(i: int) -> float:
    return 690 - 34 * i


def _text(name: str, label: str, i: int, value: str, width: float = 240) -> FieldSpec:
    y = _row(i)
    return FieldSpec(name, "text", label, (FIELD_X, y - 6, FIELD_X + width, y + 16), value)


FIELDS: tuple[FieldSpec, ...] = (
    _text("full_name", "Full name:", 0, v.PERSON["full"]),
    _text("phone", "Telephone:", 1, v.PHONE),
    _text("email", "E-mail:", 2, v.EMAIL),
    _text("ssn", "SSN:", 3, v.SSN, 140),
    _text("dob", "Date of birth:", 4, v.DOB, 140),
    FieldSpec(
        "consent",
        "checkbox",
        "Consent on file:",
        (FIELD_X, _row(5) - 4, FIELD_X + 14, _row(5) + 10),
        "on",
    ),
    FieldSpec(
        "mailing",
        "checkbox",
        "Mail me copies:",
        (FIELD_X, _row(6) - 4, FIELD_X + 14, _row(6) + 10),
        "off",
    ),
    FieldSpec(
        "contact_pref",
        "radio",
        "Contact by:",
        (FIELD_X, _row(7) - 4, FIELD_X + 194, _row(7) + 10),
        "email",
        ("phone", "email", "post"),
        tuple(
            (opt, (FIELD_X + 90 * k, _row(7) - 4, FIELD_X + 90 * k + 14, _row(7) + 10))
            for k, opt in enumerate(("phone", "email", "post"))
        ),
    ),
    FieldSpec(
        "state",
        "combo",
        "State:",
        (FIELD_X, _row(8) - 6, FIELD_X + 90, _row(8) + 14),
        "ZZ",
        ("ZX", "ZY", "ZZ"),
    ),
    FieldSpec(
        "program",
        "list",
        "Program:",
        (FIELD_X, _row(10) - 6, FIELD_X + 160, _row(9) + 14),
        "Records",
        ("Archive", "Records", "Review"),
    ),
    FieldSpec(
        "notes",
        "multiline",
        "Notes:",
        (FIELD_X, _row(12) - 6, FIELD_X + 240, _row(11) + 14),
        (
            f"Called {v.PHONE} on {v.DATE} about the file. Left a message for {v.PERSON['full']} "
            f"and sent a copy to {v.EMAIL}. The office will call again next week if there is no "
            f"answer. Account {' '.join(v.ACCOUNT)} stays on hold until then. Reference {v.CASE_NO}."
        ),
    ),
    FieldSpec(
        "signature",
        "signature",
        "Signature:",
        (FIELD_X, _row(14) - 6, FIELD_X + 200, _row(13) + 10),
    ),
)


def by_name(name: str) -> FieldSpec:
    return next(f for f in FIELDS if f.name == name)


@dataclass
class PageText:
    """Extra printed text drawn into the page content (used by the cover documents)."""

    items: list[tuple[float, float, str]] = field(default_factory=list)


def draw_page(c: canvas.Canvas, extra: PageText | None = None) -> None:
    """The printed form on ``c``: heading, labels, a rule under each text field, the footer."""
    c.setFont("Helvetica-Bold", 14)
    c.drawString(LABEL_X, 740, TITLE)
    c.setFont("Helvetica", 12)
    for f in FIELDS:
        y = f.rect[1] + 6 if f.kind in ("text", "combo") else f.rect[3] - 12
        c.drawString(LABEL_X, y, f.label)
        if f.kind == "text":
            c.setLineWidth(0.5)
            c.line(f.rect[0], f.rect[1] - 1, f.rect[2], f.rect[1] - 1)
    for opt, r in by_name("contact_pref").radio_rects:
        c.drawString(r[2] + 4, r[1] + 3, opt)
    c.setFont("Helvetica", 9)
    c.drawString(
        LABEL_X,
        60,
        "This synthetic form is a test document. Every name and number on it is invented.",
    )
    if extra:
        c.setFont("Helvetica", 12)
        for x, y, s in extra.items:
            c.drawString(x, y, s)
