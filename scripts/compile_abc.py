#!/usr/bin/env python3
"""Compile a musical Blueprint (JSON) into a SheetSage2-style two-voice ABC.

The model composes in scale degrees and beats.  This script does the notation
math: bar sums, voice alignment, key-signature spelling, chord validation,
motif/repeat expansion, syllable alignment, and grid conversion.  It never
chooses a note.

Usage:
    python3 scripts/compile_abc.py blueprint.json -o song.abc \
        --report song.report.json --validation-out song.validation.abc \
        --intake intake.json --strict
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import os
import re
import sys
from fractions import Fraction

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from abc_common import (  # noqa: E402
    LETTERS, degree_to_midi, dump_json, load_json, parse_key, spell_midi,
    split_duration,
)

CHORD_QUALITIES = [
    "", "m", "maj7", "m7", "7", "6", "m6", "m7b5", "dim", "aug", "sus2",
    "sus4", "7sus4", "9", "m9", "dim7", "maj9", "5",
]
CHORD_RE = re.compile(
    r"^([A-G][#b]?)(" + "|".join(re.escape(q) for q in sorted(CHORD_QUALITIES, key=len, reverse=True)) + r")?(?:/([A-G][#b]?))?$"
)

# Semitones above the tonic -> the degree label used in Blueprint notes.
DEGREE_BY_PC = {
    0: "1", 1: "b2", 2: "2", 3: "b3", 4: "3", 5: "4",
    6: "#4", 7: "5", 8: "b6", 9: "6", 10: "b7", 11: "7",
}



class CompileError(Exception):
    def __init__(self, code: str, msg: str, section: str | None = None,
                 bar: int | None = None):
        super().__init__(msg)
        self.code = code
        self.msg = msg
        self.section = section
        self.bar = bar


def as_fraction(value, default: Fraction | None = None) -> Fraction:
    if value is None:
        if default is not None:
            return default
        raise ValueError("missing duration")
    if isinstance(value, Fraction):
        return value
    if isinstance(value, int):
        return Fraction(value)
    if isinstance(value, float):
        return Fraction(str(value)).limit_denominator(64)
    s = str(value).strip()
    if s.endswith("~"):
        s = s[:-1]
    if "/" in s:
        a, b = s.split("/", 1)
        return Fraction(int(a), int(b))
    if "." in s:
        return Fraction(s).limit_denominator(64)
    return Fraction(int(s))


def parse_duration_token(token: str) -> tuple[Fraction, bool]:
    tie = token.endswith("~")
    if tie:
        token = token[:-1]
    return as_fraction(token), tie


def parse_meter(text) -> tuple[int, int]:
    if isinstance(text, (tuple, list)) and len(text) == 2:
        num, den = int(text[0]), int(text[1])
        if num > 0 and den > 0:
            return num, den
    m = re.match(r"^(\d+)/(\d+)$", str(text).strip())
    if not m:
        raise CompileError("bad_meter", f"bad meter {text!r}")
    num, den = int(m.group(1)), int(m.group(2))
    if num <= 0 or den <= 0:
        raise CompileError("bad_meter", f"bad meter {text!r}")
    return num, den


def bar_beats(meter: tuple[int, int]) -> Fraction:
    return Fraction(meter[0] * 4, meter[1])


def validate_chord(ch: str) -> str:
    if ch is None:
        return ""
    ch = str(ch).strip()
    if not ch:
        return ""
    if not CHORD_RE.match(ch):
        raise CompileError("bad_chord", f"unsupported chord symbol {ch!r}")
    return ch


# ---------------------------------------------------------------------------
# Voice-string parsing
# ---------------------------------------------------------------------------

def tokenize_voice(text: str) -> list[str]:
    return re.findall(r"\(|\)|[^\s()]+", text or "")


def parse_voice_string(text: str, key_info: dict, octave_offset: int = 0,
                       default_dur: Fraction = Fraction(1)) -> tuple[list[dict], int]:
    """Parse a literal voice string into events and syllable-group count."""
    text = (text or "").strip()
    if not text:
        return [], 0
    if text == "rest":
        return [{"type": "rest", "dur": Fraction(0)}], 0

    tokens = tokenize_voice(text)
    events: list[dict] = []
    group = 0
    in_group = False
    group_start = len(events)
    group_id = None
    bare_count = 0

    def close_group():
        nonlocal group_start, group_id, in_group
        if in_group:
            group_events = events[group_start:]
            if not any(ev["type"] == "note" for ev in group_events):
                raise CompileError("bad_group", "a melisma group needs at least one note")
            for ev in group_events:
                if ev["type"] == "note":
                    ev["group"] = group_id
            in_group = False
            group_start = len(events)
            group_id = None

    for tok in tokens:
        if tok == "(":
            if in_group:
                raise CompileError("bad_group", "nested melisma groups are not supported")
            group += 1
            group_id = group
            group_start = len(events)
            in_group = True
            continue
        if tok == ")":
            if not in_group:
                raise CompileError("bad_group", "unmatched ')' in voice string")
            close_group()
            continue
        if tok.startswith("r:"):
            dur, tie = parse_duration_token(tok[2:])
            ev = {"type": "rest", "dur": dur}
            if in_group:
                ev["group"] = group_id
            events.append(ev)
            continue
        if tok in ("rest", "|"):
            continue

        if ":" in tok:
            degree, dur_s = tok.split(":", 1)
        else:
            degree, dur_s = tok, None
        dur, tie = parse_duration_token(dur_s) if dur_s else (default_dur, False)
        if dur <= 0:
            raise CompileError("bad_duration", f"duration must be positive: {tok!r}")
        midi, letter, norm_degree = degree_to_midi(degree, key_info, octave_offset)
        ev = {
            "type": "note",
            "midi": midi,
            "letter": letter,
            "degree": norm_degree,
            "dur": dur,
            "tie": tie,
            "group": None,
        }
        if in_group:
            ev["group"] = group_id
            ev["group_first"] = not any(
                e["type"] == "note" for e in events[group_start:]
            )
        else:
            group += 1
            ev["group"] = group
            ev["group_first"] = True
            bare_count += 1
        events.append(ev)

    if in_group:
        raise CompileError("bad_group", "unclosed '(' in voice string")
    return events, group


def apply_vary(events: list[dict], vary: str, key_info: dict,
               octave_offset: int = 0) -> None:
    """vary:end-<degree> replaces the final note's degree."""
    if not vary.startswith("end-"):
        raise CompileError("bad_motif", f"unknown vary transform {vary!r}")
    degree = vary[4:]
    note = None
    for ev in reversed(events):
        if ev["type"] == "note":
            note = ev
            break
    if note is None:
        raise CompileError("bad_motif", f"vary:{vary} but no note to vary")
    midi, letter, norm = degree_to_midi(degree, key_info, octave_offset)
    # Keep the varied note in the octave of the note it replaces.
    midi += 12 * int(round((note["midi"] - midi) / 12.0))
    note["midi"] = midi
    note["letter"] = letter
    note["degree"] = norm


