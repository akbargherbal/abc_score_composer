# Vocal craft: setting a bayt, not a scale

The corpus tells you what a finished Arabic pop transcription looks like. It
cannot tell you whether the tune follows the words, because the corpus has no
lyrics. These notes cover that missing layer. They are written in Blueprint
language: scale degrees, beats, bar counts, and lyric-line ids. Nothing here
asks you to write ABC.

The failure this prevents has a name in both traditions:

| Arabic | English | What it sounds like |
|---|---|---|
| التصييم اللحني | prosodic text-setting | the melody is cut to the words |
| الصدر / العجز | sadr / ajuz (antecedent / consequent) | two halves that answer each other |
| الجملة الدورية | periodic phrasing | a question phrase, then a closed answer |
| القفلة المعلقة / التامة | half / authentic cadence | the first half hangs, the second settles |
| الموتيف | motif | a short cell the ear can follow |
| التسلسل اللحني | melodic sequence | the cell repeated a step higher or lower |
| التضاد الإيقاعي | rhythmic contrast | long notes against a few fast turns |
| القوس الطبقي | register arc | the verse climbs before the chorus |
| التجوال السلمي | aimless scalar noodling | notes move, nothing arrives |

## The line plan (do this before the Blueprint)

Do not start with sections and fill bars. Start with the lyric lines. For each
line write one row:

| line | role | bars | cadence | motif | register |
|---|---|---:|---|---|---|
| `verse_1.L1` | sadr | 4 | `2` or `4` or `5`, never `1` | open with the cell | low |
| `verse_1.L2` | ajuz | 4 | `5` (or `1` at a section end) | same cell, varied ending | higher |

Then the section is the sum of its rows: one bayt is eight bars, two shatrs.
`intake_lyrics.py` already infers `role`, `bayt`, and a four-bar budget from
the trailing `...` mark (or alternates when the mark is absent). Use its table
as the skeleton; do not invent a different bar count.

A chorus or outro may end on degree `1`. A verse sadr should not: if every
phrase lands on the tonic the ear stops hearing where the sentence is going.

## Five rules, with the reason

### 1. Cut the melody to the line

Four bars per shatr, eight per bayt. A very short line may take two bars, but
never squeeze a whole bayt into four. The listener needs a stable amount of
time per line to know which line is being sung.

### 2. Close the sadr differently from the ajuz

The sadr is the question. End it on `2`, `4`, or `5` — an open degree. The
ajuz is the answer. End it on `5` (or `1` if this is the end of the section or
song). If both halves end on the same degree, the bayt sounds like one long
line repeated.

### 3. Breathe at the hemistich

End the sadr with at least `r:1.5`; end the bayt with `r:2`. A breath rest is
not decoration: it tells the singer and the listener that a line ended. Put it
in the last bar of the line, not after the next line has already begun.

### 4. Build a cell, then develop it

Use a four-to-six-note motif with a clear rhythm. State it in the first sadr.
Bring it back in the ajuz or the next verse with one of the Blueprint
transforms, or with a changed ending:

```json
"motifs": {
  "V1": {"voc": "(1:.5 b2:.5) (1:.5 b2:.5) 1:2"},
  "V2": {"voc": "V1 vary:end-4"}
}
```

Literal repetition is the other failure: the same phrase opening in every line
sounds mechanical. Keep the cell recognisable, vary its tail or sequence it.

### 5. Make a register arc, and contrast the rhythm

Start the verse low. Lift the second shatr by roughly four to seven semitones;
save a full octave for one climax phrase. The chorus should sit above the verse
median, but the whole song should still fit one singer (about 20 semitones).

Rhythm carries the same story. Hold the important word and the line ending;
leave the fast subdivision for a short turn inside the phrase. A song made
mostly of eighth or sixteenth notes has no words, only motion.

## Worked bayt: eight bars

`verse_1.L1` is the sadr (16 syllables), `verse_1.L2` the ajuz (12). The cell
is `1 b2 1 b2`; the ajuz lifts the same intervals to `1+ b2+ 1+ b2+`.

```json
{"ch": "Dm", "syl": "@verse_1.L1:1-4",
 "voc": "(1:.5 b2:.5) (1:.5 b2:.5) 1:1 b2:1", "ins": "rest"}
{"ch": "Gm", "syl": "@verse_1.L1:5-8",
 "voc": "b3:1 (1:.5 b7-:.5) b2:1 1:1", "ins": "1:4"}
{"ch": "Bb", "syl": "@verse_1.L1:9-12",
 "voc": "b7-:1 (1:.5 b7-:.5) (b2:.5 1:.5) b7-:1", "ins": "rest"}
{"ch": "A", "syl": "@verse_1.L1:13-16",
 "voc": "b2:.5 1:.5 b2:.5 b3:1 r:1.5", "ins": "r:2 5:2"}
{"ch": "Dm", "syl": "@verse_1.L2:1-3",
 "voc": "(1+:.5 b2+:.5) (1+:.5 b2+:.5) 1+:2", "ins": "rest"}
{"ch": "Gm", "syl": "@verse_1.L2:4-6",
 "voc": "(b2+:.5 1+:.5) (b2+:.5 1+:.5) b2+:2", "ins": "1:4"}
{"ch": "Bb", "syl": "@verse_1.L2:7-9",
 "voc": "(b2+:.5 1+:.5) (b2+:.5 1+:.5) b2+:2", "ins": "rest"}
{"ch": "A", "syl": "@verse_1.L2:10-12",
 "voc": "b2+:.5 1+:.5 5:1 r:2", "ins": "r:2 5:2"}
```

What the ear gets:

- bars 1–4: the cell low, a mid-phrase turn, a `b3` cadence, then `r:1.5`;
- bars 5–8: the same intervals an octave higher, a `b2+` sequence, and a `5`
  ajuz cadence with `r:2`;
- every bar sums to 4 beats, and every line ends on a note of at least one beat.

The matching intro, chorus, and outro are in
`assets/example_blueprint.json`; the compiled result is
`assets/example_song.abc`.

## What the inspector measures

`validate_and_inspect.py` prints a `CRAFT` line and `CRAFT FLAGS`. The checks
are advisory unless a Blueprint declares `meta.targets.craft: true` and you
validate with `--strict`.

| Metric | Good sign | Flag |
|---|---|---|
| line/bayt length | each hemistich 2 or 4 bars, each bayt 8 | a compressed or padded bayt |
| breath | a rest at every sadr/ajuz end | the line runs into the next one |
| cadence | sadr not on `1`; ajuz on `5`/`1`; halves differ | both halves close alike |
| long-notes | at least 17% of notes are 1 beat or longer | everything is short |
| register | verse phrase medians span 12+ semitones | the verse is flat |

Thresholds live in `assets/craft_thresholds.json`. They are **provisional**:
they were calibrated on one singable reference score and three scores with the
reported defect, not on the lyric-less corpus. Treat a flag as a question, not
as a syntax error.

## Patching map

| `CRAFT FLAG` | Blueprint change |
|---|---|
| line/bayt length | use the skeleton's `syl` ranges; each shatr is 4 bars and each bayt 8 |
| no breath | add `r:1.5` (sadr) or `r:2` (bayt); the compiler inserts it if absent |
| sadr on `1` or same cadence | end the sadr on `2`, `4`, or `5`; vary the ajuz |
| long-notes low | turn repeated `:.5` notes into `:1` or `:2` on key words |
| register flat | lift the ajuz 4–7 semitones; keep the sadr low instead of moving the whole verse |
