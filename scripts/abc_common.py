"""Shared, standard-library-only helpers for the ABC score writer.

The corpus is SheetSage2-style two-voice ABC.  This module parses that dialect
(notes, rests, Z multi-rests, chords, per-line meter changes, key signatures)
and spells scale degrees back into exact ABC pitches.  Nothing here composes;
the composer is the model, this is the measuring stick.
"""

from __future__ import annotations

import json
import math
import re
from fractions import Fraction
from statistics import median

# ---------------------------------------------------------------------------
# Pitch and key helpers
# ---------------------------------------------------------------------------

LETTERS = "CDEFGAB"
BASE = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
SHARP_ORDER = "FCGDAEB"
FLAT_ORDER = "BEADGCF"

MAJOR_SHARPS = {"C": 0, "G": 1, "D": 2, "A": 3, "E": 4, "B": 5, "F#": 6, "C#": 7}
MAJOR_FLATS = {"F": 1, "Bb": 2, "Eb": 3, "Ab": 4, "Db": 5, "Gb": 6, "Cb": 7}

# Minor tonic -> relative major.  Spelling is explicit so Ebm gets Gb, not F#.
MINOR_TO_MAJOR = {
    "Am": "C", "Em": "G", "Bm": "D", "F#m": "A", "C#m": "E", "G#m": "B",
    "D#m": "F#", "A#m": "C#",
    "Dm": "F", "Gm": "Bb", "Cm": "Eb", "Fm": "Ab", "Bbm": "Db", "Ebm": "Gb",
    "Abm": "Cb",
}

# Pitch class -> a readable name, used only in human reports.
PC_NAMES_SHARP = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
PC_NAMES_FLAT = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]


def pc_to_name(pc: int, prefer_flats: bool = True) -> str:
    return (PC_NAMES_FLAT if prefer_flats else PC_NAMES_SHARP)[pc % 12]


def midi_to_name(midi: int, prefer_flats: bool = True) -> str:
    """Return scientific pitch name, e.g. 62 -> 'D4', 63 -> 'Eb4'."""
    name = pc_to_name(int(round(midi)) % 12, prefer_flats)
    octave = int(math.floor(midi / 12.0)) - 1
    return f"{name}{octave}"


def parse_key(key: str) -> dict:
    """Parse an ABC key such as Dm, Bbm, F#, C.

    Modal suffixes (Dphr, Ddor, ...) are accepted as a convenience but are
    reduced to the nearest major/minor signature.  The compiler only emits
    plain major/minor keys, matching the corpus.
    """
    raw = (key or "").strip()
    m = re.match(r"^([A-G])([#b]?)(.*)$", raw)
    if not m:
        raise ValueError(f"bad key: {key!r}")
    letter, acc, rest = m.group(1), m.group(2), m.group(3).strip().lower()
    minor = rest.startswith("m") or rest in {"min", "minor"}
    # Modal names: treat Dorian/Phrygian/Aeolian as minor, Lydian/Ionian as major.
    if rest.startswith(("dor", "phr", "aeo", "mix")):
        minor = True
    if rest.startswith(("ion", "lyd")):
        minor = False
    tonic_pc = (BASE[letter] + (1 if acc == "#" else -1 if acc == "b" else 0)) % 12
    tonic_name = f"{letter}{acc}"

    if minor:
        rel = MINOR_TO_MAJOR.get(f"{tonic_name}m")
        if rel is None:
            # Choose the spelling that keeps the signature simple.
            rel_pc = (tonic_pc + 3) % 12
            rel = pc_to_name(rel_pc, prefer_flats=(acc == "b"))
    else:
        rel = tonic_name

    n_sharps = MAJOR_SHARPS.get(rel, 0)
    n_flats = MAJOR_FLATS.get(rel, 0)
    sig: dict[str, int] = {}
    if n_sharps:
        for ch in SHARP_ORDER[:n_sharps]:
            sig[ch] = 1
    elif n_flats:
        for ch in FLAT_ORDER[:n_flats]:
            sig[ch] = -1

    # The tonic's default MIDI is tonic in octave 4.
    tonic_midi = 12 * (4 + 1) + tonic_pc
    return {
        "raw": raw,
        "tonic_letter": letter,
        "tonic_acc": acc,
        "tonic_pc": tonic_pc,
        "tonic_midi": tonic_midi,
        "minor": minor,
        "relative_major": rel,
        "signature": sig,
        "prefer_flats": bool(n_flats) or acc == "b",
    }


def _natural_pitch(letter: str, octave: int) -> int:
    return 12 * (octave + 1) + BASE[letter]


def _abc_octave(letter: str, octave: int) -> str:
    """ABC note letter with the right case and octave marks."""
    if octave >= 5:
        return letter.lower() + "'" * (octave - 5)
    return letter.upper() + "," * (4 - octave)


