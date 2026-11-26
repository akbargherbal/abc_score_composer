---
name: abc-score-writer
version: "0.2.0"
description: >-
  Compose a complete SheetSage2-style two-voice ABC score from Arabic lyrics
  and a style prompt (Arabic maqam, tarab, symphonic metal, etc.). The model
  writes a compact musical Blueprint; deterministic Python tools handle
  notation math, bar sums, voice alignment, maqam spelling, and abc2midi
  validation. Use whenever the user asks to write, compose, generate, or
  design a score, melody, song, or .abc file from lyrics and a style, even if
  they do not say "ABC" or "Blueprint". Do NOT use for editing an existing
  SheetSage2 transcription or for audio rendering.
---

# ABC Score Writer

You are the composer. The tune is the work. The tools measure and reject; they
never choose a note.

**Write a Blueprint, not raw ABC. Compile it. Read the card. Patch the
Blueprint. Deliver the `.abc`.**

## The loop

```text
intake -> line plan -> Blueprint -> compile -> inspect -> patch Blueprint
       -> compile -> inspect -> release
```

At most **2 musical patch rounds** after the first clean compile. Fixing
authoring errors (a wrong syllable range, an octave slip) before that is not a
musical round. If the same structural problem survives two musical rounds,
stop and report what the model or the plan could not solve.

The score is a *sung* bayt, not a scale walked up and down. The line plan is
where that is decided; the compiler and inspector can only measure it after
the fact.

## 1. Intake

```bash
python3 <skill>/scripts/intake_lyrics.py --in prompt.txt -o intake.json
```

Read the printed table. It gives stable line ids (`verse_1.L1`), syllable
counts, each line's role (`sadr` or `ajuz`), its bayt number, and a bar budget
(four bars per shatr, eight per bayt). The role comes from the trailing `...`
mark, or alternates when the mark is absent. Use `--json` only when you need
the full structure. Arabic with *tashkeel* is counted from the vowel marks;
unvocalized lines are marked `estimated`.

## 2. Plan the lines

Before writing any notes, copy the intake table and add four musical decisions
per line. This is the shatr plan; it prevents the "22 bars for five bayts"
failure where the tune ignores the words.

| line | role | bars | cadence | motif | register |
|---|---|---:|---|---|---|
| `verse_1.L1` | sadr | 4 | `2`, `4`, or `5` — not `1` | open with the cell | low |
| `verse_1.L2` | ajuz | 4 | `5` (or `1` at a section end) | same cell, varied ending | higher |

Rules that matter, with the reasons and a worked eight-bar bayt:
`references/vocal_craft.md`. Read it before the first Blueprint of a session.

## 3. Write the Blueprint

Write one JSON file. Think musically: form, chord loop, register arc, rhythm,
melisma, call-and-response. Do **not** write ABC, do **not** do bar arithmetic,
and do **not** compute pitches by hand.

### Schema

Full field reference and every error code: `references/blueprint_schema.md`.
A complete working example: `assets/example_blueprint.json` with
`assets/example_intake.json` and `assets/example_song.abc`.

```json
{
  "meta": {
    "key": "Dm",
    "maqam": "kurd",
    "meter": "4/4",
    "tempo": 84,
    "vocal_octave": 0,
    "targets": {"melisma": 1.3, "chorus_lift": 3, "call_response": 0.6,
                "vocal_span": 20, "max_phrase_seconds": 12, "maqam_fit": 0.8}
  },
  "motifs": {
    "R1": {"ins": "1:.5 b2:.5 1:.5 b7-:.5 1:2"}
  },
  "sections": [
    {"id": "intro", "kind": "intro", "bars": [
      {"ch": "Dm", "ins": "R1"},
      {"ch": "Gm", "ins": "R1 +oct"},
      {"ch": "Bb", "ins": "R1"},
      {"ch": "A",  "ins": "R1 +oct"}
    ]},
    {"id": "v1", "kind": "verse", "bars": [
      {"ch": "Dm", "syl": "@verse_1.L1:1-5",
       "voc": "1:.5 b2:.5 1:.5 b7-:.5 1:2", "ins": "rest"},
      {"ch": "Gm", "syl": "@verse_1.L1:6-9",
       "voc": "4:.5 b3:.5 (b2:.25 1:.25 b2:.5) 1:1 r:1", "ins": "rest"}
    ]},
    {"id": "c1", "kind": "chorus", "same_as": "v1",
     "syl": ["@chorus.L1:1-5", "@chorus.L1:6-9"]}
  ]
}
```

**Fields**

- `meta.key` — plain major/minor (`Dm`, `Gm`, `F#`, `Bb`). The compiler emits
  `K:` and spells the maqam's altered degrees with accidentals, matching the
  corpus. `meta.maqam` is a label, not a pitch table; the degrees decide pitches.
- `meta.meter` — default `4/4`; a section may override with `"meter": "2/4"`.
- `meta.tempo` — quarter-note BPM. `vocal_octave` shifts the whole vocal line;
  `instrument_octave` does the same for Ins (use `-1` for guitar/bass).
