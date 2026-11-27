# Changelog

## 0.2.3

### Added (all optional; no mandatory reading added)

- `assets/phrase_bank.json`: 48 real vocal phrases (`schema: "phrase_bank/2"`,
  34,788 B) from the deduped 599-song SheetSage2 corpus, in the Blueprint
  tonic-relative `degree:beats` grammar. All 48 fit `phrase_bytes <= 130`
  (45 x 8-beat, 3 x 16-beat). `intake_lyrics.py --seeds N` (default `0`, cap 3)
  prints at most three matching 8-beat seeds in a <= 400 B block, with no source
  key and no change to `intake.json` or the skeleton. Read by a script, not by
  the agent.
- `scripts/novelty_check.py`: stdlib-only advisory check for how close a
  compiled melody is to the deduped corpus. `validate_and_inspect.py` calls it
  in-process inside `try/except`; a missing asset, corrupt bank, or any
  exception is skipped silently with `novelty: null`. The compact card prints
  `NOVELTY` only when `status=close` (66 B in the example); `--verbose` always
  prints it; `--json` gains a `novelty` key. Advisory only: it never changes
  `ok` and never triggers a rewrite.
- `assets/corpus_fingerprints.bin`: 8-token novelty hashes for 596 deduped
  representatives (`bottom-256` sketch, 150,037 hashes, 630,382 B, stamped
  threshold `0.08`).
- `assets/PROVENANCE.md`: abcsim tag/commit (`handoff-0.2.3-r3`,
  `91a999f`), the AI-generated Suno/SheetSage2 source corpus, and SHA-256 for
  every imported file.
- `tests/test_integration.py` and `tests/prompts/`: novelty
  positive/negative/missing/corrupt controls, seed budget/schema/16-beat
  tests, asset-size checks, and card-word parity.

### Changed

- `intake_lyrics.py` gains `--seeds N` and `--phrase-bank PATH`. With the flag
  absent or `0`, output is byte-identical to 0.2.2.
- `validate_and_inspect.py` prints the advisory novelty line after the CRAFT
  lines. `--novelty-bank` overrides the bank path for tests.
- Version 0.2.3 in `VERSION`, `SKILL.md`, and
  `assets/craft_thresholds.json`. `SKILL.md` grows 5,824 -> 5,945 B (+121 B,
  one `NOVELTY` line; the +150 B cap holds). The seed flag is **not**
  documented in `SKILL.md` because Phase 6 was not run.

### Candidate, not adopted

- `assets/corpus_profile.dedup.candidate.json` is the profile mined from the
  deduped corpus. The largest percentile shift is 3.6% of the full-corpus IQR
  (adoption threshold 10%), so `assets/corpus_profile.json` stays unchanged.
  The candidate is included only for inspection.

### Coverage and known limits

- Seeds are practical for 8-beat lines only. Only 3 of 48 phrases are 16-beat,
  so a 16-beat shatr gets no seed rather than a mismatched one.
- Mode coverage is uneven: nahawand 15, kurd 8, hijaz 8, rast 8, minor-like 6,
  major 2, **bayati 1**. Bayati lines usually fall back to `mode=any`.
- `role_hint` is inferred; selection filters on `cadence_class`. Degrees are
  tonic-relative and no source key is printed.
- Novelty controls: exact corpus copy `1.000` close; one vocal bar changed
  `0.981` close; all notes +2 semitones `0.630` close; `example_song.abc`
  `0.000` ok. The check is advisory, not a plagiarism verdict. abcsim reports
  45 of 47 duplicate pairs caught and an unrelated whole-bank maximum of
  `0.064` against the `0.08` threshold, so the margin is thin.
- Phase 6 (does seeding improve generation?) was not run in this environment.
  Per the pre-registered rule, seeds stay off by default and the flag is not in
  `SKILL.md`. See `docs/seed_eval_0.2.3.md`.

### Footprint (measured 2026-11-27)

