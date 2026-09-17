#!/usr/bin/env python3
"""register_capture.py -- P1.9 capture registration: fiducials -> homography -> ground truth on
every capture image (`31-` SSC.3 "Registration"; `[R06]` print-then-scan workflow; D12-35 marks).

Runs in the sd venv. opencv-python and pypdfium2 are ADMITTED TOOLING (D12-36), not declared
dependencies of this repo -- the script says so and stops if they are missing. Evidence (the
captures and every output of this tool) lives in the planning estate, never in a repo.

Per capture image:
  1. detect the ArUco fiducials (`DICT_4X4_100`, full-dictionary pass) and resolve the PAGE from the
     majority of `id // 4` (the D12-35 id rule; a filename ordinal is only ever a cross-check);
  2. re-detect with a SUB-DICTIONARY holding only that page's four ids (the `packet/aruco.py`
     Hamming-distance note: detection is constrained to the ids a page is expected to carry);
  3. pair the 16 detected corners with the master geometry from `capture-masters-2026-08-marks.json`
     (the sidecar exists so nothing is re-derived by eye) -> `cv2.findHomography` (RANSAC) ->
     reprojection RMS + max in the image's own pixels -> REJECT above `--max-error-px` (2.0, `[R06]`);
  4. `cv2.perspectiveTransform` every ground-truth box of that master page (as a 4-corner polygon)
     into the capture frame -> per-image GT JSON (every field kept, `carried_from` included; `bbox`
     re-expressed in the capture page, `polygon` added) + an overlay QA PNG;
  5. per leg (and per condition inside a leg): the accepted images become ONE image-only PDF in
     master-page order (JPEG streams pass through untouched -- the scanner-JPEG artifact model of
     `[R06]`; PNG pages are Flate, lossless), with a ground-truth sidecar in the packet-GT shape
     and a DRAFT manifest row for `build_documents_manifest.py` (step 4, the L-25 second half).

Subcommands:
  synthetic  rasterize the masters with pypdfium2 into `synth<dpi>` legs (P1.9 amendment 2: the
             tool is validated BEFORE any capture exists; the same rasters are the synthetic arm of
             the synthetic-vs-real gap).
  register   register every leg under a capture dir into an evidence run dir.

Examples (from the sd root):
  .venv/bin/python tools/register_capture.py synthetic --out-dir <run>/synthetic --dpi 150,300
  .venv/bin/python tools/register_capture.py register --capture-dir <run>/synthetic --out <run> --emit-pdf
  .venv/bin/python tools/register_capture.py register --capture-dir <estate>/evidence/capture/2026-08-26 \\
      --out <estate>/evidence/8bbf5c8c/capture/<stamp>-register --emit-pdf --derive-rot90 2,10

Every character is printable ASCII.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import platform
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from packet import aruco as A  # noqa: E402  (baked marker table -- the sub-dictionary distances)

TOOL = "resecta-sample-doc tools/register_capture.py"
TOOL_VERSION = "0.1.0"
MASTERS_PDF = "capture-masters-2026-08.pdf"
MASTERS_MARKS = "capture-masters-2026-08-marks.json"
MASTERS_GT = "capture-masters-2026-08-ground-truth.json"
MARKERS_PER_PAGE = 4
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp"}
PAGE_HINT_RE = re.compile(r"(?:^|[^0-9])p(\d{2})(?:[^0-9]|$)")

# Leg name -> the manifest's capture axis (K0..K4, `30-` row "Capture"), the nominal DPI (None =
# derive it from the homography) and the structural-feature tag the leg exercises.
LEGS: dict[str, dict[str, Any]] = {
    "scan150": {"kind": "K1", "dpi": 150, "features": ["F0"]},
    "scan300": {"kind": "K2", "dpi": 300, "features": ["F0"]},
    "photo": {"kind": "K3", "dpi": None, "features": ["F0"]},
    "rotated": {"kind": "K1", "dpi": 150, "features": ["F1"]},
    "generations": {"kind": "K1", "dpi": 150, "features": ["F0"]},
    "k1i": {"kind": "K1i", "dpi": None, "features": ["F0"]},
    "k2i": {"kind": "K2i", "dpi": None, "features": ["F0"]},
}
EXPECTATION_BGR = {
    "must_fire": (255, 0, 0),  # blue
    "should_fire": (255, 200, 0),  # cyan
    "watch": (0, 200, 255),  # yellow
    "must_not_fire": (0, 0, 255),  # red
}


# ---------------------------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------------------------
def sha256_path(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def need_cv2():
    try:
        import cv2  # optional tooling, imported only when checking
    except ImportError:
        sys.exit(
            "register_capture needs opencv-python in the sd venv (admitted tooling, D12-36): "
            ".venv/bin/pip install opencv-python"
        )
    if not hasattr(cv2, "aruco") or not hasattr(cv2.aruco, "ArucoDetector"):
        sys.exit("this cv2 build has no aruco module / ArucoDetector (need opencv >= 4.7)")
    return cv2


def need_pdfium():
    try:
        import pypdfium2 as pdfium
    except ImportError:
        sys.exit(
            "the synthetic subcommand needs pypdfium2 in the sd venv (admitted tooling, D12-36)"
        )
    return pdfium


def pkg_version(name: str) -> str | None:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version(name)
    except PackageNotFoundError:
        return None


def git_describe(repo: Path) -> str:
    try:
        sha = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "-C", str(repo), "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        return sha + (" (dirty)" if dirty else "")
    except Exception:  # provenance only
        return "unknown"


def leg_spec(leg: str) -> dict[str, Any]:
    """Leg name -> {kind, dpi, features, synthetic}. `synth<dpi>[-...]` legs are the pypdfium2 rasters."""
    if leg in LEGS:
        return {**LEGS[leg], "synthetic": False}
    m = re.match(r"synth(\d+)", leg)
    if m:
        dpi = int(m.group(1))
        kind = "K1" if dpi < 225 else "K2"
        feats = ["F1"] if "rot" in leg else ["F0"]
        return {"kind": kind, "dpi": dpi, "features": feats, "synthetic": True}
    return {"kind": None, "dpi": None, "features": ["F0"], "synthetic": False}


def page_hint(path: Path) -> int | None:
    """`p02` in a filename -> master page 1 (0-indexed). A cross-check only; never the decision."""
    m = PAGE_HINT_RE.search(path.stem)
    return int(m.group(1)) - 1 if m else None


# ---------------------------------------------------------------------------------------------
# the masters (sidecar + ground truth)
# ---------------------------------------------------------------------------------------------
class Masters:
    def __init__(self, sd_root: Path):
        self.root = sd_root
        self.pdf = sd_root / MASTERS_PDF
        self.marks_path = sd_root / MASTERS_MARKS
        self.gt_path = sd_root / MASTERS_GT
        for p in (self.pdf, self.marks_path, self.gt_path):
            if not p.is_file():
                sys.exit(f"missing master artifact: {p}")
        self.marks = json.loads(self.marks_path.read_text())
        self.gt = json.loads(self.gt_path.read_text())
        self.sha = {
            "pdf": sha256_path(self.pdf),
            "marks": sha256_path(self.marks_path),
            "ground_truth": sha256_path(self.gt_path),
        }
        if self.marks.get("sha256") != self.sha["pdf"]:
            sys.exit(
                f"marks sidecar names sha {self.marks.get('sha256')} but the PDF hashes "
                f"{self.sha['pdf']} -- regenerate with .venv/bin/python -m packet.build_capture"
            )
        self.page_count = int(self.gt["page_count"])
        self.page_w, self.page_h = (float(v) for v in self.gt["page_size_pt"])
        d = self.marks["dictionary"]
        if d["name"] != A.DICT_NAME or d["markers_per_page"] != MARKERS_PER_PAGE:
            sys.exit(f"unexpected dictionary block in the sidecar: {d}")
        self.markers_by_page = {
            int(p["page"]): {int(k): [float(v) for v in q] for k, q in p["markers"].items()}
            for p in self.marks["pages"]
        }
        self.page_meta = {}
        for imp in self.marks["imported_pages"]:
            self.page_meta[int(imp["master_page"])] = {
                "exhibit": imp["exhibit"],
                "class": "C1",
                "designed_doctype": None,
                "imported_from_packet_page": int(imp["packet_page"]),
            }
        for dr in self.marks["drawn_pages"]:
            self.page_meta[int(dr["master_page"])] = {
                "exhibit": dr["exhibit"],
                "class": dr["class"],
                "designed_doctype": dr["designed_doctype"],
                "imported_from_packet_page": None,
            }
        # rows WITH geometry transform; the frozen statement's `measured_pending` rows (page known,
        # bbox null) carry into the sidecar's `carried_stmt` block untouched, the packet's own shape.
        self.rows_by_page: dict[int, list[dict]] = {p: [] for p in range(self.page_count)}
        self.pending_by_page: dict[int, list[dict]] = {p: [] for p in range(self.page_count)}
        for row in self.gt["occurrences"] + self.gt["carried_packet"]:
            page = row.get("page")
            if page is None:
                continue
            if row.get("measured_pending") or row.get("bbox") is None:
                self.pending_by_page[int(page)].append(row)
                continue
            self.rows_by_page[int(page)].append(row)

    def marker_src_points(self, page: int, marker_id: int) -> list[tuple[float, float]]:
        """The marker's TL, TR, BR, BL in the master's TOP-LEFT point frame (x right, y down).

        `variants._draw_marker` puts the marker's top row at the top of the page, unmirrored, so the
        printed marker is cv2's canonical marker upright; cv2 returns corners TL, TR, BR, BL in the
        marker's OWN frame, which makes this pairing invariant to how the page was fed."""
        x0, y0, x1, y1 = self.markers_by_page[page][marker_id]
        h = self.page_h
        return [(x0, h - y1), (x1, h - y1), (x1, h - y0), (x0, h - y0)]

    def bbox_polygon_pt(self, bbox: list[float]) -> list[tuple[float, float]]:
        """Normalized bottom-left bbox -> 4-corner polygon in the top-left point frame
        (TL, TR, BR, BL of the box on the page)."""
        x0, y0, x1, y1 = bbox
        w, h = self.page_w, self.page_h
        return [
            (x0 * w, h - y1 * h),
            (x1 * w, h - y1 * h),
            (x1 * w, h - y0 * h),
            (x0 * w, h - y0 * h),
        ]


