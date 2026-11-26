#!/usr/bin/env python3
"""Validate one two-voice ABC file and print a compact musical inspection.

This is the single source of truth: it runs abc2midi, parses every error and
warning from stdout/stderr, re-checks bar sums and voice alignment, and
measures the musical result.  It never edits the score.

Usage:
    python3 scripts/validate_and_inspect.py song.abc \
        --report song.report.json --validation song.validation.abc \
        --profile assets/corpus_profile.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter, defaultdict
from statistics import median

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from abc_common import (  # noqa: E402
    bar_has_notes, bar_rest_beats, bar_total_beats, dump_json, load_json,
    midi_to_name, parse_abc,
)
from craft_checks import analyse_craft, load_thresholds  # noqa: E402


# Pitch classes relative to the tonic for a 12-tone approximation of each maqam.
MAQAM_DEGREES = {
    "kurd": {0, 1, 3, 5, 7, 8, 10},
    "nahawand": {0, 2, 3, 5, 7, 8, 10},
    "hijaz": {0, 1, 4, 5, 7, 8, 10},
    "bayati": {0, 1, 3, 5, 7, 8, 10},
    "rast": {0, 2, 4, 5, 7, 9, 10},
    "saba": {0, 1, 3, 6, 7, 8, 10},
    "huzam": {0, 1, 4, 5, 7, 8, 11},
    "ajam": {0, 2, 4, 5, 7, 9, 11},
}


def find_abc2midi(explicit: str | None = None) -> str | None:
    candidates = [
        explicit,
        os.environ.get("ABC2MIDI"),
        shutil.which("abc2midi"),
        os.path.expanduser("~/.local/bin/abc2midi"),
        "/tmp/opencode/abcmidi/root/usr/bin/abc2midi",
        "/usr/bin/abc2midi",
        "/usr/local/bin/abc2midi",
    ]
    for c in candidates:
        if c and os.path.exists(c) and os.access(c, os.X_OK):
            return c
    return None


def run_abc2midi(binary: str, path: str) -> dict:
    try:
        p = subprocess.run(
            [binary, path, "-o", os.devnull],
            capture_output=True, text=True, timeout=60,
        )
    except Exception as exc:
        return {"available": True, "error": str(exc), "errors": [], "warnings": [],
                "exit": None}
    out = (p.stdout or "") + "\n" + (p.stderr or "")
    errs, warns = [], []
    for line in out.splitlines():
        s = line.strip()
        if not s:
            continue
        if re.search(r"\berror\b", s, re.I):
            errs.append(s)
        elif re.search(r"\bwarning\b", s, re.I):
            warns.append(s)
    version = next((l.strip() for l in out.splitlines() if re.search(r"abc2midi", l, re.I)), "")
    return {
        "available": True,
        "version": version,
        "exit": p.returncode,
        "errors": errs,
        "warnings": warns,
        "stdout": out.strip(),
    }


def longest_vocal_run(bars: list[dict], tempo: int) -> dict:
    """Longest run of vocal notes without a rest of at least 0.5 beat."""
    run = 0.0
    best = 0.0
    notes = 0
    for bar in bars:
        for ev in bar["events"]:
            if ev["type"] == "note":
                run += float(ev["dur"])
                notes += 1
                best = max(best, run)
            else:
                if float(ev["dur"]) >= 0.5:
                    run = 0.0
                    notes = 0
                else:
                    run += float(ev["dur"])
    seconds = best * 60.0 / max(1, tempo)
    return {"beats": round(best, 2), "seconds": round(seconds, 2), "notes": notes}


def parse_w_melisma(path: str) -> dict | None:
    """Fallback melisma count from a validation ABC with w: lines."""
    try:
        lines = open(path, encoding="utf-8", errors="replace").read().splitlines()
    except Exception:
        return None
    notes = 0
    syl = 0
    saw = False
    pending_notes = 0
    for line in lines:
        s = line.strip()
        if not s or s.startswith(("%", "X:", "T:", "M:", "L:", "Q:", "V:", "K:")):
            if s.startswith("V:"):
                pending_notes = 0
            continue
        if s.startswith("w:"):
            toks = s[2:].split()
            syl += sum(1 for t in toks if t not in ("*", "_"))
            notes += pending_notes
            saw = True
            pending_notes = 0
            continue
        # A music line.  Strip chords and count note letters, not rests.
        music = re.sub(r'"[^"]*"', "", s)
        n = 0
        for m in re.finditer(r"(?:\^\^|\^|__|_)?[A-Ga-g][,']*", music):
            n += 1
        pending_notes += n
    if not saw or not syl:
        return None
    return {"notes": notes, "syllables": syl, "rate": notes / syl, "source": "w:"}


def build_report(abc_path: str, validation: str | None, report_path: str | None,
                 profile_path: str | None, abc2midi_path: str | None,
                 strict: bool = False, craft_thresholds_path: str | None = None) -> dict:
    parsed = parse_abc(abc_path)
    hdr = parsed["header"]
    v_bars = parsed["voices"].get("Vocal", [])
    i_bars = parsed["voices"].get("Ins", [])
    if not v_bars:
        # Some external files may use another voice name; take the first two.
        names = list(parsed["voices"].keys())
        if len(names) >= 2:
            v_bars, i_bars = parsed["voices"][names[0]], parsed["voices"][names[1]]
    errors: list[str] = []
    warnings: list[str] = []
    if not v_bars or not i_bars:
        errors.append("expected two voices (Vocal and Ins)")
    if len(v_bars) != len(i_bars):
        errors.append(f"voice bar counts differ: {len(v_bars)} vocal vs {len(i_bars)} ins")

    total_bars = min(len(v_bars), len(i_bars))
    for idx, (bv, bi) in enumerate(zip(v_bars, i_bars)):
        if not bv.get("sum_ok", True):
            errors.append(f"bar {idx+1}: vocal sums to {bv.get('sum')} (needs {bv['beats']})")
        if not bi.get("sum_ok", True):
            errors.append(f"bar {idx+1}: instrument sums to {bi.get('sum')} (needs {bi['beats']})")

    v_notes = [ev for b in v_bars for ev in b["events"] if ev["type"] == "note"]
    i_notes = [ev for b in i_bars for ev in b["events"] if ev["type"] == "note"]
    pitches = [ev["midi"] for ev in v_notes]
    low = min(pitches) if pitches else None
    high = max(pitches) if pitches else None
    span = (high - low) if pitches else 0

    steps = leaps = reps = 0
    for a, b in zip(pitches, pitches[1:]):
        d = abs(b - a)
        if d == 0:
            reps += 1
        elif d <= 2:
            steps += 1
        else:
            leaps += 1
    moves = max(1, steps + leaps + reps)

    total_beats = sum((bar_total_beats(b) for b in v_bars), 0)
    rest_beats = sum((bar_rest_beats(b) for b in v_bars), 0)
    total_beats = float(total_beats) or 1.0
    rest_ratio = float(rest_beats) / total_beats
    onset = len(v_notes) / total_beats

    bars_with_vocal = sum(1 for b in v_bars if bar_has_notes(b))
    bars_with_ins = sum(1 for b in i_bars if bar_has_notes(b))
    vocal_silent = [b for b in v_bars if not bar_has_notes(b)]
    call_num = 0
    for bv, bi in zip(v_bars, i_bars):
        if not bar_has_notes(bv) and bar_has_notes(bi):
            call_num += 1
    call_ratio = call_num / len(vocal_silent) if vocal_silent else None
    under_vocal = sum(1 for bv, bi in zip(v_bars, i_bars)
                      if bar_has_notes(bv) and bar_has_notes(bi))
    under_ratio = under_vocal / bars_with_vocal if bars_with_vocal else None

    # Sections by contiguous label.
    sec_bars = []
    last = object()
    for i, b in enumerate(v_bars):
        label = b.get("section") or "unlabelled"
        if label != last:
            sec_bars.append({"label": label, "start": i, "bars": []})
            last = label
        sec_bars[-1]["bars"].append(b)
    sections = []
    for sb in sec_bars:
        notes = [ev for b in sb["bars"] for ev in b["events"] if ev["type"] == "note"]
        ps = [ev["midi"] for ev in notes]
        ins = [ev for b in i_bars[sb["start"]:sb["start"] + len(sb["bars"])]
               for ev in b["events"] if ev["type"] == "note"]
        sections.append({
            "label": sb["label"],
            "start_bar": sb["start"] + 1,
            "bars": len(sb["bars"]),
            "vocal_notes": len(notes),
            "median": round(median(ps), 2) if ps else None,
            "low": min(ps) if ps else None,
            "high": max(ps) if ps else None,
            "ins_notes": len(ins),
            "bars_with_vocal": sum(1 for b in sb["bars"] if bar_has_notes(b)),
        })

    def median_for(label: str):
        vals = []
        for s in sections:
            lab = s["label"].lower()
            if not (lab == label or lab.startswith(label + "_") or lab.startswith(label + " ")):
                continue
            for b in v_bars[s["start_bar"] - 1:s["start_bar"] - 1 + s["bars"]]:
                vals.extend(ev["midi"] for ev in b["events"] if ev["type"] == "note")
        return median(vals) if vals else None

    verse_med = median_for("verse")
    chorus_med = median_for("chorus")
    lift = (chorus_med - verse_med) if verse_med is not None and chorus_med is not None else None

    # Chord changes per bar (first chord in each bar).
    chord_seq = [b["chords"][0] for b in v_bars if b["chords"]]
    changes = sum(1 for a, b in zip(chord_seq, chord_seq[1:]) if a != b)
    chord_changes = changes / total_bars if total_bars else None
    qualities = Counter()
    for ch in chord_seq:
        m = re.match(r"^[A-G][#b]?([^/]*)", ch)
        qualities[(m.group(1) if m else ch) or "maj"] += 1

    # Rhythm variety.
    dur_counts = Counter()
    for ev in v_notes:
        dur_counts[float(ev["dur"])] += 1
    dominant_dur = (max(dur_counts.values()) / len(v_notes)) if v_notes else None

    run = longest_vocal_run(v_bars, hdr["Q"])

    # Melisma from the compiler report first, then from w:.
    melisma = None
    alignment = None
    targets = {}
    maqam = None
    comp_report = None
    if report_path and os.path.exists(report_path):
        try:
            comp_report = load_json(report_path)
        except Exception:
            comp_report = None
    if comp_report:
        melisma = comp_report.get("melisma_rate")
        alignment = comp_report.get("alignment")
        targets = (comp_report.get("meta") or {}).get("targets") or {}
        maqam = (comp_report.get("meta") or {}).get("maqam")
        if melisma is not None:
            melisma = {"rate": melisma, "notes": comp_report.get("vocal_notes"),
                       "syllables": comp_report.get("syllables"), "source": "report"}
    if melisma is None and validation and os.path.exists(validation):
        melisma = parse_w_melisma(validation)

    # Prosodic craft checks.  The compiler report supplies the lyric-line map
    # when the score came from a Blueprint; an external ABC falls back to its
    # own source-line breaks.
    craft_path = craft_thresholds_path or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "assets", "craft_thresholds.json")
    craft = analyse_craft(v_bars, sections, hdr["key"], comp_report,
                          load_thresholds(craft_path))

    # If the file has no compiler report, a modal key still tells us the
    # intended family.  Dphr is the ABC spelling of the Kurd/Phrygian scale.
    if not maqam:
        kraw = hdr["K"].lower()
        if "phr" in kraw:
            maqam = "kurd"
        elif "hij" in kraw:
            maqam = "hijaz"
        elif "sab" in kraw:
            maqam = "saba"

    maqam_fit = None
    maqam_expected = None
    if maqam and pitches:
        key = re.sub(r"[^a-z]", "", str(maqam).lower())
        expected = MAQAM_DEGREES.get(key)
        if expected:
            tonic = hdr["key"]["tonic_pc"]
            pcs = [(p - tonic) % 12 for p in pitches]
            maqam_fit = sum(1 for pc in pcs if pc in expected) / len(pcs)
            maqam_expected = sorted(expected)

    profile = None
    if profile_path and os.path.exists(profile_path):
        try:
            profile = load_json(profile_path)
        except Exception:
            profile = None

    def band(key):
        return ((profile or {}).get("percentiles") or {}).get(key)

    def outside(value, b):
        if value is None or not b:
            return None
        if b.get("p10") is not None and value < b["p10"]:
            return "low"
        if b.get("p90") is not None and value > b["p90"]:
            return "high"
        return None

    metrics = {
        "bars": total_bars,
        "tempo": hdr["Q"],
        "meter": f"{hdr['M'][0]}/{hdr['M'][1]}",
        "key": hdr["K"].split()[0],
        "vocal_notes": len(v_notes),
        "ins_notes": len(i_notes),
        "range": {"low": low, "high": high, "span": span,
                  "low_name": midi_to_name(low) if low is not None else None,
                  "high_name": midi_to_name(high) if high is not None else None},
        "step_ratio": steps / moves,
        "leap_ratio": leaps / moves,
        "repeat_ratio": reps / moves,
        "onsets_per_beat": onset,
        "rest_ratio": rest_ratio,
        "bars_with_vocal": bars_with_vocal,
        "bars_with_ins": bars_with_ins,
        "vocal_active_ratio": bars_with_vocal / total_bars if total_bars else None,
        "ins_active_ratio": bars_with_ins / total_bars if total_bars else None,
        "call_response": call_ratio,
        "ins_under_vocal": under_ratio,
        "chorus_lift": lift,
        "verse_median": round(verse_med, 2) if verse_med is not None else None,
        "chorus_median": round(chorus_med, 2) if chorus_med is not None else None,
        "chord_changes_per_bar": chord_changes,
        "dominant_duration_share": dominant_dur,
        "longest_vocal_run": run,
        "melisma": melisma,
        "alignment": alignment,
        "maqam": maqam,
        "maqam_fit": maqam_fit,
        "maqam_expected": maqam_expected,
        "targets": targets,
        "sections": sections,
        "craft": craft,
        "chord_qualities": dict(qualities.most_common(10)),
    }

    # Band flags and diagnostics.
    flags = []
    diags = []
    bands = {
        "vocal_span": band("vocal_span"),
        "step_ratio": band("step_ratio"),
        "leap_ratio": band("leap_ratio"),
        "repeat_ratio": band("repeat_ratio"),
        "onsets_per_beat": band("onsets_per_beat"),
        "rest_ratio": band("rest_ratio"),
        "vocal_active_ratio": band("vocal_active_bars"),
        "ins_active_ratio": band("ins_active_bars"),
        "call_response": band("ins_in_vocal_gaps"),
        "chorus_lift": band("chorus_lift_semitones"),
        "chord_changes_per_bar": band("chord_changes_per_bar"),
    }
    metrics["bands"] = bands
    for key, value in (
        ("vocal_span", span), ("step_ratio", metrics["step_ratio"]),
        ("leap_ratio", metrics["leap_ratio"]), ("repeat_ratio", metrics["repeat_ratio"]),
        ("onsets_per_beat", onset), ("rest_ratio", rest_ratio),
        ("vocal_active_ratio", metrics["vocal_active_ratio"]),
        ("ins_active_ratio", metrics["ins_active_ratio"]),
        ("call_response", call_ratio), ("chorus_lift", lift),
        ("chord_changes_per_bar", chord_changes),
    ):
        side = outside(value, bands.get(key))
        if side:
            word = "below" if side == "low" else "above"
            if isinstance(value, float):
                flags.append(f"{key} {value:.2f} is {word} the corpus p10-p90 band")
            else:
                flags.append(f"{key} {value} is {word} the corpus band")

    if targets:
        if "melisma" in targets and melisma:
            ok = melisma["rate"] >= targets["melisma"]
            metrics["targets"]["melisma_ok"] = ok
            if not ok:
                flags.append(f"melisma {melisma['rate']:.2f} < target {targets['melisma']}")
        if "chorus_lift" in targets and lift is not None:
            ok = lift >= targets["chorus_lift"]
            metrics["targets"]["chorus_lift_ok"] = ok
            if not ok:
                flags.append(f"chorus lift {lift:+.0f} < target {targets['chorus_lift']}")
        if "call_response" in targets and call_ratio is not None:
            ok = call_ratio >= targets["call_response"]
            metrics["targets"]["call_response_ok"] = ok
            if not ok:
                flags.append(f"call-response {call_ratio:.2f} < target {targets['call_response']}")
        if "vocal_span" in targets:
            ok = span <= targets["vocal_span"]
            metrics["targets"]["vocal_span_ok"] = ok
            if not ok:
                flags.append(f"vocal span {span} > target {targets['vocal_span']}")
        if "max_phrase_seconds" in targets:
            ok = run["seconds"] <= targets["max_phrase_seconds"]
            metrics["targets"]["max_phrase_ok"] = ok
            if not ok:
                flags.append(f"longest vocal run {run['seconds']}s > target {targets['max_phrase_seconds']}s")
        if "dominant_duration" in targets and dominant_dur is not None:
            ok = dominant_dur <= targets["dominant_duration"]
            metrics["targets"]["dominant_duration_ok"] = ok
            if not ok:
                flags.append(f"dominant duration share {dominant_dur:.2f} > target {targets['dominant_duration']}")
        if "maqam_fit" in targets and maqam_fit is not None:
            ok = maqam_fit >= targets["maqam_fit"]
            metrics["targets"]["maqam_fit_ok"] = ok
            if not ok:
                flags.append(f"maqam fit {maqam_fit:.2f} < target {targets['maqam_fit']}")

    if span > 24:
        diags.append(f"vocal span {span} st is wide; bring the extreme into the same singer's range")
    if run["seconds"] > 12:
        diags.append(f"longest vocal run {run['seconds']}s; add r: at a hemistich")
    if call_ratio is not None and call_ratio < 0.5:
        diags.append(f"Ins answers only {call_ratio:.0%} of vocal gaps; add gap riffs")
    if bars_with_vocal and under_ratio == 0:
        diags.append("Ins never sounds under the vocal; add a sustained root or muted riff in some vocal bars")
    if lift is not None and lift <= 0:
        diags.append("chorus is not above the verse; lift the chorus register")
    if maqam_fit is not None and maqam_fit < 0.8:
        diags.append(f"maqam fit {maqam_fit:.0%} for {maqam}; expected pitch classes "
                     f"{maqam_expected} from the tonic (0-11)")

    # abc2midi.
    binary = find_abc2midi(abc2midi_path)
    if binary:
        midi = run_abc2midi(binary, abc_path)
        metrics["abc2midi"] = midi
        if midi.get("errors") or midi.get("warnings"):
            errors.extend(midi.get("errors", []))
            warnings.extend(midi.get("warnings", []))
    else:
        metrics["abc2midi"] = {"available": False}
        errors.append("abc2midi not found; set ABC2MIDI or pass --abc2midi")

    # abc2midi exits 0 even on errors, and a track-length warning is a real
    # voice-alignment problem. Treat both as hard failures.
    hard_fail = bool(errors) or bool(warnings)
    target_fail = any(v is False for v in metrics.get("targets", {}).values() if isinstance(v, bool))
    if strict and target_fail:
        hard_fail = True
    # CRAFT is advisory by default.  A Blueprint can opt in to a hard gate by
    # declaring meta.targets.craft = true and compiling/validating --strict.
    if strict and targets.get("craft") and craft.get("flags"):
        hard_fail = True

    metrics["errors"] = errors
    metrics["warnings"] = warnings
    metrics["flags"] = flags
    metrics["diagnostics"] = diags
    metrics["ok"] = not hard_fail
    return metrics


def fmt_band(value: float, b: dict | None, nd: int = 0) -> str:
    if b is None:
        return f"{value:.{nd}f}" if isinstance(value, float) else str(value)
    return (f"{value:.{nd}f} (p50 {b['p50']:.{nd}f}, p90 {b['p90']:.{nd}f})"
            if isinstance(value, float) else f"{value} (p50 {b['p50']}, p90 {b['p90']})")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("abc")
    ap.add_argument("--report", default=None)
    ap.add_argument("--validation", default=None)
    ap.add_argument("--profile", default=None)
    ap.add_argument("--abc2midi", default=None)
    ap.add_argument("--craft-thresholds", default=None,
                    help="craft_thresholds.json (default: ../assets/craft_thresholds.json)")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 when a declared target fails")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--pretty", action="store_true")
    args = ap.parse_args()

    profile = args.profile or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "assets", "corpus_profile.json")
    try:
        r = build_report(args.abc, args.validation, args.report, profile,
                         args.abc2midi, strict=args.strict,
                         craft_thresholds_path=args.craft_thresholds)
    except Exception as exc:
        print(json.dumps({"ok": False, "errors": [f"parse: {exc}"]}))
        return 2

    if args.json:
        print(dump_json(r, None, pretty=args.pretty))
    else:
        m = r
        print(f"FILE {args.abc}")
        am = m.get("abc2midi", {})
        if am.get("available"):
            print(f"abc2midi {am.get('version','')}: {len(am.get('errors', []))} errors, "
                  f"{len(am.get('warnings', []))} warnings")
        else:
            print("abc2midi: NOT FOUND")
        print(f"FORM {m['bars']} bars  {m['meter']}  {m['key']}  {m['tempo']} BPM  "
              f"| " + " ".join(f"{s['label']} {s['bars']}" for s in m["sections"]))
        rng = m["range"]
        print(f"VOCAL range {rng['low_name']}-{rng['high_name']} ({rng['span']} st; "
              f"p50 {m['bands']['vocal_span']['p50'] if m['bands'].get('vocal_span') else '?'}, "
              f"p90 {m['bands']['vocal_span']['p90'] if m['bands'].get('vocal_span') else '?'})"
              f"  onsets {m['onsets_per_beat']:.2f}/beat  rest {m['rest_ratio']:.2f}")
        if m.get("maqam_fit") is not None:
            print(f"MAQAM {m.get('maqam')} fit {m['maqam_fit']:.0%}  "
                  f"expected pc {m.get('maqam_expected')}")
        print(f"MOTION step {m['step_ratio']:.2f}  leap {m['leap_ratio']:.2f}  "
              f"repeat {m['repeat_ratio']:.2f}  dominant dur {m['dominant_duration_share']:.2f}"
              if m['dominant_duration_share'] is not None else
              f"MOTION step {m['step_ratio']:.2f}  leap {m['leap_ratio']:.2f}  repeat {m['repeat_ratio']:.2f}")
        if m.get("chorus_lift") is not None:
            cb = m["bands"].get("chorus_lift") or {}
            print(f"REGISTER verse {m.get('verse_median')}  chorus {m.get('chorus_median')}  "
                  f"lift {m['chorus_lift']:+.0f} st  "
                  f"(p50 {cb.get('p50', '?')}, p90 {cb.get('p90', '?')})")
        if m.get("call_response") is not None:
            print(f"INS active {m['bars_with_ins']}/{m['bars']} bars  "
                  f"under-vocal {(m.get('ins_under_vocal') or 0):.2f}  "
                  f"call-response {m['call_response']:.2f}")
        else:
            print(f"INS active {m['bars_with_ins']}/{m['bars']} bars")
        mel = m.get("melisma")
        if mel:
            tgt = m.get("targets", {}).get("melisma")
            print(f"MELISMA {mel['rate']:.2f} notes/syl ({mel.get('notes')} notes / "
                  f"{mel.get('syllables')} syl)" + (f"  target {tgt} {'OK' if mel['rate'] >= tgt else 'LOW'}" if tgt else ""))
        print(f"PHRASE longest {m['longest_vocal_run']['seconds']}s  |  "
              f"CHORDS {m['chord_changes_per_bar']:.2f}/bar  "
              f"{', '.join(list(m['chord_qualities'])[:6])}")
        if m["sections"]:
            print("SECTIONS " + " | ".join(
                f"{s['label']} {s['bars']}b med {s['median']} ({s['vocal_notes']}n, ins {s['ins_notes']})"
                for s in m["sections"]))
        craft = m.get("craft") or {}
        cm = craft.get("metrics") or {}
        if cm:
            def num(key, fmt="{:.2f}"):
                value = cm.get(key)
                return "n/a" if value is None else (fmt.format(value)
                                                     if isinstance(value, float) else str(value))
            print(f"CRAFT phrases {num('phrases')}  notes {num('notes')}  "
                  f"long-notes {num('long_note_share')}  fast-notes {num('fast_note_share')}  "
                  f"end-long {num('phrase_end_long_share')}  "
                  f"reg-stdev {num('verse_register_stdev')}  range {num('verse_register_range')}  "
                  f"cad-on-1 {num('cadence_tonic_share')}  motif {num('motif_reuse')}")
            if craft.get("flags"):
                print("CRAFT FLAGS " + "; ".join(craft["flags"][:8]))
            else:
                print("CRAFT OK")
        if m["flags"]:
            print("FLAGS " + "; ".join(m["flags"][:10]))
        if m["diagnostics"]:
            print("DIAGS " + "; ".join(m["diagnostics"][:8]))
        if m["errors"]:
            print("ERRORS")
            for e in m["errors"][:10]:
                print("  " + e)
        if m["warnings"]:
            print("WARNINGS")
            for w in m["warnings"][:8]:
                print("  " + w)
    return 0 if r.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
