# Novelty check: controls and known limits (0.2.3)

Measured on 2026-11-27 with the shipped `bottom-256` bank
(`assets/corpus_fingerprints.bin`, 630,382 B, stamped threshold `0.08`) and
`scripts/novelty_check.py` at abcsim commit `91a999f`.

## Controls

| Input | Result | Runtime |
|---|---|---|
| `assets/example_song.abc` (not corpus) | `closest=none containment=0.000 status=ok` | ~0.18 s |
| `tests/fixtures/suno-0100.abc` (unmodified corpus song) | `closest=suno-0100.abc containment=1.000 status=close` | ~0.18 s |
| `suno-0100.abc`, one vocal bar changed | `closest=suno-0100.abc containment=0.981 status=close` | ~0.18 s |
| `suno-0100.abc`, all notes +2 semitones | `closest=suno-0100.abc containment=0.630 status=close` | ~0.18 s |

The varied and transposed files were generated from the fixture and are not
shipped. Both still render with abc2midi without errors.

## Known limits

- **Transposition is still detected.** The tokenizer uses interval and rhythm
  classes, which are invariant under transposition, so a transposed copy stays
  `close` (0.630 here, below the exact copy's 1.000 because accidentals and
  octave spelling shift some 8-grams). This is a feature, not a miss.
- **A one-bar change is still `close`** (0.981). The check is a corpus-similarity
  advisory, not an exact-copy detector.
- **Rhythmic variants are the weak spot.** abcsim reports 45 of 47 duplicate
  pairs caught at `0.08`; two cluster pairs score below the threshold. Exact
  8-gram matching is a lower bound.
- **Unrelated material can be near the threshold.** abcsim's whole-bank
  unrelated maximum is `0.064` against `0.08`; the margin is thin. Treat
  `close` as "look at this", never as a plagiarism verdict.
- **Compact output is silent unless `status=close`.** `status=ok` adds zero
  words to the success card; verbose mode always prints the line.
