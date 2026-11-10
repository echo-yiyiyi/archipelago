#!/usr/bin/env python3
"""Run the three old-set domain groups with the original runner and judges."""
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))
from benchmark.rebuttal.difficulty_ablation.run import main

if __name__ == "__main__":
    main(directory=HERE, axis="domain", levels=("banking", "law", "consulting"), output_name="domain_ablation")