def apply_transpose(events: list[dict], semitones: int) -> None:
    if not semitones:
        return
    for ev in events:
        if ev["type"] != "note":
            continue
        ev["midi"] = ev["midi"] + semitones
        steps = int(round(semitones * 7 / 12.0))
        ev["letter"] = LETTERS[(LETTERS.index(ev["letter"]) + steps) % 7]


def trailing_rest(events) -> Fraction:
    total = Fraction(0)
    for ev in reversed(events):
        if ev["type"] == "note":
            break
        total += ev["dur"]
    return total


def ensure_breath(events: list[dict], required: float) -> Fraction:
    """Guarantee a trailing breath rest, shortening notes if the bar is full.

    Returns the number of beats that had to be taken from notes (0 when the
    rest was already long enough).  Raises when even the shortest allowed note
    cannot make room; the composer then has to shorten that bar deliberately.
    """
    need = Fraction(str(required)).limit_denominator(64) - trailing_rest(events)
    if need <= 0:
        return Fraction(0)
    original = need
    minimum = Fraction(1, 4)
    for ev in reversed(events):
        if ev["type"] != "note":
            continue
        room = ev["dur"] - minimum
        if room <= 0:
            continue
        take = min(need, room)
        ev["dur"] -= take
        need -= take
        if need <= 0:
            break
    if need > 0:
        raise CompileError(
            "breath_space",
            f"cannot fit r:{required} breath without deleting notes; "
            f"shorten an earlier note in this bar",
        )
    # Put the freed time after the last note.
    if events and events[-1]["type"] == "rest":
        events[-1]["dur"] += original
    else:
        events.append({"type": "rest", "dur": original})
    return original


def expand_voice(text: str, motifs: dict, field: str, key_info: dict,
                 octave_offset: int = 0, stack: tuple[str, ...] = ()) -> list[dict]:
    """Expand a motif reference or a literal voice string into events."""
    raw = (text or "").strip()
    if not raw:
        return []
    toks = raw.split()
    if toks and toks[0] in motifs:
        name = toks[0]
        transforms = toks[1:]
        if name in stack:
            raise CompileError("bad_motif", f"motif cycle: {' -> '.join(stack + (name,))}")
        motif = motifs[name]
        if not isinstance(motif, dict) or field not in motif:
            raise CompileError("bad_motif", f"motif {name!r} has no {field!r} line")
        events = expand_voice(motif[field], motifs, field, key_info,
                              octave_offset, stack + (name,))
        semis = 0
        vary = None
        for tr in transforms:
            if tr == "+oct":
                semis += 12
            elif tr == "-oct":
                semis -= 12
            elif tr.startswith("shift:"):
                semis += int(tr.split(":", 1)[1])
            elif tr.startswith("vary:"):
                vary = tr.split(":", 1)[1]
            else:
                raise CompileError("bad_motif", f"unknown motif transform {tr!r}")
        if vary:
            apply_vary(events, vary, key_info, octave_offset)
        apply_transpose(events, semis)
        return events
    return parse_voice_string(raw, key_info, octave_offset)[0]


# ---------------------------------------------------------------------------
# Section / bar resolution
# ---------------------------------------------------------------------------

