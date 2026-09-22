"""pdfutil.py -- pypdf post-pass helpers shared by the statement, packet and capture-masters builders.

One definition of the default-font strip: the body is the packet builder's, byte-for-byte in effect
(the statement generator carried an identical copy). `variants._finalize` deliberately does not call it.
"""

from __future__ import annotations

import re

# reportlab emits an empty default-font (Helvetica) preamble at each page start; strip it so only the
# embedded-subset Inter survives (font hygiene shared by the statement, the packet and the masters).
_HELV_PREAMBLE = re.compile(rb"BT\s*/F1\s+12\s+Tf\s+14\.4\s+TL\s*ET")


def strip_default_helvetica(writer) -> None:
    from pypdf.generic import DecodedStreamObject, NullObject

    for page in writer.pages:
        res = page.get("/Resources")
        res = res.get_object() if res is not None else None
        fonts = res.get("/Font").get_object() if (res is not None and "/Font" in res) else None
        if fonts is not None and "/F1" in fonts:
            del fonts["/F1"]
        contents = page.get_contents()
        if contents is None:
            continue
        data = contents.get_data()
        new = _HELV_PREAMBLE.sub(b"", data)
        if new != data:
            obj = DecodedStreamObject()
            obj.set_data(new)
            page.replace_contents(obj)
    for idx, obj in enumerate(writer._objects):
        o = obj.get_object() if obj is not None else None
        try:
            is_helv = (
                o is not None
                and o.get("/Type") == "/Font"
                and "Helvetica" in str(o.get("/BaseFont", ""))
            )
        except AttributeError:
            is_helv = False
        if is_helv:
            writer._objects[idx] = NullObject()
