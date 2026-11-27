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
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

WORD_RE = re.compile(r"\S+", re.UNICODE)

# 0.2.3: also reports seed_block_B, novelty_line_B and package_zip_B.
# 0.2.2 baseline from docs/footprint_0.2.2.txt.  Mandatory reading may grow by
# at most 150 B in 0.2.3.
BASELINE_0_2_2_MANDATORY_BYTES = 26484
MANDATORY_GROWTH_LIMIT = 150


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
    """Files the agent must read before the first Blueprint.

    From v0.2.2 the example is skeleton + fill, so the full Blueprint is only
    an optional format reference.  Before that, the full Blueprint was the
    working example.
    """
    files = [
        "SKILL.md",
        "references/blueprint_schema.md",
        "assets/example_prompt.txt",
        "assets/example_intake.json",
    ]
    if os.path.exists(os.path.join(root, "assets", "example_fill.json")):
        files += ["assets/example_blueprint_skeleton.json", "assets/example_fill.json"]
    else:
        files += ["assets/example_blueprint.json"]
    files += ["assets/example_song.abc"]
    return files


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


def sample_prompts(root: str) -> list[str]:
    """Prompt files used for the seed-block measurement."""
    candidates = [
        os.path.join(root, "tests", "sample_prompt.txt"),
        os.path.join(root, "assets", "example_prompt.txt"),
    ]
    pdir = os.path.join(root, "tests", "prompts")
    if os.path.isdir(pdir):
        candidates += sorted(glob.glob(os.path.join(pdir, "*.txt")))
    return [p for p in candidates if os.path.exists(p)]


def seed_block_bytes(root: str, prompts: list[str]) -> int:
    """Largest `SEED` block, in bytes including newlines, across prompts."""
    py = sys.executable
    intake = os.path.join(root, "scripts", "intake_lyrics.py")
    if not os.path.exists(intake):
        return 0
    best = 0
    for prompt in prompts:
        tmp = tempfile.mkdtemp(prefix="abc_seed_")
        try:
            out = os.path.join(tmp, "intake.json")
            skeleton = os.path.join(tmp, "blueprint_skeleton.json")
            p = subprocess.run(
                [py, intake, "--in", prompt, "-o", out, "--skeleton", skeleton,
                 "--seeds", "3"],
                capture_output=True, text=True, cwd=root)
            block = [l for l in p.stdout.splitlines() if l.startswith("SEED ")]
            size = sum(len(l.encode("utf-8")) + 1 for l in block)
            best = max(best, size)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return best


def novelty_line_bytes(root: str, abc: str, report: str, validation: str,
                       binary: str | None) -> int:
    """Longest NOVELTY line printed in verbose mode, in bytes."""
    py = sys.executable
    validator = os.path.join(root, "scripts", "validate_and_inspect.py")
    opts = []
    if report and os.path.exists(report):
        opts += ["--report", report]
    if validation and os.path.exists(validation):
        opts += ["--validation", validation]
    if binary:
        opts += ["--abc2midi", binary]
    p = subprocess.run([py, validator, abc, "--verbose"] + opts,
                       capture_output=True, text=True, cwd=root)
    lines = [l for l in p.stdout.splitlines() if l.startswith("NOVELTY ")]
    return max((len(l.encode("utf-8")) for l in lines), default=0)


def package_zip_bytes(root: str) -> int:
    """Size of a dist-style zip of the skill, without dist/, docs/ or .git/."""
    root = os.path.abspath(root)
    skip_dirs = {".git", "dist", "docs", "__pycache__", ".pytest_cache",
                 ".opencode", "node_modules", ".venv"}
    tmp = tempfile.mkdtemp(prefix="abc_pkg_")
    try:
        zpath = os.path.join(tmp, "package.zip")
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = sorted(d for d in dirnames if d not in skip_dirs)
                for name in sorted(filenames):
                    if name.endswith((".pyc", ".mid", ".midi", ".wav", ".mp3", ".flac")):
                        continue
                    full = os.path.join(dirpath, name)
                    rel = os.path.relpath(full, root)
                    z.write(full, os.path.join("abc-score-writer", rel))
        return os.path.getsize(zpath)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


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

    fill_path = os.path.join(root, "assets", "example_fill.json")
    agent_path = fill_path if os.path.exists(fill_path) else bp_path
    skel_path = os.path.join(root, "assets", "example_blueprint_skeleton.json")
    agent_bytes = size(agent_path)
    skeleton_bytes = size(skel_path)

    tmp = tempfile.mkdtemp(prefix="abc_footprint_")
    try:
        abc, rv = run_compile(root, tmp)
        report, validation = (rv.split("\0", 1) if "\0" in rv else ("", ""))
        card_ok, card_fail = inspect_card(root, abc, report, validation, binary)
        novelty_line = novelty_line_bytes(root, abc, report, validation, binary)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    seed_block = seed_block_bytes(root, sample_prompts(root))
    package_zip = package_zip_bytes(root)

    return {
        "label": label,
        "root": root,
        "skill_bytes": size(os.path.join(root, "SKILL.md")),
        "skill_words": words(read(os.path.join(root, "SKILL.md"))),
        "mandatory_bytes": mandatory_bytes,
        "mandatory_words": mandatory_words,
        "blueprint_bytes": size(bp_path),
        "blueprint_bars": bars,
        "agent_write_bytes": agent_bytes,
        "agent_write_file": os.path.relpath(agent_path, root),
        "skeleton_bytes": skeleton_bytes,
        "agent_payload_bytes_per_bar": round(payload, 1),
        "card_ok_words": card_ok,
        "card_fail_words": card_fail,
        "seed_block_B": seed_block,
        "novelty_line_B": novelty_line,
        "package_zip_B": package_zip,
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
    guard_ok = (data["mandatory_bytes"]
                <= BASELINE_0_2_2_MANDATORY_BYTES + MANDATORY_GROWTH_LIMIT)
    data["mandatory_baseline_B"] = BASELINE_0_2_2_MANDATORY_BYTES
    data["mandatory_growth_limit_B"] = MANDATORY_GROWTH_LIMIT
    data["mandatory_guard_ok"] = guard_ok
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0 if guard_ok else 1
    print(f"{'label':10s} {'skill_B':>8s} {'skill_W':>8s} {'mand_B':>8s} "
          f"{'mand_W':>8s} {'bp_B':>7s} {'skel_B':>7s} {'agent_B':>7s} "
          f"{'bars':>5s} {'B/bar':>7s} {'ok_W':>6s} {'fail_W':>7s} "
          f"{'seed_B':>7s} {'nov_B':>6s} {'zip_B':>8s}")
    print(f"{data['label']:10s} {data['skill_bytes']:8d} {data['skill_words']:8d} "
          f"{data['mandatory_bytes']:8d} {data['mandatory_words']:8d} "
          f"{data['blueprint_bytes']:7d} {data['skeleton_bytes']:7d} "
          f"{data['agent_write_bytes']:7d} {data['blueprint_bars']:5d} "
          f"{data['agent_payload_bytes_per_bar']:7.1f} "
          f"{data['card_ok_words']:6d} {data['card_fail_words']:7d} "
          f"{data['seed_block_B']:7d} {data['novelty_line_B']:6d} "
          f"{data['package_zip_B']:8d}")
    if not guard_ok:
        print(f"GUARD FAIL: mandatory reading {data['mandatory_bytes']} B exceeds "
              f"the 0.2.2 baseline {BASELINE_0_2_2_MANDATORY_BYTES} B by more "
              f"than {MANDATORY_GROWTH_LIMIT} B", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
