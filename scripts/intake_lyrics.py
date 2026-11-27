#!/usr/bin/env python3
"""Read a style + sectioned-lyrics prompt and return a compact structural brief.

It does not compose.  It gives the model:
  * the style tags and maqam hint,
  * one stable id per lyric line (for @id references in the Blueprint),
  * a syllable count and syllable tokens per line,
  * an estimated bar budget per line/section,
  * the relevant corpus defaults.

Arabic syllabification uses the short-vowel marks when the text has tashkeel.
Unvocalized text falls back to a consonant/vowel-density estimate and is marked
``estimated: true``.

Usage:
    python3 scripts/intake_lyrics.py --in prompt.txt -o intake.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from abc_common import (  # noqa: E402
    degree_to_midi, load_json, midi_to_name, parse_key,
)

# Arabic short vowels and related marks.
FATHA = "\u064E"
DAMMA = "\u064F"
KASRA = "\u0650"
TANWIN = "\u064B\u064C\u064D"
SHADDA = "\u0651"
SUKUN = "\u0652"
VOWEL_MARKS = set(FATHA + DAMMA + KASRA + TANWIN)
ALL_MARKS = set(VOWEL_MARKS | {SHADDA, SUKUN, "\u0670", "\u0653", "\u0654", "\u0655"})
DIACRITIC_RANGE = "\u064B-\u065F\u0670"
ARABIC_LETTER_RE = re.compile(r"[\u0621-\u064A\u066E-\u06D3\u06FA-\u06FF]")
WORD_RE = re.compile(r"[\u0621-\u064A\u066E-\u06D3\u06FA-\u06FF" + DIACRITIC_RANGE + r"\u0640]+")

HEADER_RE = re.compile(r"^\s*\[([^\]|]+?)(?:\s*\|\s*([^\]]*))?\]\s*$")
MAQAM_TONIC = {
    "kurd": ("D", "m"), "hijaz": ("D", "m"), "nahawand": ("D", "m"),
    "bayati": ("D", "m"), "saba": ("D", "m"), "huzam": ("E", "m"),
    "rast": ("C", ""), "ajam": ("Bb", ""), "jiharkah": ("F", ""),
}

# Optional phrase seeds.  The bank is read by this script, never pasted into
# the agent's context.  Seeds only add stdout lines; they never touch the
# intake JSON or the skeleton.
MAQAM_MODE_HINT = {
    "kurd": "kurd-like",
    "hijaz": "hijaz-like",
    "rast": "rast-like",
    "nahawand": "nahawand-like",
    "bayati": "bayati-like",
}
SEED_MAX_BYTES = 400
SEED_MAX_PHRASES = 3
SEED_MAX_PHRASE_BYTES = 130

KIND_MAP = {
    "intro": "intro", "opening": "intro",
    "verse": "verse", "v": "verse",
    "chorus": "chorus", "refrain": "chorus",
    "interlude": "interlude", "break": "interlude", "instrumental": "interlude",
    "bridge": "bridge",
    "pre-chorus": "pre-chorus", "prechorus": "pre-chorus", "pre chorus": "pre-chorus",
    "outro": "outro", "ending": "outro", "coda": "outro",
    "end": "outro", "the end": "outro", "finale": "outro",
    "silence": "silence",
}


def strip_marks_for_count(text: str) -> str:
    return "".join(ch for ch in text if ch not in ALL_MARKS)


def _has_vowel(chunk: str) -> bool:
    return any(ch in VOWEL_MARKS for ch in chunk)


def _clean_chunk(chunk: str) -> str:
    # Keep letters and marks, drop punctuation and Latin characters.
    return "".join(ch for ch in chunk if ARABIC_LETTER_RE.match(ch) or ch in ALL_MARKS)


def syllabify_word(word: str) -> tuple[list[str], bool]:
    """Split one Arabic word into syllable-like chunks.

    Returns (chunks, estimated).  With tashkeel the chunks are faithful enough
    for alignment counting.  Without tashkeel the result is an estimate.
    """
    word = unicodedata.normalize("NFC", word)
    word = word.replace("\u0640", "")  # tatweel
    word = "".join(ch for ch in word if ch not in "\u06D6\u06D7\u06D8\u06D9\u06DA\u06DB\u06DC\u06DD\u06DE\u06DF\u06E0\u06E1\u06E2\u06E3\u06E4\u06E5\u06E6\u06E7\u06E8\u06E9\u06EA\u06EB\u06EC\u06ED")
    if not word:
        return [], False

    has_tashkeel = any(ch in VOWEL_MARKS for ch in word) or SUKUN in word or SHADDA in word
    if not has_tashkeel:
        # Unvocalized fallback: long vowels and consonant clusters.
        letters = [ch for ch in word if ARABIC_LETTER_RE.match(ch)]
        if not letters:
            return [], False
        long_vowels = sum(1 for ch in letters if ch in "اوىي")
        clusters = 0
        for a, b in zip(letters, letters[1:]):
            if a not in "اوىي" and b not in "اوىي":
                clusters += 1
        estimate = max(1, 1 + long_vowels + clusters // 2)
        estimate = min(estimate, max(1, len(letters) // 2 + 1))
        return [strip_marks_for_count(word)] * estimate, True

    # Each regex match ends at one diacritic.  A chunk may begin with a
    # diacritic when a shadda and its vowel were separated; merge those.
    pattern = re.compile(rf"[^{DIACRITIC_RANGE}]*[{DIACRITIC_RANGE}]")
    raw = []
    pos = 0
    for m in pattern.finditer(word):
        raw.append(m.group())
        pos = m.end()
    if pos < len(word):
        raw.append(word[pos:])

    chunks: list[str] = []
    for chunk in raw:
        chunk = _clean_chunk(chunk)
        if not chunk:
            continue
        if chunk[0] in ALL_MARKS and chunks:
            chunks[-1] += chunk
            continue
        if chunks and not _has_vowel(chunk):
            # A coda (sukun) belongs to the previous syllable.  An initial
            # alef/wasla chunk is kept because it is the first nucleus.
            chunks[-1] += chunk
        else:
            chunks.append(chunk)

    # A chunk that is only an initial alef/wasla is a syllable; a chunk that
    # is only a consonant with sukun at word start is not useful on its own.
    fixed = []
    for i, ch in enumerate(chunks):
        letters = [c for c in ch if ARABIC_LETTER_RE.match(c)]
        if not letters:
            continue
        if i == 0 and not _has_vowel(ch) and letters[0] not in "اأإآٱ":
            # Rare: word starts with a closed consonant cluster.  Attach it to
            # the next chunk if one exists.
            if len(chunks) > 1:
                chunks[1] = ch + chunks[1]
                continue
        fixed.append(ch)
    return fixed or [strip_marks_for_count(word)], False


def syllabify_line(text: str) -> tuple[list[str], int, bool]:
    """Return (syllable tokens, count, estimated) for a lyric line."""
    words = WORD_RE.findall(text)
    tokens = []
    estimated = False
    for word in words:
        chunks, est = syllabify_word(word)
        tokens.extend(chunks)
        estimated = estimated or est
    if not tokens:
        # Latin or mixed text: fall back to word count, marked estimated.
        latin = re.findall(r"[A-Za-z]+", text)
        tokens = latin
        estimated = True
    return tokens, len(tokens), estimated


def parse_style(block: str, profile: dict | None) -> dict:
    raw = " ".join(line.strip() for line in block.splitlines() if line.strip())
    tags = [t.strip(" .") for t in re.split(r",|\n", raw) if t.strip(" .")]
    maqam = None
    mood = None
    tempo_hint = None
    mm = re.search(r"maqam\s+([A-Za-z\u0600-\u06FF-]+)", raw, re.I)
    if mm:
        maqam = mm.group(1).strip()
    mm = re.search(r"mood\s*[:=]\s*[\"“]([^\"”]+)[\"”]", raw, re.I)
    if mm:
        mood = mm.group(1).strip()
    mm = re.search(r"\b(\d{2,3})\s*(?:bpm|beats per minute)\b", raw, re.I)
    if mm:
        tempo_hint = int(mm.group(1))
    style = {
        "raw": raw,
        "tags": tags,
        "maqam": maqam,
        "mood": mood,
        "tempo_hint": tempo_hint,
        "vocal_tags": [],
        "instrument_tags": [],
        "mood_tags": [],
    }
    if maqam:
        low = maqam.lower().replace(" ", "")
        for name, (tonic, mode) in MAQAM_TONIC.items():
            if low.startswith(name):
                style["suggested_key"] = tonic + mode
                break
    vocal_words = ("vocal", "belting", "operatic", "melisma", "tarab", "enunciation",
                   "delivery", "backing", "singer", "chant", "male", "female")
    inst_words = ("guitar", "bass", "drum", "orchestr", "symphonic", "metal", "piano",
                  "strings", "oud", "qanun", "ney", "percussion", "synth")
    for tag in tags:
        low = tag.lower()
        if any(w in low for w in vocal_words):
            style["vocal_tags"].append(tag)
        if any(w in low for w in inst_words):
            style["instrument_tags"].append(tag)
    if mood:
        style["mood_tags"] = [m.strip() for m in re.split(r"[,/]", mood) if m.strip()]
    if profile:
        tempo = style["tempo_hint"] or int(profile["tempos"]["percentiles"]["p50"] or 90)
        style["tempo_default"] = tempo
    return style


def slugify(name: str) -> str:
    s = unicodedata.normalize("NFKD", name)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s or "section"


def known_kind(name: str) -> str | None:
    """Section kind for a recognised header name, or None if unknown."""
    low = name.lower().strip()
    for key, kind in KIND_MAP.items():
        if low == key or low.startswith(key + " ") or low.startswith(key + "-"):
            return kind
    if low.startswith("verse"):
        return "verse"
    if low.startswith("chorus"):
        return "chorus"
    return None


def normalize_kind(name: str) -> str:
    return known_kind(name) or "verse"


def est_bars_for(syllables: int, tempo: int | None = None, role: str | None = None) -> int:
    """Structural budget: one hemistich is four bars, one bayt is eight.

    A very short line (eight syllables or fewer) gets two bars, the other
    convention the corpus uses.  Tempo is kept in the signature for callers
    that already pass it, but it no longer changes the budget: the defect this
    guards against was fitting a whole bayt into the space of one shatr.
    """
    return 2 if syllables <= 8 else 4


def load_phrase_bank(path: str) -> dict | None:
    """Load a phrase_bank/2 file, or None on any failure (skip silently)."""
    try:
        bank = load_json(path)
    except Exception:
        return None
    if not isinstance(bank, dict) or bank.get("schema") != "phrase_bank/2":
        return None
    if not isinstance(bank.get("phrases"), list):
        return None
    return bank


def _stable_choice(candidates: list[dict], line_id: str) -> dict | None:
    """Deterministic pick: sort by id, then a stable hash of the line id."""
    candidates = sorted(candidates, key=lambda p: str(p.get("id")))
    if not candidates:
        return None
    digest = hashlib.sha256(line_id.encode("utf-8")).digest()
    return candidates[int.from_bytes(digest[:8], "big") % len(candidates)]


def seed_for_line(rec: dict, phrases: list[dict],
                  maqam: str | None) -> tuple[dict, bool] | None:
    """Pick one optional seed for a lyric line, or None.

    Returns (phrase, mode_any).  Only 8-beat lines are seeded: the bank has 45
    eight-beat phrases and 3 sixteen-beat ones, and a 16-beat shatr must not be
    offered a mismatched 8-beat phrase.  The budget is bars x 4 because the
    skeleton is 4/4.
    """
    role = rec.get("role")
    budget = int(rec.get("est_bars") or 0) * 4
    if budget != 8:
        return None
    candidates = [
        p for p in phrases
        if p.get("cadence_class") == role
        and int(p.get("beats") or 0) == budget
        and p.get("fits_seed_budget", True)
        and int(p.get("phrase_bytes") or 0) <= SEED_MAX_PHRASE_BYTES
    ]
    if not candidates:
        return None
    mode_hint = MAQAM_MODE_HINT.get((maqam or "").lower())
    mode_any = False
    if mode_hint:
        matched = [p for p in candidates if p.get("mode_hint") == mode_hint]
        if matched:
            candidates = matched
        else:
            mode_any = True
    else:
        mode_any = True
    preferred = [p for p in candidates if p.get("register") in ("mid", "high")]
    if preferred:
        candidates = preferred
    phrase = _stable_choice(candidates, str(rec.get("id")))
    if phrase is None:
        return None
    return phrase, mode_any


def build_seed_block(out: dict, phrases: list[dict], limit: int) -> list[str]:
    """At most `limit` (cap 3) SEED lines, whole block <= 400 UTF-8 bytes."""
    limit = max(0, min(int(limit), SEED_MAX_PHRASES))
    if not limit or not phrases:
        return []
    maqam = ((out.get("style") or {}).get("maqam") or "").lower()
    lines: list[str] = []
    total = 0
    for rec in out.get("lines") or []:
        if len(lines) >= limit:
            break
        got = seed_for_line(rec, phrases, maqam)
        if not got:
            continue
        phrase, mode_any = got
        tag = " mode=any" if mode_any else ""
        line = (f"SEED {phrase['id']} {rec['role']} {int(phrase['beats'])}b"
                f"{tag} {phrase['phrase']}")
        size = len(line.encode("utf-8")) + 1
        if total + size > SEED_MAX_BYTES:
            break
        lines.append(line)
        total += size
    return lines


def _chord_root(degree: str, key_info: dict) -> str:
    midi, _letter, _norm = degree_to_midi(degree, key_info)
    name = midi_to_name(midi, prefer_flats=key_info["prefer_flats"])
    return re.sub(r"-?\d+$", "", name)


def chord_loop(key: str) -> list[str]:
    """A corpus-common one-chord-per-bar loop: i-iv-VI-V or I-vi-IV-V."""
    info = parse_key(key)
    if info["minor"]:
        specs = [("1", "m"), ("4", "m"), ("b6", ""), ("5", "")]
    else:
        specs = [("1", ""), ("6", "m"), ("4", ""), ("5", "")]
    return [_chord_root(deg, info) + quality for deg, quality in specs]


def bar_syllable_ranges(line_id: str, count: int, bars: int) -> list[str]:
    """Split a line's syllables over its bars, balancing the remainder."""
    bars = max(1, min(bars, count))
    base, rem = divmod(count, bars)
    left, right = (rem + 1) // 2, rem // 2
    sizes = [base] * bars
    for i in range(left):
        sizes[i] += 1
    for i in range(right):
        sizes[bars - 1 - i] += 1
    out, start = [], 1
    for n in sizes:
        if n:
            out.append(f"@{line_id}:{start}-{start + n - 1}")
            start += n
    return out


