# Fix plan: abc-score-writer 0.2.3 -> 0.2.4

Audience: the implementing AI agent. Language: English. Base: tag `v0.2.3` (commit `93552b1`; `main` also has the investigation folder at `9e639a4`).
Source of the findings: `investigation/v0.2.3/investigation_report.md`, **re-verified by the owner's planning session**. Only findings that survived that review are in scope here.

## 0. Principle

The owner wants two things: **quality** (an excellent score, not "mediocre slop") and **feasibility** (a ~3000-token score at about 10x thinking cost or less).
Rules for deciding what to change:

1. Fix what is **certain** (reproduced or read in code).
2. Where a problem is certain but the **effect of a remedy on quality is not**, ship **instrumentation and permissions** (a metric, a flag, a sentence saying the model may override). Do **not** ship new musical rules or new default values.
3. Do not touch anything on the watchlist (section 2).

The model's thinking is hidden in these sessions, so nothing may be justified by what an agent said about its own reasoning. Success is measured only by outputs: files, bytes, flags, warnings, test results.

## 1. Scope: issues, ordered by severity, and what ships

| Sev | Issue (confidence) | Work item | Kind of change |
|---|---|---|---|
| 1 | First pass is a template generator; rules ("at most 1 musical patch round", "CRAFT is advisory: do not chase") stop it at first green (80%) | W4 + W5 | text + flags |
| 2 | Skeleton defaults (chord loop, syllable splits, targets) are treated as locks; the lock is textual only (85%) | W4 | text |
| 3 | Durations 5, 9, 10, 11, 13 units at `L:1/16` are not representable in abcjs; compiler never checks (95%+) | W1 | code |
| 4 | `meta.targets` editable without trace; `melisma 1.2` has no corpus basis (95%+) | W3 | code + schema text |
| 5 | `[End]` maps to `verse`, fails `bad_verse_bars`, forces a hand edit, and the score then ends on A instead of Dm (95%+) | W2 | code |
| 6 | Cadence pitch classes and breath pattern identical across sessions (85%) | W5 (metric only) | instrumentation |
| 7 | `fill.json` is 1.3-1.8x the token size of the final `.abc` (90%) | W6 | instrumentation |
| 8 | `novelty_check` is blind to chords/form/other sessions (90%) | W6 | doc line |

## 2. Watchlist: do NOT change in 0.2.4

Leave all of these exactly as they are; they are archived for later releases because confidence is below 67% or evidence is missing:

- The 4/3/3/4 syllable split in `bar_syllable_ranges` (effect on quality unproven).
- The content of `chord_loop()` and the default chords. (Only *permission to override* changes, see W4.)
- CRAFT thresholds, including `verse_register_range_min: 12` in `assets/craft_thresholds.json`, and the "lift 4-7 st" advice.
- Values of `vocal_span`, `chorus_lift`, `call_response`, `max_phrase_seconds`, `maqam_fit`. Only `melisma` is touched (W3).
- Corpus medians in SKILL.md, tempo default 93.
- Adding drums/choir/percussion voices, `%%MIDI` directives, `--no-chords`, quarter tones.
- Any claim that varied chords, a different split, or hand-composition raises quality.

## 3. Global constraints

- Python stdlib only. No new runtime dependency. `node`/`abcjs` may be used only in an **optional** test that skips when absent (env var `ABCJS_DIR`).
- Complete code, no stubs. Keep compile output deterministic.
- Docs: **no new files**. Allowed edits: `SKILL.md` (budget below), `references/blueprint_schema.md`, `docs/novelty_limits_0.2.3.md` (2 lines), `CHANGELOG.md` (one `0.2.4` entry), `VERSION`. Touch `README.md` only to correct the documented test count.
- SKILL.md is read on every run: net growth <= **600 bytes**. Remove words where you add words.
- One commit per work item, message `0.2.4 Wn: <what>`. Run `python3 -m unittest discover -s tests -p 'test_*.py'` (with `ABC2MIDI=$(which abc2midi)`; `apt-get install abcmidi` if missing) before and after each item; do not proceed on red.
- Release packaging: follow exactly what commit `93552b1` did for `dist/` (inspect `git show --stat 93552b1`), producing `dist/abc-score-writer-0.2.4.{skill,zip}`.

## 4. Work items (implement in this order)