def _best_octave(midi: int, letter: str) -> int:
    best = 4
    best_delta = 999
    for octave in range(1, 8):
        delta = abs(_natural_pitch(letter, octave) - midi)
        if delta < best_delta:
            best_delta = delta
            best = octave
    return best


def spell_midi(midi: int, letter: str, key_info: dict, allow_respell: bool = True) -> str:
    """Spell a MIDI pitch using a preferred letter and the key signature.

    For a scale degree the preferred letter is fixed by the degree number, so
    Kurd's flat second on D becomes _E, not ^D.  For transposed notes a fixed
    letter can need three accidentals; in that case we respell enharmonically.
    """
    midi = int(round(midi))
    octave = _best_octave(midi, letter)
    natural = _natural_pitch(letter, octave)
    key_acc = key_info["signature"].get(letter, 0)
    default = natural + key_acc

    if midi == natural:
        acc = "=" if key_acc else ""
    else:
        diff = midi - default
        if diff > 0:
            acc = "^" * diff
        elif diff < 0:
            acc = "_" * (-diff)
        else:
            acc = ""
    if abs(midi - default) <= 2 or midi == natural:
        return acc + _abc_octave(letter, octave)

    if not allow_respell:
        raise ValueError(f"cannot spell MIDI {midi} as {letter} cleanly")

    # Enharmonic fallback: try every letter and keep the cleanest spelling.
    candidates = []
    for cand in LETTERS:
        octv = _best_octave(midi, cand)
        nat = _natural_pitch(cand, octv)
        kacc = key_info["signature"].get(cand, 0)
        d = midi - (nat + kacc)
        if abs(d) <= 2:
            candidates.append((abs(d), abs(midi - nat), cand, octv))
    if not candidates:
        raise ValueError(f"cannot spell MIDI {midi}")
    candidates.sort()
    _, _, cand, octv = candidates[0]
    nat = _natural_pitch(cand, octv)
    kacc = key_info["signature"].get(cand, 0)
    if midi == nat:
        acc = "=" if kacc else ""
    else:
        d = midi - (nat + kacc)
        acc = "^" * d if d > 0 else "_" * (-d)
    return acc + _abc_octave(cand, octv)


def degree_to_midi(degree: str, key_info: dict, octave_offset: int = 0) -> tuple[int, str, str]:
    """Convert a Blueprint degree (e.g. b2, #4, 5-) to MIDI, letter, degree.

    Returns (midi, letter, normalized_degree).
    """
    m = re.match(r"^([#b]*)([1-7])([+\-]*)$", degree.strip())
    if not m:
        raise ValueError(f"bad degree: {degree!r}")
    acc_str, num_s, oct_s = m.group(1), m.group(2), m.group(3)
    num = int(num_s)
    acc = acc_str.count("#") - acc_str.count("b")
    natural_offset = [0, 2, 4, 5, 7, 9, 11][num - 1]
    tonic_i = LETTERS.index(key_info["tonic_letter"])
    letter = LETTERS[(tonic_i + num - 1) % 7]
    octave_shift = oct_s.count("+") - oct_s.count("-")
    midi = key_info["tonic_midi"] + natural_offset + acc + 12 * (octave_shift + octave_offset)
    return midi, letter, f"{acc_str}{num}{oct_s}"


def transpose_note(midi: int, letter: str, semitones: int, key_info: dict) -> str:
    """Transpose a note and return ABC text.  Keeps the diatonic letter near."""
    if semitones == 0:
        return spell_midi(midi, letter, key_info)
    steps = int(round(semitones * 7 / 12.0))
    new_letter = LETTERS[(LETTERS.index(letter) + steps) % 7]
    return spell_midi(midi + semitones, new_letter, key_info)


# ---------------------------------------------------------------------------
# Percentiles
# ---------------------------------------------------------------------------

def percentile(values, p: float):
    """Linear-interpolation percentile; returns None for an empty list."""
    vals = sorted(float(v) for v in values if v is not None)
    if not vals:
        return None
    if len(vals) == 1:
        return vals[0]
    k = (len(vals) - 1) * (p / 100.0)
    lo = int(math.floor(k))
    hi = int(math.ceil(k))
    if lo == hi:
        return vals[lo]
    return vals[lo] * (hi - k) + vals[hi] * (k - lo)


def pct_block(values) -> dict:
    return {
        "p10": round(percentile(values, 10), 4) if values else None,
        "p25": round(percentile(values, 25), 4) if values else None,
        "p50": round(percentile(values, 50), 4) if values else None,
        "p75": round(percentile(values, 75), 4) if values else None,
        "p90": round(percentile(values, 90), 4) if values else None,
    }


