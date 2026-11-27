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
    "phrase_break_beats": 1.5,
    "min_phrase_notes": 2,
    "verse_register_range_min": 12,
    "rhythm_variety_min": 0.20,
    "contour_overlap_max": 0.80,
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


def verse_phrase_medians(v_bars: list[dict], break_beats: float = 1.5,
                         min_notes: int = 2) -> list[float]:
    """Median pitch of each sung verse phrase, split at rests >= break_beats."""
    phrases: list[tuple[str, list[int]]] = []
    current: list[int] = []
    section = None
    rest = 0.0

    def flush():
        nonlocal current
        if len(current) >= min_notes:
            phrases.append((section or "", current))
        current = []

    for bar in v_bars:
        if not current:
            section = bar.get("section")
        for ev in bar["events"]:
            if ev["type"] == "note":
                if rest >= break_beats and current:
                    flush()
                rest = 0.0
                current.append(ev["midi"])
            else:
                rest += float(ev["dur"])
                if rest >= break_beats and current:
                    flush()
    flush()
    return [statistics.median(notes) for label, notes in phrases
            if label.lower().startswith("verse")]


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

    verse_medians = verse_phrase_medians(v_bars, float(th["phrase_break_beats"]),
                                         int(th["min_phrase_notes"]))
    register_range = (max(verse_medians) - min(verse_medians)
                      if len(verse_medians) >= 2 else None)
    if (register_range is not None
            and register_range < th["verse_register_range_min"]):
        flag(f"register flat: verse line medians span {register_range:.0f} st; "
             f"lift the ajuz 4-7 semitones")

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
        "verse_register_range": (round(register_range, 1)
                                 if register_range is not None else None),
        "line_lengths": [int(r["bars"]) for r in lyric_lines
                         if str(r.get("kind") or "").lower() in ("verse", "chorus")],
        "breath_misses": breath_misses,
        "cadence_misses": cadence_misses,
        "lines": len(lyric_lines),
    }
    return {"status": "provisional", "thresholds": th,
            "metrics": metrics, "flags": flags}


# ---------------------------------------------------------------------------
# Template and sameness signals (0.2.4).  Instrumentation, not a quality claim:
# these measure variety, they do not prove excellence, and they never gate a
# build.  Only rhythm_variety and contour_overlap produce flags, and the
# thresholds are provisional.
# ---------------------------------------------------------------------------

VARIETY_KINDS = ("verse", "chorus")


def _kind_of(label: str) -> str | None:
    low = (label or "").lower()
    for kind in ("verse", "chorus", "intro", "outro", "interlude", "bridge",
                 "pre-chorus"):
        if low == kind or low.startswith(kind + "_") or low.startswith(kind + " "):
            return kind
    return low or None


def _rhythm(bar: dict) -> tuple:
    """Pitch-free bar pattern: the sequence of note and rest durations."""
    return tuple((ev["type"][0], float(ev["dur"])) for ev in bar["events"])


def _full(bar: dict) -> tuple:
    return tuple((ev["type"][0], float(ev["dur"]), ev.get("midi")) for ev in bar["events"])


def _contour_grams(bars: list[dict]) -> set:
    pitches = [ev["midi"] for bar in bars for ev in bar["events"] if ev["type"] == "note"]
    signs = []
    for a, b in zip(pitches, pitches[1:]):
        signs.append("u" if b > a else "d" if b < a else "s")
    return {tuple(signs[i:i + 3]) for i in range(len(signs) - 2)}


def _line_name_list(names: list[str], cap: int = 4) -> str:
    if len(names) <= cap:
        return ", ".join(names)
    return f"{names[0]}..{names[-1]} ({len(names)} lines)"


def _lines_for(v_bars: list[dict], sections: list[dict],
               compiler_report: dict | None) -> list[dict]:
    """[{name, kind, section, bars:[bar,...]}] for verse/chorus lines.

    With a compiler report the lines are the lyric lines (`verse_1.L1`).
    Without one, each verse/chorus section is cut into four-bar chunks.
    """
    lines: list[dict] = []
    lm = (compiler_report or {}).get("line_map")
    if isinstance(lm, list) and lm:
        for r in lm:
            kind = _kind_of(str(r.get("kind") or ""))
            if kind not in VARIETY_KINDS or not r.get("start_bar") or not r.get("end_bar"):
                continue
            lines.append({"name": r["line"], "kind": kind, "section": r.get("section"),
                          "start": int(r["start_bar"]) - 1,
                          "bars": v_bars[int(r["start_bar"]) - 1:int(r["end_bar"])]})
        if lines:
            return lines
    for sec in sections:
        kind = _kind_of(sec["label"])
        if kind not in VARIETY_KINDS:
            continue
        start = int(sec["start_bar"]) - 1
        count = int(sec["bars"])
        for off in range(0, count, 4):
            chunk = v_bars[start + off:start + min(count, off + 4)]
            lines.append({"name": f"{sec['label']}@bar{start + off + 1}", "kind": kind,
                          "section": sec["label"], "start": start + off, "bars": chunk})
    return lines


