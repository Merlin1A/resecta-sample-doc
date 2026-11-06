"""The printed page: three layouts of synthetic text, six grounds, and the seeded degradations.

Coordinates. Layout positions are integer centipoints (1/100 pt) from the page's top-left corner.
The raster is ``round(612 * dpi / 72)`` by ``round(792 * dpi / 72)`` pixels; a centipoint position
maps to the pixel ``round(cpt * dpi / 7200)``. A word's ink box is measured from its own coverage
mask, in integer pixels (top-left origin, exclusive right and bottom edges), so it is exact at the
raster's resolution. On a skewed page the box is the rotated rectangle's hull, rounded outward.
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from . import values as v
from .rng import mix_seed, uniform_ints

FONT_DIR = Path(__file__).resolve().parent.parent / "fonts"
FONT_REGULAR = FONT_DIR / "Inter-Regular.ttf"
FONT_BOLD = FONT_DIR / "Inter-Bold.ttf"

PAGE_W_PT = 612
PAGE_H_PT = 792
LEFT_CPT = 7200
SCENARIO_SIZE_PT = 13
SCENARIO_PITCH_CPT = 2400

GROUNDS = ("clean", "light-noise", "heavy-noise", "textured", "dark", "black-bar")


@dataclass(frozen=True)
class Segment:
    x_cpt: int
    text: str


@dataclass(frozen=True)
class LineSpec:
    key: str
    baseline_cpt: int
    size_pt: int
    segments: tuple[Segment, ...]
    bold: bool = False


@dataclass(frozen=True)
class Rule:
    x0_cpt: int
    x1_cpt: int
    y_cpt: int
    width_cpt: int = 75


@dataclass(frozen=True)
class Layout:
    name: str
    lines: tuple[LineSpec, ...]
    rules: tuple[Rule, ...] = ()


@dataclass
class Word:
    index: int
    line: int
    line_key: str
    position: int
    text: str
    size_pt: int
    baseline_px: int
    x_px: int
    ink_px: tuple[int, int, int, int]
    ink_polygon_px: tuple[tuple[float, float], ...] | None = None
    under_bar: bool = False
    segment_end: bool = False


@dataclass
class Page:
    dpi: int
    width_px: int
    height_px: int
    pixels: np.ndarray
    words: list[Word]
    bar_px: tuple[int, int, int, int] | None = None
    ground: str = "clean"
    rules_px: list[tuple[int, int, int, int]] = field(default_factory=list)
    rules_polygon_px: list[tuple[tuple[float, float], ...]] = field(default_factory=list)
    notes: dict[str, object] = field(default_factory=dict)


def _line(
    key: str, top_cpt: int, size: int, text: str, x_cpt: int = LEFT_CPT, bold: bool = False
) -> LineSpec:
    return LineSpec(key, top_cpt, size, (Segment(x_cpt, text),), bold)


def _scenario_block(first_baseline_cpt: int) -> list[LineSpec]:
    return [
        _line(key, first_baseline_cpt + i * SCENARIO_PITCH_CPT, SCENARIO_SIZE_PT, text)
        for i, (key, text) in enumerate(v.SCENARIO_LINES)
    ]


def _statement() -> Layout:
    lines = [
        _line("banner", 6000, 10, "SYNTHETIC STATEMENT - FICTIONAL DATA", bold=True),
        _line("org", 8400, 14, v.ORG, bold=True),
        _line("addr1", 10400, 11, v.PERSON["full"]),
        _line("addr2", 11900, 11, v.STREET),
        _line("addr3", 13400, 11, v.CITY_LINE),
        _line("period", 16000, 11, f"Statement period ending {v.DATE}"),
        _line("phone", 17500, 11, f"Questions: call {v.PHONE} or write to {v.EMAIL_2}"),
    ]
    rows = (
        ("10/02", "Opening balance", "1,204.18"),
        ("10/05", "Deposit from Hartigan Supply", "2,410.00"),
        ("10/09", "Card ending 1111 at Quarry Market", "-86.42"),
        ("10/14", "Transfer to savings", "-500.00"),
        ("10/21", "Check 0417 paid to Okafor Joinery", "-1,130.75"),
        ("10/27", "Interest", "3.11"),
        ("10/30", "Closing balance", "1,900.12"),
    )
    top = 20500
    lines.append(
        LineSpec(
            "thead",
            top,
            11,
            (Segment(7200, "Date"), Segment(13200, "Description"), Segment(45000, "Amount")),
            True,
        )
    )
    for i, (d, desc, amt) in enumerate(rows):
        lines.append(
            LineSpec(
                f"row{i}",
                top + 1800 * (i + 1),
                11,
                (Segment(7200, d), Segment(13200, desc), Segment(45000, amt)),
            )
        )
    rules = (Rule(7200, 54000, top + 450), Rule(7200, 54000, top + 1800 * len(rows) + 700))
    lines.append(_line("notes", 37600, 12, "Notes", bold=True))
    lines.extend(_scenario_block(40000))
    lines.append(
        _line(
            "footer",
            74000,
            9,
            "This synthetic page is a test document. Every name and number on it is invented.",
        )
    )
    return Layout("statement", tuple(lines), rules)


def _letter() -> Layout:
    lines = [
        _line("banner", 6000, 10, "SYNTHETIC LETTER - FICTIONAL DATA", bold=True),
        _line("from1", 8600, 12, v.OFFICE),
        _line("from2", 10200, 12, v.STREET),
        _line("from3", 11800, 12, v.CITY_LINE),
        _line("date", 14600, 12, v.DATE),
        _line("ref", 16200, 12, f"Reference {v.CASE_NO}"),
        _line("dear", 19400, 12, f"Dear Ms. {v.PERSON['last']},"),
        _line("body1", 22000, 12, "This letter confirms that the review of your file is complete."),
        _line("body2", 23800, 12, f"You may reach the office at {v.PHONE} or {v.EMAIL_2}."),
        _line("body3", 25600, 12, "Please keep this letter with your other records for the year."),
    ]
    lines.extend(_scenario_block(29400))
    lines.extend(
        [
            _line("close", 46000, 12, "Sincerely,"),
            _line("closer", 50200, 12, "Wren Castellano, Records Officer"),
            _line(
                "footer",
                74000,
                9,
                "This synthetic page is a test document. Every name and number on it is invented.",
            ),
        ]
    )
    return Layout("letter", tuple(lines))


def _form() -> Layout:
    fields = (
        ("name", "Full name:", v.PERSON["full"]),
        ("phone", "Telephone:", v.PHONE_2),
        ("email", "E-mail:", v.EMAIL),
        ("ssn", "SSN:", v.SSN),
        ("dob", "Date of birth:", v.DOB),
        ("card", "Card on file:", v.CARD),
    )
    lines = [
        _line("banner", 6000, 10, "SYNTHETIC INTAKE FORM - FICTIONAL DATA", bold=True),
        _line("title", 8600, 15, "Records Intake", bold=True),
    ]
    rules = []
    top = 12000
    for i, (key, label, value) in enumerate(fields):
        y = top + 2600 * i
        lines.append(LineSpec(key, y, 12, (Segment(7200, label), Segment(19800, value))))
        rules.append(Rule(19800, 46000, y + 500))
    lines.append(
        _line(
            "tick",
            top + 2600 * len(fields) + 600,
            11,
            "[x] I agree that the office may keep this form on file.",
        )
    )
    lines.extend(_scenario_block(32600))
    lines.append(
        _line(
            "footer",
            74000,
            9,
            "This synthetic page is a test document. Every name and number on it is invented.",
        )
    )
    return Layout("form", tuple(lines), tuple(rules))


LAYOUTS = {"statement": _statement, "letter": _letter, "form": _form}


def layout(name: str) -> Layout:
    return LAYOUTS[name]()


# --------------------------------------------------------------------------------------- raster
def page_size_px(dpi: int) -> tuple[int, int]:
    return round(PAGE_W_PT * dpi / 72), round(PAGE_H_PT * dpi / 72)


def cpt_to_px(cpt: int, dpi: int) -> int:
    return round(cpt * dpi / 7200)


def _font(size_pt: int, dpi: int, bold: bool) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_BOLD if bold else FONT_REGULAR), size_pt * dpi / 72)


def _word_ink(font: ImageFont.FreeTypeFont, text: str, x: int, y: int) -> tuple[int, int, int, int]:
    """The tight ink box of ``text`` drawn with its left baseline at integer pixel (x, y)."""
    left, t, r, b = (int(c) for c in font.getbbox(text, anchor="ls"))
    pad = 4
    scratch = Image.new("L", (r - left + 2 * pad, b - t + 2 * pad), 0)
    ImageDraw.Draw(scratch).text((pad - left, pad - t), text, font=font, fill=255, anchor="ls")
    arr = np.asarray(scratch)
    ys, xs = np.nonzero(arr)
    if xs.size == 0:
        return (x, y, x, y)
    ox, oy = x + left - pad, y + t - pad
    return (ox + int(xs.min()), oy + int(ys.min()), ox + int(xs.max()) + 1, oy + int(ys.max()) + 1)


def draw_text_mask(
    lay: Layout, dpi: int
) -> tuple[np.ndarray, list[Word], list[tuple[int, int, int, int]]]:
    """The coverage mask (0-255) of every word and rule, the words with their ink boxes, and the
    rules' pixel boxes."""
    w, h = page_size_px(dpi)
    mask = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(mask)
    words: list[Word] = []
    for li, line in enumerate(lay.lines):
        font = _font(line.size_pt, dpi, line.bold)
        space = font.getlength(" ")
        y = cpt_to_px(line.baseline_cpt, dpi)
        pos = 0
        for seg in line.segments:
            x0 = cpt_to_px(seg.x_cpt, dpi)
            advance = 0.0
            tokens = seg.text.split(" ")
            for ti, token in enumerate(tokens):
                x = x0 + round(advance)
                draw.text((x, y), token, font=font, fill=255, anchor="ls")
                ink = _word_ink(font, token, x, y)
                words.append(
                    Word(
                        len(words),
                        li,
                        line.key,
                        pos,
                        token,
                        line.size_pt,
                        y,
                        x,
                        ink,
                        segment_end=ti == len(tokens) - 1,
                    )
                )
                pos += 1
                advance += font.getlength(token) + space
    rules = []
    for rule in lay.rules:
        y = cpt_to_px(rule.y_cpt, dpi)
        thick = max(1, cpt_to_px(rule.width_cpt, dpi))
        x0, x1 = cpt_to_px(rule.x0_cpt, dpi), cpt_to_px(rule.x1_cpt, dpi)
        draw.rectangle((x0, y, x1 - 1, y + thick - 1), fill=255)
        rules.append((x0, y, x1, y + thick))
    return np.asarray(mask).copy(), words, rules


