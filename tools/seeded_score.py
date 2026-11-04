"""seeded_score.py -- score verification verdicts against the seeded rows.

Joins three records per row: `row.json` (what was planted), the oracle summary
(`seeded_oracle.py`: is the planted value recoverable, by which non-Apple
leg) and the replay runner's `run.json` (the verification verdict, per layer).

Definitions (read from the app's share gate, not from layer internals):
  alarm         the Share tap asks before sending: overall fail or attention;
                overall skipped; a warn with a skipped layer or a
                could-not-verify layer; or the sweep's remaining-items lines.
                (The source-annotation confirm reads the SOURCE document and is
                not visible to a verdict-only replay; family rows that need it
                say so.)
  flagged       the sharp measure: a check itself raised the confirm (the alarm
                above without its possible-items line), or the sweep counts more
                possible items on the seeded file than on the same output before
                the plant. The possible-items line fires on most clean outputs
                (the sweep finds every unboxed number), so `alarm` alone does not
                separate a seeded file from its twin.
  checks_passed the results masthead reads "Checks Passed": overall pass or info.
  live          the oracle recovers the planted value from the seeded file by a
                reading leg (text, bytes, Tesseract, adversarial bytes) and not
                from its clean twin.
  pixel_only    not live, but the burned box shows light pixels the twin does not
                (px delta >= PX_LIVE): visible residue nobody read.
  dead          neither: the plant left nothing recoverable (a planter defect,
                excluded from rates and listed).

Rates per class carry a Wilson 95 % interval. Routes group the verifier's
checks by method: T (PDFKit text: text extraction, spatial, count, lineage,
search re-check), B (bytes and structure: binary search, structure, metadata,
fonts, operator re-extraction), V (Vision pixels: OCR check, detection sweep).
A route "catches" a row when one of its checks reads fail or attention. The
joint miss of two routes is P(both miss) over live rows, reported beside the
product of the two marginal miss rates (their ratio > 1 means the two routes
fail together more often than independent checks would).

Usage: .venv/bin/python -I tools/seeded_score.py --rows DIR --oracle FILE
       --runs DIR [--runs2 DIR] --emit DIR --out DIR
       [--write-expected FILE [--version N] [--known FILE]]
       [--gate EXPECTED [--prereg FILE]]

Gate mode (`--gate`) reads this run against an expected table written by
`--write-expected` from a baseline run. Each live cell (and each control) reads
IDENTICAL, REBASELINED, DELTA, FLAKY, HARNESS RED or one of the RED readings
(see `gate`); the run reads GREEN (exit 0), RED (exit 1) or HARNESS RED (exit 3).
A prereg line is `<cell glob> field=value ...` over flagged, overall, headline, tier.
"""

from __future__ import annotations

import argparse
import fnmatch
import itertools
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

PX_LIVE = 0.05
ROUTES = {
    "T": {
        "textExtraction",
        "spatialVerification",
        "characterCount",
        "characterLineage",
        "searchRecheck",
    },
    "B": {
        "binaryStringSearch",
        "structureCheck",
        "metadataCheck",
        "fontVerification",
        "operatorReExtraction",
    },
    "V": {"ocrCheck", "detectionSweep"},
}
FLAGGING = {"fail", "attention"}


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(max(0.0, c - h), 3), round(min(1.0, c + h), 3))


def alarm(run: dict[str, Any]) -> bool:
    o = run["overall"]
    layers = run["layers"]
    if o in ("fail", "attention", "skipped"):
        return True
    if o == "warn" and any(
        lay["status"] == "skipped" or (lay["status"] == "warn" and lay["could_not_verify"])
        for lay in layers
    ):
        return True
    return any(
        lay["layer"] == "detectionSweep" and lay["status"] == "info" and lay.get("has_query_lines")
        for lay in layers
    )


def alarm_checks(run: dict[str, Any]) -> bool:
    """The share confirms raised by the checks themselves (no possible-items line)."""
    o = run["overall"]
    if o in ("fail", "attention", "skipped"):
        return True
    return o == "warn" and any(
        lay["status"] == "skipped" or (lay["status"] == "warn" and lay["could_not_verify"])
        for lay in run["layers"]
    )


