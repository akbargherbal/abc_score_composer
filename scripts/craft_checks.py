#!/usr/bin/env python3
"""Prosodic and phrase-level checks that the generic corpus bands miss.

The corpus profile measures a finished transcription: range, density, leaps.
It cannot tell whether the tune follows the words.  These checks look for the
defects that make a score sound like scalar noodling instead of a sung bayt:

* phrases that never breathe,
* even phrase lengths that ignore the shatr/bayt pairing,
* cadences that all land on the tonic,
* phrase endings that do not lengthen,
* a flat register instead of a verse arc,
* a rhythm made almost entirely of fast notes,
* no recurring motif, or the same opening copied too literally.

Everything here is advisory.  The thresholds are provisional and live in
``assets/craft_thresholds.json``; they were calibrated on four hand-labelled
scores (one good, three with the reported defect), not on the corpus.
"""

from __future__ import annotations

import os
import statistics

DEFAULTS = {
    "phrase_break_beats": 1.5,
    "min_phrase_notes": 2,
    "long_note_beats": 1.0,
    "fast_note_beats": 0.25,
    "long_note_share_min": 0.17,
    "fast_note_share_max": 0.165,
    "phrase_end_long_min": 0.35,
    "verse_register_stdev_min": 4.0,
    "verse_register_range_min": 12.5,
    "cadence_tonic_share_max": 0.17,
    "verse_bars_mod": 4,
    "line_bars_allowed": [2, 4],
    "bayt_bars": 8,
    "breath_rest_min": 0.5,
    "motif_notes": 4,
    "motif_reuse_min": 0.15,
    "motif_reuse_max": 0.45,
}


def load_thresholds(path: str | None = None) -> dict:
    """Return thresholds from JSON, falling back to the built-in defaults."""
    out = dict(DEFAULTS)
    if path and os.path.exists(path):
        try:
            import json
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            values = data.get("thresholds", data)
            for key, value in values.items():
                if key in out:
                    out[key] = value
        except Exception:
            pass
    return out


def _round(value, nd=2):
    return round(float(value), nd) if value is not None else None


def _lead_rest(events) -> float:
    total = 0.0
    for ev in events:
        if ev["type"] == "note":
            break
        total += float(ev["dur"])
    return total


def _trail_rest(events, after_index: int = -1) -> float:
    total = 0.0
    start = len(events) - 1 if after_index < 0 else after_index
    for ev in reversed(events[:start + 1]):
        if ev["type"] == "note":
            break
        total += float(ev["dur"])
    return total


def segment_phrases(v_bars: list[dict], break_beats: float = 1.5,
                    min_notes: int = 2) -> list[dict]:
    """Split the vocal line into sung phrases at real breath rests.

    A rest shorter than ``break_beats`` is a breath inside a phrase; a longer
    one is a phrase boundary.  1.5 beats is the calibration point that recovered
    the hand analysis of the four reference scores.
    """
    phrases = []
    current = []
    current_section = None
    rest_acc = 0.0

    def close():
        nonlocal current
        if len(current) >= min_notes:
            notes = [n["event"] for n in current]
            med = statistics.median(n["midi"] for n in notes)
            last = current[-1]
            first = current[:4]
            phrases.append({
                "section": current_section,
                "start_bar": current[0]["bar"] + 1,
                "end_bar": last["bar"] + 1,
                "notes": len(notes),
                "median": med,
                "last_pc": last["pc"],
                "last_dur": float(last["event"]["dur"]),
                "end_rest": _trail_rest(v_bars[last["bar"]]["events"], last["event_idx"]),
                "first_midis": [n["midi"] for n in first],
                "first_durs": [float(n["event"]["dur"]) for n in first],
            })
        current = []

    for bi, bar in enumerate(v_bars):
        if current:
            # Keep the phrase's section label from where it began.
            current_section = current_section or bar.get("section")
        else:
            current_section = bar.get("section")
        events = bar["events"]
        for ei, ev in enumerate(events):
            if ev["type"] == "note":
                if rest_acc >= break_beats and current:
                    close()
                rest_acc = 0.0
                current.append({"event": ev, "event_idx": ei, "bar": bi,
                                "midi": ev["midi"], "pc": ev.get("_craft_pc")})
            else:
                rest_acc += float(ev["dur"])
                if rest_acc >= break_beats and current:
                    close()
    if current:
        close()
    return phrases


def _pc_for_event(ev, tonic_pc: int) -> int:
    return (ev["midi"] - tonic_pc) % 12