### W2. `[End]` and lyric-less sections (smallest, unblocks every run)

Files: `scripts/intake_lyrics.py` (`KIND_MAP` ~L68, `normalize_kind` ~L237).

- Add `"end"`, `"the end"`, `"finale"` -> `"outro"` to `KIND_MAP`.
- A section with **no lyric lines** whose name is unknown must not default to `verse` (the compiler then demands whole bayts). Make it `outro` if it is the last section, otherwise `interlude`. Sections with lyric lines keep the current default.
- Confirm `build_skeleton` then sets the final bar chord to the tonic (`Dm` in D minor): it already does so for `kind == "outro"` (~L440-445).

Tests (add to `tests/test_integration.py` or a new `tests/test_intake_kinds.py`):
- Prompt containing `[End]` (and `[Fin]` as an unknown last section with no lines) -> `kind == "outro"`; skeleton compiles with **no manual edit**; last vocal bar chord is the tonic.
- A prompt with `[Verse 1]` unchanged -> still `verse`.
- Existing tests unchanged.

Acceptance: the session prompt (if the owner supplied `tests/prompts/suno_nahawand_28.txt`; otherwise `tests/sample_prompt.txt` plus an appended `[End]`) goes intake -> skeleton -> compile with zero hand edits and ends on the tonic chord.

### W1. Representable durations (consumer parity)

Files: `scripts/abc_common.py` (new shared helper), `scripts/compile_abc.py` (`render_events` ~L846-865 and the grid check ~L805-818), `scripts/validate_and_inspect.py` (guard).

Facts (verified on abcjs 6.7.2): at `L:1/16` the units **1,2,3,4,6,7,8,12,14,15 pass; 5,9,10,11,13 warn** `Duration not representable`. Values >= a whole note are not checked by abcjs. The accepted set below a whole note is `base * (2 - 2^-j)` for `base = 2^-k`, `j = 0..5` (see `node_modules/abcjs/src/parse/abc_parse_settings.js:114-123`). Test **by fraction of a whole note**, never by a unit list, because the grid can be `L:1/32`.

Implement:
1. `abc_common.representable(frac_of_whole: Fraction) -> bool` and `abc_common.split_duration(frac) -> list[Fraction]` (greedy, largest representable part first; e.g. at 1/16: 5 -> 4+1, 9 -> 8+1, 10 -> 8+2, 11 -> 8+3, 13 -> 12+1). Values >= 1 whole pass through unchanged.
2. In `render_events`: a non-representable **note** is emitted as tied parts (`F8-F2`); a non-representable **rest** as consecutive rests. The tie joins notes of the same syllable; syllable/onset bookkeeping (`w_counter`, `validation_lines`) must count it as **one** event.
3. The metrics must not change because of the split. Verify how `abc_common`/`craft_checks`/`validate_and_inspect` parse ties: tied continuations must be merged so **onset count, melisma rate, long-note share and rhythm patterns are identical with and without the split**. (Evidence: in session P a hand split of 2.5-beat values raised melisma 1.14 -> 1.20 purely by adding onsets. That artifact must not exist.) Merge consecutive rests for rest-share metrics.
4. Guard in `validate_and_inspect.py`: independently scan the final ABC for non-representable durations using the same helper and report them as a hard failure line `DURATION unrepresentable: <token>`. It should never fire after step 2; it protects against regressions.
5. SKILL.md release criteria: replace the wording that makes `abc2midi` the only gate with "abc2midi **and** the representability guard report nothing". One short clause.

Tests:
- Unit: every value 1..31 units at `L:1/16` and `L:1/32` -> `split_duration` parts sum exactly to the input and every part is representable.
- Compile a Blueprint using 2.5-beat notes and rests: output has no `10`, `5`, `9`, `11`, `13` tokens at `L:1/16`; bar sums intact; abc2midi 0 warnings.
- Metrics parity: compile the *same* Blueprint with the splitter disabled (temporary monkeypatch) and enabled, and parse both with the in-repo parser. Onset count, melisma rate and long-note share must be equal.
- Optional (skip if `ABCJS_DIR` unset): run `abcjs.parseOnly` over the compiled ABC and assert zero `representable` warnings.

Acceptance: a fill with 2.5-beat values compiles, passes abc2midi, passes the guard, and produces zero abcjs warnings (when abcjs is available).

