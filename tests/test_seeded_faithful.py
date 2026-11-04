"""The grammar-faithful plant mode and the side-effects column, on Resecta's own outputs.

The bases are the committed sample-statement outputs under `seeded/emit/`. A legacy
row must stay byte-identical to the published recipe; a faithful row changes only
what its class needs, and the side-effects column says which changes are which.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pymupdf
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import seeded_effects as fx
import seeded_plant as sp
import seeded_score as ss

ROOT = Path(__file__).resolve().parents[1]

EMIT = ROOT / "seeded" / "emit" / "bases"
SPECS = ROOT / "seeded" / "bases"
ROWS = {
    r["row_id"]: r for r in json.loads((ROOT / "seeded/expected/rows.json").read_text())["rows"]
}


def plant(base: str, cls: str, variant: str, mode: str, ni: int = 0) -> tuple[bytes, dict]:
    spec = json.loads((SPECS / base / "base.json").read_text())
    got = sp.plant_row(EMIT / base, spec, cls, variant, ni, mode, root=ROOT)
    assert got is not None, (base, cls, variant, mode)
    return got


def kinds(row: dict) -> dict[str, str]:
    return {e["effect"]: e["kind"] for e in row["side_effects"]}


def artefacts(row: dict) -> set[str]:
    return {e["effect"] for e in row["side_effects"] if e["kind"] == "artefact"}


@pytest.mark.parametrize(
    ("base", "cls", "variant"),
    [
        ("b01-statement-h", "O-01", "centre"),
        ("b01-statement-h", "O-09", "prior-revision"),
        ("b01-statement-h", "O-10", "actualtext"),
        ("b01-statement-s", "O-02", "invisible"),
        ("b01-statement-s", "O-08", "xmp-plain"),
        ("b01-statement-h", "C-02", "roundtrip"),
    ],
)
def test_legacy_rows_rebuild_the_published_bytes(base: str, cls: str, variant: str) -> None:
    _, row = plant(base, cls, variant, "legacy")
    rid = f"{cls}.{variant}.{base}.n0.{row['digest'][0]}"
    assert row["row_id"] == rid
    assert row["seeded_sha256"] == ROWS[rid]["seeded_sha256"]


def test_legacy_text_plant_carries_the_array_and_a_widthless_font() -> None:
    _, row = plant("b01-statement-h", "O-01", "centre", "legacy")
    assert {"contents_array", "font_added"} <= artefacts(row)


def test_faithful_text_plant_splices_into_the_writer_stream_with_its_font() -> None:
    data, row = plant("b01-statement-h", "O-01", "centre", "faithful")
    assert row["row_id"].endswith(".f") and row["plant_mode"] == "faithful"
    assert artefacts(row) == set()
    doc = pymupdf.open(stream=data, filetype="pdf")
    page = doc[0]
    assert doc.xref_get_key(page.xref, "Contents")[0] == "xref"
    assert [f[4] for f in page.get_fonts(full=True)] == ["TT1"]
    assert row["needle"]["text"] in page.get_text()


def test_faithful_secure_page_adds_a_font_with_widths_as_inherent() -> None:
    _, row = plant("b01-statement-s", "O-02", "invisible", "faithful")
    font = next(e for e in row["side_effects"] if e["effect"] == "font_added")
    assert font["kind"] == "inherent" and font["detail"]["widths"] is True
    assert "contents_array" not in kinds(row)
    _, legacy = plant("b01-statement-s", "O-02", "invisible", "legacy")
    lfont = next(e for e in legacy["side_effects"] if e["effect"] == "font_added")
    assert lfont["kind"] == "artefact" and lfont["detail"]["widths"] is False


def test_prior_revision_id_is_an_artefact_in_legacy_only() -> None:
    _, legacy = plant("b01-statement-h", "O-09", "prior-revision", "legacy")
    data, faithful = plant("b01-statement-h", "O-09", "prior-revision", "faithful")
    assert "id_not_content_derived" in artefacts(legacy)
    assert kinds(faithful).get("incremental_update") == "inherent"
    assert "id_not_content_derived" not in kinds(faithful)
    assert sp.id_matches(data) is True
    first = data[: data.index(b"%%EOF") + len(b"%%EOF")]
    assert faithful["needle"]["text"] in pymupdf.open(stream=first, filetype="pdf")[0].get_text()
    assert faithful["needle"]["text"] not in pymupdf.open(stream=data, filetype="pdf")[0].get_text()


def test_noop_splice_control_changes_nothing_in_faithful_mode() -> None:
    base = (EMIT / "b01-statement-h" / "output.pdf").read_bytes()
    data, faithful = plant("b01-statement-h", "C-04", "noop-splice", "faithful")
    _, legacy = plant("b01-statement-h", "C-04", "noop-splice", "legacy")
    assert faithful["side_effects"] == []
    assert "contents_array" in artefacts(legacy)
    a = pymupdf.open(stream=base, filetype="pdf")[0].get_text()
    assert pymupdf.open(stream=data, filetype="pdf")[0].get_text() == a


def test_reencode_control_keeps_the_writer_segments_only_in_faithful_mode() -> None:
    _, legacy = plant("b01-statement-h", "C-03", "reencode", "legacy")
    _, faithful = plant("b01-statement-h", "C-03", "reencode", "faithful")
    lj = next(e for e in legacy["side_effects"] if e["effect"] == "jpeg_reencoded")
    fj = next(e for e in faithful["side_effects"] if e["effect"] == "jpeg_reencoded")
    assert lj["kind"] == "artefact" and {"APP1", "APP13"} <= set(lj["detail"]["app_dropped"])
    assert fj["kind"] == "inherent"
    assert fj["detail"]["app_dropped"] == [] and not fj["detail"]["dri_dropped"]
    assert not fj["detail"]["qtables_changed"]
    assert fj["detail"]["blocks_changed"] < lj["detail"]["blocks_changed"]


def test_faithful_flate_image_keeps_one_stream() -> None:
    data, row = plant("b01-statement-h", "O-12", "flate-image", "faithful")
    assert "contents_array" not in kinds(row)
    page = pymupdf.open(stream=data, filetype="pdf")[0]
    assert len(page.get_images()) == 2


def test_effects_of_an_unchanged_file_are_empty() -> None:
    base = (EMIT / "b01-statement-h" / "output.pdf").read_bytes()
    assert fx.side_effects(base, base, "C-01", "twin", "h") == []


def test_fidelity_counts_artefact_only_catches() -> None:
    def r(rid: str, flagged: bool) -> dict:
        return {
            "row_id": rid,
            "class": "O-01",
            "variant": "centre",
            "leak": "live",
            "flagged": flagged,
            "overall": "fail" if flagged else "pass",
            "routes": {"T": flagged, "B": False, "V": False},
        }

    rows = [
        r("O-01.centre.b.n0.c", True),
        r("O-01.centre.b.n0.c.f", False),
        r("O-01.centre.b.n1.c", True),
        r("O-01.centre.b.n1.c.f", True),
    ]
    got = ss.fidelity(rows)["by_class_variant"]["O-01/centre"]
    assert (got["caught_legacy"], got["caught_faithful"], got["artefact_only"]) == (2, 1, 1)
