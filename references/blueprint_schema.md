# Blueprint schema and error codes

The Blueprint is the only file the model composes. The compiler turns it into
SheetSage2-style ABC. Durations are in **quarter-note beats**, not ABC grid
units. Pitches are **scale degrees**, not note letters.

## Top level

```json
{
  "meta": {...},
  "motifs": {...},
  "sections": [...]
}
```

### `meta`

| Field | Required | Meaning |
|---|---|---|
| `key` | yes | Plain major/minor key: `Dm`, `Gm`, `F#`, `Bb`. The compiler emits `K:` and spells degrees against this signature. |
| `maqam` | no | Label for the report (`kurd`, `hijaz`, `nahawand`, ...). It does not change pitches; the degrees do. |
| `meter` | no | Default `4/4`. A section may override. |
| `tempo` | no | Quarter-note BPM, default 90. |
| `vocal_octave` | no | Integer octaves added to every vocal degree. |
| `instrument_octave` | no | Same for Ins. |
| `vocal_range` | no | `[low, high]` MIDI, default `[48, 84]`. |
| `instrument_range` | no | `[low, high]` MIDI, default `[36, 96]`. |
| `title` | no | Optional label for `notes.md`; the delivered ABC keeps `T:` empty like the corpus. |
| `targets` | no | Musical targets the inspector checks: `melisma`, `chorus_lift`, `call_response`, `vocal_span`, `max_phrase_seconds`, `dominant_duration`, `maqam_fit`. Set `craft: true` to turn craft flags into a hard failure under `--strict`. |

### A section

```json
{"id": "v1", "kind": "verse", "meter": "4/4", "bars": [...]}
```

- `id` — unique; used by `same_as`, `from`, and reports.
- `kind` — `intro`, `verse`, `chorus`, `interlude`, `bridge`, `pre-chorus`,
  `outro`, `silence`. The compiler writes `% <kind>`.
- `meter` — optional override; a standalone `M:` line is emitted for both
  voices at that section boundary.
- `bars` — list of bar objects.

### A bar

```json
{"ch": "Dm", "voc": "1:.5 b2:.5 1:2", "syl": "a b c", "ins": "rest"}
```

- `ch` — one chord symbol, optional. Only the vocal bar carries it.
- `voc` — vocal line. Missing or `rest` means a whole-bar rest.
- `ins` — instrumental line. Missing or `rest` means a whole-bar rest.
- `syl` — one token per sung group, optional but required by `--strict` when
  the bar has vocal notes.
- `voc_shift` / `ins_shift` — semitone transposition, mainly for copies.
- `from` / `repeat` — copy one bar from another section; `take` selects the
  source bar index.

## Note grammar

```text
degree:beats
```

- Degree: `1`, `b2`, `2`, `b3`, `3`, `4`, `b5`, `5`, `b6`, `6`, `b7`, `7`.
  Accidental prefixes can repeat (`##`, `bb`). Examples: `#4`, `b2`.
- Octave: trailing `+`/`-` shift by one octave each. `1` is the tonic in
  octave 4; `1+` is one octave higher. Degree `7` is the leading tone **above**
  the tonic (`b7` is C5 in Dm); use `b7-` for the flat seventh below (C4).
  This is the most common octave slip when writing a descending phrase.
- Duration: quarter-note beats. Use `0.25`, `0.5`, `0.75`, `1`, `1.5`, `2`,
  `3`, `4`. Fractions (`3/2`) and decimals (`1.5`) are accepted.
- Tie: trailing `~` ties to the next note. `1:2~ 1:1` is a three-beat D.
- Rest: `r:<beats>` inside a line; `rest` alone fills the whole bar. A rest
  does not consume a syllable.

### Melisma

Parentheses group notes that are sung on **one** syllable:

```text
(b2:.25 1:.25 b2:.5)
```

This group is one syllable, three notes. The group must contain at least one
note. Groups cannot nest.

## Motifs

```json
"motifs": {
  "R1": {"ins": "1:.5 b2:.5 1:.5 b7-:.5 1:2"},
  "R2": {"ins": "R1 +oct"},
  "R3": {"ins": "R1 vary:end-b2"}
}
```

Transforms are separated by spaces after the motif name:

| Transform | Effect |
|---|---|
| `+oct` / `-oct` | transpose by ±12 semitones |
| `shift:<n>` | transpose by n semitones |
| `vary:end-<degree>` | replace the last note's degree |

A motif may contain `voc` and/or `ins`. A vocal field can only use a motif with
a `voc` line; an Ins field can only use one with `ins`.

## Reuse

### Whole section

```json
{"id": "c2", "kind": "chorus", "same_as": "c1",
 "take": [0, 1, 2, 3], "voc_shift": 0,
 "syl": ["@chorus_2.L1:1-4", "@chorus_2.L1:5-8",
         "@chorus_2.L2:1-4", "@chorus_2.L2:5-8"]}
```

- `same_as` copies all bars from the source.
- `take` selects source bar indexes (0-based).
- `voc_shift` / `ins_shift` transpose the copy by semitones. That changes the
  key, so do not use it as a chorus register lift; write higher degrees in the
  same key instead.
