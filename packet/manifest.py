"""manifest.py -- the ground-truth machinery: a recording reportlab canvas that captures a
draw-time bbox for every labeled value, emits the frozen per-occurrence
record, and reconstructs page reading-order text so the acceptance suite can verify the
token/char-distance spacing constraints without an external PDF text extractor.

Coordinate discipline: bbox is normalized 0-1, BOTTOM-LEFT origin -- reportlab's native system AND
the engine's DetectionResult.normalizedRect -- so ground-truth bbox compares directly
against a detection's normalizedRect with no transform.

Every character is printable ASCII.
"""

from __future__ import annotations

from dataclasses import dataclass

from reportlab.pdfbase import pdfmetrics

SCHEMA_VERSION = 1

# tier short codes -> ground-truth expectation strings
TIER = {
    "MF": "must_fire",
    "SF": "should_fire",
    "W": "watch",
    "MNF": "must_not_fire",
}


@dataclass(frozen=True)
class Occurrence:
    """One manifest occurrence (everything EXCEPT the draw-time bbox/spans/page, which the generator
    fills in). Mirrors a row of the values manifest."""

    id: str
    value: object  # str, or tuple[str, ...] for multiline
    category: str  # one of the 17 PIIKind keys
    exhibit: str  # urla_b | urla_a | t1040 | ach | w2 | govid | veh | stmt
    tier: str  # MF | SF | W | MNF
    label_context: str
    leg: tuple = ("text", "ocr")
    all_caps: bool = False
    masked: bool = False
    multiline: bool = False
    overlaps: tuple = ()
    justification: str = ""
    source_range: str = ""

    @property
    def expectation(self) -> str:
        return TIER[self.tier]

    @property
    def value_text(self) -> str:
        if isinstance(self.value, tuple):
            return " ".join(self.value)
        return str(self.value)


