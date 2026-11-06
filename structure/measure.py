"""Measure a structure document's property from its bytes, without the code that wrote it.

A byte walk (``objects_at``, ``streams``, the classic table reader) for offsets, lengths and markers;
``zlib`` for inflate sizes; pypdf for page, annotation and content facts. Each ``measure_<kind>``
returns the same keys the document's ``facts`` record.
"""

from __future__ import annotations

import hashlib
import io
import re
import zlib
from typing import Any

import pypdf
from pypdf.generic import ContentStream

OBJ_RE = re.compile(rb"(?m)^(\d+) (\d+) obj\b")


def objects_at(data: bytes) -> list[tuple[int, int]]:
    """(object number, offset) of every ``N G obj`` at a line start, in file order."""
    return [(int(m.group(1)), m.start()) for m in OBJ_RE.finditer(data)]


def body_of(data: bytes, offset: int) -> bytes:
    end = data.find(b"endobj", offset)
    return data[offset:end]


def last_body(data: bytes, num: int) -> bytes:
    offs = [o for n, o in objects_at(data) if n == num]
    return body_of(data, offs[-1]) if offs else b""


def streams(data: bytes) -> list[dict[str, Any]]:
    """Every stream: its object, the declared /Length, the real distance to ``endstream``, the bytes
    between ``endstream`` and ``endobj``, whether it is Flate, and its body."""
    out = []
    for num, off in objects_at(data):
        end = data.find(b"endobj", off)
        seg = data[off:end]
        m = re.search(rb"stream\r?\n", seg)
        if not m or b"<<" not in seg[: m.start()]:
            continue
        start = off + m.end()
        es = data.rfind(b"endstream", start, end)
        if es < 0:
            continue
        real = es - start
        if data[es - 1 : es] == b"\n":
            real -= 1
        dict_part = seg[: m.start()]
        lm = re.search(rb"/Length (\d+)", dict_part)
        after = data[es + len(b"endstream") : end]
        out.append(
            {
                "object": num,
                "declared": int(lm.group(1)) if lm else None,
                "real": real,
                "after_endstream": after.strip(),
                "flate": b"/FlateDecode" in dict_part,
                "body": data[start : start + real],
                "dict": dict_part,
            }
        )
    return out


def inflate(body: bytes) -> tuple[int, int]:
    """(inflated size, bytes left after the zlib stream)."""
    d = zlib.decompressobj()
    total = 0
    chunk = body
    while chunk:
        out = d.decompress(chunk, 1 << 20)
        total += len(out)
        chunk = d.unconsumed_tail
    total += len(d.flush())
    return total, len(d.unused_data)


def classic_xref(data: bytes) -> dict[int, int]:
    """The last classic cross-reference table's in-use entries: object -> offset."""
    i = data.rfind(b"\nxref\n")
    out: dict[int, int] = {}
    if i < 0:
        return out
    lines = data[i + 6 :].split(b"\n")
    k = 0
    while k < len(lines) and not lines[k].startswith(b"trailer"):
        head = lines[k].split()
        if len(head) == 2:
            first, count = int(head[0]), int(head[1])
            for j in range(count):
                e = lines[k + 1 + j].split()
                if e[2] == b"n":
                    out[first + j] = int(e[0])
            k += count + 1
        else:
            k += 1
    return out


def reader(data: bytes, password: str | None = None) -> pypdf.PdfReader:
    r = pypdf.PdfReader(io.BytesIO(data), strict=False)
    if r.is_encrypted:
        r.decrypt(password or "")
    return r


def content_ops(r: pypdf.PdfReader) -> list[tuple[list[Any], bytes]]:
    """Every operator of every page content stream and of every form XObject they draw."""
    out: list[tuple[list[Any], bytes]] = []
    seen: set[int] = set()

    def visit(container: Any, stream: Any, depth: int) -> None:
        ops = ContentStream(stream, r).operations
        out.extend((list(a), op) for a, op in ops)
        if depth >= 16:
            return
        for ref in ((container.get("/Resources") or {}).get("/XObject") or {}).values():
            if getattr(ref, "idnum", None) in seen:
                continue
            seen.add(ref.idnum)
            xo = ref.get_object()
            if xo.get("/Subtype") == "/Form":
                visit(xo, xo, depth + 1)

    for p in r.pages:
        visit(p, p.get_contents(), 0)
    return out


