"""The structure documents: unusual but valid files, files at and one past each named reader limit,
and malformed or hostile-shaped files. Every active element is inert: a script is a comment or an
empty function, a Launch action names a file that does not exist, an embedded file is a short
invented text.

Each ``Doc`` has an id, a group (``unusual``, ``limit-at``, ``limit-past``, ``malformed``), the
property it exercises as a sentence, and a ``make`` function returning the bytes and the property's
numbers (``facts``). ``verify_docs.py`` measures the same numbers again from the bytes alone.
"""

from __future__ import annotations

import hashlib
import io
import subprocess
import tempfile
import zlib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pymupdf
from PIL import Image, ImageDraw, ImageFont

from hidden_layer.rng import mix_seed, splitmix64

from . import rc4
from .pdfbytes import Obj, build, flate, next_free, simple_pages, text_content

HERE = Path(__file__).resolve().parent
RECORDED_DIR = HERE / "recorded"
INTER = HERE.parent / "fonts" / "Inter-Regular.ttf"

# The limits of the reader these files are measured against (named constants).
MAX_INPUT_BYTES = 52_428_800
MAX_OBJECTS = 100_000
MAX_STREAM_INFLATED_BYTES = 16_777_216
MAX_TOTAL_INFLATED_BYTES = 67_108_864
MAX_INFLATE_RATIO = 1_000
MAX_NESTING_DEPTH = 32
MAX_CONTENT_OPERATORS = 1_000_000
MAX_FORM_DEPTH = 8
MAX_PAGES = 2_000
MAX_IMAGE_PIXELS = 100_000_000
MAX_STRING_BYTES = 32_767
MAX_NAME_BYTES = 127
MAX_ARRAY_ELEMENTS = 8_191
MAX_DICTIONARY_ENTRIES = 4_095
MAX_GRAPHICS_STATE_DEPTH = 28
MAX_OPERANDS = 64
MAX_NUMBER_DIGITS = 18
MAX_NUMBER_SCALE = 18
MAX_WIDE_DIGITS = 36
MAX_WIDE_SCALE = 36

PAGE_TEXT = ["Synthetic structure test document.", "Every name and number on it is invented."]
BOMB_OUTPUT = 32 * 1024 * 1024
BOMB_ENCODED_MAX = 100 * 1024


@dataclass
class Doc:
    doc_id: str
    group: str
    property: str
    make: Callable[[], tuple[bytes, dict[str, Any]]]
    stored: str = "committed"
    tags: list[str] = field(default_factory=list)


def page(lines: list[str] | None = None) -> bytes:
    return text_content(lines or PAGE_TEXT)


def one_page(
    catalog_extra: bytes = b"",
    page_extra: bytes = b"",
    extra: list[Obj] | None = None,
    content: bytes | None = None,
) -> tuple[list[Obj], int]:
    return simple_pages(
        [content or page()],
        page_extra=[page_extra],
        catalog_extra=catalog_extra,
        extra_objects=extra,
    )