SWEEP_RE = re.compile(r"(\d+) possible items? remains?")


def sweep_items(report_path: Path) -> int | None:
    """The sweep's possible-item count on one output (0 when it reports none)."""
    if not report_path.exists():
        return None
    for lay in json.loads(report_path.read_text()).get("layers", []):
        if lay.get("name") == "Detection Sweep":
            m = SWEEP_RE.search(lay.get("detail", ""))
            return int(m.group(1)) if m else 0
    return None


def routes_caught(run: dict[str, Any]) -> dict[str, bool]:
    return {
        r: any(lay["layer"] in names and lay["status"] in FLAGGING for lay in run["layers"])
        for r, names in ROUTES.items()
    }


def flagging_layers(run: dict[str, Any]) -> list[str]:
    return [
        f"{lay['layer']}={lay['status']}"
        for lay in run["layers"]
        if lay["status"] not in ("pass", "info", "not_applicable")
    ]


def load_runs(d: Path) -> dict[str, dict]:
    return {p.parent.name: json.loads(p.read_text()) for p in d.glob("rows/*/run.json")}


GATE_FIELDS = ("flagged", "overall", "headline", "tier")
EXIT = {"GREEN": 0, "RED": 1, "HARNESS RED": 3}


def read_known(path: Path | None) -> set[str]:
    """`class/variant` per line (e.g. `O-09/dead-object`); `#` starts a comment."""
    if path is None:
        return set()
    lines = (ln.split("#", 1)[0].strip() for ln in path.read_text().splitlines())
    return {ln for ln in lines if ln}


def read_prereg(path: Path | None) -> list[tuple[str, dict[str, Any]]]:
    """`<cell glob> field=value ...` per line; values parse as JSON, else as strings."""
    out: list[tuple[str, dict[str, Any]]] = []
    if path is None:
        return out
    for raw in path.read_text().splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        glob, *pairs = line.split()
        want: dict[str, Any] = {}
        for pair in pairs:
            key, _, val = pair.partition("=")
            if key not in GATE_FIELDS or not val:
                raise SystemExit(f"prereg: bad field in {raw!r} (fields: {', '.join(GATE_FIELDS)})")
            try:
                want[key] = json.loads(val)
            except json.JSONDecodeError:
                want[key] = val
        if not want:
            raise SystemExit(f"prereg: no field=value in {raw!r}")
        out.append((glob, want))
    return out


def observed(s: dict[str, Any]) -> dict[str, Any]:
    return {
        "flagged": s["flagged"],
        "overall": s["overall"],
        "headline": s.get("headline"),
        "tier": s.get("tier"),
    }


def expected_table(
    scored: list[dict[str, Any]], emit: Path, known: set[str], version: int, written_from: str
) -> dict[str, Any]:
    """The gate's expected-vN table from one scored run (every row with a verdict)."""
    outputs = {}
    for rp in sorted(emit.glob("bases/*/replay.json")):
        outputs[rp.parent.name] = json.loads(rp.read_text()).get("output_sha256")
    cells = {}
    for s in scored:
        if "overall" not in s:
            continue
        cv = f"{s['class']}/{s.get('variant')}"
        cells[f"lh/{s['row_id']}"] = {
            "class": s["class"],
            "variant": s.get("variant"),
            "base": s.get("base_id"),
            "mode": s.get("mode"),
            "leak": s["leak"],
            "expect": observed(s),
            "known": cv in known,
        }
    return {
        "schema": 1,
        "version": version,
        "written_from": written_from,
        "baseline": {"base_outputs": outputs},
        "cells": cells,
    }


