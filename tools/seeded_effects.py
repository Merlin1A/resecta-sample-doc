"""seeded_effects.py -- what a planted row changed beyond the plant, by structural diff.

Compares a planted file with the base output it was planted into and lists every
structural change, each tagged `inherent` (the class cannot be planted without it)
or `artefact` (a mark of how it was planted, which Resecta's own writer never
leaves). A verifier finding that only an artefact explains is not a catch of the
class. The writer's grammar, as read from its outputs: one Flate content stream per
page; on a Searchable page one simple TrueType font with /Widths; on a Secure page
no font; one JPEG per page with its own quantisation tables, APP segments and
restart interval; a single trailer whose /ID is derived from the file's bytes.

Effects: contents_array · font_added · jpeg_reencoded · objects_added ·
catalog_keys_added · page_keys_added · annots_added · incremental_update ·
id_not_content_derived.
"""

from __future__ import annotations

import hashlib
import io
import re
from typing import Any

import numpy as np
import pymupdf
from PIL import Image, JpegImagePlugin

ID_RE = re.compile(rb"/ID\s*\[\s*<([0-9A-Fa-f]{32})>\s*<([0-9A-Fa-f]{32})>\s*\]")
# Plants that draw text: on a Secure page (no font of its own) a font with /Widths is inherent.
TEXT_CLASSES = {"O-01", "O-02", "O-03", "O-04", "O-15", "C-04"}
# Effects a class needs, whatever its plant mode (class or class/variant).
INHERENT: dict[str, set[str]] = {
    "O-04": {"objects_added"},
    "O-05": {"objects_added", "font_added"},
    "O-06": {"objects_added", "annots_added", "page_keys_added", "font_added"},
    "O-07": {
        "objects_added",
        "annots_added",
        "page_keys_added",
        "catalog_keys_added",
        "font_added",
    },
    "O-08/xmp-plain": {"objects_added", "catalog_keys_added"},
    "O-08/xmp-flate": {"objects_added", "catalog_keys_added"},
    "O-09/dead-object": {"objects_added"},
    "O-09/prior-revision": {"objects_added", "incremental_update"},
    "O-12": {"objects_added"},
    "O-13": {"objects_added", "catalog_keys_added", "page_keys_added"},
    "O-14": {
        "objects_added",
        "contents_array",
        "font_added",
        "jpeg_reencoded",
        "page_keys_added",
        "annots_added",
    },
}


def _id_content_derived(data: bytes) -> bool | None:
    tail = max(0, len(data) - 262_144)
    hits = list(ID_RE.finditer(data, tail))
    if len(hits) != 1:
        return None
    m = hits[0]
    a0, a1 = m.span(1)
    b0, b1 = m.span(2)
    z = b"0" * 32
    h = hashlib.sha256(data[:a0] + z + data[a1:b0] + z + data[b1:]).digest()[:16].hex()
    return data[a0:a1].decode().lower() == h and data[b0:b1].decode().lower() == h


def _jpeg_info(raw: bytes) -> dict[str, Any]:
    apps, dri, i = [], None, 2
    while i + 4 <= len(raw) and raw[i] == 0xFF:
        marker = raw[i + 1]
        if marker == 0xDA:
            break
        length = int.from_bytes(raw[i + 2 : i + 4], "big")
        if 0xE0 <= marker <= 0xEF:
            apps.append(f"APP{marker - 0xE0}")
        elif marker == 0xDD:
            dri = int.from_bytes(raw[i + 4 : i + 6], "big")
        i += 2 + length
    im = Image.open(io.BytesIO(raw))
    qtables = im.quantization if isinstance(im, JpegImagePlugin.JpegImageFile) else None
    return {"apps": apps, "dri": dri, "qtables": qtables, "image": im}


