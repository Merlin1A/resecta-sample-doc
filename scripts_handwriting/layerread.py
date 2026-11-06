"""Decode a page's text layer in content-stream order through each font's ToUnicode map.

For every text-showing operator this gives: the font resource, the render mode, the text-space
origin of the show (PDF points, bottom-left origin), and the decoded string: each character code of
the shown string is looked up in the font's ``/ToUnicode`` CMap (``bfchar`` and ``bfrange``), with
codes one byte wide for a simple font and two bytes wide for a ``/Type0`` font. A code missing from
the map decodes to U+FFFD. Nothing here reorders, joins or normalises: the result is the layer
exactly as the bytes encode it.

Positions follow ``Tm``, ``Td``, ``TD``, ``T*``, ``'``, ``"`` and ``cm``, and form XObjects drawn
with ``Do`` are followed (with their own resources and ``/Matrix``) to ``MAX_FORM_DEPTH``. Advances
within a show are not tracked: each show reports where it starts.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from typing import Any

import pypdf
from pypdf.generic import ContentStream


@dataclass(frozen=True)
class Show:
    font: str
    render_mode: int
    x: float
    y: float
    text: str


def _hex(b: bytes) -> int:
    return int(b, 16)


def parse_cmap(data: bytes) -> tuple[dict[int, str], int]:
    """(code -> string, code width in bytes) from a ToUnicode CMap."""
    out: dict[int, str] = {}
    width = 1
    for m in re.finditer(rb"begincodespacerange(.*?)endcodespacerange", data, re.S):
        hexes = re.findall(rb"<([0-9A-Fa-f]+)>", m.group(1))
        if hexes:
            width = max(width, len(hexes[0]) // 2)
    for m in re.finditer(rb"beginbfchar(.*?)endbfchar", data, re.S):
        for src, dst in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]*)>", m.group(1)):
            out[_hex(src)] = bytes.fromhex(dst.decode("ascii")).decode("utf-16-be", "replace")
    for m in re.finditer(rb"beginbfrange(.*?)endbfrange", data, re.S):
        body = m.group(1)
        for lo, hi, rest in re.findall(
            rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*(\[[^\]]*\]|<[0-9A-Fa-f]*>)", body
        ):
            a, b = _hex(lo), _hex(hi)
            if rest.startswith(b"["):
                for i, d in enumerate(re.findall(rb"<([0-9A-Fa-f]*)>", rest)):
                    out[a + i] = bytes.fromhex(d.decode("ascii")).decode("utf-16-be", "replace")
            else:
                start = bytes.fromhex(rest.strip(b"<>").decode("ascii"))
                base = int.from_bytes(start, "big")
                for i in range(b - a + 1):
                    v = (base + i).to_bytes(len(start), "big")
                    out[a + i] = v.decode("utf-16-be", "replace")
    return out, width


def _fonts(container: Any) -> dict[str, tuple[dict[int, str], int]]:
    res = container.get("/Resources") or {}
    fonts = res.get("/Font") or {}
    out: dict[str, tuple[dict[int, str], int]] = {}
    for name, ref in fonts.items():
        f = ref.get_object()
        tu = f.get("/ToUnicode")
        width = 2 if f.get("/Subtype") == "/Type0" else 1
        if tu is None:
            out[str(name)] = ({}, width)
            continue
        cmap, w = parse_cmap(tu.get_object().get_data())
        out[str(name)] = (cmap, max(width, w) if width == 2 else 1)
    return out


def _decode(raw: bytes, cmap: dict[int, str], width: int) -> str:
    out = []
    for i in range(0, len(raw) - width + 1, width):
        code = int.from_bytes(raw[i : i + width], "big")
        out.append(cmap.get(code, "�"))
    return "".join(out)


def _raw(x: Any) -> bytes:
    b = getattr(x, "original_bytes", None)
    if b is not None:
        return bytes(b)
    return str(x).encode("latin-1", "replace")


def _mul(m: list[float], n: list[float]) -> list[float]:
    """m then n (the PDF row-vector convention: m x n)."""
    return [
        m[0] * n[0] + m[1] * n[2],
        m[0] * n[1] + m[1] * n[3],
        m[2] * n[0] + m[3] * n[2],
        m[2] * n[1] + m[3] * n[3],
        m[4] * n[0] + m[5] * n[2] + n[4],
        m[4] * n[1] + m[5] * n[3] + n[5],
    ]


MAX_FORM_DEPTH = 8


def _walk(
    container: Any, stream: Any, rd: pypdf.PdfReader, ctm0: list[float], out: list[Show], depth: int
) -> None:
    fonts = _fonts(container)
    res = container.get("/Resources") or {}
    xobjects = res.get("/XObject") or {}
    ops = ContentStream(stream, rd).operations
    font = ""
    tr = 0
    leading = 0.0
    tm = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
    tlm = list(tm)
    ctm = list(ctm0)
    stack: list[tuple[list[float], int]] = []

    def show(raw: bytes) -> None:
        cmap, width = fonts.get(font, ({}, 1))
        m = _mul(tm, ctm)
        out.append(Show(font, tr, round(m[4], 3), round(m[5], 3), _decode(raw, cmap, width)))

    def next_line() -> None:
        nonlocal tlm, tm
        tlm = _mul([1.0, 0.0, 0.0, 1.0, 0.0, -leading], tlm)
        tm = list(tlm)

    for operands, op in ops:
        if op == b"q":
            stack.append((list(ctm), tr))
        elif op == b"Q" and stack:
            ctm, tr = stack.pop()
        elif op == b"cm":
            ctm = _mul([float(v) for v in operands], ctm)
        elif op == b"Do" and depth < MAX_FORM_DEPTH:
            xo = xobjects.get(operands[0])
            xo = xo.get_object() if xo is not None else None
            if xo is not None and xo.get("/Subtype") == "/Form":
                m = [float(v) for v in xo.get("/Matrix", [1, 0, 0, 1, 0, 0])]
                _walk(xo, xo, rd, _mul(m, ctm), out, depth + 1)
        elif op == b"BT":
            tm = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
            tlm = list(tm)
        elif op == b"Tf":
            font = str(operands[0])
        elif op == b"Tr":
            tr = int(operands[0])
        elif op == b"TL":
            leading = float(operands[0])
        elif op == b"Tm":
            tm = [float(v) for v in operands]
            tlm = list(tm)
        elif op in (b"Td", b"TD"):
            tx, ty = float(operands[0]), float(operands[1])
            if op == b"TD":
                leading = -ty
            tlm = _mul([1.0, 0.0, 0.0, 1.0, tx, ty], tlm)
            tm = list(tlm)
        elif op == b"T*":
            next_line()
        elif op == b"Tj":
            show(_raw(operands[0]))
        elif op == b"TJ":
            show(
                b"".join(
                    _raw(x)
                    for x in operands[0]
                    if not isinstance(x, int | float) and hasattr(x, "original_bytes")
                )
            )
        elif op in (b"'", b'"'):
            next_line()
            show(_raw(operands[-1]))


def shows(pdf: bytes) -> list[Show]:
    rd = pypdf.PdfReader(io.BytesIO(pdf))
    page: Any = rd.pages[0]
    out: list[Show] = []
    _walk(page, page.get_contents(), rd, [1.0, 0.0, 0.0, 1.0, 0.0, 0.0], out, 0)
    return out


def embedded_fonts(pdf: bytes) -> list[str]:
    """The /BaseFont of every font resource on the first page and in the form XObjects it draws."""
    rd = pypdf.PdfReader(io.BytesIO(pdf))
    page: Any = rd.pages[0]
    names: set[str] = set()

    def visit(container: Any, depth: int) -> None:
        res = container.get("/Resources") or {}
        for ref in (res.get("/Font") or {}).values():
            names.add(str(ref.get_object().get("/BaseFont")))
        if depth < MAX_FORM_DEPTH:
            for ref in (res.get("/XObject") or {}).values():
                xo = ref.get_object()
                if xo.get("/Subtype") == "/Form":
                    visit(xo, depth + 1)

    visit(page, 0)
    return sorted(names)


def line_text(
    all_shows: list[Show],
    y: float,
    span: tuple[float, float],
    vertical_x: float | None = None,
    tol: float = 1.5,
    column: float = 14.0,
) -> str:
    """The decoded text of one laid-out line: the shows on its baseline and in its x span (for a
    vertical line, the shows within ``column`` of its centre x), in content order."""
    if vertical_x is not None:
        return "".join(s.text for s in all_shows if abs(s.x - vertical_x) <= column)
    return "".join(s.text for s in all_shows if abs(s.y - y) <= tol and span[0] <= s.x <= span[1])
