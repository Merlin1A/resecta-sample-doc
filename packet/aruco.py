"""aruco.py -- the ArUco marker bit table, baked in so the build needs no OpenCV.

The capture packet's print masters carry four ArUco corner fiducials per page (D12-35). Drawing
them needs nothing but the marker's bit pattern; DETECTING them at registration time needs
OpenCV, but that runs in the planning estate over scanned images, not here. Baking the table
keeps this repo's declared dependencies unchanged -- cv2 is admitted tooling (D12-36), not a
build input -- and keeps the masters byte-deterministic.

The table is not hand-authored: it was extracted from
``cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)`` and :func:`verify_against_cv2`
re-derives it whenever OpenCV happens to be importable, so drift is caught rather than assumed
away. `packet/acceptance.py` calls that check.

DICTIONARY SIZE (amendment owed to RB12-08): D12-35 named `DICT_4X4_50`, but the capture packet
is 16 pages at 4 markers per page = 64 ids, and that dictionary holds 50. `DICT_4X4_100` is used
instead. It is a strict SUPERSET -- its ids 0..49 are bit-identical to DICT_4X4_50 (asserted in
verify_against_cv2) -- so the marker geometry, cell count and print size are unchanged and only
pages 13..16 use ids the smaller dictionary never had. The cost is inter-marker Hamming distance:
detection should be constrained to the ids a given page is expected to carry.

Bit order: the 4x4 data grid read row-major, most significant bit first, 1 = black cell. The
rendered marker is 6x6 -- the data grid inside a one-cell black quiet border.

Every character is printable ASCII.
"""

from __future__ import annotations

DICT_NAME = "DICT_4X4_100"
LEGACY_DICT_NAME = "DICT_4X4_50"
LEGACY_COUNT = 50
GRID = 4  # data cells per side
BORDER = 1  # quiet-border cells per side
SIDE_CELLS = GRID + 2 * BORDER  # 6

# Extracted from cv2.aruco DICT_4X4_100; re-derived by verify_against_cv2().
_BITS: tuple[int, ...] = (
    0x4ACD,
    0xF065,
    0xCCD2,
    0x66B9,
    0xAB61,
    0x8632,
    0x61D1,
    0x3B0D,
    0x0125,
    0x30A9,
    0x066E,
    0xEE58,
    0xF148,
    0xD5F0,
    0xDB4E,
    0xD9C1,
    0xB99A,
    0x99FF,
    0x93A1,
    0x8950,
    0x7974,
    0x4FD4,
    0x332A,
    0x227D,
    0x01B8,
    0x6B8E,
    0x531B,
    0x5AAB,
    0xDEDC,
    0xCB90,
    0xBBEA,
    0xA84D,
    0x6130,
    0x0F34,
    0xF751,
    0xF6D6,
    0xE78A,
    0xFB00,
    0xF209,
    0xE3A5,
    0xE8E7,
    0xD5D7,
    0xCD73,
    0xC74D,
    0xDB17,
    0xD114,
    0xD2C0,
    0xB49B,
    0xAFD1,
    0xAFEC,
    0xAE6B,
    0xAA97,
    0xA2BE,
    0xA068,
    0x97FE,
    0x9798,
    0x9EDB,
    0x9E16,
    0x94ED,
    0x901A,
    0x9820,
    0x81E4,
    0x7F5F,
    0x7CBB,
    0x745D,
    0x6C85,
    0x7B93,
    0x7AD5,
    0x7A63,
    0x6376,
    0x605E,
    0x4483,
    0x43FB,
    0x49A4,
    0x4037,
    0x4854,
    0x35E0,
    0x369D,
    0x26A7,
    0x2C2A,
    0x3367,
    0x385F,
    0x3AC8,
    0x16A2,
    0x06DA,
    0x0444,
    0x11D5,
    0x08B2,
    0xCA8A,
    0x7552,
    0x89E8,
    0xF530,
    0xF9B4,
    0xD23E,
    0xB627,
    0xBC0B,
    0xB0C9,
    0xB02C,
    0x961B,
    0x8F38,
)

COUNT = len(_BITS)


def marker_cells(marker_id: int) -> list[list[int]]:
    """Return the 6x6 cell grid for ``marker_id`` as rows of 0/1, 1 = black.

    Row 0 is the TOP row as the marker is meant to be read, matching how OpenCV
    renders it; the caller flips to PDF's bottom-left origin.
    """
    if not 0 <= marker_id < COUNT:
        raise ValueError(f"{DICT_NAME} holds ids 0..{COUNT - 1}, got {marker_id}")
    bits = _BITS[marker_id]
    rows = [[1] * SIDE_CELLS]
    for r in range(GRID):
        row = [1]
        for c in range(GRID):
            shift = (GRID * GRID - 1) - (r * GRID + c)
            row.append((bits >> shift) & 1)
        row.append(1)
        rows.append(row)
    rows.append([1] * SIDE_CELLS)
    return rows


def verify_against_cv2() -> str:
    """Re-derive the table from OpenCV and compare. Returns a human-readable verdict.

    Skips (rather than fails) when OpenCV is absent: it is admitted tooling, not a
    declared dependency of this repo.
    """
    try:
        import cv2  # optional tooling, imported only when checking
    except ImportError:
        return f"{DICT_NAME}: cv2 not importable; baked table not cross-checked"

    def cells_from(dictionary, marker_id):
        img = cv2.aruco.generateImageMarker(dictionary, marker_id, SIDE_CELLS)
        return [[1 if img[r][c] == 0 else 0 for c in range(SIDE_CELLS)] for r in range(SIDE_CELLS)]

    d = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_100)
    for marker_id in range(COUNT):
        if marker_cells(marker_id) != cells_from(d, marker_id):
            raise SystemExit(f"{DICT_NAME}: baked table disagrees with cv2 at id {marker_id}")

    # The superset claim the D12-35 amendment rests on: ids 0..49 must be unchanged.
    legacy = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    for marker_id in range(LEGACY_COUNT):
        if marker_cells(marker_id) != cells_from(legacy, marker_id):
            raise SystemExit(
                f"{DICT_NAME} id {marker_id} differs from {LEGACY_DICT_NAME}: "
                "the superset assumption behind the D12-35 amendment does not hold"
            )
    return (
        f"{DICT_NAME}: baked table matches cv2 for all {COUNT} ids; "
        f"ids 0..{LEGACY_COUNT - 1} identical to {LEGACY_DICT_NAME}"
    )


def main() -> None:
    print(verify_against_cv2())


if __name__ == "__main__":
    main()