def _blocks_changed(a: Image.Image, b: Image.Image, block: int = 16, level: float = 2.0) -> float:
    """The share of block x block tiles whose mean absolute difference exceeds `level`."""
    if a.size != b.size:
        return 1.0
    x = np.asarray(a.convert("L"), dtype=np.int16)
    y = np.asarray(b.convert("L"), dtype=np.int16)
    h, w = (x.shape[0] // block) * block, (x.shape[1] // block) * block
    d = (
        np.abs(x[:h, :w] - y[:h, :w])
        .reshape(h // block, block, w // block, block)
        .mean(axis=(1, 3))
    )
    return round(float((d > level).mean()), 4)


def _keys(doc: pymupdf.Document, xref: int) -> set[str]:
    return set(doc.xref_get_keys(xref))


def _annot_count(doc: pymupdf.Document, page_xref: int) -> int:
    """Entries in the page's /Annots (widgets included), direct or indirect."""
    kind, value = doc.xref_get_key(page_xref, "Annots")
    if kind == "xref":
        value = doc.xref_object(int(value.split()[0]))
    elif kind != "array":
        return 0
    return len(re.findall(r"\d+\s+\d+\s+R", value))


def _font_has_widths(doc: pymupdf.Document, owner: int, xref: int, name: str) -> bool:
    """Whether a font states /Widths. An inline font (xref 0) is read through the
    resources of the object that uses it (the page, or a form XObject)."""
    if xref > 0:
        return doc.xref_get_key(xref, "Widths")[0] == "array"
    kind, val = doc.xref_get_key(owner, "Resources")
    holder, prefix = (int(val.split()[0]), "") if kind == "xref" else (owner, "Resources/")
    sub_kind, sub_val = doc.xref_get_key(holder, f"{prefix}Font")
    if sub_kind == "xref":
        return doc.xref_get_key(int(sub_val.split()[0]), f"{name}/Widths")[0] == "array"
    return doc.xref_get_key(holder, f"{prefix}Font/{name}/Widths")[0] == "array"


def side_effects(base: bytes, seeded: bytes, cls: str, variant: str, page_mode: str) -> list[dict]:
    """Every structural change from `base` to `seeded`, tagged inherent or artefact."""
    a = pymupdf.open(stream=base, filetype="pdf")
    b = pymupdf.open(stream=seeded, filetype="pdf")
    need = INHERENT.get(f"{cls}/{variant}", INHERENT.get(cls, set()))
    found: list[dict] = []

    def add(effect: str, detail: Any = None, kind: str | None = None) -> None:
        found.append(
            {
                "effect": effect,
                "detail": detail,
                "kind": kind or ("inherent" if effect in need else "artefact"),
            }
        )

    if seeded.count(b"%%EOF") > base.count(b"%%EOF"):
        add("incremental_update", {"eof": seeded.count(b"%%EOF")})
    if b.xref_length() > a.xref_length():
        add("objects_added", {"count": b.xref_length() - a.xref_length()})
    new_cat = sorted(_keys(b, b.pdf_catalog()) - _keys(a, a.pdf_catalog()))
    if new_cat:
        add("catalog_keys_added", new_cat)
    for pno in range(min(a.page_count, b.page_count)):
        pa, pb = a[pno], b[pno]
        was = a.xref_get_key(pa.xref, "Contents")[0]
        if b.xref_get_key(pb.xref, "Contents")[0] == "array" and was != "array":
            add("contents_array", {"page": pno})
        new_keys = sorted(_keys(b, pb.xref) - _keys(a, pa.xref))
        if new_keys:
            add("page_keys_added", {"page": pno, "keys": new_keys})
        if _annot_count(b, pb.xref) > _annot_count(a, pa.xref):
            add("annots_added", {"page": pno})
        fonts_a = {f[4] for f in pa.get_fonts(full=True)}
        for f in pb.get_fonts(full=True):
            if f[4] in fonts_a:
                continue
            widths = _font_has_widths(b, f[6] or pb.xref, f[0], f[4])
            kind = None
            if cls in TEXT_CLASSES:
                kind = "inherent" if page_mode == "s" and widths else "artefact"
            add("font_added", {"page": pno, "name": f[4], "subtype": f[2], "widths": widths}, kind)
        imgs_a = {x[0]: x for x in pa.get_images(full=True)}
        for x in pb.get_images(full=True):
            if x[0] not in imgs_a or x[8] != "DCTDecode":
                continue
            ra, rb = a.xref_stream_raw(x[0]), b.xref_stream_raw(x[0])
            if ra == rb:
                continue
            ia, ib = _jpeg_info(ra), _jpeg_info(rb)
            detail = {
                "page": pno,
                "app_dropped": [s for s in ia["apps"] if s not in ib["apps"]],
                "dri_dropped": ia["dri"] is not None and ib["dri"] != ia["dri"],
                "qtables_changed": ia["qtables"] != ib["qtables"],
                "blocks_changed": _blocks_changed(ia["image"], ib["image"]),
            }
            faithful = not (
                detail["app_dropped"] or detail["dri_dropped"] or detail["qtables_changed"]
            )
            add("jpeg_reencoded", detail, "inherent" if faithful else "artefact")
    derived = _id_content_derived(seeded)
    if derived is not True and _id_content_derived(base) is True:
        add("id_not_content_derived", {"single_pair": derived is not None})
    return found