# ---------------------------------------------------------------------------
# ABC parser
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(
    r"""
      (?P<chord>"[^"]*")
    | (?P<zmulti>Z)(?P<znum>\d*)
    | (?P<rest>z)(?P<rnum>\d*)(?:/(?P<rden>\d+))?
    | (?P<grace>\{[^}]*\})
    | (?P<deco>![^!]*!)
    | (?P<acc>\^\^|\^|__|_|=)?(?P<note>[A-Ga-g])(?P<oct>[,\']*)(?P<num>\d*)(?:/(?P<den>\d+))?(?P<tie>-)?
    | (?P<other>.)
    """,
    re.X,
)


def _parse_duration(num: str | None, den: str | None, unit_beats: Fraction) -> Fraction:
    n = int(num) if num else 1
    d = int(den) if den else 1
    return unit_beats * Fraction(n, d)


def _parse_bar(bar: str, key_info: dict, meter: tuple[int, int], unit_beats: Fraction,
               section: str | None) -> dict | None:
    bar = bar.strip()
    if not bar:
        return None
    # A standalone meter field inside a bar is a meter change, not music.
    if re.match(r"^\[?M:\d+/\d+\]?$", bar):
        return None

    # Strip inline fields like [M:2/4] and [K:Dm] but keep the music after them.
    inline = {}
    for fm in re.finditer(r"\[([MK]):([^\]]+)\]", bar):
        inline[fm.group(1)] = fm.group(2).strip()
    bar_music = re.sub(r"\[[MK]:[^\]]+\]", "", bar)

    events = []
    chords = []
    unknown = []
    total = Fraction(0)
    bar_acc: dict[tuple[str, int], int] = {}

    for m in _TOKEN_RE.finditer(bar_music):
        if m.group("chord"):
            chords.append(m.group("chord")[1:-1])
            continue
        if m.group("zmulti"):
            n = int(m.group("znum") or 1)
            beats = Fraction(meter[0] * 4, meter[1])
            return {
                "section": section,
                "meter": meter,
                "beats": beats,
                "events": [{"type": "rest", "dur": beats}],
                "chords": chords,
                "multi": n,
                "sum_ok": True,
            }
        if m.group("rest"):
            dur = _parse_duration(m.group("rnum"), m.group("rden"), unit_beats)
            events.append({"type": "rest", "dur": dur})
            total += dur
            continue
        if m.group("grace") or m.group("deco"):
            continue
        if m.group("note"):
            letter = m.group("note").upper()
            oct_marks = m.group("oct") or ""
            if m.group("note").islower():
                octave = 5 + oct_marks.count("'") - oct_marks.count(",")
            else:
                octave = 4 + oct_marks.count("'") - oct_marks.count(",")
            midi = 12 * (octave + 1) + BASE[letter]
            acc_s = m.group("acc")
            if acc_s is None:
                acc_s = bar_acc.get((letter, octave))
                if acc_s is None:
                    acc_s = key_info["signature"].get(letter, 0)
                midi += acc_s
            else:
                if acc_s == "=":
                    acc_val = 0
                elif acc_s == "^":
                    acc_val = 1
                elif acc_s == "^^":
                    acc_val = 2
                elif acc_s == "_":
                    acc_val = -1
                elif acc_s == "__":
                    acc_val = -2
                else:
                    acc_val = 0
                midi += acc_val
                bar_acc[(letter, octave)] = acc_val
            dur = _parse_duration(m.group("num"), m.group("den"), unit_beats)
            events.append({
                "type": "note",
                "midi": midi,
                "letter": letter,
                "octave": octave,
                "dur": dur,
                "tie": bool(m.group("tie")),
            })
            total += dur
            continue
        if m.group("other"):
            ch = m.group("other")
            if ch in " \t\r\n|":
                continue
            unknown.append(ch)

    if total == 0 and not events:
        return None
    bar_beats = Fraction(meter[0] * 4, meter[1])
    return {
        "section": section,
        "meter": meter,
        "beats": bar_beats,
        "events": events,
        "chords": chords,
        "multi": 1,
        "sum_ok": total == bar_beats,
        "sum": total,
        "unknown": unknown,
    }