- `meta.targets` — optional. The inspector checks them and prints `OK/LOW/HIGH`.
  Set `"craft": true` to make the craft flags a hard failure under `--strict`;
  otherwise they are advisory.
- `motifs` — reusable `ins`/`voc` strings. Transforms: `+oct`, `-oct`,
  `shift:<semitones>`, `vary:end-<degree>`.
- Each bar has `ch` (one chord), `voc`, `syl`, `ins`. Vocal and Ins are written
  **together per bar**, so the voices cannot drift.
- `syl` — one token per sung group. `@line` or `@line:start-end` pulls the
  intake syllables; literals also work. A parenthesised group is **one**
  syllable: `(b2:.25 1:.25 b2:.5)`.
- `rest` fills a whole bar with a rest; `r:<beats>` is a timed rest.
- `same_as` copies a whole section; `take` selects bars. `voc_shift`/`ins_shift`
  transpose by semitones; they change the key, so use them for a deliberate
  key change or a riff, **not** as a chorus register lift. For a chorus lift in
  the same maqam, write higher degrees (`5`, `6`, `5`) instead. A bar-level copy
  is `{"from": "v1", "take": [0, 1], "voc_shift": 0}`.
- Keep one lyric line inside its own four bars and put its `@` reference in
  those bars. The compiler records this as `report.line_map`; the inspector
  uses it to check cadence and breath without any `w:` lines in the ABC.

**Note grammar**

`degree:beats`. Degrees are `1,b2,2,b3,3,4,b5,5,b6,6,b7,7` (also `#4`, etc.);
trailing `+`/`-` shift octaves. Degree `7` is the leading tone **above** the
tonic: in Dm `b7` is C5 and `b7-` is C4. Durations are quarter-note beats:
`0.25`, `0.5`, `0.75`, `1`, `1.5`, `2`. A trailing `~` ties to the next note.

## 4. Compile and inspect

```bash
python3 <skill>/scripts/compile_abc.py blueprint.json -o song.abc \
  --intake intake.json --report song.report.json \
  --validation-out song.validation.abc --strict

python3 <skill>/scripts/validate_and_inspect.py song.abc \
  --report song.report.json --validation song.validation.abc
```

Compile writes `song.abc` only when every bar sums to the meter and the voices
align. `--strict` requires `syl` on every vocal bar. The validation file carries
temporary `w:` placeholders; the delivered `song.abc` has **no** `w:` lines,
exactly like the corpus.

Read the card, not just the exit code:

- `ERRORS` — `bar_sum`, `syl_mismatch`, `bad_chord`, `range`, `grid`,
  `bad_motif`. Fix the Blueprint and recompile.
- `FLAGS` — corpus p10/p90 extremes and target misses. These are musical, not
  syntax; decide with the ear and the prompt.
- `DIAGS` — long phrases, no Ins under the vocal, weak call-and-response, no
  chorus lift.
- `CRAFT` — phrase length, cadence, breath, register arc, long-note and
  fast-note share, and motif reuse. `CRAFT FLAGS` names the musical problem;
  `CRAFT OK` means the line plan is audible. These flags are advisory unless
  `meta.targets.craft` is true and you pass `--strict`.
- `abc2midi` — any `Error`/`Warning` is a hard failure; the tool does not trust
  exit code 0.

## 5. Patch the Blueprint, not the ABC

Change the smallest musical unit: a bar, a motif, a section reference. Then
recompile the whole file. Do not edit `song.abc` with `sed`, Python, or
piecemeal edits; the only score write is a whole compile.

Common fixes:

| Symptom | Blueprint fix |
|---|---|
| `bar_sum` | add/remove a note or `r:<beats>` in that bar |
| `syl_mismatch` | split the `@line` range, or add/remove a note group |
| `bad_chord` | use a corpus chord: `m, maj7, m7, 7, 6, m6, m7b5, dim, aug, sus2, sus4, 7sus4, 9, m9, dim7, maj9, 5` |
| `range` | move the degree by `+`/`-`, or set `vocal_octave` |
| `grid` | use durations in 0.25-beat steps (0.125 minimum) |
| long phrase | add `r:0.5` or `r:1` at a hemistich |
| verse bars not a multiple of 4 | give each shatr 4 bars and each bayt 8; do not compress the bayt |
| `CRAFT` line/bayt length | rewrite the `syl` ranges so each line owns its 4 bars |
| no breath after a line | put `r:1.5` at the sadr end and `r:2` at the bayt end |
| sadr cadences on `1` | end sadr on `2`, `4`, or `5`; keep `1` for the ajuz or section end |
| both halves end alike | vary the ajuz degrees or use `vary:end-` on the cell |
| register flat | lift the ajuz by 4–7 semitones, or write `5+`/`1+` at the climax |
| no long notes | turn repeated `:.5` notes into `:1`/`:2` on key words and line ends |
| too many fast notes | remove some `:.25` turns; keep one turn per phrase |
| phrase opens wander | state a 4–6 note cell and reuse it with `vary:end-` |
| phrase opens too literal | vary the tail, transpose (`+oct`, `shift:2`), or keep the rhythm and change the degrees |
| no chorus lift | rewrite the chorus degrees higher in the same key; do not transpose the whole verse, which changes the maqam |
| no call-and-response | leave vocal gaps and put an Ins motif in them |
| Ins silent under vocal | add a sustained root or muted riff in some vocal bars |

