#!/usr/bin/env python3
"""Integration tests for the optional abcsim assets in 0.2.3.

Run from the skill directory:
    python3 -m unittest discover -s tests -p 'test_*.py'

The novelty positive control uses a shipped, unmodified corpus excerpt; the
seed tests use the shipped phrase bank.  No network or corpus checkout is
needed.
"""

from __future__ import annotations

import glob
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(BASE, "scripts")
ASSETS = os.path.join(BASE, "assets")
sys.path.insert(0, SCRIPTS)

import measure_footprint  # noqa: E402
import novelty_check  # noqa: E402
from abc_common import parse_key  # noqa: E402
from compile_abc import parse_voice_string  # noqa: E402

BANK = os.path.join(ASSETS, "corpus_fingerprints.bin")
PHRASE_BANK = os.path.join(ASSETS, "phrase_bank.json")
EXAMPLE = os.path.join(ASSETS, "example_song.abc")
CORPUS_FIXTURE = os.path.join(BASE, "tests", "fixtures", "suno-0100.abc")
INTAKE = os.path.join(SCRIPTS, "intake_lyrics.py")
VALIDATOR = os.path.join(SCRIPTS, "validate_and_inspect.py")


def run(args, check=False):
    p = subprocess.run([sys.executable] + args, capture_output=True, text=True,
                       cwd=BASE)
    if check and p.returncode != 0:
        raise AssertionError(
            f"command failed: {args}\nstdout={p.stdout}\nstderr={p.stderr}")
    return p


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def seed_lines(stdout):
    return [l for l in stdout.splitlines() if l.startswith("SEED ")]


def seed_block_bytes(lines):
    return sum(len(l.encode("utf-8")) + 1 for l in lines)


class NoveltyTests(unittest.TestCase):
    def test_novelty_negative(self):
        line = novelty_check.check(EXAMPLE, BANK)
        self.assertIn("status=ok", line)
        self.assertIn("closest=none", line)

    def test_novelty_positive(self):
        line = novelty_check.check(CORPUS_FIXTURE, BANK)
        self.assertIn("status=close", line)
        self.assertIn("containment=1.000", line)
        self.assertIn("suno-0100.abc", line)

    def test_novelty_missing_asset(self):
        p = run([VALIDATOR, EXAMPLE, "--novelty-bank",
                 os.path.join(tempfile.gettempdir(), "no-such-bank.bin")])
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertNotIn("NOVELTY", p.stdout)
        self.assertIn("OK", p.stdout)

    def test_novelty_never_raises(self):
        tmp = tempfile.mkdtemp(prefix="abc_novelty_bad_")
        try:
            bad = os.path.join(tmp, "corpus_fingerprints.bin")
            with open(BANK, "rb") as f:
                head = f.read(100)
            with open(bad, "wb") as f:
                f.write(head)
            p = run([VALIDATOR, EXAMPLE, "--novelty-bank", bad])
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertNotIn("NOVELTY", p.stdout)
            self.assertIn("OK", p.stdout)
        finally:
            for name in os.listdir(tmp):
                os.remove(os.path.join(tmp, name))
            os.rmdir(tmp)

    def test_novelty_time_budget(self):
        start = time.perf_counter()
        novelty_check.check(EXAMPLE, BANK)
        self.assertLess(time.perf_counter() - start, 5.0)

    def test_compact_is_silent_on_ok(self):
        p = run([VALIDATOR, EXAMPLE], check=True)
        self.assertNotIn("NOVELTY", p.stdout)

    def test_compact_shows_close(self):
        p = run([VALIDATOR, CORPUS_FIXTURE], check=True)
        self.assertIn("NOVELTY", p.stdout)
        self.assertIn("status=close", p.stdout)

    def test_json_has_novelty_key(self):
        p = run([VALIDATOR, EXAMPLE, "--json"], check=True)
        data = json.loads(p.stdout)
        self.assertIn("novelty", data)
        self.assertEqual(data["novelty"]["status"], "ok")


