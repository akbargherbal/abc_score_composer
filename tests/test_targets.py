#!/usr/bin/env python3
"""0.2.4 W3: target provenance and tamper evidence."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(BASE, "scripts")
ASSETS = os.path.join(BASE, "assets")
sys.path.insert(0, SCRIPTS)
from abc_common import DEFAULT_TARGETS, targets_edited  # noqa: E402


def run(args):
    return subprocess.run([sys.executable] + args, capture_output=True,
                          text=True, cwd=BASE)


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class TargetTests(unittest.TestCase):
    def _compile_and_inspect(self, meta_edit=None):
        tmp = tempfile.mkdtemp(prefix="abc_targets_")
        fill = load(os.path.join(ASSETS, "example_fill.json"))
        if meta_edit:
            fill["meta"] = {"targets": meta_edit}
        fill_path = os.path.join(tmp, "fill.json")
        with open(fill_path, "w", encoding="utf-8") as f:
            json.dump(fill, f)
        abc = os.path.join(tmp, "song.abc")
        rep = os.path.join(tmp, "song.report.json")
        val = os.path.join(tmp, "song.validation.abc")
        p = run([os.path.join(SCRIPTS, "compile_abc.py"),
                 "--skeleton", os.path.join(ASSETS, "example_blueprint_skeleton.json"),
                 "--fill", fill_path, "-o", abc, "--report", rep,
                 "--validation-out", val,
                 "--intake", os.path.join(ASSETS, "example_intake.json"),
                 "--strict"])
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        p = run([os.path.join(SCRIPTS, "validate_and_inspect.py"), abc,
                 "--report", rep, "--validation", val, "--json"])
        return json.loads(p.stdout), load(rep)

    def test_default_has_no_melisma_target(self):
        self.assertNotIn("melisma", DEFAULT_TARGETS)
        data, report = self._compile_and_inspect()
        self.assertNotIn("melisma", report["meta"]["targets"])
        self.assertFalse(any("melisma" in f and "target" in f for f in data["flags"]))
        self.assertIsNotNone(data["melisma"])  # still computed and visible

    def test_intake_skeleton_uses_defaults(self):
        tmp = tempfile.mkdtemp(prefix="abc_targets_")
        skel = os.path.join(tmp, "skel.json")
        p = run([os.path.join(SCRIPTS, "intake_lyrics.py"),
                 "--in", os.path.join(ASSETS, "example_prompt.txt"),
                 "-o", os.path.join(tmp, "intake.json"), "--skeleton", skel])
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(load(skel)["meta"]["targets"], DEFAULT_TARGETS)
        self.assertEqual(load(os.path.join(ASSETS, "example_blueprint_skeleton.json"))
                         ["meta"]["targets"], DEFAULT_TARGETS)

    def test_unedited_run_has_no_target_edited(self):
        data, _ = self._compile_and_inspect()
        self.assertEqual(data["targets_edited"], [])
        self.assertFalse(any(f.startswith("TARGET edited") for f in data["flags"]))

    def test_edited_vocal_span_is_flagged_and_honoured(self):
        data, _ = self._compile_and_inspect({"vocal_span": 22})
        self.assertIn("TARGET edited: vocal_span 20 -> 22", data["flags"])
        self.assertEqual(data["targets_edited"],
                         [{"key": "vocal_span", "default": 20, "value": 22}])

    def test_explicit_melisma_is_added_flagged_and_honoured(self):
        data, _ = self._compile_and_inspect({"melisma": 5.0})
        self.assertIn("TARGET edited: melisma none -> 5.0", data["flags"])
        self.assertTrue(any(f.startswith("melisma ") and "< target 5.0" in f
                            for f in data["flags"]))

    def test_helper_ignores_craft_switch(self):
        self.assertEqual(targets_edited({"craft": True, **DEFAULT_TARGETS}), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
