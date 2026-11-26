#!/usr/bin/env python3
"""Four prosodic checks that the generic corpus bands cannot see.

The corpus has no lyrics, so it cannot tell whether a tune follows the words.
These checks look for the defects that make a score sound like scalar noodling
instead of a sung bayt:

* a shatr/bayt with the wrong number of bars,
* no breath after a hemistich,
* the sadr and ajuz closing on the same degree (or the sadr closing on 1),
* almost no long notes, so no qafla is audible.

Everything is advisory.  Thresholds are provisional and live in
``assets/craft_thresholds.json``.
"""

from __future__ import annotations

import os
import statistics

DEFAULTS = {
    "long_note_beats": 1.0,
    "long_note_share_min": 0.17,
    "verse_bars_mod": 4,
    "line_bars_allowed": [2, 4],
    "bayt_bars": 8,
    "breath_rest_min": 0.5,
}


def load_thresholds(path: str | None = None) -> dict:
    out = dict(DEFAULTS)
    if path and os.path.exists(path):
        try:
            import json
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            for key, value in (data.get("thresholds", data) or {}).items():
                if key in out:
                    out[key] = value
        except Exception:
            pass
    return out


def _lead_rest(events) -> float:
    total = 0.0
    for ev in events:
        if ev["type"] == "note":
            break
        total += float(ev["dur"])
    return total


def _trail_rest(events) -> float:
    total = 0.0
    for ev in reversed(events):
        if ev["type"] == "note":
            break
        total += float(ev["dur"])
    return total


def derive_line_map(v_bars: list[dict], tonic_pc: int) -> list[dict]:
    """Recover per-source-line stats for an ABC with no compiler report."""
    groups: dict[tuple, list[tuple[int, dict]]] = {}
    for bi, bar in enumerate(v_bars):
        groups.setdefault((bar.get("section"), bar.get("line")), []).append((bi, bar))
    out = []
    for (section, line), hits in groups.items():
        bars = [bar for _, bar in hits]
        notes = [ev for bar in bars for ev in bar["events"] if ev["type"] == "note"]
        if not notes:
            continue
        label = (section or "").lower()
        kind = next((k for k in ("verse", "chorus", "intro", "outro")
                     if label.startswith(k)), "other")
        out.append({
            "line": f"line_{line}",
            "section": section,
            "kind": kind,
            "role": None,
            "bars": len({bi for bi, _ in hits}),
            "notes": len(notes),
            "median": statistics.median(ev["midi"] for ev in notes),
            "cadence_pc": (notes[-1]["midi"] - tonic_pc) % 12,
            "lead_rest": _lead_rest(bars[0]["events"]),
            "end_rest": _trail_rest(bars[-1]["events"]),
        })
    out.sort(key=lambda r: r.get("start_bar", 0))
    return out


