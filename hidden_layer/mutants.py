"""Recorded mutants: one deliberate defect per property kind, each of which ``verify_docs`` must
report as a failed property.

    .venv/bin/python -I hidden_layer/mutants.py --out <empty dir> [--record mutants.json]

Each mutant builds one document with the defect applied (to the generator, or to the files after
the build), then runs the checks. The run passes only when the unmutated control is green and every
mutant turns its own property red. The documents used carry every property kind between them: a
heavy-noise page with a drifted, misread layer, and a Vision-set page.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hidden_layer import build, grid, layer, pages, verify_docs

DOC = "hl-a3-heavy-300-none-d8-misread-substitute"
DOC_VISION = "hl-v-heavy-200-mild"
_current = {"doc": DOC}


@contextmanager
def patched(obj: Any, name: str, value: Any) -> Iterator[None]:
    old = getattr(obj, name)
    setattr(obj, name, value)
    try:
        yield
    finally:
        setattr(obj, name, old)


def _spec() -> grid.DocSpec:
    return next(s for s in grid.all_specs() if s.doc_id == _current["doc"])


def _write(out: Path, pdf: bytes, expected: dict[str, Any], spec: grid.DocSpec) -> None:
    (out / "documents").mkdir(parents=True)
    (out / "expected").mkdir(parents=True)
    exp_b = build.json_bytes(expected)
    doc = spec.doc_id
    (out / f"documents/{doc}.pdf").write_bytes(pdf)
    (out / f"expected/{doc}.expected.json").write_bytes(exp_b)
    if spec.layer == "vision":
        (out / "vision").mkdir()
        src = build.VISION_DIR / f"{doc}.vision.json"
        (out / "vision" / src.name).write_bytes(src.read_bytes())
    row = {
        "path": f"documents/{doc}.pdf",
        "bytes": len(pdf),
        "sha256": hashlib.sha256(pdf).hexdigest(),
        "expected": f"expected/{doc}.expected.json",
        "expected_sha256": hashlib.sha256(exp_b).hexdigest(),
        "stored": "local",
        "params": spec.params(),
    }
    (out / "manifest.json").write_bytes(build.json_bytes({"schema": 1, "documents": [row]}))
    sums = f"{row['sha256']}  {row['path']}\n{row['expected_sha256']}  {row['expected']}\n"
    (out / "SHA256SUMS").write_text(sums, encoding="ascii")


def _drift_zero() -> Callable[[], tuple[bytes, dict[str, Any]]]:
    def run() -> tuple[bytes, dict[str, Any]]:
        spec = _spec()
        real = build.placed_pieces
        zero = grid.DocSpec(**{**spec.__dict__, "drift_cpt": 0})
        with patched(build, "placed_pieces", lambda _s, page: real(zero, page)):
            return build.build_doc(spec)

    return run


def _render_mode_zero() -> tuple[bytes, dict[str, Any]]:
    real = layer.content_stream

    def visible(pieces: list[layer.HiddenPiece], w: int, h: int) -> bytes:
        return real(pieces, w, h).replace(b"BT 3 Tr", b"BT 0 Tr")

    with patched(build, "write_pdf", _writer_with(visible)):
        return build.build_doc(_spec())


def _writer_with(
    stream: Callable[[list[layer.HiddenPiece], int, int], bytes],
) -> Callable[..., bytes]:
    def write(
        jpeg: bytes,
        image_px: tuple[int, int],
        pieces: list[layer.HiddenPiece],
        w: int = 612,
        h: int = 792,
    ) -> bytes:
        with patched(layer, "content_stream", stream):
            return layer.write_pdf(jpeg, image_px, pieces, w, h)

    return write


def _jpeg_quality_off() -> tuple[bytes, dict[str, Any]]:
    real = pages.jpeg_bytes
    with patched(pages, "jpeg_bytes", lambda page, q: real(page, q - 10)):
        return build.build_doc(_spec())


def _ground_swapped() -> tuple[bytes, dict[str, Any]]:
    real = pages.ground_pixels
    with patched(
        pages,
        "ground_pixels",
        lambda kind, dpi, seed: real("clean" if kind == "heavy-noise" else kind, dpi, seed),
    ):
        return build.build_doc(_spec())


def _ink_box_shifted() -> tuple[bytes, dict[str, Any]]:
    pdf, raw = build.build_doc(_spec())
    exp: dict[str, Any] = raw
    w = exp["words"][len(exp["words"]) // 2]
    w["ink_px"] = [w["ink_px"][0] + 3, w["ink_px"][1], w["ink_px"][2] + 3, w["ink_px"][3]]
    return pdf, exp


def _layer_text_changed() -> tuple[bytes, dict[str, Any]]:
    real = layer.content_stream

    def changed(pieces: list[layer.HiddenPiece], w: int, h: int) -> bytes:
        return (
            real(pieces, w, h)
            .replace(b"(today. ) Tj", b"(todav. ) Tj", 1)
            .replace(b"(today.) Tj", b"(todav.) Tj", 1)
        )

    with patched(build, "write_pdf", _writer_with(changed)):
        return build.build_doc(_spec())


def _misread_dropped() -> tuple[bytes, dict[str, Any]]:
    with patched(build, "MISREAD_SUBSTITUTE", "Delgado"):
        return build.build_doc(_spec())


def _scenario_fact_emptied() -> tuple[bytes, dict[str, Any]]:
    pdf, raw = build.build_doc(_spec())
    exp: dict[str, Any] = raw
    for s in exp["scenarios"]:
        if s["name"] == "hand-box-surname":
            s["must_be_absent"] = []
    return pdf, exp


def _vision_word_dropped() -> tuple[bytes, dict[str, Any]]:
    real = build.vision_pieces

    def dropped(spec: grid.DocSpec, page: pages.Page, jpg: bytes) -> Any:
        per_word, unpaired, flat, facts = real(spec, page, jpg)
        gone = flat.pop()
        for ps in per_word:
            if gone in ps:
                ps.remove(gone)
        if gone in unpaired:
            unpaired.remove(gone)
        return per_word, unpaired, flat, facts

    with patched(build, "vision_pieces", dropped):
        return build.build_doc(_spec())


MUTANTS: dict[str, tuple[str, str, Callable[[], tuple[bytes, dict[str, Any]]]]] = {
    "drift-written-as-zero": (
        "drift",
        "the generator places the layer with drift 0; the parameters still say 8 pt",
        _drift_zero(),
    ),
    "render-mode-0": (
        "structure",
        "the layer is written in render mode 0 (visible) instead of 3",
        _render_mode_zero,
    ),
    "jpeg-quality-off": (
        "jpeg",
        "the page image is encoded at quality 10 below the stated one",
        _jpeg_quality_off,
    ),
    "ground-swapped": (
        "ground",
        "the heavy-noise ground is replaced by the clean ground",
        _ground_swapped,
    ),
    "ink-box-shifted": (
        "ink",
        "one word's recorded ink box is moved 3 px to the right",
        _ink_box_shifted,
    ),
    "layer-text-changed": (
        "layer",
        "one hidden word is written with a changed letter",
        _layer_text_changed,
    ),
    "misread-dropped": (
        "misread",
        "the misread surname is written with the printed spelling",
        _misread_dropped,
    ),
    "scenario-fact-emptied": (
        "scenarios",
        "one scenario's must_be_absent list is emptied",
        _scenario_fact_emptied,
    ),
}


def run_one(
    out: Path,
    name: str,
    make: Callable[[], tuple[bytes, dict[str, Any]]],
    tamper_manifest: bool = False,
    doc: str = DOC,
) -> dict[str, Any]:
    _current["doc"] = doc
    d = out / name
    pdf, exp = make()
    _write(d, pdf, exp, _spec())
    if tamper_manifest:
        m = json.loads((d / "manifest.json").read_text(encoding="ascii"))
        m["documents"][0]["sha256"] = "0" * 64
        (d / "manifest.json").write_bytes(build.json_bytes(m))
    manifest = verify_docs.load_json(d / "manifest.json")
    res = verify_docs.check_one(
        d, manifest["documents"][0], verify_docs.read_sums(d / "SHA256SUMS")
    )
    return {k: v["ok"] for k, v in res.checks.items()}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--record", type=Path)
    a = ap.parse_args()
    if a.out.exists() and any(a.out.iterdir()):
        sys.stderr.write(f"refusing to write into a non-empty directory: {a.out}\n")
        return 2
    rows = []
    control = run_one(a.out, "control", lambda: build.build_doc(_spec()))
    control_ok = all(v is not False for v in control.values())
    rows.append(
        {
            "mutant": "control",
            "target": None,
            "what": "no defect",
            "checks": control,
            "outcome": "green" if control_ok else "RED",
        }
    )
    control_v = run_one(a.out, "control-vision", lambda: build.build_doc(_spec()), doc=DOC_VISION)
    control_v_ok = all(v is not False for v in control_v.values())
    control_ok = control_ok and control_v_ok
    rows.append(
        {
            "mutant": "control-vision",
            "target": None,
            "what": f"no defect ({DOC_VISION})",
            "checks": control_v,
            "outcome": "green" if control_v_ok else "RED",
        }
    )
    plan = [(n, t, w, m, False, DOC) for n, (t, w, m) in MUTANTS.items()]
    plan.append(
        (
            "manifest-sha-changed",
            "checksums",
            "the manifest's SHA-256 for the document is changed",
            lambda: build.build_doc(_spec()),
            True,
            DOC,
        )
    )
    plan.append(
        (
            "vision-word-dropped",
            "vision",
            f"one recorded Vision word is left out of the layer ({DOC_VISION})",
            _vision_word_dropped,
            False,
            DOC_VISION,
        )
    )
    ok = control_ok
    for name, target, what, make, tamper, doc in plan:
        checks = run_one(a.out, name, make, tamper, doc)
        killed = checks.get(target) is False
        ok = ok and killed
        rows.append(
            {
                "mutant": name,
                "target": target,
                "what": what,
                "checks": checks,
                "outcome": "killed" if killed else "SURVIVED",
            }
        )
        sys.stdout.write(f"{'killed  ' if killed else 'SURVIVED'} {name} -> {target}\n")
    sys.stdout.write(
        f"control {'green' if control_ok else 'RED'}; {'all mutants killed' if ok else 'a mutant survived'}\n"
    )
    if a.record:
        a.record.write_bytes(build.json_bytes({"documents": [DOC, DOC_VISION], "rows": rows}))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
