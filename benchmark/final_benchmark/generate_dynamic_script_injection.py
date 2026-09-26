#!/usr/bin/env python3
"""Generate dynamic script watcher configs and ELF recovery helpers."""
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from benchmark.final_benchmark.generate_dynamic_prompt_injection_tasks import main as generate_dynamic


def main(argv=None):
    return generate_dynamic(argv, script_mode=True)


if __name__ == '__main__':
    raise SystemExit(main())