def analyse_craft(v_bars: list[dict], sections: list[dict], key_info: dict,
                  compiler_report: dict | None = None,
                  thresholds: dict | None = None) -> dict:
    th = dict(DEFAULTS)
    if thresholds:
        th.update({k: v for k, v in thresholds.items() if k in th})

    flags: list[str] = []

    def flag(msg: str) -> None:
        if msg not in flags:
            flags.append(msg)

    note_count = sum(1 for bar in v_bars for ev in bar["events"] if ev["type"] == "note")
    long_count = sum(
        1 for bar in v_bars for ev in bar["events"]
        if ev["type"] == "note" and float(ev["dur"]) >= float(th["long_note_beats"])
    )
    long_share = long_count / note_count if note_count else None
    if long_share is not None and long_share < th["long_note_share_min"]:
        flag(f"only {long_share:.0%} of vocal notes are held for a beat or more; "
             f"let the important words ring")

    line_map = None
    craft_sections = sections
    if compiler_report and isinstance(compiler_report.get("line_map"), list):
        line_map = compiler_report["line_map"]
        secs = compiler_report.get("sections")
        if isinstance(secs, list) and secs:
            craft_sections = [{"id": s.get("id"),
                               "label": s.get("kind") or s.get("id"),
                               "bars": s.get("bars", 0)} for s in secs]
    if not line_map:
        line_map = derive_line_map(v_bars, key_info["tonic_pc"])
    lyric_lines = [r for r in line_map if r.get("notes")]

    for sec in craft_sections:
        if sec["label"].lower().startswith("verse"):
            if int(sec["bars"]) % int(th["verse_bars_mod"]) != 0:
                flag(f"verse has {sec['bars']} bars, not whole bayts; "
                     f"one shatr is 4 bars and one bayt is 8")

    allowed = [int(x) for x in th["line_bars_allowed"]]
    bad_lengths = sorted({int(r["bars"]) for r in lyric_lines
                          if str(r.get("kind") or "").lower() in ("verse", "chorus")
                          and int(r["bars"]) not in allowed})
    if bad_lengths:
        flag(f"lyric line lengths {bad_lengths} bars are outside {allowed}; "
             f"a hemistich should be 2 or 4 bars")

    breath_misses = 0
    cadence_misses = 0
    role_entries = [r for r in lyric_lines if r.get("role")]
    by_section: dict[str, list[dict]] = {}
    for r in role_entries:
        by_section.setdefault(r["section"], []).append(r)
    for entries in by_section.values():
        for i, r in enumerate(entries):
            nxt = entries[i + 1] if i + 1 < len(entries) else None
            gap = max(float(r.get("end_rest") or 0),
                      float(nxt.get("lead_rest") or 0) if nxt else 0)
            if gap < float(th["breath_rest_min"]):
                breath_misses += 1
                flag(f"no breath after {r['line']}; end the hemistich with "
                     f"at least r:{th['breath_rest_min']}")
        for i in range(0, len(entries) - 1, 2):
            a, b = entries[i], entries[i + 1]
            if a.get("role") == "sadr" and a.get("cadence_pc") == 0:
                cadence_misses += 1
                flag(f"sadr {a['line']} cadences on degree 1; save that for "
                     f"the ajuz or the section end")
            if b.get("role") == "ajuz" and b.get("cadence_pc") not in (0, 7):
                cadence_misses += 1
                flag(f"ajuz {b['line']} does not settle on degree 5 or 1")
            if (a.get("role") == "sadr" and b.get("role") == "ajuz"
                    and a.get("cadence_pc") == b.get("cadence_pc")):
                cadence_misses += 1
                flag(f"bayt {i // 2 + 1} in {entries[0]['section']} ends both "
                     f"halves on the same degree; vary the ajuz cadence")

    # Pair lines into bayts and check the 8-bar budget.
    for sec in craft_sections:
        sec_id = sec.get("id") or sec.get("label")
        entries = [r for r in lyric_lines if r.get("section") == sec_id]
        if sec["label"].lower().startswith(("intro", "outro", "interlude")):
            continue
        for i in range(0, len(entries) - 1, 2):
            total = int(entries[i]["bars"]) + int(entries[i + 1]["bars"])
            if total != int(th["bayt_bars"]):
                flag(f"bayt {i // 2 + 1} in {sec['label']} spans {total} bars; "
                     f"sadr {entries[i]['bars']} + ajuz {entries[i + 1]['bars']} "
                     f"should be {th['bayt_bars']}")

    metrics = {
        "long_note_share": round(long_share, 2) if long_share is not None else None,
        "line_lengths": [int(r["bars"]) for r in lyric_lines
                         if str(r.get("kind") or "").lower() in ("verse", "chorus")],
        "breath_misses": breath_misses,
        "cadence_misses": cadence_misses,
        "lines": len(lyric_lines),
    }
    return {"status": "provisional", "thresholds": th,
            "metrics": metrics, "flags": flags}
