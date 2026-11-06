"""A small deterministic PDF writer: every object, offset and trailer key is chosen here, so a
document can hold one exact structural property, including a malformed one.

An object body is bytes; a stream is (dictionary bytes without ``/Length``, data). The writer
numbers objects as given, writes them in order, then a classic cross-reference table and trailer,
unless the caller asks otherwise. ``Built`` keeps every object's offset, so a fixture can state its
property in bytes ("the table's entry for object 4 points 7 bytes early").
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass, field

HEADER = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"
FONT = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"


@dataclass
class Obj:
    num: int
    body: bytes | None = None
    stream: tuple[bytes, bytes] | None = None  # (dictionary without /Length, data)
    gen: int = 0
    length_delta: int = 0  # added to the true /Length (a lying length when non-zero)

    def serialize(self) -> bytes:
        head = f"{self.num} {self.gen} obj\n".encode("ascii")
        if self.stream is not None:
            d, data = self.stream
            inner = d.strip()
            assert inner.startswith(b"<<") and inner.endswith(b">>")  # noqa: S101 - a writer invariant
            dict_bytes = inner[:-2] + f" /Length {len(data) + self.length_delta} >>".encode("ascii")
            return head + dict_bytes + b"\nstream\n" + data + b"\nendstream\nendobj\n"
        return head + (self.body or b"null") + b"\nendobj\n"


@dataclass
class Built:
    data: bytes
    offsets: dict[int, int] = field(default_factory=dict)
    xref_offset: int = 0


def build(
    objects: list[Obj],
    root: int,
    *,
    header: bytes = HEADER,
    trailer_extra: bytes = b"",
    info: int | None = None,
    xref_offsets: dict[int, int] | None = None,
    tail: bytes = b"",
) -> Built:
    """Serialize ``objects`` with a classic cross-reference table. ``xref_offsets`` overrides the
    offset written for an object (a lying table); ``tail`` is appended after ``%%EOF``."""
    out = bytearray(header)
    offsets: dict[int, int] = {}
    for o in objects:
        offsets[o.num] = len(out)  # a number written twice: the table points at the last copy
        out += o.serialize()
    xref = len(out)
    size = max(o.num for o in objects) + 1
    out += f"xref\n0 {size}\n0000000000 65535 f \n".encode("ascii")
    written = dict(offsets)
    if xref_offsets:
        written.update(xref_offsets)
    for n in range(1, size):
        if n in written:
            out += f"{written[n]:010d} 00000 n \n".encode("ascii")
        else:
            out += b"0000000000 65535 f \n"
    info_part = f" /Info {info} 0 R" if info else ""
    out += (
        f"trailer\n<< /Size {size} /Root {root} 0 R{info_part}".encode("ascii")
        + trailer_extra
        + b" >>\n"
    )
    out += f"startxref\n{xref}\n%%EOF\n".encode("ascii") + tail
    return Built(bytes(out), offsets, xref)


def fmt(x: float) -> str:
    """A number as written in the file: an integer without a point, otherwise its shortest exact
    decimal form (never rounded to fewer digits)."""
    if float(x).is_integer():
        return str(int(x))
    return repr(float(x))


def text_content(
    lines: list[str], size: int = 12, x: float = 72, top: float = 720, pitch: float = 18
) -> bytes:
    ops = ["BT", f"/F1 {size} Tf"]
    y = top
    for ln in lines:
        safe = ln.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        ops.append(f"1 0 0 1 {fmt(x)} {fmt(y)} Tm ({safe}) Tj")
        y -= pitch
    ops.append("ET")
    return ("\n".join(ops) + "\n").encode("latin-1")


def flate(data: bytes, level: int = 9) -> bytes:
    """zlib-wrapped deflate (RFC 1950), deterministic for a given zlib build and level."""
    return zlib.compress(data, level)


def simple_pages(
    contents: list[bytes],
    media: list[tuple[float, float]] | None = None,
    page_extra: list[bytes] | None = None,
    pages_extra: bytes = b"",
    catalog_extra: bytes = b"",
    extra_objects: list[Obj] | None = None,
    first_free: int | None = None,
) -> tuple[list[Obj], int]:
    """Catalog 1, Pages 2, font 3, then each page and its content; returns (objects, root)."""
    n = len(contents)
    media = media or [(612, 792)] * n
    page_extra = page_extra or [b""] * n
    objs = [Obj(3, FONT)]
    kids = []
    num = 4
    for i, c in enumerate(contents):
        w, h = media[i]
        kids.append(num)
        objs.append(
            Obj(
                num,
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {fmt(w)} {fmt(h)}] /Resources << /Font << /F1 3 0 R >> >> /Contents {num + 1} 0 R".encode(
                    "ascii"
                )
                + page_extra[i]
                + b" >>",
            )
        )
        objs.append(Obj(num + 1, stream=(b"<< >>", c)))
        num += 2
    kid_refs = " ".join(f"{k} 0 R" for k in kids)
    objs.insert(
        0,
        Obj(
            2,
            f"<< /Type /Pages /Kids [{kid_refs}] /Count {n}".encode("ascii") + pages_extra + b" >>",
        ),
    )
    objs.insert(0, Obj(1, b"<< /Type /Catalog /Pages 2 0 R" + catalog_extra + b" >>"))
    if extra_objects:
        objs.extend(extra_objects)
    del first_free
    return objs, 1


def next_free(objs: list[Obj]) -> int:
    return max(o.num for o in objs) + 1
