#!/usr/bin/env python3
"""0.2.4 W2: lyric-less and unknown sections must not default to `verse`."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(BASE, "scripts")
sys.path.insert(0, SCRIPTS)
from abc_common import parse_key  # noqa: E402


def run(args):
    return subprocess.run([sys.executable] + args, capture_output=True,
                          text=True, cwd=BASE)


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _syl_count(ref):
    """Syllable count of an `@line:a-b` reference."""
    rng = ref.rsplit(":", 1)[1]
    a, b = rng.split("-")
    return int(b) - int(a) + 1


def make_fill(skeleton):
    """A mechanical placeholder fill: one half-beat note per syllable."""
    fill = {}
    for sec in skeleton["sections"]:
        if "same_as" in sec:
            continue
        rows = []
        for bar in sec["bars"]:
            if bar.get("syl"):
                n = _syl_count(bar["syl"])
                voc = " ".join(["1:.5"] * n)
                if n < 8:
                    voc += " r:%s" % (4 - n * 0.5)
            else:
                voc = "rest"
            rows.append([voc, "rest"])
        fill[sec["id"]] = rows
    return {"meta": {}, "motifs": {}, "fill": fill}


class IntakeKindTests(unittest.TestCase):
    def _intake(self, text):
        tmp = tempfile.mkdtemp(prefix="abc_kinds_")
        prompt = os.path.join(tmp, "prompt.txt")
        with open(prompt, "w", encoding="utf-8") as f:
            f.write(text)
        intake = os.path.join(tmp, "intake.json")
        skel = os.path.join(tmp, "skel.json")
        p = run([os.path.join(SCRIPTS, "intake_lyrics.py"), "--in", prompt,
                 "-o", intake, "--skeleton", skel])
        self.assertEqual(p.returncode, 0, p.stderr)
        return tmp, load(intake), load(skel), intake, skel

    def _prompt(self):
        with open(os.path.join(BASE, "tests", "sample_prompt.txt"),
                  encoding="utf-8") as f:
            return f.read().rstrip("\n")

    def test_end_header_is_outro_and_compiles_without_edits(self):
        tmp, data, skel, intake, skel_path = self._intake(
            self._prompt() + "\n\n[End]\n")
        last = data["sections"][-1]
        self.assertEqual(last["name"], "End")
        self.assertEqual(last["kind"], "outro")
        fill_path = os.path.join(tmp, "fill.json")
        with open(fill_path, "w", encoding="utf-8") as f:
            json.dump(make_fill(skel), f)
        abc = os.path.join(tmp, "song.abc")
        p = run([os.path.join(SCRIPTS, "compile_abc.py"),
                 "--skeleton", skel_path, "--fill", fill_path, "-o", abc,
                 "--intake", intake, "--strict"])
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertNotIn("bad_verse_bars", p.stdout)

    def test_end_last_chord_is_tonic(self):
        _, data, skel, _, _ = self._intake(self._prompt() + "\n\n[End]\n")
        sec = skel["sections"][-1]
        self.assertEqual(sec["kind"], "outro")
        key = skel["meta"]["key"]
        self.assertTrue(parse_key(key)["minor"])
        self.assertEqual(sec["bars"][-1]["ch"], key[:-1] + "m"
                         if key.endswith("m") else key)

    def test_unknown_last_section_without_lines_is_outro(self):
        _, data, skel, _, _ = self._intake(self._prompt() + "\n\n[Fin]\n")
        self.assertEqual(data["sections"][-1]["kind"], "outro")

    def test_unknown_middle_section_without_lines_is_interlude(self):
        text = self._prompt() + "\n\n[Fin]\n\n[Verse 9]\nكلمة كلمة\n"
        _, data, _, _, _ = self._intake(text)
        fin = [s for s in data["sections"] if s["name"] == "Fin"][0]
        self.assertEqual(fin["kind"], "interlude")

    def test_unknown_section_with_lines_stays_verse(self):
        text = self._prompt() + "\n\n[Whatever]\nاعْتَضْتُ مِنْ وَجْهِ خِلِّي\nيُجَرَّعُ مِنْهَا\n"
        _, data, _, _, _ = self._intake(text)
        self.assertEqual(data["sections"][-1]["kind"], "verse")

    def test_verse_header_unchanged(self):
        _, data, _, _, _ = self._intake(self._prompt())
        kinds = {s["name"]: s["kind"] for s in data["sections"]}
        self.assertEqual(kinds["Verse 1"], "verse")
        self.assertEqual(kinds["Chorus"], "chorus")
        self.assertEqual(kinds["Verse 2"], "verse")
        for s in data["sections"]:
            self.assertNotIn("_unknown_kind", s)


if __name__ == "__main__":
    unittest.main(verbosity=2)