def parse_abc(path_or_text: str, is_text: bool = False) -> dict:
    """Parse an ABC file or string into header + per-voice bars.

    Returns:
        {
          "header": {...},
          "voices": {"Vocal": [bar...], "Ins": [bar...]},
          "order": ["Vocal", "Ins"],
          "warnings": [...]
        }
    """
    text = path_or_text if is_text else open(path_or_text, encoding="utf-8", errors="replace").read()
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    km = re.search(r"^K:(.+)$", text, re.M)
    if not km:
        raise ValueError("ABC has no K: line")
    key_raw = km.group(1).strip()
    key_info = parse_key(key_raw.split()[0])

    header_text = text[: km.start()]
    body = text[km.end():]

    def header_field(name: str) -> str | None:
        m = re.search(rf"^{name}:(.*)$", header_text, re.M)
        return m.group(1).strip() if m else None

    m_field = header_field("M") or "4/4"
    mm = re.match(r"(\d+)/(\d+)", m_field)
    if not mm:
        raise ValueError(f"bad header meter: {m_field!r}")
    initial_meter = (int(mm.group(1)), int(mm.group(2)))

    l_field = header_field("L") or "1/16"
    lm = re.match(r"1/(\d+)", l_field)
    if not lm:
        raise ValueError(f"bad header length: {l_field!r}")
    unit_beats = Fraction(4, int(lm.group(1)))

    q_field = header_field("Q") or "1/4=90"
    qm = re.search(r"1/4=(\d+)", q_field)
    tempo = int(qm.group(1)) if qm else 90

    header = {
        "X": header_field("X"),
        "T": header_field("T"),
        "M": initial_meter,
        "L": int(lm.group(1)),
        "Q": tempo,
        "K": key_raw,
        "key": key_info,
        "unit_beats": unit_beats,
    }

    voices: dict[str, list] = {}
    order: list[str] = []
    warnings: list[str] = []
    current_voice = None
    current_section = None
    meter = initial_meter

    for lineno, raw_line in enumerate(body.split("\n"), 1):
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("%"):
            label = line[1:].strip()
            if label:
                current_section = label
            continue
        if line.startswith("w:") or line.startswith("W:"):
            continue
        if line.startswith("V:"):
            name = line[2:].split()[0] if line[2:].split() else "1"
            current_voice = name
            if name not in voices:
                voices[name] = []
                order.append(name)
            continue
        if re.match(r"^M:\d+/\d+$", line):
            mm2 = re.match(r"^M:(\d+)/(\d+)$", line)
            meter = (int(mm2.group(1)), int(mm2.group(2)))
            continue
        if line.startswith("K:"):
            continue
        if current_voice is None:
            continue

        # Inline meter at the start of a music line.
        im = re.match(r"^\[?M:(\d+)/(\d+)\]?", line)
        if im and not re.search(r"[A-Ga-gzZ\"]", line[im.end():]):
            meter = (int(im.group(1)), int(im.group(2)))
            continue

        # Drop trailing comments.
        music = line.split("%", 1)[0].strip()
        if not music:
            continue
        # A line may begin with an inline meter field followed by music.
        im = re.match(r"^\[?M:(\d+)/(\d+)\]?\s*(.*)$", music)
        if im:
            meter = (int(im.group(1)), int(im.group(2)))
            music = im.group(3).strip()

        for bar_text in music.split("|"):
            bar_text = bar_text.strip()
            if not bar_text:
                continue
            parsed = _parse_bar(bar_text, key_info, meter, unit_beats, current_section)
            if parsed is None:
                # A standalone meter change inside the bar stream.
                mm3 = re.match(r"^\[?M:(\d+)/(\d+)\]?$", bar_text)
                if mm3:
                    meter = (int(mm3.group(1)), int(mm3.group(2)))
                continue
            if not parsed.get("sum_ok", True):
                warnings.append(
                    f"line {lineno}: {current_voice} bar under {meter[0]}/{meter[1]} "
                    f"sums to {parsed.get('sum', 0)} (expected {parsed['beats']})"
                )
            n = parsed.pop("multi", 1)
            for _ in range(n):
                copy_bar = dict(parsed)
                # Keep the source music line so the craft checks can recover the
                # transcriber's own phrase breaks in files with no Blueprint.
                copy_bar["line"] = lineno
                voices[current_voice].append(copy_bar)

    return {
        "header": header,
        "voices": voices,
        "order": order,
        "warnings": warnings,
    }


def bars_equal(parsed: dict) -> tuple[bool, dict]:
    counts = {v: len(b) for v, b in parsed["voices"].items()}
    if len(set(counts.values())) <= 1:
        return True, counts
    return False, counts


def voice_notes(bars: list[dict]) -> list[dict]:
    out = []
    for bar in bars:
        for ev in bar["events"]:
            if ev["type"] == "note":
                out.append(ev)
    return out


def bar_has_notes(bar: dict) -> bool:
    return any(ev["type"] == "note" for ev in bar["events"])


def bar_rest_beats(bar: dict) -> Fraction:
    return sum((ev["dur"] for ev in bar["events"] if ev["type"] == "rest"), Fraction(0))


def bar_total_beats(bar: dict) -> Fraction:
    return sum((ev["dur"] for ev in bar["events"]), Fraction(0))


def load_json(path: str):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def dump_json(obj, path: str | None = None, pretty: bool = False):
    text = json.dumps(obj, ensure_ascii=False, indent=2 if pretty else None,
                      sort_keys=pretty)
    if path:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text + ("\n" if pretty else ""))
    return text


def median_or_none(vals):
    return median(vals) if vals else None