def resolve_sections(bp: dict) -> list[dict]:
    raw_sections = bp.get("sections") or []
    by_id = {}
    for s in raw_sections:
        if "id" not in s:
            raise CompileError("bad_section", "every section needs an id")
        if s["id"] in by_id:
            raise CompileError("bad_section", f"duplicate section id {s['id']!r}")
        by_id[s["id"]] = s

    resolved: dict[str, dict] = {}
    resolving: set[str] = set()

    def get(sec_id: str) -> dict:
        if sec_id in resolved:
            return resolved[sec_id]
        if sec_id not in by_id:
            raise CompileError("bad_section", f"unknown section id {sec_id!r}")
        if sec_id in resolving:
            raise CompileError("bad_section", f"section cycle at {sec_id!r}")
        resolving.add(sec_id)
        raw = by_id[sec_id]
        source_id = raw.get("same_as")
        if source_id:
            src = get(source_id)
            bars = copy.deepcopy(src["bars"])
            take = raw.get("take")
            if take is None and isinstance(raw.get("bars"), list) and raw["bars"] and all(isinstance(x, int) for x in raw["bars"]):
                take = raw["bars"]
            if take is not None:
                bad = [i for i in take if not (0 <= i < len(bars))]
                if bad:
                    raise CompileError(
                        "bad_repeat",
                        f"take indexes {bad} are outside section {source_id!r} "
                        f"(0-{len(bars)-1})",
                    )
                bars = [copy.deepcopy(bars[i]) for i in take]
            vshift = int(raw.get("voc_shift", 0) or 0)
            ishift = int(raw.get("ins_shift", 0) or 0)
            syl_override = raw.get("syl")
            for i, b in enumerate(bars):
                b["_voc_shift"] = b.get("_voc_shift", 0) + vshift
                b["_ins_shift"] = b.get("_ins_shift", 0) + ishift
                if syl_override is not None:
                    if isinstance(syl_override, list):
                        if i < len(syl_override):
                            b["syl"] = syl_override[i]
                    else:
                        b["syl"] = syl_override
            out = {
                "id": sec_id,
                "kind": raw.get("kind", src.get("kind", "verse")),
                "meter": parse_meter(raw.get("meter", src.get("meter", bp["meta"].get("meter", "4/4")))),
                "bars": bars,
                "cues": raw.get("cues", src.get("cues", "")),
            }
        else:
            bars = copy.deepcopy(raw.get("bars") or [])
            meter = parse_meter(raw.get("meter", bp["meta"].get("meter", "4/4")))
            out = {
                "id": sec_id,
                "kind": raw.get("kind", "verse"),
                "meter": meter,
                "bars": bars,
                "cues": raw.get("cues", ""),
            }
        # Resolve bar-level copies.
        for i, b in enumerate(out["bars"]):
            src_id = b.get("from") or b.get("repeat")
            if src_id:
                src = get(src_id)
                take = b.get("take")
                if take is None and isinstance(b.get("bars"), list) and b["bars"] and all(isinstance(x, int) for x in b["bars"]):
                    take = b["bars"]
                if take is None:
                    copied = copy.deepcopy(src["bars"])
                else:
                    bad = [j for j in take if not (0 <= j < len(src["bars"]))]
                    if bad:
                        raise CompileError(
                            "bad_repeat",
                            f"take indexes {bad} are outside section {src_id!r} "
                            f"(0-{len(src['bars'])-1})",
                            out["id"], i,
                        )
                    copied = [copy.deepcopy(src["bars"][j]) for j in take]
                if len(copied) != 1:
                    raise CompileError(
                        "bad_repeat",
                        f"bar-level copy must resolve to exactly 1 bar, got {len(copied)}",
                        out["id"], i,
                    )
                newbar = copied[0]
                # Explicit fields on the copy override the source.
                for k in ("voc", "ins", "syl", "ch"):
                    if k in b:
                        newbar[k] = b[k]
                newbar["_voc_shift"] = newbar.get("_voc_shift", 0) + int(b.get("voc_shift", 0) or 0)
                newbar["_ins_shift"] = newbar.get("_ins_shift", 0) + int(b.get("ins_shift", 0) or 0)
                out["bars"][i] = newbar
            else:
                if "voc_shift" in b:
                    b["_voc_shift"] = int(b.get("voc_shift", 0) or 0)
                if "ins_shift" in b:
                    b["_ins_shift"] = int(b.get("ins_shift", 0) or 0)
        resolving.remove(sec_id)
        resolved[sec_id] = out
        return out

    return [get(s["id"]) for s in raw_sections]


# ---------------------------------------------------------------------------
# Syllables
# ---------------------------------------------------------------------------

def build_line_map(intake: dict | None) -> dict:
    if not intake:
        return {}
    return {line["id"]: line for line in intake.get("lines", [])}


def line_refs(syl) -> list[str]:
    """Unique intake line ids referenced by a bar's syl field, in order."""
    if syl is None:
        return []
    tokens = []
    if isinstance(syl, list):
        for item in syl:
            tokens.extend(str(item).split())
    else:
        tokens = str(syl).split()
    seen = []
    for tok in tokens:
        if not tok.startswith("@"):
            continue
        m = re.match(r"^@([^:]+)", tok)
        if m and m.group(1) not in seen:
            seen.append(m.group(1))
    return seen


