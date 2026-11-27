# Corpus reference

Mined from the 670 SheetSage2 files. Empty-vocal files are excluded from vocal statistics; off-meter bars are ignored for phrase lengths. The corpus has **no `w:` lyrics**, so melisma cannot be benchmarked from it.

## Deduplication (0.2.3)

abcsim removed 71 near-duplicate files before mining the phrase and
fingerprint banks, keeping 599 songs (596 with a usable vocal). The percentile
bands are essentially unchanged: the largest shift is 3.6% of the full-corpus
IQR, below the 10% adoption threshold. `assets/corpus_profile.json` is
therefore unchanged and still describes the full 670-file set. The deduped
candidate is shipped only as `assets/corpus_profile.dedup.candidate.json` for
inspection; do not swap it in without recording the change.

- Files: 670; used for vocal stats: 644; empty vocal: 26; empty Ins: 1.
- Non-dominant-meter bars: 1228; isolated 1-2 bar meter runs: 1126. The latter are the likely beat-tracking slips the brief says to ignore; the rest are intentional section changes (usually 2/4).

## Formats

- Meters: 4/4 (411), 2/4 (236), 6/8 (10), 3/4 (7), 1/4 (3), 5/8 (2), 2/8 (1)
- Grids: 1/16 (350), 1/32 (320)
- Keys: Cm (101), Gm (89), Em (74), Am (71), Dm (67), Fm (45), Bbm (43), Bm (36), D#m (29), F#m (28), G#m (28), C#m (24)
- Tempo p10/p50/p90: 72.0/93.0/135.0

## Percentiles

| Metric | p10 | p25 | p50 | p75 | p90 |
|---|---:|---:|---:|---:|---:|
| bars_per_song | 92.0 | 115.0 | 149.0 | 184.25 | 216.0 |
| vocal_low | 60.0 | 62.0 | 65.0 | 68.0 | 71.0 |
| vocal_high | 76.0 | 77.0 | 79.0 | 83.0 | 85.0 |
| vocal_span | 10.0 | 12.0 | 14.0 | 17.0 | 20.0 |
| step_ratio | 0.3873 | 0.434 | 0.4904 | 0.5606 | 0.6082 |
| leap_ratio | 0.0836 | 0.1064 | 0.1358 | 0.1775 | 0.2219 |
| repeat_ratio | 0.2541 | 0.2975 | 0.3576 | 0.4194 | 0.4663 |
| onsets_per_beat | 0.8481 | 0.9823 | 1.1731 | 1.4262 | 1.6498 |
| rest_ratio | 0.3367 | 0.3877 | 0.4471 | 0.5036 | 0.5556 |
| vocal_active_bars | 0.5466 | 0.6 | 0.6619 | 0.7134 | 0.7684 |
| ins_active_bars | 0.2115 | 0.2658 | 0.3206 | 0.3878 | 0.4524 |
| ins_in_vocal_gaps | 0.7391 | 0.8283 | 0.8913 | 0.9412 | 0.9662 |
| chorus_lift_semitones | -2.0 | 0.0 | 1.0 | 3.0 | 5.0 |
| chord_changes_per_bar | 0.4414 | 0.5465 | 0.6747 | 0.8074 | 0.89 |
| notes_per_active_vocal_bar | 3.6706 | 4.4667 | 5.7114 | 6.8847 | 8.2884 |

## Sections

| Section | p10 | p25 | p50 | p75 | p90 |
|---|---:|---:|---:|---:|---:|
| intro | 8.0 | 10.0 | 17.0 | 21.0 | 29.0 |
| verse | 8.0 | 13.25 | 16.0 | 25.0 | 34.0 |
| chorus | 8.0 | 10.0 | 16.0 | 22.0 | 32.0 |
| interlude | 8.0 | 10.0 | 16.0 | 18.0 | 24.0 |
| bridge | 6.0 | 8.0 | 9.0 | 13.5 | 17.6 |
| outro | 6.6 | 8.0 | 11.0 | 15.0 | 21.0 |
| pre-chorus | 4.0 | 6.0 | 8.0 | 8.0 | 9.0 |

