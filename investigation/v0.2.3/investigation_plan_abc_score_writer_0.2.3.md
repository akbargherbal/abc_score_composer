# Investigation Plan: why abc-score-writer v0.2.3 produced mediocre, near-identical scores

**Audience:** an AI agent that has never seen these sessions.
**Your job:** study two session transcripts and write ONE report on what happened and why.
**You do not fix anything.** Fixing is a later step, done from your report.

## 1. Goal and the two success criteria

The skill (`github.com/akbargherbal/abc_score_composer`, tag `v0.2.3`) should deliver:

1. **Quality.** An excellent score, not a scale pattern fitted to words.
2. **Feasibility (cost).** A ~3000-token score should cost at most ~10x that in thinking
   (~30k tokens), less if possible. Define `R = (thinking + non-file output tokens) / tokens(final .abc)`
   and report R per phase and per session.

**The owner's hypothesis:** changes in 0.2.x that were meant to *support* the agent now *resist* it.
The agent ends up fighting the tooling instead of using it. Test this honestly. It may be partly wrong.

## 2. Inputs

| Item | Detail |
|---|---|
| Skill repo | `git clone https://github.com/akbargherbal/abc_score_composer.git && git checkout v0.2.3` |
| Sessions | `orange_conversations-000.zip`: a zip archive containing a JSON file that holds **both** sessions. Unzip it, open the JSON file, and split the two conversations. |
| Session P | Title "كتابة سكور abc لقصيدة عربية", first message 06:51 UTC (10 messages in the slim copy the planner saw) |
| Session S | Title "كتابة سكور abc لأغنية عربية", first message 06:36 UTC (12 messages in the slim copy the planner saw) |
| Same prompt | The first human message in both is an identical Arabic Suno-style prompt: Nahawand verses, Hijaz chorus, 28 lyric lines, symphonic metal / Khaliji / tarab tags. |
| Tooling | `python3`, and `abcmidi` (`apt-get install abcmidi`). `abc2audio` is what the owner actually uses; try to obtain it, otherwise say so. |

**Critical caveat.** The planner only saw earlier *slim* exports, which **hide every tool call and its result**
(they show only "This block is not supported on your current device yet"). Check first whether `orange_conversations-000.zip`
contains tool blocks (and thinking). If it does not, you cannot see which files the agent read, the `fill.json` it wrote,
the compiler/inspector output, or its thinking.

- If tool blocks are missing, ask the owner for full transcripts, the final `.abc` and `fill.json` files from **both sessions
  (first version and rewrite)**, and any `*.report.json`. Ask for these before starting analysis. If the zip already has tool blocks, skip this.
- If they are unavailable, reconstruct by reproduction (section 4, W3) and say clearly which findings
  rest on reconstruction rather than on the record.

## 3. Evidence already gathered (verify, do not re-derive)

Tags: **[R]** reproduced by the planner by running the tool, **[T]** visible in the transcripts,
**[A]** the agent's own testimony. Treat **[A]** as a hypothesis, never as proof. Models rationalise after the fact.

**Symptoms (owner, [T]):** first versions of both sessions were "very mediocre"; the two sessions' scores
are strikingly similar; rewrites came after the owner complained. Owner's verdict on Session S's rewrite: "better than your previous output."
No verdict recorded for Session P's rewrite (ask).

**Wall times from timestamps [T]:** first pass P 1m51s, S 2m12s. Rewrite P 3m17s, S 4m26s.
(User turn to assistant turn, includes tool time. The first pass is fast; the quality path is slower.)

**Reproduced [R]** by running `intake_lyrics.py --in prompt.txt -o intake.json --skeleton skel.json`
on the shared prompt:
- Output: `SECTIONS 7 LINES 28 BAYTS 14 SYLLABLES 399 EST_BARS 116`, `tempo=93`, key `Dm`.
  Both sessions reported 116 bars, 93 BPM, D minor, so **the macro-structure is fully determined by intake, not by the model.**
  The prompt contains no BPM, so the tempo is the corpus median `p50=93`.
- Every bar's chord comes from a fixed loop `Dm Gm Bb A` (`chord_loop()`, `intake_lyrics.py` ~L355). The skeleton also carries
  default `meta.targets` (melisma 1.2, vocal_span 20, chorus_lift 3, call_response 0.6, ...).
- A 14-syllable line is split **4/3/3/4** across its 4 bars (15 -> 4/4/3/4, 16 -> 4/4/4/4). Per SKILL.md rule 3 the sadr
  ends with `r:1.5` and the ajuz with `r:2`, so the last bar of a line holds 4 syllables in ~2-2.5 beats.
  (Derived; confirm in the real fills.)
- `[End]` becomes a section of `kind=verse` with 4 bars and no lyrics, which conflicts with the "whole bayts" rule.
  Both agents hit this (S says it had to change the kind by hand).
- `compile_abc.py` ~L805-818 checks only that durations land on an integer grid (`L:1/16`). **There is no check that a
  duration is writable as a single note/rest.** 10 units (2.5 beats) passes; `grep` finds no representability handling in `scripts/`.
