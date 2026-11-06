"""Synthetic handwriting: page pictures only, never a real person's hand or signature.

Two kinds of hand:
- **font hand**: an openly licensed handwriting font (Caveat, Patrick Hand; ``fonts.py``) drawn one
  glyph at a time with seeded variation: a size change of up to ``SIZE_JITTER``, a tilt of up to
  ``TILT_DEG``, an offset of up to ``JITTER_EM`` em, a baseline wobble of ``WOBBLE_EM`` em, and a
  stroke made thicker or thinner per word (a max or min filter);
- **stroke cursive**: letters drawn as joined cubic Bézier strokes from a small set of shapes by
  letter class (x-height arch, round loop, ascender loop, descender loop; dots and crossbars added),
  each control point moved by a seeded amount and the pen width varied along the stroke. No font
  produces it. The signature scrawl is the same hand with taller loops and a closing flourish.

The pages:
- ``note``: a short note in Caveat;
- ``form``: a printed form (labels and rules, drawn with the Latin subset) filled in Patrick Hand;
- ``letter``: a short printed letter, closed by a stroke-cursive line and a signature scrawl.

Every word's ink box is the tight box of that word's own mask, in integer pixels (top-left origin,
exclusive right and bottom edges).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from hidden_layer.rng import mix_seed, scalar_ints

from . import fonts, texts

PAGE = (612, 792)
SIZE_JITTER = 0.08
TILT_DEG = 4.0
JITTER_EM = 0.04
WOBBLE_EM = 0.06
INK = 30
GROUND = 250


@dataclass
class HandWord:
    line: int
    text: str
    kind: str  # font-hand | stroke-cursive | print
    box: list[int] = field(default_factory=list)


@dataclass
class HandPage:
    name: str
    dpi: int
    mask: np.ndarray
    words: list[HandWord]
    lines: list[dict[str, object]]


def _u(seed: int, n: int) -> list[float]:
    """``n`` values in [-1, 1] from the seeded integer stream."""
    return [v / 1_000_000 for v in scalar_ints(seed, n, -1_000_000, 1_000_000)]


def _paste_max(dst: np.ndarray, src: np.ndarray, x: int, y: int) -> None:
    h, w = src.shape
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(dst.shape[1], x + w), min(dst.shape[0], y + h)
    if x1 <= x0 or y1 <= y0:
        return
    region = dst[y0:y1, x0:x1]
    np.maximum(region, src[y0 - y : y1 - y, x0 - x : x1 - x], out=region)


def _box(mask: np.ndarray) -> list[int]:
    ys, xs = np.nonzero(mask)
    if xs.size == 0:
        return []
    return [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1]


def font_hand_line(
    text: str,
    font_key: str,
    size_pt: float,
    x_pt: float,
    base_pt: float,
    dpi: int,
    seed: int,
    shape: tuple[int, int],
) -> list[tuple[str, np.ndarray]]:
    """One line in a handwriting font, one glyph at a time; returns (word, full-page word mask)."""
    s = dpi / 72
    path = str(fonts.handwriting_path(font_key))
    words = text.split(" ")
    out = []
    x = x_pt * s
    k = 0
    for wi, word in enumerate(words):
        wmask = np.zeros(shape, dtype=np.uint8)
        stroke = _u(mix_seed(seed, "stroke", wi), 1)[0]
        for ch in word:
            r = _u(mix_seed(seed, "glyph", k), 5)
            k += 1
            px = size_pt * s * (1 + SIZE_JITTER * r[0])
            f = ImageFont.truetype(path, px)
            left, top, right, bottom = (int(v) for v in f.getbbox(ch, anchor="ls"))
            pad = int(px * 0.3) + 2
            g = Image.new("L", (right - left + 2 * pad, bottom - top + 2 * pad), 0)
            ImageDraw.Draw(g).text((pad - left, pad - top), ch, font=f, fill=255, anchor="ls")
            g = g.rotate(TILT_DEG * r[1], resample=Image.Resampling.BICUBIC, expand=False)
            wobble = WOBBLE_EM * px * math.sin(x / (px * 3) + seed % 7)
            gx = round(x + left - pad + JITTER_EM * px * r[2])
            gy = round(base_pt * s + top - pad + JITTER_EM * px * r[3] + wobble)
            _paste_max(wmask, np.asarray(g), gx, gy)
            x += f.getlength(ch) * (1 + 0.03 * r[4])
        img = Image.fromarray(wmask)
        if stroke > 0.4:
            img = img.filter(ImageFilter.MaxFilter(3))
        elif stroke < -0.4:
            img = img.filter(ImageFilter.MinFilter(3)) if dpi >= 300 else img
        out.append((word, np.asarray(img).copy()))
        x += ImageFont.truetype(path, size_pt * s).getlength(" ")
    return out


# Stroke cursive: per letter class, control points (x in letter widths, y in x-heights; y up).
_CLASS = {
    **dict.fromkeys("bdfhklt", "asc"),
    **dict.fromkeys("gjpqyz", "desc"),
    **dict.fromkeys("aceo", "loop"),
}


def _letter_points(ch: str) -> list[tuple[float, float]]:
    kind = _CLASS.get(ch.lower(), "arch")
    if kind == "asc":
        return [(0.0, 0.0), (0.3, 1.6), (0.5, 2.4), (0.2, 2.2), (0.4, 0.8), (0.8, 0.0)]
    if kind == "desc":
        return [(0.0, 0.0), (0.4, 1.0), (0.8, 0.6), (0.6, -1.2), (0.3, -1.0), (0.9, 0.0)]
    if kind == "loop":
        return [(0.0, 0.0), (0.6, 1.0), (0.2, 0.9), (0.3, 0.1), (0.8, 0.5), (1.0, 0.0)]
    return [(0.0, 0.0), (0.25, 1.0), (0.55, 0.9), (0.75, 0.1), (1.0, 0.0)]


def _bezier(points: list[tuple[float, float]], steps: int = 12) -> list[tuple[float, float]]:
    """A smooth curve through the points (Catmull-Rom segments as cubic Béziers)."""
    out = []
    pts = [points[0], *points, points[-1]]
    for i in range(1, len(pts) - 2):
        p0, p1, p2, p3 = pts[i - 1], pts[i], pts[i + 1], pts[i + 2]
        c1 = (p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6)
        for k in range(steps):
            t = k / steps
            a = (1 - t) ** 3
            b = 3 * (1 - t) ** 2 * t
            c = 3 * (1 - t) * t**2
            d = t**3
            out.append(
                (
                    a * p1[0] + b * c1[0] + c * c2[0] + d * p2[0],
                    a * p1[1] + b * c1[1] + c * c2[1] + d * p2[1],
                )
            )
    out.append(points[-1])
    return out


def stroke_word(
    word: str,
    x_pt: float,
    base_pt: float,
    xh_pt: float,
    dpi: int,
    seed: int,
    shape: tuple[int, int],
    scrawl: bool = False,
) -> tuple[np.ndarray, float]:
    """One stroke-cursive word; returns its full-page mask and its end x (points)."""
    s = dpi / 72
    lw = xh_pt * 0.9
    pts: list[tuple[float, float]] = []
    extras: list[list[tuple[float, float]]] = []
    x = x_pt
    for i, ch in enumerate(word):
        r = _u(mix_seed(seed, "cur", i), 12)
        tall = 1.5 if scrawl else 1.0
        for j, (px, py) in enumerate(_letter_points(ch)):
            if pts and j == 0:
                continue
            jy = py * (tall if py > 1.2 else 1.0)
            pts.append(
                (x + (px + 0.08 * r[j % 12]) * lw, base_pt - (jy + 0.1 * r[(j + 5) % 12]) * xh_pt)
            )
        if ch.lower() in "ij":
            extras.append(
                [(x + 0.35 * lw, base_pt - 1.6 * xh_pt), (x + 0.4 * lw, base_pt - 1.65 * xh_pt)]
            )
        if ch.lower() == "t":
            extras.append(
                [(x - 0.1 * lw, base_pt - 1.3 * xh_pt), (x + 0.8 * lw, base_pt - 1.35 * xh_pt)]
            )
        x += lw * (1.0 + 0.1 * r[11])
    if scrawl:
        extras.append(
            _bezier(
                [
                    (x_pt - 4, base_pt + 0.8 * xh_pt),
                    ((x_pt + x) / 2, base_pt + 1.4 * xh_pt),
                    (x + 6, base_pt + 0.4 * xh_pt),
                ]
            )
        )
    img = Image.new("L", (shape[1], shape[0]), 0)
    d = ImageDraw.Draw(img)
    width = _u(mix_seed(seed, "pen"), 1)[0]
    for stroke in [_bezier(pts), *extras]:
        for k in range(len(stroke) - 1):
            pen = max(
                1, round((1.1 + 0.35 * math.sin(k / 5 + width * 3)) * s * (0.9 if scrawl else 0.75))
            )
            a = (stroke[k][0] * s, stroke[k][1] * s)
            b = (stroke[k + 1][0] * s, stroke[k + 1][1] * s)
            d.line([a, b], fill=255, width=pen)
            d.ellipse([b[0] - pen / 2, b[1] - pen / 2, b[0] + pen / 2, b[1] + pen / 2], fill=255)
    return np.asarray(img).copy(), x


def _print_line(
    text: str, size_pt: float, x_pt: float, base_pt: float, dpi: int, shape: tuple[int, int]
) -> list[tuple[str, np.ndarray]]:
    s = dpi / 72
    f = ImageFont.truetype(str(fonts.path_of("latin")), size_pt * s)
    out = []
    x = x_pt * s
    for word in text.split(" "):
        m = Image.new("L", (shape[1], shape[0]), 0)
        ImageDraw.Draw(m).text((round(x), round(base_pt * s)), word, font=f, fill=255, anchor="ls")
        out.append((word, np.asarray(m).copy()))
        x += f.getlength(word + " ")
    return out


NOTE_LINES = (
    "Call the office about the file on Monday.",
    f"Ask for the account ending {texts.ACCOUNT[-2:]} and the new date.",
    f"The number is {texts.PHONE}.",
    "Bring the signed copy and the two forms.",
    "Thank you - back by four.",
)
FORM_ROWS = (
    ("Full name:", "Wren Castellano"),
    ("Telephone:", "(206) 555-0187"),
    ("Date:", "30/10/2026"),
    ("Account:", texts.ACCOUNT),
    ("E-mail:", "w.castellano@example.org"),
)
LETTER_LINES = (
    "Fallowmere Records Office",
    "30 October 2026",
    "Dear Records Office,",
    "Thank you for the copy of the file. The forms are enclosed,",
    "signed and dated. Please call me if anything is missing.",
    "Sincerely,",
)
CURSIVE_LINE = "with many thanks"
SIGNATURE = "wren castellano"


def build_page(name: str, dpi: int, seed: int) -> HandPage:
    w, h = round(PAGE[0] * dpi / 72), round(PAGE[1] * dpi / 72)
    shape = (h, w)
    mask = np.zeros(shape, dtype=np.uint8)
    words: list[HandWord] = []
    lines: list[dict[str, object]] = []

    def add(line: int, kind: str, pieces: list[tuple[str, np.ndarray]]) -> None:
        for text, m in pieces:
            np.maximum(mask, m, out=mask)
            words.append(HandWord(line, text, kind, _box(m)))

    def add_rule(x0: float, x1: float, y: float) -> None:
        s = dpi / 72
        mask[
            round(y * s) : round(y * s) + max(1, round(0.6 * s)), round(x0 * s) : round(x1 * s)
        ] = 255

    if name == "note":
        for i, t in enumerate(NOTE_LINES):
            add(
                i,
                "font-hand",
                font_hand_line(
                    t, "caveat", 22, 80, 130 + 46 * i, dpi, mix_seed(seed, "note", i), shape
                ),
            )
            lines.append(
                {"line": i, "text": t, "kind": "font-hand", "font": "Caveat", "meaning": t}
            )
    elif name == "form":
        add(
            0,
            "print",
            _print_line("SYNTHETIC INTAKE FORM - FICTIONAL DATA", 12, 72, 80, dpi, shape),
        )
        lines.append(
            {
                "line": 0,
                "text": "SYNTHETIC INTAKE FORM - FICTIONAL DATA",
                "kind": "print",
                "font": "Noto Sans Subset",
                "meaning": "heading",
            }
        )
        for i, (label, value) in enumerate(FORM_ROWS, start=1):
            y = 140 + 52 * (i - 1)
            add(len(lines), "print", _print_line(label, 12, 72, y, dpi, shape))
            lines.append(
                {
                    "line": len(lines),
                    "text": label,
                    "kind": "print",
                    "font": "Noto Sans Subset",
                    "meaning": label,
                }
            )
            add_rule(200, 520, y + 4)
            add(
                len(lines),
                "font-hand",
                font_hand_line(
                    value, "patrickhand", 18, 206, y - 2, dpi, mix_seed(seed, "form", i), shape
                ),
            )
            lines.append(
                {
                    "line": len(lines),
                    "text": value,
                    "kind": "font-hand",
                    "font": "Patrick Hand",
                    "meaning": value,
                }
            )
    elif name == "letter":
        for i, t in enumerate(LETTER_LINES):
            y = 90 + 28 * i + (30 if i >= 2 else 0) + (20 if i >= 5 else 0)
            add(i, "print", _print_line(t, 12, 72, y, dpi, shape))
            lines.append(
                {"line": i, "text": t, "kind": "print", "font": "Noto Sans Subset", "meaning": t}
            )
        x = 80.0
        n = len(lines)
        for wi, word in enumerate(CURSIVE_LINE.split(" ")):
            m, x = stroke_word(word, x, 330, 7, dpi, mix_seed(seed, "cursive", wi), shape)
            np.maximum(mask, m, out=mask)
            words.append(HandWord(n, word, "stroke-cursive", _box(m)))
            x += 9
        lines.append(
            {
                "line": n,
                "text": CURSIVE_LINE,
                "kind": "stroke-cursive",
                "font": None,
                "meaning": CURSIVE_LINE,
            }
        )
        x = 90.0
        n = len(lines)
        for wi, word in enumerate(SIGNATURE.split(" ")):
            m, x = stroke_word(word, x, 400, 9, dpi, mix_seed(seed, "sig", wi), shape, scrawl=True)
            np.maximum(mask, m, out=mask)
            words.append(HandWord(n, word, "stroke-cursive", _box(m)))
            x += 12
        lines.append(
            {
                "line": n,
                "text": SIGNATURE,
                "kind": "stroke-cursive",
                "font": None,
                "meaning": "a signature-like scrawl (synthetic)",
            }
        )
    else:
        raise ValueError(name)
    return HandPage(name, dpi, mask, words, lines)


def pixels(page: HandPage) -> np.ndarray:
    m = page.mask.astype(np.int64)
    return ((GROUND * (255 - m) + INK * m + 127) // 255).astype(np.uint8)
