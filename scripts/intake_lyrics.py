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
import json
import math
import os
import re
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from abc_common import load_json  # noqa: E402

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

KIND_MAP = {
    "intro": "intro", "opening": "intro",
    "verse": "verse", "v": "verse",
    "chorus": "chorus", "refrain": "chorus",
    "interlude": "interlude", "break": "interlude", "instrumental": "interlude",
    "bridge": "bridge",
    "pre-chorus": "pre-chorus", "prechorus": "pre-chorus", "pre chorus": "pre-chorus",
    "outro": "outro", "ending": "outro", "coda": "outro",
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


def normalize_kind(name: str) -> str:
    low = name.lower().strip()
    for key, kind in KIND_MAP.items():
        if low == key or low.startswith(key + " ") or low.startswith(key + "-"):
            return kind
    if low.startswith("verse"):
        return "verse"
    if low.startswith("chorus"):
        return "chorus"
    return "verse"


def est_bars_for(syllables: int, tempo: int | None = None) -> int:
    # 4 sung notes per bar is a comfortable, breathable density; the corpus
    # overall average is about 3.8-4.7 notes per bar once rests are included.
    dens = 4.0
    if tempo and tempo >= 120:
        dens = 4.8
    elif tempo and tempo <= 75:
        dens = 3.4
    return max(2, int(math.ceil(syllables / dens)))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--in", dest="inp", required=True, help="prompt file, or - for stdin")
    ap.add_argument("-o", "--out", default="intake.json")
    ap.add_argument("--profile", default=None,
                    help="corpus_profile.json (default: ../assets/corpus_profile.json)")
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
        text_line = re.sub(r"\.{2,}\s*$", "", line).strip()
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
            "est_bars": est_bars_for(count, tempo),
        }
        current["lines"].append(line_id)
        current["syllables"] += count
        current["est_bars"] += rec["est_bars"]
        line_records.append(rec)

    for sec in sections:
        sec["line_count"] = len(sec["lines"])
        sec["couplets"] = sec["line_count"] // 2
        if sec["kind"] in ("intro", "outro", "interlude"):
            sec["est_bars"] = max(4, sec["est_bars"]) if sec["lines"] else 4
        if sec["kind"] in ("chorus", "verse") and sec["est_bars"] < 4:
            sec["est_bars"] = 4

    totals = {
        "lines": len(line_records),
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

    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2 if args.pretty else None))
        return 0

    print(f"STYLE maqam={style.get('maqam')} mood={style.get('mood')!r} tempo={tempo}")
    print(f"SECTIONS {totals['sections']}  LINES {totals['lines']}  "
          f"SYLLABLES {totals['syllables']}  EST_BARS {totals['est_bars']}")
    for sec in sections:
        print(f"\n[{sec['name']}] key={sec['key']} kind={sec['kind']} "
              f"lines={sec['line_count']} syl={sec['syllables']} bars~{sec['est_bars']}")
        if sec["cues"]:
            print(f"  cues: {sec['cues']}")
        for lid in sec["lines"]:
            r = next(x for x in line_records if x["id"] == lid)
            est = " estimated" if r["estimated"] else ""
            print(f"  {r['id']:18s} {r['count']:3d} syl  ~{r['est_bars']} bars{est}  {r['text'][:60]}")
    if reference:
        print(f"\nREFERENCE tempo p50={reference['tempo_p50']}  "
              f"bars p50={reference['bars_per_song_p50']}  "
              f"span p50={reference['vocal_span_p50']}  "
              f"onsets/beat p50={reference['onsets_per_beat_p50']}  "
              f"lift p50={reference['chorus_lift_p50']}")
        print("  section p50: " + ", ".join(f"{k} {v}" for k, v in reference["section_lengths_p50"].items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
