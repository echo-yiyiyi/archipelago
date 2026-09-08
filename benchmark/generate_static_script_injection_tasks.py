#!/usr/bin/env python3
"""Generate balanced static script injection tasks using the selected py/pyc/elf vectors."""
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from benchmark.generate_static_prompt_injection_tasks import main

if __name__ == "__main__":
    raise SystemExit(main(script_mode=True))
