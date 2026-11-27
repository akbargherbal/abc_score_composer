#!/usr/bin/env python3
"""0.2.4 W5: template/sameness signals are flags, never a gate."""

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
from abc_common import parse_abc, parse_key  # noqa: E402
from craft_checks import analyse_variety  # noqa: E402

HEADER = "X:1\nM:4/4\nL:1/16\nQ:1/4=90\nK:Dm\n"


def run(args):
    return subprocess.run([sys.executable] + args, capture_output=True,
                          text=True, cwd=BASE)


def variety_for(vocal_body: str, ins_body: str, bars: int) -> dict:
    abc = (HEADER + "V: Vocal\n% verse\n" + vocal_body + "\n"
           + "V: Ins\n" + ins_body + "\n")
    parsed = parse_abc(abc, is_text=True)
    sections = [{"id": "verse_1", "label": "verse", "start_bar": 1,
                 "bars": bars}]
    return analyse_variety(parsed["voices"]["Vocal"], parsed["voices"]["Ins"],
                           sections, parse_key("Dm"))


class VarietyTests(unittest.TestCase):
    def test_template_fixture_flags(self):
        got = variety_for("D4 D4 D4 D4|" * 8, "z16|" * 8, 8)
        self.assertEqual(got["metrics"]["rhythm_variety"]["verse"]["ratio"], 0.125)
        self.assertEqual(got["metrics"]["contour_overlap"]["verse"]["mean"], 1.0)
        self.assertTrue(any("rhythm variety" in f and "share rhythm" in f
                            for f in got["flags"]), got["flags"])
        self.assertTrue(any("contour overlap" in f and "repeat one contour" in f
                            for f in got["flags"]), got["flags"])

    def test_varied_fixture_does_not_flag(self):
        bars = ["D2 E2 F2 G2", "A3 G1 F2 E2", "D1 E1 F1 G1", "A2 A2 G2 G2",
                "F3 E1 D2 C2", "D4 E4", "G2 F2 E2 D2", "A2 G2 F2 E2"]
        got = variety_for("|".join(bars) + "|", "z16|" * 8, 8)
        self.assertGreaterEqual(got["metrics"]["rhythm_variety"]["verse"]["ratio"],
                                0.20)
        self.assertLessEqual(got["metrics"]["contour_overlap"]["verse"]["mean"],
                             0.80)
        self.assertEqual(got["flags"], [])

    def test_information_metrics_are_json_only_not_flags(self):
        got = variety_for("D4 D4 D4 D4|" * 8, "z16|" * 8, 8)
        for key in ("cadence_variety", "ins_variety", "chord_variety"):
            self.assertIn(key, got["metrics"])
        text = " ".join(got["flags"])
        self.assertNotIn("cadence", text)
        self.assertNotIn("ins ", text)
        self.assertNotIn("chord", text)

    def test_shipped_example_does_not_flag(self):
        tmp = tempfile.mkdtemp(prefix="abc_variety_")
        abc = os.path.join(tmp, "song.abc")
        rep = os.path.join(tmp, "song.report.json")
        p = run([os.path.join(SCRIPTS, "compile_abc.py"),
                 "--skeleton", os.path.join(ASSETS, "example_blueprint_skeleton.json"),
                 "--fill", os.path.join(ASSETS, "example_fill.json"),
                 "-o", abc, "--report", rep,
                 "--intake", os.path.join(ASSETS, "example_intake.json"),
                 "--strict"])
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        p = run([os.path.join(SCRIPTS, "validate_and_inspect.py"), abc,
                 "--report", rep, "--json"])
        data = json.loads(p.stdout)
        self.assertEqual(data["variety_flags"], [])
        for key in ("rhythm_variety", "contour_overlap", "cadence_variety",
                    "ins_variety", "chord_variety"):
            self.assertIn(key, data["variety"])
        self.assertEqual(data["variety"], data["variety"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
