"""Pure-function tests for tools/search_oracle.py: the engine-rule re-implementation the
differential oracle runs (normalisation, the separator and diacritic folds with their offset maps,
the whole-word rule, the literal matcher's non-overlapping walk, and the word-box IoU). No PDFs,
no external tools; the tool is loaded by file path like its siblings.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

_SPEC = importlib.util.spec_from_file_location("search_oracle", REPO / "tools" / "search_oracle.py")
assert _SPEC is not None and _SPEC.loader is not None
SO = importlib.util.module_from_spec(_SPEC)
sys.modules["search_oracle"] = SO
_SPEC.loader.exec_module(SO)


def _opt(**flags: bool) -> dict:
    """An option vector with every toggle off except the ones named."""
    opt = dict.fromkeys(SO.TOGGLES, False)
    opt.update(flags)
    return opt


def test_nfkc_expands_the_ligature_table_then_normalises() -> None:
    assert SO.nfkc("ﬁle ﬃx") == "file ffix"


def test_smart_punct_maps_the_curly_quotes_and_dashes_to_ascii() -> None:
    assert SO.smart_punct("“quoted” — dash") == '"quoted" - dash'


def test_strip_separators_returns_the_offset_map_into_the_source() -> None:
    assert SO.strip_separators("123-45 6789") == ("123456789", [0, 1, 2, 4, 5, 7, 8, 9, 10])


def test_fold_diacritics_keeps_one_offset_per_folded_character() -> None:
    assert SO.fold_diacritics("José") == ("Jose", [0, 1, 2, 3])


def test_whole_word_rule_rejects_a_match_inside_a_word() -> None:
    assert SO.whole_word_ok("a cat.", 2, 5) is True
    assert SO.whole_word_ok("concat", 3, 6) is False


def test_literal_matcher_walks_left_to_right_without_overlap() -> None:
    page = "Acct 123-45-6789 and 123456789"
    assert SO.literal_matches(page, "123456789", _opt(normalizeUnicode=True)) == [(21, 30)]


def test_literal_matcher_maps_stripped_hits_back_to_base_offsets() -> None:
    page = "Acct 123-45-6789 and 123456789"
    opt = _opt(normalizeUnicode=True, stripDigitSeparators=True)
    assert SO.literal_matches(page, "123456789", opt) == [(5, 16), (21, 30)]


def test_literal_matcher_honours_whole_word() -> None:
    page = "cat concat cat"
    assert SO.literal_matches(page, "cat", _opt(normalizeUnicode=True)) == [
        (0, 3),
        (7, 10),
        (11, 14),
    ]
    assert SO.literal_matches(page, "cat", _opt(normalizeUnicode=True, wholeWord=True)) == [
        (0, 3),
        (11, 14),
    ]


def test_literal_matcher_folds_diacritics_on_both_sides() -> None:
    opt = _opt(normalizeUnicode=True, foldDiacritics=True)
    assert SO.literal_matches("José and Jose", "jose", opt) == [(0, 4), (9, 13)]


def test_iou_of_word_boxes() -> None:
    assert SO.iou((0, 0, 2, 2), (1, 1, 2, 2)) == 1 / 7
    assert SO.iou((0, 0, 1, 1), (5, 5, 1, 1)) == 0.0