- `SKILL.md`: 5,945 B (from 5,824 B, +121 B).
- Mandatory reading: 26,605 B (from 26,484 B; the only growth is the SKILL.md
  line). The new assets are script-read and not in `mandatory_files()`.
- Example: 1,352 B skeleton + 1,241 B fill; 30 bars; 27.2 B/bar.
- Compact card: 13 words on success, 32 on failure (unchanged).
- Largest seed block: 343 B across `tests/sample_prompt.txt`,
  `assets/example_prompt.txt`, and `tests/prompts/*.txt` (cap 400 B).
- Novelty line: 66 B in verbose; zero words on a compact `ok` card.
- Package zip: 712,520 B (from 80,391 B, about 8.9x; the 630 KB fingerprint
  bank does not compress).
- Tests: 32 pass, 0 skipped with abc2midi and the corpus present; 13 pass,
  1 skipped (miner, corpus absent) in a bare checkout.

## 0.2.2

- The agent now writes only `fill.json`: a compact `meta`/`motifs` plus one
  `[voc, ins]` row per skeleton bar. `compile_abc.py --skeleton sk --fill fill`
  merges it and rejects unknown, missing, wrong-length, or `same_as` sections.
- `intake_lyrics.py` writes the skeleton compactly: 2,853 B → 1,352 B for the
  example (47%). `agent_write_B` drops from 3,444 B (full Blueprint) to
  1,241 B (fill) and is now measured by `scripts/measure_footprint.py`.
- CRAFT adds one metric: verse phrase-median range must be at least 12
  semitones. The example is 12; the fixtures are 18 (excellent) and 6/10/3
  (07/11/16), so only the defective scores get `register flat`.
- SKILL.md gains a one-line maqam identity note: Kurd `b2/b3/b6/b7`, cadences
  on `1/4/5`, and natural `2/3` when MAQAM fit falls below 80%.
- The compact card prints abc2midi errors first, then ERRORS/WARNINGS, then
  CRAFT flags, so a failed render cannot hide a prosody flag.
- Correction: the earlier full-prompt token estimate counted only `voc/ins`,
  not the whole agent output. `agent_write_B` is the reproducible metric.
- Footprint: SKILL 5,808 B; mandatory reading 26,468 B; example 1,352 B
  skeleton + 1,241 B fill; success card 13 words; failure card 32 words.
- Tests: 14 pass with abc2midi; 0 skipped.

## 0.2.1

- Leaner footprint without dropping a prosody rule.
  - `SKILL.md` 13,921 B → 6,062 B; mandatory pre-Blueprint reading 34,028 B
    → 24,961 B; success card 223 → 13 words; failure card 248 → 27 words.
  - Example Blueprint 3,733 B → 3,444 B for the same 30 bars; agent payload
    stays 27.2 B/bar.
- `intake_lyrics.py` writes `blueprint_skeleton.json`: sections, bars, `ch`,
  and `syl` ranges (4 bars per shatr, 2/4 for short lines, `same_as` repeats).
  The agent fills only `voc` and `ins`.
- `compile_abc.py` inserts a missing breath rest (`r:1.5` sadr, `r:2` ajuz)
  and rejects a verse that is not whole bayts with `bad_verse_bars`.
- CRAFT is now four checks: line/bayt length, breath, sadr/ajuz cadence, and
  long-note share. Motif, fast-note, register-spread, range, and end-long
  metrics are gone; the patch advice remains in `references/vocal_craft.md`.
- The default inspector card is one line on success and only failing flags on
  failure; `--verbose` restores the full card and corpus bands.
- One musical patch round after the first clean compile; CRAFT flags are
  reported but not chased.
- Tests: added skeleton-to-ABC equality and verse-bar-count rejection; all 13
  tests pass with abc2midi.
- Correction: the earlier full-prompt token estimate counted only `voc/ins`,
  not the whole agent output. The reproducible metric is `agent_write_B` from
  `scripts/measure_footprint.py` (1,241 B for the example in 0.2.2).
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
