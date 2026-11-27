#!/usr/bin/env python3
"""0.2.4 W1: durations abcjs can draw, split without changing any metric."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from fractions import Fraction

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(BASE, "scripts")
ASSETS = os.path.join(BASE, "assets")
sys.path.insert(0, SCRIPTS)

import abc_common  # noqa: E402
import compile_abc  # noqa: E402
import validate_and_inspect  # noqa: E402
from abc_common import (  # noqa: E402
    parse_abc, representable, scan_unrepresentable, split_duration,
)


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def blueprint_with_25_beats():
    """The shipped example with 2.5-beat notes and rests in three verse bars."""
    skeleton = load(os.path.join(ASSETS, "example_blueprint_skeleton.json"))
    fill = load(os.path.join(ASSETS, "example_fill.json"))
    rows = fill["fill"]["verse_1"]
    rows[0] = ["1:2.5 b2:.5 1:.5 b2:.5", "rest"]
    rows[1] = ["b3:.5 1:.5 b7-:.25 b2:.25 r:2.5", "1:4"]
    rows[2] = ["b7-:1 (1:.5 b7-:.5) (b2:.5 1:.5) b7-:1", "r:2.5 b7-:1.5"]
    return compile_abc.merge_fill(skeleton, fill)


def compile_it(bp):
    intake = load(os.path.join(ASSETS, "example_intake.json"))
    res = compile_abc.compile_blueprint(bp, intake=intake, strict=True)
    assert res["ok"], res.get("errors")
    return res


class RepresentableUnitTests(unittest.TestCase):
    def test_abcjs_facts_at_sixteenth(self):
        bad = [u for u in range(1, 16) if not representable(Fraction(u, 16))]
        self.assertEqual(bad, [5, 9, 10, 11, 13])

    def test_whole_note_or_longer_passes_through(self):
        for u in (16, 17, 20, 24, 31, 32, 48):
            self.assertTrue(representable(Fraction(u, 16)))
            self.assertEqual(split_duration(Fraction(u, 16)), [Fraction(u, 16)])

    def test_documented_splits(self):
        want = {5: [4, 1], 9: [8, 1], 10: [8, 2], 11: [8, 3], 13: [12, 1]}
        for u, parts in want.items():
            got = [int(p * 16) for p in split_duration(Fraction(u, 16))]
            self.assertEqual(got, parts, u)

    def test_every_unit_1_to_31_splits_exactly(self):
        for den in (16, 32):
            for u in range(1, 32):
                frac = Fraction(u, den)
                parts = split_duration(frac)
                self.assertEqual(sum(parts), frac, (den, u))
                for part in parts:
                    self.assertTrue(representable(part), (den, u, part))
                self.assertEqual(parts, sorted(parts, reverse=True), (den, u))

    def test_scan_finds_only_bad_tokens(self):
        abc = 'X:1\nM:4/4\nL:1/16\nK:Dm\nV: Vocal\n"Dm"D10 z5 F8-F2 z6|\nw:x\n'
        got = [d["token"] for d in scan_unrepresentable(abc)]
        self.assertEqual(got, ["D10", "z5"])
        abc32 = abc.replace("L:1/16", "L:1/32")
        got32 = [d["token"] for d in scan_unrepresentable(abc32)]
        self.assertEqual(got32, ["D10", "z5"])  # 10/32 and 5/32 are not valid either
        self.assertEqual(scan_unrepresentable(
            'X:1\nM:4/4\nL:1/32\nK:Dm\nV: Vocal\nD6 z12 D24|\n'), [])


class CompilerSplitTests(unittest.TestCase):
    def test_no_unrepresentable_tokens_and_bars_sum(self):
        res = compile_it(blueprint_with_25_beats())
        abc = res["abc"]
        self.assertIn("L:1/16", abc)
        body = [l for l in abc.splitlines()
                if l and not re.match(r"^[A-Za-z]:", l) and not l.startswith("%")]
        durations = re.findall(r"[A-Gz][,']*(\d+)", "\n".join(body).replace('"', " "))
        for bad in ("5", "9", "10", "11", "13"):
            self.assertNotIn(bad, durations)
        self.assertIn("-", abc)  # tied parts exist
        self.assertEqual(scan_unrepresentable(abc), [])
        parsed = parse_abc(abc, is_text=True)
        for voice, bars in parsed["voices"].items():
            for i, bar in enumerate(bars):
                self.assertTrue(bar.get("sum_ok", True), (voice, i))

    def test_abc2midi_zero_warnings(self):
        binary = validate_and_inspect.find_abc2midi(os.environ.get("ABC2MIDI"))
        if not binary:
            self.skipTest("abc2midi not available")
        res = compile_it(blueprint_with_25_beats())
        tmp = tempfile.mkdtemp(prefix="abc_rep_")
        path = os.path.join(tmp, "song.abc")
        with open(path, "w", encoding="utf-8") as f:
            f.write(res["abc"])
        midi = validate_and_inspect.run_abc2midi(binary, path)
        self.assertEqual(midi.get("errors"), [])
        self.assertEqual(midi.get("warnings"), [])

    def _metrics(self, res, with_report):
        tmp = tempfile.mkdtemp(prefix="abc_par_")
        abc = os.path.join(tmp, "song.abc")
        val = os.path.join(tmp, "song.validation.abc")
        rep = os.path.join(tmp, "song.report.json")
        with open(abc, "w", encoding="utf-8") as f:
            f.write(res["abc"])
        with open(val, "w", encoding="utf-8") as f:
            f.write(res["validation_abc"])
        with open(rep, "w", encoding="utf-8") as f:
            json.dump(res["report"], f)
        profile = os.path.join(ASSETS, "corpus_profile.json")
        m = validate_and_inspect.build_report(
            abc, val, rep if with_report else None, profile, None)
        return m

    def test_metrics_parity_with_and_without_split(self):
        bp = blueprint_with_25_beats()
        split = compile_it(bp)
        original = compile_abc.split_duration
        compile_abc.split_duration = lambda frac: [Fraction(frac)]
        try:
            plain = compile_it(bp)
        finally:
            compile_abc.split_duration = original
        # The monkeypatch really disabled the splitter.
        self.assertNotEqual(split["abc"], plain["abc"])
        self.assertTrue(scan_unrepresentable(plain["abc"]))
        self.assertEqual(scan_unrepresentable(split["abc"]), [])

        for with_report in (True, False):
            a = self._metrics(split, with_report)
            b = self._metrics(plain, with_report)
            self.assertEqual(a["vocal_notes"], b["vocal_notes"])
            self.assertEqual(a["ins_notes"], b["ins_notes"])
            self.assertEqual(a["onsets_per_beat"], b["onsets_per_beat"])
            self.assertEqual(a["rest_ratio"], b["rest_ratio"])
            self.assertEqual(a["dominant_duration_share"], b["dominant_duration_share"])
            self.assertIsNotNone(a["melisma"])
            self.assertEqual(a["melisma"]["rate"], b["melisma"]["rate"])
            self.assertEqual(a["craft"]["metrics"]["long_note_share"],
                             b["craft"]["metrics"]["long_note_share"])
            self.assertEqual(a["craft"]["metrics"]["breath_misses"],
                             b["craft"]["metrics"]["breath_misses"])
            self.assertEqual(a["longest_vocal_run"], b["longest_vocal_run"])

        # Event lists agree exactly after the parser merges ties and rests.
        pa = parse_abc(split["abc"], is_text=True)
        pb = parse_abc(plain["abc"], is_text=True)
        for voice in pa["voices"]:
            ea = [(e["type"], e.get("midi"), e["dur"])
                  for b in pa["voices"][voice] for e in b["events"]]
            eb = [(e["type"], e.get("midi"), e["dur"])
                  for b in pb["voices"][voice] for e in b["events"]]
            self.assertEqual(ea, eb, voice)

    def test_inspector_guard_reports_unrepresentable(self):
        bp = blueprint_with_25_beats()
        original = compile_abc.split_duration
        compile_abc.split_duration = lambda frac: [Fraction(frac)]
        try:
            plain = compile_it(bp)
        finally:
            compile_abc.split_duration = original
        m = self._metrics(plain, True)
        self.assertFalse(m["ok"])
        self.assertTrue(any(e.startswith("DURATION unrepresentable: ")
                            for e in m["errors"]), m["errors"])
        clean = self._metrics(compile_it(bp), True)
        self.assertEqual(clean["unrepresentable"], [])
        self.assertFalse(any(e.startswith("DURATION") for e in clean["errors"]))


class AbcjsOptionalTests(unittest.TestCase):
    def test_abcjs_reports_no_representable_warnings(self):
        abcjs_dir = os.environ.get("ABCJS_DIR")
        if not abcjs_dir or not shutil.which("node"):
            self.skipTest("ABCJS_DIR unset or node missing")
        res = compile_it(blueprint_with_25_beats())
        tmp = tempfile.mkdtemp(prefix="abc_js_")
        path = os.path.join(tmp, "song.abc")
        with open(path, "w", encoding="utf-8") as f:
            f.write(res["abc"])
        js = (
            "const fs=require('fs');"
            "const abcjs=require(process.argv[1]);"
            "const t=abcjs.parseOnly(fs.readFileSync(process.argv[2],'utf8'));"
            "const w=[];t.forEach(x=>(x.warnings||[]).forEach(s=>w.push(String(s))));"
            "console.log(JSON.stringify(w));"
        )
        p = subprocess.run(["node", "-e", js, abcjs_dir, path],
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        warnings = json.loads(p.stdout.strip().splitlines()[-1])
        self.assertEqual([w for w in warnings if "representable" in w.lower()], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
