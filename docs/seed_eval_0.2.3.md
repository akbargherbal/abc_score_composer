# Phase 6: do phrase seeds help? (0.2.3)

## Verdict

**Not run in this environment. Seeds stay off by default (`--seeds 0`), and
the flag is not mentioned in `SKILL.md`.** This is the plan's pre-registered
"no benefit shown" branch: without evidence, keep the option but do not make it
default-on and do not spend the mandatory-reading budget on it.

The deterministic work is complete: the bank is imported, the seed path is
optional and bounded, and the tests prove the flag is byte-neutral when absent.
What is missing is the live model A/B, which needs a model harness and at
least three runs per cell. That was not available here.

## Pre-registered design (from the integration plan)

- **Prompts:** at least 10. At least 4 Kurd (8 phrases exist), at least 3
  hijaz/rast, at least 2 nahawand, and 1 bayati (expect no maqam-specific
  seed). Reuse `tests/sample_prompt.txt` and `assets/example_prompt.txt`; add
  the rest. At least half the prompts must contain 8-beat lines, or arm B gets
  no seeds and the test shows nothing.
- **Arms:** (A) 0.2.2 baseline; (B) 0.2.3 with `--seeds 3`. Same model, same
  prompts, at least 3 runs per cell.
- **Record per run:** compile/inspect loops until release; CRAFT flag count at
  release; MAQAM fit; novelty containment; bytes the agent wrote (`fill.json`);
  wall time; tokens if exposed; how many lines actually received a seed.
- **Decision rule:** make seeds default-on only if arm B has fewer CRAFT flags
  or fewer loops on average, **and** no more novelty `close` results than arm
  A, **and** no regression on Kurd prompts. If the benefit shows only on
  nahawand, document it and keep seeds off. If there is no benefit, keep the
  flag but do not mention it in `SKILL.md`.

## Prompts present in this repo

| File | Maqam | 8-beat lines? | Use |
|---|---|---|---|
| `tests/sample_prompt.txt` | Kurd | no (4-bar shatrs) | existing suite |
| `assets/example_prompt.txt` | Kurd | no (4-bar shatrs) | example |
| `tests/prompts/short_kurd.txt` | Kurd | yes | seed smoke test |
| `tests/prompts/short_hijaz.txt` | Hijaz | yes | seed smoke test |
| `tests/prompts/short_bayati.txt` | Bayati | yes | `mode=any` fallback test |

The short prompts exist to exercise the seed path, not to answer Phase 6. A
real evaluation should add the remaining maqam prompts and keep the same
per-run record table.

## Why this matters for the default

The bank is skewed: 45 of 48 phrases are 8-beat, bayati has 1 phrase, and
hijaz/kurd have 8 each from small candidate pools. A 4-bar shatr (16 beats)
gets no seed by design. So even a positive result would likely apply to short
8-beat lines only, not to the common 16-beat line.

## Fingerprint variant decision

The shipped default is **bottom-256** (`assets/corpus_fingerprints.bin`,
630,382 B, stamped threshold `0.08`). It is the recommended balance: the
package grows from 80,391 B to about 700 KB (roughly 8.9x), while the check
runs in about 0.18 s on a 30-bar score and catches the exact, one-bar-varied,
and transposed controls. The `full` variant (1.03 MB) is larger and more
faithful; `k128`/`k64` are smaller but coarser and raise the threshold to
`0.15`. Keep bottom-256 unless the owner wants maximum fidelity or minimum
package size.

## What to do next

1. Add the remaining maqam prompts (Kurd x4, hijaz/rast x3, nahawand x2,
   bayati x1) with at least half containing 8-beat lines.
2. Run arms A and B three times per cell on the same model.
3. Fill in the per-run table and apply the decision rule above.
4. Only then decide whether to mention `--seeds` in `SKILL.md` or change its
   default.
