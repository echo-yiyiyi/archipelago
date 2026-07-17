#!/usr/bin/env python3
"""Count ReAct rounds (``Starting step N``) for completed concurrent tasks."""

from __future__ import annotations

import argparse
import csv
import json
import re
import statistics

import matplotlib.pyplot as plt
from collections import Counter
from pathlib import Path


FINISHED_RE = re.compile(
    r"TASK_FINISHED:.*?task=(?P<task>\S+).*?worker=(?P<worker>\d+).*?"
    r"returncode=(?P<returncode>-?\d+).*?elapsed_seconds=(?P<elapsed>[0-9.]+).*?"
    r"log_file=(?P<log_file>\S+)"
)
STEP_RE = re.compile(r"Starting step (?P<step>\d+)")


def percentile(values: list[int], fraction: float) -> float:
    """Return a linearly interpolated percentile without third-party packages."""
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def count_rounds(log_file: Path) -> tuple[int, int]:
    """Return (maximum step number, number of step markers)."""
    steps = [
        int(match.group("step"))
        for match in STEP_RE.finditer(log_file.read_text(errors="replace"))
    ]
    return (max(steps, default=0), len(steps))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Summarize agent rounds for completed tasks in a concurrent run."
    )
    parser.add_argument("run_dir", type=Path, help="Concurrent run directory")
    args = parser.parse_args()

    run_dir = args.run_dir.resolve()
    runner_log = run_dir / "runner.log"
    if not runner_log.is_file():
        raise SystemExit(f"Missing runner log: {runner_log}")

    rows: list[dict[str, object]] = []
    for line in runner_log.read_text(errors="replace").splitlines():
        match = FINISHED_RE.search(line)
        if not match:
            continue
        log_file = Path(match.group("log_file"))
        if not log_file.is_absolute():
            log_file = run_dir / log_file
        rounds, marker_count = count_rounds(log_file) if log_file.is_file() else (0, 0)
        rows.append(
            {
                "task": match.group("task"),
                "worker": int(match.group("worker")),
                "returncode": int(match.group("returncode")),
                "elapsed_seconds": float(match.group("elapsed")),
                "rounds": rounds,
                "step_marker_count": marker_count,
                "log_file": str(log_file),
            }
        )

    if not rows:
        raise SystemExit("No completed tasks found")

    round_values = [int(row["rounds"]) for row in rows]
    distribution = Counter(round_values)
    summary = {
        "run_id": run_dir.name,
        "completed_tasks": len(rows),
        "successful_tasks": sum(int(row["returncode"]) == 0 for row in rows),
        "total_rounds": sum(round_values),
        "mean_rounds": statistics.fmean(round_values),
        "median_rounds": statistics.median(round_values),
        "p90_rounds": percentile(round_values, 0.90),
        "min_rounds": min(round_values),
        "max_rounds": max(round_values),
        "round_distribution": {str(key): distribution[key] for key in sorted(distribution)},
    }

    csv_path = run_dir / "completed_task_rounds.csv"
    with csv_path.open("w", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    json_path = run_dir / "completed_round_summary.json"
    json_path.write_text(json.dumps(summary, indent=2) + "\n")

    labels = list(summary["round_distribution"].keys())
    counts = list(summary["round_distribution"].values())
    fig, ax = plt.subplots(figsize=(11, 5.8))
    fig.patch.set_facecolor("#FAFBFC")
    ax.set_facecolor("white")
    ax.bar(labels, counts, color="#2878B5", edgecolor="white", linewidth=0.8)
    ax.set_title("Completed task round distribution", loc="left", fontweight="bold")
    ax.set_xlabel("ReAct rounds")
    ax.set_ylabel("Completed tasks")
    ax.grid(axis="y", color="#DCE3E8", linewidth=0.8)
    ax.set_axisbelow(True)
    ax.spines[["top", "right"]].set_visible(False)
    fig.suptitle(f"{run_dir.name} — agent rounds", x=0.08, y=0.98, ha="left", fontsize=15, fontweight="bold")
    plot_path = run_dir / "completed_round_distribution.png"
    fig.savefig(plot_path, dpi=180, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)

    print(f"Run: {summary['run_id']}")
    print(
        f"Completed: {summary['completed_tasks']} "
        f"(successful: {summary['successful_tasks']})"
    )
    print(f"Total rounds: {summary['total_rounds']}")
    print(
        "Rounds/task: "
        f"mean={summary['mean_rounds']:.2f}, "
        f"median={summary['median_rounds']:.1f}, "
        f"p90={summary['p90_rounds']:.1f}, "
        f"min={summary['min_rounds']}, max={summary['max_rounds']}"
    )
    print("Distribution: " + ", ".join(f"{key} rounds={value}" for key, value in summary["round_distribution"].items()))
    print(f"CSV: {csv_path}")
    print(f"JSON: {json_path}")
    print(f"Plot: {plot_path}")


if __name__ == "__main__":
    main()