def derive_line_map(v_bars: list[dict], tonic_pc: int) -> list[dict]:
    """Recover per-source-line stats for an ABC with no compiler report."""
    groups: dict[tuple, list[tuple[int, dict]]] = {}
    for bi, bar in enumerate(v_bars):
        line = bar.get("line")
        key = (bar.get("section"), line)
        groups.setdefault(key, []).append((bi, bar))
    out = []
    for (section, line), hits in groups.items():
        bars = [bar for _, bar in hits]
        notes = [ev for bar in bars for ev in bar["events"] if ev["type"] == "note"]
        if not notes:
            continue
        label = (section or "").lower()
        if label.startswith("verse"):
            kind = "verse"
        elif label.startswith("chorus"):
            kind = "chorus"
        elif label.startswith("intro"):
            kind = "intro"
        elif label.startswith("outro"):
            kind = "outro"
        else:
            kind = "other"
        first = bars[0]["events"]
        last = bars[-1]["events"]
        out.append({
            "line": f"line_{line}",
            "section": section,
            "kind": kind,
            "role": None,
            "bayt": None,
            "start_bar": hits[0][0] + 1,
            "end_bar": hits[-1][0] + 1,
            "bars": len({bi for bi, _ in hits}),
            "lyric_count": None,
            "notes": len(notes),
            "melisma": None,
            "median": statistics.median(ev["midi"] for ev in notes),
            "cadence_pc": _pc_for_event(notes[-1], tonic_pc),
            "lead_rest": _lead_rest(first),
            "end_rest": _trail_rest(last),
            "end_pitch": notes[-1]["midi"],
        })
    out.sort(key=lambda r: r["start_bar"])
    return out


