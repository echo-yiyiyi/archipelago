# Sample inject goals

Expand each task in
`sample_inject_vector/output/selected_30_tasks_with_inject_vectors.json` into
three randomly sampled, distinct inject-goal variants.

The 15 non-executable vectors use fixed goal quotas: goals 1, 3, 5, 7, and 8
occur 6 times each; goals 2, 4, and 6 occur 5 times each.

The 15 `py`, `pyc`, and `elf` vectors also use fixed quotas: goals 1–8 occur 3
times each, goals 9, 11, and 12 occur 5 times each, and goal 10 occurs 6 times.

```bash
python3 archipelago/benchmark/sample_inject_goal/sample_inject_goals.py
```

Assignment to tasks is random rather than systematic and is reproducible with
the default seed of `42`. Use `--seed` to change task-to-goal matching without
changing the fixed global quotas.
For each original `task_id`, the three file-vector goals and three executable-
vector goals are jointly sampled so all six goals are distinct.

Before assigning individual tasks, the sampler constructs exact per-vector goal
quotas consistent with the fixed group totals. Within every vector, goal counts
differ by at most one. The final constrained random assignment must satisfy the
group totals, vector quotas, three-goal variants, and six-goal task-level
uniqueness simultaneously.

See [`SAMPLING_CONSTRAINTS.md`](SAMPLING_CONSTRAINTS.md) for all enforced
constraints and the latest validated vector-level distribution.

The visual report is available at
[`inject_goal_distribution_report.html`](inject_goal_distribution_report.html).
Its validated source artifact is
[`inject_goal_distribution_report.artifact.json`](inject_goal_distribution_report.artifact.json).
