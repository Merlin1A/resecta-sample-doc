"""seeded_score: the share-gate predicates, the sweep count, Wilson, and the gate readings."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import seeded_score as ss


def lay(layer: str, status: str, cnv: bool = False, query: bool = False) -> dict:
    return {"layer": layer, "status": status, "could_not_verify": cnv, "has_query_lines": query}


def run(overall: str, *layers: dict) -> dict:
    return {"overall": overall, "layers": list(layers)}


def test_alarm_checks_ignores_the_possible_items_line() -> None:
    r = run("info", lay("textExtraction", "pass"), lay("detectionSweep", "info", query=True))
    assert ss.alarm(r) is True
    assert ss.alarm_checks(r) is False


@pytest.mark.parametrize("overall", ["fail", "attention", "skipped"])
def test_serious_overall_raises_both(overall: str) -> None:
    r = run(overall, lay("ocrCheck", "attention"))
    assert ss.alarm(r) and ss.alarm_checks(r)


def test_warn_alarms_only_with_a_skipped_or_unverifiable_layer() -> None:
    assert not ss.alarm_checks(run("warn", lay("metadataCheck", "warn")))
    assert ss.alarm_checks(run("warn", lay("metadataCheck", "warn", cnv=True)))
    assert ss.alarm_checks(run("warn", lay("ocrCheck", "skipped")))


def test_sweep_items(tmp_path: Path) -> None:
    rp = tmp_path / "report.json"
    rp.write_text(
        json.dumps({"layers": [{"name": "Detection Sweep", "detail": "3 possible items remain"}]})
    )
    assert ss.sweep_items(rp) == 3
    rp.write_text(json.dumps({"layers": [{"name": "Detection Sweep", "detail": "nothing found"}]}))
    assert ss.sweep_items(rp) == 0
    assert ss.sweep_items(tmp_path / "absent.json") is None


def test_wilson_bounds() -> None:
    assert ss.wilson(0, 0) is None
    bounds = ss.wilson(8, 8)
    assert bounds is not None
    lo, hi = bounds
    assert hi == 1.0 and 0.6 < lo < 0.7


def scored(row_id: str, cls: str, flagged: bool, overall: str, leak: str = "live", **kw) -> dict:
    return {
        "row_id": row_id,
        "class": cls,
        "variant": "v",
        "base_id": "b",
        "mode": "h",
        "leak": leak,
        "flagged": flagged,
        "overall": overall,
        **kw,
    }


def table(*cells: tuple[str, str, bool, str, bool]) -> dict:
    out = {}
    for row_id, cls, flagged, overall, known in cells:
        out[f"lh/{row_id}"] = {
            "class": cls,
            "variant": "v",
            "base": "b",
            "mode": "h",
            "leak": "live",
            "expect": {"flagged": flagged, "overall": overall, "headline": None, "tier": None},
            "known": known,
        }
    return {"schema": 1, "version": 1, "cells": out}


def readings(rows: list[dict], tbl: dict, prereg: list | None = None) -> tuple[str, dict]:
    verdict, cells = ss.gate(rows, tbl, prereg or [])
    return verdict, {c["cell"].removeprefix("lh/"): c["reading"] for c in cells}


def test_identical_is_green() -> None:
    v, r = readings([scored("a", "O-03", True, "fail")], table(("a", "O-03", True, "fail", False)))
    assert (v, r) == ("GREEN", {"a": "IDENTICAL"})


def test_a_lost_catch_is_red() -> None:
    v, r = readings([scored("a", "O-03", False, "pass")], table(("a", "O-03", True, "fail", False)))
    assert (v, r["a"]) == ("RED", "RED lost")


def test_a_control_that_flags_is_red() -> None:
    v, r = readings(
        [scored("c", "C-02", True, "attention")], table(("c", "C-02", False, "pass", False))
    )
    assert (v, r["c"]) == ("RED", "RED control")


def test_a_known_blind_spot_that_starts_flagging_needs_a_prereg() -> None:
    rows, tbl = [scored("k", "O-09", True, "fail")], table(("k", "O-09", False, "pass", True))
    assert readings(rows, tbl) == ("RED", {"k": "RED unexplained"})
    assert readings(rows, tbl, [("lh/k", {"flagged": True})]) == ("GREEN", {"k": "DELTA"})


def test_prereg_rebaselines_exactly_and_an_unmet_prereg_is_red() -> None:
    tbl = table(("x", "O-08", False, "warn", False))
    moved = [scored("x", "O-08", True, "fail")]
    assert readings(moved, tbl, [("lh/x", {"overall": "fail"})]) == ("GREEN", {"x": "REBASELINED"})
    assert readings(moved, tbl, [("lh/x", {"overall": "attention"})])[0] == "RED"
    still = [scored("x", "O-08", False, "warn")]
    assert readings(still, tbl, [("lh/x", {"overall": "fail"})]) == (
        "RED",
        {"x": "RED prereg unmet"},
    )


def test_flaky_missing_and_harness_red() -> None:
    tbl = table(("f", "O-03", True, "fail", False), ("m", "O-05", True, "fail", False))
    flaky = [scored("f", "O-03", True, "fail", overall_run2="pass")]
    assert readings(flaky, tbl)[1] == {"f": "FLAKY", "m": "RED missing"}
    dead = [scored("f", "O-03", True, "fail", leak="dead"), scored("m", "O-05", True, "fail")]
    assert readings(dead, tbl) == ("HARNESS RED", {"f": "HARNESS RED", "m": "IDENTICAL"})


def test_prereg_parsing(tmp_path: Path) -> None:
    p = tmp_path / "prereg.txt"
    p.write_text("# S2\nlh/O-08.* flagged=true overall=fail\n\n")
    assert ss.read_prereg(p) == [("lh/O-08.*", {"flagged": True, "overall": "fail"})]
    p.write_text("lh/x colour=red\n")
    with pytest.raises(SystemExit):
        ss.read_prereg(p)


def test_expected_table_marks_known_cells(tmp_path: Path) -> None:
    (tmp_path / "bases" / "b").mkdir(parents=True)
    (tmp_path / "bases" / "b" / "replay.json").write_text(json.dumps({"output_sha256": "ab"}))
    rows = [
        scored("k", "O-09", False, "pass"),
        {"row_id": "n", "class": "O-01", "state": "no-verdict"},
    ]
    t = ss.expected_table(rows, tmp_path, {"O-09/v"}, 2, "run-dir")
    assert t["version"] == 2 and t["baseline"]["base_outputs"] == {"b": "ab"}
    assert list(t["cells"]) == ["lh/k"] and t["cells"]["lh/k"]["known"] is True
