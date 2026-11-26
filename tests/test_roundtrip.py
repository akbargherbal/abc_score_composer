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
        self.assertEqual(r["bars"], 18)
        self.assertGreaterEqual(r["melisma_rate"], 1.2)
        self.assertGreaterEqual(r["alignment"]["bars_with_syl"], 12)

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
                 "--abc2midi", binary, "--strict"], check=True)
        self.assertIn("0 errors, 0 warnings", p.stdout)
        self.assertIn("MELISMA", p.stdout)


class MinerTests(unittest.TestCase):
    def test_miner_smoke(self):
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