# ---------------------------------------------------------------------------------------------
# marker bits (for the sub-dictionary's safe error correction)
# ---------------------------------------------------------------------------------------------
def _marker_grid(marker_id: int) -> np.ndarray:
    cells = A.marker_cells(marker_id)
    return np.array(
        [[cells[r][c] for c in range(1, 1 + A.GRID)] for r in range(1, 1 + A.GRID)], np.uint8
    )


def min_hamming_distance(ids: list[int]) -> int:
    """Minimum Hamming distance between any two DIFFERENT markers over all four rotations."""
    grids = {i: _marker_grid(i) for i in ids}
    best = A.GRID * A.GRID
    for a in ids:
        for b in ids:
            if a == b:
                continue
            for k in range(4):
                d = int(np.count_nonzero(grids[a] != np.rot90(grids[b], k)))
                best = min(best, d)
    return best


# ---------------------------------------------------------------------------------------------
# detection + registration
# ---------------------------------------------------------------------------------------------
def make_params(
    cv2, refine: str, *, error_correction_rate: float | None, min_perimeter_rate: float
):
    p = cv2.aruco.DetectorParameters()
    p.cornerRefinementMethod = {
        "none": cv2.aruco.CORNER_REFINE_NONE,
        "subpix": cv2.aruco.CORNER_REFINE_SUBPIX,
        "contour": cv2.aruco.CORNER_REFINE_CONTOUR,
        "apriltag": cv2.aruco.CORNER_REFINE_APRILTAG,
    }[refine]
    p.minMarkerPerimeterRate = min_perimeter_rate
    if error_correction_rate is not None:
        p.errorCorrectionRate = error_correction_rate
    return p


def detect(cv2, gray: np.ndarray, dictionary, params) -> tuple[dict[int, list[np.ndarray]], int]:
    """-> ({id: [corners(4,2), ...]}, rejected_candidates). Every candidate per id is kept."""
    det = cv2.aruco.ArucoDetector(dictionary, params)
    corners, ids, rejected = det.detectMarkers(gray)
    found: dict[int, list[np.ndarray]] = {}
    if ids is not None:
        for c, i in zip(corners, ids.ravel().tolist(), strict=True):
            found.setdefault(int(i), []).append(c.reshape(4, 2).astype(np.float64))
    return found, (0 if rejected is None else len(rejected))


def _perimeter(quad: np.ndarray) -> float:
    return float(sum(np.linalg.norm(quad[(k + 1) % 4] - quad[k]) for k in range(4)))


def choose_candidates(
    found: dict[int, list[np.ndarray]],
) -> tuple[dict[int, np.ndarray], list[int]]:
    """One quad per id. Duplicates (two candidates decoding to the same id) are resolved toward the
    perimeter the OTHER markers agree on; the ids that needed it are reported."""
    singles = {i: q[0] for i, q in found.items() if len(q) == 1}
    dups = [i for i, q in found.items() if len(q) > 1]
    chosen = dict(singles)
    ref = float(np.median([_perimeter(q) for q in singles.values()])) if singles else None
    for i in dups:
        cands = found[i]
        if ref is None:
            chosen[i] = cands[0]
        else:
            chosen[i] = min(cands, key=lambda q: abs(_perimeter(q) - ref))
    return chosen, sorted(dups)


