"""Pure-function tests for tools/register_capture.py (no images, no OpenCV).

The functions under test are the array-in / array-out helpers the registration tool runs before and
after detection: the leg table, the filename page hint, the sub-dictionary Hamming distance, the
duplicate-candidate resolution and the condition labels. Expected values are the ones the tool
itself recorded in its registration output for the synthetic golden run stamped 20260825-2000
(pypdfium2 rasters of the 16 capture masters at 150 and 300 DPI, every page accepted on four
markers) and, for the rotated-leg conditions, the capture run stamped 20260829-0955. The values
are copied here as literals; no run output enters the repository.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

_SPEC = importlib.util.spec_from_file_location(
    "register_capture", REPO / "tools" / "register_capture.py"
)
assert _SPEC is not None and _SPEC.loader is not None
RC = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(RC)

# Page 0 of the golden run: the four marker quads (TL, TR, BR, BL in image pixels) cv2 returned on
# the 1275 x 1651 raster, keyed by marker id.
GOLDEN_PAGE0_QUADS = {
    0: [[36.596, 1562.616], [87.388, 1562.611], [87.389, 1613.39], [36.618, 1613.396]],
    1: [[1186.629, 1562.621], [1237.395, 1562.611], [1237.376, 1613.398], [1186.607, 1613.385]],
    2: [[1186.619, 36.604], [1237.389, 36.616], [1237.389, 87.387], [1186.613, 87.389]],
    3: [[36.611, 36.618], [87.388, 36.614], [87.387, 87.387], [36.612, 87.387]],
}
GOLDEN_PAGE0_PERIMETER_ID0 = 203.122

# `restricted_pass.min_hamming_distance` per page of the golden run (ids = 4*page .. 4*page+3).
GOLDEN_MIN_HAMMING = {
    0: 7, 1: 6, 2: 5, 3: 5, 4: 5, 5: 6, 6: 5, 7: 4,
    8: 4, 9: 4, 10: 5, 11: 4, 12: 5, 13: 4, 14: 4, 15: 6,
}  # fmt: skip


def _quads(d: dict[int, list[list[float]]]) -> dict[int, list[np.ndarray]]:
    return {i: [np.array(q, np.float32)] for i, q in d.items()}


def test_leg_spec_named_legs_match_the_leg_table():
    # the golden legs report kind / dpi / features exactly as the leg table declares them
    assert RC.leg_spec("scan150") == {
        "kind": "K1",
        "dpi": 150,
        "features": ["F0"],
        "synthetic": False,
    }
    assert RC.leg_spec("scan300") == {
        "kind": "K2",
        "dpi": 300,
        "features": ["F0"],
        "synthetic": False,
    }
    assert RC.leg_spec("rotated") == {
        "kind": "K1",
        "dpi": 150,
        "features": ["F1"],
        "synthetic": False,
    }
    assert RC.leg_spec("photo") == {
        "kind": "K3",
        "dpi": None,
        "features": ["F0"],
        "synthetic": False,
    }


def test_leg_spec_synthetic_rasters_derive_kind_from_dpi():
    # the golden run's two legs: synth150 -> K1 at 150 DPI, synth300 -> K2 at 300 DPI, both synthetic
    assert RC.leg_spec("synth150") == {
        "kind": "K1",
        "dpi": 150,
        "features": ["F0"],
        "synthetic": True,
    }
    assert RC.leg_spec("synth300") == {
        "kind": "K2",
        "dpi": 300,
        "features": ["F0"],
        "synthetic": True,
    }
    assert RC.leg_spec("synth150-rot90")["features"] == ["F1"]
    assert RC.leg_spec("mystery") == {
        "kind": None,
        "dpi": None,
        "features": ["F0"],
        "synthetic": False,
    }


@pytest.mark.parametrize(
    ("name", "hint"),
    [
        ("p01.jpg", 0),  # the golden run: p01 .. p16 all agreed with the marker vote
        ("p16.jpg", 15),
        ("derived-rot90-p02.png", 1),
        ("p02-rot180.jpg", 1),
        ("seq-01.jpg", None),  # no page hint in the name -> the marker vote alone decides
        ("page123.jpg", None),  # three digits are not a two-digit hint
    ],
)
def test_page_hint_reads_a_two_digit_p_token(name, hint):
    assert RC.page_hint(Path(name)) == hint


@pytest.mark.parametrize(("page", "expected"), sorted(GOLDEN_MIN_HAMMING.items()))
def test_min_hamming_distance_per_golden_page(page, expected):
    ids = [4 * page + k for k in range(4)]
    assert RC.min_hamming_distance(ids) == expected


def test_min_hamming_distance_of_a_single_marker_is_the_grid_size():
    assert RC.min_hamming_distance([0]) == RC.A.GRID * RC.A.GRID


def test_perimeter_of_the_golden_quad():
    assert RC._perimeter(np.array(GOLDEN_PAGE0_QUADS[0], np.float64)) == pytest.approx(
        GOLDEN_PAGE0_PERIMETER_ID0, abs=1e-3
    )


def test_choose_candidates_keeps_singletons_and_reports_no_duplicates():
    chosen, dups = RC.choose_candidates(_quads(GOLDEN_PAGE0_QUADS))
    assert dups == []
    assert sorted(chosen) == [0, 1, 2, 3]
    for i, q in GOLDEN_PAGE0_QUADS.items():
        assert np.allclose(chosen[i], np.array(q, np.float32))


def test_choose_candidates_resolves_a_duplicate_toward_the_agreed_perimeter():
    found = _quads(GOLDEN_PAGE0_QUADS)
    true_quad = found[0][0]
    shrunken = true_quad.mean(axis=0) + (true_quad - true_quad.mean(axis=0)) * 0.5
    found[0] = [shrunken.astype(np.float32), true_quad]
    chosen, dups = RC.choose_candidates(found)
    assert dups == [0]
    assert np.allclose(chosen[0], true_quad)


def test_choose_candidates_without_a_reference_takes_the_first_candidate():
    only = np.array(GOLDEN_PAGE0_QUADS[0], np.float32)
    chosen, dups = RC.choose_candidates({0: [only, only * 0.5]})
    assert dups == [0]
    assert np.allclose(chosen[0], only)


@pytest.mark.parametrize(
    ("leg", "reg", "name", "k", "group_size", "expected"),
    [
        ("photo", {}, "IMG_0001.jpg", 0, 3, "flat"),  # the golden photo_order
        ("photo", {}, "IMG_0002.jpg", 1, 3, "skew"),
        ("photo", {}, "IMG_0003.jpg", 2, 3, "shadow"),
        ("photo", {}, "IMG_0001.jpg", 0, 2, "cond1"),  # a group that is not the photo order
        ("rotated", {}, "derived-rot90-p02.png", 0, 1, "rot90"),  # the 20260829-0955 rotated leg
        ("rotated", {}, "p02-rot180.jpg", 0, 1, "rot180"),
        ("rotated", {"rotation_quadrant": 3}, "p02.jpg", 0, 1, "rot3"),
        ("generations", {}, "p02-g2.jpg", 0, 1, "gen2"),
        ("generations", {}, "p02-gen3.jpg", 0, 1, "gen3"),
        ("generations", {}, "p02.jpg", 0, 1, "gen?"),
        ("scan150", {}, "seq-01.jpg", 0, 16, None),  # no condition axis on the scan legs
    ],
)
def test_condition_of(leg, reg, name, k, group_size, expected):
    order = ["flat", "skew", "shadow"]
    assert RC.condition_of(leg, reg, Path(name), k, group_size, order) == expected
