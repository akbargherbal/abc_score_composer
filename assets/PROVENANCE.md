# Provenance of the abcsim assets

These files come from `akbargherbal/abcsim`, handoff revision **3**:

- tag: `handoff-0.2.3-r3`
- commit: `91a999f94d6cdce600c9b95dd048b7c58462af9a`
- folder: `handoff/skill_0.2.3/`

At integration time the abcsim remote's `main` pointed at `91a999f`; the `r3`
tag name was not published on the remote (only `handoff-0.2.3-r2` was). The
commit, not the tag name, is the pin. Do not substitute `handoff-0.2.3-r2`:
its `novelty_check.check()` is broken.

## Source corpus

- 670 Suno-generated songs, transcribed with SheetSage2 into two-voice ABC.
- 599 kept after near-duplicate removal (71 near-duplicate files removed).
- 596 have a usable vocal track and are represented in the fingerprint bank.
- Transcriptions use 12-TET quantization, so there are no quarter-tones.
- The corpus has no lyrics, no quality ratings, and no human curation.

**The phrases and fingerprints derive from AI-generated songs.** They are
advisory composition aids, not human-authored reference material and not a
plagiarism verdict.

## Files and SHA-256

| File | Bytes | SHA-256 |
|---|---:|---|
| `assets/phrase_bank.json` | 34,788 | `a0253b2a55c6ac9975546197718b6e29a289a217c2916ca4ae809e1d1b4a446d` |
| `assets/corpus_fingerprints.bin` | 630,382 | `d2bfa38503e8ba6cdaebbfc09b502a4699ac97b038352fbbd0a63a6f1c6b4830` |
| `assets/corpus_profile.dedup.candidate.json` | 20,371 | `69980610e4db09953fb8473e424ac637e5220103125f440ab3b50d90104df430` |
| `scripts/novelty_check.py` | 14,736 | `c8e33b842bcd3ceae01977cc01ce0437c6c64c4a8580d7e4a1597d254f0d25c6` |
| `tests/fixtures/suno-0100.abc` | 4,563 | see below |

`tests/fixtures/suno-0100.abc` is an unmodified corpus song from
`670_arabic_songs_abc_scores.zip` (same abcsim commit). It exists only as the
positive control for the novelty check; it is not used at composition time.
Its SHA-256 is recorded by the test suite, not used as an input.

## What is shipped and what is not

- `phrase_bank.json` — shipped, read by `scripts/intake_lyrics.py` only.
- `corpus_fingerprints.bin` — shipped (`bottom-256` sketch, stamped threshold
  `0.08`), read by `scripts/novelty_check.py` only.
- `corpus_profile.dedup.candidate.json` — shipped for inspection only. **Not
  adopted.** `assets/corpus_profile.json` is unchanged.
- `novelty_check.py` — shipped beside `abc_common.py`.
- abcsim's `assets/alt/` fingerprint variants (`full`, `k512`, `k128`, `k64`)
  are **not** shipped. Phase 7 may swap one in later.
- abcsim's own source, tests, and documentation are not copied.

`novelty_check.py` is MIT-licensed (Copyright (c) 2026 akbargherbal), the same
license as this repository.