class RecordingCanvas:
    """Wraps a reportlab canvas. Every text draw is recorded (page, baseline_y, x_left, string) so
    page reading order can be reconstructed; `value()`/`value_multiline()` additionally emit a
    ground-truth occurrence with a draw-time bbox."""

    def __init__(self, c, page_w: float, page_h: float):
        self.c = c
        self.PW = page_w
        self.PH = page_h
        self.page = 0  # current GLOBAL 0-indexed page in the final packet
        self.draws: list[tuple] = []  # (page, baseline_y, x_left, text)
        self.occurrences: list[dict] = []  # ground-truth records

    # ---- page control ----------------------------------------------------------------------------
    def begin_page(self, global_index: int) -> None:
        self.page = global_index

    def end_page(self) -> None:
        self.c.showPage()

    # ---- low-level recorded draws ----------------------------------------------------------------
    def text(self, x, y, s, font, size, color):
        self.c.setFillColor(color)
        self.c.setFont(font, size)
        self.c.drawString(x, y, s)
        self.draws.append((self.page, y, x, s))
        return x + pdfmetrics.stringWidth(s, font, size)

    def rtext(self, x, y, s, font, size, color):
        w = pdfmetrics.stringWidth(s, font, size)
        self.c.setFillColor(color)
        self.c.setFont(font, size)
        self.c.drawRightString(x, y, s)
        self.draws.append((self.page, y, x - w, s))
        return x - w

    # ---- geometry helpers (not recorded) ---------------------------------------------------------
    def hrule(self, y, x0, x1, color, w=0.6):
        self.c.setStrokeColor(color)
        self.c.setLineWidth(w)
        self.c.line(x0, y, x1, y)

    def box(self, x0, y0, x1, y1, color, w=0.7, radius=0.0):
        self.c.setStrokeColor(color)
        self.c.setLineWidth(w)
        if radius:
            self.c.roundRect(x0, y0, x1 - x0, y1 - y0, radius, stroke=1, fill=0)
        else:
            self.c.rect(x0, y0, x1 - x0, y1 - y0, stroke=1, fill=0)

    # ---- bbox capture ----------------------------------------------------------------------------
    def _bbox(self, x, y, s, font, size):
        asc, desc = pdfmetrics.getAscentDescent(font, size)  # desc is negative
        x0, x1 = x, x + pdfmetrics.stringWidth(s, font, size)
        y0, y1 = y + desc, y + asc
        return [x0 / self.PW, y0 / self.PH, x1 / self.PW, y1 / self.PH]

    # ---- value placement (draws + emits a ground-truth occurrence) -------------------------------
    def value(self, occ: Occurrence, x, y, font, size, color):
        s = occ.value_text
        self.c.setFillColor(color)
        self.c.setFont(font, size)
        self.c.drawString(x, y, s)
        self.draws.append((self.page, y, x, s))
        bbox = self._bbox(x, y, s, font, size)
        self._emit(occ, bbox, [{"page": self.page, "bbox": bbox}])
        return x + pdfmetrics.stringWidth(s, font, size)

    def value_multiline(self, occ: Occurrence, x, y, font, size, color, leading):
        lines = occ.value if isinstance(occ.value, tuple) else (occ.value,)
        spans = []
        yy = y
        for ln in lines:
            self.c.setFillColor(color)
            self.c.setFont(font, size)
            self.c.drawString(x, yy, ln)
            self.draws.append((self.page, yy, x, ln))
            bb = self._bbox(x, yy, ln, font, size)
            spans.append({"page": self.page, "bbox": bb})
            yy -= leading
        x0 = min(s["bbox"][0] for s in spans)
        y0 = min(s["bbox"][1] for s in spans)
        x1 = max(s["bbox"][2] for s in spans)
        y1 = max(s["bbox"][3] for s in spans)
        self._emit(occ, [x0, y0, x1, y1], spans)
        return yy

    # ---- non-text regions (P1.8 / T1.3(a)): a bar, a barcode, a signature stroke ---------------
    def region_value(self, occ: Occurrence, x0, y0, x1, y1):
        """Emit a ground-truth occurrence for a NON-TEXT region the caller has drawn (a redaction
        bar, a barcode, a signature stroke). Coordinates are POINTS, bottom-left origin; nothing is
        drawn here and nothing is recorded in `draws`, so the reading-order text stays exactly what
        the page carries as text."""
        bbox = [x0 / self.PW, y0 / self.PH, x1 / self.PW, y1 / self.PH]
        self._emit(occ, bbox, [{"page": self.page, "bbox": bbox}])
        return bbox

    def bar_value(self, occ: Occurrence, x, y, font, size, pad=1.5):
        """The already-redacted-input surface: fill a black bar exactly where `occ.value` WOULD have
        been drawn at (x, y) in `font`/`size`, without ever drawing the text. Ground truth carries the
        hidden value and the bar's rect so an evaluator can assert that nothing fires there on any
        leg. Returns the x just past the bar."""
        s = occ.value_text
        x0, y0, x1, y1 = self._bbox(x, y, s, font, size)
        px0, py0 = x0 * self.PW - pad, y0 * self.PH - pad
        px1, py1 = x1 * self.PW + pad, y1 * self.PH + pad
        self.c.setFillColorRGB(0, 0, 0)
        self.c.rect(px0, py0, px1 - px0, py1 - py0, stroke=0, fill=1)
        self.region_value(occ, px0, py0, px1, py1)
        return px1

    def _emit(self, occ: Occurrence, bbox, spans):
        self.occurrences.append(
            {
                "id": occ.id,
                "value": occ.value_text,
                "category": occ.category,
                "page": self.page,
                "bbox": [round(v, 6) for v in bbox],
                "bbox_origin": "bottom-left",
                "expectation": occ.expectation,
                "leg_applicability": list(occ.leg),
                "label_context": occ.label_context,
                "render": {
                    "all_caps": occ.all_caps,
                    "masked": occ.masked,
                    "multiline": occ.multiline,
                },
                "spans": [
                    {"page": s["page"], "bbox": [round(v, 6) for v in s["bbox"]]} for s in spans
                ],
                "overlaps": list(occ.overlaps),
                "justification": occ.justification,
                "source_range": occ.source_range,
                "schema_version": SCHEMA_VERSION,
            }
        )

    # ---- reading-order reconstruction (for the token/char-distance C-constraint checks) ----------
    def page_token_text(self, page: int) -> str:
        """Reconstruct the linear reading-order text of a drawn page from the recorded draws:
        sort top-to-bottom (by descending baseline_y, bucketed into ~line rows) then left-to-right.
        Approximates the engine's tokenization input closely enough to assert the SPACING we
        designed (the windows we assert are deliberately more generous than the engine's)."""
        rows = [(by, x, s) for (p, by, x, s) in self.draws if p == page]
        # bucket baselines into line rows (6pt tolerance) so same-line draws sort by x
        rows.sort(key=lambda r: (-r[0], r[1]))
        out = []
        last_y = None
        for by, _x, s in rows:
            if last_y is None or abs(by - last_y) > 6.0:
                out.append("\n")
                last_y = by
            out.append(s)
        return " ".join(out).replace(" \n ", "\n").strip()
