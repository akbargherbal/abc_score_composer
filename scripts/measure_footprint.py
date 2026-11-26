#!/usr/bin/env python3
"""Measure the token-facing footprint of one abc-score-writer checkout.

This is a development tool, not part of the shipped skill.  It reports:

* bytes/words that must be read before the first Blueprint,
* the example Blueprint's size and bars,
* the bytes the agent writes for voc/ins per bar,
* the word count of the inspector card on success and on a forced failure.

Usage:
    python3 scripts/measure_footprint.py [--root DIR] [--label NAME]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

WORD_RE = re.compile(r"\S+", re.UNICODE)


def words(text: str) -> int:
    return len(WORD_RE.findall(text or ""))


def size(path: str) -> int:
    return os.path.getsize(path) if os.path.exists(path) else 0


def read(path: str) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def count_bars(blueprint: dict) -> int:
    sections = blueprint.get("sections") or []
    by_id = {s.get("id"): s for s in sections}
    total = 0
    for sec in sections:
        bars = sec.get("bars")
        if isinstance(bars, list) and (not bars or not all(isinstance(x, int) for x in bars)):
            total += len(bars)
        elif isinstance(bars, list) and bars and all(isinstance(x, int) for x in bars):
            total += len(bars)
        elif sec.get("same_as"):
            src = by_id.get(sec["same_as"]) or {}
            src_bars = src.get("bars") if isinstance(src.get("bars"), list) else []
            take = sec.get("take")
            total += len(take) if isinstance(take, list) else len(src_bars)
    return total


def payload_per_bar(blueprint: dict, bars: int) -> float:
    payload = 0
    for sec in blueprint.get("sections") or []:
        for bar in sec.get("bars") or []:
            if not isinstance(bar, dict):
                continue
            payload += len(str(bar.get("voc", ""))) + len(str(bar.get("ins", "")))
    return payload / bars if bars else 0.0


def mandatory_files(root: str) -> list[str]:
    return [
        "SKILL.md",
        "references/blueprint_schema.md",
        "assets/example_prompt.txt",
        "assets/example_intake.json",
        "assets/example_blueprint.json",
        "assets/example_song.abc",
    ]


def run_compile(root: str, tmp: str) -> tuple[str, str]:
    py = sys.executable
    abc = os.path.join(tmp, "song.abc")
    report = os.path.join(tmp, "song.report.json")
    validation = os.path.join(tmp, "song.validation.abc")
    bp = os.path.join(root, "assets", "example_blueprint.json")
    intake = os.path.join(root, "assets", "example_intake.json")
    compiler = os.path.join(root, "scripts", "compile_abc.py")
    if not (os.path.exists(bp) and os.path.exists(compiler)):
        shutil.copyfile(os.path.join(root, "assets", "example_song.abc"), abc)
        return abc, ""
    cmd = [py, compiler, bp, "-o", abc, "--intake", intake,
           "--report", report, "--validation-out", validation, "--strict"]
    p = subprocess.run(cmd, capture_output=True, text=True, cwd=root)
    if p.returncode != 0 or not os.path.exists(abc):
        # Some old checkouts reject the newer example; fall back to the asset.
        shutil.copyfile(os.path.join(root, "assets", "example_song.abc"), abc)
        report = ""
        validation = ""
    return abc, report + "\0" + validation


def mutate_failure(abc: str, out: str) -> None:
    """Drop one vocal bar so the two voices no longer align."""
    lines = read(abc).splitlines()
    done = False
    result = []
    for line in lines:
        if not done and line.startswith('"') and "|" in line:
            parts = [p for p in line.split("|")]
            keep = [p for p in parts if p.strip()]
            if len(keep) > 1:
                keep.pop(0)
                result.append("|".join(keep) + "|")
                done = True
                continue
        result.append(line)
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(result) + "\n")


def inspect_card(root: str, abc: str, report: str, validation: str,
                 binary: str | None) -> tuple[int, int]:
    py = sys.executable
    validator = os.path.join(root, "scripts", "validate_and_inspect.py")
    opts = []
    if report and os.path.exists(report):
        opts += ["--report", report]
    if validation and os.path.exists(validation):
        opts += ["--validation", validation]
    if binary:
        opts += ["--abc2midi", binary]

    ok = subprocess.run([py, validator, abc] + opts,
                        capture_output=True, text=True, cwd=root)
    fail_path = os.path.join(os.path.dirname(abc), "broken.abc")
    mutate_failure(abc, fail_path)
    fail = subprocess.run([py, validator, fail_path] + opts,
                          capture_output=True, text=True, cwd=root)
    return words(ok.stdout), words(fail.stdout)


def measure(root: str, label: str, binary: str | None) -> dict:
    root = os.path.abspath(root)
    files = mandatory_files(root)
    rows = []
    for rel in files:
        path = os.path.join(root, rel)
        rows.append({"file": rel, "bytes": size(path), "words": words(read(path))})
    mandatory_bytes = sum(r["bytes"] for r in rows)
    mandatory_words = sum(r["words"] for r in rows)

    bp_path = os.path.join(root, "assets", "example_blueprint.json")
    bp_text = read(bp_path)
    try:
        bp = json.loads(bp_text) if bp_text else {}
    except json.JSONDecodeError:
        bp = {}
    bars = count_bars(bp)
    payload = payload_per_bar(bp, bars)

    tmp = tempfile.mkdtemp(prefix="abc_footprint_")
    try:
        abc, rv = run_compile(root, tmp)
        report, validation = (rv.split("\0", 1) if "\0" in rv else ("", ""))
        card_ok, card_fail = inspect_card(root, abc, report, validation, binary)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    return {
        "label": label,
        "root": root,
        "skill_bytes": size(os.path.join(root, "SKILL.md")),
        "skill_words": words(read(os.path.join(root, "SKILL.md"))),
        "mandatory_bytes": mandatory_bytes,
        "mandatory_words": mandatory_words,
        "blueprint_bytes": size(bp_path),
        "blueprint_bars": bars,
        "agent_payload_bytes_per_bar": round(payload, 1),
        "card_ok_words": card_ok,
        "card_fail_words": card_fail,
        "files": rows,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".")
    ap.add_argument("--label", default="")
    ap.add_argument("--abc2midi", default=os.environ.get("ABC2MIDI"))
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    label = args.label or os.path.basename(os.path.abspath(args.root))
    data = measure(args.root, label, args.abc2midi)
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    print(f"{'label':10s} {'skill_B':>8s} {'skill_W':>8s} {'mand_B':>8s} "
          f"{'mand_W':>8s} {'bp_B':>7s} {'bars':>5s} {'B/bar':>7s} "
          f"{'ok_W':>6s} {'fail_W':>7s}")
    print(f"{data['label']:10s} {data['skill_bytes']:8d} {data['skill_words']:8d} "
          f"{data['mandatory_bytes']:8d} {data['mandatory_words']:8d} "
          f"{data['blueprint_bytes']:7d} {data['blueprint_bars']:5d} "
          f"{data['agent_payload_bytes_per_bar']:7.1f} "
          f"{data['card_ok_words']:6d} {data['card_fail_words']:7d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