- `syl` is an optional per-bar override list. Use it when the repeated music
  carries different words.

### One bar

```json
{"from": "v1", "take": [0], "voc_shift": 0, "ch": "Dm"}
```

A bar-level copy must resolve to exactly one bar. Explicit `voc`, `ins`, `syl`,
and `ch` override the copied fields.

## Lyric references

`syl` accepts literal tokens or `@` references into `intake.json`:

| Form | Meaning |
|---|---|
| `@verse_1.L1` | all syllables of that line |
| `@verse_1.L1:1-4` | syllables 1 through 4 (1-based, inclusive) |
| `@verse_1.L1:5-8 @verse_1.L2:1-3` | concatenate ranges |

The compiler checks the resolved syllable count against the number of vocal
groups. A mismatch is a `syl_mismatch` error with the section, bar, and the
first syllables. It also reports unused and partially used lines, and builds
the report `line_map` from these references.

`intake_lyrics.py` marks every line `sadr` or `ajuz` (trailing `...` or
alternation), numbers its bayt, and budgets four bars per hemistich. Put each
line in its own four bars; the craft checks use that structure.

## Skeleton

`intake_lyrics.py --skeleton blueprint_skeleton.json` writes the mechanical
part of a Blueprint: `meta`, sections, bars, one `ch` per bar, and one `syl`
reference per bar. The bars follow the shatr/bayt budget (4/8, or 2/4 for a
line of eight syllables or fewer). For a repeated section named exactly the
same (`Chorus`, `Chorus`), the later one uses `same_as` and a new `syl` list.
Fill only `voc` and `ins`; the compiler adds a missing breath rest.

## Report line map

The compiler report carries a `line_map` list. It does not change the ABC and
does not add `w:` lines. Each entry records one lyric line occurrence:

```json
{
  "line": "verse_1.L1", "section": "v1", "kind": "verse",
  "role": "sadr", "bayt": 1, "start_bar": 5, "end_bar": 8, "bars": 4,
  "lyric_count": 16, "notes": 21, "melisma": 1.31, "median": 62,
  "cadence_pc": 3, "cadence_degree": "b3",
  "lead_rest": 0.0, "end_rest": 1.5
}
```

`cadence_pc` is the semitone distance of the last note above the tonic
(0 = degree 1, 7 = degree 5); `cadence_degree` is the same note spelled as a
Blueprint degree. The report also has `auto_breath`, a list of bars where the
compiler had to shorten notes to fit the required breath rest. The inspector uses it to check that a sadr does
not end on degree 1 and that an ajuz settles on 5 or 1. `end_rest` and
`lead_rest` are the rests at the line boundary; at least 0.5 beat is a breath.

## Error codes

| Code | Meaning | Fix |
|---|---|---|
| `bar_sum` | a voice does not fill the bar | add/remove a note or `r:<beats>` |
| `syl_mismatch` | syllable count ≠ vocal group count | split the `@` range or change the notes |
| `no_syl` | `--strict` and a vocal bar has no `syl` | add `syl` |
| `bad_chord` | chord outside the corpus grammar | use an accepted quality |
| `range` | a pitch is outside `vocal_range`/`instrument_range` | move octave or widen the range |
| `grid` | a duration is finer than 1/32 or does not fit | use ≥0.125-beat steps |
| `bad_motif` | unknown motif/transform, cycle, or wrong field | fix the motif reference |
| `bad_repeat` | `take` index outside the source, or a copy is not one bar | fix the indexes |
| `bad_group` | unclosed/empty/nested melisma group | fix the parentheses |
| `bad_tie` | a tie crosses a rest or a different pitch | use the same pitch, or remove the `~` |
| `bad_meter` | malformed meter | use `N/D` |
| `bad_section` | missing/duplicate/unknown id or a cycle | fix ids |
| `bad_verse_bars` | a verse with intake is not whole bayts | make it 8, 16, 24… bars |
| `breath_space` | no room for the automatic breath rest | shorten a note in that bar |

## Inspector report

The validator prints a compact card:

- `FORM` — total bars and contiguous section labels.
- `VOCAL` — range, corpus span band, onset density, rest ratio.
- `MOTION` — step/leap/repeat ratios, dominant duration share.
- `REGISTER` — verse and chorus medians, lift in semitones.
- `INS` — active bars, Ins-under-vocal ratio, call-response ratio.
- `MELISMA` — notes per syllable, target verdict.
- `PHRASE` — longest vocal run in seconds.
- `CHORDS` — changes per bar and common qualities.
- `SECTIONS` — per-section bars, median, notes.
- `FLAGS` — corpus p10/p90 extremes and target misses.
- `DIAGS` — concrete musical fixes.
- `CRAFT` — phrase count, long/fast note share, phrase-ending length,
  verse-register spread, tonic-cadence share, and motif reuse.
- `CRAFT FLAGS` — prosodic problems: compressed bayts, no breath, same
  cadence in both halves, flat register, wandering or over-literal motifs.
- `ERRORS` / `WARNINGS` — hard failures from bar sums, voice alignment, and
  abc2midi.