### W3. Targets: provenance and tamper evidence

Files: `scripts/abc_common.py` (single `DEFAULT_TARGETS` constant), `scripts/intake_lyrics.py` (~L394-401, use the constant), `scripts/validate_and_inspect.py` (~L438-470), `references/blueprint_schema.md` (~L30).

- **Remove `melisma` from the default targets.** The metric stays computed and visible as information; it must no longer produce a `melisma < target` flag unless the author explicitly sets it. Reason: corpus has no lyrics (`references/corpus.md:3`); the number was invented.
- Inspector: compare `meta.targets` read from the report with `DEFAULT_TARGETS`; for every key that is changed or added, print one flag line `TARGET edited: vocal_span 20 -> 22` and include `targets_edited` in `--json`. No other behaviour change; edited targets are still honoured.
- `blueprint_schema.md`: one compact table stating, per target, **cap or goal** (`vocal_span`, `max_phrase_seconds` are caps; `chorus_lift`, `call_response`, `maqam_fit` are goals), and **provenance**. Check `references/corpus.md` yourself: record `vocal_span 20` = corpus p90, `chorus_lift 3` = corpus p75, and label any target with no corpus baseline as `heuristic`. State: "do not edit targets; if one cannot be met, report it."

Tests: default compile has no `melisma` target and no melisma flag; editing `vocal_span` to 22 yields the `TARGET edited` flag and `targets_edited` in JSON; unedited run yields none.

### W6. Cost and blind-spot instrumentation

Files: `scripts/compile_abc.py` (report), `scripts/validate_and_inspect.py`, `scripts/measure_footprint.py`, `docs/novelty_limits_0.2.3.md`.

- Compile report (`*.report.json` and `--json`) gains `fill_bytes`, `abc_bytes`, `fill_to_abc_ratio`. **Do not** add these to the one-line compact card (keep the card size); show them in `--verbose` only. Purpose: thinking text is hidden in these exports, so the fill/ABC ratio is the only authoring-cost proxy that is measurable from outside.
- `measure_footprint.py`: add the ratio row for the shipped example so regressions are visible.
- `docs/novelty_limits_0.2.3.md`: add two lines: NOVELTY compares the Vocal voice to the corpus only; it does not see chord symbols, the Ins voice, form, or other sessions, so two scores can share backing and structure while NOVELTY reports `none`.

Tests: report contains the three fields and they are consistent with file sizes; compact card byte length for the example unchanged.

### W5. Template and sameness signals (flags only)

Files: `scripts/craft_checks.py`, `assets/craft_thresholds.json`, `scripts/validate_and_inspect.py`.

This is **instrumentation, not a quality claim**. The metrics measure variety; they do not prove excellence. Never use them as a pass/fail gate; they only produce flags that SKILL.md (W4) tells the author to address.

Metrics, computed on the final ABC:
1. `rhythm_variety` per section kind (verse, chorus) = distinct Vocal **bar rhythm patterns** (the sequence of note and rest durations in a bar, pitch ignored) divided by the number of vocal bars in that kind.
2. `contour_overlap` per section kind = mean pairwise overlap of **contour 3-grams** (up/down/same by interval sign) between lines of the same kind.
3. `cadence_variety` (information only, no flag) = distinct line-final degrees among verse lines, and the share of lines ending on the most common degree. Cadence rule effects are on the watchlist, so this stays informational.
4. `ins_variety` (information only) = distinct Ins bar patterns per section kind.
5. `chord_variety` (information only) = distinct chords and chord changes per bar.

Flags (provisional thresholds in `craft_thresholds.json`, marked `"provisional": true` like the existing ones):
- `rhythm_variety_min: 0.20`, `contour_overlap_max: 0.80`.
- Calibration data from the investigation (n=4, weak): verse rhythm patterns per 48 bars were S1 = 6 (0.125), P1 = 14, P2 = 17, S2 = 28; mean contour overlap S1 = 0.857, P1 = 0.76, P2 = 0.606, S2 = 0.682. The thresholds above flag only S1-like template output. If the owner supplied the four `.abc` files (`investigation/v0.2.3/artifacts/`), **recompute these numbers with your implementation and adjust the thresholds so S1 flags and S2 does not**; if the files are absent, build one formula-generated fill and one varied fill as synthetic fixtures, set the thresholds conservatively, and mark them `"calibration": "uncalibrated"`.
- Flag text names the **lines** involved (e.g. `verse_1.L1..L4 share rhythm patterns`) so a fix can touch only those lines.

