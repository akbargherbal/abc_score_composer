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

Compose a **sung bayt**, not a scale walked up and down. You write the
Blueprint; Python does the notation math and validation. Never hand-write ABC.

**Loop:** `intake -> Blueprint -> compile -> inspect -> patch Blueprint -> release`

At most **1 musical patch round** after the first clean compile. Authoring
fixes (a syllable range, an octave slip) are not musical rounds. If the same
structural problem survives one round, stop and report it.

## 1. Intake

```bash
python3 <skill>/scripts/intake_lyrics.py --in prompt.txt -o intake.json \
  --skeleton blueprint_skeleton.json
```

Read the printed table. Each line gets an id (`verse_1.L1`), a role (`sadr` or
`ajuz`), a bayt number, and a budget: **4 bars per shatr, 8 per bayt**. The
role comes from a trailing `...`, otherwise it alternates. Arabic with
*tashkeel* is counted from the vowel marks; unvocalized lines are `estimated`.

`blueprint_skeleton.json` already contains the sections, bars, `ch`, and `syl`
ranges, including `same_as` for a repeated chorus. **Fill only `voc` and `ins`.**
Do not retype `ch` or `syl`.

## 2. Write the Blueprint

One JSON file, starting from the skeleton. Think register, rhythm, melisma, and
call-and-response. Do not write ABC, do bar arithmetic, or compute pitches by
hand.

Full schema and error codes: `references/blueprint_schema.md`. Working example:
`assets/example_blueprint.json` with its skeleton, intake, and compiled ABC.


- `meta.key` is plain major/minor (`Dm`, `F#`); the maqam is a label and the
  degrees decide pitches. `vocal_octave`/`instrument_octave` shift a voice.
- Each bar has `ch`, `voc`, `syl`, `ins`. `syl` is one token per sung group;
  `@line:start-end` pulls intake syllables, and `(a b c)` is one melisma group.
- Use `same_as` for a repeated chorus/outro and `{"from": "v1", "take": [0]}` to
  reuse a bar. `voc_shift`/`ins_shift` transpose by semitones.
- `rest` fills a bar; `r:<beats>` is a timed rest. `meta.targets.craft: true`
  makes CRAFT flags a hard failure under `--strict`.

**Note grammar:** `degree:beats`. Degrees `1,b2,2,b3,3,4,b5,5,b6,6,b7,7`
(also `#4`). Trailing `+`/`-` shift octaves; `7` is the leading tone above the
tonic. Durations are quarter-note beats (`0.25`, `0.5`, `1`, `2`); trailing `~`
ties to the next note.

## 3. Compile and inspect

```bash
python3 <skill>/scripts/compile_abc.py blueprint.json -o song.abc \
  --intake intake.json --report song.report.json \
  --validation-out song.validation.abc --strict

python3 <skill>/scripts/validate_and_inspect.py song.abc \
  --report song.report.json --validation song.validation.abc
```

Compile writes `song.abc` when bar sums and voice alignment pass.
`--strict` requires `syl` on every vocal bar. The delivered ABC has no `w:`
lines. A verse that is not whole bayts fails with `bad_verse_bars`; the
compiler also inserts the missing breath (`r:1.5` after a sadr, `r:2` after an
ajuz). Card: one line on success; `--verbose` prints the
corpus card.

- `ERRORS` are structural (`bar_sum`, `syl_mismatch`, `bad_chord`, `range`,
  `grid`, `bad_motif`, `bad_verse_bars`). Fix the Blueprint and recompile.
- `FLAGS` are corpus extremes/target misses; musical, not syntax.
- `CRAFT` checks line length, breath, cadence, and long-note share. Advisory
  unless `meta.targets.craft` is true and you pass `--strict`.
- Any `abc2midi` `Error`/`Warning` is a hard failure.

## 4. Patch the Blueprint, not the ABC

Change the smallest unit: one bar, one motif, one section reference, then
recompile the whole file. Never edit `song.abc` with `sed`, Python, or piecemeal
edits. If a CRAFT flag appears, change only the affected bars; do not rewrite
the whole Blueprint. Fixes: `references/vocal_craft.md` (read it when a flag
appears).

## 5. Release

Deliver `song.abc` when:

- `abc2midi` reports **0 errors and 0 warnings**;
- every bar sums, both voices align, and every pitch is in range;
- `syl` covers the vocal bars and no intake line is unused;
- CRAFT is advisory: mention any flag, do not chase it;
- the chorus is above the verse and the vocal span fits one singer;
- the file has the corpus header and no `w:` lines.

## Five prosody rules

1. **Line shape:** one shatr = 4 bars, one bayt = 8; a short line (≤8 syllables) may take 2 bars.
2. **Cadence:** sadr ends on `2`, `4`, or `5`; ajuz on `5`, or `1` only at a section end. Do not end both halves on the same degree.
3. **Breath:** `r:1.5` at the sadr end, `r:2` at the bayt end.
4. **Motif:** state a 4–6 note cell, then repeat it with `vary:end-`, `+oct`, or `shift:<n>`; avoid literal copies.
5. **Arc and rhythm:** start the verse low, lift the ajuz 4–7 semitones, save an octave for one climax. Hold key words and line endings; keep `:.25` turns rare.

## Corpus

Medians: 149 bars, 93 BPM, 14 st vocal span, 1.17 onsets/beat, .45 rest, +1 st
chorus lift. Common form: intro–verse–chorus–interlude–verse–chorus–outro.
Details: `references/corpus.md`. Maqam spelling: `references/maqam.md`.

## Rules

- The model composes; the tools measure. Never hand-write ABC or hand-compute bars.
- No third-party Python. Only stdlib and `abc2midi`.
- No `w:` lines in the delivered file; validation may use them temporarily.
- Do not patch `song.abc`; patch the Blueprint and recompile.
- If `abc2midi` is missing, install it (`apt-get install abcmidi`,
  `brew install abcMIDI`) or set `ABC2MIDI=/path/to/abc2midi`.
