"""Check every hidden-layer document against its parameters and its expected file.

    .venv/bin/python -I hidden_layer/verify_docs.py <dir> [--only id,id] [--report out.json]

``<dir>`` holds ``manifest.json``, ``SHA256SUMS``, ``documents/`` and ``expected/`` (a build
directory, or ``hidden_layer/`` itself for the committed subset; a document listed as ``local``
and absent is reported as not checked). Exit status 0 means every property of every checked
document held; any failed property is exit status 1.

The properties, each a named check (``CHECKS``):

- ``structure``: one 612 x 792 pt page; the first operation draws ``/Im1`` over the whole page;
  ``/Im1`` is a DCTDecode DeviceGray image of the expected pixel size, whose stream is the expected
  JPEG (SHA-256); every text-showing operator comes after the image and in render mode 3.
- ``jpeg``: the JPEG's quantization tables equal those Pillow writes at the stated quality, and
  its pixel size gives the stated resolution.
- ``ground``: the render's left-margin strip has a mean and a spread inside the ground's class
  (``GROUND_CLASSES``); on the black-bar ground the bar's inside is dark.
- ``ink``: each word's ink, measured in the render near its expected box, has that box's edges
  within ``ink_tolerance_px``; words under the bar are skipped (their ink is painted over).
- ``layer``: each hidden piece, read back by PyMuPDF (characters, origins, advances), has the
  expected text, origin and glyph advances within ``LAYER_TOL_PT``.
- ``drift``: each word's measured hidden-copy left edge minus its measured ink left edge equals
  the document's drift plus that word's jitter (recomputed from the seed) within the drift
  tolerance; the median over all words equals the drift; the hidden baseline sits at the printed
  baseline plus the vertical shift, measured on words with no descender.
- ``misread``: where the parameters ask for it, the surname's hidden copy is spelled differently
  from the print, and no hidden word over that copy reads as the printed surname.
- ``vision``: for the Vision set, the layer holds exactly the recorded words, each spanning its
  recorded box, and the recording belongs to this picture (its SHA-256).
- ``scenarios``: every scenario's regions and facts, recomputed from the expected file's numbers
  with the same rules, equal the recorded ones.
- ``checksums``: the document and its expected file match ``manifest.json`` and ``SHA256SUMS``.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import statistics
import sys
from decimal import Decimal
from fractions import Fraction
from itertools import pairwise
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pymupdf
import pypdf
from PIL import Image, ImageDraw, ImageFilter
from pypdf.generic import ContentStream

from hidden_layer import scenarios
from hidden_layer.rng import mix_seed, scalar_ints
from hidden_layer.values import MISREAD_SPLIT, MISREAD_SUBSTITUTE, PERSON

LAYER_TOL_PT = Decimal("0.02")
MARGIN_STRIP_PT = (16, 100, 56, 700)
# (mean low, mean high, spread low, spread high), spread = standard deviation of 8-bit grey.
GROUND_CLASSES: dict[str, tuple[float, float, float, float]] = {
    "clean": (245, 256, 0, 4),
    "light-noise": (225, 250, 2.5, 15),
    "heavy-noise": (165, 215, 5, 40),
    "textured": (195, 245, 4, 30),
    "dark": (20, 70, 0, 15),
    "black-bar": (245, 256, 0, 4),
}
BAR_MEAN_MAX = 60
TEXTURE_BLOCK_SPREAD_MIN = 4.0
NO_DESCENDER = frozenset("ABCDEFGHIKLMNOPRSTUVWXZabcdefhiklmnorstuvwxz0123456789.:")
LIGHT_TEXT_THRESHOLD = frozenset({"dark"})
MIN_INK_CONTRAST = 40


def ink_tolerance_px(exp: dict[str, Any]) -> int:
    """Edge tolerance for the measured ink box: 1 px for JPEG ringing plus 3 px per pixel of blur."""
    blur = float(exp["degrade"]["blur_px"])
    return 1 + math.ceil(3 * blur)


def skew_slack_px(exp: dict[str, Any], w: dict[str, Any]) -> int:
    """How far inside its hull a skewed word's ink may stop (the hull is of the rotated rectangle)."""
    skew = float(exp["degrade"]["skew_deg"])
    if not skew:
        return 0
    x0, y0, x1, y1 = w["ink_px"]
    return math.ceil((x1 - x0 + y1 - y0) * math.sin(math.radians(skew))) + 1