def low_ratio_data(n: int, seed: int) -> bytes:
    """``n`` bytes that deflate at roughly 50:1 to 200:1: runs of one value with a seeded byte
    every 128 bytes."""
    words = splitmix64(seed, (n + 127) // 128 + 1)
    out = bytearray(n)
    for i, w in enumerate(words):
        p = i * 128
        if p < n:
            out[p] = int(w) & 0xFF
    return bytes(out)


def _stream_obj(num: int, data: bytes, filt: bool = True, extra: bytes = b"") -> Obj:
    if filt:
        return Obj(num, stream=(b"<< /Filter /FlateDecode" + extra + b" >>", flate(data)))
    return Obj(num, stream=(b"<<" + extra + b" >>", data))


# ------------------------------------------------------------------------------------- unusual
def rotated(angle: int) -> Callable[[], tuple[bytes, dict[str, Any]]]:
    def make() -> tuple[bytes, dict[str, Any]]:
        objs, root = one_page(page_extra=f" /Rotate {angle}".encode("ascii"))
        return build(objs, root).data, {"rotate": angle, "inherited": False}

    return make


def rotate_inherited() -> tuple[bytes, dict[str, Any]]:
    objs, root = simple_pages([page()], pages_extra=b" /Rotate 90")
    return build(objs, root).data, {"rotate": 90, "inherited": True}


SIZES = [(595.276, 841.89), (612, 792), (841.89, 1190.551), (72, 72), (200, 2000)]


def mixed_sizes() -> tuple[bytes, dict[str, Any]]:
    objs, root = simple_pages(
        [page([f"Page {i + 1}"]) if w > 100 else b"" for i, (w, _) in enumerate(SIZES)], media=SIZES
    )
    return build(objs, root).data, {"media_boxes": [[0, 0, w, h] for w, h in SIZES]}


def scan(dpi: int) -> Callable[[], tuple[bytes, dict[str, Any]]]:
    def make() -> tuple[bytes, dict[str, Any]]:
        w, h = round(612 * dpi / 72), round(792 * dpi / 72)
        img = Image.new("L", (w, h), 250)
        f = ImageFont.truetype(str(INTER), 14 * dpi / 72)
        d = ImageDraw.Draw(img)
        for i, t in enumerate(PAGE_TEXT):
            d.text((72 * dpi / 72, (100 + 24 * i) * dpi / 72), t, font=f, fill=25)
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=80, dpi=(dpi, dpi), optimize=False)
        jpeg = buf.getvalue()
        content = b"q 612 0 0 792 0 0 cm /Im1 Do Q\n"
        objs = [
            Obj(1, b"<< /Type /Catalog /Pages 2 0 R >>"),
            Obj(2, b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>"),
            Obj(
                3,
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /XObject << /Im1 5 0 R >> >> /Contents 4 0 R >>",
            ),
            Obj(4, stream=(b"<< >>", content)),
            Obj(
                5,
                stream=(
                    f"<< /Type /XObject /Subtype /Image /Width {w} /Height {h} /ColorSpace /DeviceGray /BitsPerComponent 8 /Filter /DCTDecode >>".encode(
                        "ascii"
                    ),
                    jpeg,
                ),
            ),
        ]
        return build(objs, 1).data, {"image_px": [w, h], "dpi": dpi}

    return make


def white_on_white() -> tuple[bytes, dict[str, Any]]:
    content = b"1 g\n" + page()
    objs, root = one_page(content=content)
    return build(objs, root).data, {"fill_gray_before_text": 1.0, "text": " ".join(PAGE_TEXT)}


def object_streams() -> tuple[bytes, dict[str, Any]]:
    objs, root = one_page()
    base = build(objs, root).data
    with pymupdf.open(stream=base, filetype="pdf") as doc:
        out = doc.tobytes(garbage=4, deflate=True, use_objstms=1, no_new_id=True)
    return bytes(out), {"xref_stream": True, "object_streams_min": 1}


def incremental(revisions: int) -> Callable[[], tuple[bytes, dict[str, Any]]]:
    def make() -> tuple[bytes, dict[str, Any]]:
        objs, root = one_page()
        b = build(objs, root)
        data = bytearray(b.data)
        prev = b.xref_offset
        size = next_free(objs)
        for r in range(2, revisions + 1):
            content = page([f"Revision {r} of {revisions}.", *PAGE_TEXT])
            o = Obj(5, stream=(b"<< >>", content))
            off = len(data)
            data += o.serialize()
            xref = len(data)
            data += f"xref\n0 1\n0000000000 65535 f \n5 1\n{off:010d} 00000 n \n".encode("ascii")
            data += f"trailer\n<< /Size {size} /Root {root} 0 R /Prev {prev} >>\nstartxref\n{xref}\n%%EOF\n".encode(
                "ascii"
            )
            prev = xref
        return bytes(data), {"revisions": revisions, "eof_markers": revisions}

    return make


def linearized() -> tuple[bytes, dict[str, Any]]:
    """qpdf --linearize --deterministic-id, kept as written in ``recorded/`` (qpdf is not in CI)."""
    path = RECORDED_DIR / "st-unusual-linearized.pdf"
    return path.read_bytes(), {"linearized": True}


def record_linearized() -> str:
    RECORDED_DIR.mkdir(exist_ok=True)
    objs, root = simple_pages([page([f"Page {i + 1} of 3."]) for i in range(3)])
    with tempfile.TemporaryDirectory() as td:
        src, dst = Path(td) / "in.pdf", Path(td) / "out.pdf"
        src.write_bytes(build(objs, root).data)
        cmd = ["qpdf", "--linearize", "--deterministic-id", str(src), str(dst)]
        subprocess.run(cmd, check=True, capture_output=True)  # noqa: S603 - qpdf on PATH
        (RECORDED_DIR / "st-unusual-linearized.pdf").write_bytes(dst.read_bytes())
    cmd = ["qpdf", "--version"]
    ver = subprocess.run(cmd, check=True, capture_output=True, text=True).stdout.splitlines()[0]  # noqa: S603
    (RECORDED_DIR / "qpdf-version.txt").write_text(ver + "\n", encoding="ascii")
    return ver


def pdf20() -> tuple[bytes, dict[str, Any]]:
    objs, root = one_page()
    return build(objs, root, header=b"%PDF-2.0\n%\xe2\xe3\xcf\xd3\n").data, {"header": "%PDF-2.0"}


def tagged() -> tuple[bytes, dict[str, Any]]:
    content = b"/P << /MCID 0 >> BDC\n" + page() + b"EMC\n"
    extra = [
        Obj(6, b"<< /Type /StructTreeRoot /K 7 0 R /ParentTree 8 0 R >>"),
        Obj(7, b"<< /Type /StructElem /S /P /P 6 0 R /Pg 4 0 R /K 0 >>"),
        Obj(8, b"<< /Nums [0 [7 0 R]] >>"),
    ]
    objs, root = one_page(
        catalog_extra=b" /MarkInfo << /Marked true >> /StructTreeRoot 6 0 R",
        page_extra=b" /StructParents 0",
        extra=extra,
        content=content,
    )
    return build(objs, root).data, {"marked": True, "struct_elements": 1, "mcid": 0}


def optional_content_off() -> tuple[bytes, dict[str, Any]]:
    content = (
        page(["This line is always shown."])
        + b"/OC /oc1 BDC\n"
        + text_content(["This line is in a layer that starts switched off."], top=690)
        + b"EMC\n"
    )
    extra = [Obj(6, b"<< /Type /OCG /Name (Synthetic hidden layer) >>")]
    objs, root = one_page(
        catalog_extra=b" /OCProperties << /OCGs [6 0 R] /D << /OFF [6 0 R] /Order [6 0 R] >> >>",
        page_extra=b" /Properties << /oc1 6 0 R >>",
        extra=extra,
        content=content,
    )
    for o in objs:
        if o.num == 4 and o.body:
            o.body = o.body.replace(
                b"/Resources << /Font << /F1 3 0 R >> >>",
                b"/Resources << /Font << /F1 3 0 R >> /Properties << /oc1 6 0 R >> >>",
            )
    return build(objs, root).data, {"ocg_off": 1}


ATTACHMENT = b"Synthetic attachment for a structure test.\nNothing in it is real.\n"


def annotation_kinds() -> tuple[bytes, dict[str, Any]]:
    annots = [
        Obj(
            6,
            b"<< /Type /Annot /Subtype /Link /Rect [72 600 200 620] /Border [0 0 0] /A << /S /GoTo /D [4 0 R /Fit] >> >>",
        ),
        Obj(
            7,
            b"<< /Type /Annot /Subtype /Text /Rect [220 600 240 620] /Contents (A synthetic note.) /Name /Note >>",
        ),
        Obj(
            8,
            b"<< /Type /Annot /Subtype /Highlight /Rect [72 712 300 732] /QuadPoints [72 732 300 732 72 712 300 712] /C [1 1 0] >>",
        ),
        Obj(
            9,
            b"<< /Type /Annot /Subtype /Ink /Rect [72 500 300 580] /InkList [[80 520 120 560 160 510 200 570 240 530]] /C [0 0 1] >>",
        ),
        Obj(10, b"<< /Type /Annot /Subtype /Stamp /Rect [320 500 520 560] /Name /Approved >>"),
        Obj(
            11,
            b"<< /Type /Annot /Subtype /FileAttachment /Rect [72 440 92 460] /FS 12 0 R /Contents (A short invented text file.) /Name /Paperclip >>",
        ),
        Obj(
            12,
            b"<< /Type /Filespec /F (synthetic-note.txt) /UF (synthetic-note.txt) /EF << /F 13 0 R >> >>",
        ),
        Obj(
            13,
            stream=(
                f"<< /Type /EmbeddedFile /Params << /Size {len(ATTACHMENT)} >> >>".encode("ascii"),
                ATTACHMENT,
            ),
        ),
    ]
    objs, root = one_page(
        page_extra=b" /Annots [6 0 R 7 0 R 8 0 R 9 0 R 10 0 R 11 0 R]", extra=annots
    )
    return build(objs, root).data, {
        "annotation_subtypes": [
            "/Link",
            "/Text",
            "/Highlight",
            "/Ink",
            "/Stamp",
            "/FileAttachment",
        ],
        "attachment_sha256": hashlib.sha256(ATTACHMENT).hexdigest(),
    }


def many_pages(n: int) -> Callable[[], tuple[bytes, dict[str, Any]]]:
    def make() -> tuple[bytes, dict[str, Any]]:
        objs, root = simple_pages([page([f"Page {i + 1} of {n}."]) for i in range(n)])
        return build(objs, root).data, {"pages": n}

    return make


# --------------------------------------------------------------------------------------- limits
def input_bytes(total: int) -> Callable[[], tuple[bytes, dict[str, Any]]]:
    """A one-page file padded with an unfiltered, unreferenced stream to exactly ``total`` bytes."""

    def make() -> tuple[bytes, dict[str, Any]]:
        objs, root = one_page()
        pad_num = next_free(objs)
        pool = splitmix64(mix_seed("pad", total), total // 8 + 1).tobytes()
        fill = total - len(build([*objs, Obj(pad_num, stream=(b"<< >>", b""))], root).data)
        for _ in range(8):  # the /Length digits grow with the fill; a few passes settle it
            out = build([*objs, Obj(pad_num, stream=(b"<< >>", pool[:fill]))], root).data
            if len(out) == total:
                return out, {"bytes": total}
            fill -= len(out) - total
        raise ValueError(f"padding did not settle at {total}")

    return make


def objects(count: int) -> Callable[[], tuple[bytes, dict[str, Any]]]:
    def make() -> tuple[bytes, dict[str, Any]]:
        objs, root = one_page()
        start = next_free(objs)
        objs += [Obj(n, b"null") for n in range(start, count + 1)]
        return build(objs, root).data, {"objects": count}

    return make


def one_stream(size: int, seed: str) -> Callable[[], tuple[bytes, dict[str, Any]]]:
    def make() -> tuple[bytes, dict[str, Any]]:
        objs, root = one_page()
        objs.append(_stream_obj(next_free(objs), low_ratio_data(size, mix_seed(seed, size))))
        return build(objs, root).data, {"largest_inflated": size}

    return make


def total_streams(total: int, parts: int = 5) -> Callable[[], tuple[bytes, dict[str, Any]]]:
    """``parts`` streams, each under the per-stream and ratio limits, inflating to ``total`` in all."""

    def make() -> tuple[bytes, dict[str, Any]]:
        objs, root = one_page()
        base, rest = divmod(total, parts)
        sizes = [base + (1 if i < rest else 0) for i in range(parts)]
        n = next_free(objs)
        for i, s in enumerate(sizes):
            objs.append(_stream_obj(n + i, low_ratio_data(s, mix_seed("total", total, i))))
        return build(objs, root).data, {"stream_sizes": sizes, "total_inflated": sum(sizes)}

    return make


FOUND_START: dict[int, int] = {}
# Where the search for each ratio succeeds (found once; the search from here is immediate).
RATIO_START = {1000: 1_000_000, 1001: 1_233_226}


def exact_ratio_body(ratio: int, start: int | None = None) -> tuple[bytes, int]:
    """(an encoded zlib body, its inflated size) with inflated size exactly ``ratio`` times the
    body's size. The body is: the zlib header; ``n`` zero bytes deflated and sync-flushed; one final
    stored block of ``k`` zero bytes; the Adler-32 checksum. Its size is ``11 + d + k`` (``d`` the
    flushed deflate data) and its output ``n + k``, so ``k = (n - ratio * (11 + d)) / (ratio - 1)``
    is searched for an integer over ``n``."""
    begin = start if start is not None else RATIO_START.get(ratio, 1_000_000)
    for n in range(begin, begin + 400_000, 7):
        c = zlib.compressobj(9, zlib.DEFLATED, -15)
        d = c.compress(bytes(n)) + c.flush(zlib.Z_SYNC_FLUSH)
        num = n - ratio * (11 + len(d))
        if num < 0 or num % (ratio - 1):
            continue
        k = num // (ratio - 1)
        if k > 0xFFFF:
            continue
        header = b"\x78\xda"
        stored = b"\x01" + k.to_bytes(2, "little") + (k ^ 0xFFFF).to_bytes(2, "little") + bytes(k)
        body = header + d + stored + zlib.adler32(bytes(n + k)).to_bytes(4, "big")
        out = zlib.decompress(body)
        if len(out) == n + k and len(out) == ratio * len(body):
            FOUND_START[ratio] = n
            return body, len(out)
    raise ValueError(f"no exact {ratio}:1 body found")


def ratio_stream(ratio: int) -> Callable[[], tuple[bytes, dict[str, Any]]]:
    """A stream of zero bytes whose inflated size is exactly ``ratio`` times its encoded body
    (``exact_ratio_body``); no byte follows the checksum."""

    def make() -> tuple[bytes, dict[str, Any]]:
        body, out_len = exact_ratio_body(ratio)
        objs, root = one_page()
        objs.append(Obj(next_free(objs), stream=(b"<< /Filter /FlateDecode >>", body)))
        return build(objs, root).data, {"inflated": out_len, "encoded": len(body)}

    return make


def nesting(depth: int) -> Callable[[], tuple[bytes, dict[str, Any]]]:
    def make() -> tuple[bytes, dict[str, Any]]:
        body = b"[" * depth + b"0" + b"]" * depth
        extra = [Obj(6, body)]
        objs, root = one_page(catalog_extra=b" /NestingProbe 6 0 R", extra=extra)
        return build(objs, root).data, {"object": 6, "array_depth": depth}

    return make


def content_operators(count: int) -> Callable[[], tuple[bytes, dict[str, Any]]]:
    def make() -> tuple[bytes, dict[str, Any]]:
        text = page()
        text_ops = 3 + 2 * len(PAGE_TEXT)  # BT, Tf, a Tm and a Tj per line, ET
        fill = count - text_ops
        content = text + b"n\n" * fill
        objs, root = one_page(content=content)
        return build(objs, root).data, {"content_operators": count}

    return make


def form_depth(depth: int) -> Callable[[], tuple[bytes, dict[str, Any]]]:
    def make() -> tuple[bytes, dict[str, Any]]:
        extra = []
        first = 6
        for i in range(depth):
            num = first + i
            inner = f"/Fm{i + 1} Do\n".encode("ascii") if i + 1 < depth else page()
            res = (
                f" /Resources << /XObject << /Fm{i + 1} {num + 1} 0 R >> >>".encode("ascii")
                if i + 1 < depth
                else b" /Resources << /Font << /F1 3 0 R >> >>"
            )
            extra.append(
                Obj(
                    num,
                    stream=(
                        b"<< /Type /XObject /Subtype /Form /BBox [0 0 612 792]" + res + b" >>",
                        inner,
                    ),
                )
            )
        objs, root = one_page(content=b"/Fm0 Do\n", extra=extra)
        for o in objs:
            if o.num == 4 and o.body:
                o.body = o.body.replace(
                    b"/Resources << /Font << /F1 3 0 R >> >>",
                    b"/Resources << /Font << /F1 3 0 R >> /XObject << /Fm0 6 0 R >> >>",
                )
        return build(objs, root).data, {"form_depth": depth}

    return make


def image_pixels(w: int, h: int) -> Callable[[], tuple[bytes, dict[str, Any]]]:
    """A 1-bit image of ``w`` x ``h`` pixels whose rows hold seeded bits, so its stream stays under
    the per-stream and ratio limits."""

    def make() -> tuple[bytes, dict[str, Any]]:
        row = (w + 7) // 8
        raw = low_ratio_data(row * h, mix_seed("img", w, h))
        img = Obj(
            6,
            stream=(
                f"<< /Type /XObject /Subtype /Image /Width {w} /Height {h} /ColorSpace /DeviceGray /BitsPerComponent 1 /Filter /FlateDecode >>".encode(
                    "ascii"
                ),
                flate(raw),
            ),
        )
        content = b"q 540 0 0 540 36 126 cm /Im1 Do Q\n"
        objs, root = one_page(content=content, extra=[img])
        for o in objs:
            if o.num == 4 and o.body:
                o.body = o.body.replace(
                    b"/Resources << /Font << /F1 3 0 R >> >>",
                    b"/Resources << /XObject << /Im1 6 0 R >> >>",
                )
        return build(objs, root).data, {"width": w, "height": h, "pixels": w * h}

    return make


def string_bytes(n: int) -> Callable[[], tuple[bytes, dict[str, Any]]]:
    def make() -> tuple[bytes, dict[str, Any]]:
        s = (b"synthetic " * (n // 10 + 1))[:n]
        objs, root = one_page()
        objs.append(Obj(next_free(objs), b"<< /Title (" + s + b") >>"))
        return build(objs, root, info=next_free(objs) - 1).data, {"longest_string": n}

    return make


def name_bytes(n: int) -> Callable[[], tuple[bytes, dict[str, Any]]]:
    def make() -> tuple[bytes, dict[str, Any]]:
        name = (b"SyntheticName" * (n // 13 + 1))[:n]
        objs, root = one_page(catalog_extra=b" /" + name + b" true")
        return build(objs, root).data, {"longest_name": n}

    return make


def array_elements(n: int) -> Callable[[], tuple[bytes, dict[str, Any]]]:
    def make() -> tuple[bytes, dict[str, Any]]:
        body = b"[" + b" ".join(str(i % 10).encode("ascii") for i in range(n)) + b"]"
        objs, root = one_page(catalog_extra=b" /ArrayProbe 6 0 R", extra=[Obj(6, body)])
        return build(objs, root).data, {"object": 6, "array_elements": n}

    return make


def dictionary_entries(n: int) -> Callable[[], tuple[bytes, dict[str, Any]]]:
    def make() -> tuple[bytes, dict[str, Any]]:
        body = b"<<" + b"".join(f" /K{i} {i % 10}".encode("ascii") for i in range(n)) + b" >>"
        objs, root = one_page(catalog_extra=b" /DictProbe 6 0 R", extra=[Obj(6, body)])
        return build(objs, root).data, {"object": 6, "dictionary_entries": n}

    return make


def gstate_depth(n: int) -> Callable[[], tuple[bytes, dict[str, Any]]]:
    def make() -> tuple[bytes, dict[str, Any]]:
        content = b"q\n" * n + page() + b"Q\n" * n
        objs, root = one_page(content=content)
        return build(objs, root).data, {"graphics_state_depth": n}

    return make


def operands(n: int) -> Callable[[], tuple[bytes, dict[str, Any]]]:
    """One operator with ``n`` operands, inside a BX/EX compatibility section."""

    def make() -> tuple[bytes, dict[str, Any]]:
        content = page() + b"BX\n" + b" ".join(b"0" for _ in range(n)) + b" sc\nEX\n"
        objs, root = one_page(content=content)
        return build(objs, root).data, {"most_operands": n}

    return make


def number_digits(n: int) -> Callable[[], tuple[bytes, dict[str, Any]]]:
    def make() -> tuple[bytes, dict[str, Any]]:
        digits = ("123456789" * 3)[:n]
        objs, root = one_page(catalog_extra=b" /NumberProbe " + digits.encode("ascii"))
        return build(objs, root).data, {"number": digits, "significant_digits": n}

    return make


def number_scale(n: int) -> Callable[[], tuple[bytes, dict[str, Any]]]:
    def make() -> tuple[bytes, dict[str, Any]]:
        num = "0." + "0" * (n - 1) + "1"
        objs, root = one_page(catalog_extra=b" /NumberProbe " + num.encode("ascii"))
        return build(objs, root).data, {"number": num, "decimal_places": n}

    return make


WIDE_A = "123456789012345678"
WIDE_S = "0.000000000000000001"


def wide(kind: str, factors: int) -> Callable[[], tuple[bytes, dict[str, Any]]]:
    """``factors`` cm operators in a row whose first matrix entries multiply: 18-digit integers
    (``digits``) or numbers with 18 decimal places (``scale``)."""

    def make() -> tuple[bytes, dict[str, Any]]:
        v = WIDE_A if kind == "digits" else WIDE_S
        cms = b"".join(f"{v} 0 0 1 0 0 cm\n".encode("ascii") for _ in range(factors))
        content = b"q\n" + cms + b"Q\n" + page()
        objs, root = one_page(content=content)
        per = 18
        return build(objs, root).data, {
            "cm_operators": factors,
            "per_factor": per,
            "product_width": per * factors,
        }

    return make


# ------------------------------------------------------------------------------------ malformed
def xref_lies() -> tuple[bytes, dict[str, Any]]:
    objs, root = one_page()
    honest = build(objs, root)
    lie = honest.offsets[4] - 7
    b = build(objs, root, xref_offsets={4: lie})
    return b.data, {"object": 4, "table_offset": lie, "actual_offset": b.offsets[4], "delta": -7}


def length_lies(delta: int) -> Callable[[], tuple[bytes, dict[str, Any]]]:
    def make() -> tuple[bytes, dict[str, Any]]:
        objs, root = one_page()
        for o in objs:
            if o.num == 5:
                o.length_delta = delta
        b = build(objs, root)
        return b.data, {"object": 5, "length_delta": delta}

    return make


def trailer_missing() -> tuple[bytes, dict[str, Any]]:
    objs, root = one_page()
    b = build(objs, root, info=40)
    return b.data, {"info_reference": 40, "object_present": False}


def kids_cycle() -> tuple[bytes, dict[str, Any]]:
    objs, root = one_page()
    for o in objs:
        if o.num == 2:
            o.body = b"<< /Type /Pages /Kids [4 0 R 2 0 R] /Count 2 >>"
    return build(objs, root).data, {"pages_object": 2, "self_in_kids": True}


def next_cycle() -> tuple[bytes, dict[str, Any]]:
    extra = [
        Obj(6, b"<< /S /GoTo /D [4 0 R /Fit] /Next 7 0 R >>"),
        Obj(7, b"<< /S /GoTo /D [4 0 R /Fit] /Next 6 0 R >>"),
    ]
    objs, root = one_page(catalog_extra=b" /OpenAction 6 0 R", extra=extra)
    return build(objs, root).data, {"cycle": [6, 7]}


SHARED_CHAIN = 400
SHARED_LINKS = 400


def next_shared_chain() -> tuple[bytes, dict[str, Any]]:
    chain_start = 6
    extra = []
    for i in range(SHARED_CHAIN):
        nxt = f" /Next {chain_start + i + 1} 0 R" if i + 1 < SHARED_CHAIN else ""
        extra.append(Obj(chain_start + i, f"<< /S /GoTo /D [4 0 R /Fit]{nxt} >>".encode("ascii")))
    first_link = chain_start + SHARED_CHAIN
    for k in range(SHARED_LINKS):
        x = 72 + (k % 20) * 24
        y = 300 + (k // 20) * 16
        extra.append(
            Obj(
                first_link + k,
                f"<< /Type /Annot /Subtype /Link /Rect [{x} {y} {x + 20} {y + 12}] /Border [0 0 0] /A {chain_start} 0 R >>".encode(
                    "ascii"
                ),
            )
        )
    annots = " ".join(f"{first_link + k} 0 R" for k in range(SHARED_LINKS))
    objs, root = one_page(page_extra=f" /Annots [{annots}]".encode("ascii"), extra=extra)
    return build(objs, root).data, {
        "chain_length": SHARED_CHAIN,
        "links_sharing_it": SHARED_LINKS,
        "chain_head": chain_start,
    }


def duplicate_object() -> tuple[bytes, dict[str, Any]]:
    objs, root = one_page()
    decoy = Obj(
        5,
        stream=(
            b"<< >>",
            text_content(["This is the first object 5; the table points at the second."]),
        ),
    )
    objs.insert(3, decoy)
    b = build(objs, root)
    return b.data, {"object": 5, "copies": 2, "table_points_at_last": True}


def bytes_after_endstream() -> tuple[bytes, dict[str, Any]]:
    objs, root = one_page()
    data = build(objs, root).data
    marker = b"endstream\nendobj\n"
    i = data.index(marker)
    junk = b"JUNKBYTES\n"
    out = data[:i] + b"endstream\n" + junk + b"endobj\n" + data[i + len(marker) :]
    return _reindex(out), {"junk_after_endstream": len(junk)}


def _reindex(data: bytes) -> bytes:
    """Rewrite the cross-reference table so every offset is true again after an edit."""
    import re

    offsets = {int(m.group(1)): m.start() for m in re.finditer(rb"(?m)^(\d+) 0 obj", data)}
    xref = data.index(b"xref\n")
    size = max(offsets) + 1
    table = bytearray(f"xref\n0 {size}\n0000000000 65535 f \n".encode("ascii"))
    for n in range(1, size):
        table += (
            f"{offsets[n]:010d} 00000 n \n".encode("ascii")
            if n in offsets
            else b"0000000000 65535 f \n"
        )
    tr = data.index(b"trailer", xref)
    sx = data.index(b"startxref", tr)
    head = data[:xref]
    return head + bytes(table) + data[tr:sx] + f"startxref\n{len(head)}\n%%EOF\n".encode("ascii")


def after_eof() -> tuple[bytes, dict[str, Any]]:
    objs, root = one_page()
    junk = b"Synthetic bytes after the end-of-file marker.\n"
    return build(objs, root, tail=junk).data, {"bytes_after_eof": len(junk)}


def second_eof() -> tuple[bytes, dict[str, Any]]:
    objs, root = one_page()
    data = build(objs, root).data
    return data + b"%%EOF\n", {"eof_markers": 2}


def bounded_bomb() -> tuple[bytes, dict[str, Any]]:
    enc = flate(bytes(BOMB_OUTPUT))
    if len(enc) > BOMB_ENCODED_MAX:
        raise ValueError("bomb body too large")
    objs, root = one_page()
    objs.append(Obj(next_free(objs), stream=(b"<< /Filter /FlateDecode >>", enc)))
    data = build(objs, root).data
    return data, {"inflated": BOMB_OUTPUT, "encoded": len(enc)}


OWNER_PASSWORD = b"synthetic-owner-password"
FILE_ID = hashlib.md5(b"resecta-sample-doc structure rc4", usedforsecurity=False).digest()


def encrypted_empty_user() -> tuple[bytes, dict[str, Any]]:
    objs, root = one_page()
    o_entry, key = rc4.standard_r2(b"", OWNER_PASSWORD, FILE_ID, permissions=-4)
    for o in objs:
        if o.stream is not None:
            d, data = o.stream
            o.stream = (d, rc4.encrypt_object(key, o.num, o.gen, data))
    enc_num = next_free(objs)
    objs.append(
        Obj(
            enc_num,
            b"<< /Filter /Standard /V 1 /R 2 /O <"
            + o_entry.hex().encode("ascii")
            + b"> /U <"
            + rc4.u_entry(key).hex().encode("ascii")
            + b"> /P -4 >>",
        )
    )
    trailer = f" /Encrypt {enc_num} 0 R /ID [<{FILE_ID.hex()}> <{FILE_ID.hex()}>]".encode("ascii")
    return build(objs, root, trailer_extra=trailer).data, {
        "filter": "/Standard",
        "revision": 2,
        "user_password": "",
        "text": " ".join(PAGE_TEXT),
    }


INERT_JS = b"/* A synthetic test script. It does nothing. */ function inert() {}"
MISSING_FILE = "synthetic-file-that-does-not-exist.txt"


def active_elements() -> tuple[bytes, dict[str, Any]]:
    extra = [
        Obj(6, b"<< /Names [(inert) 7 0 R] >>"),
        Obj(7, b"<< /S /JavaScript /JS (" + INERT_JS + b") >>"),
        Obj(
            8,
            f"<< /Type /Annot /Subtype /Link /Rect [72 600 300 620] /Border [0 0 0] /A << /S /Launch /F ({MISSING_FILE}) >> >>".encode(
                "ascii"
            ),
        ),
    ]
    objs, root = one_page(
        catalog_extra=b" /Names << /JavaScript 6 0 R >> /OpenAction 7 0 R",
        page_extra=b" /Annots [8 0 R]",
        extra=extra,
    )
    return build(objs, root).data, {
        "javascript": INERT_JS.decode("ascii"),
        "open_action": "/JavaScript",
        "launch_file": MISSING_FILE,
        "embedded_files": 0,
    }


def docs() -> list[Doc]:
    d: list[Doc] = []
    u, la, lp, m = "unusual", "limit-at", "limit-past", "malformed"
    for a in (90, 180, 270):
        d.append(Doc(f"st-unusual-rotate-{a}", u, f"the one page has /Rotate {a}", rotated(a)))
    d += [
        Doc(
            "st-unusual-rotate-inherited",
            u,
            "the page has no /Rotate of its own; the Pages node it inherits from has /Rotate 90",
            rotate_inherited,
        ),
        Doc(
            "st-unusual-mixed-sizes",
            u,
            "five pages with media boxes A4, Letter, A3, 72 x 72 pt and 200 x 2000 pt",
            mixed_sizes,
        ),
        Doc(
            "st-unusual-scan-150dpi",
            u,
            "one page that is a 150 dpi picture (1275 x 1650 px)",
            scan(150),
        ),
        Doc(
            "st-unusual-scan-72dpi", u, "one page that is a 72 dpi picture (612 x 792 px)", scan(72)
        ),
        Doc(
            "st-unusual-white-on-white",
            u,
            "the page text is filled with white (1 g) on the white page",
            white_on_white,
        ),
        Doc(
            "st-unusual-object-streams",
            u,
            "the objects sit in object streams indexed by a cross-reference stream (PyMuPDF)",
            object_streams,
        ),
        Doc(
            "st-unusual-incremental-2",
            u,
            "an original and one incremental update: two cross-reference sections joined by /Prev, two %%EOF",
            incremental(2),
        ),
        Doc(
            "st-unusual-incremental-5",
            u,
            "an original and four incremental updates: five sections joined by /Prev, five %%EOF",
            incremental(5),
        ),
        Doc(
            "st-unusual-linearized",
            u,
            "a linearized file (qpdf --linearize --deterministic-id, kept as written)",
            linearized,
        ),
        Doc("st-unusual-pdf20", u, "the header declares PDF 2.0", pdf20),
        Doc(
            "st-unusual-tagged",
            u,
            "a tagged file: /MarkInfo /Marked true, a structure tree with one paragraph element bound to MCID 0",
            tagged,
        ),
        Doc(
            "st-unusual-optional-content-off",
            u,
            "one line sits in an optional-content group that the default configuration switches off",
            optional_content_off,
        ),
        Doc(
            "st-unusual-annotation-kinds",
            u,
            "a link, a text note, a highlight, an ink mark, a stamp and a file attachment holding a short invented text",
            annotation_kinds,
        ),
    ]
    limits: list[
        tuple[
            str,
            str,
            Callable[[], tuple[bytes, dict[str, Any]]],
            Callable[[], tuple[bytes, dict[str, Any]]],
            str,
        ]
    ] = [
        (
            "input-bytes",
            "the file is {} bytes long",
            input_bytes(MAX_INPUT_BYTES),
            input_bytes(MAX_INPUT_BYTES + 1),
            "local",
        ),
        (
            "objects",
            "the file holds {} objects",
            objects(MAX_OBJECTS),
            objects(MAX_OBJECTS + 1),
            "local",
        ),
        (
            "stream-inflated",
            "one stream inflates to {} bytes",
            one_stream(MAX_STREAM_INFLATED_BYTES, "one"),
            one_stream(MAX_STREAM_INFLATED_BYTES + 1, "one"),
            "committed",
        ),
        (
            "total-inflated",
            "five streams, each under the per-stream and ratio limits, inflate to {} bytes in all",
            total_streams(MAX_TOTAL_INFLATED_BYTES),
            total_streams(MAX_TOTAL_INFLATED_BYTES + 1),
            "local",
        ),
        (
            "inflate-ratio",
            "one stream inflates to exactly {} bytes per encoded byte",
            ratio_stream(MAX_INFLATE_RATIO),
            ratio_stream(MAX_INFLATE_RATIO + 1),
            "committed",
        ),
        (
            "nesting",
            "one array nests {} levels deep",
            nesting(MAX_NESTING_DEPTH),
            nesting(MAX_NESTING_DEPTH + 1),
            "committed",
        ),
        (
            "content-operators",
            "the content streams hold {} operators",
            content_operators(MAX_CONTENT_OPERATORS),
            content_operators(MAX_CONTENT_OPERATORS + 1),
            "local",
        ),
        (
            "form-depth",
            "form XObjects nest {} levels deep",
            form_depth(MAX_FORM_DEPTH),
            form_depth(MAX_FORM_DEPTH + 1),
            "committed",
        ),
        (
            "pages",
            "the file has {} pages",
            many_pages(MAX_PAGES),
            many_pages(MAX_PAGES + 1),
            "local",
        ),
        (
            "image-pixels",
            "one image has {} pixels",
            image_pixels(10_000, 10_000),
            image_pixels(100_000_001, 1),
            "committed",
        ),
        (
            "string-bytes",
            "one string holds {} bytes",
            string_bytes(MAX_STRING_BYTES),
            string_bytes(MAX_STRING_BYTES + 1),
            "committed",
        ),
        (
            "name-bytes",
            "one name holds {} bytes",
            name_bytes(MAX_NAME_BYTES),
            name_bytes(MAX_NAME_BYTES + 1),
            "committed",
        ),
        (
            "array-elements",
            "one array holds {} elements",
            array_elements(MAX_ARRAY_ELEMENTS),
            array_elements(MAX_ARRAY_ELEMENTS + 1),
            "committed",
        ),
        (
            "dictionary-entries",
            "one dictionary holds {} entries",
            dictionary_entries(MAX_DICTIONARY_ENTRIES),
            dictionary_entries(MAX_DICTIONARY_ENTRIES + 1),
            "committed",
        ),
        (
            "graphics-state-depth",
            "saved graphics states nest {} levels deep",
            gstate_depth(MAX_GRAPHICS_STATE_DEPTH),
            gstate_depth(MAX_GRAPHICS_STATE_DEPTH + 1),
            "committed",
        ),
        (
            "operands",
            "one content operator takes {} operands",
            operands(MAX_OPERANDS),
            operands(MAX_OPERANDS + 1),
            "committed",
        ),
        (
            "number-digits",
            "one number has {} significant digits",
            number_digits(MAX_NUMBER_DIGITS),
            number_digits(MAX_NUMBER_DIGITS + 1),
            "committed",
        ),
        (
            "number-scale",
            "one number has {} decimal places",
            number_scale(MAX_NUMBER_SCALE),
            number_scale(MAX_NUMBER_SCALE + 1),
            "committed",
        ),
        (
            "wide-digits",
            "chained cm operators whose first entries, multiplied, have {} significant digits",
            wide("digits", 2),
            wide("digits", 3),
            "committed",
        ),
        (
            "wide-scale",
            "chained cm operators whose first entries, multiplied, have {} decimal places",
            wide("scale", 2),
            wide("scale", 3),
            "committed",
        ),
    ]
    at_values = {
        "input-bytes": MAX_INPUT_BYTES,
        "objects": MAX_OBJECTS,
        "stream-inflated": MAX_STREAM_INFLATED_BYTES,
        "total-inflated": MAX_TOTAL_INFLATED_BYTES,
        "inflate-ratio": MAX_INFLATE_RATIO,
        "nesting": MAX_NESTING_DEPTH,
        "content-operators": MAX_CONTENT_OPERATORS,
        "form-depth": MAX_FORM_DEPTH,
        "pages": MAX_PAGES,
        "image-pixels": MAX_IMAGE_PIXELS,
        "string-bytes": MAX_STRING_BYTES,
        "name-bytes": MAX_NAME_BYTES,
        "array-elements": MAX_ARRAY_ELEMENTS,
        "dictionary-entries": MAX_DICTIONARY_ENTRIES,
        "graphics-state-depth": MAX_GRAPHICS_STATE_DEPTH,
        "operands": MAX_OPERANDS,
        "number-digits": MAX_NUMBER_DIGITS,
        "number-scale": MAX_NUMBER_SCALE,
        "wide-digits": MAX_WIDE_DIGITS,
        "wide-scale": MAX_WIDE_SCALE,
    }
    for name, sentence, at, past, stored in limits:
        v = at_values[name]
        past_v = 54 if name.startswith("wide") else v + 1
        past_stored = (
            "local"
            if name in ("total-inflated", "input-bytes", "objects", "content-operators", "pages")
            else stored
        )
        d.append(Doc(f"st-limit-{name}-at", la, sentence.format(f"{v:,}"), at, stored, [name]))
        d.append(
            Doc(
                f"st-limit-{name}-past",
                lp,
                sentence.format(f"{past_v:,}"),
                past,
                past_stored,
                [name],
            )
        )
    d += [
        Doc(
            "st-malformed-xref-offsets-lie",
            m,
            "the cross-reference entry for object 4 points 7 bytes before the object",
            xref_lies,
        ),
        Doc(
            "st-malformed-length-short",
            m,
            "the content stream's /Length is 40 bytes short of its endstream",
            length_lies(-40),
        ),
        Doc(
            "st-malformed-length-long",
            m,
            "the content stream's /Length runs 40 bytes past its endstream",
            length_lies(40),
        ),
        Doc(
            "st-malformed-trailer-missing-object",
            m,
            "the trailer's /Info points at object 40, which the file does not hold",
            trailer_missing,
        ),
        Doc(
            "st-malformed-kids-cycle", m, "the Pages node lists itself among its /Kids", kids_cycle
        ),
        Doc(
            "st-malformed-next-cycle",
            m,
            "the open action's /Next chain returns to itself after two actions (GoTo actions only)",
            next_cycle,
        ),
        Doc(
            "st-malformed-next-shared-chain",
            m,
            f"{SHARED_LINKS} link annotations share one /Next chain of {SHARED_CHAIN} GoTo actions",
            next_shared_chain,
        ),
        Doc(
            "st-malformed-duplicate-object",
            m,
            "object 5 appears twice, at two offsets; the table points at the second",
            duplicate_object,
        ),
        Doc(
            "st-malformed-bytes-after-endstream",
            m,
            "ten bytes sit between a stream's endstream and its endobj",
            bytes_after_endstream,
        ),
        Doc("st-malformed-bytes-after-eof", m, "bytes follow the final %%EOF marker", after_eof),
        Doc("st-malformed-second-eof", m, "a second %%EOF marker follows the first", second_eof),
        Doc(
            "st-malformed-bounded-bomb",
            m,
            f"one stream inflates to {BOMB_OUTPUT:,} bytes from under {BOMB_ENCODED_MAX // 1024} KiB (past the per-stream and ratio limits, under 64 MiB)",
            bounded_bomb,
        ),
        Doc(
            "st-malformed-encrypted-empty-user",
            m,
            "the file is RC4-encrypted (standard handler, revision 2) with an empty user password",
            encrypted_empty_user,
        ),
        Doc(
            "st-malformed-active-elements",
            m,
            "a document JavaScript that is a comment and an empty function, an open action that runs it, and a Launch action naming a file that does not exist",
            active_elements,
        ),
    ]
    return d