def register_image(  # noqa: PLR0911 -- each early return is a distinct registration verdict
    cv2,
    masters: Masters,
    gray: np.ndarray,
    *,
    refine: str = "subpix",
    max_error_px: float = 2.0,
    max_corner_error_px: float = 3.0,
    min_markers: int = 4,
    ransac_px: float = 3.0,
    max_correction_cap: int = 2,
    min_perimeter_rate: float = 0.01,
    restrict: bool = True,
) -> dict:
    """Detect -> resolve page -> restricted re-detect -> homography -> errors. Pure function of the
    pixels; never reads a filename. Two gates: RMS over all corners (`[R06]`'s 2 px) AND the worst
    single corner (default 1.5x the RMS gate) -- an RMS-only gate lets one damaged fiducial through
    (a left border shaved by 1 pt measured RMS 1.97 / worst corner 3.95 px at 300 DPI)."""
    H_img, W_img = gray.shape[:2]
    out: dict = {
        "width_px": int(W_img),
        "height_px": int(H_img),
        "accepted": False,
        "reason": None,
        "refine": refine,
        "max_error_px": max_error_px,
        "max_corner_error_px": max_corner_error_px,
        "min_markers": min_markers,
        "ransac_px": ransac_px,
    }
    full = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_100)
    found_full, rejected_full = detect(
        cv2,
        gray,
        full,
        make_params(cv2, refine, error_correction_rate=None, min_perimeter_rate=min_perimeter_rate),
    )
    out["full_pass"] = {"ids": sorted(found_full), "rejected_candidates": rejected_full}
    if not found_full:
        out["reason"] = "no fiducials detected (full-dictionary pass)"
        return out
    votes = Counter(i // MARKERS_PER_PAGE for i in found_full)
    page, _n_votes = votes.most_common(1)[0]
    out["page"] = int(page)
    out["page_votes"] = {str(k): v for k, v in sorted(votes.items())}
    out["page_ambiguous"] = len(votes) > 1
    if page >= masters.page_count:
        out["reason"] = f"majority page {page} is beyond the {masters.page_count}-page master"
        return out
    expected = [MARKERS_PER_PAGE * page + k for k in range(MARKERS_PER_PAGE)]

    found = {i: q for i, q in found_full.items() if i in expected}
    if restrict:
        dmin = min_hamming_distance(expected)
        maxcorr = min(max_correction_cap, (dmin - 1) // 2)
        sub = cv2.aruco.Dictionary(
            full.bytesList[expected[0] : expected[-1] + 1].copy(), full.markerSize, maxcorr
        )
        found_sub, rejected_sub = detect(
            cv2,
            gray,
            sub,
            make_params(
                cv2, refine, error_correction_rate=1.0, min_perimeter_rate=min_perimeter_rate
            ),
        )
        found_sub = {expected[0] + k: q for k, q in found_sub.items()}
        out["restricted_pass"] = {
            "ids": sorted(found_sub),
            "rejected_candidates": rejected_sub,
            "min_hamming_distance": dmin,
            "max_correction_bits": maxcorr,
            "error_correction_rate": 1.0,
        }
        merged = {i: list(q) for i, q in found_sub.items()}
        for i, q in found.items():  # full-pass corners fill any id the restricted pass lost
            merged.setdefault(i, list(q))
        found = merged
    else:
        found = {i: list(q) for i, q in found.items()}
    chosen, dups = choose_candidates(found)
    out["markers"] = {str(i): chosen[i].round(3).tolist() for i in sorted(chosen)}
    out["markers_detected"] = len(chosen)
    out["duplicate_ids"] = dups
    if len(chosen) < min_markers:
        out["reason"] = (
            f"{len(chosen)}/{MARKERS_PER_PAGE} fiducials of page {page} detected (< {min_markers})"
        )
        return out

    src, dst = [], []
    for mid in sorted(chosen):
        src.extend(masters.marker_src_points(page, mid))
        dst.extend(chosen[mid].tolist())
    src_a = np.array(src, np.float64).reshape(-1, 1, 2)
    dst_a = np.array(dst, np.float64).reshape(-1, 1, 2)
    H, mask = cv2.findHomography(src_a, dst_a, cv2.RANSAC, ransac_px)
    if H is None:
        out["reason"] = "findHomography failed"
        return out
    proj = cv2.perspectiveTransform(src_a, H).reshape(-1, 2)
    resid = np.linalg.norm(proj - dst_a.reshape(-1, 2), axis=1)
    rms = float(math.sqrt(float(np.mean(resid**2))))
    out["homography"] = H.tolist()
    out["homography_frame"] = "master top-left points (x right, y down) -> image pixels"
    out["homography_error_px"] = round(rms, 4)
    out["homography_error_mean_px"] = round(float(resid.mean()), 4)
    out["homography_error_max_px"] = round(float(resid.max()), 4)
    out["ransac_inliers"] = int(mask.sum()) if mask is not None else None
    out["corner_count"] = len(resid)
    out["reprojected_corners"] = {
        str(mid): proj[4 * k : 4 * k + 4].round(3).tolist() for k, mid in enumerate(sorted(chosen))
    }

    # scale, rotation, mirroring from the homography over the marker band's outer corners
    def T(x, y_pdf):
        p = np.array([[[x, masters.page_h - y_pdf]]], np.float64)
        return cv2.perspectiveTransform(p, H).reshape(2)

    e = 18.0
    bl, br = T(e, e), T(masters.page_w - e, e)
    tr, tl = T(masters.page_w - e, masters.page_h - e), T(e, masters.page_h - e)
    span_w_in = (masters.page_w - 2 * e) / 72.0
    span_h_in = (masters.page_h - 2 * e) / 72.0
    dpi_x = (np.linalg.norm(br - bl) + np.linalg.norm(tr - tl)) / 2 / span_w_in
    dpi_y = (np.linalg.norm(tl - bl) + np.linalg.norm(tr - br)) / 2 / span_h_in
    out["dpi_effective"] = round(float((dpi_x + dpi_y) / 2), 2)
    out["dpi_effective_xy"] = [round(float(dpi_x), 2), round(float(dpi_y), 2)]
    v = tr - tl  # the page's top edge, left -> right, in image pixels
    angle = math.degrees(math.atan2(float(v[1]), float(v[0])))
    out["rotation_deg"] = round(angle, 2)
    out["rotation_quadrant"] = round(angle / 90.0) % 4 * 90
    lin = np.array(H[:2, :2], np.float64)
    out["mirrored"] = bool(np.linalg.det(lin) < 0)
    out["error_px_at300"] = (
        round(rms * 300.0 / out["dpi_effective"], 4) if out["dpi_effective"] else None
    )
    if rms > max_error_px:
        out["reason"] = f"reprojection RMS {rms:.3f} px > {max_error_px} px"
        return out
    if float(resid.max()) > max_corner_error_px:
        out["reason"] = (
            f"worst corner {float(resid.max()):.3f} px > {max_corner_error_px} px "
            f"(RMS {rms:.3f} passed -- one fiducial is damaged or mis-localized)"
        )
        return out
    out["accepted"] = True
    return out


def transform_rows(
    cv2, masters: Masters, page: int, H: np.ndarray, W: int, Hpx: int
) -> tuple[list[dict], int]:
    """Every GT row of `page` mapped into the capture frame. Returns (rows, out_of_frame_count)."""
    rows = json.loads(json.dumps(masters.rows_by_page[page]))  # deep copy; never mutate the masters
    H_arr = np.array(H, np.float64)
    out_of_frame = 0

    def project(bbox):
        poly = np.array(masters.bbox_polygon_pt(bbox), np.float64).reshape(-1, 1, 2)
        img = cv2.perspectiveTransform(poly, H_arr).reshape(-1, 2)
        norm = [[float(x) / W, 1.0 - float(y) / Hpx] for x, y in img]  # bottom-left normalized
        xs = [p[0] for p in norm]
        ys = [p[1] for p in norm]
        hull = [min(xs), min(ys), max(xs), max(ys)]
        inside = all(-0.0001 <= v <= 1.0001 for v in hull)
        clamped = [min(1.0, max(0.0, v)) for v in hull]
        return (
            [[round(x, 6), round(y, 6)] for x, y in norm],
            [round(v, 6) for v in clamped],
            inside,
            [round(x, 3) for x in img.reshape(-1).tolist()],
        )

    for r in rows:
        r["master_page"] = page
        r["master_bbox"] = r["bbox"]
        poly, hull, inside, px = project(r["bbox"])
        r["polygon"] = poly
        r["polygon_px"] = px
        r["bbox"] = hull
        if not inside:
            out_of_frame += 1
            r["out_of_frame"] = True
        for s in r.get("spans") or []:
            s["master_page"] = s.get("page", page)
            s["master_bbox"] = s["bbox"]
            sp, sh, s_in, _ = project(s["bbox"])
            s["polygon"] = sp
            s["bbox"] = sh
            if not s_in:
                s["out_of_frame"] = True
    return rows, out_of_frame


def draw_overlay(
    cv2, gray: np.ndarray, reg: dict, rows: list[dict], label: str, max_px: int
) -> np.ndarray:
    Hpx, W = gray.shape[:2]
    scale = min(1.0, max_px / float(max(W, Hpx)))
    bgr = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    if scale < 1.0:
        bgr = cv2.resize(bgr, (round(W * scale), round(Hpx * scale)), interpolation=cv2.INTER_AREA)
    t = max(1, round(bgr.shape[1] / 900.0))

    def pts(seq):
        return np.array([[round(x * scale), round(y * scale)] for x, y in seq], np.int32).reshape(
            -1, 1, 2
        )

    for r in rows:
        expectation = r.get("expectation")
        color = (
            EXPECTATION_BGR.get(expectation, (128, 128, 128))
            if isinstance(expectation, str)
            else (128, 128, 128)
        )
        poly = np.array(r["polygon_px"], np.float64).reshape(-1, 2)
        cv2.polylines(bgr, [pts(poly)], True, color, t)
    for mid, quad in reg.get("markers", {}).items():
        cv2.polylines(bgr, [pts(quad)], True, (0, 200, 0), t + 1)
        x, y = quad[0]
        cv2.putText(
            bgr,
            mid,
            (int(x * scale) + 3, int(y * scale) - 3),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5 * max(1, t),
            (0, 200, 0),
            t,
        )
    for _mid, quad in reg.get("reprojected_corners", {}).items():
        for x, y in quad:
            cv2.circle(bgr, (round(x * scale), round(y * scale)), 2 * t + 1, (0, 0, 255), -1)
    cv2.rectangle(bgr, (0, 0), (bgr.shape[1], 22 * t + 10), (255, 255, 255), -1)
    cv2.putText(
        bgr, label, (6, 18 * t + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.6 * max(1, t), (0, 0, 0), t
    )
    return bgr


# ---------------------------------------------------------------------------------------------
# image loading (EXIF orientation is applied ONCE, by re-encoding, so the pixels the detector sees
# are the pixels the PDF embeds)
# ---------------------------------------------------------------------------------------------
def load_image(cv2, path: Path, stage_dir: Path) -> tuple[np.ndarray, Path, dict]:
    from PIL import Image, ImageOps

    meta: dict[str, Any] = {
        "source": str(path),
        "source_sha256": sha256_path(path),
        "exif_orientation": None,
        "re_encoded": False,
    }
    embed = path
    if path.suffix.lower() in {".jpg", ".jpeg"}:
        with Image.open(path) as im:
            orientation = im.getexif().get(0x0112)
            meta["exif_orientation"] = int(orientation) if orientation is not None else None
            if orientation not in (None, 1):
                upright = ImageOps.exif_transpose(im)
                stage_dir.mkdir(parents=True, exist_ok=True)
                embed = stage_dir / f"{path.stem}.upright.jpg"
                upright.save(embed, format="JPEG", quality=95, subsampling=0)
                meta["re_encoded"] = True
                meta["re_encode_note"] = "EXIF orientation applied by re-encoding (quality 95)"
    flags = cv2.IMREAD_GRAYSCALE | cv2.IMREAD_IGNORE_ORIENTATION
    gray = cv2.imread(str(embed), flags)
    if gray is None:
        sys.exit(
            f"cannot read image {embed} (HEIC? set the iPhone to Most Compatible, or convert first)"
        )
    meta["image"] = str(embed)
    meta["image_sha256"] = meta["source_sha256"] if embed == path else sha256_path(embed)
    meta["format"] = (
        "jpeg" if embed.suffix.lower() in {".jpg", ".jpeg"} else embed.suffix.lower().lstrip(".")
    )
    return gray, embed, meta


# ---------------------------------------------------------------------------------------------
# leg assembly: one image-only PDF per (leg, condition) + a ground-truth sidecar + a manifest draft
# ---------------------------------------------------------------------------------------------
def assemble_pdf(pages: list[dict], title: str, doc_id: bytes) -> bytes:
    """`pages`: [{image, width_px, height_px, dpi_x, dpi_y}] in order. JPEG streams pass through
    untouched (reportlab DCTDecode); anything else is Flate via PIL. Deterministic: rl invariant +
    the `variants._finalize` pinned metadata / document ID."""
    from reportlab import rl_config

    rl_config.invariant = 1  # must precede save; fixes dates + font subset tags
    from reportlab.pdfgen import canvas

    from packet.variants import _finalize

    buf = io.BytesIO()
    first = pages[0]
    c = canvas.Canvas(
        buf, pagesize=(first["page_w_pt"], first["page_h_pt"]), invariant=1, pageCompression=1
    )
    for p in pages:
        c.setPageSize((p["page_w_pt"], p["page_h_pt"]))
        c.drawImage(
            p["image"],
            0,
            0,
            width=p["page_w_pt"],
            height=p["page_h_pt"],
            preserveAspectRatio=False,
            mask=None,
        )
        c.showPage()
    c.save()
    return _finalize(buf.getvalue(), title, doc_id)


def condition_of(
    leg: str, reg: dict, path: Path, k: int, group_size: int, photo_order: list[str]
) -> str | None:
    stem = path.stem.lower()
    if leg == "photo":
        if group_size == len(photo_order):
            return photo_order[k]
        return f"cond{k + 1}"
    if leg == "rotated":
        m = re.search(r"rot(\d+)", stem)
        return f"rot{int(m.group(1))}" if m else f"rot{reg.get('rotation_quadrant', 0)}"
    if leg == "generations":
        m = re.search(r"(?:^|[^a-z])g(?:en)?(\d)(?:[^0-9]|$)", stem)
        return f"gen{m.group(1)}" if m else "gen?"
    return None


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="ascii")


def cmd_register(args) -> int:
    cv2 = need_cv2()
    masters = Masters(Path(args.sd_root).expanduser())
    capture_dir = Path(args.capture_dir).expanduser()
    out = Path(args.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    stamp = args.stamp or capture_dir.name
    photo_order = [s.strip() for s in args.photo_order.split(",") if s.strip()]
    legs = (
        args.legs.split(",")
        if args.legs
        else sorted(
            d.name
            for d in capture_dir.iterdir()
            if d.is_dir()
            and any(f.suffix.lower() in IMAGE_EXTS for f in d.iterdir() if f.is_file())
        )
    )
    if not legs:
        sys.exit(f"no legs (subdirectories with images) under {capture_dir}")
    derive_pages = (
        [int(s) - 1 for s in args.derive_rot90.split(",") if s.strip()] if args.derive_rot90 else []
    )
    derive_source = args.derive_source
    if derive_pages and derive_source not in legs:
        sys.exit(f"--derive-rot90 needs the source leg {derive_source!r} under {capture_dir}")
    # the source of derived rotations registers before `rotated`
    legs = [x for x in legs if x != "rotated"] + (
        ["rotated"] if "rotated" in legs or derive_pages else []
    )

    reg_params = {
        "refine": args.refine,
        "max_error_px": args.max_error_px,
        "max_corner_error_px": args.max_corner_error_px,
        "min_markers": args.min_markers,
        "ransac_px": args.ransac_px,
        "max_correction_cap": args.max_correction_bits,
        "min_perimeter_rate": args.min_perimeter_rate,
        "restrict": not args.no_restrict,
    }
    index: dict[str, Any] = {
        "tool": TOOL,
        "version": TOOL_VERSION,
        "sd_sha": git_describe(REPO),
        "masters": {"pdf": str(masters.pdf), **masters.sha, "page_count": masters.page_count},
        "capture_dir": str(capture_dir),
        "stamp": stamp,
        "params": reg_params,
        "photo_order": photo_order,
        "legs": {},
    }
    manifest_rows = []
    summary_lines = []
    page_images: dict[str, dict[int, list[dict]]] = {}

    for leg in legs:
        leg_dir = capture_dir / leg
        spec = leg_spec(leg)
        if derive_pages and leg == "rotated":
            leg_dir.mkdir(parents=True, exist_ok=True)
            src_rows = page_images.get(derive_source, {})
            for p in derive_pages:
                srcs = [r for r in src_rows.get(p, []) if r["accepted"]]
                if not srcs:
                    print(
                        f"  ! derive-rot90: page {p + 1:02d} has no accepted {derive_source} image; skipped"
                    )
                    continue
                src = srcs[0]
                arr = cv2.imread(src["image"], cv2.IMREAD_GRAYSCALE | cv2.IMREAD_IGNORE_ORIENTATION)
                rot = np.ascontiguousarray(np.rot90(arr, 1))  # 90 deg counter-clockwise, lossless
                dst = leg_dir / f"derived-rot90-p{p + 1:02d}.png"
                cv2.imwrite(str(dst), rot)
                write_json(
                    leg_dir / f"derived-rot90-p{p + 1:02d}.provenance.json",
                    {
                        "derived_from": src["image"],
                        "source_sha256": src["image_sha256"],
                        "transform": "numpy.rot90(k=1): lossless 90 deg counter-clockwise rotation of the decoded pixels",
                        "why": "90-degree feeds are physically impossible on letter-width hardware (IM-30 adaptation, "
                        "pre-cleared 2026-08-25); derived from the 150 DPI scan leg",
                        "saved_as": "PNG (lossless)",
                    },
                )
                print(f"  derived {dst.name} from {Path(src['image']).name}")
        files = sorted(
            f for f in leg_dir.iterdir() if f.is_file() and f.suffix.lower() in IMAGE_EXTS
        )
        if not files:
            print(f"[{leg}] no images; skipped")
            continue
        print(f"[{leg}] {len(files)} images  kind={spec['kind']} nominal_dpi={spec['dpi']}")
        leg_out = out / leg
        leg_out.mkdir(parents=True, exist_ok=True)
        rows_out = []
        by_page: dict[int, list[dict]] = {}
        for f in files:
            gray, embed, meta = load_image(cv2, f, leg_out / "staged")
            reg = register_image(cv2, masters, gray, **reg_params)
            reg.update(meta)
            reg["file"] = f.name
            hint = page_hint(f)
            reg["page_hint"] = hint
            reg["page_hint_agrees"] = (
                None if hint is None or reg.get("page") is None else hint == reg["page"]
            )
            if reg["page_hint_agrees"] is False:
                if hint is None:  # page_hint_agrees is False only when hint was set (line 779)
                    raise AssertionError("page_hint_agrees False implies hint is not None")
                print(
                    f"  ! {f.name}: filename says page {hint + 1:02d}, fiducials say {reg['page'] + 1:02d} "
                    f"(fiducials win)"
                )
            if reg["accepted"]:
                page = reg["page"]
                gt_rows, oof = transform_rows(
                    cv2, masters, page, reg["homography"], reg["width_px"], reg["height_px"]
                )
                pending = json.loads(json.dumps(masters.pending_by_page[page]))
                for row in pending:
                    row["master_page"] = page
                reg["gt_rows"] = len(gt_rows)
                reg["gt_pending_rows"] = len(pending)
                reg["gt_out_of_frame"] = oof
                tag = f"p{page + 1:02d}-{f.stem}"
                gt_path = leg_out / f"{tag}.gt.json"
                write_json(
                    gt_path,
                    {
                        "schema_version": 1,
                        "tool": TOOL,
                        "version": TOOL_VERSION,
                        "leg": leg,
                        "image": str(embed),
                        "image_sha256": reg["image_sha256"],
                        "master_page": page,
                        "registration": {
                            k: reg[k]
                            for k in (
                                "homography",
                                "homography_frame",
                                "homography_error_px",
                                "homography_error_max_px",
                                "dpi_effective",
                                "rotation_deg",
                                "mirrored",
                                "markers_detected",
                                "corner_count",
                                "ransac_inliers",
                            )
                        },
                        "bbox_origin": "bottom-left",
                        "occurrences": gt_rows,
                        "carried_stmt": pending,
                    },
                )
                reg["gt_json"] = str(gt_path)
                label = (
                    f"{leg} {f.name} -> master p{page + 1:02d} rms {reg['homography_error_px']:.2f} px "
                    f"max {reg['homography_error_max_px']:.2f} px dpi~{reg['dpi_effective']:.0f} "
                    f"rot {reg['rotation_deg']:.1f}"
                )
                ov = draw_overlay(cv2, gray, reg, gt_rows, label, args.overlay_max_px)
                ov_path = leg_out / f"{tag}.overlay.png"
                cv2.imwrite(str(ov_path), ov)
                reg["overlay_png"] = str(ov_path)
                reg["_gt_rows_data"] = gt_rows
                reg["_gt_pending_data"] = pending
                by_page.setdefault(page, []).append(reg)
                print(
                    f"  {f.name}: page {page + 1:02d}  markers {reg['markers_detected']}/4  "
                    f"rms {reg['homography_error_px']:.3f}  max {reg['homography_error_max_px']:.3f}  "
                    f"(@300 {reg['error_px_at300']:.3f})  dpi {reg['dpi_effective']:.1f}  "
                    f"rot {reg['rotation_deg']:.1f}  GT {len(gt_rows)}"
                    + (f" (+{len(pending)} pending)" if pending else "")
                    + (f"  OUT-OF-FRAME {oof}" if oof else "")
                )
            else:
                print(f"  ! {f.name}: REJECTED -- {reg['reason']}")
            rows_out.append(reg)
        page_images[leg] = by_page

        # conditions (photos: capture order within a page; rotated: the rotation; generations: g1/g2)
        for page, regs in by_page.items():
            regs.sort(key=lambda r: r["file"])
            for k, r in enumerate(regs):
                r["condition"] = condition_of(leg, r, Path(r["file"]), k, len(regs), photo_order)
                if leg == "photo" and len(regs) != len(photo_order):
                    print(
                        f"  ! photo page {page + 1:02d} has {len(regs)} shots, expected "
                        f"{len(photo_order)} ({','.join(photo_order)}); labeled cond1.."
                    )

        leg_summary = {
            "kind": spec["kind"],
            "nominal_dpi": spec["dpi"],
            "features": spec["features"],
            "synthetic": spec["synthetic"],
            "images": len(rows_out),
            "accepted": sum(1 for r in rows_out if r["accepted"]),
            "rejected": [
                r["file"] + ": " + str(r["reason"]) for r in rows_out if not r["accepted"]
            ],
            "pages_covered": sorted(int(p) + 1 for p in by_page),
            "rows": [{k: v for k, v in r.items() if not k.startswith("_gt_")} for r in rows_out],
            "documents": [],
        }

        if args.emit_pdf and by_page:
            conds: dict[str | None, list[dict]] = {}
            for page in sorted(by_page):
                for r in by_page[page]:
                    conds.setdefault(r["condition"], []).append(r)
            for cond, regs in conds.items():
                regs.sort(key=lambda r: (r["page"], r["file"]))
                name = leg + (f"-{cond}" if cond else "")
                pages_spec, gt_rows_all, pending_all, page_table = [], [], [], []
                for idx, r in enumerate(regs):
                    dpi_nom = spec["dpi"]
                    dpi_x = dpi_y = (
                        float(dpi_nom) if (dpi_nom and args.pdf_dpi == "nominal") else None
                    )
                    if dpi_x is None:
                        dpi_x, dpi_y = (float(v) for v in r["dpi_effective_xy"])
                    if (
                        dpi_x is None or dpi_y is None
                    ):  # unreachable: the branch above always sets both
                        raise AssertionError("dpi_x/dpi_y must be resolved by this point")
                    page_w_pt = r["width_px"] * 72.0 / dpi_x
                    page_h_pt = r["height_px"] * 72.0 / dpi_y
                    pages_spec.append(
                        {"image": r["image"], "page_w_pt": page_w_pt, "page_h_pt": page_h_pt}
                    )
                    meta = masters.page_meta[r["page"]]
                    page_table.append(
                        {
                            "page": idx,
                            "master_page": r["page"],
                            "exhibit": meta["exhibit"],
                            "class": meta["class"],
                            "designed_doctype": meta["designed_doctype"],
                            "imported_from_packet_page": meta["imported_from_packet_page"],
                            "image": r["image"],
                            "image_sha256": r["image_sha256"],
                            "width_px": r["width_px"],
                            "height_px": r["height_px"],
                            "page_size_pt": [round(page_w_pt, 3), round(page_h_pt, 3)],
                            "page_dpi": [round(dpi_x, 3), round(dpi_y, 3)],
                            "dpi_effective": r["dpi_effective"],
                            "rotation_deg": r["rotation_deg"],
                            "homography": r["homography"],
                            "homography_error_px": r["homography_error_px"],
                            "homography_error_max_px": r["homography_error_max_px"],
                            "error_px_at300": r["error_px_at300"],
                            "markers_detected": r["markers_detected"],
                            "condition": cond,
                        }
                    )
                    for row in json.loads(json.dumps(r["_gt_rows_data"])):
                        row["page"] = idx
                        for s in row.get("spans") or []:
                            s["page"] = idx
                        gt_rows_all.append(row)
                    for row in json.loads(json.dumps(r["_gt_pending_data"])):
                        row["page"] = idx
                        for s in row.get("spans") or []:
                            s["page"] = idx
                        pending_all.append(row)
                title = (
                    f"{masters.gt['set_id']} capture {stamp} {name} ({spec['kind'] or 'capture'})"
                )
                doc_id = f"RCap{stamp}{name}".encode("ascii", "replace")[:24]
                pdf = assemble_pdf(pages_spec, title, doc_id)
                pdf_path = out / f"{name}.pdf"
                pdf_path.write_bytes(pdf)
                sizes = {tuple(p["page_size_pt"]) for p in page_table}
                sidecar = {
                    "schema_version": 1,
                    "packet": masters.gt["packet"],
                    "generator": TOOL,
                    "set_id": masters.gt["set_id"],
                    "document": pdf_path.name,
                    "sha256": sha256_bytes(pdf),
                    "masters": {"document": MASTERS_PDF, **masters.sha},
                    "capture": {
                        "leg": leg,
                        "condition": cond,
                        "kind": spec["kind"],
                        "stamp": stamp,
                        "nominal_dpi": spec["dpi"],
                        "synthetic": spec["synthetic"],
                        "features": spec["features"],
                        "page_dpi_rule": args.pdf_dpi,
                        "registration": {"tool": TOOL, "version": TOOL_VERSION, **reg_params},
                        "pages": page_table,
                    },
                    "page_count": len(page_table),
                    "bbox_origin": "bottom-left",
                    "page_size_pt": list(sizes.pop()) if len(sizes) == 1 else None,
                    "imported": [
                        {
                            "page": p["page"],
                            "master_page": p["master_page"],
                            "exhibit": p["exhibit"],
                            "packet_page": p["imported_from_packet_page"],
                        }
                        for p in page_table
                        if p["imported_from_packet_page"] is not None
                    ],
                    "exhibits": [
                        {
                            "name": p["exhibit"],
                            "base_page": p["page"],
                            "pages": 1,
                            "class": p["class"],
                            "designed_doctype": p["designed_doctype"],
                            "master_page": p["master_page"],
                        }
                        for p in page_table
                        if p["imported_from_packet_page"] is None
                    ],
                    "occurrences": gt_rows_all,
                    "carried_stmt": pending_all,
                    "notes": (
                        "Ground truth of the capture masters carried through the fiducial homography "
                        "(bbox = axis-aligned hull of `polygon` in the capture page, normalized, "
                        "bottom-left origin; `master_bbox` = the master's own box; carried packet rows "
                        "keep `carried_from`). `page` indexes THIS document; `master_page` the master. "
                        "`carried_stmt` = the frozen statement's measured_pending rows (page known, no "
                        "geometry), untouched, as in the packet's own ground truth."
                    ),
                }
                gt_path = out / f"{name}-ground-truth.json"
                write_json(gt_path, sidecar)
                problems = []
                try:
                    from packet import schema as _schema

                    problems = _schema.validate_ground_truth(gt_rows_all)
                except ImportError:
                    problems = ["packet.schema not importable; sidecar not validated"]
                if problems:
                    print(
                        f"  ! {name}: {len(problems)} ground-truth schema problems (first: {problems[0]})"
                    )
                doc = {
                    "name": name,
                    "condition": cond,
                    "pdf": str(pdf_path),
                    "pdf_sha256": sidecar["sha256"],
                    "pdf_bytes": len(pdf),
                    "pages": len(page_table),
                    "gt": str(gt_path),
                    "gt_sha256": sha256_path(gt_path),
                    "gt_rows": len(gt_rows_all),
                    "gt_pending_rows": len(pending_all),
                    "gt_schema_problems": problems,
                    "homography_error_px": [p["homography_error_px"] for p in page_table],
                    "homography_error_max_px": [p["homography_error_max_px"] for p in page_table],
                }
                leg_summary["documents"].append(doc)
                manifest_rows.append(
                    {
                        "id": f"capture-{stamp}-{name}",
                        "path": f"<DOCS_ROOT placement ruled at step 4>/{pdf_path.name}",
                        "sha256": sidecar["sha256"],
                        "pages": len(page_table),
                        "class": None,
                        "capture": spec["kind"],
                        "features": spec["features"],
                        "gt": f"<DOCS_ROOT placement ruled at step 4>/{gt_path.name}",
                        "gt_kind": "bbox",
                        "leg_applicability": ["ocr"],
                        "source": "external",
                        "provenance": {
                            "generator": TOOL,
                            "seed": None,
                            "variant": name,
                            "capture_leg": leg,
                            "condition": cond,
                            "capture_stamp": stamp,
                            "synthetic": spec["synthetic"],
                            "gt_sha256": doc["gt_sha256"],
                            "page_classes": {str(p["page"]): p["class"] for p in page_table},
                            "master_pages": [p["master_page"] for p in page_table],
                            "homography_error_px": doc["homography_error_px"],
                            "homography_error_max_px": doc["homography_error_max_px"],
                            "dpi_effective": [p["dpi_effective"] for p in page_table],
                            "registration_run": str(out),
                            "note": (
                                "class is null because one document spans C1..C4 (per-page classes "
                                "in page_classes; the L-19 null precedent); polygons ride beside "
                                "bbox in the sidecar"
                            ),
                        },
                    }
                )
                print(
                    f"  wrote {pdf_path.name} ({len(pdf):,} bytes, {len(page_table)} pages) + {gt_path.name} "
                    f"({len(gt_rows_all)} rows{', ' + str(len(problems)) + ' schema problems' if problems else ''})"
                )
        index["legs"][leg] = leg_summary
        for r in rows_out:
            summary_lines.append(
                f"| {leg} | {r['file']} | {f'p{r["page"] + 1:02d}' if r.get('page') is not None else '-'} | "
                f"{r.get('markers_detected', 0)}/4 | "
                f"{r['homography_error_px'] if r.get('homography_error_px') is not None else '-'} | "
                f"{r['homography_error_max_px'] if r.get('homography_error_max_px') is not None else '-'} | "
                f"{r['error_px_at300'] if r.get('error_px_at300') is not None else '-'} | "
                f"{r['dpi_effective'] if r.get('dpi_effective') is not None else '-'} | "
                f"{r['rotation_deg'] if r.get('rotation_deg') is not None else '-'} | "
                f"{'ACCEPT' if r['accepted'] else 'REJECT: ' + str(r['reason'])} |"
            )

    write_json(out / "registration.json", index)
    if manifest_rows:
        write_json(out / "manifest-rows.json", manifest_rows)
    versions = {
        "python_sd_venv": platform.python_version(),
        "opencv-python": pkg_version("opencv-python"),
        "opencv-python-headless": pkg_version("opencv-python-headless"),
        "cv2": cv2.__version__,
        "numpy": np.__version__,
        "pypdfium2": pkg_version("pypdfium2"),
        "pymupdf": pkg_version("pymupdf"),
        "pillow": pkg_version("pillow"),
        "reportlab": pkg_version("reportlab"),
        "pypdf": pkg_version("pypdf"),
    }
    run = {
        "baseline_sha": args.baseline_sha,
        "dp_sha": args.dp_sha,
        "sd_sha": index["sd_sha"],
        "date": datetime.now().astimezone().isoformat(timespec="seconds"),
        "host": f"{platform.node()} / macOS {platform.mac_ver()[0]} ({platform.machine()})",
        "xcode_build": "n/a (no Swift run)",
        "sim": None,
        "device": None,
        "emitter": f"{TOOL} register (v{TOOL_VERSION})",
        "env": {},
        "inputs": [
            {"manifest_id": None, "path": str(masters.pdf), "sha256": masters.sha["pdf"]},
            {"manifest_id": None, "path": str(masters.marks_path), "sha256": masters.sha["marks"]},
            {
                "manifest_id": None,
                "path": str(masters.gt_path),
                "sha256": masters.sha["ground_truth"],
            },
        ]
        + [
            {"manifest_id": None, "path": r["image"], "sha256": r["image_sha256"]}
            for leg in index["legs"].values()
            for r in leg["rows"]
        ],
        "n_runs": 1,
        "params": reg_params,
        "capture_dir": str(capture_dir),
        "legs": list(index["legs"]),
        "tool_versions": versions,
        "notes": args.note or "",
    }
    write_json(out / "run.json", run)
    head = [
        "# SUMMARY (tool draft) -- register_capture " + stamp,
        "",
        f"masters `{MASTERS_PDF}` sha `{masters.sha['pdf'][:12]}...` | sd `{index['sd_sha']}` | "
        f"params {json.dumps(reg_params)}",
        "",
        "| leg | image | page | markers | rms px | max px | rms @300 | dpi eff | rot deg | verdict |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    tail = ["", "## documents"] + [
        f"- `{d['name']}`: {d['pages']} pp, {d['pdf_bytes']:,} B, sha `{d['pdf_sha256'][:12]}...`, "
        f"{d['gt_rows']} GT rows, rms px {d['homography_error_px']}"
        for leg in index["legs"].values()
        for d in leg["documents"]
    ]
    # a DRAFT: SUMMARY.md proper is lead-written (`32-` SS8) and must survive a re-run
    (out / "SUMMARY-draft.md").write_text(
        "\n".join(head + summary_lines + tail) + "\n", encoding="ascii"
    )
    accepted = sum(v["accepted"] for v in index["legs"].values())
    total = sum(v["images"] for v in index["legs"].values())
    print(f"\n{accepted}/{total} images registered; outputs in {out}")
    return 0 if accepted == total else 1


# ---------------------------------------------------------------------------------------------
# synthetic rasters (amendment 2): pypdfium2 renders of the masters
# ---------------------------------------------------------------------------------------------
def cmd_synthetic(args) -> int:
    pdfium = need_pdfium()
    from PIL import Image

    masters = Masters(Path(args.sd_root).expanduser())
    out_dir = Path(args.out_dir).expanduser()
    dpis = [int(s) for s in args.dpi.split(",") if s.strip()]
    pages = (
        [int(s) - 1 for s in args.pages.split(",")]
        if args.pages
        else list(range(masters.page_count))
    )
    doc = pdfium.PdfDocument(str(masters.pdf))
    for dpi in dpis:
        leg = f"synth{dpi}" + (f"-rot{args.rotate}" if args.rotate else "") + (args.suffix or "")
        leg_dir = out_dir / leg
        leg_dir.mkdir(parents=True, exist_ok=True)
        prov = {
            "tool": TOOL,
            "version": TOOL_VERSION,
            "renderer": f"pypdfium2 {pkg_version('pypdfium2')}",
            "masters": {"document": MASTERS_PDF, **masters.sha},
            "dpi": dpi,
            "grayscale": True,
            "format": args.format,
            "jpeg_quality": args.jpeg_quality if args.format == "jpeg" else None,
            "rotate_deg": args.rotate,
            "clip_left_pt": args.clip_left_pt,
            "files": [],
        }
        for i in pages:
            page = doc[i]
            bitmap = page.render(scale=dpi / 72.0, grayscale=True)
            arr = np.array(bitmap.to_pil().convert("L"))
            if args.clip_left_pt:
                x = round(args.clip_left_pt * dpi / 72.0)
                arr[:, :x] = 255
            if args.rotate:
                arr = np.ascontiguousarray(np.rot90(arr, args.rotate // 90))
            im = Image.fromarray(arr, "L")
            name = f"p{i + 1:02d}." + ("jpg" if args.format == "jpeg" else "png")
            path = leg_dir / name
            if args.format == "jpeg":
                im.save(path, format="JPEG", quality=args.jpeg_quality, subsampling=0)
            else:
                im.save(path, format="PNG", optimize=False)
            prov["files"].append(
                {
                    "file": name,
                    "master_page": i,
                    "sha256": sha256_path(path),
                    "width_px": int(arr.shape[1]),
                    "height_px": int(arr.shape[0]),
                }
            )
        write_json(leg_dir / "synthetic.json", prov)
        print(f"[{leg}] {len(pages)} pages rendered at {dpi} DPI ({args.format}) -> {leg_dir}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("synthetic", help="rasterize the masters (pypdfium2) into synth<dpi> legs")
    s.add_argument("--sd-root", default=str(REPO))
    s.add_argument("--out-dir", required=True)
    s.add_argument("--dpi", default="150,300")
    s.add_argument(
        "--pages", default=None, help="1-indexed master pages, comma-separated (default all)"
    )
    s.add_argument("--format", choices=["jpeg", "png"], default="jpeg")
    s.add_argument("--jpeg-quality", type=int, default=90)
    s.add_argument("--rotate", type=int, choices=[0, 90, 180, 270], default=0)
    s.add_argument(
        "--clip-left-pt",
        type=float,
        default=0.0,
        help="paint the left N points white (simulates an unprintable margin eating the fiducials)",
    )
    s.add_argument("--suffix", default="", help="leg-name suffix (e.g. -clip19)")
    s.set_defaults(fn=cmd_synthetic)

    r = sub.add_parser(
        "register", help="register every leg under a capture dir into an evidence run dir"
    )
    r.add_argument("--sd-root", default=str(REPO))
    r.add_argument("--capture-dir", required=True)
    r.add_argument("--out", required=True)
    r.add_argument(
        "--legs", default=None, help="comma-separated subset (default: every subdir with images)"
    )
    r.add_argument(
        "--stamp", default=None, help="capture stamp for ids (default: the capture dir name)"
    )
    r.add_argument("--refine", choices=["none", "subpix", "contour", "apriltag"], default="subpix")
    r.add_argument(
        "--max-error-px", type=float, default=2.0, help="reject above this reprojection RMS ([R06])"
    )
    r.add_argument(
        "--max-corner-error-px",
        type=float,
        default=3.0,
        help="reject when the worst single corner exceeds this (default 1.5x the RMS gate)",
    )
    r.add_argument("--min-markers", type=int, default=4)
    r.add_argument("--ransac-px", type=float, default=3.0)
    r.add_argument(
        "--max-correction-bits",
        type=int,
        default=2,
        help="cap on the restricted pass's error correction ((dmin-1)//2 otherwise)",
    )
    r.add_argument("--min-perimeter-rate", type=float, default=0.01)
    r.add_argument(
        "--no-restrict", action="store_true", help="skip the page-restricted sub-dictionary pass"
    )
    r.add_argument(
        "--emit-pdf", action="store_true", help="assemble one PDF + GT sidecar per (leg, condition)"
    )
    r.add_argument(
        "--pdf-dpi",
        choices=["nominal", "effective"],
        default="nominal",
        help="page size rule: the leg's nominal DPI when it has one, else the homography's",
    )
    r.add_argument("--photo-order", default="flat,skew,shadow")
    r.add_argument(
        "--derive-rot90", default=None, help="1-indexed pages to derive by rot90 (e.g. 2,10)"
    )
    r.add_argument("--derive-source", default="scan150")
    r.add_argument("--overlay-max-px", type=int, default=1600)
    r.add_argument("--baseline-sha", default="8bbf5c8c8b88e5953b506227e80947e3b8460ecb")
    r.add_argument("--dp-sha", default="fa1f4765")
    r.add_argument("--note", default=None)
    r.set_defaults(fn=cmd_register)
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
