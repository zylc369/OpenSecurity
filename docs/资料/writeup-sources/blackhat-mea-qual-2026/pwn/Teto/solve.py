#!/usr/bin/env python3
"""Run the verified Teto exploit schedule against the configured instance."""

from __future__ import annotations

import contextlib
import io
import json
import re
import runpy
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
FLAG_RE = re.compile(r"BHFlagY\{[^}\r\n]+\}")


def main() -> int:
    instance = json.loads((ROOT / "instance.json").read_text(encoding="utf-8"))
    endpoint = next(item for item in instance["endpoints"] if item["name"] == "main")
    core = ROOT / "output" / "support" / "core.py"
    if not core.is_file():
        print(f"error: missing solver support: {core}", file=sys.stderr)
        return 1

    captured_out = io.StringIO()
    captured_err = io.StringIO()
    original_argv = sys.argv
    original_path = list(sys.path)
    sys.path.insert(0, str(core.parent))
    sys.argv = [
        str(core),
        f"HOST={endpoint['host']}",
        f"PORT={endpoint['port']}",
        "LOG_LEVEL=error",
    ]
    exit_code = 0
    try:
        with contextlib.redirect_stdout(captured_out), contextlib.redirect_stderr(
            captured_err
        ):
            try:
                runpy.run_path(str(core), run_name="__main__")
            except SystemExit as exc:
                exit_code = int(exc.code or 0)
    finally:
        sys.argv = original_argv
        sys.path[:] = original_path

    transcript = captured_out.getvalue() + captured_err.getvalue()
    match = FLAG_RE.search(transcript)
    if exit_code == 0 and match is not None:
        sys.stdout.buffer.write(match.group(0).encode("ascii"))
        return 0
    print(captured_err.getvalue().strip() or "error: exploit failed", file=sys.stderr)
    return exit_code or 1


if __name__ == "__main__":
    raise SystemExit(main())
