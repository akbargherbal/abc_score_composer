# Changelog

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
