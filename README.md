# abc-score-writer

A lean, deterministic skill for composing SheetSage2-style two-voice ABC
scores from Arabic lyrics and a style prompt.

The model writes a **Blueprint** (scale degrees, beats, syllables, chords,
motifs). Python does the notation math and validation. No third-party packages.

This is a clean-room replacement for the legacy `02_maqam-score`
patch-by-patch workflow. The old architecture mixed composition with notation
repair; this one separates them: the model composes, the compiler and
inspector measure, and the model patches the Blueprint rather than the ABC.

Version 0.2.x adds the missing **vocal craft** layer. The corpus can measure a
transcription, but it has no lyrics, so it cannot tell whether a tune follows
the words. `CRAFT` checks shatr/bayt length, breath, sadr/ajuz cadence, and
long-note share. It is calibrated on four
hand-labelled scores: one singable (`tests/fixtures/excellent.txt`) and three
with the aimless-scalar defect (`07`, `11`, `16`). The rules, terminology, and
a worked eight-bar bayt are in `references/vocal_craft.md`.

## Quick start

```bash
python3 scripts/intake_lyrics.py --in prompt.txt -o intake.json \
  --skeleton blueprint_skeleton.json

python3 scripts/compile_abc.py \
  --skeleton blueprint_skeleton.json --fill fill.json -o song.abc \
  --intake intake.json --report song.report.json \
  --validation-out song.validation.abc --strict

python3 scripts/validate_and_inspect.py song.abc \
  --report song.report.json --validation song.validation.abc \
  --abc2midi /path/to/abc2midi
```

Write only `voc`/`ins` rows in `fill.json`; `ch` and `syl` stay in the
skeleton. The inspector prints one line on success; add `--verbose` for the
full card.

The delivered `song.abc` mirrors the corpus: `V: Vocal` + `V: Ins`, no `w:`
lyrics, 4-bar voice blocks, chord symbols on the vocal, `Z` for silent bars.

## Install

Copy this directory into your skills folder, or package it as a zip:

```bash
# OpenCode
cp -r abc-score-writer ~/.config/opencode/skills/
# Claude Code
cp -r abc-score-writer ~/.claude/skills/

# or package
cd ..
zip -r abc-score-writer.zip abc-score-writer
```

`abc2midi` is required for validation. Install it with your package manager
(`apt-get install abcmidi`, `brew install abcMIDI`) or set `ABC2MIDI`.

## Corpus profile

`assets/corpus_profile.json` is mined from the 670-file SheetSage2 corpus.
`references/corpus.md` is the readable summary. Rerun the miner with:

```bash
python3 scripts/mine_corpus.py --corpus /path/to/670_arabic_songs_abc_scores \
  --out assets/corpus_profile.json
```

## Tests

```bash
ABC2MIDI=/path/to/abc2midi python3 tests/test_roundtrip.py
```

The tests cover Arabic syllabification and sadr/ajuz roles, the unvocalized
fallback, a full compile/validate round trip, the report `line_map`,
bar-sum/chord/syllable rejection, craft separation on the four reference
scores, and a miner smoke test.

## Files

- `SKILL.md` — the workflow the model follows.
- `references/blueprint_schema.md` — full Blueprint schema, `line_map`, and error codes.
- `references/vocal_craft.md` — prosody, phrase, cadence, motif, register rules.
- `references/corpus.md` — corpus percentiles, forms, chord loops, riffs.
- `assets/craft_thresholds.json` — provisional craft thresholds and calibration.
- `assets/example_*` — a working 30-bar example (prompt, intake, skeleton, Blueprint, ABC).
- `tests/fixtures/` — the one good and three defective reference scores.