def analyse_variety(v_bars: list[dict], i_bars: list[dict], sections: list[dict],
                    key_info: dict, compiler_report: dict | None = None,
                    thresholds: dict | None = None) -> dict:
    th = dict(DEFAULTS)
    if thresholds:
        th.update({k: v for k, v in thresholds.items() if k in th})
    flags: list[str] = []

    lines = _lines_for(v_bars, sections, compiler_report)

    # Exact repeats (a repeated chorus) are one piece of music, counted once.
    seen_secs: set = set()
    dup_ranges: list[tuple[int, int]] = []
    rhythm_by_kind: dict[str, dict] = {}
    for sec in sections:
        kind = _kind_of(sec["label"])
        start = int(sec["start_bar"]) - 1
        bars = v_bars[start:start + int(sec["bars"])]
        sig = (kind, tuple(_full(b) for b in bars))
        if kind not in VARIETY_KINDS:
            continue
        if sig in seen_secs:
            dup_ranges.append((start, start + len(bars)))
            continue
        seen_secs.add(sig)
        sung = [b for b in bars if any(ev["type"] == "note" for ev in b["events"])]
        slot = rhythm_by_kind.setdefault(kind, {"patterns": set(), "bars": 0})
        slot["bars"] += len(sung)
        slot["patterns"].update(_rhythm(b) for b in sung)
    rhythm_variety = {k: {"distinct": len(v["patterns"]), "bars": v["bars"],
                          "ratio": round(len(v["patterns"]) / v["bars"], 3)}
                      for k, v in rhythm_by_kind.items() if v["bars"]}

    # Lines inside a repeated section are the same music; keep the first copy.
    # Identical lines inside one section are NOT merged: that is the template.
    uniq = [ln for ln in lines
            if not any(lo <= ln["start"] < hi for lo, hi in dup_ranges)]

    for kind, info in rhythm_variety.items():
        if info["ratio"] < float(th["rhythm_variety_min"]):
            owners: dict[tuple, list[str]] = {}
            for ln in uniq:
                if ln["kind"] != kind:
                    continue
                for pat in {_rhythm(b) for b in ln["bars"]}:
                    owners.setdefault(pat, []).append(ln["name"])
            shared = []
            for names in owners.values():
                if len(names) > 1:
                    for n in names:
                        if n not in shared:
                            shared.append(n)
            order = [ln["name"] for ln in uniq if ln["name"] in shared]
            who = _line_name_list(order) if order else kind
            flags.append(f"{kind} rhythm variety {info['ratio']:.2f} < "
                         f"{th['rhythm_variety_min']}: {who} share rhythm patterns "
                         f"({info['distinct']} patterns in {info['bars']} bars)")

    contour_overlap: dict[str, dict] = {}
    for kind in VARIETY_KINDS:
        grams = [(ln["name"], _contour_grams(ln["bars"])) for ln in uniq if ln["kind"] == kind]
        grams = [(n, g) for n, g in grams if g]
        pairs = []
        for i in range(len(grams)):
            for j in range(i + 1, len(grams)):
                union = grams[i][1] | grams[j][1]
                pairs.append((len(grams[i][1] & grams[j][1]) / len(union),
                              grams[i][0], grams[j][0]))
        if not pairs:
            continue
        mean = sum(p[0] for p in pairs) / len(pairs)
        contour_overlap[kind] = {"mean": round(mean, 3), "lines": len(grams)}
        if mean > float(th["contour_overlap_max"]):
            involved = []
            for score, a, b in pairs:
                if score > float(th["contour_overlap_max"]):
                    for n in (a, b):
                        if n not in involved:
                            involved.append(n)
            order = [n for n, _ in grams if n in involved] or [n for n, _ in grams]
            flags.append(f"{kind} contour overlap {mean:.2f} > {th['contour_overlap_max']}: "
                         f"{_line_name_list(order)} repeat one contour")

    # Information only: no flags below this line.
    tonic = key_info["tonic_pc"]
    finals = []
    for ln in uniq:
        if ln["kind"] != "verse":
            continue
        notes = [ev for b in ln["bars"] for ev in b["events"] if ev["type"] == "note"]
        if notes:
            finals.append((notes[-1]["midi"] - tonic) % 12)
    cadence_variety = None
    if finals:
        top = max(set(finals), key=finals.count)
        cadence_variety = {"distinct": len(set(finals)), "lines": len(finals),
                           "top_degree_pc": top,
                           "top_share": round(finals.count(top) / len(finals), 3)}

    ins_by_kind: dict[str, set] = {}
    seen_ins: set = set()
    for sec in sections:
        kind = _kind_of(sec["label"])
        start = int(sec["start_bar"]) - 1
        bars = i_bars[start:start + int(sec["bars"])]
        sig = (kind, tuple(_full(b) for b in bars))
        if sig in seen_ins:
            continue
        seen_ins.add(sig)
        ins_by_kind.setdefault(kind, set()).update(_full(b) for b in bars if any(
            ev["type"] == "note" for ev in b["events"]))
    ins_variety = {k: len(v) for k, v in ins_by_kind.items() if v}

    chord_seq = [b["chords"][0] for b in v_bars if b.get("chords")]
    changes = sum(1 for a, b in zip(chord_seq, chord_seq[1:]) if a != b)
    chord_variety = {"distinct": len(set(chord_seq)),
                     "changes_per_bar": round(changes / len(v_bars), 3) if v_bars else None}

    return {
        "status": "provisional",
        "metrics": {
            "rhythm_variety": rhythm_variety,
            "contour_overlap": contour_overlap,
            "cadence_variety": cadence_variety,
            "ins_variety": ins_variety,
            "chord_variety": chord_variety,
        },
        "flags": flags,
    }