def resolve_syllables(syl, line_map: dict, used: dict | None = None) -> list[str] | None:
    if syl is None:
        return None
    if isinstance(syl, list):
        tokens = []
        for item in syl:
            tokens.extend(str(item).split())
    else:
        tokens = str(syl).split()
    out = []
    for tok in tokens:
        if not tok.startswith("@"):
            out.append(tok)
            continue
        m = re.match(r"^@([^:]+)(?::(\d+)-(\d+))?$", tok)
        if not m:
            raise CompileError("bad_syl", f"bad lyric reference {tok!r}")
        line_id, a_s, b_s = m.group(1), m.group(2), m.group(3)
        if line_id not in line_map:
            raise CompileError(
                "bad_syl",
                f"unknown lyric line {line_id!r}; run intake_lyrics.py and pass --intake",
            )
        line = line_map[line_id]
        syls = line["syllables"]
        if a_s and b_s:
            a, b = int(a_s), int(b_s)
            if not (1 <= a <= b <= len(syls)):
                raise CompileError(
                    "bad_syl",
                    f"{tok!r} is outside {line_id} (1-{len(syls)})",
                )
            chunk = syls[a - 1:b]
        else:
            chunk = syls
        if used is not None:
            used[line_id] = used.get(line_id, 0) + len(chunk)
        out.extend(chunk)
    return out


# ---------------------------------------------------------------------------
# Fill merge
# ---------------------------------------------------------------------------

def merge_fill(skeleton: dict, fill: dict) -> dict:
    """Merge a compact ``fill.json`` into a generated skeleton.

    The skeleton owns meta, sections, bars, chords, and syl ranges.  The fill
    owns only the musical strings, one [voc, ins] pair per bar in section
    order.  A ``same_as`` section is filled from its source and must not appear
    in the fill.
    """
    merged = copy.deepcopy(skeleton)
    fill_meta = fill.get("meta") or {}
    if fill_meta:
        merged.setdefault("meta", {})
        for key, value in fill_meta.items():
            if key == "targets" and isinstance(value, dict):
                merged["meta"].setdefault("targets", {}).update(value)
            else:
                merged["meta"][key] = value
    if "motifs" in fill:
        merged["motifs"] = fill["motifs"] or {}

    rows_by_section = fill.get("fill")
    if not isinstance(rows_by_section, dict):
        raise CompileError("bad_fill", "fill.json needs a 'fill' object keyed by section")
    sections = merged.get("sections") or []
    known = {s.get("id") for s in sections}
    unknown = [sid for sid in rows_by_section if sid not in known]
    if unknown:
        raise CompileError("bad_fill", f"unknown section(s) in fill: {', '.join(unknown)}")

    for sec in sections:
        sid = sec.get("id")
        if sec.get("same_as"):
            if sid in rows_by_section:
                raise CompileError(
                    "bad_fill",
                    f"section {sid!r} uses same_as {sec['same_as']!r}; "
                    f"fill the source section instead",
                )
            continue
        if sid not in rows_by_section:
            raise CompileError("bad_fill", f"missing section {sid!r} in fill")
        rows = rows_by_section[sid]
        bars = sec.get("bars") or []
        if not isinstance(rows, list) or len(rows) != len(bars):
            got = len(rows) if isinstance(rows, list) else "not a list"
            raise CompileError(
                "bad_fill",
                f"section {sid!r} needs {len(bars)} [voc,ins] rows, got {got}",
            )
        for i, row in enumerate(rows):
            if not isinstance(row, (list, tuple)) or len(row) != 2:
                raise CompileError(
                    "bad_fill",
                    f"section {sid!r} bar {i + 1} must be [voc, ins]",
                )
            voc, ins = row
            bars[i]["voc"] = "rest" if voc in (None, "") else str(voc)
            bars[i]["ins"] = "rest" if ins in (None, "") else str(ins)
    return merged


# ---------------------------------------------------------------------------
# Compilation
# ---------------------------------------------------------------------------