def analyse_craft(v_bars: list[dict], sections: list[dict], key_info: dict,
                  compiler_report: dict | None = None, thresholds: dict | None = None) -> dict:
    """Measure the prosodic craft of one score and return flags."""
    th = dict(DEFAULTS)
    if thresholds:
        th.update({k: v for k, v in thresholds.items() if k in th})
    tonic_pc = key_info["tonic_pc"]
    # annotate pc on the events once so phrase records can carry it
    for bar in v_bars:
        for ev in bar["events"]:
            if ev["type"] == "note":
                ev["_craft_pc"] = _pc_for_event(ev, tonic_pc)

    phrases = segment_phrases(v_bars, float(th["phrase_break_beats"]),
                              int(th["min_phrase_notes"]))
    dates = [p for p in phrases if p["notes"] > 0]
    note_total = sum(p["notes"] for p in dates)
    long_total = sum(1 for bar in v_bars for ev in bar["events"]
                     if ev["type"] == "note" and float(ev["dur"]) >= float(th["long_note_beats"]))
    fast_total = sum(1 for bar in v_bars for ev in bar["events"]
                     if ev["type"] == "note" and float(ev["dur"]) <= float(th["fast_note_beats"]))
    note_count = sum(1 for bar in v_bars for ev in bar["events"] if ev["type"] == "note")

    end_long = sum(1 for p in dates if p["last_dur"] >= float(th["long_note_beats"]))
    tonic_end = sum(1 for p in dates if p["last_pc"] == 0)
    verse_medians = [p["median"] for p in dates
                     if (p["section"] or "").lower().startswith("verse")]
    reg_source = verse_medians if len(verse_medians) >= 2 else [p["median"] for p in dates]
    reg_stdev = statistics.pstdev(reg_source) if len(reg_source) >= 2 else None
    reg_range = (max(reg_source) - min(reg_source)) if len(reg_source) >= 2 else None

    motif_n = int(th["motif_notes"])
    seen = set()
    reused = 0
    signatures = []
    for p in phrases:
        if p["notes"] < motif_n:
            signatures.append(None)
            continue
        midis = p["first_midis"][:motif_n]
        durs = p["first_durs"][:motif_n]
        iv = tuple(b - a for a, b in zip(midis, midis[1:]))
        signatures.append((iv, tuple(durs)))
    for sig in signatures:
        if sig is None:
            continue
        if sig in seen:
            reused += 1
        seen.add(sig)
    motif_reuse = reused / len(phrases) if phrases else None

    line_map = None
    craft_sections = sections
    if compiler_report and isinstance(compiler_report.get("line_map"), list):
        line_map = compiler_report["line_map"]
        secs = compiler_report.get("sections")
        if isinstance(secs, list) and secs:
            # Compiler section ids (v1, c1) are what the line map uses; the
            # validator's sections only carry display labels.
            craft_sections = [
                {"id": s.get("id"), "label": s.get("kind") or s.get("id"),
                 "bars": s.get("bars", 0)}
                for s in secs
            ]
    if not line_map:
        line_map = derive_line_map(v_bars, tonic_pc)
    # Keep only lines that carry words/vocal notes.
    lyric_lines = [r for r in line_map if r.get("notes")]
    line_lengths = [int(r["bars"]) for r in lyric_lines
                    if str(r.get("kind") or "").lower() in ("verse", "chorus")]

    flags = []
    def flag(msg):
        if msg not in flags:
            flags.append(msg)

    long_share = long_total / note_count if note_count else None
    fast_share = fast_total / note_count if note_count else None
    end_share = end_long / len(dates) if dates else None
    tonic_share = tonic_end / len(dates) if dates else None

    if long_share is not None and long_share < th["long_note_share_min"]:
        flag(f"only {long_share:.0%} of vocal notes are held for a beat or more; "
             f"let the important words ring")
    if fast_share is not None and fast_share > th["fast_note_share_max"]:
        flag(f"{fast_share:.0%} of vocal notes are a quarter-beat or shorter; "
             f"stretch the rhythm instead of running eighth after eighth")
    if end_share is not None and end_share < th["phrase_end_long_min"]:
        flag(f"only {end_share:.0%} of phrases end on a long note; the listener "
             f"cannot hear the qafla")
    if reg_stdev is not None and reg_stdev < th["verse_register_stdev_min"]:
        flag(f"verse phrase medians vary by only {reg_stdev:.1f} st; build a "
             f"register arc from the low sadr to a higher ajuz")
    if reg_range is not None and reg_range < th["verse_register_range_min"]:
        flag(f"verse register range is {reg_range:.0f} st; the high and low "
             f"phrases sit too close to make an arc")
    if tonic_share is not None and tonic_share > th["cadence_tonic_share_max"]:
        flag(f"{tonic_share:.0%} of phrases cadence on the tonic; save degree 1 "
             f"for a section or song ending")

    for sec in craft_sections:
        if sec["label"].lower().startswith("verse"):
            if sec["bars"] % int(th["verse_bars_mod"]) != 0:
                flag(f"verse has {sec['bars']} bars, not a multiple of "
                     f"{th['verse_bars_mod']}; one shatr is 4 bars and one bayt is 8")

    allowed = [int(x) for x in th["line_bars_allowed"]]
    bad_lengths = sorted({n for n in line_lengths if n not in allowed})
    if bad_lengths:
        flag(f"lyric line lengths {bad_lengths} bars are outside {allowed}; "
             f"a hemistich should be 2 or 4 bars")

    # Pair lines into bayts and check the 8-bar budget.  With a compiler line
    # map the roles are explicit; without one, alternate by position.
    for sec in craft_sections:
        sec_id = sec.get("id") or sec.get("label")
        entries = [r for r in lyric_lines if r.get("section") == sec_id]
        if sec["label"].lower().startswith(("intro", "outro", "interlude")):
            continue
        for i in range(0, len(entries) - 1, 2):
            a, b = entries[i], entries[i + 1]
            total = int(a["bars"]) + int(b["bars"])
            if total != int(th["bayt_bars"]):
                flag(f"bayt {i // 2 + 1} in {sec['label']} spans {total} bars; "
                     f"sadr {a['bars']} + ajuz {b['bars']} should be "
                     f"{th['bayt_bars']}")

    # Breath and role cadences are only reliable when the compiler supplied
    # explicit line roles from the lyric intake.
    role_entries = [r for r in lyric_lines if r.get("role")]
    if role_entries:
        by_section = {}
        for r in role_entries:
            by_section.setdefault(r["section"], []).append(r)
        for entries in by_section.values():
            for i, r in enumerate(entries):
                nxt = entries[i + 1] if i + 1 < len(entries) else None
                gap = max(float(r.get("end_rest") or 0),
                          float(nxt.get("lead_rest") or 0) if nxt else 0)
                if gap < float(th["breath_rest_min"]):
                    flag(f"no breath after {r['line']}; end the hemistich with "
                         f"at least r:{th['breath_rest_min']}")
            for i in range(0, len(entries) - 1, 2):
                a, b = entries[i], entries[i + 1]
                if a.get("role") == "sadr" and a.get("cadence_pc") == 0:
                    flag(f"sadr {a['line']} cadences on degree 1; save that for "
                         f"the ajuz or the section end")
                if b.get("role") == "ajuz" and b.get("cadence_pc") not in (0, 7):
                    flag(f"ajuz {b['line']} does not settle on degree 5 or 1")
                if (a.get("role") == "sadr" and b.get("role") == "ajuz"
                        and a.get("cadence_pc") == b.get("cadence_pc")):
                    flag(f"bayt {i // 2 + 1} in {entries[0]['section']} ends both "
                         f"halves on the same degree; vary the ajuz cadence")

    if motif_reuse is not None and len(phrases) >= 4:
        if motif_reuse < th["motif_reuse_min"]:
            flag(f"only {motif_reuse:.0%} of phrase openings reuse a motif; the "
                 f"melody wanders instead of developing a cell")
        elif motif_reuse > th["motif_reuse_max"]:
            flag(f"{motif_reuse:.0%} of phrase openings repeat the same cell "
                 f"literally; vary the ending or transpose the sequence")

    metrics = {
        "phrases": len(phrases),
        "notes": note_count,
        "long_note_share": _round(long_share),
        "fast_note_share": _round(fast_share),
        "phrase_end_long_share": _round(end_share),
        "cadence_tonic_share": _round(tonic_share),
        "verse_register_stdev": _round(reg_stdev),
        "verse_register_range": _round(reg_range),
        "motif_reuse": _round(motif_reuse),
        "line_lengths": line_lengths,
        "line_count": len(lyric_lines),
    }
    return {
        "status": "provisional",
        "thresholds": th,
        "metrics": metrics,
        "lines": lyric_lines,
        "flags": flags,
    }