def build_skeleton(out: dict) -> dict:
    """Fill the mechanical parts: sections, bars, ch, and syl ranges."""
    style = out.get("style") or {}
    key = style.get("suggested_key") or "Dm"
    loop = chord_loop(key)
    meta = {
        "key": key,
        "maqam": (style.get("maqam") or "").lower() or None,
        "meter": "4/4",
        "tempo": style.get("tempo_default") or style.get("tempo_hint") or 90,
        "vocal_octave": 0,
        "targets": {
            "melisma": 1.2,
            "chorus_lift": 3,
            "call_response": 0.6,
            "vocal_span": 20,
            "max_phrase_seconds": 12,
            "maqam_fit": 0.8,
        },
    }
    if meta["maqam"] is None:
        meta.pop("maqam")

    line_by_id = {r["id"]: r for r in out.get("lines") or []}
    sections = []
    used_sources = {}
    for sec in out.get("sections") or []:
        # Only exact repeated names (Chorus, Chorus) share music.  Verse 1 and
        # Verse 2 are different verses even though both are "verse" sections.
        base = sec["name"].strip().lower()
        sec_lines = [line_by_id[x] for x in sec["lines"] if x in line_by_id]
        source = used_sources.get(base)
        if (source and source["kind"] == sec["kind"]
                and source["line_count"] == len(sec_lines)):
            entry = {
                "id": sec["key"],
                "kind": sec["kind"],
                "same_as": source["id"],
            }
            if sec_lines:
                entry["syl"] = [
                    rng
                    for rec in sec_lines
                    for rng in bar_syllable_ranges(rec["id"], rec["count"], rec["est_bars"])
                ]
            sections.append(entry)
            continue

        bars = []
        if sec_lines:
            for rec in sec_lines:
                ranges = bar_syllable_ranges(rec["id"], rec["count"], rec["est_bars"])
                for rng in ranges:
                    bars.append({"ch": loop[len(bars) % len(loop)], "syl": rng})
        else:
            for i in range(max(1, int(sec.get("est_bars") or 4))):
                bars.append({"ch": loop[i % len(loop)]})
        if bars and sec["kind"] == "outro":
            tonic = re.sub(r"-?\d+$", "",
                           midi_to_name(parse_key(key)["tonic_midi"],
                                        prefer_flats=parse_key(key)["prefer_flats"]))
            bars[-1]["ch"] = tonic + ("m" if parse_key(key)["minor"] else "")
        sections.append({
            "id": sec["key"],
            "kind": sec["kind"],
            "bars": bars,
        })
        used_sources[base] = {"id": sec["key"], "kind": sec["kind"],
                              "line_count": len(sec_lines)}

    return {"meta": meta, "motifs": {}, "sections": sections}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--in", dest="inp", required=True, help="prompt file, or - for stdin")
    ap.add_argument("-o", "--out", default="intake.json")
    ap.add_argument("--profile", default=None,
                    help="corpus_profile.json (default: ../assets/corpus_profile.json)")
    ap.add_argument("--skeleton", default=None,
                    help="write the mechanical Blueprint skeleton here "
                         "(default: blueprint_skeleton.json beside -o)")
    ap.add_argument("--seeds", type=int, default=0,
                    help="print at most N optional phrase seeds (0=off, cap 3)")
    ap.add_argument("--phrase-bank", default=None,
                    help="phrase_bank.json (default: ../assets/phrase_bank.json)")
    ap.add_argument("--json", action="store_true", help="print full JSON to stdout")
    ap.add_argument("--pretty", action="store_true")
    args = ap.parse_args()

    if args.inp == "-":
        text = sys.stdin.read()
    else:
        with open(args.inp, encoding="utf-8") as f:
            text = f.read()
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    profile_path = args.profile or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "assets", "corpus_profile.json")
    profile = None
    if os.path.exists(profile_path):
        try:
            profile = load_json(profile_path)
        except Exception:
            profile = None

    lines = text.split("\n")
    first_header = None
    for i, line in enumerate(lines):
        if HEADER_RE.match(line):
            first_header = i
            break
    style_block = "\n".join(lines[:first_header] if first_header is not None else [])
    style = parse_style(style_block, profile)
    tempo = style.get("tempo_hint") or (int(profile["tempos"]["percentiles"]["p50"]) if profile and profile["tempos"]["percentiles"]["p50"] else 90)

    sections = []
    line_records = []
    current = None
    seen_slugs: dict[str, int] = {}

    def start_section(name: str, cues: str):
        nonlocal current
        base = slugify(name)
        seen_slugs[base] = seen_slugs.get(base, 0) + 1
        key = base if seen_slugs[base] == 1 else f"{base}_{seen_slugs[base]}"
        current = {
            "index": len(sections),
            "name": name.strip(),
            "key": key,
            "kind": normalize_kind(name),
            "_unknown_kind": known_kind(name) is None,
            "cues": (cues or "").strip(),
            "lines": [],
            "couplets": 0,
            "syllables": 0,
            "est_bars": 0,
        }
        sections.append(current)

    for raw_line in lines[(first_header or 0):] if first_header is not None else []:
        line = raw_line.strip()
        if not line:
            continue
        hm = HEADER_RE.match(line)
        if hm:
            start_section(hm.group(1), hm.group(2) or "")
            continue
        if current is None:
            start_section("Verse", "")
        # Ignore pure separators, but keep the lyric text itself.
        if re.fullmatch(r"[-—–_.…\s]+", line):
            continue
        # A trailing ellipsis is the transcriber's usual mark for the second
        # half of a bayt.  Capture it before stripping punctuation.
        ellipsis = bool(re.search(r"(?:\.{2,}|…)\s*$", line))
        text_line = re.sub(r"(?:\.{2,}|…)\s*$", "", line).strip()
        if not text_line:
            continue
        tokens, count, estimated = syllabify_line(text_line)
        idx = len(current["lines"]) + 1
        line_id = f"{current['key']}.L{idx}"
        rec = {
            "id": line_id,
            "section": current["key"],
            "section_name": current["name"],
            "index": idx,
            "text": text_line,
            "syllables": tokens,
            "count": count,
            "estimated": estimated,
            "ellipsis": ellipsis,
            "role": None,
            "bayt": (idx + 1) // 2,
            "est_bars": est_bars_for(count, tempo),
        }
        current["lines"].append(line_id)
        current["syllables"] += count
        current["est_bars"] += rec["est_bars"]
        line_records.append(rec)

    # An unknown header with no lyric lines (e.g. [End], [Fin]) is not a
    # verse: the compiler would demand whole bayts of it.  Last -> outro,
    # otherwise interlude.  Sections with lyric lines keep the verse default.
    for pos, sec in enumerate(sections):
        if sec.pop("_unknown_kind", False) and not sec["lines"]:
            sec["kind"] = "outro" if pos == len(sections) - 1 else "interlude"

    for sec in sections:
        sec["line_count"] = len(sec["lines"])
        sec["couplets"] = sec["line_count"] // 2
        # Prefer the ellipsis mark; if the section has none, alternate.  Either
        # way a bayt is a sadr followed by an ajuz, never two lines of the
        # same role.
        sec_records = [r for r in line_records if r["section"] == sec["key"]]
        has_ellipsis = any(r.get("ellipsis") for r in sec_records)
        for pos, rec in enumerate(sec_records):
            if has_ellipsis:
                rec["role"] = "ajuz" if rec.get("ellipsis") else "sadr"
            else:
                rec["role"] = "sadr" if pos % 2 == 0 else "ajuz"
            rec["bayt"] = pos // 2 + 1
            rec["est_bars"] = est_bars_for(rec["count"], tempo, rec["role"])
        sec["est_bars"] = sum(r["est_bars"] for r in sec_records)
        if sec["kind"] in ("intro", "outro", "interlude"):
            empty_bars = {"interlude": 2, "silence": 1}.get(sec["kind"], 4)
            sec["est_bars"] = max(4, sec["est_bars"]) if sec["lines"] else empty_bars
        if sec["kind"] in ("chorus", "verse") and sec["est_bars"] < 4:
            sec["est_bars"] = 4
        sec["bayts"] = sum(1 for r in sec_records if r["role"] == "ajuz")

    totals = {
        "lines": len(line_records),
        "bayts": sum(1 for r in line_records if r["role"] == "ajuz"),
        "syllables": sum(r["count"] for r in line_records),
        "est_bars": sum(s["est_bars"] for s in sections),
        "sections": len(sections),
        "estimated_lines": sum(1 for r in line_records if r["estimated"]),
    }
    reference = {}
    if profile:
        p = profile["percentiles"]
        reference = {
            "tempo_p50": profile["tempos"]["percentiles"]["p50"],
            "bars_per_song_p50": p["bars_per_song"]["p50"],
            "vocal_span_p50": p["vocal_span"]["p50"],
            "onsets_per_beat_p50": p["onsets_per_beat"]["p50"],
            "rest_ratio_p50": p["rest_ratio"]["p50"],
            "chorus_lift_p50": p["chorus_lift_semitones"]["p50"],
            "section_lengths_p50": {
                k: v["p50"] for k, v in profile["sections"]["lengths"].items()
            },
            "top_forms": [f["form"] for f in profile["sections"]["forms"][:4]],
        }

    out = {
        "style": style,
        "sections": sections,
        "lines": line_records,
        "totals": totals,
        "reference": reference,
    }

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, sort_keys=False)
        f.write("\n")

    skeleton_path = args.skeleton or os.path.join(
        os.path.dirname(os.path.abspath(args.out)), "blueprint_skeleton.json")
    skeleton = build_skeleton(out)
    with open(skeleton_path, "w", encoding="utf-8") as f:
        # The skeleton is machine-read; compact JSON keeps the agent's context
        # small while staying valid and easy to diff by section.
        json.dump(skeleton, f, ensure_ascii=False, separators=(",", ":"))
        f.write("\n")

    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2 if args.pretty else None))
        return 0

    print(f"STYLE maqam={style.get('maqam')} mood={style.get('mood')!r} tempo={tempo}")
    print(f"SECTIONS {totals['sections']}  LINES {totals['lines']}  "
          f"BAYTS {totals['bayts']}  SYLLABLES {totals['syllables']}  "
          f"EST_BARS {totals['est_bars']}")
    print(f"SKELETON {skeleton_path}  (fill only voc/ins)")
    for sec in sections:
        print(f"\n[{sec['name']}] key={sec['key']} kind={sec['kind']} "
              f"lines={sec['line_count']} bayts={sec['bayts']} syl={sec['syllables']} "
              f"bars~{sec['est_bars']}")
        if sec["cues"]:
            print(f"  cues: {sec['cues']}")
        for lid in sec["lines"]:
            r = next(x for x in line_records if x["id"] == lid)
            est = " estimated" if r["estimated"] else ""
            print(f"  {r['id']:18s} {r['role']:4s} bayt {r['bayt']} "
                  f"{r['count']:3d} syl  ~{r['est_bars']} bars{est}  {r['text'][:60]}")
    if reference:
        print(f"\nREFERENCE tempo p50={reference['tempo_p50']}  "
              f"bars p50={reference['bars_per_song_p50']}  "
              f"span p50={reference['vocal_span_p50']}  "
              f"onsets/beat p50={reference['onsets_per_beat_p50']}  "
              f"lift p50={reference['chorus_lift_p50']}")
        print("  section p50: " + ", ".join(f"{k} {v}" for k, v in reference["section_lengths_p50"].items()))
    if args.seeds > 0:
        bank_path = args.phrase_bank or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "assets",
            "phrase_bank.json")
        bank = load_phrase_bank(bank_path)
        if bank:
            for line in build_seed_block(out, bank.get("phrases") or [], args.seeds):
                print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
