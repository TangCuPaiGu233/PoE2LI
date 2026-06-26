#!/usr/bin/env python3
"""Unified entrypoint for the GGPK data pipeline.

Workflow:
  1. validate   - check EN/TC/SC JSON completeness
  2. import     - load JSON into PostgreSQL via import_game_data.py
  3. relations  - resolve FK relations into game_relations.json

Usage:
    python scripts/run_pipeline.py --data-dir data/poe2_data
    python scripts/run_pipeline.py --data-dir data/poe2_data --step validate
    python scripts/run_pipeline.py --data-dir data/poe2_data --step import
    python scripts/run_pipeline.py --data-dir data/poe2_data --step relations
    python scripts/run_pipeline.py --data-dir data/poe2_data --game-version 0.2.0
    python scripts/run_pipeline.py --data-dir data/poe2_data --skip relations
"""
import argparse
import os
import subprocess
import sys
import time


def run(cmd, cwd=None, check=True):
    """Run a shell command and stream output."""
    print(f"\n>>> {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=cwd, check=check)
    return result.returncode


def main():
    parser = argparse.ArgumentParser(description="PoE2LI data pipeline runner")
    parser.add_argument("--data-dir", required=True, help="Path to poe2_data dir")
    parser.add_argument("--game-version", default="0.2.0", help="Game version tag")
    parser.add_argument("--step", nargs="*", default=None,
                        help="Run only specific steps: validate import relations")
    parser.add_argument("--skip", nargs="*", default=None,
                        help="Skip steps: validate import relations")
    args = parser.parse_args()

    base = os.path.abspath(args.data_dir)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.abspath(os.path.join(script_dir, ".."))

    all_steps = ["validate", "import", "relations"]
    steps = args.step or all_steps
    skip = set(args.skip or [])
    steps = [s for s in steps if s in all_steps and s not in skip]

    if not steps:
        print("No steps to run.")
        sys.exit(0)

    print("PoE2LI Data Pipeline")
    print(f"  data_dir   : {base}")
    print(f"  version    : {args.game_version}")
    print(f"  steps      : {', '.join(steps)}")
    print(f"  repo_root  : {repo_root}")
    print(f"  start_time : {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    failed = []
    started = time.time()

    # Step 1: validate
    if "validate" in steps:
        print("=" * 60)
        print("STEP: validate")
        print("=" * 60)
        cmd = [
            sys.executable, os.path.join(repo_root, "scripts", "import_game_data.py"),
            "--data-dir", base,
            "--validate",
        ]
        try:
            run(cmd, cwd=repo_root)
            print("Validation complete.")
        except subprocess.CalledProcessError as e:
            print(f"Validation failed with exit code {e.returncode}")
            failed.append("validate")

    # Step 2: import
    if "import" in steps:
        print()
        print("=" * 60)
        print("STEP: import")
        print("=" * 60)
        cmd = [
            sys.executable, os.path.join(repo_root, "scripts", "import_game_data.py"),
            "--data-dir", base,
            "--game-version", args.game_version,
        ]
        try:
            run(cmd, cwd=repo_root)
            print("Import complete.")
        except subprocess.CalledProcessError as e:
            print(f"Import failed with exit code {e.returncode}")
            failed.append("import")

    # Step 3: relations
    if "relations" in steps:
        print()
        print("=" * 60)
        print("STEP: relations")
        print("=" * 60)
        en_dir = os.path.join(base, "en")
        output = os.path.join(base, "game_relations.json")
        cmd = [
            sys.executable, os.path.join(repo_root, "scripts", "resolve_relations.py"),
            "--data-dir", en_dir,
            "--output", output,
        ]
        try:
            run(cmd, cwd=repo_root)
            print("Relations resolved.")
        except FileNotFoundError:
            print("resolve_relations.py not available; skipping relations step.")
        except subprocess.CalledProcessError as e:
            print(f"Relations failed with exit code {e.returncode}")
            failed.append("relations")

    # Summary
    elapsed = time.time() - started
    print()
    print("=" * 60)
    print("PIPELINE SUMMARY")
    print("=" * 60)
    print(f"  completed : {', '.join([s for s in steps if s not in failed]) or 'none'}")
    if failed:
        print(f"  failed    : {', '.join(failed)}")
    print(f"  elapsed   : {elapsed:.1f}s")
    print()

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
