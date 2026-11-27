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

## Optional abcsim assets (0.2.3)

Three assets from `akbargherbal/abcsim` are shipped, all optional and read by
scripts rather than by the model. Their provenance (tag, commit, SHA-256, and
the AI-generated source corpus) is in `assets/PROVENANCE.md`.

- **Phrase seeds.** `assets/phrase_bank.json` holds 48 real vocal phrases in
  the Blueprint `degree:beats` grammar. Intake prints up to three matching
  8-beat seeds with `--seeds N` (default `0`, off; cap 3):

  ```bash
  python3 scripts/intake_lyrics.py --in prompt.txt -o intake.json \
    --skeleton blueprint_skeleton.json --seeds 3
  ```

  Seeds are stdout-only: `intake.json` and the skeleton are unchanged. They
  are offered only for 8-beat lines; a 16-beat shatr gets no seed rather than a
  mismatched one. `mode=any` marks a fallback when the maqam has no matching
  phrase. The whole block is capped at 400 bytes and carries no source key.
- **Novelty advisory.** `scripts/novelty_check.py` compares a compiled melody
  with `assets/corpus_fingerprints.bin` (a 630 KB bottom-256 sketch of 596
  deduped songs, stamped threshold `0.08`). The inspector prints a `NOVELTY`
  line in the compact card only when `status=close` (at most ~120 bytes) and
  always in `--verbose`. It never fails a build or rewrites a melody.
- **Dedup profile candidate.** `assets/corpus_profile.dedup.candidate.json` is
  for inspection only; `assets/corpus_profile.json` is unchanged.

Coverage is uneven: the bank has 8 Kurd, 8 hijaz, 8 rast, 15 nahawand, and
**1 bayati** phrase, and only 3 of 48 phrases are 16-beat. Bayati and 16-beat
lines usually fall back or get no seed. The corpus is AI-generated (Suno,
transcribed with SheetSage2), so a seed is a starting contour, not a quality
guarantee. Phase 6 (does seeding help?) was not run in this environment; seeds
therefore stay off by default.

## Tests

```bash
ABC2MIDI=/path/to/abc2midi python3 -m unittest discover -s tests -p 'test_*.py'
```

The tests cover Arabic syllabification and sadr/ajuz roles, the unvocalized
fallback, a full compile/validate round trip, the report `line_map`,
bar-sum/chord/syllable rejection, craft separation on the four reference
scores, a miner smoke test, novelty positive/negative/missing/corrupt
controls, and the seed budget, schema guard, and 16-beat rule.

## Files

- `SKILL.md` — the workflow the model follows.
- `references/blueprint_schema.md` — full Blueprint schema, `line_map`, and error codes.
- `references/vocal_craft.md` — prosody, phrase, cadence, motif, register rules.
- `references/corpus.md` — corpus percentiles, forms, chord loops, riffs, dedup note.
- `assets/craft_thresholds.json` — provisional craft thresholds and calibration.
- `assets/example_*` — a working 30-bar example (prompt, intake, skeleton, Blueprint, ABC).
- `assets/phrase_bank.json` — 48 optional 8/16-beat vocal phrases (`phrase_bank/2`).
- `assets/corpus_fingerprints.bin` — bottom-256 novelty sketch (630 KB, threshold 0.08).
- `assets/corpus_profile.dedup.candidate.json` — deduped profile candidate, inspection only.
- `assets/PROVENANCE.md` — abcsim tag/commit, source corpus, SHA-256 for every asset.
- `scripts/novelty_check.py` — stdlib-only advisory novelty check.
- `tests/fixtures/` — the one good and three defective reference scores, plus the `suno-0100.abc` novelty control.
