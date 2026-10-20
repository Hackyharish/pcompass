#!/usr/bin/env python3
"""Standalone helper script for the Prompt Compass universal skill."""

from __future__ import annotations

from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
if (REPO_ROOT / "pcompass").is_dir():
    sys.path.insert(0, str(REPO_ROOT))

from pcompass.cli import main

if __name__ == "__main__":
    prompt = " ".join(sys.argv[1:]).strip()
    if not prompt:
        print("Usage: run_route.py <prompt>", file=sys.stderr)
        sys.exit(0)
    sys.exit(main(["brief", prompt]))