- The delivered header has **no `%%MIDI` directives at all** (no program, drum, or gchord), but chord symbols sit on the Vocal voice.

**Both sessions hit identical `abc2audio` warnings [T]:** `Duration not representable: z10 / F10 / G10`
(27 warnings in P, 14 in S). `abc2midi` passed both. Neither agent could run `abc2audio`. The owner pasted the warnings
and the agent patched them.

**Agent testimony [A]:**
- P, turn 1 and 7: "I used my one musical patch round and did not chase the two flags"; "the tool's own
  'register flat' flag was pointing at this, and I chose not to chase it"; "I generated the melody from templates".
- S, turn 7 and 11 (the owner asked for a root-cause list): the skeleton fixes structure first; fixed chord loop plus
  "fill only voc/ins, do not retype ch or syl" discouraged change; release criteria are structural only and CRAFT is
  "advisory, do not chase"; intake gives no usable prosody weights (long vowels split into separate tokens like `عَ`+`ارِ`);
  the example/fill format favours uniform `(x:.5 y:.5)` cells; corpus-median flags pull toward average; the two voices cannot express
  drums/choir/backing vocals/quarter-tones; validator looser than `abc2audio`; `[End]` handling.
- S rewrite **overrode the skeleton** (re-split syllables to 4/4/4/2, wrote its own chords incl. C, D, Eb, ended on Dm) and the
  compiler accepted it. The owner then said "better". This is the closest thing to a natural experiment you have.

**Anomalies to explain:**
- A1. S cites a vocal-span target of **22**; the default skeleton says **20**; P cites 20. Did the S agent edit `meta.targets`?
- A2. The owner heard "the drummer playing his own idea" in S. S's agent answered that the *renderer interprets the style prompt*.
  That is implausible, since the renderer only sees the ABC file. Find the real cause (see W5-h).
- A3. S's rewrite scored the vocal at 1.88 melisma/syllable on a first try, then cut to 1.37 as "too busy for solemn".
  Target is 1.2. Was a tool target or musical judgment steering?

## 4. Workstreams

Do them in order. Keep notes as you go, but only the final report is delivered.

### W1. Timeline per session
For each session list, in order: files read (SKILL.md, which references, which assets), each tool call and its purpose,
every flag/error the inspector printed, every decision the agent made about it, and each user turn.
Mark the point where the agent decided the work was "done". For each CRAFT/FLAG shown, record: dismissed / acted on / unseen.

### W2. Cost accounting
Per session and per phase (read skill, intake, write fill, compile/inspect loops, patches, rewrite):
tokens read from skill files before first compose, thinking tokens (or best proxy if hidden, labelled as estimate),
output tokens, tool-call count, bytes of `fill.json` authored, tokens of the final `.abc`, and `R`.
Compare the cheap path (first pass) with the rewrite path. State what the cheap path actually bought.

### W3. Cross-session similarity, measured not eyeballed
Using the final `.abc` of each session (first versions, and rewrites if you have them) plus `assets/example_song.abc`
and `assets/example_fill.json`:
- Compute vocal interval-contour n-gram overlap and rhythm-pattern overlap between P and S, using the
  repo's own tokenizer in `scripts/novelty_check.py` (interval/rhythm classes) so numbers are comparable to its `0.08` threshold.
- Separate three sources of similarity: (a) forced by intake (bars, chords, tempo, key, syllable splits),
  (b) induced by instructions or shipped examples (cadence degrees, breath rests, the `R1`/`(1:.5 b2:.5)` motif style),
  (c) genuinely model-chosen. Report what fraction each explains, and how you measured it.
- Inside each song: number of distinct bar-rhythm patterns per section, contour distinctness among the 10 verse lines,
  chord diversity, instrument-voice pattern diversity. First version vs rewrite.
- Check whether the agents read the shipped examples (`assets/example_*`) and whether their fills echo them.
- If fills are missing, regenerate a plausible fill from the agents' own summaries is NOT acceptable; report the gap.

### W4. Instruction audit
Go through `SKILL.md`, `references/blueprint_schema.md`, `references/vocal_craft.md`, `references/corpus.md`,
`references/maqam.md` line by line. Classify each directive as **Helps / Neutral / Obstructs / Contradicts another rule**,
with a transcript quote or a code reference as evidence. Start with these suspects, then add your own:

1. "At most **1** musical patch round" and "do not chase" CRAFT flags / release criteria that are structural only.
2. "Fill only `voc` and `ins`. Do not retype `ch` or `syl`." (the compiler allows overrides; the text forbids them)
3. "Never hand-write ABC", whatever it means for the model's room to compose.
4. The five prosody rules: fixed 4-bar shatr / 8-bar bayt, fixed cadence degrees, fixed breath constants, "lift ajuz 4-7 semitones".
5. Corpus medians and `meta.targets` as goals. `assets/PROVENANCE.md` says the corpus is AI-generated (Suno, transcribed by SheetSage2),
   so matching its median may mean matching mediocre output by construction.
