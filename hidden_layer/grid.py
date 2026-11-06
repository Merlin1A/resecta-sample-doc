"""The parameter grid: one ``DocSpec`` per document.

Axes:
- ``a1``: ground x drift along the line (0, 2, 5, 8, 15, 30 pt), 300 dpi, no degradation;
- ``a2``: resolution (150, 200, 300 dpi) x degradation (none, mild, rough), on the clean and the
  heavy-noise grounds, drift 30 pt (the two cells ``a1`` already holds are not repeated);
- ``a3``: layer shapes on the clean and heavy-noise grounds at 300 dpi: per-word jitter, vertical
  offsets, a misread surname (substituted or split) with and without drift, and a drift to the left.

The Vision-layer set is listed separately (``VISION``); its layer comes from recorded text
recognition output, not from these offsets.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from .pages import GROUNDS

LAYOUT_CYCLE = ("letter", "statement", "form")
DRIFTS_PT = (0, 2, 5, 8, 15, 30)
DPIS = (150, 200, 300)
DEGRADE_NAMES = ("none", "mild", "rough")
SHORT_GROUND = {
    "clean": "clean",
    "light-noise": "light",
    "heavy-noise": "heavy",
    "textured": "texture",
    "dark": "dark",
    "black-bar": "bar",
}


@dataclass(frozen=True)
class DocSpec:
    doc_id: str
    axis: str
    layout: str
    ground: str
    dpi: int
    degrade: str
    drift_cpt: int = 0
    jitter_cpt: int = 0
    vshift_cpt: int = 0
    misread: str | None = None
    layer: str = "placed"
    seed: int = 0
    purpose: str = ""

    def params(self) -> dict[str, object]:
        d = asdict(self)
        d.pop("doc_id")
        d.pop("purpose")
        return d


def _seed(i: int) -> int:
    return 1105 + i


def _shape_name(drift_cpt: int, jitter_cpt: int, vshift_cpt: int, misread: str | None) -> str:
    parts = [f"d{'m' if drift_cpt < 0 else ''}{abs(drift_cpt) // 100}"]
    if jitter_cpt:
        parts.append(f"j{jitter_cpt}")
    if vshift_cpt:
        parts.append(f"v{'m' if vshift_cpt < 0 else ''}{abs(vshift_cpt) // 100}")
    if misread:
        parts.append(f"misread-{misread}")
    return "-".join(parts)


def _spec(
    i: int,
    axis: str,
    ground: str,
    dpi: int,
    degrade: str,
    drift_cpt: int,
    purpose: str,
    jitter_cpt: int = 0,
    vshift_cpt: int = 0,
    misread: str | None = None,
) -> DocSpec:
    shape = _shape_name(drift_cpt, jitter_cpt, vshift_cpt, misread)
    doc_id = f"hl-{axis}-{SHORT_GROUND[ground]}-{dpi}-{degrade}-{shape}"
    layout = LAYOUT_CYCLE[i % len(LAYOUT_CYCLE)]
    return DocSpec(
        doc_id,
        axis,
        layout,
        ground,
        dpi,
        degrade,
        drift_cpt,
        jitter_cpt,
        vshift_cpt,
        misread,
        "placed",
        _seed(i),
        purpose,
    )


def placed_grid() -> list[DocSpec]:
    out: list[DocSpec] = []
    i = 0
    for ground in GROUNDS:
        for d in DRIFTS_PT:
            purpose = f"a {d} pt along-the-line drift of the whole layer on the {ground} ground"
            out.append(_spec(i, "a1", ground, 300, "none", d * 100, purpose))
            i += 1
    for ground in ("clean", "heavy-noise"):
        for dpi in DPIS:
            for degrade in DEGRADE_NAMES:
                if dpi == 300 and degrade == "none":
                    continue
                purpose = f"the 30 pt drift at {dpi} dpi with the {degrade} degradation on the {ground} ground"
                out.append(_spec(i, "a2", ground, dpi, degrade, 3000, purpose))
                i += 1
    # (drift, jitter, vertical shift, misread, purpose); centipoints.
    shapes: tuple[tuple[int, int, int, str | None, str], ...] = (
        (800, 150, 0, None, "an 8 pt drift with up to 1.5 pt of seeded per-word jitter in x and y"),
        (0, 0, 400, None, "the layer 4 pt above the ink, no drift along the line"),
        (1500, 0, -1200, None, "the layer 12 pt below the ink and 15 pt along the line"),
        (0, 0, 0, "substitute", "the surname's hidden copy misspelled, on its ink"),
        (800, 0, 0, "substitute", "the surname's hidden copy misspelled, 8 pt along the line"),
        (800, 0, 0, "split", "the surname's hidden copy split in two, 8 pt along the line"),
        (-3000, 0, 0, None, "a 30 pt drift to the left"),
    )
    for ground in ("clean", "heavy-noise"):
        for drift, jitter, vshift, misread, purpose in shapes:
            full = f"{purpose}, on the {ground} ground"
            out.append(_spec(i, "a3", ground, 300, "none", drift, full, jitter, vshift, misread))
            i += 1
    return out


VISION_DEGRADE = "mild"


def vision_grid(start: int) -> list[DocSpec]:
    """Six grounds x three resolutions with the mild degradation; the layer is Vision's reading."""
    out = []
    i = start
    for ground in GROUNDS:
        for dpi in DPIS:
            doc_id = f"hl-v-{SHORT_GROUND[ground]}-{dpi}-{VISION_DEGRADE}"
            purpose = f"a layer built from Apple Vision's words and boxes on the {ground} ground at {dpi} dpi"
            layout = LAYOUT_CYCLE[i % len(LAYOUT_CYCLE)]
            out.append(
                DocSpec(
                    doc_id,
                    "v",
                    layout,
                    ground,
                    dpi,
                    VISION_DEGRADE,
                    layer="vision",
                    seed=_seed(i),
                    purpose=purpose,
                )
            )
            i += 1
    return out


def all_specs() -> list[DocSpec]:
    placed = placed_grid()
    return placed + vision_grid(len(placed))
