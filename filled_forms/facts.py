"""Read a form document's facts from its bytes (pypdf object walk).

The facts: the catalog's ``/AcroForm`` (present, ``/NeedAppearances``, ``/SigFlags``, ``/XFA``
packets, field count) and ``/NeedsRendering``; the page's printed text; every widget annotation
(fully qualified field name, field type, field flags, stored value, default value, options,
annotation flags, rectangle, appearance streams and states, current state, background colour, and
the strings its normal appearance draws); and every other annotation (subtype, rectangle,
contents). Values are kept as text: a name value is written with its leading slash.
"""

from __future__ import annotations

import io
from typing import Any

import pypdf
from pypdf.generic import ArrayObject, ContentStream, DictionaryObject, IndirectObject, NameObject

ANNOT_FLAG_NAMES = {
    1: "invisible",
    2: "hidden",
    4: "print",
    8: "nozoom",
    16: "norotate",
    32: "noview",
    64: "readonly",
    128: "locked",
}


def _get(d: Any, key: str, inherit: bool = True) -> Any:
    """``d[key]``, following ``/Parent`` for inheritable field attributes."""
    seen = 0
    while d is not None and seen < 32:
        if key in d:
            return d[key]
        if not inherit or "/Parent" not in d:
            return None
        d = d["/Parent"].get_object()
        seen += 1
    return None


def _fq_name(a: DictionaryObject) -> str | None:
    parts = []
    d: Any = a
    seen = 0
    while d is not None and seen < 32:
        if "/T" in d:
            parts.append(str(d["/T"]))
        d = d["/Parent"].get_object() if "/Parent" in d else None
        seen += 1
    return ".".join(reversed(parts)) if parts else None


def text_of(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, IndirectObject):
        v = v.get_object()
    if isinstance(v, ArrayObject):
        return [text_of(x) for x in v]
    return str(v)


def num4(x: Any) -> float:
    return round(float(x), 4)


def drawn_strings(stream: Any, reader: pypdf.PdfReader) -> list[str]:
    """The string operands of every text-showing operator in a content stream (latin-1 decoding of
    the bytes as written; glyph-coded strings come out as their byte values)."""
    out: list[str] = []
    try:
        ops = ContentStream(stream, reader).operations
    except Exception:
        return out
    for operands, op in ops:
        if op in (b"Tj", b"'", b'"'):
            out.append(_str(operands[-1]))
        elif op == b"TJ":
            out.append(
                "".join(
                    _str(x)
                    for x in operands[0]
                    if not isinstance(x, int | float) and hasattr(x, "original_bytes")
                )
            )
    return out


def _str(x: Any) -> str:
    b = getattr(x, "original_bytes", None)
    if b is None:
        return str(x)
    return bytes(b).decode("latin-1")


def clip_and_origin(stream: Any, reader: pypdf.PdfReader) -> dict[str, Any]:
    """The first clip rectangle (``re W n``), the text size (``Tf``) and the first text origin (``Td``)."""
    out: dict[str, Any] = {"clip": None, "size": None, "origin": None}
    try:
        ops = ContentStream(stream, reader).operations
    except Exception:
        return out
    last_re = None
    for operands, op in ops:
        if op == b"re":
            last_re = [num4(x) for x in operands]
        elif op == b"W" and out["clip"] is None and last_re is not None:
            out["clip"] = last_re
        elif op == b"Tf" and out["size"] is None:
            out["size"] = num4(operands[1])
        elif op == b"Td" and out["origin"] is None:
            out["origin"] = [num4(operands[0]), num4(operands[1])]
    return out


def _ap(a: DictionaryObject, reader: pypdf.PdfReader) -> dict[str, Any]:
    ap = a.get("/AP")
    if ap is None:
        return {"present": False}
    n = ap.get_object().get("/N")
    if n is None:
        return {"present": True, "normal": None}
    n = n.get_object()
    if isinstance(n, DictionaryObject) and "/Subtype" not in n and not hasattr(n, "get_data"):
        states = sorted(str(k) for k in n)
        state = text_of(a.get("/AS"))
        chosen = n.get(state) if state else None
        strings = drawn_strings(chosen.get_object(), reader) if chosen is not None else []
        return {"present": True, "normal": "states", "states": states, "drawn": strings}
    return {
        "present": True,
        "normal": "stream",
        "bbox": [num4(x) for x in n.get("/BBox", [])],
        "drawn": drawn_strings(n, reader),
        **clip_and_origin(n, reader),
    }


def _flags(f: int) -> list[str]:
    return [name for bit, name in ANNOT_FLAG_NAMES.items() if f & bit]


def _mk_bg(a: DictionaryObject) -> list[float] | None:
    mk = a.get("/MK")
    if mk is None:
        return None
    bg = mk.get_object().get("/BG")
    return None if bg is None else [num4(x) for x in bg]


def read(pdf: bytes) -> dict[str, Any]:
    r = pypdf.PdfReader(io.BytesIO(pdf))
    root: Any = r.trailer["/Root"]
    af = root.get("/AcroForm")
    af = af.get_object() if af is not None else None
    acro: dict[str, Any] = {"present": af is not None}
    if af is not None:
        xfa = af.get("/XFA")
        packets = None
        if xfa is not None:
            xfa = xfa.get_object()
            if isinstance(xfa, ArrayObject):
                packets = [str(xfa[i]) for i in range(0, len(xfa), 2)]
            else:
                packets = ["(single stream)"]
        acro.update(
            {
                "need_appearances": bool(af.get("/NeedAppearances", False)),
                "sig_flags": int(af.get("/SigFlags", 0)),
                "fields": len(af.get("/Fields", [])),
                "xfa_packets": packets,
            }
        )
    page: Any = r.pages[0]
    widgets = []
    others = []
    for ref in page.get("/Annots", []) or []:
        a = ref.get_object()
        rect = [num4(x) for x in a.get("/Rect", [])]
        if a.get("/Subtype") != "/Widget":
            others.append(
                {
                    "subtype": str(a.get("/Subtype")),
                    "rect": rect,
                    "contents": text_of(a.get("/Contents")),
                }
            )
            continue
        f = int(a.get("/F", 0))
        widgets.append(
            {
                "name": _fq_name(a),
                "ft": text_of(_get(a, "/FT")),
                "ff": int(_get(a, "/Ff") or 0),
                "value": text_of(_get(a, "/V")),
                "default": text_of(_get(a, "/DV")),
                "options": text_of(_get(a, "/Opt")),
                "annot_flags": f,
                "annot_flag_names": _flags(f),
                "rect": rect,
                "state": text_of(a.get("/AS")),
                "background": _mk_bg(a),
                "appearance": _ap(a, r),
            }
        )
    text = page.extract_text() or ""
    return {
        "pages": len(r.pages),
        "needs_rendering": bool(root.get("/NeedsRendering", False)),
        "acroform": acro,
        "widgets": widgets,
        "other_annotations": others,
        "page_text": text,
        "info": {
            k: str(val)
            for k, val in (r.metadata or {}).items()
            if not isinstance(val, NameObject) or True
        },
    }