Top forms:

- intro verse chorus interlude verse chorus outro (85)
- intro verse chorus interlude verse chorus interlude verse chorus (57)
- intro verse chorus interlude verse chorus interlude verse chorus outro (45)
- intro verse chorus interlude verse chorus (41)
- intro verse chorus interlude verse chorus interlude (36)
- intro verse chorus interlude verse chorus interlude chorus (17)

## Chords

Chord qualities: m 51384, maj 31399, maj7 5888, m7 5253, 7 3077, 6 979, m7b5 522, sus4 516, 7sus4 174, sus2 165, m6 139, dim 128, aug 110, dim7 96

Top 4-chord changes (semitones from tonic; `m` = minor, `M7` = maj7):

- 0m 5m 0m 5m (380)
- 7m 0m 10 8 (298)
- 5m 0m 5m 0m (290)
- 0m 10 0m 10 (272)
- 0m 10 8 10 (230)
- 10 0m 10 0m (229)
- 0m 10 8 7m (220)
- 0m 5m 10 3 (215)
- 7m 0m 7m 0m (199)
- 0m 8 0m 8 (194)
- 10 8 7m 0m (190)
- 10 8 7 0m (184)

## Vocal note durations (quarter-note beats)

1/2: 217739, 1/4: 103877, 1: 22479, 3/4: 5804, 3/2: 1404, 2: 718, 3: 176, 4: 37

## Instrumental riff shapes (top, by tempo band)

**slow**: `0:1/2 0:1/2` (48); `0:1/2 0:1/2 0:1/2 0:1/2` (39); `7:1/2 7:1/2 7:1/2 7:1/2` (25); `2:1/2 3:1/4 0:1 7:1/4` (21); `2:1/2 3:1/4 0:1/4` (21)

**mid**: `7:1/2 7:1/4 7:1/2 5:1/2 5:1/2 7:1/2 2:1/4 3:1/4 2:1/4 0:1/4` (24); `2:1/2 2:1/2 7:1/2 2:1/2` (18); `10:1/2 0:1/2` (17); `7:1/4 8:1/4 0:1/4 10:1/2 10:1/4 9:1/4` (17); `0:1/2 0:1/2` (16)

**fast**: `4:1 3:1/2 4:3/4 11:1/2 11:1/2 0:1/4` (43); `0:1/2 3:1/2 3:1/4 3:3/4 0:1/2` (30); `7:1/2 7:1/2` (28); `7:1/2 7:1/2 7:1/2 7:1/2 7:1/2 7:1/2 7:1/2 7:1/2` (28); `0:1/2 0:1/2` (22)

## Pitch-class profiles (percent of vocal notes, 0 = tonic)

- **Dm** (35924 notes): 0:17.4, 1:1.6, 2:10.2, 3:14.1, 4:0.3, 5:15.3, 6:0.1, 7:15.0, 8:11.0, 9:0.7, 10:13.5, 11:0.8
- **Am** (36271 notes): 0:22.4, 1:0.8, 2:17.6, 3:14.7, 4:0.1, 5:11.1, 6:0.0, 7:10.8, 8:7.8, 9:0.3, 10:13.9, 11:0.5
- **Em** (37263 notes): 0:18.2, 1:3.6, 2:10.7, 3:17.5, 4:0.7, 5:11.9, 6:0.0, 7:14.0, 8:9.8, 9:0.3, 10:12.9, 11:0.4
- **Gm** (46504 notes): 0:18.7, 1:3.4, 2:11.0, 3:18.0, 4:0.9, 5:15.6, 6:0.0, 7:15.9, 8:5.3, 9:0.5, 10:10.3, 11:0.3
- **Cm** (50979 notes): 0:21.2, 1:1.4, 2:15.4, 3:8.9, 4:0.6, 5:10.1, 6:0.1, 7:14.2, 8:9.9, 9:0.9, 10:15.9, 11:1.4

Read `assets/corpus_profile.json` for the full data, including every key and riff.
