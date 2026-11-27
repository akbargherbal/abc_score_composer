#!/usr/bin/env python3
"""0.2.4 W6: authoring-cost instrumentation."""

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
import measure_footprint  # noqa: E402


def run(args):
    return subprocess.run([sys.executable] + args, capture_output=True,
                          text=True, cwd=BASE)


class CostTests(unittest.TestCase):
    def _compile(self, *extra):
        tmp = tempfile.mkdtemp(prefix="abc_cost_")
        abc = os.path.join(tmp, "song.abc")
        rep = os.path.join(tmp, "song.report.json")
        fill = os.path.join(ASSETS, "example_fill.json")
        p = run([os.path.join(SCRIPTS, "compile_abc.py"),
                 "--skeleton", os.path.join(ASSETS, "example_blueprint_skeleton.json"),
                 "--fill", fill, "-o", abc, "--report", rep,
                 "--intake", os.path.join(ASSETS, "example_intake.json"),
                 "--strict", *extra])
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        with open(rep, encoding="utf-8") as f:
            return p, json.load(f), abc, fill

    def test_report_fields_match_file_sizes(self):
        _, report, abc, fill = self._compile()
        self.assertEqual(report["fill_bytes"], os.path.getsize(fill))
        self.assertEqual(report["abc_bytes"], os.path.getsize(abc))
        self.assertAlmostEqual(report["fill_to_abc_ratio"],
                               report["fill_bytes"] / report["abc_bytes"], places=3)

    def test_json_output_has_fields(self):
        p, _, _, _ = self._compile("--json")
        data = json.loads(p.stdout)
        for key in ("fill_bytes", "abc_bytes", "fill_to_abc_ratio"):
            self.assertIn(key, data)

    def test_compact_card_unchanged_and_verbose_adds_cost(self):
        # Same output path for both runs so the card text is comparable.
        tmp = tempfile.mkdtemp(prefix="abc_cost_")
        base = [os.path.join(SCRIPTS, "compile_abc.py"),
                "--skeleton", os.path.join(ASSETS, "example_blueprint_skeleton.json"),
                "--fill", os.path.join(ASSETS, "example_fill.json"),
                "-o", os.path.join(tmp, "song.abc"),
                "--intake", os.path.join(ASSETS, "example_intake.json"), "--strict"]
        plain = run(base)
        verbose = run(base + ["--verbose"])
        self.assertEqual(plain.returncode, 0)
        self.assertNotIn("cost ", plain.stdout)
        lines = verbose.stdout.splitlines()
        self.assertEqual(lines[:-1], plain.stdout.splitlines())
        self.assertTrue(lines[-1].startswith("cost fill "))

    def test_footprint_has_ratio_row(self):
        data = measure_footprint.measure(BASE, "test", None)
        self.assertGreater(data["fill_to_abc_ratio"], 0)
        self.assertEqual(data["example_abc_bytes"],
                         os.path.getsize(os.path.join(ASSETS, "example_song.abc")))


if __name__ == "__main__":
    unittest.main(verbosity=2)
