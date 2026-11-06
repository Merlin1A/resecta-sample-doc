"""Exact rectangle arithmetic over ``Fraction`` coordinates (PDF points, bottom-left origin).

A rectangle is ``(x0, y0, x1, y1)`` with ``x0 <= x1`` and ``y0 <= y1``. Every judgement here is a
pure function with no floating point.
"""

from __future__ import annotations

from fractions import Fraction
from itertools import pairwise

Rect = tuple[Fraction, Fraction, Fraction, Fraction]


def rect(x0: Fraction | int, y0: Fraction | int, x1: Fraction | int, y1: Fraction | int) -> Rect:
    return (Fraction(x0), Fraction(y0), Fraction(x1), Fraction(y1))


def area(r: Rect) -> Fraction:
    return max(Fraction(0), r[2] - r[0]) * max(Fraction(0), r[3] - r[1])


def intersect(a: Rect, b: Rect) -> Rect | None:
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[2], b[2]), min(a[3], b[3])
    if x1 <= x0 or y1 <= y0:
        return None
    return (x0, y0, x1, y1)


def covered_area(box: Rect, rects: list[Rect]) -> Fraction:
    """The area of ``box`` covered by the union of ``rects`` (coordinate compression; exact)."""
    clipped = [c for c in (intersect(box, r) for r in rects) if c is not None]
    if not clipped:
        return Fraction(0)
    xs = sorted({c[0] for c in clipped} | {c[2] for c in clipped})
    ys = sorted({c[1] for c in clipped} | {c[3] for c in clipped})
    total = Fraction(0)
    for xa, xb in pairwise(xs):
        mx = (xa + xb) / 2
        for ya, yb in pairwise(ys):
            my = (ya + yb) / 2
            if any(c[0] <= mx <= c[2] and c[1] <= my <= c[3] for c in clipped):
                total += (xb - xa) * (yb - ya)
    return total


def relation(box: Rect, rects: list[Rect]) -> str:
    """``inside`` (wholly covered by the union), ``outside`` (no area in common) or ``partial``.
    A box of zero area is judged by whether it lies within some rectangle."""
    a = area(box)
    if a == 0:
        inside = any(
            r[0] <= box[0] and box[2] <= r[2] and r[1] <= box[1] and box[3] <= r[3] for r in rects
        )
        return "inside" if inside else "outside"
    c = covered_area(box, rects)
    if c == a:
        return "inside"
    if c == 0:
        return "outside"
    return "partial"


def centre(r: Rect) -> tuple[Fraction, Fraction]:
    return ((r[0] + r[2]) / 2, (r[1] + r[3]) / 2)


def contains_point(r: Rect, p: tuple[Fraction, Fraction]) -> bool:
    return r[0] <= p[0] <= r[2] and r[1] <= p[1] <= r[3]


def pad(r: Rect, d: Fraction) -> Rect:
    return (r[0] - d, r[1] - d, r[2] + d, r[3] + d)


def hull(rs: list[Rect]) -> Rect:
    return (
        min(r[0] for r in rs),
        min(r[1] for r in rs),
        max(r[2] for r in rs),
        max(r[3] for r in rs),
    )


def translate_centre_to(r: Rect, target: tuple[Fraction, Fraction]) -> Rect:
    cx, cy = centre(r)
    dx, dy = target[0] - cx, target[1] - cy
    return (r[0] + dx, r[1] + dy, r[2] + dx, r[3] + dy)
