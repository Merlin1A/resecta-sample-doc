"""Word ink boxes measured from a rendered page.

A line's band is the strip from ``BAND_BELOW`` em under its baseline to ``BAND_ABOVE`` em above it,
inside the line's x span (for a vertical line, the column within ``COLUMN_HALF`` em of its centre,
from its top down to ``BOTTOM_MARGIN_PT``). Pixels under an excluded rectangle (a form rule) are
not ink.
In the band, ink is every pixel darker than ``INK_LEVEL`` (on a picture whose ground is darker, the
threshold is halfway between the band's darkest pixel and its median). Ink columns (rows, for a
vertical line) are grouped into words (ink groups) wherever a gap of at least ``WORD_GAP`` em
(``WORD_GAP_VERTICAL`` em down a vertical column) separates them; a group's box is the tight box of
its ink. Boxes are integer pixels, top-left origin, exclusive right
and bottom edges.
"""

from __future__ import annotations

import numpy as np

BAND_BELOW = 0.45
BAND_ABOVE = 1.15
COLUMN_HALF = 0.75
WORD_GAP = 0.25
WORD_GAP_VERTICAL = 0.6
INK_LEVEL = 128


def _runs(idx: np.ndarray, max_gap: int) -> list[tuple[int, int]]:
    if idx.size == 0:
        return []
    out = []
    start = prev = int(idx[0])
    for raw in idx[1:]:
        i = int(raw)
        if i - prev - 1 >= max_gap:
            out.append((start, prev))
            start = i
        prev = i
    out.append((start, prev))
    return out


def threshold(band: np.ndarray) -> float:
    if band.size == 0:
        return INK_LEVEL
    med = float(np.median(band))
    if med >= 200:
        return INK_LEVEL
    return (float(band.min()) + med) / 2


BOTTOM_MARGIN_PT = 72


def word_boxes(
    img: np.ndarray,
    dpi: int,
    size: float,
    y_pt: float,
    span: tuple[float, float],
    vertical_x: float | None = None,
    page_h: float = 792.0,
    exclude: list[tuple[float, float, float, float]] | None = None,
) -> list[list[int]]:
    """``exclude``: rectangles (PDF points) whose pixels are not ink (the form rules)."""
    s = dpi / 72
    h, w = img.shape
    if exclude:
        img = img.copy()
        for ex0, ey0, ex1, ey1 in exclude:
            img[
                max(0, int((page_h - ey1) * s) - 2) : int((page_h - ey0) * s) + 3,
                max(0, int(ex0 * s) - 2) : int(ex1 * s) + 3,
            ] = 255
    gap = max(1, round((WORD_GAP if vertical_x is None else WORD_GAP_VERTICAL) * size * s))
    if vertical_x is None:
        y0 = max(0, round((page_h - y_pt - BAND_ABOVE * size) * s))
        y1 = min(h, round((page_h - y_pt + BAND_BELOW * size) * s))
        x0 = max(0, round(span[0] * s))
        x1 = min(w, round(span[1] * s))
    else:
        x0 = max(0, round((vertical_x - COLUMN_HALF * size) * s))
        x1 = min(w, round((vertical_x + COLUMN_HALF * size) * s))
        y0 = max(0, round((page_h - y_pt - 0.5 * size) * s))
        y1 = min(h, round((page_h - BOTTOM_MARGIN_PT) * s))
    band = img[y0:y1, x0:x1]
    ink = band < threshold(band)
    out = []
    if vertical_x is None:
        for a, b in _runs(np.flatnonzero(ink.any(axis=0)), gap):
            rows = np.flatnonzero(ink[:, a : b + 1].any(axis=1))
            out.append([x0 + a, y0 + int(rows[0]), x0 + b + 1, y0 + int(rows[-1]) + 1])
    else:
        for a, b in _runs(np.flatnonzero(ink.any(axis=1)), gap):
            cols = np.flatnonzero(ink[a : b + 1, :].any(axis=0))
            out.append([x0 + int(cols[0]), y0 + a, x0 + int(cols[-1]) + 1, y0 + b + 1])
    return out