def gate(
    scored: list[dict[str, Any]],
    table: dict[str, Any],
    prereg: list[tuple[str, dict[str, Any]]],
) -> tuple[str, list[dict[str, Any]]]:
    """Read every live expected cell against this run. Returns (verdict, per-cell readings).

    IDENTICAL · REBASELINED (the delta is exactly a prereg line's) · DELTA (a known
    blind spot now flags, and a prereg line names it) · RED lost (a must-flag cell
    no longer flags) · RED control (a C- control now flags) · RED unexplained · RED
    prereg unmet (a named cell did not move) · RED missing (no verdict) · FLAKY (run 2
    disagrees) · HARNESS RED (a cell the table has live is no longer live).
    """
    by_id = {f"lh/{s['row_id']}": s for s in scored}
    readings = []
    for cid, cell in sorted(table["cells"].items()):
        if cell["leak"] != "live" and not cell["class"].startswith("C-"):
            continue
        s = by_id.get(cid)
        rules = [want for glob, want in prereg if fnmatch.fnmatchcase(cid, glob)]
        exp = cell["expect"]
        if s is None or "overall" not in s:
            reading = "RED missing"
        elif cell["leak"] == "live" and s["leak"] != "live":
            reading = "HARNESS RED"
        elif s.get("overall_run2") is not None and s["overall_run2"] != s["overall"]:
            reading = "FLAKY"
        else:
            obs = observed(s)
            diff = {k for k in GATE_FIELDS if exp.get(k) is not None and obs[k] != exp[k]}
            if not diff:
                reading = "RED prereg unmet" if rules else "IDENTICAL"
            elif any(all(obs.get(k) == v for k, v in want.items()) for want in rules):
                reading = "DELTA" if cell["known"] and obs["flagged"] else "REBASELINED"
            elif cell["class"].startswith("C-") and obs["flagged"]:
                reading = "RED control"
            elif exp["flagged"] and not cell["known"] and not obs["flagged"]:
                reading = "RED lost"
            else:
                reading = "RED unexplained"
        readings.append({"cell": cid, "reading": reading, "known": cell["known"]})
    words = {r["reading"] for r in readings}
    if "HARNESS RED" in words:
        verdict = "HARNESS RED"
    elif any(w.startswith("RED") or w == "FLAKY" for w in words):
        verdict = "RED"
    else:
        verdict = "GREEN"
    return verdict, readings


def is_faithful(row: dict[str, Any]) -> bool:
    """A row planted in the grammar-faithful mode (its id ends in `.f`)."""
    return str(row.get("row_id", "")).endswith(".f")


def routes_joint(live: list[dict[str, Any]]) -> dict[str, Any]:
    """P(both miss) per pair of routes over live rows, beside the product of the marginals."""
    joint: dict[str, Any] = {}
    n = len(live)
    for a, b in itertools.combinations("TBV", 2):
        if n == 0:
            break
        ma = sum(1 for s in live if not s["routes"][a]) / n
        mb = sum(1 for s in live if not s["routes"][b]) / n
        both = sum(1 for s in live if not s["routes"][a] and not s["routes"][b]) / n
        joint[f"{a}{b}"] = {
            "miss_a": round(ma, 3),
            "miss_b": round(mb, 3),
            "both_miss": round(both, 3),
            "independent_product": round(ma * mb, 3),
            "ratio": round(both / (ma * mb), 2) if ma * mb > 0 else None,
        }
    return joint


