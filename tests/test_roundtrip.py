#!/usr/bin/env python3
"""Deterministic round-trip tests for the abc-score-writer tools.

Run from the skill directory:
    python3 tests/test_roundtrip.py

abc2midi is optional for the compiler tests but required for the full
validation test.  Set ABC2MIDI or put abc2midi on PATH.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(BASE, "scripts")
ASSETS = os.path.join(BASE, "assets")
sys.path.insert(0, SCRIPTS)
from abc_common import degree_to_midi, parse_key, spell_midi  # noqa: E402


def run(args, check=False):
    p = subprocess.run([sys.executable] + args, capture_output=True, text=True, cwd=BASE)
    if check and p.returncode != 0:
        raise AssertionError(f"command failed: {args}\nstdout={p.stdout}\nstderr={p.stderr}")
    return p


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class IntakeTests(unittest.TestCase):
    def test_sample_syllables(self):
        out = os.path.join(tempfile.gettempdir(), "abc_intake_test.json")
        p = run([os.path.join(SCRIPTS, "intake_lyrics.py"),
                 "--in", os.path.join(BASE, "tests", "sample_prompt.txt"),
                 "-o", out], check=True)
        data = load(out)
        lines = {l["id"]: l for l in data["lines"]}
        self.assertEqual(lines["verse_1.L1"]["count"], 16)
        self.assertEqual(lines["verse_1.L2"]["count"], 12)
        self.assertEqual(lines["verse_1.L3"]["count"], 14)
        self.assertEqual(data["totals"]["lines"], 26)
        self.assertFalse(lines["verse_1.L1"]["estimated"])
        # A bayt is a sadr + ajuz, and each hemistich gets four bars.
        self.assertEqual(lines["verse_1.L1"]["role"], "sadr")
        self.assertEqual(lines["verse_1.L2"]["role"], "ajuz")
        self.assertEqual(lines["verse_1.L1"]["bayt"], 1)
        self.assertEqual(lines["verse_1.L3"]["bayt"], 2)
        self.assertEqual(lines["verse_1.L1"]["est_bars"], 4)
        self.assertEqual(data["totals"]["bayts"], 13)

    def test_unvocalized_is_estimated(self):
        out = os.path.join(tempfile.gettempdir(), "abc_intake_unvocalized.json")
        prompt = os.path.join(tempfile.gettempdir(), "abc_unvocalized.txt")
        with open(prompt, "w", encoding="utf-8") as f:
            f.write("Maqam Kurd\n\n[Verse 1]\nاعتدت من وجه خلي بعد فرقته كاسا\n")
        run([os.path.join(SCRIPTS, "intake_lyrics.py"), "--in", prompt, "-o", out], check=True)
        data = load(out)
        self.assertTrue(data["lines"][0]["estimated"])
        self.assertGreaterEqual(data["lines"][0]["count"], 1)


class SpellingTests(unittest.TestCase):
    def test_kurd_spelling_on_d(self):
        key = parse_key("Dm")
        expected = {
            "1": "D", "b2": "_E", "2": "E", "b3": "F", "3": "^F",
            "4": "G", "5": "A", "b6": "B", "6": "=B", "b7": "c", "7": "^c",
        }
        for degree, abc in expected.items():
            midi, letter, _ = degree_to_midi(degree, key)
            self.assertEqual(spell_midi(midi, letter, key), abc, degree)


class CompilerTests(unittest.TestCase):
    def test_example_compiles(self):
        tmp = tempfile.mkdtemp(prefix="abc_example_")
        abc = os.path.join(tmp, "song.abc")
        rep = os.path.join(tmp, "song.report.json")
        val = os.path.join(tmp, "song.validation.abc")
        p = run([os.path.join(SCRIPTS, "compile_abc.py"),
                 os.path.join(ASSETS, "example_blueprint.json"),
                 "-o", abc,
                 "--intake", os.path.join(ASSETS, "example_intake.json"),
                 "--report", rep, "--validation-out", val, "--strict"], check=True)
        self.assertIn("OK", p.stdout)
        with open(abc, encoding="utf-8") as f:
            text = f.read()
        self.assertNotIn("\nw:", text)
        self.assertIn("V: Vocal", text)
        self.assertIn("V: Ins", text)
        r = load(rep)
        self.assertTrue(r["ok"])
        self.assertEqual(r["bars"], 30)
        self.assertGreaterEqual(r["melisma_rate"], 1.2)
        self.assertGreaterEqual(r["alignment"]["bars_with_syl"], 20)
        # The report now carries a line map, but the ABC itself still has no
        # lyric lines and no w: rows.
        self.assertEqual(len(r["line_map"]), 6)
        self.assertTrue(all(x["bars"] == 4 for x in r["line_map"]))
        self.assertTrue(all(x["role"] in ("sadr", "ajuz") for x in r["line_map"]))

    def test_bar_sum_error(self):
        tmp = tempfile.mkdtemp(prefix="abc_bad_")
        bp = {
            "meta": {"key": "Dm", "meter": "4/4", "tempo": 84},
            "sections": [{"id": "v1", "kind": "verse", "bars": [
                {"ch": "Dm", "syl": "a b", "voc": "1:1 1:1"}
            ]}],
        }
        path = os.path.join(tmp, "bp.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(bp, f)
        p = run([os.path.join(SCRIPTS, "compile_abc.py"), path,
                 "-o", os.path.join(tmp, "x.abc")])
        self.assertEqual(p.returncode, 1)
        self.assertIn("bar_sum", p.stdout)

    def test_bad_chord(self):
        tmp = tempfile.mkdtemp(prefix="abc_chord_")
        bp = {
            "meta": {"key": "Dm", "meter": "4/4", "tempo": 84},
            "sections": [{"id": "v1", "kind": "verse", "bars": [
                {"ch": "Distorted", "syl": "a b c d", "voc": "1:1 1:1 1:1 1:1"}
            ]}],
        }
        path = os.path.join(tmp, "bp.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(bp, f)
        p = run([os.path.join(SCRIPTS, "compile_abc.py"), path,
                 "-o", os.path.join(tmp, "x.abc")])
        self.assertEqual(p.returncode, 1)
        self.assertIn("bad_chord", p.stdout)

    def test_syllable_mismatch(self):
        tmp = tempfile.mkdtemp(prefix="abc_syl_")
        bp = {
            "meta": {"key": "Dm", "meter": "4/4", "tempo": 84},
            "sections": [{"id": "v1", "kind": "verse", "bars": [
                {"ch": "Dm", "syl": "a b", "voc": "1:1 1:1 1:1 1:1"}
            ]}],
        }
        path = os.path.join(tmp, "bp.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(bp, f)
        p = run([os.path.join(SCRIPTS, "compile_abc.py"), path,
                 "-o", os.path.join(tmp, "x.abc")])
        self.assertEqual(p.returncode, 1)
        self.assertIn("syl_mismatch", p.stdout)


class ValidatorTests(unittest.TestCase):
    def test_example_validates(self):
        binary = os.environ.get("ABC2MIDI") or shutil.which("abc2midi")
        if not binary:
            self.skipTest("abc2midi not available")
        tmp = tempfile.mkdtemp(prefix="abc_val_")
        abc = os.path.join(tmp, "song.abc")
        rep = os.path.join(tmp, "song.report.json")
        val = os.path.join(tmp, "song.validation.abc")
        run([os.path.join(SCRIPTS, "compile_abc.py"),
             os.path.join(ASSETS, "example_blueprint.json"),
             "-o", abc, "--intake", os.path.join(ASSETS, "example_intake.json"),
             "--report", rep, "--validation-out", val, "--strict"], check=True)
        p = run([os.path.join(SCRIPTS, "validate_and_inspect.py"), abc,
                 "--report", rep, "--validation", val,
                 "--abc2midi", binary, "--strict", "--verbose"], check=True)
        self.assertIn("0 errors, 0 warnings", p.stdout)
        self.assertIn("MELISMA", p.stdout)


class CraftTests(unittest.TestCase):
    FIXTURES = os.path.join(BASE, "tests", "fixtures")

    def _inspect(self, abc_path, report=None, validation=None):
        binary = os.environ.get("ABC2MIDI") or shutil.which("abc2midi")
        args = [os.path.join(SCRIPTS, "validate_and_inspect.py"), abc_path, "--json"]
        if report:
            args += ["--report", report]
        if validation:
            args += ["--validation", validation]
        if binary:
            args += ["--abc2midi", binary]
        p = run(args)
        return json.loads(p.stdout)

    def test_example_is_craft_clean(self):
        tmp = tempfile.mkdtemp(prefix="abc_craft_example_")
        abc = os.path.join(tmp, "song.abc")
        rep = os.path.join(tmp, "song.report.json")
        val = os.path.join(tmp, "song.validation.abc")
        run([os.path.join(SCRIPTS, "compile_abc.py"),
             os.path.join(ASSETS, "example_blueprint.json"), "-o", abc,
             "--intake", os.path.join(ASSETS, "example_intake.json"),
             "--report", rep, "--validation-out", val, "--strict"], check=True)
        data = self._inspect(abc, rep, val)
        self.assertTrue(data["ok"], data.get("errors"))
        self.assertEqual(data["craft"]["flags"], [])
        self.assertGreaterEqual(data["craft"]["metrics"]["long_note_share"], 0.17)

    def test_craft_separates_good_from_bad_fixtures(self):
        good = self._inspect(os.path.join(self.FIXTURES, "excellent.txt"))
        self.assertEqual(good["craft"]["flags"], [])
        for name in ("07-score.txt", "11-score.txt", "16-score.txt"):
            data = self._inspect(os.path.join(self.FIXTURES, name))
            self.assertTrue(data["craft"]["flags"], name)
            self.assertGreaterEqual(len(data["craft"]["flags"]), 3, name)
        # The bad scores are rejected by the craft checks, not by abc2midi.
        seven = self._inspect(os.path.join(self.FIXTURES, "07-score.txt"))
        self.assertTrue(seven["ok"])
        self.assertTrue(any("held for a beat" in f for f in seven["craft"]["flags"]))


class SkeletonTests(unittest.TestCase):
    def test_skeleton_completes_to_same_abc(self):
        tmp = tempfile.mkdtemp(prefix="abc_skeleton_")
        sk_path = os.path.join(tmp, "blueprint_skeleton.json")
        intake = os.path.join(tmp, "intake.json")
        run([os.path.join(SCRIPTS, "intake_lyrics.py"),
             "--in", os.path.join(ASSETS, "example_prompt.txt"),
             "-o", intake, "--skeleton", sk_path], check=True)
        skeleton = load(sk_path)
        full = load(os.path.join(ASSETS, "example_blueprint.json"))
        skeleton["motifs"] = full.get("motifs", {})
        by_id = {s["id"]: s for s in full["sections"]}
        for sec in skeleton["sections"]:
            source = by_id[sec["id"]]
            self.assertEqual(len(sec["bars"]), len(source["bars"]), sec["id"])
            for bar, src in zip(sec["bars"], source["bars"]):
                bar["voc"] = src.get("voc", "rest")
                bar["ins"] = src.get("ins", "rest")
        completed = os.path.join(tmp, "completed.json")
        with open(completed, "w", encoding="utf-8") as f:
            json.dump(skeleton, f)
        abc_full = os.path.join(tmp, "full.abc")
        abc_skel = os.path.join(tmp, "skel.abc")
        for src, out in ((os.path.join(ASSETS, "example_blueprint.json"), abc_full),
                         (completed, abc_skel)):
            run([os.path.join(SCRIPTS, "compile_abc.py"), src, "-o", out,
                 "--intake", intake, "--strict"], check=True)
        with open(abc_full, encoding="utf-8") as f:
            full_text = f.read()
        with open(abc_skel, encoding="utf-8") as f:
            skel_text = f.read()
        self.assertEqual(full_text, skel_text)

    def test_skeleton_plus_fill_matches_example_abc(self):
        tmp = tempfile.mkdtemp(prefix="abc_fill_")
        abc = os.path.join(tmp, "song.abc")
        run([os.path.join(SCRIPTS, "compile_abc.py"),
             "--skeleton", os.path.join(ASSETS, "example_blueprint_skeleton.json"),
             "--fill", os.path.join(ASSETS, "example_fill.json"),
             "-o", abc, "--intake", os.path.join(ASSETS, "example_intake.json"),
             "--strict"], check=True)
        with open(abc, encoding="utf-8") as f:
            got = f.read()
        with open(os.path.join(ASSETS, "example_song.abc"), encoding="utf-8") as f:
            want = f.read()
        self.assertEqual(got, want)

    def test_verse_bar_count_is_rejected(self):
        tmp = tempfile.mkdtemp(prefix="abc_verse_")
        bp = {
            "meta": {"key": "Dm", "meter": "4/4", "tempo": 84},
            "sections": [{"id": "verse_1", "kind": "verse",
                          "bars": [{"ch": "Dm"} for _ in range(6)]}],
        }
        path = os.path.join(tmp, "bp.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(bp, f)
        p = run([os.path.join(SCRIPTS, "compile_abc.py"), path,
                 "-o", os.path.join(tmp, "x.abc"),
                 "--intake", os.path.join(ASSETS, "example_intake.json")])
        self.assertEqual(p.returncode, 1)
        self.assertIn("bad_verse_bars", p.stdout)


class MinerTests(unittest.TestCase):
    def test_miner_smoke(self):
        corpus = os.path.join(BASE, "..", "670_arabic_songs_abc_scores")
        if not os.path.isdir(corpus):
            corpus = os.path.join(BASE, "..", "..", "670_arabic_songs_abc_scores")
        if not os.path.isdir(corpus):
            self.skipTest("corpus not available")
        out = os.path.join(tempfile.gettempdir(), "abc_profile_smoke.json")
        p = run([os.path.join(SCRIPTS, "mine_corpus.py"),
                 "--corpus", corpus, "--out", out, "--limit", "50"], check=True)
        data = load(out)
        self.assertEqual(data["corpus"]["files"], 50)
        self.assertGreaterEqual(data["corpus"]["used_for_vocal"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
