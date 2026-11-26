#!/usr/bin/env python3
"""Mine the SheetSage2 Arabic ABC corpus into a compact reference profile.

Standard library only.  Run once over the ~670 files; the outputs are stored
in assets/corpus_profile.json and read by the skill and the validator.

Usage:
    python3 scripts/mine_corpus.py --corpus DIR --out assets/corpus_profile.json
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from collections import Counter, defaultdict
from fractions import Fraction
from statistics import median

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from abc_common import (  # noqa: E402
    bar_has_notes, bar_rest_beats, bar_total_beats, load_json, parse_abc,
    pct_block, percentile, voice_notes,
)

CHORD_RE = re.compile(r"^([A-G][#b]?)(.*)$")
QUALITY_OK = {
    "", "m", "maj7", "m7", "7", "6", "m6", "m7b5", "dim", "aug", "sus2",
    "sus4", "7sus4", "9", "m9", "dim7", "maj9", "5",
}

TEMPO_BANDS = (("slow", 0, 90), ("mid", 91, 120), ("fast", 121, 999))


def chord_root_quality(ch: str) -> tuple[int, str] | None:
    """Return (pitch-class offset from C, quality) for a chord symbol."""
    ch = ch.strip()
    m = CHORD_RE.match(ch)
    if not m:
        return None
    root, quality = m.group(1), m.group(2)
    # Slash chords: use the upper root for the loop, as the corpus does.
    if "/" in quality:
        quality = quality.split("/", 1)[0]
    if quality not in QUALITY_OK:
        return None
    base = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}[root[0]]
    if root[1:] == "#":
        base += 1
    elif root[1:] == "b":
        base -= 1
    return base % 12, quality


def normalize_loop(chords: list[str], tonic_pc: int) -> tuple[str, ...]:
    out = []
    for ch in chords:
        rq = chord_root_quality(ch)
        if rq is None:
            continue
        root, quality = rq
        out.append(f"{(root - tonic_pc) % 12}{quality.replace('maj', 'M')}")
    return tuple(out)


def section_runs(bars: list[dict]) -> list[tuple[str, int]]:
    runs = []
    last = object()
    for bar in bars:
        sec = bar.get("section") or "unlabelled"
        if sec != last:
            runs.append([sec, 0])
            last = sec
        runs[-1][1] += 1
    return [(s, n) for s, n in runs]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--corpus", required=True, help="directory of suno-*.abc")
    ap.add_argument("--out", default="assets/corpus_profile.json")
    ap.add_argument("--limit", type=int, default=0, help="debug: only first N files")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    paths = sorted(glob.glob(os.path.join(args.corpus, "*.abc")))
    if args.limit:
        paths = paths[: args.limit]
    if not paths:
        print(f"no .abc files under {args.corpus}", file=sys.stderr)
        return 2

    meter_counts = Counter()
    grid_counts = Counter()
    key_counts = Counter()
    tempo_counts = Counter()
    empty_vocal = []
    empty_ins = []
    voice_mismatch = []
    glitch_bars = []
    glitch_count = 0
    off_meter_count = 0
    isolated_meter_runs = 0
    off_meter_examples = []

    per_file = []
    section_lengths = defaultdict(list)
    section_counts = Counter()
    forms = Counter()
    chord_qualities = Counter()
    chord_changes = []
    loops = Counter()
    durations = Counter()
    ins_riffs = {band: Counter() for band, _, _ in TEMPO_BANDS}
    pitch_hist = defaultdict(lambda: [0] * 12)
    pitch_hist_notes = Counter()

    for path in paths:
        name = os.path.basename(path)
        try:
            parsed = parse_abc(path)
        except Exception as exc:
            glitch_bars.append({"file": name, "error": f"parse: {exc}"})
            glitch_count += 1
            continue
        hdr = parsed["header"]
        voices = parsed["voices"]
        v = voices.get("Vocal", [])
        ins = voices.get("Ins", [])
        meter_counts[f"{hdr['M'][0]}/{hdr['M'][1]}"] += 1
        grid_counts[f"1/{hdr['L']}"] += 1
        key_counts[hdr["K"].split()[0]] += 1
        tempo_counts[hdr["Q"]] += 1

        if len(v) != len(ins):
            voice_mismatch.append({"file": name, "vocal": len(v), "ins": len(ins)})

        all_bars = v + ins
        if not all_bars:
            empty_vocal.append(name)
            continue
        dm = Counter((b["meter"] for b in all_bars)).most_common(1)[0][0]
        core_v = [b for b in v if b["meter"] == dm]
        core_i = [b for b in ins if b["meter"] == dm]

        for voice_name, bars in (("Vocal", v), ("Ins", ins)):
            for b in bars:
                if not b.get("sum_ok", True):
                    glitch_count += 1
                    if len(glitch_bars) < 80:
                        glitch_bars.append({
                            "file": name, "voice": voice_name,
                            "meter": f"{b['meter'][0]}/{b['meter'][1]}",
                            "sum": str(b.get("sum", "")),
                        })
            # Non-dominant meter can be an intentional 2/4 section; short runs
            # are the likely transcriber slips the brief warns about.
            run = []
            for b in bars + [None]:
                if b is not None and b["meter"] != dm:
                    run.append(b)
                    continue
                if run:
                    off_meter_count += len(run)
                    if len(run) <= 2:
                        isolated_meter_runs += 1
                        if len(off_meter_examples) < 40:
                            off_meter_examples.append({
                                "file": name, "voice": voice_name,
                                "meter": f"{run[0]['meter'][0]}/{run[0]['meter'][1]}",
                                "dominant": f"{dm[0]}/{dm[1]}",
                                "length": len(run),
                            })
                    run = []

        vnotes = voice_notes(core_v)
        inotes = voice_notes(core_i)
        if len(vnotes) < 4:
            empty_vocal.append(name)
            # Still use the file for form/chords/Ins, but not for vocal stats.
        if len(inotes) < 4:
            empty_ins.append(name)

        # Section form and lengths from the vocal voice, falling back to Ins.
        form_bars = core_v if core_v else core_i
        runs = section_runs(form_bars)
        for sec, n in runs:
            if sec in ("silence", "unlabelled"):
                continue
            section_lengths[sec].append(n)
            section_counts[sec] += 1
        form = " ".join(sec for sec, _ in runs if sec not in ("silence", "unlabelled"))
        if form:
            forms[form[:120]] += 1

        # Chords, qualitatively, from the vocal voice.
        seq = []
        this_chord_changes = None
        for b in core_v:
            if b["chords"]:
                seq.append(b["chords"][0])
        if seq:
            for ch in seq:
                rq = chord_root_quality(ch)
                if rq:
                    chord_qualities[rq[1] or "maj"] += 1
            changes = sum(1 for a, b in zip(seq, seq[1:]) if a != b)
            this_chord_changes = changes / max(1, len(core_v))
            chord_changes.append(this_chord_changes)
            tonic_pc = hdr["key"]["tonic_pc"]
            # A loop is a sequence of changes, not a run of held chords.
            changed = []
            for ch in seq:
                if not changed or ch != changed[-1]:
                    changed.append(ch)
            norm = normalize_loop(changed, tonic_pc)
            for i in range(0, max(0, len(norm) - 3)):
                loops[norm[i:i + 4]] += 1

        # Pooled note durations, vocal.
        for ev in vnotes:
            durations[str(ev["dur"])] += 1

        if len(vnotes) < 4:
            continue

        pitches = [ev["midi"] for ev in vnotes]
        lo, hi = min(pitches), max(pitches)
        steps = leaps = reps = 0
        for a, b in zip(pitches, pitches[1:]):
            d = abs(b - a)
            if d == 0:
                reps += 1
            elif d <= 2:
                steps += 1
            else:
                leaps += 1
        total_moves = max(1, steps + leaps + reps)
        core_beats = sum((bar_total_beats(b) for b in core_v), Fraction(0))
        rest_beats = sum((bar_rest_beats(b) for b in core_v), Fraction(0))
        active_bars = sum(1 for b in core_v if bar_has_notes(b))
        ins_active = sum(1 for b in core_i if bar_has_notes(b))
        vocal_silent = [b for b in core_v if not bar_has_notes(b)]
        call_num = 0
        for bv, bi in zip(core_v, core_i):
            if not bar_has_notes(bv) and bar_has_notes(bi):
                call_num += 1
        call = call_num / len(vocal_silent) if vocal_silent else None

        # Chorus lift.
        by_sec = defaultdict(list)
        for b in core_v:
            for ev in b["events"]:
                if ev["type"] == "note":
                    by_sec[b.get("section") or "unlabelled"].append(ev["midi"])
        lift = None
        if len(by_sec.get("verse", [])) >= 10 and len(by_sec.get("chorus", [])) >= 10:
            lift = median(by_sec["chorus"]) - median(by_sec["verse"])

        # Pitch-class profile by key, for maqam inference.
        tonic = hdr["key"]["tonic_midi"]
        key_name = hdr["K"].split()[0]
        for ev in vnotes:
            pitch_hist[key_name][(ev["midi"] - tonic) % 12] += 1
            pitch_hist_notes[key_name] += 1

        # Instrumental riff shapes by tempo band.
        band_name = "slow" if hdr["Q"] <= 90 else "mid" if hdr["Q"] <= 120 else "fast"
        for b in core_i:
            evs = [ev for ev in b["events"] if ev["type"] == "note"]
            if len(evs) < 2:
                continue
            shape = " ".join(
                f"{(ev['midi'] - tonic) % 12}:{ev['dur']}" for ev in evs
            )
            ins_riffs[band_name][shape] += 1

        per_file.append({
            "file": name,
            "bars": len(core_v),
            "tempo": hdr["Q"],
            "meter": dm,
            "key": key_name,
            "lo": lo,
            "hi": hi,
            "span": hi - lo,
            "step": steps / total_moves,
            "leap": leaps / total_moves,
            "repeat": reps / total_moves,
            "onset": len(vnotes) / max(1, float(core_beats)),
            "rest": float(rest_beats) / max(1, float(core_beats)),
            "vocal_active": active_bars / max(1, len(core_v)),
            "ins_active": ins_active / max(1, len(core_i)),
            "call": call,
            "lift": lift,
            "chord_changes": this_chord_changes,
            "notes_per_active_bar": len(vnotes) / max(1, active_bars),
        })

    def vals(key):
        return [r[key] for r in per_file if r.get(key) is not None]

    profile = {
        "schema": 1,
        "corpus": {
            "files": len(paths),
            "used_for_vocal": len(per_file),
            "empty_vocal_count": len(empty_vocal),
            "empty_vocal": empty_vocal,
            "empty_ins_count": len(empty_ins),
            "empty_ins": empty_ins,
            "voice_count_mismatch": voice_mismatch,
            "glitch_count": glitch_count,
            "glitch_examples": glitch_bars[:40],
            "non_dominant_meter_bars": off_meter_count,
            "isolated_meter_runs": isolated_meter_runs,
            "isolated_meter_examples": off_meter_examples[:20],
        },
        "meters": dict(meter_counts.most_common()),
        "grids": dict(grid_counts.most_common()),
        "keys": dict(key_counts.most_common(30)),
        "tempos": {
            "counts": dict(sorted(tempo_counts.items(), key=lambda kv: -kv[1])[:20]),
            "percentiles": pct_block([r["tempo"] for r in per_file]),
        },
        "percentiles": {
            "bars_per_song": pct_block([r["bars"] for r in per_file]),
            "vocal_low": pct_block(vals("lo")),
            "vocal_high": pct_block(vals("hi")),
            "vocal_span": pct_block(vals("span")),
            "step_ratio": pct_block(vals("step")),
            "leap_ratio": pct_block(vals("leap")),
            "repeat_ratio": pct_block(vals("repeat")),
            "onsets_per_beat": pct_block(vals("onset")),
            "rest_ratio": pct_block(vals("rest")),
            "vocal_active_bars": pct_block(vals("vocal_active")),
            "ins_active_bars": pct_block(vals("ins_active")),
            "ins_in_vocal_gaps": pct_block(vals("call")),
            "chorus_lift_semitones": pct_block(vals("lift")),
            "chord_changes_per_bar": pct_block(vals("chord_changes")),
            "notes_per_active_vocal_bar": pct_block(vals("notes_per_active_bar")),
        },
        "durations": {
            "vocal_note_counts": dict(sorted(durations.items(), key=lambda kv: -kv[1])),
            "top": dict(durations.most_common(12)),
        },
        "sections": {
            "counts": dict(section_counts.most_common()),
            "lengths": {k: pct_block(v) for k, v in section_lengths.items()},
            "forms": [{"form": f, "count": n} for f, n in forms.most_common(12)],
        },
        "chords": {
            "qualities": dict(chord_qualities.most_common(20)),
            "loops": [
                {"loop": list(k), "count": n}
                for k, n in loops.most_common(20)
            ],
        },
        "ins_riffs": {
            band: [
                {"shape": s, "count": n}
                for s, n in counter.most_common(12)
            ]
            for band, counter in ins_riffs.items()
        },
        "pitch_class_profiles": {
            key: {
                "notes": pitch_hist_notes[key],
                "percent": [
                    round(100.0 * n / max(1, pitch_hist_notes[key]), 1)
                    for n in hist
                ],
            }
            for key, hist in sorted(pitch_hist.items(), key=lambda kv: -pitch_hist_notes[kv[0]])[:20]
            if pitch_hist_notes[key] >= 100
        },
        "notes": [
            "Empty-vocal files are excluded from vocal statistics.",
            "Bars whose meter differs from the file's dominant meter are ignored.",
            "Glitch bars are logged, not silently corrected.",
            "The corpus has no w: lyrics, so melisma is not in these percentiles.",
        ],
    }

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=2, sort_keys=False)
        f.write("\n")

    if not args.quiet:
        p = profile["percentiles"]
        print(f"wrote {args.out}")
        print(f"files {profile['corpus']['files']}  used {profile['corpus']['used_for_vocal']}  "
              f"empty-vocal {profile['corpus']['empty_vocal_count']}  "
              f"glitch {profile['corpus']['glitch_count']}")
        print("p50 / p10-p90:")
        for k in ("bars_per_song", "vocal_span", "step_ratio", "leap_ratio",
                  "repeat_ratio", "onsets_per_beat", "rest_ratio", "chorus_lift_semitones"):
            b = p[k]
            print(f"  {k:26s} {b['p50']}  ({b['p10']}-{b['p90']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