class Result:
    def __init__(self, doc: str) -> None:
        self.doc = doc
        self.checks: dict[str, dict[str, Any]] = {}

    def record(self, name: str, ok: bool | None, detail: str) -> None:
        self.checks[name] = {"ok": ok, "detail": detail}

    @property
    def ok(self) -> bool:
        return all(c["ok"] is not False for c in self.checks.values())


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="ascii"), parse_float=Decimal)


def frac(x: Any) -> Fraction:
    return Fraction(Decimal(str(x))) if not isinstance(x, Decimal) else Fraction(x)


def rect_of(v: list[Any]) -> scenarios.Rect:
    return (frac(v[0]), frac(v[1]), frac(v[2]), frac(v[3]))


# ------------------------------------------------------------------------------------- structure
def _walk_ops(page: Any, reader: pypdf.PdfReader) -> list[tuple[list[Any], bytes]]:
    cs = ContentStream(page.get_contents(), reader)
    return [(list(ops), op) for ops, op in cs.operations]


def image_object(page: Any) -> Any:
    res: Any = page["/Resources"]
    return res["/XObject"]["/Im1"].get_object()


def check_structure(pdf: bytes, exp: dict[str, Any], r: Result) -> None:
    rd = pypdf.PdfReader(io.BytesIO(pdf))
    problems = []
    if len(rd.pages) != 1:
        problems.append(f"{len(rd.pages)} pages")
    pg = rd.pages[0]
    mb = [float(x) for x in pg.mediabox]
    if mb != [0, 0, 612, 792]:
        problems.append(f"mediabox {mb}")
    ops = _walk_ops(pg, rd)
    first = [op for _, op in ops[:4]]
    if (
        first != [b"q", b"cm", b"Do", b"Q"]
        or [float(x) for x in ops[1][0]] != [612, 0, 0, 792, 0, 0]
        or ops[2][0][0] != "/Im1"
    ):
        problems.append(f"first operations {first}")
    xo = image_object(pg)
    w, h = exp["page"]["image_px"]
    if (xo["/Width"], xo["/Height"]) != (w, h):
        problems.append(f"image {xo['/Width']}x{xo['/Height']} != {w}x{h}")
    if xo["/Filter"] != "/DCTDecode" or xo["/ColorSpace"] != "/DeviceGray":
        problems.append(f"image filter {xo['/Filter']} {xo['/ColorSpace']}")
    if hashlib.sha256(xo.get_data()).hexdigest() != exp["image"]["sha256"]:
        problems.append("image stream differs from the expected JPEG")
    tr = 0
    stack: list[int] = []
    shows = 0
    bad_tr = 0
    seen_do = False
    text_before = 0
    for operands, op in ops:
        if op == b"q":
            stack.append(tr)
        elif op == b"Q":
            tr = stack.pop() if stack else 0
        elif op == b"Tr":
            tr = int(operands[0])
        elif op == b"Do":
            seen_do = True
        elif op in (b"Tj", b"TJ", b"'", b'"'):
            shows += 1
            bad_tr += tr != 3
            text_before += not seen_do
    if bad_tr or text_before:
        problems.append(f"{bad_tr} shows not in Tr 3; {text_before} before the image")
    if shows != exp["layer"]["pieces"]:
        problems.append(f"{shows} text shows, expected {exp['layer']['pieces']}")
    r.record(
        "structure",
        not problems,
        "; ".join(problems) or f"1 page, image first, {shows} shows all Tr 3",
    )


def check_jpeg(jpeg: bytes, exp: dict[str, Any], r: Result) -> np.ndarray:
    im: Any = Image.open(io.BytesIO(jpeg))
    q = int(exp["image"]["jpeg_quality"])
    ref = io.BytesIO()
    Image.new("L", im.size, 128).save(ref, "JPEG", quality=q)
    ref_im: Any = Image.open(io.BytesIO(ref.getvalue()))
    want = ref_im.quantization
    dpi = Fraction(im.size[0] * 72, 612)
    ok = im.quantization == want and round(dpi) == int(exp["page"]["dpi"]) and im.mode == "L"
    r.record(
        "jpeg",
        ok,
        f"quantization {'equals' if im.quantization == want else 'differs from'} q{q}; {im.size[0]}x{im.size[1]} px = {float(dpi):.2f} dpi",
    )
    return np.asarray(im)


