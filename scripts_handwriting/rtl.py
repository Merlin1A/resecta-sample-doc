"""Right-to-left text for a writer that does not shape: visual order and Arabic presentation forms.

``visual(line)`` returns the characters of a right-to-left line in the order they are drawn from
left to right:
- the line is cut into right-to-left runs (Hebrew or Arabic letters, and the spaces and neutral
  punctuation between them) and left-to-right runs (digits, Latin letters, and the punctuation
  inside them);
- the run order is reversed, and each right-to-left run is reversed within itself;
- in Arabic runs each letter is first replaced by its contextual presentation form (isolated,
  initial, medial or final), and lam followed by alef by the lam-alef ligature.

The form table is read from the Unicode character database (``unicodedata``): every character in
U+FE70-U+FEFF whose decomposition is ``<isolated>``, ``<initial>``, ``<medial>`` or ``<final>`` of a
base letter. A letter with no initial form joins on its right side only.
"""

from __future__ import annotations

import unicodedata

_FORMS: dict[tuple[str, str], str] = {}
_LIGATURES: dict[tuple[str, str], str] = {}
for _cp in range(0xFE70, 0xFF00):
    _ch = chr(_cp)
    _d = unicodedata.decomposition(_ch)
    if not _d.startswith("<"):
        continue
    _tag, *_bases = _d.split()
    _form = _tag.strip("<>")
    _chars = tuple(chr(int(b, 16)) for b in _bases)
    if len(_chars) == 1:
        _FORMS[(_chars[0], _form)] = _ch
    elif len(_chars) == 2 and _form in ("isolated", "final"):
        _LIGATURES[(_chars[0] + _chars[1], _form)] = _ch


def is_rtl_letter(c: str) -> bool:
    return unicodedata.bidirectional(c) in ("R", "AL")


def _joins_left(c: str) -> bool:
    """The letter can join to the following letter (it has an initial form)."""
    return (c, "initial") in _FORMS


def _joins(c: str) -> bool:
    return (c, "isolated") in _FORMS or (c, "final") in _FORMS


def shape_arabic(run: str) -> str:
    """The run (logical order) with each Arabic letter in its contextual form; lam-alef ligated."""
    out = []
    i = 0
    n = len(run)
    while i < n:
        c = run[i]
        prev = run[i - 1] if i > 0 else ""
        nxt = run[i + 1] if i + 1 < n else ""
        joined_before = bool(prev) and _joins_left(prev) and _joins(c)
        if c == "\u0644" and nxt in ("\u0627", "\u0622", "\u0623", "\u0625"):
            lig = _LIGATURES.get((c + nxt, "final" if joined_before else "isolated"))
            if lig:
                out.append(lig)
                i += 2
                continue
        if not _joins(c):
            out.append(c)
            i += 1
            continue
        joined_after = bool(nxt) and _joins_left(c) and _joins(nxt)
        form = {
            (False, False): "isolated",
            (True, False): "final",
            (False, True): "initial",
            (True, True): "medial",
        }[(joined_before, joined_after)]
        out.append(_FORMS.get((c, form), _FORMS.get((c, "isolated"), c)))
        i += 1
    return "".join(out)


def _runs(line: str) -> list[tuple[bool, str]]:
    """(right-to-left?, text) runs; a neutral character joins the run before it unless it sits
    between two left-to-right characters."""
    out: list[tuple[bool, str]] = []
    for i, c in enumerate(line):
        bidi = unicodedata.bidirectional(c)
        if bidi in ("R", "AL"):
            rtl = True
        elif bidi in ("L", "EN", "AN", "ES", "ET", "CS") and not c.isspace():
            rtl = False
        else:
            before = next((not _is_ltr(x) for x in reversed(line[:i]) if not _neutral(x)), True)
            after = next((not _is_ltr(x) for x in line[i + 1 :] if not _neutral(x)), True)
            rtl = before or after
        if out and out[-1][0] == rtl:
            out[-1] = (rtl, out[-1][1] + c)
        else:
            out.append((rtl, c))
    return out


def _neutral(c: str) -> bool:
    return (
        unicodedata.bidirectional(c) not in ("R", "AL", "L", "EN", "AN", "ES", "ET", "CS")
        or c.isspace()
    )


def _is_ltr(c: str) -> bool:
    return unicodedata.bidirectional(c) in ("L", "EN", "AN", "ES", "ET", "CS")


_MIRROR = {"(": ")", ")": "(", "[": "]", "]": "[", "<": ">", ">": "<"}


def visual(line: str) -> str:
    parts = []
    for rtl, text in reversed(_runs(line)):
        if rtl:
            shaped = shape_arabic(text)
            parts.append("".join(_MIRROR.get(c, c) for c in reversed(shaped)))
        else:
            parts.append(text)
    return "".join(parts)
