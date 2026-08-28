# Balanced file-type assignment

## Goal

Assign one file type to every task while keeping the seven file-type counts as
equal as mathematically possible and respecting each task's GPT-5.4 ranking.

With 15 tasks and 7 file types, exact equality is impossible. The balanced
capacity is therefore 2 or 3 tasks per type: six types receive 2 tasks and one
type receives 3 tasks. The optimizer decides which type receives the extra task.

## Constraints

For task `i` and file type `j`, let `x[i,j]` be 1 when the assignment is chosen
and 0 otherwise.

1. Every task receives exactly one type: `sum_j x[i,j] = 1`.
2. Every type receives at least 2 tasks: `sum_i x[i,j] >= 2`.
3. Every type receives at most 3 tasks: `sum_i x[i,j] <= 3`.

## Preference objective

The seven ranking positions use increasing costs:

| Rank | Cost |
|---:|---:|
| 1 | 0 |
| 2 | 1 |
| 3 | 3 |
| 4 | 10 |
| 5 | 30 |
| 6 | 80 |
| 7 | 200 |

The optimization is lexicographic:

1. Minimize the number of tasks assigned outside their top three choices.
2. Among those solutions, minimize the total ranking cost.
3. Resolve exact ties deterministically using the task order and canonical file
   type order.

The first objective protects niche types such as `email`: when tasks rank
`email` in their top three, the optimizer prefers using those candidates to
meet the `email` capacity instead of assigning `email` to tasks that rank it
near the bottom.

## Algorithm

The implementation uses exact dynamic programming, which is equivalent to
solving this small capacitated minimum-cost bipartite matching problem.

A state is the current count tuple for the seven types. For each task, the
algorithm considers assigning each type whose count is still below 3, adds the
corresponding lexicographic cost, and retains only the best assignment for each
resulting count tuple. After the final task, it considers only states where all
counts are between 2 and 3 and selects the minimum-cost state.

There are at most `4^7 = 16,384` count states, so this exact method is small and
fast for the 15-task dataset and requires no third-party optimization package.

## Reproduce

```bash
python3 archipelago/benchmark/sample_inject_vector/assign_balanced_file_types.py
```

The generated JSON preserves all fields from
`extract_key_words/output/selected_15_keywords_extraction.json` and adds:

- `inject_vector`: the assigned file type;
- `harmful_task_id`: `<task_id>_<inject_vector>`.