def compile_blueprint(bp: dict, intake: dict | None = None, strict: bool = False) -> dict:
    meta = bp.get("meta") or {}
    if "key" not in meta:
        raise CompileError("bad_meta", "meta.key is required")
    key_info = parse_key(meta["key"])
    key_out = key_info["tonic_letter"] + key_info["tonic_acc"] + ("m" if key_info["minor"] else "")
    meter = parse_meter(meta.get("meter", "4/4"))
    tempo = int(meta.get("tempo", 90))
    vocals_oct = int(meta.get("vocal_octave", 0) or 0)
    inst_oct = int(meta.get("instrument_octave", 0) or 0)
    vrange = meta.get("vocal_range") or [48, 84]
    irange = meta.get("instrument_range") or [36, 96]
    motifs = bp.get("motifs") or {}
    line_map = build_line_map(intake)
    used_lines: dict[str, int] = {}

    sections = resolve_sections(bp)
    if not sections:
        raise CompileError("bad_section", "the Blueprint has no sections")

    errors: list[dict] = []
    warnings: list[dict] = []
    compiled_sections = []
    all_events = []
    auto_breath: list[dict] = []

    for sec in sections:
        sec_bars = sec["bars"]
        if not sec_bars:
            errors.append({"code": "empty_section", "section": sec["id"],
                           "msg": "section has no bars"})
            continue
        if line_map and sec["kind"] == "verse" and len(sec_bars) % 8 != 0:
            raise CompileError(
                "bad_verse_bars",
                f"verse has {len(sec_bars)} bars; write whole bayts "
                f"(4-bar shatr, 8-bar bayt), not a compressed verse",
                sec["id"],
            )
        beats = bar_beats(sec["meter"])
        line_ends = {}
        for bi0, rb0 in enumerate(sec_bars):
            for lid0 in line_refs(rb0.get("syl")):
                line_ends[lid0] = bi0
        out_bars = []
        for bi, rawbar in enumerate(sec_bars):
            try:
                ch = validate_chord(rawbar.get("ch"))
                voc_events = expand_voice(rawbar.get("voc", "rest"), motifs, "voc",
                                          key_info, vocals_oct)
                if rawbar.get("voc") in (None, "", "rest"):
                    voc_events = [{"type": "rest", "dur": beats}]
                ins_events = expand_voice(rawbar.get("ins", "rest"), motifs, "ins",
                                          key_info, inst_oct)
                if rawbar.get("ins") in (None, "", "rest"):
                    ins_events = [{"type": "rest", "dur": beats}]

                # Bar-level transposition from copied bars.
                if rawbar.get("_voc_shift"):
                    apply_transpose(voc_events, int(rawbar["_voc_shift"]))
                if rawbar.get("_ins_shift"):
                    apply_transpose(ins_events, int(rawbar["_ins_shift"]))

                # A literal "rest" event with dur 0 means "fill the bar".
                for evs in (voc_events, ins_events):
                    if len(evs) == 1 and evs[0]["type"] == "rest" and evs[0]["dur"] == 0:
                        evs[0]["dur"] = beats

                # A breath at the end of every shatr/bayt is mechanical, not a
                # musical decision.  Add it when the composer left it out.
                breath = 0.0
                for lid in line_refs(rawbar.get("syl")):
                    if line_ends.get(lid) != bi:
                        continue
                    role = (line_map.get(lid) or {}).get("role")
                    if role == "sadr":
                        breath = max(breath, 1.5)
                    elif role == "ajuz":
                        breath = max(breath, 2.0)
                if breath and any(ev["type"] == "note" for ev in voc_events):
                    freed = ensure_breath(voc_events, breath)
                    if freed:
                        auto_breath.append({
                            "section": sec["id"], "bar": bi + 1,
                            "beats": float(freed),
                        })

                vsum = sum((e["dur"] for e in voc_events), Fraction(0))
                isum = sum((e["dur"] for e in ins_events), Fraction(0))
                if vsum != beats:
                    raise CompileError(
                        "bar_sum",
                        f"vocal sums to {vsum} beats, meter needs {beats}",
                        sec["id"], bi,
                    )
                if isum != beats:
                    raise CompileError(
                        "bar_sum",
                        f"instrument sums to {isum} beats, meter needs {beats}",
                        sec["id"], bi,
                    )

                # Range checks.
                for ev in voc_events:
                    if ev["type"] == "note" and not (vrange[0] <= ev["midi"] <= vrange[1]):
                        raise CompileError(
                            "range",
                            f"vocal {ev['degree']} is MIDI {ev['midi']}, outside "
                            f"{vrange[0]}-{vrange[1]}",
                            sec["id"], bi,
                        )
                for ev in ins_events:
                    if ev["type"] == "note" and not (irange[0] <= ev["midi"] <= irange[1]):
                        raise CompileError(
                            "range",
                            f"instrument {ev['degree']} is MIDI {ev['midi']}, outside "
                            f"{irange[0]}-{irange[1]}",
                            sec["id"], bi,
                        )

                groups = sum(1 for e in voc_events if e["type"] == "note" and e.get("group_first"))
                syls = resolve_syllables(rawbar.get("syl"), line_map, used_lines)
                if syls is None:
                    if groups:
                        warnings.append({
                            "code": "no_syl", "section": sec["id"], "bar": bi,
                            "msg": f"{groups} vocal groups have no syl; alignment not verified",
                        })
                        if strict:
                            raise CompileError(
                                "no_syl",
                                f"missing syl for {groups} vocal groups (strict mode)",
                                sec["id"], bi,
                            )
                elif len(syls) != groups:
                    raise CompileError(
                        "syl_mismatch",
                        f"{len(syls)} syllables for {groups} vocal groups: "
                        f"{' '.join(syls[:8])}{'...' if len(syls) > 8 else ''}",
                        sec["id"], bi,
                    )
                # Attach syllable text to every note in a group; group_first
                # marks where a new syllable begins for the validation w: line.
                if syls is not None:
                    gi = 0
                    group_syl = {}
                    for ev in voc_events:
                        if ev["type"] == "note" and ev.get("group_first"):
                            group_syl[ev["group"]] = syls[gi]
                            gi += 1
                    for ev in voc_events:
                        if ev["type"] == "note":
                            ev["syl"] = group_syl.get(ev["group"])

                out_bars.append({
                    "ch": ch,
                    "voc": voc_events,
                    "ins": ins_events,
                    "syls": syls,
                    "groups": groups,
                    "line_ids": line_refs(rawbar.get("syl")),
                })
                all_events.extend(voc_events)
                all_events.extend(ins_events)
            except CompileError as exc:
                exc.section = exc.section or sec["id"]
                exc.bar = bi if exc.bar is None else exc.bar
                errors.append({"code": exc.code, "section": exc.section,
                               "bar": exc.bar, "msg": exc.msg})
        compiled_sections.append({
            "id": sec["id"], "kind": sec["kind"], "meter": sec["meter"],
            "bars": out_bars, "cues": sec.get("cues", ""),
        })

    # Ties must connect the same pitch; a rest or a different pitch breaks one.
    for sec in compiled_sections:
        for voice, key in (("vocal", "voc"), ("instrument", "ins")):
            pending = None
            for bi, bar in enumerate(sec["bars"]):
                for ev in bar[key]:
                    if ev["type"] == "rest":
                        if pending is not None:
                            errors.append({
                                "code": "bad_tie", "section": sec["id"], "bar": bi,
                                "msg": f"{voice} tie is broken by a rest",
                            })
                            pending = None
                        continue
                    if pending is not None:
                        if ev["midi"] != pending:
                            errors.append({
                                "code": "bad_tie", "section": sec["id"], "bar": bi,
                                "msg": f"{voice} tie ends on a different pitch "
                                       f"({pending} -> {ev['midi']})",
                            })
                        pending = None
                    if ev.get("tie"):
                        pending = ev["midi"]
            if pending is not None:
                errors.append({
                    "code": "bad_tie", "section": sec["id"], "bar": len(sec["bars"]) - 1,
                    "msg": f"{voice} tie is not resolved before the section ends",
                })

    if errors:
        return {
            "ok": False,
            "errors": errors,
            "warnings": warnings,
            "sections": [],
            "meta": meta,
        }

    # Choose a grid from the gcd of every duration.
    durs = [e["dur"] for e in all_events if e["dur"] > 0]
    if not durs:
        raise CompileError("empty_song", "no durations to compile")
    g = durs[0]
    for d in durs[1:]:
        g = Fraction(math.gcd(g.numerator * d.denominator, d.numerator * g.denominator),
                     g.denominator * d.denominator)
    if g >= Fraction(1, 4):
        l_den, units_per_beat = 16, Fraction(4)
    elif g >= Fraction(1, 8):
        l_den, units_per_beat = 32, Fraction(8)
    else:
        raise CompileError(
            "grid",
            f"smallest duration {g} beats is finer than 1/32; use 0.125 or larger",
        )

    # Every duration must land on an integer grid unit.
    for d in durs:
        u = d * units_per_beat
        if u.denominator != 1:
            raise CompileError("grid", f"duration {d} does not fit L:1/{l_den}")

    # Build the ABC.  The corpus keeps T: empty; a title belongs in notes.md.
    header = [
        "X:1",
        "T:",
        f"M:{meter[0]}/{meter[1]}",
        f"L:1/{l_den}",
        f"Q:1/4={tempo}",
        'V: Vocal clef=treble name="Vocal Melody" snm="Vocal"',
        'V: Ins clef=treble name="Ins Melody" snm="Inst."',
        f"K:{key_out}",
    ]
    body_lines: list[str] = []
    validation_lines: list[str] = []
    current_meter = meter
    section_report = []
    bar_cursor = 0
    w_counter = 0

    def voice_key(voice: str) -> str:
        return "voc" if voice == "Vocal" else "ins"

    def unit_parts(dur, units_per_beat, what):
        """Integer grid units of one event, split into representable parts.

        abcjs cannot draw 5, 9, 10, 11 or 13 units at L:1/16, so those are
        emitted as several parts (tied notes, consecutive rests).  The
        in-repo parser merges them back, so metrics do not change.
        """
        u = dur * units_per_beat
        if u.denominator != 1:
            raise CompileError("grid", f"{what} {dur} does not fit grid")
        whole_per_unit = Fraction(1, 4) / units_per_beat
        parts = []
        for part in split_duration(u * whole_per_unit):
            pu = part / whole_per_unit
            if pu.denominator != 1:
                raise CompileError("grid", f"{what} {dur} cannot be split on the grid")
            parts.append(int(pu))
        return parts

    def render_events(events, ch, voice, beats, units_per_beat, key_info):
        out = []
        if voice == "Vocal" and ch:
            out.append(f'"{ch}"')
        had_event = False
        for ev in events:
            if ev["type"] == "rest":
                for pu in unit_parts(ev["dur"], units_per_beat, "rest"):
                    out.append("z" + ("" if pu == 1 else str(pu)))
                had_event = True
            else:
                parts = unit_parts(ev["dur"], units_per_beat, "note")
                pitch = spell_midi(ev["midi"], ev["letter"], key_info)
                for i, pu in enumerate(parts):
                    txt = pitch + ("" if pu == 1 else str(pu))
                    if i < len(parts) - 1 or ev.get("tie"):
                        txt += "-"
                    out.append(txt)
                had_event = True
        if not had_event:
            for pu in unit_parts(beats, units_per_beat, "rest"):
                out.append("z" + ("" if pu == 1 else str(pu)))
        return "".join(out)

    def is_silent(bar, voice):
        if voice == "Vocal" and bar["ch"]:
            return False
        return not any(ev["type"] == "note" for ev in bar[voice_key(voice)])

    def make_tokens(bars, voice, beats):
        tokens = []
        run = 0
        for b in bars:
            if is_silent(b, voice):
                run += 1
            else:
                if run:
                    while run > 4:
                        tokens.append(("Z4", 4, []))
                        run -= 4
                    tokens.append(("Z" + ("" if run == 1 else str(run)), run, []))
                    run = 0
                txt = render_events(b[voice_key(voice)], b["ch"], voice, beats,
                                    units_per_beat, key_info)
                tokens.append((txt, 1, [b]))
        if run:
            while run > 4:
                tokens.append(("Z4", 4, []))
                run -= 4
            tokens.append(("Z" + ("" if run == 1 else str(run)), run, []))
        return tokens

    def format_tokens(tokens):
        lines = []
        line, n = [], 0
        for tok, nbars, bars in tokens:
            if n + nbars > 4 and line:
                lines.append((line, n))
                line, n = [], 0
            line.append((tok, nbars, bars))
            n += nbars
            if n == 4:
                lines.append((line, n))
                line, n = [], 0
        if line:
            lines.append((line, n))
        return lines

    for sec in compiled_sections:
        sec_meter = sec["meter"]
        sec_beats = bar_beats(sec_meter)
        marker = f"% {str(sec['kind']).strip().lower()}"
        body_lines.append(marker)
        validation_lines.append(marker)
        change = sec_meter != current_meter
        current_meter = sec_meter
        for voice in ("Vocal", "Ins"):
            vline = f"V: {voice}"
            body_lines.append(vline)
            validation_lines.append(vline)
            if change:
                mline = f"M:{sec_meter[0]}/{sec_meter[1]}"
                body_lines.append(mline)
                validation_lines.append(mline)
            tokens = make_tokens(sec["bars"], voice, sec_beats)
            lines = format_tokens(tokens)
            for line, nbars in lines:
                text = "|".join(t for t, _, _ in line) + "|"
                body_lines.append(text)
                validation_lines.append(text)
                if voice == "Vocal":
                    w_tokens = []
                    for t, nb, bars in line:
                        if t.startswith("Z"):
                            continue
                        for b in bars:
                            for ev in b["voc"]:
                                if ev["type"] != "note":
                                    continue
                                if "syl" in ev:
                                    if ev.get("group_first"):
                                        w_counter += 1
                                        w_tokens.append(f"s{w_counter}")
                                    else:
                                        w_tokens.append("*")
                                else:
                                    w_tokens.append("x")
                    if w_tokens:
                        validation_lines.append("w:" + " ".join(w_tokens))
                    else:
                        # abc2midi warns about a music line with no lyric line
                        # once any w: appears; '_' is a harmless placeholder.
                        validation_lines.append("w:_")
        section_report.append({
            "id": sec["id"], "kind": sec["kind"], "meter": f"{sec_meter[0]}/{sec_meter[1]}",
            "bars": len(sec["bars"]), "start_bar": bar_cursor + 1,
        })
        bar_cursor += len(sec["bars"])

    abc_text = "\n".join(header + body_lines) + "\n"
    validation_text = "\n".join(header + validation_lines) + "\n"

    # Coverage and metrics.
    vocal_notes = [e for s in compiled_sections for b in s["bars"] for e in b["voc"] if e["type"] == "note"]
    ins_notes = [e for s in compiled_sections for b in s["bars"] for e in b["ins"] if e["type"] == "note"]
    syl_total = sum(len(b["syls"]) for s in compiled_sections for b in s["bars"] if b["syls"] is not None)
    used_total = sum(used_lines.values())
    missing_lines = []
    partial_lines = []
    if line_map:
        for lid, line in line_map.items():
            got = used_lines.get(lid, 0)
            if got == 0:
                missing_lines.append(lid)
            elif got < len(line["syllables"]):
                partial_lines.append({"id": lid, "used": got, "total": len(line["syllables"])})
    alignment_bars = sum(1 for s in compiled_sections for b in s["bars"] if b["syls"] is not None and b["groups"])
    total_vocal_bars = sum(1 for s in compiled_sections for b in s["bars"] if b["groups"])

    if missing_lines:
        warnings.append({
            "code": "lyrics_unused",
            "msg": f"{len(missing_lines)} intake lines are not referenced: {', '.join(missing_lines[:8])}",
        })
    if partial_lines:
        warnings.append({
            "code": "lyrics_partial",
            "msg": f"{len(partial_lines)} intake lines are only partly used",
        })

    # Per-line map: which bars carry each intake line, and how the line ends.
    # This changes no ABC; it gives the inspector the prosodic structure that
    # an external ABC cannot carry without w: lines.
    def leading_rest(events) -> float:
        total = 0.0
        for ev in events:
            if ev["type"] == "note":
                break
            total += float(ev["dur"])
        return total

    def trailing_rest(events) -> float:
        total = 0.0
        for ev in reversed(events):
            if ev["type"] == "note":
                break
            total += float(ev["dur"])
        return total

    line_report = []
    global_bar = 0
    for sec in compiled_sections:
        per_line: dict[str, list[tuple[int, dict]]] = {}
        for bi, bar in enumerate(sec["bars"]):
            for lid in bar.get("line_ids", []):
                per_line.setdefault(lid, []).append((bi, bar))
        for lid, hits in per_line.items():
            bars = [bar for _, bar in hits]
            notes = [ev for bar in bars for ev in bar["voc"] if ev["type"] == "note"]
            first = bars[0]["voc"]
            last = bars[-1]["voc"]
            rec = line_map.get(lid, {})
            cadence_pc = ((notes[-1]["midi"] - key_info["tonic_pc"]) % 12) if notes else None
            line_report.append({
                "line": lid,
                "section": sec["id"],
                "kind": sec["kind"],
                "role": rec.get("role"),
                "bayt": rec.get("bayt"),
                "start_bar": global_bar + hits[0][0] + 1,
                "end_bar": global_bar + hits[-1][0] + 1,
                "bars": len({bi for bi, _ in hits}),
                "lyric_count": len(rec.get("syllables") or []),
                "notes": len(notes),
                "melisma": round(len(notes) / len(rec["syllables"]), 2) if rec.get("syllables") else None,
                "median": round(sorted(ev["midi"] for ev in notes)[len(notes) // 2], 2) if notes else None,
                "cadence_pc": cadence_pc,
                "cadence_degree": DEGREE_BY_PC.get(cadence_pc),
                "lead_rest": round(leading_rest(first), 2),
                "end_rest": round(trailing_rest(last), 2),
                "end_pitch": notes[-1]["midi"] if notes else None,
            })
        global_bar += len(sec["bars"])
    line_report.sort(key=lambda r: r["start_bar"])

    report = {
        "ok": True,
        "meta": {
            "key": key_out, "maqam": meta.get("maqam"), "meter": f"{meter[0]}/{meter[1]}",
            "tempo": tempo, "grid": f"1/{l_den}", "targets": meta.get("targets", {}),
        },
        "bars": bar_cursor,
        "sections": section_report,
        "vocal_notes": len(vocal_notes),
        "ins_notes": len(ins_notes),
        "syllables": syl_total,
        "melisma_rate": (len(vocal_notes) / syl_total) if syl_total else None,
        "vocal_range": [
            min((e["midi"] for e in vocal_notes), default=None),
            max((e["midi"] for e in vocal_notes), default=None),
        ],
        "alignment": {
            "vocal_bars": total_vocal_bars,
            "bars_with_syl": alignment_bars,
            "lines_total": len(line_map),
            "syllables_used": used_total,
            "missing_lines": missing_lines,
            "partial_lines": partial_lines,
        },
        "line_map": line_report,
        "auto_breath": auto_breath,
        "errors": [],
        "warnings": warnings,
    }
    return {
        "ok": True,
        "abc": abc_text,
        "validation_abc": validation_text,
        "report": report,
        "sections": compiled_sections,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("blueprint", nargs="?", default=None)
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--report", default=None)
    ap.add_argument("--validation-out", default=None)
    ap.add_argument("--intake", default=None)
    ap.add_argument("--skeleton", default=None,
                    help="generated blueprint_skeleton.json")
    ap.add_argument("--fill", default=None,
                    help="fill.json with only voc/ins rows")
    ap.add_argument("--strict", action="store_true",
                    help="require syl on every vocal bar")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--pretty", action="store_true")
    ap.add_argument("--verbose", action="store_true",
                    help="also print the authoring-cost line (fill bytes vs ABC bytes)")
    args = ap.parse_args()

    try:
        if bool(args.skeleton) != bool(args.fill):
            raise CompileError("bad_fill", "pass --skeleton and --fill together")
        if args.blueprint and args.skeleton:
            raise CompileError("bad_fill", "pass either a full blueprint or --skeleton/--fill")
        if not args.blueprint and not args.skeleton:
            raise CompileError("bad_meta", "pass a blueprint or --skeleton/--fill")
        if args.skeleton:
            bp = merge_fill(load_json(args.skeleton), load_json(args.fill))
        else:
            bp = load_json(args.blueprint)
        intake = load_json(args.intake) if args.intake else None
        result = compile_blueprint(bp, intake=intake, strict=args.strict)
    except CompileError as exc:
        err = {"ok": False, "errors": [{"code": exc.code, "section": exc.section,
                                        "bar": exc.bar, "msg": exc.msg}]}
        print(dump_json(err, args.report, pretty=True))
        return 1
    except FileNotFoundError as exc:
        print(json.dumps({"ok": False, "errors": [{"code": "missing_file", "msg": str(exc)}]}))
        return 2
    except Exception as exc:
        print(json.dumps({"ok": False, "errors": [{"code": "internal", "msg": str(exc)}]}))
        return 2

    if not result["ok"]:
        rep = {"ok": False, "errors": result.get("errors", []),
               "warnings": result.get("warnings", [])}
        print(dump_json(rep, args.report, pretty=True))
        return 1

    with open(args.out, "w", encoding="utf-8") as f:
        f.write(result["abc"])
    if args.validation_out:
        with open(args.validation_out, "w", encoding="utf-8") as f:
            f.write(result["validation_abc"])
    report = result["report"]
    # Authoring-cost proxy: thinking text is not visible from outside, but the
    # bytes the author wrote (the fill, or the full Blueprint) against the ABC
    # it produced are.  Compact card output is unchanged; see --verbose.
    authored = args.fill or args.blueprint
    fill_bytes = os.path.getsize(authored)
    abc_bytes = len(result["abc"].encode("utf-8"))
    report["fill_bytes"] = fill_bytes
    report["abc_bytes"] = abc_bytes
    report["fill_to_abc_ratio"] = round(fill_bytes / abc_bytes, 3) if abc_bytes else None
    if args.report:
        dump_json(report, args.report, pretty=True)

    if args.json:
        print(dump_json(report, None, pretty=args.pretty))
    else:
        r = report
        print(f"OK  {args.out}  {r['bars']} bars  {r['meta']['key']} {r['meta']['meter']} "
              f"L:{r['meta']['grid']}  {r['meta']['tempo']} BPM")
        print(f"vocal {r['vocal_notes']} notes / {r['syllables']} syl"
              + (f" ({r['melisma_rate']:.2f})" if r['melisma_rate'] else "")
              + f"  range {r['vocal_range']}")
        print("sections: " + " | ".join(f"{s['kind']} {s['bars']}" for s in r["sections"]))
        if r["warnings"]:
            for w in r["warnings"][:8]:
                print(f"warn {w['code']}: {w['msg']}")
        if args.verbose:
            print(f"cost fill {r['fill_bytes']} B -> abc {r['abc_bytes']} B "
                  f"(ratio {r['fill_to_abc_ratio']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
