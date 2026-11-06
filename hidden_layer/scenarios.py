"""Region scenarios: the boxes a test applies to a document, and the geometric facts about them.

A scenario is a list of regions. Each region has a ``paint`` rectangle (the box as drawn) and an
optional ``strip`` rectangle (the hidden-copy box recorded when the box was placed from a text
search of the hidden layer; none for a box drawn by hand, duplicated, or placed from text
recognition of the picture). The facts recorded per scenario are, all exact over the recorded
coordinates:

- ``marked``: the words whose printed ink box has its centre inside some region's paint;
- ``must_be_absent``: those words' hidden strings, which a correct export carries nowhere;
- per marked word, each hidden glyph's relation to the union of every region's paint and strip
  (``inside``, ``partial`` or ``outside`` by area) and whether the glyph's centre is covered;
- ``hidden_copies_covered``: whether every marked word's hidden glyphs have their centres inside
  that union. When it is false, removing hidden text only under the regions' rectangles leaves
  the uncovered glyphs (listed in ``uncovered_glyphs``);
- ``unmarked_glyphs_meeting_rects``: hidden glyphs of words that are not marked but share area with
  the union (a removal by rectangle may take them too).

The scenario kinds:

| kind | regions |
|---|---|
| no-box | none |
| hand-box | paint = a word's ink box grown by ``PAD``; no strip |
| duplicate-moved | a copy of a search box on one word, moved so its centre sits on another word's ink centre; no strip |
| search-resized | a search box on one word (paint and strip), its paint then grown by hand to cover the following words' ink |
| search-moved | a search box on one word, its paint then moved onto another word's ink centre; the strip is unchanged |
| recognition-box | paint = the ink box of a word whose hidden copy is spelled differently; no strip |
| search-as-placed | a search box on one word: paint = its ink box grown by ``PAD``, strip = its hidden box |
| whole-page | paint = the page; no strip |
| two-boxes | box A on a word's ink, box B on the same word's hidden box; both by hand |
| bar-box | paint = the black bar already printed on the page, grown by ``PAD``; no strip |
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from .geometry import Rect, centre, contains_point, hull, pad, rect, relation, translate_centre_to

PAD = Fraction(3, 2)
__all__ = [
    "PAD",
    "Glyph",
    "Piece",
    "Rect",
    "Region",
    "WordGeom",
    "facts",
    "rect",
    "scenario_regions",
]


@dataclass(frozen=True)
class Glyph:
    char: str
    box: Rect


@dataclass(frozen=True)
class Piece:
    text: str
    box: Rect
    glyphs: tuple[Glyph, ...]


@dataclass(frozen=True)
class WordGeom:
    index: int
    line_key: str
    position: int
    text: str
    ink: Rect
    hidden: tuple[Piece, ...]
    under_bar: bool = False


@dataclass(frozen=True)
class Region:
    made_by: str
    paint: Rect
    strip: Rect | None


def _find(words: list[WordGeom], key: str, pos: int) -> WordGeom:
    for w in words:
        if w.line_key == key and w.position == pos:
            return w
    raise KeyError((key, pos))


def _hidden_box(w: WordGeom) -> Rect:
    return hull([p.box for p in w.hidden])


def _hand(w: WordGeom) -> Region:
    return Region("hand", pad(w.ink, PAD), None)


def _search(w: WordGeom) -> Region:
    return Region("search", pad(w.ink, PAD), _hidden_box(w))


# The targets, by (line key, word position) on the common scenario lines.
SURNAME = ("contact", 2)
SIGNER = ("signed", 2)
SIGNED = ("signed", 0)
FIRST_THE = ("holds", 0)
DUP_TARGET = ("copies", 3)
MOVE_TARGET = ("copies", 5)


def scenario_regions(
    words: list[WordGeom], page: Rect, bar: Rect | None, misread: bool
) -> list[tuple[str, str, list[Region], dict[str, object]]]:
    """(name, kind, regions, notes) for every scenario this document carries."""
    sur = _find(words, *SURNAME)
    signer = _find(words, *SIGNER)
    signed = _find(words, *SIGNED)
    the = _find(words, *FIRST_THE)
    dup_to = _find(words, *DUP_TARGET)
    move_to = _find(words, *MOVE_TARGET)
    s_sur = _search(sur)
    s_signed = _search(signed)
    resized_paint = hull([s_signed.paint, pad(signer.ink, PAD)])
    out: list[tuple[str, str, list[Region], dict[str, object]]] = [
        ("no-box", "no-box", [], {}),
        ("hand-box-surname", "hand-box", [_hand(sur)], {"target": sur.index}),
        ("hand-box-short-word", "hand-box", [_hand(signer)], {"target": signer.index}),
        ("hand-box-first-word", "hand-box", [_hand(signed)], {"target": signed.index}),
        (
            "hand-box-narrow-first-word",
            "hand-box",
            [_hand(the)],
            {"target": the.index, "ink_width_pt": the.ink[2] - the.ink[0]},
        ),
        (
            "duplicate-moved",
            "duplicate-moved",
            [Region("duplicate", translate_centre_to(s_sur.paint, centre(dup_to.ink)), None)],
            {"source": sur.index, "target": dup_to.index},
        ),
        (
            "search-resized",
            "search-resized",
            [Region("search-resized", resized_paint, s_signed.strip)],
            {"source": signed.index, "grown_over_through": signer.index},
        ),
        (
            "search-moved",
            "search-moved",
            [
                Region(
                    "search-moved",
                    translate_centre_to(s_sur.paint, centre(move_to.ink)),
                    s_sur.strip,
                )
            ],
            {"source": sur.index, "target": move_to.index},
        ),
    ]
    if misread:
        out.append(
            (
                "recognition-box-surname",
                "recognition-box",
                [Region("recognition", pad(sur.ink, PAD), None)],
                {"target": sur.index},
            )
        )
    out += [
        ("search-as-placed-surname", "search-as-placed", [s_sur], {"target": sur.index}),
        (
            "search-as-placed-short-word",
            "search-as-placed",
            [_search(signer)],
            {"target": signer.index},
        ),
        ("whole-page", "whole-page", [Region("whole-page", page, None)], {}),
        (
            "two-boxes-surname",
            "two-boxes",
            [_hand(sur), Region("hand", pad(_hidden_box(sur), PAD), None)],
            {"target": sur.index, "box_a": "ink", "box_b": "hidden copy"},
        ),
    ]
    if bar is not None:
        out.append(("bar-box", "bar-box", [Region("hand", pad(bar, PAD), None)], {}))
    return out


def glyph_centre(g: Glyph) -> tuple[Fraction, Fraction]:
    return centre(g.box)


def facts(words: list[WordGeom], regions: list[Region]) -> dict[str, object]:
    """The geometric facts of one scenario (see the module docstring)."""
    rects = [r.paint for r in regions] + [r.strip for r in regions if r.strip is not None]
    marked = [w for w in words if any(contains_point(r.paint, centre(w.ink)) for r in regions)]
    marked_ids = {w.index for w in marked}
    per_word = []
    uncovered: list[dict[str, object]] = []
    for w in marked:
        rels = []
        missed = []
        for p in w.hidden:
            for g in p.glyphs:
                rel = relation(g.box, rects)
                cov = any(contains_point(r, glyph_centre(g)) for r in rects)
                rels.append(rel[0])
                if not cov:
                    missed.append(g.char)
        per_word.append({"word": w.index, "glyph_relations": "".join(rels)})
        if missed:
            uncovered.append({"word": w.index, "glyphs": "".join(missed)})
    meeting = []
    for w in words:
        if w.index in marked_ids:
            continue
        hit = "".join(
            g.char for p in w.hidden for g in p.glyphs if relation(g.box, rects) != "outside"
        )
        if hit:
            meeting.append({"word": w.index, "glyphs": hit})
    return {
        "marked": [w.index for w in marked],
        "must_be_absent": [" ".join(p.text for p in w.hidden) for w in marked],
        "glyphs": per_word,
        "hidden_copies_covered": not uncovered,
        "uncovered_glyphs": uncovered,
        "unmarked_glyphs_meeting_rects": meeting,
    }