def fidelity(scored: list[dict[str, Any]]) -> dict[str, Any]:
    """Legacy vs grammar-faithful rows of the same plant (ids equal but for `.f`).

    Per class/variant: live rows and flagged rows in each mode, and `artefact_only`:
    pairs where the legacy row is flagged and its faithful twin, also live, is not
    (a catch only the legacy planter's marks explain). The routes' joint miss is
    reported on the faithful live rows."""
    rows = [s for s in scored if "overall" in s and s.get("leak") == "live"]
    legacy = {s["row_id"]: s for s in rows if not is_faithful(s)}
    faithful = {s["row_id"].removesuffix(".f"): s for s in rows if is_faithful(s)}
    out: dict[str, dict[str, int]] = {}
    for s in rows:
        cv = f"{s['class']}/{s.get('variant')}"
        c = out.setdefault(
            cv,
            {
                "live_legacy": 0,
                "caught_legacy": 0,
                "live_faithful": 0,
                "caught_faithful": 0,
                "artefact_only": 0,
            },
        )
        side = "faithful" if is_faithful(s) else "legacy"
        c[f"live_{side}"] += 1
        c[f"caught_{side}"] += bool(s["flagged"])
    for rid, s in legacy.items():
        twin = faithful.get(rid)
        if s["flagged"] and twin is not None and not twin["flagged"]:
            out[f"{s['class']}/{s.get('variant')}"]["artefact_only"] += 1
    return {
        "pairs": sum(1 for rid in legacy if rid in faithful),
        "by_class_variant": dict(sorted(out.items())),
        "routes_joint_miss_faithful": routes_joint(
            [s for s in faithful.values() if s["class"].startswith("O")]
        ),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", required=True, type=Path)
    ap.add_argument("--oracle", required=True, type=Path)
    ap.add_argument("--runs", required=True, type=Path)
    ap.add_argument("--runs2", type=Path)
    ap.add_argument("--emit", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--write-expected", type=Path, help="write the gate's expected table here")
    ap.add_argument("--version", type=int, default=1, help="the expected table's version")
    ap.add_argument("--known", type=Path, help="the ruled blind-spot list (class/variant lines)")
    ap.add_argument(
        "--expected-from",
        choices=("legacy", "faithful"),
        default="legacy",
        help="which plant mode's rows the expected table is written from",
    )
    ap.add_argument("--gate", type=Path, help="read this run against an expected table")
    ap.add_argument("--prereg", type=Path, help="pre-registered deltas for --gate")
    args = ap.parse_args()
    rows = {
        json.loads(p.read_text())["row_id"]: json.loads(p.read_text())
        for p in args.rows.glob("*/row.json")
    }
    oracle = {s["row_id"]: s for s in json.loads(args.oracle.read_text())["rows"]}
    runs = load_runs(args.runs)
    runs2 = load_runs(args.runs2) if args.runs2 else {}

    scored: list[dict[str, Any]] = []
    for rid, row in sorted(rows.items()):
        run = runs.get(rid)
        orc = oracle.get(rid, {})
        if run is None or run.get("error"):
            scored.append(
                {
                    "row_id": rid,
                    "class": row["class"],
                    "state": "no-verdict",
                    "error": (run or {}).get("error"),
                }
            )
            continue
        px = orc.get("px_delta")
        if orc.get("live"):
            leak = "live"
        elif px is not None and px >= PX_LIVE:
            leak = "pixel_only"
        else:
            leak = "dead"
        rec = {
            "row_id": rid,
            "class": row["class"],
            "variant": row["variant"],
            "base_id": row["base_id"],
            "mode": row["mode"],
            "page_mode": row["page_mode"],
            "digest": row["digest"],
            "surface": row["needle"]["surface"],
            "expect_catch": row["expect_catch"],
            "leak": leak,
            "live_legs": orc.get("live_legs"),
            "px_delta": px,
            "overall": run["overall"],
            "alarm": alarm(run),
            "alarm_checks": alarm_checks(run),
            "sweep_items": sweep_items(args.runs / "rows" / rid / "report.json"),
            "sweep_items_base": sweep_items(args.emit / "bases" / row["base_id"] / "report.json"),
            "checks_passed": run["overall"] in ("pass", "info"),
            "routes": routes_caught(run),
            "flagging": flagging_layers(run),
            "base_matches_snapshot": run.get("base_output_matches_snapshot"),
        }
        si, sb = rec["sweep_items"], rec["sweep_items_base"]
        rec["sweep_rise"] = si is not None and sb is not None and si > sb
        # The sharp measure: a check raised the confirm, or the sweep counts
        # more possible items than on the same output before the plant.
        rec["flagged"] = rec["alarm_checks"] or rec["sweep_rise"]
        if runs2:
            r2 = runs2.get(rid)
            rec["overall_run2"] = r2["overall"] if r2 and not r2.get("error") else None
            rec["alarm_run2"] = alarm(r2) if r2 and not r2.get("error") else None
        scored.append(rec)

    # Controls: a roundtrip whose checks already raise the confirm confounds
    # every plant on its base (the possible-items line fires on most clean outputs).
    roundtrip_alarm = {
        (s["base_id"], is_faithful(s)): s["alarm_checks"]
        for s in scored
        if s.get("class") == "C-02" and "alarm" in s
    }
    for s in scored:
        if "alarm" in s and s["class"].startswith("O"):
            s["control_alarmed"] = roundtrip_alarm.get((s["base_id"], is_faithful(s)))
    # The summary below reads the legacy rows (the published baseline's planter);
    # faithful rows are compared with them in `fidelity`.
    scored_all = scored
    scored = [s for s in scored_all if not is_faithful(s)]

    def rate_table(items: list[dict], key) -> dict[str, dict]:
        groups: dict[str, list[dict]] = defaultdict(list)
        for s in items:
            groups[key(s)].append(s)
        out = {}
        for g, ss in sorted(groups.items()):
            n = len(ss)
            k = sum(1 for s in ss if s["alarm"])
            kf = sum(1 for s in ss if s["flagged"])
            cp = sum(1 for s in ss if s["checks_passed"])
            out[g] = {
                "n": n,
                "caught": k,
                "catch_rate": round(k / n, 3) if n else None,
                "catch_wilson95": wilson(k, n),
                "flagged": kf,
                "flagged_rate": round(kf / n, 3) if n else None,
                "flagged_wilson95": wilson(kf, n),
                "checks_passed": cp,
                "false_pass_rate": round(cp / n, 3) if n else None,
                "false_pass_wilson95": wilson(cp, n),
            }
        return out

    plants = [s for s in scored if "alarm" in s and s["class"].startswith("O")]
    live = [s for s in plants if s["leak"] == "live"]
    pixel_only = [s for s in plants if s["leak"] == "pixel_only"]
    dead = [s for s in plants if s["leak"] == "dead"]
    controls = [s for s in scored if "alarm" in s and s["class"].startswith("C")]
    # Family I: end-to-end rows on received documents, kept apart from the
    # mutated-output headline (no twin; live means recoverable from the output).
    fam_i = [s for s in scored if "alarm" in s and s["class"].startswith("I")]
    fam_i_live = [s for s in fam_i if s["leak"] == "live"]

    joint = routes_joint(live)
    n = len(live)
    all3 = sum(1 for s in live if not any(s["routes"].values()))

    twin_runs = {
        p.parent.name: json.loads(p.read_text()) for p in args.emit.glob("bases/*/run.json")
    }
    emit_twins = {
        b: {"overall": r["overall"], "alarm": alarm(r) if not r.get("error") else None}
        for b, r in sorted(twin_runs.items())
    }

    summary: dict[str, Any] = {
        "schema": 1,
        "definitions": "see tools/seeded_score.py docstring",
        "counts": {
            "rows": len(scored),
            "plants": len(plants),
            "live": len(live),
            "pixel_only": len(pixel_only),
            "dead": len(dead),
            "controls": len(controls),
            "family_i": len(fam_i),
            "no_verdict": sum(1 for s in scored if s.get("state") == "no-verdict"),
        },
        "headline_live": {
            "n": len(live),
            "checks_passed": sum(1 for s in live if s["checks_passed"]),
            "false_pass_wilson95": wilson(sum(1 for s in live if s["checks_passed"]), len(live)),
            "no_alarm": sum(1 for s in live if not s["alarm"]),
            "no_alarm_wilson95": wilson(sum(1 for s in live if not s["alarm"]), len(live)),
            "not_flagged": sum(1 for s in live if not s["flagged"]),
            "not_flagged_wilson95": wilson(sum(1 for s in live if not s["flagged"]), len(live)),
        },
        "by_class": rate_table(live, lambda s: s["class"]),
        "by_class_variant_clean_bases": rate_table(
            [s for s in live if s.get("control_alarmed") is False],
            lambda s: f"{s['class']}.{s['variant']}",
        ),
        "by_class_variant": rate_table(live, lambda s: f"{s['class']}.{s['variant']}"),
        "by_class_mode": rate_table(live, lambda s: f"{s['class']}.{s['page_mode']}"),
        "by_digest": rate_table(
            [s for s in live if s["class"] in ("O-01", "O-03", "O-04", "O-05", "O-15")],
            lambda s: f"{s['class']}.{s['digest']}",
        ),
        "pixel_only_by_class": rate_table(pixel_only, lambda s: f"{s['class']}.{s['variant']}"),
        "family_i": {
            "n": len(fam_i),
            "live": len(fam_i_live),
            "by_class_variant": rate_table(fam_i_live, lambda s: f"{s['class']}.{s['variant']}"),
            "rows": [
                {
                    k: s[k]
                    for k in (
                        "row_id",
                        "leak",
                        "live_legs",
                        "overall",
                        "alarm",
                        "flagged",
                        "flagging",
                    )
                }
                for s in fam_i
            ],
        },
        "routes_joint_miss": joint,
        "all_three_routes_miss": {"k": all3, "n": n},
        "false_alarm_controls": {
            "n": len(controls),
            "alarmed": sum(1 for s in controls if s["alarm"]),
            "flagged": sum(1 for s in controls if s["flagged"]),
            "rows": [
                {k: s[k] for k in ("row_id", "overall", "alarm", "flagged", "flagging")}
                for s in controls
                if s["alarm"] or s["flagged"]
            ],
        },
        "emit_twins": emit_twins,
        "dead_plants": [s["row_id"] for s in dead],
        "determinism": (
            {
                "compared": sum(1 for s in scored if s.get("overall_run2") is not None),
                "differ": [
                    s["row_id"]
                    for s in scored
                    if s.get("overall_run2") is not None and s["overall_run2"] != s["overall"]
                ],
            }
            if runs2
            else None
        ),
        "base_snapshot_mismatch": sorted(
            {s["base_id"] for s in scored if s.get("base_matches_snapshot") is False}
        ),
        "fidelity": fidelity(scored_all) if any(is_faithful(s) for s in scored_all) else None,
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "scored-rows.json").write_text(
        json.dumps(scored_all, indent=1, sort_keys=True) + "\n"
    )
    (args.out / "baseline.json").write_text(json.dumps(summary, indent=1, sort_keys=True) + "\n")
    h = summary["headline_live"]
    print(
        f"live {h['n']}: Checks Passed {h['checks_passed']} {h['false_pass_wilson95']}; "
        f"no alarm {h['no_alarm']} {h['no_alarm_wilson95']}; "
        f"not flagged {h['not_flagged']} {h['not_flagged_wilson95']}; "
        f"controls alarmed {summary['false_alarm_controls']['alarmed']}/{len(controls)}; "
        f"dead {len(dead)}; pixel-only {len(pixel_only)}"
    )
    if args.write_expected:
        source = [s for s in scored_all if is_faithful(s) == (args.expected_from == "faithful")]
        table = expected_table(
            source, args.emit, read_known(args.known), args.version, str(args.out)
        )
        table["plant_mode"] = args.expected_from
        args.write_expected.write_text(json.dumps(table, indent=1, sort_keys=True) + "\n")
        print(f"expected v{args.version}: {len(table['cells'])} cells -> {args.write_expected}")
    if args.gate:
        verdict, readings = gate(
            scored_all, json.loads(args.gate.read_text()), read_prereg(args.prereg)
        )
        counts = Counter(r["reading"] for r in readings)
        (args.out / "lh-gate.json").write_text(
            json.dumps({"verdict": verdict, "counts": counts, "cells": readings}, indent=1) + "\n"
        )
        shown = " · ".join(f"{n} {w}" for w, n in sorted(counts.items()))
        print(
            f"{verdict} {len(readings)} cells: {shown} · known {sum(r['known'] for r in readings)}"
        )
        return EXIT[verdict]
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
