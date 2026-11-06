"""The fonts of the script and handwriting pages.

Sources: the Google Fonts catalogue (github.com/google/fonts) at ``SOURCE_COMMIT``, every file under
the SIL Open Font License 1.1 (``SOURCES`` gives each path and SHA-256). The source files are not
committed. ``prepare`` turns each Noto source into a committed subset, as follows:
- a static instance (weight 400, width 100) is made with fontTools' instancer;
- the instance is subset to the characters the pages use, keeping the layout tables that shaping
  needs (all features, all scripts);
- the family is renamed "<family> Subset", and every name record that holds a reserved font name is
  removed;
- the head timestamps are fixed, so the subset's bytes depend only on the source and fontTools.
The handwriting fonts (Caveat, Patrick Hand) are used unmodified, only to draw page pictures.

    .venv/bin/python -I scripts_handwriting/fonts.py prepare <font-source dir>
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fontTools import subset
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

HERE = Path(__file__).resolve().parent
FONT_DIR = HERE / "fonts"
SOURCE_COMMIT = "24ddc1f324cac5d9f5aedca126d298f56e3f1640"
SOURCE_URL = "https://raw.githubusercontent.com/google/fonts/" + SOURCE_COMMIT + "/ofl/{path}"
FIXED_TIME = 3_900_000_000  # head.created / head.modified, seconds since 1904 (a fixed value)
RESERVED_NAMES = ("Source",)

# key: (source path under ofl/, source SHA-256, family name of the subset)
SOURCES: dict[str, tuple[str, str, str]] = {
    "sc": (
        "notosanssc/NotoSansSC[wght].ttf",
        "a3041811a78c361b1de50f953c805e0244951c21c5bd412f7232ef0d899af0da",
        "Noto Sans SC Subset",
    ),
    "tc": (
        "notosanstc/NotoSansTC[wght].ttf",
        "864727d210d54f2537bbe23b3a839436c3992af72de9322af5270897246bd44f",
        "Noto Sans TC Subset",
    ),
    "jp": (
        "notosansjp/NotoSansJP[wght].ttf",
        "c2f3b4d463500a2ddcd3849cded1fceeb9fd6d1c32e6cbecd568453ba50fc68f",
        "Noto Sans JP Subset",
    ),
    "kr": (
        "notosanskr/NotoSansKR[wght].ttf",
        "194018e6b2b293a7964f037b25c0249ce1418bc9ab3c971060a03aa57861e252",
        "Noto Sans KR Subset",
    ),
    "arabic": (
        "notonaskharabic/NotoNaskhArabic[wght].ttf",
        "67b5a525a661b607971fbd3f96a81b89d3a768e74534fca84f18ac97e6fab72f",
        "Noto Naskh Arabic Subset",
    ),
    "hebrew": (
        "notosanshebrew/NotoSansHebrew[wdth,wght].ttf",
        "7ef36a2c3593758cdb622e1bdef4f84523e92fbc3ccc667438dd80ff54c2de88",
        "Noto Sans Hebrew Subset",
    ),
    "devanagari": (
        "notosansdevanagari/NotoSansDevanagari[wdth,wght].ttf",
        "14ec4af41f27482216d1c2229f417ff9b1425e1babb014e57d1d40d03229853e",
        "Noto Sans Devanagari Subset",
    ),
    "thai": (
        "notosansthai/NotoSansThai[wdth,wght].ttf",
        "5a1c559bb539583c8a1fd99d1c5b9491e5e14478c9cd2bd0970d5c3096cc9ef8",
        "Noto Sans Thai Subset",
    ),
    "latin": (
        "notosans/NotoSans[wdth,wght].ttf",
        "bfb7bb691513f12e734dc346c03a03f784912432d7e3fa8e56efcf906fe86b3d",
        "Noto Sans Subset",
    ),
}
HANDWRITING: dict[str, tuple[str, str]] = {
    "caveat": (
        "caveat/Caveat[wght].ttf",
        "0bdb6b660482d31531b3945849fba5916b3ef8695da7024a9e6b9ee3c4157988",
    ),
    "patrickhand": (
        "patrickhand/PatrickHand-Regular.ttf",
        "0f173b3e6cb6d1af25babf7f0057c5ac4ee11f9992b0469bb817e967ef4ad0fc",
    ),
}
SCRIPT_FONT = {
    "zh-Hans": "sc",
    "zh-Hant": "tc",
    "ja": "jp",
    "ko": "kr",
    "ar": "arabic",
    "he": "hebrew",
    "hi": "devanagari",
    "th": "thai",
    "el": "latin",
    "ru": "latin",
    "vi": "latin",
    "pl": "latin",
    "is": "latin",
}
ALWAYS = "".join(chr(c) for c in range(0x20, 0x7F)) + "\u2014\u2013"
# Arabic presentation forms: kept so each shaped (contextual) glyph has a character to map back to.
ARABIC_PRESENTATION = [*range(0xFB50, 0xFE00), *range(0xFE70, 0xFF00)]


def mixed_font(c: str) -> str:
    """The font of one character on the mixed-script page: Arabic letters, CJK ideographs, or Latin."""
    o = ord(c)
    if 0x0600 <= o <= 0x06FF:
        return "arabic"
    if 0x3000 <= o <= 0x9FFF or 0xFF00 <= o <= 0xFFEF:
        return "sc"
    return "latin"


def path_of(key: str) -> Path:
    return FONT_DIR / f"{key}-subset.ttf"


def handwriting_path(key: str) -> Path:
    return FONT_DIR / Path(HANDWRITING[key][0]).name


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def used_characters() -> dict[str, set[str]]:
    """The characters each subset must hold: every character of the lines and form rows drawn in it,
    plus ASCII digits and common punctuation."""
    from scripts_handwriting import texts

    need: dict[str, set[str]] = {k: set(ALWAYS) for k in SOURCES}
    for code, s in texts.scripts().items():
        chunks = (
            [ln.text for ln in s.lines] + [f"{a}: {b}" for a, b, *_ in texts.form_rows(s)]
            if s.labels
            else [ln.text for ln in s.lines]
        )
        text = "".join(chunks)
        if code == "mixed":
            for c in text:
                need[mixed_font(c)].add(c)
            continue
        need[SCRIPT_FONT[code]] |= set(text)
        need["latin"] |= {c for c in text if ord(c) < 0x250}
    for chars in need.values():
        chars.add("\u00a0")
    return need


def extra_codepoints(key: str) -> list[int]:
    return ARABIC_PRESENTATION if key == "arabic" else []


def _rename(font: TTFont, family: str) -> None:
    name = font["name"]
    name.names = [r for r in name.names if not any(rn in r.toUnicode() for rn in RESERVED_NAMES)]
    ps = family.replace(" ", "")
    for nid, value in (
        (1, family),
        (2, "Regular"),
        (3, f"{ps}-Regular;subset"),
        (4, f"{family} Regular"),
        (6, f"{ps}-Regular"),
        (16, family),
        (17, "Regular"),
    ):
        name.setName(value, nid, 3, 1, 0x409)
        name.setName(value, nid, 1, 0, 0)


def prepare(source_dir: Path) -> list[str]:
    FONT_DIR.mkdir(exist_ok=True)
    need = used_characters()
    out = []
    for key, (rel, sha, family) in SOURCES.items():
        src = source_dir / rel
        if _sha(src) != sha:
            raise SystemExit(f"{src}: SHA-256 differs from the recorded source")
        font = TTFont(str(src))
        if "fvar" in font:
            axes = {
                a.axisTag: (
                    400 if a.axisTag == "wght" else 100 if a.axisTag == "wdth" else a.defaultValue
                )
                for a in font["fvar"].axes
            }
            font = instancer.instantiateVariableFont(font, axes, updateFontNames=False)
        opts = subset.Options()
        opts.layout_features = ["*"]
        opts.layout_scripts = ["*"]
        opts.name_IDs = ["*"]
        opts.name_languages = ["*"]
        opts.notdef_outline = True
        opts.glyph_names = False
        opts.hinting = False
        opts.recalc_timestamp = False
        sub = subset.Subsetter(opts)
        sub.populate(text="".join(sorted(need[key])), unicodes=extra_codepoints(key))
        sub.subset(font)
        _rename(font, family)
        font["head"].created = FIXED_TIME
        font["head"].modified = FIXED_TIME
        font.recalcTimestamp = False
        dst = path_of(key)
        font.save(str(dst), reorderTables=True)
        missing = sorted(c for c in need[key] if ord(c) not in TTFont(str(dst)).getBestCmap())
        out.append(
            f"{dst.name}: {dst.stat().st_size} bytes, {len(need[key])} characters"
            + (f", missing {missing}" if missing else "")
        )
    for key, (rel, sha) in HANDWRITING.items():
        src = source_dir / rel
        if _sha(src) != sha:
            raise SystemExit(f"{src}: SHA-256 differs from the recorded source")
        handwriting_path(key).write_bytes(src.read_bytes())
        out.append(f"{handwriting_path(key).name}: unmodified copy")
    return out


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] != "prepare":
        sys.stderr.write(__doc__.split("\n\n")[-1] + "\n")
        return 2
    for line in prepare(Path(sys.argv[2])):
        sys.stdout.write(line + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