class SeedTests(unittest.TestCase):
    def test_seed_off_by_default(self):
        tmp = tempfile.mkdtemp(prefix="abc_seed_off_")
        try:
            args = [INTAKE, "--in", os.path.join(ASSETS, "example_prompt.txt"),
                    "-o", os.path.join(tmp, "intake.json"),
                    "--skeleton", os.path.join(tmp, "skel.json")]
            default = run(args, check=True)
            explicit = run(args + ["--seeds", "0"], check=True)
            self.assertEqual(default.stdout, explicit.stdout)
            self.assertNotIn("SEED ", default.stdout)
        finally:
            for name in os.listdir(tmp):
                os.remove(os.path.join(tmp, name))
            os.rmdir(tmp)

    def test_seed_budget(self):
        prompts = [
            os.path.join(BASE, "tests", "sample_prompt.txt"),
            os.path.join(ASSETS, "example_prompt.txt"),
        ] + sorted(glob.glob(os.path.join(BASE, "tests", "prompts", "*.txt")))
        saw_seed = False
        for prompt in prompts:
            tmp = tempfile.mkdtemp(prefix="abc_seed_budget_")
            try:
                p = run([INTAKE, "--in", prompt,
                         "-o", os.path.join(tmp, "intake.json"),
                         "--skeleton", os.path.join(tmp, "skel.json"),
                         "--seeds", "3"], check=True)
                lines = seed_lines(p.stdout)
                self.assertLessEqual(seed_block_bytes(lines), 400, prompt)
                for line in lines:
                    self.assertNotIn("K:", line)
                    self.assertNotIn("key=", line)
                    self.assertNotIn("source_key", line)
                saw_seed = saw_seed or bool(lines)
            finally:
                for name in os.listdir(tmp):
                    os.remove(os.path.join(tmp, name))
                os.rmdir(tmp)
        self.assertTrue(saw_seed, "no prompt produced a seed")

    def test_no_seed_for_16_beat_line(self):
        # Every example-prompt line is a 4-bar shatr (16 beats).
        tmp = tempfile.mkdtemp(prefix="abc_seed_16_")
        try:
            p = run([INTAKE, "--in", os.path.join(ASSETS, "example_prompt.txt"),
                     "-o", os.path.join(tmp, "intake.json"),
                     "--skeleton", os.path.join(tmp, "skel.json"),
                     "--seeds", "3"], check=True)
            self.assertEqual(seed_lines(p.stdout), [])
        finally:
            for name in os.listdir(tmp):
                os.remove(os.path.join(tmp, name))
            os.rmdir(tmp)

    def test_seed_schema_guard(self):
        tmp = tempfile.mkdtemp(prefix="abc_seed_schema_")
        try:
            bank = load(PHRASE_BANK)
            bank["schema"] = "phrase_bank/1"
            bad = os.path.join(tmp, "bank.json")
            with open(bad, "w", encoding="utf-8") as f:
                json.dump(bank, f)
            p = run([INTAKE, "--in",
                     os.path.join(BASE, "tests", "prompts", "short_kurd.txt"),
                     "-o", os.path.join(tmp, "intake.json"),
                     "--skeleton", os.path.join(tmp, "skel.json"),
                     "--seeds", "3", "--phrase-bank", bad], check=True)
            self.assertEqual(seed_lines(p.stdout), [])
        finally:
            for name in os.listdir(tmp):
                os.remove(os.path.join(tmp, name))
            os.rmdir(tmp)

    def test_seed_phrases_parse(self):
        bank = load(PHRASE_BANK)
        key = parse_key("Dm")
        self.assertEqual(len(bank["phrases"]), 48)
        for phrase in bank["phrases"]:
            events, _groups = parse_voice_string(phrase["phrase"], key)
            self.assertTrue(events, phrase["id"])
            self.assertTrue(all(ev["type"] in ("note", "rest") for ev in events),
                            phrase["id"])

    def test_bayati_falls_back_to_mode_any(self):
        tmp = tempfile.mkdtemp(prefix="abc_seed_bayati_")
        try:
            p = run([INTAKE, "--in",
                     os.path.join(BASE, "tests", "prompts", "short_bayati.txt"),
                     "-o", os.path.join(tmp, "intake.json"),
                     "--skeleton", os.path.join(tmp, "skel.json"),
                     "--seeds", "3"], check=True)
            lines = seed_lines(p.stdout)
            self.assertTrue(lines)
            self.assertTrue(any("mode=any" in line for line in lines))
        finally:
            for name in os.listdir(tmp):
                os.remove(os.path.join(tmp, name))
            os.rmdir(tmp)


class AssetTests(unittest.TestCase):
    def test_assets_size(self):
        self.assertLessEqual(os.path.getsize(PHRASE_BANK), 60 * 1024)
        self.assertLessEqual(os.path.getsize(BANK), 700 * 1024)
        self.assertTrue(os.path.exists(
            os.path.join(ASSETS, "corpus_profile.dedup.candidate.json")))
        self.assertTrue(os.path.exists(os.path.join(ASSETS, "PROVENANCE.md")))

    def test_new_assets_are_not_mandatory(self):
        files = measure_footprint.mandatory_files(BASE)
        for rel in ("assets/phrase_bank.json", "assets/corpus_fingerprints.bin",
                    "assets/corpus_profile.dedup.candidate.json",
                    "scripts/novelty_check.py"):
            self.assertNotIn(rel, files)

    def test_card_words(self):
        binary = os.environ.get("ABC2MIDI") or measure_footprint.shutil.which("abc2midi")
        data = measure_footprint.measure(BASE, "test", binary)
        self.assertEqual(data["card_ok_words"], 13)
        self.assertEqual(data["card_fail_words"], 32)

    def test_footprint_rows(self):
        binary = os.environ.get("ABC2MIDI") or measure_footprint.shutil.which("abc2midi")
        data = measure_footprint.measure(BASE, "test", binary)
        self.assertLessEqual(data["seed_block_B"], 400)
        self.assertLessEqual(data["novelty_line_B"], 120)
        self.assertGreater(data["package_zip_B"], 600 * 1024)
        self.assertLess(data["package_zip_B"], 2 * 1024 * 1024)
        self.assertLessEqual(data["mandatory_bytes"],
                             measure_footprint.BASELINE_0_2_2_MANDATORY_BYTES
                             + measure_footprint.MANDATORY_GROWTH_LIMIT)


if __name__ == "__main__":
    unittest.main(verbosity=2)