6. The CRAFT thresholds are calibrated on **one** good score and three bad ones (`assets/craft_thresholds.json`). Judge whether
   that can support a pass/fail signal at all.
7. The tension between "compose a sung bayt, not a scale walked up and down" and a pipeline that fixes everything before the model composes.

### W5. Tool and pipeline defects
For each, give a reproduction command, observed vs expected, severity, and who it affects (quality, cost, or correctness):

- **a. Representable durations.** Determine empirically which unit counts `abc2audio` accepts as one glyph (hypothesis: single, dotted,
  double-dotted forms; 5, 9, 10, 11, 13 units fail). Show that `compile_abc.py` and `abc2midi` both let them through.
  Establish which tool is the owner's real consumer and whether validation should match it.
- **b. Syllable-to-bar splitting** (4/3/3/4) versus the breath rests: quantify beats available per syllable in each bar.
- **c. Fixed chord loop** and its audible effect (chord symbols are rendered by the player, see h).
- **d. `[End]` section** typing and the whole-bayt check.
- **e. Intro with lyrics.** S says "the tool requires every lyric line be covered". Find the rule and the cost of it.
- **f. Syllable tokens.** Inspect `intake.json` line records. Do they carry long/short or weight information? Is the `عَ`+`ارِ`
  splitting claim true? The poem appears to be classical-metre verse; note what metrical information could exist but is dropped (observe only).
- **g. Style-prompt coverage.** List every element of the prompt the skill cannot express (drums, choir, backing vocals, quarter-tones,
  per-section maqam switching over a fixed chord grid, instrumental intro) and what the agents did with each.
- **h. The drummer (A2).** Run `abc2midi` on the delivered `.abc`, list MIDI tracks/channels, check for percussion on channel 10
  and for auto-accompaniment generated from chord symbols with no `%%MIDI` directives. Explain what the owner heard.
  If the cause is default chord accompaniment driven by the fixed loop, say so.
- **i. Target provenance** (A1, A3): where each `meta.targets` value comes from, who may edit it, and whether tools penalise edits.

### W6. Natural experiment: first version vs rewrite
In S the agent left the skeleton and the owner approved; in P it stayed closer to it (verify). Compare the two rewrites against
their first versions on the W3 metrics and the inspector's own metrics. Say what the rewrite changed that the first pass could not
have changed under the instructions as written. Keep the owner's verdicts as ground truth, and do not substitute your own taste.

## 5. Evidence rules

- Every claim cites one of: session + message index, `file:line`, or a command and its output.
- Separate **Observed**, **Inferred**, **Agent testimony**. Do not promote testimony to fact without a test.
- Say "inconclusive" when it is. A short honest report beats a confident wrong one.
- Work in a copy of the repo. Do not edit the skill. Do not listen to audio.

## 6. Deliverable

One file, `investigation_report.md`, with:

1. **Executive summary** (10 lines max): the top causes of mediocrity and of the near-identical output, each with a confidence level.
2. **Timeline** per session (compact table).
3. **Cost table** with `R` per phase and per session, and a statement of how far each figure is measured or estimated.
4. **Similarity analysis** with the three-way attribution from W3.
5. **Instruction audit table** (W4) and **defect list** (W5), each item with evidence and severity.
6. **Hypothesis verdicts** for H1-H8 below: Confirmed / Refuted / Inconclusive, with the deciding evidence.
7. **Ranked recommendations**: each with expected quality gain, expected cost change (tokens), effort, and risk. Do not implement.
8. **Open questions for the owner.**

### Hypotheses to rule on

- **H1.** Release criteria and the one-round limit make the agent stop at the first structurally-green result.
- **H2.** The skeleton (fixed splits, fixed chords) plus "do not retype" removes the agent's room to compose; the compiler itself does not forbid overrides.
- **H3.** Corpus-median targets pull output toward an average that is mediocre by construction.
- **H4.** Shipped examples and the motif grammar anchor all runs to the same rhythmic cells.
- **H5.** Fixed prosody constants explain most cross-session similarity.
- **H6.** Intake prosody data is too weak to set text rhythmically (no long/short weighting).
- **H7.** Validator and consumer disagree (`abc2midi` vs `abc2audio`), costing the owner a debug round in every session.
- **H8.** The agent composes the whole first fill in one pass from a formula because nothing in the workflow asks for line-level composition.

## 7. Open items to ask the owner before starting

1. Confirm whether the zip has tool blocks and thinking; if not, full transcripts and every `.abc` / `fill.json` / `report.json` from both sessions.
2. Verdict on Session P's rewrite (`ghada_taawiyan_v2.abc`).
3. Which program renders the audio (`abc2audio` version/source) and what, if anything, sits downstream (the Suno-style prompt suggests a later AI-audio step).
4. Were any `meta.targets` edited by hand in either session (A1)?