## 6. Release

Deliver `song.abc` when:

- `abc2midi` reports **0 errors and 0 warnings**.
- every bar sums correctly and both voices have the same bar count.
- `syl` covers every vocal bar (or the user explicitly accepts a missing
  alignment), and no intake line is accidentally unused.
- `CRAFT` has no flags: one bayt is eight bars, each line breathes, sadr and
  ajuz cadences differ, the verse has a register arc, and the motif recurs
  without being copied literally.
- the chorus is measurably above the verse, and the vocal span fits one singer.
- the file has the corpus header and no `w:` lines.

## Corpus quick reference

Full data: `assets/corpus_profile.json`; readable summary:
`references/corpus.md`. Maqam degree tables and spelling: `references/maqam.md`.
Prosody, phrase, cadence, and register rules: `references/vocal_craft.md`.
Craft thresholds and their calibration: `assets/craft_thresholds.json`.

| Metric | p10 | p50 | p90 |
|---|---:|---:|---:|
| Tempo (BPM) | 72 | 93 | 135 |
| Bars per song | 92 | 149 | 216 |
| Vocal span (semitones) | 10 | 14 | 20 |
| Step / leap / repeat | .39/.08/.25 | .49/.14/.36 | .61/.22/.47 |
| Vocal onsets per beat | .85 | 1.17 | 1.65 |
| Vocal rest ratio | .34 | .45 | .56 |
| Bars with vocal | .55 | .66 | .77 |
| Bars with Ins | .21 | .32 | .45 |
| Ins in vocal gaps | .74 | .89 | .97 |
| Chorus lift (semitones) | -2 | +1 | +5 |
| Chord changes per bar | .50 | .67 | .89 |

- **Form:** `intro verse chorus interlude verse chorus outro` is the most common
  shape. Section medians: intro 17, verse 16, chorus 16, interlude 16, outro 11.
- **Keys:** Cm, Gm, Em, Am, Dm dominate. 4/4 in 411 files, 2/4 in 236.
- **Chords:** one per bar. Common changes (semitones from tonic):
  `0m-5m-0m-5m`, `7m-0m-10-8`, `0m-10-0m-10`, `0m-5m-10-3`.
- **Rhythm:** 0.5-beat notes dominate, then 0.25. Do not write a whole song in
  one duration; the dominant share should stay under ~60%.
- **Melisma:** the corpus has no lyrics, so it has no melisma percentile. Use
  the style prompt: a melismatic/tarab request means roughly 1.2-1.6 notes per
  syllable, placed on phrase endings and long vowels, not on every word.
- **Call-and-response:** Ins answers in ~89% of vocal-silent bars. That is a
  corpus habit, not a floor; still leave real gaps for it, and also let Ins
  sustain or riff under some vocal bars so the singer is not naked.

## Composition guidance

- **One shatr = 4 bars at 4/4** (2 bars for a short line); one bayt = two
  shatrs = 8 bars. A breath `r:1.5` ends the sadr; `r:2` ends the bayt.
- **Period, not a run-on:** the sadr asks, the ajuz answers. Sadr cadence on
  `2`, `4`, or `5`; ajuz on `5`, or `1` only at a section/song end. Do not end
  every phrase on the tonic.
- **Motif:** state a 4–6 note cell with a clear rhythm. Repeat it with
  `vary:end-`, `+oct`, or `shift:<n>`; do not copy the whole opening literally
  in every phrase.
- **Rhythm:** hold the important word and the line ending. Keep `:.25` turns
  rare; a stream of fast notes erases the words. The `CRAFT` card reports the
  long-note and fast-note shares.
- **Register arc:** start the verse low, lift the ajuz 4–7 semitones, and save
  an octave for one climax phrase. Chorus 3–5 semitones above the verse median;
  outro back down. A single singer should stay within about 20 semitones.
- **Maqam identity:** for Kurd on D use `b2` (Eb), `b3` (F), `b6` (Bb), `b7`
  (C), and touch `1`; for Nahawand use `2` and `b3`; for Hijaz use `b2` and `3`.
  The inspector prints `MAQAM ... fit`; below 80% means the degrees drifted
  (usually a natural `2`/`3` where Kurd wants `b2`/`b3`).
- **Chorus:** change the chord loop or the rhythmic cell, not only the words.
  The lift should be heard, not just written.
- **Instrumental:** a riff is 2-8 notes with a clear shape. Use `motifs` and
  `+oct`/`vary` instead of rewriting the same riff.

## Rules

- The model composes; the tools measure. Never hand-write ABC or hand-compute
  bar sums.
- No third-party Python packages. Only the standard library and `abc2midi`.
- No `w:` lines in the delivered file. Validation may use them temporarily.
- Do not patch `song.abc`; patch the Blueprint and recompile.
- If `abc2midi` is missing, install it (`apt-get install abcmidi`,
  `brew install abcMIDI`) or set `ABC2MIDI=/path/to/abc2midi`.