Tests: the template fixture flags; the varied fixture does not; the example shipped in `assets/` does not flag (if it does, adjust fixtures/thresholds, not the example); metrics 3-5 appear in `--json` but never in flags.

### W4. SKILL.md: defaults are overridable, and iteration is bounded by flags (last; depends on W1, W3, W5 names)

File: `SKILL.md` only (+ one sentence in `references/blueprint_schema.md` if wording must match). Net growth <= 600 bytes.

Edits:
1. **Loop paragraph (~L22-24).** Replace "At most 1 musical patch round... stop and report" with: after the first clean compile, address every **variety flag** (W5) and `TARGET edited`/`DURATION` flag by editing **only the flagged lines/bars**; at most **2** such rounds; a round that touches unflagged bars does not count as cheap, so avoid it. Authoring fixes remain exempt. Mark the limit as provisional in the CHANGELOG, not in SKILL.md.
2. **Fill rule (~L30-32).** Replace "Do not retype `ch` or `syl`" with: the skeleton's `ch`, `syl` and `meta.targets` are **defaults**. Override `ch` or `syl` per bar in the fill when the words or the cadence call for it (the schema allows explicit `ch`/`syl`; see `blueprint_schema.md` bar-level fields). Do not edit `meta.targets`.
3. **Authoring.** Add one sentence: write each line's rhythm and contour for **its own words**; do not generate the fill by looping one template over lines or sections.
4. **Release (~L93-94).** Keep "CRAFT is advisory" for register/long-notes/cadence flags (their thresholds are provisional), but add: variety flags from W5 must be fixed or explicitly reported as accepted, and the compile must show no `TARGET edited` unless the owner asked.
5. Keep "Never hand-write ABC" unchanged.
6. Do not add the corpus targets or any new musical rule. Do not mention drums, choir, or chord-track suppression.

Before editing, confirm by a test that a fill with explicit per-bar `ch` and `syl` overrides actually compiles (the schema text says yes; if the compiler rejects it, fix the compiler to match the schema and add the test, since the SKILL.md sentence depends on it).

Acceptance: `wc -c SKILL.md` grows by <= 600 bytes; every statement in SKILL.md about flags matches a flag the code actually emits.

## 5. Release steps

1. `VERSION` -> `0.2.4`. CHANGELOG `0.2.4`: Fixed (W1, W2), Changed (W3, W4), Added (W5, W6), plus a "Monitored, not changed" list copied from section 2.
2. README: change only the stated test count if it changed.
3. Build `dist/` artifacts the same way as `93552b1`. Tag `v0.2.4`.

## 6. End-to-end verification (observable results only)

Run on the session prompt if supplied, else on `tests/sample_prompt.txt` with `[End]` appended. Report these in the final message, with numbers:

| Check | Target |
|---|---|
| Hand edits needed from intake to a green compile | 0 |
| abc2midi warnings / representability guard hits | 0 / 0 |
| abcjs `Duration not representable` warnings (if abcjs available) | 0 |
| Onset/melisma parity with and without tie-splitting | identical |
| Last bar chord of the skeleton | tonic |
| `melisma` flag on a default compile | absent |
| Compact card size for the shipped example | unchanged |
| `SKILL.md` growth | <= 600 bytes |
| Full unit-test suite | green |

## 7. Inputs the owner may supply (the plan degrades gracefully without them)

- `tests/prompts/suno_nahawand_28.txt`: the exact prompt of both sessions (for the end-to-end run).
- `investigation/v0.2.3/artifacts/`: `P_v1.abc`, `P_v2.abc`, `song.abc` (S1), `song2.abc` (S2) (for W5 calibration).
- Optional: a checkout of `abc2audio` with `npm install` (for the optional abcjs test).

If any is missing, say so in the final message and use the fallback written in the relevant work item; do not invent substitutes silently.

## 8. Definition of done

All eight rows of section 6 met; every commit green; watchlist items untouched (`git diff v0.2.3 -- assets/craft_thresholds.json` shows only the two new provisional keys; `chord_loop` and `bar_syllable_ranges` are byte-identical); final message lists any deviation from this plan and why.