def render(pdf: bytes, dpi: int) -> np.ndarray:
    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        pix = doc[0].get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY, alpha=False)
        return np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width).copy()


def check_ground(img: np.ndarray, exp: dict[str, Any], r: Result) -> None:
    dpi = int(exp["page"]["dpi"])
    s = dpi / 72
    x0, y0, x1, y1 = (round(v * s) for v in MARGIN_STRIP_PT)
    strip = img[y0:y1, x0:x1].astype(np.float64)
    mean, sd = float(strip.mean()), float(strip.std())
    kind = exp["ground"]["kind"]
    lo, hi, slo, shi = GROUND_CLASSES[kind]
    ok = lo <= mean <= hi and slo <= sd <= shi
    detail = f"{kind}: margin mean {mean:.1f} in [{lo}, {hi}], spread {sd:.1f} in [{slo}, {shi}]"
    if kind == "textured":
        b = max(4, dpi // 12)
        hh, ww = (strip.shape[0] // b) * b, (strip.shape[1] // b) * b
        blocks = strip[:hh, :ww].reshape(hh // b, b, ww // b, b).mean(axis=(1, 3))
        bsd = float(blocks.std())
        ok = ok and bsd >= TEXTURE_BLOCK_SPREAD_MIN
        detail += f"; block-mean spread {bsd:.1f} >= {TEXTURE_BLOCK_SPREAD_MIN}"
    if exp["bar_px"] is not None:
        bx0, by0, bx1, by1 = exp["bar_px"]
        inset = max(2, dpi // 50)
        bar_mean = float(img[by0 + inset : by1 - inset, bx0 + inset : bx1 - inset].mean())
        ok = ok and bar_mean <= BAR_MEAN_MAX
        detail += f"; bar mean {bar_mean:.1f} <= {BAR_MEAN_MAX}"
    r.record("ground", ok, detail)


# ------------------------------------------------------------------------------------------- ink
def rule_mask(exp: dict[str, Any], size: tuple[int, int], tol: int) -> np.ndarray:
    """The printed rules (their rotated outlines on a skewed page), grown by ``tol`` pixels."""
    im = Image.new("L", size, 0)
    draw = ImageDraw.Draw(im)
    polys = exp.get("rules_polygon_px")
    if polys:
        for poly in polys:
            draw.polygon([(float(x), float(y)) for x, y in poly], fill=255)
    else:
        for b in exp["rules_px"]:
            draw.rectangle((b[0], b[1], b[2] - 1, b[3] - 1), fill=255)
    if tol:
        im = im.filter(ImageFilter.MaxFilter(2 * tol + 1))
    return np.asarray(im) > 0


def measure_ink(
    img: np.ndarray, exp: dict[str, Any]
) -> dict[int, tuple[int, int, int, int] | None]:
    """Each word's measured ink box (pixels, top-left origin, exclusive right/bottom), found in a
    window of its expected box grown by the tolerance, ignoring pixels near any other object.

    The ink threshold is set per word, halfway between the window's darkest pixel and the median of
    the ring between the expected box and the window edge (on the dark ground, with the polarity
    reversed). A word whose contrast is below ``MIN_INK_CONTRAST`` has no measured ink."""
    kind = exp["ground"]["kind"]
    dark = img if kind not in LIGHT_TEXT_THRESHOLD else 255 - img
    tol = ink_tolerance_px(exp)
    h, w = img.shape
    others = np.zeros(img.shape, dtype=bool)
    rules = rule_mask(exp, (w, h), tol)
    boxes = [(wd["i"], wd["ink_px"]) for wd in exp["words"]]
    out: dict[int, tuple[int, int, int, int] | None] = {}
    for wd in exp["words"]:
        if wd["under_bar"]:
            continue
        x0, y0, x1, y1 = wd["ink_px"]
        wx0, wy0 = max(0, x0 - tol), max(0, y0 - tol)
        wx1, wy1 = min(w, x1 + tol), min(h, y1 + tol)
        others[wy0:wy1, wx0:wx1] = False
        for j, b in boxes:
            if j != wd["i"]:
                others[max(0, b[1] - 1) : b[3] + 1, max(0, b[0] - 1) : b[2] + 1] = True
        others[wy0:wy1, wx0:wx1] |= rules[wy0:wy1, wx0:wx1]
        free = ~others[wy0:wy1, wx0:wx1]
        win = dark[wy0:wy1, wx0:wx1].astype(np.int64)
        ring = free.copy()
        ring[y0 - wy0 : y1 - wy0, x0 - wx0 : x1 - wx0] = False
        if not ring.any() or not free.any():
            out[wd["i"]] = None
            continue
        bg = float(np.median(win[ring]))
        mn = float(win[free].min())
        if bg - mn < MIN_INK_CONTRAST:
            out[wd["i"]] = None
            continue
        ys, xs = np.nonzero((win <= (bg + mn) / 2) & free)
        out[wd["i"]] = (
            wx0 + int(xs.min()),
            wy0 + int(ys.min()),
            wx0 + int(xs.max()) + 1,
            wy0 + int(ys.max()) + 1,
        )
    return out


def check_ink(
    measured: dict[int, tuple[int, int, int, int] | None], exp: dict[str, Any], r: Result
) -> None:
    tol = ink_tolerance_px(exp)
    bad = []
    worst = 0
    for wd in exp["words"]:
        if wd["under_bar"]:
            continue
        m = measured.get(wd["i"])
        if m is None:
            bad.append(f"{wd['i']}:no ink")
            continue
        slack = skew_slack_px(exp, wd)
        e = wd["ink_px"]
        # Outward the measured edge may pass the expected one by the tolerance; inward by tolerance
        # plus the skew slack.
        devs = (e[0] - m[0], e[1] - m[1], m[2] - e[2], m[3] - e[3])
        for d in devs:
            worst = max(worst, abs(d))
            if d > tol or d < -(tol + slack):
                bad.append(f"{wd['i']}:{wd['text']} {e}->{m}")
                break
    n = sum(1 for wd in exp["words"] if not wd["under_bar"])
    r.record(
        "ink",
        not bad,
        f"{n - len(bad)}/{n} words within {tol} px (worst edge {worst} px)"
        + (f"; {bad[:4]}" if bad else ""),
    )


# ----------------------------------------------------------------------------------------- layer
def read_layer(pdf: bytes) -> list[dict[str, Any]]:
    """Every hidden character PyMuPDF reads: text, origin, advance range, font size."""
    chars = []
    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        d = doc[0].get_text("rawdict")
        for b in d["blocks"]:
            for line in b.get("lines", []):
                for span in line["spans"]:
                    for ch in span["chars"]:
                        chars.append(
                            {
                                "c": ch["c"],
                                "ox": ch["origin"][0],
                                "oy": 792 - ch["origin"][1],
                                "x0": ch["bbox"][0],
                                "x1": ch["bbox"][2],
                                "size": span["size"],
                            }
                        )
    return chars


def match_piece(chars: list[dict[str, Any]], piece: dict[str, Any]) -> list[dict[str, Any]]:
    ox, oy = float(piece["origin_pt"][0]), float(piece["origin_pt"][1])
    x1 = float(piece["box_pt"][2])
    tol = float(LAYER_TOL_PT)
    got = [
        c
        for c in chars
        if c["c"] != " "
        and abs(c["oy"] - oy) <= tol
        and ox - tol <= (c["x0"] + c["x1"]) / 2 <= x1 + tol
    ]
    return sorted(got, key=lambda c: c["x0"])


def glyph_ranges(piece: dict[str, Any]) -> list[tuple[Any, Any]]:
    """Each glyph's advance range from the piece's edge list (glyph i spans edges i and i + 1)."""
    e = piece["glyph_edges_pt"]
    return list(pairwise(e))


def check_layer(chars: list[dict[str, Any]], exp: dict[str, Any], r: Result) -> dict[int, float]:
    """Returns each word's measured hidden left edge (pt)."""
    tol = float(LAYER_TOL_PT)
    bad = []
    left: dict[int, float] = {}
    n = 0
    listed = [(wd["i"], k, p) for wd in exp["words"] for k, p in enumerate(wd["hidden"])]
    listed += [(-1, k, p) for k, p in enumerate(exp.get("unpaired_hidden") or [])]
    for i, k, piece in listed:
        n += 1
        got = match_piece(chars, piece)
        text = "".join(c["c"] for c in got)
        if text != piece["text"]:
            bad.append(f"{i}: read {text!r} for {piece['text']!r}")
            continue
        dev = max(
            max(abs(c["x0"] - float(g[0])), abs(c["x1"] - float(g[1])))
            for c, g in zip(got, glyph_ranges(piece), strict=True)
        )
        if dev > tol or abs(got[0]["ox"] - float(piece["origin_pt"][0])) > tol:
            bad.append(f"{i}: glyph edges off by {dev:.3f} pt")
        if k == 0 and i >= 0:
            left[i] = got[0]["x0"]
    r.record(
        "layer",
        not bad,
        f"{n - len(bad)}/{n} pieces read back within {tol} pt" + (f"; {bad[:4]}" if bad else ""),
    )
    return left


def check_drift(
    left: dict[int, float],
    measured: dict[int, tuple[int, int, int, int] | None],
    chars: list[dict[str, Any]],
    exp: dict[str, Any],
    r: Result,
) -> None:
    p = exp["params"]
    dpi = int(exp["page"]["dpi"])
    k = 72 / dpi
    n = len(exp["words"])
    if exp["layer"]["source"] == "vision":
        offs = [
            left[w["i"]] - m[0] * k
            for w in exp["words"]
            if w["i"] in left and (m := measured.get(w["i"]))
        ]
        med = statistics.median(offs) if offs else float("nan")
        r.record(
            "drift",
            None,
            f"layer from text recognition, no drift parameter; median measured offset {med:+.2f} pt over {len(offs)} words",
        )
        return
    jit = [(0, 0)] * n
    if p["jitter_cpt"]:
        vals = scalar_ints(
            mix_seed(int(p["seed"]), "jitter"), 2 * n, -int(p["jitter_cpt"]), int(p["jitter_cpt"])
        )
        jit = [(vals[2 * i], vals[2 * i + 1]) for i in range(n)]
    drift = int(p["drift_cpt"]) / 100
    vshift = int(p["vshift_cpt"]) / 100
    tol_x = ink_tolerance_px(exp) * k + float(LAYER_TOL_PT)
    bad = []
    offsets = []
    vbad = []
    vn = 0
    for wd in exp["words"]:
        i = wd["i"]
        m = measured.get(i)
        if m is None or i not in left:
            continue
        slack = skew_slack_px(exp, wd) * k
        dx = left[i] - m[0] * k
        want = drift + jit[i][0] / 100
        offsets.append(dx - jit[i][0] / 100)
        if not (want - tol_x - slack <= dx <= want + tol_x):
            bad.append(f"{i}:{wd['text']} dx {dx:.2f} want {want:.2f}")
        if all(ch in NO_DESCENDER for ch in wd["text"]) and not float(exp["degrade"]["skew_deg"]):
            vn += 1
            got = match_piece(chars, wd["hidden"][0])
            base_meas = 792 - m[3] * k
            dy = got[0]["oy"] - base_meas if got else float("nan")
            wanty = vshift + jit[i][1] / 100
            if not (abs(dy - wanty) <= tol_x + k):
                vbad.append(f"{i}:{wd['text']} dy {dy:.2f} want {wanty:.2f}")
    med = statistics.median(offsets) if offsets else float("nan")
    ok = not bad and not vbad and abs(med - drift) <= tol_x
    r.record(
        "drift",
        ok,
        f"median along-line offset {med:+.2f} pt vs drift {drift:+.2f} (tol {tol_x:.2f}); "
        f"{len(offsets) - len(bad)}/{len(offsets)} words in band; baseline {vn - len(vbad)}/{vn} at shift {vshift:+.2f}"
        + (f"; {(bad + vbad)[:4]}" if bad or vbad else ""),
    )


def check_misread(chars: list[dict[str, Any]], exp: dict[str, Any], r: Result) -> None:
    mode = exp["params"]["misread"]
    if mode is None:
        r.record("misread", None, "not asked for")
        return
    key, pos = scenarios.SURNAME
    wd = next(w for w in exp["words"] if w["line_key"] == key and w["position"] == pos)
    want = [MISREAD_SUBSTITUTE] if mode == "substitute" else list(MISREAD_SPLIT)
    read = ["".join(c["c"] for c in match_piece(chars, p)) for p in wd["hidden"]]
    printed_ok = wd["text"] == PERSON["last"]
    no_hit = all(t.lower() != PERSON["last"].lower() for t in read)
    ok = printed_ok and read == want and no_hit
    r.record("misread", ok, f"printed {wd['text']!r}; hidden reads {read!r}; expected {want!r}")


def check_vision(chars: list[dict[str, Any]], exp: dict[str, Any], root: Path, r: Result) -> None:
    """The layer holds exactly the recorded Vision words: same text, and an advance from the
    recorded box's left edge to its right edge."""
    v = exp.get("vision")
    if not v:
        r.record("vision", None, "placed layer")
        return
    path = root / v["recording"]
    if not path.exists():
        r.record("vision", False, f"recording {v['recording']} missing")
        return
    raw = path.read_bytes()
    rec = json.loads(raw.decode("ascii"), parse_float=Decimal)
    problems = []
    if hashlib.sha256(raw).hexdigest() != v["recording_sha256"]:
        problems.append("recording checksum differs")
    if rec["image_sha256"] != exp["image"]["sha256"]:
        problems.append("recording made from a different picture")
    pieces = [p for wd in exp["words"] for p in wd["hidden"]] + list(
        exp.get("unpaired_hidden") or []
    )
    read = []
    for p in pieces:
        got = match_piece(chars, p)
        if got:
            read.append(("".join(c["c"] for c in got), got[0]["x0"], got[-1]["x1"]))
    tokens = [
        (w["text"], float(w["box"][0]) * 612, float(w["box"][2]) * 612)
        for o in rec["observations"]
        for w in o["words"]
        if w["box"] is not None
    ]
    tol = float(LAYER_TOL_PT) + 0.03
    unmatched = 0
    pool = list(read)
    for t in tokens:
        hit = next(
            (
                q
                for q in pool
                if q[0] == t[0] and abs(q[1] - t[1]) <= tol and abs(q[2] - t[2]) <= tol
            ),
            None,
        )
        if hit is None:
            unmatched += 1
        else:
            pool.remove(hit)
    if unmatched or pool:
        problems.append(
            f"{unmatched} recorded words not in the layer; {len(pool)} layer words not recorded"
        )
    r.record(
        "vision",
        not problems,
        "; ".join(problems)
        or f"{len(tokens)} recorded words = the layer (macOS {rec['macos']}, revision {rec['revision']})",
    )


# ------------------------------------------------------------------------------------- scenarios
def geoms_from_expected(exp: dict[str, Any]) -> list[scenarios.WordGeom]:
    out = []
    for wd in exp["words"]:
        pieces = []
        for p in wd["hidden"]:
            box = rect_of(p["box_pt"])
            glyphs = tuple(
                scenarios.Glyph(ch, (frac(g[0]), box[1], frac(g[1]), box[3]))
                for ch, g in zip(p["text"], glyph_ranges(p), strict=True)
            )
            pieces.append(scenarios.Piece(p["text"], box, glyphs))
        out.append(
            scenarios.WordGeom(
                wd["i"],
                wd["line_key"],
                wd["position"],
                wd["text"],
                rect_of(wd["ink_pt"]),
                tuple(pieces),
                wd["under_bar"],
            )
        )
    return out


def _norm(x: Any) -> Any:
    """JSON-comparable form: Decimals and Fractions to 3-place floats, recursively."""
    if isinstance(x, Decimal | Fraction):
        return round(float(x), 3)
    if isinstance(x, list | tuple):
        return [_norm(v) for v in x]
    if isinstance(x, dict):
        return {k: _norm(v) for k, v in x.items()}
    return x


def check_scenarios(exp: dict[str, Any], r: Result) -> None:
    geoms = geoms_from_expected(exp)
    bar = rect_of(exp["bar_pt"]) if exp["bar_pt"] is not None else None
    page = scenarios.rect(0, 0, 612, 792)
    recorded = {s["name"]: s for s in exp["scenarios"]}
    bad = []
    names = []
    for name, kind, regions, notes in scenarios.scenario_regions(
        geoms, page, bar, exp["params"]["misread"] is not None
    ):
        names.append(name)
        rec = recorded.get(name)
        if rec is None:
            bad.append(f"{name}: missing")
            continue
        regs = [
            {
                "made_by": g.made_by,
                "paint_pt": list(g.paint),
                "strip_pt": None if g.strip is None else list(g.strip),
            }
            for g in regions
        ]
        mine = {
            "name": name,
            "kind": kind,
            "regions": regs,
            "notes": dict(notes),
            **scenarios.facts(geoms, regions),
        }
        if _norm(mine) != _norm(rec):
            diff = [k for k in mine if _norm(mine[k]) != _norm(rec.get(k))]
            bad.append(f"{name}: {diff}")
    extra = set(recorded) - set(names)
    if extra:
        bad.append(f"unexpected scenarios {sorted(extra)}")
    r.record(
        "scenarios",
        not bad,
        f"{len(names) - len(bad)}/{len(names)} scenarios recomputed equal"
        + (f"; {bad[:4]}" if bad else ""),
    )


# ------------------------------------------------------------------------------------- checksums
def read_sums(path: Path) -> dict[str, str]:
    out = {}
    for line in path.read_text(encoding="ascii").splitlines():
        digest, name = line.split("  ", 1)
        out[name] = digest
    return out


def check_one(root: Path, row: dict[str, Any], sums: dict[str, str]) -> Result:
    doc_id = Path(row["path"]).stem
    r = Result(doc_id)
    pdf_path = root / row["path"]
    exp_path = root / row["expected"]
    exp_bytes = exp_path.read_bytes()
    exp = json.loads(exp_bytes.decode("ascii"), parse_float=Decimal)
    if not pdf_path.exists():
        r.record("present", None, f"stored {row['stored']}: not in this directory; not checked")
        return r
    pdf = pdf_path.read_bytes()
    sha = hashlib.sha256(pdf).hexdigest()
    esha = hashlib.sha256(exp_bytes).hexdigest()
    sums_ok = (
        sha == row["sha256"] == sums.get(row["path"])
        and esha == row["expected_sha256"] == sums.get(row["expected"])
        and len(pdf) == row["bytes"]
    )
    r.record("checksums", sums_ok, f"pdf {sha[:12]}, expected {esha[:12]}")
    check_structure(pdf, exp, r)
    rd = pypdf.PdfReader(io.BytesIO(pdf))
    jpeg = image_object(rd.pages[0]).get_data()
    check_jpeg(jpeg, exp, r)
    img = render(pdf, int(exp["page"]["dpi"]))
    check_ground(img, exp, r)
    measured = measure_ink(img, exp)
    check_ink(measured, exp, r)
    chars = read_layer(pdf)
    left = check_layer(chars, exp, r)
    check_drift(left, measured, chars, exp, r)
    check_misread(chars, exp, r)
    check_vision(chars, exp, root, r)
    check_scenarios(exp, r)
    return r


CHECKS = (
    "checksums",
    "structure",
    "jpeg",
    "ground",
    "ink",
    "layer",
    "drift",
    "misread",
    "vision",
    "scenarios",
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("root", type=Path)
    ap.add_argument("--only", default="")
    ap.add_argument("--report", type=Path)
    a = ap.parse_args()
    manifest = load_json(a.root / "manifest.json")
    sums = read_sums(a.root / "SHA256SUMS")
    only = {x for x in a.only.split(",") if x}
    results = []
    for row in manifest["documents"]:
        if only and Path(row["path"]).stem not in only:
            continue
        res = check_one(a.root, row, sums)
        results.append(res)
        mark = "ok  " if res.ok else "FAIL"
        sys.stdout.write(f"{mark} {res.doc}\n")
        for name, c in res.checks.items():
            if c["ok"] is False or a.only:
                sys.stdout.write(
                    f"     {name}: {'ok' if c['ok'] else ('n/a' if c['ok'] is None else 'FAIL')}  {c['detail']}\n"
                )
    failed = [x.doc for x in results if not x.ok]
    checked = sum(1 for x in results if "present" not in x.checks)
    sys.stdout.write(
        f"{checked} checked, {len(results) - checked} not present, {len(failed)} failed\n"
    )
    if a.report:
        a.report.write_text(
            json.dumps([{"doc": x.doc, "ok": x.ok, "checks": x.checks} for x in results], indent=1)
            + "\n",
            encoding="ascii",
        )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