# --------------------------------------------------------------------------------------- grounds
# Each ground: (base level description, text fill). Levels are 8-bit grey.
TEXT_FILL = {
    "clean": 24,
    "light-noise": 30,
    "heavy-noise": 22,
    "textured": 28,
    "dark": 222,
    "black-bar": 24,
}


def _grain(dpi: int) -> int:
    return max(1, round(dpi / 150))


def _blocky(seed: int, w: int, h: int, grain: int, lo: int, hi: int) -> np.ndarray:
    gw, gh = -(-w // grain), -(-h // grain)
    cells = uniform_ints(seed, gw * gh, lo, hi).reshape(gh, gw)
    return np.repeat(np.repeat(cells, grain, axis=0), grain, axis=1)[:h, :w]


def _smooth_field(seed: int, w: int, h: int, step: int, lo: int, hi: int) -> np.ndarray:
    """A low-frequency field: integer bilinear interpolation of a coarse uniform grid."""
    gw, gh = w // step + 2, h // step + 2
    grid = uniform_ints(seed, gw * gh, lo, hi).reshape(gh, gw)
    ys = np.arange(h, dtype=np.int64)
    xs = np.arange(w, dtype=np.int64)
    y0, fy = ys // step, ys % step
    x0, fx = xs // step, xs % step
    a = grid[y0][:, x0]
    b = grid[y0][:, x0 + 1]
    c = grid[y0 + 1][:, x0]
    d = grid[y0 + 1][:, x0 + 1]
    fxr = fx[None, :]
    fyc = fy[:, None]
    top = a * (step - fxr) + b * fxr
    bot = c * (step - fxr) + d * fxr
    return (top * (step - fyc) + bot * fyc + (step * step) // 2) // (step * step)


def ground_pixels(kind: str, dpi: int, seed: int) -> np.ndarray:
    w, h = page_size_px(dpi)
    g = _grain(dpi)
    if kind in ("clean", "black-bar"):
        return np.full((h, w), 252, dtype=np.int64)
    if kind == "light-noise":
        return _blocky(mix_seed(seed, "light"), w, h, g, 228, 252)
    if kind == "heavy-noise":
        return _blocky(mix_seed(seed, "heavy"), w, h, g, 150, 230)
    if kind == "textured":
        field = _smooth_field(mix_seed(seed, "tex"), w, h, max(8, dpi // 6), 196, 244)
        fine = _blocky(mix_seed(seed, "tex-fine"), w, h, g, -6, 6)
        return np.clip(field + fine, 0, 255)
    if kind == "dark":
        return _blocky(mix_seed(seed, "dark"), w, h, g, 28, 48)
    raise ValueError(kind)


def composite(ground: np.ndarray, mask: np.ndarray, fill: int) -> np.ndarray:
    m = mask.astype(np.int64)
    return ((ground * (255 - m) + fill * m + 127) // 255).astype(np.uint8)


BAR_LINE_KEY = "account"
BAR_PAD_PX_PER_150DPI = 6


def paint_bar(
    pixels: np.ndarray, words: list[Word], dpi: int, seed: int
) -> tuple[int, int, int, int]:
    """Paint a noisy black bar over the account digits (positions 1-4 of the account line); return
    its pixel box. The words under it are flagged."""
    under = [wd for wd in words if wd.line_key == BAR_LINE_KEY and 1 <= wd.position <= 4]
    pad = BAR_PAD_PX_PER_150DPI * dpi // 150
    x0 = min(wd.ink_px[0] for wd in under) - pad
    y0 = min(wd.ink_px[1] for wd in under) - pad
    x1 = max(wd.ink_px[2] for wd in under) + pad
    y1 = max(wd.ink_px[3] for wd in under) + pad
    bar = _blocky(mix_seed(seed, "bar"), x1 - x0, y1 - y0, _grain(dpi), 4, 44)
    pixels[y0:y1, x0:x1] = bar.astype(np.uint8)
    for wd in under:
        wd.under_bar = True
    return (x0, y0, x1, y1)


# --------------------------------------------------------------------------------------- degrade
@dataclass(frozen=True)
class Degrade:
    name: str
    skew_centideg: int = 0
    blur_centipx: int = 0
    jpeg_quality: int = 85


DEGRADES = {
    "none": Degrade("none", 0, 0, 85),
    "mild": Degrade("mild", 40, 50, 75),
    "rough": Degrade("rough", 100, 100, 55),
}


def rotate_point(x: float, y: float, w: int, h: int, deg: float) -> tuple[float, float]:
    """Where PIL's ``Image.rotate(deg)`` (counter-clockwise, about the image centre) moves (x, y)."""
    t = math.radians(deg)
    cx, cy = w / 2, h / 2
    return (
        cx + (x - cx) * math.cos(t) + (y - cy) * math.sin(t),
        cy - (x - cx) * math.sin(t) + (y - cy) * math.cos(t),
    )


def apply_skew(page: Page, centideg: int, fill: int) -> None:
    if not centideg:
        return
    deg = centideg / 100
    img = Image.fromarray(page.pixels).rotate(
        deg, resample=Image.Resampling.BICUBIC, fillcolor=fill
    )
    page.pixels = np.asarray(img).copy()
    boxes = [wd.ink_px for wd in page.words] + list(page.rules_px)
    if page.bar_px is not None:
        boxes.append(page.bar_px)
    hulls = []
    for x0, y0, x1, y1 in boxes:
        pts = tuple(
            rotate_point(x, y, page.width_px, page.height_px, deg)
            for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))
        )
        hull = (
            math.floor(min(p[0] for p in pts)),
            math.floor(min(p[1] for p in pts)),
            math.ceil(max(p[0] for p in pts)),
            math.ceil(max(p[1] for p in pts)),
        )
        hulls.append((pts, hull))
    rule_hulls = hulls[len(page.words) : len(page.words) + len(page.rules_px)]
    page.rules_px = [h for _, h in rule_hulls]
    page.rules_polygon_px = [
        tuple((round(px, 3), round(py, 3)) for px, py in pts) for pts, _ in rule_hulls
    ]
    for wd, (pts, hull) in zip(page.words, hulls, strict=False):
        mid = (wd.ink_px[0] + wd.ink_px[2]) / 2
        wd.baseline_px = round(
            rotate_point(mid, wd.baseline_px, page.width_px, page.height_px, deg)[1]
        )
        wd.ink_polygon_px = tuple((round(px, 3), round(py, 3)) for px, py in pts)
        wd.ink_px = hull
    if page.bar_px is not None:
        page.bar_px = hulls[-1][1]


def apply_blur(page: Page, centipx: int) -> None:
    if centipx:
        img = Image.fromarray(page.pixels).filter(ImageFilter.GaussianBlur(centipx / 100))
        page.pixels = np.asarray(img).copy()


def jpeg_bytes(page: Page, quality: int) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(page.pixels).save(
        buf, "JPEG", quality=quality, dpi=(page.dpi, page.dpi), optimize=False
    )
    return buf.getvalue()


def render(
    layout_name: str, ground: str, dpi: int, degrade: Degrade, seed: int
) -> tuple[Page, bytes]:
    """The printed page as a JPEG, and the page record (words with their final ink boxes)."""
    lay = layout(layout_name)
    w, h = page_size_px(dpi)
    mask, words, rules = draw_text_mask(lay, dpi)
    gp = ground_pixels(ground, dpi, seed)
    pixels = composite(gp, mask, TEXT_FILL[ground])
    page = Page(dpi, w, h, pixels, words, ground=ground, rules_px=rules)
    if ground == "black-bar":
        page.bar_px = paint_bar(page.pixels, words, dpi, seed)
    fill = int(np.median(gp[:, : max(1, w // 20)]))
    apply_skew(page, degrade.skew_centideg, fill)
    apply_blur(page, degrade.blur_centipx)
    return page, jpeg_bytes(page, degrade.jpeg_quality)
