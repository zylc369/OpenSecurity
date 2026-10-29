#!/usr/bin/env python3
"""Canonical launcher for the verified Teto exploit."""

from pathlib import Path
import runpy
import sys


SOLUTION = Path(__file__).resolve().parent / "solver"
ENTRYPOINT = SOLUTION / "solve.py"

if not ENTRYPOINT.is_file():
    raise SystemExit(f"missing teammate solution: {ENTRYPOINT}")

sys.path.insert(0, str(SOLUTION))
runpy.run_path(str(ENTRYPOINT), run_name="__main__")