def form_depth(r: pypdf.PdfReader) -> int:
    def depth(container: Any, d: int) -> int:
        best = d
        for ref in ((container.get("/Resources") or {}).get("/XObject") or {}).values():
            xo = ref.get_object()
            if xo.get("/Subtype") == "/Form" and d < 64:
                best = max(best, depth(xo, d + 1))
        return best

    return max(depth(p, 0) for p in r.pages)


def max_bracket_depth(body: bytes) -> int:
    d = best = 0
    for c in body:
        if c == 0x5B:
            d += 1
            best = max(best, d)
        elif c == 0x5D:
            d -= 1
    return best


def max_q_depth(ops: list[tuple[list[Any], bytes]]) -> int:
    d = best = 0
    for _, op in ops:
        if op == b"q":
            d += 1
            best = max(best, d)
        elif op == b"Q":
            d -= 1
    return best


def measure(kind: str, data: bytes, facts: dict[str, Any]) -> dict[str, Any]:  # noqa: PLR0911 - one branch per kind
    """The document's facts, measured again; ``kind`` names the property."""
    if kind == "rotate":
        page_body = last_body(data, 4)
        own = re.search(rb"/Rotate (\d+)", page_body)
        pages_own = re.search(rb"/Rotate (\d+)", last_body(data, 2))
        rot = int(own.group(1)) if own else int(pages_own.group(1)) if pages_own else 0
        return {"rotate": rot, "inherited": own is None and pages_own is not None}
    if kind == "media":
        r = reader(data)
        return {"media_boxes": [[round(float(v), 3) for v in p.mediabox] for p in r.pages]}
    if kind == "scan":
        im = streams(data)[-1]["dict"]
        w = int(re.search(rb"/Width (\d+)", im).group(1))  # type: ignore[union-attr]
        h = int(re.search(rb"/Height (\d+)", im).group(1))  # type: ignore[union-attr]
        return {"image_px": [w, h], "dpi": round(w * 72 / 612)}
    if kind == "white":
        r = reader(data)
        ops = content_ops(r)
        gray = next((float(a[0]) for a, op in ops if op == b"g"), None)
        text = " ".join(t.strip() for t in r.pages[0].extract_text().splitlines() if t.strip())
        return {"fill_gray_before_text": gray, "text": text}
    if kind == "objstm":
        r = reader(data)
        return {
            "xref_stream": b"/Type /XRef" in data or b"/Type/XRef" in data,
            "object_streams_min": min(1, len(re.findall(rb"/Type\s*/ObjStm", data)))
            if len(r.pages) == 1
            else 0,
        }
    if kind == "incremental":
        offset = int(data[data.rfind(b"startxref") :].split()[1])
        sections = 0
        while sections < 64:
            if data[offset : offset + 4] != b"xref":
                break
            sections += 1
            trailer = data[data.index(b"trailer", offset) : data.index(b"startxref", offset)]
            m = re.search(rb"/Prev (\d+)", trailer)
            if not m:
                break
            offset = int(m.group(1))
        return {"revisions": sections, "eof_markers": data.count(b"%%EOF")}
    if kind == "linearized":
        first = objects_at(data)[0][1]
        return {"linearized": b"/Linearized" in body_of(data, first)}
    if kind == "header":
        return {"header": data.split(b"\n", 1)[0].decode("latin-1")}
    if kind == "tagged":
        cat = last_body(data, 1)
        r = reader(data)
        mcid = next(
            (
                int(a[1]["/MCID"])
                for a, op in content_ops(r)
                if op == b"BDC" and len(a) > 1 and hasattr(a[1], "get") and "/MCID" in a[1]
            ),
            None,
        )
        return {
            "marked": b"/Marked true" in cat,
            "struct_elements": len(re.findall(rb"/Type /StructElem", data)),
            "mcid": mcid,
        }
    if kind == "ocg":
        cat = last_body(data, 1)
        m = re.search(rb"/OFF \[([^\]]*)\]", cat)
        return {"ocg_off": len(re.findall(rb"\d+ 0 R", m.group(1))) if m else 0}
    if kind == "annots":
        r = reader(data)
        annots: Any = r.pages[0]["/Annots"]
        subs = [str(a.get_object()["/Subtype"]) for a in annots]
        ef = next(s for s in streams(data) if b"/EmbeddedFile" in s["dict"])
        return {
            "annotation_subtypes": subs,
            "attachment_sha256": hashlib.sha256(ef["body"]).hexdigest(),
        }
    if kind == "pages":
        return {"pages": len(re.findall(rb"/Type /Page /", data))}
    if kind == "input-bytes":
        return {"bytes": len(data)}
    if kind == "objects":
        return {"objects": len(objects_at(data))}
    if kind == "stream-inflated":
        return {"largest_inflated": max(inflate(s["body"])[0] for s in streams(data) if s["flate"])}
    if kind == "total-inflated":
        sizes = [inflate(s["body"])[0] for s in streams(data) if s["flate"]]
        return {"stream_sizes": sizes, "total_inflated": sum(sizes)}
    if kind == "inflate-ratio":
        s = next(s for s in streams(data) if s["flate"])
        out, left = inflate(s["body"])
        if left:
            return {"inflated": out, "encoded": len(s["body"]), "trailing": left}
        return {"inflated": out, "encoded": len(s["body"])}
    if kind == "nesting":
        return {
            "object": facts["object"],
            "array_depth": max_bracket_depth(
                last_body(data, int(facts["object"])).split(b"obj", 1)[1]
            ),
        }
    if kind == "content-operators":
        return {"content_operators": len(content_ops(reader(data)))}
    if kind == "form-depth":
        return {"form_depth": form_depth(reader(data))}
    if kind == "image-pixels":
        d = next(s for s in streams(data) if b"/Subtype /Image" in s["dict"])["dict"]
        w = int(re.search(rb"/Width (\d+)", d).group(1))  # type: ignore[union-attr]
        h = int(re.search(rb"/Height (\d+)", d).group(1))  # type: ignore[union-attr]
        return {"width": w, "height": h, "pixels": w * h}
    if kind == "string-bytes":
        r = reader(data)
        info: Any = r.trailer["/Info"].get_object()
        title = info["/Title"]
        return {
            "longest_string": len(
                bytes(title.original_bytes)
                if hasattr(title, "original_bytes")
                else str(title).encode("latin-1")
            )
        }
    if kind == "name-bytes":
        names = re.findall(rb"/([A-Za-z0-9]+)", last_body(data, 1))
        return {"longest_name": max(len(n) for n in names)}
    if kind == "array-elements":
        arr: Any = reader(data).get_object(int(facts["object"]))
        return {"object": facts["object"], "array_elements": len(arr)}
    if kind == "dictionary-entries":
        dct: Any = reader(data).get_object(int(facts["object"]))
        return {"object": facts["object"], "dictionary_entries": len(dct)}
    if kind == "graphics-state-depth":
        return {"graphics_state_depth": max_q_depth(content_ops(reader(data)))}
    if kind == "operands":
        return {"most_operands": max(len(a) for a, _ in content_ops(reader(data)))}
    if kind == "number-digits":
        tok = re.search(rb"/NumberProbe ([0-9.]+)", last_body(data, 1)).group(1).decode("ascii")  # type: ignore[union-attr]
        return {"number": tok, "significant_digits": len(tok.replace(".", "").lstrip("0"))}
    if kind == "number-scale":
        tok = re.search(rb"/NumberProbe ([0-9.]+)", last_body(data, 1)).group(1).decode("ascii")  # type: ignore[union-attr]
        return {"number": tok, "decimal_places": len(tok.split(".", 1)[1]) if "." in tok else 0}
    if kind in ("wide-digits", "wide-scale"):
        cms = [a for a, op in content_ops(reader(data)) if op == b"cm"]
        firsts = [str(a[0]) for a in cms]
        per = max(
            len(f.replace(".", "").lstrip("0"))
            if kind == "wide-digits"
            else len(f.split(".", 1)[1])
            for f in firsts
        )
        return {"cm_operators": len(cms), "per_factor": per, "product_width": per * len(cms)}
    return measure_malformed(kind, data, facts)


