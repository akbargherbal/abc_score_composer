# Changelog

## 0.2.0

- New prosodic layer: `references/vocal_craft.md` defines the line plan
  (sadr/ajuz, 4 bars per shatr, 8 per bayt), cadence rules, breath rests, motif
  development, rhythmic contrast, and the verse register arc.
- `intake_lyrics.py` now infers `role` (sadr/ajuz) from the trailing `...` or
  by alternation, numbers each bayt, and budgets four bars per hemistich
  instead of estimating from syllable density.
- `compile_abc.py` emits a `line_map` in the report: bars, role, median,
  cadence pitch class, and boundary rests for every lyric line. The ABC output
  is unchanged.
- `validate_and_inspect.py` gains a `CRAFT` section and `CRAFT FLAGS`:
  phrase length, bayt budget, breath, sadr/ajuz cadence, long-note share,
  fast-note share, verse register spread, and motif reuse. Advisory by default;
  `meta.targets.craft: true` plus `--strict` makes it a gate.
- New `assets/craft_thresholds.json`, calibrated on one good and three
  defective reference scores; thresholds are marked provisional.
- Rewritten 30-bar example with two hemistichs per section, repeated-with-
  variation motif, distinct cadences, breath rests, and a verse register arc.
- New tests: role inference, `line_map`, a craft-clean example, and craft
  separation on the four reference fixtures.

## 0.1.0

- Clean-room replacement for the legacy `02_maqam-score` architecture. The old
  workflow patched ABC directly and mixed composition with notation repair;
  this version separates the Blueprint (model) from the compiler/inspector
  (deterministic Python).

- Blueprint -> ABC compiler with bar-sum, voice-alignment, chord, range,
  tie, and syllable checks.
- `intake_lyrics.py` with a tashkeel-aware Arabic syllabifier (the sample's
  first two lines count 16 and 12) and an unvocalized fallback.
- `mine_corpus.py` over the 670-file SheetSage2 corpus, with empty-vocal
  filtering, isolated meter-slip logging, percentiles, chord loops, and Ins
  riff shapes.
- `validate_and_inspect.py` with abc2midi stdout/stderr parsing, corpus band
  flags, maqam fit, melisma, chorus lift, call-response, and phrase length.
- Lean `SKILL.md`, `references/blueprint_schema.md`,
  `references/corpus.md`, `references/maqam.md`.
- 18-bar working example and 9 deterministic tests.
- End-to-end full-prompt run: 129 bars, 366/366 syllables, 0 abc2midi
  errors/warnings, maqam fit 100%, melisma 1.44, chorus lift +4, call-response
  0.92, no validator flags.
