#!/usr/bin/env python3
"""Plot elapsed-time statistics for completed concurrent HF tasks."""

from __future__ import annotations

import argparse
import re
from datetime import datetime
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


FINISHED_RE = re.compile(
    r"^\[(?P<timestamp>[^]]+)\] TASK_FINISHED:.*?"
    r"task=(?P<task>\S+).*?returncode=(?P<returncode>-?\d+).*?"
    r"elapsed_seconds=(?P<elapsed>[0-9.]+)"
)


def read_completed(log_path: Path) -> list[tuple[datetime, str, int, float]]:
    rows: list[tuple[datetime, str, int, float]] = []
    for line in log_path.read_text(errors="replace").splitlines():
        match = FINISHED_RE.search(line)
        if not match:
            continue
        timestamp = datetime.fromisoformat(match.group("timestamp").replace("Z", "+00:00"))
        rows.append(
            (
                timestamp,
                match.group("task"),
                int(match.group("returncode")),
                float(match.group("elapsed")),
            )
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()

    run_dir = args.run_dir.resolve()
    rows = read_completed(run_dir / "runner.log")
    if not rows:
        raise SystemExit("No TASK_FINISHED records found")

    rows.sort(key=lambda row: row[0])
    elapsed_min = np.array([row[3] / 60 for row in rows])
    successful = sum(row[2] == 0 for row in rows)
    median = float(np.median(elapsed_min))
    p90 = float(np.percentile(elapsed_min, 90))
    mean = float(np.mean(elapsed_min))

    plt.rcParams.update({"font.size": 10, "axes.titleweight": "bold"})
    fig, axes = plt.subplots(1, 2, figsize=(14, 6.8))
    fig.patch.set_facecolor("#FAFBFC")
    fig.subplots_adjust(left=0.07, right=0.98, bottom=0.11, top=0.76, wspace=0.24)

    blue = "#2878B5"
    orange = "#E1812C"
    ink = "#243447"
    grid = "#DCE3E8"

    ax = axes[0]
    bins = min(16, max(6, round(np.sqrt(len(rows)) * 1.5)))
    ax.hist(elapsed_min, bins=bins, color=blue, edgecolor="white", linewidth=1)
    ax.axvline(median, color=orange, linewidth=2, label=f"Median: {median:.1f} min")
    ax.axvline(p90, color=ink, linewidth=2, linestyle="--", label=f"P90: {p90:.1f} min")
    ax.set_title("Completed task duration distribution", loc="left")
    ax.set_xlabel("Elapsed time (minutes)")
    ax.set_ylabel("Completed tasks")
    ax.legend(frameon=False)

    ax = axes[1]
    order = np.arange(1, len(rows) + 1)
    ax.scatter(order, elapsed_min, s=26, color=blue, alpha=0.78, edgecolors="none")
    ax.axhline(median, color=orange, linewidth=2, label="Median")
    ax.axhline(p90, color=ink, linewidth=2, linestyle="--", label="P90")
    ax.set_title("Duration by completion order", loc="left")
    ax.set_xlabel("Completion order")
    ax.set_ylabel("Elapsed time (minutes)")
    ax.legend(frameon=False)

    for ax in axes:
        ax.set_facecolor("white")
        ax.grid(axis="y", color=grid, linewidth=0.8)
        ax.set_axisbelow(True)
        ax.spines[["top", "right"]].set_visible(False)
        ax.spines[["left", "bottom"]].set_color("#9AA7B2")

    started = rows[0][0].strftime("%Y-%m-%d %H:%M UTC")
    ended = rows[-1][0].strftime("%H:%M UTC")
    fig.suptitle(
        "Hugging Face concurrent run — completed task timings",
        x=0.07,
        y=0.965,
        ha="left",
        fontsize=16,
        fontweight="bold",
        color=ink,
    )
    fig.text(
        0.07,
        0.885,
        f"Run {run_dir.name}  •  n={len(rows)} ({successful} successful)\n"
        f"Mean {mean:.1f} min  •  Median {median:.1f} min  •  P90 {p90:.1f} min  •  "
        f"Completion window {started}–{ended}",
        ha="left",
        va="top",
        color="#566573",
        fontsize=9.5,
        linespacing=1.5,
    )

    output = run_dir / "completed_task_durations.png"
    fig.savefig(output, dpi=180, bbox_inches="tight", facecolor=fig.get_facecolor())
    print(output)
    print(f"count={len(rows)} success={successful} mean_min={mean:.2f} median_min={median:.2f} p90_min={p90:.2f} max_min={elapsed_min.max():.2f}")


if __name__ == "__main__":
    main()