def measure_malformed(kind: str, data: bytes, facts: dict[str, Any]) -> dict[str, Any]:  # noqa: PLR0911 - one branch per kind
    if kind == "xref-lies":
        num = int(facts["object"])
        table = classic_xref(data)[num]
        actual = next(o for n, o in objects_at(data) if n == num)
        return {
            "object": num,
            "table_offset": table,
            "actual_offset": actual,
            "delta": table - actual,
        }
    if kind == "length-lies":
        s = next(s for s in streams(data) if s["object"] == int(facts["object"]))
        return {"object": s["object"], "length_delta": s["declared"] - s["real"]}
    if kind == "trailer-missing":
        tr = data[data.rfind(b"trailer") :]
        ref = int(re.search(rb"/Info (\d+) 0 R", tr).group(1))  # type: ignore[union-attr]
        return {"info_reference": ref, "object_present": any(n == ref for n, _ in objects_at(data))}
    if kind == "kids-cycle":
        body = last_body(data, 2)
        kids = re.search(rb"/Kids \[([^\]]*)\]", body).group(1)  # type: ignore[union-attr]
        return {"pages_object": 2, "self_in_kids": b"2 0 R" in kids}
    if kind == "next-cycle":
        start = int(re.search(rb"/OpenAction (\d+) 0 R", last_body(data, 1)).group(1))  # type: ignore[union-attr]
        seen = []
        cur: int | None = start
        while cur is not None and cur not in seen:
            seen.append(cur)
            m = re.search(rb"/Next (\d+) 0 R", last_body(data, cur))
            cur = int(m.group(1)) if m else None
        return {"cycle": seen if cur is not None else []}
    if kind == "shared-chain":
        head = int(facts["chain_head"])
        length = 0
        cur = head
        while cur is not None and length < 100_000:
            length += 1
            m = re.search(rb"/Next (\d+) 0 R", last_body(data, cur))
            cur = int(m.group(1)) if m else None
        links = len(
            re.findall(rb"/Subtype /Link [^>]*/A " + str(head).encode("ascii") + rb" 0 R", data)
        )
        return {"chain_length": length, "links_sharing_it": links, "chain_head": head}
    if kind == "duplicate":
        num = int(facts["object"])
        offs = [o for n, o in objects_at(data) if n == num]
        return {
            "object": num,
            "copies": len(offs),
            "table_points_at_last": classic_xref(data).get(num) == offs[-1],
        }
    if kind == "after-endstream":
        junk = max(
            len(s["after_endstream"]) + (1 if s["after_endstream"] else 0) for s in streams(data)
        )
        return {"junk_after_endstream": junk}
    if kind == "after-eof":
        tail = data[data.rfind(b"%%EOF") + len(b"%%EOF\n") :]
        return {"bytes_after_eof": len(tail)}
    if kind == "second-eof":
        return {"eof_markers": data.count(b"%%EOF")}
    if kind == "bomb":
        s = max((s for s in streams(data) if s["flate"]), key=lambda s: len(s["body"]))
        return {"inflated": inflate(s["body"])[0], "encoded": len(s["body"])}
    if kind == "encrypted":
        r = pypdf.PdfReader(io.BytesIO(data))
        enc: Any = r.trailer["/Encrypt"].get_object()
        ids: Any = r.trailer["/ID"]
        ok = r.decrypt("")
        text = " ".join(t.strip() for t in r.pages[0].extract_text().splitlines() if t.strip())
        return {
            "filter": str(enc["/Filter"]),
            "v": int(enc["/V"]),
            "revision": int(enc["/R"]),
            "o": bytes(enc["/O"].original_bytes).hex(),
            "u": bytes(enc["/U"].original_bytes).hex(),
            "p": int(enc["/P"]),
            "id": bytes(ids[0].original_bytes).hex(),
            "user_password": "" if ok else None,
            "text": text,
        }
    if kind == "active":
        js = re.search(rb"/JS \((.*?)\) >>", data, re.S).group(1).decode("ascii")  # type: ignore[union-attr]
        oa = int(re.search(rb"/OpenAction (\d+) 0 R", last_body(data, 1)).group(1))  # type: ignore[union-attr]
        kind_oa = re.search(rb"/S (/\w+)", last_body(data, oa)).group(1).decode("ascii")  # type: ignore[union-attr]
        launch = re.search(rb"/S /Launch /F \(([^)]*)\)", data).group(1).decode("ascii")  # type: ignore[union-attr]
        return {
            "javascript": js,
            "open_action": kind_oa,
            "launch_file": launch,
            "embedded_files": len(re.findall(rb"/Type /EmbeddedFile", data)),
        }
    raise KeyError(kind)
